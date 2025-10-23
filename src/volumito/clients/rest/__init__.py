"""REST API client for Volumio."""

from volumito.clients.errors import (
    VolumioAPIError,
    VolumioConnectionError,
    VolumioError,
)
from volumito.clients.rest.client import VolumioRESTAPIClient

__all__ = [
    "VolumioRESTAPIClient",
    "VolumioError",
    "VolumioConnectionError",
    "VolumioAPIError",
]
