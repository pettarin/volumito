"""The API client adapters of the volumito CLI.

The library offers four clients for the APIs of a Volumio host: the synchronous and the
asynchronous REST API clients, and the synchronous and the asynchronous WebSocket API
clients. The commands of the CLI are written against the synchronous REST API client:
properties for the reads, plain methods for the commands, and the assignable ``seek``
and ``volume``. The adapters of this module give the other three clients that same
surface, so the commands run unchanged whichever client the ``--api-client`` option
selects.

The asynchronous clients run on a private event loop, served by a daemon thread for the
whole life of the adapter, so the session of the REST client and the heartbeat of the
WebSocket client survive the long synchronous stretches of a command (e.g., the
downloads between two calls of ``queue download``).

The WebSocket API offers neither the story queries nor the notification URLs: the
WebSocket adapters serve them through a REST API client when the CLI allows the
fallback, and raise :class:`UnsupportedOperationError` otherwise.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

import asyncio
import logging
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable, Coroutine
from typing import Any, Self

from volumito.clients import (
    Album,
    Artist,
    BrowseResults,
    CollectionStatistics,
    CommandResponse,
    Label,
    Notification,
    Notifications,
    Place,
    PlayerState,
    Playlist,
    Playlists,
    Queue,
    QueueTrack,
    SearchResults,
    Story,
    SuccessResponse,
    SystemInfo,
    SystemVersion,
    VolumioAsyncRESTAPIClient,
    VolumioAsyncWebSocketClient,
    VolumioHostConfiguration,
    VolumioRESTAPIClient,
    VolumioWebSocketClient,
    Zones,
)
from volumito.clients.common import VolumioCommon

EVENT_LOOP_THREAD_NAME = "volumito-event-loop"
"""The name of the thread serving the event loop of an asynchronous client."""

NOTIFICATION_OPERATION = "the notification URLs"
"""How the messages name the notification members the WebSocket API does not offer."""

STORY_OPERATION = "the story queries"
"""How the messages name the story members the WebSocket API does not offer."""


def _story_arguments(
    album: Album | None,
    artist: Artist | None,
    label: Label | None,
    place: Place | None,
) -> dict[str, Any]:
    """Return the entities of a story query given, keyed by their parameter name.

    The clients take the missing entities as None, so the ones left out are the same
    to them; passing only the given ones keeps the calls as the commands make them.

    Args:
        album: The album whose story to get, when given
        artist: The artist whose story to get, when given
        label: The label whose story to get, when given
        place: The place whose story to get, when given

    Returns:
        The entities given, by parameter name
    """
    given = {"album": album, "artist": artist, "label": label, "place": place}
    return {name: entity for name, entity in given.items() if entity is not None}


class UnsupportedOperationError(Exception):
    """Raised when the selected API client does not offer an operation a command needs."""


class APIClient(ABC):
    """The surface of a Volumio API client the commands of the CLI run against.

    It is the one of the synchronous REST API client: the reads are properties, the
    commands are methods returning what the host answered (the WebSocket API answers
    nothing, so those return None), and ``seek`` and ``volume`` can be assigned. The
    lifecycle is explicit: :meth:`open` before the first use, :meth:`close` after the
    last one, or a ``with`` statement doing both.

    The forwarders of the concrete adapters inherit the docstrings of the abstract
    members below.
    """

    DESCRIPTION: str = "API client"
    """How the adapter names itself in the messages."""

    def __init__(self, client: VolumioCommon) -> None:
        """Initialize the adapter.

        Args:
            client: The client the adapter wraps
        """
        self._wrapped = client

    def _close_quietly(self, action: Callable[[], None]) -> None:
        """Run a closing action, turning its failure into a warning.

        The adapters close from the exit callbacks of the CLI, also while an exit
        unwinds: a failure there must not replace the outcome of the command.

        Args:
            action: The closing action to run
        """
        try:
            action()
        except Exception as e:
            self.logger.warning(f"Closing the {self.description} failed ({e})")

    @abstractmethod
    def add_to_queue(self, uri: str) -> CommandResponse | None:
        """Add the content of a URI to the queue.

        Args:
            uri: The URI to add
        """

    @property
    @abstractmethod
    def base_url(self) -> str:
        """The URL of the API endpoint the client talks to."""

    @abstractmethod
    def browse(self, uri: str | None = None, offset: int | None = None) -> BrowseResults:
        """Browse the content the Volumio instance lists at a URI.

        Args:
            uri: The URI to browse, the root when not given
            offset: The number of items to skip in each list, when given
        """

    @abstractmethod
    def clear(self) -> CommandResponse | None:
        """Clear the queue."""

    @abstractmethod
    def close(self) -> None:
        """Release the connection, if the client holds one. Closing twice is harmless."""

    @property
    @abstractmethod
    def collection_statistics(self) -> CollectionStatistics:
        """The statistics of the music collection."""

    @abstractmethod
    def decrease_volume(self) -> CommandResponse | None:
        """Decrease the playback volume by one step."""

    @property
    def description(self) -> str:
        """How the adapter names itself in the messages."""
        return self.DESCRIPTION

    @abstractmethod
    def get_album_credits(self, artist: Artist | None, album: Album) -> Story:
        """Get the credits of an album.

        Args:
            artist: The artist of the album, when needed to tell it apart
            album: The album
        """

    @abstractmethod
    def get_story(
        self,
        album: Album | None = None,
        artist: Artist | None = None,
        label: Label | None = None,
        place: Place | None = None,
    ) -> Story:
        """Get the story of an album, artist, label, or place.

        Args:
            album: The album whose story to get
            artist: The artist whose story to get
            label: The label whose story to get
            place: The place whose story to get
        """

    @property
    @abstractmethod
    def has_next(self) -> bool:
        """Whether the current track has a next one in the queue."""

    @property
    @abstractmethod
    def has_previous(self) -> bool:
        """Whether the current track has a previous one in the queue."""

    @property
    def host_configuration(self) -> VolumioHostConfiguration:
        """The host configuration of the wrapped client."""
        return self._wrapped.host_configuration

    @abstractmethod
    def increase_volume(self) -> CommandResponse | None:
        """Increase the playback volume by one step."""

    @property
    @abstractmethod
    def is_muted(self) -> bool:
        """Whether the playback is muted."""

    @property
    @abstractmethod
    def is_paused(self) -> bool:
        """Whether the playback is paused."""

    @property
    @abstractmethod
    def is_playing(self) -> bool:
        """Whether the playback is running."""

    @property
    @abstractmethod
    def is_stopped(self) -> bool:
        """Whether the playback is stopped."""

    @property
    def logger(self) -> logging.Logger:
        """The logger of the wrapped client."""
        return self._wrapped.logger

    @abstractmethod
    def mute(self) -> CommandResponse | None:
        """Mute the playback."""

    @abstractmethod
    def next(self) -> CommandResponse | None:
        """Skip to the next track."""

    @property
    @abstractmethod
    def notifications(self) -> Notifications:
        """The URLs the Volumio instance pushes its notifications to."""

    @abstractmethod
    def open(self) -> None:
        """Acquire the connection, if the client needs one, before the first use."""

    @abstractmethod
    def pause(self) -> CommandResponse | None:
        """Pause the playback."""

    @abstractmethod
    def ping(self) -> str:
        """Ping the Volumio instance, returning its answer."""

    @abstractmethod
    def play(self, position: int | QueueTrack | None = None) -> CommandResponse | None:
        """Start the playback, of a given queue position when given.

        Args:
            position: The queue position, or track, to play
        """

    @abstractmethod
    def play_playlist(self, name: str | Playlist) -> CommandResponse | None:
        """Play a playlist.

        Args:
            name: The name of the playlist, or the playlist itself
        """

    @property
    @abstractmethod
    def playlists(self) -> Playlists:
        """The playlists of the Volumio instance."""

    @abstractmethod
    def previous(self) -> CommandResponse | None:
        """Skip to the previous track."""

    @property
    @abstractmethod
    def queue(self) -> Queue:
        """The queue of the Volumio instance."""

    @property
    @abstractmethod
    def queue_status(self) -> dict[str, Any]:
        """The current track, with its position and the neighbor flags of the queue."""

    @abstractmethod
    def randomize(self, value: bool | None = None) -> CommandResponse | None:
        """Set, or toggle, the random mode.

        Args:
            value: The mode to set, toggled when not given
        """

    @abstractmethod
    def register_notification(self, url: str | Notification) -> SuccessResponse:
        """Register a URL the Volumio instance pushes its notifications to.

        Args:
            url: The URL to register
        """

    @abstractmethod
    def repeat(self, value: bool | None = None) -> CommandResponse | None:
        """Set, or toggle, the repeat mode.

        Args:
            value: The mode to set, toggled when not given
        """

    @abstractmethod
    def replace_queue_and_play(self, uri: str, index: int | None = None) -> CommandResponse | None:
        """Replace the queue with the content of a URI and play it.

        Args:
            uri: The URI whose content replaces the queue
            index: The position to start playing from, when given
        """

    @abstractmethod
    def search(self, query: str) -> SearchResults:
        """Search the sources of the Volumio instance.

        Args:
            query: The text to search for
        """

    @property
    @abstractmethod
    def seek(self) -> int:
        """The playback position, in seconds; assign it to seek."""

    @seek.setter
    @abstractmethod
    def seek(self, value: int) -> None: ...

    @abstractmethod
    def seek_backward(self) -> CommandResponse | None:
        """Seek backward by one step."""

    @abstractmethod
    def seek_forward(self) -> CommandResponse | None:
        """Seek forward by one step."""

    @property
    @abstractmethod
    def state(self) -> PlayerState:
        """The playback state of the Volumio instance."""

    @abstractmethod
    def stop(self) -> CommandResponse | None:
        """Stop the playback."""

    @property
    @abstractmethod
    def system_info(self) -> SystemInfo:
        """The system information of the Volumio instance."""

    @property
    @abstractmethod
    def system_version(self) -> SystemVersion:
        """The system version of the Volumio instance."""

    @abstractmethod
    def toggle(self) -> CommandResponse | None:
        """Toggle between playing and pausing."""

    @abstractmethod
    def unmute(self) -> CommandResponse | None:
        """Unmute the playback."""

    @abstractmethod
    def unregister_notification(self, url: str | Notification) -> SuccessResponse:
        """Unregister a URL the Volumio instance pushes its notifications to.

        Args:
            url: The URL to unregister
        """

    @property
    @abstractmethod
    def volume(self) -> int:
        """The playback volume, from 0 to 100; assign it to set the volume."""

    @volume.setter
    @abstractmethod
    def volume(self, value: int) -> None: ...

    @property
    @abstractmethod
    def zones(self) -> Zones:
        """The multiroom zones of the Volumio instance."""

    def __enter__(self) -> Self:
        """Open the client, and return it."""
        self.open()
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        """Close the client."""
        self.close()


class _RESTFallback:
    """The REST API client a WebSocket adapter serves the REST-only operations with.

    Without a factory there is no fallback: the operations raise. With one, the client
    is built and opened on the first operation, kept for the following ones, and
    closed with the adapter owning it.
    """

    def __init__(self, owner: APIClient, factory: Callable[[], APIClient] | None) -> None:
        """Initialize the fallback.

        Args:
            owner: The WebSocket adapter falling back
            factory: The function building the REST API client, or None to forbid the
                fallback
        """
        self._owner = owner
        self._factory = factory
        self._client: APIClient | None = None

    def client(self, operation: str) -> APIClient:
        """Return the REST API client serving an operation.

        Args:
            operation: How the messages name the operation (e.g., "the story queries")

        Returns:
            The opened REST API client

        Raises:
            UnsupportedOperationError: If the fallback is not allowed
        """
        if self._factory is None:
            raise UnsupportedOperationError(
                f"The {self._owner.description} does not offer {operation}: use "
                "--api-client synchronous_rest or asynchronous_rest, "
                "or --allow-fallback-to-rest-api"
            )
        if self._client is None:
            self._owner.logger.debug("Opening the REST API client to fall back to...")
            client = self._factory()
            client.open()
            self._client = client
            self._owner.logger.debug("Opening the REST API client to fall back to... done")
        self._owner.logger.warning(
            f"Falling back to the REST API client for {operation} "
            "(the WebSocket API does not offer them)"
        )
        return self._client

    def close(self) -> None:
        """Close the REST API client, if one was built."""
        if self._client is not None:
            client, self._client = self._client, None
            client.close()


class SyncAPIClient[C: VolumioRESTAPIClient | VolumioWebSocketClient](APIClient):
    """The adapter of a synchronous client, forwarding the members the two share.

    The members one of the two clients lacks, or defines differently, are left to the
    concrete adapters.
    """

    def __init__(self, client: C) -> None:
        """Initialize the adapter.

        Args:
            client: The synchronous client the adapter wraps
        """
        super().__init__(client)
        self._client = client

    def add_to_queue(self, uri: str) -> CommandResponse | None:
        return self._client.add_to_queue(uri)

    def clear(self) -> CommandResponse | None:
        return self._client.clear()

    @property
    def collection_statistics(self) -> CollectionStatistics:
        return self._client.collection_statistics

    def decrease_volume(self) -> CommandResponse | None:
        return self._client.decrease_volume()

    @property
    def has_next(self) -> bool:
        return self._client.has_next

    @property
    def has_previous(self) -> bool:
        return self._client.has_previous

    def increase_volume(self) -> CommandResponse | None:
        return self._client.increase_volume()

    @property
    def is_muted(self) -> bool:
        return self._client.is_muted

    @property
    def is_paused(self) -> bool:
        return self._client.is_paused

    @property
    def is_playing(self) -> bool:
        return self._client.is_playing

    @property
    def is_stopped(self) -> bool:
        return self._client.is_stopped

    def mute(self) -> CommandResponse | None:
        return self._client.mute()

    def next(self) -> CommandResponse | None:
        return self._client.next()

    def pause(self) -> CommandResponse | None:
        return self._client.pause()

    def ping(self) -> str:
        return self._client.ping()

    def play(self, position: int | QueueTrack | None = None) -> CommandResponse | None:
        return self._client.play(position)

    def play_playlist(self, name: str | Playlist) -> CommandResponse | None:
        return self._client.play_playlist(name)

    @property
    def playlists(self) -> Playlists:
        return self._client.playlists

    def previous(self) -> CommandResponse | None:
        return self._client.previous()

    @property
    def queue(self) -> Queue:
        return self._client.queue

    @property
    def queue_status(self) -> dict[str, Any]:
        return self._client.queue_status

    def randomize(self, value: bool | None = None) -> CommandResponse | None:
        return self._client.randomize(value)

    def repeat(self, value: bool | None = None) -> CommandResponse | None:
        return self._client.repeat(value)

    def replace_queue_and_play(self, uri: str, index: int | None = None) -> CommandResponse | None:
        return self._client.replace_queue_and_play(uri, index)

    def search(self, query: str) -> SearchResults:
        return self._client.search(query)

    @property
    def seek(self) -> int:
        return self._client.seek

    @seek.setter
    def seek(self, value: int) -> None:
        self._client.seek = value

    def seek_backward(self) -> CommandResponse | None:
        return self._client.seek_backward()

    def seek_forward(self) -> CommandResponse | None:
        return self._client.seek_forward()

    @property
    def state(self) -> PlayerState:
        return self._client.state

    def stop(self) -> CommandResponse | None:
        return self._client.stop()

    @property
    def system_info(self) -> SystemInfo:
        return self._client.system_info

    @property
    def system_version(self) -> SystemVersion:
        return self._client.system_version

    def toggle(self) -> CommandResponse | None:
        return self._client.toggle()

    def unmute(self) -> CommandResponse | None:
        return self._client.unmute()

    @property
    def volume(self) -> int:
        return self._client.volume

    @volume.setter
    def volume(self, value: int) -> None:
        self._client.volume = value

    @property
    def zones(self) -> Zones:
        return self._client.zones


class SyncRESTAPIClient(SyncAPIClient[VolumioRESTAPIClient]):
    """The adapter of the synchronous REST API client, which needs no connection."""

    DESCRIPTION = "synchronous REST API client"

    @property
    def base_url(self) -> str:
        return self.host_configuration.rest_base_url

    def browse(self, uri: str | None = None, offset: int | None = None) -> BrowseResults:
        return self._client.browse(uri, offset)

    def close(self) -> None:
        """Nothing to release: the client sends each request on its own connection."""

    def get_album_credits(self, artist: Artist | None, album: Album) -> Story:
        return self._client.get_album_credits(artist, album)

    def get_story(
        self,
        album: Album | None = None,
        artist: Artist | None = None,
        label: Label | None = None,
        place: Place | None = None,
    ) -> Story:
        return self._client.get_story(**_story_arguments(album, artist, label, place))

    @property
    def notifications(self) -> Notifications:
        return self._client.notifications

    def open(self) -> None:
        """Nothing to acquire: the client sends each request on its own connection."""

    def register_notification(self, url: str | Notification) -> SuccessResponse:
        return self._client.register_notification(url)

    def unregister_notification(self, url: str | Notification) -> SuccessResponse:
        return self._client.unregister_notification(url)


class SyncWebSocketAPIClient(SyncAPIClient[VolumioWebSocketClient]):
    """The adapter of the synchronous WebSocket API client.

    The client connects on :meth:`open` and disconnects on :meth:`close`. The offset of
    :meth:`browse` is applied to the answer, the root included, since the WebSocket API
    takes none; the story queries and the notification URLs go through the REST API
    client of the fallback, when allowed.
    """

    DESCRIPTION = "synchronous WebSocket API client"

    def __init__(
        self,
        client: VolumioWebSocketClient,
        fallback: Callable[[], APIClient] | None = None,
    ) -> None:
        """Initialize the adapter.

        Args:
            client: The synchronous WebSocket API client the adapter wraps
            fallback: The function building the REST API client serving the operations
                the WebSocket API does not offer, or None to have them fail
        """
        super().__init__(client)
        self._fallback = _RESTFallback(self, fallback)

    @property
    def base_url(self) -> str:
        return self.host_configuration.websocket_base_url

    def browse(self, uri: str | None = None, offset: int | None = None) -> BrowseResults:
        results = self._client.browse(uri)
        return results.offset(offset) if offset else results

    def close(self) -> None:
        self._close_quietly(self._fallback.close)
        self._close_quietly(self._client.disconnect)

    def get_album_credits(self, artist: Artist | None, album: Album) -> Story:
        return self._fallback.client(STORY_OPERATION).get_album_credits(artist, album)

    def get_story(
        self,
        album: Album | None = None,
        artist: Artist | None = None,
        label: Label | None = None,
        place: Place | None = None,
    ) -> Story:
        return self._fallback.client(STORY_OPERATION).get_story(
            album=album, artist=artist, label=label, place=place
        )

    @property
    def notifications(self) -> Notifications:
        return self._fallback.client(NOTIFICATION_OPERATION).notifications

    def open(self) -> None:
        self._client.connect()

    def register_notification(self, url: str | Notification) -> SuccessResponse:
        return self._fallback.client(NOTIFICATION_OPERATION).register_notification(url)

    def unregister_notification(self, url: str | Notification) -> SuccessResponse:
        return self._fallback.client(NOTIFICATION_OPERATION).unregister_notification(url)


class AsyncAPIClient[C: VolumioAsyncRESTAPIClient | VolumioAsyncWebSocketClient](APIClient):
    """The adapter of an asynchronous client, running its coroutines on a private loop.

    The loop is served by a daemon thread started by :meth:`open` and stopped by
    :meth:`close`, so the whole life of the client, from the session or connection it
    opens to the one it closes, happens on the same loop, which keeps running between
    the calls. Each member forwards to its asynchronous counterpart: the nouns to the
    ``get_*`` coroutines, the assignments to ``set_seek`` and ``set_volume``, the
    predicates and the commands to the coroutines of the same name.
    """

    def __init__(self, client: C) -> None:
        """Initialize the adapter.

        Args:
            client: The asynchronous client the adapter wraps
        """
        super().__init__(client)
        self._client = client
        self._loop_thread: tuple[asyncio.AbstractEventLoop, threading.Thread] | None = None

    @abstractmethod
    def _close_client(self) -> None:
        """Close the session, or connection, of the client, on the running loop."""

    @abstractmethod
    def _open_client(self) -> None:
        """Open the session, or connection, of the client, on the running loop."""

    def _run[T](self, coroutine: Coroutine[Any, Any, T]) -> T:
        """Run a coroutine of the client on the loop, waiting for its outcome.

        Args:
            coroutine: The coroutine to run

        Returns:
            What the coroutine returned

        Raises:
            RuntimeError: If the adapter is not open
        """
        if self._loop_thread is None:
            coroutine.close()
            raise RuntimeError(f"The {self.description} is not open")
        loop, _ = self._loop_thread
        return asyncio.run_coroutine_threadsafe(coroutine, loop).result()

    def _stop_loop(self) -> None:
        """Stop the loop and its thread, if running, cancelling the tasks still pending."""
        if self._loop_thread is None:
            return
        loop, thread = self._loop_thread
        self._loop_thread = None
        self.logger.debug(f"Stopping the event loop of the {self.description}...")
        loop.call_soon_threadsafe(loop.stop)
        thread.join()
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
        self.logger.debug(f"Stopping the event loop of the {self.description}... done")

    def add_to_queue(self, uri: str) -> CommandResponse | None:
        return self._run(self._client.add_to_queue(uri))

    def clear(self) -> CommandResponse | None:
        return self._run(self._client.clear())

    def close(self) -> None:
        if self._loop_thread is not None:
            self._close_quietly(self._close_client)
        self._stop_loop()

    @property
    def collection_statistics(self) -> CollectionStatistics:
        return self._run(self._client.get_collection_statistics())

    def decrease_volume(self) -> CommandResponse | None:
        return self._run(self._client.decrease_volume())

    @property
    def has_next(self) -> bool:
        return self._run(self._client.has_next())

    @property
    def has_previous(self) -> bool:
        return self._run(self._client.has_previous())

    def increase_volume(self) -> CommandResponse | None:
        return self._run(self._client.increase_volume())

    @property
    def is_muted(self) -> bool:
        return self._run(self._client.is_muted())

    @property
    def is_paused(self) -> bool:
        return self._run(self._client.is_paused())

    @property
    def is_playing(self) -> bool:
        return self._run(self._client.is_playing())

    @property
    def is_stopped(self) -> bool:
        return self._run(self._client.is_stopped())

    def mute(self) -> CommandResponse | None:
        return self._run(self._client.mute())

    def next(self) -> CommandResponse | None:
        return self._run(self._client.next())

    def open(self) -> None:
        if self._loop_thread is None:
            self.logger.debug(f"Starting the event loop of the {self.description}...")
            loop = asyncio.new_event_loop()
            thread = threading.Thread(
                target=loop.run_forever, name=EVENT_LOOP_THREAD_NAME, daemon=True
            )
            thread.start()
            self._loop_thread = (loop, thread)
            self.logger.debug(f"Starting the event loop of the {self.description}... done")
        try:
            self._open_client()
        except BaseException:
            self._stop_loop()
            raise

    def pause(self) -> CommandResponse | None:
        return self._run(self._client.pause())

    def ping(self) -> str:
        return self._run(self._client.ping())

    def play(self, position: int | QueueTrack | None = None) -> CommandResponse | None:
        return self._run(self._client.play(position))

    def play_playlist(self, name: str | Playlist) -> CommandResponse | None:
        return self._run(self._client.play_playlist(name))

    @property
    def playlists(self) -> Playlists:
        return self._run(self._client.get_playlists())

    def previous(self) -> CommandResponse | None:
        return self._run(self._client.previous())

    @property
    def queue(self) -> Queue:
        return self._run(self._client.get_queue())

    @property
    def queue_status(self) -> dict[str, Any]:
        return self._run(self._client.get_queue_status())

    def randomize(self, value: bool | None = None) -> CommandResponse | None:
        return self._run(self._client.randomize(value))

    def repeat(self, value: bool | None = None) -> CommandResponse | None:
        return self._run(self._client.repeat(value))

    def replace_queue_and_play(self, uri: str, index: int | None = None) -> CommandResponse | None:
        return self._run(self._client.replace_queue_and_play(uri, index))

    def search(self, query: str) -> SearchResults:
        return self._run(self._client.search(query))

    @property
    def seek(self) -> int:
        return self._run(self._client.get_seek())

    @seek.setter
    def seek(self, value: int) -> None:
        self._run(self._client.set_seek(value))

    def seek_backward(self) -> CommandResponse | None:
        return self._run(self._client.seek_backward())

    def seek_forward(self) -> CommandResponse | None:
        return self._run(self._client.seek_forward())

    @property
    def state(self) -> PlayerState:
        return self._run(self._client.get_state())

    def stop(self) -> CommandResponse | None:
        return self._run(self._client.stop())

    @property
    def system_info(self) -> SystemInfo:
        return self._run(self._client.get_system_info())

    @property
    def system_version(self) -> SystemVersion:
        return self._run(self._client.get_system_version())

    def toggle(self) -> CommandResponse | None:
        return self._run(self._client.toggle())

    def unmute(self) -> CommandResponse | None:
        return self._run(self._client.unmute())

    @property
    def volume(self) -> int:
        return self._run(self._client.get_volume())

    @volume.setter
    def volume(self, value: int) -> None:
        self._run(self._client.set_volume(value))

    @property
    def zones(self) -> Zones:
        return self._run(self._client.get_zones())


class AsyncRESTAPIClient(AsyncAPIClient[VolumioAsyncRESTAPIClient]):
    """The adapter of the asynchronous REST API client.

    The client opens its session on the first request and closes it on :meth:`close`.
    """

    DESCRIPTION = "asynchronous REST API client"

    def _close_client(self) -> None:
        self._run(self._client.close())

    def _open_client(self) -> None:
        """Nothing to open: the client opens its session on the first request."""

    @property
    def base_url(self) -> str:
        return self.host_configuration.rest_base_url

    def browse(self, uri: str | None = None, offset: int | None = None) -> BrowseResults:
        return self._run(self._client.browse(uri, offset))

    def get_album_credits(self, artist: Artist | None, album: Album) -> Story:
        return self._run(self._client.get_album_credits(artist, album))

    def get_story(
        self,
        album: Album | None = None,
        artist: Artist | None = None,
        label: Label | None = None,
        place: Place | None = None,
    ) -> Story:
        return self._run(self._client.get_story(**_story_arguments(album, artist, label, place)))

    @property
    def notifications(self) -> Notifications:
        return self._run(self._client.get_notifications())

    def register_notification(self, url: str | Notification) -> SuccessResponse:
        return self._run(self._client.register_notification(url))

    def unregister_notification(self, url: str | Notification) -> SuccessResponse:
        return self._run(self._client.unregister_notification(url))


class AsyncWebSocketAPIClient(AsyncAPIClient[VolumioAsyncWebSocketClient]):
    """The adapter of the asynchronous WebSocket API client.

    The client connects on :meth:`open` and disconnects on :meth:`close`. The offset of
    :meth:`browse` is applied to the answer, the root included, since the WebSocket API
    takes none; the story queries and the notification URLs go through the REST API
    client of the fallback, when allowed.
    """

    DESCRIPTION = "asynchronous WebSocket API client"

    def __init__(
        self,
        client: VolumioAsyncWebSocketClient,
        fallback: Callable[[], APIClient] | None = None,
    ) -> None:
        """Initialize the adapter.

        Args:
            client: The asynchronous WebSocket API client the adapter wraps
            fallback: The function building the REST API client serving the operations
                the WebSocket API does not offer, or None to have them fail
        """
        super().__init__(client)
        self._fallback = _RESTFallback(self, fallback)

    def _close_client(self) -> None:
        self._close_quietly(self._fallback.close)
        self._run(self._client.disconnect())

    def _open_client(self) -> None:
        self._run(self._client.connect())

    @property
    def base_url(self) -> str:
        return self.host_configuration.websocket_base_url

    def browse(self, uri: str | None = None, offset: int | None = None) -> BrowseResults:
        results = self._run(self._client.browse(uri))
        return results.offset(offset) if offset else results

    def get_album_credits(self, artist: Artist | None, album: Album) -> Story:
        return self._fallback.client(STORY_OPERATION).get_album_credits(artist, album)

    def get_story(
        self,
        album: Album | None = None,
        artist: Artist | None = None,
        label: Label | None = None,
        place: Place | None = None,
    ) -> Story:
        return self._fallback.client(STORY_OPERATION).get_story(
            album=album, artist=artist, label=label, place=place
        )

    @property
    def notifications(self) -> Notifications:
        return self._fallback.client(NOTIFICATION_OPERATION).notifications

    def register_notification(self, url: str | Notification) -> SuccessResponse:
        return self._fallback.client(NOTIFICATION_OPERATION).register_notification(url)

    def unregister_notification(self, url: str | Notification) -> SuccessResponse:
        return self._fallback.client(NOTIFICATION_OPERATION).unregister_notification(url)
