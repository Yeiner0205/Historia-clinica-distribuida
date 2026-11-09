# Resultados medidos

Cifras de una corrida completa desde cero (`AUTO=1 ./scripts/demo.sh`), no
estimaciones. Junto a cada una está el comando que la produce, para poder
repetirla.

**Entorno de la medición:** portátil de desarrollo, Linux, Docker 29.7,
siete contenedores en la misma máquina. No es un entorno de producción ni
una prueba de carga: es la evidencia de que el sistema hace lo que dice y de
dónde se va el tiempo.

---

## 1. Latencia de extremo a extremo del bus

La latencia se mide desde que el mensaje entra por la puerta de la sede hasta
que está entregado en HAPI **y** en el nodo de la sede
(`mensaje_bus.latencia_ms`).

```bash
curl -s http://localhost:8000/metrics.json | python3 -m json.tool
```

| Métrica | Valor |
| --- | --- |
| Latencia media | **328,5 ms** |
| Percentil 95 | **1 184,2 ms** |
| Mensaje más rápido observado | 136 ms (ORU^R01 de la sede 1) |
| Primer mensaje de la corrida | 345 ms (HAPI todavía calentando) |

En una segunda corrida sobre el mismo sistema ya caliente, la media bajó a
**220,6 ms** y el p95 a **808,4 ms**. La diferencia está en las cachés de
HAPI, no en el bus: el procesamiento propio (leer, validar, normalizar) está
por debajo de 5 ms; el resto es la llamada HTTP al servidor FHIR y la
escritura en PostgreSQL.

## 2. Mensajes procesados y porcentaje de fallidos

```bash
curl -s http://localhost:8000/metrics.json \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["mensajes_por_estado"], d["porcentaje_fallidos"])'
```

| Estado | Mensajes |
| --- | --- |
| Entregado | 13 |
| Rechazado | 3 |
| Reintentando | 0 |
| Muerto | 0 |
| **Total** | **16** |

**Porcentaje de fallidos: 18,75 %.** Hay que leerlo con su contexto: los tres
rechazos son exactamente los que el contrato de `ejemplos/LEEME.md` manda
rechazar —el `03_adt_a01_invalido.hl7` y las dos filas malas del CSV de la
sede 3—. No es una tasa de error del sistema: es el validador haciendo su
trabajo. Si se descuentan los mensajes diseñados para fallar, la tasa de
error es **0 %**.

### Mensajes por minuto

El escenario del parcial no tiene carga sostenida, así que la cifra de
«mensajes por minuto» que publica `/metrics.json` es el total dividido por el
tiempo de vida del servicio y no significa gran cosa. Lo que sí se puede
afirmar con la latencia medida es la cota: con 328 ms por mensaje y un solo
trabajador, el bus sostiene del orden de **180 mensajes por minuto**; con
cuatro réplicas (`docker compose up --scale hsb=4`), unos **700**. Medirlo de
verdad exige una prueba de carga, que la plantilla marca como bonus y que
este trabajo **no hizo**.

## 3. Cobertura de migración a FHIR

```bash
curl -s http://localhost:8001/api/v1/datos/cobertura | python3 -m json.tool
```

| Momento | Sincelejo | Cartagena | Corozal | Global |
| --- | --- | --- | --- | --- |
| Al arrancar desde cero | 0/3 = **0 %** | 0/3 = **0 %** | 0/2 = **0 %** | **0 %** |
| Tras los mensajes de ejemplo | 1/3 = 33,3 % | 1/4 = 25,0 % | 3/5 = 60,0 % | 41,7 % |
| Tras normalizar el legado | 3/3 = **100 %** | 4/4 = **100 %** | 5/5 = **100 %** | **100 %** |

El total de Cartagena y Corozal crece porque los mensajes de ejemplo crean
pacientes nuevos (1007 en Cartagena; 1008, 1009 y 1010 en Corozal).

## 4. Idempotencia

```bash
curl -X POST --data-binary @ejemplos/01_adt_a01_valido_sede2.hl7 http://localhost:8000/hsb/hl7
curl -s "http://localhost:8080/fhir/Patient?identifier=1007" | grep -o '"total":[0-9]*'
```

| Comprobación | Resultado |
| --- | --- |
| Respuesta al reenvío | `duplicado` (estado del original: `entregado`) |
| `Patient` con identificador 1007 en HAPI | **1** |
| Filas de 1007 en la base de la sede 2 | **1** |
| Duplicados frenados en la corrida | **1** |

## 5. Resiliencia

### Caída de una sede

```bash
docker compose stop pg_nodo2
```

| Comprobación | Resultado |
| --- | --- |
| ¿Responde la consulta unificada? | Sí |
| Sedes disponibles | `[1, 3]` |
| Sede marcada como no disponible | Cartagena |
| Atenciones visibles | 2 de 3 |
| ¿El reporte se marca como completo? | **No** — «Reporte PARCIAL: la sede Cartagena no respondió» |
| Estado de `/health` | `degradado`, `2/3` sedes |
| Mensaje dirigido a la sede caída | queda en `reintentando` |
| Tras `docker compose start pg_nodo2` | **entregado en menos de 5 s**, sin intervención |

