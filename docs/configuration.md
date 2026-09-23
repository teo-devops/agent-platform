# Referencia de configuración

> GENERADO desde los modelos de `agent-core`. No lo edites a mano: cambia el
> modelo y ejecuta `make docs`. Si esta página se desfasa, `make test` falla.

Un manifiesto se escribe una vez y lo ejecutan los tres runtimes. Nada de lo que
hay aquí nombra un framework, salvo `spec.runtime`, que es precisamente el
interruptor para elegirlo.

Dos formas del mismo documento: la que **escribes** puede dejar cosas implícitas
(`type: sequential` en vez de escribir cada `needs`), y la que se **publica** con
`agentctl export` las deja todas escritas. Mismo `kind`, mismo esquema.

Las capas de configuración, de menor a mayor prioridad:

```
configs/defaults.yaml              -> toda la flota
configs/environments/<env>.yaml    -> ese entorno
catalog/agents/<dominio>/<nombre>/agent.yaml -> lo que pide el agente
configs/environments/<env>.yaml    -> agents.<nombre>, un retoque puntual
```


---

## `kind: Agent`

### `AgentManifest`

Un agente. Es la unidad que se ejecuta y la que se referencia desde un flujo.

| campo | tipo | por defecto | qué hace |
|---|---|---|---|
| `apiVersion` | `string` | `agents.platform/v1` |  |
| `kind` | `Agent` | `Agent` |  |
| `metadata` | [`Metadata`](#metadata) | **obligatorio** |  |
| `spec` | [`AgentBody`](#agentbody) | — |  |

### `Metadata`

Quién es este manifiesto. El `name` es la referencia que se usa en todas partes.

| campo | tipo | por defecto | qué hace |
|---|---|---|---|
| `name` | `string` | **obligatorio** | Referencia con la que se le llama desde todas partes. Minúsculas, dígitos y guiones. |
| `version` | `string` | `0.1.0` | SemVer. Es lo que se pinnea al publicar el manifiesto. |
| `description` | `string` | — | Una línea: qué hace y cuándo usarlo. |
| `owner` | `string` | `unassigned` | Equipo responsable. Aparece como label al publicar. |
| `tags` | lista de `string` | — | Etiquetas libres para buscar y agrupar. |
| `labels` | mapa de `string` | — | Metadatos clave/valor para quien consuma el manifiesto. |

### `AgentBody`

Todo lo que se puede cambiar de un agente sin tocar código.

| campo | tipo | por defecto | qué hace |
|---|---|---|---|
| `runtime` | `string` | — | Framework que lo ejecuta: adk, langgraph o langchain. Vacío, se aplica el de configs/defaults.yaml. |
| `model` | [`ModelSpec`](#modelspec) | — | Qué modelo responde y con qué ajustes. |
| `prompt` | [`PromptSpec`](#promptspec) | — | Las instrucciones del agente. |
| `tools` | lista de [`ToolRef`](#toolref) | — | Herramientas que puede llamar. |
| `skills` | lista de [`SkillRef`](#skillref) | — | Skills del catálogo. Sólo su descripción viaja en el prompt; el cuerpo lo pide el agente con `skill.read`. |
| `sub_agents` | lista de [`SubAgentRef`](#subagentref) | — | Agentes a los que puede delegar. |
| `guardrails` | [`GuardrailsSpec`](#guardrailsspec) | — | Qué se comprueba antes y después del modelo. |
| `policies` | [`PolicySpec`](#policyspec) | — | Cuánto trabajo puede hacer una invocación. |
| `permissions` | [`PermissionSpec`](#permissionspec) | — | Qué puede alcanzar. Se comprueba al construir y al llamar. |
| `plugins` | lista de [`PluginRef`](#pluginref) | — | Plugins extra, más allá de los derivados de lo anterior. |
| `output_key` | `string` | — | Nombre con el que su respuesta queda en el estado compartido, para que otro paso la lea. |

### `ModelSpec`

Qué modelo responde y con qué ajustes de generación.

| campo | tipo | por defecto | qué hace |
|---|---|---|---|
| `profile` | `string` | — | Perfil de configs/models.yaml del que se hereda. Lo que se ponga aquí explícito gana. |
| `name` | `string` | — | Modelo concreto. Déjalo vacío salvo que tengas un motivo: el perfil existe para no atarse a uno. |
| `temperature` | `number` | — | Cuánto se aparta el modelo de la respuesta más probable. |
| `top_p` | `number` | — | Muestreo por núcleo. Lo soportan los tres runtimes. |
| `top_k` | `integer` | — | Muestreo por k. Gemini lo tiene; OpenAI no. Un runtime que no lo entienda lo ignora avisando. |
| `max_output_tokens` | `integer` | — | Techo de tokens de la respuesta. |
| `stop_sequences` | lista de `string` | — | Cadenas que cortan la generación. No todos los proveedores las aplican igual. |

### `PromptSpec`

Las instrucciones del agente: en línea o en un fichero aparte.

| campo | tipo | por defecto | qué hace |
|---|---|---|---|
| `instruction` | `string` | — | Las instrucciones, en línea. Excluyente con `file`. |
| `file` | `string` | — | Ruta a un .md junto al manifiesto. Al resolver, su contenido pasa a `instruction`. |
| `global_instruction` | `string` | — | Instrucción que también heredan los sub-agentes. Sólo la aplica el runtime adk. |
| `variables` | mapa de `string` | — | Valores que sustituyen los `{{ nombre }}` del prompt. |

### `ToolRef`

Una herramienta registrada que el agente puede llamar.

| campo | tipo | por defecto | qué hace |
|---|---|---|---|
| `ref` | `string` | **obligatorio** | Referencia registrada, p. ej. `health.calculate_bmi`. Mírales el nombre con `agentctl components`. |
| `alias` | `string` | — | Otro nombre con el que el modelo verá la herramienta. |
| `enabled` | `boolean` | `True` | Ponlo a false en un overlay de entorno para quitarla sin tocar el manifiesto. |
| `params` | mapa | — | Parámetros fijos para la herramienta. |

### `SkillRef`

Una skill del catálogo. Sólo su descripción viaja en el prompt; el cuerpo lo pide el agente.

| campo | tipo | por defecto | qué hace |
|---|---|---|---|
| `ref` | `string` | **obligatorio** | `nombre` o `nombre@rango`, p. ej. `hexagonal-architecture@^1.0`. |
| `enabled` | `boolean` | `True` | Permite desengancharla por entorno. |

### `SubAgentRef`

Cómo se engancha otro agente a este.

| campo | tipo | por defecto | qué hace |
|---|---|---|---|
| `ref` | `string` | **obligatorio** | Nombre del agente delegado. Al publicar se pinnea a `nombre@X.Y.Z`. |
| `mode` | `tool` \| `transfer` | `tool` | `tool`: el coordinador manda siempre. `transfer`: el turno pasa al hijo — sólo existe en adk. |
| `alias` | `string` | — | Nombre con el que el coordinador ve al delegado. |
| `description` | `string` | — | Cuándo debe delegar el coordinador. Es lo que lee el modelo para decidir. |
| `enabled` | `boolean` | `True` | Permite desactivar la delegación por entorno. |

### `GuardrailsSpec`

Guardrails agrupados por el momento en que se aplican.

| campo | tipo | por defecto | qué hace |
|---|---|---|---|
| `profile` | `string` | — |  |
| `input` | lista de [`GuardrailRule`](#guardrailrule) | — |  |
| `output` | lista de [`GuardrailRule`](#guardrailrule) | — |  |
| `tools` | lista de [`GuardrailRule`](#guardrailrule) | — |  |

### `PolicySpec`

Cuánto trabajo puede hacer una invocación. Lo aplica el runtime, no se le pide al modelo.

| campo | tipo | por defecto | qué hace |
|---|---|---|---|
| `profile` | `string` | — | Perfil de configs/policies.yaml del que se hereda. |
| `max_tool_calls` | `integer` | — | Techo de llamadas a herramienta por invocación. |
| `max_llm_calls` | `integer` | — | Techo de llamadas al modelo por invocación. |
| `timeout_seconds` | `number` | — | Declarado y validado; todavía no lo aplica ningún runtime. |
| `retry_attempts` | `integer` | `0` | Reintentos. Es el único límite que cruza al orquestador, como `retries` de cada paso. |
| `budget` | [`BudgetSpec`](#budgetspec) | — | Techos de coste de una invocación. |

### `PermissionSpec`

Qué puede alcanzar. Se comprueba al construir y otra vez al llamar.

| campo | tipo | por defecto | qué hace |
|---|---|---|---|
| `profile` | `string` | — | Perfil de configs/permissions.yaml del que se hereda. |
| `tools` | [`AllowDeny`](#allowdeny) | — | Qué herramientas puede alcanzar. |
| `agents` | [`AllowDeny`](#allowdeny) | — | A qué agentes puede delegar. Lista distinta de la de herramientas, a propósito. |

### `PluginRef`

Un plugin extra, más allá de los que se derivan de las secciones anteriores.

| campo | tipo | por defecto | qué hace |
|---|---|---|---|
| `ref` | `string` | **obligatorio** | Plugin registrado, más allá de los que salen de guardrails/permisos/política. |
| `enabled` | `boolean` | `True` | Permite desactivarlo por entorno. |
| `config` | mapa | — | Configuración que recibe el plugin. |

### `GuardrailRule`

Una comprobación sobre un texto.

| campo | tipo | por defecto | qué hace |
|---|---|---|---|
| `name` | `string` | **obligatorio** | Nombre de la regla. Aparece en la traza cuando salta. |
| `type` | `regex_deny` \| `keywords_deny` \| `max_chars` \| `pii_redact` | **obligatorio** | Qué comprueba. Un tipo nuevo es código; una regla nueva es configuración. |
| `action` | `block` \| `redact` \| `warn` | `block` | `block` corta, `redact` reescribe y sigue, `warn` sólo deja constancia. |
| `message` | `string` | — | Qué se responde cuando bloquea. |
| `params` | mapa | — | Parámetros del tipo de regla (`keywords`, `patterns`, `limit`...). |

### `BudgetSpec`

Techos de coste de una invocación.

| campo | tipo | por defecto | qué hace |
|---|---|---|---|
| `max_tokens` | `integer` | — | Techo de tokens de una invocación. |
| `max_usd` | `number` | — | Declarado, todavía no contabilizado: hoy el corte se hace por tokens. |

### `AllowDeny`

Listas de patrones. `deny` gana siempre sobre `allow`.

| campo | tipo | por defecto | qué hace |
|---|---|---|---|
| `allow` | lista de `string` | — | Patrones permitidos, p. ej. `["health.*"]`. |
| `deny` | lista de `string` | — | Patrones prohibidos. `deny` gana siempre sobre `allow`. |


---

## `kind: Workflow`

### `WorkflowManifest`

Un flujo: varios agentes compuestos en una tubería determinista.

| campo | tipo | por defecto | qué hace |
|---|---|---|---|
| `apiVersion` | `string` | `agents.platform/v1` |  |
| `kind` | `Workflow` | `Workflow` |  |
| `metadata` | [`Metadata`](#metadata) | **obligatorio** |  |
| `spec` | [`WorkflowBody`](#workflowbody) | — |  |

### `WorkflowBody`

La forma del flujo y lo que se aplica a todos sus pasos.

| campo | tipo | por defecto | qué hace |
|---|---|---|---|
| `type` | `sequential` \| `parallel` \| `loop` \| `graph` | `sequential` | Forma del flujo: `sequential` en línea, `parallel` en abanico, `loop` repitiendo, `graph` con las aristas escritas a mano. |
| `runtime` | `string` | — | Framework que lo ejecuta. Ojo: LCEL no sabe de grafos ni bucles, así que `graph` y `loop` sólo corren en adk o langgraph. |
| `nodes` | lista de [`NodeSpec`](#nodespec) | — | Los pasos, en orden de declaración. |
| `edges` | lista de [`EdgeSpec`](#edgespec) | — | Sólo para `type: graph`: la topología, arista a arista. |
| `max_iterations` | `integer` | — | Sólo para `type: loop`: cuántas vueltas como mucho. |
| `inputs` | lista de [`InputSpec`](#inputspec) | — | Parámetros de entrada, referenciados como `{{ inputs.nombre }}`. |
| `eval` | [`EvalSpec`](#evalspec) | — | Puerta de calidad sobre el resultado del flujo. |
| `guardrails` | [`GuardrailsSpec`](#guardrailsspec) | — | Guardrails de todo el flujo, además de los de cada agente. |
| `policies` | [`PolicySpec`](#policyspec) | — | Límites operativos del flujo. |
| `permissions` | [`PermissionSpec`](#permissionspec) | — | Qué agentes puede componer este flujo. |
| `plugins` | lista de [`PluginRef`](#pluginref) | — | Plugins extra a nivel de flujo. |

### `NodeSpec`

Un paso del flujo: un agente con un nombre dentro de la tubería.

| campo | tipo | por defecto | qué hace |
|---|---|---|---|
| `name` | `string` | **obligatorio** | Nombre del paso dentro del flujo. Único. |
| `agent` | `string` | **obligatorio** | Agente que lo ejecuta. Al publicar se pinnea a `nombre@X.Y.Z`. |
| `description` | `string` | — | Qué aporta este paso. |
| `needs` | lista de `string` | — | Pasos que deben terminar antes. Normalmente se deja vacío y se deduce de `type`; la forma publicada siempre lo trae escrito. |
| `retries` | `integer` | — | Reintentos del paso. Reintentar es cosa de quien orquesta, por eso este límite viaja con el paso y el resto de `policies` no. |
| `with` | mapa de `string` | — | De dónde lee cada parámetro: `{{ inputs.x }}` o `{{ steps.y.output }}`. Vacío, cada runtime pasa el estado como sepa. |

### `EdgeSpec`

Una arista dirigida entre dos pasos.

| campo | tipo | por defecto | qué hace |
|---|---|---|---|
| `from` | `string` | **obligatorio** | Nodo origen, o `START` para una entrada del flujo. |
| `to` | `string` | **obligatorio** | Nodo destino. |

### `InputSpec`

Un parámetro de entrada del flujo.

| campo | tipo | por defecto | qué hace |
|---|---|---|---|
| `name` | `string` | **obligatorio** | Identificador, referenciado como `{{ inputs.nombre }}`. |
| `description` | `string` | — | Qué se espera en este parámetro. |
| `default` | `string` | — | Valor si no se pasa ninguno. |

### `EvalSpec`

Puerta de calidad sobre el resultado del flujo.

| campo | tipo | por defecto | qué hace |
|---|---|---|---|
| `metric` | `string` | **obligatorio** | Métrica que decide, p. ej. `pass_at_1`. |
| `threshold` | `number` | **obligatorio** | Dónde está la línea. |
| `goal` | `maximize` \| `minimize` | `maximize` | De qué lado de la línea hay que estar. |
