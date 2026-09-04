"""Tests for the async WebSocket API client module.

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

# The async WebSocket client needs the optional "websocket" extra: without it, this
# whole module has nothing to say
socketio = pytest.importorskip("socketio")
pytest.importorskip("pytest_asyncio")

from volumito.clients.errors import (  # noqa: E402
    VolumioAPIError,
    VolumioConnectionError,
    VolumioWebSocketError,
)
from volumito.clients.host_configuration import VolumioHostConfiguration  # noqa: E402
from volumito.clients.models import Alarm, Playlist, QueueTrack  # noqa: E402
from volumito.clients.websocket.asyncclient import (  # noqa: E402
    VolumioAsyncWebSocketClient,
    _load_aiohttp,
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
    EVENT_INSTALL_TO_DISK,
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

NAVIGATION_PAYLOAD = {
    "navigation": {
        "lists": [
            {
                "title": "Playlists",
                "items": [
                    {"service": "mpd", "type": "song", "title": "jazz", "uri": "mpd://a"}
                ],
            }
        ]
    }
}
"""A browse listing of the shape a Volumio host pushes."""

EMPTY_NAVIGATION = {"navigation": {"lists": [{"title": "Nothing", "items": []}]}}
"""A browse listing holding no item at all."""


@dataclass
class _Call:
    """One event the fake connection was asked to emit."""

    event: str
    payload: Any = None


@dataclass
class _FakeAsyncSocketIOClient:
    """A stand-in for socketio.AsyncClient, recording what it was asked to do.

    An entry of ``answers`` maps an emitted event to the (event, payload) pair the fake
    pushes back the moment it is emitted, which is what a Volumio host does and what
    lets a read resolve without a second task.
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

    async def connect(self, url, **kwargs):
        if self.connect_error is not None:
            raise self.connect_error
        self.connected = True
        self.connected_url = url

    async def emit(self, event, payload=None):
        self.calls.append(_Call(event, payload))
        if self.emit_error is not None:
            raise self.emit_error
        answer = self.answers.get(event)
        if answer is not None:
            await self.fire(*answer)

    async def disconnect(self):
        if self.disconnect_error is not None:
            raise self.disconnect_error
        self.connected = False

    async def wait(self):
        self.waited = True

    async def fire(self, event, payload=None):
        """Push an event, the way a Volumio host does."""
        handler = self.handlers.get(event)
        if handler is not None:
            await handler(payload)


async def _client(
    mocker: MockerFixture,
    fake: _FakeAsyncSocketIOClient | None = None,
    logger: logging.Logger | None = None,
    connect: bool = True,
    **kwargs,
) -> tuple[VolumioAsyncWebSocketClient, _FakeAsyncSocketIOClient]:
    """Build a client whose connection is a fake, connected unless asked otherwise."""
    fake = fake if fake is not None else _FakeAsyncSocketIOClient()
    mocker.patch("socketio.AsyncClient", return_value=fake)
    client = VolumioAsyncWebSocketClient(VolumioHostConfiguration(), logger=logger, **kwargs)
    if connect:
        await client.connect()
    return client, fake


async def _state_client(
    mocker: MockerFixture, logger: logging.Logger | None = None, **kwargs
) -> tuple[VolumioAsyncWebSocketClient, _FakeAsyncSocketIOClient]:
    """Build a connected client whose host answers getState with a playback state."""
    fake = _FakeAsyncSocketIOClient(
        answers={EVENT_GET_STATE: (EVENT_PUSH_STATE, STATE_PAYLOAD)}
    )
    return await _client(mocker, fake, logger=logger, **kwargs)


async def _browse_client(
    mocker: MockerFixture, logger: logging.Logger | None = None
) -> tuple[VolumioAsyncWebSocketClient, _FakeAsyncSocketIOClient]:
    """Build a connected client whose host answers a browse with one item."""
    fake = _FakeAsyncSocketIOClient(
        answers={EVENT_BROWSE_LIBRARY: (EVENT_PUSH_BROWSE_LIBRARY, NAVIGATION_PAYLOAD)}
    )
    return await _client(mocker, fake, logger=logger)


class TestVolumioAsyncWebSocketClientLifecycle:
    """The connection the async WebSocket client owns, and the packages it needs."""

    def test_load_aiohttp_returns_the_module(self):
        """With the package installed, the loader hands the module over."""
        import aiohttp

        assert _load_aiohttp() is aiohttp

    def test_load_aiohttp_without_the_package(self, mocker: MockerFixture):
        """Without the package, the loader names the extra that provides it."""
        mocker.patch.dict(sys.modules, {"aiohttp": None})

        with pytest.raises(VolumioWebSocketError) as excinfo:
            _load_aiohttp()

        assert "needs the aiohttp package" in str(excinfo.value)
        assert "pip install volumito[async_websocket]" in str(excinfo.value)

    async def test_connect_without_socketio_names_the_async_extra(self, mocker: MockerFixture):
        """Without python-socketio, connecting names the extra of the asynchronous client."""
        client, _ = await _client(mocker, connect=False)
        mocker.patch.dict(sys.modules, {"socketio": None})

        with pytest.raises(VolumioWebSocketError) as excinfo:
            await client.connect()

        assert "needs the python-socketio package" in str(excinfo.value)
        assert "pip install volumito[async_websocket]" in str(excinfo.value)
        assert client._connected is False

    async def test_connect_without_aiohttp_raises(self, mocker: MockerFixture):
        """Without aiohttp, connecting fails at once, before python-socketio is involved."""
        mocker.patch.dict(sys.modules, {"aiohttp": None})
        client, fake = await _client(mocker, connect=False)

        with pytest.raises(VolumioWebSocketError, match="needs the aiohttp package"):
            await client.connect()

        assert client._connected is False
        assert client._client is None
        assert fake.connected is False

    def test_it_is_built_outside_a_running_loop(self):
        """Nothing in the constructor touches an event loop."""
        client = VolumioAsyncWebSocketClient(VolumioHostConfiguration())

        assert client._connected is False
        assert client._client is None

    async def test_connect_opens_the_connection(self, mocker: MockerFixture):
        """Connecting reaches the WebSocket URL of the host and flips the flag."""
        client, fake = await _client(mocker)

        assert fake.connected is True
        assert fake.connected_url == BASE
        assert client._connected is True

    async def test_connect_when_already_connected_does_nothing(self, mocker: MockerFixture):
        """Connecting twice keeps the first connection rather than opening a second."""
        client, fake = await _client(mocker)

        await client.connect()

        assert client._connected is True
        assert fake.connected_url == BASE

    async def test_connect_failure_warns_and_raises(self, mocker: MockerFixture):
        """A connection that cannot be opened warns once and leaves the client clean."""
        logger = Mock()
        fake = _FakeAsyncSocketIOClient(connect_error=ConnectionRefusedError("refused"))
        client, _ = await _client(mocker, fake, logger=logger, connect=False)

        with pytest.raises(VolumioConnectionError) as excinfo:
            await client.connect()

        assert "Failed to connect to Volumio instance at" in str(excinfo.value)
        assert client._connected is False
        assert client._client is None
        logger.warning.assert_called_once()

    async def test_disconnect_closes_the_connection(self, mocker: MockerFixture):
        """Disconnecting closes the connection the client owns and forgets it."""
        client, fake = await _client(mocker)

        await client.disconnect()

        assert fake.connected is False
        assert client._connected is False
        assert client._client is None

    async def test_disconnect_when_not_connected(self, mocker: MockerFixture):
        """Disconnecting a client that never connected is a no-op."""
        client, fake = await _client(mocker, connect=False)

        await client.disconnect()

        assert fake.connected is False

    async def test_disconnect_swallows_a_cleanup_error(self, mocker: MockerFixture):
        """A failure while disconnecting is swallowed, warned about, and leaves it clean."""
        logger = Mock()
        fake = _FakeAsyncSocketIOClient(disconnect_error=RuntimeError("gone"))
        client, _ = await _client(mocker, fake, logger=logger)

        await client.disconnect()

        logger.warning.assert_called_once()
        assert client._connected is False

    async def test_async_context_manager(self, mocker: MockerFixture):
        """Entering the block connects, leaving it disconnects."""
        fake = _FakeAsyncSocketIOClient()
        mocker.patch("socketio.AsyncClient", return_value=fake)

        async with VolumioAsyncWebSocketClient(VolumioHostConfiguration()) as client:
            assert client._connected is True

        assert fake.connected is False

    async def test_async_context_manager_disconnects_on_error(self, mocker: MockerFixture):
        """An exception leaving the block still closes the connection."""
        fake = _FakeAsyncSocketIOClient()
        mocker.patch("socketio.AsyncClient", return_value=fake)

        with pytest.raises(RuntimeError):
            async with VolumioAsyncWebSocketClient(VolumioHostConfiguration()):
                raise RuntimeError("boom")

        assert fake.connected is False

    async def test_wait_blocks_on_the_connection(self, mocker: MockerFixture):
        """Waiting hands over to the connection until it drops."""
        client, fake = await _client(mocker)

        await client.wait()

        assert fake.waited is True

    async def test_wait_while_not_connected(self, mocker: MockerFixture):
        """Waiting without a connection refuses."""
        client, _ = await _client(mocker, connect=False)

        with pytest.raises(VolumioConnectionError):
            await client.wait()


