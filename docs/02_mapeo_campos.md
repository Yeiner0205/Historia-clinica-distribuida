# Mapeo de campos: origen → tabla → recurso FHIR

Entregable de la Fase 1, paso 7 (mínimo 15 filas). Aquí hay **26**.

La columna «Origen» indica el campo del sistema legado: el segmento y la
posición en HL7 v2, o el nombre de la columna en el CSV. La columna «Dónde
queda» es la tabla del nodo de la sede. La columna «Recurso FHIR» es el
elemento del recurso R4 que produce el normalizador
([fhir/normalizador.py](../fhir/normalizador.py)).

## Identificación del paciente → `Patient`

| # | Origen HL7 / CSV | Dónde queda | Campo | Recurso FHIR |
| --- | --- | --- | --- | --- |
| 1 | `PID-3.1` / `documento` | `usuario` | `documento_id` | `Patient.identifier[0].value` (system `http://www.minsalud.gov.co/identificacion`) |
| 2 | tipo de documento (por defecto CC) | `usuario` | `tipo_documento` | `Patient.identifier[0].type.coding.code` (tabla v2-0203, `NI`) |
| 3 | `PID-5.1` (apellido) | `usuario` | `nombre_completo` | `Patient.name[0].family` |
| 4 | `PID-5.2` (nombre) / `nombre` | `usuario` | `nombre_completo` | `Patient.name[0].given[0]` |
| 5 | `PID-7` / `nacimiento` | `usuario` | `fecha_nacimiento` | `Patient.birthDate` (de `YYYYMMDD` a `YYYY-MM-DD`) |
| 6 | `PID-8` / `sexo` | `usuario` | `sexo` | `Patient.gender` (M→male, F→female, O→other) |
| 7 | `MSH-4` / parámetro `?sede=` | `usuario` | `sede_id` | `Patient.managingOrganization.identifier` (system `urn:hc-distribuida:sede`) |
| 8 | municipio de residencia (legado) | `usuario` | `municipio_residencia` | `Patient.address[0].city` + extensión DIVIPOLA |
| 9 | — (lo asigna el bus) | `usuario` | `fhir_patient_id` | `Patient.id` = `pac-<documento>` (determinista) |

## Atención → `Encounter`

| # | Origen HL7 / CSV | Dónde queda | Campo | Recurso FHIR |
| --- | --- | --- | --- | --- |
| 10 | `PV1-19` (número de visita) | `atencion` | `visita` | `Encounter.identifier[0].value` y `Encounter.id` = `enc-<visita>` |
| 11 | `PV1-44` / `fecha` | `atencion` | `fecha_ingreso` | `Encounter.period.start` |
| 12 | `PV1-2` (clase: E, O, I) | `atencion` | `entorno_atencion` | `Encounter.class` (E→EMER, I→IMP, O→AMB, sistema v3-ActCode) |
| 13 | `triage` (CSV) | `atencion` | `clasificacion_triage` | `Encounter.priority.coding.code` |
| 14 | `PV1-7.1` / `profesional` | `atencion` | `profesional_codigo` | `Encounter.participant[0].individual` → `Practitioner/prof-<código>` |
| 15 | `PV1-7.2` y `PV1-7.3` | `profesional_salud` | `nombre` | `Practitioner.name[0].family` y `.given[0]` |
| 16 | motivo de consulta (legado) | `atencion` | `causa_atencion` | `Encounter.reasonCode[0].text` |
| 17 | fecha de salida (egreso) | `egreso` | `fecha_salida` | `Encounter.period.end` y `Encounter.status = finished` |
| 18 | — (lo asigna el bus) | `atencion` | `fhir_encounter_id` | `Encounter.id` |

## Diagnóstico → `Condition` (CIE-10)

| # | Origen HL7 / CSV | Dónde queda | Campo | Recurso FHIR |
| --- | --- | --- | --- | --- |
| 19 | `DG1-3.1` / `dx_local` | `diagnostico` | `dx_local` | — (se conserva el valor del legado) |
| 20 | `DG1-3.1` traducido por `ref_terminologia` | `diagnostico` | `cie10` | `Condition.code.coding[0].code` (system `http://hl7.org/fhir/sid/icd-10`) |
| 21 | `DG1-3.2` / descripción de la tabla | `diagnostico` | `descripcion_cie10` | `Condition.code.coding[0].display` |
| 22 | `DG1-5` (fecha del diagnóstico) | `diagnostico` | `created_at` | `Condition.recordedDate` |
| 23 | — (lo asigna el bus) | `diagnostico` | `fhir_condition_id` | `Condition.id` = `cond-<visita>-<CIE10 sin punto>` |

## Laboratorio → `Observation` (LOINC)

| # | Origen HL7 / CSV | Dónde queda | Campo | Recurso FHIR |
| --- | --- | --- | --- | --- |
| 24 | `OBX-3.1` (código) y `OBX-3.2` (nombre) | `observacion` | `loinc`, `descripcion` | `Observation.code.coding[0]` (system `http://loinc.org`) |
| 25 | `OBX-5` | `observacion` | `valor` | `Observation.valueQuantity.value` (o `valueString` si no es numérico) |
| 26 | `OBX-6` | `observacion` | `unidad` | `Observation.valueQuantity.unit` y `.code` (UCUM) |

## Trazabilidad del mensaje (no va a FHIR clínico)

| Origen | Dónde queda | Campo | Para qué |
| --- | --- | --- | --- |
| `MSH-10` (id del mensaje) | `mensaje_bus` | `clave_idempotencia` | Reenviar no duplica (restricción `UNIQUE`) |
| SHA-256 de la fila del CSV | `mensaje_bus` | `clave_idempotencia` | Lo mismo, cuando el origen no trae id |
| `MSH-9` (tipo) | `mensaje_bus` | `tipo` | Decide el flujo (ADT o ORU) |
| `MSH-3` (aplicación) | `mensaje_bus` | `origen` | Actor del evento de auditoría |
| quién, cuándo, qué, resultado | `evento_auditoria` | `actor`, `ts`, `accion`, `resultado` | `AuditEvent` de FHIR R4 |

## Notas de mapeo que conviene poder explicar

1. **`CC` se mapea a `NI`, no a `DL`.** La cédula colombiana es un
   identificador nacional de persona (`NI` en la tabla HL7 v2-0203), no una
   licencia de conducción. La primera versión del transformador usaba `DL`;
   quedó corregido en [fhir/transformador.py](../fhir/transformador.py).
2. **El nombre se parte distinto según el origen.** HL7 trae
   `Apellido^Nombre` en `PID-5`; el CSV trae el nombre completo en una sola
   columna y se parte por el primer espacio. Por eso el bus **completa** los
   datos de identificación que falten pero no sobreescribe los que la sede ya
   tiene: un HL7 con dos componentes no debe degradar un nombre completo del
   legado.
3. **En HL7 el diagnóstico debe venir en CIE-10.** Si `DG1-3` trae texto
   libre, el mensaje se rechaza. En el CSV legado sí se admite texto libre y
   se traduce con `ref_terminologia`. La justificación está en
   [03_decisiones_arquitectura.md](03_decisiones_arquitectura.md).
4. **Los identificadores FHIR son deterministas** (`pac-1007`,
   `enc-V-S2-0101`, `cond-V-S2-0101-J459`). Es lo que permite usar `PUT` en el
   Bundle `transaction` y que reenviar un mensaje actualice en vez de crear.
