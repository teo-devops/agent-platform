# agent-platform — punto de entrada único.
#
#   make install                  entorno de desarrollo
#   make dev-adk | dev-langgraph | dev-langchain    carril local: el playground de cada framework
#   make lab                      carril clúster: kind + MLflow + kagent + agentes
#
# `make help` lista todo.

PYTHON  ?= python3
VENV    ?= .venv
BIN     := $(VENV)/bin
AGENTCTL := $(BIN)/agentctl

# Paquetes en modo editable, con los extras que usa el desarrollo local.
PKGS := "platform/core[tracing]" platform/runtime \
        "platform/runtimes/adk[tracing]" "platform/runtimes/langgraph[tracing]" \
        "platform/runtimes/langchain[tracing]" \
        platform/mcp platform/a2a platform/kagent platform/integrations/mlflow \
        platform/sandboxes/local platform/sandboxes/sbx platform/sandboxes/openshell \
        platform/integrations/langflow

# -- lab ----------------------------------------------------------------------
CLUSTER   ?= agent-lab
REGISTRY  ?= localhost:5001
TAG       ?= 0.1.0
KAGENT_VERSION ?= 0.10.1
KAGENT_OCI     := oci://ghcr.io/kagent-dev/kagent/helm
DIST      := .agent-platform/dist

# Siempre contra el clúster del lab, nunca contra el contexto activo de kubectl
# (puede ser otro kind, p. ej. el del dataspace).
KUBE_CONTEXT ?= kind-$(CLUSTER)
KUBECTL := kubectl --context $(KUBE_CONTEXT)
HELM    := helm --kube-context $(KUBE_CONTEXT)

# Un único MLflow para los dos carriles: el del clúster (NodePort 5500) o, sin
# clúster, `make mlflow-local` en el mismo puerto.
MLFLOW_URL ?= http://localhost:5500
export MLFLOW_TRACKING_URI := $(MLFLOW_URL)

# Tracing del carril local: OTLP/HTTP directo a MLflow, experimento 0
# (`agentctl mlflow init` lo llama agent-platform). Sólo si MLflow responde:
# sin él, el exportador llenaría la terminal de reintentos de conexión.
AGENT ?= python-developer
MLFLOW_UP := $(shell curl -sf -o /dev/null --max-time 1 $(MLFLOW_URL)/health && echo yes)
OTEL_LOCAL := $(if $(MLFLOW_UP),OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=$(MLFLOW_URL)/v1/traces \
              OTEL_EXPORTER_OTLP_TRACES_HEADERS=x-mlflow-experiment-id=0)
HASH := \#
MLFLOW_HINT := $(if $(MLFLOW_UP),Trazas en $(MLFLOW_URL)/$(HASH)/experiments/0/traces,Sin trazas: MLflow no está levantado (make mlflow-local para verlas))

.PHONY: help install test validate list run export schema docs eval eval-run \
        mlflow-local mlflow-init dev-adk dev-langgraph dev-langchain mcp mcp-inspector \
        casos caso-1 caso-2 caso-3 caso-4 caso-5 caso-6 caso-7 caso-8 caso-10 test-sandbox test-sbx test-openshell sandbox-image \
        a2a-up a2a-catalog a2a-run a2a-cards a2a-ensure a2a-down kagent-a2a \
        lab cluster-up images skills platform deploy render prompts register refresh-tools metrics \
        status ui-urls cluster-down clean langflow-up langflow-url langflow-down