class TestVolumioAsyncWebSocketClientTransport:
    """The events the client emits, and the answers it waits for."""

    async def test_emit_with_and_without_a_payload(self, mocker: MockerFixture):
        """An event is emitted alone, or with what it carries."""
        client, fake = await _client(mocker)

        await client.emit("clearQueue")
        await client.emit("addToQueue", {"uri": "mpd://a"})

        assert fake.calls == [_Call("clearQueue", None), _Call("addToQueue", {"uri": "mpd://a"})]

    async def test_emit_while_not_connected(self, mocker: MockerFixture):
        """Emitting without a connection refuses and sends nothing."""
        client, fake = await _client(mocker, connect=False)

        with pytest.raises(VolumioConnectionError):
            await client.emit("stop")

        assert fake.calls == []

    async def test_emit_failure_warns_and_raises(self, mocker: MockerFixture):
        """An event that cannot be sent warns once and names the event."""
        logger = Mock()
        fake = _FakeAsyncSocketIOClient(emit_error=RuntimeError("gone"))
        client, _ = await _client(mocker, fake, logger=logger)

        with pytest.raises(VolumioConnectionError) as excinfo:
            await client.emit("stop")

        assert 'Failed to emit "stop"' in str(excinfo.value)
        logger.warning.assert_called_once()

    async def test_request_returns_the_answer(self, mocker: MockerFixture):
        """A read emits its event and returns what the answer carried."""
        client, fake = await _state_client(mocker)

        answer = await client.request(EVENT_GET_STATE)

        assert answer == STATE_PAYLOAD
        assert fake.calls == [_Call(EVENT_GET_STATE, None)]

    async def test_request_takes_an_explicit_answer_event(self, mocker: MockerFixture):
        """An event the map does not know can still be read, given its answer."""
        fake = _FakeAsyncSocketIOClient(
            answers={"noSuchEvent": ("pushNothing", {"answered": True})}
        )
        client, _ = await _client(mocker, fake)

        assert await client.request("noSuchEvent", "pushNothing") == {"answered": True}

    async def test_request_refuses_an_event_with_no_known_answer(self, mocker: MockerFixture):
        """Reading an event the host does not answer refuses."""
        client, fake = await _client(mocker)

        with pytest.raises(ValueError, match="answers no 'noSuchEvent' event"):
            await client.request("noSuchEvent")

        assert fake.calls == []

    async def test_request_times_out(self, mocker: MockerFixture):
        """A host that does not answer in time warns once and names both events."""
        logger = Mock()
        client, _ = await _client(mocker, logger=logger, timeout=0.01)

        with pytest.raises(VolumioConnectionError) as excinfo:
            await client.request(EVENT_GET_STATE)

        assert 'did not answer "getState" with "pushState"' in str(excinfo.value)
        logger.warning.assert_called_once()

    async def test_request_leaves_no_slot_behind(self, mocker: MockerFixture):
        """A read cleans up after itself, whether it succeeded or timed out."""
        client, _ = await _state_client(mocker, timeout=0.01)

        await client.request(EVENT_GET_STATE)
        with pytest.raises(VolumioConnectionError):
            await client.request(EVENT_GET_STATE, EVENT_PUSH_QUEUE)

        assert client._arrived == {}
        assert client._slots == {}

    async def test_every_answer_event_is_listened_for(self, mocker: MockerFixture):
        """Connecting registers the client for every event a read can wait on."""
        _, fake = await _client(mocker)

        assert set(RESPONSE_EVENTS.values()) <= set(fake.handlers)


class TestVolumioAsyncWebSocketClientEvents:
    """The handlers the client calls when the host pushes an event."""

    async def test_a_sync_handler(self, mocker: MockerFixture):
        """An ordinary callable is called with the payload."""
        client, fake = await _client(mocker)
        received: list[Any] = []
        client.on(EVENT_PUSH_STATE, received.append)

        await fake.fire(EVENT_PUSH_STATE, STATE_PAYLOAD)

        assert received == [STATE_PAYLOAD]

    async def test_a_coroutine_handler_is_awaited(self, mocker: MockerFixture):
        """A coroutine function is awaited rather than left pending."""
        client, fake = await _client(mocker)
        received: list[Any] = []

        async def handler(payload):
            received.append(payload)

        client.on(EVENT_PUSH_STATE, handler)
        await fake.fire(EVENT_PUSH_STATE, STATE_PAYLOAD)

        assert received == [STATE_PAYLOAD]

    async def test_a_handler_registered_before_connecting(self, mocker: MockerFixture):
        """A handler registered before the connection opens still receives its events."""
        fake = _FakeAsyncSocketIOClient()
        mocker.patch("socketio.AsyncClient", return_value=fake)
        client = VolumioAsyncWebSocketClient(VolumioHostConfiguration())
        received: list[Any] = []
        client.on("pushToastMessage", received.append)

        await client.connect()
        await fake.fire("pushToastMessage", {"title": "hello"})

        assert received == [{"title": "hello"}]

    async def test_off_removes_one_handler_and_then_all(self, mocker: MockerFixture):
        """Handlers can be removed one at a time, or all at once."""
        client, fake = await _client(mocker)
        seen: list[str] = []

        def first(payload):
            seen.append("first")

        client.on(EVENT_PUSH_STATE, first)
        client.on(EVENT_PUSH_STATE, lambda payload: seen.append("second"))
        client.off(EVENT_PUSH_STATE, first)
        await fake.fire(EVENT_PUSH_STATE, STATE_PAYLOAD)
        client.off(EVENT_PUSH_STATE)
        await fake.fire(EVENT_PUSH_STATE, STATE_PAYLOAD)

        assert seen == ["second"]

    async def test_off_an_unknown_handler(self, mocker: MockerFixture):
        """Removing a handler that was never added changes nothing."""
        client, fake = await _client(mocker)
        seen: list[str] = []
        client.on(EVENT_PUSH_STATE, lambda payload: seen.append("kept"))

        client.off(EVENT_PUSH_STATE, lambda payload: None)
        client.off("pushQueue", lambda payload: None)
        await fake.fire(EVENT_PUSH_STATE, STATE_PAYLOAD)

        assert seen == ["kept"]

    async def test_a_failing_handler_is_logged_and_the_others_run(self, mocker: MockerFixture):
        """One handler raising does not stop the others, and leaves a traceback."""
        logger = Mock()
        client, fake = await _client(mocker, logger=logger)
        seen: list[str] = []

        async def failing(payload):
            raise RuntimeError("boom")

        client.on(EVENT_PUSH_STATE, failing)
        client.on(EVENT_PUSH_STATE, lambda payload: seen.append("second"))
        await fake.fire(EVENT_PUSH_STATE, STATE_PAYLOAD)

        assert seen == ["second"]
        logger.exception.assert_called_once()


