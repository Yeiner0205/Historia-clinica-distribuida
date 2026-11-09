#!/usr/bin/env python3
"""
docs/uml/generar_diagramas.py — Dibuja los diagramas del informe en SVG.

La guía pide los diagramas «en imagen y con su fuente editable». Aquí la
fuente editable es doble:

  * este script, que produce los SVG sin depender de ninguna herramienta
    externa (basta Python; no hace falta Java ni PlantUML), y
  * los archivos `.puml` de la misma carpeta, para quien prefiera editar en
    PlantUML o en draw.io.

Uso:
    python3 docs/uml/generar_diagramas.py
"""

import os
from typing import Dict, List, Optional, Tuple

SALIDA = os.path.dirname(os.path.abspath(__file__))

# Paleta sobria, con contraste suficiente para imprimir en blanco y negro.
COLORES = {
    "fondo": "#ffffff",
    "tinta": "#14202b",
    "suave": "#5b6b7a",
    "linea": "#9fb0c0",
    "sede": "#e8f1fb",
    "sede_borde": "#2f6fb0",
    "bus": "#fdf0e3",
    "bus_borde": "#c47a1c",
    "fhir": "#e7f6ee",
    "fhir_borde": "#1f8a5c",
    "datos": "#f1ecfb",
    "datos_borde": "#6b4fb5",
    "vista": "#fde9ef",
    "vista_borde": "#b5325c",
    "seguridad": "#fff6d8",
    "seguridad_borde": "#a98300",
    "neutro": "#f3f6f9",
}

TIPOGRAFIA = "font-family='Segoe UI, Helvetica, Arial, sans-serif'"


def _escapar(texto: str) -> str:
    return (texto.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def encabezado(ancho: int, alto: int, titulo: str) -> List[str]:
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{ancho}" height="{alto}" '
        f'viewBox="0 0 {ancho} {alto}" role="img" aria-label="{_escapar(titulo)}">',
        f"<title>{_escapar(titulo)}</title>",
        f'<rect width="{ancho}" height="{alto}" fill="{COLORES["fondo"]}"/>',
        '<defs>',
        '  <marker id="flecha" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
        '          markerHeight="7" orient="auto-start-reverse">',
        f'    <path d="M 0 0 L 10 5 L 0 10 z" fill="{COLORES["tinta"]}"/>',
        '  </marker>',
        '  <marker id="flecha-abierta" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" '
        '          markerHeight="8" orient="auto-start-reverse">',
        f'    <path d="M 0 0 L 10 5 L 0 10" fill="none" stroke="{COLORES["tinta"]}" stroke-width="1.4"/>',
        '  </marker>',
        '  <marker id="rombo" viewBox="0 0 12 12" refX="11" refY="6" markerWidth="10" '
        '          markerHeight="10" orient="auto">',
        f'    <path d="M 0 6 L 6 1 L 12 6 L 6 11 z" fill="{COLORES["fondo"]}" '
        f'          stroke="{COLORES["tinta"]}" stroke-width="1.2"/>',
        '  </marker>',
        '</defs>',
        f'<text x="24" y="34" {TIPOGRAFIA} font-size="19" font-weight="700" '
        f'fill="{COLORES["tinta"]}">{_escapar(titulo)}</text>',
    ]


def texto(x: int, y: int, contenido: str, tam: int = 12, peso: str = "400",
          color: Optional[str] = None, anclaje: str = "start", cursiva: bool = False) -> str:
    estilo = f' font-style="italic"' if cursiva else ""
    return (f'<text x="{x}" y="{y}" {TIPOGRAFIA} font-size="{tam}" font-weight="{peso}"'
            f'{estilo} fill="{color or COLORES["tinta"]}" text-anchor="{anclaje}">'
            f"{_escapar(contenido)}</text>")


