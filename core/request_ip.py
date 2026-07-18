import ipaddress

from django.conf import settings


def ip_client(request) -> str | None:
    header = settings.CLIENT_IP_HEADER
    if header:
        value = request.META.get(header, "")
        candidate = value.split(",", maxsplit=1)[0].strip()
        try:
            return str(ipaddress.ip_address(candidate))
        except ValueError:
            pass

    candidate = request.META.get("REMOTE_ADDR")
    try:
        return str(ipaddress.ip_address(candidate)) if candidate else None
    except ValueError:
        return None
