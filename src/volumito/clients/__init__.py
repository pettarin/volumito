"""Volumio clients package.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

from volumito.clients.entities import Album, Artist, Label, Place
from volumito.clients.errors import (
    VolumioAPIError,
    VolumioConnectionError,
    VolumioError,
    VolumioSCPError,
    VolumioSSHError,
    VolumioStoryError,
)
from volumito.clients.host_configuration import Scheme, VolumioHostConfiguration
from volumito.clients.listener import NotificationListener, receiver_url
from volumito.clients.models import (
    CollectionStatistics,
    CommandResponse,
    DeviceState,
    Notification,
    Notifications,
    PlayerState,
    Playlist,
    Playlists,
    PushNotification,
    Queue,
    QueueTrack,
    SearchResultItem,
    SearchResultList,
    SearchResults,
    Story,
    SuccessResponse,
    SystemInfo,
    SystemVersion,
    VolumioModel,
    Zone,
    Zones,
)
from volumito.clients.mpd import VolumioMPDClient
from volumito.clients.remote import (
    VOLUMIO_INTERNAL_ROOT,
    VOLUMIO_MNT_ROOT,
    RemoteCommandResult,
    copy_from_host,
    copy_to_host,
    execute_on_host,
    is_local_file_uri,
    remote_music_path,
)
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
    "PushNotification",
    "Queue",
    "QueueTrack",
    "SearchResultItem",
    "SearchResultList",
    "SearchResults",
    "Story",
    "SuccessResponse",
    "SystemInfo",
    "SystemVersion",
    "VolumioModel",
    "Zone",
    "Zones",
    "NotificationListener",
    "receiver_url",
    "VOLUMIO_INTERNAL_ROOT",
    "VOLUMIO_MNT_ROOT",
    "RemoteCommandResult",
    "copy_from_host",
    "copy_to_host",
    "execute_on_host",
    "is_local_file_uri",
    "remote_music_path",
    "VolumioHostConfiguration",
    "VolumioRESTAPIClient",
    "VolumioMPDClient",
    "VolumioError",
    "VolumioConnectionError",
    "VolumioAPIError",
    "VolumioSCPError",
    "VolumioSSHError",
    "VolumioStoryError",
]
