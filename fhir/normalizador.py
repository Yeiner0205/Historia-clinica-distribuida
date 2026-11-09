"""
fhir/normalizador.py — Normalizador a FHIR R4 (RF2).

Entrada: un «registro clínico canónico» (dict) que producen los lectores del
HSB a partir de HL7 v2 o del CSV legado, o el lector de filas legadas de una
sede.

Salida: los recursos Patient, Encounter, Condition (CIE-10), Observation
(LOINC) y Practitioner, empaquetados en:

  * `bundle_transaccion()` → Bundle `transaction` con `PUT` e identificadores
    deterministas (`pac-<documento>`, `enc-<visita>`…). Reenviar el mismo
    mensaje sobreescribe el mismo recurso: no duplica. Es el Bundle que el bus
    entrega a HAPI.
  * `bundle_documento()` → Bundle `document` con `Composition` (laboratorio
    «Dentro de FHIR»). Es el Bundle que descarga el paciente y el que acompaña
    al Reporte de HC.

Todas las referencias apuntan a recursos que existen dentro del propio Bundle.
"""

import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from fhir import (
    SISTEMA_ACT_CODE,
    SISTEMA_CIE10,
    SISTEMA_DOCUMENTO,
    SISTEMA_LOINC,
    SISTEMA_SEDE,
    SISTEMA_TRIAGE,
    SISTEMA_V2_0203,
    SISTEMA_VISITA,
)
from fhir import terminologia

SEXO_FHIR = {"M": "male", "F": "female", "O": "other", "U": "unknown"}

CLASE_ENCUENTRO = {
    "E": ("EMER", "emergency"),
    "I": ("IMP", "inpatient encounter"),
    "O": ("AMB", "ambulatory"),
    "U": ("AMB", "ambulatory"),
}

TIPO_DOC_V2 = {"CC": "NI", "TI": "NI", "CE": "NI", "PA": "PPN", "RC": "NI", "MS": "NI", "AS": "NI"}


class ErrorNormalizacion(Exception):
    """El registro no puede convertirse a FHIR. `motivos` explica por qué."""

    def __init__(self, motivos: List[str]):
        self.motivos = motivos
        super().__init__("; ".join(motivos))


# ─────────────────────────────────────────────────────────────────────────────
# Utilidades
# ─────────────────────────────────────────────────────────────────────────────
def _slug(txt: str) -> str:
    """Convierte un texto en una pieza de id FHIR válida ([A-Za-z0-9.-], 1-64)."""
    txt = unicodedata.normalize("NFKD", str(txt or "")).encode("ascii", "ignore").decode()
    txt = re.sub(r"[^A-Za-z0-9.-]+", "-", txt).strip("-")
    return txt[:48] or "sd"


