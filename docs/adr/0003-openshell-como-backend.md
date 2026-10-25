# 0003 · NVIDIA OpenShell entra como backend de sandbox

**Estado:** aceptada (implementación pendiente)

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
