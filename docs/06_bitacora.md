# Bitácora del proyecto

Anexo exigido por el enunciado: contribución de cada integrante por commits y
declaración del uso de asistentes de IA y de código abierto.

> **Esto lo completa el equipo.** Las dos tablas de reparto están en blanco a
> propósito: nadie más puede decir quién hizo qué. La regla del parcial es que
> cada integrante debe poder **explicar y modificar en vivo** cualquier parte
> que entregue, así que el reparto debe reflejar lo que de verdad pasó.

---

## 1. Integrantes

| Integrante | Rol principal | Correo | Usuario de Git |
| --- | --- | --- | --- |
| *(completar)* | *(p. ej. bus y capa FHIR)* | | |
| *(completar)* | *(p. ej. datos, seguridad y vistas)* | | |

## 2. Reparto por fase

| Fase | Qué se hizo | Responsable | Commits |
| --- | --- | --- | --- |
| 1. Análisis, UML y diseño | Diagramas, mapeo de campos, estructura del repositorio | | |
| 2. Datos distribuidos y FHIR | Esquemas por sede, datos sintéticos, normalizador | | |
| 3. HSB / middleware | Lectores HL7 y CSV, validador, cola, entrega, métricas | | |
| 4. Seguridad y resiliencia | JWT y roles, auditoría encadenada, degradación, observabilidad | | |
| 5. Prototipo e informe | Las cuatro vistas, pruebas, informe y demostración | | |

### Cómo sacar los commits de cada integrante

```bash
# Resumen por autor
git shortlog -sne

# Commits de un integrante, con fecha y archivos tocados
git log --author="NOMBRE" --pretty=format:"%h %ad %s" --date=short --stat

# Líneas añadidas y borradas por autor
git log --author="NOMBRE" --pretty=tformat: --numstat \
  | awk '{a+=$1; b+=$2} END {print "añadidas:", a, "borradas:", b}'
```

El enunciado pide que el repositorio muestre **commits de todos los
integrantes a lo largo de las cinco fases**, no un único commit final. Si al
revisar `git shortlog -sne` el reparto está desbalanceado, conviene arreglarlo
antes de entregar: que cada quien haga suyos los archivos que va a sustentar.

---

## 3. Declaración de uso de asistentes de IA

El enunciado permite usar asistentes de IA si se declaran, y exige que el
integrante pueda explicar y modificar en vivo lo que entregue.

### Qué se hizo con asistencia de IA

Se usó **Claude (Anthropic)** como asistente de programación en una sesión de
trabajo sobre el repositorio, con estas tareas:

| Tarea | Resultado |
| --- | --- |
| Auditar el proyecto heredado contra el enunciado y las cinco guías por fase | Lista de lo que faltaba y de lo que no concordaba |
| Reestructurar el repositorio a la estructura exigida (`docs/`, `infra/`, `hsb/`, `fhir/`, `db/`, `app/`, `tests/`, `ejemplos/`) | Movimiento de archivos con `git mv`, conservando el historial |
| Escribir el bus (lectores HL7 v2 y CSV, validador, cola con reintentos, entrega) | `hsb/` |
| Escribir el normalizador a FHIR R4 y el cliente HAPI | `fhir/` |
| Escribir la seguridad por rol, la auditoría encadenada y la consulta unificada | `comun/`, `app/auth.py`, `app/consulta_unificada.py` |
| Escribir las vistas Paciente y Reporte de HC, y añadir sesión a las heredadas | `app/templates/` |
| Escribir las 96 pruebas y corregir los cuatro defectos que encontraron | `tests/` |
| Escribir esta documentación y generar los diagramas | `docs/` |

### Qué NO hizo la IA

* **No se inventaron referencias bibliográficas.** Las de la sección 13 del
  informe son fuentes primarias y normativa colombiana, y están marcadas con
  un aviso explícito de que el equipo debe abrirlas y verificarlas antes de
  entregar. Las fuentes académicas de Latinoamérica quedaron en blanco a
  propósito: las busca y las lee el equipo.
