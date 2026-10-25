# 1 · Agente simple

Un modelo, unas instrucciones, una respuesta. Sin herramientas y sin estado.

## La idea

Un agente, en su forma mínima, son tres cosas: **qué modelo** responde, **qué
instrucciones** lleva siempre delante, y **qué mensaje** recibe. Todo lo demás
—tools, memoria, delegación— se añade encima de esto.

Lo que cambia entre frameworks en este escalón es casi nada, y por eso es un buen
sitio para empezar: te acostumbras a la forma de cada uno sin nada que distraiga.

## En la plataforma

[`tech-explainer`](../../catalog/agents/technology/tech-explainer/agent.yaml):
explica un concepto técnico a alguien de negocio, en tres frases. Fíjate en que
el prompt vive en un `.md` aparte y lleva una variable:

```yaml
spec:
  model:
    profile: balanced        # perfil, no un modelo concreto
  prompt:
    file: prompt.md
    variables:
      audiencia: "una persona de negocio sin formación técnica"
  permissions:
    profile: no-tools        # no alcanza nada, y se comprueba al construir
```

Cambiar la audiencia (`"un desarrollador junior"`) es una línea de YAML, no un
prompt nuevo. Y su suite de evals vive al lado, en
[`evals/`](../../catalog/agents/technology/tech-explainer/evals/): entre otras
cosas comprueba que no se invente un precio que no puede saber.

```bash
agentctl run tech-explainer -m "¿Qué es una API REST?"
agentctl --runtime langgraph run tech-explainer -m "¿Qué es una API REST?"
```

## A mano

- [`en_adk.py`](en_adk.py) — `LlmAgent` dentro de un `Runner`, que es quien
  gestiona la sesión.
- [`en_langgraph.py`](en_langgraph.py) — `create_react_agent` sin tools: sigue
  siendo un grafo, con un solo nodo útil.
- [`en_langchain.py`](en_langchain.py) — LCEL puro: `prompt | modelo | parser`.
  Sin agente: para un caso así, un agente sobra.

## Lo que conviene llevarse

El perfil de modelo (`balanced`) en vez del nombre del modelo. Cuando dentro de
seis meses haya que mover toda la flota a otro modelo, es una línea en
`configs/models.yaml` y no una búsqueda por todo el repositorio.
