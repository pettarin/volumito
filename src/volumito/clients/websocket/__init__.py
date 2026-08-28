"""WebSocket API client for Volumio.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

from volumito.clients.errors import (
    VolumioAPIError,
    VolumioConnectionError,
    VolumioError,
    VolumioWebSocketError,
)
from volumito.clients.websocket.client import VolumioWebSocketClient

__all__ = [
    "VolumioAPIError",
    "VolumioConnectionError",
    "VolumioError",
    "VolumioWebSocketClient",
    "VolumioWebSocketError",
]
