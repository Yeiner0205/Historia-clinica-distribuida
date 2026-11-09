# app/main.py — API y vistas de la plataforma distribuida de interoperabilidad
# clínica. Puerto 8001.
#
# Sirve las cuatro vistas por rol (Paciente, Admisionista, Médico y Reporte de
# HC), la consulta unificada de las tres sedes y los endpoints de seguridad,
# auditoría y observabilidad. Ninguna vista habla directo con las bases de las
# sedes: todo pasa por esta API y por el HSB.
import logging
import os
import sys
import time

# Permite ejecutar tanto `uvicorn app.main:app` desde la raíz como
# `python app/main.py` desde la carpeta app/.
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

import httpx
from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Any, Dict, List, Optional

from app import auth, consulta_unificada, reporte
from app.fhir_app.models.patient_model import PatientIdentificationData
from app.fhir_app.services.db_service import DBService
from app.fhir_app.services.fhir_service import FHIRService
from comun import auditoria, db, seguridad, sedes
from fhir import cliente_hapi, normalizador, terminologia
from fhir.transformador import FHIRTransformer

import app.middleware as middleware
import psycopg2
from fastapi_mcp import FastApiMCP

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)-7s [api] %(message)s",
)
logger = logging.getLogger("api")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PLANTILLAS = os.path.join(BASE_DIR, "templates")


def plantilla(nombre: str) -> str:
    """Lee una plantilla HTML de app/templates."""
    ruta = os.path.join(PLANTILLAS, nombre)
    if not os.path.isfile(ruta):
        raise HTTPException(status_code=404, detail=f"Plantilla {nombre} no encontrada")
    with open(ruta, "r", encoding="utf-8") as fh:
        return fh.read()


# Cargar HTML de FIRH al iniciar
FIRH_HTML = None
_firh_path = os.path.join(PLANTILLAS, "firh.html")
if os.path.isfile(_firh_path):
    with open(_firh_path, "r", encoding="utf-8") as _f:
        FIRH_HTML = _f.read()

app = FastAPI(
    title="Plataforma distribuida de interoperabilidad clínica",
    version="1.0.0",
    description=(
        "API y vistas por rol sobre tres sedes (Sincelejo, Cartagena y Corozal) "
        "con normalización a FHIR R4, bus de integración HSB, seguridad por rol "
        "y auditoría encadenada por hash."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Observabilidad: contadores que alimentan /metrics ───────────────────────
_INICIO = time.time()
_CONTADORES: Dict[str, float] = {
    "peticiones": 0,
    "errores": 0,
    "denegados": 0,
    "latencia_total_ms": 0.0,
}


@app.middleware("http")
async def medir_peticiones(request: Request, call_next):
    """Cuenta peticiones, errores, accesos denegados y latencia."""
    comienzo = time.perf_counter()
    try:
        respuesta = await call_next(request)
    except Exception:
        _CONTADORES["peticiones"] += 1
        _CONTADORES["errores"] += 1
        raise
    transcurrido = (time.perf_counter() - comienzo) * 1000
    _CONTADORES["peticiones"] += 1
    _CONTADORES["latencia_total_ms"] += transcurrido
    if respuesta.status_code in (401, 403):
        _CONTADORES["denegados"] += 1
    elif respuesta.status_code >= 500:
        _CONTADORES["errores"] += 1
    respuesta.headers["X-Tiempo-Respuesta-ms"] = f"{transcurrido:.1f}"
    return respuesta

# Configuración de nodos: una entrada por sede, desde comun/sedes.py
USE_DOCKER_NAMES = sedes.USE_DOCKER_NAMES
NODES_CONFIG = [
    {
        "id": s["nodo"],
        "sede_id": s["sede_id"],
        "sede": s["nombre"],
        "host": s["host"],
        "port": s["port"],
        "display_port": str(s["puerto_host"]),
    }
    for s in sedes.SEDES
]


@app.get("/", response_class=RedirectResponse)
async def root_redirect():
    return RedirectResponse(url="/home", status_code=302)


@app.get("/home", response_class=HTMLResponse)
@app.get("/home/", response_class=HTMLResponse)
async def home_page():
    """Pantalla de inicio — hub de navegación entre módulos"""
    return plantilla("home.html")


@app.get("/dashboard", response_class=HTMLResponse)
@app.get("/dashboard/", response_class=HTMLResponse)
async def dashboard_page():
    """Nodes Monitor — estado de los nodos PostgreSQL y simulador de queries"""
    return plantilla("index.html")


@app.get("/api/health")
async def health():
    return {"status": "ok", "home": "/home", "medico": "/medico", "admision": "/admision", "carga_hc": "/carga-hc", "hc": "/hc"}


@app.get("/hc", response_class=HTMLResponse)
@app.get("/hc/", response_class=HTMLResponse)
@app.get("/firh", response_class=HTMLResponse)
@app.get("/firh/", response_class=HTMLResponse)
@app.get("/carga-hc", response_class=HTMLResponse)
@app.get("/carga-hc/", response_class=HTMLResponse)
async def firh_page():
    if FIRH_HTML is None:
        raise HTTPException(status_code=500, detail="Plantilla firh.html no encontrada")
    return HTMLResponse(content=FIRH_HTML)


@app.get("/api/nodes")
async def get_nodes():
    """Obtiene el estado de los nodos verificando conectividad a PostgreSQL"""
    nodes_status = []
    
    for node_config in NODES_CONFIG:
        node_info = {
            "id": node_config["id"],
            "port": node_config["display_port"],
            "status": "unknown"
        }
        
        try:
            # Intentar conectar a PostgreSQL para verificar el estado
            conn = psycopg2.connect(
                host=node_config["host"],
                port=node_config["port"],
                user="admin",
                password="admin",
                dbname="historia_clinica",
                connect_timeout=3
            )
            conn.close()
            node_info["status"] = "running"
        except Exception as e:
            node_info["status"] = "exited"
            node_info["error"] = str(e)
        
        nodes_status.append(node_info)
    
    return nodes_status


@app.post("/api/nodes/{node_id}/{action}")
async def control_node(node_id: str, action: str):
    """
    Endpoint simplificado para control de nodos.
    En la versión Dockerizada, el control se hace desde el host con docker compose.
    """
    return {
        "message": f"Para controlar nodos en Docker, usa: docker compose {action} {node_id}",
        "note": "Control de contenedores disponible desde el host"
    }


class QueryRequest(BaseModel):
    query: str


@app.post("/api/execute-query")
async def execute_query(request: QueryRequest):
    try:
        resultado = middleware.ejecutar_query_en_todos_los_nodos(request.query)
        return resultado
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# ENDPOINTS FHIR - MVP
# ============================================================================

# Inicializar servicios
fhir_service = FHIRService()
db_service = DBService()


# ============================================================================
# ENDPOINTS DE ADMISIÓN — Flujo de llegada de nuevo paciente
# Estándar HL7 FHIR R4 + DB Distribuida
# ============================================================================

@app.get("/admision", response_class=HTMLResponse)
@app.get("/admision/", response_class=HTMLResponse)
async def admision_page():
    """Vista de admisión: verifica si el paciente existe antes de registrarlo"""
    return plantilla("admision-paciente.html")


@app.get("/api/v1/admision/verificar/{documento_id}")
async def verificar_paciente(documento_id: str,
                             claims: dict = Depends(auth.requiere("paciente:buscar"))):
    """
    Punto de entrada principal del flujo de admisión.

    Estrategia de búsqueda (HL7 Patient Matching):
    1. Busca en la DB local distribuida (PostgreSQL, nodo según fragmentación)
    2. Si no está en DB, busca en HAPI FHIR por identifier
    3. Retorna: encontrado_local, encontrado_fhir, datos_paciente

    Basado en IHE PIX/PDQ y HL7 FHIR R4 Patient $match.
    """
    try:
        doc_id_int = int(documento_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="documento_id debe ser numérico")

    resultado = {
        "documento_id": documento_id,
        "encontrado_local": False,
        "encontrado_fhir": False,
        "paciente_local": None,
        "paciente_fhir": None,
        "nodo_asignado": None,
        "accion_recomendada": "registrar",
    }

    # 1. Buscar en DB local
    try:
        paciente_local = DBService.buscar_paciente(doc_id_int)
        if paciente_local:
            resultado["encontrado_local"] = True
            resultado["paciente_local"] = paciente_local
            resultado["accion_recomendada"] = "admitir_existente"
    except Exception as e:
        resultado["error_local"] = str(e)

    # 2. Buscar en HAPI FHIR si no está en local o para enriquecer
    try:
        bundle = await fhir_service.search_patient_by_identifier(documento_id)
        entries = bundle.get("entry", [])
        if entries:
            resultado["encontrado_fhir"] = True
            resultado["paciente_fhir"] = entries[0]["resource"]
            if not resultado["encontrado_local"]:
                resultado["accion_recomendada"] = "importar_de_fhir"
    except Exception as e:
        resultado["error_fhir"] = str(e)

    # 3. ¿En qué sedes existe? (detección de duplicados entre sedes)
    try:
        entre_sedes = DBService.buscar_en_todas_las_sedes(doc_id_int)
        resultado["sedes_con_registro"] = entre_sedes["sedes_con_registro"]
        resultado["duplicado_entre_sedes"] = len(entre_sedes["sedes_con_registro"]) > 1
        resultado["sedes_no_disponibles"] = entre_sedes["sedes_no_disponibles"]
        resultado["parcial"] = entre_sedes["parcial"]
    except Exception as exc:  # noqa: BLE001
        resultado["error_sedes"] = str(exc)

    # 4. Sede en la que se admitiría (la del admisionista) y nodo de respaldo
    sede_sesion = claims.get("sede_id")
    resultado["sede_admision"] = sede_sesion
    resultado["nodo_asignado"] = (
        f"sede {sede_sesion} ({sedes.sede(sede_sesion)['nombre']})" if sede_sesion
        else f"{sedes.nodo_por_documento(doc_id_int)['nodo']} por rango de documento"
    )

    auth.registrar_acceso(claims, "verificar_paciente", f"documento:{documento_id}", "ok",
                          {"encontrado_local": resultado["encontrado_local"],
                           "encontrado_fhir": resultado["encontrado_fhir"]})
    return consulta_unificada.serializable(resultado)


@app.post("/api/v1/admision/registrar")
async def registrar_admision(data: PatientIdentificationData, sede: Optional[int] = None,
                             claims: dict = Depends(auth.requiere("paciente:registrar"))):
    """
    Registra un paciente nuevo en el sistema de forma dual:
    1. Crea el recurso FHIR Patient en HAPI FHIR (estándar HL7 R4)
    2. Persiste en la DB local distribuida con el fhir_patient_id vinculado

    Si el paciente ya existe en alguno de los dos sistemas, retorna
    su información sin duplicar (idempotente).
    """
    data_dict = data.dict()
    doc_id = int(data_dict["numeroDocumento"])
    # El paciente se admite en la sede del admisionista (o en la que indique).
    sede_destino = sede or claims.get("sede_id")

    # 1. Verificar si ya existe localmente
    existente_local = None
    try:
        existente_local = DBService.buscar_paciente(doc_id)
    except Exception:
        pass

    fhir_id = None
    fhir_result = None

    # 2. Crear/buscar en HAPI FHIR
    try:
        # Primero verificar si ya existe en FHIR
        bundle = await fhir_service.search_patient_by_identifier(str(doc_id))
        entries = bundle.get("entry", [])
        if entries:
            fhir_result = entries[0]["resource"]
            fhir_id = fhir_result.get("id")
        else:
            # Crear en FHIR
            patient_resource = FHIRTransformer.to_fhir_patient(data_dict)
            fhir_result = await fhir_service.create_patient(patient_resource)
            fhir_id = fhir_result.get("id")
    except Exception as e:
        # FHIR no disponible — continuar solo con DB local
        fhir_result = {"error": str(e), "nota": "HAPI FHIR no disponible, registrado solo en DB local"}

    # 3. Persistir en la sede
    try:
        db_resultado = DBService.insertar_paciente(data_dict, fhir_patient_id=fhir_id,
                                                   sede_id=sede_destino)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en la base de la sede: {str(e)}")

    sello = auth.registrar_acceso(
        claims, "registrar_paciente", f"documento:{doc_id}", "ok",
        {"accion": db_resultado["accion"], "nodo": db_resultado["nodo"],
         "sede_id": sede_destino, "fhir_patient_id": fhir_id},
    )

    return {
        "success": True,
        "accion": db_resultado["accion"],
        "nodo": db_resultado["nodo"],
        "sede_id": sede_destino,
        "fhir_patient_id": fhir_id,
        "paciente_local": consulta_unificada.serializable(db_resultado["paciente"]),
        "fhir_resource": fhir_result,
        "sello_auditoria": (sello or {}).get("hash"),
        "mensaje": (
            f"Paciente {'encontrado' if db_resultado['accion'] == 'existente' else 'creado'} "
            f"en {db_resultado['nodo']} con FHIR ID: {fhir_id}"
        )
    }


@app.get("/api/v1/admision/tablas/estado")
async def estado_tablas_db(claims: dict = Depends(auth.requiere("plataforma:estado"))):
    """
    Verifica si las tablas del esquema clínico existen en los 3 nodos.
    Útil para diagnóstico en la vista de admisión.
    """
    return {"nodos": DBService.estado_tablas()}


@app.post("/api/v1/admision/tablas/inicializar")
async def inicializar_tablas_db(claims: dict = Depends(auth.requiere("plataforma:estado"))):
    """
    Crea las tablas (CREATE TABLE IF NOT EXISTS) en todos los nodos.
    Operación idempotente — segura de ejecutar múltiples veces.
    """
    resultado = DBService.inicializar_tablas()
    return resultado


@app.get("/api/v1/admision/buscar")
async def buscar_pacientes(
    nombre: str = "",
    documento: str = "",
    claims: dict = Depends(auth.requiere("paciente:buscar")),
):
    """
    Búsqueda unificada de pacientes:
    - Por nombre: busca en todos los nodos (LIKE)
    - Por documento: va directamente al nodo correcto + FHIR
    """
    if not nombre and not documento:
        raise HTTPException(status_code=400, detail="Proporciona 'nombre' o 'documento'")

    resultados_db = []
    resultados_fhir = []

    if documento:
        try:
            doc_int = int(documento)
            p = DBService.buscar_paciente(doc_int)
            if p:
                resultados_db.append(p)
        except Exception:
            pass

        try:
            bundle = await fhir_service.search_patient_by_identifier(documento)
            if bundle.get("entry"):
                resultados_fhir = [e["resource"] for e in bundle["entry"]]
        except Exception:
            pass

    if nombre:
        try:
            resultados_db.extend(DBService.buscar_por_nombre(nombre))
        except Exception:
            pass

        try:
            async with __import__('httpx').AsyncClient(timeout=15.0) as client:
                r = await client.get(
                    f"{fhir_service.base_url}/Patient",
                    params={"name": nombre},
                    headers={"Accept": "application/fhir+json"}
                )
                if r.status_code == 200 and r.json().get("entry"):
                    resultados_fhir.extend([e["resource"] for e in r.json()["entry"]])
        except Exception:
            pass

    return {
        "total_local": len(resultados_db),
        "total_fhir": len(resultados_fhir),
        "resultados_local": resultados_db,
        "resultados_fhir": resultados_fhir,
    }

@app.get("/registro-paciente", response_class=HTMLResponse)
@app.get("/registro-paciente/", response_class=HTMLResponse)
async def registro_paciente_page():
    """Sirve el formulario de registro de paciente"""
    return plantilla("registro-paciente.html")


@app.post("/api/v1/fhir/patient")
async def create_fhir_patient(data: PatientIdentificationData):
    """
    Crea un paciente en HAPI FHIR Server
    
    Recibe los 15 campos de identificación y los transforma a recurso FHIR Patient
    """
    try:
        # 1. Transformar datos a recurso FHIR Patient
        patient_resource = FHIRTransformer.to_fhir_patient(data.dict())
        
        # 2. Enviar a HAPI FHIR Server
        result = await fhir_service.create_patient(patient_resource)
        
        # 3. Extraer ID del paciente creado
        patient_id = result.get("id")
        
        return {
            "success": True,
            "message": "Paciente creado exitosamente en HAPI FHIR",
            "patient_id": patient_id,
            "fhir_resource": result
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error al crear paciente: {str(e)}"
        )


@app.get("/api/v1/fhir/patient/{patient_id}")
async def get_fhir_patient(patient_id: str):
    """Obtiene un paciente por ID desde HAPI FHIR"""
    try:
        patient = await fhir_service.get_patient(patient_id)
        
        if patient is None:
            raise HTTPException(status_code=404, detail="Paciente no encontrado")
        
        return patient
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error al obtener paciente: {str(e)}"
        )


@app.get("/api/v1/fhir/patient/search/{identifier}")
async def search_fhir_patient(identifier: str):
    """Busca pacientes por número de documento"""
    try:
        results = await fhir_service.search_patient_by_identifier(identifier)
        return results
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error al buscar paciente: {str(e)}"
        )


