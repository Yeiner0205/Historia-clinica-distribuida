"""
Health Service Bus (HSB) — bus de integración de salud de la plataforma.

Cadena de procesamiento (Fase 3 de la guía):

    recepción → validación → transformación a FHIR → enrutamiento por sede
              → entrega a HAPI → entrega al nodo de la sede → auditoría

Con cola persistente, reintentos con retroceso exponencial, cola de mensajes
muertos e idempotencia por clave (MSH-10 en HL7, hash del contenido en CSV).
"""

VERSION = "1.0.0"
