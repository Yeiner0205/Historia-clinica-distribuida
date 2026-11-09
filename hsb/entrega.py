"""
hsb/entrega.py — Enrutamiento y entrega (Fase 3, Paso 6).

Cada mensaje válido se convierte en un Bundle FHIR, se entrega **primero a
HAPI** y después al nodo de su sede. El orden importa: el Bundle usa `PUT`
sobre identificadores deterministas, así que repetir el envío es seguro y, si
el bus muere entre las dos entregas, al reintentar ninguna de las dos duplica.

La escritura en la sede va en **una sola transacción**: `usuario`, `atencion`,
`diagnostico` y `observacion` se confirman juntos o no se escribe nada (ACID).
Todas las sentencias son `ON CONFLICT ... DO UPDATE`, de modo que la segunda
entrega del mismo mensaje actualiza en lugar de duplicar.
"""

import logging
from typing import Any, Dict, List, Optional

from comun import db, sedes
from fhir import cliente_hapi, normalizador, terminologia

logger = logging.getLogger(__name__)


class ErrorEntrega(Exception):
    def __init__(self, mensaje: str, transitorio: bool = True, detalle: Any = None):
        super().__init__(mensaje)
        self.transitorio = transitorio
        self.detalle = detalle


def visita_efectiva(registro: Dict[str, Any]) -> str:
    """
    Identificador del encuentro en la sede. Si el origen no trae número de
    visita (caso del CSV legado), se usa el id determinista del Encounter:
    así la reentrega actualiza la misma atención y no crea otra.
    """
    return registro.get("visita") or normalizador.id_encuentro(registro)


def entregar_a_hapi(bundle: Dict[str, Any]) -> List[str]:
    """Ejecuta el Bundle transaction en HAPI y devuelve las referencias."""
    try:
        respuesta = cliente_hapi.enviar_bundle(bundle)
    except cliente_hapi.ErrorHapi as exc:
        raise ErrorEntrega(f"HAPI: {exc}", transitorio=exc.transitorio, detalle=exc.cuerpo) from exc
    refs = cliente_hapi.recursos_entregados(respuesta)
    if not refs:
        # HAPI contestó pero no creó nada: lo tratamos como fallo transitorio
        # para que el reintento lo vuelva a intentar en lugar de darlo por bueno.
        raise ErrorEntrega("HAPI no devolvió ninguna referencia creada", transitorio=True,
                           detalle=respuesta)
    return refs


