"""Logic shared by the WebSocket API clients for Volumio.

The synchronous and the asynchronous WebSocket API clients differ only in their transport:
the names of the events they emit, the payloads those events carry, the answers they wait
for, and the messages they log and raise all live here, so the two cannot drift apart.

A Volumio host answers no event with a Socket.IO acknowledgement: a read emits its request
event and waits for the matching ``push*`` event the host broadcasts, which
``RESPONSE_EVENTS`` maps. The names come from the WebSocket plugin of the Volumio backend
rather than from the published API documentation, which covers roughly a quarter of them
and disagrees with the code on the payloads of ``seek`` and ``volume``.

This module knows nothing about how a client talks to the host: it imports neither
``socketio`` nor ``aiohttp``.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

from typing import Any, NoReturn

from volumito.clients.common import VolumioCommon
from volumito.clients.errors import VolumioConnectionError
from volumito.clients.models import Playlist, QueueTrack

EVENT_ADD_PLAY = "addPlay"
"""The event appending items to the queue and playing them."""

EVENT_ADD_PLAY_CUE = "addPlayCue"
"""The event appending a track of a cue sheet and playing it."""

EVENT_ADD_QUEUE_UIDS = "addQueueUids"
"""The event appending library items to the queue by identifier."""

EVENT_ADD_TO_FAVOURITES = "addToFavourites"
"""The event adding an item to the favourites."""

EVENT_ADD_TO_PLAYLIST = "addToPlaylist"
"""The event adding an item to a saved playlist."""

EVENT_ADD_TO_QUEUE = "addToQueue"
"""The event appending items to the playback queue."""

EVENT_ADD_TO_RADIO_FAVOURITES = "addToRadioFavourites"
"""The event adding a web radio to the radio favourites."""

EVENT_ADD_WEB_RADIO = "addWebRadio"
"""The event saving a web radio of the user."""

EVENT_BROWSE_LIBRARY = "browseLibrary"
"""The event listing the content of a URI."""

EVENT_CLEAR_QUEUE = "clearQueue"
"""The event emptying the playback queue."""

EVENT_CREATE_PLAYLIST = "createPlaylist"
"""The event creating an empty saved playlist."""

EVENT_DELETE_PLAYLIST = "deletePlaylist"
"""The event deleting a saved playlist."""

EVENT_ENQUEUE = "enqueue"
"""The event appending a saved playlist to the queue."""

EVENT_GET_MULTI_ROOM_DEVICES = "getMultiRoomDevices"
"""The event asking for the Volumio devices on the network."""

EVENT_GET_MY_COLLECTION_STATS = "getMyCollectionStats"
"""The event asking for the statistics of the music collection."""

EVENT_GET_PLAYLIST_CONTENT = "getPlaylistContent"
"""The event asking for the tracks of a saved playlist."""

EVENT_GET_QUEUE = "getQueue"
"""The event asking for the playback queue."""

EVENT_GET_STATE = "getState"
"""The event asking for the playback state."""

EVENT_GET_SYSTEM_INFO = "getSystemInfo"
"""The event asking for the system information of the host."""

EVENT_GET_SYSTEM_VERSION = "getSystemVersion"
"""The event asking for the Volumio version the host runs."""

EVENT_GO_TO = "goTo"
"""The event browsing to the artist or the album of what is playing."""

EVENT_IMPORT_SERVICE_PLAYLISTS = "importServicePlaylists"
"""The event importing the playlists of the music services."""

EVENT_LIST_PLAYLIST = "listPlaylist"
"""The event asking for the names of the saved playlists."""

EVENT_MOVE_QUEUE = "moveQueue"
"""The event moving a track to another position of the queue."""

EVENT_MUTE = "mute"
"""The event muting the volume."""

EVENT_NEXT = "next"
"""The event skipping to the next track."""

EVENT_PAUSE = "pause"
"""The event pausing the playback."""

EVENT_PINGER = "pinger"
"""The event a host echoes back, unchanged, as ``ponger``."""

EVENT_PLAY = "play"
"""The event starting the playback."""

EVENT_PLAY_FAVOURITES = "playFavourites"
"""The event playing the favourites."""

EVENT_PLAY_ITEMS_LIST = "playItemsList"
"""The event replacing the queue with a list of items and playing it."""

EVENT_PLAY_NEXT = "playNext"
"""The event queueing an item right after the current track."""

EVENT_PLAY_PLAYLIST = "playPlaylist"
"""The event starting the playback of a saved playlist."""

EVENT_PLAY_RADIO_FAVOURITES = "playRadioFavourites"
"""The event playing the radio favourites."""

EVENT_PONGER = "ponger"
"""The event echoing back what ``pinger`` carried."""

EVENT_PREVIOUS = "prev"
"""The event going back to the previous track."""

EVENT_PUSH_ADD_TO_RADIO_FAVOURITES = "pushAddToRadioFavourites"
"""The event confirming a web radio was made a favourite."""

EVENT_PUSH_ADD_WEB_RADIO = "pushAddWebRadio"
"""The event confirming a web radio was saved."""

EVENT_PUSH_BROWSE_LIBRARY = "pushBrowseLibrary"
"""The event carrying a browse listing, and also a search result."""

EVENT_PUSH_CREATE_PLAYLIST = "pushCreatePlaylist"
"""The event confirming a playlist was created."""

EVENT_PUSH_ENQUEUE = "pushEnqueue"
"""The event carrying the queue a playlist was appended to."""

EVENT_PUSH_LIST_PLAYLIST = "pushListPlaylist"
"""The event carrying the names of the saved playlists."""

EVENT_PUSH_MULTI_ROOM_DEVICES = "pushMultiRoomDevices"
"""The event carrying the Volumio devices on the network."""

EVENT_PUSH_MY_COLLECTION_STATS = "pushMyCollectionStats"
"""The event carrying the statistics of the music collection."""

EVENT_PUSH_PLAYLIST_CONTENT = "pushPlaylistContent"
"""The event carrying the tracks of a saved playlist."""

EVENT_PUSH_PLAY_FAVOURITES = "pushPlayFavourites"
"""The event confirming the favourites are playing."""

EVENT_PUSH_PLAY_RADIO_FAVOURITES = "pushPlayRadioFavourites"
"""The event confirming the radio favourites are playing."""

EVENT_PUSH_QUEUE = "pushQueue"
"""The event carrying the playback queue."""

EVENT_PUSH_REMOVE_FROM_RADIO_FAVOURITES = "pushRemoveFromRadioFavourites"
"""The event confirming a web radio is no longer a favourite."""

EVENT_PUSH_SAVE_QUEUE_TO_PLAYLIST = "pushSaveQueueToPlaylist"
"""The event confirming the queue was saved as a playlist."""

EVENT_PUSH_SET_CONSUME = "pushSetConsume"
"""The event carrying the consume mode."""

EVENT_PUSH_STATE = "pushState"
"""The event carrying the playback state, broadcast on every change of it."""

EVENT_PUSH_SYSTEM_INFO = "pushSystemInfo"
"""The event carrying the system information of the host."""

EVENT_PUSH_SYSTEM_VERSION = "pushSystemVersion"
"""The event carrying the Volumio version the host runs."""

EVENT_REMOVE_FROM_FAVOURITES = "removeFromFavourites"
"""The event removing an item from the favourites."""

EVENT_REMOVE_FROM_PLAYLIST = "removeFromPlaylist"
"""The event removing an item from a saved playlist."""

EVENT_REMOVE_FROM_RADIO_FAVOURITES = "removeFromRadioFavourites"
"""The event removing a web radio from the radio favourites."""

EVENT_REMOVE_QUEUE_ITEM = "removeQueueItem"
"""The event removing a track from the queue."""

EVENT_REMOVE_WEB_RADIO = "removeWebRadio"
"""The event deleting a web radio of the user."""

EVENT_REPLACE_AND_PLAY = "replaceAndPlay"
"""The event replacing the playback queue and starting it."""

EVENT_REPLACE_AND_PLAY_CUE = "replaceAndPlayCue"
"""The event replacing the queue with a track of a cue sheet."""

EVENT_SAVE_QUEUE_TO_PLAYLIST = "saveQueueToPlaylist"
"""The event saving the queue as a saved playlist."""

EVENT_SEARCH = "search"
"""The event searching the sources of the host."""

EVENT_SEEK = "seek"
"""The event seeking to an absolute position."""

EVENT_SET_CONSUME = "setConsume"
"""The event setting the consume mode."""

EVENT_SET_RANDOM = "setRandom"
"""The event setting the random playback mode."""

EVENT_SET_REPEAT = "setRepeat"
"""The event setting the repeat playback mode."""

EVENT_STOP = "stop"
"""The event stopping the playback."""

EVENT_TOGGLE = "toggle"
"""The event toggling between playing and paused."""

EVENT_UNMUTE = "unmute"
"""The event unmuting the volume."""

EVENT_URI_FAVOURITES = "urifavourites"
"""The event carrying the favourite status of a URI."""

EVENT_VOLATILE_PLAY = "volatilePlay"
"""The event starting a volatile source at a position."""

EVENT_VOLUME = "volume"
"""The event setting the volume, by level or by increment."""

RESPONSE_EVENTS = {
    EVENT_BROWSE_LIBRARY: EVENT_PUSH_BROWSE_LIBRARY,
    EVENT_GET_MULTI_ROOM_DEVICES: EVENT_PUSH_MULTI_ROOM_DEVICES,
    EVENT_GET_MY_COLLECTION_STATS: EVENT_PUSH_MY_COLLECTION_STATS,
    EVENT_GET_PLAYLIST_CONTENT: EVENT_PUSH_PLAYLIST_CONTENT,
    EVENT_GET_QUEUE: EVENT_PUSH_QUEUE,
    EVENT_GET_STATE: EVENT_PUSH_STATE,
    EVENT_GET_SYSTEM_INFO: EVENT_PUSH_SYSTEM_INFO,
    EVENT_GET_SYSTEM_VERSION: EVENT_PUSH_SYSTEM_VERSION,
    EVENT_GO_TO: EVENT_PUSH_BROWSE_LIBRARY,
    EVENT_LIST_PLAYLIST: EVENT_PUSH_LIST_PLAYLIST,
    EVENT_PINGER: EVENT_PONGER,
    EVENT_SEARCH: EVENT_PUSH_BROWSE_LIBRARY,
}
"""The event each read waits for, keyed by the event it emits.

