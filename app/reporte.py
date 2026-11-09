"""
app/reporte.py — Reporte de la historia clínica unificada (cuarta vista).

Contiene lo que pide la guía para esta vista:
  * la historia agrupada por sede, con aviso si alguna sede no respondió,
  * cobertura de campos con la lista de los que faltan,
  * sello de integridad (SHA-256 del contenido del reporte),
  * exportación a HTML (imprimible a PDF desde el navegador),
  * el Bundle FHIR del paciente (tipo `document`, con Composition).
"""

import html
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from comun import auditoria
from fhir import normalizador

# Campos de la historia clínica que se miden para la cobertura. Son los que
# viajan a FHIR; la lista se usa tal cual en la vista y en el informe.
CAMPOS_PACIENTE = [
    ("documento_id", "Documento"),
    ("tipo_documento", "Tipo de documento"),
    ("nombre_completo", "Nombre completo"),
    ("fecha_nacimiento", "Fecha de nacimiento"),
    ("sexo", "Sexo"),
    ("pais_nacionalidad", "País de nacionalidad"),
    ("pais_residencia", "País de residencia"),
    ("municipio_residencia", "Municipio de residencia"),
    ("zona_residencia", "Zona de residencia"),
    ("ocupacion", "Ocupación"),
    ("etnia", "Etnia"),
    ("fhir_patient_id", "Identificador FHIR del paciente"),
]

CAMPOS_ATENCION = [
    ("visita", "Número de visita"),
    ("fecha_ingreso", "Fecha de ingreso"),
    ("entidad_salud", "Entidad de salud"),
    ("entorno_atencion", "Entorno de atención"),
    ("via_ingreso", "Vía de ingreso"),
    ("causa_atencion", "Causa de atención"),
    ("clasificacion_triage", "Clasificación de triage"),
    ("profesional_codigo", "Profesional que atiende"),
    ("fhir_encounter_id", "Identificador FHIR del encuentro"),
]


def _vacio(valor: Any) -> bool:
    return valor is None or (isinstance(valor, str) and not valor.strip())


def cobertura_campos(historia: Dict[str, Any]) -> Dict[str, Any]:
    """Qué porcentaje de los campos de la HC está diligenciado y qué falta."""
    presentes, faltantes = 0, []
    total = 0

    paciente = historia.get("paciente") or {}
    for clave, etiqueta in CAMPOS_PACIENTE:
        total += 1
        if _vacio(paciente.get(clave)):
            faltantes.append({"ambito": "paciente", "campo": etiqueta})
        else:
            presentes += 1

    for atencion in historia.get("atenciones") or []:
        referencia = atencion.get("visita") or f"atención {atencion.get('atencion_id')}"
        for clave, etiqueta in CAMPOS_ATENCION:
            total += 1
            if _vacio(atencion.get(clave)):
                faltantes.append({"ambito": f"sede {atencion.get('sede_id')} · {referencia}",
                                  "campo": etiqueta})
            else:
                presentes += 1
        total += 1
        if atencion.get("diagnosticos"):
            presentes += 1
        else:
            faltantes.append({"ambito": f"sede {atencion.get('sede_id')} · {referencia}",
                              "campo": "Diagnóstico CIE-10"})

    return {
        "campos_totales": total,
        "campos_presentes": presentes,
        "cobertura_pct": round(100.0 * presentes / total, 1) if total else 0.0,
        "faltantes": faltantes,
        "total_faltantes": len(faltantes),
    }


