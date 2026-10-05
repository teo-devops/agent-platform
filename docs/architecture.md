# Arquitectura

## Un manifiesto, tres frameworks

La afirmación de este repositorio es que un agente se describe una vez y lo
ejecuta el framework que quieras. Durante mucho tiempo fue sólo una afirmación:
había un runtime, ADK, y nada con lo que comprobarla. Ahora hay tres, leyendo los
mismos ficheros, y `tests/runtimes/test_runtimes.py` falla si alguien cuela un concepto de
un framework dentro del esquema.

```text
             catalog/agents/*/agent.yaml   catalog/workflows/*.yaml
                              (agents.platform/v1)
                                      |
                              spec.runtime: ?
                    ______________ ___|___ ______________
                   |                       |              |
             agent-runtime-adk   -langgraph        -langchain
             LlmAgent + App      StateGraph        create_agent + LCEL
```

## Los paquetes

Cada uno es una distribución con su `pyproject.toml`, su versión y sus
dependencias declaradas por versión, no por ruta. `pyproject.toml` de la raíz es
sólo el workspace que los agrupa.

```text
platform/
├── core/                 agent-core              neutro: esquemas, config, registros, skills, evals, tracing
├── runtime/              agent-runtime           el anfitrión: agentctl, fábrica, playgrounds
├── runtimes/
│   ├── adk/              agent-runtime-adk       manifiesto -> LlmAgent + App (+ enforcement)
│   ├── langgraph/        agent-runtime-langgraph manifiesto -> StateGraph
│   └── langchain/        agent-runtime-langchain manifiesto -> create_agent + LCEL
├── mcp/                  agent-mcp               catalog/tools servido por MCP
├── a2a/                  agent-a2a               un agente servido por A2A; delegar en uno remoto
├── kagent/               agent-kagent            manifiesto -> CRDs de kagent; host BYO
└── integrations/
    └── mlflow/           agent-mlflow            prompts, versiones de agente, evals y métricas
```

### `agent-core` — neutro de verdad

Cero imports de cualquier framework, y hay un test que lo comprueba
(`tests/test_boundaries.py`). Contiene:

- `schemas/` — los manifiestos `kind: Agent` y `kind: Workflow` como modelos
  Pydantic con `extra="forbid"`, para que un typo falle en `agentctl validate` y
  no tres semanas después. Es también de donde salen el JSON Schema
  (`agentctl schema`) y la referencia de campos: **nada se escribe dos veces**.
- `skills.py` — carga de `SKILL.md` y divulgación progresiva: el índice viaja en
  el prompt, el cuerpo se sirve con una herramienta.
- `evals/` — esquema de las suites y el motor que las puntúa. Recibe dos
  corrutinas (`run` y `judge`) desde fuera, así que no sabe de ningún framework.
- `config/` — descubrimiento del árbol, merge por capas, interpolación `${VAR}`
  y expansión de perfiles.
- `registry.py` — resolución de referencias por *entry points*, y los grupos que
  el resto de paquetes usan para enchufarse (ver abajo).
- `contracts.py` — los `Protocol` que implementan los runtimes.
- `result.py` — `BuildResult`, lo único que los tres tienen que acordar.
- `topology.py` — `sequential`/`parallel`/`graph` resueltos a pares de nombres,
  sin framework.
- `publish.py` — la forma resuelta de un manifiesto: mismo documento, con las
  dependencias escritas y las versiones pinneadas.
- `guardrails/` — evaluación de reglas sobre texto, sin red. Los tres runtimes la
  reutilizan tal cual.
- `telemetry/` — logging estructurado y **tracing OpenTelemetry opcional**
  (`agent-core[tracing]`). Sin `OTEL_EXPORTER_OTLP_ENDPOINT` no hace nada; con él,
  cada span lleva `agent.name`, `agent.version`, `agent.framework` y
  `prompt.hash`. La plataforma habla OTel y nada más: a dónde van las trazas lo
  decide quien pone la variable.

### `agent-runtime` — el anfitrión, sin framework