### Caída del servidor FHIR

```bash
docker compose stop hapi-fhir
curl -X POST --data-binary @ejemplos/06_oru_r01_reintento_sede1.hl7 http://localhost:8000/hsb/hl7
```

| Momento | Estado del mensaje |
| --- | --- |
| Con HAPI caído | `reintentando`, intento 1 de 4, siguiente en 1 s |
| Tras agotar los 4 intentos (~15 s) | `muerto`, visible en `GET /hsb/muertos` |
| Al reencolarlo con HAPI arriba | `entregado`, sin duplicar |

La latencia del mensaje reencolado fue de 209 s: incluye todo el tiempo que
HAPI estuvo apagado, que es lo correcto para una medición de extremo a
extremo.

## 6. Validación FHIR

```bash
curl -s -X POST --data-binary @ejemplos/01_adt_a01_valido_sede2.hl7 \
     "http://localhost:8000/hsb/validar?formato=hl7v2&contra_hapi=true"
curl -s -H "Authorization: Bearer $TOKEN" \
     http://localhost:8001/api/v1/reporte/1001/bundle/validar
```

| Bundle | `$validate` de HAPI |
| --- | --- |
| `transaction` (lo que entrega el bus) | **válido**, sin errores |
| `document` (el del paciente, con `Composition`) | **válido**, sin errores |

## 7. Consulta unificada y Reporte de HC

| Métrica | Valor |
| --- | --- |
| Sedes consultadas en una sola llamada | 3 |
| Sedes con registro del paciente 1001 | 1, 2 y 3 |
| Atenciones unificadas | 3 |
| Cobertura de campos de la HC | **41 de 42 = 97,6 %** |
| Campo faltante | Etnia (no está en los datos sintéticos) |
| Recursos en el Bundle `document` | 14 |
| Secciones del `Composition` | 3 (una por sede) |

## 8. Plan de la consulta distribuida

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
     "http://localhost:8001/api/v1/datos/explain?documento=1001"
```

En los tres nodos, idéntico:

```
Index Scan using usuario_pkey on usuario  (cost=0.14..8.15 rows=1 width=2361)
                                          (actual time=0.016..0.017 rows=1 loops=1)
  Index Cond: (documento_id = 1001)
Planning Time: 0.249 ms
```

Es la evidencia de que la clave de acceso elegida es la que usa el plan:
búsqueda por índice, no recorrido de la tabla. El error frecuente que señala
la guía —distribuir por una columna que casi no se usa en las consultas— se
vería aquí como un `Seq Scan`.

## 9. Transacción atómica

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
     "http://localhost:8001/api/v1/datos/prueba-acid?sede=1"
```

```json
{
  "usuarios_antes": 0,
  "error_forzado": "insert or update on table \"atencion\" violates foreign key constraint",
  "usuarios_despues": 0,
  "atenciones_despues": 0,
  "atomica": true
}
```

La transacción escribió `usuario` y `atencion` y falló en la tercera
sentencia. El rollback dejó la sede como estaba.

## 10. Permisos por rol

20 comprobaciones, todas con el código esperado:

| Rol | Permitido | Denegado |
| --- | --- | --- |
| paciente | su historia, su reporte, su Bundle, sus accesos | la historia de otro (403), escribir clínica (403), leer la auditoría (403) |
| admisionista | buscar, registrar, abrir atención, estado del bus | escribir diagnóstico (403), ver el tablero (403) |
| medico | historia unificada, escribir clínica, tablero, reporte | abrir atención (403), apagar un nodo (403), auditoría (403) |
| auditor | auditoría, verificador, tablero, reporte, operar el bus | escribir contenido clínico (403) |
| sin token | — | todo lo protegido (401) |

```bash
./ejemplos/coleccion_pruebas.sh seguridad
```

## 11. Auditoría

| Comprobación | Resultado |
| --- | --- |
| Eventos en la cadena tras la corrida | 24 |
| Verificación con la cadena intacta | **ÍNTEGRA** (código de salida 0) |
| Tras alterar el evento #13 a mano | **ALTERADA**, señala el #13 y el motivo (código 1) |
| Tras borrar una fila | **ALTERADA**, «eslabón roto: hash_anterior no coincide» |
| Hash de cabeza | `0204852e965c3f56…` (SHA-256 de 64 caracteres) |

## 12. Pruebas automatizadas

```bash
docker compose exec app pytest tests -v
```

**96 pruebas, 96 pasan.** Reparto: 52 unitarias (sin dependencias) y 44 de
integración (con la plataforma levantada).

---

## Cómo repetir todas estas mediciones

```bash
docker compose down -v && docker compose up -d
./scripts/esperar_servicios.sh
AUTO=1 ./scripts/demo.sh --sin-reinicio    # la corrida completa, narrada
./ejemplos/coleccion_pruebas.sh            # todas las llamadas, una por una
docker compose exec app pytest tests -v    # las 96 pruebas
```

Las cifras exactas variarán entre máquinas; los resultados cualitativos
—entregado, duplicado, rechazado, parcial, íntegra, alterada— no.