help:
	@$(MAKE) --no-print-directory casos
	@echo "Desarrollo"
	@echo "  make install         .venv con todos los paquetes en modo editable"
	@echo "  make test            tests (ninguno llama al modelo)"
	@echo "  make test-sandbox    el backend de sandbox local con un contenedor real (Docker)"
	@echo "  make test-sbx        el backend sbx con Docker Sandboxes de verdad (microVM)"
	@echo "  make test-openshell  el backend openshell con un gateway de OpenShell de verdad"
	@echo "  make validate        construye todos los manifiestos sin llamar al modelo"
	@echo "  make eval            valida las suites de evals (sin clave)"
	@echo "  make eval-run        ejecuta las suites y las publica en MLflow (con clave)"
	@echo "  make run AGENT=software-manager MSG='...'   narra delegaciones y tools (-v)"
	@echo ""
	@echo "Carril local — un manifiesto, tres frameworks (sin kagent)"
	@echo "  make mlflow-local    MLflow en $(MLFLOW_URL) si no hay clúster"
	@echo "  make dev-adk         ADK Dev UI: todo el catálogo, con enforcement (AGENT= elige cuál abrir)"
	@echo "  make dev-langgraph   LangGraph Studio"
	@echo "  make dev-langchain   LangGraph Studio sobre agentes de LangChain"
	@echo "  make mcp             sirve catalog/tools por MCP en :8001 (info en http://localhost:8001/)"
	@echo "  make mcp-inspector   MCP Inspector: la UI para explorar y llamar esas tools"
	@echo ""
	@echo "Carril A2A local — agentes en procesos distintos, sin clúster"
	@echo "  make a2a-up          terminal 1: python-developer, code-reviewer y data-provider por A2A"
	@echo "  make a2a-run         terminal 2: software-manager (ADK) delega en ellos por A2A"
	@echo "  make a2a-run A2A_AGENT=data-consumer MSG='...'   el caso dataspace"
	@echo "  make a2a-cards       las agent cards que publican"
	@echo "  make a2a-down        para los que levantó caso-7 / caso-8 en segundo plano"
	@echo ""
	@echo "Carril clúster — kagent + MLflow"
	@echo "  make lab             todo: cluster-up images platform deploy"
	@echo "  make deploy          prompts -> render -> apply -> register (tras cambiar un agente)"
	@echo "  make refresh-tools   tras añadir o quitar tools del catálogo"
	@echo "  make metrics         latencia, tokens y tool calls por agente/prompt/framework"
	@echo "  make kagent-a2a      A2A contra los agentes del clúster (port-forward al controlador)"
	@echo "  make status | ui-urls | cluster-down"

# -- desarrollo ---------------------------------------------------------------

$(BIN)/python:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip

install: $(BIN)/python
	$(BIN)/pip install $(foreach pkg,$(PKGS),-e $(pkg))
	$(BIN)/pip install pytest pytest-asyncio

test:
	$(BIN)/python -m pytest -q

# La prueba del sandbox con un contenedor de verdad (necesita Docker).
test-sandbox:
	AGENT_SANDBOX_DOCKER_TESTS=1 $(BIN)/python -m pytest -q tests/sandboxes tests/core/test_sandbox.py

# Con los proveedores de verdad: Docker Sandboxes (sbx) y NVIDIA OpenShell (gateway en marcha).
test-sbx:
	AGENT_SANDBOX_SBX_TESTS=1 $(BIN)/python -m pytest -q tests/sandboxes/test_sbx.py
test-openshell: sandbox-image
	AGENT_SANDBOX_OPENSHELL_TESTS=1 $(BIN)/python -m pytest -q tests/sandboxes/test_openshell.py

# La imagen de los sandboxes local y openshell: sin root y con /workspace.
sandbox-image:
	docker build -q -t agent-platform/sandbox:0.1.0 -f deploy/images/Dockerfile.sandbox deploy/images

validate:
	$(AGENTCTL) validate

list:
	$(AGENTCTL) list

MSG ?= Una función que calcule la mediana de una lista de números
# -v: narra en stderr quién delega en quién, las tools y los saltos A2A.
run:
	$(OTEL_LOCAL) $(AGENTCTL) run $(AGENT) -v -m "$(MSG)"

export:
	$(AGENTCTL) export --all -o $(DIST)/contracts

schema:
	$(AGENTCTL) schema -o $(DIST)/schemas

docs:
	$(BIN)/python scripts/gen-config-reference.py

eval:
	$(AGENTCTL) eval --all --check

SUITE ?= python-developer
eval-run:
	$(OTEL_LOCAL) $(AGENTCTL) eval $(SUITE) --sink mlflow