class TestVolumioAsyncWebSocketClientReads:
    """The reads answered by a pushed event, and the models they build."""

    async def test_get_state(self, mocker: MockerFixture):
        """The playback state is read from the state the host pushes back."""
        client, _ = await _state_client(mocker)

        state = await client.get_state()

        assert state.status == "play"

    async def test_get_queue(self, mocker: MockerFixture):
        """The queue is answered as its tracks, which the model wraps."""
        fake = _FakeAsyncSocketIOClient(
            answers={EVENT_GET_QUEUE: (EVENT_PUSH_QUEUE, QUEUE_PAYLOAD)}
        )
        client, _ = await _client(mocker, fake)

        queue = await client.get_queue()

        assert len(queue) == 1
        assert queue[0].position == 0

    async def test_get_playlists(self, mocker: MockerFixture):
        """The playlists are answered as an array of names."""
        fake = _FakeAsyncSocketIOClient(
            answers={EVENT_LIST_PLAYLIST: (EVENT_PUSH_LIST_PLAYLIST, ["jazz"])}
        )
        client, _ = await _client(mocker, fake)

        assert [playlist.name for playlist in await client.get_playlists()] == ["jazz"]

    async def test_get_system_info_and_version(self, mocker: MockerFixture):
        """The system reads build their models from the objects pushed back."""
        fake = _FakeAsyncSocketIOClient(
            answers={
                EVENT_GET_SYSTEM_INFO: ("pushSystemInfo", {"name": "volumio"}),
                EVENT_GET_SYSTEM_VERSION: ("pushSystemVersion", {"systemversion": "4.119"}),
            }
        )
        client, _ = await _client(mocker, fake)

        assert (await client.get_system_info()).name == "volumio"
        assert (await client.get_system_version()).system_version == "4.119"

    async def test_get_collection_statistics(self, mocker: MockerFixture):
        """The collection statistics are read from the object pushed back."""
        fake = _FakeAsyncSocketIOClient(
            answers={EVENT_GET_MY_COLLECTION_STATS: ("pushMyCollectionStats", {"songs": 116})}
        )
        client, _ = await _client(mocker, fake)

        assert (await client.get_collection_statistics()).songs == 116

    async def test_get_zones(self, mocker: MockerFixture):
        """The devices the host answers under "list" are read as the zones."""
        fake = _FakeAsyncSocketIOClient(
            answers={
                EVENT_GET_MULTI_ROOM_DEVICES: (
                    "pushMultiRoomDevices",
                    {"list": [{"id": "1", "name": "Kitchen"}]},
                )
            }
        )
        client, _ = await _client(mocker, fake)

        zones = await client.get_zones()

        assert [zone.name for zone in zones] == ["Kitchen"]

    async def test_get_zones_without_a_list(self, mocker: MockerFixture):
        """A host answering no devices is read as no zones."""
        fake = _FakeAsyncSocketIOClient(
            answers={EVENT_GET_MULTI_ROOM_DEVICES: ("pushMultiRoomDevices", {"misc": {}})}
        )
        client, _ = await _client(mocker, fake)

        assert len(await client.get_zones()) == 0

    async def test_browse_and_search(self, mocker: MockerFixture):
        """Both read the navigation envelope the host pushes back."""
        fake = _FakeAsyncSocketIOClient(
            answers={
                EVENT_BROWSE_LIBRARY: (EVENT_PUSH_BROWSE_LIBRARY, NAVIGATION_PAYLOAD),
                EVENT_SEARCH: (EVENT_PUSH_BROWSE_LIBRARY, NAVIGATION_PAYLOAD),
            }
        )
        client, fake = await _client(mocker, fake)

        browsed = await client.browse("playlists")
        found = await client.search("miles")

        assert [item.title for item in browsed.items] == ["jazz"]
        assert [item.title for item in found.items] == ["jazz"]
        assert fake.calls[0] == _Call(EVENT_BROWSE_LIBRARY, {"uri": "playlists"})

    async def test_browse_the_root(self, mocker: MockerFixture):
        """Browsing without a URI asks for the root."""
        client, fake = await _browse_client(mocker)

        await client.browse()

        assert fake.calls == [_Call(EVENT_BROWSE_LIBRARY, {"uri": "/"})]

    async def test_a_read_answered_with_the_wrong_shape(self, mocker: MockerFixture):
        """An answer that is not the expected JSON shape raises."""
        fake = _FakeAsyncSocketIOClient(
            answers={EVENT_GET_STATE: (EVENT_PUSH_STATE, ["not", "it"])}
        )
        client, _ = await _client(mocker, fake)

        with pytest.raises(VolumioAPIError):
            await client.get_state()

    async def test_an_array_read_answered_with_the_wrong_shape(self, mocker: MockerFixture):
        """An array read answered with an object raises."""
        fake = _FakeAsyncSocketIOClient(
            answers={EVENT_LIST_PLAYLIST: (EVENT_PUSH_LIST_PLAYLIST, {"not": "an array"})}
        )
        client, _ = await _client(mocker, fake)

        with pytest.raises(VolumioAPIError):
            await client.get_playlists()

    async def test_get_queue_status_and_the_neighbors(self, mocker: MockerFixture):
        """The navigation state reads the playback state and the queue, sequentially."""
        fake = _FakeAsyncSocketIOClient(
            answers={
                EVENT_GET_STATE: (EVENT_PUSH_STATE, STATE_PAYLOAD),
                EVENT_GET_QUEUE: (EVENT_PUSH_QUEUE, QUEUE_PAYLOAD * 2),
            }
        )
        client, _ = await _client(mocker, fake)

        status = await client.get_queue_status()

        assert status["length"] == 2
        assert status["position"] == 1
        assert await client.has_next() is False
        assert await client.has_previous() is True

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
        """Each predicate reads the status string of the playback state."""
        fake = _FakeAsyncSocketIOClient(
            answers={EVENT_GET_STATE: (EVENT_PUSH_STATE, {**STATE_PAYLOAD, "status": status})}
        )
        client, _ = await _client(mocker, fake)

        assert await client.is_playing() is playing
        assert await client.is_paused() is paused
        assert await client.is_stopped() is stopped

    async def test_is_muted_seek_and_volume(self, mocker: MockerFixture):
        """The remaining state readers take their values off the playback state."""
        client, _ = await _state_client(mocker)

        assert await client.is_muted() is False
        assert await client.get_seek() == 42
        assert await client.get_volume() == 50


class TestVolumioAsyncWebSocketClientCommands:
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
    async def test_a_bare_command(self, mocker: MockerFixture, method, event):
        """Each bare command emits its event, carrying nothing, and answers nothing."""
        client, fake = await _client(mocker)

        assert await getattr(client, method)() is None
        assert fake.calls == [_Call(event, None)]

    async def test_play(self, mocker: MockerFixture):
        """Playing carries a position only when one is given."""
        client, fake = await _client(mocker)

        await client.play()
        await client.play(3)

        assert fake.calls == [_Call(EVENT_PLAY, None), _Call(EVENT_PLAY, {"value": 3})]

    async def test_play_a_track_of_no_queue(self, mocker: MockerFixture):
        """A track that knows no position is refused before anything is sent."""
        client, fake = await _client(mocker)

        with pytest.raises(ValueError, match="does not belong to a queue"):
            await client.play(QueueTrack.from_raw({"title": "So What"}))

        assert fake.calls == []

    async def test_play_playlist(self, mocker: MockerFixture):
        """A playlist is played by name, given as a string or as a model."""
        client, fake = await _client(mocker)

        await client.play_playlist("jazz")
        await client.play_playlist(Playlist.from_name("rock"))

        assert fake.calls == [
            _Call("playPlaylist", {"name": "jazz"}),
            _Call("playPlaylist", {"name": "rock"}),
        ]

    async def test_play_playlist_without_a_name(self, mocker: MockerFixture):
        """A playlist with no name is refused before anything is sent."""
        client, fake = await _client(mocker)

        with pytest.raises(ValueError, match="playlist has no name"):
            await client.play_playlist(Playlist.from_raw({}))

        assert fake.calls == []

    async def test_set_volume(self, mocker: MockerFixture):
        """Setting the volume carries the level itself, and answers nothing."""
        client, fake = await _client(mocker)

        assert await client.set_volume(42) is None
        assert fake.calls == [_Call("volume", 42)]

    @pytest.mark.parametrize("level", [-1, 101])
    async def test_an_out_of_range_volume(self, mocker: MockerFixture, level):
        """A level outside 0..100 is refused before anything is sent."""
        client, fake = await _client(mocker)

        with pytest.raises(ValueError, match="between 0 and 100"):
            await client.set_volume(level)

        assert fake.calls == []

    async def test_the_volume_steps(self, mocker: MockerFixture):
        """The relative changes carry the increments a Volumio host understands."""
        client, fake = await _client(mocker)

        await client.increase_volume()
        await client.decrease_volume()

        assert fake.calls == [_Call("volume", "+"), _Call("volume", "-")]

    async def test_set_seek(self, mocker: MockerFixture):
        """Seeking carries the number of seconds itself."""
        client, fake = await _client(mocker)

        await client.set_seek(90)

        assert fake.calls == [_Call("seek", 90)]

    async def test_the_relative_seeks(self, mocker: MockerFixture):
        """Both read the position first and send an absolute one."""
        client, fake = await _state_client(mocker)

        await client.seek_forward()
        await client.seek_backward()

        assert fake.calls[-1] == _Call("seek", 32)
        assert _Call("seek", 52) in fake.calls

    async def test_seek_backward_stops_at_the_start(self, mocker: MockerFixture):
        """Seeking backward never goes before the start of the track."""
        fake = _FakeAsyncSocketIOClient(
            answers={EVENT_GET_STATE: (EVENT_PUSH_STATE, {**STATE_PAYLOAD, "seek": 3000})}
        )
        client, _ = await _client(mocker, fake)

        await client.seek_backward()

        assert fake.calls[-1] == _Call("seek", 0)

    @pytest.mark.parametrize(
        ("method", "event"), [("randomize", "setRandom"), ("repeat", "setRepeat")]
    )
    async def test_a_mode_is_set(self, mocker: MockerFixture, method, event):
        """Setting a mode carries the value, without reading the state first."""
        client, fake = await _client(mocker)

        await getattr(client, method)(True)

        assert fake.calls == [_Call(event, {"value": True})]

    @pytest.mark.parametrize(
        ("method", "event", "key"),
        [("randomize", "setRandom", "random"), ("repeat", "setRepeat", "repeat")],
    )
    async def test_a_mode_is_toggled(self, mocker: MockerFixture, method, event, key):
        """Toggling a mode reads the state first and sends the opposite."""
        fake = _FakeAsyncSocketIOClient(
            answers={EVENT_GET_STATE: (EVENT_PUSH_STATE, {**STATE_PAYLOAD, key: True})}
        )
        client, _ = await _client(mocker, fake)

        await getattr(client, method)()

        assert fake.calls[-1] == _Call(event, {"value": False})


