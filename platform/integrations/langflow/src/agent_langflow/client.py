"""The few Langflow REST calls the export needs: log in, read the catalogue, create a flow."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx

from agent_core.errors import PlatformError

DEFAULT_URL = "http://127.0.0.1:7860"
#: Where `make langflow-up` leaves the generated credentials.
CREDENTIALS_FILE = Path(".agent-platform/langflow.env")


class LangflowError(PlatformError):
    """Langflow could not be reached, or refused a request."""


class Langflow:
    """A logged-in Langflow API. Credentials: LANGFLOW_API_KEY, or the superuser of `make langflow-up`."""

    def __init__(self, url: str | None = None, *, root: Path | None = None, timeout: float = 60) -> None:
        self.url = (url or os.getenv("LANGFLOW_URL") or DEFAULT_URL).rstrip("/")
        self.http = httpx.Client(base_url=self.url, timeout=timeout)
        self.http.headers.update(self._auth(root or Path.cwd()))

    def catalogue(self) -> dict[str, Any]:
        return self._call("GET", "/api/v1/all")

    def create_flow(self, flow: dict[str, Any]) -> dict[str, Any]:
        """Create the flow; an existing flow with the same name is replaced, so a re-export updates it."""
        for existing in self._call("GET", "/api/v1/flows/", params={"remove_example_flows": True,
                                                                    "header_flows": True}):
            if existing.get("name") == flow["name"]:
                self._call("DELETE", f"/api/v1/flows/{existing['id']}")
        return self._call("POST", "/api/v1/flows/", json=flow)

    def run(self, flow_id: str, message: str, *, timeout: float) -> dict[str, Any]:
        """Run a flow once. `/api/v1/run` takes an API key, not a session token."""
        return self._call("POST", f"/api/v1/run/{flow_id}", params={"stream": False},
                          headers={"x-api-key": self._api_key()}, timeout=timeout,
                          json={"input_value": message, "input_type": "chat", "output_type": "chat"})

    def _api_key(self) -> str:
        if key := os.getenv("LANGFLOW_API_KEY") or _read_env(self._credentials).get("LANGFLOW_API_KEY"):
            return key
        key = self._call("POST", "/api/v1/api_key/", json={"name": "agentctl"})["api_key"]
        with self._credentials.open("a", encoding="utf-8") as handle:
            handle.write(f"LANGFLOW_API_KEY={key}\n")
        return key

    def _auth(self, root: Path) -> dict[str, str]:
        self._credentials = root / CREDENTIALS_FILE
        if key := os.getenv("LANGFLOW_API_KEY"):
            return {"x-api-key": key}
        values = _read_env(self._credentials)
        user, password = values.get("LANGFLOW_SUPERUSER"), values.get("LANGFLOW_SUPERUSER_PASSWORD")
        if not (user and password):
            raise LangflowError(
                "no Langflow credentials: set LANGFLOW_API_KEY, or start it with `make langflow-up`, "
                f"which writes them to {CREDENTIALS_FILE}"
            )
        token = self._call("POST", "/api/v1/login", data={"username": user, "password": password})
        return {"Authorization": f"Bearer {token['access_token']}"}

    def _call(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self.http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise LangflowError(f"could not reach Langflow at {self.url} ({exc}). Is it up? `make langflow-up`") from exc
        if response.status_code >= 400:
            raise LangflowError(f"Langflow answered {response.status_code} to {method} {path}: {response.text[:300]}")
        return response.json() if response.content else {}


def _read_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    pairs = (line.split("=", 1) for line in path.read_text().splitlines() if "=" in line and not line.startswith("#"))
    return {key.strip(): value.strip() for key, value in pairs}
