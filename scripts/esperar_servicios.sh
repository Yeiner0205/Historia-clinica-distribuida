#!/usr/bin/env bash
# ============================================================================
# Espera a que la plataforma esté lista. Útil tras `docker compose up` y antes
# de la demostración: HAPI FHIR tarda alrededor de un minuto en arrancar.
#
#   ./scripts/esperar_servicios.sh [segundos_max]
# ============================================================================
set -u
MAX=${1:-180}
API=${API:-http://localhost:8001}
HSB=${HSB:-http://localhost:8000}
HAPI=${HAPI:-http://localhost:8080/fhir}

esperar() {
    local nombre=$1 url=$2 inicio
    inicio=$(date +%s)
    printf '  %-22s' "$nombre"
    while :; do
        if curl -sf -m 5 "$url" > /dev/null 2>&1; then
            printf 'listo (%ss)\n' "$(( $(date +%s) - inicio ))"
            return 0
        fi
        if (( $(date +%s) - inicio > MAX )); then
            printf 'NO RESPONDE tras %ss\n' "$MAX"
            return 1
        fi
        sleep 3
    done
}

echo "Esperando a que la plataforma esté lista (máximo ${MAX}s por servicio)…"
fallos=0
esperar "API y vistas"     "$API/health"        || fallos=$((fallos+1))
esperar "Bus HSB"          "$HSB/health"        || fallos=$((fallos+1))
esperar "HAPI FHIR"        "$HAPI/metadata"     || fallos=$((fallos+1))

if (( fallos > 0 )); then
    echo
    echo "Hay $fallos servicio(s) sin responder. Revise:  docker compose ps  y  docker compose logs"
    exit 1
fi

version=$(curl -s -m 5 "$HAPI/metadata" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("fhirVersion","?"))' 2>/dev/null)
echo
echo "Todo listo. FHIR $version"
echo "  Inicio de sesión:  $API/login"
echo "  Inicio:            $API/home"
echo "  Bus:               $HSB/"
