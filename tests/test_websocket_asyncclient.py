"""Tests for the async WebSocket API client module.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

import logging
from dataclasses import dataclass, field
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
)
from volumito.clients.host_configuration import VolumioHostConfiguration  # noqa: E402
from volumito.clients.models import Playlist, QueueTrack  # noqa: E402
from volumito.clients.websocket.asyncclient import VolumioAsyncWebSocketClient  # noqa: E402
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
    """The connection the async WebSocket client owns."""

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
            answers={"getSleep": ("pushSleep", {"enabled": False})}
        )
        client, _ = await _client(mocker, fake)

        assert await client.request("getSleep", "pushSleep") == {"enabled": False}

    async def test_request_refuses_an_event_with_no_known_answer(self, mocker: MockerFixture):
        """Reading an event the host does not answer refuses."""
        client, fake = await _client(mocker)

        with pytest.raises(ValueError, match="answers no 'getSleep' event"):
            await client.request("getSleep")

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
