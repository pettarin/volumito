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
from volumito.clients.models import PlayerState

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
