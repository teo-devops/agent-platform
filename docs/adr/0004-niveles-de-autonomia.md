# 0004 · La autonomía se declara por niveles que exigen controles

**Estado:** propuesta

## Contexto

Un agente que responde a una pregunta y uno que actúa solo durante horas no
necesitan los mismos controles, pero hoy se declaran igual. Dejar que cada
equipo elija techos, aprobaciones y aislamiento por su cuenta da una flota
donde nadie sabe qué agente puede hacer qué sin leer su YAML entero.

## Decisión propuesta

`spec.autonomy.level`, de L0 a L4, donde cada nivel **exige** un mínimo que
`agentctl validate` comprueba:

| Nivel | Qué hace | Exige |
|---|---|---|
| L0 asistido | responde; ninguna tool con efecto | — |
| L1 herramientas | tools de lectura | techos de `policies` |
| L2 actúa | tools `write`/`network` | guardrails `standard` |
| L3 ejecuta | tools `exec` | `spec.sandbox` + aprobación humana para `write/exec/money` |
| L4 autónomo | disparadores, tareas largas | L3 + `budget.max_usd` + auditoría persistente |

## Consecuencias

- Requiere antes: riesgo por tool (Fase 1.3), aprobaciones y estado (Fase 3).
- Un entorno puede limitar el nivel máximo de la flota (`production: max L3`).