class TestVolumioAsyncWebSocketClientQueueing:
    """Adding to the queue and replacing it, which browse a container first."""

    async def test_add_a_local_uri_as_itself(self, mocker: MockerFixture):
        """A URI of the local library is queued as itself, without a browse."""
        client, fake = await _client(mocker)

        await client.add_to_queue("mpd://NAS/track.flac")

        assert fake.calls == [
            _Call("addToQueue", {"service": "mpd", "uri": "mpd://NAS/track.flac"})
        ]

    async def test_add_a_container_of_another_source(self, mocker: MockerFixture):
        """A container of another source is browsed and queued as its items."""
        client, fake = await _browse_client(mocker)

        await client.add_to_queue("qobuz://album/1")

        assert fake.calls[-1] == _Call(
            "addToQueue", [{"service": "mpd", "title": "jazz", "type": "song", "uri": "mpd://a"}]
        )

    async def test_add_a_container_listing_nothing(self, mocker: MockerFixture):
        """A URI of another source that lists nothing is queued as itself."""
        fake = _FakeAsyncSocketIOClient(
            answers={EVENT_BROWSE_LIBRARY: (EVENT_PUSH_BROWSE_LIBRARY, EMPTY_NAVIGATION)}
        )
        client, _ = await _client(mocker, fake)

        await client.add_to_queue("qobuz://track/1")

        assert fake.calls[-1] == _Call(
            "addToQueue", {"service": "qobuz", "uri": "qobuz://track/1"}
        )

    async def test_replace_with_a_local_uri(self, mocker: MockerFixture):
        """A URI of the local library replaces the queue as a single item."""
        client, fake = await _client(mocker)

        await client.replace_queue_and_play("mpd://NAS/album")

        assert fake.calls == [
            _Call("replaceAndPlay", {"item": {"service": "mpd", "uri": "mpd://NAS/album"}})
        ]

    async def test_replace_with_a_browsed_container(self, mocker: MockerFixture):
        """A container of another source is browsed and sent as its items."""
        client, fake = await _browse_client(mocker)

        await client.replace_queue_and_play("qobuz://album/1")

        assert fake.calls[-1].event == "replaceAndPlay"
        assert fake.calls[-1].payload["index"] == 0
        assert len(fake.calls[-1].payload["list"]) == 1

    async def test_replace_at_an_index(self, mocker: MockerFixture):
        """An index browses the URI and sends the listing along with it."""
        client, fake = await _browse_client(mocker)

        await client.replace_queue_and_play("qobuz://album/1", 0)

        assert fake.calls[-1].payload["index"] == 0

    async def test_replace_at_an_index_the_listing_is_too_short_for(self, mocker: MockerFixture):
        """An index beyond the listing raises."""
        client, _ = await _browse_client(mocker)

        with pytest.raises(VolumioAPIError, match="not enough to play the one at index 5"):
            await client.replace_queue_and_play("qobuz://album/1", 5)

    async def test_replace_at_an_index_of_a_uri_listing_nothing(self, mocker: MockerFixture):
        """Index 0 of a URI listing nothing falls back to the URI as a single item."""
        fake = _FakeAsyncSocketIOClient(
            answers={EVENT_BROWSE_LIBRARY: (EVENT_PUSH_BROWSE_LIBRARY, EMPTY_NAVIGATION)}
        )
        client, _ = await _client(mocker, fake)

        await client.replace_queue_and_play("qobuz://track/1", 0)

        assert fake.calls[-1] == _Call(
            "replaceAndPlay", {"item": {"service": "qobuz", "uri": "qobuz://track/1"}}
        )

    async def test_replace_at_a_negative_index(self, mocker: MockerFixture):
        """A negative index is refused before anything is sent."""
        client, fake = await _client(mocker)

        with pytest.raises(ValueError, match="0 or greater"):
            await client.replace_queue_and_play("mpd://NAS/album", -1)

        assert fake.calls == []


class TestVolumioAsyncWebSocketClientPing:
    """The liveness check, which a Volumio host answers by echoing it back."""

    async def test_ping_returns_pong(self, mocker: MockerFixture):
        """A host echoing the ping back is reported as healthy."""
        client, fake = await _client(mocker)

        async def echo(event, payload=None):
            fake.calls.append(_Call(event, payload))
            await fake.fire(EVENT_PONGER, payload)

        fake.emit = echo

        assert await client.ping() == "pong"

    async def test_ping_that_is_not_echoed_back(self, mocker: MockerFixture):
        """A host answering with something else refuses the answer."""
        fake = _FakeAsyncSocketIOClient(
            answers={EVENT_PINGER: (EVENT_PONGER, {"nonce": "other"})}
        )
        client, _ = await _client(mocker, fake)

        with pytest.raises(VolumioConnectionError):
            await client.ping()

    async def test_ping_answered_with_a_scalar(self, mocker: MockerFixture):
        """An answer that is not even an object is refused too."""
        fake = _FakeAsyncSocketIOClient(answers={EVENT_PINGER: (EVENT_PONGER, "pong")})
        client, _ = await _client(mocker, fake)

        with pytest.raises(VolumioConnectionError):
            await client.ping()


class TestVolumioAsyncWebSocketClientQueueEditing:
    """The queue operations the REST API has no endpoint for."""

    async def test_move_in_queue(self, mocker: MockerFixture):
        """Moving a track names the two positions the way Volumio expects."""
        client, fake = await _client(mocker)

        await client.move_in_queue(3, 0)

        assert fake.calls == [_Call("moveQueue", {"from": 3, "to": 0})]

    @pytest.mark.parametrize(("source", "target"), [(-1, 0), (0, -1)])
    async def test_move_in_queue_refuses_a_negative_position(
        self, mocker: MockerFixture, source, target
    ):
        """A negative position is refused before anything is sent."""
        client, fake = await _client(mocker)

        with pytest.raises(ValueError, match="0 or greater"):
            await client.move_in_queue(source, target)

        assert fake.calls == []

    async def test_remove_from_queue(self, mocker: MockerFixture):
        """Removing a track carries the position under "value", not bare."""
        client, fake = await _client(mocker)

        await client.remove_from_queue(2)

        assert fake.calls == [_Call("removeQueueItem", {"value": 2})]

    async def test_remove_from_queue_refuses_a_negative_position(self, mocker: MockerFixture):
        """A negative position is refused before anything is sent."""
        client, fake = await _client(mocker)

        with pytest.raises(ValueError, match="0 or greater"):
            await client.remove_from_queue(-1)

        assert fake.calls == []

    async def test_play_next(self, mocker: MockerFixture):
        """Queueing next carries only the fields that are known."""
        client, fake = await _client(mocker)

        await client.play_next("mpd://a", title="So What", album="Kind of Blue")
        await client.play_next("mpd://b")

        assert fake.calls == [
            _Call("playNext", {"uri": "mpd://a", "title": "So What", "album": "Kind of Blue"}),
            _Call("playNext", {"uri": "mpd://b"}),
        ]

    async def test_add_and_play_a_local_uri(self, mocker: MockerFixture):
        """A URI of the local library is queued as itself and played."""
        client, fake = await _client(mocker)

        await client.add_and_play("mpd://NAS/track.flac")

        assert fake.calls == [
            _Call("addPlay", {"service": "mpd", "uri": "mpd://NAS/track.flac"})
        ]

    async def test_add_and_play_a_container(self, mocker: MockerFixture):
        """A container of another source is browsed and played as its items."""
        client, fake = await _browse_client(mocker)

        await client.add_and_play("qobuz://album/1")

        assert fake.calls[-1] == _Call(
            "addPlay", [{"service": "mpd", "title": "jazz", "type": "song", "uri": "mpd://a"}]
        )

    async def test_save_queue_as_playlist(self, mocker: MockerFixture):
        """The queue is saved under a name, given as a string or as a playlist."""
        client, fake = await _client(mocker)

        await client.save_queue_as_playlist("jazz")
        await client.save_queue_as_playlist(Playlist.from_name("rock"))

        assert fake.calls == [
            _Call("saveQueueToPlaylist", {"name": "jazz"}),
            _Call("saveQueueToPlaylist", {"name": "rock"}),
        ]

    async def test_save_queue_as_playlist_without_a_name(self, mocker: MockerFixture):
        """A playlist with no name is refused before anything is sent."""
        client, fake = await _client(mocker)

        with pytest.raises(ValueError, match="playlist has no name"):
            await client.save_queue_as_playlist(Playlist.from_raw({}))

        assert fake.calls == []

    @pytest.mark.parametrize("value", [True, False])
    async def test_consume(self, mocker: MockerFixture, value):
        """The consume mode carries its value."""
        client, fake = await _client(mocker)

        await client.consume(value)

        assert fake.calls == [_Call("setConsume", {"value": value})]

    async def test_add_uids_to_queue(self, mocker: MockerFixture):
        """The identifiers are sent as the bare list Volumio expects."""
        client, fake = await _client(mocker)

        await client.add_uids_to_queue(["uid1", "uid2"])

        assert fake.calls == [_Call("addQueueUids", ["uid1", "uid2"])]

    async def test_the_cue_events(self, mocker: MockerFixture):
        """Both cue events carry the sheet, the track number, and the service."""
        client, fake = await _client(mocker)

        await client.add_cue_track("mpd://sheet.cue", 3)
        await client.replace_queue_with_cue_track("qobuz://sheet.cue", 1, service="qobuz")

        assert fake.calls == [
            _Call("addPlayCue", {"number": 3, "service": "mpd", "uri": "mpd://sheet.cue"}),
            _Call(
                "replaceAndPlayCue",
                {"number": 1, "service": "qobuz", "uri": "qobuz://sheet.cue"},
            ),
        ]

    async def test_play_items(self, mocker: MockerFixture):
        """The items are reduced to the keys queueing reads, and the index is carried."""
        client, fake = await _client(mocker)
        items = [{"uri": "mpd://a", "title": "a", "service": "mpd", "albumart": "/x"}]

        await client.play_items(items, 0)

        assert fake.calls == [
            _Call(
                "playItemsList",
                {"list": [{"service": "mpd", "title": "a", "uri": "mpd://a"}], "index": 0},
            )
        ]

    async def test_play_items_refuses_a_negative_index(self, mocker: MockerFixture):
        """A negative index is refused before anything is sent."""
        client, fake = await _client(mocker)

        with pytest.raises(ValueError, match="0 or greater"):
            await client.play_items([], -1)

        assert fake.calls == []

    async def test_play_volatile(self, mocker: MockerFixture):
        """A volatile source is started at a position carried under "value"."""
        client, fake = await _client(mocker)

        await client.play_volatile(2)

        assert fake.calls == [_Call("volatilePlay", {"value": 2})]

    async def test_play_volatile_refuses_a_negative_position(self, mocker: MockerFixture):
        """A negative position is refused before anything is sent."""
        client, fake = await _client(mocker)

        with pytest.raises(ValueError, match="0 or greater"):
            await client.play_volatile(-1)

        assert fake.calls == []

    async def test_goto(self, mocker: MockerFixture):
        """Browsing to the artist of what is playing reads the listing back."""
        fake = _FakeAsyncSocketIOClient(
            answers={"goTo": (EVENT_PUSH_BROWSE_LIBRARY, NAVIGATION_PAYLOAD)}
        )
        client, _ = await _client(mocker, fake)

        results = await client.goto("artist", "Miles Davis")

        assert [item.title for item in results.items] == ["jazz"]
        assert fake.calls == [_Call("goTo", {"type": "artist", "value": "Miles Davis"})]


