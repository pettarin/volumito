"""Logic shared by the clients reaching a Volumio host over its HTTP-based APIs.

The REST API clients and the WebSocket API clients carry the same payloads and read the
same values out of the answers a Volumio host gives: a playback state pushed over a
WebSocket is the object the REST state endpoint returns, and a queued item is queued the
same way whichever API asked for it. Everything both families need -- the shape checks on
a decoded payload, the readers of a playback state, and the two transport failures every
client can hit -- lives here, so they cannot drift apart.

This module knows nothing about how a client talks to the host: it imports no transport
library, and names the endpoint it reports as unreachable through the
``_endpoint_description`` property its subclasses define.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

import logging
from typing import TYPE_CHECKING, Any, NoReturn

from volumito.clients.base import VolumioBaseClient
from volumito.clients.errors import VolumioAPIError, VolumioConnectionError
from volumito.clients.host_configuration import VolumioHostConfiguration
from volumito.clients.models import PlayerState, Playlist, QueueTrack

MPD_LIBRARY_SCHEMES = frozenset({"albums", "artists", "genres", "playlists"})
"""The URI schemes the local library of a Volumio instance is browsed by."""

QUEUE_ITEM_KEYS = ("name", "service", "title", "type", "uri")
"""The keys of a browsed item a Volumio instance reads when queueing it: the others
(the album art URL above all) only grow the payload toward the body size limit."""


class VolumioCommon(VolumioBaseClient):
    """The transport-independent half every Volumio client shares.

    The clients inherit from this class rather than instantiating it: it checks the shape
    of the payloads they decode, reads the values their answers hold, and owns the two
    failure messages any transport can produce.
    """

    _CLIENT_DESCRIPTION: str = "client"
    """The name a client logs itself under while initializing."""

    if TYPE_CHECKING:

        @property
        def _endpoint_description(self) -> str:
            """The host endpoint named in the transport failure messages.

            Every concrete client defines this: the REST clients name their base URL,
            the WebSocket clients name theirs.
            """

    def __init__(
        self,
        host_configuration: VolumioHostConfiguration,
        timeout: float = 5.0,
        logger: logging.Logger | None = None,
    ) -> None:
        """Initialize the shared half of a Volumio client.

        Args:
            host_configuration: The host configuration (scheme, host, and ports)
            timeout: Request timeout in seconds (default: 5.0)
            logger: The logger the client writes to; without one, the client logs
                under its own name in the ``volumito`` hierarchy
        """
        super().__init__(logger)
        self.host_configuration = host_configuration
        self.timeout = timeout

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

    def _as_json_boolean(self, data: object) -> bool:
        """Check that a parsed response body is a JSON boolean.

        Args:
            data: The parsed response body

        Returns:
            The JSON boolean

        Raises:
            VolumioAPIError: If the body is not a boolean
        """
        if not isinstance(data, bool):
            self._log_warning(f"The response is not a JSON boolean: {type(data).__name__}")
            raise VolumioAPIError(
                f"Expected JSON boolean from Volumio API, got {type(data).__name__}"
            )

        return data

    def _as_json_string(self, data: object) -> str:
        """Check that a parsed response body is a JSON string.

        Args:
            data: The parsed response body

        Returns:
            The JSON string

        Raises:
            VolumioAPIError: If the body is not a string
        """
        if not isinstance(data, str):
            self._log_warning(f"The response is not a JSON string: {type(data).__name__}")
            raise VolumioAPIError(
                f"Expected JSON string from Volumio API, got {type(data).__name__}"
            )

        return data

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

    def _check_volume_level(self, value: int) -> None:
        """Check that a volume level is one a Volumio instance accepts.

        Args:
            value: The volume level, an integer between 0 and 100 (inclusive)

        Raises:
            ValueError: If the volume level is out of range
        """
        if not 0 <= value <= 100:
            self._log_warning(f"Refusing the out-of-range volume level {value}")
            raise ValueError(f"The volume level must be between 0 and 100, got {value}")

    def _fail_connection(self, error: Exception) -> NoReturn:
        """Report that the Volumio instance cannot be reached.

        Args:
            error: The transport failure being translated

        Raises:
            VolumioConnectionError: Always
        """
        self._log_warning(f"Cannot connect to the Volumio API: {error}")
        raise VolumioConnectionError(
            f"Failed to connect to Volumio instance at {self._endpoint_description}: {error}"
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
            f"{self._endpoint_description} "
            f"timed out after {waited} seconds: {error}"
        ) from error

    def _play_position(self, position: int | QueueTrack | None) -> int | None:
        """Return the queue position the playback should start at.

        Args:
            position: Optional position in the queue to play (0-indexed), or a track
                of the queue

        Returns:
            The position to play, or None to start where the queue stands

        Raises:
            ValueError: If the given track does not know its position in the queue
        """
        if isinstance(position, QueueTrack):
            if position.position is None:
                self._log_warning("Refusing to play a track that does not belong to a queue")
                raise ValueError("The track does not belong to a queue")
            return position.position
        return position

    def _playlist_name(self, name: str | Playlist) -> str:
        """Return the name of a playlist given as a string or as a model.

        Args:
            name: The name of the playlist, or the playlist itself

        Returns:
            The name of the playlist

        Raises:
            ValueError: If the given playlist has no name
        """
        if isinstance(name, Playlist):
            if name.name is None:
                self._log_warning("Refusing to play a playlist that has no name")
                raise ValueError("The playlist has no name")
            return name.name
        return name

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
