"""volumito - Python client library and CLI tool for Volumio."""

from volumito.clients import (
    VolumioAPIError,
    VolumioConnectionError,
    VolumioError,
    VolumioMPDClient,
    VolumioRESTAPIClient,
)

__version__ = "0.0.1"
__author__ = "Alberto Pettarin"
__email__ = "alberto@albertopettarin.it"

__all__ = [
    "VolumioRESTAPIClient",
    "VolumioMPDClient",
    "VolumioError",
    "VolumioConnectionError",
    "VolumioAPIError",
]
