"""
Pruebas unitarias del normalizador a FHIR R4 (Fase 2, entregable: «normalizador
con pruebas unitarias, mínimo 5 casos, incluido uno inválido»).

No necesitan la plataforma levantada: el normalizador es una función pura.
"""

import pytest

from fhir import normalizador
from fhir.normalizador import ErrorNormalizacion

REGISTRO_BASE = {
    "sede_id": 2,
    "sede_nombre": "Cartagena",
    "documento": "1007",
    "tipo_documento": "CC",
    "nombres": "Andrea",
    "apellidos": "Rojas",
    "nombre_completo": "Andrea Rojas",
    "fecha_nacimiento": "19900214",
    "sexo": "F",
    "visita": "V-S2-0101",
    "clase_encuentro": "O",
    "fecha_ingreso": "202611071015",
    "profesional": {"codigo": "MED-02", "nombre": "Mateo Ruiz"},
    "diagnosticos": [{"origen": "J45.9", "descripcion": "Asma", "fecha": "20261107"}],
    "observaciones": [],
}


def tipos(bundle):
    return [e["resource"]["resourceType"] for e in bundle["entry"]]


# ── Caso 1: admisión completa → Patient, Practitioner, Encounter, Condition ──
def test_admision_produce_los_cuatro_recursos():
    bundle = normalizador.bundle_transaccion(REGISTRO_BASE)

    assert bundle["type"] == "transaction"
    assert tipos(bundle) == ["Patient", "Practitioner", "Encounter", "Condition"]

    patient = bundle["entry"][0]["resource"]
    assert patient["id"] == "pac-1007"
    assert patient["gender"] == "female"
    assert patient["birthDate"] == "1990-02-14"
    assert patient["identifier"][0]["value"] == "1007"

    condicion = bundle["entry"][3]["resource"]
    coding = condicion["code"]["coding"][0]
    assert coding["system"] == "http://hl7.org/fhir/sid/icd-10"
    assert coding["code"] == "J45.9"
    # La referencia apunta a un recurso que existe dentro del mismo Bundle.
    assert condicion["subject"]["reference"] == "Patient/pac-1007"
    assert condicion["encounter"]["reference"] == "Encounter/enc-V-S2-0101"


# ── Caso 2: resultado de laboratorio → Observation con LOINC y cantidad ─────
def test_observacion_usa_loinc_y_valor_numerico():
    registro = {
        **REGISTRO_BASE,
        "diagnosticos": [],
        "observaciones": [{"codigo": "718-7", "prueba": "Hemoglobina", "valor": "13.8", "unidad": "g/dL"}],
    }
    bundle = normalizador.bundle_transaccion(registro)
    observacion = bundle["entry"][-1]["resource"]

    assert observacion["resourceType"] == "Observation"
    assert observacion["code"]["coding"][0]["system"] == "http://loinc.org"
    assert observacion["code"]["coding"][0]["code"] == "718-7"
    assert observacion["valueQuantity"]["value"] == 13.8
    assert observacion["valueQuantity"]["unit"] == "g/dL"


# ── Caso 3: idempotencia — mismos identificadores y método PUT ──────────────
def test_los_identificadores_son_deterministas():
    primero = normalizador.bundle_transaccion(REGISTRO_BASE)
    segundo = normalizador.bundle_transaccion(REGISTRO_BASE)

    urls_1 = [e["request"]["url"] for e in primero["entry"]]
    urls_2 = [e["request"]["url"] for e in segundo["entry"]]

    assert urls_1 == urls_2, "Reenviar el mismo mensaje debe apuntar a los mismos recursos"
    assert {e["request"]["method"] for e in primero["entry"]} == {"PUT"}
    assert urls_1[0] == "Patient/pac-1007"


# ── Caso 4: diagnóstico local del CSV traducido a CIE-10 ───────────────────
def test_diagnostico_local_se_traduce_a_cie10():
    registro = {
        **REGISTRO_BASE,
        "sede_id": 3,
        "visita": None,
        "formato": "csv",
        "diagnosticos": [{"origen": "DIARREA", "descripcion": "Diarrea"}],
    }
    bundle = normalizador.bundle_transaccion(registro)
    condicion = [e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == "Condition"][0]

    assert condicion["code"]["coding"][0]["code"] == "A09"
    assert "gastroenteritis" in condicion["code"]["coding"][0]["display"].lower()
    # Sin número de visita, el id del encuentro sigue siendo determinista.
    assert condicion["encounter"]["reference"].startswith("Encounter/enc-s3-1007-")


# ── Caso 5 (INVÁLIDO): diagnóstico sin mapeo a CIE-10 ──────────────────────
def test_diagnostico_sin_mapeo_se_rechaza_con_motivo():
    registro = {**REGISTRO_BASE, "diagnosticos": [{"origen": "DOLOR MISTERIOSO"}]}

    with pytest.raises(ErrorNormalizacion) as excepcion:
        normalizador.bundle_transaccion(registro)

    assert any("sin mapeo a CIE-10" in m for m in excepcion.value.motivos)


# ── Caso 6 (INVÁLIDO): faltan campos obligatorios ──────────────────────────
def test_registro_sin_documento_se_rechaza():
    registro = {k: v for k, v in REGISTRO_BASE.items() if k != "documento"}

    with pytest.raises(ErrorNormalizacion) as excepcion:
        normalizador.normalizar(registro)

    assert any("documento" in m for m in excepcion.value.motivos)


# ── Caso 7: Bundle document con Composition para el Reporte de HC ──────────
def test_bundle_documento_agrupa_por_sede_con_composition():
    paciente = {"documento": "1001", "nombre_completo": "Carlos Perez Ruiz",
                "sexo": "M", "fecha_nacimiento": "1980-04-12"}
    registros = [
        {**REGISTRO_BASE, "documento": "1001", "sede_id": 1, "visita": "V-S1-0150"},
        {**REGISTRO_BASE, "documento": "1001", "sede_id": 2, "visita": "V-S2-0090"},
        {**REGISTRO_BASE, "documento": "1001", "sede_id": 3, "visita": "V-S3-0045"},
    ]
    bundle = normalizador.bundle_documento(paciente, registros)

    assert bundle["type"] == "document"
    assert bundle["entry"][0]["resource"]["resourceType"] == "Composition"
    assert len(bundle["entry"][0]["resource"]["section"]) == 3
    # Un Bundle document necesita identificador y fecha (invariantes bdl-9 y bdl-10).
    assert bundle["identifier"]["value"]
    assert bundle["timestamp"]
    # Y todos los fullUrl deben ser URI absolutas.
    assert all(e["fullUrl"].startswith("http") for e in bundle["entry"])


# ── Caso 8: paciente del legado sin atenciones → solo Patient ──────────────
def test_paciente_sin_atenciones_solo_produce_patient():
    registro = {"sede_id": 1, "documento": "1005", "nombre_completo": "Andres Lora",
                "sexo": "M", "sin_atencion": True}
    bundle = normalizador.bundle_transaccion(registro)

    assert tipos(bundle) == ["Patient"]
    assert bundle["entry"][0]["request"]["url"] == "Patient/pac-1005"


# ── Caso 9: normalización de fechas HL7 ────────────────────────────────────
@pytest.mark.parametrize(
    "entrada,esperado",
    [
        ("19900214", "1990-02-14"),
        ("202611071015", "2026-11-07"),
        ("1990-02-14", "1990-02-14"),
        ("", None),
        ("no es una fecha", None),
    ],
)
def test_fechas_hl7_e_iso(entrada, esperado):
    assert normalizador._fecha_iso(entrada) == esperado
