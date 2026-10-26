# agent-platform — punto de entrada único.
#
#   make help                     por dónde empezar, en cuatro pasos
#   make status                   qué está levantado ahora mismo, y cómo levantar lo que no
#   make help-all                 todos los targets
#
# Qué servicios hay y dónde escuchan: deploy/services.yaml. Qué casos de uso:
# catalog/cases.yaml. Este Makefile no repite ninguna de las dos listas.

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
export CLUSTER KUBE_CONTEXT

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

# -- estado y procesos ------------------------------------------------------------
#
# Lo que un make deja corriendo en primer plano guarda su pid en $(PIDS), con el
# nombre que le da deploy/services.yaml. Así `make status` sabe qué es suyo y
# `make down` puede pararlo desde otra terminal. `exec` hace que el pid guardado
# sea el del propio servicio, no el de la shell que lo lanza.
PIDS   := .agent-platform/pids
STACK  := $(if $(wildcard $(BIN)/python),$(BIN)/python,$(PYTHON)) deploy/scripts/stack.py
DOCTOR := deploy/scripts/doctor.sh
TRACK   = mkdir -p $(PIDS) && echo $$$$ > $(PIDS)/$(1).pid && exec env

.PHONY: help help-all install test validate list catalog run export schema docs eval eval-run \
        status ui-urls down doctor \
        mlflow-local mlflow-down mlflow-init dev-adk dev-langgraph dev-langchain mcp mcp-inspector \
        casos test-sandbox test-sbx test-openshell sandbox-image \
        a2a-up a2a-catalog a2a-run a2a-cards a2a-ensure a2a-down kagent-a2a \
        lab cluster-up images skills platform deploy render prompts register refresh-tools metrics \
        cluster-status cluster-down clean langflow-up langflow-url langflow-down \
        gitops-lab gitops-check grafana argocd

# Los caso-N NO son .PHONY: make no busca reglas de patrón para targets .PHONY.

help:
	@echo ""
	@echo "agent-platform — por dónde empezar"
	@echo ""
	@echo "  1. Prepara       make install           .venv con todos los paquetes"
	@echo "                   cp .env.example .env   y pon tu GOOGLE_API_KEY"
	@echo "                   make doctor            comprueba que no falta nada"
	@echo ""
	@echo "  2. Prueba        make casos             el menú de casos de uso (no necesitan clúster)"
	@echo "                   make caso-3            uno de ellos · MSG=\"...\" · RUNTIME=langgraph"
	@echo "                   make catalog           qué agentes hay, para qué y cómo probar cada uno"
	@echo ""
	@echo "  3. Míralo en UI  make dev-adk           ADK Dev UI con todo el catálogo (AGENT= elige cuál)"
	@echo "                   make dev-langgraph     LangGraph Studio: el grafo de cada agente"
	@echo "                   make mlflow-local      MLflow para las trazas, si no tienes el clúster"
	@echo "                   make langflow-up       Langflow como consola, por A2A"
	@echo ""
	@echo "  4. En Kubernetes make lab               kind + MLflow + kagent + agentes (~10 min)"
	@echo "                   make caso-9            el caso 3, con A2A entre pods"
	@echo ""
	@echo "  Siempre:         make status            qué está levantado y cómo levantar lo que no"
	@echo "                   make down              para todo lo local (el clúster: make cluster-down)"
	@echo ""
	@echo "  Todos los targets: make help-all"
	@echo ""

