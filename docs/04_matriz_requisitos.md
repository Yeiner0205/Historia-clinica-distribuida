# Matriz de requisitos y evidencia

Cada requisito del enunciado con el comando que lo verifica. Todos los
comandos suponen la plataforma levantada (`docker compose up -d`) y, cuando
hace falta token, que se obtuvo así:

```bash
TOKEN=$(curl -s -X POST http://localhost:8001/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"usuario":"auditor1","password":"auditor123"}' | python3 -c 'import json,sys;print(json.load(sys.stdin)["access_token"])')
```

## Requisitos funcionales

### RF1 · Ingerir datos de las 3 sedes en al menos 2 formatos

**Estado: cumplido.** HL7 v2 (`ADT^A01` y `ORU^R01`) y CSV legado con
separador `;`, de las tres sedes.

```bash
# HL7 v2 ADT desde la sede 2
curl -X POST --data-binary @ejemplos/01_adt_a01_valido_sede2.hl7 http://localhost:8000/hsb/hl7
# HL7 v2 ORU desde la sede 1
curl -X POST --data-binary @ejemplos/02_oru_r01_laboratorio_sede1.hl7 http://localhost:8000/hsb/hl7
# CSV legado desde la sede 3
curl -X POST --data-binary @ejemplos/04_sede3_legado.csv "http://localhost:8000/hsb/csv?sede=3"
```

Código: [hsb/hl7.py](../hsb/hl7.py), [hsb/csv_legado.py](../hsb/csv_legado.py).
Pruebas: `test_lectores_y_validador.py` (16 casos).

### RF2 · Normalizar a FHIR R4 en Bundle

**Estado: cumplido y validado.** `Patient`, `Encounter`, `Condition` (CIE-10),
`Observation` (LOINC) y `Practitioner`, en Bundle `transaction` para la
ingesta y Bundle `document` con `Composition` para el paciente.

```bash
# Ver el Bundle que produce un mensaje, y validarlo contra HAPI
curl -X POST --data-binary @ejemplos/01_adt_a01_valido_sede2.hl7 \
  "http://localhost:8000/hsb/validar?formato=hl7v2&contra_hapi=true" | python3 -m json.tool

# Validar el Bundle document de un paciente
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8001/api/v1/reporte/1001/bundle/validar
```

Resultado esperado: `"valido": true` y lista de errores vacía.
Código: [fhir/normalizador.py](../fhir/normalizador.py).
Pruebas: `test_normalizador.py` (13 casos, dos de ellos inválidos).

### RF3 · HSB con enrutamiento, transformación, validación, cola con reintentos e idempotencia

**Estado: cumplido.**

| Pieza | Evidencia |
| --- | --- |
| Enrutamiento por sede | `MSH-4` o `?sede=N` deciden el nodo; el resultado de la entrega devuelve `sede_id` |
| Validación con motivos | `ejemplos/03_adt_a01_invalido.hl7` se rechaza con exactamente 3 motivos |
| Transformación | El Bundle se guarda en `mensaje_bus.bundle` y se puede consultar |
| Cola con reintentos | Apagar HAPI deja el mensaje en `reintentando` con esperas de 1, 2, 4 y 8 s |
| Cola de mensajes muertos | Tras 4 intentos pasa a `muerto`; `GET /hsb/muertos` lo lista |
| Idempotencia | Reenviar responde `duplicado` y deja un solo paciente |

```bash
# Idempotencia
curl -X POST --data-binary @ejemplos/01_adt_a01_valido_sede2.hl7 http://localhost:8000/hsb/hl7
curl -X POST --data-binary @ejemplos/01_adt_a01_valido_sede2.hl7 http://localhost:8000/hsb/hl7
#   → la segunda responde "resultado": "duplicado"
curl -s "http://localhost:8080/fhir/Patient?identifier=1007" | grep -o '"total":[0-9]*'
#   → "total":1

# Reintento y cola de muertos
docker compose stop hapi-fhir
curl -X POST --data-binary @ejemplos/06_oru_r01_reintento_sede1.hl7 http://localhost:8000/hsb/hl7
#   → "resultado": "reintentando"
docker compose start hapi-fhir
curl -s http://localhost:8000/hsb/muertos | python3 -m json.tool
```

Código: [hsb/cola.py](../hsb/cola.py), [hsb/entrega.py](../hsb/entrega.py).
Pruebas: `test_integracion_hsb.py` (10 casos).

### RF4 · Datos distribuidos y consulta unificada de un paciente en las 3 sedes

**Estado: cumplido.** Un nodo PostgreSQL por sede, consulta unificada en
paralelo. El paciente 1001 tiene atenciones en las tres.

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8001/api/v1/historia/1001 \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print("sedes:", d["resumen"]["sedes_con_registro"], "atenciones:", d["resumen"]["atenciones"])'
#   → sedes: [1, 2, 3] atenciones: 3

# EXPLAIN: la consulta usa la clave de fragmentación (índice, no recorrido)
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8001/api/v1/datos/explain?documento=1001" | python3 -m json.tool

