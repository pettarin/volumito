"""Volumio clients package.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

from volumito.clients.errors import (
    VolumioAPIError,
    VolumioConnectionError,
    VolumioError,
)
from volumito.clients.host_configuration import VolumioHostConfiguration
from volumito.clients.mpd import VolumioMPDClient
from volumito.clients.rest import VolumioRESTAPIClient

__all__ = [
    "VolumioHostConfiguration",
    "VolumioRESTAPIClient",
    "VolumioMPDClient",
    "VolumioError",
    "VolumioConnectionError",
    "VolumioAPIError",
]