Encuentra la configuración, monta el contexto, decide qué runtime construye cada
manifiesto y expone `agentctl`. No importa ADK ni LangGraph: instalarlo te da la
CLI y nada con lo que ejecutar. También genera los puentes de cada playground
(`agentctl ui`) en `.agent-platform/`.

### `agent-runtime-adk` · `-langgraph` · `-langchain`

Un paquete por framework. Cada uno publica, por entry points, los builders de
`kind: Agent` y `kind: Workflow` para su runtime, el runtime en sí y, en el caso
de LangGraph y LangChain, su instrumentación OTel (ADK emite spans de serie).
Ninguno se importa por nombre desde ningún sitio: **instalarlo es lo que hace
que `spec.runtime: X` funcione**.

El enforcement vive dentro de cada runtime, porque es donde se engancha:
`agent_runtime_adk/enforcement/` son `BasePlugin` de ADK; LangGraph usa
`pre/post_model_hook` y LangChain `AgentMiddleware`. Hasta la reorganización,
los plugins de ADK vivían en un paquete `agent-plugins` que parecía neutral y no
lo era.

### `agent-mcp` — las tools, por protocolo

Dentro del repositorio una tool es una función de `catalog/tools/` que los
runtimes llaman en proceso. En cuanto el agente vive fuera —un agente
declarativo de kagent, un IDE, otro equipo— la función tiene que viajar por un
protocolo. `agentctl mcp serve` publica **el mismo registro** por MCP
(streamable HTTP o stdio): type hints y docstring ya son el esquema. Fijado a
`mcp<2` porque los clientes que importan (kagent, ADK) están en la serie 1.x.

### `agent-a2a` — los agentes, por protocolo

Lo mismo que `agent-mcp`, un nivel más arriba. `agentctl a2a serve` publica
cualquier agente del catálogo, en cualquier framework, con su tarjeta en
`/.well-known/agent-card.json` y `message/send` por JSON-RPC. Es la otra mitad de
la delegación: cuando el entorno dice que un sub-agente vive en otro proceso
(`a2a.endpoints` en `configs/environments/<env>.yaml`, o `AGENT_A2A_ENDPOINTS`),
los builders piden a la fábrica un delegado (`factory.remote`), y lo que reciben
es un `A2ADelegate` de este paquete, anunciado bajo `agent_platform.transports`.
El builder lo envuelve como tool con el mismo nombre que tendría el hijo en
proceso: el prompt del coordinador, sus permisos y sus trazas no cambian.

El cliente es JSON-RPC sobre `httpx`, sin el SDK de A2A, y lee tanto un
`Message` (lo que responde este servidor) como un `Task` (lo que responde
kagent). Inyecta `traceparent`, y el servidor lo lee: una delegación que cruza
procesos sigue siendo una sola traza. Fijado a `a2a-sdk<1`, la serie que habla
kagent 0.10.

### `agent-kagent` — el catálogo, operado por kagent

kagent es un *runtime* en el sentido de plataforma: despliega agentes como
recursos de Kubernetes, expone cada uno por A2A, les da UI y exporta sus
trazas. No es un framework. Este paquete hace de puente en los dos sentidos:

- `agentctl kagent render` traduce los manifiestos a CRDs de kagent
  (`kagent.dev/v1alpha2`) según `deploy/kagent/release.yaml`. Un agente puede ir
  como **Declarative** —kagent lo construye y lo ejecuta con su propio motor; de
  lo nuestro no corre nada— o como **BYO** —corre nuestro runtime dentro del
  contrato de pod de kagent—. Lo que el modo declarativo no sabe expresar
  (guardrails, políticas, temperatura) se avisa; lo que no tiene sentido
  (workflows, `mode: transfer`) es un error que sugiere `byo`.
- `agentctl kagent host` es lo que corre dentro del pod BYO: construye el agente
  desde el manifiesto y lo sirve con `kagent-langgraph`. LangGraph y no ADK
  porque `kagent-adk` 0.10 fija `google-adk<2` y el runtime de la plataforma
  está en la 2.x; como `create_agent` de LangChain 1.x devuelve un grafo de
  LangGraph, el mismo host sirve los dos.