# -- carril local ---------------------------------------------------------------

# El 5500 lo publica también el clúster: si ya hay un MLflow ahí, se usa ese.
mlflow-local:
	@if [ "$(MLFLOW_UP)" = yes ]; then \
	  echo "MLflow ya responde en $(MLFLOW_URL) (el del clúster o uno local ya levantado)"; exit 0; \
	elif ss -ltn 2>/dev/null | grep -q ':5500 '; then \
	  echo "El puerto 5500 está ocupado por otra cosa:"; ss -ltnp 2>/dev/null | grep ':5500 '; exit 1; \
	fi
	mkdir -p .agent-platform/mlflow
	cd .agent-platform/mlflow && ../../$(BIN)/mlflow server --host 127.0.0.1 --port 5500 \
	  --backend-store-uri sqlite:///mlflow.db --artifacts-destination ./artifacts

# Sin MLflow levantado se salta: el cliente reintenta con backoff y parecería colgado.
mlflow-init:
ifeq ($(MLFLOW_UP),yes)
	$(AGENTCTL) mlflow init >/dev/null
else
	@echo "$(MLFLOW_HINT)"
endif

dev-adk: mlflow-init
	$(OTEL_LOCAL) OTEL_RESOURCE_ATTRIBUTES=agent.framework=adk $(AGENTCTL) --runtime adk ui $(AGENT)

dev-langgraph: mlflow-init
	$(OTEL_LOCAL) OTEL_RESOURCE_ATTRIBUTES=agent.framework=langgraph $(AGENTCTL) --runtime langgraph ui

dev-langchain: mlflow-init
	$(OTEL_LOCAL) OTEL_RESOURCE_ATTRIBUTES=agent.framework=langchain $(AGENTCTL) --runtime langchain ui

# 8001: el 8000 es de ADK Dev UI. http://localhost:8001/ describe el servidor;
# /mcp es el endpoint del protocolo, para clientes MCP (un navegador recibe 406).
mcp:
	$(AGENTCTL) mcp serve --port 8001

# La UI oficial de MCP, conectada a `make mcp`: listar tools y llamarlas a mano.
mcp-inspector:
	npx -y @modelcontextprotocol/inspector --web --transport http --server-url http://localhost:8001/mcp

# -- casos de uso ---------------------------------------------------------------
#
# Un target por fila de la tabla del README. Cada uno imprime el comando
# agentctl que ejecuta, para aprenderlo de paso, y dónde verlo en una UI.
#
#   make caso-3                                   con su mensaje de ejemplo
#   make caso-3 MSG="Una función que ..."         con el tuyo
#   make caso-3 RUNTIME=langgraph                 en otro framework (adk | langgraph | langchain)

casos:
	@echo ""
	@echo "Casos de uso — cada uno añade una forma de colaborar al anterior"
	@echo "  make caso-1   tech-explainer       un agente solo: explica un concepto técnico"
	@echo "  make caso-2   release-manager      un agente con tools: de los commits a la versión y sus notas"
	@echo "  make caso-3   software-manager     delega en un desarrollador y un revisor (lo decide el modelo)"
	@echo "  make caso-4   tech-article         flujo secuencial: investigar y redactar (lo decide el YAML)"
	@echo "  make caso-5   tech-briefing        en paralelo: una tecnología, dos audiencias"
	@echo "  make caso-6   review-loop          bucle desarrollador <-> revisor"
	@echo "  make caso-7   software-manager     el caso 3 por A2A: cada sub-agente en su proceso y framework"
	@echo "  make caso-8   data-consumer        dos organizaciones hablando por A2A (dataspace)"
	@echo "  make caso-10  python-executor      escribe código y lo EJECUTA en un sandbox aislado (Docker)"
	@echo ""
	@echo "  Opciones: MSG=\"...\" (tu mensaje)  RUNTIME=adk|langgraph|langchain (otro framework)  ENV=sandbox-sbx|sandbox-openshell (caso 10)"
	@echo ""

