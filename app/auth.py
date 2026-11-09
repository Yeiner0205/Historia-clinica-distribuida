"""
app/auth.py — Dependencias de autenticación y autorización para la API.

Los permisos se comprueban **en la API**, no en la pantalla: cambiar el HTML o
llamar al endpoint con curl no da acceso. Todo rechazo responde 403 (o 401 si
no hay token) y deja un evento en la cadena de auditoría.
"""

from typing import Any, Callable, Dict, Optional

import jwt
from fastapi import Header, HTTPException

from comun import auditoria, seguridad


def claims_opcionales(authorization: Optional[str]) -> Optional[Dict[str, Any]]:
    """Decodifica el token si viene y es válido; si no, None (sin excepción)."""
    if not authorization:
        return None
    try:
        return seguridad.verificar_token(authorization)
    except jwt.PyJWTError:
        return None


def _claims_o_401(authorization: Optional[str], recurso: str) -> Dict[str, Any]:
    if not authorization:
        auditoria.registrar("anonimo", "", "acceso_denegado", recurso, "denegado",
                            {"motivo": "sin token"})
        raise HTTPException(
            status_code=401,
            detail="Falta el token. Inicie sesión en POST /auth/login (usuarios de prueba en el README).",
        )
    try:
        return seguridad.verificar_token(authorization)
    except jwt.ExpiredSignatureError as exc:
        auditoria.registrar("anonimo", "", "acceso_denegado", recurso, "denegado",
                            {"motivo": "token expirado"})
        raise HTTPException(status_code=401, detail="El token expiró. Vuelva a iniciar sesión.") from exc
    except jwt.PyJWTError as exc:
        auditoria.registrar("anonimo", "", "acceso_denegado", recurso, "denegado",
                            {"motivo": f"token inválido: {exc}"})
        raise HTTPException(status_code=401, detail=f"Token inválido: {exc}") from exc


def requiere(permiso: str) -> Callable:
    """
    Dependencia de FastAPI que exige un permiso concreto.

        @app.get("/api/v1/...")
        def endpoint(claims = Depends(auth.requiere("historia:otros"))): ...
    """

    def dependencia(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
        claims = _claims_o_401(authorization, f"permiso:{permiso}")
        rol = claims.get("rol", "")
        if not seguridad.tiene_permiso(rol, permiso):
            auditoria.registrar(
                claims.get("sub", "?"), rol, "acceso_denegado", f"permiso:{permiso}", "denegado",
                {"permiso_requerido": permiso, "permisos_del_rol": seguridad.permisos_de(rol)},
            )
            raise HTTPException(
                status_code=403,
                detail=f"El rol '{rol}' no tiene el permiso '{permiso}'.",
            )
        return claims

    return dependencia


def requiere_sesion(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    """Solo exige una sesión válida, sin permiso concreto."""
    return _claims_o_401(authorization, "sesion")


def verificar_acceso_documento(claims: Dict[str, Any], documento_id: int, accion: str = "leer_historia") -> None:
    """
    Un paciente solo puede ver su propia historia. Si cambia el documento en
    la URL, se detiene **en la API** y queda registrado en la auditoría
    (pregunta de autoevaluación de la Fase 4).
    """
    rol = claims.get("rol", "")
    if rol != seguridad.ROL_PACIENTE:
        return
    propio = claims.get("documento")
    if propio is None or int(propio) != int(documento_id):
        auditoria.registrar(
            claims.get("sub", "?"), rol, "acceso_denegado", f"paciente:{documento_id}", "denegado",
            {"motivo": "un paciente intentó ver la historia de otro",
             "documento_propio": propio, "documento_solicitado": documento_id, "accion": accion},
        )
        raise HTTPException(
            status_code=403,
            detail="Como paciente solo puede consultar su propia historia clínica.",
        )


def registrar_acceso(claims: Dict[str, Any], accion: str, recurso: str,
                     resultado: str = "ok", detalle: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Atajo para dejar el evento de auditoría de un acceso permitido."""
    return auditoria.registrar(
        actor=claims.get("sub", "anonimo"),
        rol=claims.get("rol", ""),
        accion=accion,
        recurso=recurso,
        resultado=resultado,
        detalle=detalle or {},
    )