class TestVolumioAsyncWebSocketClientPlaylistEditing:
    """Creating, editing and reading the saved playlists."""

    async def test_create_and_delete(self, mocker: MockerFixture):
        """A playlist is created and deleted by name."""
        client, fake = await _client(mocker)

        await client.create_playlist("jazz")
        await client.delete_playlist(Playlist.from_name("rock"))

        assert fake.calls == [
            _Call("createPlaylist", {"name": "jazz"}),
            _Call("deletePlaylist", {"name": "rock"}),
        ]

    async def test_add_and_remove_an_item(self, mocker: MockerFixture):
        """An item carries the playlist, the URI, and the service it belongs to."""
        client, fake = await _client(mocker)

        await client.add_to_playlist("jazz", "qobuz://track/1")
        await client.remove_from_playlist("jazz", "mpd://NAS/a.flac")

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

    async def test_an_explicit_service_wins(self, mocker: MockerFixture):
        """A service given by the caller is not derived from the URI."""
        client, fake = await _client(mocker)

        await client.add_to_playlist("jazz", "mpd://a", service="upnp")

        assert fake.calls[-1].payload["service"] == "upnp"

    async def test_editing_a_playlist_without_a_name(self, mocker: MockerFixture):
        """A playlist with no name is refused before anything is sent."""
        client, fake = await _client(mocker)

        with pytest.raises(ValueError, match="playlist has no name"):
            await client.add_to_playlist(Playlist.from_raw({}), "mpd://a")

        assert fake.calls == []

    async def test_enqueue_playlist(self, mocker: MockerFixture):
        """A playlist is appended to the queue by name."""
        client, fake = await _client(mocker)

        await client.enqueue_playlist("jazz")

        assert fake.calls == [_Call("enqueue", {"name": "jazz"})]

    async def test_import_service_playlists(self, mocker: MockerFixture):
        """The import carries nothing."""
        client, fake = await _client(mocker)

        await client.import_service_playlists()

        assert fake.calls == [_Call("importServicePlaylists", None)]

    async def test_get_playlist_content(self, mocker: MockerFixture):
        """The tracks are read out of the one list per source the host groups them in."""
        fake = _FakeAsyncSocketIOClient(
            answers={
                "getPlaylistContent": (
                    "pushPlaylistContent",
                    {"name": "jazz", "lists": [[{"title": "So What", "uri": "mpd://a"}]]},
                )
            }
        )
        client, _ = await _client(mocker, fake)

        content = await client.get_playlist_content("jazz")

        assert content.name == "jazz"
        assert [track.title for track in content] == ["So What"]


class TestVolumioAsyncWebSocketClientFavourites:
    """The favourites and the web radios of the user."""

    async def test_add_to_favourites(self, mocker: MockerFixture):
        """A favourite carries its service, and only the fields that are known."""
        client, fake = await _client(mocker)

        await client.add_to_favourites("qobuz://track/1", title="So What", albumart="/cover")
        await client.add_to_favourites("mpd://NAS/a.flac")

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

    async def test_remove_from_favourites(self, mocker: MockerFixture):
        """Removing a favourite carries the URI and its service."""
        client, fake = await _client(mocker)

        await client.remove_from_favourites("qobuz://track/1")

        assert fake.calls == [
            _Call("removeFromFavourites", {"service": "qobuz", "uri": "qobuz://track/1"})
        ]

    async def test_an_explicit_service_wins(self, mocker: MockerFixture):
        """A service given by the caller is not derived from the URI."""
        client, fake = await _client(mocker)

        await client.add_to_favourites("mpd://a", service="upnp")

        assert fake.calls[-1].payload["service"] == "upnp"

    async def test_play_favourites(self, mocker: MockerFixture):
        """The favourites play from the start, or from a named one."""
        client, fake = await _client(mocker)

        await client.play_favourites()
        await client.play_favourites("So What")

        assert fake.calls == [
            _Call("playFavourites", None),
            _Call("playFavourites", {"name": "So What"}),
        ]

    async def test_the_radio_favourites(self, mocker: MockerFixture):
        """A web radio is made a favourite, played, and removed."""
        client, fake = await _client(mocker)

        await client.add_radio_favourite("http://stream/1")
        await client.play_radio_favourites()
        await client.remove_radio_favourite("http://stream/1")
        await client.remove_radio_favourite("http://stream/2", name="Jazz FM")

        assert fake.calls == [
            _Call("addToRadioFavourites", {"uri": "http://stream/1"}),
            _Call("playRadioFavourites", None),
            _Call("removeFromRadioFavourites", {"uri": "http://stream/1"}),
            _Call(
                "removeFromRadioFavourites",
                {"name": "Jazz FM", "uri": "http://stream/2"},
            ),
        ]

    async def test_the_web_radios_of_the_user(self, mocker: MockerFixture):
        """A web radio is saved with its URL and deleted by name alone."""
        client, fake = await _client(mocker)

        await client.add_web_radio("Jazz FM", "http://stream/1")
        await client.remove_web_radio("Jazz FM")

        assert fake.calls == [
            _Call("addWebRadio", {"name": "Jazz FM", "uri": "http://stream/1"}),
            _Call("removeWebRadio", {"name": "Jazz FM"}),
        ]


class TestVolumioAsyncWebSocketClientBrowseSources:
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

    async def test_browse_sources(self, mocker: MockerFixture):
        """The sources are answered as a bare array, which the model wraps."""
        fake = _FakeAsyncSocketIOClient(
            answers={"getBrowseSources": ("pushBrowseSources", self._SOURCES)}
        )
        client, _ = await _client(mocker, fake)

        sources = (await client.get_browse_sources())

        assert [source.name for source in sources] == ["Playlists"]
        assert sources[0].plugin_type == "music_service"

    async def test_menu_items(self, mocker: MockerFixture):
        """The menu is answered as a bare array, which the model wraps."""
        fake = _FakeAsyncSocketIOClient(
            answers={"getMenuItems": ("pushMenuItems", [{"id": "mymusic", "name": "Sources"}])}
        )
        client, _ = await _client(mocker, fake)

        assert [item.id for item in (await client.get_menu_items())] == ["mymusic"]

    async def test_last_browse(self, mocker: MockerFixture):
        """The listing pushed last is read as a browse result."""
        fake = _FakeAsyncSocketIOClient(
            answers={
                "getLastPushedBrowseLibrary": (EVENT_PUSH_BROWSE_LIBRARY, NAVIGATION_PAYLOAD)
            }
        )
        client, _ = await _client(mocker, fake)

        assert [item.title for item in (await client.get_last_browse()).items] == ["jazz"]

    async def test_super_search(self, mocker: MockerFixture):
        """The search across every source carries the query and reads the envelope."""
        fake = _FakeAsyncSocketIOClient(
            answers={"superSearch": (EVENT_PUSH_BROWSE_LIBRARY, NAVIGATION_PAYLOAD)}
        )
        client, fake = await _client(mocker, fake)

        results = await client.super_search("miles")

        assert [item.title for item in results.items] == ["jazz"]
        assert fake.calls == [_Call("superSearch", {"value": "miles"})]

    async def test_regenerate_thumbnails(self, mocker: MockerFixture):
        """Rebuilding the thumbnails carries nothing."""
        client, fake = await _client(mocker)

        await client.regenerate_thumbnails()

        assert fake.calls == [_Call("regenerateThumbnails", None)]