### `agent-mlflow` — el backend de AgentOps

El **único** paquete que importa `mlflow` (lo comprueba `tests/test_boundaries.py`).
Responde a cuatro preguntas:

| Pregunta | Comando | En MLflow |
|---|---|---|
| ¿Qué prompt está corriendo? | `agentctl mlflow prompts` | Prompt Registry; una versión por texto distinto (hash) |
| ¿Qué versión del agente respondió? | `agentctl mlflow register` · `sync` | `LoggedModel` por `nombre@versión`; trazas etiquetadas |
| ¿Es mejor la v2 que la v1? | `agentctl eval --sink mlflow` | Run por suite, métricas sobre el `LoggedModel`, tabla por caso con su traza |
| ¿Cómo se comporta? | `agentctl mlflow metrics` | Latencia, tokens y tool calls por agente, prompt y framework |

## Cómo se enchufan los paquetes

Nadie importa a nadie por nombre de más arriba. Todo se descubre por entry
points, así que **instalar un paquete es lo que hace que su capacidad exista**:

| Grupo | Lo publican | Lo consume |
|---|---|---|
| `agent_platform.builders` / `.runtimes` | `runtimes/*` | la fábrica de `agent-runtime` |
| `agent_platform.plugins` | `runtimes/adk` | `spec.plugins` |
| `agent_platform.instrumentors` | `runtimes/langgraph`, `runtimes/langchain` | `configure_tracing()` |
| `agent_platform.commands` | `mcp`, `a2a`, `kagent`, `integrations/mlflow` | `agentctl` (subcomandos) |
| `agent_platform.transports` | `a2a` | la fábrica, al construir un sub-agente remoto |
| `agent_platform.eval_sinks` | `integrations/mlflow` | `agentctl eval --sink` |

```text
agent-core  <-  agent-runtime  <-  runtimes/*  ·  mcp  ·  kagent  ·  integrations/mlflow
                     ^                                   |
                     |_____ descubre por entry points ___|
```

`agent-runtime` necesita ejecutar lo que construyen los runtimes, y los runtimes
necesitan la fábrica para construir los sub-agentes de cada paso. Eso sería un
ciclo si se importaran. No lo hacen.

## Dónde vive cada cosa, y por qué

```text
platform/     lo que se publica            cambia poco, lo toca el equipo de plataforma
catalog/      lo que se ejecuta            cambia a diario, lo toca cada equipo dueño
configs/      perfiles y entornos          cambia cuando cambia la flota
evals/        lo que mide si va bien       crece con cada fallo de producción
deploy/       lo que lo opera              kind, observabilidad, kagent, imágenes
```

El corte no es estético. Un cambio en `catalog/` no debería requerir release de
nada, y un cambio en `platform/` debería poder publicarse sin tocar un solo
agente. Cuando esas dos frases dejan de ser ciertas, el diseño se ha roto, y el
árbol es lo primero que lo enseña.

Por eso las tools bajaron a `catalog/`: estaban en un paquete, así que añadir una
era editar Python, declarar un entry point y reinstalar. Ahora es soltar un
fichero. Y por eso `deploy/kagent/release.yaml` no está dentro de ningún
`agent.yaml`: qué agentes corren en un clúster y en qué modo es una decisión de
despliegue, no parte de lo que el agente es.

## Skills: por qué no va todo en el prompt

Una skill es una carpeta con un `SKILL.md` en el formato que se ha estandarizado
—frontmatter con `name`, `version`, `description` y `when_to_use`, más el cuerpo
en Markdown—. Se eligió ese formato antes que inventar otro para poder usar
skills de fuera y publicar las propias.

Lo obvio sería concatenar el cuerpo al system prompt, y es lo caro: tres skills
de 2.000 tokens son 6.000 tokens en **cada** llamada, se usen o no, compitiendo
por la atención del modelo con la tarea. Así que sólo viaja el índice, y el
cuerpo se sirve con `skill_read`.

