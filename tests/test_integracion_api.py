"""
Pruebas de integración de la API: permisos por rol, consulta unificada de las
tres sedes, Reporte de HC, auditoría encadenada y transacción atómica.

Necesitan la plataforma levantada (`docker compose up -d`).
"""

import httpx
import pytest

from tests.conftest import cabecera

pytestmark = pytest.mark.integracion


# ─────────────────────── Seguridad y permisos (RF5) ─────────────────────────
def test_sin_token_la_api_responde_401(api):
    assert httpx.get(f"{api}/api/v1/historia/1001", timeout=20).status_code == 401


def test_con_clave_incorrecta_no_se_entrega_token(api):
    respuesta = httpx.post(f"{api}/auth/login",
                           json={"usuario": "medico1", "password": "incorrecta"}, timeout=20)
    assert respuesta.status_code == 401


def test_cada_rol_recibe_sus_permisos(api, tokens):
    esperado = {
        "paciente": "historia:propia",
        "admisionista": "atencion:abrir",
        "medico": "clinico:escribir",
        "auditor": "auditoria:leer",
    }
    for rol, permiso in esperado.items():
        yo = httpx.get(f"{api}/auth/yo", headers=cabecera(tokens[rol]), timeout=20).json()
        assert yo["rol"] == rol
        assert permiso in yo["permisos"]


@pytest.mark.parametrize(
    "rol,metodo,ruta,esperado",
    [
        # El paciente solo ve lo suyo
        ("paciente", "GET", "/api/v1/paciente/mi-historia", 200),
        ("paciente", "GET", "/api/v1/historia/1001", 403),
        ("paciente", "GET", "/api/v1/reporte/1001", 403),
        ("paciente", "GET", "/api/v1/auditoria", 403),
        # El admisionista no ve contenido clínico ni el tablero
        ("admisionista", "GET", "/api/v1/pacientes/buscar?documento=1001", 200),
        ("admisionista", "POST", "/api/v1/medico/diagnostico", 403),
        ("admisionista", "GET", "/api/v1/plataforma/estado", 403),
        # El médico sí ve historias y el tablero, pero no abre atenciones ni audita
        ("medico", "GET", "/api/v1/historia/1001", 200),
        ("medico", "GET", "/api/v1/plataforma/estado", 200),
        ("medico", "POST", "/api/v1/medico/atencion", 403),
        ("medico", "POST", "/api/v1/plataforma/nodos/2/stop", 403),
        ("medico", "GET", "/api/v1/auditoria", 403),
        # El auditor audita
        ("auditor", "GET", "/api/v1/auditoria?limite=5", 200),
        ("auditor", "GET", "/api/v1/auditoria/verificar", 200),
        ("auditor", "GET", "/api/v1/reporte/1001", 200),
    ],
)
def test_matriz_de_permisos_por_rol(api, tokens, rol, metodo, ruta, esperado):
    respuesta = httpx.request(metodo, f"{api}{ruta}", headers=cabecera(tokens[rol]), timeout=40)
    assert respuesta.status_code == esperado, f"{rol} {metodo} {ruta} → {respuesta.status_code}"


def test_un_paciente_que_cambia_el_documento_en_la_url_queda_registrado(api, tokens):
    """Pregunta de autoevaluación de la Fase 4: ¿en qué capa se detiene y qué
    queda registrado?"""
    antes = httpx.get(f"{api}/api/v1/auditoria?limite=200",
                      headers=cabecera(tokens["auditor"]), timeout=30).json()["eventos"]

    denegado = httpx.get(f"{api}/api/v1/historia/1001",
                         headers=cabecera(tokens["paciente"]), timeout=30)
    assert denegado.status_code == 403

    despues = httpx.get(f"{api}/api/v1/auditoria?limite=200",
                        headers=cabecera(tokens["auditor"]), timeout=30).json()["eventos"]
    nuevos = [e for e in despues if e not in antes]
    assert any(e["accion"] == "acceso_denegado" and e["resultado"] == "denegado" for e in nuevos)


def test_la_matriz_de_permisos_se_publica(api):
    matriz = httpx.get(f"{api}/auth/matriz", timeout=20).json()
    assert set(matriz["roles"]) == {"paciente", "admisionista", "medico", "auditor"}
    fila = next(f for f in matriz["matriz"] if f["permiso"] == "historia:otros")
    assert fila["medico"] is True and fila["paciente"] is False


# ──────────────── Consulta unificada de las 3 sedes (RF4) ───────────────────
def test_una_sola_consulta_devuelve_la_historia_de_las_tres_sedes(api, tokens):
    historia = httpx.get(f"{api}/api/v1/historia/1001",
                         headers=cabecera(tokens["medico"]), timeout=40).json()

    assert historia["encontrado"] is True
    assert sorted(historia["resumen"]["sedes_con_registro"]) == [1, 2, 3]
    assert historia["resumen"]["atenciones"] >= 3
    assert historia["parcial"] is False, "Con las tres sedes arriba el resultado es completo"
    # Las atenciones vienen ordenadas por fecha y cada una dice su sede.
    assert all(a.get("sede_nombre") for a in historia["atenciones"])


def test_el_admisionista_no_ve_diagnosticos(api, tokens):
    historia = httpx.get(f"{api}/api/v1/historia/1001",
                         headers=cabecera(tokens["admisionista"]), timeout=40)
    # El admisionista no tiene 'historia:otros'; si llegara a verla, sería sin clínica.
    if historia.status_code == 200:
        datos = historia.json()
        assert all(not a["diagnosticos"] for a in datos["atenciones"])
    else:
        assert historia.status_code == 403


