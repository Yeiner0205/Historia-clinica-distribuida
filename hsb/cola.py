"""
hsb/cola.py — Cola persistente del bus: idempotencia, reintentos con retroceso
exponencial y cola de mensajes muertos (Fase 3, pasos 7 y 8).

La cola vive en la tabla `mensaje_bus` del almacén central, no en memoria: el
`UNIQUE` sobre `clave_idempotencia` sigue vigente después de reiniciar el bus
(«idempotencia solo en memoria» es uno de los errores frecuentes que señala la
guía).

Ciclo de vida de un mensaje:

    recibido ──validar──► validado ──normalizar──► transformado ──entregar──► entregado
        │                     │                         │
        └──motivos───────► rechazado                    └──fallo──► reintentando ──(> máx)──► muerto
                                                                         │
                                                                  (espera 1s, 2s, 4s, 8s)
"""

import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import psycopg2

from comun import auditoria, db, sedes
from fhir import normalizador
from hsb import entrega, metricas, validador

logger = logging.getLogger(__name__)

ESPERA_BASE_S = float(os.getenv("HSB_ESPERA_BASE_S", "1"))
MAX_INTENTOS = int(os.getenv("HSB_MAX_INTENTOS", "4"))
INTERVALO_TRABAJADOR_S = float(os.getenv("HSB_INTERVALO_TRABAJADOR_S", "2"))

ESTADOS_PENDIENTES = ["recibido", "validado", "transformado", "reintentando"]
# Tiempo que un mensaje queda «tomado» por un trabajador antes de volver a
# estar disponible, para que dos trabajadores no procesen el mismo mensaje.
RESERVA_S = int(os.getenv("HSB_RESERVA_S", "30"))


class ColaNoDisponible(Exception):
    """El almacén central no responde: el bus no puede aceptar mensajes."""


# ─────────────────────────────────────────────────────────────────────────────
# Recepción
# ─────────────────────────────────────────────────────────────────────────────
def recibir(registro: Dict[str, Any], payload: str, procesar_ahora: bool = True) -> Dict[str, Any]:
    """
    Registra el mensaje en la cola y lo procesa.

    Si la clave de idempotencia ya existe, no se crea nada: se responde
    `duplicado` con el estado del mensaje original.
    """
    clave = registro.get("clave_idempotencia") or f"auto:{normalizador.id_encuentro(registro)}"

    try:
        with db.cursor_central() as cur:
            cur.execute(
                """
                INSERT INTO mensaje_bus (clave_idempotencia, origen, sede_id, formato, tipo,
                                         documento, estado, max_intentos, payload, registro,
                                         proximo_intento)
                VALUES (%s, %s, %s, %s, %s, %s, 'recibido', %s, %s, %s::jsonb, NOW())
                ON CONFLICT (clave_idempotencia) DO NOTHING
                RETURNING mensaje_id;
                """,
                (
                    clave,
                    registro.get("origen"),
                    registro.get("sede_id"),
                    registro.get("formato"),
                    registro.get("tipo"),
                    str(registro.get("documento") or "")[:20],
                    MAX_INTENTOS,
                    payload,
                    json.dumps(registro, ensure_ascii=False, default=str),
                ),
            )
            fila = cur.fetchone()
            if fila is None:
                cur.execute(
                    "UPDATE contador_hsb SET valor = valor + 1 WHERE nombre = 'duplicados_detectados';"
                )
                cur.execute(
                    """
                    SELECT mensaje_id, estado, intentos, documento, sede_id, recursos, motivos
                      FROM mensaje_bus WHERE clave_idempotencia = %s;
                    """,
                    (clave,),
                )
                existente = cur.fetchone()
            else:
                cur.execute(
                    "UPDATE contador_hsb SET valor = valor + 1 WHERE nombre = 'mensajes_recibidos';"
                )
                existente = None
    except psycopg2.Error as exc:
        raise ColaNoDisponible(f"almacén central no disponible: {exc}") from exc

    if existente is not None:
        auditoria.registrar(
            actor=registro.get("origen") or "sede",
            rol="sistema_sede",
            accion="bus_duplicado",
            recurso=f"mensaje:{clave}",
            resultado="duplicado",
            detalle={"mensaje_id": existente["mensaje_id"], "estado": existente["estado"]},
        )
        return {
            "resultado": "duplicado",
            "mensaje_id": existente["mensaje_id"],
            "clave_idempotencia": clave,
            "estado": existente["estado"],
            "documento": existente["documento"],
            "sede_id": existente["sede_id"],
            "recursos": existente["recursos"],
            "motivos": existente["motivos"],
            "detalle": "la clave de idempotencia ya estaba registrada: no se creó nada nuevo",
        }

    mensaje_id = fila["mensaje_id"]
    if procesar_ahora:
        return procesar(mensaje_id)
    return {"resultado": "encolado", "mensaje_id": mensaje_id, "estado": "recibido",
            "clave_idempotencia": clave}


