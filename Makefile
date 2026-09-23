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
        platform/mcp platform/a2a platform/kagent platform/integrations/mlflow

# -- lab ----------------------------------------------------------------------
CLUSTER   ?= agent-lab
REGISTRY  ?= localhost:5001
TAG       ?= 0.1.0
KAGENT_VERSION ?= 0.10.1
KAGENT_OCI     := oci://ghcr.io/kagent-dev/kagent/helm
DIST      := .agent-platform/dist

# Un único MLflow para los dos carriles: el del clúster (NodePort 5500) o, sin
# clúster, `make mlflow-local` en el mismo puerto.
MLFLOW_URL ?= http://localhost:5500
export MLFLOW_TRACKING_URI := $(MLFLOW_URL)

# Tracing del carril local: OTLP/HTTP directo a MLflow, experimento 0
# (`agentctl mlflow init` lo llama agent-platform).
AGENT ?= python-developer
OTEL_LOCAL := OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=$(MLFLOW_URL)/v1/traces \
              OTEL_EXPORTER_OTLP_TRACES_HEADERS=x-mlflow-experiment-id=0

.PHONY: help install test validate list run export schema docs eval eval-run \
        mlflow-local mlflow-init dev-adk dev-langgraph dev-langchain mcp mcp-inspector \
        a2a-up a2a-run a2a-cards kagent-a2a \
        lab cluster-up images skills platform deploy render prompts register refresh-tools metrics \
        status ui-urls cluster-down clean

help:
	@echo "Desarrollo"
	@echo "  make install         .venv con todos los paquetes en modo editable"
	@echo "  make test            tests (ninguno llama al modelo)"
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

mlflow-local:
	mkdir -p .agent-platform/mlflow
	cd .agent-platform/mlflow && ../../$(BIN)/mlflow server --host 127.0.0.1 --port 5500 \
	  --backend-store-uri sqlite:///mlflow.db --artifacts-destination ./artifacts

mlflow-init:
	$(AGENTCTL) mlflow init >/dev/null

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

# -- carril A2A local -----------------------------------------------------------
#
# Los mismos tres agentes que en kagent, cada uno en un framework y los
# sub-agentes en otro proceso: la delegación viaja por A2A de verdad. Ningún
# manifiesto cambia; configs/environments/local-a2a.yaml dice dónde está cada uno.

A2A_AGENTS ?= python-developer:langgraph code-reviewer:langchain data-provider:langgraph
# El que coordina: software-manager (ingeniería) o data-consumer (dataspace).
A2A_AGENT  ?= software-manager

a2a-up:
	$(OTEL_LOCAL) $(AGENTCTL) a2a serve $(A2A_AGENTS) --port 9101 -v

a2a-run:
	$(OTEL_LOCAL) $(AGENTCTL) --env local-a2a run $(A2A_AGENT) -v -m "$(MSG)"

a2a-cards:
	@$(AGENTCTL) a2a card http://localhost:9101/
	@$(AGENTCTL) a2a card http://localhost:9102/
	@$(AGENTCTL) a2a card http://localhost:9103/

# El controlador de kagent atiende A2A para todos los agentes del clúster.
# El port-forward queda en segundo plano; después, por ejemplo:
#   agentctl a2a send http://localhost:8083/api/a2a/kagent/software-manager/ -m "..."
kagent-a2a:
	@kubectl -n kagent port-forward svc/kagent-controller 8083:8083 >/dev/null 2>&1 & sleep 2
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
	kubectl apply -k deploy/observability
	helm upgrade --install kagent-crds $(KAGENT_OCI)/kagent-crds --version $(KAGENT_VERSION) -n kagent --wait
	helm upgrade --install kagent $(KAGENT_OCI)/kagent --version $(KAGENT_VERSION) -n kagent \
	  -f deploy/kagent/values.yaml --wait --timeout 10m
	kubectl apply -f deploy/kagent/ui-nodeport.yaml
	kubectl -n observability rollout status deploy/mlflow --timeout=5m
	$(AGENTCTL) mlflow init

render:
	$(AGENTCTL) kagent render

# Sin nombres: los agentes de deploy/kagent/release.yaml.
prompts:
	$(AGENTCTL) mlflow prompts

register:
	$(AGENTCTL) mlflow register

deploy: prompts render
	kubectl apply -k $(DIST)/kagent
	$(MAKE) --no-print-directory register
	kubectl -n kagent wait --for=condition=Ready agent --all --timeout=5m || true

# kagent no redescubre las tools de un RemoteMCPServer cuyo spec no cambia.
refresh-tools:
	kubectl -n kagent delete remotemcpserver catalog-tools --ignore-not-found
	kubectl apply -k $(DIST)/kagent

metrics:
	$(AGENTCTL) mlflow metrics

status:
	kubectl -n kagent get agents,remotemcpservers,modelconfigs
	kubectl -n kagent get pods
	kubectl -n observability get pods

ui-urls:
	@echo ""
	@echo "  kagent            http://localhost:8082/agents"
	@echo "  MLflow trazas     $(MLFLOW_URL)/#/experiments/0/traces"
	@echo "  MLflow versiones  $(MLFLOW_URL)/#/experiments/0/models"
	@echo "  MLflow prompts    $(MLFLOW_URL)/#/prompts"
	@echo "  MinIO             http://localhost:9901   (minioadmin / minioadmin)"
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
