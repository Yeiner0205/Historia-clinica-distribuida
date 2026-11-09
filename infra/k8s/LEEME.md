# Kubernetes — opcional (bonus)

El enunciado ofrece bonus por «manifiestos de Kubernetes (Deployment,
Service y probes de salud) **probados en Minikube**». Aquí están los
manifiestos; **falta probarlos**.

## Qué hay

| Archivo | Qué define |
| --- | --- |
| `00-namespace.yaml` | Espacio de nombres `historia-clinica` |
| `01-config.yaml` | ConfigMap con la configuración y Secret con el token y las claves |
| `02-sedes.yaml` | Un StatefulSet y un Service por sede, más el almacén central |
| `03-hapi.yaml` | Deployment y Service de HAPI FHIR |
| `04-hsb.yaml` | Deployment y Service del bus, con probes contra `/health` |
| `05-app.yaml` | Deployment, Service e Ingress de la API, con probes |

## Cómo probarlo (lo que falta)

```bash
minikube start --cpus 4 --memory 8192
eval $(minikube docker-env)
docker compose build                 # construir la imagen dentro de Minikube

kubectl apply -f infra/k8s/
kubectl -n historia-clinica get pods -w
kubectl -n historia-clinica port-forward svc/app 8001:8001
```

Para reclamar el bonus hay que dejar evidencia: `kubectl get pods` con todo
en `Running`, los probes en verde y la plataforma respondiendo.

## Dos diferencias frente al compose

1. **Los datos de cada sede usan `StatefulSet`**, no `Deployment`: cada nodo
   necesita su volumen estable y su identidad de red.
2. **Los secretos salen del YAML.** El `Secret` del ejemplo trae valores de
   demostración; en serio irían con `kubectl create secret` o un gestor
   externo, nunca versionados.
