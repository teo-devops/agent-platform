# Decisiones de arquitectura

Una por fichero, numeradas, en el formato de siempre: contexto, decisión,
consecuencias. Una decisión no se edita: si cambia, se escribe otra que la
sustituye y se enlazan.

| # | Decisión | Estado |
|---|---|---|
| [0001](0001-limites-de-ejecucion-en-el-core.md) | Timeout, reintentos y presupuesto se aplican en el core, alrededor de `Runtime.stream` | Aceptada |
| [0002](0002-sandbox-enchufable.md) | El sandbox es un concepto neutro con backends enchufables | Aceptada |
| [0003](0003-openshell-como-backend.md) | NVIDIA OpenShell entra como backend de sandbox, no como runtime de agentes | Aceptada |
| [0004](0004-niveles-de-autonomia.md) | La autonomía se declara por niveles que exigen controles | Propuesta |
