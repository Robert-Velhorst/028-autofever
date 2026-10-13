"""Strict origins, never inferred from request forwarding headers."""
import re
from urllib.parse import urlsplit


def https_origin(origin):
    if not isinstance(origin, str) or len(origin) > 300:
        raise ValueError('Explicit canonical HTTPS origin required')
    parsed = urlsplit(origin)
    host = parsed.hostname or ''
    labels = host.split('.')
    if (parsed.scheme != 'https' or len(labels) < 2 or len(host) > 253 or
            any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in labels) or
            re.fullmatch(r'[0-9.]+', host) or
            origin != 'https://' + host + (f':{parsed.port}' if parsed.port not in (None, 0, 443) else '')):
        raise ValueError('Use a canonical HTTPS DNS origin without path or credentials')
    return parsed.netloc