help-all:
	@echo ""
	@echo "Estado"
	@echo "  make status          cada servicio de deploy/services.yaml: ✓ con su URL, o ✗ con cómo levantarlo"
	@echo "  make ui-urls         lo mismo, con las sub-páginas de cada UI (trazas, prompts, chats...)"
	@echo "  make down            para lo que los make dejaron en marcha en local; Langflow incluido"
	@echo "  make doctor          herramientas, clave y quién gestiona el clúster, antes de empezar"
	@echo ""
	@echo "Desarrollo"
	@echo "  make install         .venv con todos los paquetes en modo editable"
	@echo "  make test            tests (ninguno llama al modelo)"
	@echo "  make test-sandbox    el backend de sandbox local con un contenedor real (Docker)"
	@echo "  make test-sbx        el backend sbx con Docker Sandboxes de verdad (microVM)"
	@echo "  make test-openshell  el backend openshell con un gateway de OpenShell de verdad"
	@echo "  make validate        construye todos los manifiestos sin llamar al modelo"
	@echo "  make catalog         el catálogo por dominio: para qué es cada agente y cómo probarlo"
	@echo "  make docs            regenera docs/configuration.md y las tablas del README"
	@echo "  make eval            valida las suites de evals (sin clave)"
	@echo "  make eval-run        ejecuta las suites y las publica en MLflow (con clave)"
	@echo "  make run AGENT=software-manager MSG='...'   narra delegaciones y tools (-v)"
	@echo ""
	@echo "Casos de uso (catalog/cases.yaml)"
	@echo "  make casos           el menú"
	@echo "  make caso-N          uno: MSG=\"...\"  RUNTIME=adk|langgraph|langchain  ENV=<entorno>"
	@echo ""
	@echo "Carril local — un manifiesto, tres frameworks (sin kagent)"
	@echo "  make mlflow-local    MLflow en $(MLFLOW_URL) si no hay clúster (make mlflow-down lo para)"
	@echo "  make dev-adk         ADK Dev UI: todo el catálogo, con enforcement (AGENT= elige cuál abrir)"
	@echo "  make dev-langgraph   LangGraph Studio"
	@echo "  make dev-langchain   LangGraph Studio sobre agentes de LangChain"
	@echo "  make mcp             sirve catalog/tools por MCP en :8001 (info en http://localhost:8001/)"
	@echo "  make mcp-inspector   MCP Inspector: la UI para explorar y llamar esas tools"
	@echo ""
	@echo "Carril A2A local — agentes en procesos distintos, sin clúster"
	@echo "  make a2a-up          terminal 1: python-developer, code-reviewer y data-provider por A2A"
	@echo "  make a2a-catalog     todos los de configs/environments/local-a2a.yaml (lo que usa Langflow)"
	@echo "  make a2a-run         terminal 2: software-manager (ADK) delega en ellos por A2A"
	@echo "  make a2a-run A2A_AGENT=data-consumer MSG='...'   el caso dataspace"
	@echo "  make a2a-cards       qué agentes A2A responden, con su tarjeta"
	@echo "  make a2a-down        para los agentes A2A que levantó make (en primer o segundo plano)"
	@echo ""
	@echo "Consola"
	@echo "  make langflow-up     Langflow en http://127.0.0.1:7860 (make langflow-url: usuario y clave)"
	@echo "  make langflow-down   lo para"
	@echo ""
	@echo "Carril clúster — kagent + MLflow"
	@echo "  make lab             todo: doctor cluster-up images platform deploy status"
	@echo "  make deploy          prompts -> render -> apply -> register (tras cambiar un agente)"
	@echo "  make refresh-tools   tras añadir o quitar tools del catálogo"
	@echo "  make metrics         latencia, tokens y tool calls por agente/prompt/framework"
	@echo "  make kagent-a2a      A2A contra los agentes del clúster (port-forward al controlador)"
	@echo "  make cluster-status  agentes, MCP y pods, según kubectl"
	@echo "  make cluster-down    borra el clúster y el registro"
	@echo ""
	@echo "GitOps — ArgoCD despliega deploy/gitops (ADR 0007)"
	@echo "  make gitops-lab      en vez de 'make platform': ArgoCD en el lab y el overlay lab desde GitHub"
	@echo "  make argocd          la UI de ArgoCD en https://localhost:8443 (port-forward), con la clave"
	@echo "  make grafana         Grafana en http://localhost:3000 (port-forward), con la clave"
	@echo "  make gitops-check    renderiza los overlays prod y lab"
	@echo ""

# -- estado -------------------------------------------------------------------

status:
	@$(STACK) status

ui-urls:
	@$(STACK) status --links

doctor:
	@$(DOCTOR)

down:
	@$(STACK) down
	@if [ -n "$$($(LANGFLOW_COMPOSE) ps -q 2>/dev/null)" ]; then $(LANGFLOW_COMPOSE) down; fi

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

catalog:
	@$(AGENTCTL) catalog

MSG ?= Una función que calcule la mediana de una lista de números
# -v: narra en stderr quién delega en quién, las tools y los saltos A2A.
run:
	$(OTEL_LOCAL) $(AGENTCTL) run $(AGENT) -v -m "$(MSG)"

export:
	$(AGENTCTL) export --all -o $(DIST)/contracts

# Versionado en schemas/: tests/core/test_contract.py comprueba que está al día.
schema:
	$(AGENTCTL) schema -o schemas

# docs/configuration.md y las tablas del README (casos, catálogo, UIs): generados.
docs:
	$(BIN)/python scripts/gen-config-reference.py
	$(BIN)/python scripts/gen-readme-tables.py

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
	@$(call TRACK,mlflow) sh -c 'cd .agent-platform/mlflow && exec $(CURDIR)/$(BIN)/mlflow server \
	  --host 127.0.0.1 --port 5500 --backend-store-uri sqlite:///mlflow.db --artifacts-destination ./artifacts'

