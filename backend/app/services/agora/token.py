"""RTC token minting.

Wraps the `agora-token-builder` PyPI package (see docs/AGORA_INTEGRATION.md
§8) so the rest of the codebase never touches token-signing details
directly, and so this can be swapped for a maintained successor without
touching callers if that package is ever replaced.
"""

from __future__ import annotations

import time
from typing import Protocol


class TokenBuildError(Exception):
    pass


class TokenBuilder(Protocol):
    def build_rtc_token(self, channel: str, uid: int, ttl_seconds: int) -> str: ...


class AgoraTokenBuilder:
    def __init__(self, app_id: str, app_certificate: str) -> None:
        if not app_id or not app_certificate:
            raise TokenBuildError("AGORA_APP_ID / AGORA_APP_CERTIFICATE are not configured")
        self._app_id = app_id
        self._app_certificate = app_certificate

    def build_rtc_token(self, channel: str, uid: int, ttl_seconds: int = 3600) -> str:
        from agora_token_builder import RtcTokenBuilder
        from agora_token_builder.RtcTokenBuilder import Role_Publisher

        expire_ts = int(time.time()) + ttl_seconds
        try:
            return RtcTokenBuilder.buildTokenWithUid(
                self._app_id, self._app_certificate, channel, uid, Role_Publisher, expire_ts
            )
        except Exception as e:  # token builder raises plain exceptions on bad input
            raise TokenBuildError(f"Failed to build RTC token: {e}") from e
