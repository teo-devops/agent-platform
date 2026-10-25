# 0001 · Los límites de ejecución se aplican en el core

**Estado:** aceptada

## Contexto

`policies.timeout_seconds`, `policies.retry_attempts` y `budget.max_usd` se
declaraban y validaban, pero ningún runtime los aplicaba. Un agente podía
quedarse esperando a un modelo indefinidamente, y un presupuesto en dólares era
decorado. Cada framework ofrece su propio mecanismo (ADK `RunConfig`, LangGraph
`recursion_limit`, middleware en LangChain), y ninguno cubre los tres límites.

## Decisión

- **Tiempo y reintentos** se aplican en `agent_core/execution.py`, alrededor de
  `Runtime.stream`: la única costura que los tres frameworks ya comparten.
  `agentctl run`, `agentctl eval` y `agentctl a2a serve` pasan por
  `stream_with_policies`.
- Se reintenta **sólo mientras no se ha emitido nada** y **nunca** un veredicto
  de la plataforma (guardrail, permiso, configuración).
- **El coste** se cuenta donde ya se contaban las llamadas: en el enforcement de
  cada runtime, que lee los tokens a su manera y pregunta a `cost_usd` /
  `check_budget` qué significan. El precio vive en `model.pricing`, junto al
  nombre del modelo en `configs/models.yaml`.

## Consecuencias

- Un framework nuevo hereda timeout y reintentos sin hacer nada.
- Sin `pricing`, `max_usd` no corta. Un test exige que todo perfil de
  `configs/models.yaml` lo tenga.
- El host BYO de kagent ejecuta con el SDK de kagent, no con `Runtime.stream`:
  ahí el timeout aún no se aplica (pendiente, `docs/strategy.md` 0.6).