# ACID: transacción que falla a la mitad y no deja nada
curl -X POST -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8001/api/v1/datos/prueba-acid?sede=1" | python3 -m json.tool
#   → "atomica": true
```

Código: [app/consulta_unificada.py](../app/consulta_unificada.py).

### RF5 · Seguridad y confianza: token, roles y auditoría encadenada por hash

**Estado: cumplido.** JWT HS256, cuatro roles con permisos distintos
verificados en la API, y cadena de hash con verificador.

```bash
# Acceso permitido y denegado
TP=$(curl -s -X POST http://localhost:8001/auth/login -H 'Content-Type: application/json' \
      -d '{"usuario":"paciente1007","password":"paciente123"}' | python3 -c 'import json,sys;print(json.load(sys.stdin)["access_token"])')
curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $TP" http://localhost:8001/api/v1/paciente/mi-historia
#   → 200  (su propia historia)
curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $TP" http://localhost:8001/api/v1/historia/1001
#   → 403  (la de otro paciente), y queda un evento de auditoría

# Verificar la cadena, alterarla y volver a verificar
docker compose exec app python scripts/verificar_auditoria.py   # → ÍNTEGRA, código 0
./scripts/alterar_auditoria_demo.sh
docker compose exec app python scripts/verificar_auditoria.py   # → ALTERADA, código 1
```

Código: [comun/seguridad.py](../comun/seguridad.py),
[comun/auditoria.py](../comun/auditoria.py), [app/auth.py](../app/auth.py).
Pruebas: 15 casos de la matriz de permisos en `test_integracion_api.py`.

### RF6 · Cuatro vistas por rol

**Estado: cumplido.**

| Vista | URL | Usuario de prueba |
| --- | --- | --- |
| Paciente | http://localhost:8001/paciente | `paciente1007` / `paciente123` |
| Admisionista | http://localhost:8001/admision | `admision2` / `admision123` |
| Médico | http://localhost:8001/medico | `medico1` / `medico123` |
| Reporte de HC (con tablero) | http://localhost:8001/reporte-hc | `auditor1` / `auditor123` |

El tablero de estado está dentro del Reporte de HC, como pide el enunciado:
nodos disponibles, cobertura FHIR por sede, métricas del bus y resultado del
verificador de auditoría.

## Requisitos no funcionales

### RNF1 · Un solo comando levanta todo

```bash
docker compose down -v && docker compose up -d
./scripts/esperar_servicios.sh
```

Los tres nodos cargan esquema y datos sintéticos en el primer arranque con
los scripts de `docker-entrypoint-initdb.d`: no hay paso manual.

### RNF2 · Si una sede cae, la vista sigue respondiendo

```bash
docker compose stop pg_nodo2
curl -H "Authorization: Bearer $TOKEN" http://localhost:8001/api/v1/historia/1001 \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print("parcial:", d["parcial"], "| disponibles:", d["sedes_disponibles"], "| caídas:", [s["nombre"] for s in d["sedes_no_disponibles"]])'
#   → parcial: True | disponibles: [1, 3] | caídas: ['Cartagena']

curl -H "Authorization: Bearer $TOKEN" http://localhost:8001/api/v1/reporte/1001 \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["completo"], d["aviso"])'
#   → False  Reporte PARCIAL: la sede Cartagena no respondió

docker compose start pg_nodo2   # el bus entrega solo lo que quedó pendiente
```

### RNF3 · Cada servicio expone /health y /metrics

| Servicio | Salud | Métricas |
| --- | --- | --- |
| API | http://localhost:8001/health | http://localhost:8001/metrics |
| HSB | http://localhost:8000/health | http://localhost:8000/metrics |
| HAPI FHIR | http://localhost:8080/fhir/metadata | (lo reportan `/health` de la API y del bus) |

Los `/metrics` salen en formato de texto de Prometheus; hay además
`/metrics.json` para el tablero.

## Lista de verificación final del enunciado

| Punto | Estado | Cómo se comprueba |
| --- | --- | --- |
| `docker compose down -v && docker compose up` levanta todo sin errores | Cumplido | `./scripts/esperar_servicios.sh` |
| Las cuatro vistas abren y respetan los permisos por rol | Cumplido | 15 casos de la matriz en `test_integracion_api.py` |
| Un HL7 v2 y un CSV llegan como FHIR a HAPI y a las bases de las sedes | Cumplido | `test_integracion_hsb.py` |
| Reenviar un mensaje no crea duplicados | Cumplido | `test_reenviar_el_mismo_mensaje_no_crea_otro_paciente` |
| Apagar una sede no detiene la vista unificada | Cumplido | RNF2 de arriba |
| El verificador detecta una fila de auditoría alterada | Cumplido | `scripts/alterar_auditoria_demo.sh` + verificador |
| El Reporte de HC se genera para un paciente de las 3 sedes | Cumplido | `/api/v1/reporte/1001` |
| Informe completo en la plantilla v7 con referencias APA 7 | **Falta el equipo** | [01_informe.md](01_informe.md): completar autores y verificar las fuentes |
| README con pasos, usuarios de prueba y etiqueta v1.0 | Cumplido | [README.md](../README.md) |
