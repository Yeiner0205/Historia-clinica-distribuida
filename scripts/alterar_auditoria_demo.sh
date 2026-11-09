#!/usr/bin/env bash
# ============================================================================
# Altera a mano una fila de la auditoría para demostrar que el verificador la
# detecta (prueba obligatoria de la Fase 4, Paso 2).
#
#   ./scripts/alterar_auditoria_demo.sh            # altera el evento del medio
#   ./scripts/alterar_auditoria_demo.sh 5          # altera el evento 5
#   ./scripts/alterar_auditoria_demo.sh 5 --borrar # lo borra en lugar de alterarlo
#
# Es una herramienta de demostración: simula a alguien con acceso a la base
# que intenta reescribir la historia.
# ============================================================================
set -euo pipefail

CONTENEDOR=${CONTENEDOR:-pg_central}
USUARIO=${PG_USER:-admin}
BASE=${PG_CENTRAL_DB:-hsb}
psql_central() { docker exec -i "$CONTENEDOR" psql -U "$USUARIO" -d "$BASE" -qtAX -c "$1"; }

objetivo=${1:-}
modo=${2:-alterar}

if [[ -z "$objetivo" ]]; then
    objetivo=$(psql_central "SELECT evento_id FROM evento_auditoria ORDER BY evento_id OFFSET (SELECT GREATEST(COUNT(*)/2,0) FROM evento_auditoria) LIMIT 1;")
fi

if [[ -z "$objetivo" ]]; then
    echo "No hay eventos de auditoría todavía. Inicie sesión o envíe un mensaje al bus primero."
    exit 1
fi

echo "Evento elegido: #$objetivo"
echo "Antes:"
psql_central "SELECT evento_id || ' | ' || actor || ' | ' || accion || ' | ' || resultado FROM evento_auditoria WHERE evento_id = $objetivo;"

if [[ "$modo" == "--borrar" ]]; then
    echo "Borrando la fila…"
    psql_central "DELETE FROM evento_auditoria WHERE evento_id = $objetivo;" > /dev/null
    echo "Fila borrada: el eslabón siguiente queda sin su anterior."
else
    echo "Cambiando el resultado a 'ok' y el actor a 'intruso'…"
    psql_central "UPDATE evento_auditoria SET resultado = 'ok', actor = 'intruso' WHERE evento_id = $objetivo;" > /dev/null
    echo "Después:"
    psql_central "SELECT evento_id || ' | ' || actor || ' | ' || accion || ' | ' || resultado FROM evento_auditoria WHERE evento_id = $objetivo;"
fi

echo
echo "Ahora ejecute el verificador:"
echo "    curl -s -H \"Authorization: Bearer \$TOKEN\" http://localhost:8001/api/v1/auditoria/verificar"
echo "  o bien:"
echo "    docker compose exec app python scripts/verificar_auditoria.py"
