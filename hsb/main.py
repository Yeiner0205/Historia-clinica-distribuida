"""
hsb/main.py — Servicio HSB (Health Service Bus). Puerto 8000.

Puertas de entrada (Fase 3, Paso 2):

    POST /hsb/hl7            un mensaje HL7 v2 en texto plano (ADT^A01, ORU^R01)
    POST /hsb/csv?sede=N     un archivo CSV legado con separador ';'
    POST /hsb/migrar?sede=N  normaliza a FHIR lo que ya está en el legado
    GET  /health             estado del servicio y de sus dependencias
    GET  /metrics            contadores, latencia y fallidos

Las puertas de ingesta quedan abiertas: representan el enlace interno con el
sistema legado de la sede (y así funcionan los `curl` de la guía). Las
operaciones de administración (reencolar un mensaje muerto) sí exigen token
con permiso `bus:enviar`, porque las ejecuta una persona.
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

import jwt
from fastapi import Body, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from comun import auditoria, db, seguridad, sedes
from fhir import cliente_hapi, normalizador, terminologia
from hsb import VERSION, cola, csv_legado, entrega, hl7, metricas, validador

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)-7s [hsb] %(message)s",
)
logger = logging.getLogger("hsb")

app = FastAPI(
    title="HSB — Health Service Bus",
    version=VERSION,
    description=(
        "Bus de integración de salud: recibe HL7 v2 y CSV legado de las tres "
        "sedes, valida, normaliza a FHIR R4 y entrega a HAPI y al nodo de la "
        "sede, con reintentos, cola de mensajes muertos e idempotencia."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def arrancar() -> None:
    cola.iniciar_trabajador()
    logger.info("HSB %s en marcha. HAPI=%s central=%s:%s", VERSION, sedes.HAPI_BASE_URL,
                sedes.CENTRAL["host"], sedes.CENTRAL["port"])


@app.on_event("shutdown")
def apagar() -> None:
    cola.detener_trabajador()


# ─────────────────────────────────────────────────────────────────────────────
# Autorización de las operaciones administrativas
# ─────────────────────────────────────────────────────────────────────────────
def _exigir(permiso: str, authorization: Optional[str]) -> Dict[str, Any]:
    if not authorization:
        auditoria.registrar("anonimo", "", "acceso_denegado", f"hsb:{permiso}", "denegado",
                            {"motivo": "sin token"})
        raise HTTPException(status_code=401, detail="Falta el token. Obtenga uno en POST /auth/login de la API.")
    try:
        claims = seguridad.verificar_token(authorization)
    except jwt.PyJWTError as exc:
        auditoria.registrar("anonimo", "", "acceso_denegado", f"hsb:{permiso}", "denegado",
                            {"motivo": f"token inválido: {exc}"})
        raise HTTPException(status_code=401, detail=f"Token inválido: {exc}") from exc
    if not seguridad.tiene_permiso(claims.get("rol", ""), permiso):
        auditoria.registrar(claims.get("sub", "?"), claims.get("rol", ""), "acceso_denegado",
                            f"hsb:{permiso}", "denegado", {"permiso": permiso})
        raise HTTPException(status_code=403, detail=f"El rol '{claims.get('rol')}' no puede '{permiso}'")
    return claims


# ─────────────────────────────────────────────────────────────────────────────
# Ingesta
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/hsb/hl7", summary="Recibe un mensaje HL7 v2 (ADT^A01 u ORU^R01)")
async def recibir_hl7(request: Request) -> Dict[str, Any]:
    metricas.contar("peticiones")
    crudo = (await request.body()).decode("utf-8", errors="replace")

    try:
        registro = hl7.parsear(crudo)
    except hl7.ErrorHL7 as exc:
        # Ni siquiera es HL7: se responde 400, pero queda en la auditoría.
        auditoria.registrar("desconocido", "sistema_sede", "bus_rechazo", "mensaje:ilegible",
                            "rechazado", {"motivo": str(exc)})
        raise HTTPException(status_code=400, detail=f"Mensaje HL7 ilegible: {exc}") from exc

    logger.info("HL7 recibido: %s", hl7.resumen(registro))
    try:
        resultado = cola.recibir(registro, crudo)
    except cola.ColaNoDisponible as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"entrada": "hl7v2", "resumen": hl7.resumen(registro), **resultado}


@app.post("/hsb/csv", summary="Recibe un archivo CSV legado (separador ';')")
async def recibir_csv(request: Request, sede: int = Query(..., ge=1, le=3)) -> Dict[str, Any]:
    metricas.contar("peticiones")
    crudo = (await request.body()).decode("utf-8", errors="replace")

    try:
        registros = csv_legado.parsear(crudo, sede)
    except csv_legado.ErrorCSV as exc:
        auditoria.registrar("desconocido", "sistema_sede", "bus_rechazo", f"csv:sede{sede}",
                            "rechazado", {"motivo": str(exc)})
        raise HTTPException(status_code=400, detail=f"CSV ilegible: {exc}") from exc

    logger.info("CSV recibido de la sede %s: %s filas", sede, len(registros))
    resultados: List[Dict[str, Any]] = []
    for registro in registros:
        fila_cruda = json.dumps(registro, ensure_ascii=False, default=str)
        try:
            resultados.append({"fila": registro.get("fila_csv"), **cola.recibir(registro, fila_cruda)})
        except cola.ColaNoDisponible as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {"entrada": "csv", "sede_id": sede, "filas": len(registros),
            "resumen": _resumen_lote(resultados), "resultados": resultados}


@app.post("/hsb/migrar", summary="Normaliza a FHIR los pacientes que ya están en el legado")
def migrar_legado(sede: int = Query(..., ge=1, le=3),
                  limite: int = Query(200, ge=1, le=2000)) -> Dict[str, Any]:
    """
    Lee las filas legadas de una sede (las que tienen `fhir_patient_id` nulo),
    las convierte en mensajes del bus y las procesa con la misma cadena. Es lo
    que hace subir la cobertura FHIR de la sede de 0 % a 100 %.
    """
    metricas.contar("peticiones")
    s = sedes.sede(sede)
    try:
        filas = db.consultar(
            s,
            """
            SELECT u.documento_id, u.tipo_documento, u.nombre_completo, u.fecha_nacimiento,
                   u.sexo, a.atencion_id, a.visita, a.fecha_ingreso, a.entidad_salud,
                   a.entorno_atencion, a.via_ingreso, a.causa_atencion, a.clasificacion_triage,
                   a.profesional_codigo
              FROM usuario u
              LEFT JOIN atencion a ON a.documento_id = u.documento_id
             WHERE u.fhir_patient_id IS NULL
             ORDER BY u.documento_id, a.atencion_id
             LIMIT %s;
            """,
            (limite,),
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Sede {sede} no disponible: {exc}") from exc

    resultados: List[Dict[str, Any]] = []
    for fila in filas:
        registro = _registro_desde_legado(fila, s)
        if registro is None:
            continue
        try:
            resultados.append(cola.recibir(registro, json.dumps(fila, ensure_ascii=False, default=str)))
        except cola.ColaNoDisponible as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {"entrada": "legado", "sede_id": sede, "filas_leidas": len(filas),
            "resumen": _resumen_lote(resultados), "resultados": resultados,
            "cobertura": db.cobertura_fhir_por_sede()}


def _registro_desde_legado(fila: Dict[str, Any], sede: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Convierte una fila legada (usuario + atención) en registro canónico."""
    documento = str(fila["documento_id"])
    sin_atencion = not fila.get("atencion_id")
    visita = None if sin_atencion else fila.get("visita")

    registro: Dict[str, Any] = {
        "formato": "csv",
        "tipo": "LEGADO",
        "origen": f"LEGADO_{sede['codigo']}",
        "sede_codigo": sede["codigo"],
        "sede_id": sede["sede_id"],
        "sede_nombre": sede["nombre"],
        "clave_idempotencia": f"legado:{sede['sede_id']}:{documento}:{visita or 'sin-visita'}",
        "sin_atencion": sin_atencion,
        "documento": documento,
        "tipo_documento": fila.get("tipo_documento") or "CC",
        "nombre_completo": fila.get("nombre_completo") or "",
        "fecha_nacimiento": fila.get("fecha_nacimiento"),
        "sexo": (fila.get("sexo") or "U").upper()[:1],
        "visita": visita,
        "fecha_ingreso": fila.get("fecha_ingreso"),
        "entidad_salud": fila.get("entidad_salud"),
        "entorno_atencion": fila.get("entorno_atencion"),
        "via_ingreso": fila.get("via_ingreso"),
        "causa_atencion": fila.get("causa_atencion"),
        "triage": fila.get("clasificacion_triage"),
        "clase_encuentro": {"Urgencias": "E", "Hospitalizacion": "I"}.get(
            fila.get("entorno_atencion") or "", "O"
        ),
        "diagnosticos": [],
        "observaciones": [],
    }
    if fila.get("profesional_codigo"):
        registro["profesional"] = {"codigo": fila["profesional_codigo"], "nombre": fila["profesional_codigo"]}

    # Diagnósticos y observaciones de esa atención
    if fila.get("atencion_id"):
        try:
            for dx in db.consultar(
                sede,
                "SELECT dx_local, cie10, descripcion_cie10 FROM diagnostico WHERE atencion_id = %s;",
                (fila["atencion_id"],),
            ):
                codigo = dx.get("cie10") or dx.get("dx_local")
                if codigo:
                    registro["diagnosticos"].append(
                        {"origen": codigo, "descripcion": dx.get("descripcion_cie10") or "",
                         "sistema_origen": "I10" if dx.get("cie10") else "L"}
                    )
            for obs in db.consultar(
                sede,
                "SELECT loinc, descripcion, valor, unidad, fecha FROM observacion WHERE atencion_id = %s;",
                (fila["atencion_id"],),
            ):
                registro["observaciones"].append(
                    {"codigo": obs.get("loinc"), "prueba": obs.get("descripcion"),
                     "valor": obs.get("valor"), "unidad": obs.get("unidad"), "fecha": obs.get("fecha")}
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("No se pudieron leer dx/obs de la atención %s: %s", fila.get("atencion_id"), exc)
    return registro


def _resumen_lote(resultados: List[Dict[str, Any]]) -> Dict[str, int]:
    resumen: Dict[str, int] = {}
    for r in resultados:
        clave = r.get("resultado", "desconocido")
        resumen[clave] = resumen.get(clave, 0) + 1
    return resumen


# ─────────────────────────────────────────────────────────────────────────────
# Validación en seco (sin entregar)
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/hsb/validar", summary="Valida y transforma sin entregar (dry-run)")
async def validar_sin_entregar(request: Request, formato: str = Query("hl7v2"),
                               sede: int = Query(3, ge=1, le=3),
                               contra_hapi: bool = Query(False)) -> Dict[str, Any]:
    crudo = (await request.body()).decode("utf-8", errors="replace")
    if formato == "hl7v2":
        registros = [hl7.parsear(crudo)]
    else:
        registros = csv_legado.parsear(crudo, sede)

    salida = []
    for registro in registros:
        motivos = validador.validar(registro)
        item: Dict[str, Any] = {
            "documento": registro.get("documento"),
            "sede_id": registro.get("sede_id"),
            "valido": not motivos,
            "motivos": motivos,
        }
        if not motivos:
            bundle = normalizador.bundle_transaccion(registro)
            item["bundle"] = bundle
            item["recursos"] = [e["request"]["url"] for e in bundle["entry"]]
            if contra_hapi:
                try:
                    item["validacion_hapi"] = cliente_hapi.validar_bundle(bundle)
                except cliente_hapi.ErrorHapi as exc:
                    item["validacion_hapi"] = {"valido": None, "error": str(exc)}
        salida.append(item)
    return {"formato": formato, "total": len(salida), "resultados": salida}


# ─────────────────────────────────────────────────────────────────────────────
# Consulta de la cola
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/hsb/mensajes", summary="Mensajes de la cola, con su estado")
def listar_mensajes(estado: Optional[str] = None, sede: Optional[int] = None,
                    limite: int = Query(50, ge=1, le=500)) -> Dict[str, Any]:
    try:
        mensajes = cola.listar(estado=estado, limite=limite, sede_id=sede)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Almacén central no disponible: {exc}") from exc
    return {"total": len(mensajes), "filtro": {"estado": estado, "sede": sede}, "mensajes": mensajes}


@app.get("/hsb/mensajes/{mensaje_id}", summary="Detalle de un mensaje, con su Bundle")
def detalle_mensaje(mensaje_id: int) -> Dict[str, Any]:
    mensaje = cola.obtener(mensaje_id)
    if mensaje is None:
        raise HTTPException(status_code=404, detail="Mensaje no encontrado")
    return mensaje


@app.post("/hsb/mensajes/{mensaje_id}/reencolar", summary="Devuelve un mensaje muerto a la cola")
def reencolar_mensaje(mensaje_id: int, authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    claims = _exigir("bus:enviar", authorization)
    resultado = cola.reencolar(mensaje_id)
    auditoria.registrar(claims.get("sub", "?"), claims.get("rol", ""), "bus_reencolar",
                        f"mensaje:{mensaje_id}", "ok", {"resultado": resultado.get("resultado")})
    return resultado


@app.get("/hsb/muertos", summary="Cola de mensajes muertos")
def mensajes_muertos(limite: int = Query(50, ge=1, le=500)) -> Dict[str, Any]:
    try:
        with db.cursor_central() as cur:
            cur.execute("SELECT * FROM cola_mensajes_muertos LIMIT %s;", (limite,))
            filas = [dict(f) for f in cur.fetchall()]
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Almacén central no disponible: {exc}") from exc
    return {"total": len(filas), "mensajes": filas}


# ─────────────────────────────────────────────────────────────────────────────
# Terminologías y reglas
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/hsb/terminologia", summary="Mapeo local → CIE-10 y LOINC")
def ver_terminologia() -> Dict[str, Any]:
    tabla = terminologia.tabla(recargar=True)
    return {
        "origen": terminologia.origen(),
        "cie10": [{"dx_local": k, **v} for k, v in sorted(tabla.items())],
        "loinc": [{"prueba_local": k, **v} for k, v in sorted(terminologia.LOINC_LOCAL.items())],
        "concept_map": terminologia.concept_map(),
    }


@app.get("/hsb/reglas", summary="Tabla de reglas de validación")
def ver_reglas() -> Dict[str, Any]:
    return {"reglas": validador.reglas(), "hl7_exige_cie10": validador.HL7_EXIGE_CIE10}


# ─────────────────────────────────────────────────────────────────────────────
# Observabilidad
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/health", summary="Estado del servicio y de sus dependencias")
def health(response: Response) -> Dict[str, Any]:
    central = db.ping(sedes.CENTRAL)
    hapi = cliente_hapi.salud()
    estado_sedes = db.estado_sedes()
    sedes_arriba = sum(1 for s in estado_sedes if s["disponible"])

    # El bus sigue «vivo» aunque falte una sede: solo el central es crítico.
    estado = "ok" if central["disponible"] and hapi["disponible"] and sedes_arriba == 3 else (
        "degradado" if central["disponible"] else "caido"
    )
    if estado == "caido":
        response.status_code = 503

    return {
        "servicio": "hsb",
        "version": VERSION,
        "estado": estado,
        "tiempo_activo_s": metricas.tiempo_activo_s(),
        "trabajador_cola": "activo" if cola.trabajador_activo() else "detenido",
        "dependencias": {
            "almacen_central": central,
            "hapi_fhir": hapi,
            "sedes": estado_sedes,
            "sedes_disponibles": f"{sedes_arriba}/3",
        },
        "terminologia": terminologia.origen(),
    }


@app.get("/metrics", response_class=PlainTextResponse, summary="Métricas (formato Prometheus)")
def metrics() -> str:
    return metricas.texto_prometheus("hsb")


@app.get("/metrics.json", summary="Métricas en JSON")
def metrics_json() -> Dict[str, Any]:
    return metricas.recolectar()


@app.get("/", summary="Presentación del bus")
def raiz() -> Dict[str, Any]:
    return {
        "servicio": "HSB — Health Service Bus",
        "version": VERSION,
        "entradas": {
            "POST /hsb/hl7": "mensaje HL7 v2 (ADT^A01, ORU^R01) en texto plano",
            "POST /hsb/csv?sede=N": "CSV legado con separador ';'",
            "POST /hsb/migrar?sede=N": "normaliza a FHIR lo que ya está en el legado",
            "POST /hsb/validar": "valida y transforma sin entregar",
        },
        "consulta": {
            "GET /hsb/mensajes": "cola con estados",
            "GET /hsb/muertos": "cola de mensajes muertos",
            "GET /hsb/terminologia": "mapeo CIE-10 y LOINC",
            "GET /health": "estado",
            "GET /metrics": "métricas",
        },
        "sedes": [{"sede_id": s["sede_id"], "codigo": s["codigo"], "nombre": s["nombre"]} for s in sedes.SEDES],
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("HSB_PORT", "8000")))
