"""
comun/db.py — Acceso a PostgreSQL con tolerancia a fallos parciales.

Toda conexión lleva `connect_timeout`: si una sede está caída, la llamada falla
rápido y el llamador puede degradar la respuesta en lugar de quedarse colgado.
"""

import time
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Tuple

import psycopg2
from psycopg2.extras import RealDictCursor

from comun import sedes

CONNECT_TIMEOUT = 3


def conectar(cfg: Dict[str, Any], timeout: int = CONNECT_TIMEOUT):
    """Abre una conexión a partir de una configuración de sede o del central."""
    return psycopg2.connect(
        host=cfg["host"],
        port=cfg["port"],
        user=cfg["user"],
        password=cfg["password"],
        dbname=cfg["dbname"],
        connect_timeout=timeout,
    )


def conectar_sede(sede_id: int, timeout: int = CONNECT_TIMEOUT):
    return conectar(sedes.sede(sede_id), timeout)


def conectar_central(timeout: int = CONNECT_TIMEOUT):
    return conectar(sedes.CENTRAL, timeout)


@contextmanager
def cursor_central(dict_rows: bool = True):
    """Transacción contra el almacén central (commit al salir, rollback si falla)."""
    conn = conectar_central()
    try:
        factory = RealDictCursor if dict_rows else None
        with conn.cursor(cursor_factory=factory) as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def cursor_sede(sede_id: int, dict_rows: bool = True):
    """
    Transacción contra una sede. Es el punto donde se demuestra ACID: todo lo
    que se escriba dentro del `with` se confirma junto o se revierte junto.
    """
    conn = conectar_sede(sede_id)
    try:
        factory = RealDictCursor if dict_rows else None
        with conn.cursor(cursor_factory=factory) as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def consultar(cfg: Dict[str, Any], sql: str, params: Tuple = ()) -> List[Dict[str, Any]]:
    conn = conectar(cfg)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def ping(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Comprueba una base y mide la latencia. No lanza excepción."""
    inicio = time.perf_counter()
    try:
        conn = conectar(cfg, timeout=2)
        with conn.cursor() as cur:
            cur.execute("SELECT 1;")
            cur.fetchone()
        conn.close()
        return {"disponible": True, "latencia_ms": round((time.perf_counter() - inicio) * 1000, 2)}
    except Exception as exc:  # noqa: BLE001  — el detalle se reporta, no se propaga
        return {
            "disponible": False,
            "latencia_ms": round((time.perf_counter() - inicio) * 1000, 2),
            "error": str(exc).strip().splitlines()[0] if str(exc).strip() else "sin detalle",
        }


def estado_sedes() -> List[Dict[str, Any]]:
    """Estado de las tres sedes para el tablero y para la degradación de la vista."""
    estado = []
    for s in sedes.SEDES:
        p = ping(s)
        estado.append(
            {
                "sede_id": s["sede_id"],
                "codigo": s["codigo"],
                "nombre": s["nombre"],
                "nodo": s["nodo"],
                "puerto": s["puerto_host"],
                "estado": "UP" if p["disponible"] else "DOWN",
                "disponible": p["disponible"],
                "latencia_ms": p["latencia_ms"],
                "error": p.get("error"),
            }
        )
    return estado


def cobertura_fhir_por_sede() -> List[Dict[str, Any]]:
    """
    Cobertura de migración a FHIR por sede: porcentaje de pacientes del sistema
    legado que ya tienen `fhir_patient_id`. Arranca en 0 % y llega a 100 %
    cuando el bus normalizó todas las filas.
    """
    salida = []
    for s in sedes.SEDES:
        fila = {
            "sede_id": s["sede_id"],
            "nombre": s["nombre"],
            "total": 0,
            "migrados": 0,
            "cobertura_pct": None,
            "disponible": False,
        }
        try:
            filas = consultar(
                s,
                """
                SELECT COUNT(*)::int AS total,
                       COUNT(fhir_patient_id)::int AS migrados
                  FROM usuario;
                """,
            )
            total = filas[0]["total"] if filas else 0
            migrados = filas[0]["migrados"] if filas else 0
            fila.update(
                total=total,
                migrados=migrados,
                cobertura_pct=round(100.0 * migrados / total, 1) if total else 0.0,
                disponible=True,
            )
        except Exception as exc:  # noqa: BLE001
            fila["error"] = str(exc).strip().splitlines()[0]
        salida.append(fila)
    return salida
