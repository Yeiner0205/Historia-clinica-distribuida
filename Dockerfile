# ============================================================================
# Imagen única para los dos servicios de Python de la plataforma:
#   * la API y las cuatro vistas  (app.main:app,  puerto 8001)
#   * el bus de integración HSB   (hsb.main:app,  puerto 8000)
#
# El comando lo elige docker-compose.yml, de modo que ambos servicios comparten
# dependencias y código común (comun/, fhir/) sin duplicar la imagen.
# ============================================================================
FROM python:3.11-slim

WORKDIR /app

# psycopg2-binary trae sus ruedas, pero psql sirve para diagnosticar desde el
# contenedor (`docker compose exec app psql ...`).
RUN apt-get update && apt-get install -y --no-install-recommends \
        postgresql-client curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Dentro de la red de Docker se usan los nombres de los contenedores.
ENV USE_DOCKER_NAMES=true \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000 8001

# Por defecto arranca la API; el HSB sobreescribe el comando en el compose.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