def caja(x: int, y: int, ancho: int, alto: int, titulo: str, lineas: List[str] = (),
         relleno: str = "neutro", borde: Optional[str] = None, radio: int = 10,
         tam_titulo: int = 13) -> List[str]:
    color = COLORES.get(relleno, relleno)
    color_borde = COLORES.get(borde or f"{relleno}_borde", COLORES["linea"])
    partes = [
        f'<rect x="{x}" y="{y}" width="{ancho}" height="{alto}" rx="{radio}" '
        f'fill="{color}" stroke="{color_borde}" stroke-width="1.6"/>',
        texto(x + ancho // 2, y + 22, titulo, tam_titulo, "700", anclaje="middle"),
    ]
    for i, linea in enumerate(lineas):
        partes.append(texto(x + ancho // 2, y + 42 + i * 16, linea, 11,
                            color=COLORES["suave"], anclaje="middle"))
    return partes


def flecha(x1: int, y1: int, x2: int, y2: int, etiqueta: str = "",
           punteada: bool = False, marcador: str = "flecha",
           desvio_etiqueta: Tuple[int, int] = (0, -6)) -> List[str]:
    guion = ' stroke-dasharray="6 4"' if punteada else ""
    partes = [
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{COLORES["tinta"]}" '
        f'stroke-width="1.5"{guion} marker-end="url(#{marcador})"/>'
    ]
    if etiqueta:
        mx, my = (x1 + x2) // 2 + desvio_etiqueta[0], (y1 + y2) // 2 + desvio_etiqueta[1]
        ancho = len(etiqueta) * 6 + 10
        partes.append(f'<rect x="{mx - ancho // 2}" y="{my - 11}" width="{ancho}" height="16" '
                      f'rx="4" fill="{COLORES["fondo"]}" opacity="0.92"/>')
        partes.append(texto(mx, my + 1, etiqueta, 10.5, color=COLORES["suave"], anclaje="middle"))
    return partes


def actor(x: int, y: int, nombre: str, rol: str = "") -> List[str]:
    """Monigote de UML."""
    c = COLORES["tinta"]
    partes = [
        f'<circle cx="{x}" cy="{y}" r="9" fill="none" stroke="{c}" stroke-width="1.6"/>',
        f'<line x1="{x}" y1="{y + 9}" x2="{x}" y2="{y + 32}" stroke="{c}" stroke-width="1.6"/>',
        f'<line x1="{x - 13}" y1="{y + 18}" x2="{x + 13}" y2="{y + 18}" stroke="{c}" stroke-width="1.6"/>',
        f'<line x1="{x}" y1="{y + 32}" x2="{x - 11}" y2="{y + 50}" stroke="{c}" stroke-width="1.6"/>',
        f'<line x1="{x}" y1="{y + 32}" x2="{x + 11}" y2="{y + 50}" stroke="{c}" stroke-width="1.6"/>',
        texto(x, y + 68, nombre, 12.5, "600", anclaje="middle"),
    ]
    if rol:
        partes.append(texto(x, y + 83, rol, 10.5, color=COLORES["suave"], anclaje="middle"))
    return partes


def elipse(cx: int, cy: int, rx: int, ry: int, etiqueta: str, relleno: str = "neutro",
           segunda_linea: str = "") -> List[str]:
    color = COLORES.get(relleno, relleno)
    borde = COLORES.get(f"{relleno}_borde", COLORES["linea"])
    partes = [
        f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" fill="{color}" '
        f'stroke="{borde}" stroke-width="1.5"/>',
    ]
    if segunda_linea:
        partes.append(texto(cx, cy - 3, etiqueta, 11.5, "600", anclaje="middle"))
        partes.append(texto(cx, cy + 12, segunda_linea, 10, color=COLORES["suave"], anclaje="middle"))
    else:
        partes.append(texto(cx, cy + 4, etiqueta, 11.5, "600", anclaje="middle"))
    return partes


def guardar(nombre: str, partes: List[str]) -> str:
    ruta = os.path.join(SALIDA, nombre)
    with open(ruta, "w", encoding="utf-8") as fh:
        fh.write("\n".join(partes + ["</svg>", ""]))
    return ruta


# ═══════════════════════════════════════════════════════════════════════════
# 1. Diagrama de casos de uso
# ═══════════════════════════════════════════════════════════════════════════
def casos_de_uso() -> str:
    A, H = 1180, 760
    p = encabezado(A, H, "Casos de uso — Plataforma de interoperabilidad clínica")
    p.append(texto(24, 54, "Actores: paciente, admisionista, médico, auditor y el sistema legado de cada sede. "
                           "12 casos de uso.", 12, color=COLORES["suave"]))

    # Frontera del sistema
    p.append(f'<rect x="300" y="78" width="560" height="640" rx="14" fill="none" '
             f'stroke="{COLORES["linea"]}" stroke-width="1.6" stroke-dasharray="8 5"/>')
    p.append(texto(580, 100, "Plataforma distribuida de interoperabilidad clínica", 12.5, "700",
                   color=COLORES["suave"], anclaje="middle"))

    # Actores a la izquierda
    p += actor(120, 150, "Paciente", "persona atendida")
    p += actor(120, 330, "Admisionista", "admisión y triage")
    p += actor(120, 520, "Médico", "profesional de salud")
    # Actores a la derecha
    p += actor(1050, 170, "Sistema de sede", "HIS legado (HL7/CSV)")
    p += actor(1050, 480, "Auditor", "auditoría y operación")

    casos = {
        "cu1": (470, 150, "Consultar mi historia", "unificada de las 3 sedes", "vista"),
        "cu2": (470, 230, "Descargar Bundle FHIR", "", "fhir"),
        "cu3": (470, 300, "Ver quién accedió", "a mi historia", "seguridad"),
        "cu4": (690, 150, "Enviar mensaje al bus", "HL7 v2 / CSV legado", "bus"),
        "cu5": (690, 230, "Normalizar a FHIR R4", "Patient/Encounter/Condition/Observation", "fhir"),
        "cu6": (470, 380, "Buscar o registrar paciente", "detecta duplicados entre sedes", "vista"),
        "cu7": (470, 455, "Abrir atención con triage", "", "vista"),
        "cu8": (690, 380, "Ver estado del bus", "mensajes por estado", "bus"),
        "cu9": (470, 530, "Registrar diagnóstico CIE-10", "ordenar, formular y egresar", "vista"),
        "cu10": (470, 610, "Generar Reporte de HC", "cobertura y sello de integridad", "vista"),
        "cu11": (690, 530, "Verificar la auditoría", "cadena de hash", "seguridad"),
        "cu12": (690, 610, "Apagar o encender un nodo", "prueba de resiliencia", "datos"),
    }
    for cx, cy, etiqueta, segunda, color in casos.values():
        p += elipse(cx, cy, 108, 34, etiqueta, color, segunda)

    def enlazar(ax, ay, clave):
        cx, cy, *_ = casos[clave]
        p.extend(flecha(ax, ay, cx - 108, cy, marcador="flecha-abierta"))

    for clave in ("cu1", "cu2", "cu3"):
        enlazar(150, 180, clave)
    for clave in ("cu6", "cu7"):
        enlazar(150, 360, clave)
    p.extend(flecha(150, 360, 582, 380, marcador="flecha-abierta"))
    for clave in ("cu1", "cu9", "cu10"):
        enlazar(150, 550, clave)

    # Sistema de sede (derecha)
    p.extend(flecha(1020, 200, 798, 150, marcador="flecha-abierta"))
    # Auditor (derecha)
    for clave in ("cu11", "cu12", "cu10"):
        cx, cy, *_ = casos[clave]
        p.extend(flecha(1020, 510, cx + 108, cy, marcador="flecha-abierta"))

    # Relaciones «include»
    p.extend(flecha(690, 184, 690, 196, "«include»", punteada=True, desvio_etiqueta=(62, 4)))
    p.extend(flecha(560, 588, 626, 556, "«include»", punteada=True, desvio_etiqueta=(-18, -8)))

    p.append(texto(24, 742, "«include»: enviar un mensaje al bus incluye normalizarlo a FHIR R4; "
                            "generar el Reporte de HC incluye verificar la auditoría.",
                   11, color=COLORES["suave"]))
    return guardar("01_casos_de_uso.svg", p)


# ═══════════════════════════════════════════════════════════════════════════
# 2. Diagrama de secuencia
# ═══════════════════════════════════════════════════════════════════════════
def secuencia() -> str:
    A, H = 1240, 920
    p = encabezado(A, H, "Secuencia — Un mensaje HL7 v2 de una sede termina como FHIR")
    p.append(texto(24, 54, "Camino feliz y camino de error: validación, reintento con retroceso "
                           "exponencial y cola de mensajes muertos.", 12, color=COLORES["suave"]))

    columnas = [
        (95, "Sistema de sede", "HIS legado", "sede"),
        (290, "HSB", "bus de integración", "bus"),
        (470, "Validador", "reglas del parcial", "bus"),
        (650, "Normalizador", "FHIR R4", "fhir"),
        (830, "HAPI FHIR", "servidor FHIR", "fhir"),
        (1000, "Nodo de la sede", "PostgreSQL", "datos"),
        (1160, "Auditoría", "cadena de hash", "seguridad"),
    ]
    for x, nombre, sub, color in columnas:
        p += caja(x - 78, 80, 156, 48, nombre, [sub], color)
        p.append(f'<line x1="{x}" y1="128" x2="{x}" y2="860" stroke="{COLORES["linea"]}" '
                 f'stroke-width="1.2" stroke-dasharray="5 5"/>')

    def activacion(x, y1, y2):
        p.append(f'<rect x="{x - 6}" y="{y1}" width="12" height="{y2 - y1}" rx="3" '
                 f'fill="{COLORES["neutro"]}" stroke="{COLORES["linea"]}"/>')

    activacion(290, 160, 820)
    activacion(470, 190, 230)
    activacion(650, 270, 320)
    activacion(830, 350, 400)
    activacion(1000, 560, 610)

    pasos = [
        (95, 290, 165, "1 POST /hsb/hl7 (ADT^A01 o ORU^R01)"),
        (290, 470, 200, "2 validar: documento, sexo, sede, fechas, CIE-10"),
        (470, 290, 235, "3 sin motivos → validado"),
        (290, 650, 280, "4 transformar a Bundle transaction (PUT, ids deterministas)"),
        (650, 290, 320, "5 Bundle FHIR R4"),
        (290, 830, 360, "6 POST / (transaction)"),
        (830, 290, 400, "7 201/200 + referencias creadas"),
    ]
    for x1, x2, y, etiqueta in pasos:
        p.extend(flecha(x1 + (8 if x2 > x1 else -8), y, x2 + (-8 if x2 > x1 else 8), y, etiqueta))

    # Camino de error
    p.append(f'<rect x="250" y="430" width="700" height="110" rx="10" fill="#fff6f6" '
             f'stroke="#d98a8a" stroke-width="1.4" stroke-dasharray="7 4"/>')
    p.append(texto(265, 452, "alt  [HAPI o la sede no responden]", 12, "700", color="#9b2c2c"))
    p.extend(flecha(298, 480, 822, 480, "7a error de red o 5xx"))
    p.append(texto(300, 505, "estado = reintentando · espera 1 s, 2 s, 4 s, 8 s · tras 4 intentos → muerto "
                             "(cola de mensajes muertos, reencolable)", 11, color="#9b2c2c"))

    p.extend(flecha(298, 570, 992, 570, "8 UPSERT usuario, atencion, diagnostico, observacion (una transacción)"))
    p.extend(flecha(992, 610, 298, 610, "9 confirmado (o rollback completo)"))
    p.extend(flecha(298, 650, 1152, 650, "10 evento encadenado: quién, cuándo, qué, resultado"))
    p.extend(flecha(1152, 690, 298, 690, "11 sello = hash del evento"))
    p.extend(flecha(282, 730, 103, 730, "12 entregado + recursos + latencia"))

    # Nota de idempotencia
    p.append(f'<rect x="250" y="770" width="700" height="62" rx="10" fill="{COLORES["seguridad"]}" '
             f'stroke="{COLORES["seguridad_borde"]}" stroke-width="1.3"/>')
    p.append(texto(265, 792, "Idempotencia", 12, "700"))
    p.append(texto(265, 810, "La clave es MSH-10 (o el hash de la fila del CSV) y está en un UNIQUE de "
                             "mensaje_bus: el reenvío responde «duplicado»", 11, color=COLORES["suave"]))
    p.append(texto(265, 826, "y los PUT sobre ids deterministas hacen que repetir la entrega "
                             "actualice en vez de crear.", 11, color=COLORES["suave"]))

    p.append(texto(24, 890, "Las vistas nunca hablan con las bases de las sedes: todo pasa por la API y "
                            "por el bus.", 11, color=COLORES["suave"]))
    return guardar("02_secuencia.svg", p)


# ═══════════════════════════════════════════════════════════════════════════
# 3. Diagrama de clases
# ═══════════════════════════════════════════════════════════════════════════
def clases() -> str:
    A, H = 1320, 900
    p = encabezado(A, H, "Clases — Modelo de datos de la plataforma")
    p.append(texto(24, 54, "13 entidades: las 6 del repositorio de referencia, las 3 que añade el parcial "
                           "(mensaje del bus, evento de auditoría y terminología) y 4 de apoyo.",
                   12, color=COLORES["suave"]))

    def clase(x, y, ancho, nombre, atributos, color, estereotipo=""):
        alto = 34 + len(atributos) * 15 + 10
        partes = [
            f'<rect x="{x}" y="{y}" width="{ancho}" height="{alto}" rx="7" '
            f'fill="{COLORES[color]}" stroke="{COLORES[color + "_borde"]}" stroke-width="1.5"/>',
            f'<line x1="{x}" y1="{y + 30}" x2="{x + ancho}" y2="{y + 30}" '
            f'stroke="{COLORES[color + "_borde"]}" stroke-width="1.2"/>',
            texto(x + ancho // 2, y + 20, nombre, 12.5, "700", anclaje="middle"),
        ]
        if estereotipo:
            partes.insert(1, texto(x + ancho // 2, y - 5, estereotipo, 10,
                                   color=COLORES["suave"], anclaje="middle", cursiva=True))
        for i, atributo in enumerate(atributos):
            partes.append(texto(x + 9, y + 47 + i * 15, atributo, 10.5, color=COLORES["tinta"]))
        return partes, alto

    cajas = {}

    def poner(clave, *args, **kwargs):
        partes, alto = clase(*args, **kwargs)
        p.extend(partes)
        cajas[clave] = (args[0], args[1], args[2], alto)

    # ── Núcleo clínico (de la sede) ─────────────────────────────────────────
    poner("usuario", 40, 110, 230, "Usuario", [
        "+ documento_id : BIGINT «PK»",
        "+ tipo_documento : VARCHAR",
        "+ nombre_completo : VARCHAR",
        "+ fecha_nacimiento : DATE",
        "+ sexo : VARCHAR",
        "+ sede_id : INT",
        "+ fhir_patient_id : VARCHAR",
    ], "sede")
    poner("atencion", 330, 110, 250, "Atencion", [
        "+ atencion_id : SERIAL «PK»",
        "+ documento_id : BIGINT «FK»",
        "+ sede_id : INT",
        "+ visita : VARCHAR «UQ»",
        "+ fecha_ingreso : TIMESTAMP",
        "+ clasificacion_triage : VARCHAR",
        "+ profesional_codigo : VARCHAR",
        "+ fhir_encounter_id : VARCHAR",
    ], "sede")
    poner("diagnostico", 650, 110, 230, "Diagnostico", [
        "+ diagnostico_id : SERIAL «PK»",
        "+ atencion_id : INT «FK»",
        "+ dx_local : VARCHAR",
        "+ cie10 : VARCHAR",
        "+ descripcion_cie10 : VARCHAR",
        "+ fhir_condition_id : VARCHAR",
    ], "sede")
    poner("observacion", 940, 110, 230, "Observacion", [
        "+ observacion_id : SERIAL «PK»",
        "+ atencion_id : INT «FK»",
        "+ loinc : VARCHAR",
        "+ valor : VARCHAR",
        "+ unidad : VARCHAR",
        "+ fhir_observation_id : VARCHAR",
    ], "sede")
    poner("tecnologia", 330, 320, 250, "TecnologiaSalud", [
        "+ tecnologia_id : UUID «PK»",
        "+ atencion_id : INT «FK»",
        "+ descripcion_medicamento : VARCHAR",
        "+ dosis / frecuencia : VARCHAR",
        "+ dias_tratamiento : INT",
    ], "sede")
    poner("egreso", 650, 320, 230, "Egreso", [
        "+ egreso_id : SERIAL «PK»",
        "+ atencion_id : INT «FK»",
        "+ fecha_salida : TIMESTAMP",
        "+ condicion_salida : VARCHAR",
        "+ sello_integridad : VARCHAR",
    ], "sede")
    poner("profesional", 40, 320, 230, "ProfesionalSalud", [
        "+ id_personal_salud : UUID «PK»",
        "+ codigo : VARCHAR «UQ»",
        "+ nombre : VARCHAR",
        "+ especialidad : VARCHAR",
        "+ activo : BOOLEAN",
    ], "sede")
    poner("sede", 40, 500, 230, "SedeInfo", [
        "+ sede_id : INT «PK»",
        "+ codigo : VARCHAR",
        "+ nombre : VARCHAR",
        "+ municipio : VARCHAR",
    ], "datos")

    # ── Plataforma (almacén central) ────────────────────────────────────────
    poner("mensaje", 330, 500, 280, "MensajeBus", [
        "+ mensaje_id : BIGSERIAL «PK»",
        "+ clave_idempotencia : VARCHAR «UQ»",
        "+ formato : hl7v2 | csv",
        "+ tipo : ADT^A01 | ORU^R01 | CSV",
        "+ sede_id : INT      + documento : VARCHAR",
        "+ estado : EstadoMensaje",
        "+ intentos / max_intentos : INT",
        "+ proximo_intento : TIMESTAMPTZ",
        "+ motivos : JSONB    + bundle : JSONB",
        "+ latencia_ms : INT",
    ], "bus", "«añadida por el parcial»")
    poner("evento", 680, 500, 280, "EventoAuditoria", [
        "+ evento_id : BIGSERIAL «PK»",
        "+ ts : TIMESTAMPTZ   (cuándo)",
        "+ actor : VARCHAR    (quién)",
        "+ rol : VARCHAR",
        "+ accion : VARCHAR   (qué)",
        "+ recurso : VARCHAR",
        "+ resultado : VARCHAR (cómo terminó)",
        "+ hash_anterior : CHAR(64)",
        "+ hash : CHAR(64)",
    ], "seguridad", "«añadida por el parcial»")
    poner("terminologia", 1030, 500, 250, "RefTerminologia", [
        "+ dx_local : VARCHAR «PK»",
        "+ cie10 : VARCHAR",
        "+ descripcion : VARCHAR",
        "— — — RefLoinc — — —",
        "+ prueba_local : VARCHAR «PK»",
        "+ loinc : VARCHAR",
        "+ unidad : VARCHAR",
    ], "fhir", "«añadida por el parcial»")

    # ── Seguridad y FHIR ────────────────────────────────────────────────────
    poner("usuarioplat", 1030, 110, 250, "UsuarioPlataforma", [
        "+ usuario : VARCHAR «PK»",
        "+ rol : Rol",
        "+ documento : BIGINT  (si es paciente)",
        "+ sede_id : INT",
        "+ permisos : lista",
    ], "vista")
    poner("bundle", 1030, 290, 250, "BundleFHIR", [
        "+ id : VARCHAR",
        "+ type : transaction | document",
        "+ entry : lista de recursos",
        "+ Patient / Encounter",
        "+ Condition (CIE-10)",
        "+ Observation (LOINC)",
    ], "fhir")

    def borde_der(clave):
        x, y, w, h = cajas[clave]
        return x + w, y + h // 2

    def borde_izq(clave):
        x, y, w, h = cajas[clave]
        return x, y + h // 2

    def borde_inf(clave):
        x, y, w, h = cajas[clave]
        return x + w // 2, y + h

    def borde_sup(clave):
        x, y, w, h = cajas[clave]
        return x + w // 2, y

    # Relaciones de composición (rombo en el lado del todo)
    for origen, destino, etiqueta in [
        ("usuario", "atencion", "1 .. *"),
        ("atencion", "diagnostico", "1 .. *"),
        ("diagnostico", "observacion", ""),
    ]:
        x1, y1 = borde_der(origen)
        x2, y2 = borde_izq(destino)
        p.extend(flecha(x1, y1, x2, y2, etiqueta, marcador="rombo"))

    x1, y1 = borde_inf("atencion")
    p.extend(flecha(x1, y1, x1, cajas["tecnologia"][1], "1 .. *", marcador="rombo"))
    x1, y1 = borde_der("tecnologia")
    p.extend(flecha(x1, y1, cajas["egreso"][0], cajas["egreso"][1] + 40, "0 .. 1", marcador="rombo"))
    x1, y1 = borde_der("profesional")
    p.extend(flecha(x1, y1, cajas["tecnologia"][0], cajas["tecnologia"][1] + 45, "atiende",
                    marcador="flecha-abierta"))
    x1, y1 = borde_sup("sede")
    p.extend(flecha(x1, y1, cajas["profesional"][0] + 115, cajas["profesional"][1] + cajas["profesional"][3],
                    "", marcador="flecha-abierta"))

    # El mensaje del bus produce el Bundle y deja el evento de auditoría
    x1, y1 = borde_der("mensaje")
    p.extend(flecha(x1, y1, cajas["evento"][0], cajas["evento"][1] + 60, "genera", punteada=True))
    p.extend(flecha(cajas["mensaje"][0] + 140, cajas["mensaje"][1], 1100, 460, "produce", punteada=True))
    p.extend(flecha(cajas["terminologia"][0], cajas["terminologia"][1] + 40,
                    cajas["evento"][0] + cajas["evento"][2], cajas["evento"][1] + 40,
                    "traduce", punteada=True))
    p.extend(flecha(cajas["evento"][0] + 20, cajas["evento"][1] + cajas["evento"][3] + 2,
                    cajas["evento"][0] + 20, cajas["evento"][1] + cajas["evento"][3] + 2, ""))

    # Autorreferencia de la cadena de hash
    ex, ey, ew, eh = cajas["evento"]
    p.append(f'<path d="M {ex + ew} {ey + eh - 24} q 40 0 40 -28 q 0 -28 -40 -28" fill="none" '
             f'stroke="{COLORES["tinta"]}" stroke-width="1.4" marker-end="url(#flecha)"/>')
    p.append(texto(ex + ew + 46, ey + eh - 48, "hash_anterior", 10, color=COLORES["suave"]))
    p.append(texto(ex + ew + 46, ey + eh - 34, "(cadena)", 10, color=COLORES["suave"]))

    p.append(texto(24, 835, "Lectura: la identidad del paciente entre sedes es el documento. "
                            "Cada nodo guarda la parte de la historia que atendió esa sede;",
                   11.5, color=COLORES["suave"]))
    p.append(texto(24, 853, "mensaje_bus, evento_auditoria y ref_terminologia viven en el almacén central "
                            "para que el bus y la auditoría sobrevivan a la caída de una sede.",
                   11.5, color=COLORES["suave"]))
    p.append(texto(24, 876, "Los campos fhir_*_id son el vínculo con FHIR y la base de la métrica de "
                            "cobertura de migración por sede.", 11.5, color=COLORES["suave"]))
    return guardar("03_clases.svg", p)


# ═══════════════════════════════════════════════════════════════════════════
# 4. Diagrama de estados del mensaje en el bus
# ═══════════════════════════════════════════════════════════════════════════
def estados() -> str:
    A, H = 1180, 640
    p = encabezado(A, H, "Estados — Ciclo de vida de un mensaje en el bus")
    p.append(texto(24, 54, "Los siete estados que exige la Fase 1, tal como los guarda la columna "
                           "mensaje_bus.estado.", 12, color=COLORES["suave"]))

    # Estado inicial
    p.append(f'<circle cx="80" cy="200" r="11" fill="{COLORES["tinta"]}"/>')
    p.append(texto(80, 232, "llega a la puerta", 10.5, color=COLORES["suave"], anclaje="middle"))

    estados_caja = {
        "recibido": (150, 170, "recibido", ["se guarda con su clave", "de idempotencia"], "bus"),
        "validado": (350, 170, "validado", ["pasó las reglas", "del validador"], "bus"),
        "transformado": (550, 170, "transformado", ["ya es un Bundle", "FHIR R4"], "fhir"),
        "entregado": (770, 170, "entregado", ["está en HAPI y", "en el nodo de la sede"], "fhir"),
        "rechazado": (350, 400, "rechazado", ["con sus motivos;", "no se reintenta"], "vista"),
        "reintentando": (560, 400, "reintentando", ["espera 1 s, 2 s, 4 s, 8 s", "(retroceso exponencial)"], "seguridad"),
        "muerto": (820, 400, "muerto", ["agotó los 4 intentos;", "reencolable a mano"], "vista"),
    }
    ancho, alto = 170, 76
    for x, y, nombre, lineas, color in estados_caja.values():
        p += caja(x, y, ancho, alto, nombre, lineas, color, radio=18)

    def der(clave):
        x, y, *_ = estados_caja[clave]
        return x + ancho, y + alto // 2

    def izq(clave):
        x, y, *_ = estados_caja[clave]
        return x, y + alto // 2

    def inf(clave):
        x, y, *_ = estados_caja[clave]
        return x + ancho // 2, y + alto

    def sup(clave):
        x, y, *_ = estados_caja[clave]
        return x + ancho // 2, y

    p.extend(flecha(91, 200, 150, 208, ""))
    p.extend(flecha(*der("recibido"), *izq("validado"), "validar: sin motivos"))
    p.extend(flecha(*der("validado"), *izq("transformado"), "normalizar"))
    p.extend(flecha(*der("transformado"), *izq("entregado"), "HAPI y nodo OK"))

    # Rechazos
    p.extend(flecha(*inf("recibido"), 350, 400, "motivos de validación"))
    p.extend(flecha(*inf("validado"), *sup("rechazado"), "4xx de HAPI"))

    # Reintentos
    p.extend(flecha(*inf("transformado"), *sup("reintentando"), "fallo transitorio"))
    p.extend(flecha(*inf("entregado"), 700, 400, "", punteada=True))
    p.extend(flecha(*der("reintentando"), *izq("muerto"), "intentos = 4"))
    p.append(f'<path d="M 645 400 q 0 -60 -10 -100" fill="none" stroke="{COLORES["tinta"]}" '
             f'stroke-width="1.5" marker-end="url(#flecha)"/>')
    p.append(texto(660, 330, "reintento con éxito", 10.5, color=COLORES["suave"]))
    p.append(f'<path d="M 905 400 q 70 -70 -20 -120" fill="none" stroke="{COLORES["tinta"]}" '
             f'stroke-width="1.5" stroke-dasharray="6 4" marker-end="url(#flecha)"/>')
    p.append(texto(930, 320, "reencolar (rol auditor", 10.5, color=COLORES["suave"]))
    p.append(texto(930, 335, "o admisionista)", 10.5, color=COLORES["suave"]))

    # Estados finales
    for clave in ("entregado", "rechazado", "muerto"):
        x, y, *_ = estados_caja[clave]
        p.append(f'<circle cx="{x + ancho + 26}" cy="{y + alto // 2}" r="11" fill="none" '
                 f'stroke="{COLORES["tinta"]}" stroke-width="1.6"/>')
        p.append(f'<circle cx="{x + ancho + 26}" cy="{y + alto // 2}" r="6" fill="{COLORES["tinta"]}"/>')

    p.append(f'<rect x="40" y="520" width="1100" height="86" rx="10" fill="{COLORES["neutro"]}" '
             f'stroke="{COLORES["linea"]}"/>')
    p.append(texto(58, 544, "Invariantes", 12.5, "700"))
    p.append(texto(58, 564, "• Un mensaje rechazado conserva sus motivos: nunca se pierde en silencio.", 11.5))
    p.append(texto(58, 582, "• La clave de idempotencia es única en la base, no en memoria: "
                            "sobrevive al reinicio del bus.", 11.5))
    p.append(texto(58, 600, "• Un estado terminal (entregado) no se degrada: si dos entregas se cruzan, "
                            "gana la que entregó.", 11.5))
    return guardar("04_estados.svg", p)


# ═══════════════════════════════════════════════════════════════════════════
# 5. Diagrama de arquitectura
# ═══════════════════════════════════════════════════════════════════════════
def arquitectura() -> str:
    A, H = 1320, 940
    p = encabezado(A, H, "Arquitectura — De las sedes a las cuatro vistas")
    p.append(texto(24, 54, "Los mensajes bajan de las sedes por el HSB hacia los tres almacenes; la API "
                           "lee de ellos y sirve a las cuatro vistas con permisos por rol.",
                   12, color=COLORES["suave"]))

    def banda(y, alto, etiqueta):
        p.append(f'<rect x="24" y="{y}" width="{A - 48}" height="{alto}" rx="12" fill="none" '
                 f'stroke="{COLORES["linea"]}" stroke-width="1.2" stroke-dasharray="7 5"/>')
        p.append(texto(38, y + 20, etiqueta, 11.5, "700", color=COLORES["suave"]))

    # ── Capa 1: sistemas legados ───────────────────────────────────────────
    banda(78, 118, "1 · SISTEMAS LEGADOS DE LAS SEDES  (no se reemplazan)")
    sedes_legado = [
        (70, "HIS Sede 1", ["Sincelejo", "HL7 v2 ORU^R01"]),
        (430, "HIS Sede 2", ["Cartagena", "HL7 v2 ADT^A01"]),
        (790, "HIS Sede 3", ["Corozal", "CSV legado (;)"]),
    ]
    for x, nombre, lineas in sedes_legado:
        p += caja(x, 106, 260, 72, nombre, lineas, "sede")
    p += caja(1090, 106, 200, 72, "Datos sintéticos", ["ejemplos/*.hl7", "ejemplos/*.csv"], "neutro")

    # ── Capa 2: bus ────────────────────────────────────────────────────────
    banda(216, 150, "2 · BUS DE INTEGRACIÓN  ·  RF1 y RF3  ·  puerto 8000")
    p += caja(70, 248, 980, 100, "HSB — Health Service Bus  (FastAPI)", [], "bus")
    etapas = ["recepción", "validación", "transformación\na FHIR R4", "enrutamiento\npor sede",
              "entrega", "auditoría"]
    for i, etapa in enumerate(etapas):
        x = 92 + i * 158
        p.append(f'<rect x="{x}" y="{286}" width="140" height="46" rx="8" fill="{COLORES["fondo"]}" '
                 f'stroke="{COLORES["bus_borde"]}" stroke-width="1.3"/>')
        for j, linea in enumerate(etapa.split("\n")):
            p.append(texto(x + 70, 306 + j * 13 - (6 if "\n" in etapa else 0), linea, 10.5, "600",
                           anclaje="middle"))
        if i < len(etapas) - 1:
            p.extend(flecha(x + 140, 309, x + 156, 309, ""))
    p += caja(1090, 248, 200, 100, "Cola persistente",
              ["reintentos 1·2·4·8 s", "cola de muertos", "idempotencia por", "clave única"], "bus")

    for x, _, _ in sedes_legado:
        p.extend(flecha(x + 130, 178, x + 130, 246, ""))
    p.append(texto(205, 206, "POST /hsb/hl7", 10.5, color=COLORES["suave"], anclaje="middle"))
    p.append(texto(565, 206, "POST /hsb/hl7", 10.5, color=COLORES["suave"], anclaje="middle"))
    p.append(texto(925, 206, "POST /hsb/csv?sede=3", 10.5, color=COLORES["suave"], anclaje="middle"))

    # ── Capa 3: almacenamiento ─────────────────────────────────────────────
    banda(386, 190, "3 · ALMACENAMIENTO DISTRIBUIDO  ·  RF2 y RF4")
    almacenes = [
        (70, "pg_nodo1", ["Sede 1 · Sincelejo", "historia_clinica", "puerto 5433"], "datos"),
        (300, "pg_nodo2", ["Sede 2 · Cartagena", "historia_clinica", "puerto 5434"], "datos"),
        (530, "pg_nodo3", ["Sede 3 · Corozal", "historia_clinica", "puerto 5435"], "datos"),
        (770, "HAPI FHIR", ["servidor FHIR R4", "Patient · Encounter", "Condition · Observation"], "fhir"),
        (1020, "pg_central", ["mensaje_bus", "evento_auditoria", "ref_terminologia"], "seguridad"),
    ]
    for x, nombre, lineas, color in almacenes:
        ancho = 200 if x < 700 else 220
        p += caja(x, 416, ancho, 96, nombre, lineas, color)

    p.extend(flecha(210, 350, 170, 414, "1 PUT", desvio_etiqueta=(-26, 0)))
    p.extend(flecha(520, 350, 400, 414, ""))
    p.extend(flecha(830, 350, 630, 414, ""))
    p.extend(flecha(880, 350, 880, 414, "primero HAPI", desvio_etiqueta=(52, -2)))
    p.extend(flecha(1190, 350, 1130, 414, ""))

    p.append(texto(70, 538, "Fragmentación horizontal: un nodo por sede. La clave de acceso es el documento "
                            "del paciente, que es por lo que consultan todas las vistas.",
                   11, color=COLORES["suave"]))
    p.append(texto(70, 555, "Según CAP se elige disponibilidad: si una sede cae, la vista responde con las "
                            "otras dos y marca la que falta (consistencia eventual al reintegrar).",
                   11, color=COLORES["suave"]))

    # ── Capa 4: API ────────────────────────────────────────────────────────
    banda(580, 130, "4 · API Y SEGURIDAD  ·  RF5  ·  puerto 8001")
    p += caja(70, 608, 700, 86, "API (FastAPI)",
              ["consulta unificada de las 3 sedes · Reporte de HC · /health · /metrics",
               "ninguna vista habla directo con las bases de las sedes"], "vista")
    p += caja(810, 608, 230, 86, "Seguridad",
              ["JWT firmado (HS256)", "4 roles y matriz", "de permisos"], "seguridad")
    p += caja(1070, 608, 220, 86, "Auditoría",
              ["cadena SHA-256", "AuditEvent FHIR", "verificador"], "seguridad")

    for x in (170, 400, 630, 880, 1130):
        p.extend(flecha(x, 512, x if x < 770 else 420, 606, ""))
    p.extend(flecha(880, 694, 790, 660, "", punteada=True))
    p.extend(flecha(1070, 660, 1044, 660, "", punteada=True))

    # ── Capa 5: vistas ─────────────────────────────────────────────────────
    banda(718, 150, "5 · LAS CUATRO VISTAS POR ROL  ·  RF6")
    vistas = [
        (70, "Paciente", ["su historia unificada", "su Bundle FHIR", "quién la consultó"]),
        (390, "Admisionista", ["buscar y registrar", "duplicados entre sedes", "estado del bus"]),
        (710, "Médico", ["historia unificada", "CIE-10, fórmula, egreso", "sello de integridad"]),
        (1030, "Reporte de HC", ["por sede + cobertura", "sello e impresión", "tablero de estado"]),
    ]
    for x, nombre, lineas in vistas:
        p += caja(x, 748, 260, 100, nombre, lineas, "vista")
        p.extend(flecha(x + 130, 694, x + 130, 746, ""))

    p.append(texto(24, 890, "Requisitos no funcionales: un solo `docker compose up` levanta todo; "
                            "cada servicio expone /health y /metrics;", 11.5, color=COLORES["suave"]))
    p.append(texto(24, 908, "y la caída de una sede degrada la vista en vez de tumbarla.",
                   11.5, color=COLORES["suave"]))
    return guardar("05_arquitectura.svg", p)


if __name__ == "__main__":
    for funcion in (casos_de_uso, secuencia, clases, estados, arquitectura):
        print("generado:", os.path.relpath(funcion(), os.getcwd()))
