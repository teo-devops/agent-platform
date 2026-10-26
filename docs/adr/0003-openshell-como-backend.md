# 0003 · NVIDIA OpenShell entra como backend de sandbox

**Estado:** aceptada · backend implementado en `platform/sandboxes/openshell` (ver [0006](0006-sandbox-es-decision-de-entorno.md))

## Contexto

NVIDIA OpenShell (alpha desde GTC 2026) ejecuta agentes autónomos en sandboxes
con políticas YAML declarativas sobre ficheros, red, procesos e inferencia,
aplicadas fuera del proceso del agente (Landlock, seccomp, proxy de salida que
permite, deniega o enruta y retira credenciales). Soporta harnesses como Claude
Code, Codex u OpenCode.

Se podía integrar de dos formas: como **runtime** (OpenShell ejecuta el agente
entero) o como **backend de sandbox** (OpenShell aísla lo que el agente ejecuta).

## Decisión

Las dos, en ese orden y sin mezclarlas:

1. **Backend `openshell`** de `agent_platform.sandboxes`: traduce `spec.sandbox`
   a una política de OpenShell, igual que `agent-kagent` traduce manifiestos a
   CRDs. El agente sigue siendo nuestro (ADK/LangGraph/LangChain, con su
   enforcement); OpenShell aísla sus comandos.
2. **Runtime `harness`**: para agentes que no son nuestros (un harness de
   coding), OpenShell ejecuta el agente y la plataforma lo expone por A2A. Para
   el resto del catálogo es un sub-agente más.

## Consecuencias

- `spec.sandbox` no puede tener campos que sólo entienda OpenShell. Lo que
  OpenShell sabe hacer y Docker no (filtrar por host, enrutar inferencia) ya
  está en el esquema; el backend `local` avisa de que no lo cumple.
- OpenShell está en alpha: el backend fija una versión y valida su esquema de
  política en tests antes de publicarse.

## Implementación

`render_policy(spec)` traduce `spec.sandbox` a la política (`version: 1`) y
`agentctl openshell policy <agente>` la imprime para auditarla:

| Del spec | En la política de OpenShell |
|---|---|
| `filesystem.write` / `read` | `filesystem_policy.read_write` / `read_only`, más la base de ejecución de la política por defecto (`/bin`, `/usr`, `/lib`, `/etc`, `/proc`); `/` nunca es escribible |
| — | `landlock.compatibility: hard_requirement`: sin Landlock, el sandbox no arranca |
| `process` | `run_as_user/group: "1000"` (OpenShell rechaza root) |
| `network.egress.allow` | una regla por host (puerto 443 o el indicado), para los binarios de `/usr/bin` y `/usr/local/bin`; comodines de al menos 3 etiquetas |
| `network.egress.default: allow` | **rechazado** |
| `inference.route: platform` / `direct` | `--provider $AGENT_OPENSHELL_PROVIDER` / **rechazado** |
| `resources.cpu/memory` | `--cpu`, `--memory` en `sandbox create` |
| `process.max_procs` | sin campo en la política: se avisa |
| `inference.route: none` | `--no-auto-providers`: el gateway no adjunta credenciales por su cuenta |

El backend usa el CLI (`sandbox create --policy --detach`, `sandbox exec -n
--no-tty`, `sandbox delete`), no el SDK, cuya documentación no cubre ni la
política ni el código de salida.

## Verificado (OpenShell 0.1.5, gateway local)

- `openshell sandbox get --policy-only` devuelve exactamente la política de `render_policy`.
- Landlock actúa: se niega `/home/sandbox`, aunque es del UID 1000 y sus permisos Unix lo permitirían; `/var` y `/root` tampoco son accesibles.
- Red denegada en `connect()` (`EACCES`), incluido TCP directo. Con `egress.allow`, sólo esos hosts responden.
- OpenShell limita el nombre del sandbox a 19 caracteres; `sandbox_name()` lo respeta.
- Crear un sandbox tarda unos 0,5 s con la imagen en local.
