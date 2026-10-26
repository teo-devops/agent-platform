# 0007 · El despliegue GitOps vive aquí; genai-platform se archiva

**Estado:** aceptada

## Contexto

`genai-platform` nació como el "plano de plataforma" separado del "plano
agéntico": ArgoCD (app-of-apps) desplegando Argo Workflows, KServe, MinIO,
MLflow, ingress-nginx, cert-manager y Prometheus/Grafana. Recibía de este
repositorio el esquema (`contracts/schemas`) y una imagen por runtime
(`runtime-adapters.yaml`), y compilaba cada `kind: Workflow` a un Argo Workflow.

Desde entonces, este repositorio ha cubierto casi todo eso por su cuenta: kagent
sirve los agentes, los workflows se ejecutan en el propio runtime (y Langflow los
invoca por A2A, ADR 0005), y MLflow + SeaweedFS + el collector OTel viven en
`deploy/observability`. Al revisarlo, además, varias piezas de `genai-platform`
no funcionaban: los `values.yaml` de cada componente no llegaban a ArgoCD (cada
Application leía los del propio chart), el chart de MLflow apuntaba al
repositorio de MinIO, y la versión de ingress-nginx era la de la aplicación, no
la del chart.

Lo que sí faltaba aquí era el despliegue declarativo de un clúster que no sea el
laboratorio: la Fase 4.3 de la estrategia.

## Decisión

**Se trae** a `deploy/gitops/`, rehecho contra lo que ya existe:

- `bootstrap/`: el AppProject, con repositorios y namespaces explícitos (sin `*`); el repositorio OCI de los charts de kagent (`repositories.yaml`); y una app-of-apps por entorno (`root-prod.yaml`, `root-lab.yaml`).
- `apps/`: una Application por pieza, en el orden de `make platform`:
  1. Los namespaces de `deploy/base`.
  2. Las CRDs de kagent.
  3. `deploy/observability`.
  4. La monitorización (kube-prometheus-stack).
  5. kagent, con `deploy/kagent/values.yaml`.

  Los values se leen del repositorio con una segunda fuente (`$values`), que es lo que no funcionaba en `genai-platform`.
- `overlays/prod`:
  - MLflow desde GHCR. El CI ahora la publica y la firma con las demás imágenes, en cada etiqueta `v*`.
  - Nada por NodePort.
  - Sin el Secret de SeaweedFS del repositorio, que trae credenciales de laboratorio.
- `overlays/lab`: lo común, más la UI de kagent por NodePort y una monitorización sin volumen. `make gitops-lab` instala ArgoCD en kind y lo aplica.
- `tests/deploy/test_gitops.py`:
  - Cada Application usa sólo lo que permite el AppProject.
  - Todo lo que lee existe en el repositorio.
  - Los charts llevan versión exacta.
  - kagent tiene la misma versión que en el Makefile.
  - Los dos overlays se renderizan.

**El esquema** se publica en `schemas/` de este repositorio (`make schema`), y
`tests/core/test_contract.py` comprueba siempre que está al día. Ya no depende de
tener un checkout de `genai-platform` al lado.

**Se descarta:**

| Pieza | Por qué |
|---|---|
| MinIO | Deprecado en esta plataforma: los artefactos van a SeaweedFS (PR #1). `test_gitops.py` impide que vuelva. |
| Argo Workflows + `flow-compiler.py` | Sería un segundo orquestador de los mismos `kind: Workflow`, que ya ejecutan el runtime y `a2a serve` (ADR 0005: uno por flujo). Las tareas largas son la Fase 3 (`Task` A2A, Temporal opcional), no un compilador. |
| KServe + `runtime-adapters.yaml` | kagent sirve los agentes; la imagen BYO (`agent-host`) es el adaptador. |
| El chart de MLflow | `deploy/observability/mlflow` es el nuestro, con SeaweedFS y el collector. |
| ingress-nginx | Kubernetes lo retiró en marzo de 2026: sin parches de seguridad. |
| cert-manager | Sólo servía al Ingress. Vuelven juntos, con Gateway API, cuando haya algo que exponer fuera del clúster, y eso espera a la autenticación A2A (Fase 1). |

## Consecuencias

- `genai-platform` deja de tener función: se archiva (no se borra; su historia sigue disponible).
- Un clúster es `make platform` (imperativo, el laboratorio de siempre) **o** `make gitops-lab` / `root-prod.yaml` (ArgoCD). No los dos a la vez, porque helm y ArgoCD se disputarían los mismos releases.
- **Lo que no vive en git** y quien opera el clúster crea antes de aplicar `root-prod.yaml`:

  | Recurso | Namespace | Claves | Para qué |
  |---|---|---|---|
  | Secret `kagent-gemini` | `kagent` | `GOOGLE_API_KEY` | La clave del modelo |
  | Secret `seaweedfs` | `observability` | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` y `s3.json` | Las credenciales S3, con la misma forma que el de `deploy/observability/seaweedfs` |
  | Secret `grafana-admin` | `monitoring` | `admin-user`, `admin-password` | El acceso a Grafana |
  | ConfigMap `host-ca` | — | — | Sólo si la red intercepta TLS, como en i2cat |

  External Secrets / Vault (Fase 1.6) lo hará declarativo.
- **Los agentes no están en el GitOps todavía.** Sus manifiestos de kagent los genera `agentctl kagent render` a partir del catálogo, y siguen aplicándose con `make deploy`, igual que `agentctl mlflow init`. Llevarlos a ArgoCD exige que el CI publique el render (en una rama o como artefacto OCI). Es el siguiente paso de la Fase 4.3.
- **Imagen de MLflow:** pasa a la 3.17.2, que corrige vulnerabilidades del propio MLflow 3.16.1. Además se actualizan los paquetes del sistema y de Python que el escaneo del CI rechazaba.
- **Imagen de producción:** el overlay `prod` usa `ghcr.io/teo-devops/agent-platform/mlflow:v0.1.0`, que no existe hasta que se publique la primera etiqueta `v0.1.0`.

## Verificación

Lo que se comprobó con `make gitops-lab GITOPS_REVISION=<rama>`, en kind con ArgoCD v3.5.4:

- **Las 7 Applications sincronizadas y sanas:**
  - `base`, `kagent-crds` (Helm sobre OCI), `observability`, `monitoring` y `kagent` (con `$values`).
  - `kagent-ui-lab`.
  - La propia raíz.
- **Endpoints desde el host:** MLflow 3.17.2 en `:5500`, la UI de kagent en `:8082` y la consola de SeaweedFS en `:9901`.
- **Después, `make deploy`:** los tres agentes de `release.yaml` quedan `Ready`. Una llamada A2A a `code-reviewer` responde con Gemini y deja su traza en el MLflow del clúster: `invoke_agent` → `generate_content gemini-2.5-flash`.
- **Dos fallos que sólo aparecieron al sincronizar,** corregidos y cubiertos por `test_gitops.py`:
  - Una Application sin namespace de destino, que el AppProject rechaza.
  - kube-prometheus-stack, que escribe en `kube-system`.

  Un render nunca los habría mostrado.

**No verificado:** el overlay `prod` en un clúster. Necesita la imagen `v0.1.0` en GHCR y los Secrets de la tabla de arriba.
