#!/usr/bin/env bash
#
# Levanta el laboratorio: registro local, clúster kind y los Secrets que no
# pueden vivir en git. Idempotente: se puede relanzar sobre un clúster vivo.
#
set -euo pipefail

CLUSTER="${CLUSTER:-agent-lab}"
REGISTRY="${REGISTRY:-agent-registry}"
REGISTRY_PORT="${REGISTRY_PORT:-5001}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

paso() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

paso "Registro local ${REGISTRY} (localhost:${REGISTRY_PORT})"
if [ "$(docker inspect -f '{{.State.Running}}' "${REGISTRY}" 2>/dev/null || true)" != "true" ]; then
  docker run -d --restart=always -p "127.0.0.1:${REGISTRY_PORT}:5000" --name "${REGISTRY}" registry:2 >/dev/null
fi
echo "    ok"

paso "Clúster kind '${CLUSTER}'"
if kind get clusters 2>/dev/null | grep -qx "${CLUSTER}"; then
  echo "    ya existe; se reutiliza"
else
  kind create cluster --config "${ROOT}/deploy/kind/cluster.yaml"
fi
kubectl config use-context "kind-${CLUSTER}" >/dev/null

paso "containerd: localhost:${REGISTRY_PORT} -> ${REGISTRY}:5000"
# Mismo registro, dos nombres: el host empuja a localhost:5001; el nodo y los
# pods lo ven como agent-registry:5000 dentro de la red de kind.
docker network connect kind "${REGISTRY}" 2>/dev/null || true
for node in $(kind get nodes --name "${CLUSTER}"); do
  docker exec "${node}" mkdir -p "/etc/containerd/certs.d/localhost:${REGISTRY_PORT}" \
    "/etc/containerd/certs.d/${REGISTRY}:5000"
  printf '[host."http://%s:5000"]\n' "${REGISTRY}" | docker exec -i "${node}" \
    cp /dev/stdin "/etc/containerd/certs.d/localhost:${REGISTRY_PORT}/hosts.toml"
  printf 'server = "http://%s:5000"\n[host."http://%s:5000"]\n  skip_verify = true\n' "${REGISTRY}" "${REGISTRY}" \
    | docker exec -i "${node}" cp /dev/stdin "/etc/containerd/certs.d/${REGISTRY}:5000/hosts.toml"
done
echo "    ok"

paso "Namespaces, CA del host y Secrets"
kubectl apply -k "${ROOT}/deploy/base" >/dev/null
for ns in kagent observability; do
  kubectl -n "${ns}" create configmap host-ca \
    --from-file=ca-certificates.crt=/etc/ssl/certs/ca-certificates.crt \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null
done

# La clave de Gemini sale de .env; nunca se escribe en un fichero del repo.
set -a; [ -f "${ROOT}/.env" ] && . "${ROOT}/.env"; set +a
KEY="${GOOGLE_API_KEY:-${GEMINI_API_KEY:-}}"
if [ -n "${KEY}" ] && [ "${KEY}" != "your_gemini_api_key_here" ]; then
  kubectl -n kagent create secret generic kagent-gemini --from-literal=GOOGLE_API_KEY="${KEY}" \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  echo "    Secret kagent-gemini: ok"
else
  echo "    AVISO: sin GOOGLE_API_KEY en .env; los agentes arrancarán pero no podrán llamar al modelo."
  kubectl -n kagent create secret generic kagent-gemini --from-literal=GOOGLE_API_KEY=missing \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null
fi