def entregar_a_sede(registro: Dict[str, Any], ids: Dict[str, Optional[str]],
                    mensaje_id: Optional[int] = None) -> Dict[str, Any]:
    """Escribe el registro en el nodo de su sede, en una sola transacción."""
    sede_id = int(registro["sede_id"])
    documento = int(str(registro["documento"]))
    visita = visita_efectiva(registro)
    escrito = {"usuario": 0, "atencion": 0, "diagnosticos": 0, "observaciones": 0}

    try:
        with db.cursor_sede(sede_id) as cur:
            # ─────────────────────────── usuario ───────────────────────────
            cur.execute(
                """
                INSERT INTO usuario (documento_id, tipo_documento, nombre_completo,
                                     fecha_nacimiento, sexo, sede_id, fhir_patient_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (documento_id) DO UPDATE
                   SET nombre_completo  = COALESCE(NULLIF(EXCLUDED.nombre_completo, ''),
                                                   usuario.nombre_completo),
                       fecha_nacimiento = COALESCE(EXCLUDED.fecha_nacimiento, usuario.fecha_nacimiento),
                       sexo             = COALESCE(EXCLUDED.sexo, usuario.sexo),
                       fhir_patient_id  = COALESCE(EXCLUDED.fhir_patient_id, usuario.fhir_patient_id),
                       updated_at       = NOW()
                RETURNING documento_id;
                """,
                (
                    documento,
                    registro.get("tipo_documento") or "CC",
                    registro.get("nombre_completo") or "",
                    normalizador._fecha_iso(registro.get("fecha_nacimiento")),
                    (registro.get("sexo") or "U")[:10],
                    sede_id,
                    ids.get("patient"),
                ),
            )
            escrito["usuario"] = 1

            if registro.get("sin_atencion"):
                # Paciente del legado sin atenciones: solo se vincula su
                # Patient FHIR; no se crea una atención inexistente.
                return {"sede_id": sede_id, "visita": None, **escrito}

            # ─────────────────────────── atención ──────────────────────────
            cur.execute(
                """
                INSERT INTO atencion (documento_id, sede_id, visita, entidad_salud, fecha_ingreso,
                                      entorno_atencion, via_ingreso, causa_atencion,
                                      fecha_triage, clasificacion_triage, profesional_codigo,
                                      mensaje_id, fhir_encounter_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (visita) DO UPDATE
                   SET fecha_ingreso        = COALESCE(EXCLUDED.fecha_ingreso, atencion.fecha_ingreso),
                       clasificacion_triage = COALESCE(EXCLUDED.clasificacion_triage,
                                                       atencion.clasificacion_triage),
                       profesional_codigo   = COALESCE(EXCLUDED.profesional_codigo,
                                                       atencion.profesional_codigo),
                       fhir_encounter_id    = COALESCE(EXCLUDED.fhir_encounter_id,
                                                       atencion.fhir_encounter_id),
                       mensaje_id           = COALESCE(EXCLUDED.mensaje_id, atencion.mensaje_id)
                RETURNING atencion_id;
                """,
                (
                    documento,
                    sede_id,
                    visita,
                    registro.get("entidad_salud") or f"IPS Red Sabana - {registro.get('sede_nombre') or sede_id}",
                    normalizador._instante_iso(registro.get("fecha_ingreso")),
                    registro.get("entorno_atencion") or _entorno(registro.get("clase_encuentro")),
                    registro.get("via_ingreso") or "Propio",
                    registro.get("causa_atencion"),
                    normalizador._instante_iso(registro.get("fecha_triage") or registro.get("fecha_ingreso"))
                    if registro.get("triage") else None,
                    str(registro.get("triage")) if registro.get("triage") not in (None, "") else None,
                    (registro.get("profesional") or {}).get("codigo"),
                    mensaje_id,
                    ids.get("encounter"),
                ),
            )
            atencion_id = cur.fetchone()["atencion_id"]
            escrito["atencion"] = atencion_id

            # ───────────────────────── diagnósticos ────────────────────────
            for dx in registro.get("diagnosticos") or []:
                mapeo = terminologia.a_cie10(dx.get("origen") or "")
                if not mapeo:
                    continue
                cur.execute(
                    """
                    INSERT INTO diagnostico (atencion_id, dx_local, cie10, descripcion_cie10,
                                             tipo_diagnostico_ingreso, diagnostico_ingreso,
                                             fhir_condition_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (atencion_id, cie10) DO UPDATE
                       SET descripcion_cie10 = EXCLUDED.descripcion_cie10,
                           fhir_condition_id = COALESCE(EXCLUDED.fhir_condition_id,
                                                        diagnostico.fhir_condition_id);
                    """,
                    (
                        atencion_id,
                        dx.get("origen"),
                        mapeo["codigo"],
                        mapeo["display"],
                        "Impresion diagnostica",
                        dx.get("descripcion") or mapeo["display"],
                        normalizador.id_condicion(ids.get("encounter") or "", mapeo["codigo"]),
                    ),
                )
                escrito["diagnosticos"] += 1

            # ───────────────────────── observaciones ───────────────────────
            for obs in registro.get("observaciones") or []:
                mapeo = terminologia.a_loinc(obs.get("prueba", ""), obs.get("codigo", ""))
                if not mapeo:
                    continue
                cur.execute(
                    """
                    INSERT INTO observacion (atencion_id, documento_id, loinc, descripcion,
                                             valor, unidad, fecha, fhir_observation_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (atencion_id, loinc) DO UPDATE
                       SET valor               = EXCLUDED.valor,
                           unidad              = EXCLUDED.unidad,
                           fhir_observation_id = COALESCE(EXCLUDED.fhir_observation_id,
                                                          observacion.fhir_observation_id);
                    """,
                    (
                        atencion_id,
                        documento,
                        mapeo["codigo"],
                        obs.get("prueba") or mapeo["display"],
                        str(obs.get("valor")),
                        obs.get("unidad") or mapeo.get("unidad"),
                        normalizador._instante_iso(obs.get("fecha") or registro.get("fecha_ingreso")),
                        normalizador.id_observacion(ids.get("encounter") or "", mapeo["codigo"]),
                    ),
                )
                escrito["observaciones"] += 1

        return {"sede_id": sede_id, "visita": visita, **escrito}

    except Exception as exc:  # noqa: BLE001
        # Si la sede está caída, el mensaje se reintenta: no se pierde.
        raise ErrorEntrega(
            f"sede {sede_id} ({sedes.sede(sede_id)['nombre']}): {str(exc).strip().splitlines()[0]}",
            transitorio=True,
        ) from exc


def _entorno(clase: Optional[str]) -> str:
    return {"E": "Urgencias", "I": "Hospitalizacion", "O": "Consulta externa"}.get(
        (clase or "O").upper(), "Consulta externa"
    )
