# infra/ — Despliegue y complementos opcionales

El despliegue del parcial es el `docker-compose.yml` de la raíz: un solo
comando levanta los siete contenedores. Lo que hay en esta carpeta son
**complementos opcionales**, que corresponden al bonus del enunciado.

| Carpeta | Qué es | Estado |
| --- | --- | --- |
| [keycloak/](keycloak/) | Realm y override de compose para sustituir el JWT propio por OAuth2/OIDC | Plantilla **sin probar** |
| [observabilidad/](observabilidad/) | Prometheus y Grafana sobre los `/metrics` que ya existen | Plantilla **sin probar** |
| [k8s/](k8s/) | Manifiestos de Kubernetes (Deployment, Service y probes) | Plantilla **sin probar** |

> **Aviso honesto.** Las tres son plantillas escritas a partir de la
> configuración real del proyecto, pero **no se ejecutaron**. El bonus del
> enunciado exige que estén *probadas* (por ejemplo, «Kubernetes probado en
> Minikube»): si el equipo quiere reclamarlo, tiene que levantarlas,
> comprobar que funcionan y dejar la evidencia. Presentarlas como hechas sin
> haberlas corrido sería justo lo que la guía castiga como «texto copiado de
> la plantilla sin evidencia».

Lo que **sí** está implementado y probado del lado de observabilidad es el
origen de los datos: `/health` y `/metrics` en la API y en el bus, en formato
de texto de Prometheus. Prometheus y Grafana solo serían la capa de
visualización encima.
