# Decisiones de arquitectura

Entregable de la Fase 1, paso 6. El error frecuente que señala la guía es
«diseñar microservicios por moda»: por eso cada componente de esta tabla
responde a un requisito concreto y dice frente a qué alternativa se eligió.

## Cada componente frente a su requisito

| Componente | Requisito | Por qué este y no la alternativa |
| --- | --- | --- |
| **HSB propio** (FastAPI + cola en PostgreSQL) | RF1, RF3 | Las alternativas eran Mirth Connect y Apache Camel. Mirth trae conectores HL7 listos, pero su configuración vive en una base propia y en una interfaz gráfica: no se versiona bien en Git ni se explica línea por línea en una sustentación. Camel es muy potente pero añade la JVM y un lenguaje de rutas nuevo al costo de aprendizaje. Con FastAPI el bus son ~900 líneas de Python legibles, se prueba con pytest, se versiona entero y usa la misma imagen que la API. El costo asumido: hay que escribir a mano el lector HL7 v2 y la política de reintentos, que es justamente lo que el parcial evalúa. |
| **Cola en la tabla `mensaje_bus`** (no RabbitMQ ni Redis) | RF3 | Un intermediario de mensajes añadiría un contenedor más y un punto de fallo, y la guía advierte contra la «idempotencia solo en memoria». Con la cola en PostgreSQL, la clave de idempotencia es una restricción `UNIQUE` que sobrevive al reinicio, los reintentos se reclaman con `FOR UPDATE SKIP LOCKED` (lo que permite varias réplicas del bus) y el estado del mensaje se consulta con SQL desde el tablero. Para el volumen del parcial sobra; se documenta el punto de ruptura en la sección de escalabilidad. |
| **HAPI FHIR** (servidor de referencia) | RF2 | Es el servidor FHIR R4 de referencia de la comunidad HL7 y trae el validador `$validate`, que es lo que la guía pide usar como juez del Bundle. Implementar un almacén FHIR propio habría sido reinventar el estándar. |
| **Recursos FHIR como JSON, sin la librería `fhir.resources`** | RF2 | La librería ata el proyecto a una versión concreta de Pydantic y, además, su paquete se llama `fhir`, que choca con la carpeta `fhir/` que exige la estructura del parcial. Se generan los recursos como diccionarios y se validan contra HAPI: el juez es el servidor, no la librería. |
| **Un nodo PostgreSQL por sede** | RF4 | Las tres opciones de la guía eran: un nodo por sede, fragmentación por rango de documento (como el repositorio de referencia) o Citus. Se eligió **un nodo por sede** porque es la que coincide con el escenario: cada sede conserva su sistema legado con base propia y la plataforma no lo reemplaza. La clave de acceso sigue siendo el documento del paciente, que es por lo que consultan todas las vistas. La fragmentación por rango de documento se conserva como regla de respaldo (`comun/sedes.py: nodo_por_documento`) para las escrituras que no declaran sede, de modo que el comportamiento del laboratorio original sigue disponible. Citus se descartó porque el escenario no pide consultar las tres sedes como una sola base: pide respetar que son tres sistemas distintos y que uno puede caerse. |
| **Almacén central aparte (`pg_central`)** | RF3, RF5, RNF | La cola del bus, la auditoría y las terminologías no pueden vivir en una sede: si esa sede cae, se quedaría sin bus y sin auditoría toda la red. En un nodo aparte, apagar una sede degrada la vista pero no detiene el bus. La base de HAPI vive en el mismo nodo central por la misma razón. |
| **JWT firmado (HS256) en lugar de Keycloak** | RF5 | La guía admite «Keycloak o, como mínimo, un token JWT firmado». Keycloak añade un contenedor que tarda más de un minuto en arrancar, un realm que importar y un punto de fallo en la demostración, a cambio de funcionalidad (federación, consentimiento, MFA) que el parcial no evalúa. Lo que se califica —roles con permisos distintos, verificados en la API— se cumple con el JWT propio. En [infra/keycloak/](../infra/keycloak/) queda el realm y un `override` de compose para quien quiera demostrar OIDC completo. |
| **Auditoría encadenada por hash en PostgreSQL** | RF5 | `hash = SHA-256(hash_anterior + contenido canónico)`. Alterar, borrar o reordenar una fila rompe la cadena desde ese punto y el verificador señala el primer evento afectado. Anclar el hash en Hyperledger Fabric es el bonus: añadiría inmutabilidad frente a un administrador de la base, pero no cambia el mecanismo de detección. |
| **Consulta unificada en paralelo con `ThreadPoolExecutor`** | RF4, RNF | Las tres sedes se consultan a la vez: la respuesta tarda lo que la sede más lenta y no la suma de las tres, y una sede caída solo cuesta su `connect_timeout` (3 s). Es lo que hace que la degradación se note poco. |
| **Las vistas hablan solo con la API** | RF6 | Regla de oro de la Fase 5. Las cuatro vistas usan `/api/v1/...`; ninguna abre una conexión a las bases de las sedes. Esto permite que los permisos se verifiquen en un solo lugar. |
| **Imagen Docker única para API y bus** | RNF | Los dos servicios comparten `comun/` y `fhir/`. Una sola imagen con dos comandos distintos evita duplicar dependencias y reduce a la mitad el tiempo de construcción. |

