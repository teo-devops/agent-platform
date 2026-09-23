# 3 · Multi-agente

Un agente que no hace el trabajo: reparte.

## La idea

Hay dos formas de enganchar un agente a otro, y confundirlas es la causa más
común de que un sistema multi-agente se vuelva impredecible:

- **Como herramienta** (`mode: tool`). El coordinador llama al especialista como
  llamaría a una función, recibe la respuesta y **sigue mandando él**. Existe en
  los tres frameworks.
- **Cediendo el turno** (`mode: transfer`). El coordinador se aparta y el hijo
  pasa a atender al usuario. Esto **sólo existe en ADK**; LangGraph mueve el
  control por aristas explícitas y LangChain no tiene equivalente.

Si quieres saber en todo momento quién está respondiendo, quieres `tool`.

## En la plataforma

[`agents/software-manager/agent.yaml`](../../agents/software-manager/agent.yaml):

```yaml
spec:
  sub_agents:
    - ref: python-developer
      mode: tool
      description: Writes a Python function that satisfies a requirement.
    - ref: code-reviewer
      mode: tool
      description: Reviews Python code and reports bugs, risks and improvements.
  permissions:
    profile: delegation-only      # puede delegar, no puede tocar herramientas
  policies:
    max_tool_calls: 8
```

El `description` de cada delegado no es documentación: es **lo que lee el modelo**
para decidir a quién llamar. Dos descripciones parecidas y el coordinador elegirá
mal la mitad de las veces.

Fíjate también en `delegation-only`: puede llamar a agentes y a ninguna
herramienta. Las dos listas son distintas a propósito, aunque el modelo vea
ambas cosas como herramientas.

```bash
agentctl run software-manager -m "Necesito una función que valide un IBAN"
```

## A mano

- [`en_adk.py`](en_adk.py) — `AgentTool` envuelve al hijo. Enseña también
  `sub_agents=[...]`, que es el modo `transfer`, para que se vea la diferencia.
- [`en_langgraph.py`](en_langgraph.py) — el grafo hijo se envuelve en una tool
  que lo invoca.
- [`en_langchain.py`](en_langchain.py) — lo mismo con `create_agent`.

## Lo que conviene llevarse

Aquí el **modelo** decide a quién llama, en qué orden y cuándo parar. Eso está
bien cuando el camino depende de la pregunta, y está mal cuando el camino ya lo
sabías tú desde el principio. Para eso está el escalón 4.
