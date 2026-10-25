# 0002 · El sandbox es un concepto neutro con backends enchufables

**Estado:** aceptada

## Contexto

Las tools del catálogo son puras a propósito (`code.py` analiza, no ejecuta)
porque no había dónde ejecutar nada sin riesgo. Los casos que piden las
organizaciones —agentes que prueban su código, instalan dependencias, navegan o
manejan un repositorio— necesitan ejecución aislada. Hay varias formas de
aislar (un contenedor local, NVIDIA OpenShell, pods con gVisor/Kata) y ninguna
sirve en todos los carriles.

## Decisión

- `spec.sandbox` describe **qué** se aísla: ficheros, salida de red (deny por
  defecto), procesos, acceso a un modelo, recursos. Con perfiles en
  `configs/sandboxes.yaml`, como el resto.
- **Cómo** se aísla es un backend instalado bajo `agent_platform.sandboxes`. El
  primero es `local` (Docker), en `platform/sandboxes/local`.
- Las tools `sandbox.*` se construyen en el core **por agente**, ligadas a su
  propio sandbox (como las de skills), y los builders sólo las envuelven. A
  diferencia de las de skills, **sí** pasan por `permissions.tools`: ejecutar un
  comando es alcanzar el mundo.
- El sandbox se abre en la primera llamada, no al construir: `validate` y los
  playgrounds construyen todo el catálogo.
- Un backend que no puede aplicar parte del spec **lo dice** al abrir.

## Consecuencias

- Cambiar de Docker a OpenShell es cambiar `backend:` en un perfil.
- `kagent render` rechaza un agente con sandbox en modo declarativo: sin él
  perdería sus tools, y eso no es un aviso, es otro agente.
- Una sesión vive lo que el agente construido; en `a2a serve` la comparten las
  peticiones. Sesión por invocación llegará con la Fase 3 (estado).
