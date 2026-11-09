"""
fhir/cliente_hapi.py — Cliente del servidor HAPI FHIR R4.

Ofrece versión sincrónica (la usa el trabajador de la cola del HSB) y
asincrónica (la usa la API con FastAPI). Las excepciones se envuelven en
`ErrorHapi` para que la cola pueda distinguir «HAPI no responde» (se reintenta)
de «el recurso es inválido» (se rechaza).
"""

import json
from typing import Any, Dict, List, Optional

import httpx

from comun import sedes

CABECERAS = {"Content-Type": "application/fhir+json", "Accept": "application/fhir+json"}
TIMEOUT = 30.0


class ErrorHapi(Exception):
    def __init__(self, mensaje: str, estado: Optional[int] = None, cuerpo: Any = None, transitorio: bool = True):
        super().__init__(mensaje)
        self.estado = estado
        self.cuerpo = cuerpo
        # `transitorio=True` → merece reintento (HAPI caído, 5xx, timeout).
        # `transitorio=False` → el mensaje no va a mejorar reintentando (4xx).
        self.transitorio = transitorio


def base_url() -> str:
    return sedes.HAPI_BASE_URL.rstrip("/")


def _procesar(resp: httpx.Response) -> Dict[str, Any]:
    if resp.status_code >= 500:
        raise ErrorHapi(f"HAPI respondió {resp.status_code}", resp.status_code, resp.text, transitorio=True)
    if resp.status_code >= 400:
        raise ErrorHapi(f"HAPI rechazó la petición ({resp.status_code})", resp.status_code, resp.text,
                        transitorio=False)
    if not resp.content:
        return {}
    try:
        return resp.json()
    except json.JSONDecodeError:
        return {"raw": resp.text}


# ─────────────────────────────────────────────────────────────────────────────
# Sincrónico
# ─────────────────────────────────────────────────────────────────────────────
def metadata() -> Dict[str, Any]:
    try:
        with httpx.Client(timeout=10.0) as cli:
            return _procesar(cli.get(f"{base_url()}/metadata", headers={"Accept": "application/fhir+json"}))
    except httpx.HTTPError as exc:
        raise ErrorHapi(f"HAPI FHIR no disponible: {exc}", transitorio=True) from exc


def enviar_bundle(bundle: Dict[str, Any]) -> Dict[str, Any]:
    """Ejecuta un Bundle `transaction` contra la raíz del servidor."""
    try:
        with httpx.Client(timeout=TIMEOUT) as cli:
            return _procesar(
                cli.post(f"{base_url()}", content=json.dumps(bundle, ensure_ascii=False), headers=CABECERAS)
            )
    except httpx.HTTPError as exc:
        raise ErrorHapi(f"no se pudo entregar el Bundle a HAPI: {exc}", transitorio=True) from exc


def validar_bundle(bundle: Dict[str, Any]) -> Dict[str, Any]:
    """`Bundle/$validate`. Devuelve el OperationOutcome y los errores hallados."""
    try:
        with httpx.Client(timeout=TIMEOUT) as cli:
            resp = cli.post(
                f"{base_url()}/Bundle/$validate",
                content=json.dumps(bundle, ensure_ascii=False),
                headers=CABECERAS,
            )
    except httpx.HTTPError as exc:
        raise ErrorHapi(f"no se pudo validar contra HAPI: {exc}", transitorio=True) from exc

    cuerpo: Dict[str, Any]
    try:
        cuerpo = resp.json()
    except json.JSONDecodeError:
        cuerpo = {"raw": resp.text}
    errores = [
        f"{i.get('severity')}: {(i.get('diagnostics') or i.get('details', {}).get('text') or '')}"
        for i in cuerpo.get("issue", [])
        if i.get("severity") in ("error", "fatal")
    ]
    return {"valido": not errores, "errores": errores, "operation_outcome": cuerpo}


def buscar_patient(identificador: str) -> Dict[str, Any]:
    try:
        with httpx.Client(timeout=TIMEOUT) as cli:
            return _procesar(
                cli.get(f"{base_url()}/Patient", params={"identifier": identificador}, headers=CABECERAS)
            )
    except httpx.HTTPError as exc:
        raise ErrorHapi(f"no se pudo buscar el paciente: {exc}", transitorio=True) from exc