caso-1: CASO_AGENT := tech-explainer
caso-1: CASO_TITLE := Un agente solo: un modelo con instrucciones
caso-1: CASO_MSG   := ¿Qué es una API REST?
caso-1: CASO_UI    := make dev-adk AGENT=tech-explainer

caso-2: CASO_AGENT := release-manager
caso-2: CASO_TITLE := Un agente que llama a tools (código Python): la versión la calcula una función, no el modelo
caso-2: CASO_MSG   := Versión actual: 1.4.2. Commits: feat(api): paginación en /orders · fix: cierre de conexiones al reiniciar · refactor!: elimina /v1/orders
caso-2: CASO_UI    := make dev-adk AGENT=release-manager  (pestaña Events: cada llamada a una tool)

caso-3: CASO_AGENT := software-manager
caso-3: CASO_TITLE := Delegación decidida por el modelo: jefe, desarrollador y revisor
caso-3: CASO_MSG   := Una función que valide un IBAN español
caso-3: CASO_UI    := make dev-adk AGENT=software-manager  (Events: python_developer y code_reviewer)

caso-4: CASO_AGENT := tech-article
caso-4: CASO_TITLE := Flujo secuencial: el orden lo fija el YAML, no el modelo
caso-4: CASO_MSG   := Qué es el protocolo A2A, explicado para desarrolladores junior
caso-4: CASO_UI    := make dev-langgraph  (el grafo del flujo en LangGraph Studio)

caso-5: CASO_AGENT := tech-briefing
caso-5: CASO_TITLE := En paralelo: una tecnología, notas para el equipo y tres frases para dirección
caso-5: CASO_MSG   := Adoptar Kubernetes operators para nuestras bases de datos
caso-5: CASO_UI    := make dev-langgraph  (las dos ramas en LangGraph Studio)

caso-6: CASO_AGENT := review-loop
caso-6: CASO_TITLE := Bucle: desarrollador y revisor, dos vueltas
caso-6: CASO_MSG   := Una función que invierta una cadena
caso-6: CASO_UI    := make dev-langgraph  (el bucle en LangGraph Studio)

caso-7: CASO_AGENT := software-manager
caso-7: CASO_TITLE := El caso 3 por A2A: cada sub-agente en su proceso y su framework
caso-7: CASO_MSG   := Una función que calcule la mediana de una lista de números
caso-7: CASO_ENV   := --env local-a2a
caso-7: CASO_UI     = los sub-agentes, en la terminal de make a2a-up (o tail -f $(A2A_LOG) si los levantó make)

caso-8: CASO_AGENT := data-consumer
caso-8: CASO_TITLE := Dos organizaciones por A2A: B pregunta a A y decide según su política
caso-8: CASO_MSG   := Datos de movilidad en bicicleta para un producto comercial
caso-8: CASO_ENV   := --env local-a2a
caso-8: CASO_UI     = la organización A, en la terminal de make a2a-up (o tail -f $(A2A_LOG)). Prueba MSG='Datos de movilidad en bicicleta para investigación'

caso-10: CASO_AGENT := python-executor
caso-10: CASO_TITLE := Código ejecutado en un sandbox: sin red, raíz de sólo lectura, /workspace en memoria
caso-10: CASO_MSG   := Una función que calcule la mediana de una lista de números
caso-10: CASO_UI    := docker ps --filter label=agent-platform.sandbox=local (mientras corre) · configs/sandboxes.yaml

# El caso del sandbox necesita su imagen (local y openshell).
caso-10: sandbox-image

# Los casos A2A necesitan a los sub-agentes escuchando: si no están, se levantan solos.
caso-7 caso-8: a2a-ensure

# Tu MSG gana al del caso; si no pasas ninguno, el de ejemplo.
CASO_MESSAGE = $(if $(filter command line environment,$(origin MSG)),$(MSG),$(CASO_MSG))
# ENV=<entorno> gana al del caso: make caso-10 ENV=sandbox-sbx
CASO_ARGS    = $(if $(RUNTIME),--runtime $(RUNTIME) )$(if $(ENV),--env $(ENV) ,$(if $(CASO_ENV),$(CASO_ENV) ))run $(CASO_AGENT) -v -m

