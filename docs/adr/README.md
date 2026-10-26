# Decisiones de arquitectura

Una por fichero, numeradas, en el formato de siempre: contexto, decisión,
consecuencias. Una decisión no se edita: si cambia, se escribe otra que la
sustituye y se enlazan.

| # | Decisión | Estado |
|---|---|---|
| [0001](0001-limites-de-ejecucion-en-el-core.md) | Timeout, reintentos y presupuesto se aplican en el core, alrededor de `Runtime.stream` | Aceptada |
| [0002](0002-sandbox-enchufable.md) | El sandbox es un concepto neutro con backends enchufables | Aceptada |
| [0003](0003-openshell-como-backend.md) | NVIDIA OpenShell entra como backend de sandbox, no como runtime de agentes | Aceptada · implementada |
| [0004](0004-niveles-de-autonomia.md) | La autonomía se declara por niveles que exigen controles | Propuesta |
| [0005](0005-langflow-como-consola.md) | Langflow es la consola, no el motor: llama al catálogo por A2A | Aceptada |
| [0006](0006-sandbox-es-decision-de-entorno.md) | Quién aísla un sandbox lo decide el entorno (local · sbx · openshell) | Aceptada |
| [0007](0007-gitops-absorbe-genai-platform.md) | El despliegue GitOps (ArgoCD) vive en `deploy/gitops`; genai-platform se archiva | Aceptada |