mlflow-down:
	@$(STACK) down mlflow

# Sin MLflow levantado se salta: el cliente reintenta con backoff y parecería colgado.
mlflow-init:
ifeq ($(MLFLOW_UP),yes)
	$(AGENTCTL) mlflow init >/dev/null
else
	@echo "$(MLFLOW_HINT)"
endif

dev-adk: mlflow-init
	@$(call TRACK,adk) $(OTEL_LOCAL) OTEL_RESOURCE_ATTRIBUTES=agent.framework=adk $(AGENTCTL) --runtime adk ui $(AGENT)

dev-langgraph: mlflow-init
	@$(call TRACK,langgraph) $(OTEL_LOCAL) OTEL_RESOURCE_ATTRIBUTES=agent.framework=langgraph $(AGENTCTL) --runtime langgraph ui

dev-langchain: mlflow-init
	@$(call TRACK,langgraph) $(OTEL_LOCAL) OTEL_RESOURCE_ATTRIBUTES=agent.framework=langchain $(AGENTCTL) --runtime langchain ui

# 8001: el 8000 es de ADK Dev UI. http://localhost:8001/ describe el servidor;
# /mcp es el endpoint del protocolo, para clientes MCP (un navegador recibe 406).
mcp:
	@$(call TRACK,mcp) $(AGENTCTL) mcp serve --port 8001

# La UI oficial de MCP, conectada a `make mcp`: listar tools y llamarlas a mano.
mcp-inspector:
	@$(call TRACK,mcp-inspector) npx -y @modelcontextprotocol/inspector --web --transport http --server-url http://localhost:8001/mcp

# -- casos de uso ---------------------------------------------------------------
#
# Todos salen de catalog/cases.yaml: `agentctl case N` imprime el comando agentctl
# que ejecuta, para aprenderlo de paso, y dónde verlo en una UI. Lo que el caso
# necesita antes (una imagen, los agentes A2A, un port-forward) lo dice su
# `requires`, y se lanza aquí.
#
#   make caso-3                                   con su mensaje de ejemplo
#   make caso-3 MSG="Una función que ..."         con el tuyo
#   make caso-3 RUNTIME=langgraph                 en otro framework (adk | langgraph | langchain)

casos:
	@if [ -x $(AGENTCTL) ]; then $(AGENTCTL) case; else echo "  Primero: make install"; fi

# Tu MSG gana al del caso; si no pasas ninguno, el de ejemplo.
CASO_FLAGS = $(if $(RUNTIME),--runtime $(RUNTIME) )$(if $(ENV),--env $(ENV) )
CASO_MSG   = $(if $(filter command line environment,$(origin MSG)),-m "$(MSG)")

caso-%:
	@for target in $$($(AGENTCTL) case $* --requires) ; do \
	  $(MAKE) --no-print-directory $$target || exit 1; \
	done
	@$(OTEL_LOCAL) $(AGENTCTL) $(CASO_FLAGS)case $* $(CASO_MSG)
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
	  echo "  Trazas de Langflow -> $(MLFLOW_URL)/$(HASH)/experiments/0/traces, unidas a las de los agentes"; \
	fi
	@$(LANGFLOW_COMPOSE) up -d
	@echo "  Esperando a Langflow en $(LANGFLOW_URL)..."
	@for i in $$(seq 1 90); do curl -sf -o /dev/null $(LANGFLOW_URL)/health && break; sleep 2; done
	@$(MAKE) --no-print-directory langflow-url

langflow-url:
	@echo "  Langflow: $(LANGFLOW_URL)   usuario: admin   clave: $$(sed -n 's/^LANGFLOW_SUPERUSER_PASSWORD=//p' $(LANGFLOW_ENV))"
	@echo "  Los agentes, por A2A: make a2a-catalog   ·   un flujo del catálogo: agentctl --env local-a2a langflow export tech-article"

langflow-down:
	$(LANGFLOW_COMPOSE) down

# -- carril A2A local -----------------------------------------------------------
#
# Los mismos tres agentes que en kagent, cada uno en un framework y los
# sub-agentes en otro proceso: la delegación viaja por A2A de verdad. Ningún
# manifiesto cambia. configs/environments/local-a2a.yaml dice dónde está cada
# uno, y `a2a serve` escucha en ese mismo puerto: el orden de estas listas da igual.

