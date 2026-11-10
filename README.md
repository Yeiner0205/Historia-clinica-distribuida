# Plataforma distribuida de interoperabilidad clínica

Parcial final de Sistemas Distribuidos. Una red de IPS con tres sedes
—**Sincelejo**, **Cartagena** y **Corozal**— donde cada sede conserva su
sistema legado y emite datos en formatos distintos (HL7 v2 y CSV). La
historia clínica de un mismo paciente está fraccionada entre las tres. Esta
plataforma la unifica **sin reemplazar los sistemas legados**.

> **Autor:** Yeiner Julian Perez Vitola · **Versión:** v1.0 · **Datos:** 100 % sintéticos

---

## Levantar todo con un comando

Requisitos: Docker y Docker Compose. Nada más.

```bash
docker compose up -d
./scripts/esperar_servicios.sh
```

HAPI FHIR tarda alrededor de un minuto en arrancar; el script espera por él.
Cuando termine:

| Qué | Dónde |
| --- | --- |
| Inicio de sesión | http://localhost:8001/login |
| Inicio (todas las vistas) | http://localhost:8001/home |
| Documentación de la API | http://localhost:8001/docs |
| Bus de integración | http://localhost:8000/ |
| Servidor FHIR | http://localhost:8080/fhir/metadata |

Para empezar de cero (borra los datos y vuelve a cargar los sintéticos):

```bash
docker compose down -v && docker compose up -d
```

---

## Usuarios de prueba

Son sintéticos y las claves se cambian con variables de entorno en un archivo
`.env` que **no se versiona** (`cp .env.example .env`).