class TestVolumioAsyncWebSocketClientSleepAndAlarms:
    """The sleep timer and the alarms, both served by the alarm-clock plugin."""

    async def test_sleep_timer(self, mocker: MockerFixture):
        """The timer is read, and its time parsed as the delay it is."""
        fake = _FakeAsyncSocketIOClient(
            answers={
                "getSleep": (
                    "pushSleep",
                    {"enabled": True, "time": "0:30", "action": {"val": "stop"}},
                )
            }
        )
        client, _ = await _client(mocker, fake)

        timer = (await client.get_sleep_timer())

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
    async def test_set_sleep_timer(self, mocker: MockerFixture, delay, expected):
        """A duration is rendered to the "H:MM" a Volumio host reads as a delay."""
        client, fake = await _client(mocker)

        await client.set_sleep_timer(delay)

        assert fake.calls == [_Call("setSleep", expected)]

    async def test_set_sleep_timer_refuses_a_negative_delay(self, mocker: MockerFixture):
        """A negative delay is refused before anything is sent."""
        logger = Mock()
        client, fake = await _client(mocker, logger=logger)

        with pytest.raises(ValueError, match="must not be negative"):
            await client.set_sleep_timer(timedelta(minutes=-5))

        assert fake.calls == []
        logger.warning.assert_called_once()

    async def test_alarms(self, mocker: MockerFixture):
        """The alarms are answered as a bare array, which the model wraps."""
        fake = _FakeAsyncSocketIOClient(
            answers={
                "getAlarms": (
                    "pushAlarm",
                    [{"id": 1, "name": "Weekday", "enabled": True, "time": "07:30",
                      "playlist": "jazz"}],
                )
            }
        )
        client, _ = await _client(mocker, fake)

        alarms = (await client.get_alarms())

        assert len(alarms) == 1
        assert alarms[0].playlist == "jazz"

    async def test_a_host_with_no_alarm(self, mocker: MockerFixture):
        """A host reporting no alarm is an empty collection."""
        fake = _FakeAsyncSocketIOClient(answers={"getAlarms": ("pushAlarm", [])})
        client, _ = await _client(mocker, fake)

        assert len(await client.get_alarms()) == 0

    async def test_set_alarms_replaces_the_whole_set(self, mocker: MockerFixture):
        """The alarms are sent as the list the Volumio API replaces its set with."""
        client, fake = await _client(mocker)
        alarms = [
            Alarm.from_raw({"id": 1, "enabled": True, "time": "07:30", "playlist": "jazz"}),
            Alarm.from_raw({"id": 2, "enabled": False, "time": "09:00", "playlist": "rock"}),
        ]

        await client.set_alarms(alarms)

        assert fake.calls == [
            _Call(
                "saveAlarm",
                [
                    {"enabled": True, "id": 1, "playlist": "jazz", "time": "07:30"},
                    {"enabled": False, "id": 2, "playlist": "rock", "time": "09:00"},
                ],
            )
        ]

    async def test_set_alarms_with_an_empty_set(self, mocker: MockerFixture):
        """Sending no alarm clears them all."""
        client, fake = await _client(mocker)

        await client.set_alarms([])

        assert fake.calls == [_Call("saveAlarm", [])]


class TestVolumioAsyncWebSocketClientAudioOutputs:
    """The audio outputs, the output devices, and the input sources."""

    _DEVICES = {
        "devices": {
            "active": {"name": "HDMI Out", "id": "0"},
            "available": [{"id": "0", "name": "HDMI Out"}, {"id": "1", "name": "Headphones"}],
        },
        "i2s": False,
    }

    async def test_output_devices(self, mocker: MockerFixture):
        """The devices are read out of the envelope the host answers with."""
        fake = _FakeAsyncSocketIOClient(
            answers={"getOutputDevices": ("pushOutputDevices", self._DEVICES)}
        )
        client, _ = await _client(mocker, fake)

        devices = (await client.get_output_devices())

        assert devices.active is not None
        assert devices.active.name == "HDMI Out"
        assert [device.name for device in devices] == ["HDMI Out", "Headphones"]

    async def test_extended_output_devices(self, mocker: MockerFixture):
        """The detailed devices come back through the same envelope."""
        fake = _FakeAsyncSocketIOClient(
            answers={"getExtendedOutputDevices": ("pushExtendedOutputDevices", self._DEVICES)}
        )
        client, _ = await _client(mocker, fake)

        assert len(await client.get_extended_output_devices()) == 2

    async def test_audio_outputs(self, mocker: MockerFixture):
        """The outputs are read from the aliased key of the answer."""
        fake = _FakeAsyncSocketIOClient(
            answers={
                "getAudioOutputs": (
                    "pushAudioOutputs",
                    {"availableOutputs": [{"id": "0", "name": "Living room", "volume": 40}]},
                )
            }
        )
        client, _ = await _client(mocker, fake)

        outputs = (await client.get_audio_outputs())

        assert [output.name for output in outputs] == ["Living room"]
        assert outputs[0].volume == 40

    async def test_input_sources(self, mocker: MockerFixture):
        """A host with no input source answers an empty mapping."""
        fake = _FakeAsyncSocketIOClient(answers={"getInputSources": ("pushInputSources", {})})
        client, _ = await _client(mocker, fake)

        assert (await client.get_input_sources()).raw == {}

    async def test_set_output_device(self, mocker: MockerFixture):
        """The device is chosen by identifier, with the mixer only when given."""
        client, fake = await _client(mocker)

        await client.set_output_device("1")
        await client.set_output_device("1", mixer="Digital")

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
    async def test_the_audio_output_commands(self, mocker: MockerFixture, method, event):
        """Each command names the output it acts on."""
        client, fake = await _client(mocker)

        await getattr(client, method)("0")

        assert fake.calls == [_Call(event, {"id": "0"})]

    async def test_set_audio_output_volume(self, mocker: MockerFixture):
        """The volume of one output carries the identifier and the level."""
        client, fake = await _client(mocker)

        await client.set_audio_output_volume("0", 42)

        assert fake.calls == [_Call("setAudioOutputVolume", {"id": "0", "volume": 42})]

    @pytest.mark.parametrize("level", [-1, 101])
    async def test_an_out_of_range_output_volume(self, mocker: MockerFixture, level):
        """A level outside 0..100 is refused before anything is sent."""
        client, fake = await _client(mocker)

        with pytest.raises(ValueError, match="between 0 and 100"):
            await client.set_audio_output_volume("0", level)

        assert fake.calls == []


class TestVolumioAsyncWebSocketClientLibrary:
    """Scanning the collection and choosing the music sources."""

    async def test_music_sources(self, mocker: MockerFixture):
        """The sources are answered as a bare array, which the model wraps."""
        fake = _FakeAsyncSocketIOClient(
            answers={
                "getMyMusicPlugins": (
                    "pushMyMusicPlugins",
                    [{"name": "upnp", "prettyName": "UPNP Renderer", "enabled": True}],
                )
            }
        )
        client, _ = await _client(mocker, fake)

        sources = (await client.get_music_sources())

        assert [source.name for source in sources] == ["upnp"]
        assert sources[0].pretty_name == "UPNP Renderer"

    async def test_set_music_source_enabled(self, mocker: MockerFixture):
        """A source is enabled or disabled by name."""
        client, fake = await _client(mocker)

        await client.set_music_source_enabled("upnp", True)

        assert fake.calls == [
            _Call("enableDisableMyMusicPlugin", {"name": "upnp", "enabled": True})
        ]

    async def test_the_scan_commands(self, mocker: MockerFixture):
        """The scans carry nothing, or the URI or service they are scoped to."""
        client, fake = await _client(mocker)

        await client.rescan_library()
        await client.update_all_metadata()
        await client.update_library()
        await client.update_library("mpd://NAS/Music")
        await client.update_service_tracklist("qobuz")

        assert fake.calls == [
            _Call("rescanDb", None),
            _Call("updateAllMetadata", None),
            _Call("updateDb", None),
            _Call("updateDb", "mpd://NAS/Music"),
            _Call("serviceUpdateTracklist", "qobuz"),
        ]


class TestVolumioAsyncWebSocketClientPower:
    """The identity of the host and the ways it can be powered down."""

    async def test_device_info(self, mocker: MockerFixture):
        """The identity carries the name and the hardware identifier."""
        fake = _FakeAsyncSocketIOClient(
            answers={"getDeviceInfo": ("pushDeviceInfo", {"uuid": "5dc4", "name": "kitchen"})}
        )
        client, _ = await _client(mocker, fake)

        info = (await client.get_device_info())

        assert info.name == "kitchen"
        assert info.uuid == "5dc4"

    async def test_device_name(self, mocker: MockerFixture):
        """The name is read on its own, and assigning to it renames the host."""
        fake = _FakeAsyncSocketIOClient(
            answers={"getDeviceName": ("pushDeviceName", {"name": "kitchen"})}
        )
        client, _ = await _client(mocker, fake)

        assert await client.get_device_name() == "kitchen"

        await client.set_device_name("living room")

        assert fake.calls[-1] == _Call("setDeviceName", {"name": "living room"})

    async def test_device_uuid(self, mocker: MockerFixture):
        """The hardware identifier is read on its own."""
        fake = _FakeAsyncSocketIOClient(
            answers={"getDeviceHWUUID": ("pushDeviceHWUUID", "5dc4ca49")}
        )
        client, _ = await _client(mocker, fake)

        assert await client.get_device_uuid() == "5dc4ca49"

    async def test_a_host_reporting_no_name(self, mocker: MockerFixture):
        """A host answering without the field reports None rather than failing."""
        fake = _FakeAsyncSocketIOClient(
            answers={
                "getDeviceName": ("pushDeviceName", {}),
            }
        )
        client, _ = await _client(mocker, fake)

        assert await client.get_device_name() is None

    async def test_power_modes(self, mocker: MockerFixture):
        """The power modes are read from their aliases."""
        fake = _FakeAsyncSocketIOClient(
            answers={
                "getShutdownOrStandbyMode": (
                    "pushShutdownOrStandbyMode",
                    {"hasPowerOffMode": True, "hasStandbyMode": False},
                )
            }
        )
        client, _ = await _client(mocker, fake)

        modes = (await client.get_power_modes())

        assert modes.has_power_off_mode is True
        assert modes.has_standby_mode is False


    async def test_a_hardware_identifier_that_is_not_a_string(self, mocker: MockerFixture):
        """The identifier comes back bare; an object instead of it is refused."""
        fake = _FakeAsyncSocketIOClient(
            answers={"getDeviceHWUUID": ("pushDeviceHWUUID", {"uuid": "5dc4"})}
        )
        client, _ = await _client(mocker, fake)

        with pytest.raises(VolumioAPIError, match="Expected JSON string"):
            await client.get_device_uuid()

    @pytest.mark.parametrize(
        ("method", "event"),
        [("reboot", "reboot"), ("shutdown", "shutdown"), ("standby", "standby")],
    )
    async def test_the_power_commands(self, mocker: MockerFixture, method, event):
        """Each power command carries nothing and answers nothing."""
        client, fake = await _client(mocker)

        assert await getattr(client, method)() is None
        assert fake.calls == [_Call(event, None)]


