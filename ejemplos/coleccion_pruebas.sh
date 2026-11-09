#!/usr/bin/env bash
# ============================================================================
# ejemplos/coleccion_pruebas.sh — Colección de pruebas de la plataforma.
#
# Es el equivalente en curl de la colección de Postman: una llamada por cada
# cosa que el parcial evalúa, con lo que se espera de cada una.
#
#   ./ejemplos/coleccion_pruebas.sh            ejecuta todo
#   ./ejemplos/coleccion_pruebas.sh seguridad  solo ese grupo
#
# Grupos: salud, ingesta, fhir, consulta, seguridad, auditoria, datos, bus
# ============================================================================
set -uo pipefail
cd "$(dirname "$0")/.."

API=${API:-http://localhost:8001}
HSB=${HSB:-http://localhost:8000}
HAPI=${HAPI:-http://localhost:8080/fhir}
GRUPO=${1:-todos}

n=$'\033[0m'; az=$'\033[1;34m'; gr=$'\033[0;90m'
titulo() { echo; echo "${az}── $* ${n}"; }
llamada() { echo "${gr}\$ $*${n}"; }

token() {
    curl -s -X POST "$API/auth/login" -H 'Content-Type: application/json' \
         -d "{\"usuario\":\"$1\",\"password\":\"$2\"}" \
      | python3 -c 'import json,sys; print(json.load(sys.stdin).get("access_token",""))'
}
quiere() { [[ "$GRUPO" == "todos" || "$GRUPO" == "$1" ]]; }

TOK_AUD=$(token auditor1 "${PWD_AUDITOR:-auditor123}")
TOK_MED=$(token medico1  "${PWD_MEDICO:-medico123}")
TOK_ADM=$(token admision2 "${PWD_ADMISION:-admision123}")
TOK_PAC=$(token paciente1007 "${PWD_PACIENTE:-paciente123}")

# ─────────────────────────────── 1 · Salud ─────────────────────────────────
if quiere salud; then
titulo "1 · Salud y métricas  (esperado: estado ok o degradado)"
llamada "GET $API/health";           curl -s "$API/health" | python3 -m json.tool | head -20
llamada "GET $HSB/health";           curl -s "$HSB/health" | python3 -m json.tool | head -20
llamada "GET $HAPI/metadata";        curl -s "$HAPI/metadata" | python3 -c 'import json,sys; print("fhirVersion:", json.load(sys.stdin).get("fhirVersion"))'
llamada "GET $API/metrics";          curl -s "$API/metrics" | head -8
llamada "GET $HSB/metrics.json";     curl -s "$HSB/metrics.json" | python3 -m json.tool | head -16
fi

# ────────────────────────────── 2 · Ingesta ────────────────────────────────
if quiere ingesta; then
titulo "2 · Ingesta — el contrato de LEEME.md"
echo "   01 ADT^A01 sede 2   → entregado: Patient 1007, Encounter, Condition J45.9"
curl -s -X POST --data-binary @ejemplos/01_adt_a01_valido_sede2.hl7 "$HSB/hsb/hl7" | python3 -m json.tool
echo "   02 ORU^R01 sede 1   → entregado: Observation LOINC 718-7 = 13,8 g/dL"
curl -s -X POST --data-binary @ejemplos/02_oru_r01_laboratorio_sede1.hl7 "$HSB/hsb/hl7" | python3 -m json.tool
echo "   03 ADT inválido     → rechazado con 3 motivos"
curl -s -X POST --data-binary @ejemplos/03_adt_a01_invalido.hl7 "$HSB/hsb/hl7" | python3 -m json.tool
echo "   04 CSV sede 3       → 3 entregados (1008, 1009, 1010) y 2 rechazados"
curl -s -X POST --data-binary @ejemplos/04_sede3_legado.csv "$HSB/hsb/csv?sede=3" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print("   resumen:", d["resumen"])'
echo "   01 otra vez         → duplicado, sin crear nada"
curl -s -X POST --data-binary @ejemplos/01_adt_a01_valido_sede2.hl7 "$HSB/hsb/hl7" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print("   resultado:", d["resultado"], "| estado del original:", d.get("estado"))'
fi

# ──────────────────────────────── 3 · FHIR ─────────────────────────────────
if quiere fhir; then
titulo "3 · FHIR — recursos y validación"
llamada "GET $HAPI/Patient?identifier=1007"
curl -s "$HAPI/Patient?identifier=1007" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("   total:", d.get("total"), "| ids:", [e["resource"]["id"] for e in d.get("entry",[])])'
llamada "GET $HAPI/Observation/obs-V-S1-0150-7187"
curl -s "$HAPI/Observation/obs-V-S1-0150-7187" | python3 -c 'import json,sys; d=json.load(sys.stdin); v=d.get("valueQuantity",{}); print("   LOINC", d["code"]["coding"][0]["code"], "=", v.get("value"), v.get("unit"))' 2>/dev/null
llamada "POST $HSB/hsb/validar?contra_hapi=true  (Bundle transaction)"
curl -s -X POST --data-binary @ejemplos/01_adt_a01_valido_sede2.hl7 \
     "$HSB/hsb/validar?formato=hl7v2&contra_hapi=true" \
  | python3 -c 'import json,sys; r=json.load(sys.stdin)["resultados"][0]; v=r.get("validacion_hapi",{}); print("   válido para HAPI:", v.get("valido"), "| errores:", v.get("errores"))'
llamada "GET $API/api/v1/reporte/1001/bundle/validar  (Bundle document)"
curl -s -H "Authorization: Bearer $TOK_AUD" "$API/api/v1/reporte/1001/bundle/validar" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print("   válido:", d["valido"], "| errores:", d["errores"])'
llamada "GET $HSB/hsb/terminologia  (ConceptMap)"
curl -s "$HSB/hsb/terminologia" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("   origen:", d["origen"], "| CIE-10:", len(d["cie10"]), "| LOINC:", len(d["loinc"]))'
fi

# ───────────────────────────── 4 · Consulta ────────────────────────────────
if quiere consulta; then
titulo "4 · Consulta unificada de las 3 sedes"
llamada "GET $API/api/v1/historia/1001"
curl -s -H "Authorization: Bearer $TOK_MED" "$API/api/v1/historia/1001" \
  | python3 -c '
import json,sys
d=json.load(sys.stdin)
print("   paciente:", d["paciente"]["nombre_completo"])
print("   sedes con registro:", d["resumen"]["sedes_con_registro"], "| parcial:", d["parcial"])
print("   atenciones:", d["resumen"]["atenciones"], "| diagnósticos:", d["resumen"]["diagnosticos"], "| laboratorio:", d["resumen"]["observaciones"])
for a in d["atenciones"]:
    print("    ", a["fecha_ingreso"], a["sede_nombre"], a["visita"], [x["cie10"] for x in a["diagnosticos"]])'
llamada "GET $API/api/v1/pacientes/1001/sedes  (duplicados entre sedes)"
curl -s -H "Authorization: Bearer $TOK_ADM" "$API/api/v1/pacientes/1001/sedes" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print("   sedes:", d["sedes_con_registro"], "| duplicado:", d["duplicado_entre_sedes"])'
llamada "GET $API/api/v1/reporte/1001"
curl -s -H "Authorization: Bearer $TOK_AUD" "$API/api/v1/reporte/1001" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); c=d["cobertura_campos"]; print("   completo:", d["completo"], "| cobertura de campos:", c["cobertura_pct"], "% | sello:", d["sello_integridad"][:24], "…")'
fi

# ──────────────────────────── 5 · Seguridad ────────────────────────────────
if quiere seguridad; then
titulo "5 · Seguridad — acceso permitido y denegado"
probar() {
  local etiqueta=$1 metodo=$2 ruta=$3 tok=$4 esperado=$5 code
  code=$(curl -s -o /dev/null -w "%{http_code}" -X "$metodo" -H "Authorization: Bearer $tok" "$API$ruta")
  local marca="OK "; [[ "$code" != "$esperado" ]] && marca="MAL"
  printf "   [%s] %-3s (esperado %s)  %s\n" "$marca" "$code" "$esperado" "$etiqueta"
}
probar "paciente ve SU historia"                  GET  /api/v1/paciente/mi-historia    "$TOK_PAC" 200
probar "paciente ve la de OTRO"                   GET  /api/v1/historia/1001           "$TOK_PAC" 403
probar "paciente pide el reporte de otro"         GET  /api/v1/reporte/1001            "$TOK_PAC" 403
probar "paciente intenta escribir diagnóstico"    POST /api/v1/medico/diagnostico      "$TOK_PAC" 403
probar "paciente intenta leer la auditoría"       GET  /api/v1/auditoria               "$TOK_PAC" 403
probar "admisionista busca paciente"              GET  "/api/v1/pacientes/buscar?documento=1001" "$TOK_ADM" 200
probar "admisionista ve el estado del bus"        GET  "/api/v1/bus/mensajes?limite=5" "$TOK_ADM" 200
probar "admisionista escribe diagnóstico"         POST /api/v1/medico/diagnostico      "$TOK_ADM" 403
probar "admisionista ve el tablero"               GET  /api/v1/plataforma/estado       "$TOK_ADM" 403
probar "médico ve la historia unificada"          GET  /api/v1/historia/1001           "$TOK_MED" 200
probar "médico ve el tablero"                     GET  /api/v1/plataforma/estado       "$TOK_MED" 200
probar "médico abre una atención"                 POST /api/v1/medico/atencion         "$TOK_MED" 403
probar "médico apaga un nodo"                     POST /api/v1/plataforma/nodos/2/stop "$TOK_MED" 403
probar "auditor lee la auditoría"                 GET  "/api/v1/auditoria?limite=5"    "$TOK_AUD" 200
probar "auditor verifica la cadena"               GET  /api/v1/auditoria/verificar     "$TOK_AUD" 200
probar "sin token"                                GET  /api/v1/historia/1001           ""         401
llamada "GET $API/auth/matriz"
curl -s "$API/auth/matriz" | python3 -c '
import json,sys
m=json.load(sys.stdin)
print("   " + "acción".ljust(46) + "".join(r[:5].ljust(8) for r in m["roles"]))
for f in m["matriz"]:
    print("   " + f["accion"][:45].ljust(46) + "".join(("sí" if f[r] else "no").ljust(8) for r in m["roles"]))'
fi

# ──────────────────────────── 6 · Auditoría ────────────────────────────────
if quiere auditoria; then
titulo "6 · Auditoría encadenada por hash"
llamada "GET $API/api/v1/auditoria/verificar"
curl -s -H "Authorization: Bearer $TOK_AUD" "$API/api/v1/auditoria/verificar" | python3 -m json.tool
llamada "GET $API/api/v1/auditoria?limite=5"
curl -s -H "Authorization: Bearer $TOK_AUD" "$API/api/v1/auditoria?limite=5" \
  | python3 -c '
import json,sys
for e in json.load(sys.stdin)["eventos"]:
    print(f"   #{e[\"evento_id\"]:<4} {e[\"actor\"]:<16} {e[\"accion\"]:<22} {e[\"resultado\"]:<10} {e[\"hash\"][:16]}…")'
llamada "GET $API/api/v1/auditoria/1/fhir  (AuditEvent)"
curl -s -H "Authorization: Bearer $TOK_AUD" "$API/api/v1/auditoria/1/fhir" | python3 -m json.tool | head -14
fi

# ─────────────────────── 7 · Capa de datos ─────────────────────────────────
if quiere datos; then
titulo "7 · Capa de datos — cobertura, ACID y EXPLAIN"
llamada "GET $API/api/v1/datos/cobertura"
curl -s "$API/api/v1/datos/cobertura" | python3 -c '
import json,sys
d=json.load(sys.stdin)
for c in d["por_sede"]: print(f"   sede {c[\"sede_id\"]} {c[\"nombre\"]:<11} {c[\"migrados\"]}/{c[\"total\"]} = {c[\"cobertura_pct\"]} %")
print("   GLOBAL:", d["global"]["cobertura_pct"], "%")'
llamada "POST $API/api/v1/datos/prueba-acid?sede=1"
curl -s -X POST -H "Authorization: Bearer $TOK_MED" "$API/api/v1/datos/prueba-acid?sede=1" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print("   atómica:", d["atomica"], "| error forzado:", d["error_forzado"][:60])'
llamada "GET $API/api/v1/datos/explain?documento=1001"
curl -s -H "Authorization: Bearer $TOK_MED" "$API/api/v1/datos/explain?documento=1001" \
  | python3 -c '
import json,sys
for nd in json.load(sys.stdin)["nodos"]:
    linea = (nd.get("plan_paciente") or ["(sede no disponible)"])[0]
    print(f"   sede {nd[\"sede_id\"]} {nd[\"nombre\"]:<11} {linea[:70]}")'
fi

# ──────────────────────────────── 8 · Bus ──────────────────────────────────
if quiere bus; then
titulo "8 · Estado del bus"
llamada "GET $HSB/hsb/mensajes?limite=10"
curl -s "$HSB/hsb/mensajes?limite=10" | python3 -c '
import json,sys
for m in json.load(sys.stdin)["mensajes"]:
    motivos = "; ".join(m.get("motivos") or [])[:52]
    print(f"   #{m[\"mensaje_id\"]:<4} {m[\"formato\"]:<6} {str(m[\"tipo\"]):<9} sede {m[\"sede_id\"]} doc {str(m[\"documento\"]):<6} {m[\"estado\"]:<13} {motivos}")'
llamada "GET $HSB/hsb/muertos"
curl -s "$HSB/hsb/muertos" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("   mensajes muertos:", d["total"])'
llamada "GET $HSB/hsb/reglas"
curl -s "$HSB/hsb/reglas" | python3 -c '
import json,sys
d=json.load(sys.stdin)
print("   HL7 exige CIE-10:", d["hl7_exige_cie10"])
for r in d["reglas"]: print(f"   {r[\"campo\"]:<28} {r[\"regla\"]}")'
fi

echo
echo "${az}Colección terminada.${n}  Grupos: salud ingesta fhir consulta seguridad auditoria datos bus"