| Usuario | Clave | Rol | Vista a la que entra |
| --- | --- | --- | --- |
| `paciente1007` | `paciente123` | paciente | [Mi historia](http://localhost:8001/paciente) |
| `admision2` | `admision123` | admisionista | [Admisión y triage](http://localhost:8001/admision) |
| `medico1` | `medico123` | medico | [Consulta médica](http://localhost:8001/medico) |
| `auditor1` | `auditor123` | auditor | [Reporte de HC y tablero](http://localhost:8001/reporte-hc) |

Los permisos se verifican **en la API**, no en la pantalla: cambiar el HTML o
llamar con `curl` no da acceso. La matriz completa está en
`GET /auth/matriz`.

---

## Las cuatro vistas

| Vista | Qué hace | Qué no puede hacer |
| --- | --- | --- |
| **Paciente** | Ver su historia unificada de las 3 sedes, descargar su Bundle FHIR y ver quién accedió a su historia | Ver datos de otros pacientes o modificar registros |
| **Admisionista** | Buscar o registrar al paciente, detectar duplicados entre sedes, abrir la atención con su triage y ver el estado de envío al bus | Ver diagnósticos ni notas clínicas |
| **Médico** | Consultar la historia unificada, registrar diagnóstico CIE-10, formular y registrar el egreso con sello de integridad | Alterar la auditoría ni abrir atenciones (eso es de admisión) |
| **Reporte de HC** | Reporte por sede con cobertura de campos, sello de integridad, impresión y Bundle FHIR; incluye el **tablero de estado** de la plataforma | Editar contenido clínico |

---

## Qué hay dentro

```
app/       API y las cuatro vistas (FastAPI + plantillas)   :8001
hsb/       bus de integración: lectores, validador, cola    :8000
fhir/      normalizador a FHIR R4, terminologías, cliente HAPI
comun/     sedes, acceso a datos, seguridad y auditoría
db/        esquemas y datos sintéticos (sedes y central)
docs/      informe, diagramas UML y anexos
tests/     96 pruebas unitarias y de integración
ejemplos/  mensajes del contrato y colección de pruebas
scripts/   espera de servicios, demostración y verificador
```

| Servicio | Contenedor | Puerto | Para qué |
| --- | --- | --- | --- |
| Sede 1 · Sincelejo | `pg_nodo1` | 5433 | Base legada de la sede |
| Sede 2 · Cartagena | `pg_nodo2` | 5434 | Base legada de la sede |
| Sede 3 · Corozal | `pg_nodo3` | 5435 | Base legada de la sede |
| Almacén central | `pg_central` | 5436 | Cola del bus, auditoría, terminologías y base de HAPI |
| Servidor FHIR | `hapi_fhir_hc` | 8080 | HAPI FHIR R4 y su validador |
| Bus de integración | `hsb` | 8000 | HL7 v2 y CSV → FHIR |
| API y vistas | `app_hc` | 8001 | Consulta unificada y las cuatro vistas |

El almacén central está **fuera de las sedes a propósito**: si una sede cae,
el bus y la auditoría siguen funcionando.

---

## Enviar los mensajes de ejemplo

Los archivos de `ejemplos/` son el contrato del parcial: cada uno debe
producir un resultado concreto.

```bash
# HL7 v2 ADT^A01 de la sede 2 → Patient 1007, Encounter y Condition J45.9
curl -X POST --data-binary @ejemplos/01_adt_a01_valido_sede2.hl7 \
     http://localhost:8000/hsb/hl7

# HL7 v2 ORU^R01 de la sede 1 → Observation LOINC 718-7 = 13,8 g/dL
curl -X POST --data-binary @ejemplos/02_oru_r01_laboratorio_sede1.hl7 \
     http://localhost:8000/hsb/hl7

# HL7 v2 inválido → rechazado con 3 motivos
curl -X POST --data-binary @ejemplos/03_adt_a01_invalido.hl7 \
     http://localhost:8000/hsb/hl7

# CSV legado de la sede 3 → 3 entregados y 2 rechazados
curl -X POST --data-binary @ejemplos/04_sede3_legado.csv \
     "http://localhost:8000/hsb/csv?sede=3"
```

Para ver cómo quedaron:

```bash
curl -s http://localhost:8000/hsb/mensajes | python3 -m json.tool
curl -s http://localhost:8000/metrics.json | python3 -m json.tool
```

La colección completa de pruebas está en
[ejemplos/coleccion_pruebas.sh](ejemplos/coleccion_pruebas.sh) (y en
[ejemplos/postman_collection.json](ejemplos/postman_collection.json) para
quien prefiera Postman).

---

## Probar lo que el parcial evalúa

### Normalizar el legado: la cobertura FHIR pasa de 0 % a 100 %

```bash
TOKEN=$(curl -s -X POST http://localhost:8001/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"usuario":"auditor1","password":"auditor123"}' \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["access_token"])')

curl -s http://localhost:8001/api/v1/datos/cobertura | python3 -m json.tool   # 0 %
for s in 1 2 3; do
  curl -s -X POST -H "Authorization: Bearer $TOKEN" \
       "http://localhost:8001/api/v1/bus/migrar?sede=$s" > /dev/null
done
curl -s http://localhost:8001/api/v1/datos/cobertura | python3 -m json.tool   # 100 %
```

O desde el tablero: **Reporte de HC → Estado de la plataforma → Normalizar sede N**.

### Reenviar un mensaje: no se duplica

```bash
curl -X POST --data-binary @ejemplos/01_adt_a01_valido_sede2.hl7 http://localhost:8000/hsb/hl7
curl -X POST --data-binary @ejemplos/01_adt_a01_valido_sede2.hl7 http://localhost:8000/hsb/hl7
#   la segunda responde "duplicado"
curl -s "http://localhost:8080/fhir/Patient?identifier=1007" | grep -o '"total":[0-9]*'
#   "total":1
```

### Apagar una sede: la vista sigue respondiendo

```bash
docker compose stop pg_nodo2

curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8001/api/v1/historia/1001 \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print("parcial:", d["parcial"], "| disponibles:", d["sedes_disponibles"])'
#   parcial: True | disponibles: [1, 3]

docker compose start pg_nodo2   # el bus entrega solo lo que quedó pendiente
```

### Reintentos y cola de mensajes muertos

```bash
docker compose stop hapi-fhir
curl -X POST --data-binary @ejemplos/06_oru_r01_reintento_sede1.hl7 http://localhost:8000/hsb/hl7
#   "resultado": "reintentando"
sleep 20
curl -s http://localhost:8000/hsb/muertos | python3 -m json.tool   # pasó a "muerto"
docker compose start hapi-fhir
curl -X POST -H "Authorization: Bearer $TOKEN" \
     http://localhost:8001/api/v1/bus/mensajes/<id>/reencolar       # vuelve y se entrega
```

### Alterar la auditoría: el verificador lo detecta

```bash
docker compose exec app python scripts/verificar_auditoria.py   # ÍNTEGRA  (salida 0)
./scripts/alterar_auditoria_demo.sh                              # cambia una fila
docker compose exec app python scripts/verificar_auditoria.py   # ALTERADA (salida 1)
```

También funciona con borrado: `./scripts/alterar_auditoria_demo.sh 5 --borrar`.

### Acceso permitido y denegado

```bash
TP=$(curl -s -X POST http://localhost:8001/auth/login -H 'Content-Type: application/json' \
      -d '{"usuario":"paciente1007","password":"paciente123"}' \
      | python3 -c 'import json,sys;print(json.load(sys.stdin)["access_token"])')

curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $TP" \
     http://localhost:8001/api/v1/paciente/mi-historia    # 200
curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $TP" \
     http://localhost:8001/api/v1/historia/1001           # 403 + evento de auditoría
```

### Transacción atómica y plan de la consulta distribuida

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
     "http://localhost:8001/api/v1/datos/prueba-acid?sede=1" | python3 -m json.tool
curl -s -H "Authorization: Bearer $TOKEN" \
     "http://localhost:8001/api/v1/datos/explain?documento=1001" | python3 -m json.tool
```

---

## La demostración completa

```bash
./scripts/demo.sh
```

Ejecuta el guion de la Fase 5 paso a paso, esperando un Enter entre pasos
para poder explicar. Con `AUTO=1 ./scripts/demo.sh` corre de principio a fin
sin detenerse. El guion narrado está en [docs/05_guion_demo.md](docs/05_guion_demo.md).

---

## Pruebas

```bash
docker compose exec app pytest tests -v                       # las 96
docker compose exec app pytest tests -v -m "not integracion"  # solo unitarias
```

| Archivo | Casos | Qué cubre |
| --- | --- | --- |
| `test_normalizador.py` | 13 | Normalizador a FHIR, con dos casos inválidos |
| `test_lectores_y_validador.py` | 16 | HL7 v2, CSV y el contrato de `ejemplos/LEEME.md` |
| `test_terminologia_y_auditoria.py` | 23 | CIE-10, LOINC, `ConceptMap` y cadena de hash |
| `test_integracion_hsb.py` | 10 | Bus de extremo a extremo, idempotencia, `$validate` |
| `test_integracion_api.py` | 34 | Permisos por rol, consulta unificada, reporte, ACID |

---

## Observabilidad

| Servicio | Salud | Métricas |
| --- | --- | --- |
| API | http://localhost:8001/health | http://localhost:8001/metrics |
| Bus | http://localhost:8000/health | http://localhost:8000/metrics |

`/health` reporta el estado de cada dependencia (las tres sedes, el almacén
central, HAPI y el otro servicio) y distingue `ok`, `degradado` y `caido`.
`/metrics` sale en formato de texto de Prometheus; hay `/metrics.json` para
el tablero.

---

## Configuración

Todo funciona sin configurar nada. Para cambiar algo:

```bash
cp .env.example .env     # y editarlo; .env no se versiona
```

| Variable | Por defecto | Para qué |
| --- | --- | --- |
| `JWT_SECRET` | `dev-secret-cambieme` | Firma de los tokens. **Cámbiela.** `/health` avisa si sigue el valor por defecto |
| `PWD_PACIENTE`, `PWD_ADMISION`, `PWD_MEDICO`, `PWD_AUDITOR` | ver arriba | Claves de los usuarios de prueba |
| `HSB_MAX_INTENTOS` | `4` | Intentos antes de la cola de muertos |
| `HSB_ESPERA_BASE_S` | `1` | Base del retroceso exponencial (1, 2, 4, 8 s) |
| `HSB_HL7_EXIGE_CIE10` | `true` | En HL7 el diagnóstico debe venir en CIE-10 ([por qué](docs/03_decisiones_arquitectura.md)) |

---

## Documentación

| Documento | Qué contiene |
| --- | --- |
| [docs/01_informe.md](docs/01_informe.md) | Informe completo con la estructura de la plantilla v7 |
| [docs/02_mapeo_campos.md](docs/02_mapeo_campos.md) | 26 campos: origen → tabla → recurso FHIR |
| [docs/03_decisiones_arquitectura.md](docs/03_decisiones_arquitectura.md) | Cada componente frente a su requisito y a sus alternativas; CAP |
| [docs/04_matriz_requisitos.md](docs/04_matriz_requisitos.md) | RF1–RF6 y los RNF con el comando que los verifica |
| [docs/05_guion_demo.md](docs/05_guion_demo.md) | Guion de la sustentación de 15 minutos |
| [docs/06_bitacora.md](docs/06_bitacora.md) | Trabajo por fase y declaración de uso de IA |
| [docs/07_resultados_medidos.md](docs/07_resultados_medidos.md) | Latencia, mensajes por minuto, fallidos y cobertura |
| [docs/uml/](docs/uml/) | Los 4 diagramas UML y el de arquitectura, en SVG y PlantUML |

---


## Resolución de problemas

| Síntoma | Causa y salida |
| --- | --- |
| `Conflict. The container name ... is already in use` | Hay contenedores de otro laboratorio con el mismo nombre: `docker ps -a` y bórrelos, o cambie `container_name` en `docker-compose.yml` |
| El bus responde 503 «almacén central no disponible» | `pg_central` todavía arranca: `docker compose ps` y espere a que esté `healthy` |
| `/health` dice `hapi_fhir: disponible false` | HAPI tarda ~1 min. `./scripts/esperar_servicios.sh` |
| Las vistas redirigen siempre a `/login` | El token expiró (8 h por defecto). Vuelva a entrar |
| Un mensaje queda en `reintentando` | Alguna dependencia está caída. `docker compose ps` y `curl localhost:8000/health` |
| El puerto 8080 u 8001 está ocupado | Otro proyecto lo está usando: `docker ps` y apáguelo, o cambie el puerto en el compose |
| Los datos no son los esperados | `docker compose down -v && docker compose up -d` recarga los datos sintéticos |

---

Datos 100 % sintéticos. Ningún dato real de pacientes entra al repositorio ni
a la demostración.