@app.get("/api/v1/fhir/health")
async def fhir_server_health():
    """Verifica el estado del servidor HAPI FHIR"""
    try:
        metadata = await fhir_service.check_server_health()
        return {
            "status": "ok",
            "fhir_version": metadata.get("fhirVersion"),
            "server": "HAPI FHIR",
            "metadata": metadata
        }
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"HAPI FHIR Server no disponible: {str(e)}"
        )


@app.get("/consulta-hc", response_class=HTMLResponse)
@app.get("/consulta-hc/", response_class=HTMLResponse)
async def consulta_hc_page():
    """Sirve la página de consulta de historias clínicas"""
    return plantilla("consulta-hc.html")


@app.get("/api/v1/fhir/patients")
async def list_patients(page: int = 1, size: int = 10):
    """
    Lista todos los pacientes con paginación
    
    Query params:
    - page: Número de página (default: 1)
    - size: Tamaño de página (default: 10)
    """
    try:
        # Buscar todos los pacientes en HAPI FHIR
        import httpx
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"http://hapi-fhir:8080/fhir/Patient",
                params={
                    "_count": size,
                    "_page": page
                },
                headers={"Accept": "application/fhir+json"}
            )
            
            response.raise_for_status()
            bundle = response.json()
            
            # Extraer pacientes del bundle
            patients = []
            if bundle.get("entry"):
                patients = [entry["resource"] for entry in bundle["entry"]]
            
            total = bundle.get("total", 0)
            total_pages = (total + size - 1) // size if total > 0 else 1
            
            return {
                "patients": patients,
                "total": total,
                "page": page,
                "size": size,
                "total_pages": total_pages
            }
            
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error al listar pacientes: {str(e)}"
        )


@app.get("/api/v1/fhir/patients/search")
async def search_patients_query(q: str):
    """
    Busca pacientes por nombre o documento
    
    Query params:
    - q: Término de búsqueda
    """
    try:
        import httpx
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Buscar por nombre
            response_name = await client.get(
                f"http://hapi-fhir:8080/fhir/Patient",
                params={"name": q},
                headers={"Accept": "application/fhir+json"}
            )
            
            # Buscar por identificador
            response_id = await client.get(
                f"http://hapi-fhir:8080/fhir/Patient",
                params={"identifier": q},
                headers={"Accept": "application/fhir+json"}
            )
            
            patients = []
            
            # Combinar resultados
            if response_name.status_code == 200:
                bundle = response_name.json()
                if bundle.get("entry"):
                    patients.extend([entry["resource"] for entry in bundle["entry"]])
            
            if response_id.status_code == 200:
                bundle = response_id.json()
                if bundle.get("entry"):
                    for entry in bundle["entry"]:
                        resource = entry["resource"]
                        # Evitar duplicados
                        if not any(p["id"] == resource["id"] for p in patients):
                            patients.append(resource)
            
            return {
                "patients": patients,
                "total": len(patients),
                "query": q
            }
            
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error en la búsqueda: {str(e)}"
        )


