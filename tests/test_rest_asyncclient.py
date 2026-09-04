"""Tests for the async REST API client.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

import json
import logging
import sys
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import Mock

import pytest
from pytest_mock import MockerFixture

# The async client needs the optional "async" extra: without it, this whole module
# has nothing to say
aiohttp = pytest.importorskip("aiohttp")
pytest.importorskip("pytest_asyncio")

import yarl  # noqa: E402
from multidict import CIMultiDict  # noqa: E402

from volumito.clients.entities import Album, Artist, Label, Place  # noqa: E402
from volumito.clients.host_configuration import VolumioHostConfiguration  # noqa: E402
from volumito.clients.models import (  # noqa: E402
    Notification,
    Playlist,
    Queue,
    QueueTrack,
)
from volumito.clients.rest import (  # noqa: E402
    VolumioAPIError,
    VolumioAsyncError,
    VolumioAsyncRESTAPIClient,
    VolumioConnectionError,
)
from volumito.clients.rest.asyncclient import _load_aiohttp  # noqa: E402

BASE = "http://volumio.local:3000"

STATE_PAYLOAD = {
    "status": "play",
    "position": 1,
    "title": "Test Song",
    "artist": "Test Artist",
    "album": "Test Album",
    "volume": 42,
    "mute": False,
    "seek": 102000,
    "service": "mpd",
}

QUEUE_PAYLOAD = {
    "queue": [
        {"title": "Song 1", "artist": "Artist 1", "service": "qobuz"},
        {"title": "Song 2", "artist": "Artist 2", "service": "qobuz"},
        {"title": "Song 3", "artist": "Artist 3", "service": "qobuz"},
    ]
}

STORY_PAYLOAD = {"success": True, "data": {"type": "story", "value": "A story."}}


@dataclass
class _Call:
    """One request the fake session was asked to perform."""

    method: str
    url: str
    kwargs: dict[str, Any] = field(default_factory=dict)


class _FakeResponse:
    """An aiohttp-shaped response: a status, a body read by awaiting text()."""

    def __init__(self, body: str = "", status: int = 200, error: BaseException | None = None):
        self.status = status
        self._body = body
        self._error = error

    def raise_for_status(self):
        if self._error is not None:
            raise self._error

    async def text(self):
        return self._body


class _FakeRequestContext:
    """The async context manager aiohttp returns from session.request()."""

    def __init__(self, response=None, error: BaseException | None = None):
        self._response = response
        self._error = error

    async def __aenter__(self):
        if self._error is not None:
            raise self._error
        return self._response

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return False


class _FakeSession:
    """A stand-in for aiohttp.ClientSession, recording what it was asked to send.

    The outcome is a response, an exception to raise instead, a list of those
    consumed in order, or a callable dispatching on the method and the URL.
    """

    def __init__(self, outcome):
        self._outcome = outcome
        self.calls: list[_Call] = []
        self.closed = False

    def request(self, method, url, **kwargs):
        self.calls.append(_Call(method, url, kwargs))
        outcome = self._outcome
        if callable(outcome) and not isinstance(outcome, BaseException):
            outcome = outcome(method, url)
        elif isinstance(outcome, list):
            outcome = outcome.pop(0)
        if isinstance(outcome, BaseException):
            return _FakeRequestContext(error=outcome)
        return _FakeRequestContext(response=outcome)

    async def close(self):
        self.closed = True


def _json_response(payload, status: int = 200) -> _FakeResponse:
    """Build a response carrying a JSON body."""
    return _FakeResponse(body=json.dumps(payload), status=status)


def _http_error_response(status: int = 500, message: str = "Server Error") -> _FakeResponse:
    """Build a response whose raise_for_status() reports an HTTP error."""
    url = yarl.URL(f"{BASE}/")
    info = aiohttp.RequestInfo(url=url, method="GET", headers=CIMultiDict(), real_url=url)
    error = aiohttp.ClientResponseError(info, (), status=status, message=message)
    return _FakeResponse(status=status, error=error)


def _client(mocker: MockerFixture, outcome, logger=None, **kwargs):
    """Build a client whose session is a fake yielding the given outcome."""
    session = _FakeSession(outcome)
    mocker.patch("aiohttp.ClientSession", return_value=session)
    client = VolumioAsyncRESTAPIClient(VolumioHostConfiguration(), logger=logger, **kwargs)
    return client, session


def _state_client(mocker: MockerFixture, payload=None, logger=None):
    """Build a client answering every request with a playback state."""
    return _client(mocker, _json_response(payload or STATE_PAYLOAD), logger=logger)


class TestVolumioAsyncRESTAPIClientLifecycle:
    """The session the async client owns, and the optional dependency it needs."""

    def test_init_default_logger(self):
        """Without a logger, the client logs under its own name in the volumito hierarchy."""
        client = VolumioAsyncRESTAPIClient(VolumioHostConfiguration())

        assert client.logger.name == "volumito.clients.rest.asyncclient"

    def test_init_custom_logger(self):
        """A passed logger is stored as given."""
        logger = logging.getLogger("test.rest.async.custom")

        client = VolumioAsyncRESTAPIClient(VolumioHostConfiguration(), logger=logger)

        assert client.logger is logger

    def test_init_keeps_the_timeouts(self):
        """The timeouts are stored as given, by keyword like the sync client."""
        client = VolumioAsyncRESTAPIClient(
            VolumioHostConfiguration(), timeout=1.5, timeout_slow_endpoints=30.0
        )

        assert client.timeout == 1.5
        assert client.timeout_slow_endpoints == 30.0

    def test_init_opens_no_session(self, mocker: MockerFixture):
        """The client is built without a running loop: no session is opened here."""
        opened = mocker.patch("aiohttp.ClientSession")

        client = VolumioAsyncRESTAPIClient(VolumioHostConfiguration())

        opened.assert_not_called()
        assert client._session is None

    async def test_the_session_is_opened_once_and_reused(self, mocker: MockerFixture):
        """The session opens on the first request and serves the following ones."""
        session = _FakeSession(_json_response(STATE_PAYLOAD))
        opened = mocker.patch("aiohttp.ClientSession", return_value=session)
        client = VolumioAsyncRESTAPIClient(VolumioHostConfiguration())

        await client.get_state()
        await client.get_state()

        opened.assert_called_once_with()
        assert len(session.calls) == 2

    async def test_close_closes_and_clears_the_session(self, mocker: MockerFixture):
        """Closing the client closes the session it owns and forgets it."""
        client, session = _state_client(mocker)
        await client.get_state()

        await client.close()

        assert session.closed is True
        assert client._session is None

    async def test_close_without_a_session_is_a_no_op(self, mocker: MockerFixture):
        """Closing a client that never sent a request opens nothing."""
        opened = mocker.patch("aiohttp.ClientSession")
        client = VolumioAsyncRESTAPIClient(VolumioHostConfiguration())

        await client.close()

        opened.assert_not_called()

    async def test_close_twice_is_a_no_op(self, mocker: MockerFixture):
        """Closing an already closed client does nothing the second time."""
        client, session = _state_client(mocker)
        await client.get_state()

        await client.close()
        await client.close()

        assert client._session is None

    async def test_an_injected_session_is_used_and_kept(self, mocker: MockerFixture):
        """A session given to the constructor serves the requests, and close() leaves it."""
        opened = mocker.patch("aiohttp.ClientSession")
        session = _FakeSession(_json_response(STATE_PAYLOAD))
        client = VolumioAsyncRESTAPIClient(VolumioHostConfiguration(), session=session)

        await client.get_state()
        await client.close()
        await client.get_state()

        opened.assert_not_called()
        assert session.closed is False
        assert len(session.calls) == 2
        assert client._session is session

    async def test_the_client_is_reusable_after_close(self, mocker: MockerFixture):
        """A request after a close opens a fresh session."""
        session = _FakeSession(_json_response(STATE_PAYLOAD))
        opened = mocker.patch("aiohttp.ClientSession", return_value=session)
        client = VolumioAsyncRESTAPIClient(VolumioHostConfiguration())

        await client.get_state()
        await client.close()
        await client.get_state()

        assert opened.call_count == 2

    async def test_async_context_manager_opens_and_closes(self, mocker: MockerFixture):
        """Entering the block opens the session, leaving it closes it."""
        session = _FakeSession(_json_response(STATE_PAYLOAD))
        mocker.patch("aiohttp.ClientSession", return_value=session)

        async with VolumioAsyncRESTAPIClient(VolumioHostConfiguration()) as client:
            assert client._session is session
            await client.get_state()

        assert session.closed is True
        assert client._session is None

    async def test_async_context_manager_closes_on_error(self, mocker: MockerFixture):
        """An exception leaving the block still closes the session."""
        session = _FakeSession(_json_response(STATE_PAYLOAD))
        mocker.patch("aiohttp.ClientSession", return_value=session)

        with pytest.raises(RuntimeError):
            async with VolumioAsyncRESTAPIClient(VolumioHostConfiguration()):
                raise RuntimeError("boom")

        assert session.closed is True

    async def test_the_session_lifecycle_logs_its_steps(self, mocker: MockerFixture):
        """Opening and closing the session leave their begin/end pairs at debug."""
        logger = Mock()
        client, _ = _state_client(mocker, logger=logger)

        await client.get_state()
        await client.close()

        debugged = [call.args[0] for call in logger.debug.call_args_list]
        assert "Opening the HTTP session..." in debugged
        assert "Opening the HTTP session... done" in debugged
        assert "Closing the HTTP session..." in debugged
        assert "Closing the HTTP session... done" in debugged
        logger.info.assert_not_called()

    def test_load_aiohttp_returns_the_module(self):
        """With the package installed, the loader hands the module over."""
        assert _load_aiohttp() is aiohttp

    def test_load_aiohttp_without_the_package(self, mocker: MockerFixture):
        """Without the package, the loader names the extra that provides it."""
        mocker.patch.dict(sys.modules, {"aiohttp": None})

        with pytest.raises(VolumioAsyncError) as excinfo:
            _load_aiohttp()

        assert "needs the aiohttp package" in str(excinfo.value)
        assert "pip install volumito[async]" in str(excinfo.value)

    async def test_a_request_without_the_package_is_refused(self, mocker: MockerFixture):
        """A request made without aiohttp fails before anything is sent."""
        client = VolumioAsyncRESTAPIClient(VolumioHostConfiguration())
        mocker.patch.dict(sys.modules, {"aiohttp": None})

        with pytest.raises(VolumioAsyncError):
            await client.get_state()

    def test_the_package_is_imported_lazily(self):
        """Importing volumito never imports aiohttp itself: the extra stays optional."""
        import volumito.clients.rest.asyncclient as module

        source = module.__doc__ or ""
        assert "pip install volumito[async]" in source


class TestVolumioAsyncRESTAPIClientTransport:
    """The funnel every request travels through, and the failures it translates."""

    async def test_a_get_sends_the_verb_the_url_and_the_timeout(self, mocker: MockerFixture):
        """A read reaches the endpoint as a GET carrying the default timeout."""
        client, session = _state_client(mocker)

        await client.get_state()

        assert session.calls[0].method == "GET"
        assert session.calls[0].url == f"{BASE}/api/v1/getState"
        assert session.calls[0].kwargs["timeout"] == aiohttp.ClientTimeout(total=5.0)
        assert "json" not in session.calls[0].kwargs

    async def test_a_post_sends_the_json_payload(self, mocker: MockerFixture):
        """A write reaches the endpoint as a POST carrying its JSON body."""
        client, session = _client(mocker, _json_response({"success": True}))

        await client.register_notification("http://192.168.1.100/receiver")

        assert session.calls[0].method == "POST"
        assert session.calls[0].url == f"{BASE}/api/v1/pushNotificationUrls"
        assert session.calls[0].kwargs["json"] == {"url": "http://192.168.1.100/receiver"}

    async def test_a_delete_sends_the_url_in_the_body(self, mocker: MockerFixture):
        """Unregistering sends the URL in the body, not in the query string."""
        client, session = _client(mocker, _json_response({"success": True}))

        await client.unregister_notification("http://192.168.1.100/receiver")

        assert session.calls[0].method == "DELETE"
        assert session.calls[0].url == f"{BASE}/api/v1/pushNotificationUrls"
        assert session.calls[0].kwargs["json"] == {"url": "http://192.168.1.100/receiver"}

    async def test_an_empty_delete_body_reads_as_an_empty_object(self, mocker: MockerFixture):
        """The Volumio API answers some DELETE requests with nothing at all."""
        client, _ = _client(mocker, _FakeResponse(body="   "))

        response = await client.unregister_notification("http://192.168.1.100/receiver")

        assert response.raw == {}

    async def test_the_slow_timeout_serves_the_slow_endpoints(self, mocker: MockerFixture):
        """Replacing the queue waits on the slow-endpoint budget, not the default one."""
        client, session = _client(mocker, _json_response({"response": "success"}))

        await client.replace_queue_and_play("mpd://track.flac")

        assert session.calls[-1].kwargs["timeout"] == aiohttp.ClientTimeout(total=60.0)

    async def test_a_custom_timeout_is_honored(self, mocker: MockerFixture):
        """The timeouts given to the constructor reach the requests."""
        client, session = _client(mocker, _json_response(STATE_PAYLOAD), timeout=1.5)

        await client.get_state()

        assert session.calls[0].kwargs["timeout"] == aiohttp.ClientTimeout(total=1.5)

    @pytest.mark.parametrize(
        ("error", "expected", "detail"),
        [
            (TimeoutError("slow"), VolumioConnectionError, "did not answer within"),
            (
                aiohttp.ClientConnectionError("down"),
                VolumioConnectionError,
                "Cannot connect",
            ),
            (
                aiohttp.ClientError("odd"),
                VolumioConnectionError,
                "request to the Volumio API failed",
            ),
        ],
    )
    async def test_a_transport_failure_logs_a_warning(
        self, mocker: MockerFixture, error, expected, detail
    ):
        """Each anticipated transport failure warns once and still raises."""
        logger = Mock()
        client, _ = _client(mocker, error, logger=logger)

        with pytest.raises(expected):
            await client.get_state()

        logger.warning.assert_called_once()
        assert detail in logger.warning.call_args.args[0]

    @pytest.mark.parametrize(
        ("error", "message"),
        [
            (TimeoutError("slow"), "timed out after 5.0 seconds"),
            (aiohttp.ClientConnectionError("down"), "Failed to connect to Volumio instance"),
            (aiohttp.ClientError("odd"), "Request to Volumio instance"),
        ],
    )
    async def test_a_transport_failure_names_the_host(
        self, mocker: MockerFixture, error, message
    ):
        """The raised error names the instance that could not be reached."""
        client, _ = _client(mocker, error)

        with pytest.raises(VolumioConnectionError) as excinfo:
            await client.get_state()

        assert message in str(excinfo.value)
        assert excinfo.value.__cause__ is error

    @pytest.mark.parametrize(
        "error",
        [
            aiohttp.ServerTimeoutError("slow"),
            aiohttp.SocketTimeoutError("slow"),
            aiohttp.ConnectionTimeoutError("slow"),
        ],
    )
    async def test_a_socket_timeout_is_read_as_a_timeout(self, mocker: MockerFixture, error):
        """These are connection errors too: catching them later would mislabel them."""
        client, _ = _client(mocker, error)

        with pytest.raises(VolumioConnectionError) as excinfo:
            await client.get_state()

        assert "timed out after" in str(excinfo.value)

    async def test_a_connector_failure_is_read_as_a_connection_error(
        self, mocker: MockerFixture
    ):
        """A connector failure that is no timeout stays a connection error."""
        connection = aiohttp.ClientConnectorError(Mock(ssl=None, host="volumio.local"), OSError())
        client, _ = _client(mocker, connection)

        with pytest.raises(VolumioConnectionError) as excinfo:
            await client.get_state()

        assert "Failed to connect" in str(excinfo.value)

    async def test_an_http_error_reports_its_status(self, mocker: MockerFixture):
        """The status of the answer travels into the raised error and the warning."""
        logger = Mock()
        client, _ = _client(mocker, _http_error_response(500), logger=logger)

        with pytest.raises(VolumioAPIError) as excinfo:
            await client.get_state()

        assert "HTTP error 500" in str(excinfo.value)
        assert "answered HTTP 500" in logger.warning.call_args.args[0]

    async def test_a_happy_request_logs_its_steps(self, mocker: MockerFixture):
        """A successful GET leaves the request pair and the status at debug, never info."""
        logger = Mock()
        client, _ = _state_client(mocker, logger=logger)

        await client.get_state()

        debugged = [call.args[0] for call in logger.debug.call_args_list]
        assert f"Requesting GET {BASE}/api/v1/getState..." in debugged
        assert f"Requesting GET {BASE}/api/v1/getState... done" in debugged
        assert "Response status: 200" in debugged
        logger.info.assert_not_called()
        logger.warning.assert_not_called()

    async def test_a_payload_is_logged(self, mocker: MockerFixture):
        """The body of a request carrying one is logged at debug."""
        logger = Mock()
        client, _ = _client(mocker, _json_response({"success": True}), logger=logger)

        await client.register_notification("http://192.168.1.100/receiver")

        debugged = [call.args[0] for call in logger.debug.call_args_list]
        assert "Request payload: {'url': 'http://192.168.1.100/receiver'}" in debugged

    async def test_an_unparsable_answer_logs_a_warning(self, mocker: MockerFixture):
        """A body that is not JSON warns once and raises."""
        logger = Mock()
        client, _ = _client(mocker, _FakeResponse(body="not json"), logger=logger)

        with pytest.raises(VolumioAPIError) as excinfo:
            await client.get_state()

        assert "Failed to parse JSON response" in str(excinfo.value)
        logger.warning.assert_called_once()

    async def test_a_non_object_answer_is_refused(self, mocker: MockerFixture):
        """An endpoint answering an array where an object is due is reported."""
        client, _ = _client(mocker, _json_response([1, 2, 3]))

        with pytest.raises(VolumioAPIError) as excinfo:
            await client.get_state()

        assert "Expected JSON object" in str(excinfo.value)

    async def test_a_non_array_answer_is_refused(self, mocker: MockerFixture):
        """An endpoint answering an object where an array is due is reported."""
        client, _ = _client(mocker, _json_response({"nope": True}))

        with pytest.raises(VolumioAPIError) as excinfo:
            await client.get_playlists()

        assert "Expected JSON array" in str(excinfo.value)

    async def test_an_oversized_payload_is_refused(self, mocker: MockerFixture):
        """A body larger than the instance accepts never leaves the client."""
        client, session = _client(mocker, _json_response({"response": "success"}))
        item = {"service": "qobuz", "type": "song", "title": "x" * 500, "uri": "qobuz://1"}
        listing = {"navigation": {"lists": [{"items": [item] * 400}]}}
        client, session = _client(
            mocker,
            [_json_response(listing), _json_response({"response": "success"})],
        )

        with pytest.raises(VolumioAPIError) as excinfo:
            await client.add_to_queue("qobuz://album/123")

        assert "larger than the" in str(excinfo.value)
        assert len(session.calls) == 1


class TestVolumioAsyncRESTAPIClientReads:
    """The members reading something out of the Volumio instance."""

    async def test_ping(self, mocker: MockerFixture):
        """Ping returns the body text, which is no JSON at all."""
        client, session = _client(mocker, _FakeResponse(body="pong"))

        assert await client.ping() == "pong"
        assert session.calls[0].url == f"{BASE}/api/v1/ping"

    async def test_get_state(self, mocker: MockerFixture):
        """The playback state is parsed into its model, raw payload included."""
        client, session = _state_client(mocker)

        state = await client.get_state()

        assert session.calls[0].url == f"{BASE}/api/v1/getState"
        assert state.status == "play"
        assert state.title == "Test Song"
        assert state.raw["service"] == "mpd"

    async def test_get_queue(self, mocker: MockerFixture):
        """The queue is parsed into its model."""
        client, session = _client(mocker, _json_response(QUEUE_PAYLOAD))

        queue = await client.get_queue()

        assert session.calls[0].url == f"{BASE}/api/v1/getQueue"
        assert len(queue) == 3

    async def test_get_system_info(self, mocker: MockerFixture):
        """The system information is parsed into its model."""
        client, session = _client(mocker, _json_response({"name": "volumio", "id": "abc"}))

        info = await client.get_system_info()

        assert session.calls[0].url == f"{BASE}/api/v1/getSystemInfo"
        assert info.name == "volumio"

    async def test_get_system_version(self, mocker: MockerFixture):
        """The system version is parsed into its model."""
        client, session = _client(mocker, _json_response({"systemversion": "4.119"}))

        version = await client.get_system_version()

        assert session.calls[0].url == f"{BASE}/api/v1/getSystemVersion"
        assert version.system_version == "4.119"

    async def test_get_zones(self, mocker: MockerFixture):
        """The multiroom zones are parsed into their model."""
        payload = {"zones": [{"id": "abc", "host": "http://192.168.1.1", "name": "Volumio"}]}
        client, session = _client(mocker, _json_response(payload))

        zones = await client.get_zones()

        assert session.calls[0].url == f"{BASE}/api/v1/getzones"
        assert len(zones) == 1

    async def test_get_collection_statistics(self, mocker: MockerFixture):
        """The collection statistics are parsed into their model."""
        client, session = _client(mocker, _json_response({"artists": 3, "albums": 4}))

        statistics = await client.get_collection_statistics()

        assert session.calls[0].url == f"{BASE}/api/v1/collectionstats"
        assert statistics.artists == 3

    async def test_get_playlists(self, mocker: MockerFixture):
        """The saved playlists come as a JSON array of names."""
        client, session = _client(mocker, _json_response(["Rock", "Jazz"]))

        playlists = await client.get_playlists()

        assert session.calls[0].url == f"{BASE}/api/v1/listplaylists"
        assert [playlist.name for playlist in playlists] == ["Rock", "Jazz"]

    async def test_get_notifications(self, mocker: MockerFixture):
        """The registered notification URLs come as a JSON array."""
        client, session = _client(mocker, _json_response(["http://192.168.1.100/receiver"]))

        notifications = await client.get_notifications()

        assert session.calls[0].url == f"{BASE}/api/v1/pushNotificationUrls"
        assert len(notifications) == 1

    async def test_get_volume(self, mocker: MockerFixture):
        """The volume level is read out of the playback state."""
        client, _ = _state_client(mocker)

        assert await client.get_volume() == 42

    async def test_get_volume_without_a_level(self, mocker: MockerFixture):
        """A state carrying no integer level is reported."""
        client, _ = _state_client(mocker, payload={"status": "play"})

        with pytest.raises(VolumioAPIError) as excinfo:
            await client.get_volume()

        assert "Expected an integer volume level" in str(excinfo.value)

    async def test_get_seek(self, mocker: MockerFixture):
        """The seek position is read out of the state, in whole seconds."""
        client, _ = _state_client(mocker)

        assert await client.get_seek() == 102

    async def test_get_seek_without_a_position(self, mocker: MockerFixture):
        """A state carrying no integer position is reported."""
        client, _ = _state_client(mocker, payload={"status": "play"})

        with pytest.raises(VolumioAPIError) as excinfo:
            await client.get_seek()

        assert "Expected an integer seek position" in str(excinfo.value)

    async def test_is_muted(self, mocker: MockerFixture):
        """The mute flag is read out of the playback state."""
        client, _ = _state_client(mocker)

        assert await client.is_muted() is False

    async def test_is_muted_without_a_flag(self, mocker: MockerFixture):
        """A state carrying no boolean flag is reported."""
        client, _ = _state_client(mocker, payload={"status": "play"})

        with pytest.raises(VolumioAPIError) as excinfo:
            await client.is_muted()

        assert "Expected a boolean mute flag" in str(excinfo.value)

    @pytest.mark.parametrize(
        ("status", "playing", "paused", "stopped"),
        [
            ("play", True, False, False),
            ("pause", False, True, False),
            ("stop", False, False, True),
        ],
    )
    async def test_the_playback_predicates(
        self, mocker: MockerFixture, status, playing, paused, stopped
    ):
        """Each predicate answers off the status string of the playback state."""
        client, _ = _state_client(mocker, payload={"status": status})

        assert await client.is_playing() is playing
        assert await client.is_paused() is paused
        assert await client.is_stopped() is stopped

    async def test_a_state_without_a_status(self, mocker: MockerFixture):
        """A state carrying no string status is reported."""
        client, _ = _state_client(mocker, payload={"volume": 10})

        with pytest.raises(VolumioAPIError) as excinfo:
            await client.is_playing()

        assert "Expected a string status" in str(excinfo.value)

    async def test_get_queue_status(self, mocker: MockerFixture):
        """The navigation state reads the playback state and the queue, in that order."""

        def answer(method, url):
            if "getQueue" in url:
                return _json_response(QUEUE_PAYLOAD)
            return _json_response(STATE_PAYLOAD)

        client, session = _client(mocker, answer)

        status = await client.get_queue_status()

        assert [call.url for call in session.calls] == [
            f"{BASE}/api/v1/getState",
            f"{BASE}/api/v1/getQueue",
        ]
        assert status == {
            "has_next": True,
            "has_previous": True,
            "length": 3,
            "position": 1,
            "track": STATE_PAYLOAD,
        }

    @pytest.mark.parametrize(
        ("position", "count", "has_next", "has_previous"),
        [(1, 3, True, True), (0, 3, True, False), (2, 3, False, True), (None, 3, False, False)],
    )
    async def test_the_queue_neighbors(
        self, mocker: MockerFixture, position, count, has_next, has_previous
    ):
        """The neighbor flags follow the current position and the queue length."""
        state = dict(STATE_PAYLOAD)
        if position is None:
            del state["position"]
        else:
            state["position"] = position
        queue = {"queue": QUEUE_PAYLOAD["queue"][:count]}

        def answer(method, url):
            return _json_response(queue if "getQueue" in url else state)

        client, _ = _client(mocker, answer)

        assert await client.has_next() is has_next
        assert await client.has_previous() is has_previous

    async def test_browse_the_root(self, mocker: MockerFixture):
        """Without a URI the root is browsed."""
        payload = {"navigation": {"lists": [{"items": [{"title": "One"}]}]}}
        client, session = _client(mocker, _json_response(payload))

        results = await client.browse()

        assert session.calls[0].url == f"{BASE}/api/v1/browse?uri=/"
        assert len(results.items) == 1

    async def test_browse_a_uri_with_an_offset(self, mocker: MockerFixture):
        """The URI keeps its own escapes, and a non-zero offset travels along."""
        payload = {"navigation": {"lists": [{"items": []}]}}
        client, session = _client(mocker, _json_response(payload))

        await client.browse("artists://Paolo%20Conte", offset=20)

        assert (
            session.calls[0].url
            == f"{BASE}/api/v1/browse?uri=artists://Paolo%20Conte&offset=20"
        )

    async def test_browse_refuses_a_negative_offset(self, mocker: MockerFixture):
        """A negative offset is refused before anything is sent."""
        client, session = _client(mocker, _json_response({}))

        with pytest.raises(ValueError, match="0 or greater"):
            await client.browse("mpd://", offset=-1)

        assert session.calls == []

    async def test_search(self, mocker: MockerFixture):
        """The query is encoded into the query string."""
        payload = {"navigation": {"isSearchResult": True, "lists": []}}
        client, session = _client(mocker, _json_response(payload))

        await client.search("paolo conte")

        assert session.calls[0].url == f"{BASE}/api/v1/search?query=paolo%20conte"


class TestVolumioAsyncRESTAPIClientCommands:
    """The members telling the Volumio instance to do something."""

    @pytest.mark.parametrize(
        ("member", "cmd"),
        [
            ("clear", "clearQueue"),
            ("decrease_volume", "volume&volume=minus"),
            ("increase_volume", "volume&volume=plus"),
            ("mute", "volume&volume=mute"),
            ("next", "next"),
            ("pause", "pause"),
            ("previous", "prev"),
            ("seek_backward", "seek&position=minus"),
            ("seek_forward", "seek&position=plus"),
            ("stop", "stop"),
            ("toggle", "toggle"),
            ("unmute", "volume&volume=unmute"),
        ],
    )
    async def test_the_plain_commands(self, mocker: MockerFixture, member, cmd):
        """Each plain command reaches the commands endpoint with its own verb."""
        client, session = _client(mocker, _json_response({"response": "success"}))

        response = await getattr(client, member)()

        assert session.calls[0].url == f"{BASE}/api/v1/commands/?cmd={cmd}"
        assert response.response == "success"

    @pytest.mark.parametrize(
        ("position", "cmd"),
        [(None, "play"), (0, "play&N=0"), (3, "play&N=3")],
    )
    async def test_play(self, mocker: MockerFixture, position, cmd):
        """Playback starts at the queue position when one is given."""
        client, session = _client(mocker, _json_response({"response": "success"}))

        await client.play(position)

        assert session.calls[0].url == f"{BASE}/api/v1/commands/?cmd={cmd}"

    async def test_play_a_queue_track(self, mocker: MockerFixture):
        """A track of the queue plays at the position it knows."""
        client, session = _client(mocker, _json_response({"response": "success"}))

        await client.play(Queue.from_raw(QUEUE_PAYLOAD)[2])

        assert session.calls[0].url == f"{BASE}/api/v1/commands/?cmd=play&N=2"

    async def test_play_a_track_without_a_position(self, mocker: MockerFixture):
        """A track that belongs to no queue is refused before anything is sent."""
        client, session = _client(mocker, _json_response({"response": "success"}))

        with pytest.raises(ValueError, match="does not belong to a queue"):
            await client.play(QueueTrack.from_raw({"title": "Song"}))

        assert session.calls == []

    async def test_play_playlist_by_name(self, mocker: MockerFixture):
        """The playlist name is encoded into the command."""
        client, session = _client(mocker, _json_response({"response": "success"}))

        await client.play_playlist("My Rock")

        assert session.calls[0].url == f"{BASE}/api/v1/commands/?cmd=playplaylist&name=My%20Rock"

    async def test_play_playlist_by_model(self, mocker: MockerFixture):
        """A saved playlist plays by the name it holds."""
        client, session = _client(mocker, _json_response({"response": "success"}))

        await client.play_playlist(Playlist.from_name("Jazz"))

        assert session.calls[0].url == f"{BASE}/api/v1/commands/?cmd=playplaylist&name=Jazz"

    @pytest.mark.parametrize(
        ("member", "mode"),
        [("randomize", "random"), ("repeat", "repeat")],
    )
    @pytest.mark.parametrize(
        ("value", "suffix"),
        [(None, ""), (True, "&value=true"), (False, "&value=false")],
    )
    async def test_the_playback_modes(
        self, mocker: MockerFixture, member, mode, value, suffix
    ):
        """Each mode is set to a value, or toggled when none is given."""
        client, session = _client(mocker, _json_response({"response": "success"}))

        await getattr(client, member)(value)

        assert session.calls[0].url == f"{BASE}/api/v1/commands/?cmd={mode}{suffix}"

    async def test_set_seek(self, mocker: MockerFixture):
        """Seeking to an absolute position answers with the parsed response."""
        client, session = _client(mocker, _json_response({"response": "success"}))

        response = await client.set_seek(102)

        assert session.calls[0].url == f"{BASE}/api/v1/commands/?cmd=seek&position=102"
        assert response.response == "success"

    async def test_set_volume(self, mocker: MockerFixture):
        """Setting the volume answers with the parsed response."""
        client, session = _client(mocker, _json_response({"response": "success"}))

        response = await client.set_volume(50)

        assert session.calls[0].url == f"{BASE}/api/v1/commands/?cmd=volume&volume=50"
        assert response.response == "success"

    @pytest.mark.parametrize("value", [-1, 101])
    async def test_set_volume_out_of_range(self, mocker: MockerFixture, value):
        """An out-of-range level is refused before anything is sent."""
        client, session = _client(mocker, _json_response({"response": "success"}))

        with pytest.raises(ValueError, match="between 0 and 100"):
            await client.set_volume(value)

        assert session.calls == []

    async def test_register_notification_from_a_model(self, mocker: MockerFixture):
        """A notification model registers by the URL it holds."""
        client, session = _client(mocker, _json_response({"success": True}))

        await client.register_notification(
            Notification.from_url("http://192.168.1.100/receiver")
        )

        assert session.calls[0].kwargs["json"] == {"url": "http://192.168.1.100/receiver"}

    async def test_unregister_a_notification_without_a_url(self, mocker: MockerFixture):
        """Unregistering a notification holding no URL is refused too."""
        client, session = _client(mocker, _json_response({"success": True}))

        with pytest.raises(ValueError, match="no URL"):
            await client.unregister_notification(Notification())

        assert session.calls == []

    async def test_register_a_notification_without_a_url(self, mocker: MockerFixture):
        """A notification holding no URL is refused before anything is sent."""
        client, session = _client(mocker, _json_response({"success": True}))

        with pytest.raises(ValueError, match="no URL"):
            await client.register_notification(Notification())

        assert session.calls == []


class TestVolumioAsyncRESTAPIClientQueueing:
    """The members that browse a URI before queueing what it lists."""

    async def test_add_a_local_uri(self, mocker: MockerFixture):
        """A local library URI is queued as itself, without a browse."""
        client, session = _client(mocker, _json_response({"response": "success"}))

        await client.add_to_queue("mpd://NAS/music/track.flac")

        assert len(session.calls) == 1
        assert session.calls[0].url == f"{BASE}/api/v1/addToQueue"
        assert session.calls[0].kwargs["json"] == {
            "service": "mpd",
            "uri": "mpd://NAS/music/track.flac",
        }

    async def test_add_a_container_of_another_source(self, mocker: MockerFixture):
        """A non-local container is browsed and queued as the items it lists."""
        item = {"service": "qobuz", "type": "song", "title": "One", "uri": "qobuz://song/1"}
        listing = {"navigation": {"lists": [{"items": [item]}]}}
        client, session = _client(
            mocker, [_json_response(listing), _json_response({"response": "success"})]
        )

        await client.add_to_queue("qobuz://album/123")

        assert len(session.calls) == 2
        assert session.calls[1].kwargs["json"] == [item]

    async def test_add_a_uri_listing_nothing(self, mocker: MockerFixture):
        """A URI that lists nothing is queued as itself."""
        listing = {"navigation": {"lists": [{"items": []}]}}
        client, session = _client(
            mocker, [_json_response(listing), _json_response({"response": "success"})]
        )

        await client.add_to_queue("qobuz://song/1")

        assert session.calls[1].kwargs["json"] == {"service": "qobuz", "uri": "qobuz://song/1"}

    async def test_adding_a_container_logs_the_decision(self, mocker: MockerFixture):
        """Queueing a non-local container logs the browse-to-queue path taken."""
        item = {"service": "qobuz", "type": "song", "title": "One", "uri": "qobuz://song/1"}
        listing = {"navigation": {"lists": [{"items": [item]}]}}
        logger = Mock()
        client, _ = _client(
            mocker,
            [_json_response(listing), _json_response({"response": "success"})],
            logger=logger,
        )

        await client.add_to_queue("qobuz://album/123")

        debugged = [call.args[0] for call in logger.debug.call_args_list]
        assert 'Service of "qobuz://album/123": qobuz' in debugged
        assert "Browsing the URI to queue the items it lists... done (1 items)" in debugged

    async def test_replace_with_a_local_uri(self, mocker: MockerFixture):
        """A local URI is sent as a single item, playing its first element."""
        client, session = _client(mocker, _json_response({"response": "success"}))

        await client.replace_queue_and_play("mpd://NAS/music/track.flac")

        assert len(session.calls) == 1
        assert session.calls[0].url == f"{BASE}/api/v1/replaceAndPlay"
        assert session.calls[0].kwargs["json"] == {
            "item": {"service": "mpd", "uri": "mpd://NAS/music/track.flac"}
        }

    async def test_replace_with_a_container_of_another_source(self, mocker: MockerFixture):
        """A non-local container is browsed and sent as the items it lists."""
        item = {"service": "qobuz", "type": "song", "title": "One", "uri": "qobuz://song/1"}
        listing = {"navigation": {"lists": [{"items": [item]}]}}
        client, session = _client(
            mocker, [_json_response(listing), _json_response({"response": "success"})]
        )

        await client.replace_queue_and_play("qobuz://album/123")

        assert session.calls[1].kwargs["json"] == {"list": [item], "index": 0}

    async def test_replace_at_an_index(self, mocker: MockerFixture):
        """With an index the URI is browsed and its items travel with it."""
        items = [
            {"service": "qobuz", "type": "song", "title": f"S{n}", "uri": f"qobuz://song/{n}"}
            for n in range(3)
        ]
        listing = {"navigation": {"lists": [{"items": items}]}}
        client, session = _client(
            mocker, [_json_response(listing), _json_response({"response": "success"})]
        )

        await client.replace_queue_and_play("qobuz://album/123", index=2)

        assert session.calls[1].kwargs["json"] == {"list": items, "index": 2}

    async def test_replace_at_an_index_a_short_listing(self, mocker: MockerFixture):
        """A listing too short for the asked index is reported."""
        item = {"service": "qobuz", "type": "song", "title": "One", "uri": "qobuz://song/1"}
        listing = {"navigation": {"lists": [{"items": [item]}]}}
        client, session = _client(mocker, _json_response(listing))

        with pytest.raises(VolumioAPIError) as excinfo:
            await client.replace_queue_and_play("qobuz://album/123", index=5)

        assert "not enough to play the one at index 5" in str(excinfo.value)
        assert len(session.calls) == 1

    async def test_replace_at_index_zero_an_empty_listing(self, mocker: MockerFixture):
        """A URI listing nothing falls back to the single-item payload at index 0."""
        listing = {"navigation": {"lists": [{"items": []}]}}
        client, session = _client(
            mocker, [_json_response(listing), _json_response({"response": "success"})]
        )

        await client.replace_queue_and_play("qobuz://song/1", index=0)

        assert session.calls[1].kwargs["json"] == {
            "item": {"service": "qobuz", "uri": "qobuz://song/1"}
        }

    async def test_replace_refuses_a_negative_index(self, mocker: MockerFixture):
        """A negative index is refused before anything is sent."""
        client, session = _client(mocker, _json_response({"response": "success"}))

        with pytest.raises(ValueError, match="0 or greater"):
            await client.replace_queue_and_play("mpd://track.flac", index=-1)

        assert session.calls == []


class TestVolumioAsyncRESTAPIClientStories:
    """The Premium plugin queries, which all travel through metavolumio."""

    def _posted(self, session):
        """Return the data payload the metavolumio endpoint was called with."""
        assert session.calls[0].url == f"{BASE}/api/v1/pluginEndpoint"
        assert session.calls[0].kwargs["json"]["endpoint"] == "metavolumio"
        return session.calls[0].kwargs["json"]["data"]

    async def test_get_story_by_artist(self, mocker: MockerFixture):
        """An artist story names the artist and the mode."""
        client, session = _client(mocker, _json_response(STORY_PAYLOAD))

        story = await client.get_story(artist=Artist("Mango"))

        assert self._posted(session) == {"mode": "storyArtist", "artist": "Mango"}
        assert story.value == "A story."

    async def test_get_story_by_album(self, mocker: MockerFixture):
        """An album story carries the album and its artist."""
        client, session = _client(mocker, _json_response(STORY_PAYLOAD))

        await client.get_story(album=Album("Odissea"), artist=Artist("Mango"))

        assert self._posted(session) == {
            "mode": "storyAlbum",
            "artist": "Mango",
            "album": "Odissea",
        }

    async def test_get_story_by_label(self, mocker: MockerFixture):
        """A label story names the label and the mode."""
        client, session = _client(mocker, _json_response(STORY_PAYLOAD))

        await client.get_story(label=Label("Fonit"))

        assert self._posted(session) == {"mode": "storyLabel", "label": "Fonit"}

    async def test_get_story_by_place(self, mocker: MockerFixture):
        """A place story names the place and the mode."""
        client, session = _client(mocker, _json_response(STORY_PAYLOAD))

        await client.get_story(place=Place("Lecce"))

        assert self._posted(session) == {"mode": "storyPlace", "place": "Lecce"}

    async def test_get_album_credits(self, mocker: MockerFixture):
        """The credits query is the album payload under its own mode."""
        client, session = _client(mocker, _json_response(STORY_PAYLOAD))

        await client.get_album_credits(Artist("Mango"), Album("Odissea"))

        assert self._posted(session) == {
            "mode": "creditsAlbum",
            "artist": "Mango",
            "album": "Odissea",
        }

    @pytest.mark.parametrize(
        ("kwargs", "detail"),
        [
            ({}, "One of album, artist, label, or place is required"),
            (
                {"label": Label("Fonit"), "place": Place("Lecce")},
                "mutually exclusive",
            ),
            (
                {"album": Album("Odissea"), "artist": Artist("Mango"), "label": Label("Fonit")},
                "An album story does not take a label or place",
            ),
            (
                {"artist": Artist("Mango"), "place": Place("Lecce")},
                "An artist story does not take a label or place",
            ),
            ({"album": Album("Odissea")}, "requires an artist"),
        ],
    )
    async def test_a_refused_story_query(self, mocker: MockerFixture, kwargs, detail):
        """An invalid entity combination is refused before anything is sent."""
        client, session = _client(mocker, _json_response(STORY_PAYLOAD))

        with pytest.raises(ValueError) as excinfo:
            await client.get_story(**kwargs)

        assert detail in str(excinfo.value)
        assert session.calls == []
