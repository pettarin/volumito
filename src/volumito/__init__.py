"""volumito - Python client library and CLI tool for Volumio.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

from volumito.clients import (
    Album,
    Artist,
    CollectionStatistics,
    CommandResponse,
    DeviceState,
    Label,
    Notification,
    NotificationListener,
    Notifications,
    Place,
    PlayerState,
    Playlist,
    Playlists,
    PushNotification,
    Queue,
    QueueTrack,
    Story,
    SuccessResponse,
    SystemInfo,
    SystemVersion,
    VolumioAPIError,
    VolumioConnectionError,
    VolumioError,
    VolumioHostConfiguration,
    VolumioModel,
    VolumioMPDClient,
    VolumioRESTAPIClient,
    VolumioStoryError,
    Zone,
    Zones,
    receiver_url,
)

__version__ = "0.0.34"
__author__ = "Alberto Pettarin"
__email__ = "alberto@albertopettarin.it"

__all__ = [
    "Album",
    "Artist",
    "Label",
    "Place",
    "CollectionStatistics",
    "CommandResponse",
    "DeviceState",
    "Notification",
    "Notifications",
    "PlayerState",
    "Playlist",
    "Playlists",
    "PushNotification",
    "Queue",
    "QueueTrack",
    "Story",
    "SuccessResponse",
    "SystemInfo",
    "SystemVersion",
    "VolumioModel",
    "Zone",
    "Zones",
    "NotificationListener",
    "receiver_url",
    "VolumioHostConfiguration",
    "VolumioRESTAPIClient",
    "VolumioMPDClient",
    "VolumioError",
    "VolumioConnectionError",
    "VolumioAPIError",
    "VolumioStoryError",
]
