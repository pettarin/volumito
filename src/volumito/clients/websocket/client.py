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
from types import ModuleType, TracebackType
from typing import Any, Self, cast

from volumito.clients.errors import VolumioWebSocketError
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
from volumito.clients.websocket.common import (
    EVENT_ADD_PLAY,
    EVENT_ADD_PLAY_CUE,
    EVENT_ADD_QUEUE_UIDS,
    EVENT_ADD_TO_QUEUE,
    EVENT_BROWSE_LIBRARY,
    EVENT_CLEAR_QUEUE,
    EVENT_GET_MULTI_ROOM_DEVICES,
    EVENT_GET_MY_COLLECTION_STATS,
    EVENT_GET_QUEUE,
    EVENT_GET_STATE,
    EVENT_GET_SYSTEM_INFO,
    EVENT_GET_SYSTEM_VERSION,
    EVENT_GO_TO,
    EVENT_LIST_PLAYLIST,
    EVENT_MOVE_QUEUE,
    EVENT_MUTE,
    EVENT_NEXT,
    EVENT_PAUSE,
    EVENT_PINGER,
    EVENT_PLAY,
    EVENT_PLAY_ITEMS_LIST,
    EVENT_PLAY_NEXT,
    EVENT_PLAY_PLAYLIST,
    EVENT_PREVIOUS,
    EVENT_REMOVE_QUEUE_ITEM,
    EVENT_REPLACE_AND_PLAY,
    EVENT_REPLACE_AND_PLAY_CUE,
    EVENT_SAVE_QUEUE_TO_PLAYLIST,
    EVENT_SEARCH,
    EVENT_SEEK,
    EVENT_SET_CONSUME,
    EVENT_SET_RANDOM,
    EVENT_SET_REPEAT,
    EVENT_STOP,
    EVENT_TOGGLE,
    EVENT_UNMUTE,
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

    def decrease_volume(self) -> None:
        """Decrease the playback volume by one step.

        The decrement is the one defined in the settings of the Volumio host.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_VOLUME, VOLUME_DOWN)

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

    def increase_volume(self) -> None:
        """Increase the playback volume by one step.

        The increment is the one defined in the settings of the Volumio host.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_VOLUME, VOLUME_UP)

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

    def mute(self) -> None:
        """Mute the playback volume.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_MUTE)

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

    def remove_from_queue(self, position: int) -> None:
        """Remove a track from the queue.

        Args:
            position: The position of the track to remove (0-based)

        Raises:
            ValueError: If the position is negative
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_REMOVE_QUEUE_ITEM, self._index_payload(position))

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

    def save_queue_as_playlist(self, name: str | Playlist) -> None:
        """Save the current queue as a saved playlist.

        Args:
            name: The name to save the queue under, or the playlist to overwrite

        Raises:
            ValueError: If the given playlist has no name
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_SAVE_QUEUE_TO_PLAYLIST, self._playlist_payload(name))

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

    def unmute(self) -> None:
        """Unmute the playback volume.

        Raises:
            VolumioConnectionError: If not connected, or if the event cannot be sent
        """
        self._emit(EVENT_UNMUTE)

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