## Qué se sacrifica según CAP

El escenario tiene una partición garantizada (tres sedes que pueden quedar
incomunicadas), así que la elección real es entre consistencia y
disponibilidad. **Se elige disponibilidad (AP).**

* **Qué se gana.** Si la sede 2 cae, la consulta unificada sigue respondiendo
  con las sedes 1 y 3. El médico ve la historia que hay, con un aviso
  explícito de que está incompleta.
* **Qué se sacrifica.** Durante la caída, la vista no es consistente con el
  estado real: faltan las atenciones de la sede caída. Por eso el Reporte de
  HC nunca se presenta como completo cuando falta una sede (`completo: false`
  y un aviso visible), que es el error frecuente que advierte la guía.
* **Cómo se recupera la consistencia.** Es eventual. Los mensajes dirigidos a
  la sede caída quedan en estado `reintentando` y el trabajador del bus los
  entrega cuando la sede vuelve. Si se agotan los cuatro intentos, el mensaje
  pasa a la cola de muertos y se reencola a mano: no se pierde.
* **Dónde sí hay consistencia fuerte.** Dentro de una sede. La escritura de
  `usuario`, `atencion`, `diagnostico` y `observacion` ocurre en una sola
  transacción ACID de PostgreSQL: se confirma entera o no se confirma nada
  (demostrado en `POST /api/v1/datos/prueba-acid`).

### La pregunta de la sustentación

> Si la sede 2 cae a mitad de una transacción distribuida, ¿qué garantiza su
> diseño y qué sacrifica según CAP?

No hay una transacción distribuida de dos fases entre sedes, y es una
decisión, no un olvido: un *two-phase commit* entre tres sedes
independientes habría convertido la caída de una sede en el bloqueo de las
otras dos, que es exactamente lo contrario de lo que pide el requisito no
funcional. Lo que hay es una transacción local por sede más un bus que
reintenta. Se garantiza: (a) atomicidad dentro de la sede, (b) que ningún
mensaje se pierde, y (c) que reentregarlo no duplica, porque la clave de
idempotencia y los `PUT` sobre identificadores deterministas hacen la
operación repetible. Se sacrifica la consistencia inmediata entre sedes.

### La otra pregunta: ¿y si el nodo cae después del COMMIT pero antes de responder?

El bus no recibe la confirmación y marca el mensaje como `reintentando`. En
el siguiente intento vuelve a ejecutar la misma escritura, pero todas las
sentencias son `ON CONFLICT ... DO UPDATE` sobre claves deterministas
(`documento_id`, `visita`, `(atencion_id, cie10)`, `(atencion_id, loinc)`):
la segunda ejecución actualiza las mismas filas en lugar de crear otras. Por
eso la reentrega es segura aunque la primera sí se hubiera confirmado.

## La asimetría HL7 / CSV en el diagnóstico

Es la decisión más discutible del proyecto y conviene poder defenderla.

**Regla:** en HL7 v2 el diagnóstico de `DG1-3` debe venir ya codificado en
CIE-10; en el CSV legado se admite texto libre y se traduce con
`ref_terminologia`.

**Por qué.** El contrato de [ejemplos/LEEME.md](../ejemplos/LEEME.md) exige
que `03_adt_a01_invalido.hl7` se rechace con tres motivos, y uno de ellos es
«diagnóstico sin mapeo a CIE-10» para el valor `DIARREA`, que sí está en la
tabla de referencia. La única lectura coherente con el contrato es que, en
HL7, el texto libre no se acepta: una sede que habla HL7 v2 habla el estándar
completo y envía el código. El CSV, en cambio, es explícitamente «legado»: es
el formato para el que existe la tabla de mapeo.

**Cómo se puede cambiar.** La regla está en una variable de entorno:
`HSB_HL7_EXIGE_CIE10=false` hace que el bus también traduzca texto libre en
HL7. Con ese valor el archivo 03 se rechazaría solo con dos motivos y dejaría
de cumplir el contrato, así que el valor por defecto es `true`.

## Concesiones conocidas (y cómo se arreglarían)

| Concesión | Riesgo | Cómo se resolvería fuera del parcial |
| --- | --- | --- |
| El contenedor de la API monta el socket de Docker para que el auditor pueda apagar un nodo desde el tablero | Quien controle la API controla el demonio de Docker del anfitrión | Un agente aparte con permisos mínimos, o simplemente `docker compose stop pg_nodo2` desde el host (el tablero muestra el comando si no hay socket) |
| El token JWT se guarda en `localStorage` | Un XSS podría leerlo | Cookie `HttpOnly` con `SameSite=Strict` y CSRF por token de formulario |
| Los usuarios de prueba están en el código, con claves por variable de entorno | No sirve para producción | Keycloak o una tabla de usuarios con `argon2` |
| Emparejamiento de pacientes por documento exacto | Un documento mal digitado crea un paciente nuevo | MDM probabilístico (Fellegi-Sunter), que la plantilla marca como bonus |
| Sin cifrado TLS entre contenedores | Tráfico en claro dentro de la red de Docker | TLS terminado en un proxy, o malla de servicios |
