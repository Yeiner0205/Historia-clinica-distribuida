"""
hsb/hl7.py — Lector de mensajes HL7 v2 (ADT^A01 de admisión y ORU^R01 de
resultados) hacia el «registro clínico canónico» que consume el normalizador.

Los segmentos se separan por retorno de carro (también se acepta salto de
línea) y los campos por `|`. En MSH el nombre del segmento ocupa el lugar del
separador, así que MSH-n está en `partes[n-1]`; en los demás segmentos MSH-n
está en `partes[n]`.

Campos usados (tabla de la Fase 3, Paso 3):

    MSH-4   sede que envía            → nodo al que se enruta
    MSH-9   tipo (ADT^A01 / ORU^R01)  → decide el flujo
    MSH-10  id del mensaje            → clave de idempotencia
    PID-3   documento                 → Patient.identifier
    PID-5   nombre (Apellido^Nombre)  → Patient.name
    PID-7   fecha de nacimiento       → Patient.birthDate
    PID-8   sexo                      → Patient.gender
    PV1-2   clase (E, O, I)           → Encounter.class
    PV1-7   médico                    → Practitioner
    PV1-19  número de visita          → Encounter.identifier
    PV1-44  fecha de admisión         → Encounter.period.start
    DG1-3   diagnóstico código^desc   → Condition.code (CIE-10)
    OBX-3/5/6  prueba, valor, unidad  → Observation
"""

from typing import Any, Dict, List, Optional

from comun import sedes


class ErrorHL7(Exception):
    """El texto recibido no es un mensaje HL7 v2 utilizable."""


def _segmentos(texto: str) -> List[List[str]]:
    plano = texto.replace("\r\n", "\r").replace("\n", "\r")
    return [s.split("|") for s in plano.split("\r") if s.strip()]


def _campo(partes: List[str], indice: int) -> str:
    return partes[indice].strip() if 0 <= indice < len(partes) else ""


def _componente(valor: str, n: int = 1) -> str:
    """Componente n de un campo compuesto (`^`)."""
    piezas = (valor or "").split("^")
    return piezas[n - 1].strip() if len(piezas) >= n else ""


def parsear(texto: str) -> Dict[str, Any]:
    """
    Convierte un mensaje HL7 v2 en el registro canónico.

    Devuelve además `clave_idempotencia` (MSH-10), `tipo` (MSH-9) y
    `sede_codigo` (MSH-4). No valida reglas de negocio: eso es trabajo de
    `hsb.validador` (primero validar, después transformar).
    """
    if not texto or not texto.strip():
        raise ErrorHL7("mensaje vacío")

    segmentos = _segmentos(texto)
    por_nombre: Dict[str, List[List[str]]] = {}
    for partes in segmentos:
        por_nombre.setdefault(partes[0].strip().upper(), []).append(partes)

    if "MSH" not in por_nombre:
        raise ErrorHL7("falta el segmento MSH: no parece un mensaje HL7 v2")

    msh = por_nombre["MSH"][0]
    sede_codigo = _campo(msh, 3)          # MSH-4
    tipo = _campo(msh, 8) or "DESCONOCIDO"  # MSH-9
    id_mensaje = _campo(msh, 9)           # MSH-10
    app_origen = _campo(msh, 2)           # MSH-3
    version = _campo(msh, 11)             # MSH-12

    sede = sedes.sede_por_codigo(sede_codigo)

    registro: Dict[str, Any] = {
        "formato": "hl7v2",
        "tipo": tipo,
        "origen": app_origen or sede_codigo,
        "sede_codigo": sede_codigo,
        "sede_id": sede["sede_id"] if sede else None,
        "sede_nombre": sede["nombre"] if sede else None,
        "version_hl7": version,
        "clave_idempotencia": id_mensaje or None,
        "diagnosticos": [],
        "observaciones": [],
    }

    # ───────────────────────────── PID ─────────────────────────────
    if "PID" in por_nombre:
        pid = por_nombre["PID"][0]
        registro["documento"] = _componente(_campo(pid, 3), 1)      # PID-3.1
        registro["tipo_documento"] = "CC"
        nombre = _campo(pid, 5)                                      # PID-5
        registro["apellidos"] = _componente(nombre, 1)
        registro["nombres"] = _componente(nombre, 2)
        registro["nombre_completo"] = " ".join(
            p for p in [registro["nombres"], registro["apellidos"]] if p
        ).strip()
        registro["fecha_nacimiento"] = _campo(pid, 7)                # PID-7
        registro["sexo"] = (_campo(pid, 8) or "").upper()            # PID-8

    # ───────────────────────────── PV1 ─────────────────────────────
    if "PV1" in por_nombre:
        pv1 = por_nombre["PV1"][0]
        registro["clase_encuentro"] = (_campo(pv1, 2) or "O").upper()  # PV1-2
        medico = _campo(pv1, 7)                                        # PV1-7
        if medico:
            registro["profesional"] = {
                "codigo": _componente(medico, 1),
                "apellidos": _componente(medico, 2),
                "nombres": _componente(medico, 3),
                "nombre": " ".join(
                    p for p in [_componente(medico, 3), _componente(medico, 2)] if p
                ).strip() or _componente(medico, 1),
            }
        registro["visita"] = _campo(pv1, 19)        # PV1-19
        registro["fecha_ingreso"] = _campo(pv1, 44) # PV1-44

    # ───────────────────────────── DG1 ─────────────────────────────
    for dg1 in por_nombre.get("DG1", []):
        codigo = _campo(dg1, 3)  # DG1-3
        if not codigo:
            continue
        registro["diagnosticos"].append(
            {
                "origen": _componente(codigo, 1),
                "descripcion": _componente(codigo, 2),
                "sistema_origen": _componente(codigo, 3),  # I10 = CIE-10, L = local
                "fecha": _campo(dg1, 5),                   # DG1-5
                "tipo": _campo(dg1, 6),                    # DG1-6
            }
        )

    # ───────────────────────────── OBX ─────────────────────────────
    for obx in por_nombre.get("OBX", []):
        prueba = _campo(obx, 3)  # OBX-3
        if not prueba:
            continue
        registro["observaciones"].append(
            {
                "codigo": _componente(prueba, 1),
                "prueba": _componente(prueba, 2) or _componente(prueba, 1),
                "sistema_origen": _componente(prueba, 3),  # LN = LOINC
                "valor": _campo(obx, 5),                   # OBX-5
                "unidad": _campo(obx, 6),                  # OBX-6
                "estado": _campo(obx, 11),                 # OBX-11
            }
        )

    registro["segmentos"] = sorted(por_nombre.keys())
    return registro


def es_hl7(texto: str) -> bool:
    return bool(texto) and texto.lstrip().upper().startswith("MSH|")


def resumen(registro: Dict[str, Any]) -> str:
    return (
        f"{registro.get('tipo')} de {registro.get('sede_codigo')} "
        f"doc={registro.get('documento')} visita={registro.get('visita')} "
        f"dx={len(registro.get('diagnosticos') or [])} obs={len(registro.get('observaciones') or [])}"
    )
