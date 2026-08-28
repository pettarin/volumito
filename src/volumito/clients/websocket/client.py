"""WebSocket API client for Volumio.

The client wraps a Socket.IO connection to a Volumio host. A Volumio host acknowledges
nothing, so a read emits its event and waits for the ``push*`` event carrying the answer;
the reads are serialized, since two of them in flight at once could take each other's
answer. Everything the host pushes on its own -- a playback state on every change above
all -- reaches the handlers registered with :meth:`VolumioWebSocketClient.on`.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

import logging
import threading
import uuid
from collections.abc import Callable
from datetime import timedelta
from types import ModuleType, TracebackType
from typing import Any, Self, cast

from volumito.clients.errors import VolumioWebSocketError
from volumito.clients.host_configuration import VolumioHostConfiguration
from volumito.clients.models import (
    Alarm,
    Alarms,
    AudioOutputs,
    BrowseResults,
    BrowseSources,
    CollectionStatistics,
    DeviceInfo,
    InputSources,
    MenuItems,
    MusicSources,
    NetworkInfo,
    OutputDevices,
    PlayerState,
    Playlist,
    PlaylistContent,
    Playlists,
    Plugins,
    PowerModes,
    Queue,
    QueueTrack,
    SearchResults,
    Share,
    Shares,
    SleepTimer,
    SystemInfo,
    SystemVersion,
    UiConfig,
    UsbDrives,
    WirelessNetworks,
    Zones,
)
from volumito.clients.websocket.common import (
    EVENT_ADD_PLAY,
    EVENT_ADD_PLAY_CUE,
    EVENT_ADD_QUEUE_UIDS,
    EVENT_ADD_SHARE,
    EVENT_ADD_TO_FAVOURITES,
    EVENT_ADD_TO_PLAYLIST,
    EVENT_ADD_TO_QUEUE,
    EVENT_ADD_TO_RADIO_FAVOURITES,
    EVENT_ADD_WEB_RADIO,
    EVENT_AUDIO_OUTPUT_PAUSE,
    EVENT_AUDIO_OUTPUT_PLAY,
    EVENT_BROWSE_LIBRARY,
    EVENT_CALL_METHOD,
    EVENT_CLEAR_QUEUE,
    EVENT_CREATE_PLAYLIST,
    EVENT_DELETE_FOLDER,
    EVENT_DELETE_PLAYLIST,
    EVENT_DELETE_SHARE,
    EVENT_DISABLE_AUDIO_OUTPUT,
    EVENT_DISABLE_PLUGIN,
    EVENT_EDIT_SHARE,
    EVENT_ENABLE_AUDIO_OUTPUT,
    EVENT_ENABLE_DISABLE_MY_MUSIC_PLUGIN,
    EVENT_ENABLE_PLUGIN,
    EVENT_ENQUEUE,
    EVENT_GET_ALARMS,
    EVENT_GET_AUDIO_OUTPUTS,
    EVENT_GET_BROWSE_SOURCES,
    EVENT_GET_DEVICE_HW_UUID,
    EVENT_GET_DEVICE_INFO,
    EVENT_GET_DEVICE_NAME,
    EVENT_GET_DSP_UI_CONFIG,
    EVENT_GET_EXTENDED_OUTPUT_DEVICES,
    EVENT_GET_INFO_NETWORK,
    EVENT_GET_INFO_SHARE,
    EVENT_GET_INPUT_SOURCES,
    EVENT_GET_INSTALLED_PLUGINS,
    EVENT_GET_LAST_PUSHED_BROWSE_LIBRARY,
    EVENT_GET_LIST_SHARES,
    EVENT_GET_MENU_ITEMS,
    EVENT_GET_MULTI_ROOM_DEVICES,
    EVENT_GET_MY_COLLECTION_STATS,
    EVENT_GET_MY_MUSIC_PLUGINS,
    EVENT_GET_NETWORK_SHARES_DISCOVERY,
    EVENT_GET_OUTPUT_DEVICES,
    EVENT_GET_PLAYLIST_CONTENT,
    EVENT_GET_QUEUE,
    EVENT_GET_SHUTDOWN_OR_STANDBY_MODE,
    EVENT_GET_SLEEP,
    EVENT_GET_STATE,
    EVENT_GET_SYSTEM_INFO,
    EVENT_GET_SYSTEM_VERSION,
    EVENT_GET_UI_CONFIG,
    EVENT_GET_WIRELESS_NETWORKS,
    EVENT_GET_WIRELESS_NETWORKS_CACHE,
    EVENT_GO_TO,
    EVENT_IMPORT_SERVICE_PLAYLISTS,
    EVENT_INSTALL_PLUGIN,
    EVENT_LIST_PLAYLIST,
    EVENT_LIST_USB_DRIVES,
    EVENT_MODIFY_PLUGIN_STATUS,
    EVENT_MOVE_QUEUE,
    EVENT_MUTE,
    EVENT_NEXT,
    EVENT_PAUSE,
    EVENT_PINGER,
    EVENT_PLAY,
    EVENT_PLAY_FAVOURITES,
    EVENT_PLAY_ITEMS_LIST,
    EVENT_PLAY_NEXT,
    EVENT_PLAY_PLAYLIST,
    EVENT_PLAY_RADIO_FAVOURITES,
    EVENT_PLUGIN_MANAGER,
    EVENT_PREVIOUS,
    EVENT_REBOOT,
    EVENT_REGENERATE_THUMBNAILS,
    EVENT_REMOVE_FROM_FAVOURITES,
    EVENT_REMOVE_FROM_PLAYLIST,
    EVENT_REMOVE_FROM_RADIO_FAVOURITES,
    EVENT_REMOVE_QUEUE_ITEM,
    EVENT_REMOVE_WEB_RADIO,
    EVENT_REPLACE_AND_PLAY,
    EVENT_REPLACE_AND_PLAY_CUE,
    EVENT_RESCAN_DB,
    EVENT_SAFE_REMOVE_DRIVE,
    EVENT_SAVE_ALARM,
    EVENT_SAVE_QUEUE_TO_PLAYLIST,
    EVENT_SAVE_WIRELESS_NETWORK_SETTINGS,
    EVENT_SEARCH,
    EVENT_SEEK,
    EVENT_SERVICE_UPDATE_TRACKLIST,
    EVENT_SET_AUDIO_OUTPUT_VOLUME,
    EVENT_SET_CONSUME,
    EVENT_SET_DEVICE_NAME,
    EVENT_SET_OUTPUT_DEVICES,
    EVENT_SET_RANDOM,
    EVENT_SET_REPEAT,
    EVENT_SET_SLEEP,
    EVENT_SHUTDOWN,
    EVENT_STANDBY,
    EVENT_STOP,
    EVENT_SUPER_SEARCH,
    EVENT_TOGGLE,
    EVENT_UNINSTALL_PLUGIN,
    EVENT_UNMUTE,
    EVENT_UPDATE_ALL_METADATA,
    EVENT_UPDATE_DB,
    EVENT_UPDATE_PLUGIN,
    EVENT_VOLATILE_PLAY,
    EVENT_VOLUME,
    RESPONSE_EVENTS,
    VOLUME_DOWN,
    VOLUME_UP,
    VolumioWebSocketCommon,
)

SEEK_STEP_SECONDS = 10
"""The number of seconds a relative seek moves by, matching the REST API clients."""


def _load_socketio() -> ModuleType:
    """Import the optional WebSocket dependency, when a connection is about to be opened.

    Returns:
        The socketio module

    Raises:
        VolumioWebSocketError: If the package is not installed
    """
    try:
        import socketio
    except ImportError as e:
        raise VolumioWebSocketError(
            "Reaching the Volumio host over WebSocket needs the python-socketio package: "
            "install it with 'pip install volumito[websocket]'"
        ) from e

    # python-socketio ships no type stubs, as paramiko does not either
    return cast(ModuleType, socketio)


class VolumioWebSocketClient(VolumioWebSocketCommon):
    """Client for interacting with Volumio's WebSocket API.

    The client owns the Socket.IO connection it emits through: use it as a context
    manager, so the connection is closed when the block is left.
    """

    def __init__(
        self,
        host_configuration: VolumioHostConfiguration,
        timeout: float = 5.0,
        logger: logging.Logger | None = None,
    ) -> None:
        """Initialize the WebSocket API client.

        Args:
            host_configuration: The host configuration (scheme, host, and ports)
            timeout: The number of seconds a read waits for its answer (default: 5.0)
            logger: The logger the client writes to; without one, the client logs
                under its own name in the ``volumito`` hierarchy
        """
        super().__init__(host_configuration, timeout, logger)
        self._log_debug(f"Initializing the {self._CLIENT_DESCRIPTION}...")
        self._client: Any = None
        self._connected = False
        self._handlers: dict[str, list[Callable[[Any], None]]] = {}
        self._arrived: dict[str, threading.Event] = {}
        self._registered: set[str] = set()
        self._request_lock = threading.Lock()
        self._slots: dict[str, object] = {}
        self._log_debug(f"Initializing the {self._CLIENT_DESCRIPTION}... done")

    def _browse_items(self, uri: str) -> list[dict[str, Any]]:
        """Browse a URI and return its items reduced to the keys queueing reads.

        Args:
            uri: The URI to browse

        Returns:
            The listed items, ready to be queued
        """
        return [self._slim_queue_item(item.raw) for item in self.browse(uri).items]

    def _deliver(self, event: str, payload: object) -> None:
        """Hand an event the host pushed to whoever is waiting for it.

        Args:
            event: The name of the event
            payload: What the event carried
        """
        self._log_debug(f'Received "{event}"')
        arrived = self._arrived.get(event)
        if arrived is not None:
            self._slots[event] = payload
            arrived.set()
        for handler in list(self._handlers.get(event, ())):
            try:
                handler(payload)
            except Exception:
                self._log_exception(f'A handler of "{event}" raised')

    def _emit(self, event: str, payload: object = None) -> None:
        """Send an event to the Volumio instance.

        Args:
            event: The name of the event to emit
            payload: What the event carries, when it carries anything

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        if not self._connected:
            self._fail_not_connected(f'emit "{event}"')
        self._log_debug(f'Emitting "{event}"...')
        try:
            if payload is None:
                self._client.emit(event)
            else:
                self._client.emit(event, payload)
        except Exception as e:
            self._fail_emit(event, e)
        self._log_debug(f'Emitting "{event}"... done')

    def _ensure_registered(self, event: str) -> None:
        """Make sure the connection hands an event over when the host pushes it.

        Args:
            event: The name of the event to listen for
        """
        if event in self._registered or self._client is None:
            return
        self._client.on(event, self._receiver(event))
        self._registered.add(event)

    def _queue_payload_items(self, uri: str) -> list[dict[str, Any]] | None:
        """Return the browsed items a URI must be queued as, or None for the URI itself.

        A Volumio instance explodes the URIs of its local library (``mpd``) into
        tracks by itself, while the plugins of the other sources leave a container
        URI silently unexploded, reporting a success and queueing nothing: for those,
        the URI is browsed here and the items it lists are queued instead. A URI
        listing nothing (a single track, for instance) is queued as itself.

        Args:
            uri: The URI to be queued

        Returns:
            The items to queue in place of the URI, or None to queue the URI itself
        """
        if self._uri_service(uri) == "mpd":
            self._log_debug("The URI belongs to the local library: queueing it as itself")
            return None
        self._log_debug("Browsing the URI to queue the items it lists...")
        items = self._browse_items(uri)
        self._log_debug(
            f"Browsing the URI to queue the items it lists... done ({len(items)} items)"
        )
        return items or None

    def _read_array(self, event: str, payload: object = None) -> list[Any]:
        """Read an event answered by a JSON array.

        Args:
            event: The event to emit
            payload: What the emitted event carries, when it carries anything

        Returns:
            The array the answer carried

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an array
        """
        return self._as_json_array(self._request(event, payload=payload))

    def _read_object(self, event: str, payload: object = None) -> dict[str, Any]:
        """Read an event answered by a JSON object.

        Args:
            event: The event to emit
            payload: What the emitted event carries, when it carries anything

        Returns:
            The object the answer carried

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        return self._as_json_object(self._request(event, payload=payload))

    def _read_text(self, event: str, payload: object = None) -> str:
        """Read an event answered by a bare JSON string.

        Args:
            event: The event to emit
            payload: What the emitted event carries, when it carries anything

        Returns:
            The string the answer carried

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not a string
        """
        return self._as_json_string(self._request(event, payload=payload))

    def _receiver(self, event: str) -> Callable[..., None]:
        """Build the callback the connection calls when the host pushes an event.

        Args:
            event: The name of the event the callback listens for

        Returns:
            The callback handing the payload over to :meth:`_deliver`
        """

        def receive(payload: object = None) -> None:
            self._deliver(event, payload)

        return receive

    def _request(
        self,
        event: str,
        response_event: str | None = None,
        payload: object = None,
        timeout: float | None = None,
    ) -> object:
        """Emit an event and return the payload of the answer the host pushes back.

        The reads are serialized: ``search`` and ``browseLibrary`` are answered by the
        same event, so two reads in flight at once could take each other's answer.

        Args:
            event: The event to emit
            response_event: The event carrying the answer, looked up when not given
            payload: What the emitted event carries, when it carries anything
            timeout: The number of seconds to wait, the timeout of the client when
                not given

        Returns:
            What the answer carried

        Raises:
            ValueError: If no answer event is given for an event the host does not answer
            VolumioConnectionError: If not connected, if the event cannot be sent, or if
                the host does not answer in time
        """
        awaited = response_event if response_event is not None else self._response_event(event)
        waited = timeout if timeout is not None else self.timeout
        with self._request_lock:
            self._log_debug(f'Requesting "{event}", waiting for "{awaited}"...')
            # an answer event outside the map is listened for from its first read on
            self._ensure_registered(awaited)
            arrived = threading.Event()
            self._arrived[awaited] = arrived
            try:
                self._emit(event, payload)
                if not arrived.wait(waited):
                    self._fail_no_response(event, awaited, waited)
                answer = self._slots.pop(awaited, None)
            finally:
                self._arrived.pop(awaited, None)
            self._log_debug(f'Requesting "{event}", waiting for "{awaited}"... done')
            return answer

    def add_and_play(self, uri: str) -> None:
        """Add the content of a URI to the queue and start playing it.

        Like :meth:`add_to_queue`, the URI of a container of a source other than the
        local library is browsed first and queued as the items it lists.

        Args:
            uri: The URI whose content to add and play, from a browse or a search

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
            VolumioAPIError: If the browse of a container answers something unexpected
        """
        self._log_debug(f'Adding "{uri}" to the queue and playing it...')
        items = self._queue_payload_items(uri)
        payload: object = items if items is not None else self._queue_uri_item(uri)
        self._emit(EVENT_ADD_PLAY, payload)
        self._log_debug(f'Adding "{uri}" to the queue and playing it... done')

    def add_cue_track(self, uri: str, number: int, service: str | None = None) -> None:
        """Add one track of a cue sheet to the queue and play it.

        Args:
            uri: The URI of the cue sheet
            number: The position of the track inside the cue sheet
            service: The service the URI belongs to, derived from it when not given

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_ADD_PLAY_CUE, self._cue_payload(uri, number, service))

    def add_radio_favourite(self, uri: str) -> None:
        """Add a web radio to the radio favourites.

        Args:
            uri: The URL the web radio streams from

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_ADD_TO_RADIO_FAVOURITES, {"uri": uri})

    def add_share(self, name: str, path: str, fstype: str, **options: str) -> None:
        """Mount a network share on the Volumio instance.

        Args:
            name: The name to mount the share under
            path: The path of the share on its host (e.g., ``"192.168.1.2/Music"``)
            fstype: The kind of the share (e.g., ``"cifs"``, ``"nfs"``)
            **options: The remaining fields the share needs (``username``, ``password``,
                ``options``)

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        payload: dict[str, Any] = {"name": name, "path": path, "fstype": fstype, **options}
        self._emit(EVENT_ADD_SHARE, payload)

    def add_to_favourites(
        self,
        uri: str,
        title: str | None = None,
        service: str | None = None,
        albumart: str | None = None,
    ) -> None:
        """Add an item to the favourites.

        Args:
            uri: The URI of the item, from a browse or a search
            title: The title to show for it, when known
            service: The service the URI belongs to, derived from it when not given
            albumart: The URL of the cover to show for it, when known

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        payload = self._favourite_payload(uri, title, service, albumart)
        self._emit(EVENT_ADD_TO_FAVOURITES, payload)

    def add_to_playlist(
        self, name: str | Playlist, uri: str, service: str | None = None
    ) -> None:
        """Add an item to a saved playlist, creating the playlist if it does not exist.

        Args:
            name: The name of the playlist, or the playlist itself
            uri: The URI of the item to add, from a browse or a search
            service: The service the URI belongs to, derived from it when not given

        Raises:
            ValueError: If the given playlist has no name
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_ADD_TO_PLAYLIST, self._playlist_item_payload(name, uri, service))

    def add_to_queue(self, uri: str) -> None:
        """Add the content of a URI to the end of the queue, without touching playback.

        The URI of a container of a source other than the local library is browsed
        first and queued as the items it lists, since only the local library explodes
        its containers by itself.

        Args:
            uri: The URI whose content to add, from a browse or a search

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
            VolumioAPIError: If the browse of a container answers something unexpected
        """
        self._log_debug(f'Adding "{uri}" to the queue...')
        items = self._queue_payload_items(uri)
        payload: object = items if items is not None else self._queue_uri_item(uri)
        self._emit(EVENT_ADD_TO_QUEUE, payload)
        self._log_debug(f'Adding "{uri}" to the queue... done')

    def add_uids_to_queue(self, uids: list[str]) -> None:
        """Add items of the local library to the queue, by identifier.

        Args:
            uids: The identifiers of the items to queue

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_ADD_QUEUE_UIDS, uids)

    def add_web_radio(self, name: str, uri: str) -> None:
        """Save a web radio of the user.

        Args:
            name: The name to save the web radio under
            uri: The URL it streams from

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_ADD_WEB_RADIO, self._web_radio_payload(name, uri))

    @property
    def alarms(self) -> Alarms:
        """The alarms set on the Volumio instance.

        Each access emits a fresh event. The alarms come from the ``alarm-clock``
        plugin: a host without it never answers, and the read times out.

        Returns:
            The alarms set on the host

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an array
        """
        return Alarms.from_raw({"alarms": self._read_array(EVENT_GET_ALARMS)})

    def audio_output_pause(self, output_id: str) -> None:
        """Pause one audio output of the Volumio instance.

        Args:
            output_id: The identifier of the output to pause

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_AUDIO_OUTPUT_PAUSE, self._audio_output_payload(output_id))

    def audio_output_play(self, output_id: str) -> None:
        """Start one audio output of the Volumio instance.

        Args:
            output_id: The identifier of the output to start

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_AUDIO_OUTPUT_PLAY, self._audio_output_payload(output_id))

    @property
    def audio_outputs(self) -> AudioOutputs:
        """The audio outputs the Volumio instance can play to.

        Each access emits a fresh event.

        Returns:
            The audio outputs of the host

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        return AudioOutputs.from_raw(self._read_object(EVENT_GET_AUDIO_OUTPUTS))

    def browse(self, uri: str | None = None) -> BrowseResults:
        """Browse the content the Volumio instance lists at a URI.

        The URIs to descend into come from the answers themselves, and from the search
        results; the Volumio API wants ``/`` for the root, which stands in when no URI
        is given.

        Unlike the REST API, the WebSocket API takes no offset: the whole listing is
        answered, and :meth:`BrowseResults.offset` skips into it.

        Args:
            uri: The URI to browse, the root when not given

        Returns:
            The content listed at the URI

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        return BrowseResults.from_envelope(
            self._read_object(EVENT_BROWSE_LIBRARY, self._browse_payload(uri))
        )

    @property
    def browse_sources(self) -> BrowseSources:
        """The sources the Volumio instance can browse.

        Each access emits a fresh event. These are the roots the URIs of :meth:`browse`
        descend from.

        Returns:
            The browsable sources

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an array
        """
        sources = self._read_array(EVENT_GET_BROWSE_SOURCES)
        return BrowseSources.from_raw({"sources": sources})

    def call_plugin_method(
        self, endpoint: str, method: str, data: dict[str, Any] | None = None
    ) -> None:
        """Call a method of a plugin of the Volumio instance directly.

        This is the generic plugin call: a Volumio host answers it with nothing, and
        whatever the plugin pushes arrives at the handlers registered with :meth:`on`.

        Args:
            endpoint: The plugin, as ``"category/name"`` (e.g., ``"music_service/mpd"``)
            method: The name of the method to call
            data: The arguments to call it with, when it takes any

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        payload: dict[str, Any] = {"endpoint": endpoint, "method": method}
        payload["data"] = data if data is not None else {}
        self._emit(EVENT_CALL_METHOD, payload)

    def clear(self) -> None:
        """Empty the playback queue.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_CLEAR_QUEUE)

    @property
    def collection_statistics(self) -> CollectionStatistics:
        """The statistics of the music collection of the Volumio instance.

        Each access emits a fresh event.

        Returns:
            The statistics of the music collection

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        return CollectionStatistics.from_raw(self._read_object(EVENT_GET_MY_COLLECTION_STATS))

    def connect(self) -> None:
        """Open the connection to the Volumio WebSocket API.

        Connecting an already connected client does nothing.

        Raises:
            VolumioWebSocketError: If the python-socketio package is not installed
            VolumioConnectionError: If the connection cannot be opened
        """
        if self._connected:
            self._log_debug("Already connected to the Volumio WebSocket API")
            return
        sio: Any = _load_socketio()
        url = self.host_configuration.websocket_base_url
        self._log_debug(f'Connecting to the Volumio WebSocket API at "{url}"...')
        self._client = sio.Client(reconnection=False)
        self._registered = set()
        for event in set(RESPONSE_EVENTS.values()) | set(self._handlers):
            self._ensure_registered(event)
        try:
            self._client.connect(url)
        except Exception as e:
            self._client = None
            self._registered = set()
            self._fail_connection(e)
        self._connected = True
        self._log_debug(f'Connecting to the Volumio WebSocket API at "{url}"... done')

    def consume(self, value: bool) -> None:
        """Set the consume mode, which drops each track from the queue once played.

        Args:
            value: True to enable the consume mode, False to disable it

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_SET_CONSUME, self._mode_payload(value))

    def create_playlist(self, name: str | Playlist) -> None:
        """Create an empty saved playlist.

        Args:
            name: The name to give the playlist, or the playlist itself

        Raises:
            ValueError: If the given playlist has no name
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_CREATE_PLAYLIST, self._playlist_payload(name))

    def decrease_volume(self) -> None:
        """Decrease the playback volume by one step.

        The decrement is the one defined in the settings of the Volumio host.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_VOLUME, VOLUME_DOWN)

    def delete_folder(self, path: str) -> None:
        """Delete a folder of the collection of the Volumio instance.

        Args:
            path: The path of the folder to delete

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_DELETE_FOLDER, {"item": {"path": path}})

    def delete_playlist(self, name: str | Playlist) -> None:
        """Delete a saved playlist.

        Args:
            name: The name of the playlist to delete, or the playlist itself

        Raises:
            ValueError: If the given playlist has no name
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_DELETE_PLAYLIST, self._playlist_payload(name))

    def delete_share(self, share_id: str) -> None:
        """Unmount a network share of the Volumio instance.

        Args:
            share_id: The identifier of the share, from :attr:`shares`

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_DELETE_SHARE, {"id": share_id})

    @property
    def device_info(self) -> DeviceInfo:
        """The identity of the Volumio instance.

        Each access emits a fresh event.

        Returns:
            The name and hardware identifier of the host

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        return DeviceInfo.from_raw(self._read_object(EVENT_GET_DEVICE_INFO))

    @property
    def device_name(self) -> str | None:
        """The name of the Volumio instance.

        Reading the property emits a fresh event; assigning to it renames the host.

        Returns:
            The name of the host, None when it reports none

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        return DeviceInfo.from_raw(self._read_object(EVENT_GET_DEVICE_NAME)).name

    @device_name.setter
    def device_name(self, value: str) -> None:
        self._emit(EVENT_SET_DEVICE_NAME, {"name": value})

    @property
    def device_uuid(self) -> str:
        """The hardware identifier of the Volumio instance.

        Each access emits a fresh event.

        Returns:
            The hardware identifier of the host

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not a string
        """
        return self._read_text(EVENT_GET_DEVICE_HW_UUID)

    def disable_audio_output(self, output_id: str) -> None:
        """Disable one audio output of the Volumio instance.

        Args:
            output_id: The identifier of the output to disable

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_DISABLE_AUDIO_OUTPUT, self._audio_output_payload(output_id))

    def disable_plugin(self, category: str, name: str) -> None:
        """Disable an installed plugin of the Volumio instance.

        Args:
            category: The category the plugin belongs to
            name: The name of the plugin

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_DISABLE_PLUGIN, self._plugin_payload(category, name))

    def disconnect(self) -> None:
        """Close the connection to the Volumio WebSocket API.

        This method is safe to call multiple times and will not raise exceptions.
        """
        if self._connected:
            self._log_debug("Disconnecting from the Volumio WebSocket API...")
            try:
                self._client.disconnect()
            except Exception as e:
                self._log_warning(
                    f"Ignoring an error while disconnecting from the Volumio "
                    f"WebSocket API: {e}"
                )
            finally:
                self._client = None
                self._connected = False
                self._registered = set()
            self._log_debug("Disconnecting from the Volumio WebSocket API... done")

    def discover_network_shares(self) -> dict[str, Any]:
        """Discover the network shares reachable from the Volumio instance.

        Returns:
            The shares the host found, as it reported them

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        return self._read_object(EVENT_GET_NETWORK_SHARES_DISCOVERY)

    @property
    def dsp_config(self) -> UiConfig:
        """The configuration page of the DSP of the Volumio instance.

        Each access emits a fresh event.

        Returns:
            The configuration page of the DSP

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        return UiConfig.from_raw(self._read_object(EVENT_GET_DSP_UI_CONFIG))

    def edit_share(self, share_id: str, **fields: str) -> None:
        """Change a network share mounted by the Volumio instance.

        Args:
            share_id: The identifier of the share, from :attr:`shares`
            **fields: The fields to change (``name``, ``path``, ``fstype``, ``username``,
                ``password``, ``options``)

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        payload: dict[str, Any] = {"id": share_id, **fields}
        self._emit(EVENT_EDIT_SHARE, payload)

    def emit(self, event: str, payload: object = None) -> None:
        """Send an event to the Volumio instance, without waiting for anything.

        This is the way to reach the events the client exposes no member for: a Volumio
        host listens for far more of them than the REST API has endpoints.

        Args:
            event: The name of the event to emit
            payload: What the event carries, when it carries anything

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(event, payload)

    def enable_audio_output(self, output_id: str) -> None:
        """Enable one audio output of the Volumio instance.

        Args:
            output_id: The identifier of the output to enable

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_ENABLE_AUDIO_OUTPUT, self._audio_output_payload(output_id))

    def enable_plugin(self, category: str, name: str) -> None:
        """Enable an installed plugin of the Volumio instance.

        Args:
            category: The category the plugin belongs to
            name: The name of the plugin

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_ENABLE_PLUGIN, self._plugin_payload(category, name))

    def enqueue_playlist(self, name: str | Playlist) -> None:
        """Append a saved playlist to the queue, without touching the playback.

        Args:
            name: The name of the playlist to append, or the playlist itself

        Raises:
            ValueError: If the given playlist has no name
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_ENQUEUE, self._playlist_payload(name))

    @property
    def extended_output_devices(self) -> OutputDevices:
        """The output devices of the Volumio instance, with their details.

        Each access emits a fresh event.

        Returns:
            The output devices, with their details

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        return OutputDevices.from_envelope(self._read_object(EVENT_GET_EXTENDED_OUTPUT_DEVICES))

    def get_playlist_content(self, name: str | Playlist) -> PlaylistContent:
        """Read the tracks of a saved playlist.

        Args:
            name: The name of the playlist to read, or the playlist itself

        Returns:
            The tracks of the playlist

        Raises:
            ValueError: If the given playlist has no name
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        return PlaylistContent.from_envelope(
            self._read_object(EVENT_GET_PLAYLIST_CONTENT, self._playlist_payload(name))
        )

    def get_plugin_config(self, page: str) -> UiConfig:
        """Read the configuration page a plugin of the Volumio instance offers.

        Args:
            page: The plugin, as ``"category/name"`` (e.g., ``"system_controller/system"``)

        Returns:
            The configuration page of the plugin

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        return UiConfig.from_raw(self._read_object(EVENT_GET_UI_CONFIG, {"page": page}))

    def get_share(self, share_id: str) -> Share:
        """Read the details of one network share of the Volumio instance.

        Args:
            share_id: The identifier of the share, from :attr:`shares`

        Returns:
            The details of the share

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        return Share.from_raw(self._read_object(EVENT_GET_INFO_SHARE, {"id": share_id}))

    def goto(self, kind: str, value: str) -> BrowseResults:
        """Browse to the artist or the album of the track currently playing.

        Args:
            kind: What to browse to (``"artist"`` or ``"album"``)
            value: The name to browse to

        Returns:
            The content listed for it

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        return BrowseResults.from_envelope(
            self._read_object(EVENT_GO_TO, self._goto_payload(kind, value))
        )

    @property
    def has_next(self) -> bool:
        """Whether the current track has a next track in the queue.

        True if and only if a current position exists and it is not the last of the
        queue; without a current track, or with an empty queue, there is no next
        track. Each access emits fresh events (reading the playback state and the
        queue).

        Returns:
            True if the queue holds a track after the current one, False otherwise

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If an answer is of an unexpected shape
        """
        return bool(self.queue_status["has_next"])

    @property
    def has_previous(self) -> bool:
        """Whether the current track has a previous track in the queue.

        True if and only if a current position exists and it is not the first of the
        queue; without a current track, or with an empty queue, there is no previous
        track. Each access emits fresh events (reading the playback state and the
        queue).

        Returns:
            True if the queue holds a track before the current one, False otherwise

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If an answer is of an unexpected shape
        """
        return bool(self.queue_status["has_previous"])

    def import_service_playlists(self) -> None:
        """Import the playlists the music services of the host expose.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_IMPORT_SERVICE_PLAYLISTS)

    def increase_volume(self) -> None:
        """Increase the playback volume by one step.

        The increment is the one defined in the settings of the Volumio host.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_VOLUME, VOLUME_UP)

    @property
    def input_sources(self) -> InputSources:
        """The input sources the Volumio instance exposes.

        Each access emits a fresh event.

        Returns:
            The input sources of the host

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        return InputSources.from_raw(self._read_object(EVENT_GET_INPUT_SOURCES))

    def install_plugin(self, url: str) -> None:
        """Install a plugin on the Volumio instance, from a URL.

        The host reports its progress through the events its user interface listens
        for, which :meth:`on` can be registered for.

        Args:
            url: The URL of the plugin package

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_INSTALL_PLUGIN, {"url": url, "confirm": True})

    @property
    def installed_plugins(self) -> Plugins:
        """The plugins installed on the Volumio instance.

        Each access emits a fresh event.

        Returns:
            The installed plugins

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an array
        """
        plugins = self._read_array(EVENT_GET_INSTALLED_PLUGINS)
        return Plugins.from_raw({"plugins": plugins})

    @property
    def is_muted(self) -> bool:
        """Whether the playback volume of the Volumio instance is muted.

        Each access emits a fresh event (reading the playback state).

        Returns:
            True if the volume is muted, False otherwise

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the state carries no boolean mute flag
        """
        return self._state_mute(self.state)

    @property
    def is_paused(self) -> bool:
        """Whether the Volumio instance is paused.

        Each access emits a fresh event (reading the playback state).

        Returns:
            True if the playback is paused, False otherwise

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the state carries no string status
        """
        return self._state_status(self.state) == "pause"

    @property
    def is_playing(self) -> bool:
        """Whether the Volumio instance is playing.

        Each access emits a fresh event (reading the playback state).

        Returns:
            True if the playback is running, False otherwise

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the state carries no string status
        """
        return self._state_status(self.state) == "play"

    @property
    def is_stopped(self) -> bool:
        """Whether the Volumio instance is stopped.

        Each access emits a fresh event (reading the playback state).

        Returns:
            True if the playback is stopped, False otherwise

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the state carries no string status
        """
        return self._state_status(self.state) == "stop"

    @property
    def last_browse(self) -> BrowseResults:
        """The listing the Volumio instance pushed last, to any of its clients.

        Each access emits a fresh event.

        Returns:
            The last listing the host pushed

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        return BrowseResults.from_envelope(
            self._read_object(EVENT_GET_LAST_PUSHED_BROWSE_LIBRARY)
        )

    def manage_plugin(self, action: str, category: str, name: str) -> Plugins:
        """Ask the plugin manager of the Volumio instance to act on a plugin.

        Args:
            action: What to do (e.g., ``"enable"``, ``"disable"``, ``"uninstall"``)
            category: The category the plugin belongs to
            name: The name of the plugin

        Returns:
            The installed plugins, as they stand after the action

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an array
        """
        payload = {**self._plugin_payload(category, name), "action": action}
        plugins = self._read_array(EVENT_PLUGIN_MANAGER, payload)
        return Plugins.from_raw({"plugins": plugins})

    @property
    def menu_items(self) -> MenuItems:
        """The menu the Volumio instance offers its user interface.

        Each access emits a fresh event.

        Returns:
            The menu entries

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an array
        """
        return MenuItems.from_raw({"items": self._read_array(EVENT_GET_MENU_ITEMS)})

    def modify_plugin_status(self, category: str, name: str, enabled: bool) -> None:
        """Enable or disable an installed plugin in one call.

        Args:
            category: The category the plugin belongs to
            name: The name of the plugin
            enabled: True to enable the plugin, False to disable it

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        payload = {**self._plugin_payload(category, name), "enabled": enabled}
        self._emit(EVENT_MODIFY_PLUGIN_STATUS, payload)

    def move_in_queue(self, source: int, target: int) -> None:
        """Move a track to another position of the queue.

        Args:
            source: The position the track is at (0-based)
            target: The position to move it to (0-based)

        Raises:
            ValueError: If either position is negative
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_MOVE_QUEUE, self._move_payload(source, target))

    @property
    def music_sources(self) -> MusicSources:
        """The music source plugins of the Volumio instance.

        Each access emits a fresh event.

        Returns:
            The music sources of the host

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an array
        """
        sources = self._read_array(EVENT_GET_MY_MUSIC_PLUGINS)
        return MusicSources.from_raw({"plugins": sources})

    def mute(self) -> None:
        """Mute the playback volume.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_MUTE)

    @property
    def network_info(self) -> NetworkInfo:
        """The network interfaces of the Volumio instance.

        Each access emits a fresh event.

        Returns:
            The network interfaces of the host

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an array
        """
        interfaces = self._read_array(EVENT_GET_INFO_NETWORK)
        return NetworkInfo.from_raw({"interfaces": interfaces})

    def next(self) -> None:
        """Skip to the next track in the queue.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_NEXT)

    def off(self, event: str, handler: Callable[[Any], None] | None = None) -> None:
        """Stop calling a handler, or every handler, when an event arrives.

        Args:
            event: The name of the event
            handler: The handler to remove; without one, every handler of the event
                is removed
        """
        if handler is None:
            self._handlers.pop(event, None)
            self._log_debug(f'Removed every handler of "{event}"')
            return
        handlers = self._handlers.get(event)
        if handlers is not None and handler in handlers:
            handlers.remove(handler)
            self._log_debug(f'Removed a handler of "{event}"')

    def on(self, event: str, handler: Callable[[Any], None]) -> None:
        """Call a handler with the payload of an event whenever the host pushes it.

        A Volumio host pushes some events on its own -- ``pushState`` on every change of
        the playback state, and a few more the moment the connection opens -- and pushes
        others as the answer to a read, in which case the handler is called too.

        Handlers can be registered before connecting. They run on the thread the
        connection reads on, and an exception one raises is logged and swallowed, so one
        failing handler does not stop the others.

        Args:
            event: The name of the event to listen for (e.g., ``"pushState"``)
            handler: The callable receiving the payload of the event
        """
        self._handlers.setdefault(event, []).append(handler)
        self._ensure_registered(event)
        self._log_debug(f'Added a handler of "{event}"')

    @property
    def output_devices(self) -> OutputDevices:
        """The output devices the Volumio instance can play through.

        Each access emits a fresh event.

        Returns:
            The output devices of the host

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        return OutputDevices.from_envelope(self._read_object(EVENT_GET_OUTPUT_DEVICES))

    def pause(self) -> None:
        """Pause the playback.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_PAUSE)

    def ping(self) -> str:
        """Ping the Volumio instance to check that it is reachable.

        The host echoes back, unchanged, what the ping carried, so the answer is matched
        against what was sent rather than merely awaited.

        Returns:
            ``"pong"`` from a healthy Volumio instance

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer in
                time or does not echo the ping back
        """
        nonce = uuid.uuid4().hex
        echoed = self._request(EVENT_PINGER, payload={"nonce": nonce})
        if not isinstance(echoed, dict) or echoed.get("nonce") != nonce:
            self._log_warning(f"The Volumio API answered a ping with {echoed!r}")
            self._fail_no_response(EVENT_PINGER, self._response_event(EVENT_PINGER), self.timeout)
        return "pong"

    def play(self, position: int | QueueTrack | None = None) -> None:
        """Start the playback, optionally at a position of the queue.

        Args:
            position: Optional position in the queue to play (0-indexed), or a track
                of the queue

        Raises:
            ValueError: If the given track does not know its position in the queue
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_PLAY, self._play_payload(position))

    def play_favourites(self, name: str | None = None) -> None:
        """Play the favourites, optionally starting at one of them.

        Args:
            name: The name of the favourite to start at, the first when not given

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_PLAY_FAVOURITES, {"name": name} if name is not None else None)

    def play_items(self, items: list[dict[str, Any]], index: int = 0) -> None:
        """Replace the queue with a list of items and play it from one of them.

        The items come from a browse or a search; they are reduced to the keys queueing
        reads, as :meth:`replace_queue_and_play` does.

        Args:
            items: The items to play
            index: The position of the item to play first (0-based)

        Raises:
            ValueError: If the index is negative
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._check_play_index(index)
        payload = {"list": [self._slim_queue_item(item) for item in items], "index": index}
        self._emit(EVENT_PLAY_ITEMS_LIST, payload)

    def play_next(self, uri: str, title: str | None = None, album: str | None = None) -> None:
        """Queue an item right after the track currently playing.

        Args:
            uri: The URI to queue
            title: The title to show for it, when known
            album: The album to show for it, when known

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_PLAY_NEXT, self._play_next_payload(uri, title, album))

    def play_playlist(self, name: str | Playlist) -> None:
        """Start the playback of a saved playlist.

        Args:
            name: The name of the playlist to play, or the playlist itself

        Raises:
            ValueError: If the given playlist has no name
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_PLAY_PLAYLIST, self._playlist_payload(name))

    def play_radio_favourites(self) -> None:
        """Play the radio favourites.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_PLAY_RADIO_FAVOURITES)

    def play_volatile(self, position: int) -> None:
        """Start a volatile source (e.g., Spotify Connect) at a position.

        Args:
            position: The position to start at (0-based)

        Raises:
            ValueError: If the position is negative
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_VOLATILE_PLAY, self._index_payload(position))

    @property
    def playlists(self) -> Playlists:
        """The saved playlists of the Volumio instance.

        Each access emits a fresh event.

        Returns:
            The saved playlists, by name

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an array
        """
        return Playlists.from_names(self._read_array(EVENT_LIST_PLAYLIST))

    @property
    def power_modes(self) -> PowerModes:
        """The ways the Volumio instance can be powered down.

        Each access emits a fresh event. A host that reports no standby mode answers
        :meth:`standby` by powering off instead.

        Returns:
            The power modes of the host

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        return PowerModes.from_raw(self._read_object(EVENT_GET_SHUTDOWN_OR_STANDBY_MODE))

    def previous(self) -> None:
        """Go back to the previous track in the queue.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_PREVIOUS)

    @property
    def queue(self) -> Queue:
        """The current playback queue of the Volumio instance.

        Each access emits a fresh event. The host answers with the tracks themselves,
        which the model wraps.

        Returns:
            The current playback queue

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an array
        """
        return Queue.from_raw({"queue": self._read_array(EVENT_GET_QUEUE)})

    @property
    def queue_status(self) -> dict[str, Any]:
        """The navigation state of the queue, as a small mapping.

        The keys are ``has_next`` and ``has_previous`` (whether the current track
        has a neighbor in the queue), ``length`` (the number of queued tracks),
        ``position`` (the 0-based index of the current track, None without one),
        and ``track`` (the playback state payload, as the Volumio host pushed it).
        Each access emits fresh events (reading the playback state and the queue).

        Returns:
            The navigation state of the queue

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If an answer is of an unexpected shape
        """
        state = self.state
        count = len(self.queue)
        return self._queue_status(state, count)

    def randomize(self, value: bool | None = None) -> None:
        """Set or toggle the random (shuffle) mode.

        The WebSocket API only sets the mode, so toggling it reads the playback state
        first and sends the opposite of what it reports.

        Args:
            value: True to enable, False to disable, or None (the default) to toggle
                the current random mode

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
            VolumioAPIError: If the state read to toggle the mode is unexpected
        """
        wanted = value if value is not None else not self.state.random
        self._emit(EVENT_SET_RANDOM, self._mode_payload(wanted))

    def reboot(self) -> None:
        """Restart the Volumio host.

        The host drops the connection as it goes down; reconnect once it is back.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_REBOOT)

    def regenerate_thumbnails(self) -> None:
        """Rebuild the thumbnails of the album art of the collection.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_REGENERATE_THUMBNAILS)

    def remove_from_favourites(self, uri: str, service: str | None = None) -> None:
        """Remove an item from the favourites.

        Args:
            uri: The URI of the item to remove
            service: The service the URI belongs to, derived from it when not given

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        payload = self._favourite_payload(uri, service=service)
        self._emit(EVENT_REMOVE_FROM_FAVOURITES, payload)

    def remove_from_playlist(
        self, name: str | Playlist, uri: str, service: str | None = None
    ) -> None:
        """Remove an item from a saved playlist.

        Args:
            name: The name of the playlist, or the playlist itself
            uri: The URI of the item to remove
            service: The service the URI belongs to, derived from it when not given

        Raises:
            ValueError: If the given playlist has no name
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_REMOVE_FROM_PLAYLIST, self._playlist_item_payload(name, uri, service))

    def remove_from_queue(self, position: int) -> None:
        """Remove a track from the queue.

        Args:
            position: The position of the track to remove (0-based)

        Raises:
            ValueError: If the position is negative
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_REMOVE_QUEUE_ITEM, self._index_payload(position))

    def remove_radio_favourite(self, uri: str, name: str | None = None) -> None:
        """Remove a web radio from the radio favourites.

        Args:
            uri: The URL the web radio streams from
            name: The name it is a favourite under, when known

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        payload = {"uri": uri} if name is None else {"name": name, "uri": uri}
        self._emit(EVENT_REMOVE_FROM_RADIO_FAVOURITES, payload)

    def remove_web_radio(self, name: str) -> None:
        """Delete a web radio of the user.

        Args:
            name: The name the web radio was saved under

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_REMOVE_WEB_RADIO, self._web_radio_payload(name))

    def repeat(self, value: bool | None = None) -> None:
        """Set or toggle the repeat mode.

        The WebSocket API only sets the mode, so toggling it reads the playback state
        first and sends the opposite of what it reports.

        Args:
            value: True to enable, False to disable, or None (the default) to toggle
                the current repeat mode

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
            VolumioAPIError: If the state read to toggle the mode is unexpected
        """
        wanted = value if value is not None else not self.state.repeat
        self._emit(EVENT_SET_REPEAT, self._mode_payload(wanted))

    def replace_queue_and_play(self, uri: str, index: int | None = None) -> None:
        """Replace the queue with the content of a URI and start playing it.

        Without an index the first item plays. With one, the URI is browsed first and
        its items are sent along with the index, since that is the only payload the
        Volumio API starts at a chosen item with. Like :meth:`add_to_queue`, the URI
        of a container of a source other than the local library is browsed and sent as
        the items it lists even without an index.

        Args:
            uri: The URI whose content to play, from a browse or a search
            index: The position of the item to play first (0-based), or None for
                the first

        Raises:
            ValueError: If the index is negative
            VolumioConnectionError: If not connected, or if the event cannot be sent
            VolumioAPIError: If the URI does not list enough items to play the asked one
        """
        self._check_play_index(index)
        self._log_debug(f'Replacing the queue with "{uri}"...')
        if index is not None:
            items = self._browse_items(uri)
            if len(items) > index:
                self._log_debug(f"Sending the {len(items)} listed items, playing index {index}")
                self._emit(EVENT_REPLACE_AND_PLAY, {"list": items, "index": index})
                self._log_debug(f'Replacing the queue with "{uri}"... done')
                return
            if items or index > 0:
                self._fail_short_listing(len(items), index)
        else:
            listed = self._queue_payload_items(uri)
            if listed is not None:
                self._log_debug(f"Sending the {len(listed)} listed items, playing the first")
                self._emit(EVENT_REPLACE_AND_PLAY, {"list": listed, "index": 0})
                self._log_debug(f'Replacing the queue with "{uri}"... done')
                return
        self._log_debug("Sending the URI as a single item, playing its first element")
        self._emit(EVENT_REPLACE_AND_PLAY, {"item": self._queue_uri_item(uri)})
        self._log_debug(f'Replacing the queue with "{uri}"... done')

    def replace_queue_with_cue_track(
        self, uri: str, number: int, service: str | None = None
    ) -> None:
        """Replace the queue with one track of a cue sheet and play it.

        Args:
            uri: The URI of the cue sheet
            number: The position of the track inside the cue sheet
            service: The service the URI belongs to, derived from it when not given

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_REPLACE_AND_PLAY_CUE, self._cue_payload(uri, number, service))

    def request(
        self,
        event: str,
        response_event: str | None = None,
        payload: object = None,
        timeout: float | None = None,
    ) -> object:
        """Emit an event and return the payload of the answer the host pushes back.

        This is the way to read through the events the client exposes no member for.

        Args:
            event: The event to emit
            response_event: The event carrying the answer; needed for the events the
                client does not already know the answer of
            payload: What the emitted event carries, when it carries anything
            timeout: The number of seconds to wait, the timeout of the client when
                not given

        Returns:
            What the answer carried

        Raises:
            ValueError: If no answer event is given for an event the host does not answer
            VolumioConnectionError: If not connected, if the event cannot be sent, or if
                the host does not answer in time
        """
        return self._request(event, response_event, payload, timeout)

    def rescan_library(self) -> None:
        """Rescan the music collection of the Volumio instance from scratch.

        This is the slower of the two: :meth:`update_library` only looks for changes.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_RESCAN_DB)

    def safe_remove_drive(self, name: str) -> None:
        """Unmount a USB drive of the Volumio instance before it is unplugged.

        Args:
            name: The name of the drive, from :attr:`usb_drives`

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_SAFE_REMOVE_DRIVE, {"name": name})

    def save_queue_as_playlist(self, name: str | Playlist) -> None:
        """Save the current queue as a saved playlist.

        Args:
            name: The name to save the queue under, or the playlist to overwrite

        Raises:
            ValueError: If the given playlist has no name
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_SAVE_QUEUE_TO_PLAYLIST, self._playlist_payload(name))

    def save_wireless_settings(self, ssid: str, password: str = "") -> None:
        """Join a wireless network with the Volumio instance.

        Args:
            ssid: The name of the network
            password: The password of the network, empty for an open one

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        payload = {"ssid": ssid, "password": password}
        self._emit(EVENT_SAVE_WIRELESS_NETWORK_SETTINGS, payload)

    def search(self, query: str) -> SearchResults:
        """Search the sources of the Volumio instance.

        The Volumio API takes the query only: the results it groups by source and by
        kind can be narrowed with :meth:`SearchResults.filtered`.

        Args:
            query: The text to search for

        Returns:
            The results of the search

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        return SearchResults.from_envelope(
            self._read_object(EVENT_SEARCH, self._search_payload(query))
        )

    @property
    def seek(self) -> int:
        """The seek position, in seconds, in the track currently playing.

        Reading the property takes the position from the current playback state,
        rounding the milliseconds reported there down to whole seconds (each access
        emits a fresh event); assigning to it seeks to an absolute position, also in
        seconds.

        See :meth:`seek_backward` and :meth:`seek_forward` for relative seeking.

        Returns:
            The current seek position, in seconds

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the state carries no integer seek position
        """
        return self._state_seek(self.state)

    @seek.setter
    def seek(self, value: int) -> None:
        self._emit(EVENT_SEEK, self._seek_payload(value))

    def seek_backward(self) -> None:
        """Seek backward by 10 seconds in the track currently playing.

        The WebSocket API seeks to absolute positions only, so this reads the current
        position first and never seeks before the start of the track.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
            VolumioAPIError: If the state carries no integer seek position
        """
        self._emit(EVENT_SEEK, self._seek_payload(max(0, self.seek - SEEK_STEP_SECONDS)))

    def seek_forward(self) -> None:
        """Seek forward by 10 seconds in the track currently playing.

        The WebSocket API seeks to absolute positions only, so this reads the current
        position first.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
            VolumioAPIError: If the state carries no integer seek position
        """
        self._emit(EVENT_SEEK, self._seek_payload(self.seek + SEEK_STEP_SECONDS))

    def set_alarms(self, alarms: list[Alarm]) -> None:
        """Replace the whole set of alarms of the Volumio instance.

        The Volumio API takes the alarms as a set rather than one at a time, so this
        replaces every alarm the host holds: read :attr:`alarms` first and send back the
        list you want to keep.

        Args:
            alarms: The alarms to keep

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_SAVE_ALARM, self._alarms_payload(alarms))

    def set_audio_output_volume(self, output_id: str, volume: int) -> None:
        """Set the volume of one audio output of the Volumio instance.

        This is the volume of one output; :attr:`volume` is the volume of the host.

        Args:
            output_id: The identifier of the output
            volume: The volume level, an integer between 0 and 100 (inclusive)

        Raises:
            ValueError: If the volume level is out of range
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        payload = self._audio_output_payload(output_id, volume)
        self._emit(EVENT_SET_AUDIO_OUTPUT_VOLUME, payload)

    def set_music_source_enabled(self, name: str, enabled: bool) -> None:
        """Enable or disable one music source of the Volumio instance.

        Args:
            name: The name of the source, from :attr:`music_sources`
            enabled: True to enable the source, False to disable it

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        payload = {"name": name, "enabled": enabled}
        self._emit(EVENT_ENABLE_DISABLE_MY_MUSIC_PLUGIN, payload)

    def set_output_device(self, device_id: str, mixer: str | None = None) -> None:
        """Choose the output device the Volumio instance plays through.

        Args:
            device_id: The identifier of the device, from :attr:`output_devices`
            mixer: The mixer to drive its volume with, left to the host when not given

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        payload = self._output_device_payload(device_id, mixer)
        self._emit(EVENT_SET_OUTPUT_DEVICES, payload)

    def set_sleep_timer(self, delay: timedelta | None) -> None:
        """Arm or disarm the sleep timer of the Volumio instance.

        The Volumio API reads the time of a sleep timer as a delay from now, not as a
        clock time, so ``timedelta(minutes=30)`` stops the host in half an hour.

        The timer comes from the ``alarm-clock`` plugin, and so does :attr:`sleep_timer`.

        Args:
            delay: How long from now the host should stop, or None to disarm the timer

        Raises:
            ValueError: If the delay is negative
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_SET_SLEEP, self._sleep_payload(delay))

    @property
    def shares(self) -> Shares:
        """The network shares mounted by the Volumio instance.

        Each access emits a fresh event.

        Returns:
            The mounted shares

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an array
        """
        return Shares.from_raw({"shares": self._read_array(EVENT_GET_LIST_SHARES)})

    def shutdown(self) -> None:
        """Power the Volumio host off.

        The host drops the connection as it goes down, and does not come back on its
        own.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_SHUTDOWN)

    @property
    def sleep_timer(self) -> SleepTimer:
        """The sleep timer of the Volumio instance.

        Each access emits a fresh event. Read the remaining delay off
        :attr:`SleepTimer.delay`, which parses it as the duration it is.

        Returns:
            The sleep timer of the host

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        return SleepTimer.from_raw(self._read_object(EVENT_GET_SLEEP))

    def standby(self) -> None:
        """Put the Volumio host on standby.

        A host whose :attr:`power_modes` report no standby mode powers off instead.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_STANDBY)

    @property
    def state(self) -> PlayerState:
        """The current playback state of the Volumio instance.

        Each access emits a fresh event. A Volumio host broadcasts the state on every
        change of it, so the answer may be a broadcast the client did not ask for --
        which carries the current state all the same.

        Returns:
            The current playback state of the Volumio instance

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        return PlayerState.from_raw(self._read_object(EVENT_GET_STATE))

    def stop(self) -> None:
        """Stop the playback.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_STOP)

    def super_search(self, query: str) -> SearchResults:
        """Search every source of the Volumio instance at once.

        Unlike :meth:`search`, which the sources answer one by one, this asks the host
        to search them together.

        The search is served by the ``metavolumio`` plugin (Volumio Premium), as the
        story queries of the REST API clients are: a host without it answers an empty
        result rather than an error.

        Args:
            query: The text to search for

        Returns:
            The results of the search

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        return SearchResults.from_envelope(
            self._read_object(EVENT_SUPER_SEARCH, self._search_payload(query))
        )

    @property
    def system_info(self) -> SystemInfo:
        """The system information of the Volumio instance.

        Each access emits a fresh event.

        Returns:
            The system information of the host

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        return SystemInfo.from_raw(self._read_object(EVENT_GET_SYSTEM_INFO))

    @property
    def system_version(self) -> SystemVersion:
        """The Volumio version the instance runs.

        Each access emits a fresh event.

        Returns:
            The version of the host

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        return SystemVersion.from_raw(self._read_object(EVENT_GET_SYSTEM_VERSION))

    def toggle(self) -> None:
        """Toggle between playing and paused.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_TOGGLE)

    def uninstall_plugin(self, category: str, name: str) -> None:
        """Remove an installed plugin from the Volumio instance.

        Args:
            category: The category the plugin belongs to
            name: The name of the plugin

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_UNINSTALL_PLUGIN, self._plugin_payload(category, name))

    def unmute(self) -> None:
        """Unmute the playback volume.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_UNMUTE)

    def update_all_metadata(self) -> None:
        """Refresh the metadata of the whole collection of the Volumio instance.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_UPDATE_ALL_METADATA)

    def update_library(self, uri: str | None = None) -> None:
        """Update the music collection of the Volumio instance, looking for changes.

        Args:
            uri: The URI to update, the whole collection when not given

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_UPDATE_DB, uri)

    def update_plugin(self, category: str, name: str) -> None:
        """Update an installed plugin of the Volumio instance.

        Args:
            category: The category the plugin belongs to
            name: The name of the plugin

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_UPDATE_PLUGIN, self._plugin_payload(category, name))

    def update_service_tracklist(self, service: str) -> None:
        """Refresh the tracks one music service of the Volumio instance offers.

        Args:
            service: The name of the service to refresh

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_SERVICE_UPDATE_TRACKLIST, service)

    @property
    def usb_drives(self) -> UsbDrives:
        """The USB drives attached to the Volumio instance.

        Each access emits a fresh event.

        Returns:
            The attached drives

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an array
        """
        return UsbDrives.from_raw({"drives": self._read_array(EVENT_LIST_USB_DRIVES)})

    @property
    def volume(self) -> int:
        """The playback volume level of the Volumio instance.

        Reading the property takes the level from the current playback state (each
        access emits a fresh event); assigning to it sets an absolute level.

        See :meth:`increase_volume` and :meth:`decrease_volume` for relative changes.

        Returns:
            The volume level, an integer between 0 and 100 (inclusive)

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the state carries no integer volume level
        """
        return self._state_volume(self.state)

    @volume.setter
    def volume(self, value: int) -> None:
        self._emit(EVENT_VOLUME, self._volume_payload(value))

    def wait(self) -> None:
        """Block until the connection to the Volumio instance drops.

        Raises:
            VolumioConnectionError: If not connected
        """
        if not self._connected:
            self._fail_not_connected("wait for events")
        self._log_debug("Waiting for the connection to drop...")
        self._client.wait()
        self._log_debug("Waiting for the connection to drop... done")

    @property
    def wireless_networks(self) -> WirelessNetworks:
        """The wireless networks the Volumio instance can see, scanning for them.

        Each access emits a fresh event, and a scan takes a moment: a host with no
        wireless interface never answers, and the read times out. See
        :attr:`wireless_networks_cache` for the networks it saw last.

        Returns:
            The wireless networks the host can see

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        return WirelessNetworks.from_raw(self._read_object(EVENT_GET_WIRELESS_NETWORKS))

    @property
    def wireless_networks_cache(self) -> WirelessNetworks:
        """The wireless networks the Volumio instance saw last, without scanning again.

        Each access emits a fresh event.

        Returns:
            The wireless networks the host saw last

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        answer = self._read_object(EVENT_GET_WIRELESS_NETWORKS_CACHE)
        return WirelessNetworks.from_raw(answer)

    @property
    def zones(self) -> Zones:
        """The multiroom zones the Volumio instance sees.

        Each access emits a fresh event. The host answers with the devices under a
        ``list`` key, which the model reads as its zones.

        Returns:
            The multiroom zones

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        answer = self._read_object(EVENT_GET_MULTI_ROOM_DEVICES)
        return Zones.from_raw({"zones": answer.get("list", [])})

    def __enter__(self) -> Self:
        """Context manager entry - connects to the Volumio WebSocket API.

        Returns:
            The VolumioWebSocketClient instance

        Raises:
            VolumioWebSocketError: If the python-socketio package is not installed
            VolumioConnectionError: If the connection cannot be opened
        """
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Context manager exit - disconnects from the Volumio WebSocket API.

        Args:
            exc_type: Exception type (if any)
            exc_val: Exception value (if any)
            exc_tb: Exception traceback (if any)
        """
        self.disconnect()
