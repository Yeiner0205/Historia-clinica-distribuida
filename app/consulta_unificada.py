"""
app/consulta_unificada.py — Consulta unificada de la historia de un paciente
en las tres sedes (RF4) con degradación cuando una sede cae (RNF).

Las tres sedes se consultan **en paralelo**: así la respuesta tarda lo que la
sede más lenta y no la suma de las tres, y una sede caída solo cuesta su
`connect_timeout`. Lo que no responde se reporta como `sede no disponible`:
la vista sigue funcionando con las otras dos y el reporte queda marcado como
`parcial`, nunca como completo (error frecuente que señala la guía).
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID

from comun import db, sedes

logger = logging.getLogger(__name__)

SQL_PACIENTE = "SELECT * FROM usuario WHERE documento_id = %s;"

SQL_ATENCIONES = """
    SELECT a.atencion_id, a.documento_id, a.sede_id, a.visita, a.entidad_salud,
           a.fecha_ingreso, a.modalidad_entrega, a.entorno_atencion, a.via_ingreso,
           a.causa_atencion, a.fecha_triage, a.clasificacion_triage,
           a.profesional_codigo, a.fhir_encounter_id, a.mensaje_id,
           p.nombre AS profesional_nombre, p.especialidad AS profesional_especialidad
      FROM atencion a
      LEFT JOIN profesional_salud p ON p.codigo = a.profesional_codigo
     WHERE a.documento_id = %s
     ORDER BY a.fecha_ingreso DESC NULLS LAST, a.atencion_id DESC;
"""

SQL_DIAGNOSTICOS = """
    SELECT d.* FROM diagnostico d
      JOIN atencion a ON a.atencion_id = d.atencion_id
     WHERE a.documento_id = %s;
"""

SQL_OBSERVACIONES = """
    SELECT o.* FROM observacion o
     WHERE o.documento_id = %s
     ORDER BY o.fecha DESC NULLS LAST;
"""

SQL_MEDICAMENTOS = """
    SELECT t.* FROM tecnologia_salud t
      JOIN atencion a ON a.atencion_id = t.atencion_id
     WHERE a.documento_id = %s;
"""

SQL_EGRESOS = """
    SELECT e.* FROM egreso e
      JOIN atencion a ON a.atencion_id = e.atencion_id
     WHERE a.documento_id = %s;
