"""
comun/sedes.py — Registro de las tres sedes de la red de IPS y del almacén central.

Decisión de distribución (Fase 2, Paso 2 de la guía):
    Se elige **un nodo PostgreSQL por sede**. Es la opción que coincide con el
    escenario del parcial: cada sede conserva su sistema legado con base propia
    y la plataforma no lo reemplaza. La consulta unificada recorre los 3 nodos.

    Se conserva además la fragmentación horizontal por documento del repositorio
    de referencia (ver `nodo_por_documento`) para el caso en que una escritura
    llega sin sede declarada: el rango del documento decide el nodo. Así el
    sistema sigue siendo compatible con el laboratorio original.

Según CAP se sacrifica consistencia fuerte entre sedes a cambio de
disponibilidad: si una sede cae, la vista unificada responde con las otras dos
y marca la sede como no disponible (AP + consistencia eventual al reintegrar
los mensajes pendientes del bus).
"""

import os
from typing import Any, Dict, List, Optional

# ¿Estamos dentro de la red de Docker (nombres de contenedor) o en el host?
USE_DOCKER_NAMES = os.getenv("USE_DOCKER_NAMES", "false").lower() == "true"

PG_USER = os.getenv("PG_USER", "admin")
PG_PASSWORD = os.getenv("PG_PASSWORD", "admin")
PG_DB_SEDE = os.getenv("PG_DB_SEDE", "historia_clinica")

# ─────────────────────────────────────────────────────────────────────────────
# Las tres sedes de la red
# ─────────────────────────────────────────────────────────────────────────────
_SEDES_BASE = [
    {
        "sede_id": 1,
        "codigo": "SEDE1",
        "nombre": "Sincelejo",
        "nodo": "pg_nodo1",
        "puerto_host": 5433,
        "rango_documento": "< 4.000.000.000",
    },
    {
        "sede_id": 2,
        "codigo": "SEDE2",
        "nombre": "Cartagena",
        "nodo": "pg_nodo2",
        "puerto_host": 5434,
        "rango_documento": "4.000.000.000 – 6.999.999.999",
    },
    {
        "sede_id": 3,
        "codigo": "SEDE3",
        "nombre": "Corozal",
        "nodo": "pg_nodo3",
        "puerto_host": 5435,
        "rango_documento": ">= 7.000.000.000",
    },
]


def _dsn_sede(base: Dict[str, Any]) -> Dict[str, Any]:
    host = base["nodo"] if USE_DOCKER_NAMES else "localhost"
    port = 5432 if USE_DOCKER_NAMES else base["puerto_host"]
    return {
        **base,
        "host": host,
        "port": port,
        "user": PG_USER,
        "password": PG_PASSWORD,
        "dbname": PG_DB_SEDE,
    }


SEDES: List[Dict[str, Any]] = [_dsn_sede(s) for s in _SEDES_BASE]

# ─────────────────────────────────────────────────────────────────────────────
# Almacén central: cola del bus, auditoría y terminologías.
# Vive fuera de las sedes a propósito: si una sede cae, el bus y la auditoría
# siguen funcionando (RNF de degradación parcial).
# ─────────────────────────────────────────────────────────────────────────────
CENTRAL: Dict[str, Any] = {
    "host": os.getenv("PG_CENTRAL_HOST", "pg_central" if USE_DOCKER_NAMES else "localhost"),
    "port": int(os.getenv("PG_CENTRAL_PORT", "5432" if USE_DOCKER_NAMES else "5436")),
    "user": PG_USER,
    "password": PG_PASSWORD,
    "dbname": os.getenv("PG_CENTRAL_DB", "hsb"),
}

# URLs de servicios
HAPI_BASE_URL = os.getenv(
    "HAPI_BASE_URL",
    "http://hapi-fhir:8080/fhir" if USE_DOCKER_NAMES else "http://localhost:8080/fhir",
)
HSB_BASE_URL = os.getenv(
    "HSB_BASE_URL",
    "http://hsb:8000" if USE_DOCKER_NAMES else "http://localhost:8000",
)
API_BASE_URL = os.getenv(
    "API_BASE_URL",
    "http://app:8001" if USE_DOCKER_NAMES else "http://localhost:8001",
)


def sede(sede_id: int) -> Dict[str, Any]:
    """Devuelve la configuración de la sede 1, 2 o 3."""
    for s in SEDES:
        if s["sede_id"] == int(sede_id):
            return s
    raise ValueError(f"sede desconocida: {sede_id}")


def sede_por_codigo(codigo: str) -> Optional[Dict[str, Any]]:
    """Resuelve 'SEDE2', 'sede2', '2', 'HIS_SEDE2' o 'Cartagena' a una sede."""
    if codigo is None:
        return None
    txt = str(codigo).strip().upper()
    for s in SEDES:
        if txt in (s["codigo"], str(s["sede_id"]), s["nombre"].upper(), f"HIS_{s['codigo']}"):
            return s
    # MSH-4 puede venir como 'SEDE2' dentro de una cadena más larga
    for s in SEDES:
        if s["codigo"] in txt:
            return s
    return None


def nodo_por_documento(documento_id: int) -> Dict[str, Any]:
    """
    Fragmentación horizontal por documento (comportamiento del repositorio de
    referencia). Se usa como regla de respaldo cuando la escritura no declara
    sede.
    """
    doc = int(documento_id)
    if doc < 4_000_000_000:
        return sede(1)
    if doc < 7_000_000_000:
        return sede(2)
    return sede(3)
