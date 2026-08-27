"""Logic shared by the REST API clients for Volumio.

The synchronous and the asynchronous REST API clients differ only in their transport:
everything else -- the endpoint paths, the payloads they build, the values they read
out of a playback state, the shape checks on a parsed response, and the messages they
log and raise -- lives here, so the two cannot drift apart.

This module knows nothing about how a request travels: it imports neither ``requests``
nor ``aiohttp``.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

import json
import logging
from typing import Any, NoReturn
from urllib.parse import quote

from volumito.clients.base import VolumioBaseClient
from volumito.clients.entities import (
    Album,
    Artist,
    Label,
    MusicEntity,
    Place,
)
from volumito.clients.errors import VolumioAPIError, VolumioConnectionError
from volumito.clients.host_configuration import VolumioHostConfiguration
from volumito.clients.models import (
    Notification,
    PlayerState,
    Playlist,
    QueueTrack,
)

MAX_POST_BODY_BYTES = 100 * 1024
"""The JSON body size a Volumio instance accepts, the default limit of its Express
body parser: a larger body is not answered by the API but by the album art server."""

MPD_LIBRARY_SCHEMES = frozenset({"albums", "artists", "genres", "playlists"})
"""The URI schemes the local library of a Volumio instance is browsed by."""

PATH_ADD_TO_QUEUE = "/api/v1/addToQueue"
"""The endpoint appending items to the playback queue."""

PATH_BROWSE = "/api/v1/browse"
"""The endpoint listing the content of a URI."""

PATH_COLLECTION_STATISTICS = "/api/v1/collectionstats"
"""The endpoint reporting the statistics of the music collection."""

PATH_COMMANDS = "/api/v1/commands/"
"""The endpoint taking the playback control commands."""

PATH_GET_QUEUE = "/api/v1/getQueue"
"""The endpoint returning the playback queue."""

PATH_GET_STATE = "/api/v1/getState"
"""The endpoint returning the playback state."""

PATH_GET_SYSTEM_INFO = "/api/v1/getSystemInfo"
"""The endpoint returning the system information."""

PATH_GET_SYSTEM_VERSION = "/api/v1/getSystemVersion"
"""The endpoint returning the system version."""

PATH_GET_ZONES = "/api/v1/getzones"
"""The endpoint returning the multiroom zones."""

PATH_LIST_PLAYLISTS = "/api/v1/listplaylists"
"""The endpoint returning the names of the saved playlists."""

PATH_PING = "/api/v1/ping"
"""The endpoint answering a reachability check."""

PATH_PLUGIN_ENDPOINT = "/api/v1/pluginEndpoint"
"""The endpoint forwarding a request to a plugin."""

PATH_PUSH_NOTIFICATION_URLS = "/api/v1/pushNotificationUrls"
"""The endpoint holding the URLs receiving the push notifications."""

PATH_REPLACE_AND_PLAY = "/api/v1/replaceAndPlay"
"""The endpoint replacing the playback queue and starting the playback."""

PATH_SEARCH = "/api/v1/search"
"""The endpoint searching the sources of the instance."""

QUEUE_ITEM_KEYS = ("name", "service", "title", "type", "uri")
"""The keys of a browsed item a Volumio instance reads when queueing it: the others
(the album art URL above all) only grow the payload toward the body size limit."""


class VolumioRESTAPICommon(VolumioBaseClient):
    """The transport-independent half of a REST API client for Volumio.

    The clients inherit from this class rather than instantiating it: it builds the
    paths and payloads their requests carry, reads the values their answers hold, and
    owns the messages they log and raise, leaving them only the requests themselves.
    """

    _CLIENT_DESCRIPTION: str = "REST API client"
    """The name a client logs itself under while initializing."""

    def __init__(
        self,
        host_configuration: VolumioHostConfiguration,
        timeout: float = 5.0,
        timeout_slow_endpoints: float = 60.0,
        logger: logging.Logger | None = None,
    ) -> None:
        """Initialize the shared half of a REST API client.

        Args:
            host_configuration: The host configuration (scheme, host, and ports)
            timeout: Request timeout in seconds (default: 5.0)
            timeout_slow_endpoints: Request timeout, in seconds, for the endpoints
                that can take long, like replacing the queue (default: 60.0)
            logger: The logger the client writes to; without one, the client logs
                under its own name in the ``volumito`` hierarchy
        """
        super().__init__(logger)
        self._log_debug(f"Initializing the {self._CLIENT_DESCRIPTION}...")
        self.host_configuration = host_configuration
        self.timeout = timeout
        self.timeout_slow_endpoints = timeout_slow_endpoints
        self._log_debug(f"Initializing the {self._CLIENT_DESCRIPTION}... done")

    def _album_credits_payload(self, artist: Artist | None, album: Album) -> dict[str, str]:
        """Build the metavolumio data payload for an album credits query.

        Args:
            artist: The album's artist by name; must be None when the album is an MBID
            album: The album, by title (requiring the artist) or by MBID

        Returns:
            The data payload dictionary, mode included

        Raises:
            ValueError: If the artist/album combination is invalid
        """
        return {"mode": "creditsAlbum", **self._story_album_payload(artist, album)}

    def _as_json_array(self, data: object) -> list[Any]:
        """Check that a parsed response body is a JSON array.

        Args:
            data: The parsed response body

        Returns:
            The JSON array

        Raises:
            VolumioAPIError: If the body is not an array
        """
        if not isinstance(data, list):
            self._log_warning(f"The response is not a JSON array: {type(data).__name__}")
            raise VolumioAPIError(
                f"Expected JSON array from Volumio API, got {type(data).__name__}"
            )

        return data

    def _as_json_object(self, data: object) -> dict[str, Any]:
        """Check that a parsed response body is a JSON object.

        Args:
            data: The parsed response body

        Returns:
            The JSON object

        Raises:
            VolumioAPIError: If the body is not an object
        """
        if not isinstance(data, dict):
            self._log_warning(f"The response is not a JSON object: {type(data).__name__}")
            raise VolumioAPIError(
                f"Expected JSON object from Volumio API, got {type(data).__name__}"
            )

        return data

    def _browse_request(self, uri: str | None, offset: int | None) -> tuple[str, str]:
        """Build the path browsing a URI, and the label naming it in the logs.

        A URI is encoded for the query string except for its structure and its percent
        signs, so the escapes the instance itself puts in its URIs (e.g.,
        ``artists://Paolo%20Conte``) are not encoded twice. An offset of 0 is not sent,
        since the instance ignores it.

        Args:
            uri: The URI to browse, the root when not given
            offset: The number of items to skip in each list, when given

        Returns:
            The path to request, and the label of the browse

        Raises:
            ValueError: If the offset is negative
        """
        if offset is not None and offset < 0:
            self._log_warning(f"Refusing the negative browse offset {offset}")
            raise ValueError(f"The offset must be 0 or greater, got {offset}")
        browsed = quote(uri if uri is not None else "/", safe=":/%")
        skipped = f"&offset={offset}" if offset else ""
        label = f"{browsed}{skipped}"
        return f"{PATH_BROWSE}?uri={label}", label

    def _check_play_index(self, index: int | None) -> None:
        """Check that an index naming the item to play first is not negative.

        Args:
            index: The position of the item to play first (0-based), when given

        Raises:
            ValueError: If the index is negative
        """
        if index is not None and index < 0:
            self._log_warning(f"Refusing the negative play index {index}")
            raise ValueError(f"The index must be 0 or greater, got {index}")

    def _check_post_body(self, payload: dict[str, Any] | list[dict[str, Any]]) -> None:
        """Check that a JSON body is not larger than the Volumio instance accepts.

        Args:
            payload: The JSON body about to be sent

        Raises:
            VolumioAPIError: If the payload is larger than the instance accepts
        """
        body_bytes = len(json.dumps(payload).encode())
        if body_bytes > MAX_POST_BODY_BYTES:
            self._log_warning(f"Refusing to send a payload of {body_bytes // 1024} kB")
            raise VolumioAPIError(
                f"The payload is {body_bytes // 1024} kB, larger than the "
                f"{MAX_POST_BODY_BYTES // 1024} kB a Volumio instance accepts"
            )

    def _command_path(self, cmd: str) -> str:
        """Build the path sending a playback control command.

        Args:
            cmd: The command to send (e.g., "play", "pause", "stop", "toggle", "next")

        Returns:
            The path to request
        """
        return f"{PATH_COMMANDS}?cmd={cmd}"

    def _fail_connection(self, error: Exception) -> NoReturn:
        """Report that the Volumio instance cannot be reached.

        Args:
            error: The transport failure being translated

        Raises:
            VolumioConnectionError: Always
        """
        self._log_warning(f"Cannot connect to the Volumio API: {error}")
        raise VolumioConnectionError(
            f"Failed to connect to Volumio instance at "
            f"{self.host_configuration.rest_base_url}: {error}"
        ) from error

    def _fail_http(self, error: Exception, status: int) -> NoReturn:
        """Report that the Volumio API answered an HTTP error.

        Args:
            error: The transport failure being translated
            status: The HTTP status code of the response

        Raises:
            VolumioAPIError: Always
        """
        self._log_warning(f"The Volumio API answered HTTP {status}: {error}")
        raise VolumioAPIError(
            f"Volumio API returned HTTP error {status}: {error}"
        ) from error

    def _fail_json(self, error: Exception) -> NoReturn:
        """Report that a response body could not be parsed as JSON.

        Args:
            error: The parse failure being translated

        Raises:
            VolumioAPIError: Always
        """
        self._log_warning(f"The response is not JSON: {error}")
        raise VolumioAPIError(
            f"Failed to parse JSON response from Volumio API: {error}"
        ) from error

    def _fail_request(self, error: Exception) -> NoReturn:
        """Report that a request to the Volumio API failed.

        Args:
            error: The transport failure being translated

        Raises:
            VolumioConnectionError: Always
        """
        self._log_warning(f"The request to the Volumio API failed: {error}")
        raise VolumioConnectionError(
            f"Request to Volumio instance at "
            f"{self.host_configuration.rest_base_url} failed: {error}"
        ) from error

    def _fail_short_listing(self, count: int, index: int) -> NoReturn:
        """Report that a URI does not list enough items to play the asked one.

        Args:
            count: The number of items the URI lists
            index: The position of the item to play first (0-based)

        Raises:
            VolumioAPIError: Always
        """
        self._log_warning(f"The URI lists {count} items, not enough for index {index}")
        raise VolumioAPIError(
            f"The URI lists {count} items, not enough to play the one "
            f"at index {index}"
        )

    def _fail_timeout(self, error: Exception, waited: float) -> NoReturn:
        """Report that the Volumio instance did not answer in time.

        Args:
            error: The transport failure being translated
            waited: The number of seconds the request waited

        Raises:
            VolumioConnectionError: Always
        """
        self._log_warning(f"The Volumio API did not answer within {waited} seconds: {error}")
        raise VolumioConnectionError(
            f"Connection to Volumio instance at "
            f"{self.host_configuration.rest_base_url} "
            f"timed out after {waited} seconds: {error}"
        ) from error

    def _mode_command(self, mode: str, value: bool | None) -> str:
        """Build the command setting or toggling a playback mode.

        Args:
            mode: The name of the mode (e.g., "random", "repeat")
            value: True to enable, False to disable, or None to let the Volumio API
                toggle the current mode

        Returns:
            The command to send
        """
        if value is None:
            return mode
        return f"{mode}&value={str(value).lower()}"

    def _notification_url(self, url: "str | Notification") -> str:
        """Return the URL of a notification given as a string or as a model.

        Args:
            url: The URL, or the notification holding it

        Returns:
            The URL

        Raises:
            ValueError: If the given notification has no URL
        """
        if isinstance(url, Notification):
            if url.url is None:
                self._log_warning("Refusing a notification that has no URL")
                raise ValueError("The notification has no URL")
            return url.url
        return url

    def _play_command(self, position: int | QueueTrack | None) -> str:
        """Build the command starting the playback, optionally at a queue position.

        Args:
            position: Optional position in the queue to play (0-indexed), or a track
                of the queue

        Returns:
            The command to send

        Raises:
            ValueError: If the given track does not know its position in the queue
        """
        if isinstance(position, QueueTrack):
            if position.position is None:
                self._log_warning("Refusing to play a track that does not belong to a queue")
                raise ValueError("The track does not belong to a queue")
            return f"play&N={position.position}"
        if position is not None:
            return f"play&N={position}"
        return "play"

    def _playlist_command(self, name: str | Playlist) -> str:
        """Build the command starting the playback of a saved playlist.

        Args:
            name: The name of the playlist to play, or the playlist itself

        Returns:
            The command to send

        Raises:
            ValueError: If the given playlist has no name
        """
        if isinstance(name, Playlist):
            if name.name is None:
                self._log_warning("Refusing to play a playlist that has no name")
                raise ValueError("The playlist has no name")
            name = name.name
        return f"playplaylist&name={quote(name, safe='')}"

    def _queue_status(self, state: PlayerState, count: int) -> dict[str, Any]:
        """Build the navigation state of the queue from a playback state and a length.

        Args:
            state: The current playback state
            count: The number of queued tracks

        Returns:
            The navigation state of the queue
        """
        position = state.position
        self._log_debug(f"Current position: {position}, queue length: {count}")
        return {
            "has_next": position is not None and position < count - 1,
            "has_previous": position is not None and count > 0 and position > 0,
            "length": count,
            "position": position,
            "track": state.raw,
        }

    def _queue_uri_item(self, uri: str) -> dict[str, str]:
        """Build the payload item queueing a URI as itself.

        Args:
            uri: The URI to be queued

        Returns:
            The item naming the URI and the service it belongs to
        """
        return {"service": self._uri_service(uri), "uri": uri}

    def _search_path(self, query: str) -> str:
        """Build the path searching the sources of the Volumio instance.

        Args:
            query: The text to search for

        Returns:
            The path to request
        """
        return f"{PATH_SEARCH}?query={quote(query, safe='')}"

    def _seek_command(self, value: int) -> str:
        """Build the command seeking to an absolute position.

        Args:
            value: The position to seek to, in seconds

        Returns:
            The command to send
        """
        return f"seek&position={value}"

    @staticmethod
    def _slim_queue_item(item: dict[str, Any]) -> dict[str, Any]:
        """Return the keys of a browsed item that queueing it needs.

        A Volumio instance queues a listed item by exploding its URI through its
        service, so the other keys of the item are dead weight; dropping them keeps
        the payload of a long listing within the body size the instance accepts.

        Args:
            item: The item, as the Volumio instance listed it

        Returns:
            The item reduced to the keys queueing reads
        """
        return {key: item[key] for key in QUEUE_ITEM_KEYS if key in item}

    def _state_mute(self, state: PlayerState) -> bool:
        """Read the mute flag out of a playback state.

        Args:
            state: The playback state to read

        Returns:
            True if the volume is muted, False otherwise

        Raises:
            VolumioAPIError: If the state does not contain a boolean mute flag
        """
        if state.mute is None:
            self._log_warning("The playback state carries no boolean mute flag")
            raise VolumioAPIError(
                f"Expected a boolean mute flag in the Volumio state, "
                f"got {type(state.raw.get('mute')).__name__}"
            )
        return state.mute

    def _state_seek(self, state: PlayerState) -> int:
        """Read the seek position, in seconds, out of a playback state.

        Args:
            state: The playback state to read

        Returns:
            The current seek position, in seconds

        Raises:
            VolumioAPIError: If the state does not contain an integer seek position
        """
        if state.seek is None:
            self._log_warning("The playback state carries no integer seek position")
            raise VolumioAPIError(
                f"Expected an integer seek position in the Volumio state, "
                f"got {type(state.raw.get('seek')).__name__}"
            )
        return state.seek // 1000

    def _state_status(self, state: PlayerState) -> str:
        """Read the playback status string out of a playback state.

        Args:
            state: The playback state to read

        Returns:
            The playback status (e.g., "play", "pause", "stop")

        Raises:
            VolumioAPIError: If the state does not contain a string status
        """
        if state.status is None:
            self._log_warning("The playback state carries no string status")
            raise VolumioAPIError(
                f"Expected a string status in the Volumio state, "
                f"got {type(state.raw.get('status')).__name__}"
            )
        return state.status

    def _state_volume(self, state: PlayerState) -> int:
        """Read the volume level out of a playback state.

        Args:
            state: The playback state to read

        Returns:
            The volume level, an integer between 0 and 100 (inclusive)

        Raises:
            VolumioAPIError: If the state does not contain an integer volume level
        """
        if state.volume is None:
            self._log_warning("The playback state carries no integer volume level")
            raise VolumioAPIError(
                f"Expected an integer volume level in the Volumio state, "
                f"got {type(state.raw.get('volume')).__name__}"
            )
        return state.volume

    def _story_album_payload(self, artist: Artist | None, album: Album) -> dict[str, str]:
        """Build the metavolumio data payload (without the mode key) for an album query.

        Args:
            artist: The album's artist by name; must be None when the album is an MBID
            album: The album, by title (requiring the artist) or by MBID

        Returns:
            The data payload dictionary

        Raises:
            ValueError: If the artist/album combination is invalid
        """
        if album.is_mbid:
            if artist is not None:
                self._log_warning("Refusing an artist next to an album specified by MBID")
                raise ValueError("An album specified by MBID does not take an artist")
            return {"mbid": album.value}
        if artist is None:
            self._log_warning("Refusing an album specified by title without an artist")
            raise ValueError("An album specified by title requires an artist")
        if artist.is_mbid:
            self._log_warning("Refusing an artist by MBID next to an album specified by title")
            raise ValueError("An album specified by title requires the artist by name, not by MBID")
        return {"artist": artist.value, "album": album.value}

    @staticmethod
    def _story_entity_payload(key: str, entity: MusicEntity) -> dict[str, str]:
        """Build the metavolumio data payload (without the mode key) for a single entity.

        Args:
            key: The payload key of the free-text value (e.g., "artist")
            entity: The entity, by free-text value or by MBID

        Returns:
            The data payload dictionary
        """
        if entity.is_mbid:
            return {"mbid": entity.value}
        return {key: entity.value}

    def _story_payload(
        self,
        album: Album | None,
        artist: Artist | None,
        label: Label | None,
        place: Place | None,
    ) -> dict[str, str]:
        """Build the metavolumio data payload for a story query.

        Exactly one entity must be queried: an album (with its artist by name, unless
        the album is an MBID), an artist, a label, or a place.

        Args:
            album: The album, by title (requiring the artist) or by MBID
            artist: The artist, by name or by MBID (or the album's artist by name)
            label: The record label, by name or by MBID
            place: The place, by name or by MBID

        Returns:
            The data payload dictionary, mode included

        Raises:
            ValueError: If the entity combination is invalid
        """
        if label is not None and place is not None:
            self._log_warning("Refusing a story query with both a label and a place")
            raise ValueError("The label and place entities are mutually exclusive")
        if album is not None:
            if label is not None or place is not None:
                self._log_warning("Refusing an album story with a label or a place")
                raise ValueError("An album story does not take a label or place")
            return {"mode": "storyAlbum", **self._story_album_payload(artist, album)}
        if artist is not None:
            if label is not None or place is not None:
                self._log_warning("Refusing an artist story with a label or a place")
                raise ValueError("An artist story does not take a label or place")
            return {"mode": "storyArtist", **self._story_entity_payload("artist", artist)}
        if label is not None:
            return {"mode": "storyLabel", **self._story_entity_payload("label", label)}
        if place is not None:
            return {"mode": "storyPlace", **self._story_entity_payload("place", place)}
        self._log_warning("Refusing a story query naming no entity")
        raise ValueError("One of album, artist, label, or place is required")

    def _uri_service(self, uri: str) -> str:
        """Return the name of the Volumio service a URI belongs to.

        A Volumio instance routes a queued URI to the service named in its payload and,
        when none is given, to ``mpd`` -- which silently adds nothing for the URI of
        another source. The service is therefore always sent, read from the URI: the
        scheme names it (``qobuz://...``), except for the schemes the local library is
        browsed by and the scheme-less local paths (``mpd``), the web URLs
        (``webradio``), and the ``spotify:`` URIs (``spop``).

        Args:
            uri: The URI to name the service of

        Returns:
            The name of the service (e.g., ``"mpd"``, ``"qobuz"``, ``"webradio"``)
        """
        if uri.startswith(("http://", "https://")):
            service = "webradio"
        elif uri.startswith("spotify:"):
            service = "spop"
        else:
            scheme, separator, _ = uri.partition("://")
            if separator and scheme not in MPD_LIBRARY_SCHEMES:
                service = scheme
            else:
                service = "mpd"
        self._log_debug(f'Service of "{uri}": {service}')
        return service

    def _volume_command(self, value: int) -> str:
        """Build the command setting the volume to an absolute level.

        Args:
            value: The volume level, an integer between 0 and 100 (inclusive)

        Returns:
            The command to send

        Raises:
            ValueError: If the volume level is out of range
        """
        if not 0 <= value <= 100:
            self._log_warning(f"Refusing the out-of-range volume level {value}")
            raise ValueError(f"The volume level must be between 0 and 100, got {value}")
        return f"volume&volume={value}"
