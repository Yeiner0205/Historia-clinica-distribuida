# Mensajes añadidos por el equipo

Los cinco archivos numerados del 01 al 05 son el **contrato** entregado con el
parcial y no se modifican. Estos dos se añadieron para poder repetir dos
pruebas que el contrato pide hacer pero que necesitan un mensaje nuevo cada
vez (si se reenvía uno ya entregado, el bus responde `duplicado`, que es
justamente lo correcto).

| Archivo | Para qué | Prueba del LEEME original |
| --- | --- | --- |
| `06_oru_r01_reintento_sede1.hl7` | Enviar con HAPI apagado: el mensaje pasa a `reintentando` y, si se deja apagado, acaba en la cola de muertos | Pruebas 2 y 3 |
| `07_adt_a01_sede2_caida.hl7` | Enviar con `pg_nodo2` apagado: el mensaje espera a que la sede vuelva | Paso 4 de la demostración |

Ambos son datos sintéticos, como el resto.

## Cómo usarlos

```bash
# Reintento por caída de HAPI
docker compose stop hapi-fhir
curl -X POST --data-binary @ejemplos/06_oru_r01_reintento_sede1.hl7 http://localhost:8000/hsb/hl7
#   → "resultado": "reintentando"
docker compose start hapi-fhir
#   el trabajador de la cola lo entrega solo

# Cola de mensajes muertos: dejar HAPI apagado más de 4 intentos (~15 s)
docker compose stop hapi-fhir
curl -X POST --data-binary @ejemplos/06_oru_r01_reintento_sede1.hl7 http://localhost:8000/hsb/hl7
sleep 20
curl -s http://localhost:8000/hsb/muertos | python3 -m json.tool
docker compose start hapi-fhir
# y reencolarlo (hace falta token de auditor o admisionista):
curl -X POST -H "Authorization: Bearer $TOKEN" \
     http://localhost:8001/api/v1/bus/mensajes/<id>/reencolar

# Caída de una sede
docker compose stop pg_nodo2
curl -X POST --data-binary @ejemplos/07_adt_a01_sede2_caida.hl7 http://localhost:8000/hsb/hl7
#   → "resultado": "reintentando"
docker compose start pg_nodo2
#   en menos de 10 s pasa a "entregado"
```

## Si hay que repetir una prueba con el mismo archivo

El bus responderá `duplicado`, que es el comportamiento correcto. Para volver
a empezar desde cero:

```bash
docker compose down -v && docker compose up -d
```
