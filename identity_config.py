"""Per-instance identity-mode configuration.

Configuration is parsed without side effects so imports remain usable in focused
tests. The application lifespan validates it before serving traffic.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _csv(name: str) -> tuple[str, ...]:
    return tuple(value.strip() for value in os.getenv(name, "").split(",") if value.strip())


@dataclass(frozen=True, slots=True)
class IdentityConfig:
    mode: str
    demo_password: str | None
    tenant_id: str | None
    api_client_id: str | None
    allowed_audiences: tuple[str, ...]

    @classmethod
    def from_env(cls) -> "IdentityConfig":
        api_client_id = os.getenv("ENTRA_API_CLIENT_ID") or os.getenv("ENTRA_CLIENT_ID") or None
        audiences = list(_csv("ENTRA_ALLOWED_AUDIENCES") + _csv("ENTRA_API_AUDIENCES"))
        if api_client_id:
            audiences[:0] = [api_client_id, f"api://{api_client_id}"]
        return cls(
            mode=(os.getenv("IDENTITY_MODE") or "").strip().lower(),
            demo_password=os.getenv("DEMO_PASSWORD") or None,
            tenant_id=os.getenv("ENTRA_TENANT_ID") or None,
            api_client_id=api_client_id,
            allowed_audiences=tuple(dict.fromkeys(audiences)),
        )

    def validate(self) -> None:
        if self.mode not in {"demo", "entra"}:
            raise ValueError("IDENTITY_MODE must be exactly 'demo' or 'entra'")
        if self.mode == "demo":
            if not self.demo_password:
                raise ValueError("DEMO_PASSWORD is required when IDENTITY_MODE=demo")
            return
        if not self.tenant_id or not self.allowed_audiences:
            raise ValueError("ENTRA_TENANT_ID and an Entra API audience are required when IDENTITY_MODE=entra")

    @property
    def is_demo(self) -> bool:
        return self.mode == "demo"

    @property
    def is_entra(self) -> bool:
        return self.mode == "entra"
