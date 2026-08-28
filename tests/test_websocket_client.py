"""Tests for the WebSocket API client module.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

import logging
import sys
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any
from unittest.mock import Mock

import pytest
from pytest_mock import MockerFixture

# The WebSocket client needs the optional "websocket" extra: without it, this whole
# module has nothing to say
socketio = pytest.importorskip("socketio")

from volumito.clients.errors import (  # noqa: E402
    VolumioAPIError,
    VolumioConnectionError,
    VolumioWebSocketError,
)
from volumito.clients.host_configuration import VolumioHostConfiguration  # noqa: E402
from volumito.clients.models import Alarm, Playlist, QueueTrack  # noqa: E402
from volumito.clients.websocket.client import (  # noqa: E402
    VolumioWebSocketClient,
    _load_socketio,
)
from volumito.clients.websocket.common import (  # noqa: E402
    EVENT_BROWSE_LIBRARY,
    EVENT_DELETE_USER_DATA,
    EVENT_FACTORY_RESET,
    EVENT_GET_MULTI_ROOM_DEVICES,
    EVENT_GET_MY_COLLECTION_STATS,
    EVENT_GET_QUEUE,
    EVENT_GET_STATE,
    EVENT_GET_SYSTEM_INFO,
    EVENT_GET_SYSTEM_VERSION,
    EVENT_LIST_PLAYLIST,
    EVENT_PINGER,
    EVENT_PLAY,
    EVENT_PONGER,
    EVENT_PUSH_BROWSE_LIBRARY,
    EVENT_PUSH_LIST_PLAYLIST,
    EVENT_PUSH_QUEUE,
    EVENT_PUSH_STATE,
    EVENT_SEARCH,
    RESPONSE_EVENTS,
)

BASE = "http://volumio.local:3000"
"""The WebSocket URL of a host left at its defaults."""

STATE_PAYLOAD = {"status": "play", "volume": 50, "mute": False, "seek": 42000, "position": 1}
"""A playback state of the shape a Volumio host pushes."""

QUEUE_PAYLOAD = [{"uri": "mpd://track.flac", "title": "So What", "service": "mpd"}]
"""A playback queue of the shape a Volumio host pushes."""


@dataclass
class _Call:
    """One event the fake connection was asked to emit."""

    event: str
    payload: Any = None


@dataclass
class _FakeSocketIOClient:
    """A stand-in for socketio.Client, recording what it was asked to do.

    An entry of ``answers`` maps an emitted event to the (event, payload) pair the fake
    pushes back the moment it is emitted, which is what a Volumio host does and what
    lets a read resolve without a second thread.
    """

    answers: dict[str, tuple[str, Any]] = field(default_factory=dict)
    connect_error: BaseException | None = None
    emit_error: BaseException | None = None
    disconnect_error: BaseException | None = None

    def __post_init__(self):
        self.handlers: dict[str, Any] = {}
        self.calls: list[_Call] = []
        self.connected = False
        self.waited = False
        self.connected_url: str | None = None

    def on(self, event, handler):
        self.handlers[event] = handler

    def connect(self, url, **kwargs):
        if self.connect_error is not None:
            raise self.connect_error
        self.connected = True
        self.connected_url = url

    def emit(self, event, payload=None):
        self.calls.append(_Call(event, payload))
        if self.emit_error is not None:
            raise self.emit_error
        answer = self.answers.get(event)
        if answer is not None:
            self.fire(*answer)

    def disconnect(self):
        if self.disconnect_error is not None:
            raise self.disconnect_error
        self.connected = False

    def wait(self):
        self.waited = True

    def fire(self, event, payload=None):
        """Push an event, the way a Volumio host does."""
        handler = self.handlers.get(event)
        if handler is not None:
            handler(payload)


def _client(
    mocker: MockerFixture,
    fake: _FakeSocketIOClient | None = None,
    logger: logging.Logger | None = None,
    connect: bool = True,
    **kwargs,
) -> tuple[VolumioWebSocketClient, _FakeSocketIOClient]:
    """Build a client whose connection is a fake, connected unless asked otherwise."""
    fake = fake if fake is not None else _FakeSocketIOClient()
    mocker.patch("socketio.Client", return_value=fake)
    client = VolumioWebSocketClient(VolumioHostConfiguration(), logger=logger, **kwargs)
    if connect:
        client.connect()
    return client, fake


NAVIGATION_PAYLOAD = {
    "navigation": {
        "lists": [
            {
                "title": "Playlists",
                "items": [
                    {
                        "service": "mpd",
                        "type": "song",
                        "title": "jazz",
                        "uri": "mpd://a",
                        "albumart": "/albumart",
                    }
                ],
            }
        ]
    }
}
"""A browse listing of the shape a Volumio host pushes."""

EMPTY_NAVIGATION = {"navigation": {"lists": [{"title": "Nothing", "items": []}]}}
"""A browse listing holding no item at all."""


def _browse_client(
    mocker: MockerFixture, logger: logging.Logger | None = None
) -> tuple[VolumioWebSocketClient, _FakeSocketIOClient]:
    """Build a connected client whose host answers a browse with one item."""
    fake = _FakeSocketIOClient(
        answers={EVENT_BROWSE_LIBRARY: (EVENT_PUSH_BROWSE_LIBRARY, NAVIGATION_PAYLOAD)}
    )
    return _client(mocker, fake, logger=logger)


def _state_and_queue_fake() -> _FakeSocketIOClient:
    """Build a fake answering a state at position 1 and a queue of two tracks."""
    return _FakeSocketIOClient(
        answers={
            EVENT_GET_STATE: (EVENT_PUSH_STATE, STATE_PAYLOAD),
            EVENT_GET_QUEUE: (EVENT_PUSH_QUEUE, QUEUE_PAYLOAD * 2),
        }
    )


def _state_client(
    mocker: MockerFixture, logger: logging.Logger | None = None, **kwargs
) -> tuple[VolumioWebSocketClient, _FakeSocketIOClient]:
    """Build a connected client whose host answers getState with a playback state."""
    fake = _FakeSocketIOClient(answers={EVENT_GET_STATE: (EVENT_PUSH_STATE, STATE_PAYLOAD)})
    return _client(mocker, fake, logger=logger, **kwargs)


class TestVolumioWebSocketClientLifecycle:
    """The connection the WebSocket client owns, and the package it needs."""

    def test_load_socketio_returns_the_module(self):
        """With the package installed, the loader hands the module over."""
        assert _load_socketio() is socketio

    def test_load_socketio_without_the_package(self, mocker: MockerFixture):
        """Without the package, the loader names the extra that provides it."""
        mocker.patch.dict(sys.modules, {"socketio": None})

        with pytest.raises(VolumioWebSocketError) as excinfo:
            _load_socketio()

        assert "needs the python-socketio package" in str(excinfo.value)
        assert "pip install volumito[websocket]" in str(excinfo.value)

    def test_importing_volumito_needs_no_websocket_package(self):
        """The package is loaded on connecting, never on importing the library."""
        assert "volumito" in sys.modules

    def test_connect_opens_the_connection(self, mocker: MockerFixture):
        """Connecting reaches the WebSocket URL of the host and flips the flag."""
        client, fake = _client(mocker)

        assert fake.connected is True
        assert fake.connected_url == BASE
        assert client._connected is True

    def test_connect_logs_its_steps(self, mocker: MockerFixture):
        """A successful connection leaves the bracketed pair at debug, never info."""
        logger = Mock()

        _client(mocker, logger=logger)

        debugged = [call.args[0] for call in logger.debug.call_args_list]
        assert any(line.endswith('at "http://volumio.local:3000"...') for line in debugged)
        assert any(line.endswith("... done") for line in debugged)
        logger.info.assert_not_called()
        logger.warning.assert_not_called()

    def test_connect_when_already_connected_does_nothing(self, mocker: MockerFixture):
        """Connecting twice keeps the first connection rather than opening a second."""
        client, fake = _client(mocker)
        opened = fake.connected_url

        client.connect()

        assert fake.connected_url == opened
        assert client._connected is True

    @pytest.mark.parametrize(
        "error",
        [
            ConnectionRefusedError("refused"),
            socketio.exceptions.ConnectionError("down"),
            RuntimeError("odd"),
        ],
    )
    def test_connect_failure_warns_and_raises(self, mocker: MockerFixture, error):
        """A connection that cannot be opened warns once and leaves the client clean."""
        logger = Mock()
        fake = _FakeSocketIOClient(connect_error=error)

        client, _ = _client(mocker, fake, logger=logger, connect=False)

        with pytest.raises(VolumioConnectionError) as excinfo:
            client.connect()

        assert "Failed to connect to Volumio instance at" in str(excinfo.value)
        assert BASE in str(excinfo.value)
        assert client._connected is False
        assert client._client is None
        logger.warning.assert_called_once()

    def test_disconnect_closes_the_connection(self, mocker: MockerFixture):
        """Disconnecting closes the connection the client owns and forgets it."""
        client, fake = _client(mocker)

        client.disconnect()

        assert fake.connected is False
        assert client._connected is False
        assert client._client is None

    def test_disconnect_when_not_connected(self, mocker: MockerFixture):
        """Disconnecting a client that never connected is a no-op."""
        client, fake = _client(mocker, connect=False)

        client.disconnect()

        assert fake.connected is False
        assert client._connected is False

    def test_disconnect_swallows_a_cleanup_error_with_a_warning(self, mocker: MockerFixture):
        """A failure while disconnecting is swallowed, warned about, and leaves it clean."""
        logger = Mock()
        fake = _FakeSocketIOClient(disconnect_error=RuntimeError("socket already gone"))
        client, _ = _client(mocker, fake, logger=logger)

        client.disconnect()

        logger.warning.assert_called_once()
        assert "disconnecting" in logger.warning.call_args.args[0]
        assert client._connected is False
        assert client._client is None

    def test_context_manager_connects_and_disconnects(self, mocker: MockerFixture):
        """Entering the block connects, leaving it disconnects."""
        fake = _FakeSocketIOClient()
        mocker.patch("socketio.Client", return_value=fake)

        with VolumioWebSocketClient(VolumioHostConfiguration()) as client:
            assert client._connected is True

        assert fake.connected is False
        assert client._connected is False

    def test_context_manager_disconnects_on_error(self, mocker: MockerFixture):
        """An exception leaving the block still closes the connection."""
        fake = _FakeSocketIOClient()
        mocker.patch("socketio.Client", return_value=fake)

        with pytest.raises(RuntimeError):
            with VolumioWebSocketClient(VolumioHostConfiguration()):
                raise RuntimeError("boom")

        assert fake.connected is False

    def test_context_manager_connection_failure(self, mocker: MockerFixture):
        """A connection that fails is not disconnected on the way out."""
        fake = _FakeSocketIOClient(connect_error=ConnectionRefusedError("refused"))
        mocker.patch("socketio.Client", return_value=fake)
        client = VolumioWebSocketClient(VolumioHostConfiguration())

        with pytest.raises(VolumioConnectionError):
            with client:
                pass

        assert client._connected is False


class TestVolumioWebSocketClientTransport:
    """The events the client emits, and the answers it waits for."""

    def test_emit_without_a_payload(self, mocker: MockerFixture):
        """An event carrying nothing is emitted on its own."""
        client, fake = _client(mocker)

        client.emit("clearQueue")

        assert fake.calls == [_Call("clearQueue", None)]

    def test_emit_with_a_payload(self, mocker: MockerFixture):
        """An event carrying a payload is emitted with it."""
        client, fake = _client(mocker)

        client.emit("addToQueue", {"uri": "mpd://track.flac"})

        assert fake.calls == [_Call("addToQueue", {"uri": "mpd://track.flac"})]

    def test_emit_logs_its_steps(self, mocker: MockerFixture):
        """Emitting leaves the bracketed pair at debug, never info."""
        logger = Mock()
        client, _ = _client(mocker, logger=logger)
        logger.reset_mock()

        client.emit("stop")

        debugged = [call.args[0] for call in logger.debug.call_args_list]
        assert 'Emitting "stop"...' in debugged
        assert 'Emitting "stop"... done' in debugged
        logger.info.assert_not_called()

    def test_emit_while_not_connected(self, mocker: MockerFixture):
        """Emitting without a connection warns once and names the host."""
        logger = Mock()
        client, fake = _client(mocker, logger=logger, connect=False)

        with pytest.raises(VolumioConnectionError) as excinfo:
            client.emit("stop")

        assert "Not connected to the Volumio WebSocket API" in str(excinfo.value)
        assert BASE in str(excinfo.value)
        assert fake.calls == []
        logger.warning.assert_called_once()

    def test_emit_failure_warns_and_raises(self, mocker: MockerFixture):
        """An event that cannot be sent warns once and names the event."""
        logger = Mock()
        fake = _FakeSocketIOClient(emit_error=RuntimeError("gone"))
        client, _ = _client(mocker, fake, logger=logger)

        with pytest.raises(VolumioConnectionError) as excinfo:
            client.emit("stop")

        assert 'Failed to emit "stop"' in str(excinfo.value)
        logger.warning.assert_called_once()

    def test_request_returns_the_answer(self, mocker: MockerFixture):
        """A read emits its event and returns what the answer carried."""
        client, fake = _state_client(mocker)

        answer = client.request(EVENT_GET_STATE)

        assert answer == STATE_PAYLOAD
        assert fake.calls == [_Call(EVENT_GET_STATE, None)]

    def test_request_takes_an_explicit_answer_event(self, mocker: MockerFixture):
        """An event the map does not know can still be read, given its answer."""
        fake = _FakeSocketIOClient(answers={"noSuchEvent": ("pushNothing", {"answered": True})})
        client, _ = _client(mocker, fake)

        answer = client.request("noSuchEvent", "pushNothing")

        assert answer == {"answered": True}

    def test_request_refuses_an_event_with_no_known_answer(self, mocker: MockerFixture):
        """Reading an event the host does not answer warns once and refuses."""
        logger = Mock()
        client, fake = _client(mocker, logger=logger)

        with pytest.raises(ValueError, match="answers no 'noSuchEvent' event"):
            client.request("noSuchEvent")

        assert fake.calls == []
        logger.warning.assert_called_once()

    def test_request_times_out(self, mocker: MockerFixture):
        """A host that does not answer in time warns once and names both events."""
        logger = Mock()
        client, _ = _client(mocker, logger=logger, timeout=0.01)

        with pytest.raises(VolumioConnectionError) as excinfo:
            client.request(EVENT_GET_STATE)

        assert 'did not answer "getState" with "pushState"' in str(excinfo.value)
        logger.warning.assert_called_once()

    def test_request_takes_its_own_timeout(self, mocker: MockerFixture):
        """A read waits the number of seconds it was given, not the client default."""
        client, _ = _client(mocker, timeout=30.0)

        with pytest.raises(VolumioConnectionError) as excinfo:
            client.request(EVENT_GET_STATE, timeout=0.01)

        assert "within 0.01 seconds" in str(excinfo.value)

    def test_request_leaves_no_slot_behind(self, mocker: MockerFixture):
        """A read cleans up after itself, whether it succeeded or timed out."""
        client, _ = _state_client(mocker, timeout=0.01)

        client.request(EVENT_GET_STATE)
        with pytest.raises(VolumioConnectionError):
            client.request(EVENT_GET_STATE, EVENT_PUSH_QUEUE)

        assert client._arrived == {}
        assert client._slots == {}

    def test_reads_are_serialized(self, mocker: MockerFixture):
        """The lock a read takes is released once it is answered."""
        client, fake = _state_client(mocker)

        client.request(EVENT_GET_STATE)
        client.request(EVENT_GET_STATE)

        assert len(fake.calls) == 2
        assert client._request_lock.acquire(blocking=False) is True
        client._request_lock.release()

    def test_wait_blocks_on_the_connection(self, mocker: MockerFixture):
        """Waiting hands over to the connection until it drops."""
        client, fake = _client(mocker)

        client.wait()

        assert fake.waited is True

    def test_wait_while_not_connected(self, mocker: MockerFixture):
        """Waiting without a connection warns once and refuses."""
        logger = Mock()
        client, _ = _client(mocker, logger=logger, connect=False)

        with pytest.raises(VolumioConnectionError):
            client.wait()

        logger.warning.assert_called_once()


class TestVolumioWebSocketClientEvents:
    """The handlers the client calls when the host pushes an event."""

    def test_a_handler_receives_a_pushed_event(self, mocker: MockerFixture):
        """A registered handler is called with the payload of the event."""
        client, fake = _client(mocker)
        received: list[Any] = []
        client.on(EVENT_PUSH_STATE, received.append)

        fake.fire(EVENT_PUSH_STATE, STATE_PAYLOAD)

        assert received == [STATE_PAYLOAD]

    def test_a_handler_registered_before_connecting(self, mocker: MockerFixture):
        """A handler registered before the connection opens still receives its events."""
        fake = _FakeSocketIOClient()
        mocker.patch("socketio.Client", return_value=fake)
        client = VolumioWebSocketClient(VolumioHostConfiguration())
        received: list[Any] = []
        client.on("pushToastMessage", received.append)

        client.connect()
        fake.fire("pushToastMessage", {"title": "hello"})

        assert received == [{"title": "hello"}]

    def test_several_handlers_of_one_event(self, mocker: MockerFixture):
        """Every handler of an event is called, in the order they were added."""
        client, fake = _client(mocker)
        seen: list[str] = []
        client.on(EVENT_PUSH_STATE, lambda payload: seen.append("first"))
        client.on(EVENT_PUSH_STATE, lambda payload: seen.append("second"))

        fake.fire(EVENT_PUSH_STATE, STATE_PAYLOAD)

        assert seen == ["first", "second"]

    def test_an_event_with_no_payload(self, mocker: MockerFixture):
        """An event a host pushes bare reaches its handler as None."""
        client, fake = _client(mocker)
        received: list[Any] = []
        client.on("closeAllModals", received.append)

        fake.handlers["closeAllModals"]()

        assert received == [None]

    def test_off_removes_one_handler(self, mocker: MockerFixture):
        """A removed handler is no longer called, the others still are."""
        client, fake = _client(mocker)
        seen: list[str] = []

        def first(payload):
            seen.append("first")

        client.on(EVENT_PUSH_STATE, first)
        client.on(EVENT_PUSH_STATE, lambda payload: seen.append("second"))
        client.off(EVENT_PUSH_STATE, first)
        fake.fire(EVENT_PUSH_STATE, STATE_PAYLOAD)

        assert seen == ["second"]

    def test_off_removes_every_handler(self, mocker: MockerFixture):
        """Without a handler, every handler of the event is removed."""
        client, fake = _client(mocker)
        seen: list[str] = []
        client.on(EVENT_PUSH_STATE, lambda payload: seen.append("first"))
        client.on(EVENT_PUSH_STATE, lambda payload: seen.append("second"))

        client.off(EVENT_PUSH_STATE)
        fake.fire(EVENT_PUSH_STATE, STATE_PAYLOAD)

        assert seen == []

    def test_off_an_unknown_handler(self, mocker: MockerFixture):
        """Removing a handler that was never added changes nothing."""
        client, fake = _client(mocker)
        seen: list[str] = []
        client.on(EVENT_PUSH_STATE, lambda payload: seen.append("kept"))

        client.off(EVENT_PUSH_STATE, lambda payload: None)
        client.off("pushQueue", lambda payload: None)
        fake.fire(EVENT_PUSH_STATE, STATE_PAYLOAD)

        assert seen == ["kept"]

    def test_a_failing_handler_is_logged_and_the_others_run(self, mocker: MockerFixture):
        """One handler raising does not stop the others, and leaves a traceback."""
        logger = Mock()
        client, fake = _client(mocker, logger=logger)
        seen: list[str] = []

        def failing(payload):
            raise RuntimeError("boom")

        client.on(EVENT_PUSH_STATE, failing)
        client.on(EVENT_PUSH_STATE, lambda payload: seen.append("second"))
        fake.fire(EVENT_PUSH_STATE, STATE_PAYLOAD)

        assert seen == ["second"]
        logger.exception.assert_called_once()
        assert 'A handler of "pushState" raised' in logger.exception.call_args.args[0]

    def test_a_handler_also_sees_the_answer_of_a_read(self, mocker: MockerFixture):
        """A read is answered by an event, so a handler of it is called too."""
        client, _ = _state_client(mocker)
        received: list[Any] = []
        client.on(EVENT_PUSH_STATE, received.append)

        answer = client.request(EVENT_GET_STATE)

        assert answer == STATE_PAYLOAD
        assert received == [STATE_PAYLOAD]

    def test_every_answer_event_is_listened_for(self, mocker: MockerFixture):
        """Connecting registers the client for every event a read can wait on."""
        _, fake = _client(mocker)

        assert set(RESPONSE_EVENTS.values()) <= set(fake.handlers)


class TestVolumioWebSocketClientPing:
    """The liveness check, which a Volumio host answers by echoing it back."""

    def test_ping_returns_pong(self, mocker: MockerFixture):
        """A host echoing the ping back is reported as healthy."""
        fake = _FakeSocketIOClient()
        fake.answers[EVENT_PINGER] = (EVENT_PONGER, None)
        client, _ = _client(mocker, fake)
        # echo back exactly what the ping carried
        fake.emit = lambda event, payload=None: fake.fire(EVENT_PONGER, payload)

        assert client.ping() == "pong"

    def test_ping_that_is_not_echoed_back(self, mocker: MockerFixture):
        """A host answering with something else warns once and refuses the answer."""
        logger = Mock()
        fake = _FakeSocketIOClient(answers={EVENT_PINGER: (EVENT_PONGER, {"nonce": "other"})})
        client, _ = _client(mocker, fake, logger=logger)

        with pytest.raises(VolumioConnectionError):
            client.ping()

        assert logger.warning.call_count == 2

    def test_ping_answered_with_a_scalar(self, mocker: MockerFixture):
        """An answer that is not even an object is refused too."""
        fake = _FakeSocketIOClient(answers={EVENT_PINGER: (EVENT_PONGER, "pong")})
        client, _ = _client(mocker, fake)

        with pytest.raises(VolumioConnectionError):
            client.ping()

class TestVolumioWebSocketClientReads:
    """The reads answered by a pushed event, and the models they build."""

    def test_state(self, mocker: MockerFixture):
        """The playback state is read from the state the host pushes back."""
        client, fake = _state_client(mocker)

        state = client.state

        assert state.status == "play"
        assert state.volume == 50
        assert fake.calls == [_Call(EVENT_GET_STATE, None)]

    def test_queue(self, mocker: MockerFixture):
        """The queue is answered as its tracks, which the model wraps."""
        fake = _FakeSocketIOClient(answers={EVENT_GET_QUEUE: (EVENT_PUSH_QUEUE, QUEUE_PAYLOAD)})
        client, _ = _client(mocker, fake)

        queue = client.queue

        assert len(queue) == 1
        assert queue[0].title == "So What"
        assert queue[0].position == 0

    def test_playlists(self, mocker: MockerFixture):
        """The playlists are answered as an array of names."""
        fake = _FakeSocketIOClient(
            answers={EVENT_LIST_PLAYLIST: (EVENT_PUSH_LIST_PLAYLIST, ["jazz", "rock"])}
        )
        client, _ = _client(mocker, fake)

        playlists = client.playlists

        assert [playlist.name for playlist in playlists] == ["jazz", "rock"]

    def test_system_info(self, mocker: MockerFixture):
        """The system information is read from the object the host pushes back."""
        fake = _FakeSocketIOClient(
            answers={EVENT_GET_SYSTEM_INFO: ("pushSystemInfo", {"name": "volumio", "id": "1"})}
        )
        client, _ = _client(mocker, fake)

        assert client.system_info.name == "volumio"

    def test_system_version(self, mocker: MockerFixture):
        """The version is read from the object the host pushes back."""
        fake = _FakeSocketIOClient(
            answers={EVENT_GET_SYSTEM_VERSION: ("pushSystemVersion", {"systemversion": "4.119"})}
        )
        client, _ = _client(mocker, fake)

        assert client.system_version.system_version == "4.119"

    def test_collection_statistics(self, mocker: MockerFixture):
        """The collection statistics are read from the object the host pushes back."""
        fake = _FakeSocketIOClient(
            answers={
                EVENT_GET_MY_COLLECTION_STATS: (
                    "pushMyCollectionStats",
                    {"artists": 6, "albums": 8, "songs": 116},
                )
            }
        )
        client, _ = _client(mocker, fake)

        assert client.collection_statistics.songs == 116

    def test_zones(self, mocker: MockerFixture):
        """The devices the host answers under "list" are read as the zones."""
        fake = _FakeSocketIOClient(
            answers={
                EVENT_GET_MULTI_ROOM_DEVICES: (
                    "pushMultiRoomDevices",
                    {"misc": {"debug": True}, "list": [{"id": "1", "name": "Kitchen"}]},
                )
            }
        )
        client, _ = _client(mocker, fake)

        zones = client.zones

        assert len(zones) == 1
        assert zones[0].name == "Kitchen"

    def test_zones_without_a_list(self, mocker: MockerFixture):
        """A host answering no devices is read as no zones."""
        fake = _FakeSocketIOClient(
            answers={EVENT_GET_MULTI_ROOM_DEVICES: ("pushMultiRoomDevices", {"misc": {}})}
        )
        client, _ = _client(mocker, fake)

        assert len(client.zones) == 0

    def test_browse(self, mocker: MockerFixture):
        """Browsing sends the URI and reads the navigation envelope back."""
        client, fake = _browse_client(mocker)

        results = client.browse("playlists")

        assert [item.title for item in results.items] == ["jazz"]
        assert fake.calls == [_Call(EVENT_BROWSE_LIBRARY, {"uri": "playlists"})]

    def test_browse_the_root(self, mocker: MockerFixture):
        """Browsing without a URI asks for the root."""
        client, fake = _browse_client(mocker)

        client.browse()

        assert fake.calls == [_Call(EVENT_BROWSE_LIBRARY, {"uri": "/"})]

    def test_search(self, mocker: MockerFixture):
        """Searching sends the query and reads the navigation envelope back."""
        fake = _FakeSocketIOClient(
            answers={EVENT_SEARCH: (EVENT_PUSH_BROWSE_LIBRARY, NAVIGATION_PAYLOAD)}
        )
        client, _ = _client(mocker, fake)

        results = client.search("miles")

        assert [item.title for item in results.items] == ["jazz"]

    def test_a_read_answered_with_the_wrong_shape(self, mocker: MockerFixture):
        """An answer that is not the expected JSON shape warns once and raises."""
        logger = Mock()
        fake = _FakeSocketIOClient(answers={EVENT_GET_STATE: (EVENT_PUSH_STATE, ["not", "it"])})
        client, _ = _client(mocker, fake, logger=logger)

        with pytest.raises(VolumioAPIError):
            _ = client.state

        logger.warning.assert_called_once()

    def test_an_array_read_answered_with_the_wrong_shape(self, mocker: MockerFixture):
        """An array read answered with an object warns once and raises."""
        fake = _FakeSocketIOClient(
            answers={EVENT_LIST_PLAYLIST: (EVENT_PUSH_LIST_PLAYLIST, {"not": "an array"})}
        )
        client, _ = _client(mocker, fake)

        with pytest.raises(VolumioAPIError):
            _ = client.playlists

    def test_queue_status(self, mocker: MockerFixture):
        """The navigation state reads the playback state and the queue."""
        client, _ = _client(mocker, _state_and_queue_fake())

        status = client.queue_status

        assert status == {
            "has_next": False,
            "has_previous": True,
            "length": 2,
            "position": 1,
            "track": STATE_PAYLOAD,
        }

    def test_has_next_and_has_previous(self, mocker: MockerFixture):
        """The neighbors of the current track are read off the navigation state."""
        client, _ = _client(mocker, _state_and_queue_fake())

        assert client.has_next is False
        assert client.has_previous is True

    @pytest.mark.parametrize(
        ("status", "playing", "paused", "stopped"),
        [
            ("play", True, False, False),
            ("pause", False, True, False),
            ("stop", False, False, True),
        ],
    )
    def test_the_playback_predicates(
        self, mocker: MockerFixture, status, playing, paused, stopped
    ):
        """Each predicate reads the status string of the playback state."""
        fake = _FakeSocketIOClient(
            answers={EVENT_GET_STATE: (EVENT_PUSH_STATE, {**STATE_PAYLOAD, "status": status})}
        )
        client, _ = _client(mocker, fake)

        assert client.is_playing is playing
        assert client.is_paused is paused
        assert client.is_stopped is stopped

    def test_is_muted(self, mocker: MockerFixture):
        """The mute flag is read off the playback state."""
        client, _ = _state_client(mocker)

        assert client.is_muted is False

    def test_seek_and_volume_are_read_off_the_state(self, mocker: MockerFixture):
        """Both properties read the playback state, seek in whole seconds."""
        client, _ = _state_client(mocker)

        assert client.seek == 42
        assert client.volume == 50


class TestVolumioWebSocketClientCommands:
    """The events the client emits without waiting for an answer."""

    @pytest.mark.parametrize(
        ("method", "event"),
        [
            ("clear", "clearQueue"),
            ("mute", "mute"),
            ("next", "next"),
            ("pause", "pause"),
            ("previous", "prev"),
            ("stop", "stop"),
            ("toggle", "toggle"),
            ("unmute", "unmute"),
        ],
    )
    def test_a_bare_command(self, mocker: MockerFixture, method, event):
        """Each bare command emits its event, carrying nothing, and answers nothing."""
        client, fake = _client(mocker)

        assert getattr(client, method)() is None
        assert fake.calls == [_Call(event, None)]

    def test_play(self, mocker: MockerFixture):
        """Playing without a position carries nothing."""
        client, fake = _client(mocker)

        client.play()

        assert fake.calls == [_Call(EVENT_PLAY, None)]

    def test_play_at_a_position(self, mocker: MockerFixture):
        """Playing at a position carries it."""
        client, fake = _client(mocker)

        client.play(3)

        assert fake.calls == [_Call(EVENT_PLAY, {"value": 3})]

    def test_play_a_queue_track(self, mocker: MockerFixture):
        """A track of a queue is played at the position it knows."""
        fake = _FakeSocketIOClient(answers={EVENT_GET_QUEUE: (EVENT_PUSH_QUEUE, QUEUE_PAYLOAD)})
        client, _ = _client(mocker, fake)
        track = client.queue[0]
        fake.calls.clear()

        client.play(track)

        assert fake.calls == [_Call(EVENT_PLAY, {"value": 0})]

    def test_play_a_track_of_no_queue(self, mocker: MockerFixture):
        """A track that knows no position is refused before anything is sent."""
        logger = Mock()
        client, fake = _client(mocker, logger=logger)

        with pytest.raises(ValueError, match="does not belong to a queue"):
            client.play(QueueTrack.from_raw({"title": "So What"}))

        assert fake.calls == []
        logger.warning.assert_called_once()

    def test_play_playlist(self, mocker: MockerFixture):
        """A playlist is played by name."""
        client, fake = _client(mocker)

        client.play_playlist("jazz")

        assert fake.calls == [_Call("playPlaylist", {"name": "jazz"})]

    def test_play_playlist_as_a_model(self, mocker: MockerFixture):
        """A playlist model is played by the name it carries."""
        client, fake = _client(mocker)

        client.play_playlist(Playlist.from_name("jazz"))

        assert fake.calls == [_Call("playPlaylist", {"name": "jazz"})]

    def test_play_playlist_without_a_name(self, mocker: MockerFixture):
        """A playlist with no name is refused before anything is sent."""
        client, fake = _client(mocker)

        with pytest.raises(ValueError, match="playlist has no name"):
            client.play_playlist(Playlist.from_raw({}))

        assert fake.calls == []

    def test_the_volume_setter(self, mocker: MockerFixture):
        """Setting the volume carries the level itself, not an object holding it."""
        client, fake = _client(mocker)

        client.volume = 42

        assert fake.calls == [_Call("volume", 42)]

    @pytest.mark.parametrize("level", [-1, 101])
    def test_an_out_of_range_volume(self, mocker: MockerFixture, level):
        """A level outside 0..100 is refused before anything is sent."""
        client, fake = _client(mocker)

        with pytest.raises(ValueError, match="between 0 and 100"):
            client.volume = level

        assert fake.calls == []

    def test_the_volume_steps(self, mocker: MockerFixture):
        """The relative changes carry the increments a Volumio host understands."""
        client, fake = _client(mocker)

        client.increase_volume()
        client.decrease_volume()

        assert fake.calls == [_Call("volume", "+"), _Call("volume", "-")]

    def test_the_seek_setter(self, mocker: MockerFixture):
        """Seeking carries the number of seconds itself."""
        client, fake = _client(mocker)

        client.seek = 90

        assert fake.calls == [_Call("seek", 90)]

    def test_seek_forward(self, mocker: MockerFixture):
        """Seeking forward reads the position first and sends an absolute one."""
        client, fake = _state_client(mocker)

        client.seek_forward()

        assert fake.calls[-1] == _Call("seek", 52)

    def test_seek_backward(self, mocker: MockerFixture):
        """Seeking backward reads the position first and sends an absolute one."""
        client, fake = _state_client(mocker)

        client.seek_backward()

        assert fake.calls[-1] == _Call("seek", 32)

    def test_seek_backward_stops_at_the_start(self, mocker: MockerFixture):
        """Seeking backward never goes before the start of the track."""
        fake = _FakeSocketIOClient(
            answers={EVENT_GET_STATE: (EVENT_PUSH_STATE, {**STATE_PAYLOAD, "seek": 3000})}
        )
        client, _ = _client(mocker, fake)

        client.seek_backward()

        assert fake.calls[-1] == _Call("seek", 0)

    @pytest.mark.parametrize(
        ("method", "event"), [("randomize", "setRandom"), ("repeat", "setRepeat")]
    )
    def test_a_mode_is_set(self, mocker: MockerFixture, method, event):
        """Setting a mode carries the value, without reading the state first."""
        client, fake = _client(mocker)

        getattr(client, method)(True)

        assert fake.calls == [_Call(event, {"value": True})]

    @pytest.mark.parametrize(
        ("method", "event", "key"),
        [("randomize", "setRandom", "random"), ("repeat", "setRepeat", "repeat")],
    )
    def test_a_mode_is_toggled(self, mocker: MockerFixture, method, event, key):
        """Toggling a mode reads the state first and sends the opposite."""
        fake = _FakeSocketIOClient(
            answers={EVENT_GET_STATE: (EVENT_PUSH_STATE, {**STATE_PAYLOAD, key: True})}
        )
        client, _ = _client(mocker, fake)

        getattr(client, method)()

        assert fake.calls[-1] == _Call(event, {"value": False})


class TestVolumioWebSocketClientQueueing:
    """Adding to the queue and replacing it, which browse a container first."""

    def test_add_a_local_uri_as_itself(self, mocker: MockerFixture):
        """A URI of the local library is queued as itself, without a browse."""
        client, fake = _client(mocker)

        client.add_to_queue("mpd://NAS/track.flac")

        assert fake.calls == [
            _Call("addToQueue", {"service": "mpd", "uri": "mpd://NAS/track.flac"})
        ]

    def test_add_a_container_of_another_source(self, mocker: MockerFixture):
        """A container of another source is browsed and queued as its items."""
        client, fake = _browse_client(mocker)

        client.add_to_queue("qobuz://album/1")

        assert fake.calls[-1] == _Call(
            "addToQueue", [{"service": "mpd", "title": "jazz", "type": "song", "uri": "mpd://a"}]
        )

    def test_add_a_container_listing_nothing(self, mocker: MockerFixture):
        """A URI of another source that lists nothing is queued as itself."""
        fake = _FakeSocketIOClient(
            answers={EVENT_BROWSE_LIBRARY: (EVENT_PUSH_BROWSE_LIBRARY, EMPTY_NAVIGATION)}
        )
        client, _ = _client(mocker, fake)

        client.add_to_queue("qobuz://track/1")

        assert fake.calls[-1] == _Call("addToQueue", {"service": "qobuz", "uri": "qobuz://track/1"})

    def test_replace_with_a_local_uri(self, mocker: MockerFixture):
        """A URI of the local library replaces the queue as a single item."""
        client, fake = _client(mocker)

        client.replace_queue_and_play("mpd://NAS/album")

        assert fake.calls == [
            _Call("replaceAndPlay", {"item": {"service": "mpd", "uri": "mpd://NAS/album"}})
        ]

    def test_replace_with_a_browsed_container(self, mocker: MockerFixture):
        """A container of another source is browsed and sent as its items."""
        client, fake = _browse_client(mocker)

        client.replace_queue_and_play("qobuz://album/1")

        assert fake.calls[-1] == _Call(
            "replaceAndPlay",
            {
                "list": [
                    {"service": "mpd", "title": "jazz", "type": "song", "uri": "mpd://a"}
                ],
                "index": 0,
            },
        )

    def test_replace_at_an_index(self, mocker: MockerFixture):
        """An index browses the URI and sends the listing along with it."""
        client, fake = _browse_client(mocker)

        client.replace_queue_and_play("qobuz://album/1", 0)

        assert fake.calls[-1] == _Call(
            "replaceAndPlay",
            {
                "list": [
                    {"service": "mpd", "title": "jazz", "type": "song", "uri": "mpd://a"}
                ],
                "index": 0,
            },
        )

    def test_replace_at_an_index_the_listing_is_too_short_for(self, mocker: MockerFixture):
        """An index beyond the listing warns once and raises."""
        logger = Mock()
        client, _ = _browse_client(mocker, logger=logger)

        with pytest.raises(VolumioAPIError, match="not enough to play the one at index 5"):
            client.replace_queue_and_play("qobuz://album/1", 5)

        logger.warning.assert_called_once()

    def test_replace_at_an_index_of_a_uri_listing_nothing(self, mocker: MockerFixture):
        """Index 0 of a URI listing nothing falls back to the URI as a single item."""
        fake = _FakeSocketIOClient(
            answers={EVENT_BROWSE_LIBRARY: (EVENT_PUSH_BROWSE_LIBRARY, EMPTY_NAVIGATION)}
        )
        client, _ = _client(mocker, fake)

        client.replace_queue_and_play("qobuz://track/1", 0)

        assert fake.calls[-1] == _Call(
            "replaceAndPlay", {"item": {"service": "qobuz", "uri": "qobuz://track/1"}}
        )

    def test_replace_at_a_negative_index(self, mocker: MockerFixture):
        """A negative index is refused before anything is sent."""
        client, fake = _client(mocker)

        with pytest.raises(ValueError, match="0 or greater"):
            client.replace_queue_and_play("mpd://NAS/album", -1)

        assert fake.calls == []


class TestVolumioWebSocketClientQueueEditing:
    """The queue operations the REST API has no endpoint for."""

    def test_move_in_queue(self, mocker: MockerFixture):
        """Moving a track names the two positions the way Volumio expects."""
        client, fake = _client(mocker)

        client.move_in_queue(3, 0)

        assert fake.calls == [_Call("moveQueue", {"from": 3, "to": 0})]

    @pytest.mark.parametrize(("source", "target"), [(-1, 0), (0, -1)])
    def test_move_in_queue_refuses_a_negative_position(
        self, mocker: MockerFixture, source, target
    ):
        """A negative position is refused before anything is sent."""
        client, fake = _client(mocker)

        with pytest.raises(ValueError, match="0 or greater"):
            client.move_in_queue(source, target)

        assert fake.calls == []

    def test_remove_from_queue(self, mocker: MockerFixture):
        """Removing a track carries the position under "value", not bare."""
        client, fake = _client(mocker)

        client.remove_from_queue(2)

        assert fake.calls == [_Call("removeQueueItem", {"value": 2})]

    def test_remove_from_queue_refuses_a_negative_position(self, mocker: MockerFixture):
        """A negative position is refused before anything is sent."""
        client, fake = _client(mocker)

        with pytest.raises(ValueError, match="0 or greater"):
            client.remove_from_queue(-1)

        assert fake.calls == []

    def test_play_next(self, mocker: MockerFixture):
        """Queueing next carries only the fields that are known."""
        client, fake = _client(mocker)

        client.play_next("mpd://a", title="So What", album="Kind of Blue")
        client.play_next("mpd://b")

        assert fake.calls == [
            _Call("playNext", {"uri": "mpd://a", "title": "So What", "album": "Kind of Blue"}),
            _Call("playNext", {"uri": "mpd://b"}),
        ]

    def test_add_and_play_a_local_uri(self, mocker: MockerFixture):
        """A URI of the local library is queued as itself and played."""
        client, fake = _client(mocker)

        client.add_and_play("mpd://NAS/track.flac")

        assert fake.calls == [
            _Call("addPlay", {"service": "mpd", "uri": "mpd://NAS/track.flac"})
        ]

    def test_add_and_play_a_container(self, mocker: MockerFixture):
        """A container of another source is browsed and played as its items."""
        client, fake = _browse_client(mocker)

        client.add_and_play("qobuz://album/1")

        assert fake.calls[-1] == _Call(
            "addPlay", [{"service": "mpd", "title": "jazz", "type": "song", "uri": "mpd://a"}]
        )

    def test_save_queue_as_playlist(self, mocker: MockerFixture):
        """The queue is saved under a name, given as a string or as a playlist."""
        client, fake = _client(mocker)

        client.save_queue_as_playlist("jazz")
        client.save_queue_as_playlist(Playlist.from_name("rock"))

        assert fake.calls == [
            _Call("saveQueueToPlaylist", {"name": "jazz"}),
            _Call("saveQueueToPlaylist", {"name": "rock"}),
        ]

    def test_save_queue_as_playlist_without_a_name(self, mocker: MockerFixture):
        """A playlist with no name is refused before anything is sent."""
        client, fake = _client(mocker)

        with pytest.raises(ValueError, match="playlist has no name"):
            client.save_queue_as_playlist(Playlist.from_raw({}))

        assert fake.calls == []

    @pytest.mark.parametrize("value", [True, False])
    def test_consume(self, mocker: MockerFixture, value):
        """The consume mode carries its value."""
        client, fake = _client(mocker)

        client.consume(value)

        assert fake.calls == [_Call("setConsume", {"value": value})]

    def test_add_uids_to_queue(self, mocker: MockerFixture):
        """The identifiers are sent as the bare list Volumio expects."""
        client, fake = _client(mocker)

        client.add_uids_to_queue(["uid1", "uid2"])

        assert fake.calls == [_Call("addQueueUids", ["uid1", "uid2"])]

    def test_the_cue_events(self, mocker: MockerFixture):
        """Both cue events carry the sheet, the track number, and the service."""
        client, fake = _client(mocker)

        client.add_cue_track("mpd://sheet.cue", 3)
        client.replace_queue_with_cue_track("qobuz://sheet.cue", 1, service="qobuz")

        assert fake.calls == [
            _Call("addPlayCue", {"number": 3, "service": "mpd", "uri": "mpd://sheet.cue"}),
            _Call(
                "replaceAndPlayCue",
                {"number": 1, "service": "qobuz", "uri": "qobuz://sheet.cue"},
            ),
        ]

    def test_play_items(self, mocker: MockerFixture):
        """The items are reduced to the keys queueing reads, and the index is carried."""
        client, fake = _client(mocker)
        items = [{"uri": "mpd://a", "title": "a", "service": "mpd", "albumart": "/x"}]

        client.play_items(items, 0)

        assert fake.calls == [
            _Call(
                "playItemsList",
                {"list": [{"service": "mpd", "title": "a", "uri": "mpd://a"}], "index": 0},
            )
        ]

    def test_play_items_refuses_a_negative_index(self, mocker: MockerFixture):
        """A negative index is refused before anything is sent."""
        client, fake = _client(mocker)

        with pytest.raises(ValueError, match="0 or greater"):
            client.play_items([], -1)

        assert fake.calls == []

    def test_play_volatile(self, mocker: MockerFixture):
        """A volatile source is started at a position carried under "value"."""
        client, fake = _client(mocker)

        client.play_volatile(2)

        assert fake.calls == [_Call("volatilePlay", {"value": 2})]

    def test_play_volatile_refuses_a_negative_position(self, mocker: MockerFixture):
        """A negative position is refused before anything is sent."""
        client, fake = _client(mocker)

        with pytest.raises(ValueError, match="0 or greater"):
            client.play_volatile(-1)

        assert fake.calls == []

    def test_goto(self, mocker: MockerFixture):
        """Browsing to the artist of what is playing reads the listing back."""
        fake = _FakeSocketIOClient(
            answers={"goTo": (EVENT_PUSH_BROWSE_LIBRARY, NAVIGATION_PAYLOAD)}
        )
        client, _ = _client(mocker, fake)

        results = client.goto("artist", "Miles Davis")

        assert [item.title for item in results.items] == ["jazz"]
        assert fake.calls == [_Call("goTo", {"type": "artist", "value": "Miles Davis"})]


class TestVolumioWebSocketClientPlaylistEditing:
    """Creating, editing and reading the saved playlists."""

    def test_create_and_delete(self, mocker: MockerFixture):
        """A playlist is created and deleted by name."""
        client, fake = _client(mocker)

        client.create_playlist("jazz")
        client.delete_playlist(Playlist.from_name("rock"))

        assert fake.calls == [
            _Call("createPlaylist", {"name": "jazz"}),
            _Call("deletePlaylist", {"name": "rock"}),
        ]

    def test_add_and_remove_an_item(self, mocker: MockerFixture):
        """An item carries the playlist, the URI, and the service it belongs to."""
        client, fake = _client(mocker)

        client.add_to_playlist("jazz", "qobuz://track/1")
        client.remove_from_playlist("jazz", "mpd://NAS/a.flac")

        assert fake.calls == [
            _Call(
                "addToPlaylist",
                {"name": "jazz", "service": "qobuz", "uri": "qobuz://track/1"},
            ),
            _Call(
                "removeFromPlaylist",
                {"name": "jazz", "service": "mpd", "uri": "mpd://NAS/a.flac"},
            ),
        ]

    def test_an_explicit_service_wins(self, mocker: MockerFixture):
        """A service given by the caller is not derived from the URI."""
        client, fake = _client(mocker)

        client.add_to_playlist("jazz", "mpd://a", service="upnp")

        assert fake.calls[-1].payload["service"] == "upnp"

    def test_editing_a_playlist_without_a_name(self, mocker: MockerFixture):
        """A playlist with no name is refused before anything is sent."""
        client, fake = _client(mocker)

        with pytest.raises(ValueError, match="playlist has no name"):
            client.add_to_playlist(Playlist.from_raw({}), "mpd://a")

        assert fake.calls == []

    def test_enqueue_playlist(self, mocker: MockerFixture):
        """A playlist is appended to the queue by name."""
        client, fake = _client(mocker)

        client.enqueue_playlist("jazz")

        assert fake.calls == [_Call("enqueue", {"name": "jazz"})]

    def test_import_service_playlists(self, mocker: MockerFixture):
        """The import carries nothing."""
        client, fake = _client(mocker)

        client.import_service_playlists()

        assert fake.calls == [_Call("importServicePlaylists", None)]

    def test_get_playlist_content(self, mocker: MockerFixture):
        """The tracks are read out of the one list per source the host groups them in."""
        fake = _FakeSocketIOClient(
            answers={
                "getPlaylistContent": (
                    "pushPlaylistContent",
                    {"name": "jazz", "lists": [[{"title": "So What", "uri": "mpd://a"}]]},
                )
            }
        )
        client, _ = _client(mocker, fake)

        content = client.get_playlist_content("jazz")

        assert content.name == "jazz"
        assert [track.title for track in content] == ["So What"]


class TestVolumioWebSocketClientFavourites:
    """The favourites and the web radios of the user."""

    def test_add_to_favourites(self, mocker: MockerFixture):
        """A favourite carries its service, and only the fields that are known."""
        client, fake = _client(mocker)

        client.add_to_favourites("qobuz://track/1", title="So What", albumart="/cover")
        client.add_to_favourites("mpd://NAS/a.flac")

        assert fake.calls == [
            _Call(
                "addToFavourites",
                {
                    "service": "qobuz",
                    "uri": "qobuz://track/1",
                    "title": "So What",
                    "albumart": "/cover",
                },
            ),
            _Call("addToFavourites", {"service": "mpd", "uri": "mpd://NAS/a.flac"}),
        ]

    def test_remove_from_favourites(self, mocker: MockerFixture):
        """Removing a favourite carries the URI and its service."""
        client, fake = _client(mocker)

        client.remove_from_favourites("qobuz://track/1")

        assert fake.calls == [
            _Call("removeFromFavourites", {"service": "qobuz", "uri": "qobuz://track/1"})
        ]

    def test_an_explicit_service_wins(self, mocker: MockerFixture):
        """A service given by the caller is not derived from the URI."""
        client, fake = _client(mocker)

        client.add_to_favourites("mpd://a", service="upnp")

        assert fake.calls[-1].payload["service"] == "upnp"

    def test_play_favourites(self, mocker: MockerFixture):
        """The favourites play from the start, or from a named one."""
        client, fake = _client(mocker)

        client.play_favourites()
        client.play_favourites("So What")

        assert fake.calls == [
            _Call("playFavourites", None),
            _Call("playFavourites", {"name": "So What"}),
        ]

    def test_the_radio_favourites(self, mocker: MockerFixture):
        """A web radio is made a favourite, played, and removed."""
        client, fake = _client(mocker)

        client.add_radio_favourite("http://stream/1")
        client.play_radio_favourites()
        client.remove_radio_favourite("http://stream/1")
        client.remove_radio_favourite("http://stream/2", name="Jazz FM")

        assert fake.calls == [
            _Call("addToRadioFavourites", {"uri": "http://stream/1"}),
            _Call("playRadioFavourites", None),
            _Call("removeFromRadioFavourites", {"uri": "http://stream/1"}),
            _Call(
                "removeFromRadioFavourites",
                {"name": "Jazz FM", "uri": "http://stream/2"},
            ),
        ]

    def test_the_web_radios_of_the_user(self, mocker: MockerFixture):
        """A web radio is saved with its URL and deleted by name alone."""
        client, fake = _client(mocker)

        client.add_web_radio("Jazz FM", "http://stream/1")
        client.remove_web_radio("Jazz FM")

        assert fake.calls == [
            _Call("addWebRadio", {"name": "Jazz FM", "uri": "http://stream/1"}),
            _Call("removeWebRadio", {"name": "Jazz FM"}),
        ]


class TestVolumioWebSocketClientBrowseSources:
    """The browse roots, the menu, and the search across every source."""

    _SOURCES = [
        {
            "albumart": "/albumart?sourceicon=x.png",
            "name": "Playlists",
            "uri": "playlists",
            "plugin_type": "music_service",
            "plugin_name": "mpd",
        }
    ]

    def test_browse_sources(self, mocker: MockerFixture):
        """The sources are answered as a bare array, which the model wraps."""
        fake = _FakeSocketIOClient(
            answers={"getBrowseSources": ("pushBrowseSources", self._SOURCES)}
        )
        client, _ = _client(mocker, fake)

        sources = client.browse_sources

        assert [source.name for source in sources] == ["Playlists"]
        assert sources[0].plugin_type == "music_service"

    def test_menu_items(self, mocker: MockerFixture):
        """The menu is answered as a bare array, which the model wraps."""
        fake = _FakeSocketIOClient(
            answers={"getMenuItems": ("pushMenuItems", [{"id": "mymusic", "name": "Sources"}])}
        )
        client, _ = _client(mocker, fake)

        assert [item.id for item in client.menu_items] == ["mymusic"]

    def test_last_browse(self, mocker: MockerFixture):
        """The listing pushed last is read as a browse result."""
        fake = _FakeSocketIOClient(
            answers={
                "getLastPushedBrowseLibrary": (EVENT_PUSH_BROWSE_LIBRARY, NAVIGATION_PAYLOAD)
            }
        )
        client, _ = _client(mocker, fake)

        assert [item.title for item in client.last_browse.items] == ["jazz"]

    def test_super_search(self, mocker: MockerFixture):
        """The search across every source carries the query and reads the envelope."""
        fake = _FakeSocketIOClient(
            answers={"superSearch": (EVENT_PUSH_BROWSE_LIBRARY, NAVIGATION_PAYLOAD)}
        )
        client, fake = _client(mocker, fake)

        results = client.super_search("miles")

        assert [item.title for item in results.items] == ["jazz"]
        assert fake.calls == [_Call("superSearch", {"value": "miles"})]

    def test_regenerate_thumbnails(self, mocker: MockerFixture):
        """Rebuilding the thumbnails carries nothing."""
        client, fake = _client(mocker)

        client.regenerate_thumbnails()

        assert fake.calls == [_Call("regenerateThumbnails", None)]


class TestVolumioWebSocketClientSleepAndAlarms:
    """The sleep timer and the alarms, both served by the alarm-clock plugin."""

    def test_sleep_timer(self, mocker: MockerFixture):
        """The timer is read, and its time parsed as the delay it is."""
        fake = _FakeSocketIOClient(
            answers={
                "getSleep": (
                    "pushSleep",
                    {"enabled": True, "time": "0:30", "action": {"val": "stop"}},
                )
            }
        )
        client, _ = _client(mocker, fake)

        timer = client.sleep_timer

        assert timer.enabled is True
        assert timer.delay == timedelta(minutes=30)

    @pytest.mark.parametrize(
        ("delay", "expected"),
        [
            (timedelta(minutes=30), {"enabled": True, "time": "0:30"}),
            (timedelta(hours=1, minutes=5), {"enabled": True, "time": "1:05"}),
            (timedelta(hours=2), {"enabled": True, "time": "2:00"}),
            (timedelta(seconds=90), {"enabled": True, "time": "0:01"}),
            (None, {"enabled": False, "time": "0:00"}),
        ],
    )
    def test_set_sleep_timer(self, mocker: MockerFixture, delay, expected):
        """A duration is rendered to the "H:MM" a Volumio host reads as a delay."""
        client, fake = _client(mocker)

        client.set_sleep_timer(delay)

        assert fake.calls == [_Call("setSleep", expected)]

    def test_set_sleep_timer_refuses_a_negative_delay(self, mocker: MockerFixture):
        """A negative delay is refused before anything is sent."""
        logger = Mock()
        client, fake = _client(mocker, logger=logger)

        with pytest.raises(ValueError, match="must not be negative"):
            client.set_sleep_timer(timedelta(minutes=-5))

        assert fake.calls == []
        logger.warning.assert_called_once()

    def test_alarms(self, mocker: MockerFixture):
        """The alarms are answered as a bare array, which the model wraps."""
        fake = _FakeSocketIOClient(
            answers={
                "getAlarms": (
                    "pushAlarm",
                    [{"id": 1, "name": "Weekday", "enabled": True, "time": "07:30",
                      "playlist": "jazz"}],
                )
            }
        )
        client, _ = _client(mocker, fake)

        alarms = client.alarms

        assert len(alarms) == 1
        assert alarms[0].playlist == "jazz"

    def test_a_host_with_no_alarm(self, mocker: MockerFixture):
        """A host reporting no alarm is an empty collection."""
        fake = _FakeSocketIOClient(answers={"getAlarms": ("pushAlarm", [])})
        client, _ = _client(mocker, fake)

        assert len(client.alarms) == 0

    def test_set_alarms_replaces_the_whole_set(self, mocker: MockerFixture):
        """The alarms are sent as the list the Volumio API replaces its set with."""
        client, fake = _client(mocker)
        alarms = [
            Alarm.from_raw({"id": 1, "enabled": True, "time": "07:30", "playlist": "jazz"}),
            Alarm.from_raw({"id": 2, "enabled": False, "time": "09:00", "playlist": "rock"}),
        ]

        client.set_alarms(alarms)

        assert fake.calls == [
            _Call(
                "saveAlarm",
                [
                    {"enabled": True, "id": 1, "playlist": "jazz", "time": "07:30"},
                    {"enabled": False, "id": 2, "playlist": "rock", "time": "09:00"},
                ],
            )
        ]

    def test_set_alarms_with_an_empty_set(self, mocker: MockerFixture):
        """Sending no alarm clears them all."""
        client, fake = _client(mocker)

        client.set_alarms([])

        assert fake.calls == [_Call("saveAlarm", [])]


class TestVolumioWebSocketClientAudioOutputs:
    """The audio outputs, the output devices, and the input sources."""

    _DEVICES = {
        "devices": {
            "active": {"name": "HDMI Out", "id": "0"},
            "available": [{"id": "0", "name": "HDMI Out"}, {"id": "1", "name": "Headphones"}],
        },
        "i2s": False,
    }

    def test_output_devices(self, mocker: MockerFixture):
        """The devices are read out of the envelope the host answers with."""
        fake = _FakeSocketIOClient(
            answers={"getOutputDevices": ("pushOutputDevices", self._DEVICES)}
        )
        client, _ = _client(mocker, fake)

        devices = client.output_devices

        assert devices.active is not None
        assert devices.active.name == "HDMI Out"
        assert [device.name for device in devices] == ["HDMI Out", "Headphones"]

    def test_extended_output_devices(self, mocker: MockerFixture):
        """The detailed devices come back through the same envelope."""
        fake = _FakeSocketIOClient(
            answers={"getExtendedOutputDevices": ("pushExtendedOutputDevices", self._DEVICES)}
        )
        client, _ = _client(mocker, fake)

        assert len(client.extended_output_devices) == 2

    def test_audio_outputs(self, mocker: MockerFixture):
        """The outputs are read from the aliased key of the answer."""
        fake = _FakeSocketIOClient(
            answers={
                "getAudioOutputs": (
                    "pushAudioOutputs",
                    {"availableOutputs": [{"id": "0", "name": "Living room", "volume": 40}]},
                )
            }
        )
        client, _ = _client(mocker, fake)

        outputs = client.audio_outputs

        assert [output.name for output in outputs] == ["Living room"]
        assert outputs[0].volume == 40

    def test_input_sources(self, mocker: MockerFixture):
        """A host with no input source answers an empty mapping."""
        fake = _FakeSocketIOClient(answers={"getInputSources": ("pushInputSources", {})})
        client, _ = _client(mocker, fake)

        assert client.input_sources.raw == {}

    def test_set_output_device(self, mocker: MockerFixture):
        """The device is chosen by identifier, with the mixer only when given."""
        client, fake = _client(mocker)

        client.set_output_device("1")
        client.set_output_device("1", mixer="Digital")

        assert fake.calls == [
            _Call("setOutputDevices", {"device": "1"}),
            _Call("setOutputDevices", {"device": "1", "mixer": "Digital"}),
        ]

    @pytest.mark.parametrize(
        ("method", "event"),
        [
            ("audio_output_pause", "audioOutputPause"),
            ("audio_output_play", "audioOutputPlay"),
            ("disable_audio_output", "disableAudioOutput"),
            ("enable_audio_output", "enableAudioOutput"),
        ],
    )
    def test_the_audio_output_commands(self, mocker: MockerFixture, method, event):
        """Each command names the output it acts on."""
        client, fake = _client(mocker)

        getattr(client, method)("0")

        assert fake.calls == [_Call(event, {"id": "0"})]

    def test_set_audio_output_volume(self, mocker: MockerFixture):
        """The volume of one output carries the identifier and the level."""
        client, fake = _client(mocker)

        client.set_audio_output_volume("0", 42)

        assert fake.calls == [_Call("setAudioOutputVolume", {"id": "0", "volume": 42})]

    @pytest.mark.parametrize("level", [-1, 101])
    def test_an_out_of_range_output_volume(self, mocker: MockerFixture, level):
        """A level outside 0..100 is refused before anything is sent."""
        client, fake = _client(mocker)

        with pytest.raises(ValueError, match="between 0 and 100"):
            client.set_audio_output_volume("0", level)

        assert fake.calls == []


class TestVolumioWebSocketClientLibrary:
    """Scanning the collection and choosing the music sources."""

    def test_music_sources(self, mocker: MockerFixture):
        """The sources are answered as a bare array, which the model wraps."""
        fake = _FakeSocketIOClient(
            answers={
                "getMyMusicPlugins": (
                    "pushMyMusicPlugins",
                    [{"name": "upnp", "prettyName": "UPNP Renderer", "enabled": True}],
                )
            }
        )
        client, _ = _client(mocker, fake)

        sources = client.music_sources

        assert [source.name for source in sources] == ["upnp"]
        assert sources[0].pretty_name == "UPNP Renderer"

    def test_set_music_source_enabled(self, mocker: MockerFixture):
        """A source is enabled or disabled by name."""
        client, fake = _client(mocker)

        client.set_music_source_enabled("upnp", True)

        assert fake.calls == [
            _Call("enableDisableMyMusicPlugin", {"name": "upnp", "enabled": True})
        ]

    def test_the_scan_commands(self, mocker: MockerFixture):
        """The scans carry nothing, or the URI or service they are scoped to."""
        client, fake = _client(mocker)

        client.rescan_library()
        client.update_all_metadata()
        client.update_library()
        client.update_library("mpd://NAS/Music")
        client.update_service_tracklist("qobuz")

        assert fake.calls == [
            _Call("rescanDb", None),
            _Call("updateAllMetadata", None),
            _Call("updateDb", None),
            _Call("updateDb", "mpd://NAS/Music"),
            _Call("serviceUpdateTracklist", "qobuz"),
        ]


class TestVolumioWebSocketClientPower:
    """The identity of the host and the ways it can be powered down."""

    def test_device_info(self, mocker: MockerFixture):
        """The identity carries the name and the hardware identifier."""
        fake = _FakeSocketIOClient(
            answers={"getDeviceInfo": ("pushDeviceInfo", {"uuid": "5dc4", "name": "kitchen"})}
        )
        client, _ = _client(mocker, fake)

        info = client.device_info

        assert info.name == "kitchen"
        assert info.uuid == "5dc4"

    def test_device_name(self, mocker: MockerFixture):
        """The name is read on its own, and assigning to it renames the host."""
        fake = _FakeSocketIOClient(
            answers={"getDeviceName": ("pushDeviceName", {"name": "kitchen"})}
        )
        client, _ = _client(mocker, fake)

        assert client.device_name == "kitchen"

        client.device_name = "living room"

        assert fake.calls[-1] == _Call("setDeviceName", {"name": "living room"})

    def test_device_uuid(self, mocker: MockerFixture):
        """The hardware identifier is read on its own."""
        fake = _FakeSocketIOClient(
            answers={"getDeviceHWUUID": ("pushDeviceHWUUID", "5dc4ca49")}
        )
        client, _ = _client(mocker, fake)

        assert client.device_uuid == "5dc4ca49"

    def test_a_host_reporting_no_name(self, mocker: MockerFixture):
        """A host answering without the field reports None rather than failing."""
        fake = _FakeSocketIOClient(
            answers={
                "getDeviceName": ("pushDeviceName", {}),
            }
        )
        client, _ = _client(mocker, fake)

        assert client.device_name is None

    def test_power_modes(self, mocker: MockerFixture):
        """The power modes are read from their aliases."""
        fake = _FakeSocketIOClient(
            answers={
                "getShutdownOrStandbyMode": (
                    "pushShutdownOrStandbyMode",
                    {"hasPowerOffMode": True, "hasStandbyMode": False},
                )
            }
        )
        client, _ = _client(mocker, fake)

        modes = client.power_modes

        assert modes.has_power_off_mode is True
        assert modes.has_standby_mode is False


    def test_a_hardware_identifier_that_is_not_a_string(self, mocker: MockerFixture):
        """The identifier comes back bare; an object instead of it is refused."""
        fake = _FakeSocketIOClient(
            answers={"getDeviceHWUUID": ("pushDeviceHWUUID", {"uuid": "5dc4"})}
        )
        client, _ = _client(mocker, fake)

        with pytest.raises(VolumioAPIError, match="Expected JSON string"):
            _ = client.device_uuid

    @pytest.mark.parametrize(
        ("method", "event"),
        [("reboot", "reboot"), ("shutdown", "shutdown"), ("standby", "standby")],
    )
    def test_the_power_commands(self, mocker: MockerFixture, method, event):
        """Each power command carries nothing and answers nothing."""
        client, fake = _client(mocker)

        assert getattr(client, method)() is None
        assert fake.calls == [_Call(event, None)]


class TestVolumioWebSocketClientPlugins:
    """The plugins installed on the host, and their configuration pages."""

    def test_installed_plugins(self, mocker: MockerFixture):
        """The plugins are answered as a bare array, which the model wraps."""
        fake = _FakeSocketIOClient(
            answers={
                "getInstalledPlugins": (
                    "pushInstalledPlugins",
                    [{"name": "spop", "prettyName": "Spotify", "enabled": True}],
                )
            }
        )
        client, _ = _client(mocker, fake)

        plugins = client.installed_plugins

        assert [plugin.name for plugin in plugins] == ["spop"]
        assert plugins[0].pretty_name == "Spotify"

    def test_a_host_with_no_plugin(self, mocker: MockerFixture):
        """A host reporting no plugin is an empty collection."""
        fake = _FakeSocketIOClient(
            answers={"getInstalledPlugins": ("pushInstalledPlugins", [])}
        )
        client, _ = _client(mocker, fake)

        assert len(client.installed_plugins) == 0

    def test_get_plugin_config(self, mocker: MockerFixture):
        """The configuration page is asked for by "category/name"."""
        fake = _FakeSocketIOClient(
            answers={
                "getUiConfig": (
                    "pushUiConfig",
                    {"page": {"label": "System Settings"}, "sections": [{"id": "language"}]},
                )
            }
        )
        client, fake = _client(mocker, fake)

        config = client.get_plugin_config("system_controller/system")

        assert config.page == {"label": "System Settings"}
        assert fake.calls == [_Call("getUiConfig", {"page": "system_controller/system"})]

    def test_dsp_config(self, mocker: MockerFixture):
        """The DSP page comes back through its own event."""
        fake = _FakeSocketIOClient(
            answers={"getDSPUiConfig": ("pushDSPUiConfig", {"page": {"label": "DSP"}})}
        )
        client, _ = _client(mocker, fake)

        assert client.dsp_config.page == {"label": "DSP"}

    def test_manage_plugin(self, mocker: MockerFixture):
        """The plugin manager answers with the plugins as they stand after the action."""
        fake = _FakeSocketIOClient(
            answers={"pluginManager": ("pushInstalledPlugins", [{"name": "spop"}])}
        )
        client, fake = _client(mocker, fake)

        plugins = client.manage_plugin("enable", "music_service", "spop")

        assert [plugin.name for plugin in plugins] == ["spop"]
        assert fake.calls == [
            _Call(
                "pluginManager",
                {"category": "music_service", "name": "spop", "action": "enable"},
            )
        ]

    @pytest.mark.parametrize(
        ("method", "event"),
        [
            ("disable_plugin", "disablePlugin"),
            ("enable_plugin", "enablePlugin"),
            ("uninstall_plugin", "unInstallPlugin"),
            ("update_plugin", "updatePlugin"),
        ],
    )
    def test_the_plugin_commands(self, mocker: MockerFixture, method, event):
        """Each command names the plugin by category and name."""
        client, fake = _client(mocker)

        getattr(client, method)("music_service", "spop")

        assert fake.calls == [_Call(event, {"category": "music_service", "name": "spop"})]

    def test_modify_plugin_status(self, mocker: MockerFixture):
        """Enabling in one call carries the flag beside the plugin."""
        client, fake = _client(mocker)

        client.modify_plugin_status("music_service", "spop", True)

        assert fake.calls == [
            _Call(
                "modifyPluginStatus",
                {"category": "music_service", "name": "spop", "enabled": True},
            )
        ]

    def test_install_plugin(self, mocker: MockerFixture):
        """Installing carries the URL and the confirmation the host expects."""
        client, fake = _client(mocker)

        client.install_plugin("http://plugins/spop.zip")

        assert fake.calls == [
            _Call("installPlugin", {"url": "http://plugins/spop.zip", "confirm": True})
        ]

    def test_call_plugin_method(self, mocker: MockerFixture):
        """The generic call carries the endpoint, the method, and its arguments."""
        client, fake = _client(mocker)

        client.call_plugin_method("music_service/mpd", "rescanDb")
        client.call_plugin_method("miscellanea/alarm", "setSleep", {"time": "0:30"})

        assert fake.calls == [
            _Call("callMethod", {"endpoint": "music_service/mpd", "method": "rescanDb",
                                 "data": {}}),
            _Call("callMethod", {"endpoint": "miscellanea/alarm", "method": "setSleep",
                                 "data": {"time": "0:30"}}),
        ]


class TestVolumioWebSocketClientNetworkAndShares:
    """The network interfaces, the wireless networks, the shares, and the USB drives."""

    def test_network_info(self, mocker: MockerFixture):
        """The interfaces are answered as a bare array, which the model wraps."""
        fake = _FakeSocketIOClient(
            answers={
                "getInfoNetwork": (
                    "pushInfoNetwork",
                    [{"type": "Wired", "ip": "192.168.1.122", "status": "connected"}],
                )
            }
        )
        client, _ = _client(mocker, fake)

        info = client.network_info

        assert len(info) == 1
        assert info[0].ip == "192.168.1.122"

    def test_shares(self, mocker: MockerFixture):
        """The shares are answered as a bare array, which the model wraps."""
        fake = _FakeSocketIOClient(
            answers={"getListShares": ("pushListShares", [{"id": "a", "name": "NAS"}])}
        )
        client, _ = _client(mocker, fake)

        assert [share.name for share in client.shares] == ["NAS"]

    def test_get_share(self, mocker: MockerFixture):
        """One share is read by identifier."""
        fake = _FakeSocketIOClient(
            answers={"getInfoShare": ("pushInfoShare", {"id": "a", "name": "NAS",
                                                        "fstype": "cifs"})}
        )
        client, fake = _client(mocker, fake)

        share = client.get_share("a")

        assert share.fstype == "cifs"
        assert fake.calls == [_Call("getInfoShare", {"id": "a"})]

    def test_add_edit_and_delete_a_share(self, mocker: MockerFixture):
        """A share is mounted with its options, changed, and unmounted."""
        client, fake = _client(mocker)

        client.add_share("NAS", "192.168.1.2/Music", "cifs", username="guest")
        client.edit_share("a", name="NAS2")
        client.delete_share("a")

        assert fake.calls == [
            _Call(
                "addShare",
                {"name": "NAS", "path": "192.168.1.2/Music", "fstype": "cifs",
                 "username": "guest"},
            ),
            _Call("editShare", {"id": "a", "name": "NAS2"}),
            _Call("deleteShare", {"id": "a"}),
        ]

    def test_discover_network_shares(self, mocker: MockerFixture):
        """The discovery answers with whatever the host found."""
        fake = _FakeSocketIOClient(
            answers={
                "getNetworkSharesDiscovery": (
                    "pushNetworkSharesDiscovery",
                    {"nas": [{"name": "NAS"}]},
                )
            }
        )
        client, _ = _client(mocker, fake)

        assert client.discover_network_shares() == {"nas": [{"name": "NAS"}]}

    def test_usb_drives_and_safe_removal(self, mocker: MockerFixture):
        """The drives are read, and one is unmounted by name."""
        fake = _FakeSocketIOClient(
            answers={"listUsbDrives": ("pushListUsbDrives", [{"name": "USB"}])}
        )
        client, fake = _client(mocker, fake)

        drives = client.usb_drives
        client.safe_remove_drive("USB")

        assert [drive.name for drive in drives] == ["USB"]
        assert fake.calls[-1] == _Call("safeRemoveDrive", {"name": "USB"})

    def test_delete_folder(self, mocker: MockerFixture):
        """A folder is deleted by the path the host nests under "item"."""
        client, fake = _client(mocker)

        client.delete_folder("mpd://NAS/Old")

        assert fake.calls == [_Call("deleteFolder", {"item": {"path": "mpd://NAS/Old"}})]

    def test_the_wireless_networks(self, mocker: MockerFixture):
        """Both the scan and the cache answer with the networks the host can see."""
        networks = {"available": [{"ssid": "home", "signal": 70}]}
        fake = _FakeSocketIOClient(
            answers={
                "getWirelessNetworks": ("pushWirelessNetworks", networks),
                "getWirelessNetworksCache": ("pushWirelessNetworksCache", networks),
            }
        )
        client, _ = _client(mocker, fake)

        assert [n.ssid for n in client.wireless_networks] == ["home"]
        assert [n.ssid for n in client.wireless_networks_cache] == ["home"]

    def test_save_wireless_settings(self, mocker: MockerFixture):
        """Joining a network carries the name and the password, empty when open."""
        client, fake = _client(mocker)

        client.save_wireless_settings("home", "hunter2")
        client.save_wireless_settings("open")

        assert fake.calls == [
            _Call("saveWirelessNetworkSettings", {"ssid": "home", "password": "hunter2"}),
            _Call("saveWirelessNetworkSettings", {"ssid": "open", "password": ""}),
        ]


class TestVolumioWebSocketClientUiPreferences:
    """The look, the language, the time zone, and the other host preferences."""

    def test_ui_settings(self, mocker: MockerFixture):
        """The look of the interface is parsed."""
        fake = _FakeSocketIOClient(
            answers={
                "getUiSettings": ("pushUiSettings", {"color": "#000", "language": "en",
                                                     "theme": "default"})
            }
        )
        client, _ = _client(mocker, fake)

        settings = client.ui_settings

        assert settings.color == "#000"
        assert settings.theme == "default"

    def test_languages_and_set_language(self, mocker: MockerFixture):
        """The languages are read, and one is chosen by code."""
        fake = _FakeSocketIOClient(
            answers={
                "getAvailableLanguages": (
                    "pushAvailableLanguages",
                    {
                        "defaultLanguage": {"language": "English", "code": "en"},
                        "available": [{"language": "Italiano", "code": "it"}],
                    },
                )
            }
        )
        client, fake = _client(mocker, fake)

        languages = client.languages
        client.set_language("it", "Italiano")
        client.set_language("fr")

        assert languages.default_language is not None
        assert languages.default_language.code == "en"
        assert [lang.code for lang in languages] == ["it"]
        assert fake.calls[-2:] == [
            _Call("setLanguage", {"defaultLanguage": {"code": "it", "language": "Italiano"}}),
            _Call("setLanguage", {"defaultLanguage": {"code": "fr", "language": "fr"}}),
        ]

    def test_the_timezone(self, mocker: MockerFixture):
        """The zone is read as a bare string, and assigning to it moves the host."""
        fake = _FakeSocketIOClient(
            answers={
                "getCurrentTimezone": ("pushCurrentTimezone", "Europe/Rome"),
                "getAvailableTimezones": ("pushAvailableTimezones", ["Europe/Rome", "UTC"]),
            }
        )
        client, fake = _client(mocker, fake)

        assert client.timezone == "Europe/Rome"
        assert list(client.available_timezones) == ["Europe/Rome", "UTC"]

        client.timezone = "UTC"

        assert fake.calls[-1] == _Call("setTimezone", {"timeZone": "UTC"})

    def test_backgrounds(self, mocker: MockerFixture):
        """The background in use is read beside the available ones."""
        fake = _FakeSocketIOClient(
            answers={
                "getBackgrounds": (
                    "pushBackgrounds",
                    {
                        "current": {"name": "Darkness", "path": "darkness.jpg"},
                        "available": [{"name": "Aurora", "path": "aurora.jpg"}],
                    },
                )
            }
        )
        client, fake = _client(mocker, fake)

        backgrounds = client.backgrounds
        client.set_background("Aurora", "aurora.jpg")
        client.set_background("Darkness")
        client.delete_background("Aurora")

        assert backgrounds.current is not None
        assert backgrounds.current.name == "Darkness"
        assert [b.name for b in backgrounds] == ["Aurora"]
        assert fake.calls[-3:] == [
            _Call("setBackgrounds", {"name": "Aurora", "path": "aurora.jpg"}),
            _Call("setBackgrounds", {"name": "Darkness"}),
            _Call("deleteBackground", {"name": "Aurora"}),
        ]

    def test_privacy_settings(self, mocker: MockerFixture):
        """The statistics flag is read from its alias."""
        fake = _FakeSocketIOClient(
            answers={"getPrivacySettings": ("pushPrivacySettings",
                                            {"allowUIStatistics": False})}
        )
        client, _ = _client(mocker, fake)

        assert client.privacy_settings.allow_ui_statistics is False

    def test_infinity_playback(self, mocker: MockerFixture):
        """The setting is read, and turned on."""
        fake = _FakeSocketIOClient(
            answers={"getInfinityPlayback": ("pushInfinityPlayback",
                                             {"available": True, "enabled": False})}
        )
        client, fake = _client(mocker, fake)

        playback = client.infinity_playback
        client.set_infinity_playback(True)

        assert playback.available is True
        assert playback.enabled is False
        assert fake.calls[-1] == _Call("setInfinityPlayback", {"enabled": True})

    def test_experience_settings(self, mocker: MockerFixture):
        """The setting is read, and the full set of options chosen."""
        fake = _FakeSocketIOClient(
            answers={
                "getExperienceAdvancedSettings": (
                    "pushExperienceAdvancedSettings",
                    {
                        "options": [{"id": True, "label": "Full"}],
                        "status": {"id": False, "label": "Simplified"},
                    },
                )
            }
        )
        client, fake = _client(mocker, fake)

        settings = client.experience_settings
        client.set_experience_settings(True)

        assert settings.advanced is False
        assert fake.calls[-1] == _Call("setExperienceAdvancedSettings", True)


class TestVolumioWebSocketClientSystemAdministration:
    """Updates, backups, multiroom, and the two members that refuse to run."""

    def test_automatic_update_enabled(self, mocker: MockerFixture):
        """The flag is answered bare, and read as the boolean it is."""
        fake = _FakeSocketIOClient(
            answers={"getAutomaticUpdateEnabled": ("pushAutomaticUpdateEnabled", False)}
        )
        client, _ = _client(mocker, fake)

        assert client.automatic_update_enabled is False

    def test_an_automatic_update_flag_that_is_not_a_boolean(self, mocker: MockerFixture):
        """Anything but a boolean is refused."""
        fake = _FakeSocketIOClient(
            answers={"getAutomaticUpdateEnabled": ("pushAutomaticUpdateEnabled", "yes")}
        )
        client, _ = _client(mocker, fake)

        with pytest.raises(VolumioAPIError, match="Expected JSON boolean"):
            _ = client.automatic_update_enabled

    def test_the_updater_channel(self, mocker: MockerFixture):
        """The channel is read beside the available ones, and one is chosen."""
        fake = _FakeSocketIOClient(
            answers={
                "getUpdaterChannel": (
                    "pushUpdaterChannel",
                    {"availableChannels": ["stable", "test"], "currentChannel": "stable"},
                )
            }
        )
        client, fake = _client(mocker, fake)

        channel = client.updater_channel
        client.updater_channel = "test"

        assert channel.current_channel == "stable"
        assert channel.available_channels == ["stable", "test"]
        assert fake.calls[-1] == _Call("setUpdaterChannel", {"channel": "test"})

    def test_the_update_commands(self, mocker: MockerFixture):
        """Checking and installing carry the flags the host expects."""
        client, fake = _client(mocker)

        client.check_for_update()
        client.check_update_cache()
        client.update()
        client.update(ignore_integrity_check=True)

        assert fake.calls == [
            _Call("updateCheck", {"hideModal": True}),
            _Call("updateCheckCache", None),
            _Call("update", {"ignoreIntegrityCheck": False}),
            _Call("update", {"ignoreIntegrityCheck": True}),
        ]

    def test_backup_and_restore(self, mocker: MockerFixture):
        """A backup is read and handed back to be restored."""
        fake = _FakeSocketIOClient(answers={"getBackup": ("pushBackup", {"playlist": []})})
        client, fake = _client(mocker, fake)

        backup = client.backup()
        client.restore_backup(backup)
        client.restore_config()

        assert backup == {"playlist": []}
        assert fake.calls[-2:] == [
            _Call("manageBackup", {"playlist": []}),
            _Call("restoreConfig", None),
        ]

    def test_install_to_disk(self, mocker: MockerFixture):
        """Writing to the internal storage carries nothing."""
        client, fake = _client(mocker)

        client.install_to_disk()

        assert fake.calls == [_Call("installToDisk", None)]

    def test_multiroom(self, mocker: MockerFixture):
        """The configuration is read, changed, and the role chosen."""
        fake = _FakeSocketIOClient(
            answers={
                "getMultiroom": ("pushMultiroom", {"enabled": True, "mode": "server"}),
                "setMultiroom": ("pushMultiroom", {"enabled": False, "mode": "single"}),
            }
        )
        client, fake = _client(mocker, fake)

        current = client.multiroom
        changed = client.set_multiroom({"enabled": False})
        client.set_as_multiroom_client("192.168.1.2")
        client.set_as_multiroom_server()
        client.set_as_multiroom_single()
        client.write_multiroom({"enabled": False})

        assert current.mode == "server"
        assert changed.mode == "single"
        assert fake.calls[-4:] == [
            _Call("setAsMultiroomClient", {"server": "192.168.1.2"}),
            _Call("setAsMultiroomServer", None),
            _Call("setAsMultiroomSingle", None),
            _Call("writeMultiroom", {"enabled": False}),
        ]

    def test_factory_reset_refuses_to_run(self, mocker: MockerFixture):
        """The reset is deliberately not implemented, and says how to mean it."""
        client, fake = _client(mocker)

        with pytest.raises(NotImplementedError) as exc_info:
            client.factory_reset()

        assert "deliberately not implemented" in str(exc_info.value)
        assert 'client.emit("factoryReset")' in str(exc_info.value)
        assert fake.calls == []

    def test_delete_user_data_refuses_to_run(self, mocker: MockerFixture):
        """Erasing the user data is deliberately not implemented."""
        client, fake = _client(mocker)

        with pytest.raises(NotImplementedError) as exc_info:
            client.delete_user_data()

        assert "deliberately not implemented" in str(exc_info.value)
        assert 'client.emit("deleteUserData")' in str(exc_info.value)
        assert fake.calls == []

    def test_the_disabled_events_are_still_named(self, mocker: MockerFixture):
        """Both events keep their constant, so emit() remains the way to mean it."""
        client, fake = _client(mocker)

        client.emit(EVENT_FACTORY_RESET)
        client.emit(EVENT_DELETE_USER_DATA)

        assert fake.calls == [_Call("factoryReset", None), _Call("deleteUserData", None)]