``search`` and ``browseLibrary`` share their answer, which is why a client serializes its
reads: two of them in flight at once could take each other's result."""

VOLUME_DOWN = "-"
"""The volume argument lowering the level by one step of the host."""

VOLUME_UP = "+"
"""The volume argument raising the level by one step of the host."""


class VolumioWebSocketCommon(VolumioCommon):
    """The transport-independent half of a WebSocket API client for Volumio.

    The clients inherit from this class rather than instantiating it: it names the events
    their requests emit and the answers they wait for, builds the payloads those events
    carry, and owns the messages they log and raise, leaving them only the connection.
    """

    _CLIENT_DESCRIPTION: str = "WebSocket API client"
    """The name a client logs itself under while initializing."""

    def _browse_payload(self, uri: str | None) -> dict[str, str]:
        """Build the payload browsing a URI.

        Args:
            uri: The URI to browse, the root when not given

        Returns:
            The payload the browse event carries
        """
        browsed = uri if uri is not None else "/"
        self._log_debug(f'Browsing "{browsed}"')
        return {"uri": browsed}

    def _cue_payload(self, uri: str, number: int, service: str | None = None) -> dict[str, Any]:
        """Build the payload naming a track inside a cue sheet.

        Args:
            uri: The URI of the cue sheet
            number: The position of the track inside the cue sheet
            service: The service the URI belongs to, derived from it when not given

        Returns:
            The payload the cue events carry
        """
        return {
            "number": number,
            "service": service if service is not None else self._uri_service(uri),
            "uri": uri,
        }

    @property
    def _endpoint_description(self) -> str:
        """The base URL a failing connection names as unreachable."""
        return self.host_configuration.websocket_base_url

    def _fail_emit(self, event: str, error: Exception) -> NoReturn:
        """Report that an event could not be sent to the Volumio instance.

        Args:
            event: The event that could not be sent
            error: The transport failure being translated

        Raises:
            VolumioConnectionError: Always
        """
        self._log_warning(f'Cannot emit "{event}" to the Volumio API: {error}')
        raise VolumioConnectionError(
            f'Failed to emit "{event}" to Volumio instance at '
            f"{self._endpoint_description}: {error}"
        ) from error

    def _fail_no_response(self, event: str, response_event: str, waited: float) -> NoReturn:
        """Report that a Volumio instance did not answer an event in time.

        Args:
            event: The event that was emitted
            response_event: The event its answer was awaited on
            waited: The number of seconds the read waited

        Raises:
            VolumioConnectionError: Always
        """
        self._log_warning(
            f'The Volumio API did not answer "{event}" with "{response_event}" '
            f"within {waited} seconds"
        )
        raise VolumioConnectionError(
            f'Volumio instance at {self._endpoint_description} did not answer "{event}" '
            f'with "{response_event}" within {waited} seconds'
        )

    def _fail_not_connected(self, action: str) -> NoReturn:
        """Report that an operation needs a connection the client does not have.

        Args:
            action: What the client was asked to do

        Raises:
            VolumioConnectionError: Always
        """
        self._log_warning(f"Refusing to {action} while not connected")
        raise VolumioConnectionError(
            f"Not connected to the Volumio WebSocket API at {self._endpoint_description}"
        )

    def _favourite_payload(
        self,
        uri: str,
        title: str | None = None,
        service: str | None = None,
        albumart: str | None = None,
    ) -> dict[str, str]:
        """Build the payload naming an item of the favourites.

        Args:
            uri: The URI of the item
            title: The title to show for it, when known
            service: The service the URI belongs to, derived from it when not given
            albumart: The URL of the cover to show for it, when known

        Returns:
            The payload the favourite events carry
        """
        payload = {
            "service": service if service is not None else self._uri_service(uri),
            "uri": uri,
        }
        if title is not None:
            payload["title"] = title
        if albumart is not None:
            payload["albumart"] = albumart
        return payload

    def _goto_payload(self, kind: str, value: str) -> dict[str, str]:
        """Build the payload browsing to the artist or the album of what is playing.

        Args:
            kind: What to browse to (``"artist"`` or ``"album"``)
            value: The name to browse to

        Returns:
            The payload the goto event carries
        """
        return {"type": kind, "value": value}

    def _index_payload(self, index: int) -> dict[str, int]:
        """Build the payload naming a position of the queue.

        Args:
            index: The position, 0-based

        Returns:
            The payload the event carries

        Raises:
            ValueError: If the position is negative
        """
        self._check_play_index(index)
        return {"value": index}

    def _mode_payload(self, value: bool) -> dict[str, bool]:
        """Build the payload setting a playback mode.

        Args:
            value: True to enable the mode, False to disable it

        Returns:
            The payload the mode event carries
        """
        return {"value": value}

    def _move_payload(self, source: int, target: int) -> dict[str, int]:
        """Build the payload moving a track to another position of the queue.

        Args:
            source: The position the track is at, 0-based
            target: The position to move it to, 0-based

        Returns:
            The payload the move event carries

        Raises:
            ValueError: If either position is negative
        """
        self._check_play_index(source)
        self._check_play_index(target)
        return {"from": source, "to": target}

    def _play_next_payload(
        self, uri: str, title: str | None = None, album: str | None = None
    ) -> dict[str, str]:
        """Build the payload queueing an item right after the current track.

        Args:
            uri: The URI to queue
            title: The title to show for it, when known
            album: The album to show for it, when known

        Returns:
            The payload the play-next event carries
        """
        payload = {"uri": uri}
        if title is not None:
            payload["title"] = title
        if album is not None:
            payload["album"] = album
        return payload

    def _play_payload(self, position: int | QueueTrack | None) -> dict[str, int] | None:
        """Build the payload starting the playback, optionally at a queue position.

        Args:
            position: Optional position in the queue to play (0-indexed), or a track
                of the queue

        Returns:
            The payload the play event carries, or None to play where the queue stands

        Raises:
            ValueError: If the given track does not know its position in the queue
        """
        played = self._play_position(position)
        if played is None:
            return None
        return {"value": played}

    def _playlist_item_payload(
        self, name: str | Playlist, uri: str, service: str | None = None
    ) -> dict[str, str]:
        """Build the payload naming an item inside a saved playlist.

        Args:
            name: The name of the playlist, or the playlist itself
            uri: The URI of the item
            service: The service the URI belongs to, derived from it when not given

        Returns:
            The payload the playlist item events carry

        Raises:
            ValueError: If the given playlist has no name
        """
        return {
            "name": self._playlist_name(name),
            "service": service if service is not None else self._uri_service(uri),
            "uri": uri,
        }

    def _playlist_payload(self, name: str | Playlist) -> dict[str, str]:
        """Build the payload starting the playback of a saved playlist.

        Args:
            name: The name of the playlist to play, or the playlist itself

        Returns:
            The payload the playlist event carries

        Raises:
            ValueError: If the given playlist has no name
        """
        return {"name": self._playlist_name(name)}

    def _response_event(self, event: str) -> str:
        """Return the event a read waits for after emitting one.

        Args:
            event: The event about to be emitted

        Returns:
            The event carrying its answer

        Raises:
            ValueError: If the event is not one a Volumio host answers
        """
        if event not in RESPONSE_EVENTS:
            self._log_warning(f'Refusing to wait for an answer to "{event}"')
            raise ValueError(
                f"The Volumio API answers no {event!r} event: emit it, or name the "
                f"event carrying its answer"
            )
        return RESPONSE_EVENTS[event]

    def _search_payload(self, query: str) -> dict[str, str]:
        """Build the payload searching the sources of the Volumio instance.

        Args:
            query: The text to search for

        Returns:
            The payload the search event carries
        """
        return {"value": query}

    def _seek_payload(self, value: int) -> int:
        """Build the payload seeking to an absolute position.

        The seek event carries the number of seconds itself, not an object holding it.

        Args:
            value: The position to seek to, in seconds

        Returns:
            The payload the seek event carries
        """
        return value

    def _volume_payload(self, value: int) -> int:
        """Build the payload setting the volume to an absolute level.

        The volume event carries the level itself, not an object holding it.

        Args:
            value: The volume level, an integer between 0 and 100 (inclusive)

        Returns:
            The payload the volume event carries

        Raises:
            ValueError: If the volume level is out of range
        """
        self._check_volume_level(value)
        return value

    def _web_radio_payload(self, name: str, uri: str | None = None) -> dict[str, str]:
        """Build the payload naming a web radio of the user.

        Args:
            name: The name of the web radio
            uri: The URL it streams from, when the event needs it

        Returns:
            The payload the web radio events carry
        """
        payload = {"name": name}
        if uri is not None:
            payload["uri"] = uri
        return payload
