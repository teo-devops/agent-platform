# Agent Platform

Un marco de referencia para desarrollar agentes **una vez** y ejecutarlos donde
haga falta: en tu portátil con el framework que prefieras, o en Kubernetes con
kagent, siempre con la misma observabilidad.

- **Un manifiesto, tres frameworks.** Cada agente es un `agent.yaml`
  (`agents.platform/v1`). ADK, LangGraph o LangChain lo construyen; se elige con
  una línea (`spec.runtime`) o un flag (`--runtime`).
- **Tools por MCP, agentes por A2A.** Las funciones de `catalog/tools/` se
  publican como servidor MCP; los agentes desplegados hablan entre sí por A2A.
- **kagent como runtime.** Los CRDs de kagent se **generan** desde los
  manifiestos: agentes declarativos (sólo YAML) o BYO (nuestro runtime dentro de
  kagent).
- **MLflow como backend de AgentOps.** Trazas por OpenTelemetry, Prompt Registry,
  una versión registrada por cada `nombre@versión` de agente, evals y métricas.

La regla que sostiene todo: **cambiar un agente nunca debería requerir un release
de la plataforma**. Si para cambiar un prompt, un modelo o un permiso hay que
tocar Python, el diseño ha fallado.

Todo el catálogo cuenta **una sola historia: la de una organización que hace
producto tecnológico**. Su equipo de ingeniería escribe, revisa, ejecuta y
versiona código; su equipo de tecnología evalúa y explica tecnologías; su equipo
de medios lo publica en el blog; y colabora con otras organizaciones por A2A. La
demo principal es la de ingeniería: un jefe de desarrollo (`software-manager`)
recibe un requisito, lo delega en un desarrollador (`python-developer`) y pasa el
resultado a un revisor (`code-reviewer`) que fundamenta sus hallazgos con
análisis estático servido por MCP.

