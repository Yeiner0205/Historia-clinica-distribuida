"""
app/middleware.py — Middleware de coordinación heredado del repositorio de
referencia: ejecuta una consulta en los tres nodos y reparte las escrituras.

Se conserva (el tablero de nodos lo usa) pero ahora toma la configuración de
`comun/sedes.py`, y la escritura acepta la sede explícita: el enrutamiento por
rango de documento queda como regla de respaldo.
"""

import psycopg2
from psycopg2.extras import RealDictCursor

from comun import sedes

NODOS = [
    {
        "host": s["host"],
        "port": s["port"],
        "user": s["user"],
        "password": s["password"],
        "dbname": s["dbname"],
        "sede_id": s["sede_id"],
        "sede": s["nombre"],
    }
    for s in sedes.SEDES
]

USE_DOCKER_NAMES = sedes.USE_DOCKER_NAMES


def ejecutar_query_en_todos_los_nodos(query):
    resultados = []
    nodos_estado = []
    
    for nodo in NODOS:
        nodo_info = {"nodo": f"nodo_{nodo['sede_id']}", "sede": nodo["sede"],
                     "estado": "DOWN", "error": None}
        try:
            conn = psycopg2.connect(
                host=nodo["host"],
                port=nodo["port"],
                user=nodo["user"],
                password=nodo["password"],
                dbname=nodo["dbname"]
            )
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query)
                filas = cur.fetchall()
                resultados.extend(filas)
            conn.close()
            nodo_info["estado"] = "UP"
        except Exception as e:
            nodo_info["error"] = str(e)
            print(f"Error en nodo {nodo['port']}: {e}")
        
        nodos_estado.append(nodo_info)
            
    return {"resultados": resultados, "nodos_estado": nodos_estado}


def insertar_registro_firh(tabla, datos, sede_id=None):
    """
    Inserta un registro en la tabla indicada, en el nodo de la sede.

    Si no se declara sede, se aplica la fragmentación horizontal por rango de
    documento del repositorio de referencia.
    """
    if "documento_id" not in datos:
        raise ValueError("documento_id es requerido para enrutar el registro")

    documento_id = int(datos["documento_id"])

    if sede_id:
        nodo_idx = int(sede_id) - 1
        if not 0 <= nodo_idx <= 2:
            raise ValueError(f"sede desconocida: {sede_id}")
    else:
        nodo_idx = sedes.nodo_por_documento(documento_id)["sede_id"] - 1

    nodo = NODOS[nodo_idx]
    
    # Construir la consulta INSERT
    columnas = ", ".join(datos.keys())
    placeholders = ", ".join(["%s"] * len(datos))
    valores = list(datos.values())
    
    query = f"INSERT INTO {tabla} ({columnas}) VALUES ({placeholders})"
    
    try:
        conn = psycopg2.connect(
            host=nodo["host"],
            port=nodo["port"],
            user=nodo["user"],
            password=nodo["password"],
            dbname=nodo["dbname"]
        )
        with conn.cursor() as cur:
            cur.execute(query, valores)
            conn.commit()
        conn.close()
        
        return {
            "success": True,
            "message": f"Registro insertado en {tabla} en nodo {nodo_idx + 1}",
            "nodo": f"nodo_{nodo['sede_id']}",
            "sede": nodo["sede"],
            "documento_id": documento_id
        }
    except Exception as e:
        raise Exception(f"Error al insertar en nodo {nodo_idx + 1}: {str(e)}")


if __name__ == "__main__":
    consulta = "SELECT documento_id, nombre_completo, edad FROM usuario;"
    salida = ejecutar_query_en_todos_los_nodos(consulta)
    for fila in salida["resultados"]:
        print(fila)
    for nodo in salida["nodos_estado"]:
        print(nodo)
