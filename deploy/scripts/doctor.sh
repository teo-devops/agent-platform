#!/usr/bin/env bash
#
# ¿Está todo lo que hace falta? Antes de descubrirlo a mitad de un `make lab`.
#
#   doctor.sh            todo, sólo informa: ✗ lo que impide empezar, ! lo que falta para un carril
#   doctor.sh helm       antes de `make lab` / `make platform`: falla si falta algo del clúster
#   doctor.sh gitops     antes de `make gitops-lab`: ídem, y ArgoCD en vez de helm
#   doctor.sh helm -q    sólo los ✗ (lo que usa `make platform` como guarda)
#
# Un clúster lo gestiona helm (make lab) o ArgoCD (make gitops-lab), nunca los
# dos: se disputarían los mismos releases. En los modos helm y gitops eso es un ✗.
#
set -uo pipefail

MODE="${1:-all}"
QUIET="${2:-}"
CLUSTER="${CLUSTER:-agent-lab}"
CONTEXT="${KUBE_CONTEXT:-kind-${CLUSTER}}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV="${VENV:-${ROOT}/.venv}"
FALLOS=0

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  OK=$'\033[32m✓\033[0m'; KO=$'\033[31m✗\033[0m'; AV=$'\033[33m!\033[0m'; B=$'\033[1m'; N=$'\033[0m'
else
  OK='✓'; KO='✗'; AV='!'; B=''; N=''
fi
titulo() { [ -n "${QUIET}" ] || printf '\n%s%s%s\n' "$B" "$1" "$N"; }

ok()    { [ -n "${QUIET}" ] || printf '  %s %-22s %s\n' "$OK" "$1" "${2:-}"; }
falla() { printf '  %s %-22s %s\n' "$KO" "$1" "$2"; FALLOS=$((FALLOS + 1)); }
aviso() { [ -n "${QUIET}" ] || printf '  %s %-22s %s\n' "$AV" "$1" "$2"; }

# Falla en los modos que lo necesitan; en `all` sólo avisa.
hace_falta() {  # <modos que lo exigen> <nombre> <mensaje>
  case " $1 " in *" ${MODE} "*) falla "$2" "$3" ;; *) aviso "$2" "$3" ;; esac
}

herramienta() {  # <comando> <modos que lo exigen> <para qué> <cómo ver la versión...>
  local bin="$1" modos="$2" para="$3"; shift 3
  if command -v "${bin}" >/dev/null 2>&1; then
    ok "${bin}" "$("$@" 2>/dev/null | head -1 || true)"
  else
    hace_falta "${modos}" "${bin}" "no está instalado: ${para}"
  fi
}

titulo Base
if [ -x "${VENV}/bin/agentctl" ]; then ok ".venv" "${VENV}"; else falla ".venv" "no existe: make install"; fi

if [ ! -f "${ROOT}/.env" ]; then
  falla ".env" "no existe: cp .env.example .env y pon tu GOOGLE_API_KEY"
else
  KEY="$(sed -n 's/^\(GOOGLE_API_KEY\|GEMINI_API_KEY\)=//p' "${ROOT}/.env" | head -1)"
  if [ -z "${KEY}" ] || [ "${KEY}" = "your_gemini_api_key_here" ]; then
    falla "GOOGLE_API_KEY" "vacía en .env: los agentes no podrán llamar al modelo"
  else
    ok "GOOGLE_API_KEY" "en .env"
  fi
fi

if docker info >/dev/null 2>&1; then ok "docker" "el demonio responde"
else hace_falta "helm gitops" "docker" "no responde: lo necesitan el clúster, Langflow y el caso 10"; fi

titulo Local
for bin in adk langgraph mlflow; do
  if [ -x "${VENV}/bin/${bin}" ]; then ok "${bin}" "en .venv"; else aviso "${bin}" "falta en .venv: make install"; fi
done
if command -v npx >/dev/null 2>&1; then ok "npx" "para make mcp-inspector"
else aviso "npx" "no está: make mcp-inspector no funcionará (instala Node.js)"; fi
if docker compose version >/dev/null 2>&1; then ok "docker compose" "para make langflow-up"
else aviso "docker compose" "no está: make langflow-up no funcionará"; fi

titulo Clúster
herramienta kind    "helm gitops" "https://kind.sigs.k8s.io"                 kind version
herramienta kubectl "helm gitops" "https://kubernetes.io/docs/tasks/tools/"  kubectl version --client
herramienta helm    "helm"        "https://helm.sh/docs/intro/install/"      helm version --short

if command -v kind >/dev/null 2>&1 && kind get clusters 2>/dev/null | grep -qx "${CLUSTER}"; then
  ARGO="$(kubectl --context "${CONTEXT}" --request-timeout=3s -n argocd get applications.argoproj.io -o name 2>/dev/null | head -1)"
  HELM_KAGENT=no
  command -v helm >/dev/null 2>&1 && helm --kube-context "${CONTEXT}" status kagent -n kagent >/dev/null 2>&1 && HELM_KAGENT=yes
  if [ -n "${ARGO}" ]; then
    if [ "${MODE}" = helm ]; then
      falla "${CLUSTER}" "lo gestiona ArgoCD: usa make gitops-lab, o make cluster-down y empieza de cero"
    else ok "${CLUSTER}" "existe; lo gestiona ArgoCD (make gitops-lab)"; fi
  elif [ "${HELM_KAGENT}" = yes ]; then
    if [ "${MODE}" = gitops ]; then
      falla "${CLUSTER}" "kagent está instalado con helm (make lab): make cluster-down antes de make gitops-lab"
    else ok "${CLUSTER}" "existe; lo gestiona helm (make lab)"; fi
  else
    ok "${CLUSTER}" "existe, sin plataforma instalada todavía"
  fi
else
  ok "${CLUSTER}" "no existe todavía: make lab lo crea"
fi

if [ "${MODE}" = gitops ]; then
  REV="${GITOPS_REVISION:-main}"
  if git -C "${ROOT}" ls-remote --exit-code --heads origin "${REV}" >/dev/null 2>&1; then
    ok "rama ${REV}" "está en GitHub: ArgoCD la puede sincronizar"
  else
    falla "rama ${REV}" "no está en origin: ArgoCD sincroniza desde GitHub (git push, o GITOPS_REVISION=<rama>)"
  fi
fi

if [ "${FALLOS}" -gt 0 ]; then
  printf '\n  %s problema(s) que arreglar antes de seguir.\n' "${FALLOS}"
  exit 1
fi
[ -n "${QUIET}" ] && exit 0
echo
case "${MODE}" in
  all) echo "  Listo. Siguiente: make casos (sin clúster) o make lab (kagent en kind). Qué está levantado: make status" ;;
  *)   echo "  Listo para el clúster." ;;
esac