# ─────────────────────────────────────────────────────────────────────────────
# Procesamiento
# ─────────────────────────────────────────────────────────────────────────────
def _actualizar(mensaje_id: int, **campos: Any) -> None:
    if not campos:
        return
    asignaciones, valores = [], []
    for columna, valor in campos.items():
        if columna in ("motivos", "registro", "bundle", "recursos"):
            asignaciones.append(f"{columna} = %s::jsonb")
            valores.append(json.dumps(valor, ensure_ascii=False, default=str))
        else:
            asignaciones.append(f"{columna} = %s")
            valores.append(valor)
    asignaciones.append("actualizado_en = NOW()")
    valores.append(mensaje_id)
    with db.cursor_central() as cur:
        cur.execute(f"UPDATE mensaje_bus SET {', '.join(asignaciones)} WHERE mensaje_id = %s;", valores)


def obtener(mensaje_id: int) -> Optional[Dict[str, Any]]:
    with db.cursor_central() as cur:
        cur.execute("SELECT * FROM mensaje_bus WHERE mensaje_id = %s;", (mensaje_id,))
        fila = cur.fetchone()
        return dict(fila) if fila else None


def procesar(mensaje_id: int) -> Dict[str, Any]:
    """
    Ejecuta la cadena completa para un mensaje. No lanza excepciones: cada
    desenlace queda reflejado en el estado del mensaje.
    """
    mensaje = obtener(mensaje_id)
    if mensaje is None:
        return {"resultado": "no_encontrado", "mensaje_id": mensaje_id}
    if mensaje["estado"] in ("entregado", "rechazado"):
        return _respuesta(mensaje, "sin_cambios")

    registro = mensaje["registro"] or {}
    if isinstance(registro, str):
        registro = json.loads(registro)

    # ── 1. Validar ──────────────────────────────────────────────────────────
    motivos = validador.validar(registro)
    if motivos:
        _actualizar(mensaje_id, estado="rechazado", motivos=motivos,
                    ultimo_error="; ".join(motivos))
        auditoria.registrar(
            actor=registro.get("origen") or "sede",
            rol="sistema_sede",
            accion="bus_rechazo",
            recurso=f"documento:{registro.get('documento')}",
            resultado="rechazado",
            detalle={"mensaje_id": mensaje_id, "motivos": motivos},
        )
        metricas.contar("rechazado")
        logger.warning("Mensaje %s rechazado: %s", mensaje_id, motivos)
        return {
            "resultado": "rechazado",
            "mensaje_id": mensaje_id,
            "estado": "rechazado",
            "motivos": motivos,
            "documento": registro.get("documento"),
            "sede_id": registro.get("sede_id"),
        }

    _actualizar(mensaje_id, estado="validado")

    # ── 2. Transformar a FHIR ───────────────────────────────────────────────
    try:
        bundle = normalizador.bundle_transaccion(registro)
        ids = normalizador.normalizar(registro)["ids"]
    except normalizador.ErrorNormalizacion as exc:
        _actualizar(mensaje_id, estado="rechazado", motivos=exc.motivos, ultimo_error=str(exc))
        auditoria.registrar(
            actor=registro.get("origen") or "sede", rol="sistema_sede", accion="bus_rechazo",
            recurso=f"documento:{registro.get('documento')}", resultado="rechazado",
            detalle={"mensaje_id": mensaje_id, "motivos": exc.motivos},
        )
        metricas.contar("rechazado")
        return {"resultado": "rechazado", "mensaje_id": mensaje_id, "estado": "rechazado",
                "motivos": exc.motivos}

    _actualizar(mensaje_id, estado="transformado", bundle=bundle)

    # ── 3. Entregar: primero HAPI, después el nodo de la sede ───────────────
    try:
        refs = entrega.entregar_a_hapi(bundle)
        resultado_sede = entrega.entregar_a_sede(registro, ids, mensaje_id=mensaje_id)
    except entrega.ErrorEntrega as exc:
        return _fallar(mensaje_id, mensaje, registro, str(exc), exc.transitorio)
    except Exception as exc:  # noqa: BLE001
        return _fallar(mensaje_id, mensaje, registro, str(exc), True)

    recibido = mensaje["recibido_en"]
    latencia = int((datetime.now(timezone.utc) - recibido).total_seconds() * 1000)
    _actualizar(
        mensaje_id,
        estado="entregado",
        recursos=refs,
        entregado_en=datetime.now(timezone.utc),
        latencia_ms=latencia,
        ultimo_error=None,
    )
    sello = auditoria.registrar(
        actor=registro.get("origen") or "sede",
        rol="sistema_sede",
        accion="bus_entrega",
        recurso=f"documento:{registro.get('documento')}",
        resultado="ok",
        detalle={
            "mensaje_id": mensaje_id,
            "sede_id": registro.get("sede_id"),
            "recursos": refs,
            "latencia_ms": latencia,
        },
    )
    metricas.contar("entregado")
    logger.info("Mensaje %s entregado en %s ms: %s", mensaje_id, latencia, refs)
    return {
        "resultado": "entregado",
        "mensaje_id": mensaje_id,
        "estado": "entregado",
        "documento": registro.get("documento"),
        "sede_id": registro.get("sede_id"),
        "recursos": refs,
        "sede": resultado_sede,
        "latencia_ms": latencia,
        "sello_auditoria": (sello or {}).get("hash"),
    }


