"""Agora Conversational AI Engine REST client.

/join is VERIFIED against a real project (see docs/AGORA_INTEGRATION.md
§3): a real call returned 200 with a genuine agent_id.

/leave's shape was originally guessed as `POST {base}/leave` with
agent_id in the body. A real call against it returned a routing 404
("no Route matched with those values"). A direct docs fetch corrected it
to `POST {base}/agents/{agent_id}/leave` (agent_id as a path parameter,
not a body field) — fixed here. A real call against the corrected
endpoint returned a *different*, structured error
(`{"reason": "TaskNotFound", ...}`) rather than a routing 404, which is
strong evidence the endpoint/shape is now correct — the specific agent
being targeted had already ended on its own (no participant ever joined
that test session) by the time this was retried, so a full
successful-leave-on-an-active-session has not been directly observed.
Isolated here so a further correction, if needed, is a one-file change.
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
                f"{self._base_url}/agents/{agent_id}/leave",
                auth=self._auth,
                timeout=15.0,
            )
        except httpx.HTTPError as e:
            raise AgoraRestError(f"Agora /leave call failed: {e}") from e

        if response.status_code >= 400:
            raise AgoraRestError(
                f"Agora /leave returned {response.status_code}: {response.text[:500]}"
            )
