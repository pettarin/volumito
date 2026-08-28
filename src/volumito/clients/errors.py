"""Exception classes for Volumio clients.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""


class VolumioError(Exception):
    """Base exception for Volumio-related errors."""

    pass


class VolumioConnectionError(VolumioError):
    """Exception raised when connection to Volumio instance fails."""

    pass


class VolumioAPIError(VolumioError):
    """Exception raised when Volumio API returns an error."""

    pass


class VolumioAsyncError(VolumioError):
    """Raised when the Volumio host cannot be reached asynchronously."""


class VolumioWebSocketError(VolumioError):
    """Raised when the Volumio host cannot be reached over its WebSocket API."""


class VolumioSSHError(VolumioError):
    """Raised when an SSH connection to the Volumio host fails."""


class VolumioSCPError(VolumioSSHError):
    """Raised when a file cannot be copied from or to the Volumio host over SCP."""


class VolumioStoryError(VolumioAPIError):
    """Exception raised when a Volumio plugin reports a failed story query."""

    pass
