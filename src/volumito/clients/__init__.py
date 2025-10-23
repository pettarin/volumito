"""Volumio clients package."""

from volumito.clients.errors import (
    VolumioAPIError,
    VolumioConnectionError,
    VolumioError,
)
from volumito.clients.mpd import VolumioMPDClient
from volumito.clients.rest import VolumioRESTAPIClient

__all__ = [
    "VolumioRESTAPIClient",
    "VolumioMPDClient",
    "VolumioError",
    "VolumioConnectionError",
    "VolumioAPIError",
]