def _fecha_iso(valor: Any) -> Optional[str]:
    """Normaliza fechas HL7 (YYYYMMDD[HHMM[SS]]) e ISO a `YYYY-MM-DD`."""
    if not valor:
        return None
    txt = str(valor).strip()
    if re.fullmatch(r"\d{8}", txt):
        return f"{txt[0:4]}-{txt[4:6]}-{txt[6:8]}"
    if re.fullmatch(r"\d{12,14}", txt):
        return f"{txt[0:4]}-{txt[4:6]}-{txt[6:8]}"
    try:
        return datetime.fromisoformat(txt.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def _instante_iso(valor: Any) -> Optional[str]:
    """Normaliza a `YYYY-MM-DDThh:mm:ss±zz:zz` (dateTime de FHIR)."""
    if not valor:
        return None
    txt = str(valor).strip()
    if re.fullmatch(r"\d{12}", txt):  # YYYYMMDDHHMM
        txt = f"{txt[0:4]}-{txt[4:6]}-{txt[6:8]}T{txt[8:10]}:{txt[10:12]}:00"
    elif re.fullmatch(r"\d{14}", txt):
        txt = f"{txt[0:4]}-{txt[4:6]}-{txt[6:8]}T{txt[8:10]}:{txt[10:12]}:{txt[12:14]}"
    elif re.fullmatch(r"\d{8}", txt):
        txt = f"{txt[0:4]}-{txt[4:6]}-{txt[6:8]}T00:00:00"
    try:
        dt = datetime.fromisoformat(txt.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone(-timedelta(hours=5)))  # hora de Colombia, UTC-5
    return dt.isoformat()


def ahora_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# Identificadores deterministas — la clave de la idempotencia
# ─────────────────────────────────────────────────────────────────────────────
def id_paciente(documento: Any) -> str:
    return f"pac-{_slug(documento)}"


def id_encuentro(registro: Dict[str, Any]) -> str:
    visita = registro.get("visita")
    if visita:
        return f"enc-{_slug(visita)}"
    marca = re.sub(r"[^0-9]", "", str(registro.get("fecha_ingreso") or ""))[:12] or "000000000000"
    return f"enc-s{registro.get('sede_id', 0)}-{_slug(registro.get('documento'))}-{marca}"


def id_condicion(id_enc: str, cie10: str) -> str:
    return f"cond-{id_enc[4:]}-{_slug(cie10).replace('.', '')}"


def id_observacion(id_enc: str, loinc: str) -> str:
    return f"obs-{id_enc[4:]}-{_slug(loinc).replace('-', '')}"


def id_profesional(codigo: Any) -> str:
    return f"prof-{_slug(codigo)}"


# ─────────────────────────────────────────────────────────────────────────────
# Recursos
# ─────────────────────────────────────────────────────────────────────────────
def recurso_patient(registro: Dict[str, Any]) -> Dict[str, Any]:
    documento = str(registro["documento"]).strip()
    tipo_doc = (registro.get("tipo_documento") or "CC").upper()
    nombres = (registro.get("nombres") or "").strip()
    apellidos = (registro.get("apellidos") or "").strip()
    completo = (registro.get("nombre_completo") or f"{nombres} {apellidos}").strip()

    nombre: Dict[str, Any] = {"use": "official", "text": completo}
    if apellidos:
        nombre["family"] = apellidos
    if nombres:
        nombre["given"] = [p for p in nombres.split() if p]

    patient: Dict[str, Any] = {
        "resourceType": "Patient",
        "id": id_paciente(documento),
        "identifier": [
            {
                "use": "official",
                "system": SISTEMA_DOCUMENTO,
                "value": documento,
                "type": {
                    "coding": [
                        {
                            "system": SISTEMA_V2_0203,
                            "code": TIPO_DOC_V2.get(tipo_doc, "NI"),
                            "display": tipo_doc,
                        }
                    ],
                    "text": tipo_doc,
                },
            }
        ],
        "active": True,
        "name": [nombre],
        "gender": SEXO_FHIR.get((registro.get("sexo") or "U").upper(), "unknown"),
    }

    nacimiento = _fecha_iso(registro.get("fecha_nacimiento"))
    if nacimiento:
        patient["birthDate"] = nacimiento

    municipio = registro.get("municipio_residencia")
    if municipio:
        patient["address"] = [{"use": "home", "city": str(municipio), "country": registro.get("pais_residencia") or "CO"}]

    if registro.get("sede_id"):
        patient["managingOrganization"] = {
            "identifier": {"system": SISTEMA_SEDE, "value": f"SEDE{registro['sede_id']}"},
            "display": registro.get("sede_nombre") or f"Sede {registro['sede_id']}",
        }
    return patient


def recurso_encounter(registro: Dict[str, Any], id_pac: str, id_enc: str,
                      id_prof: Optional[str]) -> Dict[str, Any]:
    clase, display = CLASE_ENCUENTRO.get((registro.get("clase_encuentro") or "O").upper(), ("AMB", "ambulatory"))
    inicio = _instante_iso(registro.get("fecha_ingreso")) or ahora_iso()

    encounter: Dict[str, Any] = {
        "resourceType": "Encounter",
        "id": id_enc,
        "identifier": [{"system": SISTEMA_VISITA, "value": str(registro.get("visita") or id_enc)}],
        "status": "finished" if registro.get("fecha_salida") else "in-progress",
        "class": {"system": SISTEMA_ACT_CODE, "code": clase, "display": display},
        "subject": {"reference": f"Patient/{id_pac}"},
        "period": {"start": inicio},
        "serviceProvider": {
            "identifier": {"system": SISTEMA_SEDE, "value": f"SEDE{registro.get('sede_id', 0)}"},
            "display": registro.get("sede_nombre") or f"Sede {registro.get('sede_id', 0)}",
        },
    }
    fin = _instante_iso(registro.get("fecha_salida"))
    if fin:
        encounter["period"]["end"] = fin
    if registro.get("triage") not in (None, ""):
        encounter["priority"] = {
            "coding": [{"system": SISTEMA_TRIAGE, "code": str(registro["triage"])}],
            "text": f"Triage {registro['triage']}",
        }
    if id_prof:
        encounter["participant"] = [
            {
                "individual": {"reference": f"Practitioner/{id_prof}"},
                "type": [
                    {
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/v3-ParticipationType",
                                "code": "ATND",
                                "display": "attender",
                            }
                        ]
                    }
                ],
            }
        ]
    if registro.get("causa_atencion"):
        encounter["reasonCode"] = [{"text": str(registro["causa_atencion"])}]
    return encounter


