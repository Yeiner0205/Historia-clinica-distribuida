# Observabilidad (bonus)

El enunciado ofrece hasta 0,25 extra por un «tablero con Prometheus y
Grafana». La mitad del trabajo ya está hecha: la API y el bus publican
métricas en el formato que Prometheus entiende.

## Qué ya funciona (probado)

```bash
curl http://localhost:8001/metrics    # métricas de la API
curl http://localhost:8000/metrics    # métricas del bus
```

## Qué falta para el bonus (sin probar)

```bash
docker compose -f docker-compose.yml \
               -f infra/observabilidad/docker-compose.observabilidad.yml up -d
```

Y después, en Grafana (http://localhost:3000), construir un tablero con:

| Panel | Consulta PromQL |
| --- | --- |
| Mensajes por estado | `hsb_mensajes_total` |
| Latencia media y p95 | `hsb_latencia_media_ms` y `hsb_latencia_p95_ms` |
| Porcentaje de fallidos | `hsb_porcentaje_fallidos` |
| Duplicados frenados | `hsb_duplicados_detectados` |
| Sedes disponibles | `sum(sede_disponible)` |
| Cobertura FHIR por sede | `cobertura_fhir_pct` |
| Accesos denegados | `rate(api_denegaciones_total[5m])` |

El bonus exige evidencia: una captura del tablero con datos reales.
