"""Async WebSocket API client for Volumio.

The asyncio counterpart of :class:`VolumioWebSocketClient`, exposing the same members
under the naming the async REST API client established: the nouns take a ``get_`` prefix,
the predicates keep their names, and the assignable properties take a ``set_`` prefix.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

import asyncio
import inspect
import logging
import uuid
from collections.abc import Callable
from datetime import timedelta
from types import ModuleType, TracebackType
from typing import Any, Self

from volumito.clients.errors import VolumioWebSocketError
from volumito.clients.host_configuration import VolumioHostConfiguration
from volumito.clients.models import (
    Alarm,
    Alarms,
    AudioOutputs,
    Backgrounds,
    BrowseResults,
    BrowseSources,
    CollectionStatistics,
    DeviceInfo,
    ExperienceSettings,
    InfinityPlayback,
    InputSources,
    Languages,
    MenuItems,
    Multiroom,
    MusicSources,
    NetworkInfo,
    OutputDevices,
    PlayerState,
    Playlist,
    PlaylistContent,
    Playlists,
    Plugins,
    PowerModes,
    PrivacySettings,
    Queue,
    QueueTrack,
    SearchResults,
    Share,
    Shares,
    SleepTimer,
    SystemInfo,
    SystemVersion,
    Timezones,
    UiConfig,
    UiSettings,
    UpdaterChannel,
    UsbDrives,
    WirelessNetworks,
    Zones,
)
from volumito.clients.websocket.client import SEEK_STEP_SECONDS, _load_socketio
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
    EVENT_DELETE_BACKGROUND,
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
    EVENT_GET_AUTOMATIC_UPDATE_ENABLED,
    EVENT_GET_AVAILABLE_LANGUAGES,
    EVENT_GET_AVAILABLE_TIMEZONES,
    EVENT_GET_BACKGROUNDS,
    EVENT_GET_BACKUP,
    EVENT_GET_BROWSE_SOURCES,
    EVENT_GET_CURRENT_TIMEZONE,
    EVENT_GET_DEVICE_HW_UUID,
    EVENT_GET_DEVICE_INFO,
    EVENT_GET_DEVICE_NAME,
    EVENT_GET_DSP_UI_CONFIG,
    EVENT_GET_EXPERIENCE_ADVANCED_SETTINGS,
    EVENT_GET_EXTENDED_OUTPUT_DEVICES,
    EVENT_GET_INFINITY_PLAYBACK,
    EVENT_GET_INFO_NETWORK,
    EVENT_GET_INFO_SHARE,
    EVENT_GET_INPUT_SOURCES,
    EVENT_GET_INSTALLED_PLUGINS,
    EVENT_GET_LAST_PUSHED_BROWSE_LIBRARY,
    EVENT_GET_LIST_SHARES,
    EVENT_GET_MENU_ITEMS,
    EVENT_GET_MULTI_ROOM_DEVICES,
    EVENT_GET_MULTIROOM,
    EVENT_GET_MY_COLLECTION_STATS,
    EVENT_GET_MY_MUSIC_PLUGINS,
    EVENT_GET_NETWORK_SHARES_DISCOVERY,
    EVENT_GET_OUTPUT_DEVICES,
    EVENT_GET_PLAYLIST_CONTENT,
    EVENT_GET_PRIVACY_SETTINGS,
    EVENT_GET_QUEUE,
    EVENT_GET_SHUTDOWN_OR_STANDBY_MODE,
    EVENT_GET_SLEEP,
    EVENT_GET_STATE,
    EVENT_GET_SYSTEM_INFO,
    EVENT_GET_SYSTEM_VERSION,
    EVENT_GET_UI_CONFIG,
    EVENT_GET_UI_SETTINGS,
    EVENT_GET_UPDATER_CHANNEL,
    EVENT_GET_WIRELESS_NETWORKS,
    EVENT_GET_WIRELESS_NETWORKS_CACHE,
    EVENT_GO_TO,
    EVENT_IMPORT_SERVICE_PLAYLISTS,
    EVENT_INSTALL_PLUGIN,
    EVENT_LIST_PLAYLIST,
    EVENT_LIST_USB_DRIVES,
    EVENT_MANAGE_BACKUP,
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
    EVENT_RESTORE_CONFIG,
    EVENT_SAFE_REMOVE_DRIVE,
    EVENT_SAVE_ALARM,
    EVENT_SAVE_QUEUE_TO_PLAYLIST,
    EVENT_SAVE_WIRELESS_NETWORK_SETTINGS,
    EVENT_SEARCH,
    EVENT_SEEK,
    EVENT_SERVICE_UPDATE_TRACKLIST,
    EVENT_SET_AS_MULTIROOM_CLIENT,
    EVENT_SET_AS_MULTIROOM_SERVER,
    EVENT_SET_AS_MULTIROOM_SINGLE,
    EVENT_SET_AUDIO_OUTPUT_VOLUME,
    EVENT_SET_BACKGROUNDS,
    EVENT_SET_CONSUME,
    EVENT_SET_DEVICE_NAME,
    EVENT_SET_EXPERIENCE_ADVANCED_SETTINGS,
    EVENT_SET_INFINITY_PLAYBACK,
    EVENT_SET_LANGUAGE,
    EVENT_SET_MULTIROOM,
    EVENT_SET_OUTPUT_DEVICES,
    EVENT_SET_RANDOM,
    EVENT_SET_REPEAT,
    EVENT_SET_SLEEP,
    EVENT_SET_TIMEZONE,
    EVENT_SET_UPDATER_CHANNEL,
    EVENT_SHUTDOWN,
    EVENT_STANDBY,
    EVENT_STOP,
    EVENT_SUPER_SEARCH,
    EVENT_TOGGLE,
    EVENT_UNINSTALL_PLUGIN,
    EVENT_UNMUTE,
    EVENT_UPDATE,
    EVENT_UPDATE_ALL_METADATA,
    EVENT_UPDATE_CHECK,
    EVENT_UPDATE_CHECK_CACHE,
    EVENT_UPDATE_DB,
    EVENT_UPDATE_PLUGIN,
    EVENT_VOLATILE_PLAY,
    EVENT_VOLUME,
    EVENT_WRITE_MULTIROOM,
    RESPONSE_EVENTS,
    VOLUME_DOWN,
    VOLUME_UP,
    VolumioWebSocketCommon,
)


def _load_aiohttp() -> ModuleType:
    """Import the HTTP package python-socketio needs, when a connection is about to be opened.

    python-socketio itself only logs a missing aiohttp and connects to nothing, leaving
    every request to wait for an answer that never comes: checking here fails at once.

    Returns:
        The aiohttp module

    Raises:
        VolumioWebSocketError: If the package is not installed
    """
    try:
        import aiohttp
    except ImportError as e:
        raise VolumioWebSocketError(
            "Reaching the Volumio host over WebSocket asynchronously needs the aiohttp "
            "package: install it with 'pip install volumito[async_websocket]'"
        ) from e

    return aiohttp


class VolumioAsyncWebSocketClient(VolumioWebSocketCommon):
    """Async client for interacting with Volumio's WebSocket API.

    The client owns the Socket.IO connection it emits through: use it as an async
    context manager, so the connection is closed when the block is left.

    A handler registered with :meth:`on` may be a coroutine function or an ordinary one;
    a coroutine it returns is awaited.
    """

    _CLIENT_DESCRIPTION: str = "async WebSocket API client"
    """The name a client logs itself under while initializing."""

    def __init__(
        self,
        host_configuration: VolumioHostConfiguration,
        timeout: float = 5.0,
        logger: logging.Logger | None = None,
    ) -> None:
        """Initialize the async WebSocket API client.

        Nothing here touches an event loop, so the client can be built outside a
        running one.

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
        self._handlers: dict[str, list[Callable[[Any], Any]]] = {}
        self._arrived: dict[str, asyncio.Event] = {}
        self._registered: set[str] = set()
        self._request_lock = asyncio.Lock()
        self._slots: dict[str, object] = {}
        self._log_debug(f"Initializing the {self._CLIENT_DESCRIPTION}... done")

    async def _browse_items(self, uri: str) -> list[dict[str, Any]]:
        """Browse a URI and return its items reduced to the keys queueing reads.

        Args:
            uri: The URI to browse

        Returns:
            The listed items, ready to be queued
        """
        results = await self.browse(uri)
        return [self._slim_queue_item(item.raw) for item in results.items]

    async def _deliver(self, event: str, payload: object) -> None:
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
                answered = handler(payload)
                if inspect.isawaitable(answered):
                    await answered
            except Exception:
                self._log_exception(f'A handler of "{event}" raised')

    async def _emit(self, event: str, payload: object = None) -> None:
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
                await self._client.emit(event)
            else:
                await self._client.emit(event, payload)
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

    async def _queue_payload_items(self, uri: str) -> list[dict[str, Any]] | None:
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
        items = await self._browse_items(uri)
        self._log_debug(
            f"Browsing the URI to queue the items it lists... done ({len(items)} items)"
        )
        return items or None

    async def _read_array(self, event: str, payload: object = None) -> list[Any]:
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
        return self._as_json_array(await self._request(event, payload=payload))

    async def _read_boolean(self, event: str, payload: object = None) -> bool:
        """Read an event answered by a bare JSON boolean.

        Args:
            event: The event to emit
            payload: What the emitted event carries, when it carries anything

        Returns:
            The boolean the answer carried

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not a boolean
        """
        return self._as_json_boolean(await self._request(event, payload=payload))

    async def _read_object(self, event: str, payload: object = None) -> dict[str, Any]:
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
        return self._as_json_object(await self._request(event, payload=payload))

    async def _read_text(self, event: str, payload: object = None) -> str:
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
        return self._as_json_string(await self._request(event, payload=payload))

    def _receiver(self, event: str) -> Callable[..., Any]:
        """Build the callback the connection calls when the host pushes an event.

        Args:
            event: The name of the event the callback listens for

        Returns:
            The coroutine function handing the payload over to :meth:`_deliver`
        """

        async def receive(payload: object = None) -> None:
            await self._deliver(event, payload)

        return receive

    async def _request(
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
        async with self._request_lock:
            self._log_debug(f'Requesting "{event}", waiting for "{awaited}"...')
            # an answer event outside the map is listened for from its first read on
            self._ensure_registered(awaited)
            arrived = asyncio.Event()
            self._arrived[awaited] = arrived
            try:
                await self._emit(event, payload)
                try:
                    await asyncio.wait_for(arrived.wait(), waited)
                except TimeoutError:
                    self._fail_no_response(event, awaited, waited)
                answer = self._slots.pop(awaited, None)
            finally:
                self._arrived.pop(awaited, None)
            self._log_debug(f'Requesting "{event}", waiting for "{awaited}"... done')
            return answer

    async def add_and_play(self, uri: str) -> None:
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
        items = await self._queue_payload_items(uri)
        payload: object = items if items is not None else self._queue_uri_item(uri)
        await self._emit(EVENT_ADD_PLAY, payload)
        self._log_debug(f'Adding "{uri}" to the queue and playing it... done')

    async def add_cue_track(self, uri: str, number: int, service: str | None = None) -> None:
        """Add one track of a cue sheet to the queue and play it.

        Args:
            uri: The URI of the cue sheet
            number: The position of the track inside the cue sheet
            service: The service the URI belongs to, derived from it when not given

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_ADD_PLAY_CUE, self._cue_payload(uri, number, service))

    async def add_radio_favourite(self, uri: str) -> None:
        """Add a web radio to the radio favourites.

        Args:
            uri: The URL the web radio streams from

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_ADD_TO_RADIO_FAVOURITES, {"uri": uri})

    async def add_share(self, name: str, path: str, fstype: str, **options: str) -> None:
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
        await self._emit(EVENT_ADD_SHARE, payload)

    async def add_to_favourites(
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
        await self._emit(EVENT_ADD_TO_FAVOURITES, payload)

    async def add_to_playlist(
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
        await self._emit(EVENT_ADD_TO_PLAYLIST, self._playlist_item_payload(name, uri, service))

    async def add_to_queue(self, uri: str) -> None:
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
        items = await self._queue_payload_items(uri)
        payload: object = items if items is not None else self._queue_uri_item(uri)
        await self._emit(EVENT_ADD_TO_QUEUE, payload)
        self._log_debug(f'Adding "{uri}" to the queue... done')

    async def add_uids_to_queue(self, uids: list[str]) -> None:
        """Add items of the local library to the queue, by identifier.

        Args:
            uids: The identifiers of the items to queue

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_ADD_QUEUE_UIDS, uids)

    async def add_web_radio(self, name: str, uri: str) -> None:
        """Save a web radio of the user.

        Args:
            name: The name to save the web radio under
            uri: The URL it streams from

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_ADD_WEB_RADIO, self._web_radio_payload(name, uri))

    async def audio_output_pause(self, output_id: str) -> None:
        """Pause one audio output of the Volumio instance.

        Args:
            output_id: The identifier of the output to pause

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_AUDIO_OUTPUT_PAUSE, self._audio_output_payload(output_id))

    async def audio_output_play(self, output_id: str) -> None:
        """Start one audio output of the Volumio instance.

        Args:
            output_id: The identifier of the output to start

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_AUDIO_OUTPUT_PLAY, self._audio_output_payload(output_id))

    async def backup(self) -> dict[str, Any]:
        """Read a backup of the configuration of the Volumio instance.

        Returns:
            The backup, as the host reported it

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        return await self._read_object(EVENT_GET_BACKUP)

    async def browse(self, uri: str | None = None) -> BrowseResults:
        """Browse the content the Volumio instance lists at a URI.

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
            await self._read_object(EVENT_BROWSE_LIBRARY, self._browse_payload(uri))
        )

    async def call_plugin_method(
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
        await self._emit(EVENT_CALL_METHOD, payload)

    async def check_for_update(self) -> None:
        """Ask the Volumio instance to check whether an update is available.

        The host reports what it found through the events its user interface listens
        for, which :meth:`on` can be registered for.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_UPDATE_CHECK, {"hideModal": True})

    async def check_update_cache(self) -> None:
        """Ask the Volumio instance to check the update information it cached.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_UPDATE_CHECK_CACHE)

    async def clear(self) -> None:
        """Empty the playback queue.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_CLEAR_QUEUE)

    async def connect(self) -> None:
        """Open the connection to the Volumio WebSocket API.

        Connecting an already connected client does nothing.

        Raises:
            VolumioWebSocketError: If the python-socketio or the aiohttp package is not
                installed
            VolumioConnectionError: If the connection cannot be opened
        """
        if self._connected:
            self._log_debug("Already connected to the Volumio WebSocket API")
            return
        # python-socketio only logs a missing aiohttp, and connects to nothing
        _load_aiohttp()
        sio: Any = _load_socketio("async_websocket")
        url = self.host_configuration.websocket_base_url
        self._log_debug(f'Connecting to the Volumio WebSocket API at "{url}"...')
        self._client = sio.AsyncClient(reconnection=False)
        self._registered = set()
        for event in set(RESPONSE_EVENTS.values()) | set(self._handlers):
            self._ensure_registered(event)
        try:
            await self._client.connect(url)
        except Exception as e:
            self._client = None
            self._registered = set()
            self._fail_connection(e)
        self._connected = True
        self._log_debug(f'Connecting to the Volumio WebSocket API at "{url}"... done')

    async def consume(self, value: bool) -> None:
        """Set the consume mode, which drops each track from the queue once played.

        Args:
            value: True to enable the consume mode, False to disable it

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_SET_CONSUME, self._mode_payload(value))

    async def create_playlist(self, name: str | Playlist) -> None:
        """Create an empty saved playlist.

        Args:
            name: The name to give the playlist, or the playlist itself

        Raises:
            ValueError: If the given playlist has no name
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_CREATE_PLAYLIST, self._playlist_payload(name))

    async def decrease_volume(self) -> None:
        """Decrease the playback volume by one step.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_VOLUME, VOLUME_DOWN)

    async def delete_background(self, name: str) -> None:
        """Delete a background image of the user interface.

        Args:
            name: The name of the background to delete

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_DELETE_BACKGROUND, {"name": name})

    async def delete_folder(self, path: str) -> None:
        """Delete a folder of the collection of the Volumio instance.

        Args:
            path: The path of the folder to delete

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_DELETE_FOLDER, {"item": {"path": path}})

    async def delete_playlist(self, name: str | Playlist) -> None:
        """Delete a saved playlist.

        Args:
            name: The name of the playlist to delete, or the playlist itself

        Raises:
            ValueError: If the given playlist has no name
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_DELETE_PLAYLIST, self._playlist_payload(name))

    async def delete_share(self, share_id: str) -> None:
        """Unmount a network share of the Volumio instance.

        Args:
            share_id: The identifier of the share, from :meth:`get_shares`

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_DELETE_SHARE, {"id": share_id})

    async def delete_user_data(self) -> None:
        """Erase the data of the user from the Volumio host.

        The implementation is deliberately disabled: this erases the data of the user,
        with no undo and no confirmation from Volumio itself. Emit the event yourself
        if you mean it.

        Raises:
            NotImplementedError: Always
        """
        # await self._emit(EVENT_DELETE_USER_DATA)
        raise NotImplementedError(
            "delete_user_data() is deliberately not implemented: it erases the data of "
            "the user on the Volumio host. Emit the event yourself if you mean it: "
            'await client.emit("deleteUserData")'
        )

    async def disable_audio_output(self, output_id: str) -> None:
        """Disable one audio output of the Volumio instance.

        Args:
            output_id: The identifier of the output to disable

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_DISABLE_AUDIO_OUTPUT, self._audio_output_payload(output_id))

    async def disable_plugin(self, category: str, name: str) -> None:
        """Disable an installed plugin of the Volumio instance.

        Args:
            category: The category the plugin belongs to
            name: The name of the plugin

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_DISABLE_PLUGIN, self._plugin_payload(category, name))

    async def disconnect(self) -> None:
        """Close the connection to the Volumio WebSocket API.

        This method is safe to call multiple times and will not raise exceptions.
        """
        if self._connected:
            self._log_debug("Disconnecting from the Volumio WebSocket API...")
            try:
                await self._client.disconnect()
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

    async def discover_network_shares(self) -> dict[str, Any]:
        """Discover the network shares reachable from the Volumio instance.

        Returns:
            The shares the host found, as it reported them

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        return await self._read_object(EVENT_GET_NETWORK_SHARES_DISCOVERY)

    async def edit_share(self, share_id: str, **fields: str) -> None:
        """Change a network share mounted by the Volumio instance.

        Args:
            share_id: The identifier of the share, from :meth:`get_shares`
            **fields: The fields to change (``name``, ``path``, ``fstype``, ``username``,
                ``password``, ``options``)

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        payload: dict[str, Any] = {"id": share_id, **fields}
        await self._emit(EVENT_EDIT_SHARE, payload)

    async def emit(self, event: str, payload: object = None) -> None:
        """Send an event to the Volumio instance, without waiting for anything.

        Args:
            event: The name of the event to emit
            payload: What the event carries, when it carries anything

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(event, payload)

    async def enable_audio_output(self, output_id: str) -> None:
        """Enable one audio output of the Volumio instance.

        Args:
            output_id: The identifier of the output to enable

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_ENABLE_AUDIO_OUTPUT, self._audio_output_payload(output_id))

    async def enable_plugin(self, category: str, name: str) -> None:
        """Enable an installed plugin of the Volumio instance.

        Args:
            category: The category the plugin belongs to
            name: The name of the plugin

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_ENABLE_PLUGIN, self._plugin_payload(category, name))

    async def enqueue_playlist(self, name: str | Playlist) -> None:
        """Append a saved playlist to the queue, without touching the playback.

        Args:
            name: The name of the playlist to append, or the playlist itself

        Raises:
            ValueError: If the given playlist has no name
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_ENQUEUE, self._playlist_payload(name))

    async def factory_reset(self) -> None:
        """Reset the Volumio host to its factory configuration.

        The implementation is deliberately disabled: this erases every setting on the
        host, with no undo and no confirmation from Volumio itself. Emit the event
        yourself if you mean it.

        Raises:
            NotImplementedError: Always
        """
        # await self._emit(EVENT_FACTORY_RESET)
        raise NotImplementedError(
            "factory_reset() is deliberately not implemented: it erases every setting "
            "on the Volumio host. Emit the event yourself if you mean it: "
            'await client.emit("factoryReset")'
        )

    async def get_alarms(self) -> Alarms:
        """Get the alarms set on the Volumio instance.

        The alarms come from the ``alarm-clock`` plugin: a host without it never
        answers, and the read times out.

        Returns:
            The alarms set on the host

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an array
        """
        return Alarms.from_raw({"alarms": await self._read_array(EVENT_GET_ALARMS)})

    async def get_audio_outputs(self) -> AudioOutputs:
        """Get the audio outputs the Volumio instance can play to.

        Returns:
            The audio outputs of the host

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        return AudioOutputs.from_raw(await self._read_object(EVENT_GET_AUDIO_OUTPUTS))

    async def get_available_timezones(self) -> Timezones:
        """The time zones the Volumio instance can be set to.

        Returns:
            The names of the time zones

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an array
        """
        zones = await self._read_array(EVENT_GET_AVAILABLE_TIMEZONES)
        return Timezones.from_raw({"timezones": zones})

    async def get_backgrounds(self) -> Backgrounds:
        """The background images of the user interface of the Volumio instance.

        Returns:
            The background images, and the one in use

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        return Backgrounds.from_raw(await self._read_object(EVENT_GET_BACKGROUNDS))

    async def get_browse_sources(self) -> BrowseSources:
        """Get the sources the Volumio instance can browse.

        These are the roots the URIs of :meth:`browse` descend from.

        Returns:
            The browsable sources

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an array
        """
        sources = await self._read_array(EVENT_GET_BROWSE_SOURCES)
        return BrowseSources.from_raw({"sources": sources})

    async def get_collection_statistics(self) -> CollectionStatistics:
        """Get the statistics of the music collection of the Volumio instance.

        Returns:
            The statistics of the music collection

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        return CollectionStatistics.from_raw(
            await self._read_object(EVENT_GET_MY_COLLECTION_STATS)
        )

    async def get_device_info(self) -> DeviceInfo:
        """Get the identity of the Volumio instance.

        Returns:
            The name and hardware identifier of the host

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        return DeviceInfo.from_raw(await self._read_object(EVENT_GET_DEVICE_INFO))

    async def get_device_name(self) -> str | None:
        """Get the name of the Volumio instance.

        Returns:
            The name of the host, None when it reports none

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        answer = await self._read_object(EVENT_GET_DEVICE_NAME)
        return DeviceInfo.from_raw(answer).name

    async def get_device_uuid(self) -> str:
        """Get the hardware identifier of the Volumio instance.

        Returns:
            The hardware identifier of the host

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not a string
        """
        return await self._read_text(EVENT_GET_DEVICE_HW_UUID)

    async def get_dsp_config(self) -> UiConfig:
        """Get the configuration page of the DSP of the Volumio instance.

        Returns:
            The configuration page of the DSP

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        return UiConfig.from_raw(await self._read_object(EVENT_GET_DSP_UI_CONFIG))

    async def get_experience_settings(self) -> ExperienceSettings:
        """How many options the user interface of the Volumio instance offers.

        Returns:
            The experience settings of the host

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        answer = await self._read_object(EVENT_GET_EXPERIENCE_ADVANCED_SETTINGS)
        return ExperienceSettings.from_raw(answer)

    async def get_extended_output_devices(self) -> OutputDevices:
        """Get the output devices of the Volumio instance, with their details.

        Returns:
            The output devices, with their details

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        return OutputDevices.from_envelope(
            await self._read_object(EVENT_GET_EXTENDED_OUTPUT_DEVICES)
        )

    async def get_infinity_playback(self) -> InfinityPlayback:
        """The infinity playback setting of the Volumio instance.

        Returns:
            The infinity playback setting

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        return InfinityPlayback.from_raw(await self._read_object(EVENT_GET_INFINITY_PLAYBACK))

    async def get_input_sources(self) -> InputSources:
        """Get the input sources the Volumio instance exposes.

        Returns:
            The input sources of the host

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        return InputSources.from_raw(await self._read_object(EVENT_GET_INPUT_SOURCES))

    async def get_installed_plugins(self) -> Plugins:
        """Get the plugins installed on the Volumio instance.

        Returns:
            The installed plugins

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an array
        """
        plugins = await self._read_array(EVENT_GET_INSTALLED_PLUGINS)
        return Plugins.from_raw({"plugins": plugins})

    async def get_languages(self) -> Languages:
        """The languages the user interface of the Volumio instance can be shown in.

        Returns:
            The languages, and the one in use

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        return Languages.from_raw(await self._read_object(EVENT_GET_AVAILABLE_LANGUAGES))

    async def get_last_browse(self) -> BrowseResults:
        """Get the listing the Volumio instance pushed last, to any of its clients.

        Returns:
            The last listing the host pushed

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        return BrowseResults.from_envelope(
            await self._read_object(EVENT_GET_LAST_PUSHED_BROWSE_LIBRARY)
        )

    async def get_menu_items(self) -> MenuItems:
        """Get the menu the Volumio instance offers its user interface.

        Returns:
            The menu entries

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an array
        """
        return MenuItems.from_raw({"items": await self._read_array(EVENT_GET_MENU_ITEMS)})

    async def get_multiroom(self) -> Multiroom:
        """Get the multiroom configuration of the Volumio instance.

        The configuration comes from the ``multiroom``
        plugin: a host without it never answers, and the read times out.

        Returns:
            The multiroom configuration of the host

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        return Multiroom.from_raw(await self._read_object(EVENT_GET_MULTIROOM))

    async def get_music_sources(self) -> MusicSources:
        """Get the music source plugins of the Volumio instance.

        Returns:
            The music sources of the host

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an array
        """
        sources = await self._read_array(EVENT_GET_MY_MUSIC_PLUGINS)
        return MusicSources.from_raw({"plugins": sources})

    async def get_network_info(self) -> NetworkInfo:
        """Get the network interfaces of the Volumio instance.

        Returns:
            The network interfaces of the host

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an array
        """
        interfaces = await self._read_array(EVENT_GET_INFO_NETWORK)
        return NetworkInfo.from_raw({"interfaces": interfaces})

    async def get_output_devices(self) -> OutputDevices:
        """Get the output devices the Volumio instance can play through.

        Returns:
            The output devices of the host

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        return OutputDevices.from_envelope(await self._read_object(EVENT_GET_OUTPUT_DEVICES))

    async def get_playlist_content(self, name: str | Playlist) -> PlaylistContent:
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
            await self._read_object(EVENT_GET_PLAYLIST_CONTENT, self._playlist_payload(name))
        )

    async def get_playlists(self) -> Playlists:
        """Get the saved playlists of the Volumio instance.

        Returns:
            The saved playlists, by name

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an array
        """
        return Playlists.from_names(await self._read_array(EVENT_LIST_PLAYLIST))

    async def get_plugin_config(self, page: str) -> UiConfig:
        """Read the configuration page a plugin of the Volumio instance offers.

        Args:
            page: The plugin, as ``"category/name"`` (e.g., ``"system_controller/system"``)

        Returns:
            The configuration page of the plugin

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        return UiConfig.from_raw(await self._read_object(EVENT_GET_UI_CONFIG, {"page": page}))

    async def get_power_modes(self) -> PowerModes:
        """Get the ways the Volumio instance can be powered down.

        A host that reports no standby mode answers :meth:`standby` by powering off
        instead.

        Returns:
            The power modes of the host

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        answer = await self._read_object(EVENT_GET_SHUTDOWN_OR_STANDBY_MODE)
        return PowerModes.from_raw(answer)

    async def get_privacy_settings(self) -> PrivacySettings:
        """The privacy settings of the Volumio instance.

        Returns:
            The privacy settings of the host

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        return PrivacySettings.from_raw(await self._read_object(EVENT_GET_PRIVACY_SETTINGS))

    async def get_queue(self) -> Queue:
        """Get the current playback queue of the Volumio instance.

        Returns:
            The current playback queue

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an array
        """
        return Queue.from_raw({"queue": await self._read_array(EVENT_GET_QUEUE)})

    async def get_queue_status(self) -> dict[str, Any]:
        """Get the navigation state of the queue, as a small mapping.

        The keys are ``has_next`` and ``has_previous`` (whether the current track
        has a neighbor in the queue), ``length`` (the number of queued tracks),
        ``position`` (the 0-based index of the current track, None without one),
        and ``track`` (the playback state payload, as the Volumio host pushed it).

        Returns:
            The navigation state of the queue

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If an answer is of an unexpected shape
        """
        state = await self.get_state()
        count = len(await self.get_queue())
        return self._queue_status(state, count)

    async def get_seek(self) -> int:
        """Get the seek position, in seconds, in the track currently playing.

        Returns:
            The current seek position, in seconds

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the state carries no integer seek position
        """
        return self._state_seek(await self.get_state())

    async def get_share(self, share_id: str) -> Share:
        """Read the details of one network share of the Volumio instance.

        Args:
            share_id: The identifier of the share, from :meth:`get_shares`

        Returns:
            The details of the share

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        return Share.from_raw(await self._read_object(EVENT_GET_INFO_SHARE, {"id": share_id}))

    async def get_shares(self) -> Shares:
        """Get the network shares mounted by the Volumio instance.

        Returns:
            The mounted shares

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an array
        """
        return Shares.from_raw({"shares": await self._read_array(EVENT_GET_LIST_SHARES)})

    async def get_sleep_timer(self) -> SleepTimer:
        """Get the sleep timer of the Volumio instance.

        Read the remaining delay off :attr:`SleepTimer.delay`, which parses it as the
        duration it is.

        Returns:
            The sleep timer of the host

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        return SleepTimer.from_raw(await self._read_object(EVENT_GET_SLEEP))

    async def get_state(self) -> PlayerState:
        """Get the current playback state of the Volumio instance.

        A Volumio host broadcasts the state on every change of it, so the answer may be
        a broadcast the client did not ask for -- which carries the current state all
        the same.

        Returns:
            The current playback state of the Volumio instance

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        return PlayerState.from_raw(await self._read_object(EVENT_GET_STATE))

    async def get_system_info(self) -> SystemInfo:
        """Get the system information of the Volumio instance.

        Returns:
            The system information of the host

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        return SystemInfo.from_raw(await self._read_object(EVENT_GET_SYSTEM_INFO))

    async def get_system_version(self) -> SystemVersion:
        """Get the Volumio version the instance runs.

        Returns:
            The version of the host

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        return SystemVersion.from_raw(await self._read_object(EVENT_GET_SYSTEM_VERSION))

    async def get_timezone(self) -> str:
        """Get the time zone of the Volumio instance.

        Returns:
            The name of the time zone (e.g., ``"Europe/Rome"``)

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not a string
        """
        return await self._read_text(EVENT_GET_CURRENT_TIMEZONE)

    async def get_ui_settings(self) -> UiSettings:
        """The look of the user interface of the Volumio instance.

        Returns:
            The colour, language, and theme of the interface

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        return UiSettings.from_raw(await self._read_object(EVENT_GET_UI_SETTINGS))

    async def get_updater_channel(self) -> UpdaterChannel:
        """Get the update channel the Volumio instance follows.

        Returns:
            The update channel of the host, and the ones it can follow

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        return UpdaterChannel.from_raw(await self._read_object(EVENT_GET_UPDATER_CHANNEL))

    async def get_usb_drives(self) -> UsbDrives:
        """Get the USB drives attached to the Volumio instance.

        Returns:
            The attached drives

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an array
        """
        return UsbDrives.from_raw({"drives": await self._read_array(EVENT_LIST_USB_DRIVES)})

    async def get_volume(self) -> int:
        """Get the playback volume level of the Volumio instance.

        Returns:
            The volume level, an integer between 0 and 100 (inclusive)

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the state carries no integer volume level
        """
        return self._state_volume(await self.get_state())

    async def get_wireless_networks(self) -> WirelessNetworks:
        """The wireless networks the Volumio instance can see, scanning for them.

        A scan takes a moment: a host with no
        wireless interface never answers, and the read times out. See
        :meth:`get_wireless_networks_cache` for the networks it saw last.

        Returns:
            The wireless networks the host can see

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        return WirelessNetworks.from_raw(await self._read_object(EVENT_GET_WIRELESS_NETWORKS))

    async def get_wireless_networks_cache(self) -> WirelessNetworks:
        """Get the wireless networks the Volumio instance saw last, without scanning again.

        Returns:
            The wireless networks the host saw last

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        answer = await self._read_object(EVENT_GET_WIRELESS_NETWORKS_CACHE)
        return WirelessNetworks.from_raw(answer)

    async def get_zones(self) -> Zones:
        """Get the multiroom zones the Volumio instance sees.

        The host answers with the devices under a ``list`` key, which the model reads
        as its zones.

        Returns:
            The multiroom zones

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        answer = await self._read_object(EVENT_GET_MULTI_ROOM_DEVICES)
        return Zones.from_raw({"zones": answer.get("list", [])})

    async def goto(self, kind: str, value: str) -> BrowseResults:
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
            await self._read_object(EVENT_GO_TO, self._goto_payload(kind, value))
        )

    async def has_next(self) -> bool:
        """Whether the current track has a next track in the queue.

        Returns:
            True if the queue holds a track after the current one, False otherwise

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If an answer is of an unexpected shape
        """
        return bool((await self.get_queue_status())["has_next"])

    async def has_previous(self) -> bool:
        """Whether the current track has a previous track in the queue.

        Returns:
            True if the queue holds a track before the current one, False otherwise

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If an answer is of an unexpected shape
        """
        return bool((await self.get_queue_status())["has_previous"])

    async def import_service_playlists(self) -> None:
        """Import the playlists the music services of the host expose.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_IMPORT_SERVICE_PLAYLISTS)

    async def increase_volume(self) -> None:
        """Increase the playback volume by one step.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_VOLUME, VOLUME_UP)

    async def install_plugin(self, url: str) -> None:
        """Install a plugin on the Volumio instance, from a URL.

        The host reports its progress through the events its user interface listens
        for, which :meth:`on` can be registered for.

        Args:
            url: The URL of the plugin package

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_INSTALL_PLUGIN, {"url": url, "confirm": True})

    async def install_to_disk(self) -> None:
        """Write Volumio to the internal storage of the host.

        The implementation is deliberately disabled: this overwrites whatever the
        internal storage of the host holds, with no undo and no confirmation from
        Volumio itself. Emit the event yourself if you mean it.

        Raises:
            NotImplementedError: Always
        """
        # await self._emit(EVENT_INSTALL_TO_DISK)
        raise NotImplementedError(
            "install_to_disk() is deliberately not implemented: it overwrites the "
            "internal storage of the Volumio host. Emit the event yourself if you "
            'mean it: await client.emit("installToDisk")'
        )

    async def is_automatic_update_enabled(self) -> bool:
        """Whether the Volumio instance updates itself.

        Returns:
            True if the host updates itself, False otherwise

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not a boolean
        """
        return await self._read_boolean(EVENT_GET_AUTOMATIC_UPDATE_ENABLED)

    async def is_muted(self) -> bool:
        """Whether the playback volume of the Volumio instance is muted.

        Returns:
            True if the volume is muted, False otherwise

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the state carries no boolean mute flag
        """
        return self._state_mute(await self.get_state())

    async def is_paused(self) -> bool:
        """Whether the Volumio instance is paused.

        Returns:
            True if the playback is paused, False otherwise

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the state carries no string status
        """
        return self._state_status(await self.get_state()) == "pause"

    async def is_playing(self) -> bool:
        """Whether the Volumio instance is playing.

        Returns:
            True if the playback is running, False otherwise

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the state carries no string status
        """
        return self._state_status(await self.get_state()) == "play"

    async def is_stopped(self) -> bool:
        """Whether the Volumio instance is stopped.

        Returns:
            True if the playback is stopped, False otherwise

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the state carries no string status
        """
        return self._state_status(await self.get_state()) == "stop"

    async def manage_plugin(self, action: str, category: str, name: str) -> Plugins:
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
        plugins = await self._read_array(EVENT_PLUGIN_MANAGER, payload)
        return Plugins.from_raw({"plugins": plugins})

    async def modify_plugin_status(self, category: str, name: str, enabled: bool) -> None:
        """Enable or disable an installed plugin in one call.

        Args:
            category: The category the plugin belongs to
            name: The name of the plugin
            enabled: True to enable the plugin, False to disable it

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        payload = {**self._plugin_payload(category, name), "enabled": enabled}
        await self._emit(EVENT_MODIFY_PLUGIN_STATUS, payload)

    async def move_in_queue(self, source: int, target: int) -> None:
        """Move a track to another position of the queue.

        Args:
            source: The position the track is at (0-based)
            target: The position to move it to (0-based)

        Raises:
            ValueError: If either position is negative
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_MOVE_QUEUE, self._move_payload(source, target))

    async def mute(self) -> None:
        """Mute the playback volume.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_MUTE)

    async def next(self) -> None:
        """Skip to the next track in the queue.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_NEXT)

    def off(self, event: str, handler: Callable[[Any], Any] | None = None) -> None:
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

    def on(self, event: str, handler: Callable[[Any], Any]) -> None:
        """Call a handler with the payload of an event whenever the host pushes it.

        A Volumio host pushes some events on its own -- ``pushState`` on every change of
        the playback state, and a few more the moment the connection opens -- and pushes
        others as the answer to a read, in which case the handler is called too.

        Handlers can be registered before connecting, and may be coroutine functions or
        ordinary ones. An exception one raises is logged and swallowed, so one failing
        handler does not stop the others.

        Args:
            event: The name of the event to listen for (e.g., ``"pushState"``)
            handler: The callable receiving the payload of the event
        """
        self._handlers.setdefault(event, []).append(handler)
        self._ensure_registered(event)
        self._log_debug(f'Added a handler of "{event}"')

    async def pause(self) -> None:
        """Pause the playback.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_PAUSE)

    async def ping(self) -> str:
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
        echoed = await self._request(EVENT_PINGER, payload={"nonce": nonce})
        if not isinstance(echoed, dict) or echoed.get("nonce") != nonce:
            self._log_warning(f"The Volumio API answered a ping with {echoed!r}")
            self._fail_no_response(EVENT_PINGER, self._response_event(EVENT_PINGER), self.timeout)
        return "pong"

    async def play(self, position: int | QueueTrack | None = None) -> None:
        """Start the playback, optionally at a position of the queue.

        Args:
            position: Optional position in the queue to play (0-indexed), or a track
                of the queue

        Raises:
            ValueError: If the given track does not know its position in the queue
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_PLAY, self._play_payload(position))

    async def play_favourites(self, name: str | None = None) -> None:
        """Play the favourites, optionally starting at one of them.

        Args:
            name: The name of the favourite to start at, the first when not given

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_PLAY_FAVOURITES, {"name": name} if name is not None else None)

    async def play_items(self, items: list[dict[str, Any]], index: int = 0) -> None:
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
        await self._emit(EVENT_PLAY_ITEMS_LIST, payload)

    async def play_next(self, uri: str, title: str | None = None, album: str | None = None) -> None:
        """Queue an item right after the track currently playing.

        Args:
            uri: The URI to queue
            title: The title to show for it, when known
            album: The album to show for it, when known

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_PLAY_NEXT, self._play_next_payload(uri, title, album))

    async def play_playlist(self, name: str | Playlist) -> None:
        """Start the playback of a saved playlist.

        Args:
            name: The name of the playlist to play, or the playlist itself

        Raises:
            ValueError: If the given playlist has no name
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_PLAY_PLAYLIST, self._playlist_payload(name))

    async def play_radio_favourites(self) -> None:
        """Play the radio favourites.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_PLAY_RADIO_FAVOURITES)

    async def play_volatile(self, position: int) -> None:
        """Start a volatile source (e.g., Spotify Connect) at a position.

        Args:
            position: The position to start at (0-based)

        Raises:
            ValueError: If the position is negative
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_VOLATILE_PLAY, self._index_payload(position))

    async def previous(self) -> None:
        """Go back to the previous track in the queue.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_PREVIOUS)

    async def randomize(self, value: bool | None = None) -> None:
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
        wanted = value if value is not None else not (await self.get_state()).random
        await self._emit(EVENT_SET_RANDOM, self._mode_payload(wanted))

    async def reboot(self) -> None:
        """Restart the Volumio host.

        The host drops the connection as it goes down; reconnect once it is back.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_REBOOT)

    async def regenerate_thumbnails(self) -> None:
        """Rebuild the thumbnails of the album art of the collection.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_REGENERATE_THUMBNAILS)

    async def remove_from_favourites(self, uri: str, service: str | None = None) -> None:
        """Remove an item from the favourites.

        Args:
            uri: The URI of the item to remove
            service: The service the URI belongs to, derived from it when not given

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        payload = self._favourite_payload(uri, service=service)
        await self._emit(EVENT_REMOVE_FROM_FAVOURITES, payload)

    async def remove_from_playlist(
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
        await self._emit(
            EVENT_REMOVE_FROM_PLAYLIST, self._playlist_item_payload(name, uri, service)
        )

    async def remove_from_queue(self, position: int) -> None:
        """Remove a track from the queue.

        Args:
            position: The position of the track to remove (0-based)

        Raises:
            ValueError: If the position is negative
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_REMOVE_QUEUE_ITEM, self._index_payload(position))

    async def remove_radio_favourite(self, uri: str, name: str | None = None) -> None:
        """Remove a web radio from the radio favourites.

        Args:
            uri: The URL the web radio streams from
            name: The name it is a favourite under, when known

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        payload = {"uri": uri} if name is None else {"name": name, "uri": uri}
        await self._emit(EVENT_REMOVE_FROM_RADIO_FAVOURITES, payload)

    async def remove_web_radio(self, name: str) -> None:
        """Delete a web radio of the user.

        Args:
            name: The name the web radio was saved under

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_REMOVE_WEB_RADIO, self._web_radio_payload(name))

    async def repeat(self, value: bool | None = None) -> None:
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
        wanted = value if value is not None else not (await self.get_state()).repeat
        await self._emit(EVENT_SET_REPEAT, self._mode_payload(wanted))

    async def replace_queue_and_play(self, uri: str, index: int | None = None) -> None:
        """Replace the queue with the content of a URI and start playing it.

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
            items = await self._browse_items(uri)
            if len(items) > index:
                self._log_debug(f"Sending the {len(items)} listed items, playing index {index}")
                await self._emit(EVENT_REPLACE_AND_PLAY, {"list": items, "index": index})
                self._log_debug(f'Replacing the queue with "{uri}"... done')
                return
            if items or index > 0:
                self._fail_short_listing(len(items), index)
        else:
            listed = await self._queue_payload_items(uri)
            if listed is not None:
                self._log_debug(f"Sending the {len(listed)} listed items, playing the first")
                await self._emit(EVENT_REPLACE_AND_PLAY, {"list": listed, "index": 0})
                self._log_debug(f'Replacing the queue with "{uri}"... done')
                return
        self._log_debug("Sending the URI as a single item, playing its first element")
        await self._emit(EVENT_REPLACE_AND_PLAY, {"item": self._queue_uri_item(uri)})
        self._log_debug(f'Replacing the queue with "{uri}"... done')

    async def replace_queue_with_cue_track(
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
        await self._emit(EVENT_REPLACE_AND_PLAY_CUE, self._cue_payload(uri, number, service))

    async def request(
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
        return await self._request(event, response_event, payload, timeout)

    async def rescan_library(self) -> None:
        """Rescan the music collection of the Volumio instance from scratch.

        This is the slower of the two: :meth:`update_library` only looks for changes.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_RESCAN_DB)

    async def restore_backup(self, backup: dict[str, Any]) -> None:
        """Restore a backup of the configuration of the Volumio instance.

        Args:
            backup: The backup to restore, as :meth:`backup` reported it

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_MANAGE_BACKUP, backup)

    async def restore_config(self) -> None:
        """Restore the configuration of the plugins of the Volumio instance.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_RESTORE_CONFIG)

    async def safe_remove_drive(self, name: str) -> None:
        """Unmount a USB drive of the Volumio instance before it is unplugged.

        Args:
            name: The name of the drive, from :meth:`get_usb_drives`

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_SAFE_REMOVE_DRIVE, {"name": name})

    async def save_queue_as_playlist(self, name: str | Playlist) -> None:
        """Save the current queue as a saved playlist.

        Args:
            name: The name to save the queue under, or the playlist to overwrite

        Raises:
            ValueError: If the given playlist has no name
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_SAVE_QUEUE_TO_PLAYLIST, self._playlist_payload(name))

    async def save_wireless_settings(self, ssid: str, password: str = "") -> None:
        """Join a wireless network with the Volumio instance.

        Args:
            ssid: The name of the network
            password: The password of the network, empty for an open one

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        payload = {"ssid": ssid, "password": password}
        await self._emit(EVENT_SAVE_WIRELESS_NETWORK_SETTINGS, payload)

    async def search(self, query: str) -> SearchResults:
        """Search the sources of the Volumio instance.

        Args:
            query: The text to search for

        Returns:
            The results of the search

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        return SearchResults.from_envelope(
            await self._read_object(EVENT_SEARCH, self._search_payload(query))
        )

    async def seek_backward(self) -> None:
        """Seek backward by 10 seconds in the track currently playing.

        The WebSocket API seeks to absolute positions only, so this reads the current
        position first and never seeks before the start of the track.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
            VolumioAPIError: If the state carries no integer seek position
        """
        current = await self.get_seek()
        await self._emit(EVENT_SEEK, self._seek_payload(max(0, current - SEEK_STEP_SECONDS)))

    async def seek_forward(self) -> None:
        """Seek forward by 10 seconds in the track currently playing.

        The WebSocket API seeks to absolute positions only, so this reads the current
        position first.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
            VolumioAPIError: If the state carries no integer seek position
        """
        current = await self.get_seek()
        await self._emit(EVENT_SEEK, self._seek_payload(current + SEEK_STEP_SECONDS))

    async def set_alarms(self, alarms: list[Alarm]) -> None:
        """Replace the whole set of alarms of the Volumio instance.

        The Volumio API takes the alarms as a set rather than one at a time, so this
        replaces every alarm the host holds: read :meth:`get_alarms` first and send back
        the list you want to keep.

        Args:
            alarms: The alarms to keep

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_SAVE_ALARM, self._alarms_payload(alarms))

    async def set_as_multiroom_client(self, server: str) -> None:
        """Make the Volumio instance a multiroom client of another host.

        Args:
            server: The address of the host to follow

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_SET_AS_MULTIROOM_CLIENT, {"server": server})

    async def set_as_multiroom_server(self) -> None:
        """Make the Volumio instance a multiroom server.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_SET_AS_MULTIROOM_SERVER)

    async def set_as_multiroom_single(self) -> None:
        """Take the Volumio instance out of multiroom.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_SET_AS_MULTIROOM_SINGLE)

    async def set_audio_output_volume(self, output_id: str, volume: int) -> None:
        """Set the volume of one audio output of the Volumio instance.

        This is the volume of one output; :meth:`get_volume` is the volume of the host.

        Args:
            output_id: The identifier of the output
            volume: The volume level, an integer between 0 and 100 (inclusive)

        Raises:
            ValueError: If the volume level is out of range
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        payload = self._audio_output_payload(output_id, volume)
        await self._emit(EVENT_SET_AUDIO_OUTPUT_VOLUME, payload)

    async def set_background(self, name: str, path: str | None = None) -> None:
        """Choose the background image of the user interface.

        Args:
            name: The name of the background, from :meth:`get_backgrounds`
            path: The path of its image, when the host needs it named too

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        payload = {"name": name} if path is None else {"name": name, "path": path}
        await self._emit(EVENT_SET_BACKGROUNDS, payload)

    async def set_device_name(self, value: str) -> None:
        """Rename the Volumio host.

        Args:
            value: The name to give the host

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_SET_DEVICE_NAME, {"name": value})

    async def set_experience_settings(self, advanced: bool) -> None:
        """Choose how many options the user interface of the Volumio instance offers.

        Args:
            advanced: True for the full set of options, False for the simplified one
                (the host stores the flag itself, and reports it back wrapped in its label)

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_SET_EXPERIENCE_ADVANCED_SETTINGS, advanced)

    async def set_infinity_playback(self, enabled: bool) -> None:
        """Turn infinity playback on or off.

        Args:
            enabled: True to enable infinity playback, False to disable it

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_SET_INFINITY_PLAYBACK, {"enabled": enabled})

    async def set_language(self, code: str, language: str | None = None) -> None:
        """Choose the language of the user interface of the Volumio instance.

        Args:
            code: The code of the language (e.g., ``"en"``), from :meth:`get_languages`
            language: The name of the language, when the host needs it named too

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        chosen = {"code": code, "language": language if language is not None else code}
        await self._emit(EVENT_SET_LANGUAGE, {"defaultLanguage": chosen})

    async def set_multiroom(self, settings: dict[str, Any]) -> Multiroom:
        """Change the multiroom configuration of the Volumio instance.

        Args:
            settings: The configuration to apply

        Returns:
            The configuration as it stands afterwards

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an object
        """
        return Multiroom.from_raw(await self._read_object(EVENT_SET_MULTIROOM, settings))

    async def set_music_source_enabled(self, name: str, enabled: bool) -> None:
        """Enable or disable one music source of the Volumio instance.

        Args:
            name: The name of the source, from :meth:`get_music_sources`
            enabled: True to enable the source, False to disable it

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        payload = {"name": name, "enabled": enabled}
        await self._emit(EVENT_ENABLE_DISABLE_MY_MUSIC_PLUGIN, payload)

    async def set_output_device(self, device_id: str, mixer: str | None = None) -> None:
        """Choose the output device the Volumio instance plays through.

        Args:
            device_id: The identifier of the device, from :meth:`get_output_devices`
            mixer: The mixer to drive its volume with, left to the host when not given

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        payload = self._output_device_payload(device_id, mixer)
        await self._emit(EVENT_SET_OUTPUT_DEVICES, payload)

    async def set_seek(self, value: int) -> None:
        """Seek to an absolute position in the track currently playing.

        Args:
            value: The position to seek to, in seconds

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_SEEK, self._seek_payload(value))

    async def set_sleep_timer(self, delay: timedelta | None) -> None:
        """Arm or disarm the sleep timer of the Volumio instance.

        The Volumio API reads the time of a sleep timer as a delay from now, not as a
        clock time, so ``timedelta(minutes=30)`` stops the host in half an hour.

        The timer comes from the ``alarm-clock`` plugin, and so does
        :meth:`get_sleep_timer`.

        Args:
            delay: How long from now the host should stop, or None to disarm the timer

        Raises:
            ValueError: If the delay is negative
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_SET_SLEEP, self._sleep_payload(delay))

    async def set_timezone(self, value: str) -> None:
        """Move the Volumio instance to another time zone.

        Args:
            value: The name of the zone, from :meth:`get_available_timezones`

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_SET_TIMEZONE, {"timeZone": value})

    async def set_updater_channel(self, value: str) -> None:
        """Move the Volumio instance to another update channel.

        Args:
            value: The channel to follow, one of the available ones

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_SET_UPDATER_CHANNEL, {"channel": value})

    async def set_volume(self, value: int) -> None:
        """Set the playback volume to an absolute level.

        Args:
            value: The volume level, an integer between 0 and 100 (inclusive)

        Raises:
            ValueError: If the volume level is out of range
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_VOLUME, self._volume_payload(value))

    async def shutdown(self) -> None:
        """Power the Volumio host off.

        The host drops the connection as it goes down, and does not come back on its
        own.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_SHUTDOWN)

    async def standby(self) -> None:
        """Put the Volumio host on standby.

        A host whose :meth:`get_power_modes` report no standby mode powers off instead.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_STANDBY)

    async def stop(self) -> None:
        """Stop the playback.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_STOP)

    async def super_search(self, query: str) -> SearchResults:
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
            await self._read_object(EVENT_SUPER_SEARCH, self._search_payload(query))
        )

    async def toggle(self) -> None:
        """Toggle between playing and paused.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_TOGGLE)

    async def uninstall_plugin(self, category: str, name: str) -> None:
        """Remove an installed plugin from the Volumio instance.

        Args:
            category: The category the plugin belongs to
            name: The name of the plugin

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_UNINSTALL_PLUGIN, self._plugin_payload(category, name))

    async def unmute(self) -> None:
        """Unmute the playback volume.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_UNMUTE)

    async def update(self, ignore_integrity_check: bool = False) -> None:
        """Install the update the Volumio instance found.

        The host reports its progress through the events its user interface listens
        for, and restarts when it is done.

        Args:
            ignore_integrity_check: True to install even when the check fails

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_UPDATE, {"ignoreIntegrityCheck": ignore_integrity_check})

    async def update_all_metadata(self) -> None:
        """Refresh the metadata of the whole collection of the Volumio instance.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_UPDATE_ALL_METADATA)

    async def update_library(self, uri: str | None = None) -> None:
        """Update the music collection of the Volumio instance, looking for changes.

        Args:
            uri: The URI to update, the whole collection when not given

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_UPDATE_DB, uri)

    async def update_plugin(self, category: str, name: str) -> None:
        """Update an installed plugin of the Volumio instance.

        Args:
            category: The category the plugin belongs to
            name: The name of the plugin

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_UPDATE_PLUGIN, self._plugin_payload(category, name))

    async def update_service_tracklist(self, service: str) -> None:
        """Refresh the tracks one music service of the Volumio instance offers.

        Args:
            service: The name of the service to refresh

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_SERVICE_UPDATE_TRACKLIST, service)

    async def wait(self) -> None:
        """Block until the connection to the Volumio instance drops.

        Raises:
            VolumioConnectionError: If not connected
        """
        if not self._connected:
            self._fail_not_connected("wait for events")
        self._log_debug("Waiting for the connection to drop...")
        await self._client.wait()
        self._log_debug("Waiting for the connection to drop... done")

    async def write_multiroom(self, settings: dict[str, Any]) -> None:
        """Write the multiroom configuration of the Volumio instance.

        Args:
            settings: The configuration to write

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_WRITE_MULTIROOM, settings)

    async def __aenter__(self) -> Self:
        """Async context manager entry - connects to the Volumio WebSocket API.

        Returns:
            The VolumioAsyncWebSocketClient instance

        Raises:
            VolumioWebSocketError: If the python-socketio package is not installed
            VolumioConnectionError: If the connection cannot be opened
        """
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Async context manager exit - disconnects from the Volumio WebSocket API.

        Args:
            exc_type: Exception type (if any)
            exc_val: Exception value (if any)
            exc_tb: Exception traceback (if any)
        """
        await self.disconnect()
