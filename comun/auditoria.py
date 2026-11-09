"""
comun/auditoria.py — Auditoría encadenada por hash (RF5, Fase 4 Paso 2).

Cada acción relevante (login, lectura de historia, escritura clínica, entrega
del bus, acceso denegado) genera un evento inmutable con quién, cuándo, qué y
resultado. El evento guarda el hash del anterior:

    hash = SHA-256(hash_anterior + contenido_canónico)

Así la tabla se convierte en una cadena: alterar, borrar o reordenar una fila
rompe la verificación desde ese punto. `verificar_cadena()` devuelve el primer
evento alterado. El contenido canónico es JSON con claves ordenadas, de modo
que el hash es reproducible en cualquier máquina.

Los eventos se exponen también como `AuditEvent` de FHIR R4 para cumplir la
interoperabilidad del estándar (`a_fhir_auditevent`).
"""

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from comun import db

logger = logging.getLogger(__name__)

# Hash raíz de la cadena: el "bloque génesis" de la auditoría.
GENESIS = "0" * 64

# Clave del advisory lock que serializa los apéndices a la cadena.
_LOCK_AUDITORIA = 918273645

RESULTADOS = ("ok", "error", "permitido", "denegado", "rechazado", "duplicado")


def _canonico(
    ts: datetime,
    actor: str,
    rol: str,
    accion: str,
    recurso: str,
    resultado: str,
    detalle: Optional[Dict[str, Any]],
) -> str:
    """Serialización estable del contenido del evento (orden de claves fijo)."""
    return json.dumps(
        {
            "ts": ts.astimezone(timezone.utc).isoformat(),
            "actor": actor or "",
            "rol": rol or "",
            "accion": accion or "",
            "recurso": recurso or "",
            "resultado": resultado or "",
            "detalle": detalle or {},
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


def calcular_hash(hash_anterior: str, contenido: str) -> str:
    return hashlib.sha256((hash_anterior + contenido).encode("utf-8")).hexdigest()


def registrar(
    actor: str,
    rol: str,
    accion: str,
    recurso: str = "",
    resultado: str = "ok",
    detalle: Optional[Dict[str, Any]] = None,
    propagar_error: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    Añade un evento al final de la cadena y devuelve su sello
    (`evento_id`, `hash`). Si el almacén central no responde, se registra el
    problema en el log y se devuelve None: la auditoría no debe tumbar la
    operación clínica, pero el fallo queda visible en /health.
    """
    ts = datetime.now(timezone.utc)
    try:
        with db.cursor_central() as cur:
            # Serializa los apéndices: dos procesos no pueden encadenar sobre
            # el mismo hash anterior.
            cur.execute("SELECT pg_advisory_xact_lock(%s);", (_LOCK_AUDITORIA,))
            cur.execute("SELECT hash FROM evento_auditoria ORDER BY evento_id DESC LIMIT 1;")
            fila = cur.fetchone()
            anterior = fila["hash"] if fila else GENESIS

            contenido = _canonico(ts, actor, rol, accion, recurso, resultado, detalle)
            h = calcular_hash(anterior, contenido)

            cur.execute(
                """
                INSERT INTO evento_auditoria
                    (ts, actor, rol, accion, recurso, resultado, detalle, hash_anterior, hash)
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                RETURNING evento_id, ts, hash;
                """,
                (
                    ts,
                    actor,
                    rol,
                    accion,
                    recurso,
                    resultado,
                    json.dumps(detalle or {}, ensure_ascii=False, default=str),
                    anterior,
                    h,
                ),
            )
            creado = cur.fetchone()
        return {
            "evento_id": creado["evento_id"],
            "hash": creado["hash"],
            "hash_anterior": anterior,
            "ts": creado["ts"].isoformat(),
            "sello": creado["hash"][:16],
        }
    except Exception as exc:  # noqa: BLE001
        logger.error("No se pudo registrar el evento de auditoría (%s): %s", accion, exc)
        if propagar_error:
            raise
        return None


def listar(limite: int = 100, actor: Optional[str] = None, recurso: Optional[str] = None) -> List[Dict[str, Any]]:
    sql = "SELECT * FROM evento_auditoria WHERE 1=1"
    params: List[Any] = []
    if actor:
        sql += " AND actor = %s"
        params.append(actor)
    if recurso:
        sql += " AND recurso = %s"
        params.append(recurso)
    sql += " ORDER BY evento_id DESC LIMIT %s"
    params.append(limite)
    with db.cursor_central() as cur:
        cur.execute(sql, tuple(params))
        return [dict(r) for r in cur.fetchall()]


def verificar_cadena(desde: int = 0) -> Dict[str, Any]:
    """
    Recorre la cadena completa y recalcula cada hash.

    Detecta:
      * contenido alterado (el hash recalculado no coincide con el almacenado),
      * fila borrada o reordenada (`hash_anterior` no coincide con el hash del
        evento previo),
      * cadena que no arranca en el hash génesis.
    """
    with db.cursor_central() as cur:
        cur.execute(
            """
            SELECT evento_id, ts, actor, rol, accion, recurso, resultado,
                   detalle, hash_anterior, hash
              FROM evento_auditoria
             WHERE evento_id > %s
             ORDER BY evento_id ASC;
            """,
            (desde,),
        )
        eventos = [dict(r) for r in cur.fetchall()]

        # Si se verifica un tramo, el eslabón de partida es el hash del evento
        # anterior al tramo, no el génesis.
        anterior = GENESIS
        if desde:
            cur.execute(
                "SELECT hash FROM evento_auditoria WHERE evento_id <= %s ORDER BY evento_id DESC LIMIT 1;",
                (desde,),
            )
            fila = cur.fetchone()
            if fila:
                anterior = fila["hash"]
    for ev in eventos:
        detalle = ev["detalle"] if isinstance(ev["detalle"], dict) else json.loads(ev["detalle"] or "{}")
        contenido = _canonico(
            ev["ts"], ev["actor"], ev["rol"], ev["accion"], ev["recurso"], ev["resultado"], detalle
        )
        esperado = calcular_hash(anterior, contenido)

        if ev["hash_anterior"] != anterior:
            return {
                "integra": False,
                "total_eventos": len(eventos),
                "evento_alterado": ev["evento_id"],
                "motivo": "eslabón roto: hash_anterior no coincide con el evento previo "
                          "(fila borrada, insertada o reordenada)",
                "hash_esperado": anterior,
                "hash_encontrado": ev["hash_anterior"],
                "evento": _resumen(ev),
            }
        if ev["hash"] != esperado:
            return {
                "integra": False,
                "total_eventos": len(eventos),
                "evento_alterado": ev["evento_id"],
                "motivo": "contenido alterado: el hash recalculado no coincide con el almacenado",
                "hash_esperado": esperado,
                "hash_encontrado": ev["hash"],
                "evento": _resumen(ev),
            }
        anterior = ev["hash"]

    return {
        "integra": True,
        "total_eventos": len(eventos),
        "evento_alterado": None,
        "motivo": None,
        "hash_cabeza": anterior,
        "sello": anterior[:16],
    }


def _resumen(ev: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "evento_id": ev["evento_id"],
        "ts": ev["ts"].isoformat() if hasattr(ev["ts"], "isoformat") else str(ev["ts"]),
        "actor": ev["actor"],
        "accion": ev["accion"],
        "recurso": ev["recurso"],
        "resultado": ev["resultado"],
    }


_ACCION_FHIR = {
    "login": ("110114", "User Authentication", "E"),
    "login_denegado": ("110114", "User Authentication", "E"),
    "acceso_denegado": ("110113", "Security Alert", "E"),
    "leer_historia": ("110112", "Query", "R"),
    "generar_reporte": ("110112", "Query", "R"),
}


def a_fhir_auditevent(ev: Dict[str, Any]) -> Dict[str, Any]:
    """Convierte un evento de la cadena en un AuditEvent de FHIR R4."""
    codigo, display, tipo = _ACCION_FHIR.get(ev["accion"], ("rest", "RESTful Operation", "E"))
    exitoso = ev["resultado"] in ("ok", "permitido", "duplicado")
    ts = ev["ts"].isoformat() if hasattr(ev["ts"], "isoformat") else str(ev["ts"])
    return {
        "resourceType": "AuditEvent",
        "id": f"ev-{ev['evento_id']}",
        "type": {
            "system": "http://terminology.hl7.org/CodeSystem/audit-event-type",
            "code": codigo,
            "display": display,
        },
        "subtype": [{"system": "urn:hc-distribuida:accion", "code": ev["accion"]}],
        "action": tipo,
        "recorded": ts,
        "outcome": "0" if exitoso else "4",
        "outcomeDesc": ev["resultado"],
        "agent": [
            {
                "who": {"identifier": {"value": ev["actor"]}},
                "requestor": True,
                "role": [{"text": ev["rol"]}],
            }
        ],
        "source": {"observer": {"display": "Plataforma de interoperabilidad clínica"}},
        "entity": [{"what": {"identifier": {"value": ev["recurso"]}}}],
        "extension": [
            {"url": "urn:hc-distribuida:hash", "valueString": ev["hash"]},
            {"url": "urn:hc-distribuida:hash-anterior", "valueString": ev["hash_anterior"]},
        ],
    }


def sello_contenido(contenido: Any) -> str:
    """SHA-256 del contenido de un reporte (sello de integridad del Reporte de HC)."""
    txt = json.dumps(contenido, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(txt.encode("utf-8")).hexdigest()