def _fallar(mensaje_id: int, mensaje: Dict[str, Any], registro: Dict[str, Any],
            error: str, transitorio: bool) -> Dict[str, Any]:
    """Aplica la política de reintentos o manda el mensaje a la cola de muertos."""
    intentos = int(mensaje["intentos"]) + 1
    maximo = int(mensaje["max_intentos"] or MAX_INTENTOS)

    if not transitorio:
        _actualizar(mensaje_id, estado="rechazado", intentos=intentos, ultimo_error=error,
                    motivos=[f"entrega rechazada sin posibilidad de reintento: {error}"])
        metricas.contar("rechazado")
        auditoria.registrar(
            actor=registro.get("origen") or "sede", rol="sistema_sede", accion="bus_rechazo",
            recurso=f"documento:{registro.get('documento')}", resultado="rechazado",
            detalle={"mensaje_id": mensaje_id, "error": error},
        )
        return {"resultado": "rechazado", "mensaje_id": mensaje_id, "estado": "rechazado",
                "motivos": [error]}

    if intentos >= maximo:
        _actualizar(mensaje_id, estado="muerto", intentos=intentos, ultimo_error=error,
                    proximo_intento=None)
        metricas.contar("muerto")
        auditoria.registrar(
            actor=registro.get("origen") or "sede", rol="sistema_sede", accion="bus_muerto",
            recurso=f"documento:{registro.get('documento')}", resultado="error",
            detalle={"mensaje_id": mensaje_id, "intentos": intentos, "error": error},
        )
        logger.error("Mensaje %s a la cola de muertos tras %s intentos: %s", mensaje_id, intentos, error)
        return {
            "resultado": "muerto",
            "mensaje_id": mensaje_id,
            "estado": "muerto",
            "intentos": intentos,
            "error": error,
            "detalle": "superó el máximo de intentos; se puede reencolar con POST /hsb/mensajes/{id}/reencolar",
        }

    espera = ESPERA_BASE_S * (2 ** (intentos - 1))  # 1s, 2s, 4s, 8s…
    _actualizar(
        mensaje_id,
        estado="reintentando",
        intentos=intentos,
        ultimo_error=error,
        proximo_intento=datetime.now(timezone.utc) + timedelta(seconds=espera),
    )
    metricas.contar("reintentando")
    logger.warning("Mensaje %s falló (intento %s/%s): %s — reintento en %ss",
                   mensaje_id, intentos, maximo, error, espera)
    return {
        "resultado": "reintentando",
        "mensaje_id": mensaje_id,
        "estado": "reintentando",
        "intentos": intentos,
        "max_intentos": maximo,
        "proximo_intento_en_s": espera,
        "error": error,
    }