def construir(historia: Dict[str, Any], solicitante: str, rol: str,
              incluir_bundle: bool = True) -> Dict[str, Any]:
    """
    Arma el reporte completo. El sello se calcula sobre el contenido clínico
    (no sobre la hora de generación), así que dos reportes del mismo estado de
    la historia dan el mismo sello y cualquier cambio posterior lo altera.
    """
    cobertura = cobertura_campos(historia)

    por_sede: List[Dict[str, Any]] = []
    for sede in historia.get("sedes", []):
        por_sede.append(
            {
                "sede_id": sede["sede_id"],
                "nombre": sede["nombre"],
                "disponible": sede["disponible"],
                "error": sede.get("error"),
                "atenciones": sede.get("atenciones", []),
                "totales": sede.get("totales", {}),
            }
        )

    contenido = {
        "documento_id": historia.get("documento_id"),
        "paciente": historia.get("paciente"),
        "sedes": [
            {
                "sede_id": s["sede_id"],
                "atenciones": [
                    {
                        "visita": a.get("visita"),
                        "fecha_ingreso": a.get("fecha_ingreso"),
                        "diagnosticos": [d.get("cie10") for d in a.get("diagnosticos", [])],
                        "observaciones": [
                            f"{o.get('loinc')}={o.get('valor')}{o.get('unidad') or ''}"
                            for o in a.get("observaciones", [])
                        ],
                        "medicamentos": [m.get("descripcion_medicamento") for m in a.get("medicamentos", [])],
                    }
                    for a in s["atenciones"]
                ],
            }
            for s in por_sede
            if s["disponible"]
        ],
    }
    sello = auditoria.sello_contenido(contenido)

    reporte: Dict[str, Any] = {
        "generado_en": datetime.now(timezone.utc).isoformat(),
        "generado_por": solicitante,
        "rol": rol,
        "documento_id": historia.get("documento_id"),
        "paciente": historia.get("paciente"),
        "completo": not historia.get("parcial", False),
        "aviso": (
            "Reporte PARCIAL: "
            + ", ".join(
                f"la sede {s['nombre']} no respondió" for s in historia.get("sedes_no_disponibles", [])
            )
            if historia.get("parcial")
            else None
        ),
        "sedes": por_sede,
        "sedes_no_disponibles": historia.get("sedes_no_disponibles", []),
        "resumen": historia.get("resumen", {}),
        "cobertura_campos": cobertura,
        "sello_integridad": sello,
        "sello_corto": sello[:16],
    }

    if incluir_bundle:
        reporte["bundle_fhir"] = bundle_del_paciente(historia)
    return reporte