@app.get("/paciente/{patient_id}", response_class=HTMLResponse)
async def patient_detail_page(patient_id: str):
    """Página de detalle de un paciente"""
    try:
        # Obtener paciente desde HAPI FHIR
        patient = await fhir_service.get_patient(patient_id)
        
        if patient is None:
            raise HTTPException(status_code=404, detail="Paciente no encontrado")
        
        # Generar HTML de detalle
        html = generate_patient_detail_html(patient)
        return html
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error al obtener detalle del paciente: {str(e)}"
        )


def generate_patient_detail_html(patient: dict) -> str:
    """Genera HTML para mostrar detalle de un paciente"""
    identifier = patient.get("identifier", [{}])[0].get("value", "N/A")
    name = patient.get("name", [{}])[0].get("text", "Sin nombre")
    gender = patient.get("gender", "unknown")
    birth_date = patient.get("birthDate", "N/A")
    
    gender_map = {
        "male": "Masculino",
        "female": "Femenino",
        "other": "Otro",
        "unknown": "No especificado"
    }
    
    return f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Detalle Paciente - {name}</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&display=swap" rel="stylesheet">
        <script src="https://unpkg.com/@phosphor-icons/web"></script>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{ font-family: 'Inter', sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; padding: 2rem; }}
            .container {{ max-width: 900px; margin: 0 auto; background: white; border-radius: 20px; box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3); overflow: hidden; }}
            .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 2rem; }}
            .header h1 {{ font-size: 2rem; margin-bottom: 0.5rem; }}
            .header p {{ opacity: 0.9; }}
            .content {{ padding: 2rem; }}
            .section {{ margin-bottom: 2rem; }}
            .section h2 {{ font-size: 1.25rem; color: #333; margin-bottom: 1rem; padding-bottom: 0.5rem; border-bottom: 2px solid #667eea; }}
            .field {{ display: grid; grid-template-columns: 200px 1fr; gap: 1rem; padding: 0.75rem 0; border-bottom: 1px solid #e2e8f0; }}
            .field:last-child {{ border-bottom: none; }}
            .field-label {{ font-weight: 600; color: #555; }}
            .field-value {{ color: #333; }}
            .btn-back {{ display: inline-block; margin-top: 2rem; padding: 0.75rem 1.5rem; background: #667eea; color: white; text-decoration: none; border-radius: 8px; font-weight: 600; }}
            .btn-back:hover {{ background: #5568d3; }}
            .fhir-json {{ background: #f7fafc; padding: 1rem; border-radius: 8px; overflow-x: auto; }}
            .fhir-json pre {{ margin: 0; font-size: 0.875rem; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1><i class="ph ph-user-circle"></i> {name}</h1>
                <p>ID FHIR: {patient.get("id", "N/A")}</p>
            </div>
            <div class="content">
                <div class="section">
                    <h2>Datos de Identificación</h2>
                    <div class="field">
                        <div class="field-label">Número de Documento:</div>
                        <div class="field-value">{identifier}</div>
                    </div>
                    <div class="field">
                        <div class="field-label">Nombre Completo:</div>
                        <div class="field-value">{name}</div>
                    </div>
                    <div class="field">
                        <div class="field-label">Sexo:</div>
                        <div class="field-value">{gender_map.get(gender, gender)}</div>
                    </div>
                    <div class="field">
                        <div class="field-label">Fecha de Nacimiento:</div>
                        <div class="field-value">{birth_date}</div>
                    </div>
                </div>
                
                <div class="section">
                    <h2>Recurso FHIR Completo</h2>
                    <div class="fhir-json">
                        <pre>{str(patient)}</pre>
                    </div>
                </div>
                
                <a href="/consulta-hc" class="btn-back">
                    <i class="ph ph-arrow-left"></i> Volver a la lista
                </a>
            </div>
        </div>
    </body>
    </html>
    """


# ============================================================================
# ENDPOINTS FIRH ORIGINALES
# ============================================================================

FIRH_CAMPOS = {
    "usuario": [
        {"nombre": "documento_id", "tipo": "number", "etiqueta": "Documento ID", "requerido": True, "pk": True},
        {"nombre": "nombre_completo", "tipo": "text", "etiqueta": "Nombre completo", "requerido": True},
        {"nombre": "pais_nacionalidad", "tipo": "text", "etiqueta": "País nacionalidad"},
        {"nombre": "fecha_nacimiento", "tipo": "date", "etiqueta": "Fecha nacimiento"},
        {"nombre": "edad", "tipo": "number", "etiqueta": "Edad"},
        {"nombre": "sexo", "tipo": "text", "etiqueta": "Sexo"},
        {"nombre": "genero", "tipo": "text", "etiqueta": "Género"},
        {"nombre": "ocupacion", "tipo": "text", "etiqueta": "Ocupación"},
        {"nombre": "voluntad_anticipada", "tipo": "boolean", "etiqueta": "Voluntad anticipada"},
        {"nombre": "categoria_discapacidad", "tipo": "text", "etiqueta": "Categoría discapacidad"},
        {"nombre": "pais_residencia", "tipo": "text", "etiqueta": "País residencia"},
        {"nombre": "municipio_residencia", "tipo": "text", "etiqueta": "Municipio residencia"},
        {"nombre": "etnia", "tipo": "text", "etiqueta": "Etnia"},
        {"nombre": "comunidad_etnica", "tipo": "text", "etiqueta": "Comunidad étnica"},
        {"nombre": "zona_residencia", "tipo": "text", "etiqueta": "Zona residencia"},
    ],
    "atencion": [
        {"nombre": "documento_id", "tipo": "number", "etiqueta": "Documento ID (paciente)", "requerido": True},
        {"nombre": "entidad_salud", "tipo": "text", "etiqueta": "Entidad salud"},
        {"nombre": "fecha_ingreso", "tipo": "datetime-local", "etiqueta": "Fecha ingreso"},
        {"nombre": "modalidad_entrega", "tipo": "text", "etiqueta": "Modalidad entrega"},
        {"nombre": "entorno_atencion", "tipo": "text", "etiqueta": "Entorno atención"},
        {"nombre": "via_ingreso", "tipo": "text", "etiqueta": "Vía ingreso"},
        {"nombre": "causa_atencion", "tipo": "textarea", "etiqueta": "Causa atención"},
        {"nombre": "fecha_triage", "tipo": "datetime-local", "etiqueta": "Fecha triage"},
        {"nombre": "clasificacion_triage", "tipo": "text", "etiqueta": "Clasificación triage"},
    ],
    "tecnologia_salud": [
        {"nombre": "documento_id", "tipo": "number", "etiqueta": "Documento ID (para enrutar)", "requerido": True},
        {"nombre": "tecnologia_id", "tipo": "text", "etiqueta": "UUID tecnología", "requerido": True},
        {"nombre": "atencion_id", "tipo": "number", "etiqueta": "Atención ID", "requerido": True},
        {"nombre": "descripcion_medicamento", "tipo": "text", "etiqueta": "Descripción medicamento"},
        {"nombre": "dosis", "tipo": "text", "etiqueta": "Dosis"},
        {"nombre": "via_administracion", "tipo": "text", "etiqueta": "Vía administración"},
        {"nombre": "frecuencia", "tipo": "text", "etiqueta": "Frecuencia"},
        {"nombre": "dias_tratamiento", "tipo": "number", "etiqueta": "Días tratamiento"},
        {"nombre": "unidades_aplicadas", "tipo": "number", "etiqueta": "Unidades aplicadas"},
        {"nombre": "id_personal_salud", "tipo": "text", "etiqueta": "UUID profesional"},
        {"nombre": "finalidad_tecnologia", "tipo": "text", "etiqueta": "Finalidad tecnología"},
    ],
    "diagnostico": [
        {"nombre": "documento_id", "tipo": "number", "etiqueta": "Documento ID (para enrutar)", "requerido": True},
        {"nombre": "atencion_id", "tipo": "number", "etiqueta": "Atención ID", "requerido": True},
        {"nombre": "tipo_diagnostico_ingreso", "tipo": "text", "etiqueta": "Tipo diagnóstico ingreso"},
        {"nombre": "diagnostico_ingreso", "tipo": "text", "etiqueta": "Diagnóstico ingreso"},
        {"nombre": "tipo_diagnostico_egreso", "tipo": "text", "etiqueta": "Tipo diagnóstico egreso"},
        {"nombre": "diagnostico_egreso", "tipo": "text", "etiqueta": "Diagnóstico egreso"},
        {"nombre": "diagnostico_rel1", "tipo": "text", "etiqueta": "Diagnóstico rel 1"},
        {"nombre": "diagnostico_rel2", "tipo": "text", "etiqueta": "Diagnóstico rel 2"},
        {"nombre": "diagnostico_rel3", "tipo": "text", "etiqueta": "Diagnóstico rel 3"},
    ],
    "egreso": [
        {"nombre": "documento_id", "tipo": "number", "etiqueta": "Documento ID (para enrutar)", "requerido": True},
        {"nombre": "atencion_id", "tipo": "number", "etiqueta": "Atención ID", "requerido": True},
        {"nombre": "fecha_salida", "tipo": "datetime-local", "etiqueta": "Fecha salida"},
        {"nombre": "condicion_salida", "tipo": "text", "etiqueta": "Condición salida"},
        {"nombre": "diagnostico_muerte", "tipo": "text", "etiqueta": "Diagnóstico muerte"},
        {"nombre": "codigo_prestador", "tipo": "text", "etiqueta": "Código prestador"},
        {"nombre": "tipo_incapacidad", "tipo": "text", "etiqueta": "Tipo incapacidad"},
        {"nombre": "dias_incapacidad", "tipo": "number", "etiqueta": "Días incapacidad"},
        {"nombre": "dias_lic_maternidad", "tipo": "number", "etiqueta": "Días lic. maternidad"},
        {"nombre": "alergias", "tipo": "textarea", "etiqueta": "Alergias"},
        {"nombre": "antecedente_familiar", "tipo": "textarea", "etiqueta": "Antecedente familiar"},
        {"nombre": "riesgos_ocupacionales", "tipo": "textarea", "etiqueta": "Riesgos ocupacionales"},
        {"nombre": "responsable_egreso", "tipo": "text", "etiqueta": "Responsable egreso"},
    ],
    "profesional_salud": [
        {"nombre": "id_personal_salud", "tipo": "text", "etiqueta": "UUID profesional", "requerido": True},
        {"nombre": "nombre", "tipo": "text", "etiqueta": "Nombre", "requerido": True},
        {"nombre": "especialidad", "tipo": "text", "etiqueta": "Especialidad"},
    ],
}


@app.get("/api/firh/campos")
async def firh_campos():
    return FIRH_CAMPOS


class FirhCargarBody(BaseModel):
    tabla: str
    datos: dict


@app.post("/api/firh/cargar")
async def firh_cargar(body: FirhCargarBody):
    try:
        resultado = middleware.insertar_registro_firh(body.tabla, body.datos)
        return resultado
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# MÓDULO MÉDICO
# ============================================================================

@app.get("/medico", response_class=HTMLResponse)
@app.get("/medico/", response_class=HTMLResponse)
async def medico_page():
    """Dashboard del médico: búsqueda, historia clínica, atención, diagnóstico y prescripción"""
    return plantilla("medico.html")


class AtencionRequest(BaseModel):
    documento_id: int
    sede_id: Optional[int] = None
    entidad_salud: str = ""
    fecha_ingreso: str
    modalidad_entrega: str = ""
    entorno_atencion: str = ""
    via_ingreso: str = ""
    causa_atencion: str = ""
    fecha_triage: str = None
    clasificacion_triage: str = None


class DiagnosticoRequest(BaseModel):
    documento_id: int
    sede_id: Optional[int] = None
    atencion_id: int
    tipo_diagnostico_ingreso: str = None
    diagnostico_ingreso: str = None
    tipo_diagnostico_egreso: str = None
    diagnostico_egreso: str = None
    diagnostico_rel1: str = None
    diagnostico_rel2: str = None
    diagnostico_rel3: str = None


class MedicamentoItem(BaseModel):
    documento_id: int
    sede_id: Optional[int] = None
    atencion_id: int
    tecnologia_id: str = None
    descripcion_medicamento: str = None
    dosis: str = None
    via_administracion: str = None
    frecuencia: str = None
    dias_tratamiento: int = None
    unidades_aplicadas: int = None


class PrescripcionRequest(BaseModel):
    medicamentos: list[MedicamentoItem]


def _conectar_nodo(doc_id: int, sede_id: Optional[int] = None):
    """
    Conexión al nodo donde debe escribirse.

    Con `sede_id` se escribe en la sede donde ocurre la atención (es el caso
    normal: el médico atiende en una sede). Sin sede, se aplica la
    fragmentación por rango de documento del repositorio de referencia.
    """
    sede = sedes.sede(sede_id) if sede_id else sedes.nodo_por_documento(doc_id)
    conn = db.conectar(sede, timeout=5)
    return conn, f"nodo{sede['sede_id']} ({sede['nodo']} · {sede['nombre']})"


@app.get("/api/v1/medico/historia/{documento_id}")
async def historia_clinica(documento_id: int,
                           claims: dict = Depends(auth.requiere("historia:otros"))):
    """
    Retorna la historia clínica completa de un paciente desde la DB distribuida:
    atenciones, diagnósticos y medicamentos.
    """
    try:
        conn, nodo = _conectar_nodo(documento_id)
        from psycopg2.extras import RealDictCursor
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Atenciones
            cur.execute(
                "SELECT * FROM atencion WHERE documento_id = %s ORDER BY fecha_ingreso DESC;",
                (documento_id,)
            )
            atenciones = [dict(r) for r in cur.fetchall()]

            # IDs de atenciones para joins
            ids = [a["atencion_id"] for a in atenciones]

            diagnosticos = []
            medicamentos = []
            if ids:
                cur.execute(
                    "SELECT * FROM diagnostico WHERE atencion_id = ANY(%s);", (ids,)
                )
                diagnosticos = [dict(r) for r in cur.fetchall()]

                cur.execute(
                    "SELECT * FROM tecnologia_salud WHERE atencion_id = ANY(%s);", (ids,)
                )
                medicamentos = [dict(r) for r in cur.fetchall()]

        conn.close()

        # serializar campos no JSON-serializable (fechas, UUID)
        import json
        from datetime import date, datetime
        from uuid import UUID

        def serial(obj):
            if isinstance(obj, (datetime, date)): return obj.isoformat()
            if isinstance(obj, UUID): return str(obj)
            raise TypeError(f"{type(obj)} not serializable")

        return {
            "documento_id": documento_id,
            "nodo": nodo,
            "total_atenciones": len(atenciones),
            "total_diagnosticos": len(diagnosticos),
            "total_medicamentos": len(medicamentos),
            "atenciones":   json.loads(json.dumps(atenciones, default=serial)),
            "diagnosticos": json.loads(json.dumps(diagnosticos, default=serial)),
            "medicamentos": json.loads(json.dumps(medicamentos, default=serial)),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error consultando historia: {str(e)}")


@app.post("/api/v1/medico/atencion")
async def registrar_atencion(data: AtencionRequest,
                             claims: dict = Depends(auth.requiere("atencion:abrir"))):
    """Registra una nueva atención en el nodo distribuido correcto."""
    try:
        conn, nodo = _conectar_nodo(data.documento_id, data.sede_id)
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO atencion
                  (documento_id, entidad_salud, fecha_ingreso, modalidad_entrega,
                   entorno_atencion, via_ingreso, causa_atencion, fecha_triage, clasificacion_triage)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING atencion_id;
            """, (
                data.documento_id,
                data.entidad_salud or None,
                data.fecha_ingreso,
                data.modalidad_entrega or None,
                data.entorno_atencion or None,
                data.via_ingreso or None,
                data.causa_atencion or None,
                data.fecha_triage or None,
                data.clasificacion_triage or None,
            ))
            atencion_id = cur.fetchone()[0]
            conn.commit()
        conn.close()
        sello = auth.registrar_acceso(claims, "abrir_atencion", f"documento:{data.documento_id}", "ok",
                                      {"atencion_id": atencion_id, "nodo": nodo,
                                       "triage": data.clasificacion_triage})
        return {"success": True, "atencion_id": atencion_id, "nodo": nodo,
                "sello_auditoria": (sello or {}).get("hash")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error registrando atención: {str(e)}")


@app.post("/api/v1/medico/diagnostico")
async def registrar_diagnostico(data: DiagnosticoRequest,
                                claims: dict = Depends(auth.requiere("clinico:escribir"))):
    """Guarda un diagnóstico vinculado a una atención en el nodo correcto."""
    try:
        conn, nodo = _conectar_nodo(data.documento_id, data.sede_id)
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO diagnostico
                  (atencion_id, tipo_diagnostico_ingreso, diagnostico_ingreso,
                   tipo_diagnostico_egreso, diagnostico_egreso,
                   diagnostico_rel1, diagnostico_rel2, diagnostico_rel3)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING diagnostico_id;
            """, (
                data.atencion_id,
                data.tipo_diagnostico_ingreso,
                data.diagnostico_ingreso,
                data.tipo_diagnostico_egreso,
                data.diagnostico_egreso,
                data.diagnostico_rel1,
                data.diagnostico_rel2,
                data.diagnostico_rel3,
            ))
            dx_id = cur.fetchone()[0]
            conn.commit()
        conn.close()
        sello = auth.registrar_acceso(claims, "registrar_diagnostico",
                                      f"documento:{data.documento_id}", "ok",
                                      {"diagnostico_id": dx_id, "atencion_id": data.atencion_id,
                                       "nodo": nodo})
        return {"success": True, "diagnostico_id": dx_id, "nodo": nodo,
                "sello_auditoria": (sello or {}).get("hash")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error guardando diagnóstico: {str(e)}")


@app.post("/api/v1/medico/prescripcion")
async def guardar_prescripcion(body: PrescripcionRequest,
                               claims: dict = Depends(auth.requiere("clinico:escribir"))):
    """Guarda uno o más medicamentos (tecnologia_salud) en el nodo correcto."""
    if not body.medicamentos:
        raise HTTPException(status_code=400, detail="Sin medicamentos")
    doc_id = body.medicamentos[0].documento_id
    try:
        conn, nodo = _conectar_nodo(doc_id, body.medicamentos[0].sede_id)
        inserted = 0
        with conn.cursor() as cur:
            for m in body.medicamentos:
                import uuid
                tid = m.tecnologia_id or str(uuid.uuid4())
                cur.execute("""
                    INSERT INTO tecnologia_salud
                      (tecnologia_id, atencion_id, descripcion_medicamento, dosis,
                       via_administracion, frecuencia, dias_tratamiento, unidades_aplicadas)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s);
                """, (
                    tid, m.atencion_id, m.descripcion_medicamento, m.dosis,
                    m.via_administracion, m.frecuencia, m.dias_tratamiento, m.unidades_aplicadas,
                ))
                inserted += 1
            conn.commit()
        conn.close()
        sello = auth.registrar_acceso(claims, "formular_tecnologias", f"documento:{doc_id}", "ok",
                                      {"total": inserted, "nodo": nodo})
        return {"success": True, "total": inserted, "nodo": nodo,
                "sello_auditoria": (sello or {}).get("hash")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error guardando prescripción: {str(e)}")


class EgresoRequest(BaseModel):
    documento_id: int
    sede_id: Optional[int] = None
    atencion_id: int
    fecha_salida: Optional[str] = None
    condicion_salida: Optional[str] = None
    diagnostico_muerte: Optional[str] = None
    codigo_prestador: Optional[str] = None
    tipo_incapacidad: Optional[str] = None
    dias_incapacidad: Optional[int] = None
    dias_lic_maternidad: Optional[int] = None
    alergias: Optional[str] = None
    antecedente_familiar: Optional[str] = None
    riesgos_ocupacionales: Optional[str] = None
    responsable_egreso: Optional[str] = None


@app.post("/api/v1/medico/egreso", tags=["medico"],
          summary="Registra el egreso de una atención, con sello de integridad")
async def registrar_egreso(data: EgresoRequest,
                           claims: dict = Depends(auth.requiere("clinico:escribir"))):
    """
    El egreso cierra la atención. La respuesta trae el sello: el hash del
    evento de auditoría, que además queda guardado en la fila del egreso.
    """
    # El sello se calcula antes de escribir y se guarda con el egreso: así la
    # fila queda atada al evento de la cadena.
    sello = auth.registrar_acceso(
        claims, "registrar_egreso", f"documento:{data.documento_id}", "ok",
        {"atencion_id": data.atencion_id, "condicion_salida": data.condicion_salida,
         "sede_id": data.sede_id},
    )
    hash_evento = (sello or {}).get("hash")

    try:
        conn, nodo = _conectar_nodo(data.documento_id, data.sede_id)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO egreso
                  (atencion_id, fecha_salida, condicion_salida, diagnostico_muerte,
                   codigo_prestador, tipo_incapacidad, dias_incapacidad, dias_lic_maternidad,
                   alergias, antecedente_familiar, riesgos_ocupacionales, responsable_egreso,
                   sello_integridad)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING egreso_id;
                """,
                (
                    data.atencion_id, data.fecha_salida, data.condicion_salida,
                    data.diagnostico_muerte, data.codigo_prestador, data.tipo_incapacidad,
                    data.dias_incapacidad, data.dias_lic_maternidad, data.alergias,
                    data.antecedente_familiar, data.riesgos_ocupacionales,
                    data.responsable_egreso or claims.get("nombre"), hash_evento,
                ),
            )
            egreso_id = cur.fetchone()[0]
            conn.commit()
        conn.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error registrando egreso: {str(e)}")

    return {"success": True, "egreso_id": egreso_id, "nodo": nodo,
            "sello_auditoria": hash_evento}


# ============================================================================
# ENDPOINTS DE GESTIÓN DE PROFESIONALES DE SALUD (MÉDICOS)
# ============================================================================

from app.fhir_app.models.patient_model import ProfesionalSaludData, ProfesionalSaludUpdate


@app.get("/api/v1/profesionales")
async def listar_profesionales(
    activos: bool = True,
    especialidad: str = None,
    limite: int = 100
):
    """
    Lista todos los profesionales de salud.

    Query params:
    - activos: Filtrar solo activos (default: true)
    - especialidad: Filtrar por especialidad (opcional)
    - limite: Límite de resultados (default: 100)
    """
    try:
        profesionales = DBService.listar_profesionales(
            activos_only=activos,
            especialidad=especialidad,
            limite=limite
        )
        return {
            "success": True,
            "total": len(profesionales),
            "profesionales": profesionales
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listando profesionales: {str(e)}")


@app.get("/api/v1/profesionales/{profesional_id}")
async def obtener_profesional(profesional_id: str):
    """Obtiene un profesional por su ID."""
    try:
        profesional = DBService.obtener_profesional(profesional_id)
        if not profesional:
            raise HTTPException(status_code=404, detail="Profesional no encontrado")
        return {
            "success": True,
            "profesional": profesional
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error obteniendo profesional: {str(e)}")


@app.post("/api/v1/profesionales")
async def crear_profesional(data: ProfesionalSaludData):
    """
    Crea un nuevo profesional de salud.

    Campos requeridos:
    - nombre: Nombre completo del profesional

    Campos opcionales:
    - especialidad, registroMedico, entidadSalud, email, telefono, activo
    """
    try:
        resultado = DBService.crear_profesional(data.dict())
        return resultado
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creando profesional: {str(e)}")


@app.put("/api/v1/profesionales/{profesional_id}")
async def actualizar_profesional(profesional_id: str, data: ProfesionalSaludUpdate):
    """
    Actualiza un profesional existente.
    Solo actualiza los campos proporcionados.
    """
    try:
        resultado = DBService.actualizar_profesional(profesional_id, data.dict(exclude_unset=True))
        if not resultado:
            raise HTTPException(status_code=404, detail="Profesional no encontrado")
        return resultado
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error actualizando profesional: {str(e)}")


@app.delete("/api/v1/profesionales/{profesional_id}")
async def eliminar_profesional(profesional_id: str):
    """Elimina un profesional de la base de datos."""
    try:
        deleted = DBService.eliminar_profesional(profesional_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Profesional no encontrado")
        return {
            "success": True,
            "mensaje": "Profesional eliminado correctamente"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error eliminando profesional: {str(e)}")


@app.get("/api/v1/profesionales/buscar/{nombre}")
async def buscar_profesionales(nombre: str, limite: int = 20):
    """Busca profesionales por nombre (búsqueda parcial)."""
    try:
        profesionales = DBService.buscar_profesionales_por_nombre(nombre, limite)
        return {
            "success": True,
            "total": len(profesionales),
            "query": nombre,
            "profesionales": profesionales
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error buscando profesionales: {str(e)}")


# ============================================================================
# SEGURIDAD — autenticación con token y matriz de permisos (RF5, Fase 4)
# ============================================================================

class LoginBody(BaseModel):
    usuario: str
    password: str


@app.post("/auth/login", tags=["seguridad"], summary="Inicia sesión y entrega un token JWT")
async def login(body: LoginBody):
    registro = seguridad.autenticar(body.usuario, body.password)
    if registro is None:
        auditoria.registrar(body.usuario, "", "login_denegado", "auth", "denegado",
                            {"motivo": "usuario o clave incorrectos"})
        raise HTTPException(status_code=401, detail="Usuario o clave incorrectos")

    token = seguridad.emitir_token(body.usuario, registro)
    sello = auditoria.registrar(body.usuario, registro["rol"], "login", "auth", "ok",
                                {"sede_id": registro.get("sede_id")})
    return {**token, "sello_auditoria": (sello or {}).get("hash")}


@app.get("/auth/yo", tags=["seguridad"], summary="Quién soy y qué puedo hacer")
async def quien_soy(claims: dict = Depends(auth.requiere_sesion)):
    return {
        "usuario": claims.get("sub"),
        "nombre": claims.get("nombre"),
        "rol": claims.get("rol"),
        "documento": claims.get("documento"),
        "sede_id": claims.get("sede_id"),
        "permisos": claims.get("permisos", []),
        "expira": claims.get("exp"),
    }


@app.get("/auth/matriz", tags=["seguridad"], summary="Matriz de permisos por rol")
async def matriz_permisos():
    """Tabla de la Fase 4, Paso 1: qué puede hacer cada rol. Sirve de evidencia
    en el informe y la usan las vistas para ocultar lo que no corresponde."""
    acciones = [
        ("Ver su propia historia", "historia:propia"),
        ("Ver la historia de otro paciente", "historia:otros"),
        ("Buscar pacientes", "paciente:buscar"),
        ("Registrar o admitir un paciente", "paciente:registrar"),
        ("Abrir una atención", "atencion:abrir"),
        ("Registrar diagnóstico, fórmula o egreso", "clinico:escribir"),
        ("Ver diagnósticos y notas clínicas", "diagnostico:ver"),
        ("Generar el Reporte de HC de otro paciente", "reporte:generar"),
        ("Ver el estado de la plataforma", "plataforma:estado"),
        ("Leer la auditoría completa", "auditoria:leer"),
        ("Apagar o encender un nodo (demo)", "nodo:controlar"),
        ("Enviar o reencolar mensajes del bus", "bus:enviar"),
    ]
    return {
        "roles": list(seguridad.ROLES),
        "matriz": [
            {
                "accion": etiqueta,
                "permiso": permiso,
                **{rol: seguridad.tiene_permiso(rol, permiso) for rol in seguridad.ROLES},
            }
            for etiqueta, permiso in acciones
        ],
        "permisos_por_rol": {rol: seguridad.permisos_de(rol) for rol in seguridad.ROLES},
    }


@app.get("/auth/usuarios-prueba", tags=["seguridad"], summary="Usuarios sintéticos de prueba")
async def usuarios_prueba():
    """Lista los usuarios de demostración (las claves están en el README y en
    .env.example; nunca se guardan secretos reales en el repositorio)."""
    return {
        "aviso": "Usuarios sintéticos de demostración. Las claves se configuran por variables de entorno.",
        "usuarios": [
            {
                "usuario": nombre,
                "rol": datos["rol"],
                "nombre": datos["nombre"],
                "documento": datos.get("documento"),
                "sede_id": datos.get("sede_id"),
            }
            for nombre, datos in seguridad.USUARIOS.items()
        ],
    }


# ============================================================================
# VISTAS POR ROL (HTML)
# ============================================================================

@app.get("/login", response_class=HTMLResponse, tags=["vistas"])
@app.get("/login/", response_class=HTMLResponse, include_in_schema=False)
async def vista_login():
    """Pantalla de inicio de sesión común a las cuatro vistas."""
    return plantilla("login.html")


@app.get("/paciente", response_class=HTMLResponse, tags=["vistas"])
@app.get("/paciente/", response_class=HTMLResponse, include_in_schema=False)
async def vista_paciente():
    """Vista Paciente: su historia unificada, su Bundle FHIR y quién accedió."""
    return plantilla("paciente.html")


@app.get("/reporte-hc", response_class=HTMLResponse, tags=["vistas"])
@app.get("/reporte-hc/", response_class=HTMLResponse, include_in_schema=False)
async def vista_reporte_hc():
    """Vista Reporte de HC: reporte por sede, cobertura, sello y tablero."""
    return plantilla("reporte-hc.html")


# ============================================================================
# CONSULTA UNIFICADA DE LAS TRES SEDES (RF4)
# ============================================================================

@app.get("/api/v1/historia/{documento_id}", tags=["historia"],
         summary="Historia clínica unificada de un paciente en las 3 sedes")
async def historia_unificada(documento_id: int, claims: dict = Depends(auth.requiere_sesion)):
    """
    Una sola consulta recorre las tres sedes en paralelo. Si una sede no
    responde, la respuesta llega igual con las otras dos y marca `parcial`.
    """
    rol = claims.get("rol", "")
    if not (seguridad.tiene_permiso(rol, "historia:otros") or seguridad.tiene_permiso(rol, "historia:propia")):
        auth.registrar_acceso(claims, "acceso_denegado", f"paciente:{documento_id}", "denegado",
                              {"motivo": "el rol no puede leer historias"})
        raise HTTPException(status_code=403, detail=f"El rol '{rol}' no puede consultar historias clínicas")
    auth.verificar_acceso_documento(claims, documento_id)

    historia = consulta_unificada.historia_unificada(documento_id)

    # El admisionista no ve contenido clínico (mínimo necesario).
    if not seguridad.tiene_permiso(rol, "diagnostico:ver") and rol == seguridad.ROL_ADMISIONISTA:
        historia = _ocultar_clinico(historia)

    sello = auth.registrar_acceso(
        claims, "leer_historia", f"paciente:{documento_id}", "ok",
        {"sedes_disponibles": historia["sedes_disponibles"], "parcial": historia["parcial"]},
    )
    historia["sello_auditoria"] = (sello or {}).get("hash")
    return historia


def _ocultar_clinico(historia: dict) -> dict:
    """Quita diagnósticos, laboratorio y fórmulas: lo que el admisionista no debe ver."""
    for sede in historia.get("sedes", []):
        for atencion in sede.get("atenciones", []):
            atencion["diagnosticos"] = []
            atencion["observaciones"] = []
            atencion["medicamentos"] = []
            atencion["egreso"] = None
            atencion["oculto_por_rol"] = "El rol admisionista no ve contenido clínico"
    for atencion in historia.get("atenciones", []):
        atencion["diagnosticos"] = []
        atencion["observaciones"] = []
        atencion["medicamentos"] = []
        atencion["egreso"] = None
    historia["resumen"]["diagnosticos"] = None
    historia["resumen"]["observaciones"] = None
    historia["resumen"]["medicamentos"] = None
    historia["nota_rol"] = "Vista de admisión: sin diagnósticos ni notas clínicas"
    return historia


@app.get("/api/v1/pacientes/buscar", tags=["historia"],
         summary="Busca pacientes por nombre o documento en las 3 sedes")
async def buscar_pacientes_unificado(nombre: str = "", documento: str = "",
                                     claims: dict = Depends(auth.requiere("paciente:buscar"))):
    if not nombre and not documento:
        raise HTTPException(status_code=400, detail="Indique 'nombre' o 'documento'")

    if documento:
        try:
            doc = int(documento)
        except ValueError:
            raise HTTPException(status_code=400, detail="El documento debe ser numérico")
        resultado = DBService.buscar_en_todas_las_sedes(doc)
        auth.registrar_acceso(claims, "buscar_paciente", f"documento:{doc}", "ok",
                              {"sedes": resultado["sedes_con_registro"]})
        return {
            "modo": "documento",
            **consulta_unificada.serializable(resultado),
            "duplicado_entre_sedes": len(resultado["sedes_con_registro"]) > 1,
        }

    resultado = consulta_unificada.buscar_por_nombre(nombre)
    auth.registrar_acceso(claims, "buscar_paciente", f"nombre:{nombre}", "ok",
                          {"encontrados": resultado["total"]})
    return {"modo": "nombre", **resultado}


@app.get("/api/v1/pacientes/{documento_id}/sedes", tags=["historia"],
         summary="En qué sedes existe el paciente (detección de duplicados)")
async def sedes_del_paciente(documento_id: int, claims: dict = Depends(auth.requiere("paciente:buscar"))):
    resultado = DBService.buscar_en_todas_las_sedes(documento_id)
    return {
        **consulta_unificada.serializable(resultado),
        "duplicado_entre_sedes": len(resultado["sedes_con_registro"]) > 1,
        "regla_de_coincidencia": "documento exacto (identificador común de las 3 sedes)",
    }


# ============================================================================
# EVIDENCIAS DE LA CAPA DE DATOS (Fase 2)
# ============================================================================

@app.get("/api/v1/datos/explain", tags=["datos"],
         summary="EXPLAIN ANALYZE de la consulta distribuida por documento")
async def explain_consulta(documento: int = Query(1001),
                           claims: dict = Depends(auth.requiere("plataforma:estado"))):
    return consulta_unificada.explicar_consulta(documento)


@app.post("/api/v1/datos/prueba-acid", tags=["datos"],
          summary="Transacción atómica: escribe y falla a la mitad")
async def prueba_acid(sede: int = Query(1, ge=1, le=3),
                      claims: dict = Depends(auth.requiere("plataforma:estado"))):
    resultado = consulta_unificada.prueba_acid(sede)
    auth.registrar_acceso(claims, "prueba_acid", f"sede:{sede}",
                          "ok" if resultado["atomica"] else "error", resultado)
    return resultado


@app.get("/api/v1/datos/cobertura", tags=["datos"], summary="Cobertura FHIR por sede")
async def cobertura_fhir():
    """Pública: alimenta el tablero y la demostración de 0 % → 100 %."""
    cobertura = db.cobertura_fhir_por_sede()
    total = sum(c["total"] for c in cobertura if c["disponible"])
    migrados = sum(c["migrados"] for c in cobertura if c["disponible"])
    return {
        "por_sede": cobertura,
        "global": {
            "total": total,
            "migrados": migrados,
            "cobertura_pct": round(100.0 * migrados / total, 1) if total else 0.0,
        },
    }


# ============================================================================
# REPORTE DE HC (cuarta vista)
# ============================================================================

def _reporte_para(documento_id: int, claims: dict) -> dict:
    rol = claims.get("rol", "")
    if rol == seguridad.ROL_PACIENTE:
        auth.verificar_acceso_documento(claims, documento_id, accion="generar_reporte")
    elif not seguridad.tiene_permiso(rol, "reporte:generar"):
        auth.registrar_acceso(claims, "acceso_denegado", f"reporte:{documento_id}", "denegado",
                              {"motivo": "el rol no puede generar reportes de otros"})
        raise HTTPException(status_code=403, detail=f"El rol '{rol}' no puede generar el Reporte de HC")

    historia = consulta_unificada.historia_unificada(documento_id)
    if not historia["encontrado"] and not historia["atenciones"]:
        raise HTTPException(status_code=404,
                            detail=f"No hay registros del documento {documento_id} en las sedes disponibles")
    return reporte.construir(historia, claims.get("sub", "?"), rol)


@app.get("/api/v1/reporte/{documento_id}", tags=["reporte"],
         summary="Reporte de HC unificado (JSON) con cobertura y sello")
async def reporte_hc(documento_id: int, claims: dict = Depends(auth.requiere_sesion)):
    datos = _reporte_para(documento_id, claims)
    sello = auth.registrar_acceso(
        claims, "generar_reporte", f"paciente:{documento_id}", "ok",
        {"completo": datos["completo"], "sello": datos["sello_integridad"],
         "cobertura_pct": datos["cobertura_campos"]["cobertura_pct"]},
    )
    datos["sello_auditoria"] = (sello or {}).get("hash")
    return datos


@app.get("/api/v1/reporte/{documento_id}/html", response_class=HTMLResponse, tags=["reporte"],
         summary="Reporte de HC imprimible (HTML → PDF con Ctrl+P)")
async def reporte_hc_html(documento_id: int, claims: dict = Depends(auth.requiere_sesion)):
    datos = _reporte_para(documento_id, claims)
    auth.registrar_acceso(claims, "exportar_reporte", f"paciente:{documento_id}", "ok",
                          {"formato": "html", "sello": datos["sello_integridad"]})
    return HTMLResponse(content=reporte.a_html(datos))


@app.get("/api/v1/reporte/{documento_id}/bundle", tags=["reporte"],
         summary="Bundle FHIR (document) de la historia unificada")
async def reporte_hc_bundle(documento_id: int, claims: dict = Depends(auth.requiere_sesion)):
    rol = claims.get("rol", "")
    if rol == seguridad.ROL_PACIENTE:
        auth.verificar_acceso_documento(claims, documento_id, accion="descargar_bundle")
    elif not seguridad.tiene_permiso(rol, "bundle:otros"):
        raise HTTPException(status_code=403, detail=f"El rol '{rol}' no puede descargar Bundles de otros")

    historia = consulta_unificada.historia_unificada(documento_id)
    bundle = reporte.bundle_del_paciente(historia)
    if bundle is None:
        raise HTTPException(status_code=404, detail=f"Sin datos del documento {documento_id}")
    auth.registrar_acceso(claims, "descargar_bundle", f"paciente:{documento_id}", "ok",
                          {"recursos": len(bundle.get("entry", []))})
    return bundle


@app.get("/api/v1/reporte/{documento_id}/bundle/validar", tags=["reporte"],
         summary="Valida el Bundle contra HAPI ($validate)")
async def validar_bundle_paciente(documento_id: int,
                                  claims: dict = Depends(auth.requiere("plataforma:estado"))):
    historia = consulta_unificada.historia_unificada(documento_id)
    bundle = reporte.bundle_del_paciente(historia)
    if bundle is None:
        raise HTTPException(status_code=404, detail=f"Sin datos del documento {documento_id}")
    try:
        return {"documento_id": documento_id, **cliente_hapi.validar_bundle(bundle)}
    except cliente_hapi.ErrorHapi as exc:
        raise HTTPException(status_code=503, detail=f"HAPI no disponible: {exc}") from exc


# ============================================================================
# VISTA PACIENTE
# ============================================================================

@app.get("/api/v1/paciente/mi-historia", tags=["paciente"],
         summary="El paciente consulta su propia historia unificada")
async def mi_historia(claims: dict = Depends(auth.requiere("historia:propia"))):
    documento = claims.get("documento")
    if documento is None:
        raise HTTPException(status_code=400, detail="La sesión no tiene documento asociado")
    historia = consulta_unificada.historia_unificada(int(documento))
    sello = auth.registrar_acceso(claims, "leer_historia", f"paciente:{documento}", "ok",
                                  {"propia": True, "parcial": historia["parcial"]})
    historia["sello_auditoria"] = (sello or {}).get("hash")
    return historia


@app.get("/api/v1/paciente/mis-accesos", tags=["paciente"],
         summary="Quién accedió a mi historia y cuándo")
async def mis_accesos(limite: int = Query(50, ge=1, le=200),
                      claims: dict = Depends(auth.requiere("auditoria:propia"))):
    documento = claims.get("documento")
    if documento is None:
        raise HTTPException(status_code=400, detail="La sesión no tiene documento asociado")
    try:
        eventos = auditoria.listar(limite=limite, recurso=f"paciente:{documento}")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Auditoría no disponible: {exc}") from exc
    return {
        "documento": documento,
        "total": len(eventos),
        "accesos": [
            {
                "evento_id": e["evento_id"],
                "cuando": e["ts"].isoformat() if hasattr(e["ts"], "isoformat") else str(e["ts"]),
                "quien": e["actor"],
                "rol": e["rol"],
                "accion": e["accion"],
                "resultado": e["resultado"],
                "sello": e["hash"][:16],
            }
            for e in eventos
        ],
    }


@app.get("/api/v1/paciente/mi-bundle", tags=["paciente"],
         summary="El paciente descarga su Bundle FHIR")
async def mi_bundle(claims: dict = Depends(auth.requiere("bundle:propio"))):
    documento = claims.get("documento")
    if documento is None:
        raise HTTPException(status_code=400, detail="La sesión no tiene documento asociado")
    historia = consulta_unificada.historia_unificada(int(documento))
    bundle = reporte.bundle_del_paciente(historia)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Todavía no hay datos suyos en las sedes disponibles")
    auth.registrar_acceso(claims, "descargar_bundle", f"paciente:{documento}", "ok",
                          {"propio": True, "recursos": len(bundle.get("entry", []))})
    return bundle


# ============================================================================
# AUDITORÍA ENCADENADA POR HASH
# ============================================================================

@app.get("/api/v1/auditoria", tags=["auditoria"], summary="Eventos de la cadena de auditoría")
async def listar_auditoria(limite: int = Query(100, ge=1, le=1000), actor: Optional[str] = None,
                           claims: dict = Depends(auth.requiere("auditoria:leer"))):
    try:
        eventos = auditoria.listar(limite=limite, actor=actor)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Auditoría no disponible: {exc}") from exc
    return {
        "total": len(eventos),
        "eventos": [consulta_unificada.serializable(e) for e in eventos],
    }


@app.get("/api/v1/auditoria/verificar", tags=["auditoria"],
         summary="Verificador de integridad: recorre la cadena y señala el primer evento alterado")
async def verificar_auditoria(claims: dict = Depends(auth.requiere("plataforma:estado"))):
    try:
        resultado = auditoria.verificar_cadena()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Auditoría no disponible: {exc}") from exc
    return resultado


@app.get("/api/v1/auditoria/{evento_id}/fhir", tags=["auditoria"],
         summary="El evento como AuditEvent de FHIR R4")
async def auditoria_fhir(evento_id: int, claims: dict = Depends(auth.requiere("auditoria:leer"))):
    try:
        with db.cursor_central() as cur:
            cur.execute("SELECT * FROM evento_auditoria WHERE evento_id = %s;", (evento_id,))
            fila = cur.fetchone()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Auditoría no disponible: {exc}") from exc
    if fila is None:
        raise HTTPException(status_code=404, detail="Evento no encontrado")
    return auditoria.a_fhir_auditevent(dict(fila))


# ============================================================================
# TABLERO DE ESTADO DE LA PLATAFORMA (dentro del Reporte de HC)
# ============================================================================

async def _metricas_hsb() -> dict:
    try:
        async with httpx.AsyncClient(timeout=5.0) as cli:
            r = await cli.get(f"{sedes.HSB_BASE_URL}/metrics.json")
            r.raise_for_status()
            return r.json()
    except Exception as exc:
        return {"disponible": False, "error": str(exc)}


@app.get("/api/v1/plataforma/estado", tags=["plataforma"],
         summary="Tablero: nodos, cobertura FHIR, bus y verificación de auditoría")
async def estado_plataforma(claims: dict = Depends(auth.requiere("plataforma:estado"))):
    estado_sedes = db.estado_sedes()
    cobertura = db.cobertura_fhir_por_sede()
    hapi = await cliente_hapi.a_salud()
    bus = await _metricas_hsb()
    try:
        integridad = auditoria.verificar_cadena()
    except Exception as exc:
        integridad = {"integra": None, "error": str(exc)}

    total = sum(c["total"] for c in cobertura if c["disponible"])
    migrados = sum(c["migrados"] for c in cobertura if c["disponible"])

    return {
        "sedes": estado_sedes,
        "sedes_disponibles": f"{sum(1 for s in estado_sedes if s['disponible'])}/3",
        "almacen_central": db.ping(sedes.CENTRAL),
        "hapi_fhir": {"disponible": hapi.get("disponible"), "fhir_version": hapi.get("fhir_version")},
        "cobertura_fhir": {
            "por_sede": cobertura,
            "global_pct": round(100.0 * migrados / total, 1) if total else 0.0,
        },
        "bus": bus,
        "auditoria": integridad,
        "terminologia": terminologia.origen(),
    }


@app.post("/api/v1/plataforma/nodos/{sede_id}/{accion}", tags=["plataforma"],
          summary="Apaga o enciende el nodo de una sede (demo de resiliencia)")
async def controlar_nodo(sede_id: int, accion: str,
                         claims: dict = Depends(auth.requiere("nodo:controlar"))):
    """
    Solo el rol auditor puede hacerlo, y queda en la auditoría. Requiere que el
    contenedor tenga montado el socket de Docker; si no, devuelve el comando
    equivalente para ejecutarlo desde el host.
    """
    if accion not in ("stop", "start", "restart"):
        raise HTTPException(status_code=400, detail="La acción debe ser stop, start o restart")
    sede = sedes.sede(sede_id)
    contenedor = sede["nodo"]
    comando = f"docker compose {'stop' if accion == 'stop' else accion} {contenedor}"

    resultado: Dict[str, Any] = {"sede_id": sede_id, "nodo": contenedor, "accion": accion,
                                 "comando_equivalente": comando}
    socket_docker = "/var/run/docker.sock"
    if os.path.exists(socket_docker):
        try:
            transporte = httpx.AsyncHTTPTransport(uds=socket_docker)
            async with httpx.AsyncClient(transport=transporte, base_url="http://docker", timeout=20.0) as cli:
                r = await cli.post(f"/v1.41/containers/{contenedor}/{accion}")
                resultado["ejecutado"] = r.status_code in (204, 304)
                resultado["respuesta_docker"] = r.status_code
        except Exception as exc:
            resultado["ejecutado"] = False
            resultado["error"] = str(exc)
    else:
        resultado["ejecutado"] = False
        resultado["nota"] = "Sin acceso al socket de Docker: ejecute el comando desde el host"

    auth.registrar_acceso(claims, f"nodo_{accion}", f"sede:{sede_id}",
                          "ok" if resultado.get("ejecutado") else "error", resultado)
    return resultado


# ============================================================================
# PUENTE CON EL BUS (las vistas no hablan con las sedes, hablan con el bus)
# ============================================================================

@app.get("/api/v1/bus/mensajes", tags=["bus"], summary="Estado de los mensajes enviados al bus")
async def bus_mensajes(estado: Optional[str] = None, sede: Optional[int] = None,
                       limite: int = Query(50, ge=1, le=500),
                       claims: dict = Depends(auth.requiere("bus:estado"))):
    params: Dict[str, Any] = {"limite": limite}
    if estado:
        params["estado"] = estado
    if sede:
        params["sede"] = sede
    try:
        async with httpx.AsyncClient(timeout=10.0) as cli:
            r = await cli.get(f"{sedes.HSB_BASE_URL}/hsb/mensajes", params=params)
            r.raise_for_status()
            return r.json()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"El bus no responde: {exc}") from exc


@app.get("/api/v1/bus/metricas", tags=["bus"], summary="Métricas del bus")
async def bus_metricas(claims: dict = Depends(auth.requiere("bus:estado"))):
    return await _metricas_hsb()


@app.post("/api/v1/bus/hl7", tags=["bus"], summary="Envía un mensaje HL7 v2 al bus")
async def bus_enviar_hl7(request: Request, claims: dict = Depends(auth.requiere("bus:enviar"))):
    crudo = (await request.body()).decode("utf-8", errors="replace")
    try:
        async with httpx.AsyncClient(timeout=60.0) as cli:
            r = await cli.post(f"{sedes.HSB_BASE_URL}/hsb/hl7", content=crudo.encode("utf-8"),
                               headers={"Content-Type": "text/plain; charset=utf-8"})
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"El bus no responde: {exc}") from exc
    cuerpo = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"raw": r.text}
    auth.registrar_acceso(claims, "bus_envio_manual", "hsb:hl7",
                          "ok" if r.status_code < 400 else "error",
                          {"estado_http": r.status_code, "resultado": cuerpo.get("resultado")})
    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail=cuerpo)
    return cuerpo


@app.post("/api/v1/bus/csv", tags=["bus"], summary="Envía un CSV legado al bus")
async def bus_enviar_csv(request: Request, sede: int = Query(..., ge=1, le=3),
                         claims: dict = Depends(auth.requiere("bus:enviar"))):
    crudo = (await request.body()).decode("utf-8", errors="replace")
    try:
        async with httpx.AsyncClient(timeout=120.0) as cli:
            r = await cli.post(f"{sedes.HSB_BASE_URL}/hsb/csv", params={"sede": sede},
                               content=crudo.encode("utf-8"),
                               headers={"Content-Type": "text/csv; charset=utf-8"})
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"El bus no responde: {exc}") from exc
    cuerpo = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"raw": r.text}
    auth.registrar_acceso(claims, "bus_envio_manual", f"hsb:csv:sede{sede}",
                          "ok" if r.status_code < 400 else "error",
                          {"estado_http": r.status_code, "resumen": cuerpo.get("resumen")})
    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail=cuerpo)
    return cuerpo


@app.post("/api/v1/bus/migrar", tags=["bus"],
          summary="Normaliza a FHIR el legado de una sede (cobertura 0 % → 100 %)")
async def bus_migrar(sede: int = Query(..., ge=1, le=3),
                     claims: dict = Depends(auth.requiere("bus:enviar"))):
    try:
        async with httpx.AsyncClient(timeout=300.0) as cli:
            r = await cli.post(f"{sedes.HSB_BASE_URL}/hsb/migrar", params={"sede": sede})
            r.raise_for_status()
            cuerpo = r.json()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"El bus no responde: {exc}") from exc
    auth.registrar_acceso(claims, "migrar_sede", f"sede:{sede}", "ok",
                          {"resumen": cuerpo.get("resumen")})
    return cuerpo


@app.post("/api/v1/bus/mensajes/{mensaje_id}/reencolar", tags=["bus"],
          summary="Devuelve un mensaje muerto a la cola")
async def bus_reencolar(mensaje_id: int, authorization: Optional[str] = Header(None),
                        claims: dict = Depends(auth.requiere("bus:enviar"))):
    try:
        async with httpx.AsyncClient(timeout=60.0) as cli:
            r = await cli.post(f"{sedes.HSB_BASE_URL}/hsb/mensajes/{mensaje_id}/reencolar",
                               headers={"Authorization": authorization or ""})
            r.raise_for_status()
            return r.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"El bus no responde: {exc}") from exc


@app.get("/api/v1/bus/muertos", tags=["bus"], summary="Cola de mensajes muertos")
async def bus_muertos(claims: dict = Depends(auth.requiere("bus:estado"))):
    try:
        async with httpx.AsyncClient(timeout=10.0) as cli:
            r = await cli.get(f"{sedes.HSB_BASE_URL}/hsb/muertos")
            r.raise_for_status()
            return r.json()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"El bus no responde: {exc}") from exc


@app.get("/api/v1/terminologia", tags=["bus"], summary="Mapeo CIE-10 y LOINC (ConceptMap)")
async def ver_terminologia_api():
    tabla = terminologia.tabla()
    return {
        "origen": terminologia.origen(),
        "cie10": [{"dx_local": k, **v} for k, v in sorted(tabla.items())],
        "loinc": [{"prueba_local": k, **v} for k, v in sorted(terminologia.LOINC_LOCAL.items())],
        "concept_map": terminologia.concept_map(),
    }


# ============================================================================
# OBSERVABILIDAD (/health y /metrics en cada servicio — RNF)
# ============================================================================

@app.get("/health", tags=["observabilidad"], summary="Estado de la API y de sus dependencias")
async def health_api(response: Response):
    central = db.ping(sedes.CENTRAL)
    estado_sedes = db.estado_sedes()
    arriba = sum(1 for s in estado_sedes if s["disponible"])
    hapi = await cliente_hapi.a_salud()

    bus: Dict[str, Any]
    try:
        async with httpx.AsyncClient(timeout=4.0) as cli:
            r = await cli.get(f"{sedes.HSB_BASE_URL}/health")
            bus = {"disponible": r.status_code < 500, "estado": r.json().get("estado")}
    except Exception as exc:
        bus = {"disponible": False, "error": str(exc).strip().splitlines()[0]}

    # La vista sigue sirviendo con 2 de 3 sedes: eso es «degradado», no «caído».
    if arriba == 3 and central["disponible"] and hapi.get("disponible") and bus["disponible"]:
        estado = "ok"
    elif arriba >= 1:
        estado = "degradado"
    else:
        estado = "caido"
        response.status_code = 503

    return {
        "servicio": "api",
        "version": app.version,
        "estado": estado,
        "tiempo_activo_s": round(time.time() - _INICIO, 1),
        "dependencias": {
            "sedes": estado_sedes,
            "sedes_disponibles": f"{arriba}/3",
            "almacen_central": central,
            "hapi_fhir": {"disponible": hapi.get("disponible"), "fhir_version": hapi.get("fhir_version")},
            "hsb": bus,
        },
        "seguridad": {
            "jwt": "activo",
            "secreto_por_defecto": seguridad.SECRETO_POR_DEFECTO,
            "aviso": ("Defina JWT_SECRET en el archivo .env antes de cualquier uso real"
                      if seguridad.SECRETO_POR_DEFECTO else None),
        },
    }


@app.get("/metrics", response_class=PlainTextResponse, tags=["observabilidad"],
         summary="Métricas de la API (formato Prometheus)")
async def metrics_api():
    estado_sedes = db.estado_sedes()
    cobertura = db.cobertura_fhir_por_sede()
    lineas = [
        "# HELP api_tiempo_activo_segundos Tiempo que lleva en marcha la API.",
        "# TYPE api_tiempo_activo_segundos gauge",
        f"api_tiempo_activo_segundos {round(time.time() - _INICIO, 1)}",
        "# HELP api_peticiones_total Peticiones atendidas por la API.",
        "# TYPE api_peticiones_total counter",
        f"api_peticiones_total {_CONTADORES['peticiones']}",
        "# HELP api_peticiones_error_total Peticiones que terminaron en error.",
        "# TYPE api_peticiones_error_total counter",
        f"api_peticiones_error_total {_CONTADORES['errores']}",
        "# HELP api_denegaciones_total Accesos denegados por rol (401 y 403).",
        "# TYPE api_denegaciones_total counter",
        f"api_denegaciones_total {_CONTADORES['denegados']}",
        "# HELP api_latencia_media_ms Latencia media de las peticiones.",
        "# TYPE api_latencia_media_ms gauge",
        f"api_latencia_media_ms {round(_CONTADORES['latencia_total_ms'] / max(_CONTADORES['peticiones'], 1), 2)}",
        "# HELP sede_disponible 1 si el nodo de la sede responde.",
        "# TYPE sede_disponible gauge",
    ]
    for s in estado_sedes:
        lineas.append(f'sede_disponible{{sede="{s["sede_id"]}",nombre="{s["nombre"]}"}} '
                      f'{1 if s["disponible"] else 0}')
        lineas.append(f'sede_latencia_ms{{sede="{s["sede_id"]}"}} {s["latencia_ms"]}')
    lineas += [
        "# HELP cobertura_fhir_pct Porcentaje de pacientes del legado ya normalizados a FHIR.",
        "# TYPE cobertura_fhir_pct gauge",
    ]
    for c in cobertura:
        if c["disponible"]:
            lineas.append(f'cobertura_fhir_pct{{sede="{c["sede_id"]}",nombre="{c["nombre"]}"}} '
                          f'{c["cobertura_pct"]}')
            lineas.append(f'cobertura_fhir_pacientes{{sede="{c["sede_id"]}"}} {c["total"]}')
    return "\n".join(lineas) + "\n"


@app.get("/metrics.json", tags=["observabilidad"], summary="Métricas de la API en JSON")
async def metrics_api_json():
    return {
        "tiempo_activo_s": round(time.time() - _INICIO, 1),
        "contadores": dict(_CONTADORES),
        "latencia_media_ms": round(_CONTADORES["latencia_total_ms"] / max(_CONTADORES["peticiones"], 1), 2),
        "sedes": db.estado_sedes(),
        "cobertura_fhir": db.cobertura_fhir_por_sede(),
    }


# Estáticos al final para no tapar rutas
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

# ============================================================================
# MCP - Model Context Protocol
# Expone todos los endpoints de la API como herramientas para agentes de IA
# ============================================================================
mcp = FastApiMCP(
    app,
    name="Historia Clínica Distribuida MCP",
    description=(
        "Servidor MCP del sistema de Historia Clínica Distribuida. "
        "Permite a agentes de IA consultar y gestionar pacientes FHIR, "
        "ejecutar queries SQL distribuidas, y monitorear el estado de los nodos PostgreSQL."
    ),
)
mcp.mount()  # Disponible en /mcp

PORT = 8001

if __name__ == "__main__":
    import uvicorn
    print("\n  → Dashboard:  http://localhost:{}".format(PORT))
    print("  → Admisión:   http://localhost:{}/admision".format(PORT))
    print("  → Médico:     http://localhost:{}/medico".format(PORT))
    print("  → Consulta:   http://localhost:{}/consulta-hc".format(PORT))
    print("  → Carga HC:   http://localhost:{}/carga-hc".format(PORT))
    print("  → Health:     http://localhost:{}/api/health".format(PORT))
    print("  → MCP Server: http://localhost:{}/mcp\n".format(PORT))
    uvicorn.run(app, host="0.0.0.0", port=PORT)
