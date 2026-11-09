# Guion de la demostración (15 minutos)

Es el guion del enunciado, paso por paso, con el comando exacto y lo que debe
verse. Hay un script que lo ejecuta entero y va narrando:

```bash
./scripts/demo.sh
```

Conviene haberlo corrido al menos una vez antes de la sustentación, porque la
primera vez Docker descarga las imágenes.

---

## Antes de empezar

Dos terminales y un navegador:

* **Terminal 1** — los comandos de la demostración.
* **Terminal 2** — los registros del bus: `docker compose logs -f hsb`.
* **Navegador** — http://localhost:8001/login

---

## Paso 0 · Arranque desde cero (2 min)

```bash
docker compose down -v && docker compose up -d
./scripts/esperar_servicios.sh
```

**Qué decir mientras arranca:** que son siete contenedores —tres nodos
PostgreSQL (uno por sede), el almacén central con la cola y la auditoría, el
servidor HAPI FHIR, el bus y la API— y que los nodos cargan su esquema y sus
datos sintéticos solos, sin paso manual.

**Qué debe verse:** los tres servicios en «listo» y `FHIR 4.0.1`.

---

## Paso 1 · Cobertura FHIR en 0 % (1 min)

Entrar como **auditor1 / auditor123** en http://localhost:8001/login y abrir
la pestaña **Estado de la plataforma** del Reporte de HC.

```bash
curl -s http://localhost:8001/api/v1/datos/cobertura | python3 -m json.tool
```

**Qué debe verse:** las tres sedes disponibles y cobertura **0 %** en todas.
Los pacientes existen en el legado, pero ninguno tiene `fhir_patient_id`.

---

## Paso 2 · Un mensaje HL7 v2 y uno CSV (3 min)

```bash
# ADT^A01 de la sede 2: admisión de Andrea Rojas (documento 1007)
curl -X POST --data-binary @ejemplos/01_adt_a01_valido_sede2.hl7 \
     http://localhost:8000/hsb/hl7 | python3 -m json.tool

# ORU^R01 de la sede 1: hemoglobina del paciente 1001
curl -X POST --data-binary @ejemplos/02_oru_r01_laboratorio_sede1.hl7 \
     http://localhost:8000/hsb/hl7 | python3 -m json.tool

# CSV legado de la sede 3: cinco filas
curl -X POST --data-binary @ejemplos/04_sede3_legado.csv \
     "http://localhost:8000/hsb/csv?sede=3" | python3 -m json.tool
```

**Qué debe verse:**

* El ADT: `"resultado": "entregado"` con `Patient/pac-1007`,
  `Encounter/enc-V-S2-0101` y `Condition/cond-V-S2-0101-J459`.
* El ORU: `Observation/obs-V-S1-0150-7187` (hemoglobina 13,8 g/dL del
  paciente 1001).
* El CSV: `{"entregado": 3, "rechazado": 2}`.

**Qué decir:** el CSV rechaza dos filas y dice por qué —`DOLOR MISTERIOSO`
no tiene mapeo a CIE-10 y el documento `12` tiene dos dígitos—. Un mensaje
inválido no se pierde: queda en la cola con su motivo. Enseñarlo:

```bash
curl -s "http://localhost:8000/hsb/mensajes?estado=rechazado" | python3 -m json.tool
```

Y el mensaje inválido de HL7, que debe dar exactamente tres motivos:

```bash
curl -X POST --data-binary @ejemplos/03_adt_a01_invalido.hl7 \
     http://localhost:8000/hsb/hl7 | python3 -m json.tool
```

**Volver al tablero:** la cobertura ya no es 0 %. Pulsar **Normalizar sede 1,
2 y 3** y mostrar que sube al **100 %**.

---

## Paso 3 · Reenviar el mismo mensaje: no se duplica (1 min)

```bash
curl -X POST --data-binary @ejemplos/01_adt_a01_valido_sede2.hl7 \
     http://localhost:8000/hsb/hl7 | python3 -m json.tool

curl -s "http://localhost:8080/fhir/Patient?identifier=1007" \
  | python3 -c 'import json,sys; print("Patient 1007 en HAPI:", json.load(sys.stdin)["total"])'

docker exec pg_nodo2 psql -U admin -d historia_clinica \
  -c "SELECT documento_id, nombre_completo FROM usuario WHERE documento_id=1007;"
```

**Qué debe verse:** `"resultado": "duplicado"`, un solo Patient en HAPI y una
sola fila en la sede.

**Qué decir:** la idempotencia está en dos capas independientes. La clave
`MSH-10` tiene una restricción `UNIQUE` en la tabla `mensaje_bus`, así que el
mensaje repetido ni siquiera vuelve a entrar; y aunque entrara, el Bundle usa
`PUT` sobre identificadores deterministas (`pac-1007`), de modo que
actualizaría en lugar de crear. La clave está en la base, no en memoria: el
bus se puede reiniciar y la garantía sigue en pie.

---

## Paso 4 · Caída de una sede: la vista degrada y se recupera (3 min)

```bash
docker compose stop pg_nodo2
```

En el navegador, **Reporte de HC** del paciente **1001** (tiene atenciones en
las tres sedes).

**Qué debe verse:** el aviso **«Reporte PARCIAL: la sede Cartagena no
respondió»**, las sedes 1 y 3 con sus atenciones y la 2 marcada en rojo como
no disponible.

```bash
curl -s http://localhost:8001/health \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["estado"], d["dependencias"]["sedes_disponibles"])'
#   → degradado 2/3
```

Con la sede todavía caída, enviar un mensaje dirigido a ella:

```bash
curl -X POST --data-binary @ejemplos/07_adt_a01_sede2_caida.hl7 \
     http://localhost:8000/hsb/hl7 | python3 -m json.tool
#   → "resultado": "reintentando"
```