class TestVolumioAsyncWebSocketClientPlugins:
    """The plugins installed on the host, and their configuration pages."""

    async def test_installed_plugins(self, mocker: MockerFixture):
        """The plugins are answered as a bare array, which the model wraps."""
        fake = _FakeAsyncSocketIOClient(
            answers={
                "getInstalledPlugins": (
                    "pushInstalledPlugins",
                    [{"name": "spop", "prettyName": "Spotify", "enabled": True}],
                )
            }
        )
        client, _ = await _client(mocker, fake)

        plugins = (await client.get_installed_plugins())

        assert [plugin.name for plugin in plugins] == ["spop"]
        assert plugins[0].pretty_name == "Spotify"

    async def test_a_host_with_no_plugin(self, mocker: MockerFixture):
        """A host reporting no plugin is an empty collection."""
        fake = _FakeAsyncSocketIOClient(
            answers={"getInstalledPlugins": ("pushInstalledPlugins", [])}
        )
        client, _ = await _client(mocker, fake)

        assert len(await client.get_installed_plugins()) == 0

    async def test_get_plugin_config(self, mocker: MockerFixture):
        """The configuration page is asked for by "category/name"."""
        fake = _FakeAsyncSocketIOClient(
            answers={
                "getUiConfig": (
                    "pushUiConfig",
                    {"page": {"label": "System Settings"}, "sections": [{"id": "language"}]},
                )
            }
        )
        client, fake = await _client(mocker, fake)

        config = await client.get_plugin_config("system_controller/system")

        assert config.page == {"label": "System Settings"}
        assert fake.calls == [_Call("getUiConfig", {"page": "system_controller/system"})]

    async def test_dsp_config(self, mocker: MockerFixture):
        """The DSP page comes back through its own event."""
        fake = _FakeAsyncSocketIOClient(
            answers={"getDSPUiConfig": ("pushDSPUiConfig", {"page": {"label": "DSP"}})}
        )
        client, _ = await _client(mocker, fake)

        assert (await client.get_dsp_config()).page == {"label": "DSP"}

    async def test_manage_plugin(self, mocker: MockerFixture):
        """The plugin manager answers with the plugins as they stand after the action."""
        fake = _FakeAsyncSocketIOClient(
            answers={"pluginManager": ("pushInstalledPlugins", [{"name": "spop"}])}
        )
        client, fake = await _client(mocker, fake)

        plugins = await client.manage_plugin("enable", "music_service", "spop")

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
    async def test_the_plugin_commands(self, mocker: MockerFixture, method, event):
        """Each command names the plugin by category and name."""
        client, fake = await _client(mocker)

        await getattr(client, method)("music_service", "spop")

        assert fake.calls == [_Call(event, {"category": "music_service", "name": "spop"})]

    async def test_modify_plugin_status(self, mocker: MockerFixture):
        """Enabling in one call carries the flag beside the plugin."""
        client, fake = await _client(mocker)

        await client.modify_plugin_status("music_service", "spop", True)

        assert fake.calls == [
            _Call(
                "modifyPluginStatus",
                {"category": "music_service", "name": "spop", "enabled": True},
            )
        ]

    async def test_install_plugin(self, mocker: MockerFixture):
        """Installing carries the URL and the confirmation the host expects."""
        client, fake = await _client(mocker)

        await client.install_plugin("http://plugins/spop.zip")

        assert fake.calls == [
            _Call("installPlugin", {"url": "http://plugins/spop.zip", "confirm": True})
        ]

    async def test_call_plugin_method(self, mocker: MockerFixture):
        """The generic call carries the endpoint, the method, and its arguments."""
        client, fake = await _client(mocker)

        await client.call_plugin_method("music_service/mpd", "rescanDb")
        await client.call_plugin_method("miscellanea/alarm", "setSleep", {"time": "0:30"})

        assert fake.calls == [
            _Call("callMethod", {"endpoint": "music_service/mpd", "method": "rescanDb",
                                 "data": {}}),
            _Call("callMethod", {"endpoint": "miscellanea/alarm", "method": "setSleep",
                                 "data": {"time": "0:30"}}),
        ]


class TestVolumioAsyncWebSocketClientNetworkAndShares:
    """The network interfaces, the wireless networks, the shares, and the USB drives."""

    async def test_network_info(self, mocker: MockerFixture):
        """The interfaces are answered as a bare array, which the model wraps."""
        fake = _FakeAsyncSocketIOClient(
            answers={
                "getInfoNetwork": (
                    "pushInfoNetwork",
                    [{"type": "Wired", "ip": "192.168.1.122", "status": "connected"}],
                )
            }
        )
        client, _ = await _client(mocker, fake)

        info = (await client.get_network_info())

        assert len(info) == 1
        assert info[0].ip == "192.168.1.122"

    async def test_shares(self, mocker: MockerFixture):
        """The shares are answered as a bare array, which the model wraps."""
        fake = _FakeAsyncSocketIOClient(
            answers={"getListShares": ("pushListShares", [{"id": "a", "name": "NAS"}])}
        )
        client, _ = await _client(mocker, fake)

        assert [share.name for share in await client.get_shares()] == ["NAS"]

    async def test_get_share(self, mocker: MockerFixture):
        """One share is read by identifier."""
        fake = _FakeAsyncSocketIOClient(
            answers={"getInfoShare": ("pushInfoShare", {"id": "a", "name": "NAS",
                                                        "fstype": "cifs"})}
        )
        client, fake = await _client(mocker, fake)

        share = await client.get_share("a")

        assert share.fstype == "cifs"
        assert fake.calls == [_Call("getInfoShare", {"id": "a"})]

    async def test_add_edit_and_delete_a_share(self, mocker: MockerFixture):
        """A share is mounted with its options, changed, and unmounted."""
        client, fake = await _client(mocker)

        await client.add_share("NAS", "192.168.1.2/Music", "cifs", username="guest")
        await client.edit_share("a", name="NAS2")
        await client.delete_share("a")

        assert fake.calls == [
            _Call(
                "addShare",
                {"name": "NAS", "path": "192.168.1.2/Music", "fstype": "cifs",
                 "username": "guest"},
            ),
            _Call("editShare", {"id": "a", "name": "NAS2"}),
            _Call("deleteShare", {"id": "a"}),
        ]

    async def test_discover_network_shares(self, mocker: MockerFixture):
        """The discovery answers with whatever the host found."""
        fake = _FakeAsyncSocketIOClient(
            answers={
                "getNetworkSharesDiscovery": (
                    "pushNetworkSharesDiscovery",
                    {"nas": [{"name": "NAS"}]},
                )
            }
        )
        client, _ = await _client(mocker, fake)

        assert await client.discover_network_shares() == {"nas": [{"name": "NAS"}]}

    async def test_usb_drives_and_safe_removal(self, mocker: MockerFixture):
        """The drives are read, and one is unmounted by name."""
        fake = _FakeAsyncSocketIOClient(
            answers={"listUsbDrives": ("pushListUsbDrives", [{"name": "USB"}])}
        )
        client, fake = await _client(mocker, fake)

        drives = (await client.get_usb_drives())
        await client.safe_remove_drive("USB")

        assert [drive.name for drive in drives] == ["USB"]
        assert fake.calls[-1] == _Call("safeRemoveDrive", {"name": "USB"})

    async def test_delete_folder(self, mocker: MockerFixture):
        """A folder is deleted by the path the host nests under "item"."""
        client, fake = await _client(mocker)

        await client.delete_folder("mpd://NAS/Old")

        assert fake.calls == [_Call("deleteFolder", {"item": {"path": "mpd://NAS/Old"}})]

    async def test_the_wireless_networks(self, mocker: MockerFixture):
        """Both the scan and the cache answer with the networks the host can see."""
        networks = {"available": [{"ssid": "home", "signal": 70}]}
        fake = _FakeAsyncSocketIOClient(
            answers={
                "getWirelessNetworks": ("pushWirelessNetworks", networks),
                "getWirelessNetworksCache": ("pushWirelessNetworksCache", networks),
            }
        )
        client, _ = await _client(mocker, fake)

        assert [n.ssid for n in await client.get_wireless_networks()] == ["home"]
        assert [n.ssid for n in await client.get_wireless_networks_cache()] == ["home"]

    async def test_save_wireless_settings(self, mocker: MockerFixture):
        """Joining a network carries the name and the password, empty when open."""
        client, fake = await _client(mocker)

        await client.save_wireless_settings("home", "hunter2")
        await client.save_wireless_settings("open")

        assert fake.calls == [
            _Call("saveWirelessNetworkSettings", {"ssid": "home", "password": "hunter2"}),
            _Call("saveWirelessNetworkSettings", {"ssid": "open", "password": ""}),
        ]


