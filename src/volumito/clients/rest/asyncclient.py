"""Async API client for interacting with Volumio instances.

This client mirrors :class:`VolumioRESTAPIClient` over ``aiohttp``, which is an
optional dependency: install it with ``pip install volumito[async]``.

The members the synchronous client exposes as properties are coroutine methods here,
since a property cannot be awaited: the nouns take a ``get_`` prefix
(``await client.get_state()``), the predicates keep their names
(``await client.is_playing()``), and the two assignable properties become
:meth:`set_seek` and :meth:`set_volume`.

The client owns an ``aiohttp`` session, opened on the first request: use it as an
async context manager, or close it with :meth:`close` when done, otherwise ``aiohttp``
reports an unclosed session once the client is garbage collected.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

import json
import logging
from types import ModuleType, TracebackType
from typing import TYPE_CHECKING, Any, Self, cast

from volumito.clients.entities import (
    Album,
    Artist,
    Label,
    Place,
)
from volumito.clients.errors import VolumioAsyncError
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

if TYPE_CHECKING:
    import aiohttp


def _load_aiohttp() -> ModuleType:
    """Import the optional async HTTP dependency, when a request is about to be made.

    Returns:
        The aiohttp module

    Raises:
        VolumioAsyncError: If the package is not installed
    """
    try:
        import aiohttp
    except ImportError as e:
        raise VolumioAsyncError(
            "Reaching the Volumio host asynchronously needs the aiohttp package: "
            "install it with 'pip install volumito[async]'"
        ) from e

    return aiohttp


class VolumioAsyncRESTAPIClient(VolumioRESTAPICommon):
    """Async client for interacting with Volumio API."""

    _CLIENT_DESCRIPTION: str = "async REST API client"

    def __init__(
        self,
        host_configuration: VolumioHostConfiguration,
        timeout: float = 5.0,
        timeout_slow_endpoints: float = 60.0,
        logger: logging.Logger | None = None,
    ) -> None:
        """Initialize the async Volumio client.

        The session the client sends its requests through is opened on the first
        request, not here, so the client can be built outside a running event loop.

        Args:
            host_configuration: The host configuration (scheme, host, and ports)
            timeout: Request timeout in seconds (default: 5.0)
            timeout_slow_endpoints: Request timeout, in seconds, for the endpoints
                that can take long, like replacing the queue (default: 60.0)
            logger: The logger the client writes to; without one, the client logs
                under its own name in the ``volumito`` hierarchy
        """
        super().__init__(host_configuration, timeout, timeout_slow_endpoints, logger)
        self._session: aiohttp.ClientSession | None = None

    async def _delete_json(
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
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error or a non-object response
        """
        body = await self._request("DELETE", path, payload)
        if not body.strip():
            return {}
        return self._json_object(body)

    def _ensure_session(self) -> "aiohttp.ClientSession":
        """Return the session the requests travel through, opening it when needed.

        Returns:
            The session of the client

        Raises:
            VolumioAsyncError: If the aiohttp package is not installed
        """
        session = self._session
        if session is None:
            aio: Any = _load_aiohttp()
            self._log_debug("Opening the HTTP session...")
            session = cast("aiohttp.ClientSession", aio.ClientSession())
            self._session = session
            self._log_debug("Opening the HTTP session... done")
        return session

    async def _get_json(self, path: str) -> dict[str, Any]:
        """GET ``path`` and parse the response as a JSON object.

        Args:
            path: The URL path (including any query string) to request

        Returns:
            The parsed JSON object

        Raises:
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error or a non-object response
        """
        return self._json_object(await self._request("GET", path))

    async def _get_json_list(self, path: str) -> list[Any]:
        """GET ``path`` and parse the response as a JSON array.

        Args:
            path: The URL path (including any query string) to request

        Returns:
            The parsed JSON array

        Raises:
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error or a non-array response
        """
        return self._json_array(await self._request("GET", path))

    async def _get_text(self, path: str) -> str:
        """GET ``path`` and return the response body as text.

        Args:
            path: The URL path (including any query string) to request

        Returns:
            The response body text

        Raises:
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an HTTP error response
        """
        return await self._request("GET", path)

    def _json_array(self, body: str) -> list[Any]:
        """Parse a response body as a JSON array.

        Args:
            body: The response body to parse

        Returns:
            The parsed JSON array

        Raises:
            VolumioAPIError: If the body is not parsable, or is not an array
        """
        return self._as_json_array(self._json_payload(body))

    def _json_object(self, body: str) -> dict[str, Any]:
        """Parse a response body as a JSON object.

        Args:
            body: The response body to parse

        Returns:
            The parsed JSON object

        Raises:
            VolumioAPIError: If the body is not parsable, or is not an object
        """
        return self._as_json_object(self._json_payload(body))

    def _json_payload(self, body: str) -> object:
        """Parse a response body as JSON, whatever its shape.

        Args:
            body: The response body to parse

        Returns:
            The parsed JSON value

        Raises:
            VolumioAPIError: If the body is not parsable as JSON
        """
        try:
            return json.loads(body)
        except ValueError as e:
            self._fail_json(e)

    async def _plugin_endpoint(self, endpoint: str, data: dict[str, Any]) -> dict[str, Any]:
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
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error or a non-object response
        """
        return await self._post_json(PATH_PLUGIN_ENDPOINT, {"endpoint": endpoint, "data": data})

    async def _post_json(
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
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error or a non-object response, or
                if the payload is larger than the Volumio instance accepts
        """
        self._check_post_body(payload)
        return self._json_object(await self._request("POST", path, payload, timeout))

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

        Raises:
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        if self._uri_service(uri) == "mpd":
            self._log_debug("The URI belongs to the local library: queueing it as itself")
            return None
        self._log_debug("Browsing the URI to queue the items it lists...")
        items = [self._slim_queue_item(item.raw) for item in (await self.browse(uri)).items]
        self._log_debug(
            f"Browsing the URI to queue the items it lists... done ({len(items)} items)"
        )
        return items or None

    async def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | list[dict[str, Any]] | None = None,
        timeout: float | None = None,
    ) -> str:
        """Request ``{rest_base_url}{path}``, translating failures to Volumio errors.

        The body is read inside the response context, since leaving it releases the
        connection: the text of a successful response is what the callers parse.

        Args:
            method: The HTTP method of the request (e.g., ``"GET"``)
            path: The URL path (including any query string) to request
            payload: The JSON body to send, for the requests carrying one
            timeout: The request timeout in seconds, :attr:`timeout` when not given

        Returns:
            The body of the successful response, as text

        Raises:
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an HTTP error response
        """
        aio: Any = _load_aiohttp()
        session = self._ensure_session()
        url = f"{self.host_configuration.rest_base_url}{path}"
        verb = method.upper()
        waited = timeout if timeout is not None else self.timeout
        arguments: dict[str, Any] = {"timeout": aio.ClientTimeout(total=waited)}
        self._log_debug(f"Requesting {verb} {url}...")
        if payload is not None:
            arguments["json"] = payload
            self._log_debug(f"Request payload: {payload}")

        try:
            async with session.request(verb, url, **arguments) as response:
                status = response.status
                response.raise_for_status()
                body = await response.text()
        # A total timeout raises the builtin TimeoutError, which is no ClientError at
        # all, while the socket-level timeouts are also connection errors: both must
        # be caught before the connection failures they would otherwise be read as
        except TimeoutError as e:
            self._fail_timeout(e, waited)
        except aio.ClientConnectionError as e:
            self._fail_connection(e)
        except aio.ClientResponseError as e:
            self._fail_http(e, e.status)
        except aio.ClientError as e:
            self._fail_request(e)

        self._log_debug(f"Response status: {status}")
        self._log_debug(f"Requesting {verb} {url}... done")
        return body

    async def _send_command(self, cmd: str) -> CommandResponse:
        """Send a playback control command to the Volumio instance.

        Args:
            cmd: The command to send (e.g., "play", "pause", "stop", "toggle", "next", "prev")

        Returns:
            The response of the Volumio API

        Raises:
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        self._log_debug(f"Sending the command {cmd}...")
        response = CommandResponse.from_raw(await self._get_json(self._command_path(cmd)))
        self._log_debug(f"Sending the command {cmd}... done")
        return response

    async def _status(self) -> str:
        """Return the playback status string from the current playback state.

        Returns:
            The playback status (e.g., "play", "pause", "stop")

        Raises:
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response, or the playback
                state does not contain a string status
        """
        return self._state_status(await self.get_state())

    async def add_to_queue(self, uri: str) -> CommandResponse:
        """Add the content of a URI to the end of the queue, without touching playback.

        The URI of a container of a source other than the local library is browsed
        first and queued as the items it lists, since only the local library explodes
        its containers by itself.

        Args:
            uri: The URI whose content to add, from a browse or a search

        Returns:
            The response of the Volumio API

        Raises:
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        self._log_debug(f'Adding "{uri}" to the queue...')
        items = await self._queue_payload_items(uri)
        payload: dict[str, Any] | list[dict[str, Any]] = (
            items if items is not None else self._queue_uri_item(uri)
        )
        response = CommandResponse.from_raw(
            await self._post_json(PATH_ADD_TO_QUEUE, payload, self.timeout_slow_endpoints)
        )
        self._log_debug(f'Adding "{uri}" to the queue... done')
        return response

    async def browse(self, uri: str | None = None, offset: int | None = None) -> BrowseResults:
        """Browse the content the Volumio instance lists at a URI.

        The URIs to descend into come from the answers themselves, and from the search
        results; the Volumio API wants ``/`` for the root, which stands in when no URI
        is given.

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
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        path, label = self._browse_request(uri, offset)
        self._log_debug(f"Browsing {label}...")
        results = BrowseResults.from_envelope(await self._get_json(path))
        self._log_debug(f"Browsing {label}... done")
        return results

    async def clear(self) -> CommandResponse:
        """Clear the playback queue.

        Returns:
            The response of the Volumio API

        Raises:
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return await self._send_command("clearQueue")

    async def close(self) -> None:
        """Close the session the client sends its requests through.

        Closing is idempotent, and leaves the client usable: a later request opens a
        fresh session. Calling it (or leaving an ``async with`` block, which calls it)
        is what keeps ``aiohttp`` from reporting an unclosed session later on.
        """
        if self._session is not None:
            self._log_debug("Closing the HTTP session...")
            await self._session.close()
            self._session = None
            self._log_debug("Closing the HTTP session... done")

    async def decrease_volume(self) -> CommandResponse:
        """Decrease the playback volume by one step.

        The decrement is the one defined in the settings of the Volumio host.

        Returns:
            The response of the Volumio API

        Raises:
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return await self._send_command("volume&volume=minus")

    async def get_album_credits(self, artist: Artist | None, album: Album) -> Story:
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
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioStoryError: If the Volumio host reports a failed query
            VolumioAPIError: If the API returns an error or a non-object response
        """
        payload = self._album_credits_payload(artist, album)
        envelope = await self._plugin_endpoint("metavolumio", payload)
        return Story.from_envelope(envelope)

    async def get_collection_statistics(self) -> CollectionStatistics:
        """Get the statistics of the music collection of the Volumio instance.

        Returns:
            The statistics of the music collection

        Raises:
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return CollectionStatistics.from_raw(await self._get_json(PATH_COLLECTION_STATISTICS))

    async def get_notifications(self) -> Notifications:
        """Get the URLs registered to receive the push notifications of the instance.

        Returns:
            The registered notification URLs

        Raises:
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return Notifications.from_urls(await self._get_json_list(PATH_PUSH_NOTIFICATION_URLS))

    async def get_playlists(self) -> Playlists:
        """Get the playlists saved on the Volumio instance.

        Returns:
            The saved playlists

        Raises:
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return Playlists.from_names(await self._get_json_list(PATH_LIST_PLAYLISTS))

    async def get_queue(self) -> Queue:
        """Get the current playback queue of the Volumio instance.

        Returns:
            The current playback queue

        Raises:
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return Queue.from_raw(await self._get_json(PATH_GET_QUEUE))

    async def get_queue_status(self) -> dict[str, Any]:
        """Get the navigation state of the queue, as a small mapping.

        The keys are ``has_next`` and ``has_previous`` (whether the current track
        has a neighbor in the queue), ``length`` (the number of queued tracks),
        ``position`` (the 0-based index of the current track, None without one),
        and ``track`` (the playback state payload, as the Volumio host returned
        it). Two requests are performed, reading the playback state and the queue.

        Returns:
            The navigation state of the queue

        Raises:
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        state = await self.get_state()
        count = len(await self.get_queue())
        return self._queue_status(state, count)

    async def get_seek(self) -> int:
        """Get the seek position, in seconds, in the track currently playing.

        The position is read from the current playback state, rounding the
        milliseconds reported there down to whole seconds.

        See :meth:`set_seek` for seeking to an absolute position, and
        :meth:`seek_backward` and :meth:`seek_forward` for relative seeking.

        Returns:
            The current seek position, in seconds

        Raises:
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response, or the playback
                state does not contain an integer seek position
        """
        return self._state_seek(await self.get_state())

    async def get_state(self) -> PlayerState:
        """Get the current playback state of the Volumio instance.

        Returns:
            The current playback state of the Volumio instance

        Raises:
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return PlayerState.from_raw(await self._get_json(PATH_GET_STATE))

    async def get_story(
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
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioStoryError: If the Volumio host reports a failed query
            VolumioAPIError: If the API returns an error or a non-object response
        """
        payload = self._story_payload(album, artist, label, place)
        envelope = await self._plugin_endpoint("metavolumio", payload)
        return Story.from_envelope(envelope)

    async def get_system_info(self) -> SystemInfo:
        """Get the system information of the Volumio instance.

        Returns:
            The system information of the Volumio instance

        Raises:
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return SystemInfo.from_raw(await self._get_json(PATH_GET_SYSTEM_INFO))

    async def get_system_version(self) -> SystemVersion:
        """Get the system version of the Volumio instance.

        Returns:
            The system version of the Volumio instance

        Raises:
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return SystemVersion.from_raw(await self._get_json(PATH_GET_SYSTEM_VERSION))

    async def get_volume(self) -> int:
        """Get the playback volume level of the Volumio instance.

        See :meth:`set_volume` for setting the level, :meth:`decrease_volume` and
        :meth:`increase_volume` for stepping it, and :meth:`mute` and :meth:`unmute`
        for muting and unmuting it.

        Returns:
            The volume level, an integer between 0 and 100 (inclusive)

        Raises:
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response, or the playback
                state does not contain an integer volume level
        """
        return self._state_volume(await self.get_state())

    async def get_zones(self) -> Zones:
        """Get the multiroom zones seen by the Volumio instance.

        Returns:
            The multiroom zones seen by the Volumio instance

        Raises:
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return Zones.from_raw(await self._get_json(PATH_GET_ZONES))

    async def has_next(self) -> bool:
        """Whether the current track has a next track in the queue.

        True if and only if a current position exists and it is not the last of the
        queue; without a current track, or with an empty queue, there is no next
        track. Two requests are performed, reading the playback state and the queue.

        Returns:
            True if the queue holds a track after the current one, False otherwise

        Raises:
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return bool((await self.get_queue_status())["has_next"])

    async def has_previous(self) -> bool:
        """Whether the current track has a previous track in the queue.

        True if and only if a current position exists and it is not the first of the
        queue; without a current track, or with an empty queue, there is no previous
        track. Two requests are performed, reading the playback state and the queue.

        Returns:
            True if the queue holds a track before the current one, False otherwise

        Raises:
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return bool((await self.get_queue_status())["has_previous"])

    async def increase_volume(self) -> CommandResponse:
        """Increase the playback volume by one step.

        The increment is the one defined in the settings of the Volumio host.

        Returns:
            The response of the Volumio API

        Raises:
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return await self._send_command("volume&volume=plus")

    async def is_muted(self) -> bool:
        """Whether the playback volume of the Volumio instance is muted.

        See :meth:`mute` and :meth:`unmute` for muting and unmuting the volume.

        Returns:
            True if the volume is muted, False otherwise

        Raises:
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response, or the playback
                state does not contain a boolean mute flag
        """
        return self._state_mute(await self.get_state())

    async def is_paused(self) -> bool:
        """Whether the playback of the Volumio instance is paused.

        True if and only if the playback status is "pause".

        See :meth:`pause` for pausing the playback.

        Returns:
            True if the playback status is "pause", False otherwise

        Raises:
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response, or the playback
                state does not contain a string status
        """
        return await self._status() == "pause"

    async def is_playing(self) -> bool:
        """Whether the Volumio instance is playing.

        True if and only if the playback status is "play".

        See :meth:`play` for starting the playback.

        Returns:
            True if the playback status is "play", False otherwise

        Raises:
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response, or the playback
                state does not contain a string status
        """
        return await self._status() == "play"

    async def is_stopped(self) -> bool:
        """Whether the playback of the Volumio instance is stopped.

        True if and only if the playback status is "stop".

        See :meth:`stop` for stopping the playback.

        Returns:
            True if the playback status is "stop", False otherwise

        Raises:
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response, or the playback
                state does not contain a string status
        """
        return await self._status() == "stop"

    async def mute(self) -> CommandResponse:
        """Mute the playback volume.

        Returns:
            The response of the Volumio API

        Raises:
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return await self._send_command("volume&volume=mute")

    async def next(self) -> CommandResponse:
        """Skip to the next track.

        Returns:
            The response of the Volumio API

        Raises:
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return await self._send_command("next")

    async def pause(self) -> CommandResponse:
        """Pause playback.

        Returns:
            The response of the Volumio API

        Raises:
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return await self._send_command("pause")

    async def ping(self) -> str:
        """Ping the Volumio instance to check that it is reachable.

        Returns:
            The response body text (``"pong"`` from a healthy Volumio instance)

        Raises:
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return await self._get_text(PATH_PING)

    async def play(self, position: int | QueueTrack | None = None) -> CommandResponse:
        """Start playback.

        The track to play can be given by its position in the queue, or as a track of
        the queue itself (e.g., ``await client.play((await client.get_queue())[3])``).

        Args:
            position: Optional position in the queue to play (0-indexed), or a track
                of the queue

        Returns:
            The response of the Volumio API

        Raises:
            ValueError: If the given track does not know its position in the queue
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return await self._send_command(self._play_command(position))

    async def play_playlist(self, name: str | Playlist) -> CommandResponse:
        """Start playback of a saved playlist.

        The playlist can be given by name, or as one of the saved playlists (e.g.,
        ``await client.play_playlist((await client.get_playlists())[0])``).

        Args:
            name: The name of the playlist to play, or the playlist itself

        Returns:
            The response of the Volumio API

        Raises:
            ValueError: If the given playlist has no name
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return await self._send_command(self._playlist_command(name))

    async def previous(self) -> CommandResponse:
        """Skip to the previous track.

        Returns:
            The response of the Volumio API

        Raises:
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return await self._send_command("prev")

    async def randomize(self, value: bool | None = None) -> CommandResponse:
        """Set or toggle the random (shuffle) mode.

        Args:
            value: True to enable, False to disable, or None (the default) to let
                the Volumio API toggle the current random mode

        Returns:
            The response of the Volumio API

        Raises:
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return await self._send_command(self._mode_command("random", value))

    async def register_notification(self, url: str | Notification) -> SuccessResponse:
        """Register a URL to receive the push notifications of the Volumio instance.

        The URL can be given as a string, or as one of the registered notifications.

        Args:
            url: The URL to register, or the notification holding it

        Returns:
            The response of the Volumio API

        Raises:
            ValueError: If the given notification has no URL
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        payload = {"url": self._notification_url(url)}
        return SuccessResponse.from_raw(
            await self._post_json(PATH_PUSH_NOTIFICATION_URLS, payload)
        )

    async def repeat(self, value: bool | None = None) -> CommandResponse:
        """Set or toggle the repeat mode.

        Args:
            value: True to enable, False to disable, or None (the default) to let
                the Volumio API toggle the current repeat mode

        Returns:
            The response of the Volumio API

        Raises:
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return await self._send_command(self._mode_command("repeat", value))

    async def replace_queue_and_play(
        self, uri: str, index: int | None = None
    ) -> CommandResponse:
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
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response, or if the URI
                does not list enough items to play the asked one
        """
        self._check_play_index(index)
        self._log_debug(f'Replacing the queue with "{uri}"...')
        if index is not None:
            items = [self._slim_queue_item(item.raw) for item in (await self.browse(uri)).items]
            if len(items) > index:
                self._log_debug(f"Sending the {len(items)} listed items, playing index {index}")
                response = CommandResponse.from_raw(
                    await self._post_json(
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
            listed = await self._queue_payload_items(uri)
            if listed is not None:
                self._log_debug(f"Sending the {len(listed)} listed items, playing the first")
                response = CommandResponse.from_raw(
                    await self._post_json(
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
            await self._post_json(
                PATH_REPLACE_AND_PLAY, {"item": item}, self.timeout_slow_endpoints
            )
        )
        self._log_debug(f'Replacing the queue with "{uri}"... done')
        return response

    async def search(self, query: str) -> SearchResults:
        """Search the sources of the Volumio instance.

        The Volumio API takes the query only: the results it groups by source and by
        kind can be narrowed with :meth:`SearchResults.filtered`.

        Args:
            query: The text to search for

        Returns:
            The results of the search

        Raises:
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return SearchResults.from_envelope(await self._get_json(self._search_path(query)))

    async def seek_backward(self) -> CommandResponse:
        """Seek backward by 10 seconds in the track currently playing.

        Returns:
            The response of the Volumio API

        Raises:
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return await self._send_command("seek&position=minus")

    async def seek_forward(self) -> CommandResponse:
        """Seek forward by 10 seconds in the track currently playing.

        Returns:
            The response of the Volumio API

        Raises:
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return await self._send_command("seek&position=plus")

    async def set_seek(self, value: int) -> CommandResponse:
        """Seek to an absolute position in the track currently playing.

        See :meth:`get_seek` for reading the current position, and
        :meth:`seek_backward` and :meth:`seek_forward` for relative seeking.

        Args:
            value: The position to seek to, in seconds

        Returns:
            The response of the Volumio API

        Raises:
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return await self._send_command(self._seek_command(value))

    async def set_volume(self, value: int) -> CommandResponse:
        """Set the playback volume to an absolute level.

        See :meth:`get_volume` for reading the level, :meth:`decrease_volume` and
        :meth:`increase_volume` for stepping it, and :meth:`mute` and :meth:`unmute`
        for muting and unmuting it.

        Args:
            value: The volume level, an integer between 0 and 100 (inclusive)

        Returns:
            The response of the Volumio API

        Raises:
            ValueError: If the volume level is out of range
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return await self._send_command(self._volume_command(value))

    async def stop(self) -> CommandResponse:
        """Stop playback.

        Returns:
            The response of the Volumio API

        Raises:
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return await self._send_command("stop")

    async def toggle(self) -> CommandResponse:
        """Toggle between play and pause states.

        Returns:
            The response of the Volumio API

        Raises:
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return await self._send_command("toggle")

    async def unmute(self) -> CommandResponse:
        """Unmute the playback volume.

        Returns:
            The response of the Volumio API

        Raises:
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return await self._send_command("volume&volume=unmute")

    async def unregister_notification(self, url: str | Notification) -> SuccessResponse:
        """Stop pushing the notifications of the Volumio instance to a URL.

        The URL can be given as a string, or as one of the registered notifications.

        The URL travels in the request body: the Volumio API documents a ``?url=``
        query string instead, but a Volumio 4 host answers that form with an error.

        Args:
            url: The URL to unregister, or the notification holding it

        Returns:
            The response of the Volumio API

        Raises:
            ValueError: If the given notification has no URL
            VolumioAsyncError: If the aiohttp package is not installed
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        payload = {"url": self._notification_url(url)}
        return SuccessResponse.from_raw(
            await self._delete_json(PATH_PUSH_NOTIFICATION_URLS, payload)
        )

    async def __aenter__(self) -> Self:
        """Open the session of the client, entering an ``async with`` block.

        Returns:
            The client itself

        Raises:
            VolumioAsyncError: If the aiohttp package is not installed
        """
        self._ensure_session()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Close the session of the client, leaving an ``async with`` block.

        Args:
            exc_type: The class of the exception leaving the block, when one does
            exc_val: The exception leaving the block, when one does
            exc_tb: The traceback of the exception leaving the block, when one does
        """
        await self.close()
