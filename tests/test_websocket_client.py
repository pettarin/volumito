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
    VolumioConnectionError,
    VolumioWebSocketError,
)
from volumito.clients.host_configuration import VolumioHostConfiguration  # noqa: E402
from volumito.clients.websocket.client import (  # noqa: E402
    VolumioWebSocketClient,
    _load_socketio,
)
from volumito.clients.websocket.common import (  # noqa: E402
    EVENT_GET_STATE,
    EVENT_PINGER,
    EVENT_PONGER,
    EVENT_PUSH_QUEUE,
    EVENT_PUSH_STATE,
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
