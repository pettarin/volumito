"""Volumio clients package.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

from volumito.clients.base import VolumioBaseClient
from volumito.clients.entities import (
    Album,
    Artist,
    Label,
    Place,
)
from volumito.clients.errors import (
    VolumioAPIError,
    VolumioAsyncError,
    VolumioConnectionError,
    VolumioError,
    VolumioSCPError,
    VolumioSSHError,
    VolumioStoryError,
    VolumioWebSocketError,
)
from volumito.clients.host_configuration import (
    Scheme,
    VolumioHostConfiguration,
)
from volumito.clients.listener import (
    NotificationListener,
    receiver_url,
)
from volumito.clients.models import (
    BrowseResults,
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
    SearchResultItemKind,
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
from volumito.clients.rest import (
    VolumioAsyncRESTAPIClient,
    VolumioRESTAPIClient,
)
from volumito.clients.websocket import (
    VolumioAsyncWebSocketClient,
    VolumioWebSocketClient,
)

__all__ = [
    "Album",
    "Artist",
    "BrowseResults",
    "CollectionStatistics",
    "CommandResponse",
    "DeviceState",
    "Label",
    "Notification",
    "NotificationListener",
    "Notifications",
    "Place",
    "PlayerState",
    "Playlist",
    "Playlists",
    "PushNotification",
    "Queue",
    "QueueTrack",
    "RemoteCommandResult",
    "Scheme",
    "SearchResultItem",
    "SearchResultItemKind",
    "SearchResultList",
    "SearchResults",
    "Story",
    "SuccessResponse",
    "SystemInfo",
    "SystemVersion",
    "VOLUMIO_INTERNAL_ROOT",
    "VOLUMIO_MNT_ROOT",
    "VolumioAPIError",
    "VolumioAsyncError",
    "VolumioAsyncRESTAPIClient",
    "VolumioAsyncWebSocketClient",
    "VolumioBaseClient",
    "VolumioConnectionError",
    "VolumioError",
    "VolumioHostConfiguration",
    "VolumioMPDClient",
    "VolumioModel",
    "VolumioRESTAPIClient",
    "VolumioSCPError",
    "VolumioSSHError",
    "VolumioStoryError",
    "VolumioWebSocketClient",
    "VolumioWebSocketError",
    "Zone",
    "Zones",
    "copy_from_host",
    "copy_to_host",
    "execute_on_host",
    "is_local_file_uri",
    "receiver_url",
    "remote_music_path",
]
