"""Agora Conversational AI Engine REST client — /join is VERIFIED (see
docs/AGORA_INTEGRATION.md §3); /leave's exact body shape is best-effort
(§1) and should be spot-checked against a live project before relying on
it. Isolated here so a correction is a one-file change.
"""

from __future__ import annotations

from typing import Protocol

import httpx


class AgoraRestError(Exception):
    pass


class AgoraConversationalAIClient(Protocol):
    def join(self, name: str, properties: dict) -> dict: ...
    def leave(self, agent_id: str) -> None: ...


class HttpxAgoraConversationalAIClient:
    def __init__(self, app_id: str, customer_key: str, customer_secret: str, base_url: str) -> None:
        if not app_id:
            raise AgoraRestError("AGORA_APP_ID is not configured")
        if not customer_key or not customer_secret:
            raise AgoraRestError("AGORA_CUSTOMER_KEY / AGORA_CUSTOMER_SECRET are not configured")
        self._base_url = f"{base_url.rstrip('/')}/projects/{app_id}"
        self._auth = (customer_key, customer_secret)

    def join(self, name: str, properties: dict) -> dict:
        try:
            response = httpx.post(
                f"{self._base_url}/join",
                json={"name": name, "properties": properties},
                auth=self._auth,
                timeout=15.0,
            )
        except httpx.HTTPError as e:
            raise AgoraRestError(f"Agora /join call failed: {e}") from e

        if response.status_code >= 400:
            raise AgoraRestError(
                f"Agora /join returned {response.status_code}: {response.text[:500]}"
            )
        return response.json()

    def leave(self, agent_id: str) -> None:
        try:
            response = httpx.post(
                f"{self._base_url}/leave",
                json={"agent_id": agent_id},
                auth=self._auth,
                timeout=15.0,
            )
        except httpx.HTTPError as e:
            raise AgoraRestError(f"Agora /leave call failed: {e}") from e

        if response.status_code >= 400:
            raise AgoraRestError(
                f"Agora /leave returned {response.status_code}: {response.text[:500]}"
            )
