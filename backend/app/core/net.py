"""Outbound network safety shared by the HTTP Request node and the agent's HTTP tool.

``ensure_url_allowed`` enforces http/https only and (unless HTTP_ALLOW_PRIVATE_NETWORKS)
blocks private, loopback, link-local, multicast, reserved and unspecified targets after
DNS resolution. Callers re-check it on every redirect hop. Known limitation: the check
happens at resolution time, so DNS rebinding between check and connect is not fully
mitigated.
"""

from __future__ import annotations

import asyncio
import ipaddress

import httpx

from app.core.errors import ErrorCategory, NodeExecutionError


def _ip_is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


async def ensure_url_allowed(url: httpx.URL, allow_private: bool) -> None:
    """Reject non-HTTP schemes and (unless allowed) private/loopback/link-local targets."""
    if url.scheme not in {"http", "https"}:
        raise NodeExecutionError(
            ErrorCategory.SCHEMA_VALIDATION,
            f"Unsupported URL scheme '{url.scheme}'. Only http and https are allowed.",
            field="url",
        )
    host = url.host
    if not host:
        raise NodeExecutionError(ErrorCategory.SCHEMA_VALIDATION, "URL has no host.", field="url")
    if allow_private:
        return
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(host, url.port or (443 if url.scheme == "https" else 80))
        except OSError as exc:
            raise NodeExecutionError(
                ErrorCategory.PROVIDER_ERROR,
                f"Could not resolve host '{host}'.",
                field="url",
                retryable=True,
                technical_detail=str(exc),
            ) from exc
        addresses = [ipaddress.ip_address(info[4][0]) for info in infos]
    for ip in addresses:
        if _ip_is_blocked(ip):
            raise NodeExecutionError(
                ErrorCategory.PERMISSION_DENIED,
                f"Requests to private or local network addresses are blocked ({host} -> {ip}).",
                field="url",
                suggestion="Use a public URL. For local development set HTTP_ALLOW_PRIVATE_NETWORKS=true.",
            )
