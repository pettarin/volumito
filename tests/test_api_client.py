"""Tests for the API client adapters of the volumito CLI.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

import asyncio
import threading
from datetime import timedelta
from unittest.mock import AsyncMock, Mock, PropertyMock, call

import pytest

from volumito.cli.api_client import (
    ALARM_OPERATION,
    AUDIO_OPERATION,
    COLLECTION_OPERATION,
    EVENT_LOOP_THREAD_NAME,
    EVENT_OPERATION,
    FAVOURITE_OPERATION,
    MULTIROOM_OPERATION,
    NETWORK_OPERATION,
    PLAYBACK_OPERATION,
    PLAYLIST_OPERATION,
    PLUGIN_OPERATION,
    QUEUE_OPERATION,
    SHARE_OPERATION,
    SYSTEM_OPERATION,
    UI_OPERATION,
    UPDATE_OPERATION,
    APIClient,
    AsyncAPIClient,
    AsyncRESTAPIClient,
    AsyncWebSocketAPIClient,
    SyncRESTAPIClient,
    SyncWebSocketAPIClient,
    UnsupportedOperationError,
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

WEBSOCKET_METHODS = [
    ("add_and_play", ("uri",), {}, QUEUE_OPERATION),
    ("add_cue_track", ("uri", 2, "mpd"), {}, QUEUE_OPERATION),
    ("add_radio_favourite", ("uri",), {}, FAVOURITE_OPERATION),
    ("add_share", ("name", "//host/share", "cifs"), {"username": "user"}, SHARE_OPERATION),
    ("add_to_favourites", ("uri", "title", "mpd", "albumart"), {}, FAVOURITE_OPERATION),
    ("add_to_playlist", ("name", "uri", "mpd"), {}, PLAYLIST_OPERATION),
    ("add_uids_to_queue", (["1", "2"],), {}, QUEUE_OPERATION),
    ("add_web_radio", ("name", "uri"), {}, FAVOURITE_OPERATION),
    ("audio_output_pause", ("output",), {}, AUDIO_OPERATION),
    ("audio_output_play", ("output",), {}, AUDIO_OPERATION),
    ("backup", (), {}, SYSTEM_OPERATION),
    ("call_plugin_method", ("music_service/mpd", "method", {"k": "v"}), {}, PLUGIN_OPERATION),
    ("check_for_update", (), {}, UPDATE_OPERATION),
    ("check_update_cache", (), {}, UPDATE_OPERATION),
    ("consume", (True,), {}, QUEUE_OPERATION),
    ("create_playlist", ("name",), {}, PLAYLIST_OPERATION),
    ("delete_background", ("name",), {}, UI_OPERATION),
    ("delete_folder", ("path",), {}, COLLECTION_OPERATION),
    ("delete_playlist", ("name",), {}, PLAYLIST_OPERATION),
    ("delete_share", ("share",), {}, SHARE_OPERATION),
    ("disable_audio_output", ("output",), {}, AUDIO_OPERATION),
    ("disable_plugin", ("category", "name"), {}, PLUGIN_OPERATION),
    ("discover_network_shares", (), {}, SHARE_OPERATION),
    ("edit_share", ("share",), {"name": "new"}, SHARE_OPERATION),
    ("emit", ("event", {"k": "v"}), {}, EVENT_OPERATION),
    ("enable_audio_output", ("output",), {}, AUDIO_OPERATION),
    ("enable_plugin", ("category", "name"), {}, PLUGIN_OPERATION),
    ("enqueue_playlist", ("name",), {}, PLAYLIST_OPERATION),
    ("get_playlist_content", ("name",), {}, PLAYLIST_OPERATION),
    ("get_plugin_config", ("page",), {}, PLUGIN_OPERATION),
    ("get_share", ("share",), {}, SHARE_OPERATION),
    ("goto", ("artist", "value"), {}, COLLECTION_OPERATION),
    ("import_service_playlists", (), {}, PLAYLIST_OPERATION),
    ("install_plugin", ("url",), {}, PLUGIN_OPERATION),
    ("manage_plugin", ("enable", "category", "name"), {}, PLUGIN_OPERATION),
    ("modify_plugin_status", ("category", "name", True), {}, PLUGIN_OPERATION),
    ("move_in_queue", (1, 2), {}, QUEUE_OPERATION),
    ("off", ("event", None), {}, EVENT_OPERATION),
    ("on", ("event", print), {}, EVENT_OPERATION),
    ("play_favourites", ("name",), {}, FAVOURITE_OPERATION),
    ("play_next", ("uri", "title", "album"), {}, QUEUE_OPERATION),
    ("play_radio_favourites", (), {}, FAVOURITE_OPERATION),
    ("play_volatile", (2,), {}, PLAYBACK_OPERATION),
    ("reboot", (), {}, SYSTEM_OPERATION),
    ("regenerate_thumbnails", (), {}, COLLECTION_OPERATION),
    ("remove_from_favourites", ("uri", "mpd"), {}, FAVOURITE_OPERATION),
    ("remove_from_playlist", ("name", "uri", "mpd"), {}, PLAYLIST_OPERATION),
    ("remove_from_queue", (3,), {}, QUEUE_OPERATION),
    ("remove_radio_favourite", ("uri", "name"), {}, FAVOURITE_OPERATION),
    ("remove_web_radio", ("name",), {}, FAVOURITE_OPERATION),
    ("replace_queue_with_cue_track", ("uri", 2, "mpd"), {}, QUEUE_OPERATION),
    ("request", ("event", "pushEvent", {"k": "v"}, 1.0), {}, EVENT_OPERATION),
    ("rescan_library", (), {}, COLLECTION_OPERATION),
    ("restore_backup", ({"k": "v"},), {}, SYSTEM_OPERATION),
    ("restore_config", (), {}, SYSTEM_OPERATION),
    ("safe_remove_drive", ("name",), {}, SHARE_OPERATION),
    ("save_queue_as_playlist", ("name",), {}, QUEUE_OPERATION),
    ("save_wireless_settings", ("ssid", "secret"), {}, NETWORK_OPERATION),
    ("set_alarms", ([],), {}, ALARM_OPERATION),
    ("set_as_multiroom_client", ("server",), {}, MULTIROOM_OPERATION),
    ("set_as_multiroom_server", (), {}, MULTIROOM_OPERATION),
    ("set_as_multiroom_single", (), {}, MULTIROOM_OPERATION),
    ("set_audio_output_volume", ("output", 50), {}, AUDIO_OPERATION),
    ("set_background", ("name", "path"), {}, UI_OPERATION),
    ("set_experience_settings", (True,), {}, UI_OPERATION),
    ("set_infinity_playback", (True,), {}, PLAYBACK_OPERATION),
    ("set_language", ("en", "English"), {}, UI_OPERATION),
    ("set_multiroom", ({"k": "v"},), {}, MULTIROOM_OPERATION),
    ("set_music_source_enabled", ("name", True), {}, COLLECTION_OPERATION),
    ("set_output_device", ("device", "mixer"), {}, AUDIO_OPERATION),
    ("set_sleep_timer", (timedelta(minutes=5),), {}, ALARM_OPERATION),
    ("shutdown", (), {}, SYSTEM_OPERATION),
    ("standby", (), {}, SYSTEM_OPERATION),
    ("super_search", ("query",), {}, COLLECTION_OPERATION),
    ("uninstall_plugin", ("category", "name"), {}, PLUGIN_OPERATION),
    ("update", (True,), {}, UPDATE_OPERATION),
    ("update_all_metadata", (), {}, COLLECTION_OPERATION),
    ("update_library", ("uri",), {}, COLLECTION_OPERATION),
    ("update_plugin", ("category", "name"), {}, PLUGIN_OPERATION),
    ("update_service_tracklist", ("service",), {}, COLLECTION_OPERATION),
    ("write_multiroom", ({"k": "v"},), {}, MULTIROOM_OPERATION),
]
"""The methods the REST API does not offer: name, positional and keyword arguments, and
how the messages name them. The WebSocket adapters forward them; the REST ones fall back."""

WEBSOCKET_HANDLER_METHODS = ["off", "on"]
"""The methods registering the event handlers, plain calls on the asynchronous client too."""

WEBSOCKET_PROPERTIES = [
    ("alarms", "get_alarms", ALARM_OPERATION),
    ("audio_outputs", "get_audio_outputs", AUDIO_OPERATION),
    ("automatic_update_enabled", "is_automatic_update_enabled", UPDATE_OPERATION),
    ("available_timezones", "get_available_timezones", SYSTEM_OPERATION),
    ("backgrounds", "get_backgrounds", UI_OPERATION),
    ("browse_sources", "get_browse_sources", COLLECTION_OPERATION),
    ("device_name", "get_device_name", SYSTEM_OPERATION),
    ("dsp_config", "get_dsp_config", AUDIO_OPERATION),
    ("experience_settings", "get_experience_settings", UI_OPERATION),
    ("extended_output_devices", "get_extended_output_devices", AUDIO_OPERATION),
    ("infinity_playback", "get_infinity_playback", PLAYBACK_OPERATION),
    ("input_sources", "get_input_sources", AUDIO_OPERATION),
    ("installed_plugins", "get_installed_plugins", PLUGIN_OPERATION),
    ("languages", "get_languages", UI_OPERATION),
    ("last_browse", "get_last_browse", COLLECTION_OPERATION),
    ("menu_items", "get_menu_items", UI_OPERATION),
    ("multiroom", "get_multiroom", MULTIROOM_OPERATION),
    ("music_sources", "get_music_sources", COLLECTION_OPERATION),
    ("network_info", "get_network_info", NETWORK_OPERATION),
    ("output_devices", "get_output_devices", AUDIO_OPERATION),
    ("power_modes", "get_power_modes", SYSTEM_OPERATION),
    ("privacy_settings", "get_privacy_settings", UI_OPERATION),
    ("shares", "get_shares", SHARE_OPERATION),
    ("sleep_timer", "get_sleep_timer", ALARM_OPERATION),
    ("timezone", "get_timezone", SYSTEM_OPERATION),
    ("ui_settings", "get_ui_settings", UI_OPERATION),
    ("updater_channel", "get_updater_channel", UPDATE_OPERATION),
    ("usb_drives", "get_usb_drives", SHARE_OPERATION),
    ("wireless_networks", "get_wireless_networks", NETWORK_OPERATION),
    ("wireless_networks_cache", "get_wireless_networks_cache", NETWORK_OPERATION),
]
"""The read properties the REST API does not offer: the name, the coroutine of the
asynchronous client, and how the messages name them."""

WEBSOCKET_REMEDIES = (
    "--api-client synchronous_websocket or asynchronous_websocket, "
    "or --allow-fallback-to-websocket-api"
)
"""How the error message of a REST adapter names the ways of reaching the WebSocket API."""

WEBSOCKET_SETTERS = [
    ("device_name", "set_device_name", SYSTEM_OPERATION),
    ("timezone", "set_timezone", SYSTEM_OPERATION),
    ("updater_channel", "set_updater_channel", UPDATE_OPERATION),
]
"""The assignable properties the REST API does not offer: the name, the coroutine of the
asynchronous client, and how the messages name them."""

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

    @pytest.mark.parametrize("adapter_class", [SyncRESTAPIClient, SyncWebSocketAPIClient])
    @pytest.mark.parametrize(("name", "args", "kwargs"), METHODS)
    def test_method_forwarded(self, adapter_class, name, args, kwargs):
        """A shared method calls the one of the client with the same arguments."""
        client = Mock()
        getattr(client, name).return_value = "outcome"

        assert getattr(adapter_class(client), name)(*args, **kwargs) == "outcome"
        getattr(client, name).assert_called_once_with(*args, **kwargs)

    @pytest.mark.parametrize("adapter_class", [SyncRESTAPIClient, SyncWebSocketAPIClient])
    @pytest.mark.parametrize(("name", "_async_name"), PROPERTIES)
    def test_property_forwarded(self, adapter_class, name, _async_name):
        """A shared property reads the one of the client."""
        client = Mock()
        prop = _property(client, name, "value")

        assert getattr(adapter_class(client), name) == "value"
        prop.assert_called_once_with()

    @pytest.mark.parametrize("adapter_class", [SyncRESTAPIClient, SyncWebSocketAPIClient])
    @pytest.mark.parametrize(("name", "_async_name"), SETTERS)
    def test_setter_forwarded(self, adapter_class, name, _async_name):
        """Assigning a property assigns the one of the client."""
        client = Mock()

        setattr(adapter_class(client), name, 42)

        assert getattr(client, name) == 42

    @pytest.mark.parametrize(("name", "args", "kwargs", "_operation"), WEBSOCKET_METHODS)
    def test_websocket_method_forwarded(self, name, args, kwargs, _operation):
        """The WebSocket adapter forwards the methods the REST API lacks as they are."""
        client = Mock()
        getattr(client, name).return_value = "outcome"

        assert getattr(SyncWebSocketAPIClient(client), name)(*args, **kwargs) == "outcome"
        getattr(client, name).assert_called_once_with(*args, **kwargs)

    @pytest.mark.parametrize(("name", "_async_name", "_operation"), WEBSOCKET_PROPERTIES)
    def test_websocket_property_forwarded(self, name, _async_name, _operation):
        """The WebSocket adapter reads the properties the REST API lacks from the client."""
        client = Mock()
        prop = _property(client, name, "value")

        assert getattr(SyncWebSocketAPIClient(client), name) == "value"
        prop.assert_called_once_with()

    @pytest.mark.parametrize(("name", "_async_name", "_operation"), WEBSOCKET_SETTERS)
    def test_websocket_setter_forwarded(self, name, _async_name, _operation):
        """Assigning a property the REST API lacks assigns the one of the client."""
        client = Mock()

        setattr(SyncWebSocketAPIClient(client), name, "new")

        assert getattr(client, name) == "new"

    @pytest.mark.parametrize(("name", "args", "kwargs"), REST_ONLY_METHODS)
    def test_rest_only_method_forwarded(self, name, args, kwargs):
        """The REST adapter forwards the members the WebSocket API lacks as they are."""
        client = Mock()
        getattr(client, name).return_value = "outcome"

        assert getattr(SyncRESTAPIClient(client), name)(*args, **kwargs) == "outcome"
        getattr(client, name).assert_called_once_with(*args, **kwargs)

    def test_rest_notifications_forwarded(self):
        """The REST adapter reads the notification URLs of the client."""
        client = Mock()
        _property(client, "notifications", "urls")

        assert SyncRESTAPIClient(client).notifications == "urls"

    def test_rest_story_forwards_only_the_entities_given(self):
        """A story query passes the client only the entities it was given."""
        client = Mock()

        SyncRESTAPIClient(client).get_story(artist="b")

        client.get_story.assert_called_once_with(artist="b")

    def test_rest_lifecycle(self):
        """The REST adapter has nothing to open, and closes the session of the client."""
        client = Mock()

        with SyncRESTAPIClient(client) as adapter:
            adapter.open()
            client.close.assert_not_called()
        adapter.close()

        assert client.mock_calls == [call.close(), call.close()]

    def test_websocket_lifecycle(self):
        """The WebSocket adapter connects on open and disconnects on close."""
        client = Mock()

        with SyncWebSocketAPIClient(client) as adapter:
            client.connect.assert_called_once_with()
            client.disconnect.assert_not_called()
        client.disconnect.assert_called_once_with()
        adapter.close()

        assert client.disconnect.call_count == 2

    def test_websocket_close_failure_is_a_warning(self):
        """A failure while disconnecting is logged, not raised."""
        client = Mock()
        client.disconnect.side_effect = RuntimeError("boom")

        SyncWebSocketAPIClient(client).close()

        client.logger.warning.assert_called_once_with(
            "Closing the synchronous WebSocket API client failed (boom)"
        )

    def test_websocket_browse_without_offset(self):
        """Without an offset, the answer of the client is returned as it is."""
        client = Mock()
        results = BrowseResults.from_envelope(_ENVELOPE)
        client.browse.return_value = results

        assert SyncWebSocketAPIClient(client).browse("uri") is results
        client.browse.assert_called_once_with("uri")

    def test_websocket_browse_with_offset(self):
        """The offset skips the first items of the answer, since the API takes none."""
        client = Mock()
        client.browse.return_value = BrowseResults.from_envelope(_ENVELOPE)

        results = SyncWebSocketAPIClient(client).browse(None, 1)

        assert [item.name for item in results.items] == ["QOBUZ"]
        client.browse.assert_called_once_with(None)


class TestAsyncAdapters:
    """Test cases for the adapters of the asynchronous clients."""

    @pytest.mark.parametrize("adapter_class", [AsyncRESTAPIClient, AsyncWebSocketAPIClient])
    @pytest.mark.parametrize(("name", "args", "kwargs"), METHODS)
    def test_method_forwarded(self, adapter_class, name, args, kwargs):
        """A shared method awaits the coroutine of the client with the same arguments."""
        client = _async_client()
        setattr(client, name, AsyncMock(return_value="outcome"))

        with adapter_class(client) as adapter:
            assert getattr(adapter, name)(*args, **kwargs) == "outcome"
        getattr(client, name).assert_awaited_once_with(*args, **kwargs)

    @pytest.mark.parametrize("adapter_class", [AsyncRESTAPIClient, AsyncWebSocketAPIClient])
    @pytest.mark.parametrize(("name", "async_name"), PROPERTIES)
    def test_property_forwarded(self, adapter_class, name, async_name):
        """A shared property awaits the reading coroutine of the client."""
        client = _async_client()
        setattr(client, async_name, AsyncMock(return_value="value"))

        with adapter_class(client) as adapter:
            assert getattr(adapter, name) == "value"
        getattr(client, async_name).assert_awaited_once_with()

    @pytest.mark.parametrize("adapter_class", [AsyncRESTAPIClient, AsyncWebSocketAPIClient])
    @pytest.mark.parametrize(("name", "async_name"), SETTERS)
    def test_setter_forwarded(self, adapter_class, name, async_name):
        """Assigning a property awaits the setting coroutine of the client."""
        client = _async_client()
        setattr(client, async_name, AsyncMock())

        with adapter_class(client) as adapter:
            setattr(adapter, name, 42)
        getattr(client, async_name).assert_awaited_once_with(42)

    @pytest.mark.parametrize(
        ("name", "args", "kwargs", "_operation"),
        [row for row in WEBSOCKET_METHODS if row[0] not in WEBSOCKET_HANDLER_METHODS],
    )
    def test_websocket_method_awaited(self, name, args, kwargs, _operation):
        """The WebSocket adapter awaits the coroutines the REST API lacks as they are."""
        client = _async_client()
        setattr(client, name, AsyncMock(return_value="outcome"))

        with AsyncWebSocketAPIClient(client) as adapter:
            assert getattr(adapter, name)(*args, **kwargs) == "outcome"
        getattr(client, name).assert_awaited_once_with(*args, **kwargs)

    @pytest.mark.parametrize(
        ("name", "args", "kwargs", "_operation"),
        [row for row in WEBSOCKET_METHODS if row[0] in WEBSOCKET_HANDLER_METHODS],
    )
    def test_websocket_handler_registered_directly(self, name, args, kwargs, _operation):
        """Registering a handler is a plain call on the client, needing no loop."""
        client = _async_client()
        getattr(client, name).return_value = "outcome"

        assert getattr(AsyncWebSocketAPIClient(client), name)(*args, **kwargs) == "outcome"
        getattr(client, name).assert_called_once_with(*args, **kwargs)

    @pytest.mark.parametrize(("name", "async_name", "_operation"), WEBSOCKET_PROPERTIES)
    def test_websocket_property_awaited(self, name, async_name, _operation):
        """The WebSocket adapter awaits the reading coroutines the REST API lacks."""
        client = _async_client()
        setattr(client, async_name, AsyncMock(return_value="value"))

        with AsyncWebSocketAPIClient(client) as adapter:
            assert getattr(adapter, name) == "value"
        getattr(client, async_name).assert_awaited_once_with()

    @pytest.mark.parametrize(("name", "async_name", "_operation"), WEBSOCKET_SETTERS)
    def test_websocket_setter_awaited(self, name, async_name, _operation):
        """Assigning a property the REST API lacks awaits the setting coroutine."""
        client = _async_client()
        setattr(client, async_name, AsyncMock())

        with AsyncWebSocketAPIClient(client) as adapter:
            setattr(adapter, name, "new")
        getattr(client, async_name).assert_awaited_once_with("new")

    @pytest.mark.parametrize(("name", "args", "kwargs"), REST_ONLY_METHODS)
    def test_rest_only_method_forwarded(self, name, args, kwargs):
        """The REST adapter awaits the members the WebSocket API lacks as they are."""
        client = _async_client()
        setattr(client, name, AsyncMock(return_value="outcome"))

        with AsyncRESTAPIClient(client) as adapter:
            assert getattr(adapter, name)(*args, **kwargs) == "outcome"
        getattr(client, name).assert_awaited_once_with(*args, **kwargs)

    def test_rest_notifications_forwarded(self):
        """The REST adapter awaits the notification URLs of the client."""
        client = _async_client()
        client.get_notifications = AsyncMock(return_value="urls")

        with AsyncRESTAPIClient(client) as adapter:
            assert adapter.notifications == "urls"

    def test_rest_story_forwards_only_the_entities_given(self):
        """A story query passes the client only the entities it was given."""
        client = _async_client()
        client.get_story = AsyncMock(return_value="story")

        with AsyncRESTAPIClient(client) as adapter:
            assert adapter.get_story(label="c") == "story"
        client.get_story.assert_awaited_once_with(label="c")

    def test_the_calls_share_one_loop_on_its_own_thread(self):
        """Every coroutine runs on the same loop, served by the thread of the adapter."""
        client = _async_client()
        client.ping = AsyncMock(
            side_effect=lambda: (asyncio.get_running_loop(), threading.current_thread().name)
        )

        with AsyncRESTAPIClient(client) as adapter:
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
        adapter = AsyncRESTAPIClient(client)
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

        with AsyncWebSocketAPIClient(client):
            client.connect.assert_awaited_once_with()
            client.disconnect.assert_not_awaited()

        client.disconnect.assert_awaited_once_with()
        assert _loop_threads() == []

    def test_not_open(self):
        """A member used before opening fails, without leaking a coroutine."""
        client = _async_client()
        client.ping = AsyncMock(return_value="pong")

        with pytest.raises(RuntimeError, match="asynchronous REST API client is not open"):
            AsyncRESTAPIClient(client).ping()

        client.ping.assert_not_awaited()

    def test_reopen_after_close(self):
        """A closed adapter can be opened again, on a fresh loop."""
        client = _async_client()
        client.ping = AsyncMock(side_effect=lambda: asyncio.get_running_loop())
        adapter = AsyncRESTAPIClient(client)

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
        adapter = AsyncWebSocketAPIClient(client)

        with pytest.raises(VolumioConnectionError, match="unreachable"):
            adapter.open()

        assert _loop_threads() == []
        with pytest.raises(RuntimeError, match="is not open"):
            adapter.ping()

    def test_close_failure_is_a_warning(self):
        """A failure while closing the session is logged, and the loop still stopped."""
        client = _async_client()
        client.close = AsyncMock(side_effect=RuntimeError("boom"))
        adapter = AsyncRESTAPIClient(client)
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

        with AsyncWebSocketAPIClient(client):
            assert not tasks[0].done()

        assert tasks[0].cancelled()

    def test_websocket_browse_without_offset(self):
        """Without an offset, the answer of the client is returned as it is."""
        client = _async_client()
        results = BrowseResults.from_envelope(_ENVELOPE)
        client.browse = AsyncMock(return_value=results)

        with AsyncWebSocketAPIClient(client) as adapter:
            assert adapter.browse("uri") is results
        client.browse.assert_awaited_once_with("uri")

    def test_websocket_browse_with_offset(self):
        """The offset skips the first items of the answer, since the API takes none."""
        client = _async_client()
        client.browse = AsyncMock(return_value=BrowseResults.from_envelope(_ENVELOPE))

        with AsyncWebSocketAPIClient(client) as adapter:
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
        "adapter_class", [SyncWebSocketAPIClient, AsyncWebSocketAPIClient]
    )
    @pytest.mark.parametrize(("name", "args", "kwargs", "operation"), UNSUPPORTED)
    def test_unsupported_without_fallback(self, adapter_class, name, args, kwargs, operation):
        """Without a fallback, the members the WebSocket API lacks raise."""
        adapter, _ = self._adapter(adapter_class)
        expected = (
            f"The {adapter.description} does not offer {operation}: use "
            "--api-client synchronous_rest or asynchronous_rest, "
            "or --allow-fallback-to-rest-api"
        )

        with pytest.raises(UnsupportedOperationError) as excinfo:
            getattr(adapter, name)(*args, **kwargs)

        assert str(excinfo.value) == expected
        adapter.close()

    @pytest.mark.parametrize(
        "adapter_class", [SyncWebSocketAPIClient, AsyncWebSocketAPIClient]
    )
    def test_unsupported_notifications_without_fallback(self, adapter_class):
        """Without a fallback, reading the notification URLs raises."""
        adapter, _ = self._adapter(adapter_class)

        with pytest.raises(UnsupportedOperationError, match="does not offer the notification URLs"):
            _ = adapter.notifications

        adapter.close()

    @pytest.mark.parametrize(
        "adapter_class", [SyncWebSocketAPIClient, AsyncWebSocketAPIClient]
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
        "adapter_class", [SyncWebSocketAPIClient, AsyncWebSocketAPIClient]
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
        adapter, _ = self._adapter(SyncWebSocketAPIClient, fallback=factory)

        adapter.close()

        factory.assert_not_called()


class TestRESTFallback:
    """Test cases for the WebSocket API client the REST adapters fall back to."""

    @staticmethod
    def _adapter(adapter_class, fallback=None):
        """Build a REST adapter over a mock client, opened."""
        client = _async_client() if issubclass(adapter_class, AsyncAPIClient) else Mock()
        adapter = adapter_class(client, fallback=fallback)
        adapter.open()
        return adapter, client

    @staticmethod
    def _unsupported(adapter, operation):
        """The error message of an adapter lacking an operation, without a fallback."""
        return f"The {adapter.description} does not offer {operation}: use {WEBSOCKET_REMEDIES}"

    @staticmethod
    def _falling_back(operation):
        """The warning logged when an operation goes through the fallback."""
        return (
            f"Falling back to the WebSocket API client for {operation} "
            "(the REST API does not offer them)"
        )

    @pytest.mark.parametrize("adapter_class", [SyncRESTAPIClient, AsyncRESTAPIClient])
    @pytest.mark.parametrize(("name", "args", "kwargs", "operation"), WEBSOCKET_METHODS)
    def test_unsupported_method_without_fallback(
        self, adapter_class, name, args, kwargs, operation
    ):
        """Without a fallback, the methods the REST API lacks raise, naming the remedies."""
        adapter, _ = self._adapter(adapter_class)

        with pytest.raises(UnsupportedOperationError) as excinfo:
            getattr(adapter, name)(*args, **kwargs)

        assert str(excinfo.value) == self._unsupported(adapter, operation)
        adapter.close()

    @pytest.mark.parametrize("adapter_class", [SyncRESTAPIClient, AsyncRESTAPIClient])
    @pytest.mark.parametrize(("name", "_async_name", "operation"), WEBSOCKET_PROPERTIES)
    def test_unsupported_property_without_fallback(
        self, adapter_class, name, _async_name, operation
    ):
        """Without a fallback, reading a property the REST API lacks raises."""
        adapter, _ = self._adapter(adapter_class)

        with pytest.raises(UnsupportedOperationError) as excinfo:
            _ = getattr(adapter, name)

        assert str(excinfo.value) == self._unsupported(adapter, operation)
        adapter.close()

    @pytest.mark.parametrize("adapter_class", [SyncRESTAPIClient, AsyncRESTAPIClient])
    @pytest.mark.parametrize(("name", "_async_name", "operation"), WEBSOCKET_SETTERS)
    def test_unsupported_setter_without_fallback(
        self, adapter_class, name, _async_name, operation
    ):
        """Without a fallback, assigning a property the REST API lacks raises."""
        adapter, _ = self._adapter(adapter_class)

        with pytest.raises(UnsupportedOperationError) as excinfo:
            setattr(adapter, name, "new")

        assert str(excinfo.value) == self._unsupported(adapter, operation)
        adapter.close()

    @pytest.mark.parametrize("adapter_class", [SyncRESTAPIClient, AsyncRESTAPIClient])
    @pytest.mark.parametrize(("name", "args", "kwargs", "operation"), WEBSOCKET_METHODS)
    def test_method_delegated_to_the_fallback(
        self, adapter_class, name, args, kwargs, operation
    ):
        """With a fallback, the methods the REST API lacks use the WebSocket API client."""
        websocket = Mock()
        getattr(websocket, name).return_value = "outcome"
        factory = Mock(return_value=websocket)
        adapter, client = self._adapter(adapter_class, fallback=factory)

        assert getattr(adapter, name)(*args, **kwargs) == "outcome"

        getattr(websocket, name).assert_called_once_with(*args, **kwargs)
        websocket.open.assert_called_once_with()
        client.logger.warning.assert_called_once_with(self._falling_back(operation))
        adapter.close()

    @pytest.mark.parametrize("adapter_class", [SyncRESTAPIClient, AsyncRESTAPIClient])
    @pytest.mark.parametrize(("name", "_async_name", "operation"), WEBSOCKET_PROPERTIES)
    def test_property_delegated_to_the_fallback(
        self, adapter_class, name, _async_name, operation
    ):
        """With a fallback, the properties the REST API lacks read the WebSocket API client."""
        websocket = Mock()
        prop = _property(websocket, name, "value")
        factory = Mock(return_value=websocket)
        adapter, client = self._adapter(adapter_class, fallback=factory)

        assert getattr(adapter, name) == "value"

        prop.assert_called_once_with()
        client.logger.warning.assert_called_once_with(self._falling_back(operation))
        adapter.close()

    @pytest.mark.parametrize("adapter_class", [SyncRESTAPIClient, AsyncRESTAPIClient])
    @pytest.mark.parametrize(("name", "_async_name", "operation"), WEBSOCKET_SETTERS)
    def test_setter_delegated_to_the_fallback(
        self, adapter_class, name, _async_name, operation
    ):
        """With a fallback, assigning a property the REST API lacks assigns the client one."""
        websocket = Mock()
        factory = Mock(return_value=websocket)
        adapter, client = self._adapter(adapter_class, fallback=factory)

        setattr(adapter, name, "new")

        assert getattr(websocket, name) == "new"
        client.logger.warning.assert_called_once_with(self._falling_back(operation))
        adapter.close()

    @pytest.mark.parametrize("adapter_class", [SyncRESTAPIClient, AsyncRESTAPIClient])
    def test_the_fallback_is_built_once_and_closed_with_the_adapter(self, adapter_class):
        """The WebSocket API client is built on the first operation, kept, and closed at the end."""
        websocket = Mock()
        _property(websocket, "sleep_timer", "timer")
        websocket.backup.return_value = {"k": "v"}
        factory = Mock(return_value=websocket)
        adapter, client = self._adapter(adapter_class, fallback=factory)

        assert adapter.sleep_timer == "timer"
        assert adapter.backup() == {"k": "v"}
        websocket.close.assert_not_called()
        adapter.close()

        factory.assert_called_once_with()
        websocket.open.assert_called_once_with()
        websocket.close.assert_called_once_with()
        assert client.logger.warning.call_count == 2
        # The session of the REST client is released after the fallback
        client.close.assert_called_once_with()

    def test_the_fallback_is_not_closed_when_never_built(self):
        """Closing an adapter that never fell back builds nothing."""
        factory = Mock()
        adapter, _ = self._adapter(SyncRESTAPIClient, fallback=factory)

        adapter.close()

        factory.assert_not_called()


class TestCommonMembers:
    """Test cases for the members every adapter shares."""

    _HOST = VolumioHostConfiguration(host="volumio", rest_api_port=3001, websocket_port=3002)

    @pytest.mark.parametrize(
        ("adapter_class", "description", "base_url"),
        [
            (SyncRESTAPIClient, "synchronous REST API client", "http://volumio:3001"),
            (AsyncRESTAPIClient, "asynchronous REST API client", "http://volumio:3001"),
            (SyncWebSocketAPIClient, "synchronous WebSocket API client", "http://volumio:3002"),
            (AsyncWebSocketAPIClient, "asynchronous WebSocket API client", "http://volumio:3002"),
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

        adapter = SyncRESTAPIClient(client)

        assert adapter.host_configuration is self._HOST
        assert adapter.logger is client.logger

    def test_the_surface_is_abstract(self):
        """The surface itself cannot be instantiated."""
        with pytest.raises(TypeError):
            APIClient(Mock())