caso-1 caso-2 caso-3 caso-4 caso-5 caso-6 caso-7 caso-8 caso-10:
	@echo ""
	@echo "  Caso $(@:caso-%=%) · $(CASO_TITLE)"
	@echo "  \$$ agentctl $(CASO_ARGS) '$(CASO_MESSAGE)'"
	@echo ""
	@$(OTEL_LOCAL) $(AGENTCTL) $(CASO_ARGS) "$(CASO_MESSAGE)"
	@echo ""
	@echo "  Míralo también: $(CASO_UI)"
	@echo "  $(MLFLOW_HINT)"

# -- Langflow: la consola ------------------------------------------------------
#
# Langflow llama a los agentes por A2A; no los ejecuta (docs/control-plane.md).
LANGFLOW_ENV  := .agent-platform/langflow.env
LANGFLOW_URL  ?= http://127.0.0.1:7860
# LANGFLOW_OTEL=1 añade sus trazas hacia MLflow (deploy/langflow/compose.otel.yaml).
LANGFLOW_COMPOSE := docker compose -f deploy/langflow/compose.yaml $(if $(LANGFLOW_OTEL),-f deploy/langflow/compose.otel.yaml)

$(LANGFLOW_ENV):
	@mkdir -p .agent-platform
	@printf 'LANGFLOW_SUPERUSER=admin\nLANGFLOW_SUPERUSER_PASSWORD=%s\nLANGFLOW_SECRET_KEY=%s\n' \
	  "$$(openssl rand -hex 12)" "$$(openssl rand -base64 32)" > $@
	@chmod 600 $@
	@echo "  credenciales de Langflow generadas en $@ (no se versionan)"

langflow-up: $(LANGFLOW_ENV)
	@if [ -n "$(LANGFLOW_OTEL)" ]; then \
	  [ "$(MLFLOW_UP)" = yes ] || { echo "LANGFLOW_OTEL necesita MLflow en $(MLFLOW_URL): make mlflow-local"; exit 1; }; \
	  id=$$(curl -sf "$(MLFLOW_URL)/api/2.0/mlflow/experiments/get-by-name?experiment_name=langflow" | sed -n 's/.*"experiment_id": *"\([0-9]*\)".*/\1/p'); \
	  [ -n "$$id" ] || id=$$(curl -sf -X POST -H 'Content-Type: application/json' -d '{"name":"langflow"}' \
	    "$(MLFLOW_URL)/api/2.0/mlflow/experiments/create" | sed -n 's/.*"experiment_id": *"\([0-9]*\)".*/\1/p'); \
	  echo "  Trazas de Langflow -> MLflow, experimento 'langflow' ($$id)"; \
	  LANGFLOW_MLFLOW_EXPERIMENT_ID=$$id $(LANGFLOW_COMPOSE) up -d; \
	else $(LANGFLOW_COMPOSE) up -d; fi
	@echo "  Esperando a Langflow en $(LANGFLOW_URL)..."
	@for i in $$(seq 1 90); do curl -sf -o /dev/null $(LANGFLOW_URL)/health && break; sleep 2; done
	@$(MAKE) --no-print-directory langflow-url

langflow-url:
	@echo "  Langflow: $(LANGFLOW_URL)   usuario: admin   clave: $$(sed -n 's/^LANGFLOW_SUPERUSER_PASSWORD=//p' $(LANGFLOW_ENV))"
	@echo "  Los agentes, por A2A: make a2a-up   ·   un flujo del catálogo: agentctl langflow export tech-article"

langflow-down:
	$(LANGFLOW_COMPOSE) down

# -- carril A2A local -----------------------------------------------------------
#
# Los mismos tres agentes que en kagent, cada uno en un framework y los
# sub-agentes en otro proceso: la delegación viaja por A2A de verdad. Ningún
# manifiesto cambia; configs/environments/local-a2a.yaml dice dónde está cada uno.

