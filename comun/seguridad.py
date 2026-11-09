"""
comun/seguridad.py — Autenticación por token JWT y autorización por rol (RF5).

La guía permite Keycloak (OAuth2/OIDC) o, como mínimo, un token JWT firmado.
Aquí se implementa el JWT firmado (HS256) con cuatro roles y una matriz de
permisos explícita; en `infra/keycloak/` queda el realm y un override de
compose para quien quiera demostrar OIDC completo.

Reglas:
  * El secreto NUNCA va en el repositorio: se lee de `JWT_SECRET` (.env).
  * Los permisos se validan en la API, no solo en la pantalla.
  * Un acceso denegado responde 403 y deja un evento en la auditoría.
"""

import hashlib
import hmac
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import jwt

JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-cambieme")
JWT_ALG = "HS256"
JWT_HORAS = int(os.getenv("JWT_HORAS", "8"))
SECRETO_POR_DEFECTO = JWT_SECRET == "dev-secret-cambieme"

ROL_PACIENTE = "paciente"
ROL_ADMISIONISTA = "admisionista"
ROL_MEDICO = "medico"
ROL_AUDITOR = "auditor"
ROLES = (ROL_PACIENTE, ROL_ADMISIONISTA, ROL_MEDICO, ROL_AUDITOR)

# ─────────────────────────────────────────────────────────────────────────────
# Matriz de permisos (Fase 4, Paso 1 de la guía)
#
# Acción                        Paciente  Admisionista  Médico  Auditor
# Ver su propia historia           Sí          No         No       No
# Ver la historia de otro          No          No         Sí       Sí (reporte)
# Abrir una atención               No          Sí         No       No
# Registrar diagnóstico/egreso     No          No         Sí       No
# Ver el estado de la plataforma   No          No         Sí       Sí
# Apagar o encender un nodo        No          No         No       Sí
# ─────────────────────────────────────────────────────────────────────────────
PERMISOS: Dict[str, List[str]] = {
    ROL_PACIENTE: [
        "historia:propia",
        "reporte:propio",
        "auditoria:propia",
        "bundle:propio",
    ],
    ROL_ADMISIONISTA: [
        "paciente:buscar",
        "paciente:registrar",
        "atencion:abrir",
        "bus:estado",
        "bus:enviar",   # enviar los mensajes de su sede al bus
        "bus:operar",   # reencolar un mensaje muerto y lanzar la normalización
    ],
    ROL_MEDICO: [
        "paciente:buscar",
        "historia:otros",
        "diagnostico:ver",
        "clinico:escribir",
        "reporte:generar",
        "plataforma:estado",
        "bundle:otros",
    ],
    ROL_AUDITOR: [
        "paciente:buscar",
        "historia:otros",
        "diagnostico:ver",
        "reporte:generar",
        "plataforma:estado",
        "auditoria:leer",
        "nodo:controlar",
        "bus:estado",
        "bus:operar",   # opera la plataforma, pero no envía contenido clínico
        "bundle:otros",
    ],
}

# Usuarios de prueba. Las claves se pueden sobreescribir por variables de
# entorno (.env) y están documentadas en el README como datos sintéticos.
USUARIOS: Dict[str, Dict[str, Any]] = {
    "paciente1007": {
        "password": os.getenv("PWD_PACIENTE", "paciente123"),
        "rol": ROL_PACIENTE,
        "nombre": "Andrea Rojas",
        "documento": 1007,
        "sede_id": 2,
    },
    "admision2": {
        "password": os.getenv("PWD_ADMISION", "admision123"),
        "rol": ROL_ADMISIONISTA,
        "nombre": "Luisa Pérez (admisión Cartagena)",
        "documento": None,
        "sede_id": 2,
    },
    "medico1": {
        "password": os.getenv("PWD_MEDICO", "medico123"),
        "rol": ROL_MEDICO,
        "nombre": "Laura Vega",
        "documento": None,
        "sede_id": 1,
        "codigo_profesional": "MED-01",
    },
    "auditor1": {
        "password": os.getenv("PWD_AUDITOR", "auditor123"),
        "rol": ROL_AUDITOR,
        "nombre": "Mateo Ruiz (auditoría)",
        "documento": None,
        "sede_id": None,
    },
}


def tiene_permiso(rol: str, permiso: str) -> bool:
    return permiso in PERMISOS.get(rol, [])


def permisos_de(rol: str) -> List[str]:
    return list(PERMISOS.get(rol, []))


def autenticar(usuario: str, password: str) -> Optional[Dict[str, Any]]:
    """Comprueba usuario y clave en tiempo constante. None si no coincide."""
    registro = USUARIOS.get(usuario)
    if not registro:
        return None
    if not hmac.compare_digest(str(registro["password"]), str(password)):
        return None
    return {**registro, "usuario": usuario}


def emitir_token(usuario: str, registro: Dict[str, Any]) -> Dict[str, Any]:
    ahora = datetime.now(timezone.utc)
    expira = ahora + timedelta(hours=JWT_HORAS)
    claims = {
        "sub": usuario,
        "nombre": registro["nombre"],
        "rol": registro["rol"],
        "documento": registro.get("documento"),
        "sede_id": registro.get("sede_id"),
        "codigo_profesional": registro.get("codigo_profesional"),
        "permisos": permisos_de(registro["rol"]),
        "iat": int(ahora.timestamp()),
        "exp": int(expira.timestamp()),
        "jti": str(uuid.uuid4()),
    }
    token = jwt.encode(claims, JWT_SECRET, algorithm=JWT_ALG)
    return {
        "access_token": token if isinstance(token, str) else token.decode("utf-8"),
        "token_type": "Bearer",
        "expira": expira.isoformat(),
        "rol": registro["rol"],
        "nombre": registro["nombre"],
        "documento": registro.get("documento"),
        "sede_id": registro.get("sede_id"),
        "permisos": claims["permisos"],
    }


def verificar_token(token: str) -> Dict[str, Any]:
    """Decodifica y valida el token. Lanza jwt.PyJWTError si no es válido."""
    if token and token.lower().startswith("bearer "):
        token = token[7:]
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])


def token_de_servicio(nombre: str = "hsb") -> str:
    """Token técnico para que el HSB llame a la API sin usuario humano."""
    ahora = datetime.now(timezone.utc)
    claims = {
        "sub": f"svc:{nombre}",
        "nombre": f"Servicio {nombre}",
        "rol": ROL_AUDITOR,
        "permisos": permisos_de(ROL_AUDITOR),
        "iat": int(ahora.timestamp()),
        "exp": int((ahora + timedelta(hours=JWT_HORAS)).timestamp()),
        "jti": str(uuid.uuid4()),
    }
    token = jwt.encode(claims, JWT_SECRET, algorithm=JWT_ALG)
    return token if isinstance(token, str) else token.decode("utf-8")


def huella_secreto() -> str:
    """Huella del secreto para diagnóstico, sin revelarlo."""
    return hashlib.sha256(JWT_SECRET.encode()).hexdigest()[:12]
