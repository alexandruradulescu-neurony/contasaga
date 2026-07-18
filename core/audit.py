from dataclasses import dataclass

from .request_ip import ip_client


@dataclass(frozen=True)
class ContextAudit:
    ip_address: str | None = None
    user_agent: str | None = None


def context_audit_din_request(request) -> ContextAudit:
    return ContextAudit(
        ip_address=ip_client(request),
        user_agent=request.META.get("HTTP_USER_AGENT"),
    )
