"""volumito - Python client library and CLI tool for Volumio.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

from volumito.clients import (
    VolumioAPIError,
    VolumioConnectionError,
    VolumioError,
    VolumioHostConfiguration,
    VolumioMPDClient,
    VolumioRESTAPIClient,
)

__version__ = "0.0.10"
__author__ = "Alberto Pettarin"
__email__ = "alberto@albertopettarin.it"

__all__ = [
    "VolumioHostConfiguration",
    "VolumioRESTAPIClient",
    "VolumioMPDClient",
    "VolumioError",
    "VolumioConnectionError",
    "VolumioAPIError",
]