A2A_AGENTS ?= python-developer:langgraph code-reviewer:langchain data-provider:langgraph
# El que coordina: software-manager (ingeniería) o data-consumer (dataspace).
A2A_AGENT  ?= software-manager

# Todo lo que local-a2a.yaml declara, en el orden de sus puertos: lo que Langflow
# necesita para llamar a cualquier agente del catálogo.
A2A_CATALOG ?= python-developer:langgraph code-reviewer:langchain data-provider:langgraph \
               tech-researcher tech-writer tech-explainer release-manager software-manager
a2a-catalog:
	@$(MAKE) --no-print-directory a2a-up A2A_AGENTS="$(A2A_CATALOG)"

a2a-up:
	$(OTEL_LOCAL) $(AGENTCTL) a2a serve $(A2A_AGENTS) --port $(A2A_PORT) -v

# Lo que usan caso-7 y caso-8: si los agentes A2A no responden, se levantan en
# segundo plano. Si ya los tienes en otra terminal (make a2a-up), se usan esos.
A2A_LOG  := .agent-platform/a2a.log
A2A_PID  := .agent-platform/a2a.pid
A2A_PORT ?= 9101
A2A_LAST := $(shell echo $$(($(A2A_PORT) - 1 + $(words $(A2A_AGENTS)))))

a2a-ensure:
	@if curl -sf 127.0.0.1:$(A2A_LAST)/.well-known/agent-card.json >/dev/null 2>&1; then \
	  echo "  A2A: usando los agentes que ya escuchan en :$(A2A_PORT)-:$(A2A_LAST)"; \
	else \
	  mkdir -p .agent-platform; \
	  echo "  A2A: levantando $(A2A_AGENTS) en segundo plano (log: $(A2A_LOG) · parar: make a2a-down)"; \
	  $(OTEL_LOCAL) nohup $(AGENTCTL) a2a serve $(A2A_AGENTS) --port $(A2A_PORT) -v > $(A2A_LOG) 2>&1 </dev/null & echo $$! > $(A2A_PID); \
	  for i in $$(seq 1 60); do \
	    curl -sf 127.0.0.1:$(A2A_LAST)/.well-known/agent-card.json >/dev/null 2>&1 && exit 0; sleep 1; \
	  done; \
	  echo "  A2A: no arrancaron en 60 s; mira $(A2A_LOG)"; exit 1; \
	fi

a2a-down:
	@if [ -f $(A2A_PID) ] && kill $$(cat $(A2A_PID)) 2>/dev/null; then \
	  echo "  A2A: parados"; rm -f $(A2A_PID); \
	else \
	  rm -f $(A2A_PID); echo "  A2A: no había nada levantado por make (si usaste make a2a-up, Ctrl+C en su terminal)"; \
	fi

a2a-run:
	$(OTEL_LOCAL) $(AGENTCTL) --env local-a2a run $(A2A_AGENT) -v -m "$(MSG)"

a2a-cards:
	@$(AGENTCTL) a2a card http://127.0.0.1:9101/
	@$(AGENTCTL) a2a card http://127.0.0.1:9102/
	@$(AGENTCTL) a2a card http://127.0.0.1:9103/

# El controlador de kagent atiende A2A para todos los agentes del clúster.
# El port-forward queda en segundo plano; después, por ejemplo:
#   agentctl a2a send http://localhost:8083/api/a2a/kagent/software-manager/ -m "..."
kagent-a2a:
	@ss -ltn 2>/dev/null | grep -q ':8083 ' || \
	  { $(KUBECTL) -n kagent port-forward svc/kagent-controller 8083:8083 >/dev/null 2>&1 & sleep 2; }
	$(AGENTCTL) a2a card http://localhost:8083/api/a2a/kagent/software-manager/

# -- carril clúster -------------------------------------------------------------

lab: cluster-up images platform deploy ui-urls

cluster-up:
	CLUSTER=$(CLUSTER) deploy/scripts/cluster-up.sh