* **No se usaron datos reales de pacientes.** Todo es sintético.
* **No se inventaron resultados.** Las cifras de
  [07_resultados_medidos.md](07_resultados_medidos.md) salen de ejecutar el
  sistema; el comando que las produce está junto a cada una.

### Qué tiene que hacer el equipo antes de sustentar

La nota de sustentación es individual y se evalúa que cada integrante
**explique y modifique en vivo** lo que entrega. Recorrido mínimo recomendado:

1. Leer de punta a punta [hsb/cola.py](../hsb/cola.py) y
   [hsb/entrega.py](../hsb/entrega.py): son el corazón del parcial y donde
   están la idempotencia y los reintentos.
2. Leer [fhir/normalizador.py](../fhir/normalizador.py) y entender **por qué**
   los identificadores son deterministas.
3. Leer [comun/auditoria.py](../comun/auditoria.py) y poder explicar la
   fórmula del hash y qué detecta el verificador.
4. Leer [comun/seguridad.py](../comun/seguridad.py): es la tabla que el
   docente puede pedir modificar en vivo.
5. Correr las pruebas y romper una a propósito, para ver qué dice.
6. Ensayar el guion de [05_guion_demo.md](05_guion_demo.md) completo, con
   cronómetro.

## 4. Código abierto utilizado

| Componente | Licencia | Para qué |
| --- | --- | --- |
| FastAPI | MIT | API y bus |
| Uvicorn | BSD-3 | Servidor ASGI |
| Pydantic | MIT | Validación de modelos |
| psycopg2-binary | LGPL con excepción | Cliente de PostgreSQL |
| httpx | BSD-3 | Cliente HTTP |
| PyJWT | MIT | Token firmado |
| pytest | MIT | Pruebas |
| PostgreSQL 15 | PostgreSQL License | Bases de datos |
| HAPI FHIR (`hapiproject/hapi`) | Apache 2.0 | Servidor FHIR R4 |
| Inter (Google Fonts) | SIL OFL 1.1 | Tipografía de las vistas |
| Phosphor Icons | MIT | Iconos del tablero heredado |

Punto de partida: el repositorio de referencia
`historia-clinica-distribuida`, indicado por el enunciado, del que se
conservan el esquema clínico, el tablero de nodos y los módulos de admisión y
de médico.

## 5. Registro de correcciones

El enunciado pide anotar aquí la corrección de cualquier fase que no haya
pasado su criterio.

| Fecha | Fase | Qué no pasó | Cómo se corrigió |
| --- | --- | --- | --- |
| *(completar si el docente devuelve alguna fase)* | | | |

### Correcciones internas durante el desarrollo

Defectos encontrados por las propias pruebas y corregidos antes de entregar:

| # | Defecto | Corrección |
| --- | --- | --- |
| 1 | Carrera entre la entrega en línea y el trabajador de la cola: ambos procesaban el mismo mensaje y el segundo lo degradaba a `rechazado` | El mensaje nace reservado y un estado terminal ya no se degrada (`hsb/cola.py`) |
| 2 | Un 409 de HAPI (conflicto de versión) se trataba como error definitivo | Se clasifica como transitorio y se reintenta (`fhir/cliente_hapi.py`) |
| 3 | Los Bundle no pasaban `$validate`: faltaba `fullUrl` absoluto | Se añadió con una base canónica; `urn:uuid:` no servía porque exige UUID reales (`fhir/normalizador.py`) |
| 4 | El bus sobreescribía datos del legado (un `ORU` degradaba el nombre y movía la fecha del encuentro) | El bus completa lo que falta, no pisa lo que ya está (`hsb/entrega.py`) |
| 5 | Índices únicos parciales incompatibles con `ON CONFLICT`, que rompían la carga inicial | Índices no parciales; PostgreSQL ya trata los NULL como distintos (`db/sede/01_esquema.sql`) |
| 6 | El contenedor de la API no arrancaba por una incompatibilidad de versiones en el extra de MCP | MCP pasó a ser opcional: si falla, la API arranca igual (`app/main.py`) |