def leer(tipo: str, recurso_id: str) -> Optional[Dict[str, Any]]:
    try:
        with httpx.Client(timeout=TIMEOUT) as cli:
            resp = cli.get(f"{base_url()}/{tipo}/{recurso_id}", headers=CABECERAS)
            if resp.status_code == 404:
                return None
            return _procesar(resp)
    except httpx.HTTPError as exc:
        raise ErrorHapi(f"no se pudo leer {tipo}/{recurso_id}: {exc}", transitorio=True) from exc


def buscar(tipo: str, params: Dict[str, Any]) -> Dict[str, Any]:
    try:
        with httpx.Client(timeout=TIMEOUT) as cli:
            return _procesar(cli.get(f"{base_url()}/{tipo}", params=params, headers=CABECERAS))
    except httpx.HTTPError as exc:
        raise ErrorHapi(f"no se pudo buscar {tipo}: {exc}", transitorio=True) from exc


def salud() -> Dict[str, Any]:
    """Nunca lanza: resume el estado de HAPI para /health."""
    try:
        meta = metadata()
        return {
            "disponible": True,
            "fhir_version": meta.get("fhirVersion"),
            "software": (meta.get("software") or {}).get("name", "HAPI FHIR"),
        }
    except Exception as exc:  # noqa: BLE001
        return {"disponible": False, "error": str(exc)}


# ─────────────────────────────────────────────────────────────────────────────
# Asincrónico (API)
# ─────────────────────────────────────────────────────────────────────────────
async def a_metadata() -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0) as cli:
        return _procesar(await cli.get(f"{base_url()}/metadata", headers={"Accept": "application/fhir+json"}))


async def a_enviar_bundle(bundle: Dict[str, Any]) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=TIMEOUT) as cli:
        return _procesar(
            await cli.post(f"{base_url()}", content=json.dumps(bundle, ensure_ascii=False), headers=CABECERAS)
        )


async def a_crear(tipo: str, recurso: Dict[str, Any]) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=TIMEOUT) as cli:
        return _procesar(
            await cli.post(f"{base_url()}/{tipo}", content=json.dumps(recurso, ensure_ascii=False), headers=CABECERAS)
        )


async def a_actualizar(tipo: str, recurso_id: str, recurso: Dict[str, Any]) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=TIMEOUT) as cli:
        return _procesar(
            await cli.put(
                f"{base_url()}/{tipo}/{recurso_id}",
                content=json.dumps(recurso, ensure_ascii=False),
                headers=CABECERAS,
            )
        )


async def a_leer(tipo: str, recurso_id: str) -> Optional[Dict[str, Any]]:
    async with httpx.AsyncClient(timeout=TIMEOUT) as cli:
        resp = await cli.get(f"{base_url()}/{tipo}/{recurso_id}", headers=CABECERAS)
        if resp.status_code == 404:
            return None
        return _procesar(resp)


async def a_buscar(tipo: str, params: Dict[str, Any]) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=TIMEOUT) as cli:
        return _procesar(await cli.get(f"{base_url()}/{tipo}", params=params, headers=CABECERAS))


async def a_eliminar(tipo: str, recurso_id: str) -> bool:
    async with httpx.AsyncClient(timeout=TIMEOUT) as cli:
        resp = await cli.delete(f"{base_url()}/{tipo}/{recurso_id}", headers=CABECERAS)
        return resp.status_code < 300


async def a_salud() -> Dict[str, Any]:
    try:
        meta = await a_metadata()
        return {"disponible": True, "fhir_version": meta.get("fhirVersion"), "metadata": meta}
    except Exception as exc:  # noqa: BLE001
        return {"disponible": False, "error": str(exc)}


def recursos_entregados(respuesta_transaccion: Dict[str, Any]) -> List[str]:
    """Extrae las referencias creadas/actualizadas de la respuesta de un transaction."""
    salida = []
    for entrada in respuesta_transaccion.get("entry", []):
        loc = (entrada.get("response") or {}).get("location")
        if loc:
            salida.append(loc.split("/_history")[0])
    return salida