def recurso_practitioner(profesional: Dict[str, Any]) -> Dict[str, Any]:
    codigo = str(profesional.get("codigo") or "SIN-CODIGO")
    nombre = (profesional.get("nombre") or codigo).strip()
    recurso: Dict[str, Any] = {
        "resourceType": "Practitioner",
        "id": id_profesional(codigo),
        "identifier": [{"system": "urn:hc-distribuida:profesional", "value": codigo}],
        "active": True,
        "name": [{"use": "official", "text": nombre}],
    }
    if profesional.get("apellidos"):
        recurso["name"][0]["family"] = profesional["apellidos"]
    if profesional.get("nombres"):
        recurso["name"][0]["given"] = [profesional["nombres"]]
    return recurso


def recurso_condition(dx: Dict[str, Any], registro: Dict[str, Any], id_pac: str,
                      id_enc: str) -> Tuple[Dict[str, Any], Dict[str, str]]:
    mapeo = terminologia.a_cie10(dx.get("origen") or dx.get("cie10") or "")
    if not mapeo:
        raise ErrorNormalizacion([f"diagnóstico '{dx.get('origen')}' sin mapeo a CIE-10"])
    fecha = _instante_iso(dx.get("fecha") or registro.get("fecha_ingreso")) or ahora_iso()
    condition = {
        "resourceType": "Condition",
        "id": id_condicion(id_enc, mapeo["codigo"]),
        "clinicalStatus": {
            "coding": [
                {"system": "http://terminology.hl7.org/CodeSystem/condition-clinical", "code": "active"}
            ]
        },
        "verificationStatus": {
            "coding": [
                {"system": "http://terminology.hl7.org/CodeSystem/condition-ver-status", "code": "confirmed"}
            ]
        },
        "category": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/condition-category",
                        "code": "encounter-diagnosis",
                        "display": "Encounter Diagnosis",
                    }
                ]
            }
        ],
        "code": {
            "coding": [{"system": SISTEMA_CIE10, "code": mapeo["codigo"], "display": mapeo["display"]}],
            "text": dx.get("descripcion") or mapeo["display"],
        },
        "subject": {"reference": f"Patient/{id_pac}"},
        "encounter": {"reference": f"Encounter/{id_enc}"},
        "recordedDate": fecha,
    }
    return condition, mapeo


