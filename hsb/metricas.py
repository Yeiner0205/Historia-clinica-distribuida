"""
hsb/metricas.py — Medición del bus (Fase 3, Paso 9).

Expone, en `/metrics`:
  * total de mensajes por estado,
  * mensajes del último minuto (y por minuto),
  * latencia media de extremo a extremo (ms),
  * porcentaje de fallidos (rechazados + muertos),
  * duplicados detectados.

Los contadores que no se pueden derivar de `mensaje_bus` (duplicados,
reencolados) viven en la tabla `contador_hsb`, así que sobreviven al reinicio.
Además se publica el formato de texto de Prometheus para el tablero del bonus.
"""

import threading
import time
from typing import Any, Dict, List

from comun import db

_inicio = time.time()
_candado = threading.Lock()
# Contadores en memoria del proceso (complementan los de la base).
_proceso: Dict[str, int] = {
    "entregado": 0,
    "rechazado": 0,
    "reintentando": 0,
    "muerto": 0,
    "peticiones": 0,
}


def contar(nombre: str, cuanto: int = 1) -> None:
    with _candado:
        _proceso[nombre] = _proceso.get(nombre, 0) + cuanto


def tiempo_activo_s() -> float:
    return round(time.time() - _inicio, 1)


def recolectar() -> Dict[str, Any]:
    """Métricas completas. Nunca lanza: si el central no responde, lo dice."""
    datos: Dict[str, Any] = {
        "tiempo_activo_s": tiempo_activo_s(),
        "proceso": dict(_proceso),
        "central_disponible": False,
    }
    try:
        with db.cursor_central() as cur:
            cur.execute("SELECT estado, COUNT(*)::int AS total FROM mensaje_bus GROUP BY estado;")
            por_estado = {f["estado"]: f["total"] for f in cur.fetchall()}

            cur.execute(
                """
                SELECT COUNT(*)::int AS total
                  FROM mensaje_bus
                 WHERE recibido_en >= NOW() - INTERVAL '1 minute';
                """
            )
            ultimo_minuto = cur.fetchone()["total"]

            cur.execute(
                """
                SELECT ROUND(AVG(latencia_ms)::numeric, 1) AS media,
                       MIN(latencia_ms) AS minima,
                       MAX(latencia_ms) AS maxima,
                       PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latencia_ms) AS p95
                  FROM mensaje_bus
                 WHERE latencia_ms IS NOT NULL;
                """
            )
            lat = cur.fetchone()

            cur.execute("SELECT nombre, valor FROM contador_hsb;")
            contadores = {f["nombre"]: int(f["valor"]) for f in cur.fetchall()}

            cur.execute(
                """
                SELECT sede_id, estado, COUNT(*)::int AS total
                  FROM mensaje_bus GROUP BY sede_id, estado ORDER BY sede_id;
                """
            )
            por_sede: Dict[str, Dict[str, int]] = {}
            for f in cur.fetchall():
                por_sede.setdefault(str(f["sede_id"]), {})[f["estado"]] = f["total"]

        total = sum(por_estado.values())
        fallidos = por_estado.get("rechazado", 0) + por_estado.get("muerto", 0)
        datos.update(
            central_disponible=True,
            mensajes_por_estado=por_estado,
            total_mensajes=total,
            mensajes_ultimo_minuto=ultimo_minuto,
            mensajes_por_minuto=round(total / max(tiempo_activo_s() / 60.0, 1 / 60.0), 2),
            latencia_media_ms=float(lat["media"]) if lat and lat["media"] is not None else None,
            latencia_min_ms=lat["minima"] if lat else None,
            latencia_max_ms=lat["maxima"] if lat else None,
            latencia_p95_ms=round(float(lat["p95"]), 1) if lat and lat["p95"] is not None else None,
            fallidos=fallidos,
            porcentaje_fallidos=round(100.0 * fallidos / total, 2) if total else 0.0,
            duplicados_detectados=contadores.get("duplicados_detectados", 0),
            reencolados=contadores.get("reencolados", 0),
            mensajes_por_sede=por_sede,
            en_cola=sum(por_estado.get(e, 0) for e in ("recibido", "validado", "transformado", "reintentando")),
            muertos=por_estado.get("muerto", 0),
        )
    except Exception as exc:  # noqa: BLE001
        datos["error"] = str(exc).strip().splitlines()[0]
    return datos


def texto_prometheus(servicio: str = "hsb") -> str:
    """Formato de exposición de Prometheus (para el tablero del bonus)."""
    m = recolectar()
    lineas: List[str] = [
        "# HELP hsb_tiempo_activo_segundos Tiempo que lleva en marcha el servicio.",
        "# TYPE hsb_tiempo_activo_segundos gauge",
        f'hsb_tiempo_activo_segundos{{servicio="{servicio}"}} {m["tiempo_activo_s"]}',
        "# HELP hsb_central_disponible 1 si el almacén central responde.",
        "# TYPE hsb_central_disponible gauge",
        f'hsb_central_disponible{{servicio="{servicio}"}} {1 if m["central_disponible"] else 0}',
    ]
    if m["central_disponible"]:
        lineas += [
            "# HELP hsb_mensajes_total Mensajes del bus por estado.",
            "# TYPE hsb_mensajes_total counter",
        ]
        for estado, total in sorted(m["mensajes_por_estado"].items()):
            lineas.append(f'hsb_mensajes_total{{estado="{estado}"}} {total}')
        for sede, estados in sorted(m["mensajes_por_sede"].items()):
            for estado, total in sorted(estados.items()):
                lineas.append(f'hsb_mensajes_sede_total{{sede="{sede}",estado="{estado}"}} {total}')
        lineas += [
            "# HELP hsb_latencia_media_ms Latencia media de extremo a extremo.",
            "# TYPE hsb_latencia_media_ms gauge",
            f'hsb_latencia_media_ms {m["latencia_media_ms"] if m["latencia_media_ms"] is not None else 0}',
            "# HELP hsb_latencia_p95_ms Percentil 95 de la latencia.",
            "# TYPE hsb_latencia_p95_ms gauge",
            f'hsb_latencia_p95_ms {m["latencia_p95_ms"] if m["latencia_p95_ms"] is not None else 0}',
            "# HELP hsb_porcentaje_fallidos Porcentaje de mensajes rechazados o muertos.",
            "# TYPE hsb_porcentaje_fallidos gauge",
            f'hsb_porcentaje_fallidos {m["porcentaje_fallidos"]}',
            "# HELP hsb_duplicados_detectados Mensajes repetidos frenados por idempotencia.",
            "# TYPE hsb_duplicados_detectados counter",
            f'hsb_duplicados_detectados {m["duplicados_detectados"]}',
            "# HELP hsb_mensajes_ultimo_minuto Mensajes recibidos en el último minuto.",
            "# TYPE hsb_mensajes_ultimo_minuto gauge",
            f'hsb_mensajes_ultimo_minuto {m["mensajes_ultimo_minuto"]}',
            "# HELP hsb_en_cola Mensajes pendientes de entrega.",
            "# TYPE hsb_en_cola gauge",
            f'hsb_en_cola {m["en_cola"]}',
        ]
    return "\n".join(lineas) + "\n"
