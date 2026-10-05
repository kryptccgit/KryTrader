from __future__ import annotations

import ssl
from typing import Optional

_ctx: Optional[ssl.SSLContext] = None


def client_context() -> Optional[ssl.SSLContext]:
    global _ctx
    if _ctx is None:
        try:
            import certifi
            _ctx = ssl.create_default_context(cafile=certifi.where())
        except Exception:
            return None
    return _ctx