A2A_AGENTS ?= python-developer:langgraph code-reviewer:langchain data-provider:langgraph
# El que coordina: software-manager (ingeniería) o data-consumer (dataspace).
A2A_AGENT  ?= software-manager
A2A_LOG    := .agent-platform/a2a.log

# Todo lo que local-a2a.yaml declara: lo que Langflow necesita para llamar a
# cualquier agente del catálogo.
A2A_CATALOG ?= python-developer:langgraph code-reviewer:langchain data-provider:langgraph \
               tech-researcher tech-writer tech-explainer release-manager software-manager
a2a-catalog:
	@$(MAKE) --no-print-directory a2a-up A2A_AGENTS="$(A2A_CATALOG)"

a2a-up:
	@$(call TRACK,a2a) $(OTEL_LOCAL) $(AGENTCTL) a2a serve $(A2A_AGENTS) -v

# Lo que usan caso-7 y caso-8: los agentes A2A que no respondan se levantan en
# segundo plano. Si ya los tienes en otra terminal (make a2a-up), se usan esos.
a2a-ensure:
	@missing="$$($(AGENTCTL) a2a ping $(A2A_AGENTS) --missing)"; \
	if [ -z "$$missing" ]; then \
	  echo "  A2A: usando los agentes que ya responden ($(A2A_AGENTS))"; \
	else \
	  mkdir -p $(PIDS); \
	  echo "  A2A: levantando $$missing en segundo plano (log: $(A2A_LOG) · parar: make a2a-down)"; \
	  $(OTEL_LOCAL) nohup $(AGENTCTL) a2a serve $$missing -v > $(A2A_LOG) 2>&1 </dev/null & echo $$! > $(PIDS)/a2a.bg.pid; \
	  $(AGENTCTL) a2a ping $$missing --wait 60 -q || { echo "  A2A: no arrancaron en 60 s; mira $(A2A_LOG)"; exit 1; }; \
	fi

a2a-down:
	@$(STACK) down a2a

a2a-run:
	$(OTEL_LOCAL) $(AGENTCTL) --env local-a2a run $(A2A_AGENT) -v -m "$(MSG)"

a2a-cards:
	@$(AGENTCTL) a2a ping

# El controlador de kagent atiende A2A para todos los agentes del clúster.
# El port-forward queda en segundo plano; después, por ejemplo:
#   agentctl a2a send http://localhost:8083/api/a2a/kagent/software-manager/ -m "..."
kagent-a2a:
	@$(KUBECTL) -n kagent get deploy kagent-controller >/dev/null 2>&1 || \
	  { echo "  kagent no está en $(KUBE_CONTEXT): make lab"; exit 1; }
	@ss -ltn 2>/dev/null | grep -q ':8083 ' || \
	  { $(KUBECTL) -n kagent port-forward svc/kagent-controller 8083:8083 >/dev/null 2>&1 & sleep 2; }
	@$(AGENTCTL) a2a card http://localhost:8083/api/a2a/kagent/software-manager/ >/dev/null 2>&1 || \
	  { echo "  software-manager no responde en kagent: make deploy"; exit 1; }
	@echo "  kagent A2A: http://localhost:8083/api/a2a/kagent/<agente>/"

# -- carril clúster -------------------------------------------------------------

lab:
	@$(DOCTOR) helm
	@$(MAKE) --no-print-directory cluster-up images platform deploy status

cluster-up:
	CLUSTER=$(CLUSTER) deploy/scripts/cluster-up.sh

images: skills
	docker build --network host -t $(REGISTRY)/agent-platform/mlflow:3.17.2 -f deploy/images/Dockerfile.mlflow deploy/images
	docker build --network host -t $(REGISTRY)/agent-platform/mcp:$(TAG) -f deploy/images/Dockerfile.mcp .
	docker build --network host -t $(REGISTRY)/agent-platform/agent-host:$(TAG) -f deploy/images/Dockerfile.agent-host .
	docker push -q $(REGISTRY)/agent-platform/mlflow:3.17.2
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

# helm y ArgoCD no pueden gestionar el mismo clúster: la guarda lo impide.
platform:
	@$(DOCTOR) helm -q
	$(KUBECTL) apply -k deploy/observability
	$(HELM) upgrade --install kagent-crds $(KAGENT_OCI)/kagent-crds --version $(KAGENT_VERSION) -n kagent --wait
	$(HELM) upgrade --install kagent $(KAGENT_OCI)/kagent --version $(KAGENT_VERSION) -n kagent \
	  -f deploy/kagent/values.yaml --wait --timeout 10m
	$(KUBECTL) apply -f deploy/kagent/ui-nodeport.yaml
	$(KUBECTL) -n observability rollout status deploy/mlflow --timeout=5m
	$(AGENTCTL) mlflow init