Y levantarla:

```bash
docker compose start pg_nodo2
sleep 10
curl -s "http://localhost:8000/hsb/mensajes?limite=3" | python3 -m json.tool
```

**Qué debe verse:** el mensaje pasó solo a `entregado`. Nadie lo reenvió: lo
hizo el trabajador de la cola.

**Qué decir:** esta es la elección AP del teorema CAP. Se sacrifica
consistencia inmediata —durante la caída faltan las atenciones de Cartagena—
a cambio de que el médico pueda seguir trabajando. Y por eso el reporte
**nunca** se presenta como completo cuando falta una sede.

---

## Paso 5 · Alterar un evento de auditoría (2 min)

```bash
docker compose exec app python scripts/verificar_auditoria.py
#   → CADENA ÍNTEGRA

./scripts/alterar_auditoria_demo.sh

docker compose exec app python scripts/verificar_auditoria.py
#   → CADENA ALTERADA, con el número del primer evento afectado
```

También en el navegador: pestaña **Auditoría** → **Verificar la cadena**.

**Qué decir:** cada evento guarda `hash = SHA-256(hash_anterior + contenido)`.
Cambiar un carácter cambia el hash de ese evento, y como el siguiente guarda
el hash del anterior, la cadena se rompe desde ahí. Por eso el verificador
señala el **primero** afectado: todo lo posterior queda bajo sospecha.
También detecta el borrado de una fila, porque el eslabón siguiente ya no
encuentra su anterior:

```bash
./scripts/alterar_auditoria_demo.sh 5 --borrar
docker compose exec app python scripts/verificar_auditoria.py
```

---

## Paso 6 · Acceso permitido y acceso denegado (2 min)

En el navegador, salir y entrar como **paciente1007 / paciente123**: se ve su
historia unificada y quién la consultó.

Luego, en la terminal, intentar ver la historia de otro paciente:

```bash
TP=$(curl -s -X POST http://localhost:8001/auth/login -H 'Content-Type: application/json' \
      -d '{"usuario":"paciente1007","password":"paciente123"}' \
      | python3 -c 'import json,sys;print(json.load(sys.stdin)["access_token"])')

curl -s -H "Authorization: Bearer $TP" http://localhost:8001/api/v1/historia/1001 | python3 -m json.tool
#   → 403: "Como paciente solo puede consultar su propia historia clínica."
```

**Qué decir:** el rechazo ocurre en la API, no en la pantalla. Cambiar el
documento en la URL, borrar el token del navegador o llamar con `curl` da lo
mismo. Y el intento queda registrado: enseñarlo en la pestaña **Auditoría**
como un evento `acceso_denegado`.

Si el docente pide cambiar en vivo el rol permitido de una acción: está en
una sola tabla, [comun/seguridad.py](../comun/seguridad.py), diccionario
`PERMISOS`. Quitar `clinico:escribir` del rol `medico`, reiniciar con
`docker compose restart app` y mostrar que ahora el médico recibe 403.

---

## Paso 7 · Consulta unificada y Reporte de HC (1 min)

Con todas las sedes arriba, **Reporte de HC** del paciente **1001**:

* Tres sedes, cada una con su atención, su diagnóstico CIE-10 y su
  laboratorio LOINC.
* Cobertura de campos con la lista de los que faltan.
* Sello de integridad SHA-256 del contenido.
* **Descargar Bundle FHIR** y **Validar Bundle contra HAPI** →
  «El validador de HAPI acepta el Bundle sin errores».
* **Imprimir o guardar en PDF**.

---

## Preguntas típicas y por dónde responder

| Pregunta | Dónde está la respuesta |
| --- | --- |
| Si la sede 2 cae a mitad de una transacción distribuida, ¿qué garantiza su diseño y qué sacrifica según CAP? | [03_decisiones_arquitectura.md](03_decisiones_arquitectura.md), sección «Qué se sacrifica según CAP» |
| ¿Por qué reenviar un mensaje no crea un paciente duplicado? | Dos capas: `UNIQUE` en `mensaje_bus.clave_idempotencia` y `PUT` sobre ids deterministas en `fhir/normalizador.py` |
| ¿Cómo sabe que la auditoría no fue alterada? | `comun/auditoria.py: verificar_cadena()` recalcula cada hash desde el génesis |
| Cambie en vivo el rol permitido de una acción | `comun/seguridad.py`, diccionario `PERMISOS` |
| ¿Qué escalaría primero con 100 veces más mensajes? | El bus (`docker compose up --scale hsb=4`); está explicado en la sección 10.1 del informe |
| ¿Y si el nodo cae después del COMMIT pero antes de responder? | El mensaje se reintenta y todas las escrituras son `ON CONFLICT DO UPDATE`: la reentrega actualiza, no duplica |
| ¿Por qué el archivo 03 se rechaza si `DIARREA` sí está en la tabla? | Decisión documentada: en HL7 el diagnóstico debe venir en CIE-10; el texto libre solo se admite en el CSV legado |

---

## Capturas que hay que tomar para el informe

Con el sistema levantado, para la sección «Diseño de interfaces»:

1. `/login` — pantalla de inicio de sesión con los usuarios de prueba.
2. `/paciente` — historia unificada y pestaña «Quién vio mi historia».
3. `/admision` — búsqueda que muestra en qué sedes existe el paciente.
4. `/medico` — historia unificada con el aviso de las tres sedes.
5. `/reporte-hc` — reporte del paciente 1001 agrupado por sede.
6. `/reporte-hc` → **Estado de la plataforma** — el tablero completo.
7. El mismo reporte **con `pg_nodo2` apagado**, mostrando el aviso de parcial.
8. La pestaña **Auditoría** con el resultado «CADENA ALTERADA».
