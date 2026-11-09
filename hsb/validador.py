"""
hsb/validador.py — Validación antes de transformar (Fase 3, Paso 5).

Regla de oro del parcial: **transformar sin validar es un error frecuente**.
Un mensaje inválido se rechaza con todos sus motivos y queda registrado en
`mensaje_bus` con estado `rechazado`; nunca se pierde en silencio.

Reglas:
  1. documento: solo dígitos, entre 4 y 15 caracteres.
  2. nombre: no vacío.
  3. sexo: M, F u O (U se admite como «no registrado» solo si la sede no lo
     envía en el CSV legado; en HL7 el campo es obligatorio).
  4. sede: entre 1 y 3 (MSH-4 debe resolver a una sede conocida).
  5. fechas: nacimiento y ingreso deben ser interpretables.
  6. diagnóstico: debe producir un CIE-10 válido.
       * En HL7 v2 el diagnóstico debe venir ya codificado en CIE-10 (DG1-3
         con sistema I10 o un código con formato CIE-10). El texto libre no se
         acepta en HL7: la sede que habla HL7 habla el estándar completo.
       * En el CSV legado sí se acepta texto libre, y se traduce con la tabla
         `ref_terminologia`. Si no hay mapeo, se rechaza.
     Esta asimetría es la que exige el contrato de `ejemplos/LEEME.md`
     (el archivo 03 trae `DIARREA` en HL7 y debe rechazarse, mientras que la
     misma palabra en el CSV de la sede 3 sí se entrega).
  7. ORU^R01: debe traer al menos una observación con valor y mapeo LOINC.
"""

import os
import re
from typing import Any, Dict, List

from fhir import normalizador, terminologia

SEXOS_VALIDOS = ("M", "F", "O")
RE_DOCUMENTO = re.compile(r"^\d{4,15}$")

# Con `false` el bus también traduce texto libre en HL7 (más permisivo, pero
# deja de cumplir el contrato del archivo 03 de ejemplos).
HL7_EXIGE_CIE10 = os.getenv("HSB_HL7_EXIGE_CIE10", "true").lower() == "true"


def validar(registro: Dict[str, Any]) -> List[str]:
    """Devuelve la lista de motivos de rechazo. Vacía = mensaje válido."""
    motivos: List[str] = []
    formato = registro.get("formato", "hl7v2")

    # 1. Documento
    documento = str(registro.get("documento") or "").strip()
    if not documento:
        motivos.append("documento ausente")
    elif not RE_DOCUMENTO.match(documento):
        if not documento.isdigit():
            motivos.append(f"documento no numérico: '{documento}'")
        else:
            motivos.append(f"documento con longitud inválida ({len(documento)} dígitos; se esperan 4 a 15)")

    # 2. Nombre
    if not str(registro.get("nombre_completo") or "").strip():
        motivos.append("nombre vacío")

    # 3. Sexo
    sexo = str(registro.get("sexo") or "").strip().upper()
    if sexo not in SEXOS_VALIDOS:
        if sexo in ("", "U") and formato == "csv":
            pass  # el legado puede no traerlo
        else:
            motivos.append(f"sexo no válido: '{sexo or 'vacío'}' (se espera M, F u O)")

    # 4. Sede
    sede_id = registro.get("sede_id")
    if sede_id not in (1, 2, 3):
        motivos.append(f"sede no reconocida: '{registro.get('sede_codigo') or sede_id}' (se espera SEDE1, SEDE2 o SEDE3)")

    # 5. Fechas
    if registro.get("fecha_nacimiento") and not normalizador._fecha_iso(registro["fecha_nacimiento"]):
        motivos.append(f"fecha de nacimiento no interpretable: '{registro['fecha_nacimiento']}'")
    if registro.get("fecha_ingreso") and not normalizador._instante_iso(registro["fecha_ingreso"]):
        motivos.append(f"fecha de ingreso no interpretable: '{registro['fecha_ingreso']}'")

    # 6. Diagnósticos → CIE-10
    for dx in registro.get("diagnosticos") or []:
        origen = str(dx.get("origen") or "").strip()
        if not origen:
            motivos.append("diagnóstico sin código ni descripción")
            continue
        if formato == "hl7v2" and HL7_EXIGE_CIE10 and not terminologia.es_cie10(origen):
            motivos.append(
                f"diagnóstico '{origen}' sin mapeo a CIE-10 "
                "(en HL7 v2 el DG1-3 debe traer el código CIE-10; el texto libre "
                "solo se acepta en el CSV legado)"
            )
            continue
        if terminologia.a_cie10(origen) is None:
            motivos.append(f"diagnóstico '{origen}' sin mapeo a CIE-10 en ref_terminologia")

    # 7. Observaciones
    tipo = str(registro.get("tipo") or "")
    observaciones = registro.get("observaciones") or []
    if tipo.startswith("ORU") and not observaciones:
        motivos.append("mensaje ORU^R01 sin segmentos OBX: no hay resultado que publicar")
    for obs in observaciones:
        if terminologia.a_loinc(obs.get("prueba", ""), obs.get("codigo", "")) is None:
            motivos.append(f"prueba '{obs.get('prueba') or obs.get('codigo')}' sin mapeo a LOINC")
        if str(obs.get("valor") or "").strip() == "":
            motivos.append(f"observación '{obs.get('prueba')}' sin valor (OBX-5 vacío)")

    # 8. Tipo de mensaje soportado
    if formato == "hl7v2" and not (tipo.startswith("ADT") or tipo.startswith("ORU")):
        motivos.append(f"tipo de mensaje HL7 no soportado: '{tipo}' (se admiten ADT^A01 y ORU^R01)")

    return motivos


def reglas() -> List[Dict[str, str]]:
    """Tabla de reglas de validación para el informe (plantilla v7)."""
    return [
        {"campo": "documento", "regla": "solo dígitos, 4 a 15 caracteres",
         "si_falla": "rechazado: documento no numérico / longitud inválida"},
        {"campo": "nombre", "regla": "no vacío", "si_falla": "rechazado: nombre vacío"},
        {"campo": "sexo", "regla": "M, F u O (U tolerado en CSV legado)",
         "si_falla": "rechazado: sexo no válido"},
        {"campo": "sede (MSH-4 / parámetro)", "regla": "resuelve a sede 1, 2 o 3",
         "si_falla": "rechazado: sede no reconocida"},
        {"campo": "fecha de nacimiento (PID-7)", "regla": "YYYYMMDD o ISO",
         "si_falla": "rechazado: fecha no interpretable"},
        {"campo": "fecha de ingreso (PV1-44)", "regla": "YYYYMMDDHHMM o ISO",
         "si_falla": "rechazado: fecha no interpretable"},
        {"campo": "diagnóstico (DG1-3)", "regla": "CIE-10 válido en HL7; mapeable por ref_terminologia en CSV",
         "si_falla": "rechazado: diagnóstico sin mapeo a CIE-10"},
        {"campo": "prueba (OBX-3)", "regla": "mapeable a LOINC y con valor en OBX-5",
         "si_falla": "rechazado: prueba sin mapeo a LOINC / sin valor"},
        {"campo": "tipo de mensaje (MSH-9)", "regla": "ADT^A01 u ORU^R01",
         "si_falla": "rechazado: tipo no soportado"},
    ]
