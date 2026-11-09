"""
tests/conftest.py — Configuración común de las pruebas.

Hay dos clases de pruebas:

  * **Unitarias**: no necesitan nada levantado. Cubren el lector HL7 v2, el
    lector de CSV legado, el validador, las terminologías, el normalizador a
    FHIR y el cálculo de la cadena de hash.
  * **De integración** (marca `integracion`): necesitan la plataforma en
    marcha (`docker compose up -d`). Si no responde, se omiten con un aviso
    claro en vez de fallar.

Ejecución:

    pytest tests -v                      # todo lo que se pueda
    pytest tests -v -m "not integracion" # solo unitarias
    docker compose exec app pytest tests -v
"""

import os
import sys

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

# Dentro de la red de Docker los servicios se llaman por su nombre de
# contenedor; desde el host, por localhost.
_EN_DOCKER = os.getenv("USE_DOCKER_NAMES", "false").lower() == "true"
API = os.getenv("API_URL", "http://app:8001" if _EN_DOCKER else "http://localhost:8001")
HSB = os.getenv("HSB_URL", "http://hsb:8000" if _EN_DOCKER else "http://localhost:8000")
EJEMPLOS = os.path.join(RAIZ, "ejemplos")

USUARIOS = {
    "paciente": ("paciente1007", os.getenv("PWD_PACIENTE", "paciente123")),
    "admisionista": ("admision2", os.getenv("PWD_ADMISION", "admision123")),
    "medico": ("medico1", os.getenv("PWD_MEDICO", "medico123")),
    "auditor": ("auditor1", os.getenv("PWD_AUDITOR", "auditor123")),
}


def pytest_configure(config):
    config.addinivalue_line("markers", "integracion: necesita la plataforma levantada")


def _responde(url: str) -> bool:
    import httpx

    try:
        return httpx.get(url, timeout=4).status_code < 500
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture(scope="session")
def api() -> str:
    if not _responde(f"{API}/health"):
        pytest.skip(f"La API no responde en {API}. Levante la plataforma: docker compose up -d")
    return API


@pytest.fixture(scope="session")
def hsb() -> str:
    if not _responde(f"{HSB}/health"):
        pytest.skip(f"El bus no responde en {HSB}. Levante la plataforma: docker compose up -d")
    return HSB


@pytest.fixture(scope="session")
def tokens(api: str) -> dict:
    """Un token por rol, para las pruebas de permisos."""
    import httpx

    salida = {}
    for rol, (usuario, clave) in USUARIOS.items():
        respuesta = httpx.post(f"{api}/auth/login", json={"usuario": usuario, "password": clave}, timeout=10)
        assert respuesta.status_code == 200, f"No se pudo iniciar sesión como {usuario}"
        salida[rol] = respuesta.json()["access_token"]
    return salida


def cabecera(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def leer_ejemplo(nombre: str) -> str:
    with open(os.path.join(EJEMPLOS, nombre), newline="", encoding="utf-8") as fh:
        return fh.read()
