"""Backend admission policy for the managed Magelloku desktop."""

from __future__ import annotations

from typing import Optional

_MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_BLOCKED_PREFIXES = (
    "/api/skills", "/api/tools", "/api/models", "/api/model/set",
    "/api/providers", "/api/profiles", "/api/mcp", "/api/config",
    "/api/plugins", "/api/local-models",
)


def managed_mutation_denial(method: str, path: str, *, managed: bool) -> Optional[str]:
    """Return a denial message for managed-desktop configuration mutations."""
    if not managed or method.upper() not in _MUTATING:
        return None
    clean = path.split("?", 1)[0].split("#", 1)[0]
    if any(clean == prefix or clean.startswith(prefix + "/") for prefix in _BLOCKED_PREFIXES):
        return "This managed desktop does not allow configuration changes."
    return None


def is_managed_desktop() -> bool:
    import os
    return os.environ.get("HERMES_DESKTOP") == "1" and os.environ.get("HERMES_MANAGED_MODE", "1") != "0"


def install_managed_policy_middleware(app) -> None:
    from fastapi import Request
    from fastapi.responses import JSONResponse

    @app.middleware("http")
    async def managed_policy(request: Request, call_next):
        denial = managed_mutation_denial(request.method, request.url.path, managed=is_managed_desktop())
        if denial:
            return JSONResponse({"detail": denial}, status_code=403)
        return await call_next(request)