def test_la_busqueda_detecta_el_paciente_en_varias_sedes(api, tokens):
    datos = httpx.get(f"{api}/api/v1/pacientes/1001/sedes",
                      headers=cabecera(tokens["admisionista"]), timeout=40).json()
    assert len(datos["sedes_con_registro"]) >= 2
    assert datos["duplicado_entre_sedes"] is True
    assert "documento exacto" in datos["regla_de_coincidencia"]


# ─────────────────────── Reporte de HC (cuarta vista) ───────────────────────
def test_el_reporte_agrupa_por_sede_con_cobertura_y_sello(api, tokens):
    reporte = httpx.get(f"{api}/api/v1/reporte/1001",
                        headers=cabecera(tokens["auditor"]), timeout=60).json()

    assert len(reporte["sedes"]) == 3
    assert reporte["completo"] is True
    assert 0 <= reporte["cobertura_campos"]["cobertura_pct"] <= 100
    assert len(reporte["sello_integridad"]) == 64
    assert reporte["bundle_fhir"]["type"] == "document"


def test_el_sello_del_reporte_es_estable_si_no_cambia_la_historia(api, tokens):
    uno = httpx.get(f"{api}/api/v1/reporte/1001", headers=cabecera(tokens["auditor"]), timeout=60).json()
    dos = httpx.get(f"{api}/api/v1/reporte/1001", headers=cabecera(tokens["auditor"]), timeout=60).json()
    assert uno["sello_integridad"] == dos["sello_integridad"]


def test_el_reporte_se_exporta_a_html_imprimible(api, tokens):
    respuesta = httpx.get(f"{api}/api/v1/reporte/1001/html",
                          headers=cabecera(tokens["auditor"]), timeout=60)
    assert respuesta.status_code == 200
    assert "Reporte de historia clínica unificada" in respuesta.text
    assert "Sello de integridad" in respuesta.text


def test_el_bundle_del_paciente_pasa_el_validador_de_hapi(api, tokens):
    validacion = httpx.get(f"{api}/api/v1/reporte/1001/bundle/validar",
                           headers=cabecera(tokens["auditor"]), timeout=120).json()
    assert validacion["valido"] is True, validacion["errores"]


# ──────────────────────── Auditoría encadenada ──────────────────────────────
def test_la_cadena_de_auditoria_se_puede_verificar(api, tokens):
    resultado = httpx.get(f"{api}/api/v1/auditoria/verificar",
                          headers=cabecera(tokens["auditor"]), timeout=60).json()
    assert "integra" in resultado and "total_eventos" in resultado
    if resultado["integra"]:
        assert len(resultado["hash_cabeza"]) == 64
    else:
        # Si una prueba anterior alteró la cadena a propósito, debe decir cuál.
        assert resultado["evento_alterado"] is not None


def test_cada_evento_se_puede_leer_como_auditevent_fhir(api, tokens):
    eventos = httpx.get(f"{api}/api/v1/auditoria?limite=1",
                        headers=cabecera(tokens["auditor"]), timeout=30).json()["eventos"]
    identificador = eventos[0]["evento_id"]
    recurso = httpx.get(f"{api}/api/v1/auditoria/{identificador}/fhir",
                        headers=cabecera(tokens["auditor"]), timeout=30).json()
    assert recurso["resourceType"] == "AuditEvent"


# ──────────────────── Capa de datos: ACID y distribución ────────────────────
def test_una_transaccion_que_falla_no_deja_nada_escrito(api, tokens):
    resultado = httpx.post(f"{api}/api/v1/datos/prueba-acid", params={"sede": 1},
                           headers=cabecera(tokens["medico"]), timeout=60).json()

    assert resultado["error_forzado"], "La prueba debe forzar un error a mitad de la transacción"
    assert resultado["usuarios_despues"] == resultado["usuarios_antes"]
    assert resultado["atenciones_despues"] == 0
    assert resultado["atomica"] is True


def test_el_plan_de_la_consulta_usa_la_clave_de_fragmentacion(api, tokens):
    plan = httpx.get(f"{api}/api/v1/datos/explain", params={"documento": 1001},
                     headers=cabecera(tokens["medico"]), timeout=60).json()

    disponibles = [n for n in plan["nodos"] if n["disponible"]]
    assert disponibles, "Al menos un nodo debe responder"
    for nodo in disponibles:
        texto = " ".join(nodo["plan_paciente"])
        assert "Index Scan" in texto, "La consulta por documento debe usar el índice, no recorrer la tabla"
        assert "documento_id = 1001" in texto


def test_la_cobertura_fhir_se_mide_por_sede(api):
    cobertura = httpx.get(f"{api}/api/v1/datos/cobertura", timeout=30).json()
    assert len(cobertura["por_sede"]) == 3
    for sede in cobertura["por_sede"]:
        if sede["disponible"]:
            assert 0 <= sede["cobertura_pct"] <= 100


# ─────────────────────────── Observabilidad ─────────────────────────────────
def test_la_api_expone_health_y_metrics(api):
    salud = httpx.get(f"{api}/health", timeout=30).json()
    assert salud["servicio"] == "api"
    assert salud["estado"] in ("ok", "degradado", "caido")
    assert salud["dependencias"]["sedes_disponibles"].endswith("/3")

    metricas = httpx.get(f"{api}/metrics", timeout=30).text
    assert "api_peticiones_total" in metricas
    assert "sede_disponible" in metricas
    assert "cobertura_fhir_pct" in metricas


def test_las_cuatro_vistas_responden(api):
    for ruta in ("/login", "/paciente", "/admision", "/medico", "/reporte-hc", "/home"):
        respuesta = httpx.get(f"{api}{ruta}", timeout=30)
        assert respuesta.status_code == 200, ruta
        assert "<!DOCTYPE html>" in respuesta.text[:200]