Que eso funcione igual en los tres runtimes no es casualidad: por debajo es una
herramienta más, y las herramientas ya eran neutras.

Una decisión que conviene tener explícita: **las herramientas de skill no pasan
por `permissions.tools`**. Esas listas controlan lo que un agente alcanza del
mundo, y leer las instrucciones que él mismo declaró en `spec.skills` no es
alcanzar nada. Declarar la skill es el permiso. Lo contrario sería contabilidad
doble: engancharías una skill, olvidarías el permiso, y el agente se quedaría sin
poder leerla sin que nadie dijera nada.

### Una skill, dos mecanismos

La misma carpeta `catalog/skills/<nombre>/` llega al agente por dos caminos, y
la demo enseña los dos:

- **En nuestros runtimes** (local o BYO): índice en el prompt y `skill_read`.
- **En un agente declarativo de kagent**: kagent 0.10 carga skills de forma
  nativa (`spec.skills.refs`). `make skills` publica cada skill como imagen OCI
  (`FROM scratch` + la carpeta) en el registro del laboratorio, y un init
  container de kagent la deja en `/skills/<nombre>` antes de arrancar el agente.
  Imágenes y no S3: el init container de kagent usa el cliente S3 de AWS sin
  *path-style*, y SeaweedFS no lo sirve sin DNS comodín.

## Evals: dos puertas, no una

Evaluar un agente exige ejecutarlo, y ejecutarlo exige un modelo. No hay forma de
puntuar una respuesta que no existe, así que la idea de "evals en CI sin
credenciales" es media verdad. Las puertas son dos:

| | Qué comprueba | ¿Clave? | Cuándo |
|---|---|---|---|
| `agentctl eval --check` | esquema, criterios y objetivos que existen | no | cada commit |
| `agentctl eval` | si el agente responde bien | sí | antes de release |

El juez es un agente del catálogo (`eval-judge`) construido con la misma fábrica,
lo que evita añadir una superficie de protocolo sólo para esto. Corre a
temperatura 0: un juez que fluctúa no sirve para comparar dos ejecuciones, que es
justo para lo que existe. Y cuando su respuesta no se puede leer, el caso
**suspende** — dar por bueno lo que no se entendió convertiría la suite en
decorado.

## Paridad entre runtimes

No es completa, y fingir que lo es sería peor que la tabla. Cada ❌ tiene una
razón de diseño del framework, no una tarea pendiente:

| | adk | langgraph | langchain |
|---|---|---|---|
| Guardrails de entrada/salida | ✅ plugins de `App` | ✅ `pre_model_hook` / `post_model_hook` | ✅ `AgentMiddleware` |
| Permisos de herramienta | ✅ en build y en llamada | ✅ en build y en llamada | ✅ en build y en `wrap_tool_call` |
| Techos de llamadas | ✅ | ✅ | ✅ |
| Delegación `mode: tool` | ✅ | ✅ | ✅ |
| Delegación `mode: transfer` | ✅ nativo | ❌ el control va por aristas | ❌ sin equivalente |
| Flujo `sequential` / `parallel` | ✅ | ✅ | ✅ |
| Flujo `graph` | ✅ | ✅ | ❌ LCEL son cadenas |
| Flujo `loop` | ✅ `LoopAgent` | ✅ arista condicional de vuelta | ❌ |
| Skills (`skill_read`) | ✅ | ✅ | ✅ |
| Playground | ✅ `adk web`, todo local, con enforcement | ⚠️ API local, UI remota | ⚠️ igual que langgraph |
| Trazas OTel | ✅ nativas | ✅ OpenInference | ✅ OpenInference |
| Agente BYO en kagent | ❌ `kagent-adk` fija `google-adk<2` | ✅ `kagent-langgraph` | ✅ el mismo host |

Dos diferencias de comportamiento que conviene conocer:

