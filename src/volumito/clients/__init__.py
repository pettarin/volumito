"""Volumio clients package.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

from volumito.clients.entities import Album, Artist, Label, Place
from volumito.clients.errors import (
    VolumioAPIError,
    VolumioConnectionError,
    VolumioError,
    VolumioStoryError,
)
from volumito.clients.host_configuration import Scheme, VolumioHostConfiguration
from volumito.clients.models import (
    CollectionStatistics,
    CommandResponse,
    DeviceState,
    Notification,
    Notifications,
    PlayerState,
    Playlist,
    Playlists,
    Queue,
    QueueTrack,
    Story,
    SuccessResponse,
    SystemInfo,
    SystemVersion,
    VolumioModel,
    Zone,
    Zones,
)
from volumito.clients.mpd import VolumioMPDClient
from volumito.clients.rest import VolumioRESTAPIClient

__all__ = [
    "Album",
    "Artist",
    "Label",
    "Place",
    "Scheme",
    "CollectionStatistics",
    "CommandResponse",
    "DeviceState",
    "Notification",
    "Notifications",
    "PlayerState",
    "Playlist",
    "Playlists",
    "Queue",
    "QueueTrack",
    "Story",
    "SuccessResponse",
    "SystemInfo",
    "SystemVersion",
    "VolumioModel",
    "Zone",
    "Zones",
    "VolumioHostConfiguration",
    "VolumioRESTAPIClient",
    "VolumioMPDClient",
    "VolumioError",
    "VolumioConnectionError",
    "VolumioAPIError",
    "VolumioStoryError",
]