def recurso_observation(obs: Dict[str, Any], registro: Dict[str, Any], id_pac: str,
                        id_enc: str) -> Dict[str, Any]:
    mapeo = terminologia.a_loinc(obs.get("prueba", ""), obs.get("codigo", ""))
    if not mapeo:
        raise ErrorNormalizacion([f"prueba '{obs.get('prueba')}' sin mapeo a LOINC"])
    fecha = _instante_iso(obs.get("fecha") or registro.get("fecha_ingreso")) or ahora_iso()
    recurso: Dict[str, Any] = {
        "resourceType": "Observation",
        "id": id_observacion(id_enc, mapeo["codigo"]),
        "status": "final",
        "category": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                        "code": "laboratory",
                        "display": "Laboratory",
                    }
                ]
            }
        ],
        "code": {
            "coding": [{"system": SISTEMA_LOINC, "code": mapeo["codigo"], "display": mapeo["display"]}],
            "text": obs.get("prueba") or mapeo["display"],
        },
        "subject": {"reference": f"Patient/{id_pac}"},
        "encounter": {"reference": f"Encounter/{id_enc}"},
        "effectiveDateTime": fecha,
    }
    valor = obs.get("valor")
    unidad = obs.get("unidad") or mapeo.get("unidad") or ""
    try:
        recurso["valueQuantity"] = {
            "value": float(str(valor).replace(",", ".")),
            "unit": unidad,
            "system": "http://unitsofmeasure.org",
            "code": unidad or "1",
        }
    except (TypeError, ValueError):
        recurso["valueString"] = str(valor) if valor is not None else "sin valor"
    return recurso


