"""
fhir/transformador.py — Transformación del formulario de identificación
colombiano (15 campos de la HC, Resolución 1995/1999 y anexo técnico de
interoperabilidad) a un recurso `Patient` de FHIR R4.

Se emite JSON plano (dict) y la validación de referencia la hace el servidor
HAPI (`$validate`): así la plataforma no queda atada a la versión de una
librería de modelos.
"""

from typing import Any, Dict

from fhir import SISTEMA_DOCUMENTO, SISTEMA_V2_0203

# Tipos de documento colombianos → HL7 v2-0203. `NI` = National unique
# individual identifier, que es la lectura correcta de la cédula (la versión
# anterior de este módulo usaba `DL`, licencia de conducción, por error).
TIPO_DOCUMENTO_V2 = {
    "CC": "NI",
    "TI": "NI",
    "CE": "NI",
    "PA": "PPN",
    "RC": "NI",
    "MS": "NI",
    "AS": "NI",
    "NU": "NI",
}

SEXO_FHIR = {
    "M": "male",
    "F": "female",
    "O": "other",
    "U": "unknown",
    "MALE": "male",
    "FEMALE": "female",
    "OTHER": "other",
    "UNKNOWN": "unknown",
    "MASCULINO": "male",
    "FEMENINO": "female",
}

MUNICIPIOS_DANE = {
    "11001": "Bogotá D.C.",
    "05001": "Medellín",
    "76001": "Cali",
    "08001": "Barranquilla",
    "13001": "Cartagena",
    "68001": "Bucaramanga",
    "66001": "Pereira",
    "17001": "Manizales",
    "50001": "Villavicencio",
    "70001": "Sincelejo",
    "70215": "Corozal",
}


class FHIRTransformer:
    """Transforma datos de la HC colombiana a recursos FHIR R4."""

    @staticmethod
    def to_fhir_patient(data: Dict[str, Any]) -> Dict[str, Any]:
        documento = str(data["numeroDocumento"]).strip()
        tipo = str(data.get("tipoDocumento") or "CC").upper()

        patient: Dict[str, Any] = {
            "resourceType": "Patient",
            "identifier": [
                {
                    "use": "official",
                    "system": SISTEMA_DOCUMENTO,
                    "value": documento,
                    "type": {
                        "coding": [
                            {
                                "system": SISTEMA_V2_0203,
                                "code": TIPO_DOCUMENTO_V2.get(tipo, "NI"),
                                "display": tipo,
                            }
                        ],
                        "text": tipo,
                    },
                }
            ],
            "active": True,
            "name": [{"use": "official", "text": str(data["nombreCompleto"]).strip()}],
            "gender": FHIRTransformer._sexo(data.get("sexo")),
            "birthDate": str(data["fechaNacimiento"]),
        }

        municipio = str(data.get("municipioResidencia") or "")
        if municipio:
            patient["address"] = [
                {
                    "use": "home",
                    "country": data.get("paisResidencia") or "CO",
                    "city": FHIRTransformer._municipio(municipio),
                    "extension": [
                        {
                            "url": "http://hl7.org/fhir/StructureDefinition/iso21090-SC-coding",
                            "valueCoding": {"system": "https://www.dane.gov.co/divipola", "code": municipio},
                        }
                    ],
                }
            ]

        extensiones = []
        if data.get("paisNacionalidad"):
            extensiones.append(
                {
                    "url": "http://hl7.org/fhir/StructureDefinition/patient-nationality",
                    "extension": [
                        {
                            "url": "code",
                            "valueCodeableConcept": {
                                "coding": [
                                    {"system": "urn:iso:std:iso:3166", "code": str(data["paisNacionalidad"])}
                                ]
                            },
                        }
                    ],
                }
            )
        if data.get("ocupacion"):
            extensiones.append(
                {
                    "url": "http://hl7.org/fhir/StructureDefinition/patient-occupation",
                    "valueString": str(data["ocupacion"]),
                }
            )
        if data.get("etnia") and str(data["etnia"]).lower() not in ("ninguna", ""):
            extensiones.append(
                {
                    "url": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-ethnicity",
                    "valueCodeableConcept": {"text": str(data["etnia"])},
                }
            )
        if data.get("categoriaDiscapacidad"):
            extensiones.append(
                {
                    "url": "http://hl7.org/fhir/StructureDefinition/patient-disability",
                    "valueCodeableConcept": {"text": str(data["categoriaDiscapacidad"])},
                }
            )
        if data.get("genero"):
            extensiones.append(
                {
                    "url": "http://hl7.org/fhir/StructureDefinition/patient-genderIdentity",
                    "valueCodeableConcept": {"text": str(data["genero"])},
                }
            )
        if extensiones:
            patient["extension"] = extensiones
        return patient

    @staticmethod
    def _sexo(valor: Any) -> str:
        return SEXO_FHIR.get(str(valor or "U").strip().upper(), "unknown")

    @staticmethod
    def _municipio(codigo: str) -> str:
        return MUNICIPIOS_DANE.get(codigo, "No registrado")

    # Alias conservados por compatibilidad con la versión anterior del módulo.
    _map_document_type = staticmethod(lambda tipo: TIPO_DOCUMENTO_V2.get(str(tipo).upper(), "NI"))
    _get_city_name = staticmethod(lambda codigo: MUNICIPIOS_DANE.get(codigo, "No registrado"))
