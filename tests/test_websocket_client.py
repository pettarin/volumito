"""Tests for the WebSocket API client module.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

import logging
import sys
from dataclasses import dataclass, field
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
from volumito.clients.models import Playlist, QueueTrack  # noqa: E402
from volumito.clients.websocket.client import (  # noqa: E402
    VolumioWebSocketClient,
    _load_socketio,
)
from volumito.clients.websocket.common import (  # noqa: E402
    EVENT_BROWSE_LIBRARY,
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
        fake = _FakeSocketIOClient(answers={"getSleep": ("pushSleep", {"enabled": False})})
        client, _ = _client(mocker, fake)

        answer = client.request("getSleep", "pushSleep")

        assert answer == {"enabled": False}

    def test_request_refuses_an_event_with_no_known_answer(self, mocker: MockerFixture):
        """Reading an event the host does not answer warns once and refuses."""
        logger = Mock()
        client, fake = _client(mocker, logger=logger)

        with pytest.raises(ValueError, match="answers no 'getSleep' event"):
            client.request("getSleep")

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
