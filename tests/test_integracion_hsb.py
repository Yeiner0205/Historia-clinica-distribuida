"""
Pruebas de integración del bus (Fase 3, entregable: «código del HSB con
pruebas de integración»). Necesitan la plataforma levantada.

Cubren el contrato de `ejemplos/LEEME.md` de extremo a extremo: un mensaje
entra por la puerta de la sede, se valida, se transforma y aparece como
recursos FHIR en HAPI y como filas en la base de la sede, sin duplicarse.
"""

import os
import uuid

import httpx
import pytest

from tests.conftest import cabecera, leer_ejemplo

pytestmark = pytest.mark.integracion

# Dentro de la red de Docker el servidor FHIR se llama `hapi-fhir`; desde el
# host, `localhost`. Se puede fijar con la variable HAPI_URL.
HAPI = os.getenv(
    "HAPI_URL",
    "http://hapi-fhir:8080/fhir" if os.getenv("USE_DOCKER_NAMES", "").lower() == "true"
    else "http://localhost:8080/fhir",
)


def enviar_hl7(hsb: str, texto: str) -> dict:
    respuesta = httpx.post(f"{hsb}/hsb/hl7", content=texto.encode("utf-8"), timeout=90)
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


def mensaje_unico(documento: str, sede: str, visita: str, cie10: str = "R51") -> str:
    """Mensaje ADT^A01 con clave de idempotencia nueva en cada ejecución."""
    identificador = f"MSG-TEST-{uuid.uuid4().hex[:10]}"
    return (
        f"MSH|^~\\&|HIS_{sede}|{sede}|HSB|CENTRAL|20261108120000||ADT^A01|{identificador}|P|2.5\r"
        f"PID|1||{documento}^^^HIS||Prueba^Sintetica||19900101|F\r"
        f"PV1|1|O|||||MED-01^Vega^Laura||||||||||||{visita}"
        f"|||||||||||||||||||||||||202611081200\r"
        f"DG1|1||{cie10}^Cefalea^I10||20261108|A\r"
    )


# ── El contrato de los archivos de ejemplo ─────────────────────────────────
def test_adt_valido_llega_a_hapi_y_a_la_sede_2(hsb):
    resultado = enviar_hl7(hsb, leer_ejemplo("01_adt_a01_valido_sede2.hl7"))

    assert resultado["resultado"] in ("entregado", "duplicado")
    if resultado["resultado"] == "entregado":
        assert resultado["sede_id"] == 2
        assert "Patient/pac-1007" in resultado["recursos"]
        assert "Encounter/enc-V-S2-0101" in resultado["recursos"]
        assert "Condition/cond-V-S2-0101-J459" in resultado["recursos"]

    # Y el recurso existe de verdad en HAPI.
    patient = httpx.get(f"{HAPI}/Patient/pac-1007", timeout=30)
    assert patient.status_code == 200
    assert patient.json()["identifier"][0]["value"] == "1007"


def test_oru_publica_la_observacion_loinc_en_hapi(hsb):
    enviar_hl7(hsb, leer_ejemplo("02_oru_r01_laboratorio_sede1.hl7"))

    observacion = httpx.get(f"{HAPI}/Observation/obs-V-S1-0150-7187", timeout=30)
    assert observacion.status_code == 200
    cuerpo = observacion.json()
    assert cuerpo["code"]["coding"][0]["code"] == "718-7"
    assert cuerpo["valueQuantity"]["value"] == 13.8
    assert cuerpo["subject"]["reference"] == "Patient/pac-1001"


def test_mensaje_invalido_se_rechaza_con_tres_motivos_y_queda_registrado(hsb):
    resultado = enviar_hl7(hsb, leer_ejemplo("03_adt_a01_invalido.hl7"))

    assert resultado["resultado"] in ("rechazado", "duplicado")
    motivos = resultado.get("motivos") or []
    if resultado["resultado"] == "rechazado":
        assert len(motivos) == 3, motivos

    # No se pierde en silencio: está en la cola con su motivo.
    cola = httpx.get(f"{hsb}/hsb/mensajes", params={"estado": "rechazado", "limite": 50}, timeout=30).json()
    assert any(m["clave_idempotencia"] == "MSG-0003" for m in cola["mensajes"])


