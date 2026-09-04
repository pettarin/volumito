"""API client for interacting with Volumio instances.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

import logging
from collections.abc import Callable
from types import TracebackType
from typing import Any, Self

import requests

from volumito.clients.entities import (
    Album,
    Artist,
    Label,
    Place,
)
from volumito.clients.host_configuration import VolumioHostConfiguration
from volumito.clients.models import (
    BrowseResults,
    CollectionStatistics,
    CommandResponse,
    Notification,
    Notifications,
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
    Zones,
)
from volumito.clients.rest.common import (
    PATH_ADD_TO_QUEUE,
    PATH_COLLECTION_STATISTICS,
    PATH_GET_QUEUE,
    PATH_GET_STATE,
    PATH_GET_SYSTEM_INFO,
    PATH_GET_SYSTEM_VERSION,
    PATH_GET_ZONES,
    PATH_LIST_PLAYLISTS,
    PATH_PING,
    PATH_PLUGIN_ENDPOINT,
    PATH_PUSH_NOTIFICATION_URLS,
    PATH_REPLACE_AND_PLAY,
    VolumioRESTAPICommon,
)


class VolumioRESTAPIClient(VolumioRESTAPICommon):
    """Client for interacting with Volumio API.

    The client sends its requests through one HTTP session, opened on the first request
    (or on entering a ``with`` block) and closed by :meth:`close` (or on leaving the
    block); a session given to the constructor is used instead, and left to its owner.
    """

    def __init__(
        self,
        host_configuration: VolumioHostConfiguration,
        session: requests.Session | None = None,
        timeout: float = 5.0,
        timeout_slow_endpoints: float = 60.0,
        logger: logging.Logger | None = None,
    ) -> None:
        """Initialize the Volumio client.

        Args:
            host_configuration: The host configuration (scheme, host, and ports)
            session: The HTTP session to send the requests through; without one, the
                client opens its own on the first request, and closes it on
                :meth:`close`
            timeout: Request timeout in seconds (default: 5.0)
            timeout_slow_endpoints: Request timeout, in seconds, for the endpoints
                that can take long, like replacing the queue (default: 60.0)
            logger: The logger the client writes to; without one, the client logs
                under its own name in the ``volumito`` hierarchy
        """
        super().__init__(host_configuration, timeout, timeout_slow_endpoints, logger)
        self._session = session
        self._session_owned = False

    def _delete_json(
        self, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """DELETE ``path`` and parse the response as a JSON object.

        The Volumio API answers some DELETE requests with an empty body, which is
        read as an empty JSON object.

        Args:
            path: The URL path (including any query string) to request
            payload: The JSON body to send, for the requests carrying one

        Returns:
            The parsed JSON object, empty if the response has no body

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error or a non-object response
        """
        response = self._request("delete", path, payload)
        if not response.text.strip():
            return {}
        return self._json_object(response)

    def _ensure_session(self) -> requests.Session:
        """Return the session the requests travel through, opening it when needed.

        Returns:
            The session of the client
        """
        session = self._session
        if session is None:
            self._log_debug("Opening the HTTP session...")
            session = requests.Session()
            self._session = session
            self._session_owned = True
            self._log_debug("Opening the HTTP session... done")
        return session

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
        return self._request("get", path)

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
        return self._json_object(self._get(path))

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
        return self._json_array(self._get(path))

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

    def _json_array(self, response: requests.Response) -> list[Any]:
        """Parse a response body as a JSON array.

        Args:
            response: The response to parse

        Returns:
            The parsed JSON array

        Raises:
            VolumioAPIError: If the body is not parsable, or is not an array
        """
        return self._as_json_array(self._json_payload(response))

    def _json_object(self, response: requests.Response) -> dict[str, Any]:
        """Parse a response body as a JSON object.

        Args:
            response: The response to parse

        Returns:
            The parsed JSON object

        Raises:
            VolumioAPIError: If the body is not parsable, or is not an object
        """
        return self._as_json_object(self._json_payload(response))

    def _json_payload(self, response: requests.Response) -> object:
        """Parse a response body as JSON, whatever its shape.

        Args:
            response: The response to parse

        Returns:
            The parsed JSON value

        Raises:
            VolumioAPIError: If the body is not parsable as JSON
        """
        try:
            return response.json()
        except ValueError as e:
            self._fail_json(e)

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
        return self._post_json(PATH_PLUGIN_ENDPOINT, {"endpoint": endpoint, "data": data})

    def _post_json(
        self,
        path: str,
        payload: dict[str, Any] | list[dict[str, Any]],
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """POST ``payload`` as JSON to ``path`` and parse the response as a JSON object.

        Args:
            path: The URL path to request
            payload: The JSON body to send
            timeout: The request timeout in seconds, :attr:`timeout` when not given

        Returns:
            The parsed JSON object

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error or a non-object response, or
                if the payload is larger than the Volumio instance accepts
        """
        self._check_post_body(payload)
        return self._json_object(self._request("post", path, payload, timeout))

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
        items = [self._slim_queue_item(item.raw) for item in self.browse(uri).items]
        self._log_debug(
            f"Browsing the URI to queue the items it lists... done ({len(items)} items)"
        )
        return items or None

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | list[dict[str, Any]] | None = None,
        timeout: float | None = None,
    ) -> requests.Response:
        """Request ``{rest_base_url}{path}``, translating failures to Volumio errors.

        Args:
            method: The HTTP method, as the session names it (e.g., ``"get"``)
            path: The URL path (including any query string) to request
            payload: The JSON body to send, for the requests carrying one
            timeout: The request timeout in seconds, :attr:`timeout` when not given

        Returns:
            The successful :class:`requests.Response`

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an HTTP error response
        """
        url = f"{self.host_configuration.rest_base_url}{path}"
        send: Callable[..., requests.Response] = getattr(self._ensure_session(), method)
        verb = method.upper()
        waited = timeout if timeout is not None else self.timeout
        arguments: dict[str, Any] = {"timeout": waited}
        self._log_debug(f"Requesting {verb} {url}...")
        if payload is not None:
            arguments["json"] = payload
            self._log_debug(f"Request payload: {payload}")

        try:
            response = send(url, **arguments)
            response.raise_for_status()
        except requests.exceptions.ConnectionError as e:
            self._fail_connection(e)
        except requests.exceptions.Timeout as e:
            self._fail_timeout(e, waited)
        except requests.exceptions.HTTPError as e:
            self._fail_http(e, response.status_code)
        except requests.exceptions.RequestException as e:
            self._fail_request(e)

        self._log_debug(f"Response status: {response.status_code}")
        self._log_debug(f"Requesting {verb} {url}... done")
        return response

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
        self._log_debug(f"Sending the command {cmd}...")
        response = CommandResponse.from_raw(self._get_json(self._command_path(cmd)))
        self._log_debug(f"Sending the command {cmd}... done")
        return response

    def _status(self) -> str:
        """Return the playback status string from the current playback state.

        Returns:
            The playback status (e.g., "play", "pause", "stop")

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response, or the playback
                state does not contain a string status
        """
        return self._state_status(self.state)

    def add_to_queue(self, uri: str) -> CommandResponse:
        """Add the content of a URI to the end of the queue, without touching playback.

        The URI of a container of a source other than the local library is browsed
        first and queued as the items it lists, since only the local library explodes
        its containers by itself.

        Args:
            uri: The URI whose content to add, from a browse or a search

        Returns:
            The response of the Volumio API

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        self._log_debug(f'Adding "{uri}" to the queue...')
        items = self._queue_payload_items(uri)
        payload: dict[str, Any] | list[dict[str, Any]] = (
            items if items is not None else self._queue_uri_item(uri)
        )
        response = CommandResponse.from_raw(
            self._post_json(PATH_ADD_TO_QUEUE, payload, self.timeout_slow_endpoints)
        )
        self._log_debug(f'Adding "{uri}" to the queue... done')
        return response

    def browse(self, uri: str | None = None, offset: int | None = None) -> BrowseResults:
        """Browse the content the Volumio instance lists at a URI.

        The URIs to descend into come from the answers themselves, and from the search
        results; the Volumio API wants ``/`` for the root, which stands in when no URI
        is given. A URI is encoded for the query string except for its structure and
        its percent signs, so the escapes the instance itself puts in its URIs (e.g.,
        ``artists://Paolo%20Conte``) are not encoded twice.

        The offset is applied by the instance to each list of the answer, whose
        ``count`` then tells how many items it held; the root ignores it, and so does
        the instance when it is 0, which is therefore not sent.

        Args:
            uri: The URI to browse, the root when not given
            offset: The number of items to skip in each list, when given

        Returns:
            The content listed at the URI

        Raises:
            ValueError: If the offset is negative
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        path, label = self._browse_request(uri, offset)
        self._log_debug(f"Browsing {label}...")
        results = BrowseResults.from_envelope(self._get_json(path))
        self._log_debug(f"Browsing {label}... done")
        return results

    def clear(self) -> CommandResponse:
        """Clear the playback queue.

        Returns:
            The response of the Volumio API

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return self._send_command("clearQueue")

    def close(self) -> None:
        """Close the session the client sends its requests through.

        Closing is idempotent, and leaves the client usable: a later request opens a
        fresh session. A session given to the constructor belongs to the caller: it is
        left open, and kept for the following requests.
        """
        if self._session is not None and self._session_owned:
            self._log_debug("Closing the HTTP session...")
            self._session.close()
            self._session = None
            self._session_owned = False
            self._log_debug("Closing the HTTP session... done")

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
        return CollectionStatistics.from_raw(self._get_json(PATH_COLLECTION_STATISTICS))

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
        payload = self._album_credits_payload(artist, album)
        envelope = self._plugin_endpoint("metavolumio", payload)
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
        payload = self._story_payload(album, artist, label, place)
        envelope = self._plugin_endpoint("metavolumio", payload)
        return Story.from_envelope(envelope)

    @property
    def has_next(self) -> bool:
        """Whether the current track has a next track in the queue.

        True if and only if a current position exists and it is not the last of the
        queue; without a current track, or with an empty queue, there is no next
        track. Each access performs fresh HTTP requests (reading the playback state
        and the queue).

        Returns:
            True if the queue holds a track after the current one, False otherwise

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return bool(self.queue_status["has_next"])

    @property
    def has_previous(self) -> bool:
        """Whether the current track has a previous track in the queue.

        True if and only if a current position exists and it is not the first of the
        queue; without a current track, or with an empty queue, there is no previous
        track. Each access performs fresh HTTP requests (reading the playback state
        and the queue).

        Returns:
            True if the queue holds a track before the current one, False otherwise

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return bool(self.queue_status["has_previous"])

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
        return self._state_mute(self.state)

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

    @property
    def notifications(self) -> Notifications:
        """The URLs registered to receive the push notifications of the Volumio instance.

        Each access performs a fresh HTTP request.

        Returns:
            The registered notification URLs

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return Notifications.from_urls(self._get_json_list(PATH_PUSH_NOTIFICATION_URLS))

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
        return self._get_text(PATH_PING)

    def play(self, position: int | QueueTrack | None = None) -> CommandResponse:
        """Start playback.

        The track to play can be given by its position in the queue, or as a track of
        the queue itself (e.g., ``client.play(client.queue[3])``).

        Args:
            position: Optional position in the queue to play (0-indexed), or a track
                of the queue

        Returns:
            The response of the Volumio API

        Raises:
            ValueError: If the given track does not know its position in the queue
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return self._send_command(self._play_command(position))

    def play_playlist(self, name: str | Playlist) -> CommandResponse:
        """Start playback of a saved playlist.

        The playlist can be given by name, or as one of the saved playlists (e.g.,
        ``client.play_playlist(client.playlists[0])``).

        Args:
            name: The name of the playlist to play, or the playlist itself

        Returns:
            The response of the Volumio API

        Raises:
            ValueError: If the given playlist has no name
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return self._send_command(self._playlist_command(name))

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
        return Playlists.from_names(self._get_json_list(PATH_LIST_PLAYLISTS))

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
        return Queue.from_raw(self._get_json(PATH_GET_QUEUE))

    @property
    def queue_status(self) -> dict[str, Any]:
        """The navigation state of the queue, as a small mapping.

        The keys are ``has_next`` and ``has_previous`` (whether the current track
        has a neighbor in the queue), ``length`` (the number of queued tracks),
        ``position`` (the 0-based index of the current track, None without one),
        and ``track`` (the playback state payload, as the Volumio host returned
        it). Each access performs fresh HTTP requests (reading the playback state
        and the queue).

        Returns:
            The navigation state of the queue

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        state = self.state
        count = len(self.queue)
        return self._queue_status(state, count)

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
        return self._send_command(self._mode_command("random", value))

    def register_notification(self, url: str | Notification) -> SuccessResponse:
        """Register a URL to receive the push notifications of the Volumio instance.

        The URL can be given as a string, or as one of the registered notifications
        (e.g., ``client.register_notification(other_client.notifications[0])``).

        Args:
            url: The URL to register, or the notification holding it

        Returns:
            The response of the Volumio API

        Raises:
            ValueError: If the given notification has no URL
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        payload = {"url": self._notification_url(url)}
        return SuccessResponse.from_raw(self._post_json(PATH_PUSH_NOTIFICATION_URLS, payload))

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
        return self._send_command(self._mode_command("repeat", value))

    def replace_queue_and_play(self, uri: str, index: int | None = None) -> CommandResponse:
        """Replace the queue with the content of a URI and start playing it.

        Without an index the first item plays. With one, the URI is browsed first and
        its items are sent along with the index, since that is the only payload the
        Volumio API starts at a chosen item with; a URI listing nothing (a single
        track, for instance) falls back to the payload without an index when the
        index is 0, whose first item is the wanted one. Like :meth:`add_to_queue`,
        the URI of a container of a source other than the local library is browsed
        and sent as the items it lists even without an index, since only the local
        library explodes its containers by itself.

        Args:
            uri: The URI whose content to play, from a browse or a search
            index: The position of the item to play first (0-based), or None for
                the first

        Returns:
            The response of the Volumio API

        Raises:
            ValueError: If the index is negative
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response, or if the URI
                does not list enough items to play the asked one
        """
        self._check_play_index(index)
        self._log_debug(f'Replacing the queue with "{uri}"...')
        if index is not None:
            items = [self._slim_queue_item(item.raw) for item in self.browse(uri).items]
            if len(items) > index:
                self._log_debug(f"Sending the {len(items)} listed items, playing index {index}")
                response = CommandResponse.from_raw(
                    self._post_json(
                        PATH_REPLACE_AND_PLAY,
                        {"list": items, "index": index},
                        self.timeout_slow_endpoints,
                    )
                )
                self._log_debug(f'Replacing the queue with "{uri}"... done')
                return response
            if items or index > 0:
                self._fail_short_listing(len(items), index)
        else:
            listed = self._queue_payload_items(uri)
            if listed is not None:
                self._log_debug(f"Sending the {len(listed)} listed items, playing the first")
                response = CommandResponse.from_raw(
                    self._post_json(
                        PATH_REPLACE_AND_PLAY,
                        {"list": listed, "index": 0},
                        self.timeout_slow_endpoints,
                    )
                )
                self._log_debug(f'Replacing the queue with "{uri}"... done')
                return response
        self._log_debug("Sending the URI as a single item, playing its first element")
        item = self._queue_uri_item(uri)
        response = CommandResponse.from_raw(
            self._post_json(
                PATH_REPLACE_AND_PLAY, {"item": item}, self.timeout_slow_endpoints
            )
        )
        self._log_debug(f'Replacing the queue with "{uri}"... done')
        return response

    def search(self, query: str) -> SearchResults:
        """Search the sources of the Volumio instance.

        The Volumio API takes the query only: the results it groups by source and by
        kind can be narrowed with :meth:`SearchResults.filtered`.

        Args:
            query: The text to search for

        Returns:
            The results of the search

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return SearchResults.from_envelope(self._get_json(self._search_path(query)))

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
        return self._state_seek(self.state)

    @seek.setter
    def seek(self, value: int) -> None:
        self._send_command(self._seek_command(value))

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
        return PlayerState.from_raw(self._get_json(PATH_GET_STATE))

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
        return SystemInfo.from_raw(self._get_json(PATH_GET_SYSTEM_INFO))

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
        return SystemVersion.from_raw(self._get_json(PATH_GET_SYSTEM_VERSION))

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

    def unregister_notification(self, url: str | Notification) -> SuccessResponse:
        """Stop pushing the notifications of the Volumio instance to a URL.

        The URL can be given as a string, or as one of the registered notifications
        (e.g., ``client.unregister_notification(client.notifications[0])``).

        Args:
            url: The URL to unregister, or the notification holding it

        Returns:
            The response of the Volumio API

        The URL travels in the request body: the Volumio API documents a ``?url=``
        query string instead, but a Volumio 4 host answers that form with an error.

        Raises:
            ValueError: If the given notification has no URL
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        payload = {"url": self._notification_url(url)}
        return SuccessResponse.from_raw(
            self._delete_json(PATH_PUSH_NOTIFICATION_URLS, payload)
        )

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
        return self._state_volume(self.state)

    @volume.setter
    def volume(self, value: int) -> None:
        self._send_command(self._volume_command(value))

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
        return Zones.from_raw(self._get_json(PATH_GET_ZONES))

    def __enter__(self) -> Self:
        """Open the session of the client, entering a ``with`` block.

        Returns:
            The client itself
        """
        self._ensure_session()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Close the session of the client, leaving a ``with`` block.

        Args:
            exc_type: The class of the exception leaving the block, when one does
            exc_val: The exception leaving the block, when one does
            exc_tb: The traceback of the exception leaving the block, when one does
        """
        self.close()
