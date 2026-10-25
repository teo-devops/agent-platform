# 0006 · Quién aísla un sandbox lo decide el entorno

**Estado:** aceptada · amplía [0002](0002-sandbox-enchufable.md)

## Contexto

Con un solo backend (`local`, un contenedor Docker), el proveedor iba escrito en
el perfil, y cambiarlo exigía tocar `configs/sandboxes.yaml`. Pero un sandbox es
un entorno, y cada proveedor tiene su propuesta:

- **Docker Sandboxes (`sbx`):** microVMs con kernel propio.
- **NVIDIA OpenShell:** política declarativa aplicada fuera del proceso, con Landlock y seccomp, red denegada por defecto y credenciales que nunca entran.

Qué proveedor usar depende de la máquina y del riesgo, no del agente.

## Decisión

- El perfil dice **qué** se aísla (ficheros, red, procesos, recursos). El entorno dice **con quién**: `sandbox.backend` en `configs/environments/<env>.yaml`, o `AGENT_SANDBOX_BACKEND`, que gana. Es la misma regla que A2A: dónde vive un sub-agente tampoco está en su manifiesto.
- El entorno sólo cambia el proveedor de los agentes que ya tienen sandbox. Nunca le da uno a quien no lo pidió.
- Cada backend traduce el spec y **dice lo que no puede cumplir**. Si lo que no puede cumplir **rebajaría** el aislamiento declarado, se niega en lugar de avisar.

## Consecuencias

```text
agentctl --env sandbox-sbx       run python-executor ...    # microVM
agentctl --env sandbox-openshell run python-executor ...    # OpenShell
agentctl                         run python-executor ...    # contenedor local
```

- **sbx (verificado, v0.42):**
  - La política global por defecto permite `**`, y las reglas por sandbox sólo restringen. Por eso "sólo pypi.org" no se puede expresar sin tocar la política global, que afecta a todos los sandboxes de la máquina. El backend se niega y explica por qué; nunca la toca.
  - La red se corta en el proxy de sbx: un `connect()` TCP se acepta, pero no llegan datos.
- **OpenShell:** `egress.default: allow` e `inference.route: direct` se rechazan porque rebajarían el aislamiento.
