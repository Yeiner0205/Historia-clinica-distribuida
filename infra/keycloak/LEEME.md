# Keycloak (OAuth2 / OIDC) — opcional

La guía de la Fase 4 admite «Keycloak (OAuth2/OIDC) o, como mínimo, un token
JWT firmado». **La plataforma implementa el JWT firmado**, que es lo que se
califica: cuatro roles con permisos distintos, verificados en la API.

Esta carpeta queda por si el equipo quiere subir de nivel y demostrar OIDC
completo.

## Por qué no se usó Keycloak de entrada

| Razón | Detalle |
| --- | --- |
| Tiempo de arranque | Más de un minuto, encima del minuto de HAPI. El requisito no funcional es que `docker compose up` levante el sistema |
| Punto de fallo en la demostración | Si el realm no importa bien, no se puede iniciar sesión en ninguna de las cuatro vistas |
| Lo que añade no se califica | Federación, consentimiento, MFA y gestión de sesiones son valiosos, pero el parcial evalúa «roles con permisos distintos» |

El razonamiento completo está en
[docs/03_decisiones_arquitectura.md](../../docs/03_decisiones_arquitectura.md).

## Si se quiere activar (sin probar)

```bash
docker compose -f docker-compose.yml \
               -f infra/keycloak/docker-compose.keycloak.yml up -d
```

* Consola: http://localhost:8180 (`admin` / `admin`)
* Realm: `historia-clinica`, con los cuatro roles y los cuatro usuarios de
  prueba ya definidos en `realm-hc.json`.

### Qué habría que cambiar en el código

La verificación del token está en un solo lugar,
[comun/seguridad.py](../../comun/seguridad.py), función `verificar_token`.
Pasar a OIDC es cambiar la validación HS256 por validación RS256 contra el
JWKS del realm:

```python
import jwt
from jwt import PyJWKClient

JWKS = PyJWKClient("http://keycloak:8080/realms/historia-clinica/protocol/openid-connect/certs")

def verificar_token(token: str) -> dict:
    if token and token.lower().startswith("bearer "):
        token = token[7:]
    clave = JWKS.get_signing_key_from_jwt(token).key
    claims = jwt.decode(token, clave, algorithms=["RS256"], audience="plataforma-hc")
    # Keycloak trae los roles en realm_access.roles
    roles = (claims.get("realm_access") or {}).get("roles", [])
    claims["rol"] = next((r for r in roles if r in ROLES), "")
    claims["permisos"] = permisos_de(claims["rol"])
    return claims
```

El resto de la plataforma no cambia: `app/auth.py` y las vistas usan
`verificar_token` y los permisos derivados del rol, no el emisor del token.

### Para reclamarlo como trabajo hecho

Hay que levantarlo, iniciar sesión con los cuatro usuarios, comprobar que los
permisos siguen funcionando y dejar la evidencia. Mientras eso no ocurra,
esto es una propuesta, y así está declarado en el informe.
