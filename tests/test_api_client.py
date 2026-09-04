"""Tests for the API client adapters of the volumito CLI.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

import asyncio
import threading
from unittest.mock import AsyncMock, Mock, PropertyMock

import pytest

from volumito.cli.api_client import (
    EVENT_LOOP_THREAD_NAME,
    APIClient,
    AsyncAPIClient,
    RESTAsyncAPIClient,
    RESTSyncAPIClient,
    UnsupportedOperationError,
    WebSocketAsyncAPIClient,
    WebSocketSyncAPIClient,
)
from volumito.clients import (
    BrowseResults,
    VolumioConnectionError,
    VolumioHostConfiguration,
    VolumioRESTAPIClient,
)

METHODS = [
    ("add_to_queue", ("uri",), {}),
    ("clear", (), {}),
    ("decrease_volume", (), {}),
    ("increase_volume", (), {}),
    ("mute", (), {}),
    ("next", (), {}),
    ("pause", (), {}),
    ("ping", (), {}),
    ("play", (3,), {}),
    ("play_playlist", ("name",), {}),
    ("previous", (), {}),
    ("randomize", (True,), {}),
    ("repeat", (None,), {}),
    ("replace_queue_and_play", ("uri", 2), {}),
    ("search", ("query",), {}),
    ("seek_backward", (), {}),
    ("seek_forward", (), {}),
    ("stop", (), {}),
    ("toggle", (), {}),
    ("unmute", (), {}),
]
"""The methods every adapter forwards as they are: name, positional and keyword arguments."""

REST_ONLY_METHODS = [
    ("browse", ("uri", 2), {}),
    ("get_album_credits", ("artist", "album"), {}),
    ("get_story", (), {"album": "a", "artist": "b", "label": "c", "place": "d"}),
    ("register_notification", ("http://localhost:3003/n",), {}),
    ("unregister_notification", ("http://localhost:3003/n",), {}),
]
"""The methods the REST adapters forward as they are, and the WebSocket ones adapt."""

PROPERTIES = [
    ("collection_statistics", "get_collection_statistics"),
    ("has_next", "has_next"),
    ("has_previous", "has_previous"),
    ("is_muted", "is_muted"),
    ("is_paused", "is_paused"),
    ("is_playing", "is_playing"),
    ("is_stopped", "is_stopped"),
    ("playlists", "get_playlists"),
    ("queue", "get_queue"),
    ("queue_status", "get_queue_status"),
    ("seek", "get_seek"),
    ("state", "get_state"),
    ("system_info", "get_system_info"),
    ("system_version", "get_system_version"),
    ("volume", "get_volume"),
    ("zones", "get_zones"),
]
"""The read properties every adapter offers: the name, and the coroutine of the async clients."""

SETTERS = [
    ("seek", "set_seek"),
    ("volume", "set_volume"),
]
"""The assignable properties: the name, and the coroutine of the async clients."""

_STORY_KWARGS = {"album": "a", "artist": "b", "label": "c", "place": "d"}
"""The keyword arguments of a story query: the adapters always pass all four."""

UNSUPPORTED = [
    ("get_album_credits", ("artist", "album"), {}, "the story queries"),
    ("get_story", (), _STORY_KWARGS, "the story queries"),
    ("register_notification", ("http://localhost:3003/n",), {}, "the notification URLs"),
    ("unregister_notification", ("http://localhost:3003/n",), {}, "the notification URLs"),
]
"""The methods the WebSocket API does not offer, and how the messages name them."""

_ENVELOPE = {
    "navigation": {
        "lists": [
            {"name": "Music Library", "uri": "music-library"},
            {"name": "QOBUZ", "uri": "qobuz://"},
        ],
    }
}
"""A root browse answer with two items."""


def _property(mock: Mock, name: str, value: object) -> PropertyMock:
    """Attach a property to the type of a mock, so that reading it returns the value."""
    prop = PropertyMock(return_value=value)
    setattr(type(mock), name, prop)
    return prop


def _async_client() -> Mock:
    """A mock of an asynchronous client, whose lifecycle coroutines succeed."""
    client = Mock()
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.close = AsyncMock()
    return client


def _loop_threads() -> list[threading.Thread]:
    """The threads serving an event loop of an adapter still alive."""
    return [thread for thread in threading.enumerate() if thread.name == EVENT_LOOP_THREAD_NAME]


class TestSyncAdapters:
    """Test cases for the adapters of the synchronous clients."""

    @pytest.mark.parametrize("adapter_class", [RESTSyncAPIClient, WebSocketSyncAPIClient])
    @pytest.mark.parametrize(("name", "args", "kwargs"), METHODS)
    def test_method_forwarded(self, adapter_class, name, args, kwargs):
        """A shared method calls the one of the client with the same arguments."""
        client = Mock()
        getattr(client, name).return_value = "outcome"

        assert getattr(adapter_class(client), name)(*args, **kwargs) == "outcome"
        getattr(client, name).assert_called_once_with(*args, **kwargs)

    @pytest.mark.parametrize("adapter_class", [RESTSyncAPIClient, WebSocketSyncAPIClient])
    @pytest.mark.parametrize(("name", "_async_name"), PROPERTIES)
    def test_property_forwarded(self, adapter_class, name, _async_name):
        """A shared property reads the one of the client."""
        client = Mock()
        prop = _property(client, name, "value")

        assert getattr(adapter_class(client), name) == "value"
        prop.assert_called_once_with()

    @pytest.mark.parametrize("adapter_class", [RESTSyncAPIClient, WebSocketSyncAPIClient])
    @pytest.mark.parametrize(("name", "_async_name"), SETTERS)
    def test_setter_forwarded(self, adapter_class, name, _async_name):
        """Assigning a property assigns the one of the client."""
        client = Mock()

        setattr(adapter_class(client), name, 42)

        assert getattr(client, name) == 42

    @pytest.mark.parametrize(("name", "args", "kwargs"), REST_ONLY_METHODS)
    def test_rest_only_method_forwarded(self, name, args, kwargs):
        """The REST adapter forwards the members the WebSocket API lacks as they are."""
        client = Mock()
        getattr(client, name).return_value = "outcome"

        assert getattr(RESTSyncAPIClient(client), name)(*args, **kwargs) == "outcome"
        getattr(client, name).assert_called_once_with(*args, **kwargs)

    def test_rest_notifications_forwarded(self):
        """The REST adapter reads the notification URLs of the client."""
        client = Mock()
        _property(client, "notifications", "urls")

        assert RESTSyncAPIClient(client).notifications == "urls"

    def test_rest_story_forwards_only_the_entities_given(self):
        """A story query passes the client only the entities it was given."""
        client = Mock()

        RESTSyncAPIClient(client).get_story(artist="b")

        client.get_story.assert_called_once_with(artist="b")

    def test_rest_lifecycle_is_a_no_op(self):
        """The REST adapter has nothing to open nor to close."""
        client = Mock()

        with RESTSyncAPIClient(client) as adapter:
            adapter.open()
        adapter.close()

        assert client.mock_calls == []

    def test_websocket_lifecycle(self):
        """The WebSocket adapter connects on open and disconnects on close."""
        client = Mock()

        with WebSocketSyncAPIClient(client) as adapter:
            client.connect.assert_called_once_with()
            client.disconnect.assert_not_called()
        client.disconnect.assert_called_once_with()
        adapter.close()

        assert client.disconnect.call_count == 2

    def test_websocket_close_failure_is_a_warning(self):
        """A failure while disconnecting is logged, not raised."""
        client = Mock()
        client.disconnect.side_effect = RuntimeError("boom")

        WebSocketSyncAPIClient(client).close()

        client.logger.warning.assert_called_once_with(
            "Closing the synchronous WebSocket API client failed (boom)"
        )

    def test_websocket_browse_without_offset(self):
        """Without an offset, the answer of the client is returned as it is."""
        client = Mock()
        results = BrowseResults.from_envelope(_ENVELOPE)
        client.browse.return_value = results

        assert WebSocketSyncAPIClient(client).browse("uri") is results
        client.browse.assert_called_once_with("uri")

    def test_websocket_browse_with_offset(self):
        """The offset skips the first items of the answer, since the API takes none."""
        client = Mock()
        client.browse.return_value = BrowseResults.from_envelope(_ENVELOPE)

        results = WebSocketSyncAPIClient(client).browse(None, 1)

        assert [item.name for item in results.items] == ["QOBUZ"]
        client.browse.assert_called_once_with(None)


class TestAsyncAdapters:
    """Test cases for the adapters of the asynchronous clients."""

    @pytest.mark.parametrize("adapter_class", [RESTAsyncAPIClient, WebSocketAsyncAPIClient])
    @pytest.mark.parametrize(("name", "args", "kwargs"), METHODS)
    def test_method_forwarded(self, adapter_class, name, args, kwargs):
        """A shared method awaits the coroutine of the client with the same arguments."""
        client = _async_client()
        setattr(client, name, AsyncMock(return_value="outcome"))

        with adapter_class(client) as adapter:
            assert getattr(adapter, name)(*args, **kwargs) == "outcome"
        getattr(client, name).assert_awaited_once_with(*args, **kwargs)

    @pytest.mark.parametrize("adapter_class", [RESTAsyncAPIClient, WebSocketAsyncAPIClient])
    @pytest.mark.parametrize(("name", "async_name"), PROPERTIES)
    def test_property_forwarded(self, adapter_class, name, async_name):
        """A shared property awaits the reading coroutine of the client."""
        client = _async_client()
        setattr(client, async_name, AsyncMock(return_value="value"))

        with adapter_class(client) as adapter:
            assert getattr(adapter, name) == "value"
        getattr(client, async_name).assert_awaited_once_with()

    @pytest.mark.parametrize("adapter_class", [RESTAsyncAPIClient, WebSocketAsyncAPIClient])
    @pytest.mark.parametrize(("name", "async_name"), SETTERS)
    def test_setter_forwarded(self, adapter_class, name, async_name):
        """Assigning a property awaits the setting coroutine of the client."""
        client = _async_client()
        setattr(client, async_name, AsyncMock())

        with adapter_class(client) as adapter:
            setattr(adapter, name, 42)
        getattr(client, async_name).assert_awaited_once_with(42)

    @pytest.mark.parametrize(("name", "args", "kwargs"), REST_ONLY_METHODS)
    def test_rest_only_method_forwarded(self, name, args, kwargs):
        """The REST adapter awaits the members the WebSocket API lacks as they are."""
        client = _async_client()
        setattr(client, name, AsyncMock(return_value="outcome"))

        with RESTAsyncAPIClient(client) as adapter:
            assert getattr(adapter, name)(*args, **kwargs) == "outcome"
        getattr(client, name).assert_awaited_once_with(*args, **kwargs)

    def test_rest_notifications_forwarded(self):
        """The REST adapter awaits the notification URLs of the client."""
        client = _async_client()
        client.get_notifications = AsyncMock(return_value="urls")

        with RESTAsyncAPIClient(client) as adapter:
            assert adapter.notifications == "urls"

    def test_rest_story_forwards_only_the_entities_given(self):
        """A story query passes the client only the entities it was given."""
        client = _async_client()
        client.get_story = AsyncMock(return_value="story")

        with RESTAsyncAPIClient(client) as adapter:
            assert adapter.get_story(label="c") == "story"
        client.get_story.assert_awaited_once_with(label="c")

    def test_the_calls_share_one_loop_on_its_own_thread(self):
        """Every coroutine runs on the same loop, served by the thread of the adapter."""
        client = _async_client()
        client.ping = AsyncMock(
            side_effect=lambda: (asyncio.get_running_loop(), threading.current_thread().name)
        )

        with RESTAsyncAPIClient(client) as adapter:
            first_loop, thread_name = adapter.ping()
            second_loop, _ = adapter.ping()
            assert len(_loop_threads()) == 1

        assert first_loop is second_loop
        assert thread_name == EVENT_LOOP_THREAD_NAME
        assert _loop_threads() == []

    def test_rest_close_closes_the_session_once(self):
        """Closing awaits the client close, stops the loop, and is then a no-op."""
        client = _async_client()
        client.ping = AsyncMock(return_value="pong")
        adapter = RESTAsyncAPIClient(client)
        adapter.open()
        adapter.ping()

        adapter.close()
        adapter.close()

        client.close.assert_awaited_once_with()
        assert _loop_threads() == []
        with pytest.raises(RuntimeError, match="asynchronous REST API client is not open"):
            adapter.ping()

    def test_websocket_lifecycle(self):
        """The WebSocket adapter connects on open and disconnects on close."""
        client = _async_client()

        with WebSocketAsyncAPIClient(client):
            client.connect.assert_awaited_once_with()
            client.disconnect.assert_not_awaited()

        client.disconnect.assert_awaited_once_with()
        assert _loop_threads() == []

    def test_not_open(self):
        """A member used before opening fails, without leaking a coroutine."""
        client = _async_client()
        client.ping = AsyncMock(return_value="pong")

        with pytest.raises(RuntimeError, match="asynchronous REST API client is not open"):
            RESTAsyncAPIClient(client).ping()

        client.ping.assert_not_awaited()

    def test_reopen_after_close(self):
        """A closed adapter can be opened again, on a fresh loop."""
        client = _async_client()
        client.ping = AsyncMock(side_effect=lambda: asyncio.get_running_loop())
        adapter = RESTAsyncAPIClient(client)

        with adapter:
            first = adapter.ping()
        with adapter:
            second = adapter.ping()

        assert first is not second
        assert client.close.await_count == 2

    def test_failed_open_stops_the_loop(self):
        """When the connection fails, the loop is stopped and the failure propagates."""
        client = _async_client()
        client.connect = AsyncMock(side_effect=VolumioConnectionError("unreachable"))
        adapter = WebSocketAsyncAPIClient(client)

        with pytest.raises(VolumioConnectionError, match="unreachable"):
            adapter.open()

        assert _loop_threads() == []
        with pytest.raises(RuntimeError, match="is not open"):
            adapter.ping()

    def test_close_failure_is_a_warning(self):
        """A failure while closing the session is logged, and the loop still stopped."""
        client = _async_client()
        client.close = AsyncMock(side_effect=RuntimeError("boom"))
        adapter = RESTAsyncAPIClient(client)
        adapter.open()

        adapter.close()

        client.logger.warning.assert_called_once_with(
            "Closing the asynchronous REST API client failed (boom)"
        )
        assert _loop_threads() == []

    def test_close_cancels_the_pending_tasks(self):
        """A task the client left running is cancelled when the loop stops."""
        client = _async_client()
        tasks = []

        def spawn():
            tasks.append(asyncio.get_running_loop().create_task(asyncio.sleep(60)))

        client.connect = AsyncMock(side_effect=spawn)

        with WebSocketAsyncAPIClient(client):
            assert not tasks[0].done()

        assert tasks[0].cancelled()

    def test_websocket_browse_without_offset(self):
        """Without an offset, the answer of the client is returned as it is."""
        client = _async_client()
        results = BrowseResults.from_envelope(_ENVELOPE)
        client.browse = AsyncMock(return_value=results)

        with WebSocketAsyncAPIClient(client) as adapter:
            assert adapter.browse("uri") is results
        client.browse.assert_awaited_once_with("uri")

    def test_websocket_browse_with_offset(self):
        """The offset skips the first items of the answer, since the API takes none."""
        client = _async_client()
        client.browse = AsyncMock(return_value=BrowseResults.from_envelope(_ENVELOPE))

        with WebSocketAsyncAPIClient(client) as adapter:
            results = adapter.browse(None, 1)

        assert [item.name for item in results.items] == ["QOBUZ"]
        client.browse.assert_awaited_once_with(None)


class TestWebSocketFallback:
    """Test cases for the REST API client the WebSocket adapters fall back to."""

    @staticmethod
    def _adapter(adapter_class, fallback=None):
        """Build a WebSocket adapter over a mock client, opened."""
        client = _async_client() if issubclass(adapter_class, AsyncAPIClient) else Mock()
        adapter = adapter_class(client, fallback=fallback)
        adapter.open()
        return adapter, client

    @pytest.mark.parametrize(
        "adapter_class", [WebSocketSyncAPIClient, WebSocketAsyncAPIClient]
    )
    @pytest.mark.parametrize(("name", "args", "kwargs", "operation"), UNSUPPORTED)
    def test_unsupported_without_fallback(self, adapter_class, name, args, kwargs, operation):
        """Without a fallback, the members the WebSocket API lacks raise."""
        adapter, _ = self._adapter(adapter_class)
        expected = (
            f"The {adapter.description} does not offer {operation}: use "
            "--api-client rest_synchronous or rest_asynchronous, "
            "or --allow-fallback-to-rest-api"
        )

        with pytest.raises(UnsupportedOperationError) as excinfo:
            getattr(adapter, name)(*args, **kwargs)

        assert str(excinfo.value) == expected
        adapter.close()

    @pytest.mark.parametrize(
        "adapter_class", [WebSocketSyncAPIClient, WebSocketAsyncAPIClient]
    )
    def test_unsupported_notifications_without_fallback(self, adapter_class):
        """Without a fallback, reading the notification URLs raises."""
        adapter, _ = self._adapter(adapter_class)

        with pytest.raises(UnsupportedOperationError, match="does not offer the notification URLs"):
            _ = adapter.notifications

        adapter.close()

    @pytest.mark.parametrize(
        "adapter_class", [WebSocketSyncAPIClient, WebSocketAsyncAPIClient]
    )
    @pytest.mark.parametrize(("name", "args", "kwargs", "operation"), UNSUPPORTED)
    def test_delegated_to_the_fallback(self, adapter_class, name, args, kwargs, operation):
        """With a fallback, the members the WebSocket API lacks use the REST API client."""
        rest = Mock()
        getattr(rest, name).return_value = "outcome"
        factory = Mock(return_value=rest)
        adapter, client = self._adapter(adapter_class, fallback=factory)

        assert getattr(adapter, name)(*args, **kwargs) == "outcome"

        getattr(rest, name).assert_called_once_with(*args, **kwargs)
        rest.open.assert_called_once_with()
        client.logger.warning.assert_called_once_with(
            f"Falling back to the REST API client for {operation} "
            "(the WebSocket API does not offer them)"
        )
        adapter.close()

    @pytest.mark.parametrize(
        "adapter_class", [WebSocketSyncAPIClient, WebSocketAsyncAPIClient]
    )
    def test_the_fallback_is_built_once_and_closed_with_the_adapter(self, adapter_class):
        """The REST API client is built on the first operation, kept, and closed at the end."""
        rest = Mock()
        _property(rest, "notifications", "urls")
        rest.get_story.return_value = "story"
        factory = Mock(return_value=rest)
        adapter, client = self._adapter(adapter_class, fallback=factory)

        assert adapter.notifications == "urls"
        assert adapter.get_story(artist="b") == "story"
        rest.close.assert_not_called()
        adapter.close()

        factory.assert_called_once_with()
        rest.open.assert_called_once_with()
        rest.close.assert_called_once_with()
        assert client.logger.warning.call_count == 2
        # The disconnection follows the closing of the fallback
        client.disconnect.assert_called_once_with()

    def test_the_fallback_is_not_closed_when_never_built(self):
        """Closing an adapter that never fell back builds nothing."""
        factory = Mock()
        adapter, _ = self._adapter(WebSocketSyncAPIClient, fallback=factory)

        adapter.close()

        factory.assert_not_called()


class TestCommonMembers:
    """Test cases for the members every adapter shares."""

    _HOST = VolumioHostConfiguration(host="volumio", rest_api_port=3001, websocket_port=3002)

    @pytest.mark.parametrize(
        ("adapter_class", "description", "base_url"),
        [
            (RESTSyncAPIClient, "synchronous REST API client", "http://volumio:3001"),
            (RESTAsyncAPIClient, "asynchronous REST API client", "http://volumio:3001"),
            (WebSocketSyncAPIClient, "synchronous WebSocket API client", "http://volumio:3002"),
            (WebSocketAsyncAPIClient, "asynchronous WebSocket API client", "http://volumio:3002"),
        ],
    )
    def test_description_and_base_url(self, adapter_class, description, base_url):
        """Each adapter names itself and the endpoint of its API."""
        client = Mock()
        client.host_configuration = self._HOST

        adapter = adapter_class(client)

        assert adapter.description == description
        assert adapter.base_url == base_url
        assert adapter.host_configuration is self._HOST
        assert adapter.logger is client.logger

    def test_a_real_client_is_wrapped(self):
        """The adapter exposes the host configuration and the logger of a real client."""
        client = VolumioRESTAPIClient(self._HOST)

        adapter = RESTSyncAPIClient(client)

        assert adapter.host_configuration is self._HOST
        assert adapter.logger is client.logger

    def test_the_surface_is_abstract(self):
        """The surface itself cannot be instantiated."""
        with pytest.raises(TypeError):
            APIClient(Mock())
