"""API client for interacting with Volumio instances.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

from typing import Any
from urllib.parse import quote

import requests

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
    CollectionStatistics,
    CommandResponse,
    PlayerState,
    Playlists,
    Queue,
    Story,
    SystemInfo,
    SystemVersion,
    Zones,
)


class VolumioRESTAPIClient:
    """Client for interacting with Volumio API."""

    def __init__(
        self,
        host_configuration: VolumioHostConfiguration,
        timeout: float = 5.0,
    ) -> None:
        """Initialize the Volumio client.

        Args:
            host_configuration: The host configuration (scheme, host, and ports)
            timeout: Request timeout in seconds (default: 5.0)
        """
        self.host_configuration = host_configuration
        self.timeout = timeout

    def _get(self, path: str) -> requests.Response:
        """GET ``{rest_base_url}{path}``, translating request failures to Volumio errors.

        Args:
            path: The URL path (including any query string) to request

        Returns:
            The successful :class:`requests.Response`

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an HTTP error response
        """
        url = f"{self.host_configuration.rest_base_url}{path}"

        try:
            response = requests.get(url, timeout=self.timeout)
            response.raise_for_status()
        except requests.exceptions.ConnectionError as e:
            raise VolumioConnectionError(
                f"Failed to connect to Volumio instance at "
                f"{self.host_configuration.rest_base_url}: {e}"
            ) from e
        except requests.exceptions.Timeout as e:
            raise VolumioConnectionError(
                f"Connection to Volumio instance at "
                f"{self.host_configuration.rest_base_url} "
                f"timed out after {self.timeout} seconds: {e}"
            ) from e
        except requests.exceptions.HTTPError as e:
            raise VolumioAPIError(
                f"Volumio API returned HTTP error {response.status_code}: {e}"
            ) from e
        except requests.exceptions.RequestException as e:
            raise VolumioConnectionError(
                f"Request to Volumio instance at "
                f"{self.host_configuration.rest_base_url} failed: {e}"
            ) from e

        return response

    def _get_json(self, path: str) -> dict[str, Any]:
        """GET ``path`` and parse the response as a JSON object.

        Args:
            path: The URL path (including any query string) to request

        Returns:
            The parsed JSON object

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error or a non-object response
        """
        response = self._get(path)

        try:
            data = response.json()
        except ValueError as e:
            raise VolumioAPIError(
                f"Failed to parse JSON response from Volumio API: {e}"
            ) from e

        if not isinstance(data, dict):
            raise VolumioAPIError(
                f"Expected JSON object from Volumio API, got {type(data).__name__}"
            )

        return data

    def _get_json_list(self, path: str) -> list[Any]:
        """GET ``path`` and parse the response as a JSON array.

        Args:
            path: The URL path (including any query string) to request

        Returns:
            The parsed JSON array

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error or a non-array response
        """
        response = self._get(path)

        try:
            data = response.json()
        except ValueError as e:
            raise VolumioAPIError(
                f"Failed to parse JSON response from Volumio API: {e}"
            ) from e

        if not isinstance(data, list):
            raise VolumioAPIError(
                f"Expected JSON array from Volumio API, got {type(data).__name__}"
            )

        return data

    def _get_text(self, path: str) -> str:
        """GET ``path`` and return the response body as text.

        Args:
            path: The URL path (including any query string) to request

        Returns:
            The response body text

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an HTTP error response
        """
        return self._get(path).text

    def _plugin_endpoint(self, endpoint: str, data: dict[str, Any]) -> dict[str, Any]:
        """POST a plugin endpoint request to the Volumio instance.

        The response envelope (e.g., ``{"success": true, "data": {...}}`` or
        ``{"success": false, "error": "..."}`` for the Premium plugins) is returned
        verbatim, without interpreting the "success" flag.

        Args:
            endpoint: The name of the plugin endpoint (e.g., "metavolumio")
            data: The data payload to send to the plugin endpoint

        Returns:
            The response of the Volumio API

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error or a non-object response
        """
        return self._post_json("/api/v1/pluginEndpoint", {"endpoint": endpoint, "data": data})

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST ``payload`` as JSON to ``path`` and parse the response as a JSON object.

        Args:
            path: The URL path to request
            payload: The JSON body to send

        Returns:
            The parsed JSON object

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error or a non-object response
        """
        url = f"{self.host_configuration.rest_base_url}{path}"

        try:
            response = requests.post(url, json=payload, timeout=self.timeout)
            response.raise_for_status()
        except requests.exceptions.ConnectionError as e:
            raise VolumioConnectionError(
                f"Failed to connect to Volumio instance at "
                f"{self.host_configuration.rest_base_url}: {e}"
            ) from e
        except requests.exceptions.Timeout as e:
            raise VolumioConnectionError(
                f"Connection to Volumio instance at "
                f"{self.host_configuration.rest_base_url} "
                f"timed out after {self.timeout} seconds: {e}"
            ) from e
        except requests.exceptions.HTTPError as e:
            raise VolumioAPIError(
                f"Volumio API returned HTTP error {response.status_code}: {e}"
            ) from e
        except requests.exceptions.RequestException as e:
            raise VolumioConnectionError(
                f"Request to Volumio instance at "
                f"{self.host_configuration.rest_base_url} failed: {e}"
            ) from e

        try:
            data = response.json()
        except ValueError as e:
            raise VolumioAPIError(
                f"Failed to parse JSON response from Volumio API: {e}"
            ) from e

        if not isinstance(data, dict):
            raise VolumioAPIError(
                f"Expected JSON object from Volumio API, got {type(data).__name__}"
            )

        return data

    def _send_command(self, cmd: str) -> CommandResponse:
        """Send a playback control command to the Volumio instance.

        Args:
            cmd: The command to send (e.g., "play", "pause", "stop", "toggle", "next", "prev")

        Returns:
            The response of the Volumio API

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        url = f"{self.host_configuration.rest_base_url}/api/v1/commands/?cmd={cmd}"

        try:
            response = requests.get(url, timeout=self.timeout)
            response.raise_for_status()
        except requests.exceptions.ConnectionError as e:
            raise VolumioConnectionError(
                f"Failed to connect to Volumio instance at "
                f"{self.host_configuration.rest_base_url}: {e}"
            ) from e
        except requests.exceptions.Timeout as e:
            raise VolumioConnectionError(
                f"Connection to Volumio instance at "
                f"{self.host_configuration.rest_base_url} "
                f"timed out after {self.timeout} seconds: {e}"
            ) from e
        except requests.exceptions.HTTPError as e:
            raise VolumioAPIError(
                f"Volumio API returned HTTP error {response.status_code}: {e}"
            ) from e
        except requests.exceptions.RequestException as e:
            raise VolumioConnectionError(
                f"Request to Volumio instance at "
                f"{self.host_configuration.rest_base_url} failed: {e}"
            ) from e

        try:
            data = response.json()
        except ValueError as e:
            raise VolumioAPIError(
                f"Failed to parse JSON response from Volumio API: {e}"
            ) from e

        if not isinstance(data, dict):
            raise VolumioAPIError(
                f"Expected JSON object from Volumio API, got {type(data).__name__}"
            )

        return CommandResponse.from_raw(data)

    def _status(self) -> str:
        """Return the playback status string from the current playback state.

        Returns:
            The playback status (e.g., "play", "pause", "stop")

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response, or the playback
                state does not contain a string status
        """
        state = self.state
        if state.status is None:
            raise VolumioAPIError(
                f"Expected a string status in the Volumio state, "
                f"got {type(state.raw.get('status')).__name__}"
            )
        return state.status

    @staticmethod
    def _story_album_payload(artist: Artist | None, album: Album) -> dict[str, str]:
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
                raise ValueError("An album specified by MBID does not take an artist")
            return {"mbid": album.value}
        if artist is None:
            raise ValueError("An album specified by title requires an artist")
        if artist.is_mbid:
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

    def clear(self) -> CommandResponse:
        """Clear the playback queue.

        Returns:
            The response of the Volumio API

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return self._send_command("clearQueue")

    @property
    def collection_statistics(self) -> CollectionStatistics:
        """The statistics of the music collection of the Volumio instance.

        Each access performs a fresh HTTP request.

        Returns:
            The statistics of the music collection

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return CollectionStatistics.from_raw(self._get_json("/api/v1/collectionstats"))

    def decrease_volume(self) -> CommandResponse:
        """Decrease the playback volume by one step.

        The decrement is the one defined in the settings of the Volumio host.

        Returns:
            The response of the Volumio API

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return self._send_command("volume&volume=minus")

    def get_album_credits(self, artist: Artist | None, album: Album) -> Story:
        """Get the credits of an album via the metavolumio plugin endpoint.

        Requires the Volumio host to be running with a Premium (or better)
        subscription. The whole response envelope is kept in the ``raw`` attribute
        of the returned story.

        Args:
            artist: The album's artist by name; must be None when the album is an MBID
            album: The album, by title (requiring the artist) or by MBID

        Returns:
            The credits of the album

        Raises:
            ValueError: If the artist/album combination is invalid
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioStoryError: If the Volumio host reports a failed query
            VolumioAPIError: If the API returns an error or a non-object response
        """
        payload = self._story_album_payload(artist, album)
        envelope = self._plugin_endpoint("metavolumio", {"mode": "creditsAlbum", **payload})
        return Story.from_envelope(envelope)

    def get_story(
        self,
        album: Album | None = None,
        artist: Artist | None = None,
        label: Label | None = None,
        place: Place | None = None,
    ) -> Story:
        """Get the story of an album, artist, label, or place via metavolumio.

        Requires the Volumio host to be running with a Premium (or better)
        subscription. Exactly one entity must be queried: an album (with its artist
        by name, unless the album is an MBID), an artist, a label, or a place. The
        whole response envelope is kept in the ``raw`` attribute of the returned
        story.

        Args:
            album: The album, by title (requiring the artist) or by MBID
            artist: The artist, by name or by MBID (or the album's artist by name)
            label: The record label, by name or by MBID
            place: The place, by name or by MBID

        Returns:
            The story of the queried entity

        Raises:
            ValueError: If the entity combination is invalid
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioStoryError: If the Volumio host reports a failed query
            VolumioAPIError: If the API returns an error or a non-object response
        """
        if label is not None and place is not None:
            raise ValueError("The label and place entities are mutually exclusive")
        if album is not None:
            if label is not None or place is not None:
                raise ValueError("An album story does not take a label or place")
            payload = self._story_album_payload(artist, album)
            envelope = self._plugin_endpoint("metavolumio", {"mode": "storyAlbum", **payload})
            return Story.from_envelope(envelope)
        if artist is not None:
            if label is not None or place is not None:
                raise ValueError("An artist story does not take a label or place")
            payload = self._story_entity_payload("artist", artist)
            envelope = self._plugin_endpoint("metavolumio", {"mode": "storyArtist", **payload})
            return Story.from_envelope(envelope)
        if label is not None:
            payload = self._story_entity_payload("label", label)
            envelope = self._plugin_endpoint("metavolumio", {"mode": "storyLabel", **payload})
            return Story.from_envelope(envelope)
        if place is not None:
            payload = self._story_entity_payload("place", place)
            envelope = self._plugin_endpoint("metavolumio", {"mode": "storyPlace", **payload})
            return Story.from_envelope(envelope)
        raise ValueError("One of album, artist, label, or place is required")

    def increase_volume(self) -> CommandResponse:
        """Increase the playback volume by one step.

        The increment is the one defined in the settings of the Volumio host.

        Returns:
            The response of the Volumio API

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return self._send_command("volume&volume=plus")

    @property
    def is_muted(self) -> bool:
        """Whether the playback volume of the Volumio instance is muted.

        Each access performs a fresh HTTP request (reading the playback state).

        See :meth:`mute` and :meth:`unmute` for muting and unmuting the volume.

        Returns:
            True if the volume is muted, False otherwise

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response, or the playback
                state does not contain a boolean mute flag
        """
        state = self.state
        if state.mute is None:
            raise VolumioAPIError(
                f"Expected a boolean mute flag in the Volumio state, "
                f"got {type(state.raw.get('mute')).__name__}"
            )
        return state.mute

    @property
    def is_paused(self) -> bool:
        """Whether the playback of the Volumio instance is paused.

        True if and only if the playback status is "pause". Each access performs a
        fresh HTTP request (reading the playback state).

        See :meth:`pause` for pausing the playback.

        Returns:
            True if the playback status is "pause", False otherwise

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response, or the playback
                state does not contain a string status
        """
        return self._status() == "pause"

    @property
    def is_playing(self) -> bool:
        """Whether the Volumio instance is playing.

        True if and only if the playback status is "play". Each access performs a
        fresh HTTP request (reading the playback state).

        See :meth:`play` for starting the playback.

        Returns:
            True if the playback status is "play", False otherwise

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response, or the playback
                state does not contain a string status
        """
        return self._status() == "play"

    @property
    def is_stopped(self) -> bool:
        """Whether the playback of the Volumio instance is stopped.

        True if and only if the playback status is "stop". Each access performs a
        fresh HTTP request (reading the playback state).

        See :meth:`stop` for stopping the playback.

        Returns:
            True if the playback status is "stop", False otherwise

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response, or the playback
                state does not contain a string status
        """
        return self._status() == "stop"

    def mute(self) -> CommandResponse:
        """Mute the playback volume.

        Returns:
            The response of the Volumio API

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return self._send_command("volume&volume=mute")

    def next(self) -> CommandResponse:
        """Skip to the next track.

        Returns:
            The response of the Volumio API

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return self._send_command("next")

    def pause(self) -> CommandResponse:
        """Pause playback.

        Returns:
            The response of the Volumio API

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return self._send_command("pause")

    def ping(self) -> str:
        """Ping the Volumio instance to check that it is reachable.

        Returns:
            The response body text (``"pong"`` from a healthy Volumio instance)

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return self._get_text("/api/v1/ping")

    def play(self, position: int | None = None) -> CommandResponse:
        """Start playback.

        Args:
            position: Optional position in the queue to play (0-indexed)

        Returns:
            The response of the Volumio API

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        if position is not None:
            return self._send_command(f"play&N={position}")
        return self._send_command("play")

    def play_playlist(self, name: str) -> CommandResponse:
        """Start playback of a saved playlist.

        Args:
            name: The name of the playlist to play

        Returns:
            The response of the Volumio API

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return self._send_command(f"playplaylist&name={quote(name, safe='')}")

    @property
    def playlists(self) -> Playlists:
        """The playlists saved on the Volumio instance.

        Each access performs a fresh HTTP request.

        Returns:
            The saved playlists

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return Playlists.from_names(self._get_json_list("/api/v1/listplaylists"))

    def previous(self) -> CommandResponse:
        """Skip to the previous track.

        Returns:
            The response of the Volumio API

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return self._send_command("prev")

    @property
    def queue(self) -> Queue:
        """The current playback queue of the Volumio instance.

        Each access performs a fresh HTTP request.

        Returns:
            The current playback queue

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return Queue.from_raw(self._get_json("/api/v1/getQueue"))

    def randomize(self, value: bool | None = None) -> CommandResponse:
        """Set or toggle the random (shuffle) mode.

        Args:
            value: True to enable, False to disable, or None (the default) to let
                the Volumio API toggle the current random mode

        Returns:
            The response of the Volumio API

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        if value is None:
            return self._send_command("random")
        return self._send_command(f"random&value={str(value).lower()}")

    def repeat(self, value: bool | None = None) -> CommandResponse:
        """Set or toggle the repeat mode.

        Args:
            value: True to enable, False to disable, or None (the default) to let
                the Volumio API toggle the current repeat mode

        Returns:
            The response of the Volumio API

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        if value is None:
            return self._send_command("repeat")
        return self._send_command(f"repeat&value={str(value).lower()}")

    @property
    def seek(self) -> int:
        """The seek position, in seconds, in the track currently playing.

        Reading the property fetches the position from the current playback state,
        rounding the milliseconds reported there down to whole seconds (each access
        performs a fresh HTTP request); assigning to it seeks to an absolute
        position, also in seconds.

        See :meth:`seek_backward` and :meth:`seek_forward` for relative seeking.

        Returns:
            The current seek position, in seconds

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response, or the playback
                state does not contain an integer seek position
        """
        state = self.state
        if state.seek is None:
            raise VolumioAPIError(
                f"Expected an integer seek position in the Volumio state, "
                f"got {type(state.raw.get('seek')).__name__}"
            )
        return state.seek // 1000

    @seek.setter
    def seek(self, value: int) -> None:
        self._send_command(f"seek&position={value}")

    def seek_backward(self) -> CommandResponse:
        """Seek backward by 10 seconds in the track currently playing.

        Returns:
            The response of the Volumio API

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return self._send_command("seek&position=minus")

    def seek_forward(self) -> CommandResponse:
        """Seek forward by 10 seconds in the track currently playing.

        Returns:
            The response of the Volumio API

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return self._send_command("seek&position=plus")

    @property
    def state(self) -> PlayerState:
        """The current playback state of the Volumio instance.

        Each access performs a fresh HTTP request.

        Returns:
            The current playback state of the Volumio instance

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return PlayerState.from_raw(self._get_json("/api/v1/getState"))

    def stop(self) -> CommandResponse:
        """Stop playback.

        Returns:
            The response of the Volumio API

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return self._send_command("stop")

    @property
    def system_info(self) -> SystemInfo:
        """The system information of the Volumio instance.

        Each access performs a fresh HTTP request.

        Returns:
            The system information of the Volumio instance

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return SystemInfo.from_raw(self._get_json("/api/v1/getSystemInfo"))

    @property
    def system_version(self) -> SystemVersion:
        """The system version of the Volumio instance.

        Each access performs a fresh HTTP request.

        Returns:
            The system version of the Volumio instance

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return SystemVersion.from_raw(self._get_json("/api/v1/getSystemVersion"))

    def toggle(self) -> CommandResponse:
        """Toggle between play and pause states.

        Returns:
            The response of the Volumio API

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return self._send_command("toggle")

    def unmute(self) -> CommandResponse:
        """Unmute the playback volume.

        Returns:
            The response of the Volumio API

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return self._send_command("volume&volume=unmute")

    @property
    def volume(self) -> int:
        """The playback volume level of the Volumio instance.

        Reading the property fetches the level from the current playback state
        (each access performs a fresh HTTP request); assigning to it sets the
        volume to an absolute level, an integer between 0 and 100 (inclusive),
        raising a ValueError for an out-of-range value.

        See :meth:`decrease_volume` and :meth:`increase_volume` for stepping the
        volume, and :meth:`mute` and :meth:`unmute` for muting and unmuting it.

        Returns:
            The volume level, an integer between 0 and 100 (inclusive)

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response, or the playback
                state does not contain an integer volume level
        """
        state = self.state
        if state.volume is None:
            raise VolumioAPIError(
                f"Expected an integer volume level in the Volumio state, "
                f"got {type(state.raw.get('volume')).__name__}"
            )
        return state.volume

    @volume.setter
    def volume(self, value: int) -> None:
        if not 0 <= value <= 100:
            raise ValueError(f"The volume level must be between 0 and 100, got {value}")
        self._send_command(f"volume&volume={value}")

    @property
    def zones(self) -> Zones:
        """The multiroom zones seen by the Volumio instance.

        Each access performs a fresh HTTP request.

        Returns:
            The multiroom zones seen by the Volumio instance

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return Zones.from_raw(self._get_json("/api/v1/getzones"))