class TestVolumioAsyncWebSocketClientUiPreferences:
    """The look, the language, the time zone, and the other host preferences."""

    async def test_ui_settings(self, mocker: MockerFixture):
        """The look of the interface is parsed."""
        fake = _FakeAsyncSocketIOClient(
            answers={
                "getUiSettings": ("pushUiSettings", {"color": "#000", "language": "en",
                                                     "theme": "default"})
            }
        )
        client, _ = await _client(mocker, fake)

        settings = (await client.get_ui_settings())

        assert settings.color == "#000"
        assert settings.theme == "default"

    async def test_languages_and_set_language(self, mocker: MockerFixture):
        """The languages are read, and one is chosen by code."""
        fake = _FakeAsyncSocketIOClient(
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
        client, fake = await _client(mocker, fake)

        languages = (await client.get_languages())
        await client.set_language("it", "Italiano")
        await client.set_language("fr")

        assert languages.default_language is not None
        assert languages.default_language.code == "en"
        assert [lang.code for lang in languages] == ["it"]
        assert fake.calls[-2:] == [
            _Call("setLanguage", {"defaultLanguage": {"code": "it", "language": "Italiano"}}),
            _Call("setLanguage", {"defaultLanguage": {"code": "fr", "language": "fr"}}),
        ]

    async def test_the_timezone(self, mocker: MockerFixture):
        """The zone is read as a bare string, and assigning to it moves the host."""
        fake = _FakeAsyncSocketIOClient(
            answers={
                "getCurrentTimezone": ("pushCurrentTimezone", "Europe/Rome"),
                "getAvailableTimezones": ("pushAvailableTimezones", ["Europe/Rome", "UTC"]),
            }
        )
        client, fake = await _client(mocker, fake)

        assert await client.get_timezone() == "Europe/Rome"
        assert list(await client.get_available_timezones()) == ["Europe/Rome", "UTC"]

        await client.set_timezone("UTC")

        assert fake.calls[-1] == _Call("setTimezone", {"timeZone": "UTC"})

    async def test_backgrounds(self, mocker: MockerFixture):
        """The background in use is read beside the available ones."""
        fake = _FakeAsyncSocketIOClient(
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
        client, fake = await _client(mocker, fake)

        backgrounds = (await client.get_backgrounds())
        await client.set_background("Aurora", "aurora.jpg")
        await client.set_background("Darkness")
        await client.delete_background("Aurora")

        assert backgrounds.current is not None
        assert backgrounds.current.name == "Darkness"
        assert [b.name for b in backgrounds] == ["Aurora"]
        assert fake.calls[-3:] == [
            _Call("setBackgrounds", {"name": "Aurora", "path": "aurora.jpg"}),
            _Call("setBackgrounds", {"name": "Darkness"}),
            _Call("deleteBackground", {"name": "Aurora"}),
        ]

    async def test_privacy_settings(self, mocker: MockerFixture):
        """The statistics flag is read from its alias."""
        fake = _FakeAsyncSocketIOClient(
            answers={"getPrivacySettings": ("pushPrivacySettings",
                                            {"allowUIStatistics": False})}
        )
        client, _ = await _client(mocker, fake)

        assert (await client.get_privacy_settings()).allow_ui_statistics is False

    async def test_infinity_playback(self, mocker: MockerFixture):
        """The setting is read, and turned on."""
        fake = _FakeAsyncSocketIOClient(
            answers={"getInfinityPlayback": ("pushInfinityPlayback",
                                             {"available": True, "enabled": False})}
        )
        client, fake = await _client(mocker, fake)

        playback = (await client.get_infinity_playback())
        await client.set_infinity_playback(True)

        assert playback.available is True
        assert playback.enabled is False
        assert fake.calls[-1] == _Call("setInfinityPlayback", {"enabled": True})

    async def test_experience_settings(self, mocker: MockerFixture):
        """The setting is read, and the full set of options chosen."""
        fake = _FakeAsyncSocketIOClient(
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
        client, fake = await _client(mocker, fake)

        settings = (await client.get_experience_settings())
        await client.set_experience_settings(True)

        assert settings.advanced is False
        assert fake.calls[-1] == _Call("setExperienceAdvancedSettings", True)


class TestVolumioAsyncWebSocketClientSystemAdministration:
    """Updates, backups, multiroom, and the two members that refuse to run."""

    async def test_automatic_update_enabled(self, mocker: MockerFixture):
        """The flag is answered bare, and read as the boolean it is."""
        fake = _FakeAsyncSocketIOClient(
            answers={"getAutomaticUpdateEnabled": ("pushAutomaticUpdateEnabled", False)}
        )
        client, _ = await _client(mocker, fake)

        assert await client.is_automatic_update_enabled() is False

    async def test_an_automatic_update_flag_that_is_not_a_boolean(self, mocker: MockerFixture):
        """Anything but a boolean is refused."""
        fake = _FakeAsyncSocketIOClient(
            answers={"getAutomaticUpdateEnabled": ("pushAutomaticUpdateEnabled", "yes")}
        )
        client, _ = await _client(mocker, fake)

        with pytest.raises(VolumioAPIError, match="Expected JSON boolean"):
            await client.is_automatic_update_enabled()

    async def test_the_updater_channel(self, mocker: MockerFixture):
        """The channel is read beside the available ones, and one is chosen."""
        fake = _FakeAsyncSocketIOClient(
            answers={
                "getUpdaterChannel": (
                    "pushUpdaterChannel",
                    {"availableChannels": ["stable", "test"], "currentChannel": "stable"},
                )
            }
        )
        client, fake = await _client(mocker, fake)

        channel = await client.get_updater_channel()
        await client.set_updater_channel("test")

        assert channel.current_channel == "stable"
        assert channel.available_channels == ["stable", "test"]
        assert fake.calls[-1] == _Call("setUpdaterChannel", {"channel": "test"})

    async def test_the_update_commands(self, mocker: MockerFixture):
        """Checking and installing carry the flags the host expects."""
        client, fake = await _client(mocker)

        await client.check_for_update()
        await client.check_update_cache()
        await client.update()
        await client.update(ignore_integrity_check=True)

        assert fake.calls == [
            _Call("updateCheck", {"hideModal": True}),
            _Call("updateCheckCache", None),
            _Call("update", {"ignoreIntegrityCheck": False}),
            _Call("update", {"ignoreIntegrityCheck": True}),
        ]

    async def test_backup_and_restore(self, mocker: MockerFixture):
        """A backup is read and handed back to be restored."""
        fake = _FakeAsyncSocketIOClient(answers={"getBackup": ("pushBackup", {"playlist": []})})
        client, fake = await _client(mocker, fake)

        backup = await client.backup()
        await client.restore_backup(backup)
        await client.restore_config()

        assert backup == {"playlist": []}
        assert fake.calls[-2:] == [
            _Call("manageBackup", {"playlist": []}),
            _Call("restoreConfig", None),
        ]

    async def test_install_to_disk_refuses_to_run(self, mocker: MockerFixture):
        """Writing to the internal storage is deliberately not implemented."""
        client, fake = await _client(mocker)

        with pytest.raises(NotImplementedError) as exc_info:
            await client.install_to_disk()

        assert "deliberately not implemented" in str(exc_info.value)
        assert 'await client.emit("installToDisk")' in str(exc_info.value)
        assert fake.calls == []

    async def test_multiroom(self, mocker: MockerFixture):
        """The configuration is read, changed, and the role chosen."""
        fake = _FakeAsyncSocketIOClient(
            answers={
                "getMultiroom": ("pushMultiroom", {"enabled": True, "mode": "server"}),
                "setMultiroom": ("pushMultiroom", {"enabled": False, "mode": "single"}),
            }
        )
        client, fake = await _client(mocker, fake)

        current = await client.get_multiroom()
        changed = await client.set_multiroom({"enabled": False})
        await client.set_as_multiroom_client("192.168.1.2")
        await client.set_as_multiroom_server()
        await client.set_as_multiroom_single()
        await client.write_multiroom({"enabled": False})

        assert current.mode == "server"
        assert changed.mode == "single"
        assert fake.calls[-4:] == [
            _Call("setAsMultiroomClient", {"server": "192.168.1.2"}),
            _Call("setAsMultiroomServer", None),
            _Call("setAsMultiroomSingle", None),
            _Call("writeMultiroom", {"enabled": False}),
        ]

    async def test_factory_reset_refuses_to_run(self, mocker: MockerFixture):
        """The reset is deliberately not implemented, and says how to mean it."""
        client, fake = await _client(mocker)

        with pytest.raises(NotImplementedError) as exc_info:
            await client.factory_reset()

        assert "deliberately not implemented" in str(exc_info.value)
        assert 'await client.emit("factoryReset")' in str(exc_info.value)
        assert fake.calls == []

    async def test_delete_user_data_refuses_to_run(self, mocker: MockerFixture):
        """Erasing the user data is deliberately not implemented."""
        client, fake = await _client(mocker)

        with pytest.raises(NotImplementedError) as exc_info:
            await client.delete_user_data()

        assert "deliberately not implemented" in str(exc_info.value)
        assert 'await client.emit("deleteUserData")' in str(exc_info.value)
        assert fake.calls == []

    async def test_the_disabled_events_are_still_named(self, mocker: MockerFixture):
        """Each event keeps its constant, so emit() remains the way to mean it."""
        client, fake = await _client(mocker)

        await client.emit(EVENT_FACTORY_RESET)
        await client.emit(EVENT_DELETE_USER_DATA)
        await client.emit(EVENT_INSTALL_TO_DISK)

        assert fake.calls == [
            _Call("factoryReset", None),
            _Call("deleteUserData", None),
            _Call("installToDisk", None),
        ]
