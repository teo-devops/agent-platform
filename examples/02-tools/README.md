# 2 · Tools

El modelo deja de inventarse las cuentas y llama a tu código.

## La idea

Una tool es una **función Python normal**: type hints, docstring y nada más. Los
tres frameworks derivan de ella el esquema JSON que el modelo necesita para
saber cómo llamarla, leyendo los tipos y la documentación.

Eso significa que el docstring **no es un comentario**: es la descripción que lee
el modelo para decidir si usa la función y con qué argumentos. Un docstring vago
es un bug.

Y por eso las tools de este repositorio ([`catalog/tools/`](../../catalog/tools/))
no importan ningún framework: el envoltorio lo pone cada runtime, y
[`agent-mcp`](../../platform/mcp/) las sirve tal cual por MCP a quien viva fuera.

## En la plataforma

[`agents/health-advisor/agent.yaml`](../../agents/health-advisor/agent.yaml):

```yaml
spec:
  tools:
    - ref: health.calculate_bmi     # referencias, no imports
    - ref: health.get_advice
  permissions:
    profile: health-only            # sólo health.* y time.*
  policies:
    max_tool_calls: 6               # techo, por si el modelo se emboba
```

Dos cosas que no se ven a simple vista:

1. Una tool denegada **no se adjunta** al agente. El modelo ni la ve, así que no
   puede insistir. Y se vuelve a comprobar en cada llamada, por si llega por otro
   camino.
2. `max_tool_calls` existe porque un modelo en bucle llamando a una herramienta
   es la forma más rápida de gastarte el presupuesto de un mes en una tarde.

```bash
agentctl run health-advisor -m "Peso 80 kg y mido 1.82 m, ¿cómo estoy?"
```

## A mano

- [`en_adk.py`](en_adk.py) — `FunctionTool` envuelve la función.
- [`en_langgraph.py`](en_langgraph.py) — `StructuredTool.from_function`, y el
  grafo ReAct ya trae el bucle modelo→tool→modelo montado.
- [`en_langchain.py`](en_langchain.py) — `create_agent`, que en LangChain 1.x
  devuelve por dentro un grafo de LangGraph.

## Lo que conviene llevarse

La función no sabe quién la llama. Esa es la razón por la que la misma
`calculate_bmi` sirve en los tres frameworks sin tocar una línea, y la razón por
la que merece la pena mantenerla así aunque hoy sólo uses uno.
