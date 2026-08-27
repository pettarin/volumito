"""REST API client for Volumio.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

from volumito.clients.errors import (
    VolumioAPIError,
    VolumioAsyncError,
    VolumioConnectionError,
    VolumioError,
)
from volumito.clients.rest.asyncclient import VolumioAsyncRESTAPIClient
from volumito.clients.rest.client import VolumioRESTAPIClient

__all__ = [
    "VolumioAsyncRESTAPIClient",
    "VolumioRESTAPIClient",
    "VolumioError",
    "VolumioConnectionError",
    "VolumioAPIError",
    "VolumioAsyncError",
]
