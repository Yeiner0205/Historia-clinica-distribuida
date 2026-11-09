# Documentación del parcial final

Plataforma distribuida de interoperabilidad clínica — red de IPS con tres sedes
(Sincelejo, Cartagena y Corozal).

## Qué hay en esta carpeta

| Archivo | Qué contiene | Fase |
| --- | --- | --- |
| [01_informe.md](01_informe.md) | Informe completo con la estructura de la plantilla v7 | 1 a 5 |
| [02_mapeo_campos.md](02_mapeo_campos.md) | Tabla de mapeo origen → tabla → recurso FHIR (26 campos) | 1 |
| [03_decisiones_arquitectura.md](03_decisiones_arquitectura.md) | Cada componente frente al requisito que cubre y a sus alternativas | 1 |
| [04_matriz_requisitos.md](04_matriz_requisitos.md) | RF1 a RF6 y los RNF con su evidencia verificable | 5 |
| [05_guion_demo.md](05_guion_demo.md) | Guion de la sustentación de 15 minutos, comando por comando | 5 |
| [06_bitacora.md](06_bitacora.md) | Contribución de cada integrante y uso declarado de IA | 1 a 5 |
| [07_resultados_medidos.md](07_resultados_medidos.md) | Latencia, mensajes por minuto, fallidos y cobertura medidos | 5 |
| [uml/](uml/) | Los 4 diagramas UML y el de arquitectura, en imagen y fuente editable | 1 |
| [anexos/](anexos/) | Documentación heredada del repositorio de referencia | — |
| [articulo/](articulo/) | Borrador en LaTeX y figuras del artículo IEEE previo | — |

## Los diagramas

Cada diagrama está en dos formatos:

* **Imagen** (`.svg`): la que va en el informe. Se genera con
  `python3 docs/uml/generar_diagramas.py`, que solo necesita Python.
* **Fuente editable** (`.puml`): PlantUML, para editar en VS Code, IntelliJ o
  en el servidor público de PlantUML.

| Diagrama | Imagen | Fuente |
| --- | --- | --- |
| Casos de uso (5 actores, 12 casos) | [01_casos_de_uso.svg](uml/01_casos_de_uso.svg) | [.puml](uml/01_casos_de_uso.puml) |
| Secuencia (HL7 v2 → FHIR, con camino de error) | [02_secuencia.svg](uml/02_secuencia.svg) | [.puml](uml/02_secuencia.puml) |
| Clases (13 entidades) | [03_clases.svg](uml/03_clases.svg) | [.puml](uml/03_clases.puml) |
| Estados del mensaje en el bus (7 estados) | [04_estados.svg](uml/04_estados.svg) | [.puml](uml/04_estados.puml) |
| Arquitectura | [05_arquitectura.svg](uml/05_arquitectura.svg) | [.puml](uml/05_arquitectura.puml) |

## Coherencia entre los diagramas

El criterio para pasar la Fase 1 es que los cuatro diagramas sean coherentes
entre sí. Se puede comprobar así:

* El actor **Sistema de sede** del diagrama de casos de uso es el primer
  participante del diagrama de secuencia y el origen de los mensajes en el de
  arquitectura.
* El caso de uso **Enviar mensaje al bus** se desarrolla paso a paso en el
  diagrama de secuencia y sus estados intermedios son exactamente los siete
  del diagrama de estados.
* Cada entidad que toca la secuencia (`usuario`, `atencion`, `diagnostico`,
  `observacion`, `mensaje_bus`, `evento_auditoria`) existe como clase en el
  diagrama de clases, con los mismos nombres de columna que el esquema de
  [db/sede/01_esquema.sql](../db/sede/01_esquema.sql) y
  [db/central/01_esquema.sql](../db/central/01_esquema.sql).
* Los estados del diagrama de estados son los valores admitidos por la
  restricción `ck_mensaje_estado` de la tabla `mensaje_bus`.