render:
	$(AGENTCTL) kagent render

# -- GitOps -------------------------------------------------------------------
#
# Lo mismo que `make platform`, pero declarativo: ArgoCD sincroniza
# deploy/gitops/overlays/lab desde GitHub. Una cosa o la otra en un clúster, no
# las dos: ArgoCD y helm se disputarían los mismos releases (doctor lo comprueba).
ARGOCD_VERSION ?= v3.5.4
# La rama (subida) que sincroniza el lab: root-lab.yaml la lleva a todas las fuentes git.
GITOPS_REVISION ?= main
export GITOPS_REVISION

gitops-check:
	@for o in prod lab; do kubectl kustomize deploy/gitops/overlays/$$o >/dev/null && echo "  overlay $$o: ok"; done

gitops-lab:
	@$(DOCTOR) gitops
	@$(MAKE) --no-print-directory cluster-up images
	$(KUBECTL) create namespace argocd --dry-run=client -o yaml | $(KUBECTL) apply -f - >/dev/null
	$(KUBECTL) apply --server-side --force-conflicts -n argocd \
	  -f https://raw.githubusercontent.com/argoproj/argo-cd/$(ARGOCD_VERSION)/manifests/install.yaml >/dev/null
	$(KUBECTL) -n argocd wait --for=condition=Available deployment/argocd-server --timeout=5m >/dev/null
	@# La clave de Grafana no vive en git: se genera una por clúster.
	@$(KUBECTL) create namespace monitoring --dry-run=client -o yaml | $(KUBECTL) apply -f - >/dev/null
	@$(KUBECTL) -n monitoring get secret grafana-admin >/dev/null 2>&1 || \
	  $(KUBECTL) -n monitoring create secret generic grafana-admin \
	    --from-literal=admin-user=admin --from-literal=admin-password="$$(openssl rand -hex 12)" >/dev/null
	$(KUBECTL) apply -f deploy/gitops/bootstrap/project.yaml -f deploy/gitops/bootstrap/repositories.yaml
	sed 's|value: main }|value: $(GITOPS_REVISION) }|; s|targetRevision: main|targetRevision: $(GITOPS_REVISION)|' \
	  deploy/gitops/bootstrap/root-lab.yaml | $(KUBECTL) apply -f -
	@echo "  ArgoCD sincroniza deploy/gitops/overlays/lab. Después: make deploy (los agentes) y $(AGENTCTL) mlflow init"
	@echo "  Sus UIs: make argocd · make grafana · y make status para ver qué ya responde"

# Port-forward en segundo plano y la clave, para no tener que buscarla.
# Las UIs de ArgoCD y Grafana sólo existen con make gitops-lab.
argocd:
	@$(KUBECTL) -n argocd get deploy argocd-server >/dev/null 2>&1 || \
	  { echo "  ArgoCD no está en $(KUBE_CONTEXT): make gitops-lab"; exit 1; }
	@ss -ltn 2>/dev/null | grep -q ':8443 ' || \
	  { $(KUBECTL) -n argocd port-forward svc/argocd-server 8443:443 >/dev/null 2>&1 & sleep 2; }
	@echo "  ArgoCD: https://localhost:8443   usuario: admin   clave: $$($(KUBECTL) -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d)"

grafana:
	@$(KUBECTL) -n monitoring get deploy monitoring-grafana >/dev/null 2>&1 || \
	  { echo "  Grafana no está en $(KUBE_CONTEXT): sólo viene con make gitops-lab"; exit 1; }
	@ss -ltn 2>/dev/null | grep -q ':3000 ' || \
	  { $(KUBECTL) -n monitoring port-forward svc/monitoring-grafana 3000:80 >/dev/null 2>&1 & sleep 2; }
	@echo "  Grafana: http://localhost:3000   usuario: admin   clave: $$($(KUBECTL) -n monitoring get secret grafana-admin -o jsonpath='{.data.admin-password}' | base64 -d)"

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

cluster-status:
	$(KUBECTL) -n kagent get agents,remotemcpservers,modelconfigs
	$(KUBECTL) -n kagent get pods
	$(KUBECTL) -n observability get pods

cluster-down:
	kind delete cluster --name $(CLUSTER)
	docker rm -f agent-registry >/dev/null 2>&1 || true

clean:
	rm -rf $(VENV) .pytest_cache .agent-platform langgraph.json
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	find platform -name '*.egg-info' -type d -prune -exec rm -rf {} +
