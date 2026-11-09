"""
hsb/csv_legado.py — Lector del CSV legado de las sedes (separador `;`).

Formato (ejemplos/04_sede3_legado.csv):

    documento;nombre;sexo;nacimiento;dx_local;fecha;triage;profesional

A diferencia del HL7, aquí el diagnóstico llega en texto libre (`dx_local`) y
se traduce a CIE-10 con la tabla `ref_terminologia`. Si no hay mapeo, la fila
se rechaza con motivo: es el comportamiento que exige el contrato de
`ejemplos/LEEME.md`.

Cada fila es un mensaje independiente: su clave de idempotencia es el SHA-256
de la fila más la sede, de modo que volver a subir el mismo archivo responde
«duplicado» fila por fila y no duplica pacientes.
"""

import csv
import hashlib
import io
from typing import Any, Dict, List, Optional

from comun import sedes

COLUMNAS = ("documento", "nombre", "sexo", "nacimiento", "dx_local", "fecha", "triage", "profesional")


class ErrorCSV(Exception):
    """El archivo no tiene la forma esperada del CSV legado."""


def clave_fila(sede_id: int, fila_cruda: str) -> str:
    return "csv:" + hashlib.sha256(f"{sede_id}|{fila_cruda.strip()}".encode("utf-8")).hexdigest()


def _partir_nombre(completo: str) -> Dict[str, str]:
    piezas = [p for p in (completo or "").split() if p]
    if not piezas:
        return {"nombres": "", "apellidos": "", "nombre_completo": ""}
    if len(piezas) == 1:
        return {"nombres": piezas[0], "apellidos": "", "nombre_completo": piezas[0]}
    return {
        "nombres": piezas[0],
        "apellidos": " ".join(piezas[1:]),
        "nombre_completo": " ".join(piezas),
    }


def parsear(contenido: str, sede_id: int) -> List[Dict[str, Any]]:
    """Convierte el CSV en una lista de registros canónicos (uno por fila)."""
    if not contenido or not contenido.strip():
        raise ErrorCSV("archivo vacío")

    sede = sedes.sede(sede_id)
    texto = contenido.replace("\r\n", "\n").replace("\r", "\n")
    lineas = [ln for ln in texto.split("\n") if ln.strip()]
    if not lineas:
        raise ErrorCSV("archivo sin filas")

    cabecera = [c.strip().lower() for c in lineas[0].split(";")]
    faltantes = [c for c in ("documento", "nombre", "dx_local") if c not in cabecera]
    if faltantes:
        raise ErrorCSV(f"el CSV no trae las columnas obligatorias: {', '.join(faltantes)}")

    lector = csv.DictReader(io.StringIO("\n".join(lineas)), delimiter=";")
    registros: List[Dict[str, Any]] = []

    for numero, fila in enumerate(lector, start=2):
        cruda = ";".join((fila.get(c) or "") for c in cabecera)
        nombre = _partir_nombre((fila.get("nombre") or "").strip())
        triage = (fila.get("triage") or "").strip()
        profesional = (fila.get("profesional") or "").strip()

        registro: Dict[str, Any] = {
            "formato": "csv",
            "tipo": "CSV",
            "origen": f"LEGADO_{sede['codigo']}",
            "sede_codigo": sede["codigo"],
            "sede_id": sede["sede_id"],
            "sede_nombre": sede["nombre"],
            "clave_idempotencia": clave_fila(sede_id, cruda),
            "fila_csv": numero,
            "documento": (fila.get("documento") or "").strip(),
            "tipo_documento": "CC",
            "sexo": ((fila.get("sexo") or "").strip() or "U").upper(),
            "fecha_nacimiento": (fila.get("nacimiento") or "").strip(),
            "fecha_ingreso": (fila.get("fecha") or "").strip(),
            "clase_encuentro": "O",
            "triage": triage or None,
            "visita": None,
            "diagnosticos": [],
            "observaciones": [],
            **nombre,
        }
        dx_local = (fila.get("dx_local") or "").strip()
        if dx_local:
            registro["diagnosticos"].append(
                {"origen": dx_local, "descripcion": dx_local.title(), "sistema_origen": "L"}
            )
        if profesional:
            registro["profesional"] = {"codigo": profesional, "nombre": profesional}
        registros.append(registro)

    if not registros:
        raise ErrorCSV("el CSV solo trae cabecera")
    return registros


def resumen(registros: List[Dict[str, Any]]) -> str:
    return f"{len(registros)} filas de la sede {registros[0]['sede_codigo'] if registros else '?'}"