def test_csv_legado_entrega_tres_y_rechaza_dos(hsb):
    """
    Contrato de LEEME.md: 1008, 1009 y 1010 entregados; 1011 (diagnóstico sin
    mapeo) y 12 (documento de 2 dígitos) rechazados.

    Se mira el **estado** de cada fila, no el resultado de la llamada: si el
    archivo ya se subió antes, el bus responde `duplicado` y devuelve el
    estado del mensaje original. Esa es justamente la idempotencia.
    """
    respuesta = httpx.post(
        f"{hsb}/hsb/csv", params={"sede": 3},
        content=leer_ejemplo("04_sede3_legado.csv").encode("utf-8"), timeout=180,
    )
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["filas"] == 5

    estados = {}
    for fila in cuerpo["resultados"]:
        detalle = httpx.get(f"{hsb}/hsb/mensajes/{fila['mensaje_id']}", timeout=30).json()
        estados[detalle["documento"]] = detalle["estado"]

    assert estados["1008"] == "entregado"
    assert estados["1009"] == "entregado"
    assert estados["1010"] == "entregado"
    assert estados["1011"] == "rechazado"
    assert estados["12"] == "rechazado"


# ── Idempotencia ───────────────────────────────────────────────────────────
def test_reenviar_el_mismo_mensaje_no_crea_otro_paciente(hsb):
    texto = mensaje_unico("1099", "SEDE2", f"V-TEST-{uuid.uuid4().hex[:6]}")

    primero = enviar_hl7(hsb, texto)
    segundo = enviar_hl7(hsb, texto)

    assert primero["resultado"] == "entregado"
    assert segundo["resultado"] == "duplicado"
    assert segundo["mensaje_id"] == primero["mensaje_id"]

    # Un solo Patient en HAPI.
    busqueda = httpx.get(f"{HAPI}/Patient", params={"identifier": "1099"}, timeout=30).json()
    assert busqueda.get("total", 0) == 1


def test_dos_mensajes_distintos_del_mismo_paciente_no_duplican_el_encuentro(hsb):
    visita = f"V-TEST-{uuid.uuid4().hex[:6]}"
    enviar_hl7(hsb, mensaje_unico("1098", "SEDE1", visita, "R51"))
    enviar_hl7(hsb, mensaje_unico("1098", "SEDE1", visita, "I10"))

    encuentros = httpx.get(f"{HAPI}/Encounter", params={"identifier": visita}, timeout=30).json()
    assert encuentros.get("total", 0) == 1, "La misma visita no debe crear dos encuentros"


# ── Validación en seco contra el validador de HAPI ─────────────────────────
def test_el_bundle_generado_pasa_el_validador_de_hapi(hsb):
    respuesta = httpx.post(
        f"{hsb}/hsb/validar", params={"formato": "hl7v2", "contra_hapi": "true"},
        content=leer_ejemplo("01_adt_a01_valido_sede2.hl7").encode("utf-8"), timeout=120,
    )
    resultado = respuesta.json()["resultados"][0]

    assert resultado["valido"] is True
    validacion = resultado["validacion_hapi"]
    assert validacion["valido"] is True, validacion["errores"]


# ── Observabilidad ─────────────────────────────────────────────────────────
def test_el_bus_expone_health_y_metrics(hsb):
    salud = httpx.get(f"{hsb}/health", timeout=20).json()
    assert salud["servicio"] == "hsb"
    assert salud["estado"] in ("ok", "degradado")
    assert "sedes" in salud["dependencias"]

    metricas = httpx.get(f"{hsb}/metrics", timeout=20).text
    assert "hsb_mensajes_total" in metricas
    assert "hsb_latencia_media_ms" in metricas
    assert "hsb_duplicados_detectados" in metricas

    json_metricas = httpx.get(f"{hsb}/metrics.json", timeout=20).json()
    assert json_metricas["total_mensajes"] > 0
    assert json_metricas["porcentaje_fallidos"] >= 0


def test_la_terminologia_se_publica_como_conceptmap(hsb):
    datos = httpx.get(f"{hsb}/hsb/terminologia", timeout=20).json()
    assert len(datos["cie10"]) >= 8
    assert datos["concept_map"]["resourceType"] == "ConceptMap"


def test_reencolar_exige_permiso(hsb, tokens):
    # Sin token: 401
    assert httpx.post(f"{hsb}/hsb/mensajes/1/reencolar", timeout=20).status_code == 401
    # Con un rol que no puede operar el bus: 403
    respuesta = httpx.post(f"{hsb}/hsb/mensajes/1/reencolar",
                           headers=cabecera(tokens["paciente"]), timeout=20)
    assert respuesta.status_code == 403
