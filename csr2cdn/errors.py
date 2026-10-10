"""Exceptions raised by csr2cdn."""


class Csr2CdnError(Exception):
    """Base class for every error raised by this package."""


class DatabaseFormatError(Csr2CdnError, ValueError):
    """An asset database is not in the expected ``[header, [assets]]`` shape."""


class AssetNotFoundError(Csr2CdnError, KeyError):
    """No asset with the requested code or alias exists in the database."""

    def __str__(self) -> str:  # KeyError would otherwise repr() the message
        return self.args[0] if self.args else ""


class MetadataError(Csr2CdnError):
    """The metadata service answered with an unexpected response code."""

    def __init__(self, message: str, response_code=None, response_message=None):
        super().__init__(message)
        self.response_code = response_code
        self.response_message = response_message


class BranchNotFoundError(Csr2CdnError):
    """No reachable asset database branch could be resolved."""


class StoreVersionError(Csr2CdnError):
    """The current app version could not be read from any store source."""


class MissingZidError(Csr2CdnError, ValueError):
    """An operation needs a player id and none was supplied."""
