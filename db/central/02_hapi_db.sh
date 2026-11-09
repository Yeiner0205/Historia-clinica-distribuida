#!/bin/bash
# Base de datos propia para el servidor HAPI FHIR.
# Vive en el nodo central (no en una sede) para que la caída de una sede no
# deje sin servidor FHIR a toda la plataforma.
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<-EOSQL
    SELECT 'CREATE DATABASE fhir_db'
     WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'fhir_db')\gexec
EOSQL
echo "fhir_db lista para HAPI FHIR"