- Cuando un guardrail de **entrada** bloquea, ADK devuelve el mensaje de bloqueo
  en lugar de la respuesta; en LangGraph y LangChain la ejecución lanza
  `GuardrailViolation`. Un hook devuelve actualizaciones de estado y no puede
  cortocircuitar el grafo, y simular el corte pidiéndole al modelo que se niegue
  sería teatro: la llamada se haría igual.
- Los techos de `policies` se cuentan leyendo la conversación en vez de llevando
  un contador. Sale gratis que sean correctos por invocación: no hay estado que
  reiniciar entre ejecuciones.

## Cómo se aplica lo declarado

### Permisos: dos veces, a propósito

1. **En build**: `build_tools()` no adjunta una tool denegada, así que el modelo
   ni siquiera la ve. Esto permite que un overlay de entorno restrinja la flota
   entera sin editar ningún manifiesto.
2. **En ejecución**: `ToolPermissionPlugin` vuelve a comprobar en cada llamada,
   para que una tool que llegue por otro camino (un sub-agente, un toolset
   resuelto en runtime) siga sujeta a las mismas listas.

Las tools y los agentes delegados se rigen por listas distintas
(`permissions.tools` y `permissions.agents`) aunque el modelo vea ambos como
herramientas.

### Guardrails: dónde vs. qué

El *dónde* (antes del modelo, después del modelo, antes de la tool) lo decide el
plugin. El *qué significa una regla* vive en `agent_core.guardrails`. Añadir una
regla es configuración; añadir un **tipo** de regla es una versión nueva del core.

### Plugins con ámbito

ADK registra los plugins en la `App`, así que sus callbacks se disparan para todos
los agentes del árbol. La plataforma construye una instancia de plugin por
manifiesto y cada una ignora los callbacks de otros agentes (`_scope.py`). Gracias
a eso un sub-agente puede llevar sus propios guardrails y permisos usando el
gestor de plugins único de ADK.

Consecuencia práctica: los plugins viajan junto al agente en un `BuildResult`, y
`build_app()` recoge los de todo el árbol. Si usas `build_agent()` en vez de
`build_app()`, obtienes el agente **sin** enforcement: úsalo solo para incrustarlo
en otro runtime.

## Límites conocidos

- LangGraph Studio sirve su API en local pero la interfaz se sirve desde
  `smith.langchain.com` y se conecta a tu `localhost`. En una red que lo bloquee,
  la API sigue en pie y la UI no. `adk web` no tiene ese problema.
- `timeout_seconds` y `retry_attempts` se declaran y se validan, pero hoy no se
  aplican en el runtime; están pendientes de conectar con `RunConfig`.
- `budget.max_usd` se declara pero no se contabiliza: el corte por coste se hace
  hoy con `budget.max_tokens`.
- **kagent declarativo no aplica guardrails ni políticas.** `render` lo avisa.
  Si un agente los necesita en el clúster, va en `mode: byo`.
- **Un sub-agente remoto sólo puede ser `mode: tool`.** `transfer` cede el turno
  dentro de una sesión de ADK, y eso no cruza un proceso.
- **`agentctl a2a serve` no guarda conversación ni hace streaming.** Cada
  `message/send` es una ejecución nueva, que es lo que necesita una delegación.
- **El host BYO no conserva memoria entre mensajes.** El grafo se compila sin el
  checkpointer de kagent; para un agente al que se delega por A2A (una petición,
  una respuesta) es lo esperado.
- **kagent 0.10 no vuelve a descubrir las tools de un `RemoteMCPServer`** cuyo
  spec no cambia, aunque el servidor publique otras. Tras añadir o quitar tools
  del catálogo: `make refresh-tools` (recrea el recurso).
- **Un agente ADK no puede ir como BYO** con kagent 0.10 (`google-adk<2`). Va
  como declarativo, o con `runtime: langgraph`/`langchain` en el release.
- Enlazar trazas a un `LoggedModel` exige que la traza lleve el id del modelo
  cuando se crea, y las que llegan por OTLP no lo llevan. Se enlazan por
  etiquetas (`agent.version`) con `agentctl mlflow sync`; las métricas de eval sí
  se registran sobre el `LoggedModel`.
