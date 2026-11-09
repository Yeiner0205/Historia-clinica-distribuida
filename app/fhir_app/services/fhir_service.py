"""
app/fhir_app/services/fhir_service.py — Fachada asincrónica del servidor HAPI
FHIR usada por la API. La comunicación real está en `fhir/cliente_hapi.py`;
aquí se conserva la interfaz que ya usaban las vistas.
"""

import json
from typing import Any, Dict, Optional

from comun import sedes
from fhir import cliente_hapi


def _a_dict(recurso: Any) -> Dict[str, Any]:
    """Acepta un dict, un JSON en texto o un modelo con `.json()`/`.dict()`."""
    if isinstance(recurso, dict):
        return recurso
    if isinstance(recurso, (str, bytes)):
        return json.loads(recurso)
    for metodo in ("model_dump", "dict"):
        if hasattr(recurso, metodo):
            return getattr(recurso, metodo)()
    if hasattr(recurso, "json"):
        return json.loads(recurso.json())
    raise TypeError(f"no sé convertir {type(recurso)} a recurso FHIR")


class FHIRService:
    """Servicio para comunicación con el servidor HAPI FHIR."""

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url or sedes.HAPI_BASE_URL).rstrip("/")

    async def create_patient(self, patient: Any) -> Dict[str, Any]:
        return await cliente_hapi.a_crear("Patient", _a_dict(patient))

    async def get_patient(self, patient_id: str) -> Optional[Dict[str, Any]]:
        return await cliente_hapi.a_leer("Patient", patient_id)

    async def search_patient_by_identifier(self, identifier: str) -> Dict[str, Any]:
        return await cliente_hapi.a_buscar("Patient", {"identifier": identifier})

    async def search_patient_by_name(self, nombre: str) -> Dict[str, Any]:
        return await cliente_hapi.a_buscar("Patient", {"name": nombre})

    async def update_patient(self, patient_id: str, patient: Any) -> Dict[str, Any]:
        return await cliente_hapi.a_actualizar("Patient", patient_id, _a_dict(patient))

    async def delete_patient(self, patient_id: str) -> bool:
        return await cliente_hapi.a_eliminar("Patient", patient_id)

    async def enviar_bundle(self, bundle: Dict[str, Any]) -> Dict[str, Any]:
        return await cliente_hapi.a_enviar_bundle(bundle)

    async def buscar(self, tipo: str, params: Dict[str, Any]) -> Dict[str, Any]:
        return await cliente_hapi.a_buscar(tipo, params)

    async def check_server_health(self) -> Dict[str, Any]:
        return await cliente_hapi.a_metadata()

    async def salud(self) -> Dict[str, Any]:
        return await cliente_hapi.a_salud()