def bundle_del_paciente(historia: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Bundle FHIR `document` con la historia unificada (Composition + recursos)."""
    paciente = historia.get("paciente")
    if not paciente:
        return None

    base = {
        "documento": str(paciente.get("documento_id")),
        "tipo_documento": paciente.get("tipo_documento") or "CC",
        "nombre_completo": paciente.get("nombre_completo") or "",
        "fecha_nacimiento": paciente.get("fecha_nacimiento"),
        "sexo": (paciente.get("sexo") or "U")[:1].upper(),
        "municipio_residencia": paciente.get("municipio_residencia"),
        "pais_residencia": paciente.get("pais_residencia"),
    }

    registros: List[Dict[str, Any]] = []
    for sede in historia.get("sedes", []):
        if not sede["disponible"]:
            continue
        for atencion in sede["atenciones"]:
            registros.append(
                {
                    **base,
                    "sede_id": sede["sede_id"],
                    "sede_nombre": sede["nombre"],
                    "visita": atencion.get("visita"),
                    "fecha_ingreso": atencion.get("fecha_ingreso"),
                    "triage": atencion.get("clasificacion_triage"),
                    "causa_atencion": atencion.get("causa_atencion"),
                    "clase_encuentro": {"Urgencias": "E", "Hospitalizacion": "I"}.get(
                        atencion.get("entorno_atencion") or "", "O"
                    ),
                    "profesional": (
                        {"codigo": atencion["profesional_codigo"],
                         "nombre": atencion.get("profesional_nombre") or atencion["profesional_codigo"]}
                        if atencion.get("profesional_codigo")
                        else {}
                    ),
                    "diagnosticos": [
                        {"origen": d.get("cie10") or d.get("dx_local"),
                         "descripcion": d.get("descripcion_cie10") or d.get("diagnostico_ingreso") or ""}
                        for d in atencion.get("diagnosticos", [])
                        if d.get("cie10") or d.get("dx_local")
                    ],
                    "observaciones": [
                        {"codigo": o.get("loinc"), "prueba": o.get("descripcion"),
                         "valor": o.get("valor"), "unidad": o.get("unidad"), "fecha": o.get("fecha")}
                        for o in atencion.get("observaciones", [])
                    ],
                }
            )

    if not registros:
        registros = [{**base, "sede_id": 0, "sin_atencion": True}]
    return normalizador.bundle_documento(base, registros,
                                         titulo="Historia clínica unificada de las 3 sedes")


# ─────────────────────────────────────────────────────────────────────────────
# Exportación a HTML (imprimible a PDF con Ctrl+P)
# ─────────────────────────────────────────────────────────────────────────────
def _e(valor: Any) -> str:
    return html.escape("" if valor is None else str(valor))


def a_html(reporte: Dict[str, Any]) -> str:
    paciente = reporte.get("paciente") or {}
    cobertura = reporte.get("cobertura_campos", {})

    filas_sedes = []
    for sede in reporte.get("sedes", []):
        if not sede["disponible"]:
            filas_sedes.append(
                f"""<section class="sede caida">
                      <h3>Sede {_e(sede['nombre'])} — no disponible</h3>
                      <p class="aviso">Esta sede no respondió: {_e(sede.get('error') or 'sin respuesta')}.
                      El reporte está incompleto.</p>
                    </section>"""
            )
            continue
        atenciones_html = []
        for a in sede["atenciones"]:
            dx = "".join(
                f"<li><strong>{_e(d.get('cie10'))}</strong> — {_e(d.get('descripcion_cie10') or d.get('diagnostico_ingreso'))}</li>"
                for d in a.get("diagnosticos", [])
            ) or "<li class='vacio'>Sin diagnóstico registrado</li>"
            obs = "".join(
                f"<li>{_e(o.get('descripcion'))} (LOINC {_e(o.get('loinc'))}): "
                f"<strong>{_e(o.get('valor'))} {_e(o.get('unidad'))}</strong></li>"
                for o in a.get("observaciones", [])
            ) or "<li class='vacio'>Sin resultados de laboratorio</li>"
            med = "".join(
                f"<li>{_e(m.get('descripcion_medicamento'))} — {_e(m.get('dosis'))} "
                f"{_e(m.get('via_administracion'))} {_e(m.get('frecuencia'))}</li>"
                for m in a.get("medicamentos", [])
            ) or "<li class='vacio'>Sin tecnologías en salud</li>"
            egreso = a.get("egreso")
            egreso_html = (
                f"<p><strong>Egreso:</strong> {_e(egreso.get('fecha_salida'))} — "
                f"{_e(egreso.get('condicion_salida'))}</p>"
                if egreso
                else ""
            )
            atenciones_html.append(
                f"""<article class="atencion">
                      <h4>Visita {_e(a.get('visita'))} · {_e(a.get('fecha_ingreso'))}</h4>
                      <p class="meta">{_e(a.get('entorno_atencion'))} · vía {_e(a.get('via_ingreso'))} ·
                         triage {_e(a.get('clasificacion_triage') or 'no registrado')} ·
                         profesional {_e(a.get('profesional_nombre') or a.get('profesional_codigo') or 'no registrado')}</p>
                      <p class="motivo">{_e(a.get('causa_atencion'))}</p>
                      <div class="columnas">
                        <div><h5>Diagnósticos (CIE-10)</h5><ul>{dx}</ul></div>
                        <div><h5>Laboratorio (LOINC)</h5><ul>{obs}</ul></div>
                        <div><h5>Tecnologías en salud</h5><ul>{med}</ul></div>
                      </div>
                      {egreso_html}
                    </article>"""
            )
        filas_sedes.append(
            f"""<section class="sede">
                  <h3>Sede {_e(sede['nombre'])}</h3>
                  <p class="meta">{sede['totales'].get('atenciones', 0)} atenciones ·
                     {sede['totales'].get('diagnosticos', 0)} diagnósticos ·
                     {sede['totales'].get('observaciones', 0)} resultados</p>
                  {''.join(atenciones_html) or "<p class='vacio'>Sin atenciones en esta sede</p>"}
                </section>"""
        )

    faltantes = "".join(
        f"<li>{_e(f['ambito'])}: {_e(f['campo'])}</li>" for f in cobertura.get("faltantes", [])[:40]
    ) or "<li class='vacio'>No falta ningún campo</li>"

    aviso = (
        f"<p class='aviso grande'>{_e(reporte['aviso'])}</p>" if reporte.get("aviso") else
        "<p class='ok grande'>Reporte completo: las tres sedes respondieron.</p>"
    )

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Reporte de HC — {_e(paciente.get('nombre_completo'))}</title>
<style>
  :root {{ --tinta:#14202b; --suave:#5b6b7a; --linea:#d6dee6; --fondo:#fff; --acento:#0b6e4f; --alerta:#9b2c2c; }}
  * {{ box-sizing:border-box; }}
  body {{ font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif; color:var(--tinta);
         background:var(--fondo); margin:0; padding:24px; line-height:1.5; }}
  .hoja {{ max-width:900px; margin:0 auto; }}
  h1 {{ font-size:1.5rem; margin:0 0 4px; }}
  h2 {{ font-size:1.1rem; margin:28px 0 8px; border-bottom:2px solid var(--linea); padding-bottom:4px; }}
  h3 {{ font-size:1rem; margin:18px 0 6px; color:var(--acento); }}
  h4 {{ font-size:.95rem; margin:12px 0 2px; }}
  h5 {{ font-size:.8rem; margin:0 0 4px; color:var(--suave); text-transform:uppercase; letter-spacing:.04em; }}
  .meta, .motivo {{ color:var(--suave); font-size:.85rem; margin:2px 0; }}
  .ficha {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:8px 18px;
            border:1px solid var(--linea); border-radius:8px; padding:14px; margin-top:10px; }}
  .ficha div span {{ display:block; font-size:.72rem; color:var(--suave); text-transform:uppercase; }}
  .sede {{ border:1px solid var(--linea); border-radius:8px; padding:14px; margin:12px 0; }}
  .sede.caida {{ border-color:var(--alerta); background:#fff5f5; }}
  .atencion {{ border-top:1px dashed var(--linea); padding-top:10px; margin-top:10px; }}
  .columnas {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:14px; margin-top:8px; }}
  ul {{ margin:0; padding-left:18px; font-size:.9rem; }}
  .vacio {{ color:var(--suave); font-style:italic; list-style:none; margin-left:-18px; }}
  .aviso {{ color:var(--alerta); font-weight:600; }}
  .ok {{ color:var(--acento); font-weight:600; }}
  .grande {{ font-size:1rem; }}
  .sello {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:.8rem;
            background:#f4f7fa; border:1px solid var(--linea); border-radius:6px; padding:10px;
            word-break:break-all; }}
  .barra {{ height:10px; background:#eef2f6; border-radius:99px; overflow:hidden; margin:6px 0; }}
  .barra i {{ display:block; height:100%; background:var(--acento); }}
  footer {{ margin-top:28px; font-size:.78rem; color:var(--suave); border-top:1px solid var(--linea);
            padding-top:10px; }}
  @media print {{ body {{ padding:0; }} .sede, .ficha {{ break-inside:avoid; }} }}
</style>
</head>
<body>
<div class="hoja">
  <h1>Reporte de historia clínica unificada</h1>
  <p class="meta">Plataforma distribuida de interoperabilidad clínica · Red de IPS Sincelejo · Cartagena · Corozal</p>
  {aviso}

  <h2>Paciente</h2>
  <div class="ficha">
    <div><span>Documento</span>{_e(paciente.get('tipo_documento'))} {_e(paciente.get('documento_id'))}</div>
    <div><span>Nombre</span>{_e(paciente.get('nombre_completo'))}</div>
    <div><span>Nacimiento</span>{_e(paciente.get('fecha_nacimiento'))}</div>
    <div><span>Sexo</span>{_e(paciente.get('sexo'))}</div>
    <div><span>Municipio</span>{_e(paciente.get('municipio_residencia'))}</div>
    <div><span>Id FHIR</span>{_e(paciente.get('fhir_patient_id') or 'sin normalizar')}</div>
  </div>

  <h2>Atenciones por sede</h2>
  {''.join(filas_sedes)}

  <h2>Cobertura de campos</h2>
  <p>{cobertura.get('campos_presentes', 0)} de {cobertura.get('campos_totales', 0)} campos
     diligenciados ({cobertura.get('cobertura_pct', 0)} %).</p>
  <div class="barra"><i style="width:{cobertura.get('cobertura_pct', 0)}%"></i></div>
  <h5>Campos faltantes ({cobertura.get('total_faltantes', 0)})</h5>
  <ul>{faltantes}</ul>

  <h2>Sello de integridad</h2>
  <p class="meta">SHA-256 del contenido clínico del reporte. Si el contenido cambia, el sello cambia.</p>
  <p class="sello">{_e(reporte.get('sello_integridad'))}</p>

  <footer>
    Generado el {_e(reporte.get('generado_en'))} por {_e(reporte.get('generado_por'))}
    (rol {_e(reporte.get('rol'))}). Datos sintéticos de uso académico.
    Para guardar como PDF: imprimir y elegir «Guardar como PDF».
  </footer>
</div>
</body>
</html>"""
