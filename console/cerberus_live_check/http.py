"""HTTPS fetch and the TLS version probe. Standard library only; no program is run."""

import socket
import ssl
import urllib.error
import urllib.request
from urllib.parse import urlsplit

TIMEOUT_S = 20

# Client-side wording: the local OpenSSL cannot offer this protocol at all.
_LOCAL = ("NO_PROTOCOLS_AVAILABLE", "NO_CIPHERS_AVAILABLE", "UNSUPPORTED_PROTOCOL")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Report a redirect as its own status instead of following it."""

    def redirect_request(self, *args, **kwargs):
        return None


def fetch(
    url: str,
    method: str = "GET",
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    follow: bool = False,
) -> tuple[int, dict[str, str], bytes]:
    """https only. Returns (status, lower-case headers, body). An HTTP error is a status."""
    if urlsplit(url).scheme != "https":
        raise ValueError("https only")
    request = urllib.request.Request(url, data=data, method=method, headers=headers or {})  # noqa: S310
    opener = urllib.request.build_opener() if follow else urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=TIMEOUT_S) as response:  # noqa: S310
            return response.status, _lower(response.headers), response.read(1_000_000)
    except urllib.error.HTTPError as err:
        return err.code, _lower(err.headers), err.read(1_000_000)


def _lower(headers) -> dict[str, str]:
    return {k.lower(): v for k, v in headers.items()}


def host_of(url: str) -> str:
    return urlsplit(url).hostname or ""


def tls_probe(host: str) -> dict[str, str]:
    """Offer one TLS version at a time. Each result is accepted, refused or untestable-locally.

    SECLEVEL=0 lets the client offer the old protocols. A local OpenSSL build can still refuse
    to: that is "untestable-locally", not a finding about the server.
    """
    versions = {
        "TLS1.0": ssl.TLSVersion.TLSv1,
        "TLS1.1": ssl.TLSVersion.TLSv1_1,
        "TLS1.2": ssl.TLSVersion.TLSv1_2,
    }
    results = {}
    for label, version in versions.items():
        results[label] = _probe_one(host, version)
    return results


def _probe_one(host: str, version: ssl.TLSVersion) -> str:
    # The point is to see which protocol the server accepts, not to trust the server,
    # so the certificate is not checked here.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        context.set_ciphers("DEFAULT:@SECLEVEL=0")
        context.minimum_version = version
        context.maximum_version = version
    except (ssl.SSLError, ValueError):
        return "untestable-locally"
    try:
        with socket.create_connection((host, 443), timeout=TIMEOUT_S) as raw:
            with context.wrap_socket(raw, server_hostname=host) as tls:
                return f"accepted ({tls.version()})"
    except ssl.SSLError as err:
        reason = str(err)
        if any(word in reason for word in _LOCAL):
            return "untestable-locally"
        return f"refused ({err.reason or 'alert'})"
    except (ConnectionResetError, EOFError):
        return "refused (connection closed)"
    except OSError as err:
        return f"error ({type(err).__name__})"
