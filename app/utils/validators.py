"""URL validation + SSRF protection."""
import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

ALLOWED_PORTS = {80, 443}


class InvalidURLError(ValueError):
    pass


class UnsafeURLError(ValueError):
    pass


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def normalize_url(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw or len(raw) > 2048:
        raise InvalidURLError("URL is empty or too long.")
    if "://" not in raw:
        raw = "https://" + raw
    parts = urlsplit(raw)
    if parts.scheme not in ("http", "https"):
        raise InvalidURLError("Only http and https URLs are supported.")
    host = parts.hostname
    if not host or ("." not in host and not _is_ip(host) and host != "localhost"):
        raise InvalidURLError("URL must contain a valid public hostname.")
    if parts.username or parts.password:
        raise InvalidURLError("URLs with credentials are not allowed.")
    try:
        port = parts.port
    except ValueError:
        raise InvalidURLError("Invalid port in URL.")
    if port and port not in ALLOWED_PORTS:
        raise UnsafeURLError("Only ports 80 and 443 are allowed.")
    return parts._replace(fragment="").geturl()


async def assert_public_host(url: str) -> None:
    """Resolve the host and reject private/loopback/link-local/reserved addresses."""
    host = urlsplit(url).hostname or ""
    if _is_ip(host):
        ips = [ipaddress.ip_address(host)]
    else:
        try:
            infos = await asyncio.to_thread(socket.getaddrinfo, host, None, proto=socket.IPPROTO_TCP)
        except socket.gaierror:
            raise InvalidURLError("Host could not be resolved.")
        ips = [ipaddress.ip_address(i[4][0].split("%")[0]) for i in infos]
    for ip in ips:
        if ip.version == 6 and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if not ip.is_global or ip.is_multicast:
            raise UnsafeURLError("URL points to a private or internal network address.")
