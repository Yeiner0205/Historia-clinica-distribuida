"""
Capa FHIR R4 de la plataforma.

  * `terminologia` — mapeo de diagnóstico local a CIE-10 y de prueba a LOINC
    (tabla `ref_terminologia` + ConceptMap).
  * `transformador` — construcción de recursos individuales (Patient, Encounter,
    Condition, Observation, Practitioner).
  * `normalizador` — empaqueta los recursos en Bundle (transaction para ingesta
    idempotente y document para el Reporte de HC).
  * `cliente_hapi` — cliente del servidor HAPI FHIR.

Los recursos se construyen como diccionarios JSON y se validan contra el
servidor HAPI (`Bundle/$validate`), que es el validador de referencia del
estándar. Así no se depende de la versión de una librería de modelos.
"""

SISTEMA_DOCUMENTO = "http://www.minsalud.gov.co/identificacion"
SISTEMA_CIE10 = "http://hl7.org/fhir/sid/icd-10"
SISTEMA_LOINC = "http://loinc.org"
SISTEMA_V2_0203 = "http://terminology.hl7.org/CodeSystem/v2-0203"
SISTEMA_ACT_CODE = "http://terminology.hl7.org/CodeSystem/v3-ActCode"
SISTEMA_SEDE = "urn:hc-distribuida:sede"
SISTEMA_VISITA = "urn:hc-distribuida:visita"
SISTEMA_TRIAGE = "urn:hc-distribuida:triage"
