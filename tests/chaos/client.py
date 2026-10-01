"""Toxiproxy REST API client with strict typing, secret protection, and in-memory test simulation (P3.3)."""

from __future__ import annotations

from typing import Any

import httpx

from shared.logging import get_logger
from tests.chaos.config import ChaosConfig, redact_secrets
from tests.chaos.models import ProxyDefinition, Toxic

logger = get_logger("chaos_client")


class ToxiproxyError(RuntimeError):
    """Raised when Toxiproxy API returns an error or connection fails."""


class ToxiproxyClient:
    """Strongly-typed client for the Shopify Toxiproxy HTTP Management API (port 8474).

    Supports:
    - Live HTTP communication with Shopify Toxiproxy daemon via httpx.
    - Deterministic in-memory simulation mode for unit and offline testing.
    - Automatic credential sanitization in logging and error handling.
    """

    def __init__(
        self,
        config: ChaosConfig | None = None,
        use_simulator: bool = False,
    ) -> None:
        self.config = config or ChaosConfig()
        self.use_simulator = use_simulator
        self._simulated_proxies: dict[str, dict[str, Any]] = {}
        self._http_client = httpx.Client(
            base_url=self.config.toxiproxy_url,
            timeout=self.config.request_timeout_sec,
        )

    def close(self) -> None:
        """Close underlying HTTP client session."""
        self._http_client.close()

    def __enter__(self) -> ToxiproxyClient:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def is_server_available(self) -> bool:
        """Probe Toxiproxy server health and reachability."""
        if self.use_simulator:
            return True
        try:
            res = self._http_client.get("/version")
            return res.status_code == 200
        except Exception:
            return False

    def get_version(self) -> str:
        """Return the Toxiproxy daemon server version."""
        if self.use_simulator:
            return "2.11.0-simulated"
        try:
            res = self._http_client.get("/version")
            res.raise_for_status()
            return str(res.text.strip())
        except Exception as exc:
            safe_err = redact_secrets(str(exc))
            raise ToxiproxyError(f"Failed to query Toxiproxy version: {safe_err}") from exc

    def list_proxies(self) -> dict[str, ProxyDefinition]:
        """Fetch all registered proxies from the Toxiproxy server."""
        if self.use_simulator:
            return {name: ProxyDefinition.from_dict(data) for name, data in self._simulated_proxies.items()}
        try:
            res = self._http_client.get("/proxies")
            res.raise_for_status()
            data: dict[str, dict[str, Any]] = res.json()
            return {name: ProxyDefinition.from_dict(p_data) for name, p_data in data.items()}
        except Exception as exc:
            safe_err = redact_secrets(str(exc))
            raise ToxiproxyError(f"Failed to list proxies: {safe_err}") from exc

    def get_proxy(self, proxy_name: str) -> ProxyDefinition:
        """Retrieve details and active toxics for a specific proxy."""
        if self.use_simulator:
            if proxy_name not in self._simulated_proxies:
                raise ToxiproxyError(f"Proxy '{proxy_name}' not found")
            return ProxyDefinition.from_dict(self._simulated_proxies[proxy_name])
        try:
            res = self._http_client.get(f"/proxies/{proxy_name}")
            res.raise_for_status()
            return ProxyDefinition.from_dict(res.json())
        except Exception as exc:
            safe_err = redact_secrets(str(exc))
            raise ToxiproxyError(f"Failed to get proxy '{proxy_name}': {safe_err}") from exc

    def create_proxy(self, definition: ProxyDefinition) -> ProxyDefinition:
        """Register a new proxy on the Toxiproxy server."""
        self.config.validate_safety(definition.upstream)
        if self.use_simulator:
            payload = definition.to_dict()
            payload["toxics"] = []
            self._simulated_proxies[definition.name] = payload
            return definition

        try:
            res = self._http_client.post("/proxies", json=definition.to_dict())
            res.raise_for_status()
            return ProxyDefinition.from_dict(res.json())
        except Exception as exc:
            safe_err = redact_secrets(str(exc))
            raise ToxiproxyError(f"Failed to create proxy '{definition.name}': {safe_err}") from exc

    def populate(self, definitions: list[ProxyDefinition]) -> list[ProxyDefinition]:
        """Populate or update multiple proxies in a single atomic configuration call."""
        for d in definitions:
            self.config.validate_safety(d.upstream)

        if self.use_simulator:
            results: list[ProxyDefinition] = []
            for d in definitions:
                payload = d.to_dict()
                payload["toxics"] = []
                self._simulated_proxies[d.name] = payload
                results.append(d)
            return results

        try:
            payload_list = [d.to_dict() for d in definitions]
            res = self._http_client.post("/populate", json=payload_list)
            res.raise_for_status()
            data = res.json()
            proxies_list: list[dict[str, Any]] = data.get("proxies", [])
            return [ProxyDefinition.from_dict(p) for p in proxies_list]
        except Exception as exc:
            safe_err = redact_secrets(str(exc))
            raise ToxiproxyError(f"Failed to populate proxies: {safe_err}") from exc

    def enable_proxy(self, proxy_name: str) -> ProxyDefinition:
        """Enable network traffic flow through a proxy."""
        return self._set_proxy_enabled(proxy_name, enabled=True)

    def disable_proxy(self, proxy_name: str) -> ProxyDefinition:
        """Disable network traffic flow through a proxy (simulates total dependency outage)."""
        return self._set_proxy_enabled(proxy_name, enabled=False)

    def _set_proxy_enabled(self, proxy_name: str, enabled: bool) -> ProxyDefinition:
        if self.use_simulator:
            if proxy_name not in self._simulated_proxies:
                raise ToxiproxyError(f"Proxy '{proxy_name}' not found")
            self._simulated_proxies[proxy_name]["enabled"] = enabled
            return ProxyDefinition.from_dict(self._simulated_proxies[proxy_name])

        try:
            res = self._http_client.post(f"/proxies/{proxy_name}", json={"enabled": enabled})
            res.raise_for_status()
            return ProxyDefinition.from_dict(res.json())
        except Exception as exc:
            action = "enable" if enabled else "disable"
            safe_err = redact_secrets(str(exc))
            raise ToxiproxyError(f"Failed to {action} proxy '{proxy_name}': {safe_err}") from exc

    def delete_proxy(self, proxy_name: str) -> None:
        """Delete a proxy registration from Toxiproxy."""
        if self.use_simulator:
            self._simulated_proxies.pop(proxy_name, None)
            return

        try:
            res = self._http_client.delete(f"/proxies/{proxy_name}")
            if res.status_code not in (200, 204, 404):
                res.raise_for_status()
        except Exception as exc:
            safe_err = redact_secrets(str(exc))
            raise ToxiproxyError(f"Failed to delete proxy '{proxy_name}': {safe_err}") from exc

    def add_toxic(self, proxy_name: str, toxic: Toxic) -> Toxic:
        """Apply a toxic fault (latency, bandwidth, timeout, reset) to a proxy."""
        if self.use_simulator:
            if proxy_name not in self._simulated_proxies:
                raise ToxiproxyError(f"Proxy '{proxy_name}' not found")
            toxics = self._simulated_proxies[proxy_name].setdefault("toxics", [])
            # Replace existing toxic with same name if present
            toxics[:] = [t for t in toxics if t["name"] != toxic.name]
            toxics.append(toxic.to_dict())
            return toxic

        try:
            res = self._http_client.post(f"/proxies/{proxy_name}/toxics", json=toxic.to_dict())
            res.raise_for_status()
            return Toxic.from_dict(res.json())
        except Exception as exc:
            safe_err = redact_secrets(str(exc))
            raise ToxiproxyError(f"Failed to add toxic '{toxic.name}' to '{proxy_name}': {safe_err}") from exc

    def remove_toxic(self, proxy_name: str, toxic_name: str) -> None:
        """Remove an active toxic fault from a proxy."""
        if self.use_simulator:
            if proxy_name in self._simulated_proxies:
                toxics = self._simulated_proxies[proxy_name].get("toxics", [])
                self._simulated_proxies[proxy_name]["toxics"] = [t for t in toxics if t["name"] != toxic_name]
            return

        try:
            res = self._http_client.delete(f"/proxies/{proxy_name}/toxics/{toxic_name}")
            if res.status_code not in (200, 204, 404):
                res.raise_for_status()
        except Exception as exc:
            safe_err = redact_secrets(str(exc))
            raise ToxiproxyError(f"Failed to remove toxic '{toxic_name}' from '{proxy_name}': {safe_err}") from exc

    def list_toxics(self, proxy_name: str) -> list[Toxic]:
        """List all active toxics configured on a proxy."""
        if self.use_simulator:
            if proxy_name not in self._simulated_proxies:
                raise ToxiproxyError(f"Proxy '{proxy_name}' not found")
            toxics_data = self._simulated_proxies[proxy_name].get("toxics", [])
            return [Toxic.from_dict(t) for t in toxics_data]

        try:
            res = self._http_client.get(f"/proxies/{proxy_name}/toxics")
            res.raise_for_status()
            data: list[dict[str, Any]] = res.json()
            return [Toxic.from_dict(t) for t in data]
        except Exception as exc:
            safe_err = redact_secrets(str(exc))
            raise ToxiproxyError(f"Failed to list toxics for '{proxy_name}': {safe_err}") from exc

    def reset(self) -> None:
        """Global recovery: Enable all proxies and purge all active toxics."""
        if self.use_simulator:
            for p in self._simulated_proxies.values():
                p["enabled"] = True
                p["toxics"] = []
            return

        try:
            res = self._http_client.post("/reset")
            res.raise_for_status()
        except Exception as exc:
            safe_err = redact_secrets(str(exc))
            raise ToxiproxyError(f"Failed to reset Toxiproxy state: {safe_err}") from exc