def _respuesta(mensaje: Dict[str, Any], resultado: str) -> Dict[str, Any]:
    return {
        "resultado": resultado,
        "mensaje_id": mensaje["mensaje_id"],
        "estado": mensaje["estado"],
        "documento": mensaje["documento"],
        "sede_id": mensaje["sede_id"],
        "recursos": mensaje["recursos"],
        "motivos": mensaje["motivos"],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Reencolado y consulta
# ─────────────────────────────────────────────────────────────────────────────
def reencolar(mensaje_id: int) -> Dict[str, Any]:
    """Devuelve un mensaje muerto (o rechazado por entrega) a la cola."""
    mensaje = obtener(mensaje_id)
    if mensaje is None:
        return {"resultado": "no_encontrado", "mensaje_id": mensaje_id}
    _actualizar(mensaje_id, estado="reintentando", intentos=0, proximo_intento=datetime.now(timezone.utc),
                ultimo_error=None)
    with db.cursor_central() as cur:
        cur.execute("UPDATE contador_hsb SET valor = valor + 1 WHERE nombre = 'reencolados';")
    return procesar(mensaje_id)


def listar(estado: Optional[str] = None, limite: int = 50, sede_id: Optional[int] = None) -> List[Dict[str, Any]]:
    sql = """
        SELECT mensaje_id, clave_idempotencia, origen, sede_id, formato, tipo, documento,
               estado, intentos, max_intentos, motivos, recursos, ultimo_error,
               recibido_en, actualizado_en, entregado_en, latencia_ms
          FROM mensaje_bus WHERE 1=1
    """
    params: List[Any] = []
    if estado:
        sql += " AND estado = %s"
        params.append(estado)
    if sede_id:
        sql += " AND sede_id = %s"
        params.append(sede_id)
    sql += " ORDER BY mensaje_id DESC LIMIT %s"
    params.append(limite)
    with db.cursor_central() as cur:
        cur.execute(sql, tuple(params))
        return [dict(f) for f in cur.fetchall()]


def pendientes(limite: int = 20) -> List[int]:
    """
    Reclama los mensajes cuya hora de reintento ya llegó.

    La reclamación es atómica: el mismo `UPDATE` que los selecciona les corre
    `proximo_intento`, así que dos trabajadores (o dos réplicas del bus) no
    procesan el mismo mensaje. `SKIP LOCKED` evita que se bloqueen entre sí.
    """
    with db.cursor_central() as cur:
        cur.execute(
            """
            WITH candidatos AS (
                SELECT mensaje_id FROM mensaje_bus
                 WHERE estado = ANY(%s)
                   AND (proximo_intento IS NULL OR proximo_intento <= NOW())
                 ORDER BY proximo_intento NULLS FIRST, mensaje_id
                 LIMIT %s
                 FOR UPDATE SKIP LOCKED
            )
            UPDATE mensaje_bus m
               SET proximo_intento = NOW() + (%s || ' seconds')::interval
              FROM candidatos c
             WHERE m.mensaje_id = c.mensaje_id
            RETURNING m.mensaje_id;
            """,
            (ESTADOS_PENDIENTES, limite, RESERVA_S),
        )
        return [f["mensaje_id"] for f in cur.fetchall()]


# ─────────────────────────────────────────────────────────────────────────────
# Trabajador de fondo
# ─────────────────────────────────────────────────────────────────────────────
_detener = threading.Event()
_hilo: Optional[threading.Thread] = None


def _bucle() -> None:
    logger.info("Trabajador de la cola en marcha (intervalo %ss)", INTERVALO_TRABAJADOR_S)
    while not _detener.is_set():
        try:
            for mensaje_id in pendientes():
                if _detener.is_set():
                    break
                procesar(mensaje_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("El trabajador no pudo consultar la cola: %s", exc)
        _detener.wait(INTERVALO_TRABAJADOR_S)
    logger.info("Trabajador de la cola detenido")


def iniciar_trabajador() -> None:
    global _hilo
    if _hilo and _hilo.is_alive():
        return
    _detener.clear()
    _hilo = threading.Thread(target=_bucle, name="hsb-cola", daemon=True)
    _hilo.start()


def detener_trabajador() -> None:
    _detener.set()
    if _hilo:
        _hilo.join(timeout=5)


def trabajador_activo() -> bool:
    return bool(_hilo and _hilo.is_alive())