images: skills
	docker build --network host -t $(REGISTRY)/agent-platform/mlflow:3.16.1 -f deploy/images/Dockerfile.mlflow deploy/images
	docker build --network host -t $(REGISTRY)/agent-platform/mcp:$(TAG) -f deploy/images/Dockerfile.mcp .
	docker build --network host -t $(REGISTRY)/agent-platform/agent-host:$(TAG) -f deploy/images/Dockerfile.agent-host .
	docker push -q $(REGISTRY)/agent-platform/mlflow:3.16.1
	docker push -q $(REGISTRY)/agent-platform/mcp:$(TAG)
	docker push -q $(REGISTRY)/agent-platform/agent-host:$(TAG)

# Cada skill del catálogo, como imagen OCI etiquetada con su versión.
skills:
	@for dir in catalog/skills/*/; do \
	  name=$$(basename $$dir); \
	  version=$$(sed -n 's/^version: *//p' $$dir/SKILL.md | head -1); \
	  docker build -q -f deploy/images/Dockerfile.skill --build-arg SKILL=$$name \
	    -t $(REGISTRY)/skills/$$name:$$version . >/dev/null && \
	  docker push -q $(REGISTRY)/skills/$$name:$$version >/dev/null && \
	  echo "  skill $$name:$$version"; \
	done

platform:
	$(KUBECTL) apply -k deploy/observability
	$(HELM) upgrade --install kagent-crds $(KAGENT_OCI)/kagent-crds --version $(KAGENT_VERSION) -n kagent --wait
	$(HELM) upgrade --install kagent $(KAGENT_OCI)/kagent --version $(KAGENT_VERSION) -n kagent \
	  -f deploy/kagent/values.yaml --wait --timeout 10m
	$(KUBECTL) apply -f deploy/kagent/ui-nodeport.yaml
	$(KUBECTL) -n observability rollout status deploy/mlflow --timeout=5m
	$(AGENTCTL) mlflow init

render:
	$(AGENTCTL) kagent render

# Sin nombres: los agentes de deploy/kagent/release.yaml.
prompts:
	$(AGENTCTL) mlflow prompts

register:
	$(AGENTCTL) mlflow register

deploy: prompts render
	$(KUBECTL) apply -k $(DIST)/kagent
	$(MAKE) --no-print-directory register
	$(KUBECTL) -n kagent wait --for=condition=Ready agent --all --timeout=5m || true

# kagent no redescubre las tools de un RemoteMCPServer cuyo spec no cambia.
refresh-tools:
	$(KUBECTL) -n kagent delete remotemcpserver catalog-tools --ignore-not-found
	$(KUBECTL) apply -k $(DIST)/kagent

metrics:
	$(AGENTCTL) mlflow metrics

status:
	$(KUBECTL) -n kagent get agents,remotemcpservers,modelconfigs
	$(KUBECTL) -n kagent get pods
	$(KUBECTL) -n observability get pods

ui-urls:
	@echo ""
	@echo "  kagent            http://localhost:8082/agents"
	@echo "  MLflow trazas     $(MLFLOW_URL)/#/experiments/0/traces"
	@echo "  MLflow versiones  $(MLFLOW_URL)/#/experiments/0/models"
	@echo "  MLflow prompts    $(MLFLOW_URL)/#/prompts"
	@echo "  SeaweedFS         http://localhost:9901   (seaweedadmin / seaweedadmin)"
	@echo "  ADK Dev UI        http://localhost:8000/dev-ui/?app=$(subst -,_,$(AGENT))   (make dev-adk)"
	@echo "  LangGraph Studio  https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024   (make dev-langgraph | dev-langchain)"
	@echo "  MCP               http://localhost:8001/   (make mcp; clientes MCP: /mcp)"
	@echo "  MCP Inspector     http://localhost:6274   (make mcp-inspector)"

cluster-down:
	kind delete cluster --name $(CLUSTER)
	docker rm -f agent-registry >/dev/null 2>&1 || true

clean:
	rm -rf $(VENV) .pytest_cache .agent-platform langgraph.json
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	find platform -name '*.egg-info' -type d -prune -exec rm -rf {} +
