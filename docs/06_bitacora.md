# Bitácora del proyecto

Anexo exigido por el enunciado: contribución por commits y declaración del uso
de asistentes de IA y de código abierto.

---

## 1. Autor

| Autor | Rol | Correo | Usuario de Git |
| --- | --- | --- | --- |
| **Yeiner Julian Perez Vitola** | Desarrollo completo de la plataforma: capa de datos, bus, FHIR, seguridad, vistas, pruebas y documentación | grencitoop7@gmail.com | `Yeiner Julian Perez Vitola` |

**Trabajo individual.** El enunciado contempla equipos de dos estudiantes;
este parcial se desarrolló y se sustenta de forma individual. No hay reparto
que declarar: todas las partes son responsabilidad del autor, que debe poder
explicarlas y modificarlas en vivo.

## 2. Trabajo por fase

| Fase | Qué se hizo | Dónde quedó |
| --- | --- | --- |
| 1. Análisis, UML y diseño | Auditoría del repositorio de referencia frente al enunciado, estructura exigida (`docs/`, `infra/`, `hsb/`, `fhir/`, `db/`, `app/`, `tests/`, `ejemplos/`), los 4 diagramas UML más el de arquitectura, mapeo de 26 campos y tabla de decisiones | `docs/`, `docs/uml/` |
| 2. Datos distribuidos y FHIR | Un nodo PostgreSQL por sede con su esquema y datos sintéticos (cobertura FHIR en 0 %), almacén central, normalizador a FHIR R4, cliente HAPI y terminologías | `db/`, `fhir/`, `comun/` |
| 3. HSB / middleware | Lectores HL7 v2 y CSV legado, validador con motivos, cola persistente con idempotencia, reintentos con retroceso exponencial, cola de mensajes muertos, entrega a HAPI y a la sede, y métricas | `hsb/` |
| 4. Seguridad y resiliencia | JWT con 4 roles y matriz de permisos verificada en la API, auditoría encadenada por hash con verificador, consulta unificada con degradación, `/health` y `/metrics` | `comun/seguridad.py`, `comun/auditoria.py`, `app/auth.py`, `app/consulta_unificada.py` |
| 5. Prototipo e informe | Vistas Paciente y Reporte de HC, sesión y permisos en las vistas heredadas, Reporte con cobertura y sello, 96 pruebas, informe, guion de demostración y etiqueta `v1.0` | `app/templates/`, `app/reporte.py`, `tests/`, `docs/` |

### Cómo mostrar el historial en la sustentación

```bash
# Resumen de commits
git shortlog -sne

# Los commits por fase, con fecha
git log --pretty=format:"%h %ad %s" --date=short

# Qué cambió en un commit concreto
git show --stat <hash>

# La etiqueta de entrega
git tag -n20 v1.0
```

El historial está organizado por fases, no en un único commit final:

| Commit | Qué entrega |
| --- | --- |
| `d63e7d2` | Estado base: el repositorio de referencia tal como se recibió |
| `8ac50a2` | Fases 1–3: estructura, capa FHIR y bus de integración |
| `99d154e` | Fases 4–5: seguridad, auditoría, consulta unificada, reporte y las cuatro vistas |
| `036c007` | Las 96 pruebas y los 4 defectos que destaparon |
| `83216f6` | Documentación, diagramas, guion de demostración e infraestructura opcional |
| `0a2b2cd` | Resultados medidos, colección de Postman y limpieza |
| `1d8180e` | Coherencia de las vistas heredadas con las reglas de la plataforma |

---

## 3. Declaración de uso de asistentes de IA

El enunciado permite usar asistentes de IA si se declaran, y exige poder
explicar y modificar en vivo lo que se entrega.

### Qué se hizo con asistencia de IA

Se usó **Claude (Anthropic)** como asistente de programación en una sesión de
trabajo sobre el repositorio, con estas tareas:

| Tarea | Resultado |
| --- | --- |
| Auditar el proyecto heredado contra el enunciado y las cinco guías por fase | Lista de lo que faltaba y de lo que no concordaba |
| Reestructurar el repositorio a la estructura exigida | Movimiento de archivos con `git mv`, conservando el historial |
| Escribir el bus (lectores HL7 v2 y CSV, validador, cola con reintentos, entrega) | `hsb/` |
| Escribir el normalizador a FHIR R4 y el cliente HAPI | `fhir/` |
| Escribir la seguridad por rol, la auditoría encadenada y la consulta unificada | `comun/`, `app/auth.py`, `app/consulta_unificada.py` |
| Escribir las vistas Paciente y Reporte de HC, y añadir sesión a las heredadas | `app/templates/` |
| Escribir las 96 pruebas y corregir los defectos que encontraron | `tests/` |
| Escribir la documentación y generar los diagramas | `docs/` |

### Qué NO hizo la IA

* **No se inventaron referencias bibliográficas.** Las de la sección 13.4 del
  informe son fuentes primarias y normativa colombiana, y llevan un aviso
  explícito de que hay que abrirlas y verificarlas antes de entregar. Las
  fuentes académicas de Latinoamérica quedaron en blanco a propósito.
* **No se usaron datos reales de pacientes.** Todo es sintético.
* **No se inventaron resultados.** Las cifras de
  [07_resultados_medidos.md](07_resultados_medidos.md) salen de ejecutar el
  sistema; el comando que produce cada una está junto a ella.

### Preparación para la sustentación

La nota de sustentación es individual y se evalúa explicar y **modificar en
vivo** cualquier parte entregada. Recorrido mínimo recomendado:

1. Leer de punta a punta [hsb/cola.py](../hsb/cola.py) y
   [hsb/entrega.py](../hsb/entrega.py): son el corazón del parcial y donde
   están la idempotencia y los reintentos.
2. Leer [fhir/normalizador.py](../fhir/normalizador.py) y entender **por qué**
   los identificadores son deterministas.
3. Leer [comun/auditoria.py](../comun/auditoria.py) y poder explicar la
   fórmula del hash y qué detecta el verificador.
4. Leer [comun/seguridad.py](../comun/seguridad.py): es la tabla que el
   docente puede pedir modificar en vivo (quitar un permiso a un rol,
   `docker compose restart app` y mostrar el 403).
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
| 7 | Las vistas de admisión y registro exigían documentos de 6 a 15 dígitos, contra la regla de la plataforma (4 a 15) y los datos del contrato | Validación alineada con `hsb/validador.py` |
| 8 | La vista médica mostraba «Nodo 1» calculado por rango de documento, que dejó de ser la regla | Ahora muestra en qué sedes tiene registros el paciente |