"""


def serializable(valor: Any) -> Any:
    """Convierte fechas, UUID y Decimal a tipos que viajan en JSON."""
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    if isinstance(valor, UUID):
        return str(valor)
    if isinstance(valor, Decimal):
        return float(valor)
    if isinstance(valor, dict):
        return {k: serializable(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [serializable(v) for v in valor]
    return valor


def _historia_en_sede(sede: Dict[str, Any], documento_id: int) -> Dict[str, Any]:
    """Lee toda la historia del paciente en UNA sede. No lanza excepciones."""
    salida: Dict[str, Any] = {
        "sede_id": sede["sede_id"],
        "codigo": sede["codigo"],
        "nombre": sede["nombre"],
        "nodo": sede["nodo"],
        "disponible": False,
        "paciente": None,
        "atenciones": [],
        "totales": {"atenciones": 0, "diagnosticos": 0, "observaciones": 0, "medicamentos": 0},
    }
    try:
        conn = db.conectar(sede)
    except Exception as exc:  # noqa: BLE001
        salida["error"] = str(exc).strip().splitlines()[0]
        logger.warning("Sede %s no disponible: %s", sede["nombre"], salida["error"])
        return salida

    try:
        from psycopg2.extras import RealDictCursor

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(SQL_PACIENTE, (documento_id,))
            fila = cur.fetchone()
            salida["paciente"] = serializable(dict(fila)) if fila else None

            cur.execute(SQL_ATENCIONES, (documento_id,))
            atenciones = [serializable(dict(r)) for r in cur.fetchall()]

            cur.execute(SQL_DIAGNOSTICOS, (documento_id,))
            diagnosticos = [serializable(dict(r)) for r in cur.fetchall()]

            cur.execute(SQL_OBSERVACIONES, (documento_id,))
            observaciones = [serializable(dict(r)) for r in cur.fetchall()]

            cur.execute(SQL_MEDICAMENTOS, (documento_id,))
            medicamentos = [serializable(dict(r)) for r in cur.fetchall()]

            cur.execute(SQL_EGRESOS, (documento_id,))
            egresos = [serializable(dict(r)) for r in cur.fetchall()]

        # Se arma el árbol atención → diagnósticos / observaciones / fórmulas
        por_atencion = {a["atencion_id"]: a for a in atenciones}
        for a in atenciones:
            a["sede_nombre"] = sede["nombre"]
            a["diagnosticos"] = []
            a["observaciones"] = []
            a["medicamentos"] = []
            a["egreso"] = None
        for d in diagnosticos:
            if d["atencion_id"] in por_atencion:
                por_atencion[d["atencion_id"]]["diagnosticos"].append(d)
        for o in observaciones:
            if o.get("atencion_id") in por_atencion:
                por_atencion[o["atencion_id"]]["observaciones"].append(o)
        for m in medicamentos:
            if m["atencion_id"] in por_atencion:
                por_atencion[m["atencion_id"]]["medicamentos"].append(m)
        for e in egresos:
            if e["atencion_id"] in por_atencion:
                por_atencion[e["atencion_id"]]["egreso"] = e

        salida.update(
            disponible=True,
            atenciones=atenciones,
            totales={
                "atenciones": len(atenciones),
                "diagnosticos": len(diagnosticos),
                "observaciones": len(observaciones),
                "medicamentos": len(medicamentos),
            },
        )
    except Exception as exc:  # noqa: BLE001
        salida["error"] = str(exc).strip().splitlines()[0]
        logger.warning("Error leyendo la sede %s: %s", sede["nombre"], salida["error"])
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass
    return salida


def historia_unificada(documento_id: int) -> Dict[str, Any]:
    """
    Una sola llamada devuelve la historia del paciente en las 3 sedes.

    `parcial = True` significa que alguna sede no respondió: la vista debe
    avisarlo y el reporte no puede presentarse como completo.
    """
    with ThreadPoolExecutor(max_workers=3) as pool:
        resultados = list(pool.map(lambda s: _historia_en_sede(s, documento_id), sedes.SEDES))

    disponibles = [r for r in resultados if r["disponible"]]
    caidas = [
        {"sede_id": r["sede_id"], "nombre": r["nombre"], "error": r.get("error", "sin respuesta")}
        for r in resultados
        if not r["disponible"]
    ]

    # Identidad del paciente entre sedes: la regla de coincidencia es el
    # documento exacto. El primer registro disponible sirve de ficha base.
    paciente: Optional[Dict[str, Any]] = None
    for r in disponibles:
        if r["paciente"]:
            paciente = dict(r["paciente"])
            paciente["_sedes"] = []
            break
    if paciente is not None:
        for r in disponibles:
            if r["paciente"]:
                paciente["_sedes"].append({"sede_id": r["sede_id"], "nombre": r["nombre"],
                                           "fhir_patient_id": r["paciente"].get("fhir_patient_id")})

    atenciones = [a for r in disponibles for a in r["atenciones"]]
    atenciones.sort(key=lambda a: (a.get("fecha_ingreso") or ""), reverse=True)

    return {
        "documento_id": documento_id,
        "encontrado": paciente is not None,
        "paciente": paciente,
        "sedes": resultados,
        "sedes_disponibles": [r["sede_id"] for r in disponibles],
        "sedes_no_disponibles": caidas,
        "parcial": bool(caidas),
        "atenciones": atenciones,
        "resumen": {
            "sedes_con_registro": [r["sede_id"] for r in disponibles if r["paciente"] or r["atenciones"]],
            "atenciones": len(atenciones),
            "diagnosticos": sum(r["totales"]["diagnosticos"] for r in disponibles),
            "observaciones": sum(r["totales"]["observaciones"] for r in disponibles),
            "medicamentos": sum(r["totales"]["medicamentos"] for r in disponibles),
        },
    }


def buscar_por_nombre(texto: str, limite: int = 20) -> Dict[str, Any]:
    """Busca pacientes por nombre en las tres sedes a la vez."""

    def en_sede(sede: Dict[str, Any]) -> Dict[str, Any]:
        try:
            filas = db.consultar(
                sede,
                """
                SELECT documento_id, tipo_documento, nombre_completo, fecha_nacimiento,
                       sexo, sede_id, fhir_patient_id
                  FROM usuario
                 WHERE LOWER(nombre_completo) LIKE LOWER(%s)
                 LIMIT %s;
                """,
                (f"%{texto}%", limite),
            )
            return {"sede_id": sede["sede_id"], "nombre": sede["nombre"], "disponible": True,
                    "pacientes": [serializable(f) for f in filas]}
        except Exception as exc:  # noqa: BLE001
            return {"sede_id": sede["sede_id"], "nombre": sede["nombre"], "disponible": False,
                    "pacientes": [], "error": str(exc).strip().splitlines()[0]}

    with ThreadPoolExecutor(max_workers=3) as pool:
        resultados = list(pool.map(en_sede, sedes.SEDES))

    # Un mismo documento puede aparecer en varias sedes: se agrupa.
    agrupado: Dict[int, Dict[str, Any]] = {}
    for r in resultados:
        for p in r["pacientes"]:
            clave = p["documento_id"]
            entrada = agrupado.setdefault(clave, {**p, "sedes": []})
            entrada["sedes"].append({"sede_id": r["sede_id"], "nombre": r["nombre"]})

    caidas = [{"sede_id": r["sede_id"], "nombre": r["nombre"], "error": r.get("error")}
              for r in resultados if not r["disponible"]]
    return {
        "texto": texto,
        "total": len(agrupado),
        "pacientes": sorted(agrupado.values(), key=lambda p: p["nombre_completo"]),
        "sedes_no_disponibles": caidas,
        "parcial": bool(caidas),
    }


def explicar_consulta(documento_id: int) -> Dict[str, Any]:
    """
    `EXPLAIN (ANALYZE)` de la consulta distribuida en cada nodo: evidencia de
    que la clave de fragmentación (el documento del paciente) es la que usa el
    plan, con búsqueda por índice en lugar de recorrido completo.
    """
    salida = []
    for sede in sedes.SEDES:
        item: Dict[str, Any] = {"sede_id": sede["sede_id"], "nombre": sede["nombre"],
                                "disponible": False}
        try:
            filas = db.consultar(sede, "EXPLAIN (ANALYZE, BUFFERS) " + SQL_ATENCIONES, (documento_id,))
            item["disponible"] = True
            item["plan"] = [list(f.values())[0] for f in filas]
            filas = db.consultar(sede, "EXPLAIN (ANALYZE) " + SQL_PACIENTE, (documento_id,))
            item["plan_paciente"] = [list(f.values())[0] for f in filas]
        except Exception as exc:  # noqa: BLE001
            item["error"] = str(exc).strip().splitlines()[0]
        salida.append(item)
    return {"documento_id": documento_id, "consulta": SQL_ATENCIONES.strip(), "nodos": salida}


def prueba_acid(sede_id: int, documento_id: int = 999999999) -> Dict[str, Any]:
    """
    Demostración de atomicidad (Fase 2, Paso 8): se escribe `usuario` y
    `atencion` en la misma transacción y se fuerza un error a la mitad. Al
    final no debe quedar nada.
    """
    sede = sedes.sede(sede_id)
    antes = db.consultar(sede, "SELECT COUNT(*)::int AS n FROM usuario WHERE documento_id = %s;",
                         (documento_id,))[0]["n"]
    error = None
    try:
        with db.cursor_sede(sede_id) as cur:
            cur.execute(
                """
                INSERT INTO usuario (documento_id, tipo_documento, nombre_completo, sexo, sede_id)
                VALUES (%s, 'CC', 'PRUEBA ACID (no debe quedar)', 'O', %s);
                """,
                (documento_id, sede_id),
            )
            cur.execute(
                """
                INSERT INTO atencion (documento_id, sede_id, visita, fecha_ingreso)
                VALUES (%s, %s, %s, NOW());
                """,
                (documento_id, sede_id, f"V-ACID-{documento_id}"),
            )
            # Error deliberado a mitad de la transacción: la atención apunta a
            # un paciente que no existe, así que la clave ajena falla.
            cur.execute(
                """
                INSERT INTO atencion (documento_id, sede_id, visita, fecha_ingreso)
                VALUES (%s, %s, %s, NOW());
                """,
                (documento_id + 1, sede_id, f"V-ACID-ERROR-{documento_id}"),
            )
    except Exception as exc:  # noqa: BLE001
        error = str(exc).strip().splitlines()[0]

    despues = db.consultar(sede, "SELECT COUNT(*)::int AS n FROM usuario WHERE documento_id = %s;",
                           (documento_id,))[0]["n"]
    atenciones = db.consultar(sede, "SELECT COUNT(*)::int AS n FROM atencion WHERE visita LIKE %s;",
                              (f"V-ACID-%{documento_id}",))[0]["n"]
    return {
        "sede_id": sede_id,
        "sede": sede["nombre"],
        "documento_prueba": documento_id,
        "usuarios_antes": antes,
        "error_forzado": error,
        "usuarios_despues": despues,
        "atenciones_despues": atenciones,
        "atomica": despues == antes and atenciones == 0,
        "explicacion": (
            "La transacción escribió usuario y atencion y falló en la tercera sentencia "
            "(clave ajena inexistente). El rollback dejó la sede como estaba: "
            "o se confirma todo, o no se confirma nada."
        ),
    }
