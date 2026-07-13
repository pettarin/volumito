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
