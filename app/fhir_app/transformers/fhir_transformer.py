"""
Compatibilidad: el transformador vive ahora en `fhir/transformador.py`, dentro
de la capa FHIR que exige la estructura del parcial (docs/, infra/, hsb/,
fhir/, db/, app/, tests/). Este módulo re-exporta la clase para que el código
existente siga funcionando.
"""

from fhir.transformador import FHIRTransformer  # noqa: F401

__all__ = ["FHIRTransformer"]
