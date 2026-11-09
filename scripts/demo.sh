#!/usr/bin/env bash
# ============================================================================
# scripts/demo.sh — Guion de la demostración de la Fase 5, ejecutado paso a
# paso y narrado. Es el mismo guion de docs/05_guion_demo.md.
#
#   ./scripts/demo.sh            arranca desde cero y hace la demostración
#   ./scripts/demo.sh --sin-reinicio   usa la plataforma que ya está arriba
#
# Entre paso y paso espera un Enter, para poder explicar mientras tanto.
# Con AUTO=1 no se detiene (útil para grabar o para comprobar que todo corre).
# ============================================================================
set -uo pipefail

cd "$(dirname "$0")/.."

API=${API:-http://localhost:8001}
HSB=${HSB:-http://localhost:8000}
HAPI=${HAPI:-http://localhost:8080/fhir}
AUTO=${AUTO:-0}
REINICIAR=1
[[ "${1:-}" == "--sin-reinicio" ]] && REINICIAR=0

# ── Presentación ────────────────────────────────────────────────────────────
n=$'\033[0m'; az=$'\033[1;34m'; ve=$'\033[1;32m'; am=$'\033[1;33m'; ro=$'\033[1;31m'; gr=$'\033[0;90m'

paso()    { echo; echo "${az}═══ $* ${n}"; }
dice()    { echo "${gr}   $*${n}"; }
ok()      { echo "${ve}   ✓ $*${n}"; }
alerta()  { echo "${am}   ! $*${n}"; }
error()   { echo "${ro}   ✗ $*${n}"; }
corre()   { echo "${gr}   \$ $*${n}"; eval "$@"; }
pausa()   { [[ "$AUTO" == "1" ]] && return 0; echo; read -rp "   ${gr}[Enter para continuar]${n} " _; }

json() { python3 -c "import json,sys
try:
    d = json.load(sys.stdin)
except Exception as e:
    print('   (respuesta no JSON)', e); raise SystemExit
$1"; }

token_de() {
    curl -s -X POST "$API/auth/login" -H 'Content-Type: application/json' \
         -d "{\"usuario\":\"$1\",\"password\":\"$2\"}" \
      | python3 -c 'import json,sys; print(json.load(sys.stdin).get("access_token",""))'
}

echo
echo "${az}╔═══════════════════════════════════════════════════════════════════════╗${n}"
echo "${az}║  Plataforma distribuida de interoperabilidad clínica                  ║${n}"
echo "${az}║  Demostración del parcial final — red de IPS con tres sedes           ║${n}"
echo "${az}╚═══════════════════════════════════════════════════════════════════════╝${n}"

# ── Paso 0 · arranque desde cero ────────────────────────────────────────────
if [[ "$REINICIAR" == "1" ]]; then
    paso "Paso 0 · Arranque desde cero"
    dice "Siete contenedores: tres nodos (uno por sede), el almacén central,"
    dice "HAPI FHIR, el bus y la API. Los nodos cargan su esquema y sus datos"
    dice "sintéticos solos: no hay paso manual de inicialización."
    corre "docker compose down -v >/dev/null 2>&1"
    corre "docker compose up -d >/dev/null 2>&1"
    ./scripts/esperar_servicios.sh 240 || { error "La plataforma no arrancó"; exit 1; }
else
    paso "Paso 0 · Usando la plataforma que ya está levantada"
    ./scripts/esperar_servicios.sh 60 || { error "La plataforma no responde"; exit 1; }
fi
pausa

# ── Paso 1 · cobertura en 0 % ───────────────────────────────────────────────
paso "Paso 1 · Las tres sedes con cobertura FHIR en 0 %"
dice "Los pacientes ya existen en el legado, pero ninguno tiene recurso FHIR."
curl -s "$API/api/v1/datos/cobertura" | json '
for c in d["por_sede"]:
    print("   sede %s %-11s %s/%s pacientes = %s %%" % (
        c["sede_id"], c["nombre"], c["migrados"], c["total"], c["cobertura_pct"]))
print("   GLOBAL: %s %%" % d["global"]["cobertura_pct"])'
pausa

# ── Paso 2 · un HL7 y un CSV ────────────────────────────────────────────────
paso "Paso 2 · Un mensaje HL7 v2 y uno CSV"

dice "ADT^A01 de la sede 2 (Cartagena): admisión de Andrea Rojas, documento 1007"
curl -s -X POST --data-binary @ejemplos/01_adt_a01_valido_sede2.hl7 "$HSB/hsb/hl7" | json '
print("  ", d["resultado"].upper(), "en", d.get("latencia_ms"), "ms")
for r in d.get("recursos") or []: print("     ", r)'

dice "ORU^R01 de la sede 1 (Sincelejo): hemoglobina del paciente 1001"
curl -s -X POST --data-binary @ejemplos/02_oru_r01_laboratorio_sede1.hl7 "$HSB/hsb/hl7" | json '
print("  ", d["resultado"].upper(), "en", d.get("latencia_ms"), "ms")
for r in d.get("recursos") or []: print("     ", r)'

echo
dice "Mensaje inválido: debe rechazarse con TRES motivos y quedar registrado"
curl -s -X POST --data-binary @ejemplos/03_adt_a01_invalido.hl7 "$HSB/hsb/hl7" | json '
print("  ", d["resultado"].upper())
for m in d.get("motivos") or []: print("     -", m)'

echo
dice "CSV legado de la sede 3 (Corozal): 3 filas válidas y 2 rechazadas"
curl -s -X POST --data-binary @ejemplos/04_sede3_legado.csv "$HSB/hsb/csv?sede=3" | json '
print("   resumen:", d["resumen"])
for r in d["resultados"]:
    motivo = "; ".join(r.get("motivos") or [])
    print("     fila %s doc %5s -> %s%s" % (
        r["fila"], r.get("documento", "?"), r["resultado"],
        ("  (" + motivo + ")") if motivo else ""))'
pausa

paso "Paso 2b · Normalizar el resto del legado: la cobertura sube al 100 %"
TOK_AUD=$(token_de auditor1 "${PWD_AUDITOR:-auditor123}")
for s in 1 2 3; do
    printf "   sede %s: " "$s"
    curl -s -X POST -H "Authorization: Bearer $TOK_AUD" "$API/api/v1/bus/migrar?sede=$s" \
      | json 'print(d.get("resumen"))'
done
curl -s "$API/api/v1/datos/cobertura" | json '
for c in d["por_sede"]:
    print("   sede %s %-11s %s/%s = %s %%" % (
        c["sede_id"], c["nombre"], c["migrados"], c["total"], c["cobertura_pct"]))
print("   GLOBAL: %s %%" % d["global"]["cobertura_pct"])'
pausa

# ── Paso 3 · idempotencia ───────────────────────────────────────────────────
paso "Paso 3 · Reenviar el mismo mensaje: no se duplica"
dice "La clave MSH-10 tiene un UNIQUE en la base (no en memoria) y el Bundle"
dice "usa PUT sobre identificadores deterministas. Dos capas independientes."
curl -s -X POST --data-binary @ejemplos/01_adt_a01_valido_sede2.hl7 "$HSB/hsb/hl7" | json '
print("  ", d["resultado"].upper(), "- estado del original:", d.get("estado"))'
printf "   Patient 1007 en HAPI: "
curl -s "$HAPI/Patient?identifier=1007" | json 'print(d.get("total"))'
printf "   Filas de 1007 en la sede 2: "
docker exec pg_nodo2 psql -U "${PG_USER:-admin}" -d "${PG_DB_SEDE:-historia_clinica}" -qtAX \
    -c "SELECT count(*) FROM usuario WHERE documento_id=1007;"
pausa

# ── Paso 4 · caída y recuperación de una sede ───────────────────────────────
paso "Paso 4 · Cae la sede 2: la vista degrada y después se recupera"
corre "docker compose stop pg_nodo2 >/dev/null 2>&1"
sleep 2
TOK_MED=$(token_de medico1 "${PWD_MEDICO:-medico123}")

dice "Consulta unificada del paciente 1001 (tiene atenciones en las 3 sedes)"
curl -s -H "Authorization: Bearer $TOK_MED" "$API/api/v1/historia/1001" | json '
print("   responde:", d["encontrado"], "| parcial:", d["parcial"])
print("   sedes disponibles:", d["sedes_disponibles"])
for s in d["sedes_no_disponibles"]: print("   NO DISPONIBLE:", s["nombre"])
print("   atenciones visibles:", d["resumen"]["atenciones"], "(de 3)")'

dice "El reporte NO puede presentarse como completo:"
curl -s -H "Authorization: Bearer $TOK_MED" "$API/api/v1/reporte/1001" | json '
print("   completo:", d["completo"])
print("   aviso:", d["aviso"])'

dice "Y el bus acepta un mensaje dirigido a la sede caída: lo deja pendiente"
curl -s -X POST --data-binary @ejemplos/07_adt_a01_sede2_caida.hl7 "$HSB/hsb/hl7" | json '
print("  ", d["resultado"].upper(), "-", (d.get("error") or "")[:70])'

echo
corre "docker compose start pg_nodo2 >/dev/null 2>&1"
dice "Esperando a que el trabajador de la cola lo entregue solo…"
for i in $(seq 1 12); do
    sleep 5
    estado=$(docker exec pg_central psql -U "${PG_USER:-admin}" -d "${PG_CENTRAL_DB:-hsb}" -qtAX \
             -c "SELECT estado FROM mensaje_bus WHERE clave_idempotencia='MSG-0007';" 2>/dev/null | tr -d ' ')
    echo "     [$i] $estado"
    [[ "$estado" == "entregado" ]] && { ok "Entregado sin que nadie lo reenviara"; break; }
done
pausa

# ── Paso 5 · auditoría ──────────────────────────────────────────────────────
paso "Paso 5 · Alterar un evento de auditoría y detectarlo"
dice "hash = SHA-256(hash_anterior + contenido). Primero, la cadena intacta:"
docker compose exec -T app python scripts/verificar_auditoria.py | sed 's/^/   /'
echo
dice "Ahora alguien con acceso a la base cambia una fila a mano:"
./scripts/alterar_auditoria_demo.sh 2>/dev/null | sed 's/^/   /'
echo
dice "El verificador la señala:"
docker compose exec -T app python scripts/verificar_auditoria.py | sed 's/^/   /'
pausa

# ── Paso 6 · permisos ───────────────────────────────────────────────────────
paso "Paso 6 · Acceso permitido y acceso denegado"
TOK_PAC=$(token_de paciente1007 "${PWD_PACIENTE:-paciente123}")

probar() {
    local etiqueta=$1 metodo=$2 ruta=$3 tok=$4 esperado=$5
    local code
    code=$(curl -s -o /dev/null -w "%{http_code}" -X "$metodo" -H "Authorization: Bearer $tok" "$API$ruta")
    if [[ "$code" == "$esperado" ]]; then
        printf "   ${ve}%-3s${n} %s\n" "$code" "$etiqueta"
    else
        printf "   ${ro}%-3s${n} %s (se esperaba %s)\n" "$code" "$etiqueta" "$esperado"
    fi
}
probar "paciente ve SU historia"                     GET  /api/v1/paciente/mi-historia "$TOK_PAC" 200
probar "paciente intenta ver la historia de OTRO"    GET  /api/v1/historia/1001        "$TOK_PAC" 403
probar "paciente intenta escribir un diagnóstico"    POST /api/v1/medico/diagnostico   "$TOK_PAC" 403
probar "médico ve la historia unificada"             GET  /api/v1/historia/1001        "$TOK_MED" 200
probar "médico intenta abrir una atención"           POST /api/v1/medico/atencion      "$TOK_MED" 403
probar "médico intenta apagar un nodo"               POST /api/v1/plataforma/nodos/2/stop "$TOK_MED" 403
probar "auditor lee la auditoría"                    GET  "/api/v1/auditoria?limite=5" "$TOK_AUD" 200
probar "sin token"                                   GET  /api/v1/historia/1001        ""         401
dice "Cada denegación dejó su evento en la cadena de auditoría."
pausa

# ── Paso 7 · consulta unificada y reporte ───────────────────────────────────
paso "Paso 7 · Consulta unificada del paciente 1001 y su Reporte de HC"
curl -s -H "Authorization: Bearer $TOK_AUD" "$API/api/v1/reporte/1001" | json '
print("   completo:", d["completo"])
print("   sedes:", ", ".join(
    "%s(%s at.)" % (s["nombre"], s["totales"]["atenciones"])
    for s in d["sedes"] if s["disponible"]))
c = d["cobertura_campos"]
print("   cobertura de campos: %s/%s = %s %%" % (
    c["campos_presentes"], c["campos_totales"], c["cobertura_pct"]))
print("   campos faltantes:", ", ".join(x["campo"] for x in c["faltantes"][:4]) or "ninguno")
print("   sello de integridad:", d["sello_integridad"][:48], "…")
print("   Bundle FHIR:", d["bundle_fhir"]["type"], "con", len(d["bundle_fhir"]["entry"]), "recursos")'

dice "Y el Bundle pasa el validador de HAPI:"
curl -s -H "Authorization: Bearer $TOK_AUD" "$API/api/v1/reporte/1001/bundle/validar" | json '
print("   válido:", d["valido"], "| errores:", d["errores"] or "ninguno")'
pausa

# ── Métricas finales ────────────────────────────────────────────────────────
paso "Resultados medidos en esta corrida"
curl -s "$HSB/metrics.json" | json '
print("   mensajes por estado:", d.get("mensajes_por_estado"))
print("   total:", d.get("total_mensajes"), "| latencia media:", d.get("latencia_media_ms"), "ms | p95:", d.get("latencia_p95_ms"), "ms")
print("   fallidos:", d.get("porcentaje_fallidos"), "% | duplicados frenados:", d.get("duplicados_detectados"))
print("   en cola:", d.get("en_cola"), "| muertos:", d.get("muertos"))'

echo
echo "${ve}Demostración terminada.${n}"
echo "   Vistas:  $API/login"
echo "            paciente1007 / admision2 / medico1 / auditor1"
echo "   Guion:   docs/05_guion_demo.md"
