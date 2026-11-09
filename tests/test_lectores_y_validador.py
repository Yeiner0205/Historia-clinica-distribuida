"""
Pruebas unitarias de los lectores del bus (HL7 v2 y CSV legado) y del
validador, contra el contrato de `ejemplos/LEEME.md`.
"""

import pytest

from hsb import csv_legado, hl7, validador
from tests.conftest import leer_ejemplo


# ─────────────────────────── Lector HL7 v2 ──────────────────────────────────
def test_adt_a01_se_lee_completo():
    registro = hl7.parsear(leer_ejemplo("01_adt_a01_valido_sede2.hl7"))

    assert registro["tipo"] == "ADT^A01"
    assert registro["sede_codigo"] == "SEDE2"
    assert registro["sede_id"] == 2
    assert registro["clave_idempotencia"] == "MSG-0001"   # MSH-10
    assert registro["documento"] == "1007"                 # PID-3.1
    assert registro["nombre_completo"] == "Andrea Rojas"   # PID-5 = Apellido^Nombre
    assert registro["fecha_nacimiento"] == "19900214"      # PID-7
    assert registro["sexo"] == "F"                         # PID-8
    assert registro["clase_encuentro"] == "O"              # PV1-2
    assert registro["profesional"]["codigo"] == "MED-02"   # PV1-7
    assert registro["visita"] == "V-S2-0101"               # PV1-19
    assert registro["fecha_ingreso"] == "202611071015"     # PV1-44
    assert registro["diagnosticos"][0]["origen"] == "J45.9"  # DG1-3


def test_oru_r01_trae_la_observacion():
    registro = hl7.parsear(leer_ejemplo("02_oru_r01_laboratorio_sede1.hl7"))

    assert registro["tipo"] == "ORU^R01"
    assert registro["sede_id"] == 1
    observacion = registro["observaciones"][0]
    assert observacion["codigo"] == "718-7"      # OBX-3
    assert observacion["valor"] == "13.8"        # OBX-5
    assert observacion["unidad"] == "g/dL"       # OBX-6


def test_los_segmentos_se_separan_por_retorno_de_carro_o_salto_de_linea():
    crudo = leer_ejemplo("01_adt_a01_valido_sede2.hl7")
    con_lf = crudo.replace("\r", "\n")
    con_crlf = crudo.replace("\r", "\r\n")

    assert hl7.parsear(crudo)["documento"] == hl7.parsear(con_lf)["documento"]
    assert hl7.parsear(crudo)["documento"] == hl7.parsear(con_crlf)["documento"]


def test_texto_que_no_es_hl7_se_rechaza():
    with pytest.raises(hl7.ErrorHL7):
        hl7.parsear("esto no es un mensaje HL7")
    with pytest.raises(hl7.ErrorHL7):
        hl7.parsear("")


# ─────────────────────────── Lector CSV legado ──────────────────────────────
def test_csv_legado_produce_una_fila_por_paciente():
    registros = csv_legado.parsear(leer_ejemplo("04_sede3_legado.csv"), sede_id=3)

    assert len(registros) == 5
    assert [r["documento"] for r in registros] == ["1008", "1009", "1010", "1011", "12"]
    assert registros[0]["nombre_completo"] == "Camila Suarez Pineda"
    assert registros[0]["sede_id"] == 3
    assert registros[1]["triage"] is None, "El triage vacío del legado queda vacío, no inventado"


def test_la_clave_de_idempotencia_del_csv_es_estable_y_distinta_por_fila():
    primero = csv_legado.parsear(leer_ejemplo("04_sede3_legado.csv"), sede_id=3)
    segundo = csv_legado.parsear(leer_ejemplo("04_sede3_legado.csv"), sede_id=3)

    claves_1 = [r["clave_idempotencia"] for r in primero]
    claves_2 = [r["clave_idempotencia"] for r in segundo]

    assert claves_1 == claves_2, "La misma fila debe dar siempre la misma clave"
    assert len(set(claves_1)) == 5, "Cada fila es un mensaje independiente"


def test_csv_sin_columnas_obligatorias_se_rechaza():
    with pytest.raises(csv_legado.ErrorCSV):
        csv_legado.parsear("a;b;c\n1;2;3", sede_id=1)


# ──────────────── Validador: contrato de ejemplos/LEEME.md ──────────────────
def test_los_dos_mensajes_validos_pasan():
    for archivo in ("01_adt_a01_valido_sede2.hl7", "02_oru_r01_laboratorio_sede1.hl7"):
        registro = hl7.parsear(leer_ejemplo(archivo))
        assert validador.validar(registro) == [], f"{archivo} debería ser válido"


def test_el_mensaje_invalido_se_rechaza_con_tres_motivos():
    """El contrato de LEEME.md: documento no numérico, sexo no válido y
    diagnóstico sin mapeo a CIE-10."""
    registro = hl7.parsear(leer_ejemplo("03_adt_a01_invalido.hl7"))
    motivos = validador.validar(registro)

    assert len(motivos) == 3, motivos
    assert any("documento no numérico" in m for m in motivos)
    assert any("sexo no válido" in m for m in motivos)
    assert any("CIE-10" in m for m in motivos)


def test_el_csv_de_la_sede_3_da_tres_validos_y_dos_rechazados():
    """El contrato de LEEME.md: 1008, 1009 y 1010 entregados; 1011 (diagnóstico
    sin mapeo) y 12 (documento de 2 dígitos) rechazados."""
    registros = csv_legado.parsear(leer_ejemplo("04_sede3_legado.csv"), sede_id=3)
    resultados = {r["documento"]: validador.validar(r) for r in registros}

    assert resultados["1008"] == []
    assert resultados["1009"] == []
    assert resultados["1010"] == []
    assert any("sin mapeo a CIE-10" in m for m in resultados["1011"])
    assert any("longitud inválida" in m for m in resultados["12"])


@pytest.mark.parametrize(
    "documento,valido",
    [("1007", True), ("123456789012345", True), ("12", False), ("ABC123", False), ("", False)],
)
def test_regla_del_documento(documento, valido):
    registro = {
        "formato": "csv", "documento": documento, "nombre_completo": "Prueba Sintetica",
        "sexo": "F", "sede_id": 1, "diagnosticos": [], "observaciones": [],
    }
    assert (validador.validar(registro) == []) is valido


def test_la_tabla_de_reglas_esta_documentada():
    """La plantilla v7 pide una tabla de reglas de validación en el informe."""
    reglas = validador.reglas()
    assert len(reglas) >= 8
    assert all({"campo", "regla", "si_falla"} <= set(r) for r in reglas)