> ¿Primera vez? Cuatro comandos:
>
> ```bash
> make install && cp .env.example .env   # y pon tu GOOGLE_API_KEY
> make doctor                            # ¿falta algo?
> make casos                             # el menú de casos de uso; make caso-1 para empezar
> make status                            # qué está levantado y cómo levantar lo que no
> ```
>
> `make help` es la misma guía en la terminal. Después, los diagramas de
> [Arquitectura](#arquitectura) y [Explora los casos de uso](#explora-los-casos-de-uso),
> que no necesita clúster. Para entender el porqué: [`docs/concepts.md`](docs/concepts.md)
> (framework vs runtime vs protocolo, con el diagrama del flujo). Para presentarlo:
> el guion de [`docs/demo.md`](docs/demo.md).

---

## Arquitectura

La idea central cabe en una frase: **cada agente es sólo un `agent.yaml` y un
`prompt.md`**. Al arrancar, la plataforma lee ese manifiesto y construye con él un
agente del framework que toque —ADK, LangGraph o LangChain—. Es **el mismo YAML
para los tres**; sólo cambia el *builder* que lo traduce. Ningún agente del
catálogo tiene una línea de Python.

Los diagramas van de lo general a lo concreto. El detalle de cada paquete está en
[`docs/architecture.md`](docs/architecture.md).

### 1. El mapa completo

Qué se escribe (izquierda), quién lo convierte en algo ejecutable (centro) y
dónde acaba corriendo y observándose (derecha).

```mermaid
flowchart LR
    subgraph ESCRIBES["Lo que escribes — catalog/ y configs/"]
        direction TB
        AG["catalog/agents/‹dominio›/‹nombre›/<br/>agent.yaml + prompt.md"]
        WF["catalog/workflows/*.yaml"]
        TL["catalog/tools/*.py<br/>funciones sueltas"]
        SK["catalog/skills/‹nombre›/SKILL.md"]
        CF["configs/<br/>defaults · models · guardrails<br/>permissions · policies · environments/"]
    end

    subgraph PLATAFORMA["La plataforma — platform/"]
        direction TB
        CORE["agent-core<br/>esquemas · capas de config · registros"]
        FAC["agent-runtime<br/>agentctl + AgentFactory"]
        subgraph RT["runtimes/ — un builder por framework"]
            ADK["agent-runtime-adk"]
            LG["agent-runtime-langgraph"]
            LC["agent-runtime-langchain"]
        end
        MCP["agent-mcp"]
        A2A["agent-a2a"]
        KAG["agent-kagent"]
        MLF["agent-mlflow"]
    end

    subgraph CORRE["Dónde corre"]
        direction TB
        LOCAL["Carril local<br/>agentctl run · ADK Dev UI · LangGraph Studio"]
        PROC["Carril A2A local<br/>un proceso por agente :9101-9103"]
        K8S["Carril clúster<br/>kind + kagent"]
    end

    OBS[("MLflow<br/>trazas · prompts · versiones · evals")]

    AG & WF & SK & CF --> CORE
    TL --> CORE
    CORE --> FAC
    FAC --> ADK & LG & LC
    ADK & LG & LC --> LOCAL
    A2A --> PROC
    KAG --> K8S
    MCP --> K8S
    LOCAL & PROC & K8S -. OpenTelemetry .-> OBS
    MLF --> OBS
```

### 2. Un manifiesto, tres frameworks

El recorrido de `python-developer` desde el disco hasta un objeto del framework.

```mermaid
flowchart TD
    Y["agent.yaml<br/>(agents.platform/v1)"] --> L
    P["prompt.md"] --> L

    subgraph L["1 · Carga y mezcla de capas — agent_core/config/store.py"]
        direction LR
        D["configs/defaults.yaml"] --> A["agent.yaml"] --> E["configs/environments/‹env›.yaml"]
    end

    L --> R["2 · Resolución de referencias"]
    R --> R1["model.profile: precise<br/>→ configs/models.yaml → gemini-2.5-flash, temp 0.1"]
    R --> R2["tools: code.check_syntax<br/>→ catalog/tools/code.py :: check_syntax"]
    R --> R3["skills: hexagonal-architecture@^1.0<br/>→ catalog/skills/"]
    R --> R4["permissions / guardrails / policies<br/>→ perfiles de configs/"]

    R1 & R2 & R3 & R4 --> M["AgentManifest validado<br/>(pydantic, neutro: sin conceptos de ningún framework)"]

    M --> Q{"3 · ¿Qué runtime?<br/>--runtime  ›  spec.runtime  ›  agentDefaults.runtime"}

    Q -->|adk| B1["builder agent:adk"]
    Q -->|langgraph| B2["builder agent:langgraph"]
    Q -->|langchain| B3["builder agent:langchain"]

    B1 --> O1["LlmAgent<br/>+ plugins de enforcement"]
    B2 --> O2["create_react_agent<br/>+ pre/post_model_hook"]
    B3 --> O3["create_agent<br/>+ middleware"]
```

La precedencia del runtime es la misma que la de cualquier otro ajuste: el flag
del CLI gana al manifiesto, y el manifiesto a los valores de la flota. Hoy
`configs/defaults.yaml` dice `runtime: adk`.

### 3. Qué se convierte en qué

Cada campo del manifiesto tiene su equivalente en los tres frameworks. Esta tabla
es, literalmente, lo que hacen los tres `builder.py`.

| En el `agent.yaml` | ADK | LangGraph | LangChain |
|---|---|---|---|
| `prompt` (+ índice de skills) | `LlmAgent(instruction=)` | `create_react_agent(prompt=)` | `create_agent(system_prompt=)` |
| `model.profile` | nombre del modelo + `generate_content_config` | chat model de LangChain | chat model de LangChain |
| `tools: [code.check_syntax]` | `FunctionTool` | `StructuredTool` | `StructuredTool` |
| `skills` | dos `FunctionTool` que sirven el `SKILL.md` | dos `StructuredTool` | dos `StructuredTool` |
| `sub_agents` · `mode: tool` | `AgentTool(hijo)` | tool que llama a `hijo.invoke()` | tool que llama a `hijo.invoke()` |
| `sub_agents` · otro modo | `sub_agents=[…]` (cede el turno) | ❌ error explicado | ❌ error explicado |
| `guardrails` · `permissions` · `policies` | plugins de ADK | `pre_model_hook` / `post_model_hook` | middleware |
| `kind: Workflow` | `LoopAgent` (loop) · `Workflow` con aristas (el resto) | `StateGraph` | LCEL: secuencia o `RunnableParallel` (sin bucles ni DAG) |

### 4. Anatomía de un agente

Todo lo que aparece en un `agent.yaml` es una **referencia por nombre** a algo
que vive en otro sitio. Por eso cambiar un modelo, un permiso o una tool no
requiere tocar Python.

```mermaid
flowchart LR
    subgraph M["catalog/agents/engineering/python-developer/agent.yaml"]
        direction TB
        m1["metadata: name, version 0.2.0, owner"]
        m2["spec.model.profile: precise"]
        m3["spec.prompt.file: prompt.md"]
        m4["spec.tools: code.check_syntax"]
        m5["spec.skills: hexagonal-architecture@^1.0"]
        m6["spec.permissions.tools.allow"]
        m7["spec.sub_agents (en software-manager)"]
    end

    m2 --> c1["configs/models.yaml<br/>profiles.precise"]
    m3 --> c2["prompt.md<br/>(al lado del yaml)"]
    m4 --> c3["catalog/tools/code.py<br/>def check_syntax(code) -> dict"]
    m5 --> c4["catalog/skills/hexagonal-architecture/SKILL.md"]
    m6 --> c5["configs/permissions.yaml<br/>+ reglas del propio agente"]
    m7 --> c6["otro agent.yaml del catálogo<br/>(se construye de forma recursiva)"]
    m1 --> c7["MLflow: LoggedModel<br/>python-developer@0.2.0"]
```

Una tool es una función con type hints y docstring: el registro las descubre
solas al arrancar (`agent_runtime/context.py`), y la firma **es** el esquema que
ve el modelo. Soltar un `.py` en `catalog/tools/` basta para publicarla.

### 5. Cómo se enchufan los paquetes

Nadie importa a nadie por nombre. Cada paquete se anuncia por *entry points* en
su `pyproject.toml`, así que **instalar un paquete es lo que hace que su
capacidad exista**. Por eso añadir un cuarto framework sería un paquete nuevo, no
un cambio en la fábrica.

```mermaid
flowchart BT
    CORE["agent-core<br/>esquemas · config · registros · telemetry<br/>(sin frameworks)"]
    RUN["agent-runtime<br/>agentctl · AgentFactory · playgrounds"]

    ADK["agent-runtime-adk"]
    LG["agent-runtime-langgraph"]
    LC["agent-runtime-langchain"]
    MCP["agent-mcp"]
    A2A["agent-a2a"]
    KAG["agent-kagent"]
    MLF["agent-mlflow<br/>(el único que importa mlflow)"]

    RUN --> CORE
    ADK & LG & LC & MCP & A2A & KAG & MLF --> RUN

    ADK -. "builders agent:adk · workflow:adk<br/>runtimes · plugins" .-> RUN
    LG -. "builders · runtimes · instrumentors" .-> RUN
    LC -. "builders · runtimes · instrumentors" .-> RUN
    A2A -. "transports: a2a · commands" .-> RUN
    MCP -. "commands: mcp" .-> RUN
    KAG -. "commands: kagent" .-> RUN
    MLF -. "commands: mlflow · eval_sinks" .-> RUN
```

Las flechas sólidas son dependencias de instalación; las punteadas, lo que la
fábrica y `agentctl` descubren en tiempo de ejecución.

### 6. Delegación: el sub-agente no sabe dónde vive el otro

`software-manager` declara `sub_agents: [python-developer, code-reviewer]` con
`mode: tool`. El manifiesto es el mismo en los tres carriles; lo que cambia es lo
que `factory.remote()` responde al construirlo.

```mermaid
flowchart TD
    SM["software-manager<br/>sub_agents: python-developer, code-reviewer"] --> F{"factory.remote(hijo)<br/>¿el entorno dice que vive fuera?"}

    F -->|"None — agentctl run"| IN["Se construye en el mismo proceso<br/>y se envuelve como tool"]
    F -->|"URL — --env local-a2a<br/>o AGENT_A2A_ENDPOINTS"| RM["A2ADelegate → tool con el mismo nombre<br/>message/send por HTTP a :9101 / :9102"]
    F -->|"kagent"| KG["Tool de tipo Agent en el CRD<br/>A2A a través del controlador de kagent"]

    IN & RM & KG --> SAME["Para el modelo del coordinador es idéntico:<br/>mismo nombre de tool, misma descripción,<br/>mismos permisos, una sola traza (traceparent)"]
```

```mermaid
sequenceDiagram
    autonumber
    actor U as Usuario
    participant SM as software-manager
    participant PD as python-developer
    participant CR as code-reviewer
    participant T as catalog/tools (code.*)

    U->>SM: "Una función que calcule la mediana"
    SM->>PD: tool python_developer(request)
    Note over SM,PD: en proceso · A2A local · A2A vía kagent
    PD->>T: code.check_syntax(code)
    T-->>PD: {valid: true}
    PD-->>SM: código + docstring
    SM->>CR: tool code_reviewer(código)
    CR->>T: code.metrics(code)
    T-->>CR: complejidad, longitud, tipos
    CR-->>SM: hallazgos concretos
    SM-->>U: código revisado
```

### 7. El carril clúster: de manifiesto a pods

`agentctl kagent render` traduce los mismos manifiestos a CRDs de kagent según
[`deploy/kagent/release.yaml`](deploy/kagent/release.yaml), que decide **dónde y
cómo** corre cada agente. El `agent.yaml` no sabe que existe kagent.

```mermaid
flowchart LR
    subgraph REPO["Repositorio"]
        AY["catalog/agents/*/agent.yaml"]
        REL["deploy/kagent/release.yaml<br/>qué agentes · qué modo"]
        TOOLS["catalog/tools/*.py"]
        SKL["catalog/skills/*"]
    end

    AY & REL --> RENDER["agentctl kagent render"]
    RENDER --> DIST[".agent-platform/dist/kagent/*.yaml<br/>Agent · ModelConfig · RemoteMCPServer"]

    TOOLS --> IMG_MCP["imagen mcp"]
    SKL --> IMG_SK["imágenes OCI de skills"]
    IMG_MCP & IMG_SK --> REG[("registro local<br/>localhost:5001")]

    subgraph KIND["kind · agent-lab"]
        subgraph NS_K["ns kagent"]
            CTRL["kagent-controller<br/>A2A para todos los agentes"]
            SMP["software-manager<br/>Declarative — lo ejecuta kagent"]
            CRP["code-reviewer<br/>Declarative + skill OCI"]
            PDP["python-developer<br/>BYO — agentctl kagent host (LangGraph)"]
            MCPS["catalog-tools<br/>servidor MCP"]
            UI["kagent UI :8082"]
        end
        subgraph NS_O["ns observability"]
            OTEL["OTel Collector :4317"]
            MLS["MLflow :5500"]
            SEAWEED[("SeaweedFS :9901")]
        end
    end

    DIST -->|kubectl apply| CTRL
    REG --> PDP & MCPS & CRP
    SMP -->|A2A| CTRL
    CTRL -->|A2A| PDP & CRP
    CRP -->|MCP code.*| MCPS
    SMP & CRP & PDP -. trazas .-> OTEL
    OTEL --> MLS --> SEAWEED
```

| Modo | Quién ejecuta el agente | Lo que aprovecha | Límite |
|---|---|---|---|
| **Declarative** | el motor de kagent | sólo YAML, UI y A2A gratis | no sabe expresar guardrails, políticas ni temperatura (se avisa al renderizar) |
| **BYO** | nuestro runtime en un pod (`agentctl kagent host`) | todo el manifiesto, con enforcement | necesita la imagen `agent-host` |

### 8. Observabilidad: la misma traza en los tres carriles

```mermaid
flowchart LR
    subgraph L["Carril local"]
        LA["agentctl run / dev-adk / dev-langgraph<br/>(OTEL_EXPORTER_OTLP_TRACES_ENDPOINT)"]
    end
    subgraph C["Carril clúster"]
        CA["pods de kagent"] --> COL["OTel Collector"]
    end

    LA -->|"OTLP/HTTP directo"| ML[("MLflow :5500<br/>experimento agent-platform")]
    COL -->|OTLP| ML

    CLI["agentctl mlflow<br/>prompts · register · sync · metrics"] --> ML
    EV["agentctl eval --sink mlflow"] --> ML
```

MLflow escucha en `localhost:5500` en los dos carriles: el del clúster por
NodePort o, sin clúster, `make mlflow-local`. Nunca los dos a la vez; el Makefile
y `cluster-up.sh` lo comprueban antes de arrancar.

### 9. Carriles y puertos

Cada servicio, su puerto y cómo se levanta están en un solo sitio,
[`deploy/services.yaml`](deploy/services.yaml): de ahí salen `make status` y la
tabla de [Las UIs](#las-uis). Los puertos de los agentes A2A, en
[`configs/environments/local-a2a.yaml`](configs/environments/local-a2a.yaml):
`agentctl a2a serve` escucha en el puerto que dice ese fichero, así que el
coordinador nunca llama a un agente por otro.

Los carriles local y clúster no comparten puertos salvo el 5500 (MLflow), que es a
propósito. Todo lo que habla con Kubernetes va contra el contexto
`kind-agent-lab`, nunca contra el contexto activo de `kubectl`.

---

## El catálogo

Cada agente es una carpeta: su manifiesto, su prompt y, si se mide, su suite de
evals. **Una ruta por agente**; no hay un segundo árbol con los mismos nombres.

```text
catalog/agents/engineering/release-manager/
├── agent.yaml      qué es: modelo, tools, permisos, límites
├── prompt.md       qué instrucciones lleva
└── evals/          cómo se sabe que funciona (agentctl eval release-manager)
    ├── dataset.yaml
    └── judges.yaml
```

<!-- BEGIN GENERADO: catálogo (make docs, desde los agent.yaml y catalog/cases.yaml) -->
| Dominio | Agente | Para qué es | Usa | Casos |
|---|---|---|---|---|
| dataspace | `data-consumer` | Organización B. Busca datos en la organización A y comprueba si su política permite el uso que se pide. | delega en `data-provider` | 8 |
| dataspace | `data-provider` | Organización A. Ofrece sus datasets y la política de uso de cada uno. | `dataspace.*` | 8 |
| engineering | `code-reviewer` | Revisa código Python con análisis estático; informa de bugs, smells y riesgos. | `code.*` · skill `hexagonal-architecture` | 3, 6, 7, 9 |
| engineering | `python-developer` | Escribe funciones Python limpias, tipadas y documentadas a partir de un requisito. | `code.*` · skill `hexagonal-architecture` | 3, 6, 7, 9 |
| engineering | `python-executor` | Escribe código Python y lo EJECUTA en un sandbox aislado, con sus tests, antes de responder. | `code.*` · sandbox | 10 |
| engineering | `release-manager` | A partir de los commits desde la última versión, decide la siguiente (semver) y redacta las notas de release. | `release.*`, `time.*` | 2 |
| engineering | `software-manager` | Coordina a un desarrollador y a un revisor para entregar código Python revisado. | delega en `python-developer`, `code-reviewer` | 3, 7, 9 |
| media | `tech-writer` | Convierte notas técnicas en un artículo para el blog de ingeniería, legible y sin perder rigor. | `text.*` | 4 |
| platform | `eval-judge` | Juez de las evals — decide si una respuesta cumple un criterio y dice por qué. Interno de la plataforma. | — | — |
| technology | `tech-explainer` | Explica un concepto técnico en lenguaje claro, en tres frases, para quien no es especialista. | — | 1, 5 |
| technology | `tech-researcher` | Prepara notas técnicas sobre una tecnología — qué es, alternativas, riesgos y preguntas abiertas — para quien tiene que decidir o escribir. | — | 4, 5 |
| workflow · loop | `review-loop` | Bucle desarrollador ↔ revisor — escribe, revisa y corrige hasta agotar las vueltas. | `python-developer` → `code-reviewer` | 6 |
| workflow · sequential | `tech-article` | De un tema a un artículo para el blog de ingeniería. El orden lo fija el YAML, no el modelo. | `tech-researcher` → `tech-writer` | 4 |
| workflow · parallel | `tech-briefing` | Una tecnología, dos audiencias a la vez — notas para el equipo técnico y una explicación para dirección. | `tech-researcher` → `tech-explainer` | 5 |
<!-- END GENERADO: catálogo -->

`make catalog` (o `agentctl catalog`) enseña lo mismo en la terminal, con la
skill, el sandbox y el comando para probar cada agente.

Todos tienen su suite en `evals/` (`make eval` la valida; un test impide añadir
un agente sin ella). Y tres workflows que componen esos mismos agentes: `tech-article` (investigar →
redactar), `tech-briefing` (una tecnología, dos audiencias en paralelo) y
`review-loop` (desarrollador ↔ revisor). Un agente no sabe si corre suelto o
como paso de un flujo.

## Explora los casos de uso

```bash
make install                   # .venv con todos los paquetes
cp .env.example .env           # pon tu GOOGLE_API_KEY
make doctor                    # comprueba que no falta nada
make casos                     # el menú: qué caso es cada número
make caso-3                    # y a jugar
```

Los casos viven en [`catalog/cases.yaml`](catalog/cases.yaml): agente, mensaje de
ejemplo, entorno, lo que necesitan antes y dónde verlos. Añadir uno es una entrada
ahí y `make docs`; ni el Makefile ni esta tabla se tocan a mano.

Cada caso añade **una** forma de colaborar a la anterior. Todos narran en la
terminal el trabajo que la respuesta final esconde: quién delega en quién, qué
tools llama cada uno y qué viaja por A2A.

<!-- BEGIN GENERADO: casos (make docs, desde catalog/cases.yaml) -->
| # | Pruébalo | Qué colaboración ves | Míralo también en una UI |
|---|---|---|---|
| 1 | `make caso-1` | `tech-explainer`: ninguna, un modelo con instrucciones | `make dev-adk AGENT=tech-explainer` |
| 2 | `make caso-2` | `release-manager`: un agente que llama a **tools** (código Python): la versión la calcula una función, no el modelo | `make dev-adk AGENT=release-manager` (pestaña Events) |
| 3 | `make caso-3` | `software-manager`: **delegación decidida por el modelo**. El jefe llama a `python-developer` y a `code-reviewer`, y si la revisión encuentra un fallo, vuelve al desarrollador | `make dev-adk AGENT=software-manager` (Events) |
| 4 | `make caso-4` | `tech-article`: **flujo secuencial**, investigar y redactar. El orden lo fija el YAML, no el modelo | `make dev-langgraph` (el grafo) |
| 5 | `make caso-5` | `tech-briefing`: **en paralelo**, una tecnología para dos audiencias (equipo y dirección) | `make dev-langgraph` (las dos ramas) |
| 6 | `make caso-6` | `review-loop`: **bucle** desarrollador ↔ revisor, dos vueltas | `make dev-langgraph` (el bucle) |
| 7 | `make caso-7` | El 3 por **A2A**: cada sub-agente en **su proceso y su framework** | `make a2a-up` (su terminal; o tail -f .agent-platform/a2a.log si los levantó make) |
| 8 | `make caso-8` | `data-consumer` → `data-provider`: **dos organizaciones** por A2A. B pregunta a A qué datos tiene y decide si su política permite el uso | `make a2a-up` (su terminal; o tail -f .agent-platform/a2a.log si los levantó make) |
| 9 | `make caso-9` | `software-manager` en **kagent**: A2A entre **pods**. El mensaje entra por el controlador de kagent | El [chat de `software-manager`](http://localhost:8082/agents/kagent/software-manager/chat) en kagent |
| 10 | `make caso-10` | `python-executor`: escribe el código y **lo ejecuta en un sandbox** antes de responder. El proveedor lo elige el entorno: `ENV=sandbox-sbx` (microVM de Docker Sandboxes) o `ENV=sandbox-openshell` (NVIDIA OpenShell); sin `ENV`, un contenedor local | `docker ps --filter label=agent-platform.sandbox=local` (mientras corre) |
<!-- END GENERADO: casos -->

Para jugar con cualquiera:

```bash
make caso-3 MSG="Una función que convierta grados Celsius a Fahrenheit"   # tu mensaje
make caso-3 RUNTIME=langgraph                                              # otro framework: adk | langgraph | langchain
make caso-8 MSG="Datos de movilidad en bicicleta para investigación"       # misma pregunta, otro propósito
```

Cada caso imprime primero el comando `agentctl` que ejecuta, así que de paso lo
aprendes (sin make: `agentctl case 3`). Para usar `agentctl` directamente, `source .venv/bin/activate` (sin eso,
`command not found`). En resumen: `make` para enseñar, `agentctl` para lo que
`make` no cubre (`show`, `validate`, `a2a send`...), y las UIs para verlo en pantalla.

**Lo que un caso necesita se monta solo.** El 7 y el 8 levantan en segundo plano
los sub-agentes A2A que no respondan (log en `.agent-platform/a2a.log`; se paran
con `make a2a-down`), el 9 abre el port-forward al controlador de kagent y el 10
construye la imagen del sandbox. `make status` dice qué quedó levantado. Para una demo, mejor verlos: `make a2a-up` en una terminal y
`make caso-7` en otra, una al lado de la otra.

El 3 y el 7 son el mismo agente y el mismo manifiesto. Así se ve el 7 (real,
recortado): el jefe corre en ADK, el desarrollador en LangGraph y el revisor en
LangChain, en otro proceso.

```text
▶ software-manager
  → delega en python-developer
    ⇄ A2A message/send → http://localhost:9101/
    ⇄ A2A message (8.8s)
  ← python-developer responde (8.8s): def validate_spanish_iban(iban: str) -> bool: …
  → delega en code-reviewer
    ⇄ A2A message/send → http://localhost:9102/
    ⇄ A2A message (17.8s)
  ← code-reviewer responde (17.8s): Hallazgos del análisis estático …
  → delega en python-developer          ← el jefe devuelve el bug que encontró el revisor
```

Y en la terminal de `make a2a-up`, lo que hace cada sub-agente al recibir la petición:

```text
⇠ A2A code-reviewer: def validate_spanish_iban(iban: str) -> bool: …
▶ code-reviewer
  · code_metrics(def validate_spanish_iban(…) = {"functions": [{"name": "validate_spanish_iban", …
  · code_find_smells(def validate_spanish_iban(…) = {"smells": []}
⇢ code-reviewer (17.8s): Hallazgos del análisis estático …
```

Para trastear:

- **Otro framework, mismo agente:** `agentctl --runtime langgraph run software-manager -v -m "..."`
  (`adk`, `langgraph` o `langchain`; `review-loop` no existe en LangChain, que no tiene bucles).
- **Otro reparto en A2A:** `make a2a-up A2A_AGENTS="python-developer:adk code-reviewer:langgraph"`.
- **Hablar con un agente A2A a mano:** `agentctl a2a card http://localhost:9101/` y
  `agentctl a2a send http://localhost:9101/ -m "Una función que sume dos enteros"`.
- **Tirar un sub-agente:** para `make a2a-up` a mitad de una petición. El jefe
  recibe el error como resultado de la tool y lo cuenta en su respuesta; no se cae.
- **Ver lo mismo en una UI:** `make dev-adk AGENT=software-manager` (pestaña *Events*),
  `make dev-langgraph` (el grafo) o las [trazas de MLflow](http://localhost:5500/#/experiments/0/traces)
  (`make mlflow-local` si no hay clúster).

### El caso más pequeño de A2A: dos organizaciones

`software-manager` enseña a delegar. `data-consumer` enseña **por qué A2A**: dos
organizaciones que no comparten código, ni modelo, ni datos. Solo se hablan.

| | Organización A · `data-provider` | Organización B · `data-consumer` |
|---|---|---|
| Qué tiene | Una tool, [`dataspace.search_datasets`](catalog/tools/dataspace.py): tres datasets, cada uno con su política de uso | Nada propio: ni datos ni tools |
| Qué hace | Responde qué ofrece sobre un tema, con la política tal cual | Pregunta a A y decide si la política permite el uso del usuario |
| Dónde corre | Su proceso, en LangGraph (`make a2a-up`, :9103) | El tuyo, en ADK (`make caso-8`) |

Prueba el mismo tema con dos propósitos. La respuesta cambia por la política de
A, no por el prompt de B:

```text
"Datos de movilidad en bicicleta para un producto comercial"  → No: commercial: false
"Datos de movilidad en bicicleta para investigación"          → Sí: purposes incluye research
"Datos de calidad del aire para una app comercial"            → Sí: commercial: true
```

En la terminal de B ves la pregunta salir por A2A. En la de A, la tool que llama
para contestar, que B no ve ni necesita ver:

```text
▶ data-consumer                                 ⇠ A2A data-provider: datos de movilidad en bicicleta
  → delega en data-provider                     ▶ data-provider
    ⇄ A2A message/send → http://localhost:9103/   · dataspace_search_datasets(bicicleta) = {"datasets": …
  ← data-provider responde (2.4s): …            ⇢ data-provider (2.3s): …
```

En un espacio de datos real, la tool de A sería el catálogo de su conector EDC y
la política, una oferta ODRL. La conversación entre los dos agentes no cambiaría.

### A2A: en proceso, entre procesos, entre pods

Dónde vive un sub-agente es una decisión de **despliegue**, no del agente. El
manifiesto de `software-manager` dice `sub_agents: [python-developer, code-reviewer]`
en los tres casos:

| Carril | Dónde vive cada sub-agente | Cómo viaja la delegación | Quién lo decide |
|---|---|---|---|
| `agentctl run` | En el mismo proceso | Llamada a una tool, en memoria | Nadie: es lo que pasa por defecto |
| `--env local-a2a` | En otro proceso (`make a2a-up`) | **A2A** `message/send` por HTTP | [`configs/environments/local-a2a.yaml`](configs/environments/local-a2a.yaml) (`a2a.endpoints`) o `AGENT_A2A_ENDPOINTS` |
| kagent | En otro pod | **A2A** a través del controlador de kagent | [`deploy/kagent/release.yaml`](deploy/kagent/release.yaml) |

En kagent, un coordinador **declarativo** delega con `tools[type=Agent]`. Uno **BYO**
recibe `AGENT_A2A_ENDPOINTS` de `agentctl kagent render`. En los dos casos cada
salto es A2A: nadie construye copias de los hijos dentro de su pod.

---

## Las UIs

`make status` dice, en vivo, qué está levantado: ✓ con su URL (y las credenciales,
si las tiene) o ✗ con el comando que lo levanta. `make ui-urls` añade las
sub-páginas de cada UI: las trazas, los prompts o el chat de cada agente.
`make down` para todo lo que los `make` dejaron corriendo en local; el clúster no
se toca.

```text
Local — sin clúster
  ✓ ADK Dev UI             http://localhost:8000/dev-ui/                parar: make down
  ✗ LangGraph Studio       —                                            make dev-langgraph · make dev-langchain
  ✓ Agentes A2A            8/8 responden  :9101-9108                    make a2a-cards · parar: make a2a-down
  ✓ Langflow               http://127.0.0.1:7860                        admin / la clave de make langflow-url
  ✓ MLflow                 http://localhost:5500                        no lo levantó make: otra terminal o el clúster

Clúster — kind-agent-lab  lo gestiona helm (make lab)
  ✓ kagent                 http://localhost:8082                        3/3 agentes Ready
  ✗ A2A de kagent          desplegado, pero no responde                 make kagent-a2a
```

<!-- BEGIN GENERADO: uis (make docs, desde deploy/services.yaml) -->
| UI | URL | Se levanta con | Para qué |
|---|---|---|---|
| **ADK Dev UI** | http://localhost:8000/dev-ui/ | `make dev-adk` | Playground de ADK, 100 % local: todo el catálogo en el desplegable, con guardrails y permisos activos |
| **LangGraph Studio** | https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024 | `make dev-langgraph` · `make dev-langchain` | El grafo de cada agente; la UI se sirve desde smith.langchain.com. Studio sirve LangGraph y LangChain: uno cada vez |
| └ API de LangGraph | http://127.0.0.1:2024/docs | | La misma API, sin la UI remota |
| **MCP (catalog-tools)** | http://localhost:8001/ | `make mcp` | Qué publica el servidor. El endpoint del protocolo es /mcp: para clientes MCP (IDE, Inspector), no para el navegador |
| **MCP Inspector** | http://localhost:6274 | `make mcp-inspector` | UI oficial de MCP, sobre make mcp: lista las tools y las llama a mano. Ábrelo con la URL con token que imprime |
| **Agentes A2A** | http://127.0.0.1:9101/.well-known/agent-card.json … :9108 | `make a2a-up` · `make a2a-catalog` | Un proceso por agente, en el puerto que dice configs/environments/local-a2a.yaml. make a2a-cards los sondea |
| **Langflow** | http://127.0.0.1:7860 | `make langflow-up` | La consola: flujos generados del catálogo con agentctl langflow export, que llaman a los agentes por A2A (make a2a-catalog) (admin / la clave de make langflow-url) |
| **MLflow** | http://localhost:5500 | `make mlflow-local` · `make lab` | Backend de AgentOps. El mismo puerto en los dos carriles: el del clúster o, sin clúster, make mlflow-local |
| └ Trazas | http://localhost:5500/#/experiments/0/traces | | Una traza por pregunta, con agent.* y prompt.* |
| └ Versiones de agente | http://localhost:5500/#/experiments/0/models | | Un LoggedModel por nombre@versión |
| └ Prompts | http://localhost:5500/#/prompts | | Prompt Registry: una versión por texto distinto |
| └ Runs (evals, métricas) | http://localhost:5500/#/experiments/0/runs | | make eval-run, make metrics |
| **kagent** | http://localhost:8082 | `make lab` | Chatear con los agentes desplegados |
| └ chat de software-manager | http://localhost:8082/agents/kagent/software-manager/chat | | El jefe de desarrollo: orquesta a los otros dos por A2A (make caso-9) |
| └ chat de code-reviewer | http://localhost:8082/agents/kagent/code-reviewer/chat | | Revisor declarativo: tools code.* por MCP + skill |
| └ chat de python-developer | http://localhost:8082/agents/kagent/python-developer/chat | | Desarrollador BYO (LangGraph dentro de kagent) |
| **A2A de kagent** | http://localhost:8083/api/a2a/kagent/software-manager/ | `make kagent-a2a` | El controlador atiende A2A para todos los agentes del clúster (port-forward) |
| **SeaweedFS** | http://localhost:9901 | `make lab` | Artefactos de MLflow (seaweedadmin / seaweedadmin) |
| **Registro de imágenes** | http://localhost:5001/v2/_catalog | `make cluster-up` | Las imágenes de agent-host, mcp, mlflow y las skills (make images) |
| **ArgoCD** | https://localhost:8443 | `make argocd` | Qué sincroniza ArgoCD de deploy/gitops/overlays/lab (port-forward) (admin / la clave que imprime make argocd) · sólo con `make gitops-lab` |
| **Grafana** | http://localhost:3000 | `make grafana` | Salud del clúster y de los pods (Prometheus). Las trazas de los agentes siguen en MLflow (admin / la clave que imprime make grafana) · sólo con `make gitops-lab` |
<!-- END GENERADO: uis -->

Los tres playgrounds locales comparten puertos entre sí (Studio sirve LangGraph y
LangChain): abre uno cada vez.

---

## El repositorio

Tres verbos, tres zonas: lo que **se publica**, lo que **se ejecuta** y lo que
**lo opera**.

```text
agent-platform/
├── platform/                  LO QUE SE PUBLICA — paquetes Python versionados
│   ├── core/                  agent-core: esquemas, config, registros, skills, evals, tracing. Sin frameworks
│   ├── runtime/               agent-runtime: agentctl, la fábrica, los playgrounds
│   ├── runtimes/              agent-runtime-{adk,langgraph,langchain}: manifiesto -> framework
│   ├── mcp/                   agent-mcp: catalog/tools por MCP
│   ├── a2a/                   agent-a2a: servir un agente por A2A, o delegar en uno remoto
│   ├── kagent/                agent-kagent: manifiesto -> CRDs de kagent; host de agentes BYO
│   ├── integrations/mlflow/   agent-mlflow: el único paquete que conoce MLflow
│   ├── integrations/langflow/ agent-langflow: Langflow como consola, por A2A
│   └── sandboxes/             local (contenedor) · sbx (microVM de Docker) · openshell (NVIDIA)
│
├── catalog/                   LO QUE SE EJECUTA — lo toca cada equipo
│   ├── agents/<dominio>/<nombre>/   technology · media · engineering · dataspace · platform
│   │                                agent.yaml + prompt.md + evals/ (si se mide)
│   ├── workflows/*.yaml
│   ├── cases.yaml                   los casos de uso: make casos, make caso-N, la tabla de arriba
│   ├── skills/<nombre>/SKILL.md     instrucciones que el agente lee bajo demanda
│   └── tools/*.py                   funciones sueltas: soltar un .py y ya
├── configs/                   perfiles (modelos, guardrails, permisos, políticas, sandboxes) y entornos
│
├── deploy/                    LO QUE LO OPERA
│   ├── kind/                  el clúster del laboratorio
│   ├── observability/         SeaweedFS + MLflow + OTel Collector (kustomize)
│   ├── kagent/                values de Helm y release.yaml (qué agentes, en qué modo)
│   ├── gitops/                ArgoCD: app-of-apps y overlays prod · lab (ADR 0007)
│   ├── images/                Dockerfiles: agent-host, mcp, mlflow, skill
│   ├── services.yaml          cada servicio y UI: make status, make down, la tabla de UIs
│   └── scripts/               cluster-up · doctor (make doctor) · stack (make status / down)
│
├── schemas/                   el JSON Schema de agent y workflow (make schema; un test lo vigila)
├── docs/                      strategy · concepts · demo · architecture · configuration · adr/
├── examples/                  la escalera de 4 escalones, a mano en los 3 frameworks
├── tests/                     core · runtime · runtimes · mcp · kagent · integrations · catalog
└── .agent-platform/           TODO lo generado (puentes de UI, CRDs, contratos). Ignorado por git
```

---

## Puesta en marcha

```bash
make install                   # .venv con todos los paquetes en modo editable
cp .env.example .env           # GOOGLE_API_KEY (Gemini)
make doctor                    # herramientas, clave y estado del clúster
source .venv/bin/activate      # para usar agentctl directamente; los `make` no lo necesitan
make test                      # ninguno llama al modelo
```

`make status` en cualquier momento, y `make down` para parar lo local.

### Carril local — un manifiesto, tres frameworks

```bash
make mlflow-local              # MLflow en :5500 (si no tienes el clúster levantado)

make dev-adk AGENT=python-developer   # ADK Dev UI, 100% local
make dev-langgraph             # LangGraph Studio
make dev-langchain             # LangGraph Studio sobre agentes de LangChain
make run AGENT=software-manager MSG="Una función que valide un IBAN español"   # narra (-v)

make a2a-up                    # los sub-agentes, en otro proceso, por A2A
make caso-7 MSG="..."          # (otra terminal) el jefe delega en ellos
```

Cada ejecución deja su traza en MLflow con `agent.framework` distinto. `make`
sólo activa las trazas si MLflow responde en :5500 (`make mlflow-local`); si no,
el caso corre igual y te lo dice al final.

### Carril clúster — kagent + MLflow

```bash
make lab                       # doctor + kind + registro + MLflow/SeaweedFS/collector + kagent + agentes, y status
make caso-9                    # el caso 3 contra kagent, por A2A entre pods
make cluster-status            # agentes, servidor MCP y pods, según kubectl
```

Tras cambiar un agente: `make deploy` (registra el prompt, regenera los CRDs,
aplica y registra la versión del agente). Para borrarlo todo: `make cluster-down`.

Con ArgoCD en vez de helm: `make gitops-lab` sincroniza `deploy/gitops/overlays/lab`
desde GitHub y, además de lo de `make lab`, trae Prometheus y Grafana
(`make argocd` y `make grafana` abren sus UIs con la clave). Un clúster lo gestiona
helm o ArgoCD, nunca los dos: `make doctor` lo comprueba y `make lab`,
`make platform` y `make gitops-lab` se niegan a mezclarlos. En producción se aplica
`deploy/gitops/bootstrap/root-prod.yaml` (qué crear antes y qué queda fuera:
[ADR 0007](docs/adr/0007-gitops-absorbe-genai-platform.md)).

---

## `agentctl`

```bash
agentctl catalog                                        # por dominio: para qué es cada agente y cómo probarlo
agentctl case [N] [-m "..."]                            # los casos de catalog/cases.yaml (lo que llama make caso-N)
agentctl list | show <agente> | validate | components
agentctl run software-manager -v -m "Una función que valide un IBAN español"   # -v: narra el trabajo
agentctl --runtime langgraph run python-developer -m "..."   # el MISMO manifiesto, otro framework
agentctl --runtime adk ui python-developer                    # el playground del framework
agentctl eval --all --check                             # la puerta barata, sin clave
agentctl eval python-developer --sink mlflow            # ejecuta, puntúa y publica
agentctl export --all -o <dir>                          # forma resuelta, para un orquestador
agentctl schema                                         # el JSON Schema, generado de los modelos

agentctl mcp list | serve                               # agent-mcp
agentctl a2a serve <agente[:framework]>... | ping | card <url> | send <url> -m "..."   # agent-a2a
agentctl kagent render | host                           # agent-kagent
agentctl mlflow init | prompts | register | sync | metrics   # agent-mlflow
```

Los cuatro últimos grupos existen porque su paquete está instalado: `agentctl` los
descubre por entry points.

---

## Qué se puede cambiar sin tocar la plataforma

Todo esto es una edición de YAML más `agentctl validate`:

- **Prompts** — inline en `spec.prompt.instruction` o en un `prompt.md`, con variables `{{ }}`.
- **Modelos** — por perfil (`profile: precise`) o con parámetros concretos.
- **Tools** — por referencia (`code.find_smells`); añadir una es soltar un `.py` en `catalog/tools/`.
- **Skills** — `spec.skills: [hexagonal-architecture@^1.0]`; al prompt sólo viaja el índice.
- **Guardrails, políticas y permisos** — perfiles en `configs/`, con overrides por agente.
  Timeout, reintentos y presupuesto en tokens o dólares se aplican de verdad.
- **Sandbox** — `spec.sandbox: {profile: code-exec}` y el agente ejecuta código aislado; el backend (`local`, después `openshell`) es un perfil.
- **Topología** — un agente pasa a ser paso de un workflow, o delega en otros (`sub_agents`).
- **Dónde vive cada sub-agente** — en proceso o por A2A: `a2a.endpoints` en el entorno.
- **Framework** — `spec.runtime: adk | langgraph | langchain`.
- **Despliegue** — qué agentes corren en kagent y en qué modo: `deploy/kagent/release.yaml`.

Añadir un **tipo nuevo** de cosa (un tipo de guardrail, una forma de orquestación,
un destino de despliegue) sí es código, y se publica como versión nueva del
paquete que toque. Esa es la frontera.

Cómo se combinan las capas (flota, entorno, agente, override): [`docs/configuration.md`](docs/configuration.md).

---

## Documentación

- [`docs/control-plane.md`](docs/control-plane.md) — Langflow como consola: evaluación crítica en 5 ejes y cómo se usa.
- [`docs/strategy.md`](docs/strategy.md) — hacia dónde va: robustez, seguridad, sandbox (OpenShell), agentes autónomos y boilerplate para organizaciones. Las decisiones, en [`docs/adr/`](docs/adr/).
- [`docs/concepts.md`](docs/concepts.md) — framework vs runtime vs protocolo; cómo viaja una petición.
- [`docs/demo.md`](docs/demo.md) — el guion de la demo (25′ y 15′), con plan B.
- [`docs/architecture.md`](docs/architecture.md) — paquetes, entry points, paridad entre frameworks, límites conocidos.
- [`docs/configuration.md`](docs/configuration.md) — referencia campo a campo, generada de los modelos (`make docs`).
- [`catalog/skills/README.md`](catalog/skills/README.md) · [`catalog/tools/README.md`](catalog/tools/README.md) · [`docs/evals.md`](docs/evals.md)
- [`examples/`](examples/) — la escalera en código nativo de cada framework.
