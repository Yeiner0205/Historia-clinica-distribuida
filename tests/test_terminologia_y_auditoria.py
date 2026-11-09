"""
Pruebas unitarias de las terminologías (CIE-10 y LOINC) y del cálculo de la
cadena de hash de la auditoría. No necesitan la plataforma levantada.
"""

import pytest

from comun import auditoria
from fhir import terminologia


# ─────────────────────────── Terminologías ──────────────────────────────────
@pytest.mark.parametrize(
    "local,cie10",
    [
        ("DIARREA", "A09"),
        ("HIPERTENSION", "I10"),
        ("DIABETES", "E11.9"),
        ("ASMA", "J45.9"),
        ("INFECCION URINARIA", "N39.0"),
        ("LUMBAGO", "M54.5"),
        ("NEUMONIA", "J18.9"),
        ("CEFALEA", "R51"),
    ],
)
def test_la_tabla_de_referencia_mapea_los_ocho_diagnosticos(local, cie10):
    assert terminologia.a_cie10(local)["codigo"] == cie10


def test_un_codigo_cie10_se_acepta_tal_cual():
    assert terminologia.a_cie10("J45.9")["codigo"] == "J45.9"


def test_un_diagnostico_sin_mapeo_devuelve_none():
    assert terminologia.a_cie10("DOLOR MISTERIOSO") is None


@pytest.mark.parametrize("codigo,valido", [("A09", True), ("E11.9", True), ("R51", True),
                                           ("DIARREA", False), ("123", False), ("", False)])
def test_formato_cie10(codigo, valido):
    assert terminologia.es_cie10(codigo) is valido


def test_loinc_por_nombre_y_por_codigo():
    assert terminologia.a_loinc("Hemoglobina", "")["codigo"] == "718-7"
    assert terminologia.a_loinc("", "718-7")["codigo"] == "718-7"
    assert terminologia.a_loinc("Prueba inventada", "") is None


def test_el_concept_map_es_un_recurso_fhir():
    mapa = terminologia.concept_map()
    assert mapa["resourceType"] == "ConceptMap"
    assert mapa["targetUri"] == "http://hl7.org/fhir/sid/icd-10"
    assert len(mapa["group"][0]["element"]) >= 8


# ───────────────────────── Cadena de auditoría ──────────────────────────────
def test_el_hash_encadena_el_anterior_con_el_contenido():
    primero = auditoria.calcular_hash(auditoria.GENESIS, "contenido A")
    segundo = auditoria.calcular_hash(primero, "contenido B")

    assert len(primero) == 64 and len(segundo) == 64
    assert primero != segundo
    # Reproducible: el mismo cálculo da el mismo hash en cualquier máquina.
    assert auditoria.calcular_hash(auditoria.GENESIS, "contenido A") == primero


def test_cambiar_un_caracter_cambia_el_hash():
    a = auditoria.calcular_hash(auditoria.GENESIS, "resultado:denegado")
    b = auditoria.calcular_hash(auditoria.GENESIS, "resultado:permitido")
    assert a != b


def test_el_sello_del_reporte_depende_solo_del_contenido():
    contenido = {"documento": 1001, "atenciones": [{"visita": "V-S1-0150", "cie10": "I10"}]}
    otro_orden = {"atenciones": [{"cie10": "I10", "visita": "V-S1-0150"}], "documento": 1001}

    assert auditoria.sello_contenido(contenido) == auditoria.sello_contenido(otro_orden), \
        "El sello no debe depender del orden de las claves"

    alterado = {"documento": 1001, "atenciones": [{"visita": "V-S1-0150", "cie10": "E11.9"}]}
    assert auditoria.sello_contenido(contenido) != auditoria.sello_contenido(alterado)


def test_el_evento_se_puede_expresar_como_auditevent_fhir():
    from datetime import datetime, timezone

    evento = {
        "evento_id": 7, "ts": datetime(2026, 11, 7, 10, 0, tzinfo=timezone.utc),
        "actor": "medico1", "rol": "medico", "accion": "leer_historia",
        "recurso": "paciente:1001", "resultado": "ok",
        "hash": "a" * 64, "hash_anterior": "b" * 64,
    }
    recurso = auditoria.a_fhir_auditevent(evento)

    assert recurso["resourceType"] == "AuditEvent"
    assert recurso["outcome"] == "0"
    assert recurso["agent"][0]["who"]["identifier"]["value"] == "medico1"
    assert any(e["url"].endswith("hash") for e in recurso["extension"])


def test_un_acceso_denegado_se_marca_como_fallido_en_fhir():
    from datetime import datetime, timezone

    evento = {
        "evento_id": 8, "ts": datetime(2026, 11, 7, 10, 0, tzinfo=timezone.utc),
        "actor": "paciente1007", "rol": "paciente", "accion": "acceso_denegado",
        "recurso": "paciente:1001", "resultado": "denegado",
        "hash": "c" * 64, "hash_anterior": "d" * 64,
    }
    assert auditoria.a_fhir_auditevent(evento)["outcome"] == "4"
