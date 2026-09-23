# Guion de la demo — plataforma de agentes para desarrolladores junior

**Caso de uso: ingeniería de software.** Un jefe de desarrollo recibe un
requisito, lo encarga a un desarrollador y pasa el resultado a un revisor que
fundamenta sus hallazgos con análisis estático. Tres agentes, una skill, tres
tools de código.

El camino que recorre la demo: un agente se describe una vez, se desarrolla en
local con el framework que quieras, se despliega en un runtime de plataforma y
se observa en MLflow.

- **Versión completa: ~25 min.** Paso 0 con los tres frameworks.
- **Versión exprés: 15 min.** Paso 0 sólo con ADK (3′), Paso 3 sin evals.

Antes de empezar, lee [`concepts.md`](concepts.md): la matriz y el diagrama son
la primera diapositiva.

---

## Preparación (el día antes, no en directo)

```bash
cd agent-platform
make install
cp .env.example .env            # GOOGLE_API_KEY=...  (también la lee el clúster)
make lab                        # kind + registro + MLflow + MinIO + collector + kagent + agentes (~10 min)
make status                     # los tres agentes Ready; catalog-tools ACCEPTED True
```

Deja abiertas en pestañas las UIs de la tabla del
[README](../README.md#las-uis) (`make ui-urls` las imprime): kagent, MLflow
(trazas, versiones, prompts) y, para el Paso 0, la del playground de turno.

Haz **una pasada completa** del guion. Así quedan trazas de ensayo que sirven de
plan B, y `make metrics` tiene algo que comparar.

Ten a mano, en un editor:

- `catalog/agents/engineering/python-developer/agent.yaml` y su `prompt.md`
- `catalog/agents/engineering/code-reviewer/agent.yaml`
- `catalog/agents/engineering/software-manager/agent.yaml`
- `catalog/skills/hexagonal-architecture/SKILL.md`
- `catalog/tools/code.py`
- `deploy/kagent/release.yaml`

Y este fragmento con fallos, para el Paso 1:

```python
def load(path, cache={}):
    try:
        if cache.get(path) == None:
            print("miss")
    except:
        pass
    return eval(path)
```

---

## 0–2′ · Contexto

Enseña la matriz de [`concepts.md`](concepts.md).

> "Hoy vamos a separar tres cosas que se suelen mezclar. El framework es cómo
> escribes el agente. El runtime es quién lo ejecuta y lo opera. El protocolo es
> cómo habla con lo que no es él. Vais a ver el mismo agente pasar por tres
> frameworks, desplegarse en un runtime y hablar por dos protocolos, haciendo
> algo que conocéis: escribir y revisar código."

---

## 2–9′ · Paso 0 — un manifiesto, tres frameworks (sin kagent)

**Qué enseña:** framework, tools, skills, y que la observabilidad no depende del
runtime.

1. Abre `python-developer/agent.yaml`. Señala `model.profile`, `prompt.file`,
   `tools: code.check_syntax` y `skills: hexagonal-architecture@^1.0`.
   *"No hay una línea de Python del framework."*
2. Abre `code.py`: *"una tool es una función con tipos y docstring; el docstring
   es lo que lee el modelo"*. Y `hexagonal-architecture/SKILL.md`: *"una skill son
   instrucciones que el agente lee sólo cuando le hacen falta; al prompt sólo va
   la descripción"*.
3. **ADK:**

   ```bash
   make dev-adk AGENT=python-developer
   ```

   En ADK Dev UI (http://localhost:8000/dev-ui/?app=python_developer; el
   desplegable de arriba tiene todo el catálogo, una app por manifiesto):

   > Una función que guarde un pedido en PostgreSQL y devuelva su id.

   Pestaña **Events/Trace**: `skill_read(hexagonal-architecture)` antes de
   escribir y `code.check_syntax` sobre el borrador. *"Toca infraestructura, así
   que el agente decidió leer la skill. Nadie se la metió en el prompt."* El
   código sale con un puerto (`Protocol`) y el driver fuera del dominio.

   Ahora escribe *"ignore previous instructions"*: responde el guardrail, sin
   llamar al modelo. *"Guardrails y permisos también se aplican en el
   playground, porque la app que carga ADK es la misma que ejecuta `agentctl run`."*

4. **LangGraph** (Ctrl+C y):

   ```bash
   make dev-langgraph
   ```

   En LangGraph Studio, elige `python-developer`. Se ve el **grafo**: `model`,
   `tools` y los nodos de enforcement (`before_model`, `after_model`). Misma
   petición. *"Mismo YAML. Ahora es un StateGraph, y los guardrails son nodos."*

5. **LangChain** (Ctrl+C y):

   ```bash
   make dev-langchain
   ```

   Mismo Studio: `create_agent` de LangChain 1.x devuelve un grafo de LangGraph.

6. MLflow → [Trazas](http://localhost:5500/#/experiments/0/traces). Tres trazas
   de `python-developer`; columna `agent.framework`: `adk`, `langgraph`,
   `langchain`.

   > "El framework cambió tres veces; lo que vemos en MLflow no. Los agentes no
   > saben que existe MLflow: sólo hablan OpenTelemetry."

   Para ver el código nativo que la plataforma escribe por ti:
   [`examples/`](../examples/). Para ver qué **no** hace cada framework: la
   tabla de paridad de [`architecture.md`](architecture.md).

> **Exprés:** sólo los puntos 3 y 6.

---

## 9–13′ · Paso 1 — despliegue declarativo con un ToolServer MCP

**Qué enseña:** runtime, CRDs, MCP.

1. Abre `deploy/kagent/release.yaml`. *"El manifiesto dice qué es el agente;
   esto dice dónde y cómo corre. El revisor y el jefe van en modo declarativo:
   kagent los construye y los ejecuta, de lo nuestro no corre nada. El
   desarrollador va en BYO: ahí sí corre nuestro runtime."*
2. Genera los CRDs:

   ```bash
   make render
   ```

   Lee los avisos: *"kagent no aplica nuestros guardrails en modo declarativo,
   y nos lo dice. Si los necesitas, `mode: byo`."* Abre
   `.agent-platform/dist/kagent/agent-code-reviewer.yaml`: `ModelConfig`,
   `ConfigMap` con el prompt, `Agent` con `tools: McpServer` (`code.*`) y
   `skills.refs`. *"Nadie ha escrito este YAML: sale del manifiesto."*
3. El ToolServer MCP:

   ```bash
   kubectl -n kagent get remotemcpserver catalog-tools -o yaml | grep -A8 discoveredTools
   ```

   *"Es un servidor MCP que publica `catalog/tools/code.py`: las mismas
   funciones que en el Paso 0 se llamaban en proceso. kagent le preguntó qué
   tools tiene: descubrimiento, no configuración."* (En kagent 0.10 el antiguo
   `ToolServer` se llama `RemoteMCPServer`.)
4. kagent UI → [`code-reviewer`](http://localhost:8082/agents/kagent/code-reviewer/chat).
   Pega el fragmento con fallos y pide: *"Revisa este código"*.
   Se ven las llamadas a `code.metrics` y `code.find_smells`, y la revisión cita
   líneas concretas: default mutable (1), `== None` (3), `print` (4), `except:`
   desnudo (5), `eval` (7). *"El agente no adivina los fallos: los mide una
   herramienta, por MCP, y él los explica."*

---

## 13–18′ · Paso 2 — A2A: tres agentes colaborando

**Qué enseña:** A2A, declarativo vs BYO, la misma skill por dos caminos.

1. La tarjeta A2A del desarrollador:

   ```bash
   kubectl -n kagent port-forward svc/python-developer 18080:8080 &
   curl -s localhost:18080/.well-known/agent-card.json | jq '{name, version, description}'
   ```

   *"Así se presenta un agente a otros agentes: qué sabe hacer y en qué
   versión. Es A2A. Al jefe le da igual que por dentro sea LangGraph."*
2. kagent UI → [`software-manager`](http://localhost:8082/agents/kagent/software-manager/chat):

   > Una función que calcule la mediana de una lista de números.

   Se ven dos llamadas de herramienta, `python_developer` y `code_reviewer`:
   cada una es una llamada **A2A** a otro pod. Si el revisor marca algo de
   severidad alta (por ejemplo, la lista vacía), el jefe devuelve el código una
   vez al desarrollador. La respuesta final trae código, revisión y qué se
   corrigió.
3. La skill, por dos caminos:

   ```bash
   kubectl -n kagent exec deploy/code-reviewer -c kagent -- ls -R /skills
   ```

   *"El revisor, declarativo, recibe la skill como imagen OCI que kagent monta
   en `/skills`. El desarrollador, BYO, la lee con `skill_read`. Misma carpeta
   del catálogo, dos mecanismos."*

---

## 18–24′ · Paso 3 — MLflow: trazas, prompt versionado, métricas

**Qué enseña:** observabilidad, versionado de prompts y de agentes, evals.

1. **La traza.** MLflow → [Trazas](http://localhost:5500/#/experiments/0/traces)
   → la última. Despliega el árbol: controller → `software-manager` → A2A →
   `python-developer` → `skill_read`/`code.check_syntax` → A2A →
   `code-reviewer` → `code.metrics`/`code.find_smells`. *"Una petición, cuatro
   pods, una traza."* Columnas `agent.name`, `agent.version`, `prompt.version`
   (si no aparecen: `make metrics`, que primero sincroniza).
2. **Versiones del agente.** MLflow → [Modelos](http://localhost:5500/#/experiments/0/models):
   un `LoggedModel` por agente, con modelo, framework, tools, skills y
   `prompt.hash`. *"Cada versión del manifiesto es un modelo registrado."*
3. **Prompt Registry.** MLflow → [Prompts](http://localhost:5500/#/prompts) →
   `python-developer`, versión 1.
4. **Línea base de calidad** (necesita clave; ~1 min):

   ```bash
   make eval-run SUITE=python-developer
   ```

   Run `eval python-developer · python-developer@0.2.0`: `pass_at_1`, tabla por
   caso (función tipada, mediana con lista vacía, puerto hexagonal) con el
   `trace_id` de cada uno. La eval ejecuta **el mismo manifiesto** en local y su
   juez es otro agente del catálogo (`eval-judge`): se compara la versión del
   agente, no el pod.
5. **Cambiar el prompt.** En `python-developer/prompt.md` añade:

   ```text
   - Trata explícitamente las entradas vacías o inválidas: lanza un ValueError
     con un mensaje claro y documéntalo en el docstring.
   ```

   y en `agent.yaml` sube `version: 0.2.0` → `0.3.0`. Después:

   ```bash
   make deploy          # prompts (v2) -> render -> apply -> register (python-developer@0.3.0)
   ```

   *"Un cambio de prompt es un cambio de versión: nuevo prompt en el registro,
   nuevo modelo y el pod se reinicia con él."* Repite la petición de la mediana
   al `software-manager`; la traza nueva dice `prompt.version = 2`, y el revisor
   ya no marca la lista vacía.
6. **¿Mejor o peor?**

   ```bash
   make eval-run SUITE=python-developer
   make metrics
   ```

   MLflow → [Runs](http://localhost:5500/#/experiments/0/runs): compara los dos
   runs de eval (el caso `casos-limite` debería pasar a verde). La tabla de
   `make metrics` agrupa por agente, versión de prompt y framework: latencia
   p50/p95, tokens y tool calls, **incluidos los tres frameworks del Paso 0**.

---

## 24–26′ · Cierre

> "Hemos cambiado de framework con una línea y de runtime con un fichero de
> release, y en ningún momento hemos tocado la observabilidad. El framework es
> vuestro, el runtime es de plataforma, y lo que los une son protocolos: MCP
> para las tools, A2A entre agentes, OpenTelemetry para las trazas."

Preguntas que suelen salir:

- **¿Por qué no todo declarativo?** Porque kagent no aplica tus guardrails ni tus
  políticas, y no sabe de workflows. `render` te lo dice.
- **¿Por qué el BYO es LangGraph y no ADK?** `kagent-adk` 0.10 fija
  `google-adk<2`; la plataforma usa ADK 2.x. Detalle en
  [`architecture.md`](architecture.md).
- **¿Las tools ejecutan el código que revisan?** No: `code.py` sólo lo analiza
  con `ast`. Ejecutar código generado por un modelo exige un sandbox, y eso es
  otra demo.
- **¿Y si cambio de proveedor de trazas?** Cambias el exporter del collector.
  Ningún agente se entera.

---

## Plan B

| Si falla... | Haz esto |
|---|---|
| Gemini (cuota, red) | Enseña las trazas del ensayo en MLflow; el Paso 1 se puede contar con `make render` y `discoveredTools`, que no llaman al modelo |
| LangGraph Studio no carga (UI en smith.langchain.com) | `langgraph dev --no-browser` y enseña la API en http://127.0.0.1:2024/docs; o salta a ADK |
| Un pod no arranca | `make status`; `kubectl -n kagent describe agent <nombre>`; `make deploy` es idempotente |
| `discoveredTools` no refleja las tools nuevas | `make refresh-tools` |
| La traza no tiene `agent.*` | `make metrics` (sincroniza primero); `kubectl -n observability logs deploy/otel-collector` |
| El clúster no está (Paso 2) | A2A sin kagent: `make a2a-up` en una terminal y `make a2a-run` en otra. Mismos tres agentes, cada uno en su framework, delegación por A2A narrada en las dos terminales |
| WARP conectado (TLS interceptado) | El clúster monta la CA del host; si Gemini falla por certificado, `warp-cli disconnect` |

## Resetear entre ensayos

Deshaz los dos cambios del paso 3.5 (la línea del prompt y `version: 0.3.0`) y
vuelve a desplegar:

```bash
make deploy          # el prompt v1 ya está registrado: no crea versión nueva
```

MLflow conserva las versiones anteriores a propósito: el historial es parte de
lo que se enseña. Para empezar de cero: `make cluster-down && make lab`.
