"""The shared HTTP session.

Two things matter here. Transient failures (connection resets, 429s, 5xx) are
retried with backoff, because a sync of twenty thousand bundles will hit them.
And a 404 is kept distinct from a failure: a branch that does not exist answers
404, while a branch that could not be reached answers with an exception. Folding
the two together would let a network blip look like "this branch is gone", which
during branch discovery means silently picking the wrong branch.
"""

from __future__ import annotations

from typing import Any, Optional

DEFAULT_RETRIES = 3
DEFAULT_BACKOFF = 0.4
DEFAULT_POOL_SIZE = 16
#: Statuses worth retrying. 404 is deliberately absent.
RETRY_STATUSES = (429, 500, 502, 503, 504)


def build_session(
    retries: int = DEFAULT_RETRIES,
    backoff: float = DEFAULT_BACKOFF,
    pool_size: int = DEFAULT_POOL_SIZE,
) -> Any:
    """A :class:`requests.Session` with retries and a pool sized for threads."""
    import requests
    from requests.adapters import HTTPAdapter

    try:
        from urllib3.util.retry import Retry
    except ImportError:  # pragma: no cover - very old urllib3
        Retry = None

    session = requests.Session()
    if Retry is not None and retries > 0:
        retry = Retry(
            total=retries,
            connect=retries,
            read=retries,
            status=retries,
            backoff_factor=backoff,
            status_forcelist=RETRY_STATUSES,
            allowed_methods=frozenset({"GET", "HEAD", "POST"}),
            raise_on_status=False,
        )
    else:  # pragma: no cover
        retry = None
    adapter = HTTPAdapter(max_retries=retry, pool_connections=pool_size, pool_maxsize=pool_size)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def status_of(error: BaseException) -> Optional[int]:
    """The HTTP status behind an exception, when there is one."""
    response = getattr(error, "response", None)
    return getattr(response, "status_code", None) if response is not None else None


def is_missing(error: BaseException) -> bool:
    """True when the error means "this file is not on the server"."""
    return status_of(error) in (403, 404, 410)


__all__ = [
    "DEFAULT_BACKOFF",
    "DEFAULT_POOL_SIZE",
    "DEFAULT_RETRIES",
    "RETRY_STATUSES",
    "build_session",
    "is_missing",
    "status_of",
]
