"""Error classes that decide whether the scheduler retries a failed run."""


class CollectError(Exception):
    """Base class for adapter failures."""


class TransientError(CollectError):
    """Worth retrying later: timeouts, connection errors, HTTP 429 and 5xx."""


class PermanentError(CollectError):
    """Retrying will not help: missing credentials, HTTP 401/403/404, disallowed by robots.txt, bad config."""
