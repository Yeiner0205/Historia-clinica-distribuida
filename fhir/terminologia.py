"""
fhir/terminologia.py — Interoperabilidad semántica: diagnóstico local → CIE-10
y prueba de laboratorio → LOINC.

El mapeo vive en la tabla `ref_terminologia` del almacén central (tabla de
referencia, replicada/consultable desde cualquier nodo). Si el central no
responde, se usa la copia de `ejemplos/05_ref_terminologia.csv` para que el
bus pueda seguir validando. Un diagnóstico sin mapeo **no se transforma**: el
mensaje se rechaza con motivo (regla de la Fase 3, Paso 4).
"""

import csv
import os
import threading
from typing import Any, Dict, List, Optional

from fhir import SISTEMA_CIE10, SISTEMA_LOINC

RUTA_CSV = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "ejemplos",
    "05_ref_terminologia.csv",
)

# Pruebas de laboratorio locales → LOINC (usado por el CSV legado y por OBX-3
# cuando la sede envía el nombre de la prueba sin código).
LOINC_LOCAL: Dict[str, Dict[str, str]] = {
    "HEMOGLOBINA": {"codigo": "718-7", "display": "Hemoglobin [Mass/volume] in Blood", "unidad": "g/dL"},
    "GLUCOSA": {"codigo": "2345-7", "display": "Glucose [Mass/volume] in Serum or Plasma", "unidad": "mg/dL"},
    "CREATININA": {"codigo": "2160-0", "display": "Creatinine [Mass/volume] in Serum or Plasma", "unidad": "mg/dL"},
    "LEUCOCITOS": {"codigo": "6690-2", "display": "Leukocytes [#/volume] in Blood", "unidad": "10*3/uL"},
    "PLAQUETAS": {"codigo": "777-3", "display": "Platelets [#/volume] in Blood", "unidad": "10*3/uL"},
    "TENSION ARTERIAL SISTOLICA": {"codigo": "8480-6", "display": "Systolic blood pressure", "unidad": "mm[Hg]"},
    "TEMPERATURA": {"codigo": "8310-5", "display": "Body temperature", "unidad": "Cel"},
}

_cache: Dict[str, Dict[str, str]] = {}
_origen: str = "sin cargar"
_candado = threading.Lock()


def _cargar_desde_csv() -> Dict[str, Dict[str, str]]:
    tabla: Dict[str, Dict[str, str]] = {}
    if not os.path.isfile(RUTA_CSV):
        return tabla
    with open(RUTA_CSV, newline="", encoding="utf-8") as fh:
        for fila in csv.DictReader(fh, delimiter=";"):
            clave = (fila.get("dx_local") or "").strip().upper()
            if clave:
                tabla[clave] = {
                    "cie10": (fila.get("cie10") or "").strip(),
                    "descripcion": (fila.get("descripcion") or "").strip(),
                }
    return tabla


def _cargar_desde_central() -> Dict[str, Dict[str, str]]:
    from comun import db  # import tardío: el CSV debe servir sin base de datos

    filas = db.consultar(
        __import__("comun.sedes", fromlist=["CENTRAL"]).CENTRAL,
        "SELECT dx_local, cie10, descripcion FROM ref_terminologia;",
    )
    return {
        (f["dx_local"] or "").strip().upper(): {
            "cie10": (f["cie10"] or "").strip(),
            "descripcion": (f["descripcion"] or "").strip(),
        }
        for f in filas
    }


def tabla(recargar: bool = False) -> Dict[str, Dict[str, str]]:
    """Mapeo dx_local → {cie10, descripcion}. Se memoriza tras la primera carga."""
    global _cache, _origen
    with _candado:
        if _cache and not recargar:
            return _cache
        try:
            datos = _cargar_desde_central()
            if not datos:
                raise RuntimeError("ref_terminologia vacía")
            _origen = "ref_terminologia (central)"
        except Exception:  # noqa: BLE001
            datos = _cargar_desde_csv()
            _origen = "ejemplos/05_ref_terminologia.csv"
        _cache = datos
        return _cache


def origen() -> str:
    """De dónde se cargó la tabla de referencia (para /health y el informe)."""
    tabla()
    return _origen


def a_cie10(dx_local: str) -> Optional[Dict[str, str]]:
    """Traduce un diagnóstico local a CIE-10. None si no hay mapeo."""
    if not dx_local:
        return None
    clave = str(dx_local).strip().upper()
    datos = tabla()
    if clave in datos:
        return {"codigo": datos[clave]["cie10"], "display": datos[clave]["descripcion"], "sistema": SISTEMA_CIE10}
    # El origen ya puede traer el código CIE-10 directamente (p. ej. DG1-3 = J45.9)
    if es_cie10(clave):
        for info in datos.values():
            if info["cie10"].upper() == clave:
                return {"codigo": info["cie10"], "display": info["descripcion"], "sistema": SISTEMA_CIE10}
        return {"codigo": clave, "display": dx_local, "sistema": SISTEMA_CIE10}
    return None


def es_cie10(codigo: str) -> bool:
    """Formato CIE-10: una letra, dos dígitos y, opcionalmente, punto y un dígito."""
    import re

    return bool(re.fullmatch(r"[A-Z]\d{2}(\.\d{1,2})?", (codigo or "").strip().upper()))


def a_loinc(prueba: str, codigo_origen: str = "") -> Optional[Dict[str, str]]:
    """Traduce el nombre o el código de una prueba a LOINC."""
    codigo_origen = (codigo_origen or "").strip()
    if codigo_origen and any(c.isdigit() for c in codigo_origen) and "-" in codigo_origen:
        for info in LOINC_LOCAL.values():
            if info["codigo"] == codigo_origen:
                return {"codigo": info["codigo"], "display": info["display"], "unidad": info["unidad"],
                        "sistema": SISTEMA_LOINC}
        return {"codigo": codigo_origen, "display": prueba or codigo_origen, "unidad": "", "sistema": SISTEMA_LOINC}
    clave = (prueba or "").strip().upper()
    if clave in LOINC_LOCAL:
        info = LOINC_LOCAL[clave]
        return {"codigo": info["codigo"], "display": info["display"], "unidad": info["unidad"],
                "sistema": SISTEMA_LOINC}
    return None


def concept_map() -> Dict[str, Any]:
    """ConceptMap FHIR del mapeo local → CIE-10 (interoperabilidad semántica)."""
    elementos: List[Dict[str, Any]] = []
    for local, info in sorted(tabla().items()):
        elementos.append(
            {
                "code": local,
                "display": local.title(),
                "target": [
                    {
                        "code": info["cie10"],
                        "display": info["descripcion"],
                        "equivalence": "equivalent",
                    }
                ],
            }
        )
    return {
        "resourceType": "ConceptMap",
        "id": "dx-local-a-cie10",
        "url": "urn:hc-distribuida:ConceptMap/dx-local-a-cie10",
        "version": "1.0.0",
        "name": "DiagnosticoLocalACIE10",
        "title": "Diagnóstico local de las sedes a CIE-10",
        "status": "active",
        "experimental": True,
        "sourceUri": "urn:hc-distribuida:CodeSystem/dx-local",
        "targetUri": SISTEMA_CIE10,
        "group": [
            {
                "source": "urn:hc-distribuida:CodeSystem/dx-local",
                "target": SISTEMA_CIE10,
                "element": elementos,
            }
        ],
    }
