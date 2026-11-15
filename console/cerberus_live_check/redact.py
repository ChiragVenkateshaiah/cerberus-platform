"""Redaction for reports. Pure. Idempotent: redacting twice gives the same text.

The public Cognito hosted-UI host and the expected response headers are not secret,
and none of the patterns below touches them.
"""

import re

_UUID = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_ACCOUNT = re.compile(r"(?<!\d)\d{12}(?!\d)")
_POOL = re.compile(r"\b[a-z]{2}-[a-z]+-\d_[A-Za-z0-9]+\b")
_TOKEN = re.compile(r"eyJ[\w-]+\.[\w-]+\.[\w-]*")
_PARAM = re.compile(r"\b(code|state|client_id|redirect_uri)=(?!<redacted>)[^&\s\"'<>)]*")


def redact(text: str, hosts: dict[str, str] | None = None) -> str:
    """hosts maps a real host name to its placeholder ("d1.cloudfront.net": "<standing-cf>")."""
    out = text
    for host, placeholder in (hosts or {}).items():
        if host:
            out = out.replace(host, placeholder)
    out = _TOKEN.sub("<TOKEN>", out)
    out = _UUID.sub("<UUID>", out)
    out = _POOL.sub("<POOL_ID>", out)
    out = _ACCOUNT.sub("<ACCOUNT_ID>", out)
    return _PARAM.sub(lambda m: m.group(1) + "=<redacted>", out)