# ─────────────────────────────────────────────────────────────────────────────
# Normalización completa
# ─────────────────────────────────────────────────────────────────────────────
def normalizar(registro: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convierte un registro canónico en recursos FHIR.

    Devuelve `{"recursos": [...], "ids": {...}, "cie10": [...], "loinc": [...]}`.
    Lanza `ErrorNormalizacion` con todos los motivos acumulados si falta algo
    obligatorio o si un diagnóstico no tiene mapeo a CIE-10.
    """
    motivos: List[str] = []
    for campo in ("documento", "nombre_completo", "sede_id"):
        if not registro.get(campo) and not (campo == "nombre_completo" and registro.get("apellidos")):
            motivos.append(f"falta el campo obligatorio '{campo}'")
    if motivos:
        raise ErrorNormalizacion(motivos)

    id_pac = id_paciente(registro["documento"])

    profesional = registro.get("profesional") or {}
    id_prof = id_profesional(profesional["codigo"]) if profesional.get("codigo") else None

    recursos: List[Dict[str, Any]] = [recurso_patient(registro)]

    # Un paciente del legado puede no tener ninguna atención registrada. En ese
    # caso se normaliza solo el Patient: no se inventa un encuentro que no
    # existió, y por tanto tampoco hay diagnósticos ni observaciones.
    if registro.get("sin_atencion"):
        if id_prof:
            recursos.append(recurso_practitioner(profesional))
        return {"recursos": recursos, "ids": {"patient": id_pac, "encounter": None,
                                              "practitioner": id_prof},
                "cie10": [], "loinc": []}

    id_enc = id_encuentro(registro)
    if id_prof:
        recursos.append(recurso_practitioner(profesional))
    recursos.append(recurso_encounter(registro, id_pac, id_enc, id_prof))

    cie10: List[str] = []
    for dx in registro.get("diagnosticos") or []:
        try:
            condition, mapeo = recurso_condition(dx, registro, id_pac, id_enc)
        except ErrorNormalizacion as exc:
            motivos.extend(exc.motivos)
            continue
        recursos.append(condition)
        cie10.append(mapeo["codigo"])

    loinc: List[str] = []
    for obs in registro.get("observaciones") or []:
        try:
            observation = recurso_observation(obs, registro, id_pac, id_enc)
        except ErrorNormalizacion as exc:
            motivos.extend(exc.motivos)
            continue
        recursos.append(observation)
        loinc.append(observation["code"]["coding"][0]["code"])

    if motivos:
        raise ErrorNormalizacion(motivos)

    return {
        "recursos": recursos,
        "ids": {"patient": id_pac, "encounter": id_enc, "practitioner": id_prof},
        "cie10": cie10,
        "loinc": loinc,
    }


def bundle_transaccion(registro: Dict[str, Any]) -> Dict[str, Any]:
    """
    Bundle `transaction` con `PUT` por recurso: la entrega es idempotente.
    Es lo que el HSB envía a HAPI.
    """
    normalizado = normalizar(registro)
    entradas = []
    for recurso in normalizado["recursos"]:
        ref = f"{recurso['resourceType']}/{recurso['id']}"
        # Sin `fullUrl`: en un Bundle `transaction` el `request.url` ya
        # identifica el recurso, y el PUT sobre un id determinista es la
        # garantía de que reenviar no duplica.
        entradas.append({"resource": recurso, "request": {"method": "PUT", "url": ref}})
    return {
        "resourceType": "Bundle",
        "id": f"bdl-{normalizado['ids']['encounter'] or normalizado['ids']['patient']}",
        "type": "transaction",
        "timestamp": ahora_iso(),
        "entry": entradas,
    }


def bundle_documento(
    paciente: Dict[str, Any],
    registros: List[Dict[str, Any]],
    titulo: str = "Historia clínica unificada",
) -> Dict[str, Any]:
    """
    Bundle `document` con `Composition`: el Bundle descargable del paciente,
    con una sección por sede. `registros` son registros canónicos (uno por
    atención, ya con su sede).
    """
    recursos: List[Dict[str, Any]] = []
    vistos: set = set()
    secciones: Dict[int, List[str]] = {}

    patient = recurso_patient({**paciente, "sede_id": paciente.get("sede_id", 0)})
    recursos.append(patient)
    vistos.add(f"Patient/{patient['id']}")

    for registro in registros:
        reg = {**registro, "documento": paciente["documento"]}
        try:
            normalizado = normalizar(reg)
        except ErrorNormalizacion:
            continue
        for recurso in normalizado["recursos"]:
            ref = f"{recurso['resourceType']}/{recurso['id']}"
            if ref in vistos:
                continue
            vistos.add(ref)
            if recurso["resourceType"] != "Patient":
                recursos.append(recurso)
                secciones.setdefault(int(reg.get("sede_id") or 0), []).append(ref)

    composition = {
        "resourceType": "Composition",
        "id": f"comp-{patient['id']}",
        "status": "final",
        "type": {
            "coding": [{"system": SISTEMA_LOINC, "code": "34133-9", "display": "Summary of episode note"}],
            "text": titulo,
        },
        "subject": {"reference": f"Patient/{patient['id']}"},
        "date": ahora_iso(),
        "author": [{"display": "Plataforma distribuida de interoperabilidad clínica"}],
        "title": titulo,
        "section": [
            {
                "title": f"Sede {sede_id}",
                "code": {"coding": [{"system": SISTEMA_SEDE, "code": f"SEDE{sede_id}"}]},
                "entry": [{"reference": ref} for ref in refs],
            }
            for sede_id, refs in sorted(secciones.items())
        ],
    }

    entradas = [{"fullUrl": f"urn:uuid:{composition['id']}", "resource": composition}]
    entradas.append({"fullUrl": f"urn:uuid:{patient['id']}", "resource": patient})
    entradas.extend({"fullUrl": f"urn:uuid:{r['id']}", "resource": r} for r in recursos if r["resourceType"] != "Patient")

    return {
        "resourceType": "Bundle",
        "id": f"doc-{patient['id']}",
        "type": "document",
        "timestamp": ahora_iso(),
        "identifier": {"system": "urn:hc-distribuida:bundle", "value": f"doc-{patient['id']}"},
        "entry": entradas,
    }
