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
from types import TracebackType
from typing import Any, Self

from volumito.clients.host_configuration import VolumioHostConfiguration
from volumito.clients.models import (
    BrowseResults,
    CollectionStatistics,
    PlayerState,
    Playlist,
    Playlists,
    Queue,
    QueueTrack,
    SearchResults,
    SystemInfo,
    SystemVersion,
    Zones,
)
from volumito.clients.websocket.client import SEEK_STEP_SECONDS, _load_socketio
from volumito.clients.websocket.common import (
    EVENT_ADD_TO_QUEUE,
    EVENT_BROWSE_LIBRARY,
    EVENT_CLEAR_QUEUE,
    EVENT_GET_MULTI_ROOM_DEVICES,
    EVENT_GET_MY_COLLECTION_STATS,
    EVENT_GET_QUEUE,
    EVENT_GET_STATE,
    EVENT_GET_SYSTEM_INFO,
    EVENT_GET_SYSTEM_VERSION,
    EVENT_LIST_PLAYLIST,
    EVENT_MUTE,
    EVENT_NEXT,
    EVENT_PAUSE,
    EVENT_PINGER,
    EVENT_PLAY,
    EVENT_PLAY_PLAYLIST,
    EVENT_PREVIOUS,
    EVENT_REPLACE_AND_PLAY,
    EVENT_SEARCH,
    EVENT_SEEK,
    EVENT_SET_RANDOM,
    EVENT_SET_REPEAT,
    EVENT_STOP,
    EVENT_TOGGLE,
    EVENT_UNMUTE,
    EVENT_VOLUME,
    RESPONSE_EVENTS,
    VOLUME_DOWN,
    VOLUME_UP,
    VolumioWebSocketCommon,
)


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
            VolumioWebSocketError: If the python-socketio package is not installed
            VolumioConnectionError: If the connection cannot be opened
        """
        if self._connected:
            self._log_debug("Already connected to the Volumio WebSocket API")
            return
        sio: Any = _load_socketio()
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

    async def decrease_volume(self) -> None:
        """Decrease the playback volume by one step.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_VOLUME, VOLUME_DOWN)

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

    async def emit(self, event: str, payload: object = None) -> None:
        """Send an event to the Volumio instance, without waiting for anything.

        Args:
            event: The name of the event to emit
            payload: What the event carries, when it carries anything

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(event, payload)

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

    async def get_playlists(self) -> Playlists:
        """Get the saved playlists of the Volumio instance.

        Returns:
            The saved playlists, by name

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the answer is not an array
        """
        return Playlists.from_names(await self._read_array(EVENT_LIST_PLAYLIST))

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

    async def get_volume(self) -> int:
        """Get the playback volume level of the Volumio instance.

        Returns:
            The volume level, an integer between 0 and 100 (inclusive)

        Raises:
            VolumioConnectionError: If not connected, or if the host does not answer
            VolumioAPIError: If the state carries no integer volume level
        """
        return self._state_volume(await self.get_state())

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

    async def increase_volume(self) -> None:
        """Increase the playback volume by one step.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_VOLUME, VOLUME_UP)

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

    async def play_playlist(self, name: str | Playlist) -> None:
        """Start the playback of a saved playlist.

        Args:
            name: The name of the playlist to play, or the playlist itself

        Raises:
            ValueError: If the given playlist has no name
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_PLAY_PLAYLIST, self._playlist_payload(name))

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

    async def set_seek(self, value: int) -> None:
        """Seek to an absolute position in the track currently playing.

        Args:
            value: The position to seek to, in seconds

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_SEEK, self._seek_payload(value))

    async def set_volume(self, value: int) -> None:
        """Set the playback volume to an absolute level.

        Args:
            value: The volume level, an integer between 0 and 100 (inclusive)

        Raises:
            ValueError: If the volume level is out of range
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_VOLUME, self._volume_payload(value))

    async def stop(self) -> None:
        """Stop the playback.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_STOP)

    async def toggle(self) -> None:
        """Toggle between playing and paused.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_TOGGLE)

    async def unmute(self) -> None:
        """Unmute the playback volume.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        await self._emit(EVENT_UNMUTE)

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
