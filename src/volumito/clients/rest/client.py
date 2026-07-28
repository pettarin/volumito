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
    MusicBrainzEntityReference,
    Place,
)
from volumito.clients.errors import VolumioAPIError, VolumioConnectionError
from volumito.clients.host_configuration import VolumioHostConfiguration


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

        The response envelope (e.g. ``{"success": true, "data": {...}}`` or
        ``{"success": false, "error": "..."}`` for the Premium plugins) is returned
        verbatim, without interpreting the "success" flag.

        Args:
            endpoint: The name of the plugin endpoint (e.g. "metavolumio")
            data: The data payload to send to the plugin endpoint

        Returns:
            A dictionary containing the response from the Volumio API

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

    def _send_command(self, cmd: str) -> dict[str, Any]:
        """Send a playback control command to the Volumio instance.

        Args:
            cmd: The command to send (e.g., "play", "pause", "stop", "toggle", "next", "prev")

        Returns:
            A dictionary containing the response from the Volumio API

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

        return data

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
    def _story_entity_payload(key: str, entity: MusicBrainzEntityReference) -> dict[str, str]:
        """Build the metavolumio data payload (without the mode key) for a single entity.

        Args:
            key: The payload key of the free-text value (e.g. "artist")
            entity: The entity, by free-text value or by MBID

        Returns:
            The data payload dictionary
        """
        if entity.is_mbid:
            return {"mbid": entity.value}
        return {key: entity.value}

    def clear(self) -> dict[str, Any]:
        """Clear the playback queue.

        Returns:
            A dictionary containing the response from the Volumio API

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return self._send_command("clearQueue")

    @property
    def collection_statistics(self) -> dict[str, Any]:
        """The statistics of the music collection of the Volumio instance.

        Each access performs a fresh HTTP request.

        Returns:
            A dictionary containing the statistics of the music collection

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return self._get_json("/api/v1/collectionstats")

    def decrease_volume(self) -> dict[str, Any]:
        """Decrease the playback volume by one step.

        The decrement is the one defined in the settings of the Volumio host.

        Returns:
            A dictionary containing the response from the Volumio API

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return self._send_command("volume&volume=minus")

    def get_album_credits(self, artist: Artist | None, album: Album) -> dict[str, Any]:
        """Get the credits of an album via the metavolumio plugin endpoint.

        Requires the Volumio host to be running with a Premium (or better)
        subscription. The response envelope (``{"success": ..., ...}``) is returned
        verbatim, without interpreting the "success" flag.

        Args:
            artist: The album's artist by name; must be None when the album is an MBID
            album: The album, by title (requiring the artist) or by MBID

        Returns:
            A dictionary containing the response from the Volumio API

        Raises:
            ValueError: If the artist/album combination is invalid
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error or a non-object response
        """
        payload = self._story_album_payload(artist, album)
        return self._plugin_endpoint("metavolumio", {"mode": "creditsAlbum", **payload})

    def get_story(
        self,
        album: Album | None = None,
        artist: Artist | None = None,
        label: Label | None = None,
        place: Place | None = None,
    ) -> dict[str, Any]:
        """Get the story of an album, artist, label, or place via metavolumio.

        Requires the Volumio host to be running with a Premium (or better)
        subscription. Exactly one entity must be queried: an album (with its artist
        by name, unless the album is an MBID), an artist, a label, or a place. The
        response envelope (``{"success": ..., ...}``) is returned verbatim, without
        interpreting the "success" flag.

        Args:
            album: The album, by title (requiring the artist) or by MBID
            artist: The artist, by name or by MBID (or the album's artist by name)
            label: The record label, by name or by MBID
            place: The place, by name or by MBID

        Returns:
            A dictionary containing the response from the Volumio API

        Raises:
            ValueError: If the entity combination is invalid
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error or a non-object response
        """
        if label is not None and place is not None:
            raise ValueError("The label and place entities are mutually exclusive")
        if album is not None:
            if label is not None or place is not None:
                raise ValueError("An album story does not take a label or place")
            payload = self._story_album_payload(artist, album)
            return self._plugin_endpoint("metavolumio", {"mode": "storyAlbum", **payload})
        if artist is not None:
            if label is not None or place is not None:
                raise ValueError("An artist story does not take a label or place")
            payload = self._story_entity_payload("artist", artist)
            return self._plugin_endpoint("metavolumio", {"mode": "storyArtist", **payload})
        if label is not None:
            payload = self._story_entity_payload("label", label)
            return self._plugin_endpoint("metavolumio", {"mode": "storyLabel", **payload})
        if place is not None:
            payload = self._story_entity_payload("place", place)
            return self._plugin_endpoint("metavolumio", {"mode": "storyPlace", **payload})
        raise ValueError("One of album, artist, label, or place is required")

    def increase_volume(self) -> dict[str, Any]:
        """Increase the playback volume by one step.

        The increment is the one defined in the settings of the Volumio host.

        Returns:
            A dictionary containing the response from the Volumio API

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return self._send_command("volume&volume=plus")

    def mute(self) -> dict[str, Any]:
        """Mute the playback volume.

        Returns:
            A dictionary containing the response from the Volumio API

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return self._send_command("volume&volume=mute")

    def next(self) -> dict[str, Any]:
        """Skip to the next track.

        Returns:
            A dictionary containing the response from the Volumio API

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return self._send_command("next")

    def pause(self) -> dict[str, Any]:
        """Pause playback.

        Returns:
            A dictionary containing the response from the Volumio API

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

    def play(self, position: int | None = None) -> dict[str, Any]:
        """Start playback.

        Args:
            position: Optional position in the queue to play (0-indexed)

        Returns:
            A dictionary containing the response from the Volumio API

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        if position is not None:
            return self._send_command(f"play&N={position}")
        return self._send_command("play")

    def play_playlist(self, name: str) -> dict[str, Any]:
        """Start playback of a saved playlist.

        Args:
            name: The name of the playlist to play

        Returns:
            A dictionary containing the response from the Volumio API

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return self._send_command(f"playplaylist&name={quote(name, safe='')}")

    @property
    def playlists(self) -> list[Any]:
        """The names of the playlists saved on the Volumio instance.

        Each access performs a fresh HTTP request.

        Returns:
            A list containing the names of the saved playlists

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return self._get_json_list("/api/v1/listplaylists")

    def previous(self) -> dict[str, Any]:
        """Skip to the previous track.

        Returns:
            A dictionary containing the response from the Volumio API

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return self._send_command("prev")

    @property
    def queue(self) -> dict[str, Any]:
        """The current playback queue of the Volumio instance.

        Each access performs a fresh HTTP request.

        Returns:
            A dictionary containing the current playback queue

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return self._get_json("/api/v1/getQueue")

    def randomize(self, value: bool | None = None) -> dict[str, Any]:
        """Set or toggle the random (shuffle) mode.

        Args:
            value: True to enable, False to disable, or None (the default) to let
                the Volumio API toggle the current random mode

        Returns:
            A dictionary containing the response from the Volumio API

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        if value is None:
            return self._send_command("random")
        return self._send_command(f"random&value={str(value).lower()}")

    def repeat(self, value: bool | None = None) -> dict[str, Any]:
        """Set or toggle the repeat mode.

        Args:
            value: True to enable, False to disable, or None (the default) to let
                the Volumio API toggle the current repeat mode

        Returns:
            A dictionary containing the response from the Volumio API

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        if value is None:
            return self._send_command("repeat")
        return self._send_command(f"repeat&value={str(value).lower()}")

    def seek(self, value: int) -> dict[str, Any]:
        """Seek to an absolute position in the track currently playing.

        See :meth:`seek_backward` and :meth:`seek_forward` for relative seeking.

        Args:
            value: The position to seek to, in seconds

        Returns:
            A dictionary containing the response from the Volumio API

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return self._send_command(f"seek&position={value}")

    def seek_backward(self) -> dict[str, Any]:
        """Seek backward by 10 seconds in the track currently playing.

        Returns:
            A dictionary containing the response from the Volumio API

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return self._send_command("seek&position=minus")

    def seek_forward(self) -> dict[str, Any]:
        """Seek forward by 10 seconds in the track currently playing.

        Returns:
            A dictionary containing the response from the Volumio API

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return self._send_command("seek&position=plus")

    @property
    def state(self) -> dict[str, Any]:
        """The current playback state of the Volumio instance.

        Each access performs a fresh HTTP request.

        Returns:
            A dictionary containing the current state of the Volumio instance

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return self._get_json("/api/v1/getState")

    def stop(self) -> dict[str, Any]:
        """Stop playback.

        Returns:
            A dictionary containing the response from the Volumio API

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return self._send_command("stop")

    @property
    def system_info(self) -> dict[str, Any]:
        """The system information of the Volumio instance.

        Each access performs a fresh HTTP request.

        Returns:
            A dictionary containing the Volumio system information

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return self._get_json("/api/v1/getSystemInfo")

    @property
    def system_version(self) -> dict[str, Any]:
        """The system version of the Volumio instance.

        Each access performs a fresh HTTP request.

        Returns:
            A dictionary containing the Volumio system version information

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return self._get_json("/api/v1/getSystemVersion")

    def toggle(self) -> dict[str, Any]:
        """Toggle between play and pause states.

        Returns:
            A dictionary containing the response from the Volumio API

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return self._send_command("toggle")

    def unmute(self) -> dict[str, Any]:
        """Unmute the playback volume.

        Returns:
            A dictionary containing the response from the Volumio API

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return self._send_command("volume&volume=unmute")

    def volume(self, value: int) -> dict[str, Any]:
        """Set the playback volume to an absolute level.

        See :meth:`decrease_volume` and :meth:`increase_volume` for stepping the
        volume, and :meth:`mute` and :meth:`unmute` for muting and unmuting it.

        Args:
            value: The volume level, an integer between 0 and 100 (inclusive)

        Returns:
            A dictionary containing the response from the Volumio API

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return self._send_command(f"volume&volume={value}")

    @property
    def zones(self) -> dict[str, Any]:
        """The multiroom zones seen by the Volumio instance.

        Each access performs a fresh HTTP request.

        Returns:
            A dictionary containing the multiroom zones (under the "zones" key)

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return self._get_json("/api/v1/getzones")
