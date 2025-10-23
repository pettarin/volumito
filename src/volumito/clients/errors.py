"""Exception classes for Volumio clients."""


class VolumioError(Exception):
    """Base exception for Volumio-related errors."""

    pass


class VolumioConnectionError(VolumioError):
    """Exception raised when connection to Volumio instance fails."""

    pass


class VolumioAPIError(VolumioError):
    """Exception raised when Volumio API returns an error."""

    pass
