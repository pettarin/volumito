"""Tests for the CLI module.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

import json
import os
import re
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock, PropertyMock

import click
import pytest
import requests
import yaml
from click.testing import CliRunner
from pytest_mock import MockerFixture

from volumito import __version__
from volumito.cli.api_client import (
    AsyncRESTAPIClient,
    AsyncWebSocketAPIClient,
    SyncRESTAPIClient,
    SyncWebSocketAPIClient,
    UnsupportedOperationError,
)
from volumito.cli.click_helpers import (
    APIClientParamType,
    OnOffParamType,
    ResultKindsParamType,
    SchemeParamType,
    SeekParamType,
    SleepTimerParamType,
    VolumeParamType,
    correct_audio_extension,
    create_client,
    render_output_filename,
    resolve_command_path,
)
from volumito.cli.console import LOGGER
from volumito.cli.constants import (
    API_CLIENTS,
    MPD_PORT_VOLUMIO_3,
    MPD_PORT_VOLUMIO_4,
    MUTUALLY_EXCLUSIVE_CURRENT_TRACK_ERROR,
    SHORT_FORMAT_FIELDS_PLAYER_STATE,
    SHORT_FORMAT_FIELDS_QUEUE_LIST,
    SHORT_FORMAT_FIELDS_TRACK_INFO,
    STORY_ARTIST_ALBUM_ARGUMENTS_ERROR,
    STORY_ARTIST_ARGUMENT_ERROR,
)
from volumito.cli.pure_helpers import (
    display_position,
    expand_manifest_file,
    expand_timestamp_placeholder,
    extract_filename_from_uri,
    filter_fields,
    filter_queue_fields,
    filter_zones_fields,
    format_as_json,
    format_as_pretty,
    format_as_table,
    format_browse_results_as_table,
    format_notification_as_line,
    format_queue_as_table,
    format_search_results_as_table,
    format_termination_conditions,
    is_expandable_uri,
    is_mbid,
    manifest_matches_queue,
    parse_result_kinds,
    parse_time_to_seconds,
    parse_track_selection,
    preserve_local_file_name,
    queue_album_volumes,
    queue_track_metadata_current,
    rebase_queue_positions,
    sanitize_filename_component,
    story_query_reference,
)
from volumito.cli.volumito import main
from volumito.clients import (
    Album,
    Artist,
    BrowseResults,
    Label,
    Place,
    RemoteCommandResult,
    SearchResults,
    VolumioHostConfiguration,
)
from volumito.clients.common import stored_local_uri
from volumito.clients.errors import (
    VolumioAsyncError,
    VolumioSCPError,
    VolumioSSHError,
    VolumioWebSocketError,
)
from volumito.clients.models import (
    Alarm,
    Alarms,
    AudioOutputs,
    AvailablePlugins,
    Backgrounds,
    BrowseSources,
    CollectionStatistics,
    ExperienceSettings,
    InfinityPlayback,
    InputSources,
    Languages,
    MenuItems,
    Multiroom,
    MusicSources,
    NetworkInfo,
    Notifications,
    OutputDevices,
    PlayerState,
    PlaylistContent,
    Playlists,
    Plugins,
    PowerModes,
    PrivacySettings,
    PushNotification,
    Queue,
    QueueTrack,
    SearchResultItemKind,
    Share,
    Shares,
    SleepTimer,
    Story,
    SuccessResponse,
    SystemInfo,
    SystemVersion,
    Timezones,
    UiConfig,
    UiSettings,
    UpdateCheck,
    UpdaterChannel,
    UsbDrives,
    VolumioModel,
    WirelessNetworks,
    Zones,
)
from volumito.clients.rest import (
    VolumioAPIError,
    VolumioConnectionError,
)

# The per-command file-name-template defaults emitted in the bundled template.
_ALBUMART_FILE_NAME_TEMPLATE = "000___{album}___{artist}.{extension}"
_AUDIO_FILE_NAME_TEMPLATE = "{position:03d}___{title}___{album}___{artist}.{extension}"
_QUEUE_ALBUMART_FILE_NAME_TEMPLATE = "{artist}/{album_volume}/000___{album}.{extension}"
_QUEUE_AUDIO_FILE_NAME_TEMPLATE = (
    "{artist}/{album_volume}/{tracknumber:03d}___{title}.{extension}"
)


@pytest.fixture(autouse=True)
def _isolate_config_probing(mocker: MockerFixture):
    """Isolate every CLI test from a real configuration file on the host.

    The eager -c callback probes the standard locations on every invocation; without
    this, a developer's real ~/volumito.yaml would perturb unrelated tests. Tests
    that need probing patch configuration_paths with their own values.
    """
    mocker.patch(
        "volumito.cli.configuration.configuration_paths",
        return_value=[],
    )


_RESPONSE_MODELS: dict[str, type[VolumioModel]] = {
    "alarms": Alarms,
    "audio_outputs": AudioOutputs,
    "available_plugins": AvailablePlugins,
    "available_timezones": Timezones,
    "backgrounds": Backgrounds,
    "browse_sources": BrowseSources,
    "collection_statistics": CollectionStatistics,
    "dsp_config": UiConfig,
    "experience_settings": ExperienceSettings,
    "infinity_playback": InfinityPlayback,
    "input_sources": InputSources,
    "installed_plugins": Plugins,
    "languages": Languages,
    "menu_items": MenuItems,
    "multiroom": Multiroom,
    "music_sources": MusicSources,
    "network_info": NetworkInfo,
    "notifications": Notifications,
    "playlists": Playlists,
    "power_modes": PowerModes,
    "privacy_settings": PrivacySettings,
    "queue": Queue,
    "shares": Shares,
    "sleep_timer": SleepTimer,
    "state": PlayerState,
    "system_info": SystemInfo,
    "system_version": SystemVersion,
    "ui_settings": UiSettings,
    "updater_channel": UpdaterChannel,
    "usb_drives": UsbDrives,
    "wireless_networks": WirelessNetworks,
    "wireless_networks_cache": WirelessNetworks,
    "zones": Zones,
}
"""The response model each mocked client property returns, keyed by property name."""


def _as_model(name: str, value: object) -> object:
    """Parse a raw payload into the model the named client property returns.

    The tests express the mocked responses as the raw JSON payloads the Volumio API
    returns; this marshals them exactly like the client does, leaving anything else
    (scalars, exceptions) untouched.

    Args:
        name: The property name (e.g., "state")
        value: The mocked value (a raw payload, or anything else)

    Returns:
        The parsed model, or the value unchanged
    """
    model = _RESPONSE_MODELS.get(name)
    if model is None:
        return value
    if isinstance(value, dict):
        return model.from_raw(value)
    if isinstance(value, list):
        if issubclass(model, Notifications):
            return model.from_urls(value)
        if issubclass(model, Playlists):
            return model.from_names(value)
    return value


def _queue_tracks(payloads: list[dict[str, object]]) -> list[QueueTrack]:
    """Parse raw queue entries into the tracks the helpers work on.

    Args:
        payloads: The raw queue entries, as the Volumio API returns them

    Returns:
        The parsed queue tracks
    """
    return [QueueTrack.from_raw(payload) for payload in payloads]


def _played_positions(mock_client: Mock) -> list[object]:
    """Return the queue position of every play() call on the mocked client.

    The queue download plays a track of the queue, the other callers a position.

    Args:
        mock_client: The mocked VolumioRESTAPIClient instance

    Returns:
        The played queue position of each call, in call order
    """
    positions: list[object] = []
    for call in mock_client.play.call_args_list:
        played = call.args[0] if call.args else None
        positions.append(played.position if isinstance(played, QueueTrack) else played)
    return positions


def _attach_story(mock_client: Mock, envelope: dict[str, object]) -> None:
    """Make the story query methods marshal a raw envelope like the client does.

    A failure envelope therefore raises VolumioStoryError, exactly as the client
    does when the Volumio host reports a failed query.

    Args:
        mock_client: The mocked VolumioRESTAPIClient instance
        envelope: The raw response envelope of the metavolumio query
    """

    def marshal(*args: object, **kwargs: object) -> Story:
        return Story.from_envelope(envelope)

    mock_client.get_story.side_effect = marshal
    mock_client.get_album_credits.side_effect = marshal


def _attach_property(mock_client: Mock, name: str, **kwargs: object) -> PropertyMock:
    """Attach a PropertyMock as the ``name`` property of the mocked client.

    The property must live on the mock's type (each Mock instance has its own type,
    so this does not leak across tests). The PropertyMock is also stashed on the
    mock as the plain ``{name}_property`` attribute, so tests can assert on the
    property accesses (e.g., ``mock_client.state_property.assert_not_called()``).
    Raw payloads given as ``return_value`` (or in a ``side_effect`` list) are parsed
    into the response model of the property.

    Args:
        mock_client: The mocked VolumioRESTAPIClient instance
        name: The property name (e.g., "state")
        **kwargs: Passed to PropertyMock (e.g., return_value, side_effect)

    Returns:
        The attached PropertyMock
    """
    if "return_value" in kwargs:
        kwargs["return_value"] = _as_model(name, kwargs["return_value"])
    side_effect = kwargs.get("side_effect")
    if isinstance(side_effect, list):
        kwargs["side_effect"] = [_as_model(name, item) for item in side_effect]
    prop = PropertyMock(**kwargs)
    setattr(type(mock_client), name, prop)
    setattr(mock_client, f"{name}_property", prop)
    return prop


_MP3_CONTENT = b"ID3\x04\x00\x00\x00\x00\x00\x23tag"
"""An MP3 file opening with an ID3v2 tag, as the format sniffing recognizes it."""

class TestFilterFields:
    """Test cases for the filter_fields function."""

    def test_filter_fields_all(self):
        """Test filter_fields with 'all' option."""
        state = {
            "status": "play",
            "title": "Test",
            "volume": 100,
            "mute": False,
            "extra": "data",
        }

        result = filter_fields(state, "ALL")

        assert result == state
        assert "extra" in result

    def test_filter_fields_short(self):
        """Test filter_fields with 'short' option."""
        state = {
            "position": 0,
            "title": "Test Song",
            "artist": "Test Artist",
            "album": "Test Album",
            "samplerate": "44.1 kHz",
            "bitdepth": "16 bit",
            "channels": 2,
            "service": "mpd",
            "duration": 180,
            "volume": 100,
            "mute": False,
            "extra": "data",
        }

        result = filter_fields(state, "SHORT")

        # Should only include SHORT_FORMAT_FIELDS_PLAYER_STATE
        for field in SHORT_FORMAT_FIELDS_PLAYER_STATE:
            if field in state:
                assert field in result

        # volume and mute are part of the short field set
        assert "volume" in result
        assert "mute" in result

        # Audio-quality fields are now part of the short field set
        assert "samplerate" in result
        assert "bitdepth" in result
        assert "channels" in result

        # service is not part of the short field set
        assert "service" not in result

        # Should not include non-short fields
        assert "extra" not in result

    def test_filter_fields_short_with_missing_fields(self):
        """Test filter_fields with 'short' when some fields are missing."""
        state = {"title": "Test", "artist": "Test Artist"}

        result = filter_fields(state, "SHORT")

        assert "title" in result
        assert "artist" in result
        assert len(result) == 2

    def test_filter_fields_short_track(self):
        """Test filter_fields with a custom short-field list (SHORT_FORMAT_FIELDS_TRACK_INFO)."""
        state = {
            "position": 0,
            "title": "Test Song",
            "artist": "Test Artist",
            "album": "Test Album",
            "duration": 180,
            "trackType": "flac",
            "samplerate": "44.1 kHz",
            "bitdepth": "16 bit",
            "channels": 2,
            "status": "play",
            "volume": 100,
            "extra": "data",
        }

        result = filter_fields(state, "SHORT", SHORT_FORMAT_FIELDS_TRACK_INFO)

        # Track-oriented fields are kept
        for field in SHORT_FORMAT_FIELDS_TRACK_INFO:
            assert field in result

        # Player-only and unknown fields are dropped
        assert "status" not in result
        assert "volume" not in result
        assert "extra" not in result

    def test_filter_fields_custom_list(self):
        """A comma-separated list keeps exactly those fields, in order, omitting unknowns."""
        state = {
            "status": "play",
            "title": "Test Song",
            "artist": "Test Artist",
            "album": "Test Album",
            "volume": 100,
        }

        result = filter_fields(state, "artist,album,foobar")

        # Only the requested, present fields, in the requested order
        assert list(result.keys()) == ["artist", "album"]
        # Unknown field silently omitted
        assert "foobar" not in result
        # Non-requested fields dropped
        assert "status" not in result

    def test_filter_fields_custom_list_strips_whitespace_and_empties(self):
        """Whitespace around names is trimmed and empty entries are dropped."""
        state = {"artist": "A", "album": "B", "title": "C"}

        result = filter_fields(state, " artist , , album ")

        assert list(result.keys()) == ["artist", "album"]

    def test_filter_fields_dotted_path(self):
        """A dotted field resolves into nested dictionaries, inside its rebuilt nesting."""
        state = {"success": True, "data": {"type": "story", "value": "A story."}}

        result = filter_fields(state, "data.value")

        assert result == {"data": {"value": "A story."}}

    def test_filter_fields_dotted_path_missing_leaf(self):
        """A dotted field whose leaf is missing is silently omitted."""
        state = {"success": True, "data": {"type": "story"}}

        result = filter_fields(state, "success,data.value")

        assert result == {"success": True}

    def test_filter_fields_dotted_path_non_dict_intermediate(self):
        """A dotted field whose intermediate value is not a dictionary is omitted."""
        state = {"data": "not a dictionary"}

        result = filter_fields(state, "data.value")

        assert result == {}

    def test_filter_fields_dotted_literal_key_precedence(self):
        """A literal top-level key containing a dot wins over the dotted-path lookup."""
        state = {"data.value": "literal", "data": {"value": "nested"}}

        result = filter_fields(state, "data.value")

        assert result == {"data.value": "literal"}


class TestFormatFunctions:
    """Test cases for formatting functions."""

    def test_format_as_json(self):
        """Test format_as_json function."""
        state = {"title": "Test", "artist": "Artist"}

        result = format_as_json(state)

        assert isinstance(result, str)
        parsed = json.loads(result)
        assert parsed == state
        # Check for 2-space indentation
        assert "  " in result
        assert "    " not in result or result.count("    ") < result.count("  ")

    def test_format_as_pretty(self):
        """Test format_as_pretty function."""
        state = {"title": "Test", "artist": "Artist"}

        result = format_as_pretty(state)

        assert isinstance(result, str)
        parsed = json.loads(result)
        assert parsed == state
        # Check for 4-space indentation
        assert "    " in result

    def test_format_as_pretty_seek(self):
        """Test format_as_pretty renders seek (milliseconds) as HH:MM:SS.mmm."""
        state = {"title": "Test", "seek": 42123}

        result = format_as_pretty(state)

        parsed = json.loads(result)
        assert parsed["seek"] == "00:00:42.123"

    def test_display_position(self):
        """Test display_position with both indexing bases."""
        assert display_position(0, True) == 1
        assert display_position(0, False) == 0
        assert display_position(7, True) == 8
        assert display_position(7, False) == 7

    def test_format_as_pretty_position_starting_at_one(self):
        """Test format_as_pretty renders position starting at one by default."""
        state = {"title": "Test", "position": 0}

        parsed = json.loads(format_as_pretty(state))

        assert parsed["position"] == 1

    def test_format_as_pretty_position_starting_at_zero(self):
        """Test format_as_pretty leaves position as returned by the API when 0-based."""
        state = {"title": "Test", "position": 0}

        parsed = json.loads(format_as_pretty(state, position_starting_at_one=False))

        assert parsed["position"] == 0

    def test_format_as_pretty_duration(self):
        """Test format_as_pretty renders duration (seconds) as HH:MM:SS."""
        state = {"title": "Test", "duration": 3725}

        parsed = json.loads(format_as_pretty(state))

        assert parsed["duration"] == "01:02:05"

    def test_format_as_json_ignores_position_indexing(self):
        """Test format_as_json always prints the position as returned by the API."""
        state = {"title": "Test", "position": 0}

        assert json.loads(format_as_json(state))["position"] == 0

    def test_format_as_table_short(self):
        """Test format_as_table with short fields."""
        state = {
            "status": "play",
            "position": 0,
            "title": "Test Song",
            "artist": "Test Artist",
            "album": "Test Album",
            "seek": 42123,
        }

        result = format_as_table(state)

        assert "Volumio Status" in result
        assert "=" * 50 in result
        assert "Test Song" in result
        assert "Test Artist" in result
        assert "play" in result
        # seek (milliseconds) is rendered as HH:MM:SS.mmm
        assert "00:00:42.123" in result

    def test_format_as_table_all(self):
        """Test format_as_table with all fields."""
        state = {
            "status": "play",
            "volume": 100,
            "mute": False,
            "title": "Test",
        }

        result = format_as_table(state)

        assert "Volumio Status" in result
        assert "Test" in result

    def test_format_as_table_short_set_labels(self):
        """The short set is labelled through its audio-quality fields."""
        state = {
            "status": "play",
            "mute": False,
            "trackType": "flac",
            "samplerate": "44.1 kHz",
            "bitdepth": "16 bit",
            "channels": 2,
        }

        result = format_as_table(state)

        assert f"{'Tracktype':20}: flac" in result
        assert f"{'Samplerate':20}: 44.1 kHz" in result
        assert f"{'Bitdepth':20}: 16 bit" in result
        assert f"{'Channels':20}: 2" in result

    def test_format_as_table_duration(self):
        """Test format_as_table renders duration (seconds) as HH:MM:SS."""
        state = {"status": "play", "title": "Test Song", "duration": 3725}

        result = format_as_table(state)

        assert f"{'Duration':20}: 01:02:05" in result

    def test_format_as_table_position_indexing(self):
        """Test format_as_table renders position per the indexing base."""
        state = {"status": "play", "position": 0, "title": "Test Song"}

        one_based = format_as_table(state)
        zero_based = format_as_table(state, position_starting_at_one=False)

        assert f"{'Position':20}: 1" in one_based
        assert f"{'Position':20}: 0" in zero_based

    def test_format_as_table_nested_dictionary(self):
        """A nested object is printed as one indented key/value line per sub-key."""
        state = {
            "name": "volumio4b",
            "state": {"status": "play", "volume": 20, "mute": False},
        }

        result = format_as_table(state, heading="System Info")
        lines = result.splitlines()

        assert f"{'State':20}:" in lines
        assert f"  {'Status':18}: play" in lines
        assert f"  {'Volume':18}: 20" in lines
        assert f"  {'Mute':18}: False" in lines
        # Sub-keys keep the order returned by the API
        assert lines.index("  " + f"{'Status':18}: play") < lines.index(
            "  " + f"{'Volume':18}: 20"
        )

    def test_format_as_table_dotted_field_order_label(self):
        """A dotted field-order key is labeled with the dot replaced by a space."""
        state = {"data.value": "A story."}

        result = format_as_table(state, heading="Album Story", field_order=["data.value"])

        assert "Album Story" in result
        assert f"{'Data Value':20}: A story." in result.splitlines()


class TestFormatBrowseResultsAsTable:
    """Test cases for the format_browse_results_as_table function."""

    def test_the_untitled_list_and_its_named_items(self):
        """An untitled list gets no title line, and an item is told by its name."""
        lines = format_browse_results_as_table(
            [
                {
                    "items": [
                        {"name": "Music Library", "uri": "music-library"},
                        {"name": "Web Radio", "uri": "radio"},
                    ],
                }
            ],
            print_uri=True,
        ).splitlines()

        assert lines[0] == "Volumio Browse Results"
        assert lines[2] == ""
        assert lines[3] == "1. Music Library"
        assert lines[4] == "   music-library"
        assert lines[5] == "2. Web Radio"
        assert lines[6] == "   radio"

    def test_the_info_follows_the_heading(self):
        """The entity being browsed is told under the heading, without repeating its URI."""
        lists = [{"items": [{"title": "Aguaplano", "artist": "Paolo Conte"}]}]
        info = {
            "title": "Aguaplano",
            "artist": "Paolo Conte",
            "uri": "albums://Paolo%20Conte/Aguaplano",
        }

        lines = format_browse_results_as_table(lists, info, print_uri=True).splitlines()

        assert lines[2] == "Aguaplano - Paolo Conte"
        # The URI of the entity is the very URI that was browsed
        assert "albums://" not in "\n".join(lines)

    def test_an_info_with_nothing_to_tell(self):
        """An entity without a title or a name adds no line."""
        table = format_browse_results_as_table(
            [{"items": [{"title": "A Track"}]}], {"uri": "somewhere://"}
        )

        assert table.splitlines()[2] == ""
        assert "somewhere://" not in table

    def test_no_content_at_all(self):
        """Without any item the table says so, after the info when there is one."""
        assert format_browse_results_as_table([]).endswith("(no result)")
        assert format_browse_results_as_table(
            [], {"title": "An Album"}
        ).splitlines() == ["Volumio Browse Results", "=" * 50, "An Album", "(no result)"]


class TestFormatNotificationAsLine:
    """Test cases for the format_notification_as_line function."""

    def test_a_state_notification(self):
        """A state notification shows its status and its track."""
        line = format_notification_as_line(
            "state",
            {"status": "play", "title": "Caterina", "artist": "Francesco De Gregori"},
            "2026-08-04T10:15:32.123Z",
        )

        assert line == (
            "[2026-08-04T10:15:32.123Z] state    play | Caterina - Francesco De Gregori"
        )

    def test_a_state_notification_without_a_track(self):
        """The track part is omitted when the state carries no title nor artist."""
        line = format_notification_as_line(
            "state", {"status": "stop"}, "2026-08-04T10:15:32.123Z"
        )

        assert line == "[2026-08-04T10:15:32.123Z] state    stop"

    def test_a_state_notification_without_a_status(self):
        """The status part is omitted when the state carries none."""
        line = format_notification_as_line(
            "state", {"title": "Caterina"}, "2026-08-04T10:15:32.123Z"
        )

        assert line == "[2026-08-04T10:15:32.123Z] state    Caterina"

    def test_a_mapping_without_any_known_key(self):
        """A mapping carrying none of the known keys is shown as JSON."""
        line = format_notification_as_line("state", {"volume": 42}, "2026-08-04T10:15:32.123Z")

        assert line == '[2026-08-04T10:15:32.123Z] state    {"volume": 42}'

    def test_an_array_notification(self):
        """An array is summarized by its length."""
        line = format_notification_as_line(
            "queue", [{"title": "A"}, {"title": "B"}], "2026-08-04T10:15:32.123Z"
        )

        assert line == "[2026-08-04T10:15:32.123Z] queue    2 items"

    def test_a_notification_without_an_item(self):
        """A notification the host sent without an item is still readable."""
        line = format_notification_as_line(None, None, "2026-08-04T10:15:32.123Z")

        assert line == "[2026-08-04T10:15:32.123Z] ?        null"


class TestFormatSearchResultsAsTable:
    """Test cases for the format_search_results_as_table function."""

    def test_the_lists_and_their_items(self):
        """Every list is titled, and its items are numbered."""
        lines = format_search_results_as_table(
            [
                {
                    "title": "QOBUZ Tracks",
                    "items": [
                        {
                            "title": "Aguaplano",
                            "artist": "Paolo Conte",
                            "album": "Aguaplano",
                            "service": "qobuz",
                            "type": "song",
                        },
                        {"title": "Come Di", "service": "qobuz", "type": "song"},
                    ],
                }
            ]
        ).splitlines()

        assert lines[0] == "Volumio Search Results"
        assert lines[2] == ""
        assert lines[3] == "QOBUZ Tracks"
        assert lines[4] == "1. Aguaplano - Paolo Conte - Aguaplano"
        assert lines[5] == "2. Come Di"

    def test_a_list_titled_after_the_query(self):
        """A list the host titles after the query is titled after its source instead."""
        table = format_search_results_as_table(
            [
                {
                    "title": "Found 1 Album 'Sirtaki'",
                    "items": [{"title": "Sirtaki", "artist": "Mango", "service": "mpd"}],
                },
                {
                    "title": "Found 12 Tracks 'Sirtaki'",
                    "items": [{"title": "6 - Sirtaki", "service": "mpd"}],
                },
            ]
        )

        assert "MPD Albums" in table
        assert "MPD Tracks" in table
        assert "Found" not in table

    def test_a_list_titled_after_the_query_without_a_service(self):
        """Without a service to name, the title of the host is kept."""
        table = format_search_results_as_table(
            [{"title": "Found 1 Album 'Sirtaki'", "items": [{"title": "Sirtaki"}]}]
        )

        assert "Found 1 Album 'Sirtaki'" in table

    def test_a_list_without_items_is_skipped(self):
        """A list the host sent empty contributes no title."""
        table = format_search_results_as_table(
            [
                {"title": "Empty", "items": []},
                {"title": "Web Radio", "items": [{"title": "RADIO", "service": "webradio"}]},
            ]
        )

        assert "Empty" not in table
        # The title a source gives is kept as it is
        assert "Web Radio" in table
        assert "1. RADIO" in table

    def test_no_result_at_all(self):
        """Without any item the table says so."""
        assert format_search_results_as_table([]).endswith("(no result)")
        assert format_search_results_as_table([{"title": "Empty"}]).endswith("(no result)")

    def test_the_uris_are_printed_under_their_items(self):
        """Each URI starts at the column the title of its result starts at."""
        lists = [
            {
                "title": "MPD Tracks",
                "items": [
                    {"title": "Aguaplano", "service": "mpd", "uri": "music-library/1.flac"},
                    {"title": "Come Di", "service": "mpd"},
                ],
            }
        ]

        lines = format_search_results_as_table(lists, print_uri=True).splitlines()

        assert lines[4] == "1. Aguaplano"
        assert lines[5] == "   music-library/1.flac"
        # An item the host gave no URI for gets no line of its own
        assert lines[6] == "2. Come Di"
        assert len(lines) == 7
        # Without the flag the table is the one it has always been
        assert format_search_results_as_table(lists).splitlines() == [
            *lines[:5],
            lines[6],
        ]

    def test_the_uris_of_a_list_numbered_past_nine(self):
        """The indent widens with the numbers, keeping the URIs under the titles."""
        lines = format_search_results_as_table(
            [
                {
                    "title": "QOBUZ Tracks",
                    "items": [
                        {"title": f"Track {index}", "service": "qobuz", "uri": f"qobuz://{index}"}
                        for index in range(1, 11)
                    ],
                }
            ],
            print_uri=True,
        ).splitlines()

        assert lines[4] == " 1. Track 1"
        assert lines[5] == "    qobuz://1"
        assert lines[22] == "10. Track 10"
        assert lines[23] == "    qobuz://10"


class TestFormatTerminationConditions:
    """Test cases for the format_termination_conditions function."""

    def test_only_the_interruption(self):
        """Without limits, only the interruption ends the listening."""
        assert (
            format_termination_conditions(None, None, None)
            == "Terminate as soon as: CTRL+C is issued"
        )

    def test_a_count(self):
        """A count is listed as the last condition."""
        assert format_termination_conditions(3, None, None) == (
            "Terminate as soon as: CTRL+C is issued, or 3 notifications received"
        )

    def test_a_timeout(self):
        """A total timeout is listed with the seconds it was given."""
        assert format_termination_conditions(None, 60.0, None) == (
            "Terminate as soon as: CTRL+C is issued, or a total of 60 seconds elapsed"
        )

    def test_an_idle_timeout(self):
        """An idle timeout is listed as a silence."""
        assert format_termination_conditions(None, None, 30.0) == (
            "Terminate as soon as: CTRL+C is issued, "
            "or no notifications received for 30 seconds"
        )

    def test_every_condition(self):
        """Every condition is listed, in order, with "or" before the last one."""
        assert format_termination_conditions(10, 60.0, 5.0) == (
            "Terminate as soon as: CTRL+C is issued, a total of 60 seconds elapsed, "
            "no notifications received for 5 seconds, or 10 notifications received"
        )

    def test_the_singular_forms(self):
        """A value of one is spelled in the singular."""
        assert format_termination_conditions(1, 1.0, 1.0) == (
            "Terminate as soon as: CTRL+C is issued, a total of 1 second elapsed, "
            "no notifications received for 1 second, or 1 notification received"
        )

    def test_a_fractional_number_of_seconds(self):
        """A fractional timeout keeps its decimals, and stays plural."""
        assert format_termination_conditions(None, None, 1.5) == (
            "Terminate as soon as: CTRL+C is issued, "
            "or no notifications received for 1.5 seconds"
        )


class TestExpandManifestFile:
    """Test cases for the expand_manifest_file function."""

    def test_no_placeholders(self):
        """A path without placeholders is returned unchanged."""
        assert (
            expand_manifest_file("/tmp/run.json", "/music", "20260101000000")
            == "/tmp/run.json"
        )

    def test_output_directory_placeholder(self):
        """The {output_directory} placeholder is replaced with the given directory."""
        assert (
            expand_manifest_file("{output_directory}/myqueue.json", "/music", "20260101000000")
            == "/music/myqueue.json"
        )

    def test_both_placeholders(self):
        """Both placeholders are replaced in the same path."""
        assert (
            expand_manifest_file(
                "{output_directory}/{timestamp}.json", "/music", "20260101000000"
            )
            == "/music/20260101000000.json"
        )

    def test_expanded_output_directory_flows_in(self):
        """A timestamp-expanded output directory is injected as-is."""
        assert (
            expand_manifest_file(
                "{output_directory}/manifest.json", "/music/20260101000000", "20260101000000"
            )
            == "/music/20260101000000/manifest.json"
        )


class TestExpandTimestampPlaceholder:
    """Test cases for the expand_timestamp_placeholder function."""

    def test_no_placeholder(self):
        """A path without the placeholder is returned unchanged."""
        assert expand_timestamp_placeholder("/tmp/volumito", "20260101000000") == "/tmp/volumito"

    def test_placeholder_inside_path(self):
        """The placeholder is replaced wherever it appears in the path."""
        assert (
            expand_timestamp_placeholder("/tmp/{timestamp}/queue", "20260101000000")
            == "/tmp/20260101000000/queue"
        )

    def test_multiple_occurrences(self):
        """Every occurrence of the placeholder is replaced."""
        assert (
            expand_timestamp_placeholder("/{timestamp}/{timestamp}", "20260101000000")
            == "/20260101000000/20260101000000"
        )

    def test_other_braces_untouched(self):
        """Braces other than the placeholder are left as they are."""
        assert (
            expand_timestamp_placeholder("/tmp/{artist}/{timestamp}", "20260101000000")
            == "/tmp/{artist}/20260101000000"
        )


class TestExtractFilenameFromUri:
    """Test cases for the extract_filename_from_uri function."""

    def test_from_query_param_path(self):
        """The 'path' query parameter's basename wins when present."""
        uri = "http://volumio.local:3000/albumart?cacheid=x&path=/mnt/USB/Album/cover.png"
        assert extract_filename_from_uri(uri) == "cover.png"

    def test_from_uri_path(self):
        """Falls back to the basename of the URI path."""
        assert extract_filename_from_uri("http://example.com/images/cover.jpg") == "cover.jpg"

    def test_audio_uri(self):
        """Works for plain audio URIs."""
        assert extract_filename_from_uri("http://volumio.local:8000/music/song.flac") == "song.flac"

    def test_no_filename(self):
        """Returns an empty string when no file name can be determined."""
        assert extract_filename_from_uri("http://example.com/") == ""


class TestRenderOutputFilename:
    """Test cases for the render_output_filename function."""

    def _state(self, **overrides):
        """Return the player state the templates are rendered against."""
        return PlayerState.from_raw(
            {
                "position": 0,
                "title": "La rondine",
                "album": "Puccini",
                "artist": "Anna",
                "trackType": "flac",
                "duration": 200,
                "bitdepth": "16 bit",
                "samplerate": "44.1 kHz",
                "channels": 2,
                **overrides,
            }
        )

    def test_default_template(self):
        """The default template reproduces the URI basename."""
        uri = "http://volumio.local:8000/music/song.flac"
        empty = PlayerState.from_raw({})
        assert render_output_filename("{file_name_from_uri}", uri, empty, "flac") == "song.flac"

    def test_custom_template(self):
        """Custom template renders metadata; position starts at one; spaces -> underscores."""
        result = render_output_filename(
            "{position:03d}_{title}.{extension}", "http://x/y.flac", self._state(), "flac"
        )
        assert result == "001_La_rondine.flac"

    def test_custom_template_position_starting_at_zero(self):
        """The position key follows the indexing base."""
        result = render_output_filename(
            "{position:03d}_{title}.{extension}",
            "http://x/y.flac",
            self._state(),
            "flac",
            position_starting_at_one=False,
        )
        assert result == "000_La_rondine.flac"

    def test_duration_key(self):
        """The duration key is HH:MM:SS; the default replacement rewrites the colons."""
        result = render_output_filename(
            "{duration}.{extension}", "http://x/y", self._state(), "flac"
        )
        assert result == "00_03_20.flac"

    def test_extension_from_uri(self):
        """The extension key is taken from the URI file name."""
        result = render_output_filename("{extension}", "http://x/song.mp3", self._state(), "flac")
        assert result == "mp3"

    def test_extension_default_when_uri_has_none(self):
        """The default extension is used when the URI file has no extension."""
        empty = PlayerState.from_raw({})
        assert render_output_filename("{extension}", "http://x/song", empty, "flac") == "flac"
        assert render_output_filename("{extension}", "http://x/albumart", empty, "jpg") == "jpg"

    def test_bad_template_unknown_key(self):
        """An unknown template key raises a UsageError."""
        with pytest.raises(click.UsageError):
            render_output_filename("{unknown}", "http://x/y.flac", self._state(), "flac")

    def test_bad_template_bad_spec(self):
        """An invalid format specification raises a UsageError."""
        with pytest.raises(click.UsageError):
            render_output_filename("{title:03d}", "http://x/y.flac", self._state(), "flac")

    def test_traversal_metadata_is_neutralized(self):
        """Path separators in metadata cannot escape the output directory."""
        state = self._state(title="../../../home/user/x")
        result = render_output_filename("{title}.{extension}", "http://x/y.flac", state, "flac")
        assert "/" not in result
        assert "\\" not in result
        assert result == "_.._.._home_user_x.flac"

    def test_separators_in_metadata_replaced(self):
        """Slashes and backslashes in metadata become the replacement string."""
        state = self._state(title="AC/DC", album="Back\\Slash")
        result = render_output_filename(
            "{title}_{album}.{extension}", "http://x/y.flac", state, "flac"
        )
        assert result == "AC_DC_Back_Slash.flac"

    def test_control_characters_removed(self):
        """Control characters (including NUL) in metadata are removed."""
        state = self._state(title="a\x00b\nc")
        result = render_output_filename("{title}.{extension}", "http://x/y.flac", state, "flac")
        assert result == "abc.flac"

    def test_uri_dot_dot_yields_empty_name(self):
        """A URI whose basename is '..' renders to an empty name (rejected by the caller)."""
        assert render_output_filename(
            "{file_name_from_uri}", "http://x/foo/..", PlayerState.from_raw({}), "flac"
        ) == ""

    def test_uri_backslashes_sanitized(self):
        """Backslashes from the URI path parameter cannot survive into the name."""
        uri = "http://x/albumart?path=..%5C..%5Cx.jpg"
        result = render_output_filename(
            "{file_name_from_uri}", uri, PlayerState.from_raw({}), "jpg"
        )
        assert result == "_.._x.jpg"

    def test_attribute_access_rejected(self):
        """Attribute access in a template field raises a UsageError."""
        with pytest.raises(click.UsageError, match="unknown key 'title.upper'"):
            render_output_filename("{title.upper}", "http://x/y.flac", self._state(), "flac")

    def test_positional_field_rejected(self):
        """A positional template field raises a UsageError."""
        with pytest.raises(click.UsageError, match="unknown key '0'"):
            render_output_filename("{0}", "http://x/y.flac", self._state(), "flac")

    def test_unbalanced_template_rejected(self):
        """A malformed template raises a UsageError."""
        with pytest.raises(click.UsageError, match="Invalid --file-name-template"):
            render_output_filename("{title", "http://x/y.flac", self._state(), "flac")

    def test_template_literal_separator_rejected(self):
        """A template rendering to a path (literal separator) raises a UsageError."""
        with pytest.raises(click.UsageError, match="plain file name"):
            render_output_filename(
                "covers/{album}.{extension}", "http://x/y.flac", self._state(), "flac"
            )

    def test_template_literal_separator_can_be_replaced(self):
        """A separator listed in the replace characters is replaced instead of rejected."""
        result = render_output_filename(
            "covers/{album}.{extension}",
            "http://x/y.flac",
            self._state(),
            "flac",
            replace_characters_in_file_names=" /",
        )
        assert result == "covers_Puccini.flac"

    def test_leading_dots_stripped(self):
        """Leading dots are stripped, so the rendered name cannot be a hidden file."""
        state = self._state(title="..hidden")
        result = render_output_filename("{title}.{extension}", "http://x/y.flac", state, "flac")
        assert result == "hidden.flac"

    def test_custom_replace_characters(self):
        """The replace characters and the replacement string are configurable."""
        state = self._state(title="A (B) C")
        result = render_output_filename(
            "{title}.{extension}",
            "http://x/y.flac",
            state,
            "flac",
            replace_characters_in_file_names=" ()",
            replace_characters_in_file_names_with="-",
        )
        assert result == "A--B--C.flac"

    def test_empty_replace_characters_keeps_spaces(self):
        """An empty replace-characters string disables the replacement."""
        result = render_output_filename(
            "{title}.{extension}",
            "http://x/y.flac",
            self._state(),
            "flac",
            replace_characters_in_file_names="",
        )
        assert result == "La rondine.flac"

    def test_empty_replacement_removes_characters(self):
        """An empty replacement string removes the selected characters."""
        result = render_output_filename(
            "{title}.{extension}",
            "http://x/y.flac",
            self._state(),
            "flac",
            replace_characters_in_file_names=" ",
            replace_characters_in_file_names_with="",
        )
        assert result == "Larondine.flac"

    def test_replacement_with_separator_rejected(self):
        """A replacement string containing a path separator raises a UsageError."""
        with pytest.raises(click.UsageError, match="replace-characters-in-file-names-with"):
            render_output_filename(
                "{title}.{extension}",
                "http://x/y.flac",
                self._state(),
                "flac",
                replace_characters_in_file_names_with="../",
            )

    def test_non_numeric_position_falls_back_to_base(self):
        """A malformed position in the state falls back to the indexing base."""
        state = self._state(position="abc")
        result = render_output_filename("{position:03d}_{title}", "http://x/y.flac", state, "flac")
        assert result == "001_La_rondine"

    def test_tracknumber_key(self):
        """The tracknumber key renders the given track number verbatim."""
        result = render_output_filename(
            "{tracknumber:03d}", "http://x/y.flac", self._state(), "flac", tracknumber=4
        )

        assert result == "004"

    def test_tracknumber_key_from_the_state(self):
        """Without an explicit track number, the one of the state is rendered."""
        state = self._state(tracknumber=7)

        result = render_output_filename("{tracknumber:03d}", "http://x/y.flac", state, "flac")

        assert result == "007"

    def test_tracknumber_key_missing_or_malformed(self):
        """A missing or malformed tracknumber falls back to zero."""
        empty = PlayerState.from_raw({})
        assert render_output_filename("{tracknumber}", "http://x/y.flac", empty, "flac") == "0"
        malformed = PlayerState.from_raw({"tracknumber": "abc"})
        assert (
            render_output_filename("{tracknumber}", "http://x/y.flac", malformed, "flac") == "0"
        )

    def test_tracknumber_key_ignores_indexing_option(self):
        """The tracknumber key is absolute, not affected by the indexing base."""
        result = render_output_filename(
            "{tracknumber}",
            "http://x/y.flac",
            self._state(),
            "flac",
            position_starting_at_one=False,
            tracknumber=4,
        )

        assert result == "4"

    def test_album_volume_key(self):
        """The album_volume key keeps its deliberate separator under subdirectories."""
        result = render_output_filename(
            "{album_volume}/{title}.{extension}",
            "http://x/y.flac",
            self._state(),
            "flac",
            allow_subdirectories=True,
            album_volume="Elegia/2",
        )

        assert result == "Elegia/2/La_rondine.flac"

    def test_album_volume_key_missing(self):
        """A missing album_volume renders as an empty string."""
        empty = PlayerState.from_raw({})
        assert render_output_filename("x_{album_volume}", "http://x/y.flac", empty, "flac") == "x_"

    def test_album_volume_key_components_sanitized(self):
        """Backslashes and control characters inside the components are neutralized."""
        result = render_output_filename(
            "{album_volume}",
            "http://x/y.flac",
            self._state(),
            "flac",
            allow_subdirectories=True,
            album_volume="Ele\\gia/2\x01",
        )

        assert result == "Ele_gia/2"

    def test_album_volume_key_requires_subdirectories(self):
        """A multi-volume value without subdirectory support is rejected."""
        with pytest.raises(click.UsageError, match="plain file name"):
            render_output_filename(
                "{album_volume}.{extension}",
                "http://x/y.flac",
                self._state(),
                "flac",
                album_volume="Elegia/2",
            )


class TestPreserveLocalFileName:
    """Test cases for the preserve_local_file_name function."""

    def test_a_local_file_keeps_its_name(self):
        """The rendered name of a file of the host library becomes the name it has there."""
        assert (
            preserve_local_file_name("000___8_-_Luiza.mp3", "INTERNAL/music/elegy/08-Luiza.mp3")
            == "08-Luiza.mp3"
        )

    def test_the_rendered_directories_are_kept(self):
        """Only the last component of the rendered name is replaced."""
        assert preserve_local_file_name(
            "Aeon_Trio/Elegy/000___8_-_Luiza.mp3", "INTERNAL/music/elegy/08-Luiza.mp3"
        ) == os.path.join("Aeon_Trio/Elegy", "08-Luiza.mp3")

    def test_a_file_without_an_extension(self):
        """A name without an extension is kept as it is."""
        assert preserve_local_file_name("001___Song.flac", "INTERNAL/music/track") == "track"

    def test_a_uri_fetched_over_http(self):
        """A URI carrying a scheme keeps the rendered name."""
        assert (
            preserve_local_file_name("001___Song.flac", "http://volumio.local/x/track.flac")
            == "001___Song.flac"
        )


class TestSanitizeFilenameComponent:
    """Test cases for the sanitize_filename_component function."""

    def test_separators_replaced(self):
        """Forward and backward slashes become the replacement string."""
        assert sanitize_filename_component("a/b\\c", "_") == "a_b_c"

    def test_control_characters_removed(self):
        """Control characters (below 32, and 127) are removed."""
        assert sanitize_filename_component("a\x00b\tc\nd\x7fe", "_") == "abcde"

    def test_empty_replacement_removes_separators(self):
        """An empty replacement removes the separators."""
        assert sanitize_filename_component("a/b\\c", "") == "abc"

    def test_clean_text_unchanged(self):
        """Text without separators or control characters is returned unchanged."""
        assert sanitize_filename_component("Song Title (Live) 'x'", "_") == "Song Title (Live) 'x'"


class TestParseTimeToSeconds:
    """Test cases for the parse_time_to_seconds function."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("00:00", 0),
            ("04:12", 252),
            ("01:04:12", 3852),
            ("00:04:12", 252),
            ("99:00:00", 356400),
        ],
    )
    def test_colon_times(self, text: str, expected: int):
        """A HH:MM:SS or MM:SS time is converted to seconds."""
        assert parse_time_to_seconds(text) == expected

    @pytest.mark.parametrize(
        "text",
        ["42", "", "1:2:3:4", "00:99", "01:60:00", "aa:bb", "-1:00", "1.5:00", "00:04:12.345"],
    )
    def test_not_a_colon_time(self, text: str):
        """Anything that is not a well-formed colon time yields None."""
        assert parse_time_to_seconds(text) is None


class TestParseResultKinds:
    """Test cases for the parse_result_kinds function."""

    def test_a_single_kind(self):
        """A single kind is parsed into its member."""
        assert parse_result_kinds("album") == {SearchResultItemKind.ALBUM}

    def test_several_kinds(self):
        """A comma-separated list is parsed into its members."""
        assert parse_result_kinds("album,track") == {
            SearchResultItemKind.ALBUM,
            SearchResultItemKind.TRACK,
        }

    def test_blanks_are_ignored(self):
        """Blanks around the items are ignored."""
        assert parse_result_kinds(" artist , other ") == {
            SearchResultItemKind.ARTIST,
            SearchResultItemKind.OTHER,
        }

    def test_repeated_kinds_are_kept_once(self):
        """A kind listed twice appears once."""
        assert parse_result_kinds("track,track") == {SearchResultItemKind.TRACK}

    @pytest.mark.parametrize(
        "value",
        ["", "   ", "album,,track", "song", "Album", "nonesuch"],
        ids=["empty", "blank", "empty-item", "host-word", "capitalized", "unknown"],
    )
    def test_an_invalid_list(self, value):
        """A list naming a kind that does not exist is rejected."""
        with pytest.raises(ValueError):
            parse_result_kinds(value)


class TestResultKindsParamType:
    """Test cases for the ResultKindsParamType Click parameter type."""

    def test_convert_a_list(self):
        """A well-formed list is converted to the kinds it names."""
        assert ResultKindsParamType().convert("album,track", None, None) == {
            SearchResultItemKind.ALBUM,
            SearchResultItemKind.TRACK,
        }

    def test_convert_an_unknown_kind(self):
        """An unknown kind is a usage error naming the accepted values."""
        with pytest.raises(click.exceptions.BadParameter) as exc_info:
            ResultKindsParamType().convert("nonesuch", None, None)

        assert "album, artist, other, playlist, track" in str(exc_info.value)

    def test_the_metavar(self):
        """The --help metavar lists the accepted kinds."""
        assert (
            ResultKindsParamType().get_metavar(None, None)
            == "[album|artist|other|playlist|track]"
        )


class TestIsExpandableUri:
    """Test cases for is_expandable_uri."""

    @pytest.mark.parametrize(
        ("uri", "expected"),
        [
            ("qobuz://album/0884977674569", True),
            ("qobuz://playlist/19844454", True),
            ("qobuz://artist/178398", True),
            ("tidal://album/123", True),
            ("spotify:album:abc", True),
            ("qobuz://song/2210819", False),
            ("tidal://song/123", False),
            ("other://track/9", False),
            ("spotify:track:abc", False),
            ("http://opml.radiotime.com/Tune.ashx?id=s339255", False),
            ("https://stream.example/radio", False),
            ("music-library/INTERNAL/music/track.flac", False),
            ("music-library/INTERNAL/music", False),
            ("albums://Paolo%20Conte/Aguaplano", False),
            ("artists://Paolo%20Conte", False),
            ("genres://Jazz", False),
            ("playlists://jazz", False),
        ],
    )
    def test_is_expandable_uri(self, uri, expected):
        """Only the containers of the sources other than the local library expand."""
        assert is_expandable_uri(uri) is expected


class TestStoredLocalUri:
    """Test cases for stored_local_uri."""

    @pytest.mark.parametrize(
        ("uri", "expected"),
        [
            ("music-library/INTERNAL/music/a.flac", "mnt/INTERNAL/music/a.flac"),
            ("mnt/INTERNAL/music/a.flac", "mnt/INTERNAL/music/a.flac"),
            ("qobuz://track/3", "qobuz://track/3"),
            ("albums://X/Y", "albums://X/Y"),
            ("http://stream.example/radio", "http://stream.example/radio"),
        ],
    )
    def test_stored_local_uri(self, uri, expected):
        """Only the browse form of a local file is converted, to its mount path."""
        assert stored_local_uri(uri) == expected


class TestParseTrackSelection:
    """Test cases for the parse_track_selection function."""

    def test_single_positions(self):
        """A comma-separated list of positions is parsed."""
        assert parse_track_selection("5") == {5}
        assert parse_track_selection("2,4,7") == {2, 4, 7}

    def test_ranges(self):
        """A start-end range is inclusive on both ends."""
        assert parse_track_selection("1-3") == {1, 2, 3}
        assert parse_track_selection("4-4") == {4}

    def test_mixed_selection(self):
        """Positions and ranges can be mixed."""
        assert parse_track_selection("1-3,6-8,12") == {1, 2, 3, 6, 7, 8, 12}

    def test_blanks_are_ignored(self):
        """Blanks around the items and the range separator are ignored."""
        assert parse_track_selection(" 2 , 5 - 6 ") == {2, 5, 6}

    def test_repeated_positions_are_kept_once(self):
        """A position listed twice appears once in the selection."""
        assert parse_track_selection("3,1-3,3") == {1, 2, 3}

    @pytest.mark.parametrize(
        "value",
        ["", "   ", "1,,2", "abc", "1-a", "1-", "-3", "3-1"],
        ids=[
            "empty",
            "blank",
            "empty-item",
            "not-a-number",
            "range-end-not-a-number",
            "range-without-end",
            "range-without-start",
            "reversed-range",
        ],
    )
    def test_invalid_selection(self, value):
        """A malformed selection is rejected."""
        with pytest.raises(ValueError):
            parse_track_selection(value)


class TestSeekParamType:
    """Test cases for the SeekParamType Click parameter type."""

    def test_convert_already_int(self):
        """An already-converted int value passes through unchanged."""
        assert SeekParamType().convert(252, None, None) == 252

    def test_convert_numeric_string(self):
        """A numeric string is converted to an int number of seconds."""
        assert SeekParamType().convert("252", None, None) == 252

    @pytest.mark.parametrize(
        ("text", "expected"),
        [("04:12", 252), ("01:04:12", 3852)],
    )
    def test_convert_colon_time(self, text: str, expected: int):
        """A colon time is converted to the corresponding number of seconds."""
        assert SeekParamType().convert(text, None, None) == expected

    @pytest.mark.parametrize(
        ("spelling", "canonical"),
        [
            ("plus", "plus"),
            ("increase", "plus"),
            ("up", "plus"),
            ("forward", "plus"),
            ("minus", "minus"),
            ("decrease", "minus"),
            ("down", "minus"),
            ("backward", "minus"),
        ],
    )
    def test_convert_alias(self, spelling: str, canonical: str):
        """Relative aliases are normalized to their canonical keyword."""
        assert SeekParamType().convert(spelling, None, None) == canonical

    @pytest.mark.parametrize("value", ["bogus", "UP", "Plus", "12s", "00:99"])
    def test_convert_invalid_rejected(self, value: str):
        """A value that is neither a keyword, a time, nor a number is a usage error."""
        with pytest.raises(click.exceptions.BadParameter):
            SeekParamType().convert(value, None, None)

    @pytest.mark.parametrize("value", ["-1", -5])
    def test_convert_negative_rejected(self, value: str | int):
        """A negative position is a usage error."""
        with pytest.raises(click.exceptions.BadParameter):
            SeekParamType().convert(value, None, None)


class TestSleepTimerParamType:
    """Test cases for the SleepTimerParamType Click parameter type."""

    def test_convert_already_timedelta(self):
        """An already-converted delay passes through unchanged."""
        delay = timedelta(minutes=30)

        assert SleepTimerParamType().convert(delay, None, None) is delay

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("0", timedelta()),
            ("30", timedelta(minutes=30)),
            ("90", timedelta(minutes=90)),
            ("1:30", timedelta(hours=1, minutes=30)),
            ("0:05", timedelta(minutes=5)),
            ("12:00", timedelta(hours=12)),
        ],
    )
    def test_convert_delay(self, text: str, expected: timedelta):
        """A number of minutes, or a H:MM delay, is converted to a timedelta."""
        assert SleepTimerParamType().convert(text, None, None) == expected

    def test_convert_off(self):
        """The off spelling is returned as it is, to disarm the timer."""
        assert SleepTimerParamType().convert("off", None, None) == "off"

    @pytest.mark.parametrize("value", ["bogus", "OFF", "-5", "1:60", "1:2:3", "30m", ""])
    def test_convert_invalid_rejected(self, value: str):
        """A value that is neither a number of minutes, a H:MM delay, nor off is an error."""
        with pytest.raises(click.exceptions.BadParameter, match="must be a number of minutes"):
            SleepTimerParamType().convert(value, None, None)


class TestVolumeParamType:
    """Test cases for the VolumeParamType Click parameter type."""

    def test_convert_already_int(self):
        """An already-converted int value passes through unchanged."""
        assert VolumeParamType().convert(50, None, None) == 50

    def test_convert_keyword(self):
        """A lowercase keyword value is accepted as-is."""
        assert VolumeParamType().convert("mute", None, None) == "mute"

    def test_convert_numeric_string(self):
        """A numeric string is converted to an int."""
        assert VolumeParamType().convert("50", None, None) == 50

    @pytest.mark.parametrize(
        ("spelling", "canonical"),
        [
            ("up", "plus"),
            ("increase", "plus"),
            ("down", "minus"),
            ("decrease", "minus"),
        ],
    )
    def test_convert_alias(self, spelling: str, canonical: str):
        """Step aliases are normalized to their canonical keyword."""
        assert VolumeParamType().convert(spelling, None, None) == canonical

    @pytest.mark.parametrize("value", ["UP", "MUTE", "Plus"])
    def test_convert_uppercase_rejected(self, value: str):
        """Only lowercase spellings are accepted; others are a usage error."""
        with pytest.raises(click.exceptions.BadParameter):
            VolumeParamType().convert(value, None, None)


class TestOnOffParamType:
    """Test cases for the OnOffParamType Click parameter type."""

    def test_convert_already_bool(self):
        """An already-converted bool value passes through unchanged."""
        assert OnOffParamType().convert(True, None, None) is True
        assert OnOffParamType().convert(False, None, None) is False

    @pytest.mark.parametrize(
        ("spelling", "expected"),
        [
            ("on", True),
            ("true", True),
            ("yes", True),
            ("1", True),
            ("off", False),
            ("false", False),
            ("no", False),
            ("0", False),
        ],
    )
    def test_convert_spellings(self, spelling: str, expected: bool):
        """The accepted spellings normalize to their boolean value."""
        assert OnOffParamType().convert(spelling, None, None) is expected

    @pytest.mark.parametrize("value", ["ON", "True", "maybe", "2"])
    def test_convert_invalid_rejected(self, value: str):
        """Only the accepted lowercase spellings are valid; others are a usage error."""
        with pytest.raises(click.exceptions.BadParameter):
            OnOffParamType().convert(value, None, None)


class TestSchemeParamType:
    """Test cases for the SchemeParamType Click parameter type."""

    @pytest.mark.parametrize("scheme", ["http", "https"])
    def test_convert_valid(self, scheme: str):
        """The lowercase http/https values pass through unchanged."""
        assert SchemeParamType().convert(scheme, None, None) == scheme

    @pytest.mark.parametrize("value", ["HTTP", "HTTPS", "Http", "ftp"])
    def test_convert_invalid_rejected(self, value: str):
        """Only the lowercase http/https are valid (case-sensitive); others are a usage error."""
        with pytest.raises(click.exceptions.BadParameter):
            SchemeParamType().convert(value, None, None)

    def test_metavar_lists_the_schemes(self):
        """The --help metavar lists the accepted schemes."""
        assert SchemeParamType().get_metavar(None, None) == "[http|https]"


class TestAPIClientParamType:
    """Test cases for the APIClientParamType Click parameter type."""

    @pytest.mark.parametrize("api_client", API_CLIENTS)
    def test_convert_canonical(self, api_client: str):
        """The canonical values pass through unchanged."""
        assert APIClientParamType().convert(api_client, None, None) == api_client

    @pytest.mark.parametrize(
        ("short_form", "api_client"),
        [
            ("sync_rest", "synchronous_rest"),
            ("sr", "synchronous_rest"),
            ("async_rest", "asynchronous_rest"),
            ("ar", "asynchronous_rest"),
            ("sync_websocket", "synchronous_websocket"),
            ("sw", "synchronous_websocket"),
            ("async_websocket", "asynchronous_websocket"),
            ("aw", "asynchronous_websocket"),
        ],
    )
    def test_convert_short_form(self, short_form: str, api_client: str):
        """A short form converts to its canonical value."""
        assert APIClientParamType().convert(short_form, None, None) == api_client

    @pytest.mark.parametrize("value", ["SYNCHRONOUS_REST", "SR", "rest", "nope"])
    def test_convert_invalid_rejected(self, value: str):
        """Anything else (case-sensitive) is a usage error naming every accepted value."""
        with pytest.raises(click.exceptions.BadParameter) as excinfo:
            APIClientParamType().convert(value, None, None)

        assert str(excinfo.value) == (
            f"{value!r} must be one of synchronous_rest, asynchronous_rest, "
            "synchronous_websocket, asynchronous_websocket (or the short forms sync_rest, "
            "sr, async_rest, ar, sync_websocket, sw, async_websocket, aw)"
        )

    def test_metavar_lists_the_canonical_values(self):
        """The --help metavar lists the canonical values only."""
        assert APIClientParamType().get_metavar(None, None) == (
            "[synchronous_rest|asynchronous_rest|synchronous_websocket|asynchronous_websocket]"
        )


class TestCorrectAudioExtension:
    """Test cases for the correct_audio_extension helper."""

    _MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x23tag"

    def test_renames_to_the_format_of_the_content(self, tmp_path):
        """A downloaded MP3 named ".flac" is renamed to ".mp3"."""
        path = tmp_path / "track.flac"
        path.write_bytes(self._MP3)

        assert correct_audio_extension(str(path), False) == str(tmp_path / "track.mp3")
        assert (tmp_path / "track.mp3").read_bytes() == self._MP3
        assert not path.exists()

    def test_keeps_a_name_already_matching(self, tmp_path):
        """A file whose extension matches its content is left alone."""
        path = tmp_path / "track.MP3"
        path.write_bytes(self._MP3)

        assert correct_audio_extension(str(path), False) == str(path)
        assert path.exists()

    def test_keeps_an_unrecognized_content(self, tmp_path):
        """A file whose format is not recognized is left alone."""
        path = tmp_path / "track.flac"
        path.write_bytes(b"not audio at all")

        assert correct_audio_extension(str(path), False) == str(path)
        assert path.exists()

    def test_keeps_the_name_when_the_corrected_one_is_taken(self, tmp_path):
        """Without --overwrite-existing-files, an existing corrected name is kept."""
        path = tmp_path / "track.flac"
        path.write_bytes(self._MP3)
        taken = tmp_path / "track.mp3"
        taken.write_bytes(b"another file")

        assert correct_audio_extension(str(path), False) == str(path)
        assert taken.read_bytes() == b"another file"
        assert path.exists()

    def test_overwrites_the_corrected_name_when_asked(self, tmp_path):
        """With --overwrite-existing-files, the corrected name is replaced."""
        path = tmp_path / "track.flac"
        path.write_bytes(self._MP3)
        taken = tmp_path / "track.mp3"
        taken.write_bytes(b"another file")

        assert correct_audio_extension(str(path), True) == str(taken)
        assert taken.read_bytes() == self._MP3
        assert not path.exists()


class TestCreateClient:
    """Test cases for the create_client helper."""

    def test_the_client_logs_to_the_cli_console(self):
        """The clients the CLI builds write to the logger of the console."""
        client = create_client(VolumioHostConfiguration(), 5.0)

        assert client.logger is LOGGER

    @pytest.mark.parametrize(
        ("api_client", "adapter_class"),
        [
            ("synchronous_rest", SyncRESTAPIClient),
            ("asynchronous_rest", AsyncRESTAPIClient),
            ("synchronous_websocket", SyncWebSocketAPIClient),
            ("asynchronous_websocket", AsyncWebSocketAPIClient),
        ],
    )
    def test_each_choice_builds_its_adapter(self, api_client, adapter_class):
        """Each -C/--api-client value builds the adapter of its client, logging to the console."""
        host_configuration = VolumioHostConfiguration()

        client = create_client(host_configuration, 5.0, api_client=api_client)

        assert isinstance(client, adapter_class)
        assert client.host_configuration is host_configuration
        assert client.logger is LOGGER

    def test_an_unknown_choice_is_rejected(self):
        """A name outside the accepted values is an error."""
        with pytest.raises(ValueError, match="Unknown API client 'nope'"):
            create_client(VolumioHostConfiguration(), 5.0, api_client="nope")

    @pytest.mark.parametrize("api_client", ["synchronous_rest", "asynchronous_rest"])
    def test_a_rest_adapter_refuses_the_websocket_members_by_default(self, api_client):
        """Without the switch, a REST adapter fails the members needing the WebSocket API."""
        client = create_client(VolumioHostConfiguration(), 5.0, api_client=api_client)
        expected = (
            f"The {client.description} does not offer the sleep timer and the alarms: use "
            "--api-client synchronous_websocket or asynchronous_websocket, "
            "or --allow-fallback-to-websocket-api"
        )

        with client, pytest.raises(UnsupportedOperationError) as excinfo:
            _ = client.sleep_timer

        assert str(excinfo.value) == expected

    @pytest.mark.parametrize(
        ("api_client", "websocket_class"),
        [
            ("synchronous_rest", "VolumioWebSocketClient"),
            ("asynchronous_rest", "VolumioAsyncWebSocketClient"),
        ],
    )
    def test_a_rest_adapter_falls_back_to_the_websocket_client_of_its_kind(
        self, mocker, api_client, websocket_class
    ):
        """With the switch, a REST adapter serves those members through a WebSocket client."""
        instance = mocker.Mock()
        instance.logger = LOGGER
        if api_client == "asynchronous_rest":
            instance.connect = AsyncMock()
            instance.disconnect = AsyncMock()
            instance.get_sleep_timer = AsyncMock(return_value="timer")
        else:
            type(instance).sleep_timer = PropertyMock(return_value="timer")
        mock_class = mocker.patch(
            f"volumito.cli.click_helpers.{websocket_class}", return_value=instance
        )
        host_configuration = VolumioHostConfiguration()
        client = create_client(
            host_configuration,
            5.0,
            websocket_timeout=7.0,
            api_client=api_client,
            allow_fallback_to_websocket_api=True,
        )

        with client:
            assert client.sleep_timer == "timer"

        mock_class.assert_called_once_with(host_configuration, 7.0, LOGGER)
        instance.connect.assert_called_once_with()
        instance.disconnect.assert_called_once_with()


class TestAPIClientOption:
    """Test cases for the -C/--api-client option and the options accompanying it."""

    _CLIENT_CLASSES = {
        "synchronous_rest": "VolumioRESTAPIClient",
        "asynchronous_rest": "VolumioAsyncRESTAPIClient",
        "synchronous_websocket": "VolumioWebSocketClient",
        "asynchronous_websocket": "VolumioAsyncWebSocketClient",
    }
    """The client class the CLI instantiates for each -C/--api-client value."""

    _STORY_ENVELOPE = {"success": True, "data": {"type": "story", "value": "A long story."}}
    """A successful story query answer."""

    _URLS = ["http://192.168.1.100/receiver", "http://192.168.1.101/other"]
    """The notification URLs the mocked REST API client reports."""

    @pytest.fixture
    def runner(self):
        """Create a CliRunner instance."""
        return CliRunner()

    def _mock_client(self, mocker: MockerFixture, api_client: str):
        """Patch the client class of an -C/--api-client value, answering pings.

        Returns:
            The mocked class, and the instance it returns
        """
        instance = mocker.Mock()
        # The adapters log through the logger of their client: the console one
        instance.logger = LOGGER
        if api_client.startswith("asynchronous"):
            for name in ("connect", "disconnect", "close"):
                setattr(instance, name, AsyncMock())
            instance.ping = AsyncMock(return_value="pong")
            instance.pause = AsyncMock(return_value=None)
        else:
            instance.ping.return_value = "pong"
            instance.pause.return_value = None
        mock_class = mocker.patch(
            f"volumito.cli.click_helpers.{self._CLIENT_CLASSES[api_client]}",
            return_value=instance,
        )
        return mock_class, instance

    def _mock_story(self, mocker: MockerFixture, api_client: str):
        """Patch the REST API client class of a value, answering the story queries."""
        mock_class, instance = self._mock_client(mocker, api_client)
        story = Story.from_envelope(self._STORY_ENVELOPE)
        if api_client.startswith("asynchronous"):
            instance.get_story = AsyncMock(return_value=story)
        else:
            instance.get_story.return_value = story
        return mock_class, instance

    def _write_configuration(self, tmp_path, content: str) -> str:
        """Write a configuration file with the given content, returning its path."""
        config = tmp_path / "volumito.yaml"
        config.write_text(content)
        return str(config)

    @pytest.mark.parametrize("api_client", list(_CLIENT_CLASSES))
    def test_each_choice_reaches_its_client(self, runner, mocker, api_client):
        """Each value builds its client with the host configuration, timeouts, and logger."""
        mock_class, instance = self._mock_client(mocker, api_client)

        result = runner.invoke(main, ["-C", api_client, "system", "ping"])

        assert result.exit_code == 0
        assert "pong" in result.output
        if api_client.endswith("websocket"):
            mock_class.assert_called_once_with(VolumioHostConfiguration(), 5.0, LOGGER)
            instance.connect.assert_called_once_with()
            instance.disconnect.assert_called_once_with()
        else:
            mock_class.assert_called_once_with(
                VolumioHostConfiguration(), timeout=5.0, timeout_slow_endpoints=60.0, logger=LOGGER
            )
            # The session of the REST client is released at exit
            instance.close.assert_called_once_with()
        if api_client == "asynchronous_rest":
            instance.close.assert_awaited_once_with()

    @pytest.mark.parametrize("short_form", ["sync_websocket", "sw"])
    def test_a_short_form_selects_its_client(self, runner, mocker, short_form):
        """A short form of a value selects the same client as the value itself."""
        mock_class, _ = self._mock_client(mocker, "synchronous_websocket")

        result = runner.invoke(main, ["-v", "-C", short_form, "system", "ping"])

        assert result.exit_code == 0
        assert "pong" in result.output
        assert "Using the Synchronous WebSocket API client" in result.output
        assert "Connecting to http://volumio.local:3000... done" in result.output
        mock_class.assert_called_once()

    def test_the_websocket_port_and_timeout_reach_the_client(self, runner, mocker):
        """-W/--websocket-port and --websocket-timeout configure the WebSocket API client."""
        mock_class, _ = self._mock_client(mocker, "synchronous_websocket")

        result = runner.invoke(
            main,
            [
                "-v",
                "-C", "synchronous_websocket",
                "-W", "4000",
                "--websocket-timeout", "7",
                "system", "ping",
            ],
        )

        assert result.exit_code == 0
        host_configuration, timeout, _ = mock_class.call_args[0]
        assert host_configuration.websocket_port == 4000
        assert timeout == 7.0
        assert "Using the Synchronous WebSocket API client" in result.output
        assert "Connecting to http://volumio.local:4000... done" in result.output

    def test_the_client_is_shared_by_the_calls_of_an_invocation(self, runner, mocker):
        """The resulting status of a playback command reuses the connection of the command."""
        mock_class, instance = self._mock_client(mocker, "synchronous_websocket")
        _attach_property(instance, "state", return_value={"title": "Test Song", "status": "pause"})
        mocker.patch("volumito.cli.click_helpers.time.sleep")

        result = runner.invoke(main, ["-C", "synchronous_websocket", "playback", "pause"])

        assert result.exit_code == 0
        assert "Command 'pause' executed successfully" in result.output
        assert "Test Song" in result.output
        mock_class.assert_called_once()
        instance.connect.assert_called_once_with()
        instance.disconnect.assert_called_once_with()
        instance.pause.assert_called_once_with()
        instance.state_property.assert_called_once()

    def test_the_configuration_file_keys_are_honored(self, runner, mocker, tmp_path):
        """The API client, WebSocket port, and WebSocket timeout can come from the file."""
        mock_class, _ = self._mock_client(mocker, "asynchronous_websocket")
        config = self._write_configuration(
            tmp_path,
            "volumio:\n"
            "  api-client: asynchronous_websocket\n"
            "  websocket-port: 4000\n"
            "timeouts:\n"
            "  websocket-timeout: 9\n",
        )

        result = runner.invoke(main, ["-c", config, "system", "ping"])

        assert result.exit_code == 0
        host_configuration, timeout, _ = mock_class.call_args[0]
        assert host_configuration.websocket_port == 4000
        assert timeout == 9.0

    def test_a_short_form_in_the_configuration_file(self, runner, mocker, tmp_path):
        """A short form in the file selects the same client as the value itself."""
        mock_class, _ = self._mock_client(mocker, "asynchronous_rest")
        config = self._write_configuration(tmp_path, "volumio:\n  api-client: ar\n")

        result = runner.invoke(main, ["-c", config, "-v", "system", "ping"])

        assert result.exit_code == 0
        assert "Using the Asynchronous REST API client" in result.output
        mock_class.assert_called_once()

    def test_an_invalid_api_client_in_the_configuration_file(self, runner, tmp_path):
        """A value outside the accepted ones in the file is rejected like on the command line."""
        config = self._write_configuration(tmp_path, "volumio:\n  api-client: nope\n")

        result = runner.invoke(main, ["-c", config, "system", "ping"])

        assert result.exit_code == 2
        assert "Invalid value for" in result.output
        assert "'--api-client'" in result.output

    @pytest.mark.parametrize(
        ("arguments", "allowed"),
        [
            ([], False),
            (["--allow-fallback-to-websocket-api"], True),
            (["--no-allow-fallback-to-websocket-api"], False),
        ],
    )
    def test_the_websocket_fallback_switch_reaches_the_client(
        self, runner, mocker, arguments, allowed
    ):
        """The switch allowing a REST API client to fall back is passed on, off by default."""
        create = mocker.patch("volumito.cli.click_helpers.create_client")
        create.return_value.ping.return_value = "pong"

        result = runner.invoke(main, [*arguments, "system", "ping"])

        assert result.exit_code == 0
        assert "pong" in result.output
        assert create.call_args.kwargs["allow_fallback_to_websocket_api"] is allowed

    def test_the_websocket_fallback_switch_from_the_configuration_file(
        self, runner, mocker, tmp_path
    ):
        """The fallback to a WebSocket API client can be allowed from the file."""
        create = mocker.patch("volumito.cli.click_helpers.create_client")
        create.return_value.ping.return_value = "pong"
        config = self._write_configuration(
            tmp_path, "volumio:\n  allow-fallback-to-websocket-api: true\n"
        )

        result = runner.invoke(main, ["-c", config, "system", "ping"])

        assert result.exit_code == 0
        assert create.call_args.kwargs["allow_fallback_to_websocket_api"] is True

    def test_the_fallback_switch_from_the_configuration_file(self, runner, mocker, tmp_path):
        """The fallback to the REST API client can be allowed from the file."""
        self._mock_client(mocker, "synchronous_websocket")
        rest_class, _ = self._mock_story(mocker, "synchronous_rest")
        config = self._write_configuration(
            tmp_path,
            "volumio:\n"
            "  api-client: synchronous_websocket\n"
            "  allow-fallback-to-rest-api: true\n",
        )

        result = runner.invoke(main, ["-c", config, "story", "artist", "Mango"])

        assert result.exit_code == 0
        assert json.loads(result.stdout)["data"]["value"] == "A long story."
        rest_class.assert_called_once()

    @pytest.mark.parametrize(
        "arguments",
        [
            ["system", "ping"],
            ["playback", "pause"],
            ["queue", "track", "audio"],
            ["queue", "track", "albumart"],
            ["queue", "list"],
            ["queue", "download", "-d", "{tmp_path}"],
            ["playlist", "download", "--no-check-playlist-name", "X", "-d", "{tmp_path}"],
        ],
    )
    def test_a_client_that_cannot_open_fails_the_command(
        self, runner, mocker, tmp_path, arguments
    ):
        """A client failing to open (e.g., its extra missing) fails the command with exit 1."""
        _, instance = self._mock_client(mocker, "synchronous_websocket")
        instance.connect.side_effect = VolumioWebSocketError("needs python-socketio")
        arguments = [argument.replace("{tmp_path}", str(tmp_path)) for argument in arguments]

        result = runner.invoke(main, ["-C", "synchronous_websocket", *arguments])

        assert result.exit_code == 1
        assert "API client error: needs python-socketio" in result.output

    def test_an_asynchronous_client_error_fails_the_command(self, runner, mocker):
        """The failure of an asynchronous client (e.g., its extra missing) exits 1."""
        _, instance = self._mock_client(mocker, "asynchronous_rest")
        instance.ping = AsyncMock(side_effect=VolumioAsyncError("needs aiohttp"))

        result = runner.invoke(main, ["-C", "asynchronous_rest", "system", "ping"])

        assert result.exit_code == 1
        assert "API client error: needs aiohttp" in result.output

    @pytest.mark.parametrize(
        ("arguments", "operation"),
        [
            (["story", "artist", "Mango"], "the story queries"),
            (["notification", "list"], "the notification URLs"),
        ],
    )
    def test_the_websocket_gaps_fail_without_the_fallback(
        self, runner, mocker, arguments, operation
    ):
        """The commands the WebSocket API does not offer fail, naming the remedies."""
        self._mock_client(mocker, "synchronous_websocket")

        result = runner.invoke(main, ["-C", "synchronous_websocket", *arguments])

        assert result.exit_code == 1
        assert (
            "API client error: The Synchronous WebSocket API client does not offer "
            f"{operation}: use --api-client synchronous_rest or asynchronous_rest, "
            "or --allow-fallback-to-rest-api"
        ) in result.output

    @pytest.mark.parametrize(
        ("api_client", "rest_api_client"),
        [
            ("synchronous_websocket", "synchronous_rest"),
            ("asynchronous_websocket", "asynchronous_rest"),
        ],
    )
    def test_the_websocket_gaps_fall_back_to_the_rest_api_client(
        self, runner, mocker, api_client, rest_api_client
    ):
        """With the fallback allowed, the REST API client of the same kind serves them."""
        _, instance = self._mock_client(mocker, api_client)
        rest_class, rest = self._mock_story(mocker, rest_api_client)

        result = runner.invoke(
            main, ["-C", api_client, "--allow-fallback-to-rest-api", "story", "artist", "Mango"]
        )

        assert result.exit_code == 0
        assert json.loads(result.stdout)["data"]["value"] == "A long story."
        assert "Falling back to the REST API client for the story queries" in result.output
        rest_class.assert_called_once()
        instance.disconnect.assert_called_once_with()
        if rest_api_client == "asynchronous_rest":
            rest.close.assert_awaited_once_with()

    def test_the_fallback_client_serves_every_operation_of_an_invocation(
        self, runner, mocker
    ):
        """The REST API client is built once, however many operations fall back to it."""
        self._mock_client(mocker, "synchronous_websocket")
        rest_class, rest = self._mock_client(mocker, "synchronous_rest")
        _attach_property(rest, "notifications", return_value=self._URLS)
        rest.unregister_notification.return_value = SuccessResponse.from_raw({"success": True})

        result = runner.invoke(
            main,
            ["-C", "synchronous_websocket", "--allow-fallback-to-rest-api", "notification",
             "unregister", "--all"],
        )

        assert result.exit_code == 0
        rest_class.assert_called_once()
        assert rest.unregister_notification.call_count == 2
        assert result.output.count("Falling back to the REST API client") == 3


class TestCLICommands:
    """Test cases for CLI commands using CliRunner."""

    @pytest.fixture
    def runner(self):
        """Create a CliRunner instance."""
        return CliRunner()

    @pytest.fixture(autouse=True)
    def _no_resulting_status(self, mocker: MockerFixture):
        """Isolate per-command tests from the print-resulting-status feature.

        Player action subcommands print the resulting "playback status" by default;
        no-op the helper here so these tests stay focused (and fast). The feature
        itself is covered by TestPrintResultingState.
        """
        mocker.patch("volumito.cli.volumito.execute_conditionally")

    def _mock_mpd_client(
        self,
        mocker: MockerFixture,
        track_uri: str | None = None,
        side_effect: Exception | None = None,
    ):
        """Helper to create a mocked VolumioMPDClient with context manager support."""
        mock_mpd_instance = mocker.Mock()
        if track_uri:
            mock_mpd_instance.get_track_uri.return_value = track_uri
        if side_effect:
            mock_mpd_instance.get_track_uri.side_effect = side_effect

        mock_mpd_client_class = mocker.Mock(return_value=mock_mpd_instance)
        mock_mpd_client_class.return_value.__enter__ = mocker.Mock(return_value=mock_mpd_instance)
        mock_mpd_client_class.return_value.__exit__ = mocker.Mock(return_value=None)

        mocker.patch("volumito.cli.volumito.VolumioMPDClient", new=mock_mpd_client_class)
        return mock_mpd_instance

    def test_main_help(self, runner: CliRunner):
        """Test main command with --help."""
        result = runner.invoke(main, ["--help"])

        assert result.exit_code == 0
        assert "volumito" in result.output
        assert "info" in result.output
        assert "version" in result.output
        assert "--allow-fallback-to-rest-api" in result.output
        assert "--allow-fallback-to-websocket-api" in result.output
        assert "--api-client" in result.output
        assert "--machine-readable" in result.output
        assert "--rest-api-timeout" in result.output
        assert "--mpd-timeout" in result.output
        assert "--pager" in result.output
        assert "--retries-on-unexpected-state" in result.output
        assert "--sleep-before-next-api-call" in result.output
        assert "--strict-parsing-configuration-file" in result.output
        assert "--websocket-port" in result.output
        assert "--websocket-timeout" in result.output
        # Short options
        assert "-C" in result.output
        assert "-G" in result.output
        assert "-H" in result.output
        assert "-M" in result.output
        assert "-P" in result.output
        assert "-W" in result.output

    def test_version_command(self, runner: CliRunner):
        """Test the version subcommand."""
        result = runner.invoke(main, ["version"])

        assert result.exit_code == 0
        assert "volumito, version 0.5.0" in result.output

    def test_version_command_machine_readable(self, runner: CliRunner):
        """Test --machine-readable version prints the quoted version string."""
        result = runner.invoke(main, ["--machine-readable", "version"])

        assert result.exit_code == 0
        assert result.output.strip() == '"0.5.0"'
        assert "volumito" not in result.output
        assert "version" not in result.output

    def test_version_command_machine_readable_shorthand(self, runner: CliRunner):
        """Test the -m shorthand for --machine-readable with the version subcommand."""
        result = runner.invoke(main, ["-m", "version"])

        assert result.exit_code == 0
        assert result.output.strip() == '"0.5.0"'

    def test_info_help(self, runner: CliRunner):
        """The top-level info command is an alias for system info (minimal surface)."""
        result = runner.invoke(main, ["info", "--help"])

        assert result.exit_code == 0
        assert "--format" in result.output
        assert "--raw" not in result.output
        # info is now system info: no --fields
        assert "--fields" not in result.output

    def test_info_success_default(self, runner: CliRunner, mocker: MockerFixture):
        """The info alias fetches the system info and prints it as pretty JSON."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "system_info", return_value={
            "name": "Living Room",
            "systemversion": "3.601",
        })

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["info"])

        assert result.exit_code == 0
        assert "Living Room" in result.output
        mock_client.system_info_property.assert_called_once()

    def test_playback_status_help(self, runner: CliRunner):
        """Test playback status command with --help."""
        result = runner.invoke(main, ["playback", "status", "--help"])

        assert result.exit_code == 0
        assert "--format" in result.output
        assert "--fields" in result.output
        # Short options
        assert "-F" in result.output
        assert "-L" in result.output
        # The --raw flag has been replaced by the "raw" value of --format
        assert "--raw" not in result.output
        assert "raw" in result.output

    def test_playback_status_raw_option_removed(self, runner: CliRunner):
        """The removed -R/--raw option is now a usage error."""
        for option in ("-R", "--raw"):
            result = runner.invoke(main, ["playback", "status", option])
            assert result.exit_code == 2
            assert "No such option" in result.output

    def test_playback_status_success_default(self, runner: CliRunner, mocker: MockerFixture):
        """Test playback status (the canonical form of info) with default options."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={
            "position": 0,
            "title": "Test Song",
            "artist": "Test Artist",
        })

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["playback", "status"])

        assert result.exit_code == 0
        assert "Test Song" in result.output

    def test_info_with_custom_host(self, runner: CliRunner, mocker: MockerFixture):
        """Test info command with custom host."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "system_info", return_value={"name": "Test"})

        mock_client_class = mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["--host", "192.168.1.100", "info"])

        assert result.exit_code == 0
        mock_client_class.assert_called_once()
        host_configuration = mock_client_class.call_args[0][0]
        assert host_configuration.host == "192.168.1.100"

    def test_info_with_raw_format(self, runner: CliRunner, mocker: MockerFixture):
        """Test info command with --format raw prints compact JSON."""
        mock_client = mocker.Mock()
        _attach_property(
            mock_client, "system_info", return_value={"name": "Test", "systemversion": "3.601"}
        )

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["info", "--format", "raw"])

        assert result.exit_code == 0
        # Compact single-line JSON
        assert "\n" not in result.output.strip()
        output_data = json.loads(result.output)
        assert output_data["name"] == "Test"
        assert output_data["systemversion"] == "3.601"

    def test_short_option_host(self, runner: CliRunner, mocker: MockerFixture):
        """Test the -H shorthand for --host."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "system_info", return_value={"name": "Test"})

        mock_client_class = mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["-H", "192.168.1.100", "info"])

        assert result.exit_code == 0
        host_configuration = mock_client_class.call_args[0][0]
        assert host_configuration.host == "192.168.1.100"

    def test_short_option_ports(self, runner: CliRunner, mocker: MockerFixture):
        """Test the -M/-P shorthands for --mpd-port/--rest-api-port."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "system_info", return_value={"name": "Test"})

        mock_client_class = mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["-M", "6599", "-P", "8080", "info"])

        assert result.exit_code == 0
        host_configuration = mock_client_class.call_args[0][0]
        assert host_configuration.mpd_port == 6599
        assert host_configuration.rest_api_port == 8080

    def test_short_option_format(self, runner: CliRunner, mocker: MockerFixture):
        """Test the -F shorthand for --format (on playback status)."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={"title": "Test Song"})

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["playback", "status", "-F", "table"])

        assert result.exit_code == 0
        assert "Volumio Status" in result.output
        assert "Test Song" in result.output

    def test_short_option_fields(self, runner: CliRunner, mocker: MockerFixture):
        """Test the -L shorthand for --fields (on playback status)."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={
            "title": "Test",
            "volume": 100,
            "extra": "data",
        })

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["playback", "status", "-L", "ALL"])

        assert result.exit_code == 0
        output_data = json.loads(result.output)
        assert "extra" in output_data

    def test_short_option_format_raw(self, runner: CliRunner, mocker: MockerFixture):
        """Test the -F shorthand with the raw format (on the info/system info command)."""
        mock_client = mocker.Mock()
        _attach_property(
            mock_client, "system_info", return_value={"name": "Test", "systemversion": "3.601"}
        )

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["info", "-F", "raw"])

        assert result.exit_code == 0
        output_data = json.loads(result.output)
        assert output_data["name"] == "Test"
        assert output_data["systemversion"] == "3.601"

    def test_short_option_position(self, runner: CliRunner, mocker: MockerFixture):
        """Test the -p shorthand for --position on playback play."""
        mock_client = mocker.Mock()
        mock_client.play.return_value = {"response": "play"}

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["playback", "play", "3"])

        assert result.exit_code == 0
        # Position is 1-indexed on the CLI, 0-indexed to the client
        mock_client.play.assert_called_once_with(2)

    def test_info_with_verbose(self, runner: CliRunner, mocker: MockerFixture):
        """Test info command with --verbose flag."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "system_info", return_value={"name": "Test"})

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["--verbose", "info"])

        assert result.exit_code == 0
        # Verbose messages go to stderr
        assert "Connecting to" in result.output or "Successfully retrieved" in result.output

    def test_info_connection_error(self, runner: CliRunner, mocker: MockerFixture):
        """Test info command with connection error."""
        mock_client = mocker.Mock()
        _attach_property(
            mock_client, "system_info", side_effect=VolumioConnectionError("Connection failed")
        )

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["info"])

        assert result.exit_code == 1
        assert "Connection error" in result.output

    def test_info_api_error(self, runner: CliRunner, mocker: MockerFixture):
        """Test info command with API error."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "system_info", side_effect=VolumioAPIError("API error"))

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["info"])

        assert result.exit_code == 1
        assert "API error" in result.output

    def test_info_machine_readable_suppresses_errors(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """Test info command with --machine-readable flag suppresses errors."""
        mock_client = mocker.Mock()
        _attach_property(
            mock_client, "system_info", side_effect=VolumioConnectionError("Connection failed")
        )

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["--machine-readable", "info"])

        assert result.exit_code == 1
        # No error output with machine-readable flag
        assert result.output == ""

    def test_playback_help(self, runner: CliRunner):
        """Test playback group with --help."""
        result = runner.invoke(main, ["playback", "--help"])

        assert result.exit_code == 0
        assert "playback" in result.output.lower()
        assert "status" in result.output.lower()
        assert "toggle" in result.output.lower()
        assert "play" in result.output.lower()
        assert "pause" in result.output.lower()
        assert "volume" in result.output.lower()
        assert "mute" in result.output.lower()
        assert "unmute" in result.output.lower()

    def test_playback_no_subcommand(self, runner: CliRunner):
        """Test playback group without subcommand."""
        result = runner.invoke(main, ["playback"])

        # Click returns exit code 2 when a group is invoked without a subcommand
        assert result.exit_code == 2
        assert "playback" in result.output.lower()
        # Should show usage/error information when no subcommand is provided
        assert "toggle" in result.output.lower() or "play" in result.output.lower()

    def test_toggle_help(self, runner: CliRunner):
        """Test toggle command with --help."""
        result = runner.invoke(main, ["playback", "toggle", "--help"])

        assert result.exit_code == 0
        assert "toggle" in result.output.lower()
        # Global options like --scheme and --host are shown in main --help, not subcommand help

    def test_toggle_success_default(self, runner: CliRunner, mocker: MockerFixture):
        """Test successful toggle command with default options."""
        mock_client = mocker.Mock()
        mock_client.toggle.return_value = {"response": "toggle"}

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["playback", "toggle"])

        assert result.exit_code == 0
        assert "Command 'toggle' executed successfully" in result.output

    def test_toggle_with_custom_host(self, runner: CliRunner, mocker: MockerFixture):
        """Test toggle command with custom host."""
        mock_client = mocker.Mock()
        mock_client.toggle.return_value = {"response": "toggle"}

        mock_client_class = mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["--host", "192.168.1.50", "playback", "toggle"])

        assert result.exit_code == 0
        host_configuration = mock_client_class.call_args[0][0]
        assert host_configuration.host == "192.168.1.50"

    def test_toggle_with_verbose(self, runner: CliRunner, mocker: MockerFixture):
        """Test toggle command with --verbose flag."""
        mock_client = mocker.Mock()
        mock_client.toggle.return_value = {"response": "toggle"}

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["--verbose", "playback", "toggle"])

        assert result.exit_code == 0
        assert "Connecting to" in result.output

    def test_toggle_connection_error(self, runner: CliRunner, mocker: MockerFixture):
        """Test toggle command with connection error."""
        mock_client = mocker.Mock()
        mock_client.toggle.side_effect = VolumioConnectionError("Connection failed")

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["playback", "toggle"])

        assert result.exit_code == 1
        assert "Connection error" in result.output

    def test_toggle_api_error(self, runner: CliRunner, mocker: MockerFixture):
        """Test toggle command with API error."""
        mock_client = mocker.Mock()
        mock_client.toggle.side_effect = VolumioAPIError("API error")

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["playback", "toggle"])

        assert result.exit_code == 1
        assert "API error" in result.output

    def test_play_success_default(self, runner: CliRunner, mocker: MockerFixture):
        """Test successful play command with default options."""
        mock_client = mocker.Mock()
        mock_client.play.return_value = {"response": "play"}

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["playback", "play"])

        assert result.exit_code == 0
        assert "Command 'play' executed successfully" in result.output

    def test_play_connection_error(self, runner: CliRunner, mocker: MockerFixture):
        """Test play command with connection error."""
        mock_client = mocker.Mock()
        mock_client.play.side_effect = VolumioConnectionError("Connection failed")

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["playback", "play"])

        assert result.exit_code == 1
        assert "Connection error" in result.output

    def test_play_with_verbose(self, runner: CliRunner, mocker: MockerFixture):
        """Test play command with --verbose flag."""
        mock_client = mocker.Mock()
        mock_client.play.return_value = {"response": "play"}

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["--verbose", "playback", "play"])

        assert result.exit_code == 0
        assert "Connecting to" in result.output

    def test_pause_success_default(self, runner: CliRunner, mocker: MockerFixture):
        """Test successful pause command with default options."""
        mock_client = mocker.Mock()
        mock_client.pause.return_value = {"response": "pause"}

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["playback", "pause"])

        assert result.exit_code == 0
        assert "Command 'pause' executed successfully" in result.output

    def test_pause_connection_error(self, runner: CliRunner, mocker: MockerFixture):
        """Test pause command with connection error."""
        mock_client = mocker.Mock()
        mock_client.pause.side_effect = VolumioConnectionError("Connection failed")

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["playback", "pause"])

        assert result.exit_code == 1
        assert "Connection error" in result.output

    def test_pause_with_machine_readable(self, runner: CliRunner, mocker: MockerFixture):
        """Test pause command with --machine-readable flag."""
        mock_client = mocker.Mock()
        mock_client.pause.return_value = {"response": "pause"}

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["--machine-readable", "playback", "pause"])

        assert result.exit_code == 0
        assert result.output == ""

    def test_stop_success_default(self, runner: CliRunner, mocker: MockerFixture):
        """Test successful stop command with default options."""
        mock_client = mocker.Mock()
        mock_client.stop.return_value = {"response": "stop"}

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["playback", "stop"])

        assert result.exit_code == 0
        assert "Command 'stop' executed successfully" in result.output

    def test_stop_api_error(self, runner: CliRunner, mocker: MockerFixture):
        """Test stop command with API error."""
        mock_client = mocker.Mock()
        mock_client.stop.side_effect = VolumioAPIError("API error")

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["playback", "stop"])

        assert result.exit_code == 1
        assert "API error" in result.output

    def test_next_success_default(self, runner: CliRunner, mocker: MockerFixture):
        """Test successful next command with default options."""
        mock_client = mocker.Mock()
        mock_client.next.return_value = {"response": "next"}

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["playback", "next"])

        assert result.exit_code == 0
        assert "Command 'next' executed successfully" in result.output

    def test_next_with_custom_options(self, runner: CliRunner, mocker: MockerFixture):
        """Test next command with custom host, port, and REST API timeout."""
        mock_client = mocker.Mock()
        mock_client.next.return_value = {"response": "next"}

        mock_client_class = mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(
            main,
            [
                "--host", "192.168.1.100",
                "--rest-api-port", "8080",
                "--rest-api-timeout", "10",
                "playback", "next"
            ],
        )

        assert result.exit_code == 0
        host_configuration = mock_client_class.call_args[0][0]
        timeout = mock_client_class.call_args.kwargs["timeout"]
        assert host_configuration.host == "192.168.1.100"
        assert host_configuration.rest_api_port == 8080
        assert timeout == 10.0

    def test_previous_success_default(self, runner: CliRunner, mocker: MockerFixture):
        """Test successful previous command with default options."""
        mock_client = mocker.Mock()
        mock_client.previous.return_value = {"response": "prev"}

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["playback", "previous"])

        assert result.exit_code == 0
        assert "Command 'previous' executed successfully" in result.output

    def test_previous_connection_error(self, runner: CliRunner, mocker: MockerFixture):
        """Test previous command with connection error."""
        mock_client = mocker.Mock()
        mock_client.previous.side_effect = VolumioConnectionError("Connection failed")

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["playback", "previous"])

        assert result.exit_code == 1
        assert "Connection error" in result.output

    def test_play_machine_readable_suppresses_errors(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """Test play command with --machine-readable flag suppresses errors."""
        mock_client = mocker.Mock()
        mock_client.play.side_effect = VolumioAPIError("API error")

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["--machine-readable", "playback", "play"])

        assert result.exit_code == 1
        assert result.output == ""

    def test_stop_with_verbose(self, runner: CliRunner, mocker: MockerFixture):
        """Test stop command with --verbose flag."""
        mock_client = mocker.Mock()
        mock_client.stop.return_value = {"response": "stop"}

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["--verbose", "playback", "stop"])

        assert result.exit_code == 0
        assert "Connecting to" in result.output

    def test_next_connection_error(self, runner: CliRunner, mocker: MockerFixture):
        """Test next command with connection error."""
        mock_client = mocker.Mock()
        mock_client.next.side_effect = VolumioConnectionError("Connection failed")

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["playback", "next"])

        assert result.exit_code == 1
        assert "Connection error" in result.output

    def test_previous_api_error(self, runner: CliRunner, mocker: MockerFixture):
        """Test previous command with API error."""
        mock_client = mocker.Mock()
        mock_client.previous.side_effect = VolumioAPIError("API error")

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["playback", "previous"])

        assert result.exit_code == 1
        assert "API error" in result.output

    def test_toggle_with_machine_readable(self, runner: CliRunner, mocker: MockerFixture):
        """Test toggle command with --machine-readable flag and connection error."""
        mock_client = mocker.Mock()
        mock_client.toggle.side_effect = VolumioConnectionError("Connection failed")

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["--machine-readable", "playback", "toggle"])

        assert result.exit_code == 1
        assert result.output == ""

    def test_play_api_error(self, runner: CliRunner, mocker: MockerFixture):
        """Test play command with API error."""
        mock_client = mocker.Mock()
        mock_client.play.side_effect = VolumioAPIError("API error")

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["playback", "play"])

        assert result.exit_code == 1
        assert "API error" in result.output

    def test_pause_api_error(self, runner: CliRunner, mocker: MockerFixture):
        """Test pause command with API error."""
        mock_client = mocker.Mock()
        mock_client.pause.side_effect = VolumioAPIError("API error")

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["playback", "pause"])

        assert result.exit_code == 1
        assert "API error" in result.output

    def test_stop_connection_error(self, runner: CliRunner, mocker: MockerFixture):
        """Test stop command with connection error."""
        mock_client = mocker.Mock()
        mock_client.stop.side_effect = VolumioConnectionError("Connection failed")

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["playback", "stop"])

        assert result.exit_code == 1
        assert "Connection error" in result.output

    def test_next_api_error(self, runner: CliRunner, mocker: MockerFixture):
        """Test next command with API error."""
        mock_client = mocker.Mock()
        mock_client.next.side_effect = VolumioAPIError("API error")

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["playback", "next"])

        assert result.exit_code == 1
        assert "API error" in result.output

    def test_pause_with_verbose(self, runner: CliRunner, mocker: MockerFixture):
        """Test pause command with --verbose flag."""
        mock_client = mocker.Mock()
        mock_client.pause.return_value = {"response": "pause"}

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["--verbose", "playback", "pause"])

        assert result.exit_code == 0
        assert "Connecting to" in result.output
        assert "Response:" in result.output

    def test_next_with_verbose(self, runner: CliRunner, mocker: MockerFixture):
        """Test next command with --verbose flag."""
        mock_client = mocker.Mock()
        mock_client.next.return_value = {"response": "next"}

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["--verbose", "playback", "next"])

        assert result.exit_code == 0
        assert "Connecting to" in result.output
        assert "Response:" in result.output

    def test_previous_with_verbose(self, runner: CliRunner, mocker: MockerFixture):
        """Test previous command with --verbose flag."""
        mock_client = mocker.Mock()
        mock_client.previous.return_value = {"response": "prev"}

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["--verbose", "playback", "previous"])

        assert result.exit_code == 0
        assert "Connecting to" in result.output
        assert "Response:" in result.output

    def test_volume_help(self, runner: CliRunner):
        """Test playback volume command with --help."""
        result = runner.invoke(main, ["playback", "volume", "--help"])

        assert result.exit_code == 0
        assert "volume" in result.output.lower()

    def test_volume_absolute_success(self, runner: CliRunner, mocker: MockerFixture):
        """Test playback volume with an absolute integer level."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "volume")

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["playback", "volume", "50"])

        assert result.exit_code == 0
        assert "Command 'volume 50' executed successfully" in result.output
        # The value reaches the client as an int, assigned to the volume property
        mock_client.volume_property.assert_called_once_with(50)

    def test_volume_no_value_prints_current(self, runner: CliRunner, mocker: MockerFixture):
        """Test playback volume without a value prints the current volume."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "volume", return_value=42)

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["playback", "volume"])

        assert result.exit_code == 0
        assert "42" in result.output
        # The property is only read, never assigned
        mock_client.volume_property.assert_called_once_with()

    @pytest.mark.parametrize(
        ("spelling", "method"),
        [
            ("up", "increase_volume"),
            ("increase", "increase_volume"),
            ("down", "decrease_volume"),
            ("decrease", "decrease_volume"),
        ],
    )
    def test_volume_alias_success(
        self, runner: CliRunner, mocker: MockerFixture, spelling: str, method: str
    ):
        """Test playback volume dispatches the step aliases to the dedicated methods."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "volume")

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["playback", "volume", spelling])

        assert result.exit_code == 0
        getattr(mock_client, method).assert_called_once_with()
        mock_client.volume_property.assert_not_called()

    @pytest.mark.parametrize(
        ("keyword", "method"),
        [("plus", "increase_volume"), ("minus", "decrease_volume")],
    )
    def test_volume_keyword_success(
        self, runner: CliRunner, mocker: MockerFixture, keyword: str, method: str
    ):
        """Test playback volume dispatches the step keywords to the dedicated methods."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "volume")

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["playback", "volume", keyword])

        assert result.exit_code == 0
        getattr(mock_client, method).assert_called_once_with()
        mock_client.volume_property.assert_not_called()

    @pytest.mark.parametrize("keyword", ["mute", "unmute"])
    def test_volume_mute_keywords(
        self, runner: CliRunner, mocker: MockerFixture, keyword: str
    ):
        """Test playback volume dispatches mute/unmute to the dedicated client methods."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "volume")

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["playback", "volume", keyword])

        assert result.exit_code == 0
        getattr(mock_client, keyword).assert_called_once_with()
        mock_client.volume_property.assert_not_called()

    @pytest.mark.parametrize("level", ["0", "100"])
    def test_volume_boundaries(self, runner: CliRunner, mocker: MockerFixture, level: str):
        """Test playback volume accepts the 0 and 100 boundary levels."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "volume")

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["playback", "volume", level])

        assert result.exit_code == 0
        mock_client.volume_property.assert_called_once_with(int(level))

    @pytest.mark.parametrize("bad_value", ["101", "-1", "foo", "UP", "+"])
    def test_volume_invalid(self, runner: CliRunner, mocker: MockerFixture, bad_value: str):
        """Test playback volume rejects out-of-range, non-numeric, and non-lowercase values."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "volume")

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["playback", "volume", bad_value])

        # Click reports a usage error (exit code 2) and never calls the client
        assert result.exit_code == 2
        mock_client.volume_property.assert_not_called()

    def test_mute_synonym(self, runner: CliRunner, mocker: MockerFixture):
        """Test playback mute is a synonym for playback volume mute."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "volume")
        mock_client.mute.return_value = {"response": "volume"}

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["playback", "mute"])

        assert result.exit_code == 0
        assert "Command 'volume mute' executed successfully" in result.output
        mock_client.mute.assert_called_once_with()
        mock_client.volume_property.assert_not_called()

    def test_unmute_synonym(self, runner: CliRunner, mocker: MockerFixture):
        """Test playback unmute is a synonym for playback volume unmute."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "volume")
        mock_client.unmute.return_value = {"response": "volume"}

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["playback", "unmute"])

        assert result.exit_code == 0
        assert "Command 'volume unmute' executed successfully" in result.output
        mock_client.unmute.assert_called_once_with()
        mock_client.volume_property.assert_not_called()

    @pytest.mark.parametrize("value", [True, False])
    def test_is_muted(self, runner: CliRunner, mocker: MockerFixture, value: bool):
        """playback is_muted prints the mute flag read from the client."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "is_muted", return_value=value)

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["playback", "is_muted"])

        assert result.exit_code == 0
        assert result.output.strip() == str(value)
        mock_client.is_muted_property.assert_called_once_with()

    def test_is_muted_machine_readable(self, runner: CliRunner, mocker: MockerFixture):
        """In machine-readable mode the mute flag is printed as a JSON boolean."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "is_muted", return_value=True)

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["-m", "playback", "is_muted"])

        assert result.exit_code == 0
        assert result.output.strip() == "true"

    def test_is_muted_connection_error(self, runner: CliRunner, mocker: MockerFixture):
        """playback is_muted exits 1 on a connection error."""
        mock_client = mocker.Mock()
        _attach_property(
            mock_client, "is_muted", side_effect=VolumioConnectionError("Connection failed")
        )

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["playback", "is_muted"])

        assert result.exit_code == 1
        assert "Connection error" in result.output

    @pytest.mark.parametrize("command", ["is_paused", "is_playing", "is_stopped"])
    @pytest.mark.parametrize("value", [True, False])
    def test_status_flag_commands(
        self, runner: CliRunner, mocker: MockerFixture, command: str, value: bool
    ):
        """The playback status flag commands print the flag read from the client."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, command, return_value=value)

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["playback", command])

        assert result.exit_code == 0
        assert result.output.strip() == str(value)
        getattr(mock_client, f"{command}_property").assert_called_once_with()

    @pytest.mark.parametrize("command", ["is_paused", "is_playing", "is_stopped"])
    def test_status_flag_commands_machine_readable(
        self, runner: CliRunner, mocker: MockerFixture, command: str
    ):
        """In machine-readable mode the status flags are printed as JSON booleans."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, command, return_value=True)

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["-m", "playback", command])

        assert result.exit_code == 0
        assert result.output.strip() == "true"

    @pytest.mark.parametrize("command", ["is_paused", "is_playing", "is_stopped"])
    def test_status_flag_commands_connection_error(
        self, runner: CliRunner, mocker: MockerFixture, command: str
    ):
        """The playback status flag commands exit 1 on a connection error."""
        mock_client = mocker.Mock()
        _attach_property(
            mock_client, command, side_effect=VolumioConnectionError("Connection failed")
        )

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["playback", command])

        assert result.exit_code == 1
        assert "Connection error" in result.output

    def test_track_info_help(self, runner: CliRunner):
        """Test track info command with --help."""
        result = runner.invoke(main, ["queue", "track", "info", "--help"])

        assert result.exit_code == 0
        assert "--fields" in result.output
        assert "--format" in result.output
        # Short options
        assert "-L" in result.output
        assert "-F" in result.output
        assert "--raw" not in result.output
        assert "raw" in result.output

    def test_track_info_success_default(self, runner: CliRunner, mocker: MockerFixture):
        """Test successful track info command with default options."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={
            "position": 0,
            "title": "Test Song",
            "artist": "Test Artist",
        })

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["queue", "track", "info"])

        assert result.exit_code == 0
        assert "Test Song" in result.output

    def test_track_info_fields_short(self, runner: CliRunner, mocker: MockerFixture):
        """Test track info with the track-oriented short field set."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={
            "title": "Test",
            "artist": "Test Artist",
            "samplerate": "44.1 kHz",
            "bitdepth": "16 bit",
            "trackType": "flac",
            "status": "play",
            "volume": 100,
            "extra": "data",
        })

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["queue", "track", "info", "--format", "json"])

        assert result.exit_code == 0
        output_data = json.loads(result.output)
        # Track-oriented fields are present
        assert "samplerate" in output_data
        assert "bitdepth" in output_data
        assert "trackType" in output_data
        # Player-only and unknown fields are dropped
        assert "status" not in output_data
        assert "volume" not in output_data
        assert "extra" not in output_data

    def test_track_info_fields_all(self, runner: CliRunner, mocker: MockerFixture):
        """Test track info with --fields all."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={
            "title": "Test",
            "status": "play",
            "extra": "data",
        })

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["queue", "track", "info", "-L", "ALL"])

        assert result.exit_code == 0
        output_data = json.loads(result.output)
        assert "extra" in output_data
        assert "status" in output_data

    def test_track_info_format_table(self, runner: CliRunner, mocker: MockerFixture):
        """Test track info --format table: 'Track Info' heading and track short-field order."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={
            "position": 0,
            "title": "Test Song",
            "artist": "Test Artist",
            "trackType": "flac",
            "samplerate": "44.1 kHz",
            "bitdepth": "16 bit",
        })

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["queue", "track", "info", "-F", "table"])

        assert result.exit_code == 0
        # Heading is "Track Info", not the playback's "Volumio Status"
        assert "Track Info" in result.output
        assert "Volumio Status" not in result.output
        assert "Test Song" in result.output
        assert "Samplerate" in result.output
        # Fields appear in SHORT_FORMAT_FIELDS_TRACK_INFO order, not sorted alphabetically
        assert (
            result.output.index("Title")
            < result.output.index("Artist")
            < result.output.index("Tracktype")
            < result.output.index("Samplerate")
            < result.output.index("Bitdepth")
        )

    def test_track_info_raw(self, runner: CliRunner, mocker: MockerFixture):
        """Test track info with the raw format."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={"title": "Test", "extra": "data"})

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["queue", "track", "info", "-F", "raw"])

        assert result.exit_code == 0
        output_data = json.loads(result.output)
        # Raw output is the unfiltered state
        assert "title" in output_data
        assert "extra" in output_data

    def test_track_help(self, runner: CliRunner):
        """Test track group with --help."""
        result = runner.invoke(main, ["track", "--help"])

        assert result.exit_code == 0
        assert "track" in result.output.lower()
        assert "info" in result.output.lower()
        assert "audio" in result.output.lower()
        assert "albumart" in result.output.lower()

    def test_track_no_subcommand(self, runner: CliRunner):
        """Test track group without subcommand."""
        result = runner.invoke(main, ["track"])

        # Click returns exit code 2 when a group is invoked without a subcommand
        assert result.exit_code == 2
        assert "track" in result.output.lower()
        # Should show usage/error information when no subcommand is provided
        assert "audio" in result.output.lower() or "albumart" in result.output.lower()

    def test_audio_help(self, runner: CliRunner):
        """Test audio command with --help."""
        result = runner.invoke(main, ["queue", "track", "audio", "--help"])

        assert result.exit_code == 0
        assert "audio" in result.output.lower()
        assert "uri" in result.output.lower()

    def test_audio_success_default(self, runner: CliRunner, mocker: MockerFixture):
        """Test successful audio command with default options."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={
            "title": "Test Song",
            "artist": "Test Artist",
            "album": "Test Album",
            "service": "mpd",
        })

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        self._mock_mpd_client(mocker, track_uri="http://volumio.local:8000/music/test.flac")

        result = runner.invoke(main, ["queue", "track", "audio"])

        assert result.exit_code == 0
        assert "http://volumio.local:8000/music/test.flac" in result.output
        # Without --machine-readable, the URI is printed bare (not quoted)
        assert '"http://volumio.local:8000/music/test.flac"' not in result.output

    def test_audio_with_custom_host(self, runner: CliRunner, mocker: MockerFixture):
        """Test audio command with custom host."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={
            "title": "Test Song",
            "artist": "Test Artist",
        })

        mock_client_class = mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        # The MPD client's get_track_uri() would replace 127.0.0.1 with the actual host
        self._mock_mpd_client(mocker, track_uri="http://192.168.1.100:8000/music/test.flac")

        result = runner.invoke(main, ["--host", "192.168.1.100", "queue", "track", "audio"])

        assert result.exit_code == 0
        host_configuration = mock_client_class.call_args[0][0]
        assert host_configuration.host == "192.168.1.100"
        # Check that localhost was replaced with the custom host
        assert "192.168.1.100" in result.output
        assert "127.0.0.1" not in result.output

    def test_audio_with_custom_mpd_port(self, runner: CliRunner, mocker: MockerFixture):
        """Test audio command with custom MPD port."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={"title": "Test"})

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        # The MPD client's get_track_uri() would replace localhost with volumio.local (default host)
        self._mock_mpd_client(mocker, track_uri="http://volumio.local:8000/music/test.flac")

        result = runner.invoke(main, ["--mpd-port", "6600", "queue", "track", "audio"])

        assert result.exit_code == 0

    def test_audio_with_custom_timeouts(self, runner: CliRunner, mocker: MockerFixture):
        """Test audio command routes --rest-api-timeout and --mpd-timeout to the right clients."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={"title": "Test"})

        mock_rest_class = mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        # Build an MPD class mock so we can inspect the constructor arguments
        mock_mpd_instance = mocker.Mock()
        mock_mpd_instance.get_track_uri.return_value = "http://volumio.local:8000/music/test.flac"
        mock_mpd_class = mocker.Mock(return_value=mock_mpd_instance)
        mock_mpd_class.return_value.__enter__ = mocker.Mock(return_value=mock_mpd_instance)
        mock_mpd_class.return_value.__exit__ = mocker.Mock(return_value=None)
        mocker.patch("volumito.cli.volumito.VolumioMPDClient", new=mock_mpd_class)

        result = runner.invoke(
            main,
            ["--rest-api-timeout", "10", "--mpd-timeout", "3", "queue", "track", "audio"],
        )

        assert result.exit_code == 0
        # REST client receives the REST API timeout
        assert mock_rest_class.call_args.kwargs["timeout"] == 10.0
        # MPD client receives the MPD timeout
        assert mock_mpd_class.call_args[0][1] == 3.0

    def test_audio_replaces_localhost(self, runner: CliRunner, mocker: MockerFixture):
        """Test audio command replaces localhost with host value."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={"title": "Test Song"})

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        # The MPD client's get_track_uri() would replace localhost with myhost.local
        self._mock_mpd_client(mocker, track_uri="http://myhost.local:8000/music/test.flac")

        result = runner.invoke(main, ["--host", "myhost.local", "queue", "track", "audio"])

        assert result.exit_code == 0
        assert "myhost.local" in result.output
        assert "localhost" not in result.output or "localhost" in result.output.lower()

    def test_audio_replaces_127_0_0_1(self, runner: CliRunner, mocker: MockerFixture):
        """Test audio command replaces 127.0.0.1 with host value."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={"title": "Test Song"})

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        # The MPD client's get_track_uri() would replace 127.0.0.1 with myhost.local
        self._mock_mpd_client(mocker, track_uri="http://myhost.local:8000/music/test.flac")

        result = runner.invoke(main, ["--host", "myhost.local", "queue", "track", "audio"])

        assert result.exit_code == 0
        assert "myhost.local" in result.output
        assert "127.0.0.1" not in result.output

    def test_audio_with_verbose(self, runner: CliRunner, mocker: MockerFixture):
        """Test audio command with --verbose flag."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={"title": "Test Song"})

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        # The MPD client's get_track_uri() would replace localhost with volumio.local (default host)
        self._mock_mpd_client(mocker, track_uri="http://volumio.local:8000/music/test.flac")

        result = runner.invoke(main, ["--verbose", "queue", "track", "audio"])

        assert result.exit_code == 0
        assert "Connecting to" in result.output
        assert "Connecting to http://volumio.local:3000... done" in result.output
        assert "Successfully retrieved state" in result.output
        # The MPD steps are logged by the (here mocked) client itself, not by the CLI

    def test_audio_with_machine_readable(self, runner: CliRunner, mocker: MockerFixture):
        """Test audio command with --machine-readable flag."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={"title": "Test Song"})

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        # The MPD client's get_track_uri() would replace localhost with volumio.local (default host)
        self._mock_mpd_client(mocker, track_uri="http://volumio.local:8000/music/test.flac")

        result = runner.invoke(main, ["--machine-readable", "queue", "track", "audio"])

        assert result.exit_code == 0
        # In machine-readable mode, only the quoted URI should be printed
        assert result.output.strip() == '"http://volumio.local:8000/music/test.flac"'
        assert "Title" not in result.output
        assert "Artist" not in result.output

    def test_audio_connection_error(self, runner: CliRunner, mocker: MockerFixture):
        """Test audio command with connection error."""
        mock_client = mocker.Mock()
        _attach_property(
            mock_client, "state", side_effect=VolumioConnectionError("Connection failed")
        )

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["queue", "track", "audio"])

        assert result.exit_code == 1
        assert "Connection error" in result.output

    def test_audio_api_error(self, runner: CliRunner, mocker: MockerFixture):
        """Test audio command with API error."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", side_effect=VolumioAPIError("API error"))

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["queue", "track", "audio"])

        assert result.exit_code == 1
        assert "API error" in result.output

    def test_audio_mpd_connection_refused(self, runner: CliRunner, mocker: MockerFixture):
        """Test audio command with MPD connection refused."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={"title": "Test Song"})

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        # Mock MPD client with connection error raised in __enter__
        mock_mpd_instance = mocker.Mock()
        mock_mpd_client_class = mocker.Mock(return_value=mock_mpd_instance)
        mock_mpd_client_class.return_value.__enter__ = mocker.Mock(
            side_effect=VolumioConnectionError("Connection refused to MPD")
        )
        mock_mpd_client_class.return_value.__exit__ = mocker.Mock(return_value=None)
        mocker.patch("volumito.cli.volumito.VolumioMPDClient", new=mock_mpd_client_class)

        result = runner.invoke(main, ["queue", "track", "audio"])

        assert result.exit_code == 1
        assert "Connection refused to MPD" in result.output

    def test_audio_mpd_os_error(self, runner: CliRunner, mocker: MockerFixture):
        """Test audio command with MPD OS error."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={"title": "Test Song"})

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        # Mock MPD client with connection error raised in __enter__
        mock_mpd_instance = mocker.Mock()
        mock_mpd_client_class = mocker.Mock(return_value=mock_mpd_instance)
        mock_mpd_client_class.return_value.__enter__ = mocker.Mock(
            side_effect=VolumioConnectionError("MPD connection error")
        )
        mock_mpd_client_class.return_value.__exit__ = mocker.Mock(return_value=None)
        mocker.patch("volumito.cli.volumito.VolumioMPDClient", new=mock_mpd_client_class)

        result = runner.invoke(main, ["queue", "track", "audio"])

        assert result.exit_code == 1
        assert "MPD connection error" in result.output

    def test_audio_mpd_no_current_song(self, runner: CliRunner, mocker: MockerFixture):
        """Test audio command when no track is playing."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={"title": "Test Song"})

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        self._mock_mpd_client(
            mocker,
            side_effect=VolumioConnectionError("No track currently playing")
        )

        result = runner.invoke(main, ["queue", "track", "audio"])

        assert result.exit_code == 1
        assert "No track currently playing" in result.output

    def test_audio_machine_readable_suppresses_errors(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """Test audio command with --machine-readable flag suppresses errors."""
        mock_client = mocker.Mock()
        _attach_property(
            mock_client, "state", side_effect=VolumioConnectionError("Connection failed")
        )

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["--machine-readable", "queue", "track", "audio"])

        assert result.exit_code == 1
        assert result.output == ""

    def test_audio_with_minimal_metadata(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """Test audio command with minimal metadata."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={"status": "play"})

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        # The MPD client's get_track_uri() would replace localhost with volumio.local (default host)
        self._mock_mpd_client(mocker, track_uri="http://volumio.local:8000/music/test.flac")

        result = runner.invoke(main, ["queue", "track", "audio"])

        assert result.exit_code == 0
        # Should still print the URI even without metadata fields
        assert "http://volumio.local:8000/music/test.flac" in result.output

    def test_audio_mpd_generic_exception(self, runner: CliRunner, mocker: MockerFixture):
        """Test audio command with generic MPD exception after connection."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={"title": "Test Song"})

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        self._mock_mpd_client(
            mocker,
            side_effect=VolumioConnectionError("MPD error: MPD protocol error")
        )

        result = runner.invoke(main, ["queue", "track", "audio"])

        assert result.exit_code == 1
        assert "MPD error" in result.output

    def test_audio_mpd_exception_with_machine_readable(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """Test audio command with generic MPD exception and --machine-readable flag."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={"title": "Test Song"})

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        self._mock_mpd_client(
            mocker,
            side_effect=VolumioConnectionError("MPD error: Unexpected MPD response")
        )

        result = runner.invoke(main, ["--machine-readable", "queue", "track", "audio"])

        assert result.exit_code == 1
        # Error should be suppressed in machine-readable mode
        assert result.output == ""

    def test_audio_with_output_directory(self, runner: CliRunner, mocker: MockerFixture):
        """Test audio command with -d flag (filename taken from the URI)."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={"title": "Test Song"})

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        self._mock_mpd_client(mocker, track_uri="http://volumio.local:8000/music/test.flac")

        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"fake", b"audio", b"data"]
        mock_get = mocker.patch(
            "volumito.cli.click_helpers.requests.get", return_value=mock_response
        )
        mock_open = mocker.patch("builtins.open", mocker.mock_open(read_data=b"fake audio data"))
        mocker.patch("volumito.cli.click_helpers.os.makedirs")

        result = runner.invoke(
            main,
            [
                "track",
                "audio",
                "-d",
                "/tmp/music",
                "--no-create-download-manifest",
                "--no-add-cover-and-metadata",
            ],
        )

        assert result.exit_code == 0
        assert "successfully downloaded" in result.output
        mock_get.assert_called_once()
        # Filename derived from the URI basename
        mock_open.assert_any_call(os.path.join("/tmp/music", "test.flac"), "wb")

    def test_audio_output_directory_with_template(self, runner: CliRunner, mocker: MockerFixture):
        """Test audio -d with a -f/--file-name-template."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={"position": 0, "title": "La rondine"})

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        self._mock_mpd_client(mocker, track_uri="http://volumio.local:8000/music/test.flac")

        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"data"]
        mocker.patch("volumito.cli.click_helpers.requests.get", return_value=mock_response)
        mock_open = mocker.patch("builtins.open", mocker.mock_open(read_data=b"fake audio data"))
        mocker.patch("volumito.cli.click_helpers.os.makedirs")

        result = runner.invoke(
            main,
            [
                "track",
                "audio",
                "-d",
                "/tmp/music",
                "-f",
                "{position:03d}_{title}.{extension}",
                "--no-create-download-manifest",
                "--no-add-cover-and-metadata",
            ],
        )

        assert result.exit_code == 0
        mock_open.assert_any_call(os.path.join("/tmp/music", "001_La_rondine.flac"), "wb")

    def test_audio_output_directory_bad_template(self, runner: CliRunner, mocker: MockerFixture):
        """Test audio -d with an invalid -f template errors out."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={"title": "Test Song"})

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        self._mock_mpd_client(mocker, track_uri="http://volumio.local:8000/music/test.flac")

        result = runner.invoke(
            main, ["queue", "track", "audio", "-d", "/tmp/music", "-f", "{unknown}"]
        )

        assert result.exit_code == 2
        assert "Invalid --file-name-template" in result.output

    def test_audio_output_file_and_dir_mutually_exclusive(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """Test audio command rejects combining -o and -d."""
        result = runner.invoke(main, ["queue", "track", "audio", "-o", "/tmp/a.flac", "-d", "/tmp"])

        assert result.exit_code == 2
        assert "mutually exclusive" in result.output

    def test_audio_no_overwrite_existing_file(self, runner: CliRunner, mocker: MockerFixture):
        """Test audio command refuses to overwrite an existing file by default."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={"title": "Test Song"})

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        self._mock_mpd_client(mocker, track_uri="http://volumio.local:8000/music/test.flac")
        # Only the destination path "exists" (a blanket True would corrupt gettext lookups)
        mocker.patch(
            "volumito.cli.click_helpers.os.path.exists",
            side_effect=lambda p: p == "/tmp/track.flac",
        )

        mock_get = mocker.patch("volumito.cli.click_helpers.requests.get")
        mock_open = mocker.patch("builtins.open", mocker.mock_open())

        result = runner.invoke(main, ["queue", "track", "audio", "-o", "/tmp/track.flac"])

        assert result.exit_code == 1
        assert 'File already exists: "/tmp/track.flac"' in result.output
        # Nothing is downloaded or written
        mock_get.assert_not_called()
        mock_open.assert_not_called()

    def test_audio_overwrite_existing_file(self, runner: CliRunner, mocker: MockerFixture):
        """Test audio command overwrites an existing file with --overwrite-existing-files."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={"title": "Test Song"})

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        self._mock_mpd_client(mocker, track_uri="http://volumio.local:8000/music/test.flac")
        mocker.patch(
            "volumito.cli.click_helpers.os.path.exists",
            side_effect=lambda p: p == "/tmp/track.flac",
        )

        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"fake", b"audio", b"data"]
        mocker.patch("volumito.cli.click_helpers.requests.get", return_value=mock_response)
        mock_open = mocker.patch("builtins.open", mocker.mock_open())

        result = runner.invoke(
            main,
            [
                "track",
                "audio",
                "-o",
                "/tmp/track.flac",
                "--overwrite-existing-files",
                "--no-create-download-manifest",
                "--no-add-cover-and-metadata",
            ],
        )

        assert result.exit_code == 0
        assert "successfully downloaded" in result.output
        mock_open.assert_called_once_with("/tmp/track.flac", "wb")

    def test_audio_with_output_file_explicit_path(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """Test audio command with -o and explicit file path."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={
            "title": "Test Song",
            "artist": "Test Artist",
        })

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        self._mock_mpd_client(mocker, track_uri="http://volumio.local:8000/music/test.flac")

        # Mock requests.get
        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"fake", b"audio", b"data"]
        mock_get = mocker.patch(
            "volumito.cli.click_helpers.requests.get", return_value=mock_response
        )

        # Mock file operations
        mock_open = mocker.patch("builtins.open", mocker.mock_open())

        result = runner.invoke(
            main,
            [
                "track",
                "audio",
                "-o",
                "/tmp/my_track.flac",
                "--no-create-download-manifest",
                "--no-add-cover-and-metadata",
            ],
        )

        assert result.exit_code == 0
        assert "http://volumio.local:8000/music/test.flac" in result.output
        assert "successfully downloaded" in result.output
        mock_get.assert_called_once()
        mock_open.assert_called_once_with("/tmp/my_track.flac", "wb")

    def test_audio_of_a_file_of_the_host_library(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """A URI without a scheme is copied from the Volumio host over SCP."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={"title": "Test Song"})
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        self._mock_mpd_client(mocker, track_uri="INTERNAL/music/album/01-track.flac")
        copy = mocker.patch("volumito.cli.click_helpers.copy_from_host")
        mock_get = mocker.patch("volumito.cli.click_helpers.requests.get")
        # The download manifest is really written, so the destination must be a
        # test-managed directory
        destination = str(tmp_path / "track.flac")

        result = runner.invoke(main, ["queue", "track", "audio", "-o", destination])

        assert result.exit_code == 0
        assert f'successfully downloaded to "{destination}"' in result.output
        mock_get.assert_not_called()
        assert copy.call_args.args[1:3] == (
            "/mnt/INTERNAL/music/album/01-track.flac",
            destination,
        )
        assert copy.call_args.args[0].ssh_username == "volumio"

    def test_audio_of_a_file_of_the_host_library_keeps_its_name(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """A copied file keeps the name it has on the host, and is not retagged."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={"title": "8 - Luiza"})
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        self._mock_mpd_client(mocker, track_uri="INTERNAL/music/elegy/08-Luiza.mp3")
        copy = mocker.patch("volumito.cli.click_helpers.copy_from_host")
        embed = mocker.patch("volumito.cli.volumito.embed_track_tags")

        result = runner.invoke(main, ["--verbose", "queue", "track", "audio", "-d", str(tmp_path)])

        assert result.exit_code == 0
        assert copy.call_args.args[2] == str(tmp_path / "08-Luiza.mp3")
        embed.assert_not_called()
        assert (
            "Not embedding the album art and the metadata, to preserve the file being copied"
            in result.output
        )

    def test_audio_of_a_file_of_the_host_library_renamed(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """--allow-local-file-rename names the copy after the template."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={"title": "8 - Luiza"})
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        self._mock_mpd_client(mocker, track_uri="INTERNAL/music/elegy/08-Luiza.mp3")
        copy = mocker.patch("volumito.cli.click_helpers.copy_from_host")
        embed = mocker.patch("volumito.cli.volumito.embed_track_tags")

        result = runner.invoke(
            main,
            [
                "track",
                "audio",
                "-d",
                str(tmp_path),
                "--allow-local-file-rename",
                "-f",
                "{title}.{extension}",
            ],
        )

        assert result.exit_code == 0
        assert copy.call_args.args[2] == str(tmp_path / "8_-_Luiza.mp3")
        # The file is still left untouched: only its name follows the template
        embed.assert_not_called()

    def test_audio_fetched_over_http_is_still_tagged(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """A track fetched over HTTP keeps the templated name and the embedded tags."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={"title": "Test Song"})
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        self._mock_mpd_client(mocker, track_uri="http://volumio.local:8000/music/test.flac")
        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"audio"]
        mocker.patch("volumito.cli.click_helpers.requests.get", return_value=mock_response)
        embed = mocker.patch("volumito.cli.volumito.embed_track_tags")

        result = runner.invoke(
            main, ["queue", "track", "audio", "-d", str(tmp_path), "-f", "{title}.{extension}"]
        )

        assert result.exit_code == 0
        assert (tmp_path / "Test_Song.flac").exists()
        embed.assert_called_once()

    def test_audio_renamed_after_the_format_of_its_content(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """A track served as MP3 under a ".flac" name is saved, tagged, as ".mp3"."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={"title": "Test Song"})
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        self._mock_mpd_client(mocker, track_uri="http://volumio.local:8000/music/test.flac")
        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [_MP3_CONTENT]
        mocker.patch("volumito.cli.click_helpers.requests.get", return_value=mock_response)
        embed = mocker.patch("volumito.cli.volumito.embed_track_tags")

        result = runner.invoke(
            main, ["queue", "track", "audio", "-d", str(tmp_path), "-f", "{title}.{extension}"]
        )

        assert result.exit_code == 0
        assert (tmp_path / "Test_Song.mp3").read_bytes() == _MP3_CONTENT
        assert not (tmp_path / "Test_Song.flac").exists()
        assert (tmp_path / "Test_Song.mp3.json").exists()
        assert f'successfully downloaded to "{tmp_path / "Test_Song.mp3"}"' in result.output
        assert embed.call_args.args[0] == str(tmp_path / "Test_Song.mp3")

    def test_audio_output_file_keeps_the_name_asked_for(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """An explicit -o path is kept, whatever the format of the content."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={"title": "Test Song"})
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        self._mock_mpd_client(mocker, track_uri="http://volumio.local:8000/music/test.flac")
        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [_MP3_CONTENT]
        mocker.patch("volumito.cli.click_helpers.requests.get", return_value=mock_response)
        mocker.patch("volumito.cli.volumito.embed_track_tags")
        destination = tmp_path / "song.flac"

        result = runner.invoke(
            main,
            ["queue", "track", "audio", "-o", str(destination), "--no-create-download-manifest"],
        )

        assert result.exit_code == 0
        assert destination.read_bytes() == _MP3_CONTENT
        assert not (tmp_path / "song.mp3").exists()

    def test_audio_of_a_file_of_the_host_library_failing(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """A failed copy exits 1, reporting what went wrong."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={"title": "Test Song"})
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        self._mock_mpd_client(mocker, track_uri="INTERNAL/music/album/01-track.flac")
        mocker.patch(
            "volumito.cli.click_helpers.copy_from_host",
            side_effect=VolumioSCPError("Authentication failed"),
        )

        result = runner.invoke(
            main, ["queue", "track", "audio", "-o", str(tmp_path / "track.flac")]
        )

        assert result.exit_code == 1
        assert "Download error: Authentication failed" in result.output

    def test_audio_with_the_ssh_options(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """The SSH options reach the copy through the host configuration."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={"title": "Test Song"})
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        self._mock_mpd_client(mocker, track_uri="INTERNAL/music/album/01-track.flac")
        copy = mocker.patch("volumito.cli.click_helpers.copy_from_host")

        result = runner.invoke(
            main,
            [
                "--ssh-password",
                "hunter2",
                "--ssh-port",
                "2222",
                "--ssh-username",
                "pi",
                "track",
                "audio",
                "-o",
                # The download manifest is really written, so the destination must
                # be a test-managed directory
                str(tmp_path / "track.flac"),
            ],
        )

        assert result.exit_code == 0
        host_configuration = copy.call_args.args[0]
        assert host_configuration.ssh_password == "hunter2"
        assert host_configuration.ssh_port == 2222
        assert host_configuration.ssh_username == "pi"

    def test_audio_with_output_file_verbose(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """Test audio command with --verbose and -o option."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={
            "title": "Test Song",
        })

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        self._mock_mpd_client(mocker, track_uri="http://volumio.local:8000/music/test.flac")

        # Mock requests.get
        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"fake", b"audio", b"data"]
        mocker.patch("volumito.cli.click_helpers.requests.get", return_value=mock_response)

        # Mock file operations
        mocker.patch("builtins.open", mocker.mock_open())

        result = runner.invoke(
            main, ["--verbose", "queue", "track", "audio", "-o", "/tmp/track.flac"]
        )

        assert result.exit_code == 0
        assert "Connecting to" in result.output
        assert 'Downloading track to "/tmp/track.flac"' in result.output
        assert "successfully downloaded" in result.output

    def test_audio_file_write_error(self, runner: CliRunner, mocker: MockerFixture):
        """Test audio command with file write error."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={
            "title": "Test Song",
        })

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        self._mock_mpd_client(mocker, track_uri="http://volumio.local:8000/music/test.flac")

        # Mock requests.get
        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"fake", b"data"]
        mocker.patch("volumito.cli.click_helpers.requests.get", return_value=mock_response)

        # Mock open to raise OSError
        mocker.patch("builtins.open", side_effect=OSError("Permission denied"))

        result = runner.invoke(main, ["queue", "track", "audio", "-o", "/tmp/track.flac"])

        assert result.exit_code == 1
        assert "File write error" in result.output

    def test_audio_download_error(self, runner: CliRunner, mocker: MockerFixture):
        """Test audio command with download error."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={
            "title": "Test Song",
        })

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        self._mock_mpd_client(mocker, track_uri="http://volumio.local:8000/music/test.flac")

        # Mock requests.get to raise an exception
        mocker.patch(
            "volumito.cli.click_helpers.requests.get",
            side_effect=requests.exceptions.RequestException("Download failed"),
        )

        result = runner.invoke(main, ["queue", "track", "audio", "-o", "/tmp/track.flac"])

        assert result.exit_code == 1
        assert "Download error" in result.output

    def test_albumart_help(self, runner: CliRunner):
        """Test albumart command with --help."""
        result = runner.invoke(main, ["queue", "track", "albumart", "--help"])

        assert result.exit_code == 0
        assert "albumart" in result.output.lower()
        assert "album art" in result.output.lower()

    def test_albumart_success_default(self, runner: CliRunner, mocker: MockerFixture):
        """Test successful albumart command with default options."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={
            "albumart": "/albumart?path=image.jpg",
        })

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["queue", "track", "albumart"])

        assert result.exit_code == 0
        assert "http://volumio.local:3000/albumart?path=image.jpg" in result.output
        # Without --machine-readable, the URI is printed bare (not quoted)
        assert '"http://volumio.local:3000/albumart?path=image.jpg"' not in result.output

    def test_albumart_with_custom_host(self, runner: CliRunner, mocker: MockerFixture):
        """Test albumart command with custom host."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={
            "albumart": "/albumart?path=image.jpg",
        })

        mock_client_class = mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["--host", "192.168.1.100", "queue", "track", "albumart"])

        assert result.exit_code == 0
        host_configuration = mock_client_class.call_args[0][0]
        assert host_configuration.host == "192.168.1.100"
        assert "192.168.1.100" in result.output

    def test_albumart_with_absolute_uri(self, runner: CliRunner, mocker: MockerFixture):
        """Test albumart command with absolute URI."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={
            "albumart": "http://example.com/albumart.jpg",
        })

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["queue", "track", "albumart"])

        assert result.exit_code == 0
        assert "http://example.com/albumart.jpg" in result.output

    def test_albumart_with_relative_uri(self, runner: CliRunner, mocker: MockerFixture):
        """Test albumart command with relative URI path."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={
            "albumart": "/albumart",
        })

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["queue", "track", "albumart"])

        assert result.exit_code == 0
        # Should prepend scheme://host:port
        assert "http://volumio.local:3000/albumart" in result.output

    def test_albumart_with_output_file(self, runner: CliRunner, mocker: MockerFixture):
        """Test albumart command with -o/--output-file option."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={
            "albumart": "http://example.com/albumart.jpg",
        })

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        # Mock requests.get
        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"fake", b"image", b"data"]
        mock_get = mocker.patch(
            "volumito.cli.click_helpers.requests.get", return_value=mock_response
        )

        # Mock file operations
        mock_open = mocker.patch("builtins.open", mocker.mock_open())

        result = runner.invoke(
            main,
            ["queue", "track", "albumart", "-o", "/tmp/albumart.jpg",
             "--no-create-download-manifest"],
        )

        assert result.exit_code == 0
        assert "http://example.com/albumart.jpg" in result.output
        assert "successfully downloaded" in result.output
        mock_get.assert_called_once()
        mock_open.assert_called_once_with("/tmp/albumart.jpg", "wb")

    def test_albumart_missing_albumart(self, runner: CliRunner, mocker: MockerFixture):
        """Test albumart command when albumart field is missing."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={
            "title": "Test Song",
        })

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["queue", "track", "albumart"])

        assert result.exit_code == 1
        assert "No album art URI found" in result.output

    def test_albumart_with_verbose(self, runner: CliRunner, mocker: MockerFixture):
        """Test albumart command with --verbose flag."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={
            "albumart": "http://example.com/albumart.jpg",
        })

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["--verbose", "queue", "track", "albumart"])

        assert result.exit_code == 0
        assert "Connecting to" in result.output
        assert "Successfully retrieved state" in result.output
        assert "Album art URI:" in result.output

    def test_albumart_with_machine_readable(self, runner: CliRunner, mocker: MockerFixture):
        """Test albumart command with --machine-readable flag."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={
            "albumart": "http://example.com/albumart.jpg",
        })

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["--machine-readable", "queue", "track", "albumart"])

        assert result.exit_code == 0
        # In machine-readable mode, only the quoted URI should be printed
        assert result.output.strip() == '"http://example.com/albumart.jpg"'
        assert "Connecting" not in result.output

    def test_albumart_connection_error(self, runner: CliRunner, mocker: MockerFixture):
        """Test albumart command with connection error."""
        mock_client = mocker.Mock()
        _attach_property(
            mock_client, "state", side_effect=VolumioConnectionError("Connection failed")
        )

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["queue", "track", "albumart"])

        assert result.exit_code == 1
        assert "Connection error" in result.output

    def test_albumart_api_error(self, runner: CliRunner, mocker: MockerFixture):
        """Test albumart command with API error."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", side_effect=VolumioAPIError("API error"))

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["queue", "track", "albumart"])

        assert result.exit_code == 1
        assert "API error" in result.output

    def test_albumart_download_error(self, runner: CliRunner, mocker: MockerFixture):
        """Test albumart command with download error."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={
            "albumart": "http://example.com/albumart.jpg",
        })

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        # Mock requests.get to raise an exception
        mocker.patch(
            "volumito.cli.click_helpers.requests.get",
            side_effect=requests.exceptions.RequestException("Download failed"),
        )

        result = runner.invoke(main, ["queue", "track", "albumart", "-o", "/tmp/albumart.jpg"])

        assert result.exit_code == 1
        assert "Download error" in result.output

    def test_albumart_file_write_error(self, runner: CliRunner, mocker: MockerFixture):
        """Test albumart command with file write error."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={
            "albumart": "http://example.com/albumart.jpg",
        })

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        # Mock requests.get
        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"fake", b"data"]
        mocker.patch("volumito.cli.click_helpers.requests.get", return_value=mock_response)

        # Mock open to raise OSError
        mocker.patch("builtins.open", side_effect=OSError("Permission denied"))

        result = runner.invoke(main, ["queue", "track", "albumart", "-o", "/tmp/albumart.jpg"])

        assert result.exit_code == 1
        assert "File write error" in result.output

    def test_albumart_machine_readable_suppresses_errors(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """Test albumart command with --machine-readable flag suppresses errors."""
        mock_client = mocker.Mock()
        _attach_property(
            mock_client, "state", side_effect=VolumioConnectionError("Connection failed")
        )

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["--machine-readable", "queue", "track", "albumart"])

        assert result.exit_code == 1
        # Error should be suppressed in machine-readable mode
        assert result.output == ""

    def test_albumart_with_output_directory_query_param(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """Test albumart -d flag: filename from the URI 'path' query parameter."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={
            "albumart": "/albumart?path=/mnt/USB/Album/cover.png",
        })

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"fake", b"image", b"data"]
        mock_get = mocker.patch(
            "volumito.cli.click_helpers.requests.get", return_value=mock_response
        )
        mock_open = mocker.patch("builtins.open", mocker.mock_open())
        mocker.patch("volumito.cli.click_helpers.os.makedirs")

        result = runner.invoke(
            main,
            ["queue", "track", "albumart", "-d", "/tmp/covers", "--no-create-download-manifest"],
        )

        assert result.exit_code == 0
        assert "successfully downloaded" in result.output
        mock_get.assert_called_once()
        mock_open.assert_called_once_with(os.path.join("/tmp/covers", "cover.png"), "wb")

    def test_albumart_with_output_directory_direct_path(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """Test albumart -d flag: filename from a direct URI path."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={
            "albumart": "http://example.com/images/cover.jpg",
        })

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"fake", b"image", b"data"]
        mocker.patch("volumito.cli.click_helpers.requests.get", return_value=mock_response)
        mock_open = mocker.patch("builtins.open", mocker.mock_open())
        mocker.patch("volumito.cli.click_helpers.os.makedirs")

        result = runner.invoke(
            main,
            ["queue", "track", "albumart", "-d", "/tmp/covers", "--no-create-download-manifest"],
        )

        assert result.exit_code == 0
        mock_open.assert_called_once_with(os.path.join("/tmp/covers", "cover.jpg"), "wb")

    def test_albumart_output_directory_timestamp_placeholder(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """The {timestamp} placeholder in -d expands and the directory is created."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={
            "albumart": "http://example.com/images/cover.jpg",
        })

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"fake", b"image", b"data"]
        mocker.patch("volumito.cli.click_helpers.requests.get", return_value=mock_response)
        mock_datetime = mocker.patch("volumito.cli.click_helpers.datetime")
        mock_datetime.now.return_value.strftime.return_value = "20260101000000"

        result = runner.invoke(
            main,
            [
                "track",
                "albumart",
                "-d",
                os.path.join(str(tmp_path), "{timestamp}"),
                "--no-create-download-manifest",
            ],
        )

        assert result.exit_code == 0
        cover = tmp_path / "20260101000000" / "cover.jpg"
        assert cover.read_bytes() == b"fakeimagedata"

    def test_albumart_output_directory_with_template(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """Test albumart -d with a -f/--file-name-template."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={
            "position": 0,
            "title": "La rondine",
            "albumart": "http://example.com/images/cover.jpg",
        })

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"data"]
        mocker.patch("volumito.cli.click_helpers.requests.get", return_value=mock_response)
        mock_open = mocker.patch("builtins.open", mocker.mock_open())
        mocker.patch("volumito.cli.click_helpers.os.makedirs")

        result = runner.invoke(
            main,
            [
                "track",
                "albumart",
                "-d",
                "/tmp/covers",
                "-f",
                "{position:03d}_{title}.{extension}",
                "--no-create-download-manifest",
            ],
        )

        assert result.exit_code == 0
        # Extension derived from the album art URI (cover.jpg -> jpg)
        mock_open.assert_called_once_with(os.path.join("/tmp/covers", "001_La_rondine.jpg"), "wb")

    def test_albumart_output_directory_template_default_extension(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """Test albumart {extension} defaults to jpg when the URI has no extension."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={
            "title": "La rondine",
            "albumart": "http://example.com/albumart",
        })

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"data"]
        mocker.patch("volumito.cli.click_helpers.requests.get", return_value=mock_response)
        mock_open = mocker.patch("builtins.open", mocker.mock_open())
        mocker.patch("volumito.cli.click_helpers.os.makedirs")

        result = runner.invoke(
            main,
            [
                "track",
                "albumart",
                "-d",
                "/tmp/covers",
                "-f",
                "{title}.{extension}",
                "--no-create-download-manifest",
            ],
        )

        assert result.exit_code == 0
        mock_open.assert_called_once_with(os.path.join("/tmp/covers", "La_rondine.jpg"), "wb")

    def test_albumart_replace_characters_options(self, runner: CliRunner, mocker: MockerFixture):
        """The replace-characters options control the file-name substitution."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={
            "title": "La rondine",
            "albumart": "http://example.com/images/cover.jpg",
        })
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"data"]
        mocker.patch("volumito.cli.click_helpers.requests.get", return_value=mock_response)
        mock_open = mocker.patch("builtins.open", mocker.mock_open())
        mocker.patch("volumito.cli.click_helpers.os.makedirs")

        result = runner.invoke(
            main,
            [
                "track",
                "albumart",
                "-d",
                "/tmp/covers",
                "-f",
                "{title}.{extension}",
                "--replace-characters-in-file-names",
                " ",
                "--replace-characters-in-file-names-with",
                "-",
                "--no-create-download-manifest",
            ],
        )

        assert result.exit_code == 0
        mock_open.assert_called_once_with(os.path.join("/tmp/covers", "La-rondine.jpg"), "wb")

    def test_albumart_traversal_title_is_neutralized(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """A title with path separators cannot make the download leave the directory."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={
            "title": "../x",
            "albumart": "http://example.com/images/cover.jpg",
        })
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"data"]
        mocker.patch("volumito.cli.click_helpers.requests.get", return_value=mock_response)
        mock_open = mocker.patch("builtins.open", mocker.mock_open())
        mocker.patch("volumito.cli.click_helpers.os.makedirs")

        result = runner.invoke(
            main,
            [
                "track",
                "albumart",
                "-d",
                "/tmp/covers",
                "-f",
                "{title}.{extension}",
                "--no-create-download-manifest",
            ],
        )

        assert result.exit_code == 0
        # "../x" is sanitized to ".._x", and the leading dots are stripped
        mock_open.assert_called_once_with(os.path.join("/tmp/covers", "_x.jpg"), "wb")

    def test_albumart_output_directory_bad_template(self, runner: CliRunner, mocker: MockerFixture):
        """Test albumart -d with an invalid -f template errors out."""
        mock_client = mocker.Mock()
        _attach_property(
            mock_client, "state", return_value={"albumart": "http://example.com/cover.jpg"}
        )

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(
            main, ["queue", "track", "albumart", "-d", "/tmp/covers", "-f", "{unknown}"]
        )

        assert result.exit_code == 2
        assert "Invalid --file-name-template" in result.output

    def test_albumart_output_directory_no_filename(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """Test albumart -d flag errors when no file name can be derived from the URI."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={
            "albumart": "http://example.com/",
        })

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["queue", "track", "albumart", "-d", "/tmp/covers"])

        assert result.exit_code == 1
        assert "Cannot determine a file name" in result.output

    def test_albumart_output_file_and_dir_mutually_exclusive(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """Test albumart command rejects combining -o and -d."""
        result = runner.invoke(
            main, ["queue", "track", "albumart", "-o", "/tmp/a.jpg", "-d", "/tmp"]
        )

        assert result.exit_code == 2
        assert "mutually exclusive" in result.output

    def test_albumart_no_overwrite_existing_file(self, runner: CliRunner, mocker: MockerFixture):
        """Test albumart command refuses to overwrite an existing file by default."""
        mock_client = mocker.Mock()
        _attach_property(
            mock_client, "state", return_value={"albumart": "http://example.com/cover.jpg"}
        )

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        # Only the destination path "exists" (a blanket True would corrupt gettext lookups)
        mocker.patch(
            "volumito.cli.click_helpers.os.path.exists",
            side_effect=lambda p: p == "/tmp/cover.jpg",
        )

        mock_get = mocker.patch("volumito.cli.click_helpers.requests.get")
        mock_open = mocker.patch("builtins.open", mocker.mock_open())

        result = runner.invoke(main, ["queue", "track", "albumart", "-o", "/tmp/cover.jpg"])

        assert result.exit_code == 1
        assert 'File already exists: "/tmp/cover.jpg"' in result.output
        # Nothing is downloaded or written
        mock_get.assert_not_called()
        mock_open.assert_not_called()

    def test_albumart_overwrite_existing_file(self, runner: CliRunner, mocker: MockerFixture):
        """Test albumart command overwrites an existing file with --overwrite-existing-files."""
        mock_client = mocker.Mock()
        _attach_property(
            mock_client, "state", return_value={"albumart": "http://example.com/cover.jpg"}
        )

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        mocker.patch(
            "volumito.cli.click_helpers.os.path.exists",
            side_effect=lambda p: p == "/tmp/cover.jpg",
        )

        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"fake", b"image", b"data"]
        mocker.patch("volumito.cli.click_helpers.requests.get", return_value=mock_response)
        mock_open = mocker.patch("builtins.open", mocker.mock_open())

        result = runner.invoke(
            main,
            [
                "track",
                "albumart",
                "-o",
                "/tmp/cover.jpg",
                "--overwrite-existing-files",
                "--no-create-download-manifest",
            ],
        )

        assert result.exit_code == 0
        assert "successfully downloaded" in result.output
        mock_open.assert_called_once_with("/tmp/cover.jpg", "wb")

    def test_audio_create_download_manifest(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """track audio writes a sidecar JSON manifest next to the downloaded file."""
        state = {"title": "Test Song", "artist": "X", "status": "play"}
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value=state)
        mocker.patch("volumito.cli.click_helpers.VolumioRESTAPIClient", return_value=mock_client)
        self._mock_mpd_client(mocker, track_uri="http://volumio.local:8000/music/test.flac")

        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"fake", b"audio"]
        mocker.patch("volumito.cli.click_helpers.requests.get", return_value=mock_response)

        out = tmp_path / "song.flac"
        # --verbose exercises the "Manifest written to ..." message branch
        result = runner.invoke(
            main,
            [
                "--verbose",
                "track",
                "audio",
                "-o",
                str(out),
                "--create-download-manifest",
                "--no-add-cover-and-metadata",
            ],
        )

        assert result.exit_code == 0
        assert out.read_bytes() == b"fakeaudio"
        assert "Manifest written to" in result.output

        manifest_path = tmp_path / "song.flac.json"
        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["entity"] == "track"
        assert manifest["kind"] == "audio"
        assert manifest["output_file_name"] == "song.flac"
        assert manifest["output_file_path"] == str(out)
        assert manifest["source_uri"] == "http://volumio.local:8000/music/test.flac"
        assert manifest["state"] == state
        assert manifest["volumio_host"] == "http://volumio.local:3000"
        assert manifest["volumito_version"] == __version__
        assert manifest["download_date"]
        # The audio manifest records the add-cover-and-metadata choice (here disabled)
        assert manifest["add_cover_and_metadata"] is False
        # Keys are serialized in lexicographic order
        assert list(manifest.keys()) == sorted(manifest.keys())

    def test_albumart_create_download_manifest(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """track albumart writes a manifest with kind 'albumart' (default on, non-verbose)."""
        state = {"albumart": "http://example.com/images/cover.jpg", "status": "play"}
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value=state)
        mocker.patch("volumito.cli.click_helpers.VolumioRESTAPIClient", return_value=mock_client)

        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"img"]
        mocker.patch("volumito.cli.click_helpers.requests.get", return_value=mock_response)

        out = tmp_path / "cover.jpg"
        # No explicit flag: the manifest is created because the default is on
        result = runner.invoke(main, ["queue", "track", "albumart", "-o", str(out)])

        assert result.exit_code == 0
        assert "Manifest written to" not in result.output

        manifest_path = tmp_path / "cover.jpg.json"
        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["entity"] == "track"
        assert manifest["kind"] == "albumart"
        assert manifest["output_file_name"] == "cover.jpg"
        assert manifest["output_file_path"] == str(out)
        assert manifest["source_uri"] == "http://example.com/images/cover.jpg"
        assert manifest["state"] == state
        # The albumart command has no such option, so the key is absent
        assert "add_cover_and_metadata" not in manifest

    def test_audio_no_create_download_manifest(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """--no-create-download-manifest suppresses the sidecar JSON file."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={"title": "Test Song"})
        mocker.patch("volumito.cli.click_helpers.VolumioRESTAPIClient", return_value=mock_client)
        self._mock_mpd_client(mocker, track_uri="http://volumio.local:8000/music/test.flac")

        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"fakeaudio"]
        mocker.patch("volumito.cli.click_helpers.requests.get", return_value=mock_response)

        out = tmp_path / "song.flac"
        result = runner.invoke(
            main,
            [
                "track",
                "audio",
                "-o",
                str(out),
                "--no-create-download-manifest",
                "--no-add-cover-and-metadata",
            ],
        )

        assert result.exit_code == 0
        assert out.exists()
        assert not (tmp_path / "song.flac.json").exists()

    def _mock_audio_download(self, mocker: MockerFixture, state: dict, chunks=(b"data",)):
        """Mock the REST client (state), MPD (URI), and requests.get for an audio download."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value=state)
        mocker.patch("volumito.cli.click_helpers.VolumioRESTAPIClient", return_value=mock_client)
        self._mock_mpd_client(mocker, track_uri="http://volumio.local:8000/music/test.flac")
        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = list(chunks)
        return mocker.patch("volumito.cli.click_helpers.requests.get", return_value=mock_response)

    def test_audio_embeds_metadata_and_cover(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """By default, track audio embeds the metadata and cover into the download."""
        state = {
            "title": "T",
            "artist": "A",
            "album": "Al",
            "albumartist": "AA",
            "position": 1,
            "albumart": "http://example.com/cover.jpg",
            "status": "play",
        }
        self._mock_audio_download(mocker, state, chunks=(b"cover-bytes",))
        embed = mocker.patch("volumito.cli.click_helpers.embed_metadata_and_cover")

        out = tmp_path / "song.flac"
        result = runner.invoke(
            main,
            ["--verbose", "queue", "track", "audio", "-o", str(out),
             "--no-create-download-manifest"],
        )

        assert result.exit_code == 0
        assert "Embedded metadata and cover" in result.output
        embed.assert_called_once_with(
            str(out),
            title="T",
            artist="A",
            album="Al",
            albumartist="AA",
            track_number=2,
            cover=b"cover-bytes",
        )

    def test_audio_no_add_cover_and_metadata_skips_embedding(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """--no-add-cover-and-metadata leaves the downloaded file untagged."""
        self._mock_audio_download(mocker, {"title": "T"})
        embed = mocker.patch("volumito.cli.click_helpers.embed_metadata_and_cover")

        out = tmp_path / "song.flac"
        result = runner.invoke(
            main,
            [
                "track",
                "audio",
                "-o",
                str(out),
                "--no-add-cover-and-metadata",
                "--no-create-download-manifest",
            ],
        )

        assert result.exit_code == 0
        embed.assert_not_called()

    def test_audio_embed_without_albumart_has_no_cover(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """With no album art in the state, the metadata is embedded without a cover."""
        self._mock_audio_download(mocker, {"title": "T", "position": 0})
        embed = mocker.patch("volumito.cli.click_helpers.embed_metadata_and_cover")

        out = tmp_path / "song.flac"
        result = runner.invoke(
            main, ["queue", "track", "audio", "-o", str(out), "--no-create-download-manifest"]
        )

        assert result.exit_code == 0
        embed.assert_called_once_with(
            str(out),
            title="T",
            artist=None,
            album=None,
            albumartist=None,
            track_number=1,
            cover=None,
        )

    def test_audio_embed_cover_fetch_failure_warns(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """A failure fetching the cover warns and embeds the metadata without a cover."""
        state = {"title": "T", "albumart": "http://example.com/cover.jpg"}
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value=state)
        mocker.patch("volumito.cli.click_helpers.VolumioRESTAPIClient", return_value=mock_client)
        self._mock_mpd_client(mocker, track_uri="http://volumio.local:8000/music/test.flac")

        download_response = mocker.Mock()
        download_response.iter_content.return_value = [b"data"]
        mocker.patch(
            "volumito.cli.click_helpers.requests.get",
            side_effect=[download_response, requests.exceptions.ConnectionError("boom")],
        )
        embed = mocker.patch("volumito.cli.click_helpers.embed_metadata_and_cover")

        out = tmp_path / "song.flac"
        result = runner.invoke(
            main, ["queue", "track", "audio", "-o", str(out), "--no-create-download-manifest"]
        )

        assert result.exit_code == 0
        assert "Cannot fetch cover art" in result.output
        assert embed.call_args.kwargs["cover"] is None

    def test_audio_embed_unsupported_format_warns(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """An unsupported audio format warns but still exits 0 with the file downloaded."""
        self._mock_audio_download(mocker, {"title": "T"})

        out = tmp_path / "song.ogg"
        result = runner.invoke(
            main, ["queue", "track", "audio", "-o", str(out), "--no-create-download-manifest"]
        )

        assert result.exit_code == 0
        assert "unsupported format" in result.output
        assert out.exists()

    def test_audio_embed_generic_error_warns(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """A tagging error warns but still exits 0."""
        self._mock_audio_download(mocker, {"title": "T"})
        mocker.patch(
            "volumito.cli.click_helpers.embed_metadata_and_cover",
            side_effect=ValueError("boom"),
        )

        out = tmp_path / "song.flac"
        result = runner.invoke(
            main, ["queue", "track", "audio", "-o", str(out), "--no-create-download-manifest"]
        )

        assert result.exit_code == 0
        assert "Cannot embed metadata into" in result.output
        assert "boom" in result.output

    def test_audio_embed_track_number_follows_indexing(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """The embedded track number honours --position-starting-at-zero."""
        self._mock_audio_download(mocker, {"title": "T", "position": 1})
        embed = mocker.patch("volumito.cli.click_helpers.embed_metadata_and_cover")

        out = tmp_path / "song.flac"
        result = runner.invoke(
            main,
            [
                "--position-starting-at-zero",
                "track",
                "audio",
                "-o",
                str(out),
                "--no-create-download-manifest",
            ],
        )

        assert result.exit_code == 0
        assert embed.call_args.kwargs["track_number"] == 1

    def test_queue_help(self, runner: CliRunner):
        """Test queue group with --help."""
        result = runner.invoke(main, ["queue", "--help"])

        assert result.exit_code == 0
        assert "queue" in result.output.lower()
        assert "list" in result.output.lower()

    def test_queue_no_subcommand(self, runner: CliRunner):
        """Test queue group without subcommand."""
        result = runner.invoke(main, ["queue"])

        # Click returns exit code 2 when a group is invoked without a subcommand
        assert result.exit_code == 2
        assert "queue" in result.output.lower()
        # Should show usage/error information when no subcommand is provided
        assert "list" in result.output.lower()

    def test_queue_list_help(self, runner: CliRunner):
        """Test queue list command with --help."""
        result = runner.invoke(main, ["queue", "list", "--help"])

        assert result.exit_code == 0
        assert "list" in result.output.lower()
        assert "--format" in result.output
        assert "--fields" in result.output

    def test_queue_list_success_default(self, runner: CliRunner, mocker: MockerFixture):
        """Test successful queue list command with default options."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "queue", return_value={
            "queue": [
                {
                    "title": "Song 1",
                    "artist": "Artist 1",
                    "album": "Album 1",
                    "duration": 180,
                    "service": "mpd",
                },
                {
                    "title": "Song 2",
                    "artist": "Artist 2",
                    "album": "Album 2",
                    "duration": 240,
                    "service": "webradio",
                },
            ]
        })

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["queue", "list"])

        assert result.exit_code == 0
        assert "Song 1" in result.output
        assert "Song 2" in result.output

    @pytest.mark.parametrize("extra", [[], ["-F", "table"]])
    def test_queue_list_of_local_files(
        self, runner: CliRunner, mocker: MockerFixture, extra: list[str]
    ):
        """A local file reports its title under name, which the short fields keep."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "queue", return_value={
            "queue": [
                {
                    "name": "1 - Belli capelli",
                    "artist": "Francesco De Gregori",
                    "album": "Titanic",
                    "service": "mpd",
                    "uri": "mnt/INTERNAL/music/001___Belli_capelli.flac",
                },
            ]
        })
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["queue", "list", *extra])

        assert result.exit_code == 0
        assert "1 - Belli capelli" in result.output
        # The keys the local files do not fill stay out of the short output
        assert "uri" not in result.output.lower()

    def test_queue_list_with_custom_host(self, runner: CliRunner, mocker: MockerFixture):
        """Test queue list command with custom host."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "queue", return_value={
            "queue": [
                {"title": "Test Song", "artist": "Test Artist"}
            ]
        })

        mock_client_class = mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["--host", "192.168.1.100", "queue", "list"])

        assert result.exit_code == 0
        host_configuration = mock_client_class.call_args[0][0]
        assert host_configuration.host == "192.168.1.100"

    def test_queue_list_with_format_json(self, runner: CliRunner, mocker: MockerFixture):
        """Test queue list command with --format json."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "queue", return_value={
            "queue": [
                {"title": "Test Song", "artist": "Test Artist", "duration": 180}
            ]
        })

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["queue", "list", "--format", "json"])

        assert result.exit_code == 0
        # Should be valid JSON
        output_data = json.loads(result.output)
        assert isinstance(output_data, list)
        assert len(output_data) == 1
        assert output_data[0]["title"] == "Test Song"
        assert output_data[0]["position"] == 1

    def test_queue_list_with_format_table(self, runner: CliRunner, mocker: MockerFixture):
        """Test queue list command with --format table."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "queue", return_value={
            "queue": [
                {"title": "Test Song", "artist": "Test Artist", "duration": 180}
            ]
        })

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["queue", "list", "--format", "table"])

        assert result.exit_code == 0
        assert "Volumio Queue" in result.output
        assert "Test Song" in result.output

    def test_queue_list_with_fields_all(self, runner: CliRunner, mocker: MockerFixture):
        """Test queue list command with --fields all."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "queue", return_value={
            "queue": [
                {
                    "title": "Test",
                    "artist": "Artist",
                    "extra_field": "extra_data",
                }
            ]
        })

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["queue", "list", "--fields", "ALL"])

        assert result.exit_code == 0
        output_data = json.loads(result.output)
        assert "extra_field" in output_data[0]

    def test_queue_list_with_fields_short(self, runner: CliRunner, mocker: MockerFixture):
        """Test queue list command with --fields short."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "queue", return_value={
            "queue": [
                {
                    "title": "Test",
                    "artist": "Artist",
                    "extra_field": "extra_data",
                }
            ]
        })

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["queue", "list", "--fields", "SHORT"])

        assert result.exit_code == 0
        output_data = json.loads(result.output)
        assert "title" in output_data[0]
        assert "artist" in output_data[0]
        assert "extra_field" not in output_data[0]

    def test_queue_list_with_raw_format(self, runner: CliRunner, mocker: MockerFixture):
        """Test queue list command with --format raw."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "queue", return_value={
            "queue": [
                {"title": "Test", "artist": "Artist", "extra_field": "data"}
            ]
        })

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["queue", "list", "--format", "raw"])

        assert result.exit_code == 0
        output_data = json.loads(result.output)
        # Raw should include all fields from the original response
        assert "queue" in output_data
        assert "extra_field" in output_data["queue"][0]

    def test_queue_list_with_verbose(self, runner: CliRunner, mocker: MockerFixture):
        """Test queue list command with --verbose flag."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "queue", return_value={
            "queue": [
                {"title": "Test Song"}
            ]
        })

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["--verbose", "queue", "list"])

        assert result.exit_code == 0
        assert "Connecting to" in result.output or "Successfully retrieved" in result.output

    def test_queue_list_connection_error(self, runner: CliRunner, mocker: MockerFixture):
        """Test queue list command with connection error."""
        mock_client = mocker.Mock()
        _attach_property(
            mock_client, "queue", side_effect=VolumioConnectionError("Connection failed")
        )

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["queue", "list"])

        assert result.exit_code == 1
        assert "Connection error" in result.output

    def test_queue_list_api_error(self, runner: CliRunner, mocker: MockerFixture):
        """Test queue list command with API error."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "queue", side_effect=VolumioAPIError("API error"))

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["queue", "list"])

        assert result.exit_code == 1
        assert "API error" in result.output

    def test_queue_list_machine_readable_suppresses_errors(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """Test queue list command with --machine-readable flag suppresses errors."""
        mock_client = mocker.Mock()
        _attach_property(
            mock_client, "queue", side_effect=VolumioConnectionError("Connection failed")
        )

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["--machine-readable", "queue", "list"])

        assert result.exit_code == 1
        # No error output with machine-readable flag
        assert result.output == ""

    def test_queue_list_empty_queue(self, runner: CliRunner, mocker: MockerFixture):
        """Test queue list command with empty queue."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "queue", return_value={"queue": []})

        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["queue", "list", "--format", "table"])

        assert result.exit_code == 0
        assert "Volumio Queue" in result.output
        assert "(empty)" in result.output


class TestPagerOption:
    """Test cases for the global --pager/--no-pager option."""

    @pytest.fixture
    def runner(self):
        """Create a CliRunner instance."""
        return CliRunner()

    def _mock_client(self, mocker: MockerFixture):
        """Mock VolumioRESTAPIClient with a one-track queue; mock the pager."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "queue", return_value={
            "queue": [{"title": "Paged Song", "artist": "Paged Artist", "service": "mpd"}]
        })
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        mock_pager = mocker.patch("volumito.cli.click_helpers.click.echo_via_pager")
        return mock_client, mock_pager

    def test_pager_routes_the_data_output(self, runner: CliRunner, mocker: MockerFixture):
        """With --pager the rendered data goes through echo_via_pager."""
        _, mock_pager = self._mock_client(mocker)

        result = runner.invoke(main, ["--pager", "queue", "list"])

        assert result.exit_code == 0
        mock_pager.assert_called_once()
        assert "Paged Song" in mock_pager.call_args.args[0]
        assert "Paged Song" not in result.output

    def test_no_pager_is_the_default(self, runner: CliRunner, mocker: MockerFixture):
        """Without --pager the data prints directly to the standard output."""
        _, mock_pager = self._mock_client(mocker)

        result = runner.invoke(main, ["queue", "list"])

        assert result.exit_code == 0
        mock_pager.assert_not_called()
        assert "Paged Song" in result.output

    def test_machine_readable_bypasses_the_pager(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """--machine-readable prints directly even with --pager."""
        _, mock_pager = self._mock_client(mocker)

        result = runner.invoke(main, ["-m", "-G", "queue", "list"])

        assert result.exit_code == 0
        mock_pager.assert_not_called()
        assert "Paged Song" in result.output


class TestAliases:
    """Test cases for the user-defined command aliases."""

    @pytest.fixture
    def runner(self):
        """Create a CliRunner instance."""
        return CliRunner()

    def _write_config(self, tmp_path, content: str) -> str:
        """Write a configuration file with the given content, returning its path."""
        config = tmp_path / "volumito.yaml"
        config.write_text(content)
        return str(config)

    def _mock_state(self, mocker: MockerFixture):
        """Mock VolumioRESTAPIClient with a recognizable playback state."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={
            "title": "AliasMarkerTitle",
            "artist": "Artist",
            "status": "stop",
        })
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        return mock_client

    def test_alias_invokes_the_target(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """An alias runs the subcommand its path leads to."""
        self._mock_state(mocker)
        config = self._write_config(tmp_path, "aliases:\n  zzstatus: playback status\n")

        result = runner.invoke(main, ["-c", config, "zzstatus"])

        assert result.exit_code == 0
        assert "AliasMarkerTitle" in result.output

    def test_alias_forwards_arguments(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """The arguments after the alias reach the target command."""
        self._mock_state(mocker)
        config = self._write_config(tmp_path, "aliases:\n  zzstatus: playback status\n")

        result = runner.invoke(main, ["-c", config, "zzstatus", "-F", "table"])

        assert result.exit_code == 0
        assert "Volumio Status" in result.output

    def test_alias_to_a_group(self, runner: CliRunner, mocker: MockerFixture, tmp_path):
        """An alias may target a group, whose subcommands then resolve normally."""
        self._mock_state(mocker)
        config = self._write_config(tmp_path, "aliases:\n  zzpb: playback\n")

        result = runner.invoke(main, ["-c", config, "zzpb", "status"])

        assert result.exit_code == 0
        assert "AliasMarkerTitle" in result.output

    def test_alias_shadowing_a_command_is_dropped(self, runner: CliRunner, tmp_path):
        """An alias with the name of a built-in command warns and is dropped."""
        config = self._write_config(
            tmp_path, "aliases:\n  info: system version\n  zzver: version\n"
        )

        result = runner.invoke(main, ["-c", config, "zzver"])

        assert result.exit_code == 0
        assert "shadows the command 'info'" in result.output
        # The valid alias of the same file still resolves
        assert "volumito, version" in result.output

    def test_alias_with_unknown_target_is_dropped(self, runner: CliRunner, tmp_path):
        """A dropped alias does not resolve, and invoking it names the problem."""
        config = self._write_config(tmp_path, "aliases:\n  zzbad: does not exist\n")

        result = runner.invoke(main, ["-c", config, "zzbad"])

        assert result.exit_code == 2
        assert "targets the unknown command 'does not exist'" in result.output

    def test_broken_alias_warns_on_other_commands(self, runner: CliRunner, tmp_path):
        """A dropped alias warns without refusing the other invocations."""
        config = self._write_config(tmp_path, "aliases:\n  zzbad: does not exist\n")

        result = runner.invoke(main, ["-c", config, "version"])

        assert result.exit_code == 0
        assert "targets the unknown command 'does not exist'" in result.output
        assert "volumito, version" in result.output

    def test_check_reports_broken_aliases(self, runner: CliRunner, tmp_path):
        """configuration check reports the shadowing and unresolved aliases."""
        config = self._write_config(
            tmp_path, "aliases:\n  info: system info\n  zzbad: no such\n"
        )

        result = runner.invoke(main, ["configuration", "check", config])

        assert result.exit_code == 1
        assert "shadows the command 'info'" in result.output
        assert "targets the unknown command 'no such'" in result.output

    def test_check_prints_the_aliases(self, runner: CliRunner, tmp_path):
        """configuration check lists the aliases like the other keys."""
        config = self._write_config(tmp_path, "aliases:\n  zzstatus: playback status\n")

        result = runner.invoke(main, ["configuration", "check", config])

        assert result.exit_code == 0
        assert "aliases.zzstatus = playback status" in result.output

    def test_ignore_configuration_file_disables_the_aliases(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """With -i the aliases of the probed configuration do not exist."""
        self._mock_state(mocker)
        config = self._write_config(tmp_path, "aliases:\n  zzstatus: playback status\n")
        mocker.patch(
            "volumito.cli.configuration.configuration_paths", return_value=[config]
        )

        probed = runner.invoke(main, ["zzstatus"])
        ignored = runner.invoke(main, ["-i", "zzstatus"])

        assert probed.exit_code == 0
        assert "AliasMarkerTitle" in probed.output
        assert ignored.exit_code == 2
        assert "No such command 'zzstatus'" in ignored.output

    def test_alias_takes_the_target_subsection_defaults(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """The per-command configuration defaults of the target apply under the alias."""
        self._mock_state(mocker)
        config = self._write_config(
            tmp_path,
            "aliases:\n  zzstatus: playback status\n"
            "output:\n  playback-status:\n    format: table\n",
        )

        result = runner.invoke(main, ["-c", config, "zzstatus"])

        assert result.exit_code == 0
        assert "Volumio Status" in result.output

    def test_aliases_are_not_listed_in_help(self, runner: CliRunner, tmp_path):
        """The configuration-defined aliases do not appear in the group help."""
        config = self._write_config(tmp_path, "aliases:\n  zzstatus: playback status\n")

        result = runner.invoke(main, ["-c", config, "--help"])

        assert result.exit_code == 0
        assert "zzstatus" not in result.output
        # The static built-in alias stays listed
        assert "info" in result.output

    def test_command_alias_prints_the_aliases(self, runner: CliRunner, tmp_path):
        """command alias prints one line per alias, sorted, followed by its target."""
        config = self._write_config(
            tmp_path, "aliases:\n  zzstatus: playback status\n  zzcover: track albumart\n"
        )

        result = runner.invoke(main, ["-c", config, "command", "alias"])

        assert result.exit_code == 0
        assert result.output.splitlines() == [
            "zzcover : track albumart",
            "zzstatus : playback status",
        ]

    def test_command_alias_machine_readable(self, runner: CliRunner, tmp_path):
        """In machine-readable mode command alias prints the JSON object."""
        config = self._write_config(tmp_path, "aliases:\n  zzstatus: playback status\n")

        result = runner.invoke(main, ["-m", "-c", config, "command", "alias"])

        assert result.exit_code == 0
        assert result.output == '{"zzstatus": "playback status"}\n'

    def test_command_alias_without_aliases(self, runner: CliRunner):
        """Without any alias defined, command alias prints nothing (an empty object with -m)."""
        plain = runner.invoke(main, ["-i", "command", "alias"])
        machine = runner.invoke(main, ["-m", "-i", "command", "alias"])

        assert plain.exit_code == 0
        assert plain.output == ""
        assert machine.exit_code == 0
        assert machine.output == "{}\n"


class TestCommandList:
    """Test cases for the command list command."""

    @pytest.fixture
    def runner(self):
        """Create a CliRunner instance."""
        return CliRunner()

    def _write_config(self, tmp_path, content: str) -> str:
        """Write a configuration file with the given content, returning its path."""
        config = tmp_path / "volumito.yaml"
        config.write_text(content)
        return str(config)

    _ALIASES = (
        "aliases:\n"
        "  q: queue\n"
        "  qc: queue clear\n"
        "  clr: queue clear\n"
    )

    def test_tree_is_the_default(self, runner: CliRunner):
        """The tree heads with the program name and indents each level by four spaces."""
        result = runner.invoke(main, ["-i", "command", "list"])

        assert result.exit_code == 0
        lines = result.output.splitlines()
        assert lines[0] == "volumito"
        assert "    queue" in lines
        assert "        clear" in lines
        # The groups of each level are listed lexicographically
        top = [line[4:] for line in lines if line.startswith("    ") and line[4] != " "]
        assert top == sorted(top)

    def test_tree_lists_the_new_commands(self, runner: CliRunner):
        """The command group and its list subcommand list themselves."""
        result = runner.invoke(main, ["-i", "command", "list"])

        assert result.exit_code == 0
        assert "    command" in result.output.splitlines()
        assert "        list" in result.output.splitlines()

    def test_no_tree_prints_sorted_paths(self, runner: CliRunner):
        """--no-tree prints the full command paths, sorted, groups included."""
        result = runner.invoke(main, ["-i", "command", "list", "--no-tree"])

        assert result.exit_code == 0
        lines = result.output.splitlines()
        assert lines == sorted(lines)
        assert "queue" in lines
        assert "queue clear" in lines
        assert "info" in lines

    def test_tree_shows_the_aliases(self, runner: CliRunner, tmp_path):
        """The aliases of a path follow its name, sorted and comma-separated."""
        config = self._write_config(tmp_path, self._ALIASES)

        result = runner.invoke(main, ["-c", config, "command", "list"])

        assert result.exit_code == 0
        lines = result.output.splitlines()
        assert "    queue (q)" in lines
        assert "        clear (clr, qc)" in lines

    def test_no_tree_shows_the_aliases(self, runner: CliRunner, tmp_path):
        """The flat paths carry the same alias suffixes."""
        config = self._write_config(tmp_path, self._ALIASES)

        result = runner.invoke(main, ["-c", config, "command", "list", "--no-tree"])

        assert result.exit_code == 0
        lines = result.output.splitlines()
        assert "queue (q)" in lines
        assert "queue clear (clr, qc)" in lines

    def test_machine_readable_is_the_node_tree(self, runner: CliRunner, tmp_path):
        """In machine-readable mode the tree is a list of typed, nested nodes."""
        config = self._write_config(tmp_path, self._ALIASES)

        result = runner.invoke(main, ["-m", "-c", config, "command", "list"])

        assert result.exit_code == 0
        nodes = json.loads(result.output)
        assert [node["path"] for node in nodes] == sorted(node["path"] for node in nodes)
        queue = next(node for node in nodes if node["path"] == "queue")
        assert list(queue) == ["aliases", "path", "type", "subcommands"]
        assert queue["aliases"] == ["q"]
        assert queue["type"] == "group"
        clear = next(node for node in queue["subcommands"] if node["path"] == "clear")
        assert clear == {"aliases": ["clr", "qc"], "path": "clear", "type": "command"}
        # A command without aliases carries an empty list
        info = next(node for node in nodes if node["path"] == "info")
        assert info == {"aliases": [], "path": "info", "type": "command"}

    def test_machine_readable_no_tree_flattens_the_nodes(
        self, runner: CliRunner, tmp_path
    ):
        """--no-tree flattens the nodes, holding its full path."""
        config = self._write_config(tmp_path, self._ALIASES)

        result = runner.invoke(main, ["-m", "-c", config, "command", "list", "--no-tree"])

        assert result.exit_code == 0
        nodes = json.loads(result.output)
        names = [node["path"] for node in nodes]
        assert names == sorted(names)
        assert all("subcommands" not in node for node in nodes)
        assert {"aliases": ["q"], "path": "queue", "type": "group"} in nodes
        assert {
            "aliases": ["clr", "qc"],
            "path": "queue clear",
            "type": "command",
        } in nodes

    @pytest.mark.parametrize("extra", [[], ["--no-tree"]])
    def test_no_aliases_omits_them(self, runner: CliRunner, tmp_path, extra: list[str]):
        """--no-aliases drops the parenthesized suffixes from both layouts."""
        config = self._write_config(tmp_path, self._ALIASES)

        result = runner.invoke(
            main, ["-c", config, "command", "list", "--no-aliases", *extra]
        )

        assert result.exit_code == 0
        assert "(" not in result.output
        assert "clear" in result.output

    def test_the_configuration_keys(self, runner: CliRunner, tmp_path):
        """The command-list subsection sets the defaults of both switches."""
        config = self._write_config(
            tmp_path,
            self._ALIASES + "output:\n  command-list:\n    aliases: false\n    tree: false\n",
        )

        result = runner.invoke(main, ["-c", config, "command", "list"])

        assert result.exit_code == 0
        lines = result.output.splitlines()
        # Flat (no volumito heading, full paths) and without the alias suffixes
        assert lines[0] != "volumito"
        assert "queue clear" in lines
        assert "(" not in result.output

    def test_the_shorthands(self, runner: CliRunner, tmp_path):
        """-a and -t are the shorthands of --aliases and --tree."""
        config = self._write_config(tmp_path, self._ALIASES)

        flat = runner.invoke(main, ["-c", config, "command", "list", "-a", "--no-tree"])
        tree = runner.invoke(main, ["-c", config, "command", "list", "-a", "-t"])

        assert flat.exit_code == 0
        assert "queue (q)" in flat.output.splitlines()
        assert tree.exit_code == 0
        assert tree.output.splitlines()[0] == "volumito"
        assert "    queue (q)" in tree.output.splitlines()

    def test_no_aliases_machine_readable_drops_the_key(
        self, runner: CliRunner, tmp_path
    ):
        """In machine-readable mode --no-aliases leaves the aliases key out."""
        config = self._write_config(tmp_path, self._ALIASES)

        result = runner.invoke(
            main, ["-m", "-c", config, "command", "list", "--no-aliases"]
        )

        assert result.exit_code == 0
        nodes = json.loads(result.output)
        queue = next(node for node in nodes if node["path"] == "queue")
        assert list(queue) == ["path", "type", "subcommands"]
        assert {"path": "clear", "type": "command"} in queue["subcommands"]


class TestResolveCommandPath:
    """Test cases for the command-path resolver behind the aliases."""

    def test_resolves_a_leaf(self):
        """A two-token path leads to the subcommand."""
        ctx = click.Context(main)

        command = resolve_command_path(main, ctx, "track albumart")

        assert command is not None
        assert command.name == "albumart"

    def test_an_empty_path_does_not_resolve(self):
        """A path with no tokens resolves to nothing."""
        ctx = click.Context(main)

        assert resolve_command_path(main, ctx, "  ") is None

    def test_a_path_through_a_leaf_does_not_resolve(self):
        """A token after a subcommand (not a group) resolves to nothing."""
        ctx = click.Context(main)

        assert resolve_command_path(main, ctx, "playback status extra") is None


class TestSystemCommands:
    """Test cases for the system ping/version/info commands."""

    @pytest.fixture
    def runner(self):
        """Create a CliRunner instance."""
        return CliRunner()

    def _mock_client(self, mocker: MockerFixture):
        """Mock VolumioRESTAPIClient with usable system-utility methods."""
        mock_client = mocker.Mock()
        mock_client.ping.return_value = "pong"
        _attach_property(mock_client, "system_version", return_value={
            "systemversion": "3.601",
            "hardware": "pi",
        })
        _attach_property(mock_client, "system_info", return_value={
            "name": "Living Room",
            "systemversion": "3.601",
        })
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        return mock_client

    def test_ping(self, runner: CliRunner, mocker: MockerFixture):
        """system ping prints the response text."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["system", "ping"])

        assert result.exit_code == 0
        assert result.output.strip() == "pong"

    def test_ping_machine_readable(self, runner: CliRunner, mocker: MockerFixture):
        """In machine-readable mode ping prints the text as a quoted JSON string."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["-m", "system", "ping"])

        assert result.exit_code == 0
        assert result.output.strip() == '"pong"'

    def test_ping_connection_error(self, runner: CliRunner, mocker: MockerFixture):
        """system ping exits 1 on a connection error."""
        mock_client = self._mock_client(mocker)
        mock_client.ping.side_effect = VolumioConnectionError("Connection failed")

        result = runner.invoke(main, ["system", "ping"])

        assert result.exit_code == 1
        assert "Connection error" in result.output

    def test_version_pretty(self, runner: CliRunner, mocker: MockerFixture):
        """system version prints pretty JSON by default."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["system", "version"])

        assert result.exit_code == 0
        assert "\n" in result.output.strip()  # indented / multi-line
        assert json.loads(result.output)["systemversion"] == "3.601"

    def test_version_raw(self, runner: CliRunner, mocker: MockerFixture):
        """system version -F raw prints compact JSON."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["system", "version", "-F", "raw"])

        assert result.exit_code == 0
        assert "\n" not in result.output.strip()
        assert json.loads(result.output)["hardware"] == "pi"

    def test_version_json(self, runner: CliRunner, mocker: MockerFixture):
        """system version -F json prints JSON with 2-space indentation."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["system", "version", "-F", "json"])

        assert result.exit_code == 0
        assert '\n  "' in result.output
        assert json.loads(result.output)["hardware"] == "pi"

    def test_version_table(self, runner: CliRunner, mocker: MockerFixture):
        """system version -F table prints a table with its heading."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["system", "version", "-F", "table"])

        assert result.exit_code == 0
        assert "Volumio System Version" in result.output
        assert "Hardware" in result.output
        assert "pi" in result.output

    def test_version_invalid_format(self, runner: CliRunner, mocker: MockerFixture):
        """An unknown --format value is a usage error."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["system", "version", "-F", "yaml"])

        assert result.exit_code == 2
        assert "'yaml' is not one of" in result.output

    def test_version_raw_option_removed(self, runner: CliRunner):
        """The removed -R/--raw option is now a usage error."""
        for option in ("-R", "--raw"):
            result = runner.invoke(main, ["system", "version", option])
            assert result.exit_code == 2
            assert "No such option" in result.output

    def test_version_machine_readable(self, runner: CliRunner, mocker: MockerFixture):
        """In machine-readable mode system version prints compact JSON."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["-m", "system", "version"])

        assert result.exit_code == 0
        assert "\n" not in result.output.strip()
        assert json.loads(result.output)["systemversion"] == "3.601"

    def test_version_api_error(self, runner: CliRunner, mocker: MockerFixture):
        """system version exits 1 on an API error."""
        mock_client = self._mock_client(mocker)
        _attach_property(mock_client, "system_version", side_effect=VolumioAPIError("API error"))

        result = runner.invoke(main, ["system", "version"])

        assert result.exit_code == 1
        assert "API error" in result.output

    def test_info(self, runner: CliRunner, mocker: MockerFixture):
        """system info prints the system information as pretty JSON."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["system", "info"])

        assert result.exit_code == 0
        assert json.loads(result.output)["name"] == "Living Room"

    def test_info_table(self, runner: CliRunner, mocker: MockerFixture):
        """system info -F table prints a table with its heading."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["system", "info", "-F", "table"])

        assert result.exit_code == 0
        assert "Volumio System Info" in result.output
        assert "Living Room" in result.output

    def test_info_raw(self, runner: CliRunner, mocker: MockerFixture):
        """system info -F raw prints compact JSON."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["system", "info", "-F", "raw"])

        assert result.exit_code == 0
        assert "\n" not in result.output.strip()
        assert json.loads(result.output)["name"] == "Living Room"

    def test_top_level_info_is_alias_for_system_info(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """The top-level info command produces the same output as system info."""
        self._mock_client(mocker)

        info_result = runner.invoke(main, ["info"])
        system_info_result = runner.invoke(main, ["system", "info"])

        assert info_result.exit_code == 0
        assert info_result.output == system_info_result.output
        assert json.loads(info_result.output)["name"] == "Living Room"


class TestSystemAlarm:
    """Test cases for the system alarm subgroup."""

    ALARMS = {
        "alarms": [
            {"id": 3, "name": "Weekday", "enabled": True, "time": "07:30", "playlist": "jazz"},
            {"id": 5, "name": "Weekend", "enabled": False, "time": "09:00", "playlist": "rock"},
        ]
    }
    """The alarms, as a Volumio host answers them."""

    _REFUSAL = (
        "API client error: The Synchronous REST API client does not offer the sleep timer "
        "and the alarms: use --api-client synchronous_websocket or asynchronous_websocket, "
        "or --allow-fallback-to-websocket-api"
    )
    """The error of a REST API client asked for an alarm member, without the fallback."""

    _WEBSOCKET = ["-C", "synchronous_websocket"]
    """The global option selecting the WebSocket API client the commands need."""

    @pytest.fixture
    def runner(self):
        """Create a CliRunner instance."""
        return CliRunner()

    def _mock_rest_client(self, mocker: MockerFixture):
        """Mock VolumioRESTAPIClient, the default client."""
        mock_client = mocker.Mock()
        mock_client.logger = LOGGER
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        return mock_client

    def _mock_websocket_client(self, mocker: MockerFixture):
        """Mock VolumioWebSocketClient answering the alarm reads and edits."""
        mock_client = mocker.Mock()
        mock_client.logger = LOGGER
        _attach_property(mock_client, "alarms", return_value=self.ALARMS)
        mock_client.add_alarm.return_value = Alarm.from_raw(
            {"id": 6, "name": "Nap", "enabled": True, "time": "14:15", "playlist": "ambient"}
        )
        mocker.patch(
            "volumito.cli.click_helpers.VolumioWebSocketClient",
            return_value=mock_client,
        )
        return mock_client

    def test_list(self, runner: CliRunner, mocker: MockerFixture):
        """system alarm list prints the short fields of each alarm, as a table too."""
        self._mock_websocket_client(mocker)

        pretty = runner.invoke(main, [*self._WEBSOCKET, "system", "alarm", "list"])
        table = runner.invoke(main, [*self._WEBSOCKET, "system", "alarm", "list", "-F", "table"])

        assert pretty.exit_code == 0
        assert json.loads(pretty.output) == self.ALARMS["alarms"]
        assert table.exit_code == 0
        lines = table.output.splitlines()
        assert "Volumio Alarms" in lines
        assert "1. Weekday" in lines
        assert "   Time             : 07:30" in lines

    @pytest.mark.parametrize(("options", "enabled"), [([], True), (["--disabled"], False)])
    def test_add(self, runner: CliRunner, mocker: MockerFixture, options, enabled):
        """system alarm add adds an alarm, armed unless --disabled."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "system", "alarm", "add", "Nap", "14:15", "ambient", *options]
        )

        assert result.exit_code == 0
        assert "Command 'add alarm \"Nap\"' executed successfully" in result.output
        mock_client.add_alarm.assert_called_once_with("Nap", "14:15", "ambient", enabled)

    def test_add_requires_its_arguments(self, runner: CliRunner, mocker: MockerFixture):
        """The name, the time, and the playlist are all required."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "alarm", "add", "Nap", "14:15"])

        assert result.exit_code == 2
        assert "Missing argument 'PLAYLIST'" in result.output
        mock_client.add_alarm.assert_not_called()

    def test_add_with_a_bad_time(self, runner: CliRunner, mocker: MockerFixture):
        """A time the client refuses is reported as an invalid value."""
        mock_client = self._mock_websocket_client(mocker)
        mock_client.add_alarm.side_effect = ValueError(
            'The alarm time must be a time of day as "HH:MM", got "7:30am"'
        )

        result = runner.invoke(
            main, [*self._WEBSOCKET, "system", "alarm", "add", "Nap", "7:30am", "ambient"]
        )

        assert result.exit_code == 1
        assert 'Invalid value: The alarm time must be a time of day as "HH:MM"' in result.output

    def test_clear_refused_without_yes(self, runner: CliRunner, mocker: MockerFixture):
        """Without -y/--yes the alarms are kept."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "alarm", "clear"])

        assert result.exit_code == 1
        assert "Refusing to clear the alarms without -y/--yes" in result.output
        mock_client.set_alarms.assert_not_called()

    def test_clear(self, runner: CliRunner, mocker: MockerFixture):
        """With -y/--yes the set of alarms is replaced with an empty one."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "alarm", "clear", "-y"])

        assert result.exit_code == 0
        assert "Command 'clear alarms' executed successfully" in result.output
        mock_client.set_alarms.assert_called_once_with([])

    @pytest.mark.parametrize(
        ("command", "member"),
        [("disable", "disable_alarm"), ("enable", "enable_alarm")],
    )
    def test_one_alarm_actions(self, runner: CliRunner, mocker: MockerFixture, command, member):
        """The actions on one alarm name it by its identifier."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "alarm", command, "5"])

        assert result.exit_code == 0
        assert f"Command '{command} alarm 5' executed successfully" in result.output
        getattr(mock_client, member).assert_called_once_with(5)

    def test_remove_refused_without_yes(self, runner: CliRunner, mocker: MockerFixture):
        """Without -y/--yes the alarm is kept."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "alarm", "remove", "5"])

        assert result.exit_code == 1
        assert "Refusing to remove the alarm without -y/--yes: 5" in result.output
        mock_client.remove_alarm.assert_not_called()

    def test_remove(self, runner: CliRunner, mocker: MockerFixture):
        """With -y/--yes the alarm is removed by its identifier."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "alarm", "remove", "5", "-y"])

        assert result.exit_code == 0
        assert "Command 'remove alarm 5' executed successfully" in result.output
        mock_client.remove_alarm.assert_called_once_with(5)

    def test_an_unknown_alarm(self, runner: CliRunner, mocker: MockerFixture):
        """An identifier the client refuses is reported as an invalid value."""
        mock_client = self._mock_websocket_client(mocker)
        mock_client.remove_alarm.side_effect = ValueError("No alarm has the identifier 9")

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "alarm", "remove", "9", "-y"])

        assert result.exit_code == 1
        assert "Invalid value: No alarm has the identifier 9" in result.output

    def test_an_identifier_must_be_an_integer(self, runner: CliRunner, mocker: MockerFixture):
        """The identifier is the number system alarm list prints."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "system", "alarm", "remove", "Weekday", "-y"]
        )

        assert result.exit_code == 2
        mock_client.remove_alarm.assert_not_called()

    def test_set_from_a_file(self, runner: CliRunner, mocker: MockerFixture, tmp_path):
        """system alarm set replaces the set with the alarms of the file."""
        mock_client = self._mock_websocket_client(mocker)
        source = tmp_path / "alarms.json"
        source.write_text(json.dumps(self.ALARMS["alarms"]))

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "alarm", "set", str(source)])

        assert result.exit_code == 0
        assert f"Command 'set alarms \"{source}\"' executed successfully" in result.output
        mock_client.set_alarms.assert_called_once()
        sent = mock_client.set_alarms.call_args.args[0]
        assert [alarm.id for alarm in sent] == [3, 5]
        assert sent[0].playlist == "jazz"

    @pytest.mark.parametrize("content", ['{"id": 1}', "[1, 2]"])
    def test_set_from_a_file_of_another_shape(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path, content
    ):
        """The file must hold a list of alarm objects."""
        mock_client = self._mock_websocket_client(mocker)
        source = tmp_path / "alarms.json"
        source.write_text(content)

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "alarm", "set", str(source)])

        assert result.exit_code == 2
        assert "Expected FILE to hold a JSON list of alarm objects" in result.output
        mock_client.set_alarms.assert_not_called()

    @pytest.mark.parametrize("content", ["not json", None])
    def test_set_from_an_unreadable_file(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path, content
    ):
        """A file that is missing, or is not JSON, is an error."""
        mock_client = self._mock_websocket_client(mocker)
        source = tmp_path / "alarms.json"
        if content is not None:
            source.write_text(content)

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "alarm", "set", str(source)])

        assert result.exit_code == 1
        assert "Cannot read alarms file" in result.output
        mock_client.set_alarms.assert_not_called()

    @pytest.mark.parametrize(
        "arguments",
        [
            ["add", "Nap", "14:15", "ambient"],
            ["clear", "-y"],
            ["disable", "3"],
            ["enable", "3"],
            ["list"],
            ["remove", "3", "-y"],
        ],
    )
    def test_a_rest_client_refuses(self, runner: CliRunner, mocker: MockerFixture, arguments):
        """With the default REST API client, the commands fail naming the remedies."""
        self._mock_rest_client(mocker)

        result = runner.invoke(main, ["system", "alarm", *arguments])

        assert result.exit_code == 1
        assert self._REFUSAL in result.output

    def test_a_rest_client_falls_back_when_allowed(self, runner: CliRunner, mocker: MockerFixture):
        """With the switch, the REST API client serves the command through a WebSocket one."""
        rest = self._mock_rest_client(mocker)
        websocket = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, ["--allow-fallback-to-websocket-api", "system", "alarm", "enable", "5"]
        )

        assert result.exit_code == 0
        assert (
            "Falling back to the WebSocket API client for the sleep timer and the alarms"
        ) in result.output
        websocket.enable_alarm.assert_called_once_with(5)
        websocket.disconnect.assert_called_once_with()
        rest.close.assert_called_once_with()


class TestSystemAudio:
    """Test cases for the system audio subgroup."""

    AUDIO_OUTPUTS = {
        "availableOutputs": [
            {"id": "alsa", "name": "Main", "type": "device", "enabled": True, "volume": 60},
            {
                "id": "bt",
                "name": "Bluetooth",
                "type": "bluetooth",
                "enabled": False,
                "volume": 0,
                "extra": "detail",
            },
        ]
    }
    """The audio outputs, as a Volumio host answers them."""

    DEVICES = {
        "devices": {
            "active": {"id": "1", "name": "HiFiBerry DAC"},
            "available": [{"id": "0", "name": "Headphones"}, {"id": "1", "name": "HiFiBerry DAC"}],
        },
        "i2s": True,
    }
    """The output devices, as a Volumio host answers them."""

    DSP = {"page": {"label": "DSP"}, "sections": [{"id": "section", "content": []}]}
    """A DSP configuration page, as a Volumio host answers it."""

    INPUTS = {"spdif": {"name": "S/PDIF", "enabled": True}}
    """The input sources, as a Volumio host answers them."""

    _REFUSAL = (
        "API client error: The Synchronous REST API client does not offer the audio "
        "outputs and devices: use --api-client synchronous_websocket or "
        "asynchronous_websocket, or --allow-fallback-to-websocket-api"
    )
    """The error of a REST API client asked for an audio member, without the fallback."""

    _WEBSOCKET = ["-C", "synchronous_websocket"]
    """The global option selecting the WebSocket API client the commands need."""

    @pytest.fixture
    def runner(self):
        """Create a CliRunner instance."""
        return CliRunner()

    def _mock_rest_client(self, mocker: MockerFixture):
        """Mock VolumioRESTAPIClient, the default client."""
        mock_client = mocker.Mock()
        mock_client.logger = LOGGER
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        return mock_client

    def _mock_websocket_client(self, mocker: MockerFixture):
        """Mock VolumioWebSocketClient answering the audio reads."""
        mock_client = mocker.Mock()
        mock_client.logger = LOGGER
        _attach_property(mock_client, "audio_outputs", return_value=self.AUDIO_OUTPUTS)
        _attach_property(mock_client, "dsp_config", return_value=self.DSP)
        _attach_property(
            mock_client, "output_devices", return_value=OutputDevices.from_envelope(self.DEVICES)
        )
        _attach_property(
            mock_client,
            "extended_output_devices",
            return_value=OutputDevices.from_envelope({**self.DEVICES, "extended": True}),
        )
        _attach_property(mock_client, "input_sources", return_value=self.INPUTS)
        mocker.patch(
            "volumito.cli.click_helpers.VolumioWebSocketClient",
            return_value=mock_client,
        )
        return mock_client

    def test_device_list(self, runner: CliRunner, mocker: MockerFixture):
        """system audio device list prints the devices and the active one."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "audio", "device", "list"])

        assert result.exit_code == 0
        assert json.loads(result.output) == self.DEVICES
        mock_client.output_devices_property.assert_called_once()
        mock_client.extended_output_devices_property.assert_not_called()

    def test_device_list_extended(self, runner: CliRunner, mocker: MockerFixture):
        """--extended asks for the devices with their details."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main,
            [*self._WEBSOCKET, "system", "audio", "device", "list", "--extended", "-F", "json"],
        )

        assert result.exit_code == 0
        assert json.loads(result.output)["extended"] is True
        mock_client.extended_output_devices_property.assert_called_once()
        mock_client.output_devices_property.assert_not_called()

    def test_device_list_table(self, runner: CliRunner, mocker: MockerFixture):
        """-F table heads the devices."""
        self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "system", "audio", "device", "list", "-F", "table"]
        )

        assert result.exit_code == 0
        assert "Volumio Output Devices" in result.output
        assert "HiFiBerry DAC" in result.output


    def test_device_set(self, runner: CliRunner, mocker: MockerFixture):
        """system audio device set chooses the device."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "audio", "device", "set", "1"])

        assert result.exit_code == 0
        assert "Command 'set output device \"1\"' executed successfully" in result.output
        mock_client.set_output_device.assert_called_once_with("1")
    @pytest.mark.parametrize(
        ("command", "member"),
        [
            ("disable", "disable_audio_output"),
            ("enable", "enable_audio_output"),
            ("pause", "audio_output_pause"),
            ("play", "audio_output_play"),
        ],
    )
    def test_output_actions(self, runner: CliRunner, mocker: MockerFixture, command, member):
        """The output actions name the output to the client."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "audio", command, "bt"])

        assert result.exit_code == 0
        assert f"Command '{command} output \"bt\"' executed successfully" in result.output
        getattr(mock_client, member).assert_called_once_with("bt")

    def test_dsp(self, runner: CliRunner, mocker: MockerFixture):
        """system audio dsp prints the configuration page of the DSP."""
        self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "audio", "dsp", "-F", "json"])

        assert result.exit_code == 0
        assert json.loads(result.output) == self.DSP

    def test_inputs(self, runner: CliRunner, mocker: MockerFixture):
        """system audio inputs prints the input sources as the host reports them."""
        self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "audio", "inputs"])

        assert result.exit_code == 0
        assert json.loads(result.output) == self.INPUTS

    def test_outputs_default_short_fields(self, runner: CliRunner, mocker: MockerFixture):
        """system audio outputs prints the short fields of each output."""
        self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "audio", "outputs"])

        assert result.exit_code == 0
        outputs = json.loads(result.output)
        assert [output["id"] for output in outputs] == ["alsa", "bt"]
        assert outputs[1]["volume"] == 0
        assert "extra" not in outputs[1]

    def test_outputs_all_fields_as_a_table(self, runner: CliRunner, mocker: MockerFixture):
        """-L ALL -F table lists every field of each output under the heading."""
        self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "system", "audio", "outputs", "-L", "ALL", "-F", "table"]
        )

        assert result.exit_code == 0
        lines = result.output.splitlines()
        assert "Volumio Audio Outputs" in lines
        assert "1. Main" in lines
        assert "2. Bluetooth" in lines
        assert "   Extra            : detail" in lines

    def test_outputs_raw(self, runner: CliRunner, mocker: MockerFixture):
        """-F raw prints the answer of the host as it is."""
        self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, ["-m", *self._WEBSOCKET, "system", "audio", "outputs", "-F", "raw"]
        )

        assert result.exit_code == 0
        assert json.loads(result.output) == self.AUDIO_OUTPUTS

    def test_outputs_format_from_the_configuration(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """The system-audio-outputs subsection sets the default fields and format."""
        self._mock_websocket_client(mocker)
        config = tmp_path / "volumito.yaml"
        config.write_text("output:\n  system-audio-outputs:\n    fields: id\n    format: json\n")

        result = runner.invoke(
            main, ["-c", str(config), *self._WEBSOCKET, "system", "audio", "outputs"]
        )

        assert result.exit_code == 0
        assert json.loads(result.output) == [{"id": "alsa"}, {"id": "bt"}]

    def test_volume(self, runner: CliRunner, mocker: MockerFixture):
        """system audio volume sets the volume of the output."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "audio", "volume", "alsa", "75"])

        assert result.exit_code == 0
        assert "Command 'volume 75 of output \"alsa\"' executed successfully" in result.output
        mock_client.set_audio_output_volume.assert_called_once_with("alsa", 75)

    @pytest.mark.parametrize("value", ["-1", "101", "loud"])
    def test_volume_out_of_range(self, runner: CliRunner, mocker: MockerFixture, value):
        """The volume is an integer from 0 to 100."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "system", "audio", "volume", "alsa", "--", value]
        )

        assert result.exit_code == 2
        mock_client.set_audio_output_volume.assert_not_called()

    @pytest.mark.parametrize(
        "arguments",
        [
            ["device", "list"],
            ["device", "set", "1"],
            ["disable", "bt"],
            ["dsp"],
            ["enable", "bt"],
            ["inputs"],
            ["outputs"],
            ["pause", "bt"],
            ["play", "bt"],
            ["volume", "alsa", "50"],
        ],
    )
    def test_a_rest_client_refuses(self, runner: CliRunner, mocker: MockerFixture, arguments):
        """With the default REST API client, the commands fail naming the remedies."""
        self._mock_rest_client(mocker)

        result = runner.invoke(main, ["system", "audio", *arguments])

        assert result.exit_code == 1
        assert self._REFUSAL in result.output

    def test_a_rest_client_falls_back_when_allowed(self, runner: CliRunner, mocker: MockerFixture):
        """With the switch, the REST API client serves the command through a WebSocket one."""
        rest = self._mock_rest_client(mocker)
        websocket = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, ["--allow-fallback-to-websocket-api", "system", "audio", "inputs"]
        )

        assert result.exit_code == 0
        assert (
            "Falling back to the WebSocket API client for the audio outputs and devices"
        ) in result.output
        assert json.loads(result.stdout) == self.INPUTS
        websocket.disconnect.assert_called_once_with()
        rest.close.assert_called_once_with()


class TestSystemSettings:
    """Test cases for system name, backup, power, timezone, and update."""

    BACKUPS = {
        "favourites": [{"uri": "song", "title": "Song"}],
        "my-web-radio": [],
        "playlist": [{"name": "jazz", "content": [{"uri": "track"}]}],
        "radio-favourites": [{"uri": "radio", "title": "Radio"}],
    }
    """The backup of each kind, as a Volumio host answers it."""

    BACKUP_ID = {"name": "volumio", "uuid": "1234", "time": "6/8/2026 - 15:29"}
    """The identification a Volumio host puts in a backup."""

    CHANNEL = {"currentChannel": "stable", "availableChannels": ["stable", "test"]}
    """The update channel, as a Volumio host answers it."""

    CHECK = {"updateavailable": False, "title": "No update available", "description": "Latest"}
    """The answer of the updater, as a Volumio host relays it."""

    POWER_MODES = {"hasPowerOffMode": True, "hasStandbyMode": False}
    """The power modes of a host without a standby mode."""

    TIMEZONES = ["Europe/Rome", "Europe/Paris", "UTC"]
    """The time zones a Volumio host can be set to."""

    _WEBSOCKET = ["-C", "synchronous_websocket"]
    """The global option selecting the WebSocket API client the commands need."""

    @pytest.fixture
    def runner(self):
        """Create a CliRunner instance."""
        return CliRunner()

    @staticmethod
    def _refusal(operation: str) -> str:
        """The error of a REST API client asked for an operation, without the fallback."""
        return (
            f"API client error: The Synchronous REST API client does not offer {operation}: "
            "use --api-client synchronous_websocket or asynchronous_websocket, "
            "or --allow-fallback-to-websocket-api"
        )

    def _mock_rest_client(self, mocker: MockerFixture):
        """Mock VolumioRESTAPIClient, the default client."""
        mock_client = mocker.Mock()
        mock_client.logger = LOGGER
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        return mock_client

    def _backup_document(self) -> dict:
        """What system backup create prints or writes: the identification and every kind."""
        return {"id": self.BACKUP_ID, **self.BACKUPS}

    def _mock_websocket_client(self, mocker: MockerFixture, power_modes: dict | None = None):
        """Mock VolumioWebSocketClient answering the system reads."""
        mock_client = mocker.Mock()
        mock_client.logger = LOGGER
        mock_client.backup.side_effect = lambda kind: {
            "id": self.BACKUP_ID,
            "backup": self.BACKUPS[kind],
        }
        _attach_property(
            mock_client, "available_timezones", return_value={"timezones": self.TIMEZONES}
        )
        _attach_property(mock_client, "automatic_update_enabled", return_value=True)
        _attach_property(mock_client, "device_name", return_value="Living Room")
        _attach_property(
            mock_client,
            "power_modes",
            return_value=self.POWER_MODES if power_modes is None else power_modes,
        )
        _attach_property(mock_client, "timezone", return_value="Europe/Rome")
        _attach_property(mock_client, "updater_channel", return_value=self.CHANNEL)
        mock_client.check_for_update.return_value = UpdateCheck.from_raw(self.CHECK)
        mock_client.check_update_cache.return_value = UpdateCheck.from_raw(self.CHECK)
        mocker.patch(
            "volumito.cli.click_helpers.VolumioWebSocketClient",
            return_value=mock_client,
        )
        return mock_client

    def test_name_prints_the_name(self, runner: CliRunner, mocker: MockerFixture):
        """Without a value, system name prints the name of the host."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "name"])

        assert result.exit_code == 0
        assert result.output.strip() == "Living Room"
        mock_client.device_name_property.assert_called_once_with()

    def test_name_prints_a_missing_name(self, runner: CliRunner, mocker: MockerFixture):
        """A host reporting no name prints an empty line, or null when machine-readable."""
        mock_client = self._mock_websocket_client(mocker)
        _attach_property(mock_client, "device_name", return_value=None)

        plain = runner.invoke(main, [*self._WEBSOCKET, "system", "name"])
        machine = runner.invoke(main, ["-m", *self._WEBSOCKET, "system", "name"])

        assert plain.exit_code == 0
        assert plain.output == "\n"
        assert machine.exit_code == 0
        assert machine.output.strip() == "null"

    def test_name_renames_the_host(self, runner: CliRunner, mocker: MockerFixture):
        """With a value, system name renames the host."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "name", "Kitchen"])

        assert result.exit_code == 0
        assert "Command 'name \"Kitchen\"' executed successfully" in result.output
        mock_client.device_name_property.assert_called_once_with("Kitchen")

    def test_backup_create_prints_the_backup(self, runner: CliRunner, mocker: MockerFixture):
        """Without a file, system backup create prints the backup of every kind."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "system", "backup", "create", "-F", "json"]
        )

        assert result.exit_code == 0
        assert json.loads(result.output) == self._backup_document()
        assert [c.args for c in mock_client.backup.call_args_list] == [
            ("favourites",), ("my-web-radio",), ("playlist",), ("radio-favourites",)
        ]

    def test_backup_create_writes_the_file(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """-o writes the backup as JSON to the file, and reports the path."""
        self._mock_websocket_client(mocker)
        target = tmp_path / "backup.json"

        result = runner.invoke(
            main, [*self._WEBSOCKET, "system", "backup", "create", "-o", str(target)]
        )

        assert result.exit_code == 0
        assert f'Created backup file "{target}"' in result.output
        assert json.loads(target.read_text()) == self._backup_document()

    def test_backup_create_machine_readable_prints_the_path(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """In machine-readable mode the written path is printed as a JSON string."""
        self._mock_websocket_client(mocker)
        target = tmp_path / "backup.json"

        result = runner.invoke(
            main, ["-m", *self._WEBSOCKET, "system", "backup", "create", "-o", str(target)]
        )

        assert result.exit_code == 0
        assert json.loads(result.output) == str(target)

    def test_backup_create_refuses_to_overwrite(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """An existing file is kept unless --overwrite-existing-files is given."""
        self._mock_websocket_client(mocker)
        target = tmp_path / "backup.json"
        target.write_text("{}")

        kept = runner.invoke(
            main, [*self._WEBSOCKET, "system", "backup", "create", "-o", str(target)]
        )
        replaced = runner.invoke(
            main,
            [*self._WEBSOCKET, "system", "backup", "create", "-o", str(target),
             "--overwrite-existing-files"],
        )

        assert kept.exit_code == 1
        assert "File already exists" in kept.output
        assert replaced.exit_code == 0
        assert json.loads(target.read_text()) == self._backup_document()

    def test_backup_create_cannot_write(self, runner: CliRunner, mocker: MockerFixture, tmp_path):
        """A file that cannot be written is an error."""
        self._mock_websocket_client(mocker)
        target = tmp_path / "missing" / "backup.json"

        result = runner.invoke(
            main, [*self._WEBSOCKET, "system", "backup", "create", "-o", str(target)]
        )

        assert result.exit_code == 1
        assert "Cannot write backup file" in result.output

    def test_backup_restore(self, runner: CliRunner, mocker: MockerFixture):
        """With -y/--yes the host restores its local backup."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "backup", "restore", "-y"])

        assert result.exit_code == 0
        assert "Command 'restore backup' executed successfully" in result.output
        mock_client.restore_backup.assert_called_once_with()

    def test_backup_restore_refused_without_yes(self, runner: CliRunner, mocker: MockerFixture):
        """Without -y/--yes nothing is restored."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "backup", "restore"])

        assert result.exit_code == 1
        assert "Refusing to restore the backup without -y/--yes" in result.output
        mock_client.restore_backup.assert_not_called()

    def test_backup_save(self, runner: CliRunner, mocker: MockerFixture):
        """system backup save has the host write its local backup."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "backup", "save"])

        assert result.exit_code == 0
        assert "Command 'save backup' executed successfully" in result.output
        mock_client.save_backup.assert_called_once_with()

    def test_power_modes(self, runner: CliRunner, mocker: MockerFixture):
        """system power modes prints the power modes of the host."""
        self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "power", "modes"])

        assert result.exit_code == 0
        assert json.loads(result.output) == self.POWER_MODES

    @pytest.mark.parametrize(
        ("command", "message"),
        [
            ("reboot", "Refusing to reboot the Volumio host without -y/--yes"),
            ("shutdown", "Refusing to shut the Volumio host down without -y/--yes"),
            ("standby", "Refusing to put the Volumio host on standby without -y/--yes"),
        ],
    )
    def test_power_actions_refused_without_yes(
        self, runner: CliRunner, mocker: MockerFixture, command, message
    ):
        """Without -y/--yes the host is left alone."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "power", command])

        assert result.exit_code == 1
        assert message in result.output
        getattr(mock_client, command).assert_not_called()

    @pytest.mark.parametrize("command", ["reboot", "shutdown"])
    def test_power_actions(self, runner: CliRunner, mocker: MockerFixture, command):
        """With -y/--yes the host reboots or shuts down."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "power", command, "-y"])

        assert result.exit_code == 0
        assert f"Command '{command}' executed successfully" in result.output
        getattr(mock_client, command).assert_called_once_with()

    @pytest.mark.parametrize(
        ("has_standby_mode", "refused"), [(True, False), (False, True), (None, True)]
    )
    def test_power_standby(
        self, runner: CliRunner, mocker: MockerFixture, has_standby_mode, refused
    ):
        """With -y/--yes the host goes on standby, unless it reports no such mode."""
        mock_client = self._mock_websocket_client(
            mocker, power_modes={"hasPowerOffMode": True, "hasStandbyMode": has_standby_mode}
        )

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "power", "standby", "-y"])

        assert result.exit_code == (1 if refused else 0)
        assert ("Command 'standby' executed successfully" in result.output) is not refused
        assert ("reports no standby mode" in result.output) is refused
        assert mock_client.standby.call_count == (0 if refused else 1)

    def test_timezone_prints_the_zone(self, runner: CliRunner, mocker: MockerFixture):
        """system timezone alone prints the time zone of the host."""
        mock_client = self._mock_websocket_client(mocker)

        plain = runner.invoke(main, [*self._WEBSOCKET, "system", "timezone"])
        machine = runner.invoke(main, ["-m", *self._WEBSOCKET, "system", "timezone"])

        assert plain.exit_code == 0
        assert plain.output.strip() == "Europe/Rome"
        assert machine.exit_code == 0
        assert machine.output.strip() == '"Europe/Rome"'
        assert mock_client.timezone_property.call_count == 2

    def test_timezone_list(self, runner: CliRunner, mocker: MockerFixture):
        """system timezone list prints the zones the host can be set to."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "system", "timezone", "list", "-F", "table"]
        )

        assert result.exit_code == 0
        lines = result.output.splitlines()
        assert "Volumio Time Zones" in lines
        assert "1. Europe/Rome" in lines
        assert "3. UTC" in lines
        # The group callback does not read the zone when a subcommand runs
        mock_client.timezone_property.assert_not_called()

    def test_timezone_set(self, runner: CliRunner, mocker: MockerFixture):
        """system timezone set moves the host to a zone of the list."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "timezone", "set", "UTC"])

        assert result.exit_code == 0
        assert "Command 'timezone \"UTC\"' executed successfully" in result.output
        mock_client.available_timezones_property.assert_called_once_with()
        mock_client.timezone_property.assert_called_once_with("UTC")

    def test_timezone_set_unknown(self, runner: CliRunner, mocker: MockerFixture):
        """A zone outside the list is refused."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "system", "timezone", "set", "Mars/Olympus"]
        )

        assert result.exit_code == 1
        assert 'Time zone not found: "Mars/Olympus"' in result.output
        mock_client.timezone_property.assert_not_called()

    def test_update_automatic(self, runner: CliRunner, mocker: MockerFixture):
        """system update automatic prints whether the host updates itself."""
        self._mock_websocket_client(mocker)

        plain = runner.invoke(main, [*self._WEBSOCKET, "system", "update", "automatic"])
        machine = runner.invoke(main, ["-m", *self._WEBSOCKET, "system", "update", "automatic"])

        assert plain.exit_code == 0
        assert plain.output.strip() == "True"
        assert machine.exit_code == 0
        assert machine.output.strip() == "true"

    @pytest.mark.parametrize(
        ("arguments", "expected"),
        [
            (["enable"], (True, None, None)),
            (["enable", "--start-time", "3", "--end-time", "6"], (True, 3, 6)),
            (["disable"], (False, None, None)),
        ],
    )
    def test_update_automatic_switch(
        self, runner: CliRunner, mocker: MockerFixture, arguments, expected
    ):
        """system update automatic enable/disable switches the automatic updates."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "system", "update", "automatic", *arguments]
        )

        assert result.exit_code == 0
        assert f"Command 'update automatic {arguments[0]}' executed successfully" in (
            result.output
        )
        mock_client.set_automatic_updates.assert_called_once_with(*expected)

    def test_update_automatic_enable_refuses_an_hour_outside_the_day(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """The window hours are hours of the day."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "system", "update", "automatic", "enable", "--end-time", "24"]
        )

        assert result.exit_code == 2
        assert "24 is not in the range 0<=x<=23" in result.output
        mock_client.set_automatic_updates.assert_not_called()

    def test_update_channel_prints_the_channel(self, runner: CliRunner, mocker: MockerFixture):
        """system update channel alone prints the channel in use."""
        self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "update", "channel"])

        assert result.exit_code == 0
        assert result.output.strip() == "stable"

    def test_update_channel_prints_a_missing_channel(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """A host reporting no channel prints an empty line."""
        mock_client = self._mock_websocket_client(mocker)
        _attach_property(mock_client, "updater_channel", return_value={"availableChannels": []})

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "update", "channel"])

        assert result.exit_code == 0
        assert result.output == "\n"

    def test_update_channel_list(self, runner: CliRunner, mocker: MockerFixture):
        """system update channel list prints the channels the host can follow."""
        self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "system", "update", "channel", "list", "-F", "json"]
        )

        assert result.exit_code == 0
        assert json.loads(result.output) == ["stable", "test"]

    def test_update_channel_set(self, runner: CliRunner, mocker: MockerFixture):
        """system update channel set moves the host to a channel of the list."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "system", "update", "channel", "set", "test"]
        )

        assert result.exit_code == 0
        assert "Command 'update channel \"test\"' executed successfully" in result.output
        mock_client.updater_channel_property.assert_called_with("test")

    @pytest.mark.parametrize("channels", [["stable", "test"], []])
    def test_update_channel_set_unknown(
        self, runner: CliRunner, mocker: MockerFixture, channels
    ):
        """A channel outside the list is refused, listing the available ones."""
        mock_client = self._mock_websocket_client(mocker)
        _attach_property(
            mock_client, "updater_channel", return_value={"availableChannels": channels}
        )

        result = runner.invoke(
            main, [*self._WEBSOCKET, "system", "update", "channel", "set", "nightly"]
        )

        assert result.exit_code == 1
        assert 'Update channel not found: "nightly"' in result.output
        assert "Available update channels:" in result.output
        assert ('  "stable"' in result.output) is bool(channels)
        assert ("  (none)" in result.output) is not bool(channels)

    @pytest.mark.parametrize(
        ("options", "member"), [([], "check_for_update"), (["--cached"], "check_update_cache")]
    )
    def test_update_check(self, runner: CliRunner, mocker: MockerFixture, options, member):
        """system update check waits for the answer, anew or cached, and prints it."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "system", "update", "check", *options, "-F", "json"]
        )

        assert result.exit_code == 0
        assert json.loads(result.output) == self.CHECK
        getattr(mock_client, member).assert_called_once_with()

    def test_update_install_refused_without_yes(self, runner: CliRunner, mocker: MockerFixture):
        """Without -y/--yes nothing is installed."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "update", "install"])

        assert result.exit_code == 1
        assert "Refusing to install the update without -y/--yes" in result.output
        mock_client.update.assert_not_called()

    @pytest.mark.parametrize(
        ("options", "ignore"), [([], False), (["--ignore-integrity-check"], True)]
    )
    def test_update_install(self, runner: CliRunner, mocker: MockerFixture, options, ignore):
        """With -y/--yes the update is installed, checked unless told otherwise."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "system", "update", "install", "-y", *options]
        )

        assert result.exit_code == 0
        assert "Command 'update install' executed successfully" in result.output
        mock_client.update.assert_called_once_with(ignore)

    @pytest.mark.parametrize(
        ("arguments", "operation"),
        [
            (["name"], "the system settings"),
            (["name", "Kitchen"], "the system settings"),
            (["backup", "create"], "the system settings"),
            (["backup", "restore", "-y"], "the system settings"),
            (["backup", "save"], "the system settings"),
            (["power", "modes"], "the system settings"),
            (["power", "reboot", "-y"], "the system settings"),
            (["power", "shutdown", "-y"], "the system settings"),
            (["power", "standby", "-y"], "the system settings"),
            (["timezone"], "the system settings"),
            (["timezone", "list"], "the system settings"),
            (["timezone", "set", "UTC"], "the system settings"),
            (["update", "automatic"], "the updates"),
            (["update", "automatic", "disable"], "the updates"),
            (["update", "automatic", "enable"], "the updates"),
            (["update", "channel"], "the updates"),
            (["update", "channel", "list"], "the updates"),
            (["update", "channel", "set", "test"], "the updates"),
            (["update", "check"], "the updates"),
            (["update", "check", "--cached"], "the updates"),
            (["update", "install", "-y"], "the updates"),
        ],
    )
    def test_a_rest_client_refuses(
        self, runner: CliRunner, mocker: MockerFixture, arguments, operation
    ):
        """With the default REST API client, the commands fail naming the remedies."""
        self._mock_rest_client(mocker)

        result = runner.invoke(main, ["system", *arguments])

        assert result.exit_code == 1
        assert self._refusal(operation) in result.output

    def test_a_rest_client_falls_back_when_allowed(self, runner: CliRunner, mocker: MockerFixture):
        """With the switch, the REST API client serves the command through a WebSocket one."""
        rest = self._mock_rest_client(mocker)
        websocket = self._mock_websocket_client(mocker)

        result = runner.invoke(main, ["--allow-fallback-to-websocket-api", "system", "name"])

        assert result.exit_code == 0
        assert "Falling back to the WebSocket API client for the system settings" in (
            result.output
        )
        assert result.stdout.strip() == "Living Room"
        websocket.disconnect.assert_called_once_with()
        rest.close.assert_called_once_with()


class TestSystemNetworkShareUsb:
    """Test cases for the system network, system share, and system usb subgroups."""

    INTERFACES = {
        "interfaces": [
            {"type": "Wired", "ip": "192.168.1.10", "status": "connected", "speed": "1Gb/s"},
            {"type": "Wireless", "ip": "", "status": "disconnected", "speed": "", "mac": "a"},
        ]
    }
    """The network interfaces, as a Volumio host answers them."""

    NETWORKS = {
        "available": [
            {"ssid": "Home", "signal": 70, "security": "wpa", "configured": True},
            {"ssid": "Guest", "signal": 40, "security": "", "configured": False},
        ]
    }
    """The wireless networks seen last, as a Volumio host answers them."""

    SCANNED = {"available": [{"ssid": "Cafe", "signal": 20, "security": "wpa"}]}
    """The wireless networks a scan finds."""

    SHARE = {"id": "s1", "name": "Music", "path": "192.168.1.2/Music", "fstype": "cifs"}
    """The details of one share."""

    SHARES = {
        "shares": [
            {
                "id": "s1",
                "name": "Music",
                "path": "192.168.1.2/Music",
                "fstype": "cifs",
                "size": "1.2 TB",
                "username": "guest",
                "options": "vers=2.0",
                "mounted": True,
            },
            {"id": "s2", "name": "Films", "path": "nas/films", "fstype": "nfs"},
        ]
    }
    """The mounted shares, as a Volumio host answers them."""

    DRIVES = {
        "drives": [
            {
                "type": "remdisk",
                "title": "USB Stick",
                "service": "mpd",
                "albumart": "/albumart?icon=usb",
                "uri": "music-library/USB/USB Stick",
            },
        ]
    }
    """The USB drives, as the USB music source of a Volumio host lists them."""

    DRIVES_SHORT = [{"title": "USB Stick", "uri": "music-library/USB/USB Stick"}]
    """The short fields of the drives, as system usb list prints them."""

    DISCOVERED = {"192.168.1.2": ["Music", "Films"]}
    """The shares a discovery finds."""

    _WEBSOCKET = ["-C", "synchronous_websocket"]
    """The global option selecting the WebSocket API client the commands need."""

    @pytest.fixture
    def runner(self):
        """Create a CliRunner instance."""
        return CliRunner()

    @staticmethod
    def _refusal(operation: str) -> str:
        """The error of a REST API client asked for an operation, without the fallback."""
        return (
            f"API client error: The Synchronous REST API client does not offer {operation}: "
            "use --api-client synchronous_websocket or asynchronous_websocket, "
            "or --allow-fallback-to-websocket-api"
        )

    def _mock_rest_client(self, mocker: MockerFixture):
        """Mock VolumioRESTAPIClient, the default client."""
        mock_client = mocker.Mock()
        mock_client.logger = LOGGER
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        return mock_client

    def _mock_websocket_client(self, mocker: MockerFixture):
        """Mock VolumioWebSocketClient answering the network, share, and USB reads."""
        mock_client = mocker.Mock()
        mock_client.logger = LOGGER
        _attach_property(mock_client, "network_info", return_value=self.INTERFACES)
        _attach_property(mock_client, "wireless_networks_cache", return_value=self.NETWORKS)
        _attach_property(mock_client, "wireless_networks", return_value=self.SCANNED)
        _attach_property(mock_client, "shares", return_value=self.SHARES)
        _attach_property(mock_client, "usb_drives", return_value=self.DRIVES)
        mock_client.discover_network_shares.return_value = self.DISCOVERED
        mock_client.get_share.return_value = Share.from_raw(self.SHARE)
        mocker.patch(
            "volumito.cli.click_helpers.VolumioWebSocketClient",
            return_value=mock_client,
        )
        return mock_client

    def test_network_info(self, runner: CliRunner, mocker: MockerFixture):
        """system network info prints the short fields of each interface."""
        self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "network", "info"])

        assert result.exit_code == 0
        interfaces = json.loads(result.output)
        assert [interface["type"] for interface in interfaces] == ["Wired", "Wireless"]
        assert interfaces[0]["ip"] == "192.168.1.10"
        assert "mac" not in interfaces[1]

    def test_network_info_table_heads_each_block_with_the_type(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """-F table names each interface by its type."""
        self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "system", "network", "info", "-F", "table"]
        )

        assert result.exit_code == 0
        lines = result.output.splitlines()
        assert "Volumio Network Interfaces" in lines
        assert "1. Wired" in lines
        assert "   Ip               : 192.168.1.10" in lines
        assert "2. Wireless" in lines

    def test_network_wireless_prints_the_cache(self, runner: CliRunner, mocker: MockerFixture):
        """Without --scan, the networks seen last are printed, named by their SSID."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "system", "network", "wireless", "-F", "table"]
        )

        assert result.exit_code == 0
        lines = result.output.splitlines()
        assert "Volumio Wireless Networks" in lines
        assert "1. Home" in lines
        assert "   Signal           : 70" in lines
        assert "2. Guest" in lines
        mock_client.wireless_networks_cache_property.assert_called_once()
        mock_client.wireless_networks_property.assert_not_called()

    def test_network_wireless_scans(self, runner: CliRunner, mocker: MockerFixture):
        """--scan asks the host to scan anew."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "system", "network", "wireless", "--scan", "-F", "json"]
        )

        assert result.exit_code == 0
        assert [network["ssid"] for network in json.loads(result.output)] == ["Cafe"]
        mock_client.wireless_networks_property.assert_called_once()
        mock_client.wireless_networks_cache_property.assert_not_called()

    def test_network_join_refused_without_yes(self, runner: CliRunner, mocker: MockerFixture):
        """Without -y/--yes no network is joined."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "network", "join", "Home"])

        assert result.exit_code == 1
        assert 'Refusing to join the wireless network without -y/--yes: "Home"' in result.output
        mock_client.save_wireless_settings.assert_not_called()

    @pytest.mark.parametrize(
        ("options", "password"), [([], ""), (["--password", "secret"], "secret")]
    )
    def test_network_join(self, runner: CliRunner, mocker: MockerFixture, options, password):
        """With -y/--yes the network is joined, with the password given or none."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "system", "network", "join", "Home", "-y", *options]
        )

        assert result.exit_code == 0
        assert "Command 'join \"Home\"' executed successfully" in result.output
        mock_client.save_wireless_settings.assert_called_once_with("Home", password)

    @pytest.mark.parametrize(
        ("options", "given"),
        [
            ([], {}),
            (
                ["--username", "guest", "--password", "pw", "--options", "vers=2.0"],
                {"username": "guest", "password": "pw", "options": "vers=2.0"},
            ),
        ],
    )
    def test_share_add(self, runner: CliRunner, mocker: MockerFixture, options, given):
        """system share add mounts the share, with the fields given."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main,
            [*self._WEBSOCKET, "system", "share", "add", "Music", "192.168.1.2/Music", "cifs",
             *options],
        )

        assert result.exit_code == 0
        assert "Command 'add share \"Music\"' executed successfully" in result.output
        mock_client.add_share.assert_called_once_with("Music", "192.168.1.2/Music", "cifs", **given)

    def test_share_discover(self, runner: CliRunner, mocker: MockerFixture):
        """system share discover prints what the host found, as it reports it."""
        self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "share", "discover"])

        assert result.exit_code == 0
        assert json.loads(result.output) == self.DISCOVERED

    def test_share_edit(self, runner: CliRunner, mocker: MockerFixture):
        """system share edit changes the fields given of the share."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main,
            [*self._WEBSOCKET, "system", "share", "edit", "s1", "--name", "Tunes", "--path",
             "nas/tunes", "--fstype", "nfs", "--username", "u", "--password", "p",
             "--options", "ro"],
        )

        assert result.exit_code == 0
        assert "Command 'edit share \"s1\"' executed successfully" in result.output
        mock_client.edit_share.assert_called_once_with(
            "s1", name="Tunes", path="nas/tunes", fstype="nfs", username="u", password="p",
            options="ro",
        )

    def test_share_edit_nothing(self, runner: CliRunner, mocker: MockerFixture):
        """Editing nothing is a usage error."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "share", "edit", "s1"])

        assert result.exit_code == 2
        assert "Expected at least one of the --fstype, --name, --options" in result.output
        mock_client.edit_share.assert_not_called()

    def test_share_info(self, runner: CliRunner, mocker: MockerFixture):
        """system share info prints the details of the share."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "system", "share", "info", "s1", "-F", "table"]
        )

        assert result.exit_code == 0
        assert 'Volumio Network Share "s1"' in result.output
        assert "192.168.1.2/Music" in result.output
        mock_client.get_share.assert_called_once_with("s1")

    def test_share_list(self, runner: CliRunner, mocker: MockerFixture):
        """system share list prints the short fields of each share."""
        self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "share", "list"])

        assert result.exit_code == 0
        shares = json.loads(result.output)
        assert [share["name"] for share in shares] == ["Music", "Films"]
        assert shares[0]["options"] == "vers=2.0"
        assert "mounted" not in shares[0]

    def test_share_list_raw(self, runner: CliRunner, mocker: MockerFixture):
        """-F raw prints the answer of the host as it is."""
        self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, ["-m", *self._WEBSOCKET, "system", "share", "list", "-F", "raw"]
        )

        assert result.exit_code == 0
        assert json.loads(result.output) == self.SHARES

    def test_share_remove_refused_without_yes(self, runner: CliRunner, mocker: MockerFixture):
        """Without -y/--yes no share is unmounted."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "share", "remove", "s1"])

        assert result.exit_code == 1
        assert 'Refusing to unmount the share without -y/--yes: "s1"' in result.output
        mock_client.delete_share.assert_not_called()

    def test_share_remove(self, runner: CliRunner, mocker: MockerFixture):
        """With -y/--yes the share is unmounted."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "system", "share", "remove", "s1", "-y"]
        )

        assert result.exit_code == 0
        assert "Command 'remove share \"s1\"' executed successfully" in result.output
        mock_client.delete_share.assert_called_once_with("s1")

    def test_usb_list(self, runner: CliRunner, mocker: MockerFixture):
        """system usb list prints the drives, as a table too."""
        self._mock_websocket_client(mocker)

        pretty = runner.invoke(main, [*self._WEBSOCKET, "system", "usb", "list"])
        table = runner.invoke(main, [*self._WEBSOCKET, "system", "usb", "list", "-F", "table"])

        assert pretty.exit_code == 0
        assert json.loads(pretty.output) == self.DRIVES_SHORT
        assert table.exit_code == 0
        assert "Volumio USB Drives" in table.output
        assert "1. USB Stick" in table.output

    def test_usb_eject(self, runner: CliRunner, mocker: MockerFixture):
        """system usb eject unmounts the drive."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "usb", "eject", "USB Stick"])

        assert result.exit_code == 0
        assert "Command 'eject \"USB Stick\"' executed successfully" in result.output
        mock_client.safe_remove_drive.assert_called_once_with("USB Stick")

    @pytest.mark.parametrize(
        ("arguments", "operation"),
        [
            (["network", "info"], "the network settings"),
            (["network", "join", "Home", "-y"], "the network settings"),
            (["network", "wireless"], "the network settings"),
            (["network", "wireless", "--scan"], "the network settings"),
            (
                ["share", "add", "Music", "nas/music", "nfs"],
                "the network shares and the USB drives",
            ),
            (["share", "discover"], "the network shares and the USB drives"),
            (["share", "edit", "s1", "--name", "X"], "the network shares and the USB drives"),
            (["share", "info", "s1"], "the network shares and the USB drives"),
            (["share", "list"], "the network shares and the USB drives"),
            (["share", "remove", "s1", "-y"], "the network shares and the USB drives"),
            (["usb", "eject", "USB Stick"], "the network shares and the USB drives"),
            (["usb", "list"], "the network shares and the USB drives"),
        ],
    )
    def test_a_rest_client_refuses(
        self, runner: CliRunner, mocker: MockerFixture, arguments, operation
    ):
        """With the default REST API client, the commands fail naming the remedies."""
        self._mock_rest_client(mocker)

        result = runner.invoke(main, ["system", *arguments])

        assert result.exit_code == 1
        assert self._refusal(operation) in result.output

    def test_a_rest_client_falls_back_when_allowed(self, runner: CliRunner, mocker: MockerFixture):
        """With the switch, the REST API client serves the command through a WebSocket one."""
        rest = self._mock_rest_client(mocker)
        websocket = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, ["--allow-fallback-to-websocket-api", "system", "usb", "list", "-F", "json"]
        )

        assert result.exit_code == 0
        assert (
            "Falling back to the WebSocket API client for the network shares and the USB drives"
        ) in result.output
        assert json.loads(result.stdout) == self.DRIVES_SHORT
        websocket.disconnect.assert_called_once_with()
        rest.close.assert_called_once_with()


class TestSystemPluginAndUi:
    """Test cases for the system plugin and system ui subgroups."""

    PLUGINS = {
        "plugins": [
            {
                "category": "music_service",
                "name": "mpd",
                "prettyName": "Music Library",
                "version": "1.0.0",
                "enabled": True,
                "active": True,
                "icon": "fa-music",
            },
            {
                "category": "audio_interface",
                "name": "alsa",
                "prettyName": "ALSA",
                "version": "0.9.1",
                "enabled": False,
                "active": False,
                "icon": "fa-volume-up",
            },
            {
                "category": "user_interface",
                "name": "touch_display",
                "prettyName": "Touch Display",
                "version": "3.0.0",
                "enabled": True,
                "active": True,
                "icon": "fa-tv",
            },
        ]
    }
    """The installed plugins, as a Volumio host answers them."""

    AVAILABLE = {
        "categories": [
            {
                "name": "music_service",
                "prettyName": "Music Services",
                "plugins": [
                    {
                        "category": "music_service",
                        "name": "spop",
                        "prettyName": "Spotify",
                        "version": "2.0.0",
                        "installed": False,
                        "url": "http://store/spop.zip",
                        "description": "Spotify",
                        "author": "Volumio",
                    }
                ],
            },
            {
                "name": "user_interface",
                "prettyName": "User Interface",
                "plugins": [
                    {
                        "category": "user_interface",
                        "name": "touch_display",
                        "prettyName": "Touch Display",
                        "version": "3.1.0",
                        "installed": True,
                        "updateAvailable": True,
                        "url": "http://store/touch.zip",
                    }
                ],
            },
        ]
    }
    """The plugins the store offers, as a Volumio host answers them."""

    MANAGED = {"plugins": [{"category": "music_service", "name": "mpd", "enabled": False}]}
    """The plugins as they stand after the plugin manager acted."""

    CONFIG = {"page": {"label": "MPD"}, "sections": [{"id": "section", "content": []}]}
    """A configuration page, as a Volumio host answers it."""

    BACKGROUNDS = {
        "available": [{"name": "Default", "path": "/bg/default.jpg"}],
        "current": {"name": "Default", "path": "/bg/default.jpg"},
    }
    """The backgrounds, as a Volumio host answers them."""

    EXPERIENCE = {
        "options": [{"id": True, "label": "Advanced"}, {"id": False, "label": "Simple"}],
        "status": {"id": True, "label": "Advanced"},
    }
    """The experience settings, as a Volumio host answers them."""

    LANGUAGES = {
        "available": [
            {"code": "en", "language": "English"},
            {"code": "it", "language": "Italiano"},
        ],
        "defaultLanguage": {"code": "en", "language": "English"},
    }
    """The languages, as a Volumio host answers them."""

    PRIVACY = {"allowUIStatistics": False}
    """The privacy settings, as a Volumio host answers them."""

    UI = {"color": "#54c688", "language": "it", "theme": "volumio"}
    """The user interface settings, as a Volumio host answers them."""

    _WEBSOCKET = ["-C", "synchronous_websocket"]
    """The global option selecting the WebSocket API client the commands need."""

    @pytest.fixture
    def runner(self):
        """Create a CliRunner instance."""
        return CliRunner()

    @staticmethod
    def _refusal(operation: str) -> str:
        """The error of a REST API client asked for an operation, without the fallback."""
        return (
            f"API client error: The Synchronous REST API client does not offer {operation}: "
            "use --api-client synchronous_websocket or asynchronous_websocket, "
            "or --allow-fallback-to-websocket-api"
        )

    def _mock_rest_client(self, mocker: MockerFixture):
        """Mock VolumioRESTAPIClient, the default client."""
        mock_client = mocker.Mock()
        mock_client.logger = LOGGER
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        return mock_client

    def _mock_websocket_client(self, mocker: MockerFixture):
        """Mock VolumioWebSocketClient answering the plugin and interface reads."""
        mock_client = mocker.Mock()
        mock_client.logger = LOGGER
        _attach_property(mock_client, "installed_plugins", return_value=self.PLUGINS)
        _attach_property(mock_client, "available_plugins", return_value=self.AVAILABLE)
        mock_client.manage_plugin.return_value = Plugins.from_raw(self.MANAGED)
        mock_client.get_plugin_config.return_value = UiConfig.from_raw(self.CONFIG)
        _attach_property(mock_client, "backgrounds", return_value=self.BACKGROUNDS)
        _attach_property(mock_client, "experience_settings", return_value=self.EXPERIENCE)
        _attach_property(mock_client, "languages", return_value=self.LANGUAGES)
        _attach_property(mock_client, "privacy_settings", return_value=self.PRIVACY)
        _attach_property(mock_client, "ui_settings", return_value=self.UI)
        mocker.patch(
            "volumito.cli.click_helpers.VolumioWebSocketClient",
            return_value=mock_client,
        )
        return mock_client

    def test_plugin_available(self, runner: CliRunner, mocker: MockerFixture):
        """system plugin available prints the store plugins with their URLs, as a table too."""
        self._mock_websocket_client(mocker)

        pretty = runner.invoke(main, [*self._WEBSOCKET, "system", "plugin", "available"])
        table = runner.invoke(
            main, [*self._WEBSOCKET, "system", "plugin", "available", "-F", "table"]
        )

        assert pretty.exit_code == 0
        plugins = json.loads(pretty.output)
        assert [plugin["name"] for plugin in plugins] == ["spop", "touch_display"]
        assert plugins[0]["url"] == "http://store/spop.zip"
        assert plugins[1]["updateAvailable"] is True
        assert "description" not in plugins[0]
        assert table.exit_code == 0
        assert "Volumio Available Plugins" in table.output
        assert "1. spop" in table.output

    def test_plugin_available_wants_a_login(self, runner: CliRunner, mocker: MockerFixture):
        """A host not logged in to MyVolumio makes the command fail with the API error."""
        mock_client = self._mock_websocket_client(mocker)
        _attach_property(
            mock_client, "available_plugins", side_effect=VolumioAPIError("Please login")
        )

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "plugin", "available"])

        assert result.exit_code == 1
        assert "Please login" in result.output

    def test_plugin_configuration(self, runner: CliRunner, mocker: MockerFixture):
        """system plugin config prints the configuration page of the plugin."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main,
            [*self._WEBSOCKET, "system", "plugin", "configuration", "mpd", "-F", "json"],
        )

        assert result.exit_code == 0
        assert json.loads(result.output) == self.CONFIG
        mock_client.get_plugin_config.assert_called_once_with("music_service/mpd")

    def test_plugin_configuration_of_a_plugin_not_installed(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """A name the host does not list as installed is an error naming the listing."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "system", "plugin", "configuration", "nope"]
        )

        assert result.exit_code == 1
        assert 'Plugin not installed: "nope" (see "system plugin list")' in result.output
        mock_client.get_plugin_config.assert_not_called()

    @pytest.mark.parametrize(
        ("arguments", "action"),
        [
            (["disable", "mpd"], "disable"),
            (["enable", "mpd"], "enable"),
        ],
    )
    def test_plugin_manager_actions(
        self, runner: CliRunner, mocker: MockerFixture, arguments, action
    ):
        """The plugin manager acts on the plugin, and the plugins are printed as they stand."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "plugin", *arguments])

        assert result.exit_code == 0
        assert json.loads(result.output) == self.MANAGED["plugins"]
        mock_client.manage_plugin.assert_called_once_with(action, "music_service", "mpd")

    def test_plugin_install_refused_without_yes(self, runner: CliRunner, mocker: MockerFixture):
        """Without -y/--yes nothing is installed."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "plugin", "install", "spop"])

        assert result.exit_code == 1
        assert 'Refusing to install the plugin without -y/--yes: "spop"' in result.output
        mock_client.install_plugin.assert_not_called()

    def test_plugin_install(self, runner: CliRunner, mocker: MockerFixture):
        """With -y/--yes the plugin is installed from the package the store offers."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "system", "plugin", "install", "spop", "-y"]
        )

        assert result.exit_code == 0
        assert "Command 'install plugin \"spop\"' executed" in result.output
        mock_client.install_plugin.assert_called_once_with("http://store/spop.zip")

    def test_plugin_install_wait_and_enable(self, runner: CliRunner, mocker: MockerFixture):
        """--wait-and-enable polls the host until it registers the plugin, then enables it."""
        mock_client = self._mock_websocket_client(mocker)
        moving = {"category": "music_service", "name": "spop", "prettyName": "Spotify"}
        registered = {**moving, "version": "2.0.0", "enabled": False, "active": False}
        _attach_property(
            mock_client,
            "installed_plugins",
            side_effect=[
                self.PLUGINS,
                {"plugins": [*self.PLUGINS["plugins"], moving]},
                {"plugins": [*self.PLUGINS["plugins"], registered]},
            ],
        )
        sleep = mocker.patch("volumito.cli.click_helpers.time.sleep")

        result = runner.invoke(
            main,
            [*self._WEBSOCKET, "system", "plugin", "install", "spop", "--url", "http://x/p.zip",
             "--wait-and-enable", "-y"],
        )

        assert result.exit_code == 0
        assert "Command 'install plugin \"spop\"' executed" in result.output
        assert 'Waiting for the plugin "spop" to be installed... done' in result.output
        assert "Command 'enable plugin \"spop\"' executed" in result.output
        mock_client.install_plugin.assert_called_once_with("http://x/p.zip")
        mock_client.manage_plugin.assert_called_once_with("enable", "music_service", "spop")
        assert sleep.call_count == 2

    def test_plugin_install_wait_and_enable_times_out(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """A plugin the host never registers is reported after the last look."""
        mock_client = self._mock_websocket_client(mocker)
        mocker.patch("volumito.cli.click_helpers.PLUGIN_INSTALL_WAIT_RETRIES", 2)
        sleep = mocker.patch("volumito.cli.click_helpers.time.sleep")

        result = runner.invoke(
            main,
            [*self._WEBSOCKET, "system", "plugin", "install", "spop", "--url", "http://x/p.zip",
             "--wait-and-enable", "-y"],
        )

        assert result.exit_code == 1
        assert 'Plugin not installed within 10 seconds: "spop"' in result.output
        mock_client.manage_plugin.assert_not_called()
        assert sleep.call_count == 1

    def test_plugin_install_with_a_url(self, runner: CliRunner, mocker: MockerFixture):
        """--url names the package, and the store is not consulted."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main,
            [*self._WEBSOCKET, "system", "plugin", "install", "spop", "--url", "http://x/p.zip",
             "-y"],
        )

        assert result.exit_code == 0
        assert "Command 'install plugin \"spop\"' executed" in result.output
        mock_client.install_plugin.assert_called_once_with("http://x/p.zip")
        mock_client.available_plugins_property.assert_not_called()

    def test_plugin_install_an_unknown_name(self, runner: CliRunner, mocker: MockerFixture):
        """A name the store does not offer is an error naming the listing."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "system", "plugin", "install", "nope", "-y"]
        )

        assert result.exit_code == 1
        assert 'Plugin not found: "nope" (see "system plugin available")' in result.output
        mock_client.install_plugin.assert_not_called()

    def test_plugin_list(self, runner: CliRunner, mocker: MockerFixture):
        """system plugin list prints the short fields of each plugin, as a table too."""
        self._mock_websocket_client(mocker)

        pretty = runner.invoke(main, [*self._WEBSOCKET, "system", "plugin", "list"])
        table = runner.invoke(
            main, [*self._WEBSOCKET, "system", "plugin", "list", "-F", "table"]
        )

        assert pretty.exit_code == 0
        plugins = json.loads(pretty.output)
        assert [plugin["name"] for plugin in plugins] == ["mpd", "alsa", "touch_display"]
        assert plugins[0]["version"] == "1.0.0"
        assert "icon" not in plugins[0]
        assert table.exit_code == 0
        assert "Volumio Plugins" in table.output
        assert "1. mpd" in table.output

    def test_plugin_uninstall_refused_without_yes(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """Without -y/--yes nothing is removed."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "plugin", "uninstall", "mpd"])

        assert result.exit_code == 1
        assert 'Refusing to uninstall the plugin without -y/--yes: "mpd"' in result.output
        mock_client.uninstall_plugin.assert_not_called()

    def test_plugin_uninstall(self, runner: CliRunner, mocker: MockerFixture):
        """With -y/--yes the plugin is removed."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "system", "plugin", "uninstall", "mpd", "-y"]
        )

        assert result.exit_code == 0
        assert "Command 'uninstall plugin \"music_service/mpd\"' executed" in result.output
        mock_client.uninstall_plugin.assert_called_once_with("music_service", "mpd")


    def test_plugin_update_refused_without_yes(self, runner: CliRunner, mocker: MockerFixture):
        """Without -y/--yes nothing is updated, and the host is not consulted."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "plugin", "update", "mpd"])

        assert result.exit_code == 1
        assert 'Refusing to update the plugin without -y/--yes: "mpd"' in result.output
        mock_client.update_plugin.assert_not_called()
        mock_client.installed_plugins_property.assert_not_called()

    def test_plugin_update(self, runner: CliRunner, mocker: MockerFixture):
        """system plugin update reads the category from the host and the package from the store."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "system", "plugin", "update", "touch_display", "-y"]
        )

        assert result.exit_code == 0
        assert "Command 'update plugin \"user_interface/touch_display\"' executed" in (
            result.output
        )
        mock_client.update_plugin.assert_called_once_with(
            "user_interface", "touch_display", "http://store/touch.zip"
        )

    def test_plugin_update_with_a_url(self, runner: CliRunner, mocker: MockerFixture):
        """--url names the package, and the store is not consulted."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main,
            [*self._WEBSOCKET, "system", "plugin", "update", "mpd", "--url", "http://x/mpd.zip",
             "-y"],
        )

        assert result.exit_code == 0
        assert "Command 'update plugin \"music_service/mpd\"' executed" in result.output
        mock_client.update_plugin.assert_called_once_with(
            "music_service", "mpd", "http://x/mpd.zip"
        )
        mock_client.available_plugins_property.assert_not_called()

    def test_plugin_update_of_a_plugin_the_store_lacks(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """An installed plugin the store does not offer cannot be updated."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "plugin", "update", "mpd", "-y"])

        assert result.exit_code == 1
        assert 'Plugin not found: "mpd" (see "system plugin available")' in result.output
        mock_client.update_plugin.assert_not_called()
    def test_ui_background_prints_the_current_one(self, runner: CliRunner, mocker: MockerFixture):
        """system ui background alone prints the title of the image in use, or the colour."""
        mock_client = self._mock_websocket_client(mocker)

        colour = runner.invoke(main, [*self._WEBSOCKET, "system", "ui", "background"])
        machine = runner.invoke(main, ["-m", *self._WEBSOCKET, "system", "ui", "background"])
        _attach_property(
            mock_client,
            "ui_settings",
            return_value={"background": {"title": "Yosemite", "path": "y.jpg"}, "theme": "x"},
        )
        image = runner.invoke(main, [*self._WEBSOCKET, "system", "ui", "background"])

        assert colour.exit_code == 0
        assert colour.output.strip() == "#54c688"
        assert machine.exit_code == 0
        assert machine.output.strip() == '"#54c688"'
        assert image.exit_code == 0
        assert image.output.strip() == "Yosemite"
        mock_client.backgrounds_property.assert_not_called()

    def test_ui_background_list(self, runner: CliRunner, mocker: MockerFixture):
        """system ui background list prints the backgrounds and the one in use."""
        self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "ui", "background", "list"])

        assert result.exit_code == 0
        assert json.loads(result.output) == self.BACKGROUNDS

    def test_ui_background_delete_refused_without_yes(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """Without -y/--yes no background is deleted."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "system", "ui", "background", "delete", "Default"]
        )

        assert result.exit_code == 1
        assert 'Refusing to delete the background without -y/--yes: "Default"' in result.output
        mock_client.delete_background.assert_not_called()

    def test_ui_background_delete(self, runner: CliRunner, mocker: MockerFixture):
        """With -y/--yes the background is deleted."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "system", "ui", "background", "delete", "Default", "-y"]
        )

        assert result.exit_code == 0
        assert "Command 'delete background \"Default\"' executed" in result.output
        mock_client.delete_background.assert_called_once_with("Default")

    @pytest.mark.parametrize("name", ["Sea", "#000"])
    def test_ui_background_set(self, runner: CliRunner, mocker: MockerFixture, name):
        """system ui background set chooses an image by name, or a colour by its value."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "ui", "background", "set", name])

        assert result.exit_code == 0
        assert f"Command 'set background \"{name}\"' executed" in result.output
        mock_client.set_background.assert_called_once_with(name)

    def test_ui_background_set_an_unknown_name(self, runner: CliRunner, mocker: MockerFixture):
        """A background the host does not list is reported as an invalid value."""
        mock_client = self._mock_websocket_client(mocker)
        mock_client.set_background.side_effect = ValueError('No background is named "Nope"')

        result = runner.invoke(
            main, [*self._WEBSOCKET, "system", "ui", "background", "set", "Nope"]
        )

        assert result.exit_code == 1
        assert 'Invalid value: No background is named "Nope"' in result.output

    def test_ui_experience_prints_the_settings(self, runner: CliRunner, mocker: MockerFixture):
        """Without a value, system ui experience prints the settings."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "ui", "experience"])

        assert result.exit_code == 0
        assert json.loads(result.output) == self.EXPERIENCE
        mock_client.set_experience_settings.assert_not_called()

    @pytest.mark.parametrize(("value", "advanced"), [("advanced", True), ("simple", False)])
    def test_ui_experience_sets_the_mode(
        self, runner: CliRunner, mocker: MockerFixture, value, advanced
    ):
        """A value chooses the set of options."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "ui", "experience", value])

        assert result.exit_code == 0
        assert f"Command 'experience {value}' executed successfully" in result.output
        mock_client.set_experience_settings.assert_called_once_with(advanced)

    def test_ui_experience_rejects_other_values(self, runner: CliRunner, mocker: MockerFixture):
        """VALUE is advanced or simple."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "ui", "experience", "expert"])

        assert result.exit_code == 2
        mock_client.set_experience_settings.assert_not_called()

    def test_ui_language_prints_the_current_one(self, runner: CliRunner, mocker: MockerFixture):
        """system ui language alone prints the code of the language in use.

        The host reports English as the default language whatever is in use, so the
        code comes from the user interface settings, not from the language listing.
        """
        mock_client = self._mock_websocket_client(mocker)

        plain = runner.invoke(main, [*self._WEBSOCKET, "system", "ui", "language"])
        machine = runner.invoke(main, ["-m", *self._WEBSOCKET, "system", "ui", "language"])

        assert plain.exit_code == 0
        assert plain.output.strip() == "it"
        assert machine.exit_code == 0
        assert machine.output.strip() == '"it"'
        assert mock_client.ui_settings_property.call_count == 2
        mock_client.languages_property.assert_not_called()

    def test_ui_language_list(self, runner: CliRunner, mocker: MockerFixture):
        """system ui language list prints the languages and the one in use."""
        self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "ui", "language", "list"])

        assert result.exit_code == 0
        assert json.loads(result.output) == self.LANGUAGES

    @pytest.mark.parametrize(
        ("options", "name"), [([], None), (["--name", "Italiano"], "Italiano")]
    )
    def test_ui_language_set(self, runner: CliRunner, mocker: MockerFixture, options, name):
        """system ui language set chooses a language of the list, named when given."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "system", "ui", "language", "set", "it", *options]
        )

        assert result.exit_code == 0
        assert "Command 'language \"it\"' executed successfully" in result.output
        mock_client.set_language.assert_called_once_with("it", name)

    @pytest.mark.parametrize("available", [LANGUAGES["available"], []])
    def test_ui_language_set_unknown(
        self, runner: CliRunner, mocker: MockerFixture, available
    ):
        """A code outside the list is refused, listing the available codes."""
        mock_client = self._mock_websocket_client(mocker)
        _attach_property(mock_client, "languages", return_value={"available": available})

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "ui", "language", "set", "xx"])

        assert result.exit_code == 1
        assert 'Language not found: "xx"' in result.output
        assert ('  "en"' in result.output) is bool(available)
        assert ("  (none)" in result.output) is not bool(available)
        mock_client.set_language.assert_not_called()

    @pytest.mark.parametrize(
        ("command", "payload"), [("privacy", PRIVACY), ("settings", UI)]
    )
    def test_ui_reads(self, runner: CliRunner, mocker: MockerFixture, command, payload):
        """system ui privacy and settings print the answer of the host."""
        self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "system", "ui", command])

        assert result.exit_code == 0
        assert json.loads(result.output) == payload

    @pytest.mark.parametrize(
        ("arguments", "operation"),
        [
            (["plugin", "available"], "the plugins"),
            (["plugin", "configuration", "mpd"], "the plugins"),
            (["plugin", "disable", "mpd"], "the plugins"),
            (["plugin", "enable", "mpd"], "the plugins"),
            (["plugin", "install", "spop", "-y"], "the plugins"),
            (["plugin", "install", "spop", "--url", "http://x", "-y"], "the plugins"),
            (["plugin", "list"], "the plugins"),
            (["plugin", "uninstall", "mpd", "-y"], "the plugins"),
            (["plugin", "update", "mpd", "-y"], "the plugins"),
            (["ui", "background"], "the user interface settings"),
            (["ui", "background", "delete", "x", "-y"], "the user interface settings"),
            (["ui", "background", "list"], "the user interface settings"),
            (["ui", "background", "set", "x"], "the user interface settings"),
            (["ui", "experience"], "the user interface settings"),
            (["ui", "experience", "simple"], "the user interface settings"),
            (["ui", "language"], "the user interface settings"),
            (["ui", "language", "list"], "the user interface settings"),
            (["ui", "language", "set", "en"], "the user interface settings"),
            (["ui", "privacy"], "the user interface settings"),
            (["ui", "settings"], "the user interface settings"),
        ],
    )
    def test_a_rest_client_refuses(
        self, runner: CliRunner, mocker: MockerFixture, arguments, operation
    ):
        """With the default REST API client, the commands fail naming the remedies."""
        self._mock_rest_client(mocker)

        result = runner.invoke(main, ["system", *arguments])

        assert result.exit_code == 1
        assert self._refusal(operation) in result.output

    def test_a_rest_client_falls_back_when_allowed(self, runner: CliRunner, mocker: MockerFixture):
        """With the switch, the REST API client serves the command through a WebSocket one."""
        rest = self._mock_rest_client(mocker)
        websocket = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, ["--allow-fallback-to-websocket-api", "system", "ui", "settings"]
        )

        assert result.exit_code == 0
        assert "Falling back to the WebSocket API client for the user interface settings" in (
            result.output
        )
        assert json.loads(result.stdout) == self.UI
        websocket.disconnect.assert_called_once_with()
        rest.close.assert_called_once_with()


class TestSystemExecute:
    """Test cases for the system execute command."""

    @pytest.fixture
    def runner(self):
        """Create a CliRunner instance."""
        return CliRunner()

    def _mock_execution(self, mocker: MockerFixture, exit_code=0, stdout="up 3 days\n"):
        """Patch the remote execution with a prepared result."""
        return mocker.patch(
            "volumito.cli.volumito.execute_on_host",
            return_value=RemoteCommandResult(
                command="uptime", exit_code=exit_code, stdout=stdout, stderr=""
            ),
        )

    def test_help_warns_about_the_host(self, runner: CliRunner):
        """The help says the command may damage the host, and needs -y/--yes."""
        result = runner.invoke(main, ["system", "execute", "--help"])
        joined = " ".join(result.output.split())

        assert result.exit_code == 0
        assert "may damage it" in joined
        assert "executed only when -y/--yes is given" in joined

    def test_without_yes(self, runner: CliRunner, mocker: MockerFixture):
        """Without -y/--yes nothing is executed."""
        execute = self._mock_execution(mocker)

        result = runner.invoke(main, ["system", "execute", "uptime"])

        assert result.exit_code == 1
        assert 'Refusing to execute the command without -y/--yes: "uptime"' in result.output
        execute.assert_not_called()

    def test_without_yes_machine_readable(self, runner: CliRunner, mocker: MockerFixture):
        """The refusal prints nothing in machine-readable mode."""
        self._mock_execution(mocker)

        result = runner.invoke(main, ["-m", "system", "execute", "uptime"])

        assert result.exit_code == 1
        assert result.output == ""

    def test_executes_and_prints_the_result(self, runner: CliRunner, mocker: MockerFixture):
        """With -y the command runs and its outcome is printed."""
        execute = self._mock_execution(mocker)

        result = runner.invoke(main, ["system", "execute", "-y", "uptime"])

        assert result.exit_code == 0
        # The pretty view strips the outer whitespace of the strings, as it does
        # for every payload; the other formats keep the streams verbatim
        assert json.loads(result.output) == {
            "command": "uptime",
            "exit_code": 0,
            "stdout": "up 3 days",
            "stderr": "",
        }
        assert execute.call_args.args[1] == "uptime"

    def test_the_json_format_keeps_the_output_verbatim(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """-F json prints what the command wrote, newlines included."""
        self._mock_execution(mocker, stdout="  indented\n")

        result = runner.invoke(main, ["system", "execute", "-y", "uptime", "-F", "json"])

        assert result.exit_code == 0
        assert json.loads(result.output)["stdout"] == "  indented\n"

    def test_the_table_format(self, runner: CliRunner, mocker: MockerFixture):
        """-F table prints the outcome as a table."""
        self._mock_execution(mocker)

        result = runner.invoke(main, ["system", "execute", "-y", "uptime", "-F", "table"])

        assert result.exit_code == 0
        assert "Remote Command" in result.output
        assert "up 3 days" in result.output

    def test_machine_readable(self, runner: CliRunner, mocker: MockerFixture):
        """Machine-readable mode prints the outcome as compact JSON."""
        self._mock_execution(mocker)

        result = runner.invoke(main, ["-m", "system", "execute", "-y", "uptime"])

        assert result.exit_code == 0
        assert result.output.strip() == json.dumps(
            {"command": "uptime", "exit_code": 0, "stdout": "up 3 days\n", "stderr": ""}
        )

    def test_the_remote_exit_code_is_propagated(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """By default volumito exits with the status of the remote command."""
        self._mock_execution(mocker, exit_code=3, stdout="inactive\n")

        result = runner.invoke(main, ["system", "execute", "-y", "uptime"])

        assert result.exit_code == 3
        assert "inactive" in result.output

    def test_the_remote_exit_code_can_be_ignored(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """--no-propagate-remote-exit-code exits 0 whatever the command returned."""
        self._mock_execution(mocker, exit_code=3)

        result = runner.invoke(
            main,
            ["system", "execute", "-y", "--no-propagate-remote-exit-code", "uptime"],
        )

        assert result.exit_code == 0

    def test_a_failed_execution(self, runner: CliRunner, mocker: MockerFixture):
        """A failure of the connection exits 1, reporting what went wrong."""
        mocker.patch(
            "volumito.cli.volumito.execute_on_host",
            side_effect=VolumioSSHError("Authentication failed."),
        )

        result = runner.invoke(main, ["system", "execute", "-y", "uptime"])

        assert result.exit_code == 1
        assert "Authentication failed." in result.output

    def test_a_failed_execution_machine_readable(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """The failure prints nothing in machine-readable mode."""
        mocker.patch(
            "volumito.cli.volumito.execute_on_host",
            side_effect=VolumioSSHError("Authentication failed."),
        )

        result = runner.invoke(main, ["-m", "system", "execute", "-y", "uptime"])

        assert result.exit_code == 1
        assert result.output == ""


class TestCollectionBrowse:
    """Test cases for the collection browse command."""

    ENVELOPE = {
        "navigation": {
            # The root answers with its items directly in the lists array
            "lists": [
                {
                    "name": "Music Library",
                    "uri": "music-library",
                    "plugin_type": "music_service",
                    "plugin_name": "mpd",
                },
                {
                    "name": "Web Radio",
                    "uri": "radio",
                    "plugin_type": "music_service",
                    "plugin_name": "webradio",
                },
            ],
            "prev": {"uri": "/"},
        }
    }
    """A payload of the shape a root browse is answered with."""

    ALBUM_ENVELOPE = {
        "navigation": {
            "lists": [
                {
                    "items": [
                        {
                            "service": "mpd",
                            "type": "song",
                            "title": "Aguaplano",
                            "artist": "Paolo Conte",
                            "uri": "music-library/INTERNAL/music/001___Aguaplano.flac",
                        },
                        {
                            "service": "mpd",
                            "type": "folder",
                            "title": "A Folder",
                            "uri": "music-library/INTERNAL/music/folder",
                        },
                        {
                            "service": "mpd",
                            "type": "song",
                            "title": "Come Di",
                            "artist": "Paolo Conte",
                            "uri": "music-library/INTERNAL/music/002___Come_Di.flac",
                        },
                    ],
                }
            ],
            "info": {
                "title": "Aguaplano",
                "artist": "Paolo Conte",
                "service": "mpd",
                "type": "album",
                "uri": "albums://Paolo%20Conte/Aguaplano",
            },
            "prev": {"uri": "albums://Paolo%20Conte"},
        }
    }
    """A payload of the shape an album browse is answered with."""

    @pytest.fixture
    def runner(self):
        """Create a CliRunner instance."""
        return CliRunner()

    def _mock_client(self, mocker: MockerFixture, envelope: dict | None = None):
        """Mock VolumioRESTAPIClient with a prepared browse result."""
        mock_client = mocker.Mock()
        mock_client.browse.return_value = BrowseResults.from_envelope(envelope or self.ENVELOPE)
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        return mock_client

    def test_browses_the_root_by_default(self, runner: CliRunner, mocker: MockerFixture):
        """Without a URI the root is asked for, and the navigation is printed."""
        mock_client = self._mock_client(mocker)

        result = runner.invoke(main, ["collection", "browse", "-F", "json"])

        assert result.exit_code == 0
        mock_client.browse.assert_called_once_with(None, None)
        navigation = json.loads(result.output)
        assert [item["name"] for item in navigation["lists"][0]["items"]] == [
            "Music Library",
            "Web Radio",
        ]
        assert navigation["info"] is None
        assert navigation["prev"] == {"uri": "/"}

    def test_browses_the_uri(self, runner: CliRunner, mocker: MockerFixture):
        """The URI argument is what the host is asked for."""
        mock_client = self._mock_client(mocker)

        result = runner.invoke(main, ["collection", "browse", "music-library"])

        assert result.exit_code == 0
        mock_client.browse.assert_called_once_with("music-library", None)

    def test_the_table_format(self, runner: CliRunner, mocker: MockerFixture):
        """The table numbers the named items, with their URIs unless declined."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["collection", "browse", "-F", "table"])

        assert result.exit_code == 0
        assert "Volumio Browse Results" in result.output
        # The URIs are printed by default: browsing deeper needs them
        assert "1. Music Library\n   music-library" in result.output
        assert "2. Web Radio\n   radio" in result.output

    def test_the_table_format_without_the_uris(self, runner: CliRunner, mocker: MockerFixture):
        """--no-print-uri leaves the URIs out of the table."""
        self._mock_client(mocker)

        result = runner.invoke(
            main, ["collection", "browse", "-F", "table", "--no-print-uri"]
        )

        assert result.exit_code == 0
        assert "1. Music Library\n2. Web Radio" in result.output

    def test_the_offset_reaches_the_client(self, runner: CliRunner, mocker: MockerFixture):
        """-o passes the offset to the client, which lets the host skip."""
        mock_client = self._mock_client(mocker)

        result = runner.invoke(main, ["collection", "browse", "music-library", "-o", "2"])

        assert result.exit_code == 0
        mock_client.browse.assert_called_once_with("music-library", 2)

    def test_a_negative_offset(self, runner: CliRunner, mocker: MockerFixture):
        """A negative offset is a usage error."""
        mock_client = self._mock_client(mocker)

        result = runner.invoke(main, ["collection", "browse", "-o", "-1"])

        assert result.exit_code == 2
        mock_client.browse.assert_not_called()

    def test_the_slow_endpoints_timeout_reaches_the_client(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """The global slow-endpoints timeout also reaches the fetching commands."""
        mock_client = mocker.Mock()
        mock_client.browse.return_value = BrowseResults.from_envelope(self.ENVELOPE)
        mock_class = mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient", return_value=mock_client
        )

        result = runner.invoke(
            main, ["--rest-api-timeout-slow-endpoints", "120", "collection", "browse"]
        )

        assert result.exit_code == 0
        assert mock_class.call_args.kwargs == {
            "timeout": 5.0,
            "timeout_slow_endpoints": 120.0,
            "logger": LOGGER,
        }

    def test_the_short_uri_flag_of_the_search_is_not_taken(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """The -u short form belongs to the search: the URIs are already on here."""
        mock_client = self._mock_client(mocker)

        result = runner.invoke(main, ["collection", "browse", "-u"])

        assert result.exit_code == 2
        mock_client.browse.assert_not_called()

    def test_the_table_format_with_the_info(self, runner: CliRunner, mocker: MockerFixture):
        """The entity being browsed follows the heading."""
        self._mock_client(mocker, self.ALBUM_ENVELOPE)

        result = runner.invoke(main, ["collection", "browse", "-F", "table"])

        assert result.exit_code == 0
        assert "==\nAguaplano - Paolo Conte\n" in result.output
        # The URI of the entity itself is not repeated: it is the URI browsed
        assert "\n  albums://Paolo%20Conte/Aguaplano" not in result.output

    def test_the_raw_format_is_the_payload_of_the_host(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """-F raw prints what the host answered, even when the results are limited."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["collection", "browse", "-l", "1", "-F", "raw"])

        assert result.exit_code == 0
        assert json.loads(result.output) == self.ENVELOPE

    def test_machine_readable(self, runner: CliRunner, mocker: MockerFixture):
        """Machine-readable mode prints the payload of the host, compact."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["-m", "collection", "browse"])

        assert result.exit_code == 0
        assert result.output.strip() == json.dumps(self.ENVELOPE)

    def test_the_json_format(self, runner: CliRunner, mocker: MockerFixture):
        """-F json prints the navigation with 2-space indentation."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["collection", "browse", "-F", "json"])

        assert result.exit_code == 0
        assert '\n  "lists"' in result.output

    def test_the_pretty_format(self, runner: CliRunner, mocker: MockerFixture):
        """-F pretty prints the navigation with 4-space indentation and sorted keys."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["collection", "browse", "-F", "pretty"])

        assert result.exit_code == 0
        assert '\n    "info"' in result.output
        assert json.loads(result.output)["prev"] == {"uri": "/"}

    def test_the_limit(self, runner: CliRunner, mocker: MockerFixture):
        """-l keeps at most that number of results in each list."""
        self._mock_client(mocker, self.ALBUM_ENVELOPE)

        result = runner.invoke(main, ["collection", "browse", "-l", "2", "-F", "json"])

        assert result.exit_code == 0
        assert [item["title"] for item in json.loads(result.output)["lists"][0]["items"]] == [
            "Aguaplano",
            "A Folder",
        ]

    def test_the_best_result_only(self, runner: CliRunner, mocker: MockerFixture):
        """-1 keeps the first result of each list, as --limit 1 does."""
        self._mock_client(mocker, self.ALBUM_ENVELOPE)

        result = runner.invoke(main, ["collection", "browse", "-1", "-F", "json"])

        assert result.exit_code == 0
        assert [item["title"] for item in json.loads(result.output)["lists"][0]["items"]] == [
            "Aguaplano"
        ]

    def test_the_best_result_only_with_a_limit(self, runner: CliRunner, mocker: MockerFixture):
        """The flag and the limit exclude each other."""
        mock_client = self._mock_client(mocker)

        result = runner.invoke(main, ["collection", "browse", "-1", "-l", "3"])

        assert result.exit_code == 2
        assert "not both" in result.output
        mock_client.browse.assert_not_called()

    @pytest.mark.parametrize(
        ("option", "titles"),
        [
            ("--tracks-only", ["Aguaplano", "Come Di"]),
            ("-T", ["Aguaplano", "Come Di"]),
            ("--result-kinds", None),
        ],
    )
    def test_the_kinds_are_kept(
        self, runner: CliRunner, mocker: MockerFixture, option, titles
    ):
        """A kind option keeps the results of that kind only."""
        self._mock_client(mocker, self.ALBUM_ENVELOPE)
        arguments = ["collection", "browse", "-F", "json", option]
        if option == "--result-kinds":
            arguments.append("track")
            titles = ["Aguaplano", "Come Di"]

        result = runner.invoke(main, arguments)

        assert result.exit_code == 0
        assert [item["title"] for item in json.loads(result.output)["lists"][0]["items"]] == titles

    def test_the_kind_options_must_agree(self, runner: CliRunner, mocker: MockerFixture):
        """Two options asking for different kinds refuse each other."""
        mock_client = self._mock_client(mocker)

        result = runner.invoke(main, ["collection", "browse", "-B", "-T"])

        assert result.exit_code == 2
        assert "agree on the kinds to keep" in result.output
        assert "--playlist," not in result.output
        mock_client.browse.assert_not_called()

    def test_an_unknown_result_kind(self, runner: CliRunner, mocker: MockerFixture):
        """A kind that does not exist is a usage error."""
        mock_client = self._mock_client(mocker)

        result = runner.invoke(main, ["collection", "browse", "-k", "song"])

        assert result.exit_code == 2
        assert "album, artist, other, playlist, track" in result.output
        mock_client.browse.assert_not_called()

    def test_the_format_comes_from_the_configuration(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """The collection-browse subsection sets the format of the command."""
        self._mock_client(mocker)
        configuration = tmp_path / "volumito.yaml"
        configuration.write_text(
            yaml.safe_dump({"output": {"collection-browse": {"format": "table"}}})
        )

        result = runner.invoke(
            main, ["--configuration-file", str(configuration), "collection", "browse"]
        )

        assert result.exit_code == 0
        assert "Volumio Browse Results" in result.output

    def test_a_connection_error(self, runner: CliRunner, mocker: MockerFixture):
        """A host that cannot be reached exits 1."""
        mock_client = mocker.Mock()
        mock_client.browse.side_effect = VolumioConnectionError("Connection failed")
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["collection", "browse"])

        assert result.exit_code == 1
        assert "[ERRO] Connection error" in result.output


class TestCollectionBrowseLastAndRoot:
    """Test cases for the --last and --root options of collection browse."""

    SOURCES = [
        {
            "name": "Music Library",
            "uri": "music-library",
            "plugin_type": "music_service",
            "plugin_name": "mpd",
            "albumart": "/albumart?sourceicon=music_service/mpd/musiclibraryicon.png",
        },
        {
            "name": "Web Radio",
            "uri": "radio",
            "plugin_type": "music_service",
            "plugin_name": "webradio",
        },
    ]
    """The browse sources, as a Volumio host answers them."""

    _REFUSAL = (
        "API client error: The Synchronous REST API client does not offer the collection "
        "extras: use --api-client synchronous_websocket or asynchronous_websocket, "
        "or --allow-fallback-to-websocket-api"
    )
    """The error of a REST API client asked for a collection extra, without the fallback."""

    _WEBSOCKET = ["-C", "synchronous_websocket"]
    """The global option selecting the WebSocket API client the options need."""

    @pytest.fixture
    def runner(self):
        """Create a CliRunner instance."""
        return CliRunner()

    def _mock_websocket_client(self, mocker: MockerFixture):
        """Mock VolumioWebSocketClient answering the last browse and the sources."""
        mock_client = mocker.Mock()
        mock_client.logger = LOGGER
        _attach_property(
            mock_client,
            "last_browse",
            return_value=BrowseResults.from_envelope(TestCollectionBrowse.ALBUM_ENVELOPE),
        )
        _attach_property(mock_client, "browse_sources", return_value={"sources": self.SOURCES})
        mocker.patch(
            "volumito.cli.click_helpers.VolumioWebSocketClient",
            return_value=mock_client,
        )
        return mock_client

    def test_last_prints_the_last_listing(self, runner: CliRunner, mocker: MockerFixture):
        """--last prints the listing the host pushed last, without browsing."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "collection", "browse", "--last", "-F", "json"]
        )

        assert result.exit_code == 0
        navigation = json.loads(result.output)
        assert navigation["info"]["title"] == "Aguaplano"
        assert len(navigation["lists"][0]["items"]) == 3
        mock_client.last_browse_property.assert_called_once()
        mock_client.browse.assert_not_called()

    def test_last_with_a_kind_filter(self, runner: CliRunner, mocker: MockerFixture):
        """The kind options act on the last listing too."""
        self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "collection", "browse", "--last", "-T", "-F", "json"]
        )

        assert result.exit_code == 0
        navigation = json.loads(result.output)
        assert [item["title"] for item in navigation["lists"][0]["items"]] == [
            "Aguaplano",
            "Come Di",
        ]

    def test_root_prints_the_sources_like_the_root(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """--root prints the browse sources as the root listing prints them."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "collection", "browse", "--root"])

        assert result.exit_code == 0
        lines = result.output.splitlines()
        assert "1. Music Library" in lines
        assert "   music-library" in lines
        assert "2. Web Radio" in lines
        mock_client.browse_sources_property.assert_called_once()
        mock_client.browse.assert_not_called()

    def test_root_raw_prints_the_sources_as_answered(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """-F raw prints the answer of the host, not the listing built from it."""
        self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "collection", "browse", "--root", "-F", "raw"]
        )

        assert result.exit_code == 0
        assert json.loads(result.output) == {"sources": self.SOURCES}

    @pytest.mark.parametrize(
        "arguments",
        [
            ["--last", "--root"],
            ["--last", "music-library"],
            ["--root", "music-library"],
            ["--last", "-o", "1"],
            ["--root", "-o", "1"],
        ],
    )
    def test_last_and_root_take_nothing_else(
        self, runner: CliRunner, mocker: MockerFixture, arguments
    ):
        """--last and --root refuse each other, the URI, and the offset."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "collection", "browse", *arguments])

        assert result.exit_code == 2
        assert (
            "Expected the -b/--current-track-album, -a/--current-track-artist, --last, and --root"
            in result.output
        )
        mock_client.browse.assert_not_called()

    @pytest.mark.parametrize("option", ["--last", "--root"])
    def test_a_rest_client_refuses(self, runner: CliRunner, mocker: MockerFixture, option):
        """With the default REST API client, the options fail naming the remedies."""
        mock_client = mocker.Mock()
        mock_client.logger = LOGGER
        mocker.patch("volumito.cli.click_helpers.VolumioRESTAPIClient", return_value=mock_client)

        result = runner.invoke(main, ["collection", "browse", option])

        assert result.exit_code == 1
        assert self._REFUSAL in result.output
        mock_client.browse.assert_not_called()


class TestCollectionCommands:
    """Test cases for the collection statistics command."""

    @pytest.fixture
    def runner(self):
        """Create a CliRunner instance."""
        return CliRunner()

    def _mock_client(self, mocker: MockerFixture):
        """Mock VolumioRESTAPIClient with a usable collection_statistics property."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "collection_statistics", return_value={
            "artists": 3,
            "albums": 4,
            "songs": 105,
            "playtime": "7:11:15",
        })
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        return mock_client

    def test_statistics(self, runner: CliRunner, mocker: MockerFixture):
        """collection statistics prints the collection statistics as pretty JSON."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["collection", "statistics"])

        assert result.exit_code == 0
        assert json.loads(result.output)["songs"] == 105

    def test_statistics_table(self, runner: CliRunner, mocker: MockerFixture):
        """collection statistics -F table prints a table with its heading."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["collection", "statistics", "-F", "table"])

        assert result.exit_code == 0
        assert "Collection Statistics" in result.output
        assert "Playtime" in result.output
        assert "7:11:15" in result.output

    def test_statistics_raw(self, runner: CliRunner, mocker: MockerFixture):
        """collection statistics -F raw prints compact JSON."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["collection", "statistics", "-F", "raw"])

        assert result.exit_code == 0
        assert "\n" not in result.output.strip()
        assert json.loads(result.output)["artists"] == 3

    def test_statistics_machine_readable(self, runner: CliRunner, mocker: MockerFixture):
        """In machine-readable mode collection statistics prints compact JSON."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["-m", "collection", "statistics"])

        assert result.exit_code == 0
        assert "\n" not in result.output.strip()
        assert json.loads(result.output)["albums"] == 4

    def test_statistics_connection_error(self, runner: CliRunner, mocker: MockerFixture):
        """collection statistics exits 1 on a connection error."""
        mock_client = self._mock_client(mocker)
        _attach_property(
            mock_client,
            "collection_statistics",
            side_effect=VolumioConnectionError("Connection failed"),
        )

        result = runner.invoke(main, ["collection", "statistics"])

        assert result.exit_code == 1
        assert "Connection error" in result.output


class TestCollectionExtras:
    """Test cases for collection browse --current-track-*, update, directory, source,
    and search --super."""

    MUSIC_SOURCES = {
        "plugins": [
            {
                "name": "mpd",
                "prettyName": "Music Library",
                "category": "music_service",
                "active": True,
                "enabled": True,
                "hasConfiguration": True,
                "icon": "fa-music",
            },
            {
                "name": "webradio",
                "prettyName": "Web Radio",
                "category": "music_service",
                "active": False,
                "enabled": False,
                "hasConfiguration": False,
                "icon": "fa-microphone",
            },
        ]
    }
    """The music sources, as a Volumio host answers them."""

    _REFUSAL = (
        "API client error: The Synchronous REST API client does not offer the collection "
        "extras: use --api-client synchronous_websocket or asynchronous_websocket, "
        "or --allow-fallback-to-websocket-api"
    )
    """The error of a REST API client asked for a collection extra, without the fallback."""

    _WEBSOCKET = ["-C", "synchronous_websocket"]
    """The global option selecting the WebSocket API client the commands need."""

    @pytest.fixture
    def runner(self):
        """Create a CliRunner instance."""
        return CliRunner()

    def _mock_rest_client(self, mocker: MockerFixture):
        """Mock VolumioRESTAPIClient, the default client, answering the state reads."""
        mock_client = mocker.Mock()
        mock_client.logger = LOGGER
        _attach_property(mock_client, "state", return_value={"artist": "Paolo Conte"})
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        return mock_client

    def _mock_websocket_client(self, mocker: MockerFixture, state: dict | None = None):
        """Mock VolumioWebSocketClient answering the goto, the sources, and the state."""
        mock_client = mocker.Mock()
        mock_client.logger = LOGGER
        mock_client.goto.return_value = BrowseResults.from_envelope(
            TestCollectionBrowse.ALBUM_ENVELOPE
        )
        mock_client.super_search.return_value = SearchResults.from_envelope(
            TestCollectionSearch.ENVELOPE
        )
        _attach_property(mock_client, "music_sources", return_value=self.MUSIC_SOURCES)
        _attach_property(
            mock_client,
            "state",
            return_value={"artist": "Paolo Conte", "album": "Aguaplano"} if state is None
            else state,
        )
        mocker.patch(
            "volumito.cli.click_helpers.VolumioWebSocketClient",
            return_value=mock_client,
        )
        return mock_client

    @pytest.mark.parametrize(
        ("option", "kind", "value"),
        [
            ("--current-track-artist", "artist", "Paolo Conte"),
            ("-a", "artist", "Paolo Conte"),
            ("--current-track-album", "album", "Aguaplano"),
            ("-b", "album", "Aguaplano"),
        ],
    )
    def test_browse_to_the_current_track(
        self, runner: CliRunner, mocker: MockerFixture, option, kind, value
    ):
        """The artist or the album of the current track is browsed to, as a browse prints."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "collection", "browse", option])

        assert result.exit_code == 0
        lines = result.output.splitlines()
        assert "1. Aguaplano - Paolo Conte" in lines
        assert "   music-library/INTERNAL/music/001___Aguaplano.flac" in lines
        mock_client.state_property.assert_called_once()
        mock_client.goto.assert_called_once_with(kind, value)
        mock_client.browse.assert_not_called()

    def test_browse_to_the_current_track_without_the_metadata(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """A current track without the album cannot be browsed to."""
        mock_client = self._mock_websocket_client(mocker, state={"title": "A stream"})

        result = runner.invoke(
            main, [*self._WEBSOCKET, "collection", "browse", "--current-track-album"]
        )

        assert result.exit_code == 1
        assert "The current track does not provide the album to browse to" in result.output
        mock_client.goto.assert_not_called()

    def test_browse_to_the_current_track_with_the_browse_options(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """The kind and limit options act on the listing, like on any browse."""
        self._mock_websocket_client(mocker)

        result = runner.invoke(
            main,
            [
                *self._WEBSOCKET,
                "collection",
                "browse",
                "--current-track-album",
                "-T",
                "-l",
                "1",
                "-F",
                "json",
            ],
        )

        assert result.exit_code == 0
        assert [item["title"] for item in json.loads(result.output)["lists"][0]["items"]] == [
            "Aguaplano"
        ]

    @pytest.mark.parametrize(
        "arguments",
        [
            ["--current-track-artist", "--current-track-album"],
            ["--current-track-artist", "--last"],
            ["--current-track-album", "--root"],
            ["music-library", "--current-track-artist"],
            ["--current-track-album", "-o", "2"],
        ],
    )
    def test_browse_to_the_current_track_alone(
        self, runner: CliRunner, mocker: MockerFixture, arguments
    ):
        """The current-track options stand alone, like --last and --root."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "collection", "browse", *arguments])

        assert result.exit_code == 2
        assert "Expected the -b/--current-track-album, -a/--current-track-artist" in result.output
        mock_client.goto.assert_not_called()

    @pytest.mark.parametrize(
        ("arguments", "member", "called_with", "label"),
        [
            ([], "update_library", (None,), "update library"),
            (["music-library"], "update_library", ("music-library",), "update library"),
            (["--rescan"], "rescan_library", (), "rescan library"),
            (["--thumbnails"], "regenerate_thumbnails", (), "regenerate thumbnails"),
        ],
    )
    def test_update(
        self, runner: CliRunner, mocker: MockerFixture, arguments, member, called_with, label
    ):
        """collection update refreshes the collection the way its options ask."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "collection", "update", *arguments])

        assert result.exit_code == 0
        assert f"Command '{label}' executed successfully" in result.output
        getattr(mock_client, member).assert_called_once_with(*called_with)

    def test_update_in_two_ways(self, runner: CliRunner, mocker: MockerFixture):
        """The refreshes are mutually exclusive."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "collection", "update", "--rescan", "--thumbnails"]
        )

        assert result.exit_code == 2
        assert "Expected at most one of the --rescan and --thumbnails" in result.output
        mock_client.update_library.assert_not_called()

    def test_update_a_uri_with_a_refresh(self, runner: CliRunner, mocker: MockerFixture):
        """Only the plain update takes a URI."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "collection", "update", "music-library", "--rescan"]
        )

        assert result.exit_code == 2
        assert "Expected the URI argument only without" in result.output
        mock_client.rescan_library.assert_not_called()

    def test_directory_delete_refused_without_yes(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """Without -y/--yes nothing is deleted."""
        mock_client = self._mock_websocket_client(mocker)
        uri = "music-library/INTERNAL/music/old"

        result = runner.invoke(
            main, [*self._WEBSOCKET, "collection", "directory", "delete", uri]
        )

        assert result.exit_code == 1
        assert f'Refusing to delete the directory without -y/--yes: "{uri}"' in result.output
        mock_client.delete_folder.assert_not_called()

    def test_directory_delete(self, runner: CliRunner, mocker: MockerFixture):
        """With -y/--yes the directory is deleted, by its URI."""
        mock_client = self._mock_websocket_client(mocker)
        uri = "music-library/INTERNAL/music/old"

        result = runner.invoke(
            main, [*self._WEBSOCKET, "collection", "directory", "delete", uri, "-y"]
        )

        assert result.exit_code == 0
        assert f"Command 'delete directory \"{uri}\"' executed successfully" in result.output
        mock_client.delete_folder.assert_called_once_with(uri)
        # The library is then updated at the directory above, so the listing follows
        parent = "music-library/INTERNAL/music"
        assert f"Command 'update library \"{parent}\"' executed successfully" in result.output
        mock_client.update_library.assert_called_once_with(parent)

    def test_directory_delete_without_the_update(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """--no-update-library leaves the library as it is after the deletion."""
        mock_client = self._mock_websocket_client(mocker)
        uri = "music-library/INTERNAL/music/old"

        result = runner.invoke(
            main,
            [
                *self._WEBSOCKET,
                "collection",
                "directory",
                "delete",
                uri,
                "-y",
                "--no-update-library",
            ],
        )

        assert result.exit_code == 0
        mock_client.delete_folder.assert_called_once_with(uri)
        mock_client.update_library.assert_not_called()

    def test_source_list_default_short_fields(self, runner: CliRunner, mocker: MockerFixture):
        """collection source list prints the short fields of each source as pretty JSON."""
        self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "collection", "source", "list"])

        assert result.exit_code == 0
        sources = json.loads(result.output)
        assert [source["name"] for source in sources] == ["mpd", "webradio"]
        assert sources[0]["prettyName"] == "Music Library"
        assert sources[0]["enabled"] is True
        assert "icon" not in sources[0]

    def test_source_list_all_fields(self, runner: CliRunner, mocker: MockerFixture):
        """-L ALL keeps every field of each source."""
        self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "collection", "source", "list", "-L", "ALL", "-F", "json"]
        )

        assert result.exit_code == 0
        assert json.loads(result.output)[0]["icon"] == "fa-music"

    def test_source_list_table(self, runner: CliRunner, mocker: MockerFixture):
        """-F table numbers the sources under the heading, with their fields."""
        self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "collection", "source", "list", "-F", "table"]
        )

        assert result.exit_code == 0
        lines = result.output.splitlines()
        assert "Volumio Music Sources" in lines
        assert "1. mpd" in lines
        assert "   Pretty Name      : Music Library" in lines
        assert "2. webradio" in lines

    def test_source_list_raw(self, runner: CliRunner, mocker: MockerFixture):
        """-F raw prints the answer of the host as it is."""
        self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, ["-m", *self._WEBSOCKET, "collection", "source", "list", "-F", "raw"]
        )

        assert result.exit_code == 0
        assert json.loads(result.output) == self.MUSIC_SOURCES

    def test_source_list_fields_from_the_configuration(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """The collection-source-list subsection sets the default fields."""
        self._mock_websocket_client(mocker)
        config = tmp_path / "volumito.yaml"
        config.write_text("output:\n  collection-source-list:\n    fields: name\n")

        result = runner.invoke(
            main, ["-c", str(config), *self._WEBSOCKET, "collection", "source", "list"]
        )

        assert result.exit_code == 0
        assert json.loads(result.output) == [{"name": "mpd"}, {"name": "webradio"}]

    @pytest.mark.parametrize(("command", "enabled"), [("enable", True), ("disable", False)])
    def test_source_enable_and_disable(
        self, runner: CliRunner, mocker: MockerFixture, command, enabled
    ):
        """collection source enable/disable set the flag of the named source."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "collection", "source", command, "qobuz"])

        assert result.exit_code == 0
        assert f"Command '{command} source \"qobuz\"' executed successfully" in result.output
        mock_client.set_music_source_enabled.assert_called_once_with("qobuz", enabled)

    def test_search_super(self, runner: CliRunner, mocker: MockerFixture):
        """--super searches every source at once, keeping the other options."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main,
            [*self._WEBSOCKET, "collection", "search", "paolo conte", "--super", "-A",
             "-F", "json"],
        )

        assert result.exit_code == 0
        lists = json.loads(result.output)
        assert [item["title"] for result_list in lists for item in result_list["items"]] == [
            "Paolo Conte"
        ]
        mock_client.super_search.assert_called_once_with("paolo conte")
        mock_client.search.assert_not_called()

    @pytest.mark.parametrize(
        "arguments",
        [
            ["browse", "--current-track-artist"],
            ["update"],
            ["update", "--rescan"],
            ["directory", "delete", "music-library/INTERNAL/music/old", "-y"],
            ["source", "list"],
            ["source", "enable", "qobuz"],
            ["search", "paolo conte", "--super"],
        ],
    )
    def test_a_rest_client_refuses(self, runner: CliRunner, mocker: MockerFixture, arguments):
        """With the default REST API client, the commands fail naming the remedies."""
        self._mock_rest_client(mocker)

        result = runner.invoke(main, ["collection", *arguments])

        assert result.exit_code == 1
        assert self._REFUSAL in result.output

    def test_a_rest_client_falls_back_when_allowed(self, runner: CliRunner, mocker: MockerFixture):
        """With the switch, the REST API client serves the command through a WebSocket one."""
        rest = self._mock_rest_client(mocker)
        websocket = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, ["--allow-fallback-to-websocket-api", "collection", "update", "--thumbnails"]
        )

        assert result.exit_code == 0
        assert "Falling back to the WebSocket API client for the collection extras" in (
            result.output
        )
        websocket.regenerate_thumbnails.assert_called_once_with()
        websocket.disconnect.assert_called_once_with()
        rest.close.assert_called_once_with()


class TestCollectionFavouriteAndRadio:
    """Test cases for the collection favourite and collection radio subgroups."""

    ENVELOPE = {
        "navigation": {
            "lists": [
                {
                    "items": [
                        {
                            "service": "webradio",
                            "type": "webradio",
                            "title": "Radio Uno",
                            "uri": "http://radio.example/uno",
                        },
                        {
                            "service": "webradio",
                            "type": "webradio",
                            "title": "Radio Due",
                            "uri": "http://radio.example/due",
                        },
                    ],
                }
            ],
            "prev": {"uri": "radio"},
        }
    }
    """A payload of the shape a browse of the Web radios is answered with."""

    _REFUSAL = (
        "API client error: The Synchronous REST API client does not offer the favourites "
        "and the web radios: use --api-client synchronous_websocket or "
        "asynchronous_websocket, or --allow-fallback-to-websocket-api"
    )
    """The error of a REST API client asked for a favourite edit, without the fallback."""

    _STREAM = "http://radio.example/tre"
    """The URL a Web radio streams from."""

    _URI = "albums://Paolo%20Conte/Aguaplano"
    """A URI of the kind a browse or a search prints."""

    _WEBSOCKET = ["-C", "synchronous_websocket"]
    """The global option selecting the WebSocket API client the edits need."""

    @pytest.fixture
    def runner(self):
        """Create a CliRunner instance."""
        return CliRunner()

    def _mock_rest_client(self, mocker: MockerFixture):
        """Mock VolumioRESTAPIClient, the default client, answering the browses."""
        mock_client = mocker.Mock()
        mock_client.logger = LOGGER
        mock_client.browse.return_value = BrowseResults.from_envelope(self.ENVELOPE)
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        return mock_client

    def _mock_websocket_client(self, mocker: MockerFixture):
        """Mock VolumioWebSocketClient answering the browses and the state reads."""
        mocker.patch("volumito.cli.click_helpers.time.sleep")
        mock_client = mocker.Mock()
        mock_client.logger = LOGGER
        mock_client.browse.return_value = BrowseResults.from_envelope(self.ENVELOPE)
        _attach_property(
            mock_client,
            "state",
            return_value={"title": "Test Song", "artist": "StatusMarkerArtist"},
        )
        mocker.patch(
            "volumito.cli.click_helpers.VolumioWebSocketClient",
            return_value=mock_client,
        )
        mocker.patch("volumito.cli.click_helpers.time.sleep")
        return mock_client

    @pytest.mark.parametrize(
        ("arguments", "uri"),
        [
            (["favourite", "list"], "favourites"),
            (["favourite", "list", "--radio"], "radio/favourites"),
            (["radio", "list"], "radio/myWebRadio"),
        ],
    )
    def test_the_lists_browse_their_uri(
        self, runner: CliRunner, mocker: MockerFixture, arguments, uri
    ):
        """Each list browses the URI of what it lists, over any client, as a table."""
        mock_client = self._mock_rest_client(mocker)

        result = runner.invoke(main, ["collection", *arguments])

        assert result.exit_code == 0
        mock_client.browse.assert_called_once_with(uri, None)
        lines = result.output.splitlines()
        assert "1. Radio Uno" in lines
        assert "   http://radio.example/uno" in lines
        assert "2. Radio Due" in lines

    @pytest.mark.parametrize(
        ("arguments", "uri"),
        [(["favourite", "list"], "favourites"), (["radio", "list"], "radio/myWebRadio")],
    )
    def test_a_list_with_the_browse_options(
        self, runner: CliRunner, mocker: MockerFixture, arguments, uri
    ):
        """The offset reaches the host, the limit applies after, the URIs can be dropped."""
        mock_client = self._mock_rest_client(mocker)

        result = runner.invoke(
            main, ["collection", *arguments, "-o", "2", "-l", "1", "--no-print-uri"]
        )

        assert result.exit_code == 0
        mock_client.browse.assert_called_once_with(uri, 2)
        lines = result.output.splitlines()
        assert "1. Radio Uno" in lines
        assert "2. Radio Due" not in lines
        assert "http://radio.example/uno" not in result.output

    def test_a_list_as_json(self, runner: CliRunner, mocker: MockerFixture):
        """-F json prints the navigation, like collection browse does."""
        self._mock_rest_client(mocker)

        result = runner.invoke(main, ["collection", "radio", "list", "-F", "json"])

        assert result.exit_code == 0
        navigation = json.loads(result.output)
        assert [item["title"] for item in navigation["lists"][0]["items"]] == [
            "Radio Uno",
            "Radio Due",
        ]
        assert navigation["prev"] == {"uri": "radio"}

    def test_a_list_format_from_the_configuration(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """The collection-favourite-list subsection sets the default format."""
        self._mock_rest_client(mocker)
        config = tmp_path / "volumito.yaml"
        config.write_text("output:\n  collection-favourite-list:\n    format: raw\n")

        result = runner.invoke(main, ["-c", str(config), "collection", "favourite", "list"])

        assert result.exit_code == 0
        assert json.loads(result.output) == self.ENVELOPE

    @pytest.mark.parametrize(
        ("options", "details"),
        [
            ([], (None, None, None)),
            (
                ["--title", "T", "--service", "mpd", "--albumart", "http://a"],
                ("T", "mpd", "http://a"),
            ),
        ],
    )
    def test_favourite_add(self, runner: CliRunner, mocker: MockerFixture, options, details):
        """collection favourite add adds the URI, with the details given."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "collection", "favourite", "add", self._URI, *options]
        )

        assert result.exit_code == 0
        assert f"Command 'add favourite \"{self._URI}\"' executed successfully" in result.output
        mock_client.add_to_favourites.assert_called_once_with(self._URI, *details)
        mock_client.add_radio_favourite.assert_not_called()
        mock_client.browse.assert_not_called()

    @pytest.mark.parametrize(
        ("radio", "options", "title"),
        [
            ("Radio Uno", [], "Radio Uno"),
            ("http://radio.example/uno", [], "Radio Uno"),
            ("Radio Uno", ["--title", "Uno!"], "Uno!"),
        ],
    )
    def test_favourite_add_radio(
        self, runner: CliRunner, mocker: MockerFixture, radio, options, title
    ):
        """--radio adds a Web radio of the host, by name or URL, with its name and logo."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main,
            [*self._WEBSOCKET, "collection", "favourite", "add", radio, "--radio", *options],
        )

        assert result.exit_code == 0
        assert "Command 'add radio favourite \"http://radio.example/uno\"'" in result.output
        mock_client.add_radio_favourite.assert_called_once_with(
            "http://radio.example/uno", title, None
        )
        mock_client.add_to_favourites.assert_not_called()
        # The Web radios of the host resolve the radio, the radio favourites confirm it
        assert mock_client.browse.call_args_list == [
            mocker.call("radio/myWebRadio"),
            mocker.call("radio/favourites"),
        ]

    def test_favourite_add_radio_by_url(self, runner: CliRunner, mocker: MockerFixture):
        """A Web radio the host does not list is added by URL, with its title and logo."""
        mock_client = self._mock_websocket_client(mocker)
        listed = {
            "navigation": {
                "lists": [{"items": [{"service": "webradio", "uri": self._STREAM}]}]
            }
        }
        mock_client.browse.side_effect = [
            BrowseResults.from_envelope(self.ENVELOPE),
            BrowseResults.from_envelope(listed),
        ]

        result = runner.invoke(
            main,
            [*self._WEBSOCKET, "collection", "favourite", "add", self._STREAM, "--radio",
             "--title", "Radio Tre", "--albumart", "http://logo/tre"],
        )

        assert result.exit_code == 0
        assert f"Command 'add radio favourite \"{self._STREAM}\"'" in result.output
        mock_client.add_radio_favourite.assert_called_once_with(
            self._STREAM, "Radio Tre", "http://logo/tre"
        )

    def test_favourite_add_radio_not_listed_afterwards(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """A Web radio the host does not list after the add is reported."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main,
            [*self._WEBSOCKET, "collection", "favourite", "add", self._STREAM, "--radio",
             "--title", "Radio Tre"],
        )

        assert result.exit_code == 1
        assert f'does not list "{self._STREAM}" among its radio favourites' in result.output
        mock_client.add_radio_favourite.assert_called_once_with(self._STREAM, "Radio Tre", None)

    def test_favourite_add_radio_without_a_title(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """A Web radio the host does not list needs a title."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main,
            [*self._WEBSOCKET, "collection", "favourite", "add", self._STREAM, "--radio"],
        )

        assert result.exit_code == 2
        assert "Expected the --title option with --radio" in result.output
        mock_client.add_radio_favourite.assert_not_called()

    def test_favourite_add_radio_with_a_service(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """A Web radio takes no service."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main,
            [*self._WEBSOCKET, "collection", "favourite", "add", self._STREAM, "--radio",
             "--service", "mpd"],
        )

        assert result.exit_code == 2
        assert "Expected the --service option only without --radio" in result.output
        mock_client.add_radio_favourite.assert_not_called()

    def test_favourite_play(self, runner: CliRunner, mocker: MockerFixture):
        """collection favourite play starts the favourites from the named one."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main,
            [*self._WEBSOCKET, "collection", "favourite", "play", "Favourite Song",
             "--no-print-resulting-status"],
        )

        assert result.exit_code == 0
        assert "Command 'play favourites' executed successfully" in result.output
        mock_client.play_favourites.assert_called_once_with("Favourite Song")
        mock_client.play_radio_favourites.assert_not_called()
        mock_client.state_property.assert_not_called()

    def test_favourite_play_without_a_name(self, runner: CliRunner, mocker: MockerFixture):
        """The favourites play from a named one only."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "collection", "favourite", "play"])

        assert result.exit_code == 2
        assert "Expected the NAME argument without --radio" in result.output
        mock_client.play_favourites.assert_not_called()

    def test_favourite_play_prints_the_resulting_status(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """By default the resulting playback status is printed."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "collection", "favourite", "play", "Favourite Song"]
        )

        assert result.exit_code == 0
        assert "StatusMarkerArtist" in result.output
        mock_client.state_property.assert_called_once()

    def test_favourite_play_radio(self, runner: CliRunner, mocker: MockerFixture):
        """--radio starts the radio favourites."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main,
            [*self._WEBSOCKET, "collection", "favourite", "play", "--radio",
             "--no-print-resulting-status"],
        )

        assert result.exit_code == 0
        assert "Command 'play radio favourites' executed successfully" in result.output
        mock_client.play_radio_favourites.assert_called_once_with()
        mock_client.play_favourites.assert_not_called()

    @pytest.mark.parametrize("radio", ["Radio Due", "http://radio.example/due"])
    def test_favourite_play_radio_with_a_name(
        self, runner: CliRunner, mocker: MockerFixture, radio
    ):
        """--radio NAME plays the radio favourites from the one named, or streaming from."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main,
            [*self._WEBSOCKET, "collection", "favourite", "play", radio, "--radio",
             "--no-print-resulting-status"],
        )

        assert result.exit_code == 0
        assert f"Command 'play radio favourite \"{radio}\"' executed successfully" in (
            result.output
        )
        mock_client.browse.assert_called_once_with("radio/favourites")
        mock_client.replace_queue_and_play.assert_called_once_with("radio/favourites", 1)
        mock_client.play_radio_favourites.assert_not_called()

    def test_favourite_play_radio_unknown(self, runner: CliRunner, mocker: MockerFixture):
        """A radio the host lists among no radio favourites is reported, and not played."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main,
            [*self._WEBSOCKET, "collection", "favourite", "play", self._STREAM, "--radio"],
        )

        assert result.exit_code == 1
        assert f'lists no radio favourite named, or streaming from, "{self._STREAM}"' in (
            result.output
        )
        mock_client.replace_queue_and_play.assert_not_called()
        mock_client.play_radio_favourites.assert_not_called()

    @pytest.mark.parametrize(("options", "service"), [([], None), (["--service", "mpd"], "mpd")])
    def test_favourite_remove(self, runner: CliRunner, mocker: MockerFixture, options, service):
        """collection favourite remove drops the URI, of the given service."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main,
            [*self._WEBSOCKET, "collection", "favourite", "remove", self._URI, *options],
        )

        assert result.exit_code == 0
        assert f"Command 'remove favourite \"{self._URI}\"' executed" in result.output
        mock_client.remove_from_favourites.assert_called_once_with(self._URI, service)
        mock_client.remove_radio_favourite.assert_not_called()
        # The favourites are read again, to check that the item is gone
        mock_client.browse.assert_called_once_with("favourites")

    @pytest.mark.parametrize(
        ("uri", "listed"),
        [
            ("qobuz://track/3", "qobuz://track/3"),
            ("music-library/INTERNAL/a.flac", "mnt/INTERNAL/a.flac"),
        ],
    )
    def test_favourite_remove_still_listed(
        self, runner: CliRunner, mocker: MockerFixture, uri, listed
    ):
        """A favourite the host still lists after the removal is reported."""
        mock_client = self._mock_websocket_client(mocker)
        mock_client.browse.return_value = BrowseResults.from_envelope(
            {"navigation": {"lists": [{"items": [{"service": "x", "uri": listed}]}]}}
        )

        result = runner.invoke(
            main, [*self._WEBSOCKET, "collection", "favourite", "remove", uri]
        )

        assert result.exit_code == 1
        assert f'The Volumio host still lists "{uri}" among its favourites' in result.output
        mock_client.remove_from_favourites.assert_called_once_with(uri, None)

    @pytest.mark.parametrize("radio", ["Radio Due", "http://radio.example/due"])
    def test_favourite_remove_radio(self, runner: CliRunner, mocker: MockerFixture, radio):
        """--radio drops a radio favourite, by name or URL, checking that it is gone."""
        mock_client = self._mock_websocket_client(mocker)
        remaining = {
            "navigation": {
                "lists": [{"items": [self.ENVELOPE["navigation"]["lists"][0]["items"][0]]}]
            }
        }
        mock_client.browse.side_effect = [
            BrowseResults.from_envelope(self.ENVELOPE),
            BrowseResults.from_envelope(remaining),
        ]

        result = runner.invoke(
            main, [*self._WEBSOCKET, "collection", "favourite", "remove", radio, "--radio"]
        )

        assert result.exit_code == 0
        assert "Command 'remove radio favourite \"http://radio.example/due\"'" in result.output
        mock_client.remove_radio_favourite.assert_called_once_with("http://radio.example/due")
        mock_client.remove_from_favourites.assert_not_called()
        assert mock_client.browse.call_args_list == [
            mocker.call("radio/favourites"),
            mocker.call("radio/favourites"),
        ]

    def test_favourite_remove_radio_still_listed(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """A radio favourite the host still lists after the removal is reported."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main,
            [*self._WEBSOCKET, "collection", "favourite", "remove", "Radio Due", "--radio"],
        )

        assert result.exit_code == 1
        assert 'still lists "http://radio.example/due" among its favourites' in result.output
        mock_client.remove_radio_favourite.assert_called_once_with("http://radio.example/due")

    def test_favourite_remove_radio_unknown(self, runner: CliRunner, mocker: MockerFixture):
        """A radio the host lists among no radio favourites is reported, and not removed."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main,
            [*self._WEBSOCKET, "collection", "favourite", "remove", self._STREAM, "--radio"],
        )

        assert result.exit_code == 1
        assert f'lists no radio favourite named, or streaming from, "{self._STREAM}"' in (
            result.output
        )
        mock_client.remove_radio_favourite.assert_not_called()

    def test_favourite_remove_radio_with_a_service(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """A Web radio takes no service."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main,
            [*self._WEBSOCKET, "collection", "favourite", "remove", self._STREAM, "--radio",
             "--service", "webradio"],
        )

        assert result.exit_code == 2
        assert "Expected the --service option only without --radio" in result.output
        mock_client.remove_radio_favourite.assert_not_called()

    def test_radio_add(self, runner: CliRunner, mocker: MockerFixture):
        """collection radio add saves the stream URL under the name."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "collection", "radio", "add", "Radio Tre", self._STREAM]
        )

        assert result.exit_code == 0
        assert "Command 'add web radio \"Radio Tre\"' executed successfully" in result.output
        # The Web radios are then listed, as "collection radio list" lists them
        assert "1. Radio Uno" in result.output
        mock_client.add_web_radio.assert_called_once_with("Radio Tre", self._STREAM)
        mock_client.browse.assert_called_once_with("radio/myWebRadio")

    def test_radio_add_without_the_list(self, runner: CliRunner, mocker: MockerFixture):
        """--no-print-resulting-list skips the listing after the save."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main,
            [
                *self._WEBSOCKET,
                "collection",
                "radio",
                "add",
                "Radio Tre",
                self._STREAM,
                "--no-print-resulting-list",
            ],
        )

        assert result.exit_code == 0
        assert "Radio Uno" not in result.output
        mock_client.browse.assert_not_called()

    def test_radio_remove(self, runner: CliRunner, mocker: MockerFixture):
        """collection radio remove deletes the Web radio saved under the name."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "collection", "radio", "remove", "Radio Tre"]
        )

        assert result.exit_code == 0
        assert "Command 'remove web radio \"Radio Tre\"' executed successfully" in result.output
        mock_client.remove_web_radio.assert_called_once_with("Radio Tre")
        # The Web radios are read again to check that the radio is gone, then listed
        assert mock_client.browse.call_count == 2
        assert "1. Radio Uno" in result.output

    def test_radio_remove_without_the_list(self, runner: CliRunner, mocker: MockerFixture):
        """--no-print-resulting-list keeps the check, and skips the listing."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main,
            [
                *self._WEBSOCKET,
                "collection",
                "radio",
                "remove",
                "Radio Tre",
                "--no-print-resulting-list",
            ],
        )

        assert result.exit_code == 0
        assert "Radio Uno" not in result.output
        # The check still reads the Web radios once
        mock_client.browse.assert_called_once_with("radio/myWebRadio")

    def test_radio_remove_still_listed(self, runner: CliRunner, mocker: MockerFixture):
        """A Web radio the host still lists after the removal is reported."""
        mock_client = self._mock_websocket_client(mocker)
        mock_client.browse.return_value = BrowseResults.from_envelope(
            {
                "navigation": {
                    "lists": [
                        {
                            "items": [
                                {
                                    "service": "webradio",
                                    "type": "mywebradio",
                                    "title": "Radio Tre",
                                    "uri": self._STREAM,
                                }
                            ]
                        }
                    ]
                }
            }
        )

        result = runner.invoke(
            main, [*self._WEBSOCKET, "collection", "radio", "remove", "Radio Tre"]
        )

        assert result.exit_code == 1
        assert (
            'The Volumio host still lists the Web radio "Radio Tre" after the removal'
            in result.output
        )
        mock_client.remove_web_radio.assert_called_once_with("Radio Tre")
        # No listing follows a failed removal
        mock_client.browse.assert_called_once_with("radio/myWebRadio")

    @pytest.mark.parametrize(
        "arguments",
        [
            ["favourite", "add", _URI],
            ["favourite", "add", "Radio Uno", "--radio"],
            ["favourite", "play", "Favourite Song", "--no-print-resulting-status"],
            ["favourite", "play", "--radio", "--no-print-resulting-status"],
            ["favourite", "remove", _URI],
            ["favourite", "remove", "Radio Uno", "--radio"],
            ["radio", "add", "Radio Tre", _STREAM],
            ["radio", "remove", "Radio Tre"],
        ],
    )
    def test_a_rest_client_refuses(self, runner: CliRunner, mocker: MockerFixture, arguments):
        """With the default REST API client, the edits fail naming the remedies."""
        self._mock_rest_client(mocker)

        result = runner.invoke(main, ["collection", *arguments])

        assert result.exit_code == 1
        assert self._REFUSAL in result.output

    def test_a_rest_client_falls_back_when_allowed(self, runner: CliRunner, mocker: MockerFixture):
        """With the switch, the REST API client serves the edit through a WebSocket one."""
        rest = self._mock_rest_client(mocker)
        websocket = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main,
            ["--allow-fallback-to-websocket-api", "collection", "radio", "add", "Radio Tre",
             self._STREAM],
        )

        assert result.exit_code == 0
        assert (
            "Falling back to the WebSocket API client for the favourites and the web radios"
        ) in result.output
        websocket.add_web_radio.assert_called_once_with("Radio Tre", self._STREAM)
        websocket.disconnect.assert_called_once_with()
        rest.close.assert_called_once_with()


class TestCollectionSearch:
    """Test cases for the collection search command."""

    ENVELOPE = {
        "navigation": {
            "isSearchResult": True,
            "lists": [
                {
                    "title": "Found 1 Artist 'paolo conte'",
                    "items": [
                        {
                            "service": "mpd",
                            "type": "folder",
                            "title": "Paolo Conte",
                            "uri": "artists://Paolo%20Conte",
                        }
                    ],
                },
                {
                    "title": "QOBUZ Playlists",
                    "items": [
                        {
                            "service": "qobuz",
                            "type": "folder-with-favourites",
                            "title": "Paolo Conte Essentials",
                            "uri": "qobuz://playlist/13980206",
                        }
                    ],
                },
            ],
        }
    }

    ENVELOPE_OF_A_LONG_LIST = {
        "navigation": {
            "isSearchResult": True,
            "lists": [
                {
                    "title": "QOBUZ Tracks",
                    "items": [
                        {"service": "qobuz", "type": "song", "title": "Aguaplano"},
                        {"service": "qobuz", "type": "song", "title": "Come Di"},
                        {"service": "qobuz", "type": "song", "title": "Sotto le stelle del jazz"},
                    ],
                },
            ],
        }
    }
    """A payload whose list carries more results than a limit keeps."""

    ENVELOPE_OF_EVERY_KIND = {
        "navigation": {
            "isSearchResult": True,
            "lists": [
                {
                    "title": "Everything",
                    "items": [
                        {
                            "service": "mpd",
                            "type": "folder",
                            "title": "An Artist",
                            "uri": "artists://An%20Artist",
                        },
                        {
                            "service": "mpd",
                            "type": "folder",
                            "title": "An Album",
                            "artist": "Enzo Jannacci",
                            "uri": "albums://Enzo%20Jannacci/An%20Album",
                        },
                        {
                            "service": "qobuz",
                            "type": "folder-with-favourites",
                            "title": "A Playlist",
                            "uri": "qobuz://playlist/1",
                        },
                        {
                            "service": "qobuz",
                            "type": "song",
                            "title": "A Track",
                            "uri": "qobuz://song/1",
                        },
                        {
                            "service": "webradio",
                            "type": "webradio",
                            "title": "A Radio",
                            "uri": "http://opml.radiotime.com/Tune.ashx?id=1",
                        },
                    ],
                },
            ],
        }
    }
    """A payload carrying one result of each kind."""

    @pytest.fixture
    def runner(self):
        """Create a CliRunner instance."""
        return CliRunner()

    def _mock_client(self, mocker: MockerFixture, envelope: dict | None = None):
        """Mock VolumioRESTAPIClient with a prepared search result."""
        mock_client = mocker.Mock()
        mock_client.search.return_value = SearchResults.from_envelope(envelope or self.ENVELOPE)
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        return mock_client

    def test_searches_for_the_query(self, runner: CliRunner, mocker: MockerFixture):
        """The query argument is what the host is asked for."""
        mock_client = self._mock_client(mocker)

        result = runner.invoke(main, ["collection", "search", "Paolo Conte", "-F", "json"])

        assert result.exit_code == 0
        mock_client.search.assert_called_once_with("Paolo Conte")
        assert [block["title"] for block in json.loads(result.output)] == [
            "Found 1 Artist 'paolo conte'",
            "QOBUZ Playlists",
        ]

    def test_the_query_is_composed_from_the_options(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """Without a query, the text of the options is what is searched for."""
        mock_client = self._mock_client(mocker)

        result = runner.invoke(
            main, ["collection", "search", "-a", "Paolo Conte", "-t", "Aguaplano"]
        )

        assert result.exit_code == 0
        mock_client.search.assert_called_once_with("Paolo Conte Aguaplano")

    def test_nothing_to_search_for(self, runner: CliRunner, mocker: MockerFixture):
        """Without a query and without any text option, the command says what it expects."""
        mock_client = self._mock_client(mocker)

        result = runner.invoke(main, ["collection", "search"])

        assert result.exit_code == 2
        assert "Expected a QUERY argument" in result.output
        mock_client.search.assert_not_called()

    def test_filtered_by_service(self, runner: CliRunner, mocker: MockerFixture):
        """The service option keeps the results of that source only."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["collection", "search", "Paolo", "-s", "mpd", "-F", "json"])

        assert result.exit_code == 0
        assert [block["title"] for block in json.loads(result.output)] == [
            "Found 1 Artist 'paolo conte'"
        ]

    def test_an_unknown_service(self, runner: CliRunner, mocker: MockerFixture):
        """Only the services the tool knows are accepted."""
        mock_client = self._mock_client(mocker)

        result = runner.invoke(main, ["collection", "search", "Paolo", "--service", "spotify"])

        assert result.exit_code == 2
        assert (
            "'spotify' is not one of 'highresaudio', 'mpd', 'qobuz', 'soundcloud', 'spop', "
            "'tidal', 'webradio', 'youtube2'" in result.output
        )
        mock_client.search.assert_not_called()

    def test_the_playlists_only(self, runner: CliRunner, mocker: MockerFixture):
        """--playlists-only keeps the playlists, whatever the other options match."""
        mock_client = self._mock_client(mocker)

        result = runner.invoke(
            main,
            [
                "collection",
                "search",
                "--artist",
                "Paolo Conte",
                "--service",
                "qobuz",
                "--playlists-only",
                "-F",
                "json",
            ],
        )

        assert result.exit_code == 0
        # The artist still says what to search for, but only the playlists are kept
        mock_client.search.assert_called_once_with("Paolo Conte")
        assert [block["title"] for block in json.loads(result.output)] == ["QOBUZ Playlists"]

    def test_a_playlist_query(self, runner: CliRunner, mocker: MockerFixture):
        """--playlist searches for its text and keeps every playlist found for it."""
        mock_client = self._mock_client(mocker)

        # A source answers with the playlists it finds related to the query, whose
        # titles rarely carry it, so they are kept whatever they are called
        result = runner.invoke(main, ["collection", "search", "-y", "Mango", "-F", "json"])

        assert result.exit_code == 0
        mock_client.search.assert_called_once_with("Mango")
        assert [block["title"] for block in json.loads(result.output)] == ["QOBUZ Playlists"]
        assert json.loads(result.output)[0]["items"][0]["title"] == "Paolo Conte Essentials"

    def test_the_table_format(self, runner: CliRunner, mocker: MockerFixture):
        """-F table prints the lists with their numbered items."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["collection", "search", "Paolo", "-F", "table"])

        assert result.exit_code == 0
        assert "Volumio Search Results" in result.output
        assert "MPD Artists" in result.output
        assert "1. Paolo Conte" in result.output

    def test_the_table_format_without_a_result(self, runner: CliRunner, mocker: MockerFixture):
        """A filter matching nothing prints an empty table."""
        self._mock_client(mocker)

        result = runner.invoke(
            main, ["collection", "search", "Paolo", "--track", "nothing", "-F", "table"]
        )

        assert result.exit_code == 0
        assert "(no result)" in result.output

    def test_the_json_format(self, runner: CliRunner, mocker: MockerFixture):
        """-F json prints the lists with 2-space indentation."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["collection", "search", "Paolo", "-F", "json"])

        assert result.exit_code == 0
        assert '\n    "title"' in result.output

    def test_the_pretty_format(self, runner: CliRunner, mocker: MockerFixture):
        """-F pretty prints the lists with 4-space indentation and sorted keys."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["collection", "search", "Paolo", "-F", "pretty"])

        assert result.exit_code == 0
        assert '\n        "items"' in result.output
        assert [block["title"] for block in json.loads(result.output)] == [
            "Found 1 Artist 'paolo conte'",
            "QOBUZ Playlists",
        ]

    def test_the_raw_format_is_the_payload_of_the_host(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """-F raw prints what the host answered, even when the results are filtered."""
        self._mock_client(mocker)

        result = runner.invoke(
            main, ["collection", "search", "Paolo", "--service", "mpd", "-F", "raw"]
        )

        assert result.exit_code == 0
        assert json.loads(result.output) == self.ENVELOPE

    def test_machine_readable(self, runner: CliRunner, mocker: MockerFixture):
        """Machine-readable mode prints the payload of the host, compact."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["-m", "collection", "search", "Paolo"])

        assert result.exit_code == 0
        assert result.output.strip() == json.dumps(self.ENVELOPE)

    def test_the_limit(self, runner: CliRunner, mocker: MockerFixture):
        """-l keeps at most that number of results in each list."""
        self._mock_client(mocker, self.ENVELOPE_OF_A_LONG_LIST)

        result = runner.invoke(main, ["collection", "search", "Paolo", "-l", "2", "-F", "json"])

        assert result.exit_code == 0
        assert [item["title"] for item in json.loads(result.output)[0]["items"]] == [
            "Aguaplano",
            "Come Di",
        ]

    def test_the_limit_in_the_table_format(self, runner: CliRunner, mocker: MockerFixture):
        """The table prints the lists the limit shortened."""
        self._mock_client(mocker, self.ENVELOPE_OF_A_LONG_LIST)

        result = runner.invoke(
            main, ["collection", "search", "Paolo", "--limit", "1", "-F", "table"]
        )

        assert result.exit_code == 0
        assert "1. Aguaplano" in result.output
        assert "Come Di" not in result.output

    def test_a_limit_below_one(self, runner: CliRunner, mocker: MockerFixture):
        """A limit that would keep nothing is a usage error."""
        mock_client = self._mock_client(mocker)

        result = runner.invoke(main, ["collection", "search", "Paolo", "--limit", "0"])

        assert result.exit_code == 2
        mock_client.search.assert_not_called()

    def test_the_best_result_only(self, runner: CliRunner, mocker: MockerFixture):
        """-b keeps the first result of each list, as --limit 1 does."""
        self._mock_client(mocker, self.ENVELOPE_OF_A_LONG_LIST)

        result = runner.invoke(main, ["collection", "search", "Paolo", "-1", "-F", "json"])

        assert result.exit_code == 0
        assert [item["title"] for item in json.loads(result.output)[0]["items"]] == ["Aguaplano"]

    def test_the_best_result_only_with_a_limit(self, runner: CliRunner, mocker: MockerFixture):
        """The flag and the limit exclude each other."""
        mock_client = self._mock_client(mocker)

        result = runner.invoke(main, ["collection", "search", "Paolo", "-1", "--limit", "3"])

        assert result.exit_code == 2
        assert "not both" in result.output
        mock_client.search.assert_not_called()

    def test_the_offset(self, runner: CliRunner, mocker: MockerFixture):
        """-o skips the first results of each list, client-side."""
        self._mock_client(mocker, self.ENVELOPE_OF_A_LONG_LIST)

        result = runner.invoke(main, ["collection", "search", "Paolo", "-o", "1", "-F", "json"])

        assert result.exit_code == 0
        assert [item["title"] for item in json.loads(result.output)[0]["items"]] == [
            "Come Di",
            "Sotto le stelle del jazz",
        ]

    def test_the_offset_applies_after_the_filters_and_before_the_limit(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """-o skips among the filtered results, and -l then caps the window."""
        self._mock_client(mocker, self.ENVELOPE_OF_A_LONG_LIST)

        result = runner.invoke(
            main,
            ["collection", "search", "Paolo", "-T", "-o", "1", "-l", "1", "-F", "json"],
        )

        assert result.exit_code == 0
        assert [item["title"] for item in json.loads(result.output)[0]["items"]] == ["Come Di"]

    def test_an_offset_of_zero(self, runner: CliRunner, mocker: MockerFixture):
        """-o 0 changes nothing."""
        self._mock_client(mocker, self.ENVELOPE_OF_A_LONG_LIST)

        result = runner.invoke(main, ["collection", "search", "Paolo", "-o", "0", "-F", "json"])

        assert result.exit_code == 0
        assert len(json.loads(result.output)[0]["items"]) == 3

    def test_the_uris_in_the_table_format(self, runner: CliRunner, mocker: MockerFixture):
        """--print-uri prints the URI of each result under its line."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["collection", "search", "Paolo", "-u", "-F", "table"])

        assert result.exit_code == 0
        assert "1. Paolo Conte\n   artists://Paolo%20Conte" in result.output
        assert "qobuz://playlist/13980206" in result.output

    def test_the_uris_are_not_printed_by_default(self, runner: CliRunner, mocker: MockerFixture):
        """Without the flag the table carries no URI."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["collection", "search", "Paolo", "-F", "table"])

        assert result.exit_code == 0
        assert "artists://" not in result.output

    def test_the_uris_in_another_format(self, runner: CliRunner, mocker: MockerFixture):
        """--print-uri says nothing to the other formats, which carry the URI already."""
        self._mock_client(mocker)

        result = runner.invoke(
            main, ["collection", "search", "Paolo", "--print-uri", "-F", "json"]
        )

        assert result.exit_code == 0
        assert json.loads(result.output)[0]["items"][0]["uri"] == "artists://Paolo%20Conte"

    def test_a_limit_leaves_the_raw_payload(self, runner: CliRunner, mocker: MockerFixture):
        """-F raw prints what the host answered, whatever the limit keeps."""
        self._mock_client(mocker, self.ENVELOPE_OF_A_LONG_LIST)

        result = runner.invoke(main, ["collection", "search", "Paolo", "-1", "-F", "raw"])

        assert result.exit_code == 0
        assert json.loads(result.output) == self.ENVELOPE_OF_A_LONG_LIST

    def _titles_of_every_kind(self, runner: CliRunner, mocker: MockerFixture, *options: str):
        """Invoke a search over the payload of every kind and return the titles kept."""
        self._mock_client(mocker, self.ENVELOPE_OF_EVERY_KIND)

        result = runner.invoke(main, ["collection", "search", "Paolo", "-F", "json", *options])

        assert result.exit_code == 0
        return [item["title"] for block in json.loads(result.output) for item in block["items"]]

    def test_the_result_kinds(self, runner: CliRunner, mocker: MockerFixture):
        """--result-kinds keeps the results of the kinds it names."""
        assert self._titles_of_every_kind(runner, mocker, "--result-kinds", "album") == [
            "An Album"
        ]

    def test_several_result_kinds(self, runner: CliRunner, mocker: MockerFixture):
        """A comma-separated list keeps every kind it names."""
        assert self._titles_of_every_kind(runner, mocker, "-k", "album,track") == [
            "An Album",
            "A Track",
        ]

    def test_the_kind_of_the_results_nothing_else_is(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """The other kind keeps what none of the named kinds is, a Web radio here."""
        assert self._titles_of_every_kind(runner, mocker, "--result-kinds", "other") == ["A Radio"]

    @pytest.mark.parametrize(
        ("option", "title"),
        [
            ("--albums-only", "An Album"),
            ("-B", "An Album"),
            ("--artists-only", "An Artist"),
            ("-A", "An Artist"),
            ("--playlists-only", "A Playlist"),
            ("-Y", "A Playlist"),
            ("--tracks-only", "A Track"),
            ("-T", "A Track"),
        ],
    )
    def test_the_only_flags(self, runner: CliRunner, mocker: MockerFixture, option, title):
        """Each flag keeps the kind it names, as --result-kinds does."""
        assert self._titles_of_every_kind(runner, mocker, option) == [title]

    def test_the_text_options_only_feed_the_query_with_a_kind(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """With a kind asked for, the text options say what to search for, nothing more."""
        mock_client = self._mock_client(mocker, self.ENVELOPE_OF_EVERY_KIND)

        result = runner.invoke(
            main, ["collection", "search", "-a", "Paolo Conte", "--albums-only", "-F", "json"]
        )

        assert result.exit_code == 0
        mock_client.search.assert_called_once_with("Paolo Conte")
        # The album is kept although another artist is the one it carries
        assert [item["title"] for item in json.loads(result.output)[0]["items"]] == ["An Album"]

    def test_an_unknown_result_kind(self, runner: CliRunner, mocker: MockerFixture):
        """A kind that does not exist is a usage error."""
        mock_client = self._mock_client(mocker)

        result = runner.invoke(main, ["collection", "search", "Paolo", "--result-kinds", "song"])

        assert result.exit_code == 2
        assert "album, artist, other, playlist, track" in result.output
        mock_client.search.assert_not_called()

    def test_the_kind_options_must_agree(self, runner: CliRunner, mocker: MockerFixture):
        """Two options asking for different kinds refuse each other."""
        mock_client = self._mock_client(mocker)

        result = runner.invoke(
            main, ["collection", "search", "Paolo", "--albums-only", "--tracks-only"]
        )

        assert result.exit_code == 2
        assert "agree on the kinds to keep" in result.output
        mock_client.search.assert_not_called()

    def test_the_result_kinds_and_a_flag_must_agree(self, runner: CliRunner, mocker: MockerFixture):
        """A flag is refused next to --result-kinds, which already says what to keep."""
        mock_client = self._mock_client(mocker)

        result = runner.invoke(
            main, ["collection", "search", "Paolo", "--result-kinds", "album", "--albums-only"]
        )

        assert result.exit_code == 2
        mock_client.search.assert_not_called()

    def test_the_playlist_options_agree(self, runner: CliRunner, mocker: MockerFixture):
        """--playlist and --playlists-only ask for the same kind, so both may be given."""
        assert self._titles_of_every_kind(
            runner, mocker, "--playlist", "Paolo", "--playlists-only"
        ) == ["A Playlist"]

    def test_a_connection_error(self, runner: CliRunner, mocker: MockerFixture):
        """A host that cannot be reached exits 1."""
        mock_client = mocker.Mock()
        mock_client.search.side_effect = VolumioConnectionError("Connection failed")
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["collection", "search", "Paolo"])

        assert result.exit_code == 1
        assert "Connection error" in result.output


class TestMultiroomCommands:
    """Test cases for the zones list command."""

    ZONES = {
        "zones": [
            {
                "id": "zone-1",
                "host": "http://192.168.211.1",
                "name": "Volumio",
                "isSelf": True,
                "type": "device",
                "state": {"status": "stop", "volume": 43, "mute": False, "albumart": "/art1.png"},
            },
            {
                "id": "zone-2",
                "host": "http://192.168.1.22",
                "name": "Volumio Studio",
                "isSelf": False,
                "type": "device",
                "state": {"status": "play", "volume": 10, "mute": False, "albumart": "/art2.png"},
            },
        ]
    }

    @pytest.fixture
    def runner(self):
        """Create a CliRunner instance."""
        return CliRunner()

    def _mock_client(self, mocker: MockerFixture, zones=None):
        """Mock VolumioRESTAPIClient with a usable zones property."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "zones", return_value=self.ZONES if zones is None else zones)
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        return mock_client

    def test_get_default_short_fields(self, runner: CliRunner, mocker: MockerFixture):
        """multiroom info prints pretty JSON with the short fields, including the state."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["multiroom", "info"])

        assert result.exit_code == 0
        output_data = json.loads(result.output)
        assert [zone["name"] for zone in output_data] == ["Volumio", "Volumio Studio"]
        assert output_data[0]["host"] == "http://192.168.211.1"
        assert output_data[0]["state"]["status"] == "stop"
        # Fields outside the short set are filtered out
        assert "id" not in output_data[0]
        assert "type" not in output_data[0]
        # The albumart of the state is hidden in short mode
        assert "albumart" not in output_data[0]["state"]

    def test_get_all_fields(self, runner: CliRunner, mocker: MockerFixture):
        """multiroom info -L all keeps every field of each zone."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["multiroom", "info", "-L", "ALL"])

        assert result.exit_code == 0
        output_data = json.loads(result.output)
        assert output_data[0]["id"] == "zone-1"
        assert output_data[0]["type"] == "device"
        assert output_data[0]["state"]["status"] == "stop"
        # The albumart of the state is kept with all fields
        assert output_data[0]["state"]["albumart"] == "/art1.png"

    def test_get_json_format(self, runner: CliRunner, mocker: MockerFixture):
        """multiroom info -F json prints JSON with 2-space indentation."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["multiroom", "info", "-F", "json"])

        assert result.exit_code == 0
        assert '\n    "' in result.output
        assert json.loads(result.output)[1]["name"] == "Volumio Studio"

    def test_get_table_format(self, runner: CliRunner, mocker: MockerFixture):
        """multiroom info -F table prints numbered blocks with aligned labels."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["multiroom", "info", "-F", "table"])
        lines = result.output.splitlines()

        assert result.exit_code == 0
        assert "Volumio Multiroom Zones" in lines
        assert "1. Volumio" in lines
        assert "2. Volumio Studio" in lines
        # The labels are indented to start at the column of the zone name
        assert f"   {'Host':17}: http://192.168.211.1" in lines
        assert f"   {'Is Self':17}: True" in lines
        # The name is the block heading and is not repeated in the body
        assert not any(line.strip().startswith("Name ") for line in lines)

    def test_get_table_format_nested_state(self, runner: CliRunner, mocker: MockerFixture):
        """The nested state is printed one key/value per line, also with the short fields."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["multiroom", "info", "-F", "table"])
        lines = result.output.splitlines()

        assert result.exit_code == 0
        assert f"   {'State':17}:" in lines
        assert f"     {'Status':15}: stop" in lines
        assert f"     {'Volume':15}: 43" in lines

    def test_get_table_format_two_digit_numbers(self, runner: CliRunner, mocker: MockerFixture):
        """With 10+ zones the numbers are right-aligned and the labels indented to match."""
        zones = {
            "zones": [
                {
                    "host": f"http://192.168.1.{index}",
                    "name": f"Zone {index}",
                    "isSelf": False,
                    "state": {"status": "play", "volume": 10},
                }
                for index in range(1, 12)
            ]
        }
        self._mock_client(mocker, zones=zones)

        result = runner.invoke(main, ["multiroom", "info", "-F", "table"])
        lines = result.output.splitlines()

        assert result.exit_code == 0
        assert " 9. Zone 9" in lines
        assert "10. Zone 10" in lines
        # The labels of every block start at the column of the zone name
        assert f"    {'Host':17}: http://192.168.1.9" in lines
        assert f"    {'Host':17}: http://192.168.1.10" in lines
        # The nested state keeps its extra two-space offset
        assert f"    {'State':17}:" in lines
        assert f"      {'Status':15}: play" in lines

    def test_get_table_format_empty(self, runner: CliRunner, mocker: MockerFixture):
        """multiroom info -F table reports an empty zone list."""
        self._mock_client(mocker, zones={"zones": []})

        result = runner.invoke(main, ["multiroom", "info", "-F", "table"])

        assert result.exit_code == 0
        assert "Volumio Multiroom Zones" in result.output
        assert "(empty)" in result.output

    def test_get_raw_format(self, runner: CliRunner, mocker: MockerFixture):
        """multiroom info -F raw prints the unfiltered payload as compact JSON."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["multiroom", "info", "-F", "raw"])

        assert result.exit_code == 0
        assert "\n" not in result.output.strip()
        output_data = json.loads(result.output)
        # Raw is the whole response, including the nested state
        assert output_data["zones"][0]["state"]["volume"] == 43

    def test_get_machine_readable(self, runner: CliRunner, mocker: MockerFixture):
        """In machine-readable mode zones list still honors the format option."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["-m", "multiroom", "info", "-F", "raw"])

        assert result.exit_code == 0
        assert json.loads(result.output)["zones"][1]["name"] == "Volumio Studio"

    def test_get_connection_error(self, runner: CliRunner, mocker: MockerFixture):
        """multiroom info exits 1 on a connection error."""
        mock_client = self._mock_client(mocker)
        _attach_property(
            mock_client, "zones", side_effect=VolumioConnectionError("Connection failed")
        )

        result = runner.invoke(main, ["multiroom", "info"])

        assert result.exit_code == 1
        assert "Connection error" in result.output


class TestMultiroomSettings:
    """Test cases for the multiroom commands beyond the zones, and the zones rename."""

    STATUS = {"enabled": True, "mode": "server", "port": 3001}
    """The multiroom configuration, as a Volumio host answers it."""

    _REFUSAL = (
        "API client error: The Synchronous REST API client does not offer the multiroom "
        "settings: use --api-client synchronous_websocket or asynchronous_websocket, "
        "or --allow-fallback-to-websocket-api"
    )
    """The error of a REST API client asked for a multiroom setting, without the fallback."""

    _WEBSOCKET = ["-C", "synchronous_websocket"]
    """The global option selecting the WebSocket API client the commands need."""

    @pytest.fixture
    def runner(self):
        """Create a CliRunner instance."""
        return CliRunner()

    def _mock_rest_client(self, mocker: MockerFixture):
        """Mock VolumioRESTAPIClient, the default client."""
        mock_client = mocker.Mock()
        mock_client.logger = LOGGER
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        return mock_client

    def _mock_websocket_client(self, mocker: MockerFixture):
        """Mock VolumioWebSocketClient answering the multiroom reads."""
        mock_client = mocker.Mock()
        mock_client.logger = LOGGER
        _attach_property(mock_client, "multiroom", return_value=self.STATUS)
        mock_client.set_multiroom.return_value = Multiroom.from_raw(
            {**self.STATUS, "mode": "client"}
        )
        mocker.patch(
            "volumito.cli.click_helpers.VolumioWebSocketClient",
            return_value=mock_client,
        )
        return mock_client

    def test_zones_is_now_info(self, runner: CliRunner):
        """multiroom zones no longer exists, without a synonym."""
        result = runner.invoke(main, ["-i", "multiroom", "zones"])

        assert result.exit_code == 2
        assert "No such command 'zones'" in result.output

    def test_status(self, runner: CliRunner, mocker: MockerFixture):
        """multiroom status prints the configuration of the host, as a table too."""
        self._mock_websocket_client(mocker)

        pretty = runner.invoke(main, [*self._WEBSOCKET, "multiroom", "status"])
        table = runner.invoke(main, [*self._WEBSOCKET, "multiroom", "status", "-F", "table"])

        assert pretty.exit_code == 0
        assert json.loads(pretty.output) == self.STATUS
        assert table.exit_code == 0
        assert "Volumio Multiroom Status" in table.output
        assert "server" in table.output

    def test_client(self, runner: CliRunner, mocker: MockerFixture):
        """multiroom client makes the host a client of the named server."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "multiroom", "client", "volumio-living.local"]
        )

        assert result.exit_code == 0
        assert "Command 'multiroom client of \"volumio-living.local\"' executed" in (
            result.output
        )
        mock_client.set_as_multiroom_client.assert_called_once_with("volumio-living.local")

    @pytest.mark.parametrize(
        ("command", "member"),
        [("server", "set_as_multiroom_server"), ("single", "set_as_multiroom_single")],
    )
    def test_server_and_single(self, runner: CliRunner, mocker: MockerFixture, command, member):
        """multiroom server and single change the role of the host."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "multiroom", command])

        assert result.exit_code == 0
        assert f"Command 'multiroom {command}' executed successfully" in result.output
        getattr(mock_client, member).assert_called_once_with()

    def test_set_from_json(self, runner: CliRunner, mocker: MockerFixture):
        """multiroom set sends the JSON object, printing the configuration answered."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "multiroom", "set", '{"enabled": true, "mode": "client"}']
        )

        assert result.exit_code == 0
        assert json.loads(result.output)["mode"] == "client"
        mock_client.set_multiroom.assert_called_once_with({"enabled": True, "mode": "client"})

    def test_set_from_a_file(self, runner: CliRunner, mocker: MockerFixture, tmp_path):
        """A path names a file holding the JSON object."""
        mock_client = self._mock_websocket_client(mocker)
        source = tmp_path / "multiroom.json"
        source.write_text('{"enabled": false}')

        result = runner.invoke(main, [*self._WEBSOCKET, "multiroom", "set", str(source)])

        assert result.exit_code == 0
        mock_client.set_multiroom.assert_called_once_with({"enabled": False})

    def test_write(self, runner: CliRunner, mocker: MockerFixture):
        """multiroom write sends the JSON object without waiting for an answer."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "multiroom", "write", '{"enabled": false}']
        )

        assert result.exit_code == 0
        assert "Command 'multiroom write' executed successfully" in result.output
        mock_client.write_multiroom.assert_called_once_with({"enabled": False})
        mock_client.set_multiroom.assert_not_called()

    @pytest.mark.parametrize("settings", ["not json", "[1, 2]", '"text"'])
    def test_settings_of_another_shape(
        self, runner: CliRunner, mocker: MockerFixture, settings
    ):
        """The settings must be a JSON object, or a file holding one."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "multiroom", "set", settings])

        assert result.exit_code == 2
        assert "Expected the SETTINGS argument to be a JSON object" in result.output
        mock_client.set_multiroom.assert_not_called()

    def test_settings_from_an_unreadable_file(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """A file that is not JSON is a usage error naming the problem."""
        mock_client = self._mock_websocket_client(mocker)
        source = tmp_path / "multiroom.json"
        source.write_text("{not json")

        result = runner.invoke(main, [*self._WEBSOCKET, "multiroom", "write", str(source)])

        assert result.exit_code == 2
        assert "Expected the SETTINGS argument to be a JSON object" in result.output
        mock_client.write_multiroom.assert_not_called()

    @pytest.mark.parametrize(
        "arguments",
        [
            ["client", "volumio-living.local"],
            ["server"],
            ["set", "{}"],
            ["single"],
            ["status"],
            ["write", "{}"],
        ],
    )
    def test_a_rest_client_refuses(self, runner: CliRunner, mocker: MockerFixture, arguments):
        """With the default REST API client, the commands fail naming the remedies."""
        self._mock_rest_client(mocker)

        result = runner.invoke(main, ["multiroom", *arguments])

        assert result.exit_code == 1
        assert self._REFUSAL in result.output

    def test_a_rest_client_falls_back_when_allowed(self, runner: CliRunner, mocker: MockerFixture):
        """With the switch, the REST API client serves the command through a WebSocket one."""
        rest = self._mock_rest_client(mocker)
        websocket = self._mock_websocket_client(mocker)

        result = runner.invoke(main, ["--allow-fallback-to-websocket-api", "multiroom", "status"])

        assert result.exit_code == 0
        assert "Falling back to the WebSocket API client for the multiroom settings" in (
            result.output
        )
        assert json.loads(result.stdout) == self.STATUS
        websocket.disconnect.assert_called_once_with()
        rest.close.assert_called_once_with()


class TestPlaylistCommands:
    """Test cases for the playlist commands."""

    PLAYLISTS = ["Rock", "Jazz Classics", "Ambient"]

    _CONTENT = {
        "name": "Rock",
        "lists": [
            [
                {
                    "title": "Song A",
                    "artist": "Artist A",
                    "album": "Album X",
                    "duration": 61,
                    "service": "mpd",
                    "uri": "music-library/a.flac",
                }
            ],
            [
                {
                    "name": "Song B",
                    "artist": "Artist B",
                    "album": "Album Y",
                    "duration": 125,
                    "service": "qobuz",
                    "uri": "qobuz://track/2",
                }
            ],
        ],
    }
    """The content of a playlist as a Volumio host answers it: one list per source."""

    _ALBUM_LISTING = {
        "navigation": {
            "lists": [
                {
                    "items": [
                        {
                            "service": "qobuz",
                            "type": "song",
                            "title": "One",
                            "uri": "qobuz://song/1",
                        },
                        {
                            "type": "song",
                            "title": "Two",
                            "uri": "qobuz://song/2",
                        },
                        {
                            "service": "qobuz",
                            "type": "folder-with-favourites",
                            "title": "Related album",
                            "uri": "qobuz://album/9",
                        },
                    ]
                }
            ]
        }
    }
    """What a Volumio host lists at an album of another source: its songs, and more."""

    _REFUSAL = (
        "API client error: The Synchronous REST API client does not offer the playlist edits: "
        "use --api-client synchronous_websocket or asynchronous_websocket, "
        "or --allow-fallback-to-websocket-api"
    )
    """The error of a REST API client asked for a playlist edit, without the fallback."""

    _URI = "qobuz://track/3"
    """A URI of the kind a browse or a search prints."""

    _WEBSOCKET = ["-C", "synchronous_websocket"]
    """The global option selecting the WebSocket API client the editing commands need."""

    @pytest.fixture
    def runner(self):
        """Create a CliRunner instance."""
        return CliRunner()

    def _mock_client(self, mocker: MockerFixture, playlists=None):
        """Mock VolumioRESTAPIClient with usable playlist methods; patch out the sleep."""
        mock_client = mocker.Mock()
        _attach_property(
            mock_client,
            "playlists",
            return_value=self.PLAYLISTS if playlists is None else playlists,
        )
        mock_client.play_playlist.return_value = {"response": "playPlaylist Response"}
        _attach_property(mock_client, "state", return_value={
            "title": "Test Song",
            "artist": "StatusMarkerArtist",
        })
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        mock_sleep = mocker.patch("volumito.cli.click_helpers.time.sleep")
        return mock_client, mock_sleep

    def test_group_help(self, runner: CliRunner):
        """The playlist group lists both of its commands."""
        result = runner.invoke(main, ["playlist", "--help"])

        assert result.exit_code == 0
        assert "list" in result.output
        assert "play" in result.output

    def test_list_default_pretty(self, runner: CliRunner, mocker: MockerFixture):
        """playlist list prints the playlist names as pretty JSON by default."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["playlist", "list"])

        assert result.exit_code == 0
        assert json.loads(result.output) == self.PLAYLISTS
        # Pretty uses 4-space indentation
        assert '\n    "Rock"' in result.output

    def test_list_json_format(self, runner: CliRunner, mocker: MockerFixture):
        """playlist list -F json prints JSON with 2-space indentation."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["playlist", "list", "-F", "json"])

        assert result.exit_code == 0
        assert json.loads(result.output) == self.PLAYLISTS
        assert '\n  "Rock"' in result.output

    def test_list_table_format(self, runner: CliRunner, mocker: MockerFixture):
        """playlist list -F table prints a numbered list."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["playlist", "list", "-F", "table"])
        lines = result.output.splitlines()

        assert result.exit_code == 0
        assert "Volumio Playlists" in lines
        assert "1. Rock" in lines
        assert "2. Jazz Classics" in lines
        assert "3. Ambient" in lines

    def test_list_table_format_two_digit_numbers(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """With 10+ playlists the numbers are right-aligned."""
        self._mock_client(mocker, playlists=[f"Playlist {index}" for index in range(1, 12)])

        result = runner.invoke(main, ["playlist", "list", "-F", "table"])
        lines = result.output.splitlines()

        assert result.exit_code == 0
        assert " 9. Playlist 9" in lines
        assert "10. Playlist 10" in lines

    def test_list_table_format_empty(self, runner: CliRunner, mocker: MockerFixture):
        """playlist list -F table reports an empty playlist list."""
        self._mock_client(mocker, playlists=[])

        result = runner.invoke(main, ["playlist", "list", "-F", "table"])

        assert result.exit_code == 0
        assert "Volumio Playlists" in result.output
        assert "(empty)" in result.output

    def test_list_raw_format(self, runner: CliRunner, mocker: MockerFixture):
        """playlist list -F raw prints the payload as compact JSON."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["playlist", "list", "-F", "raw"])

        assert result.exit_code == 0
        assert "\n" not in result.output.strip()
        assert json.loads(result.output) == self.PLAYLISTS

    def test_list_connection_error(self, runner: CliRunner, mocker: MockerFixture):
        """playlist list exits 1 on a connection error."""
        mock_client, _ = self._mock_client(mocker)
        _attach_property(
            mock_client, "playlists", side_effect=VolumioConnectionError("Connection failed")
        )

        result = runner.invoke(main, ["playlist", "list"])

        assert result.exit_code == 1
        assert "Connection error" in result.output

    def test_list_api_error(self, runner: CliRunner, mocker: MockerFixture):
        """playlist list exits 1 on an API error."""
        mock_client, _ = self._mock_client(mocker)
        _attach_property(mock_client, "playlists", side_effect=VolumioAPIError("Bad payload"))

        result = runner.invoke(main, ["playlist", "list"])

        assert result.exit_code == 1
        assert "API error" in result.output

    def test_play_calls_the_client_with_the_name(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """playlist play passes the playlist name to the client."""
        mock_client, _ = self._mock_client(mocker)

        result = runner.invoke(
            main, ["playlist", "play", "Jazz Classics", "--no-print-resulting-status"]
        )

        assert result.exit_code == 0
        mock_client.play_playlist.assert_called_once_with("Jazz Classics")
        # The double quotes delimit a name that contains spaces
        assert "Command 'playplaylist \"Jazz Classics\"' executed successfully" in result.output

    def test_play_requires_the_name(self, runner: CliRunner, mocker: MockerFixture):
        """playlist play without a name is a usage error."""
        mock_client, _ = self._mock_client(mocker)

        result = runner.invoke(main, ["playlist", "play"])

        assert result.exit_code != 0
        mock_client.play_playlist.assert_not_called()

    def test_play_default_prints_resulting_status(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """By default, playlist play waits and prints the resulting playback status."""
        mock_client, mock_sleep = self._mock_client(mocker)

        result = runner.invoke(main, ["playlist", "play", "Rock"])

        assert result.exit_code == 0
        mock_sleep.assert_called_once_with(2.0)
        mock_client.state_property.assert_called_once()
        assert "StatusMarkerArtist" in result.output

    def test_play_no_print_resulting_status(self, runner: CliRunner, mocker: MockerFixture):
        """With --no-print-resulting-status the status is not fetched."""
        mock_client, mock_sleep = self._mock_client(mocker)

        result = runner.invoke(
            main, ["playlist", "play", "Rock", "--no-print-resulting-status"]
        )

        assert result.exit_code == 0
        mock_sleep.assert_not_called()
        mock_client.state_property.assert_not_called()
        assert "StatusMarkerArtist" not in result.output

    def test_play_checks_the_name_by_default(self, runner: CliRunner, mocker: MockerFixture):
        """By default the name is looked up before the command is sent."""
        mock_client, _ = self._mock_client(mocker)

        result = runner.invoke(
            main, ["playlist", "play", "Rock", "--no-print-resulting-status"]
        )

        assert result.exit_code == 0
        mock_client.playlists_property.assert_called_once()
        mock_client.play_playlist.assert_called_once_with("Rock")

    def test_play_unknown_name(self, runner: CliRunner, mocker: MockerFixture):
        """An unknown playlist name exits 1, listing the available names."""
        mock_client, _ = self._mock_client(mocker)

        result = runner.invoke(main, ["playlist", "play", "Nope"])

        assert result.exit_code == 1
        assert 'Playlist not found: "Nope"' in result.output
        assert "Available playlists:" in result.output
        for name in self.PLAYLISTS:
            assert f'  "{name}"' in result.output
        mock_client.play_playlist.assert_not_called()

    def _mock_websocket_client(self, mocker: MockerFixture):
        """Mock VolumioWebSocketClient with the playlists, a content, and the state."""
        mock_client = mocker.Mock()
        mock_client.logger = LOGGER
        _attach_property(mock_client, "playlists", return_value=self.PLAYLISTS)
        mock_client.get_playlist_content.return_value = PlaylistContent.from_envelope(
            self._CONTENT
        )
        mock_client.browse.return_value = BrowseResults.from_envelope(self._ALBUM_LISTING)
        _attach_property(
            mock_client,
            "state",
            return_value={"title": "Test Song", "artist": "StatusMarkerArtist"},
        )
        mocker.patch(
            "volumito.cli.click_helpers.VolumioWebSocketClient",
            return_value=mock_client,
        )
        mocker.patch("volumito.cli.click_helpers.time.sleep")
        return mock_client

    def test_group_help_lists_the_editing_commands(self, runner: CliRunner):
        """The playlist group lists the editing commands beside the original ones."""
        result = runner.invoke(main, ["playlist", "--help"])

        assert result.exit_code == 0
        for command in (
            "add", "content", "copy", "create", "delete", "enqueue", "remove", "rename"
        ):
            assert f"  {command} " in result.output

    @pytest.mark.parametrize(
        ("options", "service"), [([], None), (["--service", "qobuz"], "qobuz")]
    )
    def test_add(self, runner: CliRunner, mocker: MockerFixture, options, service):
        """playlist add checks the name, then adds the URI, of the given service."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "playlist", "add", "Rock", self._URI, *options]
        )

        assert result.exit_code == 0
        assert "Command 'add to playlist \"Rock\"' executed successfully" in result.output
        # The resulting content is printed, as "playlist content" prints it
        assert '"uri": "music-library/a.flac"' in result.output
        mock_client.playlists_property.assert_called_once()
        # A track URI is not browsed, even with the default --expand-tracks
        mock_client.browse.assert_not_called()
        mock_client.add_to_playlist.assert_called_once_with("Rock", self._URI, service)
        mock_client.get_playlist_content.assert_called_once_with("Rock")

    @pytest.mark.parametrize(
        ("options", "service"), [([], None), (["--service", "qobuz"], "qobuz")]
    )
    def test_add_expands_an_album(
        self, runner: CliRunner, mocker: MockerFixture, options, service
    ):
        """An album of another source is browsed, and the tracks it lists are added."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "playlist", "add", "Rock", "qobuz://album/1", *options]
        )

        assert result.exit_code == 0
        assert 'Adding the 2 tracks listed at "qobuz://album/1"' in result.output
        assert result.output.count("executed successfully") == 1
        mock_client.browse.assert_called_once_with("qobuz://album/1")
        # A track without a service takes the given one, or none, to be derived
        assert mock_client.add_to_playlist.call_args_list == [
            mocker.call("Rock", "qobuz://song/1", "qobuz"),
            mocker.call("Rock", "qobuz://song/2", service),
        ]
        mock_client.get_playlist_content.assert_called_once_with("Rock")

    def test_add_without_expanding(self, runner: CliRunner, mocker: MockerFixture):
        """--no-expand-tracks adds the URI as one item, without browsing it."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main,
            [*self._WEBSOCKET, "playlist", "add", "Rock", "qobuz://album/1", "--no-expand-tracks"],
        )

        assert result.exit_code == 0
        mock_client.browse.assert_not_called()
        mock_client.add_to_playlist.assert_called_once_with("Rock", "qobuz://album/1", None)

    def test_add_a_uri_listing_no_track(self, runner: CliRunner, mocker: MockerFixture):
        """A URI listing no track (an artist, its albums) is added as itself."""
        mock_client = self._mock_websocket_client(mocker)
        albums_only = self._ALBUM_LISTING["navigation"]["lists"][0]["items"][2:]
        mock_client.browse.return_value = BrowseResults.from_envelope(
            {"navigation": {"lists": [{"items": albums_only}]}}
        )

        result = runner.invoke(
            main, [*self._WEBSOCKET, "playlist", "add", "Rock", "qobuz://artist/1"]
        )

        assert result.exit_code == 0
        mock_client.browse.assert_called_once_with("qobuz://artist/1")
        mock_client.add_to_playlist.assert_called_once_with("Rock", "qobuz://artist/1", None)

    def test_add_to_a_new_playlist_without_the_check(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """--no-check-playlist-name lets the host create the playlist."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main,
            [*self._WEBSOCKET, "playlist", "add", "New", self._URI, "--no-check-playlist-name"],
        )

        assert result.exit_code == 0
        mock_client.playlists_property.assert_not_called()
        mock_client.add_to_playlist.assert_called_once_with("New", self._URI, None)
        mock_client.get_playlist_content.assert_called_once_with("New")

    @pytest.mark.parametrize("command", ["add", "remove"])
    def test_editing_without_the_resulting_content(
        self, runner: CliRunner, mocker: MockerFixture, command
    ):
        """--no-print-resulting-content skips the content print after the edit."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main,
            [
                *self._WEBSOCKET,
                "playlist",
                command,
                "Rock",
                self._URI,
                "--no-print-resulting-content",
            ],
        )

        assert result.exit_code == 0
        assert "executed successfully" in result.output
        assert '"uri"' not in result.output
        # A removal still reads the content once, to check what it leaves behind
        assert mock_client.get_playlist_content.call_count == (1 if command == "remove" else 0)

    def test_editing_prints_the_resulting_content_as_a_table(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """-F table heads the resulting content with the name of the playlist."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "playlist", "remove", "Rock", self._URI, "-F", "table"]
        )

        assert result.exit_code == 0
        assert 'Volumio Playlist "Rock"' in result.output
        assert "   URI    : music-library/a.flac" in result.output
        mock_client.remove_from_playlist.assert_called_once_with("Rock", self._URI, None)

    @pytest.mark.parametrize(
        "arguments",
        [
            ["add", "Nope", _URI],
            ["content", "Nope"],
            ["delete", "Nope", "-y"],
            ["enqueue", "Nope"],
            ["remove", "Nope", _URI],
        ],
    )
    def test_an_unknown_name(self, runner: CliRunner, mocker: MockerFixture, arguments):
        """An unknown playlist name exits 1, listing the available names, before any edit."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "playlist", *arguments])

        assert result.exit_code == 1
        assert 'Playlist not found: "Nope"' in result.output
        assert "Available playlists:" in result.output
        for name in (
            "add_to_playlist",
            "delete_playlist",
            "enqueue_playlist",
            "get_playlist_content",
            "remove_from_playlist",
        ):
            getattr(mock_client, name).assert_not_called()

    def test_content_default_pretty(self, runner: CliRunner, mocker: MockerFixture):
        """playlist content prints the tracks as pretty JSON, one-based, durations formatted."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "playlist", "content", "Rock"])

        assert result.exit_code == 0
        tracks = json.loads(result.output)
        assert [track["position"] for track in tracks] == [1, 2]
        assert tracks[0]["title"] == "Song A"
        assert tracks[0]["duration"] == "00:01:01"
        # The local files report their title under "name"
        assert tracks[1]["name"] == "Song B"
        # The URI of each track is part of the short field set of a playlist
        assert [track["uri"] for track in tracks] == ["music-library/a.flac", "qobuz://track/2"]
        mock_client.playlists_property.assert_called_once()
        mock_client.get_playlist_content.assert_called_once_with("Rock")

    def test_content_json(self, runner: CliRunner, mocker: MockerFixture):
        """playlist content -F json keeps the durations in seconds."""
        self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "playlist", "content", "Rock", "-F", "json"]
        )

        assert result.exit_code == 0
        tracks = json.loads(result.output)
        assert tracks[0]["position"] == 1
        assert tracks[0]["duration"] == 61

    def test_content_fields(self, runner: CliRunner, mocker: MockerFixture):
        """-L keeps the listed fields of each track."""
        self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "playlist", "content", "Rock", "-L", "title,uri"]
        )

        assert result.exit_code == 0
        assert json.loads(result.output) == [
            {"title": "Song A", "uri": "music-library/a.flac"},
            {"uri": "qobuz://track/2"},
        ]

    def test_content_table(self, runner: CliRunner, mocker: MockerFixture):
        """-F table heads the tracks with the name of the playlist."""
        self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "playlist", "content", "Rock", "-F", "table"]
        )

        assert result.exit_code == 0
        lines = result.output.splitlines()
        assert 'Volumio Playlist "Rock"' in lines
        assert "1. Song A" in lines
        assert "2. Song B" in lines

    def test_content_raw(self, runner: CliRunner, mocker: MockerFixture):
        """-F raw prints the answer of the host as it is."""
        self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, ["-m", *self._WEBSOCKET, "playlist", "content", "Rock", "-F", "raw"]
        )

        assert result.exit_code == 0
        assert json.loads(result.output) == self._CONTENT

    def test_content_without_the_check(self, runner: CliRunner, mocker: MockerFixture):
        """--no-check-playlist-name skips the lookup of the name."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "playlist", "content", "Rock", "--no-check-playlist-name"]
        )

        assert result.exit_code == 0
        mock_client.playlists_property.assert_not_called()
        mock_client.get_playlist_content.assert_called_once_with("Rock")

    def test_content_format_from_the_configuration(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """The playlist-content subsection of the configuration sets the default format."""
        self._mock_websocket_client(mocker)
        config = tmp_path / "volumito.yaml"
        config.write_text("output:\n  playlist-content:\n    format: table\n")

        result = runner.invoke(
            main, ["-c", str(config), *self._WEBSOCKET, "playlist", "content", "Rock"]
        )

        assert result.exit_code == 0
        assert 'Volumio Playlist "Rock"' in result.output

    def test_copy(self, runner: CliRunner, mocker: MockerFixture):
        """playlist copy creates the target, adds every item of the source, and prints it."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "playlist", "copy", "Rock", "New"])

        assert result.exit_code == 0
        assert 'Copying 2 items of "Rock" to "New"' in result.output
        assert "Command 'copy playlist \"Rock\" to \"New\"' executed successfully" in result.output
        # One read checks the source exists, one that the target does not
        assert mock_client.playlists_property.call_count == 2
        mock_client.create_playlist.assert_called_once_with("New")
        assert mock_client.add_to_playlist.call_args_list == [
            mocker.call("New", "music-library/a.flac", "mpd"),
            mocker.call("New", "qobuz://track/2", "qobuz"),
        ]
        # The content of the source is read, then the one of the target is printed
        assert mock_client.get_playlist_content.call_args_list == [
            mocker.call("Rock"),
            mocker.call("New"),
        ]
        assert '"uri": "music-library/a.flac"' in result.output

    def test_copy_without_the_resulting_content(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """--no-print-resulting-content skips the print of the target."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main,
            [*self._WEBSOCKET, "playlist", "copy", "Rock", "New", "--no-print-resulting-content"],
        )

        assert result.exit_code == 0
        mock_client.get_playlist_content.assert_called_once_with("Rock")
        assert '"uri"' not in result.output

    def test_copy_skips_an_item_without_a_uri(self, runner: CliRunner, mocker: MockerFixture):
        """An item the host lists without a URI cannot be added, and is skipped with a warning."""
        mock_client = self._mock_websocket_client(mocker)
        mock_client.get_playlist_content.return_value = PlaylistContent.from_envelope(
            {
                "name": "Rock",
                "lists": [
                    [
                        {"title": "No URI", "service": "mpd"},
                        {"title": "Song", "service": "qobuz", "uri": "qobuz://track/2"},
                    ]
                ],
            }
        )

        result = runner.invoke(
            main,
            [*self._WEBSOCKET, "playlist", "copy", "Rock", "New", "--no-print-resulting-content"],
        )

        assert result.exit_code == 0
        assert 'Skipping the item at position 1 of "Rock", which has no URI' in result.output
        assert 'Copying 1 items of "Rock" to "New"' in result.output
        mock_client.add_to_playlist.assert_called_once_with("New", "qobuz://track/2", "qobuz")

    @pytest.mark.parametrize(
        ("position", "uri", "service"),
        [("1", "music-library/a.flac", "mpd"), ("2", "qobuz://track/2", "qobuz")],
    )
    def test_copy_by_position(
        self, runner: CliRunner, mocker: MockerFixture, position, uri, service
    ):
        """-p/--position copies the item listed there only."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main,
            [*self._WEBSOCKET, "playlist", "copy", "Rock", "New", "-p", position,
             "--no-print-resulting-content"],
        )

        assert result.exit_code == 0
        assert 'Copying 1 items of "Rock" to "New"' in result.output
        mock_client.create_playlist.assert_called_once_with("New")
        mock_client.add_to_playlist.assert_called_once_with("New", uri, service)

    def test_copy_by_a_selection_of_positions(self, runner: CliRunner, mocker: MockerFixture):
        """A selection copies the items at every position it covers, in order."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main,
            [*self._WEBSOCKET, "playlist", "copy", "Rock", "New", "--position", "1-2",
             "--no-print-resulting-content"],
        )

        assert result.exit_code == 0
        assert 'Copying 2 items of "Rock" to "New"' in result.output
        assert mock_client.add_to_playlist.call_args_list == [
            mocker.call("New", "music-library/a.flac", "mpd"),
            mocker.call("New", "qobuz://track/2", "qobuz"),
        ]

    def test_copy_by_a_position_past_the_end(self, runner: CliRunner, mocker: MockerFixture):
        """A position the source does not reach is an invalid value, and nothing is created."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "playlist", "copy", "Rock", "New", "-p", "3"]
        )

        assert result.exit_code == 1
        assert (
            'Invalid value: the playlist "Rock" lists 2 items, none at position 3'
            in result.output
        )
        mock_client.create_playlist.assert_not_called()

    def test_rename(self, runner: CliRunner, mocker: MockerFixture):
        """playlist rename copies the source to the target, then deletes the source."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "playlist", "rename", "Rock", "New"])

        assert result.exit_code == 0
        assert 'Copying 2 items of "Rock" to "New"' in result.output
        assert "Command 'rename playlist \"Rock\" to \"New\"' executed successfully" in (
            result.output
        )
        mock_client.create_playlist.assert_called_once_with("New")
        assert mock_client.add_to_playlist.call_args_list == [
            mocker.call("New", "music-library/a.flac", "mpd"),
            mocker.call("New", "qobuz://track/2", "qobuz"),
        ]
        mock_client.delete_playlist.assert_called_once_with("Rock")
        # The source is deleted only once the target holds its items
        calls = mock_client.mock_calls
        assert calls.index(mocker.call.delete_playlist("Rock")) > calls.index(
            mocker.call.add_to_playlist("New", "qobuz://track/2", "qobuz")
        )
        assert '"uri": "music-library/a.flac"' in result.output

    def test_rename_to_a_name_the_host_refuses(self, runner: CliRunner, mocker: MockerFixture):
        """A target the host does not create leaves the source in place."""
        mock_client = self._mock_websocket_client(mocker)
        mock_client.create_playlist.side_effect = VolumioAPIError(
            'The host did not create the playlist "New": Playlist name not allowed'
        )

        result = runner.invoke(main, [*self._WEBSOCKET, "playlist", "rename", "Rock", "New"])

        assert result.exit_code == 1
        assert "API error: The host did not create the playlist" in result.output
        mock_client.add_to_playlist.assert_not_called()
        mock_client.delete_playlist.assert_not_called()

    def test_rename_refuses_an_existing_target(self, runner: CliRunner, mocker: MockerFixture):
        """A target already listed exits 1, naming the overriding option, touching nothing."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "playlist", "rename", "Rock", "Jazz Classics"]
        )

        assert result.exit_code == 1
        assert (
            'Playlist already exists: "Jazz Classics" '
            "(use --overwrite-existing-playlist to overwrite)"
        ) in result.output
        mock_client.create_playlist.assert_not_called()
        mock_client.delete_playlist.assert_not_called()

    def test_rename_overwrites_an_existing_target_when_asked(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """With --overwrite-existing-playlist, the target is deleted first, then filled."""
        mock_client = self._mock_websocket_client(mocker)
        _attach_property(
            mock_client,
            "playlists",
            side_effect=[self.PLAYLISTS, self.PLAYLISTS, ["Rock", "Ambient"]],
        )

        result = runner.invoke(
            main,
            [
                *self._WEBSOCKET,
                "playlist",
                "rename",
                "Rock",
                "Jazz Classics",
                "--overwrite-existing-playlist",
            ],
        )

        assert result.exit_code == 0
        assert "Command 'delete playlist \"Jazz Classics\"' executed successfully" in (
            result.output
        )
        assert "Command 'rename playlist \"Rock\" to \"Jazz Classics\"' executed successfully" in (
            result.output
        )
        assert mock_client.delete_playlist.call_args_list == [
            mocker.call("Jazz Classics"),
            mocker.call("Rock"),
        ]
        mock_client.create_playlist.assert_called_once_with("Jazz Classics")
        # The target is deleted only once the source items are read, and created after
        calls = mock_client.mock_calls
        assert calls.index(mocker.call.delete_playlist("Jazz Classics")) > calls.index(
            mocker.call.get_playlist_content("Rock")
        )
        assert calls.index(mocker.call.create_playlist("Jazz Classics")) > calls.index(
            mocker.call.delete_playlist("Jazz Classics")
        )

    def test_rename_overwrite_stops_when_the_target_stays_listed(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """A target the host keeps listing after the deletion exits 1, creating nothing."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main,
            [
                *self._WEBSOCKET,
                "playlist",
                "rename",
                "Rock",
                "Jazz Classics",
                "--overwrite-existing-playlist",
            ],
        )

        assert result.exit_code == 1
        assert (
            'The Volumio host still lists the playlist "Jazz Classics" after the deletion.'
            in result.output
        )
        mock_client.delete_playlist.assert_called_once_with("Jazz Classics")
        mock_client.create_playlist.assert_not_called()

    def test_rename_to_the_same_name(self, runner: CliRunner, mocker: MockerFixture):
        """The same name twice is a usage error, before any read."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main,
            [
                *self._WEBSOCKET,
                "playlist",
                "rename",
                "Rock",
                "Rock",
                "--overwrite-existing-playlist",
            ],
        )

        assert result.exit_code == 2
        assert "Expected SOURCE and TARGET to be different playlist names." in result.output
        mock_client.playlists_property.assert_not_called()
        mock_client.delete_playlist.assert_not_called()

    def test_rename_overwrite_from_the_configuration_file(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """The miscellaneous.overwrite-existing-playlist key turns the option on."""
        mock_client = self._mock_websocket_client(mocker)
        _attach_property(
            mock_client,
            "playlists",
            side_effect=[self.PLAYLISTS, self.PLAYLISTS, ["Rock", "Ambient"]],
        )
        config = tmp_path / "volumito.yaml"
        config.write_text("miscellaneous:\n  overwrite-existing-playlist: true\n")

        result = runner.invoke(
            main,
            ["-c", str(config), *self._WEBSOCKET, "playlist", "rename", "Rock", "Jazz Classics"],
        )

        assert result.exit_code == 0
        assert mock_client.delete_playlist.call_args_list == [
            mocker.call("Jazz Classics"),
            mocker.call("Rock"),
        ]

    def test_rename_of_a_missing_source(self, runner: CliRunner, mocker: MockerFixture):
        """A source the host does not list is refused before anything is created."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "playlist", "rename", "Nope", "New"])

        assert result.exit_code == 1
        assert 'Playlist not found: "Nope"' in result.output
        mock_client.create_playlist.assert_not_called()
        mock_client.delete_playlist.assert_not_called()

    def test_copy_refuses_an_existing_target(self, runner: CliRunner, mocker: MockerFixture):
        """A target already listed exits 1, naming the overriding option, touching nothing."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "playlist", "copy", "Rock", "Jazz Classics"]
        )

        assert result.exit_code == 1
        assert (
            'Playlist already exists: "Jazz Classics" '
            "(use --overwrite-existing-playlist to overwrite)"
        ) in result.output
        mock_client.create_playlist.assert_not_called()
        mock_client.delete_playlist.assert_not_called()

    def test_copy_overwrites_an_existing_target_when_asked(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """With --overwrite-existing-playlist, the target is deleted, recreated, and filled."""
        mock_client = self._mock_websocket_client(mocker)
        _attach_property(
            mock_client,
            "playlists",
            side_effect=[self.PLAYLISTS, self.PLAYLISTS, ["Rock", "Ambient"]],
        )

        result = runner.invoke(
            main,
            [
                *self._WEBSOCKET,
                "playlist",
                "copy",
                "Rock",
                "Jazz Classics",
                "--overwrite-existing-playlist",
            ],
        )

        assert result.exit_code == 0
        assert "Command 'delete playlist \"Jazz Classics\"' executed successfully" in (
            result.output
        )
        assert "Command 'copy playlist \"Rock\" to \"Jazz Classics\"' executed successfully" in (
            result.output
        )
        mock_client.delete_playlist.assert_called_once_with("Jazz Classics")
        mock_client.create_playlist.assert_called_once_with("Jazz Classics")
        assert mock_client.add_to_playlist.call_args_list == [
            mocker.call("Jazz Classics", "music-library/a.flac", "mpd"),
            mocker.call("Jazz Classics", "qobuz://track/2", "qobuz"),
        ]
        # The target is deleted only once the source items are read, and created after
        calls = mock_client.mock_calls
        assert calls.index(mocker.call.delete_playlist("Jazz Classics")) > calls.index(
            mocker.call.get_playlist_content("Rock")
        )
        assert calls.index(mocker.call.create_playlist("Jazz Classics")) > calls.index(
            mocker.call.delete_playlist("Jazz Classics")
        )

    def test_copy_overwrite_stops_when_the_target_stays_listed(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """A target the host keeps listing after the deletion exits 1, creating nothing."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main,
            [
                *self._WEBSOCKET,
                "playlist",
                "copy",
                "Rock",
                "Jazz Classics",
                "--overwrite-existing-playlist",
            ],
        )

        assert result.exit_code == 1
        assert (
            'The Volumio host still lists the playlist "Jazz Classics" after the deletion.'
            in result.output
        )
        mock_client.delete_playlist.assert_called_once_with("Jazz Classics")
        mock_client.create_playlist.assert_not_called()

    def test_copy_to_the_same_name(self, runner: CliRunner, mocker: MockerFixture):
        """The same name twice is a usage error, before any read."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main,
            [
                *self._WEBSOCKET,
                "playlist",
                "copy",
                "Rock",
                "Rock",
                "--overwrite-existing-playlist",
            ],
        )

        assert result.exit_code == 2
        assert "Expected SOURCE and TARGET to be different playlist names." in result.output
        mock_client.playlists_property.assert_not_called()
        mock_client.delete_playlist.assert_not_called()

    def test_copy_overwrite_from_the_configuration_file(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """The miscellaneous.overwrite-existing-playlist key turns the option on."""
        mock_client = self._mock_websocket_client(mocker)
        _attach_property(
            mock_client,
            "playlists",
            side_effect=[self.PLAYLISTS, self.PLAYLISTS, ["Rock", "Ambient"]],
        )
        config = tmp_path / "volumito.yaml"
        config.write_text("miscellaneous:\n  overwrite-existing-playlist: true\n")

        result = runner.invoke(
            main,
            ["-c", str(config), *self._WEBSOCKET, "playlist", "copy", "Rock", "Jazz Classics"],
        )

        assert result.exit_code == 0
        mock_client.delete_playlist.assert_called_once_with("Jazz Classics")
        mock_client.create_playlist.assert_called_once_with("Jazz Classics")

    def test_copy_of_a_missing_source(self, runner: CliRunner, mocker: MockerFixture):
        """A source the host does not list is refused before anything is created."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "playlist", "copy", "Nope", "New"])

        assert result.exit_code == 1
        assert 'Playlist not found: "Nope"' in result.output
        mock_client.create_playlist.assert_not_called()

    def test_create(self, runner: CliRunner, mocker: MockerFixture):
        """playlist create makes an empty playlist."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "playlist", "create", "New"])

        assert result.exit_code == 0
        assert "Command 'create playlist \"New\"' executed successfully" in result.output
        mock_client.create_playlist.assert_called_once_with("New")
        mock_client.add_to_playlist.assert_not_called()
        mock_client.get_playlist_content.assert_not_called()
        # The playlists are listed once done
        mock_client.playlists_property.assert_called_once()
        assert "Jazz Classics" in result.output

    def test_create_without_the_resulting_list(self, runner: CliRunner, mocker: MockerFixture):
        """--no-print-resulting-list skips the listing of the playlists."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "playlist", "create", "New", "--no-print-resulting-list"]
        )

        assert result.exit_code == 0
        mock_client.create_playlist.assert_called_once_with("New")
        mock_client.playlists_property.assert_not_called()
        assert "Jazz Classics" not in result.output

    def test_create_importing_a_file(self, runner: CliRunner, mocker: MockerFixture, tmp_path):
        """-f/--import-from-file fills the new playlist with the items of the file."""
        mock_client = self._mock_websocket_client(mocker)
        source = tmp_path / "rock.json"
        source.write_text(
            json.dumps(
                [
                    {
                        "album": "Album X",
                        "artist": "Artist A",
                        "duration": "00:01:01",
                        "position": 1,
                        "service": "mpd",
                        "title": "Song A",
                        "uri": "music-library/a.flac",
                    },
                    {"position": 2, "uri": "qobuz://track/2"},
                ],
                indent=4,
            )
        )

        result = runner.invoke(
            main, [*self._WEBSOCKET, "playlist", "create", "New", "-f", str(source)]
        )

        assert result.exit_code == 0
        assert f'Importing 2 items of "{source}" into "New"' in result.output
        assert "Command 'create playlist \"New\"' executed successfully" in result.output
        mock_client.create_playlist.assert_called_once_with("New")
        assert mock_client.add_to_playlist.call_args_list == [
            mocker.call("New", "music-library/a.flac", "mpd"),
            mocker.call("New", "qobuz://track/2", None),
        ]
        # The resulting content is printed, as "playlist content" prints it
        mock_client.get_playlist_content.assert_called_once_with("New")
        assert '"uri": "music-library/a.flac"' in result.output

    def test_create_importing_a_raw_file(self, runner: CliRunner, mocker: MockerFixture, tmp_path):
        """A file in the raw format holds the envelope of the host, whose lists are read."""
        mock_client = self._mock_websocket_client(mocker)
        source = tmp_path / "rock.json"
        source.write_text(json.dumps(self._CONTENT))

        result = runner.invoke(
            main,
            [
                *self._WEBSOCKET,
                "playlist",
                "create",
                "New",
                "-f",
                str(source),
                "--no-print-resulting-content",
            ],
        )

        assert result.exit_code == 0
        assert f'Importing 2 items of "{source}" into "New"' in result.output
        # The tracks of every list of the envelope, in order
        assert mock_client.add_to_playlist.call_args_list == [
            mocker.call("New", "music-library/a.flac", "mpd"),
            mocker.call("New", "qobuz://track/2", "qobuz"),
        ]

    def test_create_importing_a_file_without_the_resulting_content(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """--no-print-resulting-content skips the print after the import."""
        mock_client = self._mock_websocket_client(mocker)
        source = tmp_path / "rock.json"
        source.write_text(json.dumps([{"uri": "qobuz://track/2", "service": "qobuz"}]))

        result = runner.invoke(
            main,
            [
                *self._WEBSOCKET,
                "playlist",
                "create",
                "New",
                "--import-from-file",
                str(source),
                "--no-print-resulting-content",
            ],
        )

        assert result.exit_code == 0
        mock_client.add_to_playlist.assert_called_once_with("New", "qobuz://track/2", "qobuz")
        mock_client.get_playlist_content.assert_not_called()

    @pytest.mark.parametrize(
        "content",
        [
            '{"uri": "qobuz://track/2"}',
            '{"name": "Rock", "lists": "none"}',
            "[1]",
            '[{"title": "No URI"}]',
            '[{"uri": ""}]',
            '[{"uri": "qobuz://track/2", "service": 3}]',
        ],
    )
    def test_create_importing_a_file_of_another_shape(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path, content
    ):
        """A file that is not a list of items with a URI is a usage error."""
        mock_client = self._mock_websocket_client(mocker)
        source = tmp_path / "rock.json"
        source.write_text(content)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "playlist", "create", "New", "-f", str(source)]
        )

        assert result.exit_code == 2
        assert "Expected FILE to hold a JSON list of playlist items" in result.output
        mock_client.create_playlist.assert_not_called()

    def test_create_importing_an_unreadable_file(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """A file that cannot be read, or is not JSON, ends the command before creating."""
        mock_client = self._mock_websocket_client(mocker)
        source = tmp_path / "rock.json"
        source.write_text("not json")

        result = runner.invoke(
            main, [*self._WEBSOCKET, "playlist", "create", "New", "-f", str(source)]
        )

        assert result.exit_code == 1
        assert f'Cannot read playlist file "{source}"' in result.output
        mock_client.create_playlist.assert_not_called()

    def test_delete_refused_without_yes(self, runner: CliRunner, mocker: MockerFixture):
        """Without -y/--yes nothing is deleted, nor looked up."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "playlist", "delete", "Rock"])

        assert result.exit_code == 1
        assert 'Refusing to delete the playlist without -y/--yes: "Rock"' in result.output
        mock_client.playlists_property.assert_not_called()
        mock_client.delete_playlist.assert_not_called()

    _REMAINING = ["Jazz Classics", "Ambient"]
    """The playlists once "Rock" is deleted."""

    def test_delete(self, runner: CliRunner, mocker: MockerFixture):
        """With -y/--yes the playlist is deleted, after the name check, and the rest listed."""
        mock_client = self._mock_websocket_client(mocker)
        _attach_property(mock_client, "playlists", side_effect=[self.PLAYLISTS, self._REMAINING])

        result = runner.invoke(main, [*self._WEBSOCKET, "playlist", "delete", "Rock", "-y"])

        assert result.exit_code == 0
        assert "Command 'delete playlist \"Rock\"' executed successfully" in result.output
        mock_client.delete_playlist.assert_called_once_with("Rock")
        # The playlists are read for the check, then once the deletion is seen, and listed
        assert mock_client.playlists_property.call_count == 2
        assert '    "Jazz Classics"' in result.output
        assert '    "Rock"' not in result.output

    def test_delete_waits_for_the_deletion(self, runner: CliRunner, mocker: MockerFixture):
        """The playlists are read again while the host still lists the deleted one."""
        mock_client = self._mock_websocket_client(mocker)
        _attach_property(
            mock_client,
            "playlists",
            side_effect=[self.PLAYLISTS, self.PLAYLISTS, self.PLAYLISTS, self._REMAINING],
        )

        result = runner.invoke(main, [*self._WEBSOCKET, "playlist", "delete", "Rock", "-y"])

        assert result.exit_code == 0
        assert mock_client.playlists_property.call_count == 4
        assert '    "Rock"' not in result.output

    def test_delete_still_listed(self, runner: CliRunner, mocker: MockerFixture):
        """A playlist the host keeps listing after a few reads is reported."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "playlist", "delete", "Rock", "-y"])

        assert result.exit_code == 1
        assert 'The Volumio host still lists the playlist "Rock" after the deletion' in (
            result.output
        )
        mock_client.delete_playlist.assert_called_once_with("Rock")
        # One read for the check, then the bounded reads waiting for the deletion
        assert mock_client.playlists_property.call_count == 4
        assert '    "Jazz Classics"' not in result.output

    def test_delete_without_the_resulting_list(self, runner: CliRunner, mocker: MockerFixture):
        """--no-print-resulting-list skips the listing of the playlists."""
        mock_client = self._mock_websocket_client(mocker)
        _attach_property(mock_client, "playlists", side_effect=[self.PLAYLISTS, self._REMAINING])

        result = runner.invoke(
            main,
            [*self._WEBSOCKET, "playlist", "delete", "Rock", "-y", "--no-print-resulting-list"],
        )

        assert result.exit_code == 0
        mock_client.delete_playlist.assert_called_once_with("Rock")
        assert mock_client.playlists_property.call_count == 2
        assert '    "Jazz Classics"' not in result.output

    def test_delete_without_the_check(self, runner: CliRunner, mocker: MockerFixture):
        """--no-check-playlist-name deletes without looking the name up first."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main,
            [*self._WEBSOCKET, "playlist", "delete", "Gone", "-y", "--no-check-playlist-name",
             "--no-print-resulting-list"],
        )

        assert result.exit_code == 0
        # The only read waits for the deletion
        mock_client.playlists_property.assert_called_once()
        mock_client.delete_playlist.assert_called_once_with("Gone")

    def test_enqueue(self, runner: CliRunner, mocker: MockerFixture):
        """playlist enqueue appends the playlist to the queue."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "playlist", "enqueue", "Rock", "--no-print-resulting-status"]
        )

        assert result.exit_code == 0
        assert "Command 'enqueue playlist \"Rock\"' executed successfully" in result.output
        mock_client.playlists_property.assert_called_once()
        mock_client.enqueue_playlist.assert_called_once_with("Rock")
        mock_client.state_property.assert_not_called()

    def test_enqueue_prints_the_resulting_status(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """By default the resulting playback status is printed."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "playlist", "enqueue", "Rock"])

        assert result.exit_code == 0
        assert "StatusMarkerArtist" in result.output
        mock_client.state_property.assert_called_once()

    @pytest.mark.parametrize(
        ("options", "service"), [([], None), (["--service", "qobuz"], "qobuz")]
    )
    def test_remove(self, runner: CliRunner, mocker: MockerFixture, options, service):
        """playlist remove checks the name, then removes the URI, of the given service."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "playlist", "remove", "Rock", self._URI, *options]
        )

        assert result.exit_code == 0
        assert "Command 'remove from playlist \"Rock\"' executed successfully" in result.output
        # The resulting content is printed, as "playlist content" prints it
        assert '"uri": "music-library/a.flac"' in result.output
        mock_client.playlists_property.assert_called_once()
        mock_client.remove_from_playlist.assert_called_once_with("Rock", self._URI, service)
        # One content read checks the removal, one prints the resulting content
        assert mock_client.get_playlist_content.call_count == 2
        assert "leave the playlist" not in result.output

    @pytest.mark.parametrize(
        ("position", "uri", "service"),
        [("1", "music-library/a.flac", "mpd"), ("2", "qobuz://track/2", "qobuz")],
    )
    def test_remove_by_position(
        self, runner: CliRunner, mocker: MockerFixture, position, uri, service
    ):
        """-p/--position removes the item listed there, by the URI and service it holds."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "playlist", "remove", "Rock", "-p", position]
        )

        assert result.exit_code == 0
        assert "Command 'remove from playlist \"Rock\"' executed successfully" in result.output
        assert "leave the playlist" not in result.output
        mock_client.remove_from_playlist.assert_called_once_with("Rock", uri, service)
        # One content read resolves the position, one prints the resulting content
        assert mock_client.get_playlist_content.call_count == 2

    def test_remove_all_occurrences(self, runner: CliRunner, mocker: MockerFixture):
        """--all-occurrences sends one removal per item listed at the URI."""
        mock_client = self._mock_websocket_client(mocker)
        mock_client.get_playlist_content.return_value = PlaylistContent.from_envelope(
            {
                "name": "Rock",
                "lists": [
                    [
                        {"title": "A", "service": "mpd", "uri": "mpd://a"},
                        {"title": "B", "service": "mpd", "uri": "mpd://b"},
                        {"title": "A", "service": "mpd", "uri": "mpd://a"},
                    ]
                ],
            }
        )

        result = runner.invoke(
            main,
            [*self._WEBSOCKET, "playlist", "remove", "Rock", "mpd://a", "--all-occurrences"],
        )

        assert result.exit_code == 0
        assert "Command 'remove from playlist \"Rock\"' executed successfully" in result.output
        assert "leave the playlist" not in result.output
        assert mock_client.remove_from_playlist.call_args_list == [
            mocker.call("Rock", "mpd://a", None),
            mocker.call("Rock", "mpd://a", None),
        ]

    def test_remove_first_occurrence_only_by_default(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """Without --all-occurrences, one removal is sent, whatever the playlist lists."""
        mock_client = self._mock_websocket_client(mocker)
        mock_client.get_playlist_content.return_value = PlaylistContent.from_envelope(
            {
                "name": "Rock",
                "lists": [
                    [
                        {"title": "A", "service": "mpd", "uri": "mpd://a"},
                        {"title": "A", "service": "mpd", "uri": "mpd://a"},
                    ]
                ],
            }
        )

        result = runner.invoke(
            main,
            [*self._WEBSOCKET, "playlist", "remove", "Rock", "mpd://a", "--first-occurrence-only"],
        )

        assert result.exit_code == 0
        mock_client.remove_from_playlist.assert_called_once_with("Rock", "mpd://a", None)

    def test_remove_all_occurrences_of_every_item_warns(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """Occurrences covering the whole playlist warn that the host may refuse it."""
        mock_client = self._mock_websocket_client(mocker)
        mock_client.get_playlist_content.return_value = PlaylistContent.from_envelope(
            {
                "name": "Rock",
                "lists": [
                    [
                        {"title": "A", "service": "mpd", "uri": "mpd://a"},
                        {"title": "A", "service": "mpd", "uri": "mpd://a"},
                    ]
                ],
            }
        )

        result = runner.invoke(
            main,
            [*self._WEBSOCKET, "playlist", "remove", "Rock", "mpd://a", "--all-occurrences"],
        )

        assert result.exit_code == 0
        assert 'The removal would leave the playlist "Rock" empty' in result.output
        assert mock_client.remove_from_playlist.call_count == 2

    def test_remove_all_occurrences_of_a_uri_not_listed(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """A URI the playlist does not list exits 1 with --all-occurrences, sending nothing."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main,
            [*self._WEBSOCKET, "playlist", "remove", "Rock", "mpd://nope", "--all-occurrences"],
        )

        assert result.exit_code == 1
        assert 'No item at URI "mpd://nope" in the playlist "Rock".' in result.output
        mock_client.remove_from_playlist.assert_not_called()

    def test_remove_the_last_item_warns(self, runner: CliRunner, mocker: MockerFixture):
        """Removing the only item of a playlist warns that the host may refuse it."""
        mock_client = self._mock_websocket_client(mocker)
        mock_client.get_playlist_content.return_value = PlaylistContent.from_envelope(
            {"name": "Rock", "lists": [[{"title": "Only", "service": "mpd", "uri": "mpd://a"}]]}
        )

        result = runner.invoke(main, [*self._WEBSOCKET, "playlist", "remove", "Rock", "mpd://a"])

        assert result.exit_code == 0
        assert (
            'The removal would leave the playlist "Rock" empty, which the Volumio host may '
            'refuse: to empty a playlist, delete it with "playlist delete" and create it '
            'again with "playlist create".'
        ) in result.output
        mock_client.remove_from_playlist.assert_called_once_with("Rock", "mpd://a", None)

    def test_remove_another_uri_from_a_one_item_playlist_does_not_warn(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """A URI the only item does not hold cannot empty the playlist."""
        mock_client = self._mock_websocket_client(mocker)
        mock_client.get_playlist_content.return_value = PlaylistContent.from_envelope(
            {"name": "Rock", "lists": [[{"title": "Only", "service": "mpd", "uri": "mpd://a"}]]}
        )

        result = runner.invoke(main, [*self._WEBSOCKET, "playlist", "remove", "Rock", "mpd://b"])

        assert result.exit_code == 0
        assert "leave the playlist" not in result.output

    def test_remove_by_every_position_warns(self, runner: CliRunner, mocker: MockerFixture):
        """A selection covering the whole playlist warns that the host may refuse it."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "playlist", "remove", "Rock", "-p", "1-2"]
        )

        assert result.exit_code == 0
        assert 'The removal would leave the playlist "Rock" empty' in result.output
        assert mock_client.remove_from_playlist.call_count == 2

    def test_remove_by_position_starting_at_zero(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """The position is read according to the indexing base in use."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main,
            [
                "--position-starting-at-zero",
                *self._WEBSOCKET,
                "playlist",
                "remove",
                "Rock",
                "--position",
                "0",
            ],
        )

        assert result.exit_code == 0
        mock_client.remove_from_playlist.assert_called_once_with(
            "Rock", "music-library/a.flac", "mpd"
        )

    def test_remove_by_a_selection_of_positions(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """A selection removes every item listed there, in position order."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "playlist", "remove", "Rock", "-p", "2,1-1"]
        )

        assert result.exit_code == 0
        assert result.output.count("executed successfully") == 1
        assert mock_client.remove_from_playlist.call_args_list == [
            mocker.call("Rock", "music-library/a.flac", "mpd"),
            mocker.call("Rock", "qobuz://track/2", "qobuz"),
        ]
        assert mock_client.get_playlist_content.call_count == 2

    def test_remove_by_a_selection_past_the_end(self, runner: CliRunner, mocker: MockerFixture):
        """Every position the playlist does not reach is named, and nothing is removed."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "playlist", "remove", "Rock", "-p", "1,3-4"]
        )

        assert result.exit_code == 1
        assert (
            'Invalid value: the playlist "Rock" lists 2 items, none at positions 3, 4'
            in result.output
        )
        mock_client.remove_from_playlist.assert_not_called()

    def test_remove_by_a_malformed_selection(self, runner: CliRunner, mocker: MockerFixture):
        """A selection that is not positions and ranges is a usage error."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "playlist", "remove", "Rock", "-p", "1,two"]
        )

        assert result.exit_code == 2
        assert "invalid item 'two'" in result.output
        mock_client.remove_from_playlist.assert_not_called()

    def test_remove_by_a_position_past_the_end(self, runner: CliRunner, mocker: MockerFixture):
        """A position the playlist does not reach is an invalid value."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "playlist", "remove", "Rock", "-p", "3"])

        assert result.exit_code == 1
        assert (
            'Invalid value: the playlist "Rock" lists 2 items, none at position 3'
            in result.output
        )
        mock_client.remove_from_playlist.assert_not_called()

    def test_remove_by_the_position_of_an_item_without_a_uri(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """An item the host lists without a URI cannot be removed by position."""
        mock_client = self._mock_websocket_client(mocker)
        mock_client.get_playlist_content.return_value = PlaylistContent.from_envelope(
            {"name": "Rock", "lists": [[{"title": "No URI", "service": "mpd"}]]}
        )

        result = runner.invoke(main, [*self._WEBSOCKET, "playlist", "remove", "Rock", "-p", "1"])

        assert result.exit_code == 1
        assert 'the item at position 1 of the playlist "Rock" has no URI' in result.output
        mock_client.remove_from_playlist.assert_not_called()

    def test_remove_by_the_positions_of_items_without_a_uri(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """Every selected item the host lists without a URI is named."""
        mock_client = self._mock_websocket_client(mocker)
        mock_client.get_playlist_content.return_value = PlaylistContent.from_envelope(
            {"name": "Rock", "lists": [[{"title": "One"}, {"title": "Two"}]]}
        )

        result = runner.invoke(
            main, [*self._WEBSOCKET, "playlist", "remove", "Rock", "-p", "1-2"]
        )

        assert result.exit_code == 1
        assert 'the items at positions 1, 2 of the playlist "Rock" have no URI' in result.output
        mock_client.remove_from_playlist.assert_not_called()

    @pytest.mark.parametrize(
        "arguments",
        [
            ["Rock"],
            ["Rock", _URI, "-p", "1"],
            ["Rock", "-p", "1", "--service", "qobuz"],
            ["Rock", "-p", "1", "--all-occurrences"],
        ],
    )
    def test_remove_usage_errors(self, runner: CliRunner, mocker: MockerFixture, arguments):
        """A URI or a position is expected, not both; the URI-only options need the URI."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "playlist", "remove", *arguments])

        assert result.exit_code == 2
        assert "Expected" in result.output
        mock_client.remove_from_playlist.assert_not_called()

    @pytest.mark.parametrize(
        "arguments",
        [
            ["add", "Rock", _URI],
            ["content", "Rock"],
            ["copy", "Rock", "New"],
            ["rename", "Rock", "New"],
            ["create", "New"],
            ["delete", "Rock", "-y"],
            ["enqueue", "Rock"],
            ["remove", "Rock", _URI],
        ],
    )
    def test_a_rest_client_refuses(self, runner: CliRunner, mocker: MockerFixture, arguments):
        """With the default REST API client, the edits fail naming the remedies."""
        mock_client, _ = self._mock_client(mocker)

        result = runner.invoke(main, ["playlist", *arguments])

        assert result.exit_code == 1
        assert self._REFUSAL in result.output
        mock_client.play_playlist.assert_not_called()

    def test_a_rest_client_falls_back_when_allowed(self, runner: CliRunner, mocker: MockerFixture):
        """With the switch, the REST API client serves the edit through a WebSocket one."""
        rest, _ = self._mock_client(mocker)
        rest.logger = LOGGER
        websocket = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, ["--allow-fallback-to-websocket-api", "playlist", "create", "New"]
        )

        assert result.exit_code == 0
        assert "Falling back to the WebSocket API client for the playlist edits" in result.output
        websocket.create_playlist.assert_called_once_with("New")
        websocket.disconnect.assert_called_once_with()
        rest.close.assert_called_once_with()

    def test_play_unknown_name_is_case_sensitive(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """The name must match exactly: a different casing is not accepted."""
        mock_client, _ = self._mock_client(mocker)

        result = runner.invoke(main, ["playlist", "play", "rock"])

        assert result.exit_code == 1
        mock_client.play_playlist.assert_not_called()

    def test_play_unknown_name_with_no_playlists(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """With no saved playlists the error reports that none are available."""
        mock_client, _ = self._mock_client(mocker, playlists=[])

        result = runner.invoke(main, ["playlist", "play", "Rock"])

        assert result.exit_code == 1
        assert "Available playlists:" in result.output
        assert "  (none)" in result.output

    def test_download_unknown_name_with_no_playlists(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """The download twin of the empty-playlists error reports none as well."""
        mock_client, _ = self._mock_client(mocker, playlists=[])

        result = runner.invoke(main, ["playlist", "download", "Rock"])

        assert result.exit_code == 1
        assert "Available playlists:" in result.output
        assert "  (none)" in result.output
        mock_client.play_playlist.assert_not_called()

    def test_play_unknown_name_machine_readable(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """In machine-readable mode the not-found error is silent."""
        mock_client, _ = self._mock_client(mocker)

        result = runner.invoke(main, ["-m", "playlist", "play", "Nope"])

        assert result.exit_code == 1
        assert result.output == ""
        mock_client.play_playlist.assert_not_called()

    def test_play_no_check_playlist_name(self, runner: CliRunner, mocker: MockerFixture):
        """With --no-check-playlist-name the name is not looked up."""
        mock_client, _ = self._mock_client(mocker)

        result = runner.invoke(
            main,
            [
                "playlist",
                "play",
                "Nope",
                "--no-check-playlist-name",
                "--no-print-resulting-status",
            ],
        )

        assert result.exit_code == 0
        mock_client.playlists_property.assert_not_called()
        mock_client.play_playlist.assert_called_once_with("Nope")

    def test_play_check_connection_error(self, runner: CliRunner, mocker: MockerFixture):
        """A failing lookup exits 1 without sending the command."""
        mock_client, _ = self._mock_client(mocker)
        _attach_property(
            mock_client, "playlists", side_effect=VolumioConnectionError("Connection failed")
        )

        result = runner.invoke(main, ["playlist", "play", "Rock"])

        assert result.exit_code == 1
        assert "Connection error" in result.output
        mock_client.play_playlist.assert_not_called()

    def test_play_connection_error(self, runner: CliRunner, mocker: MockerFixture):
        """playlist play exits 1 on a connection error."""
        mock_client, _ = self._mock_client(mocker)
        mock_client.play_playlist.side_effect = VolumioConnectionError("Connection failed")

        result = runner.invoke(main, ["playlist", "play", "Rock"])

        assert result.exit_code == 1
        assert "Connection error" in result.output


class TestScpCommands:
    """Test cases for the scp get and scp put commands."""

    @pytest.fixture
    def runner(self):
        """Create a CliRunner instance."""
        return CliRunner()

    def test_group_help(self, runner: CliRunner):
        """The scp group lists both of its commands, and warns about the host."""
        result = runner.invoke(main, ["scp", "--help"])

        assert result.exit_code == 0
        assert "get" in result.output
        assert "put" in result.output
        # The help is wrapped, so the note is matched on the joined text
        assert "copying to the Volumio host may damage its integrity" in " ".join(
            result.output.split()
        )

    def test_put_help(self, runner: CliRunner):
        """The warning about the host is on the writing command too."""
        result = runner.invoke(main, ["scp", "put", "--help"])

        assert result.exit_code == 0
        joined = " ".join(result.output.split())
        assert "writes to the Volumio host and may damage its integrity" in joined
        assert "the copy is made only when -y/--yes is given" in joined

    def test_get_help(self, runner: CliRunner):
        """The reading command carries no such warning."""
        result = runner.invoke(main, ["scp", "get", "--help"])

        assert result.exit_code == 0
        assert "damage" not in result.output

    def test_get(self, runner: CliRunner, mocker: MockerFixture):
        """scp get copies a path of the host to a local one."""
        copy = mocker.patch("volumito.cli.volumito.copy_from_host")

        result = runner.invoke(main, ["scp", "get", "/tmp/remote_file", "./local_file"])

        assert result.exit_code == 0
        assert (
            result.output.strip()
            .endswith('[INFO] Copied "/tmp/remote_file" from the Volumio host to "./local_file"')
        )
        assert copy.call_args.args[1:] == ("/tmp/remote_file", "./local_file")
        assert copy.call_args.kwargs == {"recursive": False}

    def test_get_recursive(self, runner: CliRunner, mocker: MockerFixture):
        """-r/--recursive is forwarded."""
        copy = mocker.patch("volumito.cli.volumito.copy_from_host")

        result = runner.invoke(main, ["scp", "get", "-r", "/mnt/INTERNAL/music", "./music"])

        assert result.exit_code == 0
        assert copy.call_args.kwargs == {"recursive": True}

    def test_get_machine_readable(self, runner: CliRunner, mocker: MockerFixture):
        """scp get prints nothing in machine-readable mode."""
        mocker.patch("volumito.cli.volumito.copy_from_host")

        result = runner.invoke(main, ["-m", "scp", "get", "/tmp/a", "./a"])

        assert result.exit_code == 0
        assert result.output == ""

    def test_get_failing(self, runner: CliRunner, mocker: MockerFixture):
        """A failed copy exits 1, reporting what went wrong."""
        mocker.patch(
            "volumito.cli.volumito.copy_from_host",
            side_effect=VolumioSCPError("No such file"),
        )

        result = runner.invoke(main, ["scp", "get", "/tmp/nope", "./nope"])

        assert result.exit_code == 1
        assert "No such file" in result.output

    def test_get_failing_machine_readable(self, runner: CliRunner, mocker: MockerFixture):
        """A failed copy prints nothing in machine-readable mode."""
        mocker.patch(
            "volumito.cli.volumito.copy_from_host",
            side_effect=VolumioSCPError("No such file"),
        )

        result = runner.invoke(main, ["-m", "scp", "get", "/tmp/nope", "./nope"])

        assert result.exit_code == 1
        assert result.output == ""

    def test_put(self, runner: CliRunner, mocker: MockerFixture):
        """scp put copies a local path to one of the host."""
        copy = mocker.patch("volumito.cli.volumito.copy_to_host")

        result = runner.invoke(
            main, ["scp", "put", "-y", "/tmp/local_file", "/mnt/INTERNAL/remote_file"]
        )

        assert result.exit_code == 0
        assert (
            result.output.strip()
            .endswith(
                '[INFO] Copied "/tmp/local_file" to "/mnt/INTERNAL/remote_file" '
                "on the Volumio host"
            )
        )
        assert copy.call_args.args[1:] == ("/tmp/local_file", "/mnt/INTERNAL/remote_file")
        assert copy.call_args.kwargs == {"recursive": False}

    def test_put_recursive(self, runner: CliRunner, mocker: MockerFixture):
        """-r/--recursive is forwarded, with the SSH options of the host configuration."""
        copy = mocker.patch("volumito.cli.volumito.copy_to_host")

        result = runner.invoke(
            main,
            [
                "--ssh-username",
                "pi",
                "scp",
                "put",
                "--yes",
                "--recursive",
                "/tmp/local_directory",
                "/mnt/INTERNAL/remote_directory",
            ],
        )

        assert result.exit_code == 0
        assert copy.call_args.kwargs == {"recursive": True}
        assert copy.call_args.args[0].ssh_username == "pi"

    def test_put_without_yes(self, runner: CliRunner, mocker: MockerFixture):
        """Without -y/--yes nothing is copied to the host."""
        copy = mocker.patch("volumito.cli.volumito.copy_to_host")

        result = runner.invoke(main, ["scp", "put", "/tmp/a", "/mnt/INTERNAL/a"])

        assert result.exit_code == 1
        assert (
            'Refusing to copy to the Volumio host without -y/--yes: "/mnt/INTERNAL/a"'
            in result.output
        )
        copy.assert_not_called()

    def test_put_without_yes_machine_readable(self, runner: CliRunner, mocker: MockerFixture):
        """The refusal prints nothing in machine-readable mode."""
        copy = mocker.patch("volumito.cli.volumito.copy_to_host")

        result = runner.invoke(main, ["-m", "scp", "put", "/tmp/a", "/mnt/a"])

        assert result.exit_code == 1
        assert result.output == ""
        copy.assert_not_called()

    def test_put_failing(self, runner: CliRunner, mocker: MockerFixture):
        """A failed copy exits 1, reporting what went wrong."""
        mocker.patch(
            "volumito.cli.volumito.copy_to_host",
            side_effect=VolumioSCPError("Permission denied"),
        )

        result = runner.invoke(main, ["scp", "put", "-y", "/tmp/a", "/mnt/a"])

        assert result.exit_code == 1
        assert "Permission denied" in result.output

    def test_put_machine_readable(self, runner: CliRunner, mocker: MockerFixture):
        """scp put prints nothing in machine-readable mode."""
        mocker.patch("volumito.cli.volumito.copy_to_host")

        result = runner.invoke(main, ["-m", "scp", "put", "-y", "/tmp/a", "/mnt/a"])

        assert result.exit_code == 0
        assert result.output == ""


class TestNotificationEvents:
    """Test cases for the notification event subgroup."""

    STATE = {"status": "play", "title": "Caterina", "artist": "Francesco De Gregori"}
    """A playback state, as a pushState event carries it."""

    _REFUSAL = (
        "API client error: The Synchronous REST API client does not offer the events: "
        "use --api-client synchronous_websocket or asynchronous_websocket, "
        "or --allow-fallback-to-websocket-api"
    )
    """The error of a REST API client asked for an event member, without the fallback."""

    _WEBSOCKET = ["-C", "synchronous_websocket"]
    """The global option selecting the WebSocket API client the commands need."""

    @pytest.fixture
    def runner(self):
        """Create a CliRunner instance."""
        return CliRunner()

    def _mock_rest_client(self, mocker: MockerFixture):
        """Mock VolumioRESTAPIClient, the default client."""
        mock_client = mocker.Mock()
        mock_client.logger = LOGGER
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        return mock_client

    def _mock_websocket_client(self, mocker: MockerFixture, pushes: dict | None = None):
        """Mock VolumioWebSocketClient pushing, on registration, the payload of each event.

        Args:
            mocker: The mocker fixture
            pushes: The payload each event carries the moment its handler is registered,
                keyed by event name; an event outside the mapping is never pushed
        """
        mock_client = mocker.Mock()
        mock_client.logger = LOGGER
        pushed = {} if pushes is None else pushes

        def register(event, handler):
            if event in pushed:
                handler(pushed[event])

        mock_client.on.side_effect = register
        mock_client.request.return_value = {"answer": 42}
        mocker.patch(
            "volumito.cli.click_helpers.VolumioWebSocketClient",
            return_value=mock_client,
        )
        return mock_client

    def test_listen_prints_the_state_by_default(self, runner: CliRunner, mocker: MockerFixture):
        """Without an event, pushState is listened for, and printed as pretty JSON."""
        mock_client = self._mock_websocket_client(mocker, pushes={"pushState": self.STATE})

        result = runner.invoke(
            main, [*self._WEBSOCKET, "notification", "event", "listen", "-n", "1"]
        )

        assert result.exit_code == 0
        lines = result.output.splitlines()
        assert lines[0].endswith("[INFO] Listening for the events: pushState")
        assert lines[1].endswith(
            "[INFO] Terminate as soon as: CTRL+C is issued, or 1 notification received"
        )
        assert json.loads(result.stdout) == {"event": "pushState", "data": self.STATE}
        mock_client.on.assert_called_once()
        assert mock_client.on.call_args.args[0] == "pushState"
        # The handler is unregistered on the way out
        mock_client.off.assert_called_once_with("pushState", mock_client.on.call_args.args[1])

    def test_listen_several_events(self, runner: CliRunner, mocker: MockerFixture):
        """Each event named is listened for, and printed as it arrives."""
        mock_client = self._mock_websocket_client(
            mocker, pushes={"pushState": self.STATE, "pushQueue": [{"title": "Caterina"}]}
        )

        result = runner.invoke(
            main,
            [*self._WEBSOCKET, "notification", "event", "listen", "pushState", "pushQueue",
             "-n", "2", "-F", "raw"],
        )

        assert result.exit_code == 0
        events = [json.loads(line) for line in result.stdout.splitlines()]
        assert [event["event"] for event in events] == ["pushState", "pushQueue"]
        assert events[1]["data"] == [{"title": "Caterina"}]
        assert mock_client.off.call_count == 2

    def test_listen_table_format(self, runner: CliRunner, mocker: MockerFixture):
        """-F table prints one line per event, named and timestamped."""
        self._mock_websocket_client(mocker, pushes={"pushState": self.STATE})

        result = runner.invoke(
            main, [*self._WEBSOCKET, "notification", "event", "listen", "-n", "1", "-F", "table"]
        )

        assert result.exit_code == 0
        line = result.stdout.strip()
        assert line.startswith("[")
        assert "pushState" in line
        assert "Caterina" in line

    def test_listen_json_and_machine_readable(self, runner: CliRunner, mocker: MockerFixture):
        """-F json indents the event, the machine-readable mode prints it compact."""
        self._mock_websocket_client(mocker, pushes={"pushState": self.STATE})

        indented = runner.invoke(
            main, [*self._WEBSOCKET, "notification", "event", "listen", "-n", "1", "-F", "json"]
        )
        compact = runner.invoke(
            main, ["-m", *self._WEBSOCKET, "notification", "event", "listen", "-n", "1"]
        )

        assert indented.exit_code == 0
        assert '\n  "event": "pushState"' in indented.output
        assert compact.exit_code == 0
        assert compact.output.strip() == json.dumps({"event": "pushState", "data": self.STATE})

    def test_listen_times_out(self, runner: CliRunner, mocker: MockerFixture):
        """Without an event, --timeout ends the listening, failing when a count was asked."""
        self._mock_websocket_client(mocker)

        plain = runner.invoke(
            main, [*self._WEBSOCKET, "notification", "event", "listen", "--timeout", "0.05"]
        )
        counted = runner.invoke(
            main,
            [*self._WEBSOCKET, "notification", "event", "listen", "--timeout", "0.05", "-n", "1"],
        )

        assert plain.exit_code == 0
        assert "Timed out after 0.05 seconds" in plain.output
        assert counted.exit_code == 1
        assert "Timed out after 0.05 seconds" in counted.output

    def test_listen_with_a_zero_timeout(self, runner: CliRunner, mocker: MockerFixture):
        """A deadline already passed ends the listening before any wait."""
        mock_client = self._mock_websocket_client(mocker, pushes={"pushState": self.STATE})

        result = runner.invoke(
            main, [*self._WEBSOCKET, "notification", "event", "listen", "--timeout", "0"]
        )

        assert result.exit_code == 0
        assert "Timed out after 0 seconds" in result.output
        mock_client.off.assert_called_once()

    def test_listen_idle_times_out(self, runner: CliRunner, mocker: MockerFixture):
        """--idle-timeout ends the listening after a silence, counting what arrived."""
        self._mock_websocket_client(mocker, pushes={"pushState": self.STATE})

        result = runner.invoke(
            main,
            [*self._WEBSOCKET, "notification", "event", "listen", "--idle-timeout", "0.05",
             "-n", "2"],
        )

        assert result.exit_code == 1
        assert json.loads(result.stdout) == {"event": "pushState", "data": self.STATE}
        assert "Timed out after 0.05 seconds without events" in result.output

    def test_listen_deadline_before_the_idle_timeout(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """A deadline closer than the idle timeout is the one reported."""
        self._mock_websocket_client(mocker)

        result = runner.invoke(
            main,
            [*self._WEBSOCKET, "notification", "event", "listen", "--timeout", "0.05",
             "--idle-timeout", "10"],
        )

        assert result.exit_code == 0
        assert "Timed out after 0.05 seconds" in result.output
        assert "without events" not in result.output

    def test_listen_interrupted(self, runner: CliRunner, mocker: MockerFixture):
        """Ctrl-C ends the listening quietly, unregistering the handler."""
        mock_client = self._mock_websocket_client(mocker)
        mocker.patch("volumito.cli.volumito.Queue.get", side_effect=KeyboardInterrupt)

        result = runner.invoke(main, [*self._WEBSOCKET, "notification", "event", "listen"])

        assert result.exit_code == 0
        assert "Timed out" not in result.output
        mock_client.off.assert_called_once()

    def test_emit_refused_without_yes(self, runner: CliRunner, mocker: MockerFixture):
        """Without -y/--yes nothing is sent."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "notification", "event", "emit", "rebuildAlbumart"]
        )

        assert result.exit_code == 1
        assert 'Refusing to emit the event without -y/--yes: "rebuildAlbumart"' in result.output
        mock_client.emit.assert_not_called()

    @pytest.mark.parametrize(
        ("arguments", "payload"),
        [([], None), (['{"uri": "music-library"}'], {"uri": "music-library"}), (["42"], 42)],
    )
    def test_emit(self, runner: CliRunner, mocker: MockerFixture, arguments, payload):
        """With -y/--yes the event is sent, with the JSON payload given."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "notification", "event", "emit", "updateDb", *arguments, "-y"]
        )

        assert result.exit_code == 0
        assert "Command 'emit \"updateDb\"' executed successfully" in result.output
        mock_client.emit.assert_called_once_with("updateDb", payload)

    def test_emit_with_a_bad_payload(self, runner: CliRunner, mocker: MockerFixture):
        """A payload that is not JSON is a usage error, before the refusal."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "notification", "event", "emit", "updateDb", "{oops"]
        )

        assert result.exit_code == 2
        assert "Expected PAYLOAD to be JSON" in result.output
        mock_client.emit.assert_not_called()

    def test_request(self, runner: CliRunner, mocker: MockerFixture):
        """notification event request sends the event and prints the answer."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main,
            [*self._WEBSOCKET, "notification", "event", "request", "getState", "-F", "table"],
        )

        assert result.exit_code == 0
        assert 'Volumio Event "getState"' in result.output
        assert "42" in result.output
        mock_client.request.assert_called_once_with("getState", None, None, None)

    def test_request_with_the_options(self, runner: CliRunner, mocker: MockerFixture):
        """The payload, the answer event, and the timeout reach the client."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main,
            [*self._WEBSOCKET, "notification", "event", "request", "getInfo", '{"a": 1}',
             "--response-event", "pushInfo", "--timeout", "2.5", "-F", "json"],
        )

        assert result.exit_code == 0
        assert json.loads(result.output) == {"answer": 42}
        mock_client.request.assert_called_once_with("getInfo", "pushInfo", {"a": 1}, 2.5)

    @pytest.mark.parametrize(
        ("options", "expected"),
        [
            ([], "[\n    1,\n    2\n]"),
            (["-F", "json"], "[\n  1,\n  2\n]"),
            (["-F", "raw"], "[1, 2]"),
            (["-F", "table"], "[1, 2]"),
        ],
    )
    def test_request_answered_with_a_list(
        self, runner: CliRunner, mocker: MockerFixture, options, expected
    ):
        """An answer that is not an object is printed as JSON, compact when not indentable."""
        mock_client = self._mock_websocket_client(mocker)
        mock_client.request.return_value = [1, 2]

        result = runner.invoke(
            main, [*self._WEBSOCKET, "notification", "event", "request", "getList", *options]
        )

        assert result.exit_code == 0
        assert result.output.strip() == expected

    def test_request_without_a_known_answer(self, runner: CliRunner, mocker: MockerFixture):
        """An event the client cannot wait for is reported as an invalid value."""
        mock_client = self._mock_websocket_client(mocker)
        mock_client.request.side_effect = ValueError(
            "The Volumio API answers no 'rebuildAlbumart' event: emit it, or name the "
            "event carrying its answer"
        )

        result = runner.invoke(
            main, [*self._WEBSOCKET, "notification", "event", "request", "rebuildAlbumart"]
        )

        assert result.exit_code == 1
        assert "Invalid value: The Volumio API answers no 'rebuildAlbumart' event" in (
            result.output
        )

    @pytest.mark.parametrize(
        "arguments",
        [
            ["emit", "updateDb", "-y"],
            ["listen", "--timeout", "0.05"],
            ["request", "getState"],
        ],
    )
    def test_a_rest_client_refuses(self, runner: CliRunner, mocker: MockerFixture, arguments):
        """With the default REST API client, the commands fail naming the remedies."""
        self._mock_rest_client(mocker)

        result = runner.invoke(main, ["notification", "event", *arguments])

        assert result.exit_code == 1
        assert self._REFUSAL in result.output

    def test_a_rest_client_falls_back_when_allowed(self, runner: CliRunner, mocker: MockerFixture):
        """With the switch, the REST API client serves the command through a WebSocket one."""
        rest = self._mock_rest_client(mocker)
        websocket = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main,
            ["--allow-fallback-to-websocket-api", "notification", "event", "request", "getState",
             "-F", "json"],
        )

        assert result.exit_code == 0
        assert "Falling back to the WebSocket API client for the events" in result.output
        assert json.loads(result.stdout) == {"answer": 42}
        websocket.disconnect.assert_called_once_with()
        rest.close.assert_called_once_with()


class TestNotificationCommands:
    """Test cases for the notifications list, listen, register, and unregister commands."""

    LISTEN_URL = "http://192.168.1.50:3003/volumionotifications"

    NOTIFICATIONS = [
        {
            "item": "state",
            "data": {
                "status": "play",
                "title": "Caterina",
                "artist": "Francesco De Gregori",
            },
        },
        {"item": "queue", "data": [{"title": "Caterina"}]},
    ]

    URLS = ["http://192.168.1.100/receiver", "http://192.168.1.101/other"]

    @pytest.fixture
    def runner(self):
        """Create a CliRunner instance."""
        return CliRunner()

    def _mock_client(self, mocker: MockerFixture, urls=None, response=None):
        """Mock VolumioRESTAPIClient with usable notification members."""
        mock_client = mocker.Mock()
        _attach_property(
            mock_client,
            "notifications",
            return_value=self.URLS if urls is None else urls,
        )
        outcome = SuccessResponse.from_raw({"success": True} if response is None else response)
        mock_client.register_notification.return_value = outcome
        mock_client.unregister_notification.return_value = outcome
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        return mock_client

    def test_group_help(self, runner: CliRunner):
        """The notification group lists its three commands."""
        result = runner.invoke(main, ["notification", "--help"])

        assert result.exit_code == 0
        assert "list" in result.output
        assert "register" in result.output
        assert "unregister" in result.output

    def test_list_default_pretty(self, runner: CliRunner, mocker: MockerFixture):
        """notification list prints the URLs as pretty JSON by default."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["notification", "list"])

        assert result.exit_code == 0
        assert json.loads(result.output) == self.URLS
        # Pretty uses 4-space indentation
        assert '\n    "http://192.168.1.100/receiver"' in result.output

    def test_list_json_format(self, runner: CliRunner, mocker: MockerFixture):
        """notification list -F json prints JSON with 2-space indentation."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["notification", "list", "-F", "json"])

        assert result.exit_code == 0
        assert json.loads(result.output) == self.URLS
        assert '\n  "http://192.168.1.100/receiver"' in result.output

    def test_list_raw_format(self, runner: CliRunner, mocker: MockerFixture):
        """notification list -F raw prints the array as the host returns it."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["notification", "list", "-F", "raw"])

        assert result.exit_code == 0
        assert result.output.strip() == json.dumps(self.URLS)

    def test_list_table_format(self, runner: CliRunner, mocker: MockerFixture):
        """notification list -F table prints a numbered list."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["notification", "list", "-F", "table"])
        lines = result.output.splitlines()

        assert result.exit_code == 0
        assert "Volumio Notification URLs" in lines
        assert "1. http://192.168.1.100/receiver" in lines
        assert "2. http://192.168.1.101/other" in lines

    def test_list_empty(self, runner: CliRunner, mocker: MockerFixture):
        """notification list reports an empty registration list."""
        self._mock_client(mocker, urls=[])

        result = runner.invoke(main, ["notification", "list", "-F", "table"])

        assert result.exit_code == 0
        assert "(empty)" in result.output

    def test_list_connection_error(self, runner: CliRunner, mocker: MockerFixture):
        """notification list exits 1 when the host cannot be reached."""
        mock_client = mocker.Mock()
        _attach_property(
            mock_client, "notifications", side_effect=VolumioConnectionError("Connection failed")
        )
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["notification", "list"])

        assert result.exit_code == 1
        assert "Connection error" in result.output

    def test_register(self, runner: CliRunner, mocker: MockerFixture):
        """notification register registers the URL and names it."""
        mock_client = self._mock_client(mocker)

        result = runner.invoke(main, ["notification", "register", self.URLS[0]])

        assert result.exit_code == 0
        assert result.output.strip().endswith(
            f"[INFO] Registered notification URL: {self.URLS[0]}"
        )
        mock_client.register_notification.assert_called_once_with(self.URLS[0])

    def test_register_autocompose_url(self, runner: CliRunner, mocker: MockerFixture):
        """--autocompose-url registers the URL of the local listener."""
        mock_client = self._mock_client(mocker)
        composed = mocker.patch(
            "volumito.cli.volumito.receiver_url", return_value=self.LISTEN_URL
        )

        result = runner.invoke(main, ["notification", "register", "--autocompose-url"])

        assert result.exit_code == 0
        assert result.output.strip().endswith(
            f"[INFO] Registered notification URL: {self.LISTEN_URL}"
        )
        mock_client.register_notification.assert_called_once_with(self.LISTEN_URL)
        assert composed.call_args.args[1:] == (3003, "/volumionotifications")

    def test_register_autocompose_url_with_a_port_and_an_endpoint(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """The composed URL follows the given port and endpoint."""
        self._mock_client(mocker)
        composed = mocker.patch(
            "volumito.cli.volumito.receiver_url", return_value=self.LISTEN_URL
        )

        result = runner.invoke(
            main, ["notification", "register", "-A", "-p", "9000", "-e", "/hook"]
        )

        assert result.exit_code == 0
        assert composed.call_args.args[1:] == (9000, "/hook")

    def test_register_autocompose_url_with_a_url(self, runner: CliRunner, mocker: MockerFixture):
        """A URL cannot be combined with --autocompose-url."""
        mock_client = self._mock_client(mocker)

        result = runner.invoke(
            main, ["notification", "register", "--autocompose-url", self.URLS[0]]
        )

        assert result.exit_code == 2
        assert "mutually exclusive" in result.output
        mock_client.register_notification.assert_not_called()

    def test_register_without_a_url(self, runner: CliRunner, mocker: MockerFixture):
        """Without a URL and without --autocompose-url, the command says what it expects."""
        mock_client = self._mock_client(mocker)

        result = runner.invoke(main, ["notification", "register"])

        assert result.exit_code == 2
        assert "Expected a URL argument, or the -A/--autocompose-url option." in result.output
        mock_client.register_notification.assert_not_called()

    def test_register_autocompose_url_invalid_endpoint(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """An endpoint without a leading slash is a usage error."""
        self._mock_client(mocker)

        result = runner.invoke(
            main, ["notification", "register", "-A", "-e", "volumionotifications"]
        )

        assert result.exit_code == 2
        assert "The endpoint must start with a slash." in result.output

    def test_register_machine_readable(self, runner: CliRunner, mocker: MockerFixture):
        """notification register prints nothing in machine-readable mode."""
        mock_client = self._mock_client(mocker)

        result = runner.invoke(main, ["-m", "notification", "register", self.URLS[0]])

        assert result.exit_code == 0
        assert result.output == ""
        mock_client.register_notification.assert_called_once_with(self.URLS[0])

    def test_register_refused(self, runner: CliRunner, mocker: MockerFixture):
        """A refused registration exits 1, reporting what the host said."""
        self._mock_client(mocker, response={"error": "Missing URL parameter"})

        result = runner.invoke(main, ["notification", "register", self.URLS[0]])

        assert result.exit_code == 1
        assert (
            f"The Volumio host did not register the URL: {self.URLS[0]} "
            "(Missing URL parameter)" in result.output
        )

    def test_register_refused_without_an_error(self, runner: CliRunner, mocker: MockerFixture):
        """A registration denied without an error message is still reported."""
        self._mock_client(mocker, response={"success": False})

        result = runner.invoke(main, ["notification", "register", self.URLS[0]])

        assert result.exit_code == 1
        assert (
            result.output.strip()
            .endswith(f"[ERRO] The Volumio host did not register the URL: {self.URLS[0]}")
        )

    def test_register_refused_machine_readable(self, runner: CliRunner, mocker: MockerFixture):
        """A refused registration prints nothing in machine-readable mode."""
        self._mock_client(mocker, response={"success": False})

        result = runner.invoke(main, ["-m", "notification", "register", self.URLS[0]])

        assert result.exit_code == 1
        assert result.output == ""

    def test_unregister(self, runner: CliRunner, mocker: MockerFixture):
        """notification unregister unregisters the URL and names it."""
        mock_client = self._mock_client(mocker)

        result = runner.invoke(main, ["notification", "unregister", self.URLS[1]])

        assert result.exit_code == 0
        assert result.output.strip().endswith(
            f"[INFO] Unregistered notification URL: {self.URLS[1]}"
        )
        mock_client.unregister_notification.assert_called_once_with(self.URLS[1])

    def test_unregister_refused(self, runner: CliRunner, mocker: MockerFixture):
        """Unregistering a URL the host does not know exits 1, reporting its error."""
        self._mock_client(mocker, response={"error": "No such URL is present"})

        result = runner.invoke(main, ["notification", "unregister", self.URLS[1]])

        assert result.exit_code == 1
        assert (
            f"The Volumio host did not unregister the URL: {self.URLS[1]} "
            "(No such URL is present)" in result.output
        )

    def test_unregister_machine_readable(self, runner: CliRunner, mocker: MockerFixture):
        """notification unregister prints nothing in machine-readable mode."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["-m", "notification", "unregister", self.URLS[1]])

        assert result.exit_code == 0
        assert result.output == ""

    def _mock_listener(
        self,
        mocker: MockerFixture,
        notifications=None,
        interrupt=False,
        start_error=None,
        idle_timed_out=False,
    ):
        """Patch the notification listener used by the listen command."""
        fake = mocker.Mock()
        fake.idle_timed_out = idle_timed_out
        if start_error is not None:
            fake.start.side_effect = start_error
        if interrupt:
            fake.listen.side_effect = KeyboardInterrupt
        else:
            fake.listen.return_value = iter(
                [PushNotification.from_raw(payload) for payload in notifications or []]
            )
        mocker.patch("volumito.cli.volumito.NotificationListener", return_value=fake)
        mocker.patch("volumito.cli.volumito.receiver_url", return_value=self.LISTEN_URL)
        return fake

    def test_listen_prints_the_notifications(self, runner: CliRunner, mocker: MockerFixture):
        """notification listen prints each notification as pretty JSON by default."""
        self._mock_client(mocker, urls=[self.LISTEN_URL])
        self._mock_listener(mocker, self.NOTIFICATIONS)

        result = runner.invoke(main, ["notification", "listen"])

        assert result.exit_code == 0
        lines = result.output.splitlines()
        assert lines[0].endswith(
            f"[INFO] Listening on port 3003 for the notifications sent to {self.LISTEN_URL}"
        )
        # The ways out are the last thing said before the wait begins
        assert lines[1].endswith("[INFO] Terminate as soon as: CTRL+C is issued")
        assert '\n    "item": "state"' in result.output
        assert '"item": "queue"' in result.output

    def test_listen_json_format(self, runner: CliRunner, mocker: MockerFixture):
        """notification listen -F json prints JSON with 2-space indentation."""
        self._mock_client(mocker, urls=[self.LISTEN_URL])
        self._mock_listener(mocker, self.NOTIFICATIONS[:1])

        result = runner.invoke(main, ["notification", "listen", "-F", "json"])

        assert result.exit_code == 0
        assert '\n  "item": "state"' in result.output

    def test_listen_raw_format(self, runner: CliRunner, mocker: MockerFixture):
        """notification listen -F raw prints each payload as the host sent it."""
        self._mock_client(mocker, urls=[self.LISTEN_URL])
        self._mock_listener(mocker, self.NOTIFICATIONS[:1])

        result = runner.invoke(main, ["notification", "listen", "-F", "raw"])

        assert result.exit_code == 0
        assert json.dumps(self.NOTIFICATIONS[0]) in result.output

    def test_listen_table_format(self, runner: CliRunner, mocker: MockerFixture):
        """notification listen -F table prints one line per notification."""
        self._mock_client(mocker, urls=[self.LISTEN_URL])
        self._mock_listener(mocker, self.NOTIFICATIONS)

        result = runner.invoke(main, ["notification", "listen", "-F", "table"])
        # The notification lines start with their [timestamp]; the [INFO] lines do not count
        lines = [
            line
            for line in result.output.splitlines()
            if line.startswith("[2") and "] [" not in line
        ]

        assert result.exit_code == 0
        assert lines[0].endswith("state    play | Caterina - Francesco De Gregori")
        assert lines[1].endswith("queue    1 items")
        # The time of arrival is the UTC date and time, to the millisecond
        stamped = re.match(r"\[(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z)\] ", lines[0])
        assert stamped is not None
        received = datetime.strptime(stamped.group(1), "%Y-%m-%dT%H:%M:%S.%fZ").replace(
            tzinfo=UTC
        )
        assert abs((datetime.now(UTC) - received).total_seconds()) < 60

    def test_listen_machine_readable(self, runner: CliRunner, mocker: MockerFixture):
        """In machine-readable mode only the payloads are printed, one per line."""
        self._mock_client(mocker, urls=[self.LISTEN_URL])
        self._mock_listener(mocker, self.NOTIFICATIONS)

        result = runner.invoke(main, ["-m", "notification", "listen"])

        assert result.exit_code == 0
        assert result.output.splitlines() == [
            json.dumps(payload) for payload in self.NOTIFICATIONS
        ]

    def test_listen_url_not_registered(self, runner: CliRunner, mocker: MockerFixture):
        """Listening on a URL the host does not push to exits 1, naming the option."""
        mock_client = self._mock_client(mocker, urls=[])
        self._mock_listener(mocker)

        result = runner.invoke(main, ["notification", "listen"])

        assert result.exit_code == 1
        assert (
            f"The URL is not registered on the Volumio host: {self.LISTEN_URL} "
            "(use --register-url to register it)" in result.output
        )
        mock_client.register_notification.assert_not_called()

    def test_listen_url_not_registered_machine_readable(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """The not-registered error prints nothing in machine-readable mode."""
        self._mock_client(mocker, urls=[])
        self._mock_listener(mocker)

        result = runner.invoke(main, ["-m", "notification", "listen"])

        assert result.exit_code == 1
        assert result.output == ""

    def test_listen_registers_and_unregisters(self, runner: CliRunner, mocker: MockerFixture):
        """--register-url registers the missing URL, and the exit unregisters it."""
        mock_client = self._mock_client(mocker, urls=[])
        self._mock_listener(mocker, self.NOTIFICATIONS[:1])

        result = runner.invoke(main, ["notification", "listen", "--register-url"])

        assert result.exit_code == 0
        assert f"Registered notification URL: {self.LISTEN_URL}" in result.output
        assert f"Unregistered notification URL: {self.LISTEN_URL}" in result.output
        mock_client.register_notification.assert_called_once_with(self.LISTEN_URL)
        mock_client.unregister_notification.assert_called_once_with(self.LISTEN_URL)

    def test_listen_keeps_the_registered_url(self, runner: CliRunner, mocker: MockerFixture):
        """--no-unregister-url-on-exit leaves the URL registered."""
        mock_client = self._mock_client(mocker, urls=[])
        self._mock_listener(mocker, self.NOTIFICATIONS[:1])

        result = runner.invoke(
            main,
            ["notification", "listen", "--register-url", "--no-unregister-url-on-exit"],
        )

        assert result.exit_code == 0
        mock_client.register_notification.assert_called_once_with(self.LISTEN_URL)
        mock_client.unregister_notification.assert_not_called()

    def test_listen_never_unregisters_a_preexisting_url(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """A URL registered before the run is left alone on exit."""
        mock_client = self._mock_client(mocker, urls=[self.LISTEN_URL])
        self._mock_listener(mocker, self.NOTIFICATIONS[:1])

        result = runner.invoke(main, ["notification", "listen"])

        assert result.exit_code == 0
        mock_client.register_notification.assert_not_called()
        mock_client.unregister_notification.assert_not_called()

    def test_listen_register_url_full(self, runner: CliRunner, mocker: MockerFixture):
        """--register-url-full replaces the composed URL."""
        advertised = "http://receiver.lan:9000/hook"
        self._mock_client(mocker, urls=[advertised])
        listener_url = mocker.patch(
            "volumito.cli.volumito.receiver_url", return_value=self.LISTEN_URL
        )
        fake = mocker.Mock()
        fake.listen.return_value = iter([])
        mocker.patch("volumito.cli.volumito.NotificationListener", return_value=fake)

        result = runner.invoke(
            main, ["notification", "listen", "--register-url-full", advertised]
        )

        assert result.exit_code == 0
        assert advertised in result.output
        listener_url.assert_not_called()

    def test_listen_invalid_endpoint(self, runner: CliRunner, mocker: MockerFixture):
        """An endpoint without a leading slash is a usage error."""
        self._mock_client(mocker, urls=[self.LISTEN_URL])

        result = runner.invoke(main, ["notification", "listen", "-e", "notifications"])

        assert result.exit_code == 2
        assert "The endpoint must start with a slash." in result.output

    def test_listen_port_in_use(self, runner: CliRunner, mocker: MockerFixture):
        """A port that cannot be bound exits 1, reporting the reason."""
        self._mock_client(mocker, urls=[self.LISTEN_URL])
        self._mock_listener(mocker, start_error=OSError("Address already in use"))

        result = runner.invoke(main, ["notification", "listen", "-p", "80"])

        assert result.exit_code == 1
        assert "Cannot listen on port 80: Address already in use" in result.output

    def test_listen_port_in_use_machine_readable(self, runner: CliRunner, mocker: MockerFixture):
        """The port error prints nothing in machine-readable mode."""
        self._mock_client(mocker, urls=[self.LISTEN_URL])
        self._mock_listener(mocker, start_error=OSError("Address already in use"))

        result = runner.invoke(main, ["-m", "notification", "listen", "-p", "80"])

        assert result.exit_code == 1
        assert result.output == ""

    def test_listen_interrupted(self, runner: CliRunner, mocker: MockerFixture):
        """Ctrl-C ends the listening cleanly."""
        fake = self._mock_listener(mocker, interrupt=True)

        self._mock_client(mocker, urls=[self.LISTEN_URL])

        result = runner.invoke(main, ["notification", "listen"])

        assert result.exit_code == 0
        fake.stop.assert_called_once()

    def test_listen_count_is_forwarded(self, runner: CliRunner, mocker: MockerFixture):
        """--count is passed to the listener, and reaching it is not a timeout."""
        self._mock_client(mocker, urls=[self.LISTEN_URL])
        fake = self._mock_listener(mocker, self.NOTIFICATIONS)

        result = runner.invoke(
            main, ["notification", "listen", "-n", "2", "--timeout", "30"]
        )

        assert result.exit_code == 0
        assert "Timed out" not in result.output
        assert (
            "Terminate as soon as: CTRL+C is issued, a total of 30 seconds elapsed, "
            "or 2 notifications received" in result.output
        )
        fake.listen.assert_called_once_with(2, 30.0, None)

    def test_listen_timeout(self, runner: CliRunner, mocker: MockerFixture):
        """A timeout expiring without a requested count is reported, and exits 0."""
        self._mock_client(mocker, urls=[self.LISTEN_URL])
        self._mock_listener(mocker)

        result = runner.invoke(main, ["notification", "listen", "--timeout", "2"])

        assert result.exit_code == 0
        assert "Timed out after 2 seconds" in result.output

    def test_listen_idle_timeout(self, runner: CliRunner, mocker: MockerFixture):
        """The idle timeout is reported as such, with the number of seconds given."""
        self._mock_client(mocker, urls=[self.LISTEN_URL])
        fake = self._mock_listener(mocker, idle_timed_out=True)

        result = runner.invoke(main, ["notification", "listen", "--idle-timeout", "1.5"])

        assert result.exit_code == 0
        assert "Timed out after 1.5 seconds without notifications" in result.output
        fake.listen.assert_called_once_with(None, None, 1.5)

    def test_listen_idle_timeout_with_a_total_timeout(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """With both limits set, the idle one that expired is the one reported."""
        self._mock_client(mocker, urls=[self.LISTEN_URL])
        self._mock_listener(mocker, idle_timed_out=True)

        result = runner.invoke(
            main, ["notification", "listen", "--timeout", "60", "--idle-timeout", "3"]
        )

        assert result.exit_code == 0
        assert "Timed out after 3 seconds without notifications" in result.output
        # The total timeout is named among the conditions, but is not the one reported
        assert "Timed out after 60 seconds" not in result.output

    def test_listen_timeout_before_the_count(self, runner: CliRunner, mocker: MockerFixture):
        """A timeout expiring before the requested count exits 1."""
        self._mock_client(mocker, urls=[self.LISTEN_URL])
        self._mock_listener(mocker, self.NOTIFICATIONS[:1])

        result = runner.invoke(
            main, ["notification", "listen", "-n", "3", "--timeout", "2"]
        )

        assert result.exit_code == 1
        assert "Timed out after 2 seconds" in result.output

    def test_listen_timeout_machine_readable(self, runner: CliRunner, mocker: MockerFixture):
        """The timeout message is suppressed in machine-readable mode."""
        self._mock_client(mocker, urls=[self.LISTEN_URL])
        self._mock_listener(mocker)

        result = runner.invoke(main, ["-m", "notification", "listen", "--timeout", "2"])

        assert result.exit_code == 0
        assert result.output == ""

    def test_unregister_autocompose_url(self, runner: CliRunner, mocker: MockerFixture):
        """--autocompose-url unregisters the URL of the local listener."""
        mock_client = self._mock_client(mocker)
        composed = mocker.patch(
            "volumito.cli.volumito.receiver_url", return_value=self.LISTEN_URL
        )

        result = runner.invoke(main, ["notification", "unregister", "--autocompose-url"])

        assert result.exit_code == 0
        assert result.output.strip().endswith(
            f"[INFO] Unregistered notification URL: {self.LISTEN_URL}"
        )
        mock_client.unregister_notification.assert_called_once_with(self.LISTEN_URL)
        assert composed.call_args.args[1:] == (3003, "/volumionotifications")

    def test_unregister_autocompose_url_with_a_port_and_an_endpoint(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """The composed URL follows the given port and endpoint."""
        self._mock_client(mocker)
        composed = mocker.patch(
            "volumito.cli.volumito.receiver_url", return_value=self.LISTEN_URL
        )

        result = runner.invoke(
            main, ["notification", "unregister", "-A", "-p", "9000", "-e", "/hook"]
        )

        assert result.exit_code == 0
        assert composed.call_args.args[1:] == (9000, "/hook")

    def test_unregister_autocompose_url_with_all(self, runner: CliRunner, mocker: MockerFixture):
        """--autocompose-url cannot be combined with --all."""
        mock_client = self._mock_client(mocker)

        result = runner.invoke(
            main, ["notification", "unregister", "--autocompose-url", "--all"]
        )

        assert result.exit_code == 2
        assert "mutually exclusive" in result.output
        mock_client.unregister_notification.assert_not_called()

    def test_unregister_all(self, runner: CliRunner, mocker: MockerFixture):
        """notification unregister --all unregisters every registered URL."""
        mock_client = self._mock_client(mocker)

        result = runner.invoke(main, ["notification", "unregister", "--all"])

        assert result.exit_code == 0
        assert [
            line.endswith(f"[INFO] Unregistered notification URL: {url}")
            for line, url in zip(result.output.splitlines(), self.URLS, strict=True)
        ] == [True, True]
        assert [
            call.args[0] for call in mock_client.unregister_notification.call_args_list
        ] == self.URLS

    def test_unregister_all_shorthand(self, runner: CliRunner, mocker: MockerFixture):
        """The -a shorthand selects every registered URL as well."""
        mock_client = self._mock_client(mocker)

        result = runner.invoke(main, ["notification", "unregister", "-a"])

        assert result.exit_code == 0
        assert mock_client.unregister_notification.call_count == len(self.URLS)

    def test_unregister_all_without_registered_urls(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """notification unregister --all reports that there is nothing to unregister."""
        mock_client = self._mock_client(mocker, urls=[])

        result = runner.invoke(main, ["notification", "unregister", "--all"])

        assert result.exit_code == 0
        assert "No notification URL is registered, nothing to unregister" in result.output
        mock_client.unregister_notification.assert_not_called()

    def test_unregister_all_without_registered_urls_machine_readable(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """The nothing-to-unregister message is suppressed in machine-readable mode."""
        self._mock_client(mocker, urls=[])

        result = runner.invoke(main, ["-m", "notification", "unregister", "--all"])

        assert result.exit_code == 0
        assert result.output == ""

    def test_unregister_all_machine_readable(self, runner: CliRunner, mocker: MockerFixture):
        """notification unregister --all prints nothing in machine-readable mode."""
        mock_client = self._mock_client(mocker)

        result = runner.invoke(main, ["-m", "notification", "unregister", "--all"])

        assert result.exit_code == 0
        assert result.output == ""
        assert mock_client.unregister_notification.call_count == len(self.URLS)

    def test_unregister_all_refused(self, runner: CliRunner, mocker: MockerFixture):
        """A URL the host refuses exits 1, after the URLs already unregistered."""
        mock_client = self._mock_client(mocker)
        mock_client.unregister_notification.side_effect = [
            SuccessResponse.from_raw({"success": True}),
            SuccessResponse.from_raw({"error": "No such URL is present"}),
        ]

        result = runner.invoke(main, ["notification", "unregister", "--all"])

        assert result.exit_code == 1
        assert f"Unregistered notification URL: {self.URLS[0]}" in result.output
        assert (
            f"The Volumio host did not unregister the URL: {self.URLS[1]} "
            "(No such URL is present)" in result.output
        )

    def test_unregister_all_with_a_url(self, runner: CliRunner, mocker: MockerFixture):
        """A URL cannot be combined with --all."""
        mock_client = self._mock_client(mocker)

        result = runner.invoke(main, ["notification", "unregister", "--all", self.URLS[0]])

        assert result.exit_code == 2
        assert "mutually exclusive" in result.output
        mock_client.unregister_notification.assert_not_called()

    def test_unregister_without_a_url(self, runner: CliRunner, mocker: MockerFixture):
        """Without a URL and without --all, the command reports what it expects."""
        mock_client = self._mock_client(mocker)

        result = runner.invoke(main, ["notification", "unregister"])

        assert result.exit_code == 2
        assert (
            "Expected a URL argument, or one of the -a/--all and -A/--autocompose-url options."
            in result.output
        )
        mock_client.unregister_notification.assert_not_called()


class TestIsMbid:
    """Test cases for the is_mbid function."""

    def test_uuid_shaped(self):
        """A canonical UUID is recognized as an MBID."""
        assert is_mbid("83d91898-7763-47d7-b03b-b92132375c47") is True

    def test_uuid_shaped_uppercase(self):
        """Uppercase hexadecimal digits are accepted."""
        assert is_mbid("83D91898-7763-47D7-B03B-B92132375C47") is True

    def test_name(self):
        """An artist name is not an MBID."""
        assert is_mbid("Pink Floyd") is False

    def test_wrong_group_length(self):
        """A UUID with a wrong group length is not an MBID."""
        assert is_mbid("83d91898-7763-47d7-b03b-b92132375c4") is False

    def test_non_hexadecimal(self):
        """A UUID-shaped string with non-hexadecimal digits is not an MBID."""
        assert is_mbid("83d91898-7763-47d7-b03b-b92132375c4z") is False

    def test_embedded_uuid(self):
        """A UUID embedded in longer text is not an MBID (the match is anchored)."""
        assert is_mbid("x83d91898-7763-47d7-b03b-b92132375c47") is False


class TestStoryQueryReference:
    """Test cases for the story_query_reference function."""

    _MBID = "83d91898-7763-47d7-b03b-b92132375c47"

    def test_pair_autodetect_two_arguments(self):
        """Two arguments autodetect as an ARTIST ALBUM pair."""
        result = story_query_reference(("Mango", "Sirtaki"), "autodetect", pair=True)

        assert result == ("name", ("Mango", "Sirtaki"))

    def test_pair_autodetect_single_mbid(self):
        """A single UUID-shaped argument autodetects as an MBID."""
        result = story_query_reference((self._MBID,), "autodetect", pair=True)

        assert result == ("mbid", (self._MBID,))

    def test_pair_autodetect_single_name_invalid(self):
        """A single non-UUID argument cannot be autodetected for a pair command."""
        assert story_query_reference(("Sirtaki",), "autodetect", pair=True) is None

    def test_pair_autodetect_no_arguments_invalid(self):
        """No arguments are invalid."""
        assert story_query_reference((), "autodetect", pair=True) is None

    def test_pair_autodetect_three_arguments_invalid(self):
        """More than two arguments are invalid."""
        assert story_query_reference(("A", "B", "C"), "autodetect", pair=True) is None

    def test_pair_explicit_mbid(self):
        """An explicit mbid type takes the single argument verbatim, without shape checks."""
        result = story_query_reference(("not-a-uuid",), "mbid", pair=True)

        assert result == ("mbid", ("not-a-uuid",))

    def test_pair_explicit_mbid_two_arguments_invalid(self):
        """An explicit mbid type rejects two arguments."""
        assert story_query_reference(("A", "B"), "mbid", pair=True) is None

    def test_pair_explicit_name_uuid_arguments(self):
        """An explicit name type keeps UUID-shaped arguments as an ARTIST ALBUM pair."""
        result = story_query_reference((self._MBID, "Sirtaki"), "name", pair=True)

        assert result == ("name", (self._MBID, "Sirtaki"))

    def test_pair_explicit_name_single_argument_invalid(self):
        """An explicit name type rejects a single argument for a pair command."""
        assert story_query_reference(("Sirtaki",), "name", pair=True) is None

    def test_single_autodetect_name(self):
        """A single non-UUID argument autodetects as a name."""
        result = story_query_reference(("Mango",), "autodetect", pair=False)

        assert result == ("name", ("Mango",))

    def test_single_autodetect_mbid(self):
        """A single UUID-shaped argument autodetects as an MBID."""
        result = story_query_reference((self._MBID,), "autodetect", pair=False)

        assert result == ("mbid", (self._MBID,))

    def test_single_explicit_name_uuid_argument(self):
        """An explicit name type keeps a UUID-shaped argument as a name."""
        result = story_query_reference((self._MBID,), "name", pair=False)

        assert result == ("name", (self._MBID,))

    def test_single_explicit_mbid(self):
        """An explicit mbid type takes the single argument verbatim."""
        result = story_query_reference(("Mango",), "mbid", pair=False)

        assert result == ("mbid", ("Mango",))


class TestStoryCommands:
    """Test cases for the story album/artist/credits/label/place commands."""

    _MBID = "83d91898-7763-47d7-b03b-b92132375c47"

    @pytest.fixture
    def runner(self):
        """Create a CliRunner instance."""
        return CliRunner()

    def _mock_client(self, mocker: MockerFixture):
        """Mock VolumioRESTAPIClient with successful story query methods."""
        mock_client = mocker.Mock()
        envelope = {
            "success": True,
            "data": {"type": "story", "value": "A long story."},
        }
        _attach_story(mock_client, envelope)
        _attach_property(mock_client, "state", return_value={
            "status": "play",
            "title": "La rondine",
            "artist": " Mango ",
            "album": "Sirtaki",
        })
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        return mock_client

    def test_album_name_pair(self, runner: CliRunner, mocker: MockerFixture):
        """story album autodetects two arguments as an ARTIST ALBUM pair."""
        mock_client = self._mock_client(mocker)

        result = runner.invoke(main, ["story", "album", "Mango", "Sirtaki"])

        assert result.exit_code == 0
        mock_client.get_story.assert_called_once_with(
            album=Album("Sirtaki"), artist=Artist("Mango")
        )
        assert json.loads(result.output)["data"]["value"] == "A long story."
        # Explicit arguments never trigger a state fetch
        mock_client.state_property.assert_not_called()

    def test_album_single_mbid(self, runner: CliRunner, mocker: MockerFixture):
        """story album autodetects a single UUID-shaped argument as an MBID."""
        mock_client = self._mock_client(mocker)

        result = runner.invoke(main, ["story", "album", self._MBID])

        assert result.exit_code == 0
        # The adapter passes the client only the entities given
        mock_client.get_story.assert_called_once_with(album=Album(self._MBID, is_mbid=True))

    def test_album_explicit_mbid_type(self, runner: CliRunner, mocker: MockerFixture):
        """story album -T mbid takes the single argument verbatim."""
        mock_client = self._mock_client(mocker)

        result = runner.invoke(main, ["story", "album", "-T", "mbid", "not-a-uuid"])

        assert result.exit_code == 0
        mock_client.get_story.assert_called_once_with(album=Album("not-a-uuid", is_mbid=True))

    def test_album_explicit_name_type(self, runner: CliRunner, mocker: MockerFixture):
        """story album -T name keeps a UUID-shaped first argument as the artist."""
        mock_client = self._mock_client(mocker)

        result = runner.invoke(main, ["story", "album", "-T", "name", self._MBID, "Sirtaki"])

        assert result.exit_code == 0
        mock_client.get_story.assert_called_once_with(
            album=Album("Sirtaki"), artist=Artist(self._MBID)
        )

    def test_album_single_name_argument_error(self, runner: CliRunner, mocker: MockerFixture):
        """story album with a single non-UUID argument is a usage error."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["story", "album", "Sirtaki"])

        assert result.exit_code == 2
        assert STORY_ARTIST_ALBUM_ARGUMENTS_ERROR in result.output

    def test_album_no_arguments_error(self, runner: CliRunner, mocker: MockerFixture):
        """story album without arguments is a usage error."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["story", "album"])

        assert result.exit_code == 2
        assert STORY_ARTIST_ALBUM_ARGUMENTS_ERROR in result.output

    def test_album_three_arguments_error(self, runner: CliRunner, mocker: MockerFixture):
        """story album with three arguments is a usage error."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["story", "album", "A", "B", "C"])

        assert result.exit_code == 2
        assert STORY_ARTIST_ALBUM_ARGUMENTS_ERROR in result.output

    def test_album_explicit_mbid_type_two_arguments_error(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """story album -T mbid with two arguments is a usage error."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["story", "album", "-T", "mbid", "A", "B"])

        assert result.exit_code == 2
        assert STORY_ARTIST_ALBUM_ARGUMENTS_ERROR in result.output

    def test_artist_name(self, runner: CliRunner, mocker: MockerFixture):
        """story artist autodetects a non-UUID argument as the artist name."""
        mock_client = self._mock_client(mocker)

        result = runner.invoke(main, ["story", "artist", "Mango"])

        assert result.exit_code == 0
        mock_client.get_story.assert_called_once_with(artist=Artist("Mango"))

    def test_artist_mbid(self, runner: CliRunner, mocker: MockerFixture):
        """story artist autodetects a UUID-shaped argument as an MBID."""
        mock_client = self._mock_client(mocker)

        result = runner.invoke(main, ["story", "artist", self._MBID])

        assert result.exit_code == 0
        mock_client.get_story.assert_called_once_with(artist=Artist(self._MBID, is_mbid=True))

    def test_artist_explicit_name_type(self, runner: CliRunner, mocker: MockerFixture):
        """story artist -T name keeps a UUID-shaped argument as the artist name."""
        mock_client = self._mock_client(mocker)

        result = runner.invoke(main, ["story", "artist", "-T", "name", self._MBID])

        assert result.exit_code == 0
        mock_client.get_story.assert_called_once_with(artist=Artist(self._MBID))

    def test_credits_name_pair(self, runner: CliRunner, mocker: MockerFixture):
        """story credits autodetects two arguments as an ARTIST ALBUM pair."""
        mock_client = self._mock_client(mocker)

        result = runner.invoke(main, ["story", "credits", "Mango", "Sirtaki"])

        assert result.exit_code == 0
        mock_client.get_album_credits.assert_called_once_with(
            Artist("Mango"), Album("Sirtaki")
        )

    def test_credits_explicit_name_type_single_argument_error(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """story credits -T name with a single argument is a usage error."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["story", "credits", "-T", "name", "Sirtaki"])

        assert result.exit_code == 2
        assert STORY_ARTIST_ALBUM_ARGUMENTS_ERROR in result.output

    def test_label_mbid(self, runner: CliRunner, mocker: MockerFixture):
        """story label autodetects a UUID-shaped argument as an MBID."""
        mock_client = self._mock_client(mocker)

        result = runner.invoke(main, ["story", "label", self._MBID])

        assert result.exit_code == 0
        mock_client.get_story.assert_called_once_with(label=Label(self._MBID, is_mbid=True))

    def test_label_name(self, runner: CliRunner, mocker: MockerFixture):
        """story label autodetects a non-UUID argument as the label name."""
        mock_client = self._mock_client(mocker)

        result = runner.invoke(main, ["story", "label", "Blue Note"])

        assert result.exit_code == 0
        mock_client.get_story.assert_called_once_with(label=Label("Blue Note"))

    def test_place_mbid(self, runner: CliRunner, mocker: MockerFixture):
        """story place autodetects a UUID-shaped argument as an MBID."""
        mock_client = self._mock_client(mocker)

        result = runner.invoke(main, ["story", "place", self._MBID])

        assert result.exit_code == 0
        mock_client.get_story.assert_called_once_with(place=Place(self._MBID, is_mbid=True))

    def test_place_explicit_name_type(self, runner: CliRunner, mocker: MockerFixture):
        """story place -T name keeps a UUID-shaped argument as the place name."""
        mock_client = self._mock_client(mocker)

        result = runner.invoke(main, ["story", "place", "-T", "name", self._MBID])

        assert result.exit_code == 0
        mock_client.get_story.assert_called_once_with(place=Place(self._MBID))

    def test_album_current_track(self, runner: CliRunner, mocker: MockerFixture):
        """story album --current-track takes artist and album from the player state."""
        mock_client = self._mock_client(mocker)

        result = runner.invoke(main, ["story", "album", "--current-track"])

        assert result.exit_code == 0
        mock_client.state_property.assert_called_once_with()
        # The state values are stripped of surrounding whitespace
        mock_client.get_story.assert_called_once_with(
            album=Album("Sirtaki"), artist=Artist("Mango")
        )

    def test_artist_current_track(self, runner: CliRunner, mocker: MockerFixture):
        """story artist --current-track takes the artist from the player state."""
        mock_client = self._mock_client(mocker)

        result = runner.invoke(main, ["story", "artist", "--current-track"])

        assert result.exit_code == 0
        mock_client.get_story.assert_called_once_with(artist=Artist("Mango"))

    def test_credits_current_track(self, runner: CliRunner, mocker: MockerFixture):
        """story credits --current-track takes artist and album from the player state."""
        mock_client = self._mock_client(mocker)

        result = runner.invoke(main, ["story", "credits", "--current-track"])

        assert result.exit_code == 0
        mock_client.get_album_credits.assert_called_once_with(
            Artist("Mango"), Album("Sirtaki")
        )

    def test_current_track_ignores_type(self, runner: CliRunner, mocker: MockerFixture):
        """The --current-track option bypasses the -T/--type interpretation."""
        mock_client = self._mock_client(mocker)

        result = runner.invoke(main, ["story", "artist", "-T", "mbid", "--current-track"])

        assert result.exit_code == 0
        mock_client.get_story.assert_called_once_with(artist=Artist("Mango"))

    def test_current_track_with_arguments_error(self, runner: CliRunner, mocker: MockerFixture):
        """Combining --current-track with positional arguments is a usage error."""
        mock_client = self._mock_client(mocker)

        result = runner.invoke(
            main, ["story", "album", "--current-track", "Mango", "Sirtaki"]
        )

        assert result.exit_code == 2
        assert MUTUALLY_EXCLUSIVE_CURRENT_TRACK_ERROR in result.output
        mock_client.state_property.assert_not_called()

    def test_artist_current_track_with_argument_error(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """Combining --current-track with the artist argument is a usage error."""
        mock_client = self._mock_client(mocker)

        result = runner.invoke(main, ["story", "artist", "--current-track", "Mango"])

        assert result.exit_code == 2
        assert MUTUALLY_EXCLUSIVE_CURRENT_TRACK_ERROR in result.output
        mock_client.state_property.assert_not_called()

    def test_artist_no_argument_error(self, runner: CliRunner, mocker: MockerFixture):
        """story artist without an argument (and without --current-track) is a usage error."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["story", "artist"])

        assert result.exit_code == 2
        assert STORY_ARTIST_ARGUMENT_ERROR in result.output

    def test_current_track_missing_album(self, runner: CliRunner, mocker: MockerFixture):
        """A current track without an album fails story album --current-track."""
        mock_client = self._mock_client(mocker)
        _attach_property(mock_client, "state", return_value={"status": "play", "artist": "Mango"})

        result = runner.invoke(main, ["story", "album", "--current-track"])

        assert result.exit_code == 1
        assert "the current track does not provide the required metadata" in result.output.lower()
        mock_client.get_story.assert_not_called()

    def test_current_track_blank_artist(self, runner: CliRunner, mocker: MockerFixture):
        """A current track with a blank artist fails story artist --current-track."""
        mock_client = self._mock_client(mocker)
        _attach_property(mock_client, "state", return_value={"status": "stop", "artist": "   "})

        result = runner.invoke(main, ["story", "artist", "--current-track"])

        assert result.exit_code == 1
        assert "the current track does not provide the required metadata" in result.output.lower()

    def test_current_track_missing_metadata_machine_readable(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """In machine-readable mode the missing-metadata failure exits 1 printing nothing."""
        mock_client = self._mock_client(mocker)
        _attach_property(mock_client, "state", return_value={"status": "stop"})

        result = runner.invoke(main, ["-m", "story", "artist", "--current-track"])

        assert result.exit_code == 1
        assert result.output.strip() == ""

    def test_current_track_state_error(self, runner: CliRunner, mocker: MockerFixture):
        """A failing state fetch exits 1 before querying the story."""
        mock_client = self._mock_client(mocker)
        _attach_property(
            mock_client, "state", side_effect=VolumioConnectionError("Connection failed")
        )

        result = runner.invoke(main, ["story", "album", "--current-track"])

        assert result.exit_code == 1
        assert "Connection error" in result.output
        mock_client.get_story.assert_not_called()

    def test_label_has_no_current_track_option(self, runner: CliRunner, mocker: MockerFixture):
        """story label does not support the --current-track option."""
        mock_client = self._mock_client(mocker)

        result = runner.invoke(main, ["story", "label", "--current-track"])

        assert result.exit_code == 2
        # Click quotes the option name of this message since 8.4
        assert "No such option" in result.output
        assert "--current-track" in result.output
        mock_client.get_story.assert_not_called()

    def test_failure_envelope(self, runner: CliRunner, mocker: MockerFixture):
        """A success=false response exits 1 with the reported error."""
        mock_client = self._mock_client(mocker)
        _attach_story(mock_client, {"success": False, "error": "Metavolumio not available"})

        result = runner.invoke(main, ["story", "artist", "Mango"])

        assert result.exit_code == 1
        assert "Story error: Metavolumio not available" in result.output

    def test_failure_envelope_machine_readable(self, runner: CliRunner, mocker: MockerFixture):
        """In machine-readable mode a success=false response exits 1 printing nothing."""
        mock_client = self._mock_client(mocker)
        _attach_story(mock_client, {"success": False, "error": "nope"})

        result = runner.invoke(main, ["-m", "story", "artist", "Mango"])

        assert result.exit_code == 1
        assert result.output.strip() == ""

    def test_failure_envelope_missing_success(self, runner: CliRunner, mocker: MockerFixture):
        """A response without the success flag exits 1 with the fallback error."""
        mock_client = self._mock_client(mocker)
        _attach_story(mock_client, {"data": {"value": "A long story."}})

        result = runner.invoke(main, ["story", "artist", "Mango"])

        assert result.exit_code == 1
        assert "Story error: unknown error" in result.output

    def test_connection_error(self, runner: CliRunner, mocker: MockerFixture):
        """story artist exits 1 on a connection error."""
        mock_client = self._mock_client(mocker)
        mock_client.get_story.side_effect = VolumioConnectionError("Connection failed")

        result = runner.invoke(main, ["story", "artist", "Mango"])

        assert result.exit_code == 1
        assert "Connection error" in result.output

    def test_default_pretty_short(self, runner: CliRunner, mocker: MockerFixture):
        """The default output is pretty JSON with only the data.value field."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["story", "album", "Mango", "Sirtaki"])

        assert result.exit_code == 0
        assert json.loads(result.output) == {"data": {"value": "A long story."}}

    def test_format_raw(self, runner: CliRunner, mocker: MockerFixture):
        """story album -F raw prints the compact full envelope, ignoring the fields filter."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["story", "album", "Mango", "Sirtaki", "-F", "raw"])

        assert result.exit_code == 0
        assert "\n" not in result.output.strip()
        assert json.loads(result.output) == {
            "success": True,
            "data": {"type": "story", "value": "A long story."},
        }

    def test_format_json(self, runner: CliRunner, mocker: MockerFixture):
        """story album -F json prints the filtered fields with 2-space indentation."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["story", "album", "Mango", "Sirtaki", "-F", "json"])

        assert result.exit_code == 0
        assert result.output.startswith("{\n  ")
        assert json.loads(result.output) == {"data": {"value": "A long story."}}

    def test_format_table(self, runner: CliRunner, mocker: MockerFixture):
        """story album -F table prints the heading and the dotted field label."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["story", "album", "Mango", "Sirtaki", "-F", "table"])

        assert result.exit_code == 0
        assert "Album Story" in result.output
        assert f"{'Data Value':20}: A long story." in result.output.splitlines()

    def test_format_table_all_fields(self, runner: CliRunner, mocker: MockerFixture):
        """story album -L ALL -F table prints the nested data object as indented sub-keys."""
        self._mock_client(mocker)

        result = runner.invoke(
            main, ["story", "album", "Mango", "Sirtaki", "-L", "ALL", "-F", "table"]
        )

        assert result.exit_code == 0
        lines = result.output.splitlines()
        assert f"{'Success':20}: True" in lines
        assert f"{'Data':20}:" in lines
        assert f"  {'Value':18}: A long story." in lines

    def test_fields_custom_list(self, runner: CliRunner, mocker: MockerFixture):
        """A comma-separated fields list keeps the requested dotted fields, in order."""
        self._mock_client(mocker)

        result = runner.invoke(
            main, ["story", "album", "Mango", "Sirtaki", "-L", "data.type,data.value"]
        )

        assert result.exit_code == 0
        assert json.loads(result.output) == {
            "data": {"type": "story", "value": "A long story."},
        }

    def test_verbose(self, runner: CliRunner, mocker: MockerFixture):
        """Verbose mode reports the successful story retrieval."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["-v", "story", "album", "Mango", "Sirtaki"])

        assert result.exit_code == 0
        assert "[DEBU] Successfully retrieved story" in result.output

    def test_not_verbose_hides_debug(self, runner: CliRunner, mocker: MockerFixture):
        """Without -v the debug messages stay hidden."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["story", "album", "Mango", "Sirtaki"])

        assert result.exit_code == 0
        assert "[DEBU]" not in result.output

    def test_the_color_options_are_accepted(self, runner: CliRunner, mocker: MockerFixture):
        """--color and --no-color are accepted; the captured output stays plain."""
        self._mock_client(mocker)

        colored = runner.invoke(main, ["--color", "-v", "story", "album", "Mango", "Sirtaki"])
        plain = runner.invoke(main, ["--no-color", "-v", "story", "album", "Mango", "Sirtaki"])

        assert colored.exit_code == 0
        assert plain.exit_code == 0
        # The runner is not a terminal, so neither run carries ANSI codes
        assert "\x1b" not in colored.output
        # The two runs differ only by their timestamps
        stamp = re.compile(r"\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z\] ")
        assert stamp.sub("", colored.output) == stamp.sub("", plain.output)


class TestQueueAlbumVolumes:
    """Test cases for the queue_album_volumes function."""

    def test_single_volume_album(self):
        """An album with one distinct volume renders as the album name alone."""
        tracks = [
            {"artist": "A", "album": "Allegria", "volumeNumber": 1},
            {"artist": "A", "album": "Allegria", "volumeNumber": 1},
        ]

        assert queue_album_volumes(_queue_tracks(tracks), "_") == ["Allegria", "Allegria"]

    def test_multi_volume_album(self):
        """An album with several volumes gets per-volume components."""
        tracks = [
            {"artist": "A", "album": "Elegia", "volumeNumber": 1},
            {"artist": "A", "album": "Elegia", "volumeNumber": 2},
            {"artist": "A", "album": "Allegria", "volumeNumber": 1},
        ]

        assert queue_album_volumes(_queue_tracks(tracks), "_") == [
            "Elegia/1",
            "Elegia/2",
            "Allegria",
        ]

    def test_missing_volume_number(self):
        """A track without volumeNumber renders the album alone, even in a multi-volume album."""
        tracks = [
            {"artist": "A", "album": "Elegia", "volumeNumber": 1},
            {"artist": "A", "album": "Elegia", "volumeNumber": 2},
            {"artist": "A", "album": "Elegia"},
        ]

        assert queue_album_volumes(_queue_tracks(tracks), "_") == ["Elegia/1", "Elegia/2", "Elegia"]

    def test_same_album_name_different_artists(self):
        """Same-named albums by different artists are separate groups."""
        tracks = [
            {"artist": "A", "album": "Live", "volumeNumber": 1},
            {"artist": "B", "album": "Live", "volumeNumber": 2},
        ]

        assert queue_album_volumes(_queue_tracks(tracks), "_") == ["Live", "Live"]

    def test_album_name_separators_sanitized(self):
        """Path separators inside the album name are replaced; only ours survives."""
        tracks = [
            {"artist": "A", "album": "AC/DC Live", "volumeNumber": 1},
            {"artist": "A", "album": "AC/DC Live", "volumeNumber": 2},
        ]

        assert queue_album_volumes(_queue_tracks(tracks), "_") == ["AC_DC Live/1", "AC_DC Live/2"]

    def test_missing_album_and_empty_queue(self):
        """A missing album yields an empty component; an empty queue an empty list."""
        assert queue_album_volumes(_queue_tracks([{"volumeNumber": 1}]), "_") == [""]
        assert queue_album_volumes([], "_") == []


class TestQueueTrackMetadataCurrent:
    """Test cases for the queue_track_metadata_current function."""

    _EXPECTED = QueueTrack.from_raw({"album": "X", "artist": "A", "title": "T"})

    def _state(self, **overrides):
        """Return the player state fetched after playing the track."""
        return PlayerState.from_raw(
            {"album": "X", "artist": "A", "title": "T", "position": 2, **overrides}
        )

    def test_current(self):
        """A state matching the queue entry and position, with a new URI, is accepted."""
        current = queue_track_metadata_current(self._state(), "u2", self._EXPECTED, 2, "u1", False)

        assert current is True

    def test_title_mismatch(self):
        """A state title differing from the queue entry is rejected."""
        state = self._state(title="Other")

        assert queue_track_metadata_current(state, "u2", self._EXPECTED, 2, "u1", False) is False

    def test_artist_and_album_mismatch(self):
        """A state artist or album differing from the queue entry is rejected."""
        state = self._state(album="Y")
        assert queue_track_metadata_current(state, "u2", self._EXPECTED, 2, "u1", False) is False
        state = self._state(artist="B")
        assert queue_track_metadata_current(state, "u2", self._EXPECTED, 2, "u1", False) is False

    def test_queue_entry_without_metadata_skips_fields(self):
        """Queue-entry fields that are absent are not compared."""
        state = PlayerState.from_raw({"title": "Whatever", "position": 2})
        expected = QueueTrack.from_raw({})

        assert queue_track_metadata_current(state, "u2", expected, 2, "u1", False) is True

    def test_wrong_position(self):
        """A stale position is rejected."""
        state = self._state(position=1)

        assert queue_track_metadata_current(state, "u2", self._EXPECTED, 2, "u1", False) is False

    def test_missing_or_malformed_position(self):
        """A missing or malformed position is rejected."""
        state = PlayerState.from_raw({"album": "X", "artist": "A", "title": "T"})
        assert queue_track_metadata_current(state, "u2", self._EXPECTED, 2, "u1", False) is False
        state = self._state(position="abc")
        assert queue_track_metadata_current(state, "u2", self._EXPECTED, 2, "u1", False) is False

    def test_stale_uri(self):
        """A URI equal to the previous track's is rejected when a change is expected."""
        current = queue_track_metadata_current(self._state(), "u1", self._EXPECTED, 2, "u1", False)

        assert current is False

    def test_expected_same_uri(self):
        """A URI equal to the previous track's is accepted when the queue lists it twice."""
        current = queue_track_metadata_current(self._state(), "u1", self._EXPECTED, 2, "u1", True)

        assert current is True

    def test_first_track_skips_uri_check(self):
        """The first track has no previous URI to compare against."""
        state = self._state(position=0)

        assert queue_track_metadata_current(state, "u1", self._EXPECTED, 0, None, False) is True


class TestManifestMatchesQueue:
    """Test cases for the manifest_matches_queue function."""

    _TRACKS = _queue_tracks(
        [
            {"title": "Song A", "artist": "Artist", "album": "Album"},
            {"title": "Song B", "artist": "Artist", "album": "Album"},
        ]
    )

    def test_matching(self):
        """Entries matching title, artist, and album at every position match."""
        entries = [
            {"title": "Song A", "artist": "Artist", "album": "Album", "status": "error"},
            {"title": "Song B", "artist": "Artist", "album": "Album", "status": "pending"},
        ]

        assert manifest_matches_queue(entries, self._TRACKS) is True

    def test_different_length(self):
        """A different number of entries does not match."""
        entries = [{"title": "Song A", "artist": "Artist", "album": "Album"}]

        assert manifest_matches_queue(entries, self._TRACKS) is False

    def test_different_title(self):
        """A different title at some position does not match."""
        entries = [
            {"title": "Song A", "artist": "Artist", "album": "Album"},
            {"title": "Other", "artist": "Artist", "album": "Album"},
        ]

        assert manifest_matches_queue(entries, self._TRACKS) is False

    def test_missing_keys_on_both_sides_match(self):
        """Keys missing on both sides compare as equal (None == None)."""
        assert manifest_matches_queue([{"title": "X"}], _queue_tracks([{"title": "X"}])) is True


class TestQueueDownload:
    """Test cases for the queue download command."""

    _BASE = ["queue", "download", "--no-create-download-manifest", "--no-add-cover-and-metadata"]

    @pytest.fixture
    def runner(self):
        """Create a CliRunner instance."""
        return CliRunner()

    def _queue_tracks(self):
        return [
            {"title": "Song A", "artist": "Artist", "album": "Album", "tracknumber": 1},
            {"title": "Song B", "artist": "Artist", "album": "Album", "tracknumber": 2},
        ]

    def _mock_services(self, mocker: MockerFixture, tracks, uris, states=None):
        """Mock the REST client, the MPD client, the HTTP download, and the sleep."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "queue", return_value={"queue": tracks})
        if states is not None:
            _attach_property(mock_client, "state", side_effect=states)
        else:
            # The default state mirrors the queue entry being played (fresh metadata)
            _attach_property(
                mock_client,
                "state",
                side_effect=[
                    {**track, "position": index} for index, track in enumerate(tracks)
                ],
            )
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        mpd = mocker.Mock()
        mpd.get_track_uri.side_effect = list(uris)
        mpd_class = mocker.Mock(return_value=mpd)
        mpd_class.return_value.__enter__ = mocker.Mock(return_value=mpd)
        mpd_class.return_value.__exit__ = mocker.Mock(return_value=None)
        mocker.patch("volumito.cli.volumito.VolumioMPDClient", new=mpd_class)

        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"data"]
        mocker.patch("volumito.cli.click_helpers.requests.get", return_value=mock_response)
        mocker.patch("volumito.cli.click_helpers.time.sleep")
        return mock_client

    def _read_log(self, base):
        """Return the run's download manifest (path, parsed content)."""
        log_path = base / "manifest.json"
        with open(log_path, encoding="utf-8") as log_file:
            return log_path, json.load(log_file)

    def test_download_happy_path(self, runner: CliRunner, mocker: MockerFixture, tmp_path):
        """All queue tracks are downloaded, logged, and playback is repositioned."""
        client = self._mock_services(
            mocker,
            self._queue_tracks(),
            ["http://h/a.flac", "http://h/b.flac"],
        )

        result = runner.invoke(main, ["-v", *self._BASE, "-d", str(tmp_path)])

        assert result.exit_code == 0
        assert "Successfully retrieved queue" in result.output
        run = tmp_path
        assert (run / "a.flac").read_bytes() == b"data"
        assert (run / "b.flac").read_bytes() == b"data"
        log_path, log = self._read_log(tmp_path)
        assert log["entity"] == "queue"
        assert log["kind"] == "download"
        assert log["output_directory"] == str(run)
        assert log["updates"] == 1
        assert "first_download_date" in log
        assert "last_update_date" in log
        assert "download_date" not in log
        assert [t["status"] for t in log["tracks"]] == ["downloaded", "downloaded"]
        assert [t["position"] for t in log["tracks"]] == [1, 2]
        assert log["tracks"][0]["output_file_path"] == str(run / "a.flac")
        assert log["tracks"][0]["source_uri"] == "http://h/a.flac"
        # Stop at the start and at the end; play each track, then reposition to the first
        assert client.stop.call_count == 2
        assert _played_positions(client) == [0, 1, 0]
        assert client.pause.call_count == 2
        assert "Downloaded 2, skipped 0, errors 0" in result.output
        assert f'Creating manifest file "{log_path}"' in result.output
        assert str(log_path) in result.output

    def test_download_renamed_after_the_format_of_the_content(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """A track served as MP3 lands as ".mp3", and the manifest records that path."""
        self._mock_services(
            mocker,
            [{"title": "Song A", "artist": "Artist", "album": "Album", "tracknumber": 1}],
            ["http://h/a.flac"],
            states=[{"title": "Song A", "artist": "Artist", "album": "Album", "position": 0}],
        )
        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [_MP3_CONTENT]
        mocker.patch("volumito.cli.click_helpers.requests.get", return_value=mock_response)

        result = runner.invoke(
            main, [*self._BASE, "-d", str(tmp_path), "-f", "{title}.{extension}"]
        )

        assert result.exit_code == 0
        assert (tmp_path / "Song_A.mp3").read_bytes() == _MP3_CONTENT
        assert not (tmp_path / "Song_A.flac").exists()
        _, log = self._read_log(tmp_path)
        assert log["tracks"][0]["output_file_path"] == str(tmp_path / "Song_A.mp3")
        assert str(tmp_path / "Song_A.mp3") in result.output

    def test_download_subdirectories(self, runner: CliRunner, mocker: MockerFixture, tmp_path):
        """Template separators create subdirectories; metadata separators are sanitized."""
        self._mock_services(
            mocker,
            [{"title": "Song", "artist": "AC/DC", "album": "Alb"}],
            ["http://h/a.flac"],
            states=[{"title": "Song", "artist": "AC/DC", "album": "Alb", "position": 0}],
        )

        result = runner.invoke(
            main,
            [*self._BASE, "-d", str(tmp_path), "-f", "{artist}/{album}/{title}.{extension}"],
        )

        assert result.exit_code == 0
        run = tmp_path
        assert (run / "AC_DC" / "Alb" / "Song.flac").read_bytes() == b"data"
        _, log = self._read_log(tmp_path)
        assert log["tracks"][0]["status"] == "downloaded"

    def test_download_template_escape_rejected(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """A template escaping the output directory is a usage error."""
        self._mock_services(mocker, self._queue_tracks()[:1], ["http://h/a.flac"])

        result = runner.invoke(
            main, [*self._BASE, "-d", str(tmp_path), "-f", "x/../../{title}.{extension}"]
        )

        assert result.exit_code == 2
        assert "escapes the output directory" in result.output

    def test_download_requires_output_directory(self, runner: CliRunner):
        """Without -d (or a configuration value) the command is a usage error."""
        result = runner.invoke(main, ["queue", "download"])

        assert result.exit_code == 2
        assert "is required" in result.output

    def test_download_skips_duplicate_names(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """A rendered name colliding with an earlier track of the run is skipped."""
        self._mock_services(mocker, self._queue_tracks(), ["http://h/a.flac", "http://h2/a.flac"])

        result = runner.invoke(main, [*self._BASE, "-d", str(tmp_path)])

        assert result.exit_code == 0
        run = tmp_path
        _, log = self._read_log(tmp_path)
        assert [t["status"] for t in log["tracks"]] == ["downloaded", "skipped"]
        assert log["tracks"][1]["output_file_path"] == str(run / "a.flac")
        assert "skipped 1" in result.output

    def test_download_error_continues(self, runner: CliRunner, mocker: MockerFixture, tmp_path):
        """A failing track is logged as an error and the loop continues; exit code is 1."""
        self._mock_services(mocker, self._queue_tracks(), ["http://h/a.flac", "http://h/b.flac"])
        ok_response = mocker.Mock()
        ok_response.iter_content.return_value = [b"data"]
        mocker.patch(
            "volumito.cli.click_helpers.requests.get",
            side_effect=[requests.exceptions.RequestException("boom"), ok_response],
        )

        result = runner.invoke(main, [*self._BASE, "-d", str(tmp_path)])

        assert result.exit_code == 1
        _, log = self._read_log(tmp_path)
        assert [t["status"] for t in log["tracks"]] == ["error", "downloaded"]
        assert "boom" in log["tracks"][0]["error"]
        assert (tmp_path / "b.flac").exists()
        assert "errors 1" in result.output

    def test_download_into_existing_directory_skips_existing_files(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """An existing output directory is reused; existing files are skipped."""
        self._mock_services(mocker, self._queue_tracks(), ["http://h/a.flac", "http://h/b.flac"])
        (tmp_path / "a.flac").write_bytes(b"old")

        result = runner.invoke(main, [*self._BASE, "-d", str(tmp_path)])

        assert result.exit_code == 0
        _, log = self._read_log(tmp_path)
        assert [t["status"] for t in log["tracks"]] == ["skipped", "downloaded"]
        assert (tmp_path / "a.flac").read_bytes() == b"old"
        assert (tmp_path / "b.flac").read_bytes() == b"data"
        assert "skipped 1" in result.output

    def test_download_output_directory_timestamp_placeholder(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """The {timestamp} placeholder in -d expands to the current UTC time."""
        self._mock_services(mocker, self._queue_tracks()[:1], ["http://h/a.flac"])
        mock_datetime = mocker.patch("volumito.cli.volumito.datetime")
        mock_datetime.now.return_value.strftime.return_value = "20260101000000"
        mock_datetime.now.return_value.isoformat.return_value = "2026-01-01T00:00:00+00:00"

        result = runner.invoke(
            main, [*self._BASE, "-d", os.path.join(str(tmp_path), "{timestamp}")]
        )

        assert result.exit_code == 0
        run = tmp_path / "20260101000000"
        assert (run / "a.flac").read_bytes() == b"data"
        _, log = self._read_log(run)
        assert log["output_directory"] == str(run)

    def test_download_manifest_file_custom_path(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """--manifest-file writes the manifest to the given path, creating parents."""
        self._mock_services(mocker, self._queue_tracks()[:1], ["http://h/a.flac"])
        out = tmp_path / "out"
        manifest = tmp_path / "reports" / "run.json"

        result = runner.invoke(
            main, ["-m", *self._BASE, "-d", str(out), "--manifest-file", str(manifest)]
        )

        assert result.exit_code == 0
        assert result.output.strip() == json.dumps(str(manifest))
        with open(manifest, encoding="utf-8") as manifest_handle:
            log = json.load(manifest_handle)
        assert log["tracks"][0]["status"] == "downloaded"
        assert not (out / "manifest.json").exists()

    def test_download_manifest_file_output_directory_placeholder(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """The {output_directory} placeholder in --manifest-file expands to the -d path."""
        self._mock_services(mocker, self._queue_tracks()[:1], ["http://h/a.flac"])

        result = runner.invoke(
            main,
            [
                *self._BASE,
                "-d",
                str(tmp_path),
                "--manifest-file",
                "{output_directory}/myqueue.json",
            ],
        )

        assert result.exit_code == 0
        with open(tmp_path / "myqueue.json", encoding="utf-8") as manifest_handle:
            log = json.load(manifest_handle)
        assert log["tracks"][0]["status"] == "downloaded"
        assert not (tmp_path / "manifest.json").exists()

    def test_download_manifest_file_timestamp_placeholder(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """{timestamp} expands to the same value in -d and --manifest-file."""
        self._mock_services(mocker, self._queue_tracks()[:1], ["http://h/a.flac"])
        mock_datetime = mocker.patch("volumito.cli.volumito.datetime")
        mock_datetime.now.return_value.strftime.return_value = "20260101000000"
        mock_datetime.now.return_value.isoformat.return_value = "2026-01-01T00:00:00+00:00"

        result = runner.invoke(
            main,
            [
                *self._BASE,
                "-d",
                os.path.join(str(tmp_path), "{timestamp}"),
                "--manifest-file",
                os.path.join(str(tmp_path), "{timestamp}", "{timestamp}.json"),
            ],
        )

        assert result.exit_code == 0
        run = tmp_path / "20260101000000"
        assert (run / "a.flac").read_bytes() == b"data"
        with open(run / "20260101000000.json", encoding="utf-8") as manifest_handle:
            log = json.load(manifest_handle)
        assert log["output_directory"] == str(run)

    def test_download_manifest_file_from_configuration(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """The queue-download configuration subsection supplies the manifest path."""
        self._mock_services(mocker, self._queue_tracks()[:1], ["http://h/a.flac"])
        out = tmp_path / "out"
        config = tmp_path / "volumito.yaml"
        config.write_text(
            "downloads:\n"
            "  queue-download:\n"
            f"    output-directory: {out}\n"
            "    manifest-file: '{output_directory}/from_config.json'\n"
        )

        result = runner.invoke(main, ["-c", str(config), *self._BASE])

        assert result.exit_code == 0
        assert (out / "from_config.json").exists()
        assert not (out / "manifest.json").exists()

    def test_download_of_a_file_of_the_host_library(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """A track copied from the host keeps its name, under the template directories."""
        tracks = [{"title": "8 - Luiza", "artist": "Aeon Trio", "album": "Elegy"}]
        self._mock_services(mocker, tracks, ["INTERNAL/music/elegy/08-Luiza.mp3"])
        copy = mocker.patch("volumito.cli.click_helpers.copy_from_host")
        embed = mocker.patch("volumito.cli.volumito.embed_track_tags")

        result = runner.invoke(
            main,
            [
                "--verbose",
                *self._BASE,
                # Both are asked for, and both are skipped for a file copied from the host
                "--create-download-manifest",
                "--add-cover-and-metadata",
                "-d",
                str(tmp_path),
                "--no-with-albumart",
                "--audio-file-name-template",
                "{artist}/{album}/{tracknumber:03d}___{title}.{extension}",
            ],
        )

        assert result.exit_code == 0
        assert copy.call_args.args[2] == str(tmp_path / "Aeon_Trio/Elegy/08-Luiza.mp3")
        embed.assert_not_called()
        assert (
            "Not embedding the album art and the metadata, to preserve the file being copied"
            in result.output
        )
        _, log = self._read_log(tmp_path)
        assert log["tracks"][0]["status"] == "downloaded"
        # The manifest of the file records that nothing was embedded into it
        with open(tmp_path / "Aeon_Trio/Elegy/08-Luiza.mp3.json", encoding="utf-8") as sidecar:
            assert json.load(sidecar)["add_cover_and_metadata"] is False

    def test_download_of_a_file_of_the_host_library_renamed(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """--allow-local-file-rename names the copy after the template."""
        tracks = [{"title": "8 - Luiza", "artist": "Aeon Trio", "album": "Elegy"}]
        self._mock_services(mocker, tracks, ["INTERNAL/music/elegy/08-Luiza.mp3"])
        copy = mocker.patch("volumito.cli.click_helpers.copy_from_host")

        result = runner.invoke(
            main,
            [
                *self._BASE,
                "-d",
                str(tmp_path),
                "--no-with-albumart",
                "--allow-local-file-rename",
                "--audio-file-name-template",
                "{artist}/{album}/{tracknumber:03d}___{title}.{extension}",
            ],
        )

        assert result.exit_code == 0
        assert copy.call_args.args[2] == str(
            tmp_path / "Aeon_Trio/Elegy/000___8_-_Luiza.mp3"
        )

    def test_download_only_tracks_help(self, runner: CliRunner):
        """The selection option is listed in the help, with its metavar."""
        result = runner.invoke(main, ["queue", "download", "--help"])

        assert result.exit_code == 0
        assert "--only-tracks" in result.output
        assert "[SELECTION]" in result.output

    def test_download_only_tracks(self, runner: CliRunner, mocker: MockerFixture, tmp_path):
        """Only the selected tracks are played and downloaded."""
        tracks = [
            {"title": "Song A", "artist": "Artist", "album": "Album", "tracknumber": 1},
            {"title": "Song B", "artist": "Artist", "album": "Album", "tracknumber": 2},
            {"title": "Song C", "artist": "Artist", "album": "Album", "tracknumber": 3},
        ]
        client = self._mock_services(
            mocker,
            tracks,
            ["http://h/b.flac", "http://h/c.flac"],
            states=[{**tracks[1], "position": 1}, {**tracks[2], "position": 2}],
        )

        result = runner.invoke(main, [*self._BASE, "-d", str(tmp_path), "-T", "2-3"])

        assert result.exit_code == 0
        assert "Downloading 2 of 3 tracks" in result.output
        assert "Downloaded 2, skipped 0, errors 0, not selected 1" in result.output
        # Only the selected tracks are played (plus the final reposition)
        assert _played_positions(client) == [1, 2, 0]
        _, log = self._read_log(tmp_path)
        assert [t["status"] for t in log["tracks"]] == ["pending", "downloaded", "downloaded"]

    def test_download_only_tracks_completes_in_a_later_run(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """A second run with another selection downloads the tracks left out."""
        tracks = self._queue_tracks()
        self._mock_services(
            mocker,
            tracks,
            ["http://h/a.flac"],
            states=[{**tracks[0], "position": 0}],
        )

        first = runner.invoke(main, [*self._BASE, "-d", str(tmp_path), "-T", "1"])

        assert first.exit_code == 0
        _, log = self._read_log(tmp_path)
        assert [t["status"] for t in log["tracks"]] == ["downloaded", "pending"]

        self._mock_services(
            mocker,
            tracks,
            ["http://h/b.flac"],
            states=[{**tracks[1], "position": 1}],
        )
        second = runner.invoke(main, [*self._BASE, "-d", str(tmp_path), "-T", "2"])

        assert second.exit_code == 0
        assert "Reading manifest file" in second.output
        _, log = self._read_log(tmp_path)
        assert [t["status"] for t in log["tracks"]] == ["downloaded", "downloaded"]
        assert log["updates"] == 2

    def test_download_only_tracks_position_starting_at_zero(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """With the zero base, the selected positions are the zero-indexed ones."""
        tracks = self._queue_tracks()
        client = self._mock_services(
            mocker,
            tracks,
            ["http://h/a.flac"],
            states=[{**tracks[0], "position": 0}],
        )

        result = runner.invoke(
            main, ["--position-starting-at-zero", *self._BASE, "-d", str(tmp_path), "-T", "0"]
        )

        assert result.exit_code == 0
        assert _played_positions(client) == [0, 0]
        _, log = self._read_log(tmp_path)
        assert [t["status"] for t in log["tracks"]] == ["downloaded", "pending"]

    def test_download_only_tracks_keeps_the_selected_downloaded_ones(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """A selection whose tracks are all downloaded leaves the playback untouched."""
        client = self._mock_services(mocker, self._queue_tracks(), [])
        mpd_class = mocker.patch("volumito.cli.volumito.VolumioMPDClient")
        manifest = tmp_path / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "updates": 1,
                    "tracks": [
                        {
                            "title": "Song A",
                            "artist": "Artist",
                            "album": "Album",
                            "status": "downloaded",
                            "output_file_path": str(tmp_path / "a.flac"),
                        },
                        {
                            "title": "Song B",
                            "artist": "Artist",
                            "album": "Album",
                            "status": "pending",
                        },
                    ],
                }
            )
        )

        result = runner.invoke(main, [*self._BASE, "-d", str(tmp_path), "-T", "1"])

        assert result.exit_code == 0
        assert "(kept)" in result.output
        assert "Downloaded 1, skipped 0, errors 0, not selected 1" in result.output
        client.stop.assert_not_called()
        mpd_class.assert_not_called()
        with open(manifest, encoding="utf-8") as manifest_handle:
            log = json.load(manifest_handle)
        assert [t["status"] for t in log["tracks"]] == ["downloaded", "pending"]

    def test_download_only_tracks_outside_the_queue(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """A selection matching no queue position is refused."""
        self._mock_services(mocker, self._queue_tracks(), [])

        result = runner.invoke(main, [*self._BASE, "-d", str(tmp_path), "-T", "7-9"])

        assert result.exit_code == 1
        assert "No track of the queue is selected" in result.output

    def test_download_only_tracks_invalid_selection(self, runner: CliRunner):
        """A malformed selection is a usage error."""
        result = runner.invoke(main, [*self._BASE, "-d", "/tmp", "-T", "3-1"])

        assert result.exit_code == 2
        assert "reversed range" in result.output

    def test_download_only_tracks_from_configuration(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """The queue-download configuration subsection supplies the selection."""
        tracks = self._queue_tracks()
        self._mock_services(
            mocker,
            tracks,
            ["http://h/b.flac"],
            states=[{**tracks[1], "position": 1}],
        )
        out = tmp_path / "out"
        config = tmp_path / "volumito.yaml"
        config.write_text(
            "downloads:\n"
            "  queue-download:\n"
            f"    output-directory: {out}\n"
            "    only-tracks: '2'\n"
        )

        result = runner.invoke(main, ["-c", str(config), *self._BASE])

        assert result.exit_code == 0
        assert "Downloading 1 of 2 tracks" in result.output
        assert (out / "b.flac").read_bytes() == b"data"

    def test_download_resume_retries_failed_track(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """A re-run with an existing manifest retries only the errored track."""
        tracks = self._queue_tracks()
        self._mock_services(
            mocker,
            tracks,
            ["http://h/a.flac", "http://h/b.flac", "http://h/a.flac"],
            states=[
                {**tracks[0], "position": 0},
                {**tracks[1], "position": 1},
                {**tracks[0], "position": 0},
            ],
        )
        ok_response = mocker.Mock()
        ok_response.iter_content.return_value = [b"data"]
        mock_get = mocker.patch(
            "volumito.cli.click_helpers.requests.get",
            side_effect=[
                requests.exceptions.RequestException("boom"),
                ok_response,
                ok_response,
            ],
        )

        first = runner.invoke(main, [*self._BASE, "-d", str(tmp_path)])

        assert first.exit_code == 1
        _, log = self._read_log(tmp_path)
        assert [t["status"] for t in log["tracks"]] == ["error", "downloaded"]
        assert log["updates"] == 1
        first_date = log["first_download_date"]

        second = runner.invoke(main, [*self._BASE, "-d", str(tmp_path)])

        assert second.exit_code == 0
        assert "(kept)" in second.output
        _, log = self._read_log(tmp_path)
        assert [t["status"] for t in log["tracks"]] == ["downloaded", "downloaded"]
        assert "error" not in log["tracks"][0]
        assert log["updates"] == 2
        assert log["first_download_date"] == first_date
        assert "last_update_date" in log
        assert (tmp_path / "a.flac").read_bytes() == b"data"
        assert (tmp_path / "b.flac").read_bytes() == b"data"
        # Two fetches in the first run, only the retried track in the second
        assert mock_get.call_count == 3

    def test_download_resume_retries_pending_and_skipped(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """Pending and skipped manifest entries are retried; downloaded ones are kept."""
        tracks = [
            {"title": "Song A", "artist": "Artist", "album": "Album", "tracknumber": 1},
            {"title": "Song B", "artist": "Artist", "album": "Album", "tracknumber": 2},
            {"title": "Song C", "artist": "Artist", "album": "Album", "tracknumber": 3},
        ]
        self._mock_services(
            mocker,
            tracks,
            ["http://h/b.flac", "http://h/c.flac"],
            states=[
                {**tracks[1], "position": 1},
                {**tracks[2], "position": 2},
            ],
        )
        manifest = tmp_path / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "first_download_date": "2026-01-01T00:00:00+00:00",
                    "updates": 3,
                    "tracks": [
                        {
                            "title": "Song A",
                            "artist": "Artist",
                            "album": "Album",
                            "status": "downloaded",
                            "output_file_path": str(tmp_path / "a.flac"),
                        },
                        {
                            "title": "Song B",
                            "artist": "Artist",
                            "album": "Album",
                            "status": "skipped",
                        },
                        {
                            "title": "Song C",
                            "artist": "Artist",
                            "album": "Album",
                            "status": "pending",
                        },
                    ],
                }
            )
        )

        result = runner.invoke(main, [*self._BASE, "-d", str(tmp_path)])

        assert result.exit_code == 0
        _, log = self._read_log(tmp_path)
        assert [t["status"] for t in log["tracks"]] == ["downloaded"] * 3
        assert log["updates"] == 4
        assert log["first_download_date"] == "2026-01-01T00:00:00+00:00"
        # Only the skipped and pending tracks are played (plus the final reposition)
        assert (tmp_path / "b.flac").read_bytes() == b"data"
        assert (tmp_path / "c.flac").read_bytes() == b"data"
        assert not (tmp_path / "a.flac").exists()

    def test_download_resume_all_downloaded_leaves_playback_untouched(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """With every track already downloaded, playback and MPD are not touched."""
        client = self._mock_services(mocker, self._queue_tracks()[:1], [])
        mpd_class = mocker.patch("volumito.cli.volumito.VolumioMPDClient")
        mock_get = mocker.patch("volumito.cli.click_helpers.requests.get")
        manifest = tmp_path / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "first_download_date": "2026-01-01T00:00:00+00:00",
                    "updates": 1,
                    "tracks": [
                        {
                            "title": "Song A",
                            "artist": "Artist",
                            "album": "Album",
                            "status": "downloaded",
                            "output_file_path": str(tmp_path / "a.flac"),
                        }
                    ],
                }
            )
        )

        result = runner.invoke(main, [*self._BASE, "-d", str(tmp_path)])

        assert result.exit_code == 0
        assert f'"{tmp_path / "a.flac"}" (kept)' in result.output
        assert "Downloaded 1, skipped 0, errors 0" in result.output
        assert f'Reading manifest file "{manifest}"' in result.output
        client.stop.assert_not_called()
        client.play.assert_not_called()
        mpd_class.assert_not_called()
        mock_get.assert_not_called()
        with open(manifest, encoding="utf-8") as manifest_handle:
            log = json.load(manifest_handle)
        assert log["updates"] == 2

        machine = runner.invoke(main, ["-m", *self._BASE, "-d", str(tmp_path)])

        assert machine.exit_code == 0
        assert machine.output.strip() == json.dumps(str(manifest))

    def test_download_resume_keeps_skipped_with_existing_file(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """Skipped entries whose file still exists are kept without replaying."""
        client = self._mock_services(mocker, self._queue_tracks(), [])
        mpd_class = mocker.patch("volumito.cli.volumito.VolumioMPDClient")
        mock_get = mocker.patch("volumito.cli.click_helpers.requests.get")
        (tmp_path / "a.flac").write_bytes(b"old")
        (tmp_path / "b.flac").write_bytes(b"old")
        manifest = tmp_path / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "first_download_date": "2026-01-01T00:00:00+00:00",
                    "updates": 2,
                    "tracks": [
                        {
                            "title": "Song A",
                            "artist": "Artist",
                            "album": "Album",
                            "status": "skipped",
                            "output_file_path": str(tmp_path / "a.flac"),
                        },
                        {
                            "title": "Song B",
                            "artist": "Artist",
                            "album": "Album",
                            "status": "skipped",
                            "output_file_path": str(tmp_path / "b.flac"),
                        },
                    ],
                }
            )
        )

        result = runner.invoke(main, [*self._BASE, "-d", str(tmp_path)])

        assert result.exit_code == 0
        assert "Downloaded 0, skipped 2, errors 0" in result.output
        assert result.output.count("(kept)") == 2
        client.stop.assert_not_called()
        client.play.assert_not_called()
        mpd_class.assert_not_called()
        mock_get.assert_not_called()
        with open(manifest, encoding="utf-8") as manifest_handle:
            log = json.load(manifest_handle)
        assert [t["status"] for t in log["tracks"]] == ["skipped", "skipped"]
        assert log["updates"] == 3

    def test_download_resume_retries_skipped_with_missing_file(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """A skipped entry whose file is gone is retried and downloaded."""
        tracks = self._queue_tracks()[:1]
        self._mock_services(
            mocker,
            tracks,
            ["http://h/a.flac"],
            states=[{**tracks[0], "position": 0}],
        )
        manifest = tmp_path / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "tracks": [
                        {
                            "title": "Song A",
                            "artist": "Artist",
                            "album": "Album",
                            "status": "skipped",
                            "output_file_path": str(tmp_path / "a.flac"),
                        }
                    ]
                }
            )
        )

        result = runner.invoke(main, [*self._BASE, "-d", str(tmp_path)])

        assert result.exit_code == 0
        assert (tmp_path / "a.flac").read_bytes() == b"data"
        with open(manifest, encoding="utf-8") as manifest_handle:
            log = json.load(manifest_handle)
        assert log["tracks"][0]["status"] == "downloaded"

    def test_download_resume_overwrite_retries_skipped(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """With --overwrite-existing-files, skipped entries are retried and rewritten."""
        tracks = self._queue_tracks()[:1]
        self._mock_services(
            mocker,
            tracks,
            ["http://h/a.flac"],
            states=[{**tracks[0], "position": 0}],
        )
        (tmp_path / "a.flac").write_bytes(b"old")
        manifest = tmp_path / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "tracks": [
                        {
                            "title": "Song A",
                            "artist": "Artist",
                            "album": "Album",
                            "status": "skipped",
                            "output_file_path": str(tmp_path / "a.flac"),
                        }
                    ]
                }
            )
        )

        result = runner.invoke(
            main, [*self._BASE, "-d", str(tmp_path), "--overwrite-existing-files"]
        )

        assert result.exit_code == 0
        assert (tmp_path / "a.flac").read_bytes() == b"data"
        with open(manifest, encoding="utf-8") as manifest_handle:
            log = json.load(manifest_handle)
        assert log["tracks"][0]["status"] == "downloaded"

    def test_download_resume_mismatched_manifest(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """A manifest that does not match the current queue is refused untouched."""
        self._mock_services(mocker, self._queue_tracks(), [])
        manifest = tmp_path / "manifest.json"
        content = json.dumps(
            {
                "tracks": [
                    {"title": "Other", "artist": "Artist", "album": "Album", "status": "error"}
                ]
            }
        )
        manifest.write_text(content)

        result = runner.invoke(main, [*self._BASE, "-d", str(tmp_path)])

        assert result.exit_code == 1
        assert "does not match the current queue" in result.output
        assert manifest.read_text() == content

    @pytest.mark.parametrize(
        "content",
        [
            "not json at all {",
            "[1, 2]",
            '{"tracks": "nope"}',
            '{"tracks": [1, 2]}',
        ],
    )
    def test_download_resume_unreadable_manifest(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path, content: str
    ):
        """An unparseable or malformed manifest file is refused with a clean error."""
        self._mock_services(mocker, self._queue_tracks(), [])
        manifest = tmp_path / "manifest.json"
        manifest.write_text(content)

        result = runner.invoke(main, [*self._BASE, "-d", str(tmp_path)])

        assert result.exit_code == 1
        assert "Cannot read the manifest file" in result.output

    def test_download_resume_legacy_manifest(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """A legacy manifest with download_date only is resumed with fallbacks."""
        tracks = self._queue_tracks()
        self._mock_services(
            mocker,
            tracks,
            ["http://h/a.flac"],
            states=[{**tracks[0], "position": 0}],
        )
        manifest = tmp_path / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "download_date": "2020-01-01T00:00:00+00:00",
                    "tracks": [
                        {
                            "title": "Song A",
                            "artist": "Artist",
                            "album": "Album",
                            "status": "error",
                            "error": "boom",
                        },
                        {
                            "title": "Song B",
                            "artist": "Artist",
                            "album": "Album",
                            "status": "downloaded",
                            "output_file_path": str(tmp_path / "b.flac"),
                        },
                    ],
                }
            )
        )

        result = runner.invoke(main, [*self._BASE, "-d", str(tmp_path)])

        assert result.exit_code == 0
        _, log = self._read_log(tmp_path)
        assert log["first_download_date"] == "2020-01-01T00:00:00+00:00"
        assert "download_date" not in log
        assert log["updates"] == 1
        assert [t["status"] for t in log["tracks"]] == ["downloaded", "downloaded"]

    def test_download_machine_readable(self, runner: CliRunner, mocker: MockerFixture, tmp_path):
        """In machine-readable mode only the quoted log path is printed."""
        self._mock_services(mocker, self._queue_tracks()[:1], ["http://h/a.flac"])

        result = runner.invoke(main, ["-m", *self._BASE, "-d", str(tmp_path)])

        assert result.exit_code == 0
        log_path, log = self._read_log(tmp_path)
        assert result.output.strip() == json.dumps(str(log_path))
        assert log["tracks"][0]["status"] == "downloaded"

    def test_download_empty_queue(self, runner: CliRunner, mocker: MockerFixture, tmp_path):
        """An empty queue downloads nothing and writes no log."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "queue", return_value={"queue": []})
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient", return_value=mock_client
        )

        result = runner.invoke(main, [*self._BASE, "-d", str(tmp_path)])

        assert result.exit_code == 0
        assert "The queue is empty" in result.output
        assert list(tmp_path.iterdir()) == []
        mock_client.stop.assert_not_called()

    def test_download_manifest_and_embedding(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """With the defaults on, a per-track manifest is written and tags are embedded."""
        self._mock_services(mocker, self._queue_tracks()[:1], ["http://h/a.flac"])
        embed = mocker.patch("volumito.cli.volumito.embed_track_tags")

        result = runner.invoke(main, ["queue", "download", "-d", str(tmp_path)])

        assert result.exit_code == 0
        run = tmp_path
        with open(run / "a.flac.json", encoding="utf-8") as manifest_file:
            manifest = json.load(manifest_file)
        assert manifest["entity"] == "track"
        assert manifest["kind"] == "audio"
        assert manifest["add_cover_and_metadata"] is True
        embed.assert_called_once()
        assert embed.call_args.args[0] == str(run / "a.flac")

    def test_download_config_subsection(self, runner: CliRunner, mocker: MockerFixture, tmp_path):
        """The queue-download configuration subsection supplies directory and template."""
        out = tmp_path / "out"
        config = tmp_path / "volumito.yaml"
        config.write_text(
            "downloads:\n"
            "  queue-download:\n"
            f"    output-directory: {out}\n"
            '    audio-file-name-template: "{title}.{extension}"\n'
        )
        self._mock_services(
            mocker,
            [{"title": "Song", "artist": "A", "album": "B"}],
            ["http://h/a.flac"],
            states=[{"title": "Song", "artist": "A", "album": "B", "position": 0}],
        )

        result = runner.invoke(main, ["-c", str(config), *self._BASE])

        assert result.exit_code == 0
        assert (out / "Song.flac").read_bytes() == b"data"

    def test_download_position_starting_at_zero(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """--position-starting-at-zero is reflected in the log positions."""
        self._mock_services(mocker, self._queue_tracks(), ["http://h/a.flac", "http://h/b.flac"])

        result = runner.invoke(
            main, ["--position-starting-at-zero", *self._BASE, "-d", str(tmp_path)]
        )

        assert result.exit_code == 0
        _, log = self._read_log(tmp_path)
        assert [t["position"] for t in log["tracks"]] == [0, 1]

    def test_download_api_error_marks_track(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """A per-track API error is recorded and the remaining tracks proceed."""
        self._mock_services(
            mocker,
            self._queue_tracks(),
            ["http://h/b.flac"],
            states=[
                VolumioAPIError("bad state"),
                {"title": "Song B", "artist": "Artist", "album": "Album", "position": 1},
            ],
        )

        result = runner.invoke(main, [*self._BASE, "-d", str(tmp_path)])

        assert result.exit_code == 1
        _, log = self._read_log(tmp_path)
        assert log["tracks"][0]["status"] == "error"
        assert "bad state" in log["tracks"][0]["error"]
        assert log["tracks"][1]["status"] == "downloaded"

    def test_download_unresolvable_name(self, runner: CliRunner, mocker: MockerFixture, tmp_path):
        """A URI without a usable file name is recorded as an error."""
        self._mock_services(mocker, self._queue_tracks()[:1], ["http://h/"])

        result = runner.invoke(main, [*self._BASE, "-d", str(tmp_path)])

        assert result.exit_code == 1
        _, log = self._read_log(tmp_path)
        assert log["tracks"][0]["status"] == "error"
        assert "cannot determine a file name" in log["tracks"][0]["error"]

    def test_download_connection_error(self, runner: CliRunner, mocker: MockerFixture, tmp_path):
        """A connection failure while fetching the queue exits with an error."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "queue", side_effect=VolumioConnectionError("no route"))
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient", return_value=mock_client
        )

        result = runner.invoke(main, [*self._BASE, "-d", str(tmp_path)])

        assert result.exit_code == 1
        assert "Connection error" in result.output

    def test_download_api_error(self, runner: CliRunner, mocker: MockerFixture, tmp_path):
        """An API failure while fetching the queue exits with an error."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "queue", side_effect=VolumioAPIError("nope"))
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient", return_value=mock_client
        )

        result = runner.invoke(main, [*self._BASE, "-d", str(tmp_path)])

        assert result.exit_code == 1
        assert "API error" in result.output

    def test_download_tracknumber_restarts_per_album(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """{tracknumber} numbers each album's tracks from one, unlike {position}."""
        tracks = [
            {"title": "A", "artist": "Art1", "album": "Alb1", "tracknumber": 1},
            {"title": "B", "artist": "Art1", "album": "Alb1", "tracknumber": 2},
            {"title": "C", "artist": "Art2", "album": "Alb2", "tracknumber": 1},
        ]
        self._mock_services(
            mocker,
            tracks,
            ["http://h/a.flac", "http://h/b.flac", "http://h/c.flac"],
            states=[
                {"title": "A", "artist": "Art1", "album": "Alb1", "position": 0},
                {"title": "B", "artist": "Art1", "album": "Alb1", "position": 1},
                {"title": "C", "artist": "Art2", "album": "Alb2", "position": 2},
            ],
        )

        result = runner.invoke(
            main,
            [*self._BASE, "-d", str(tmp_path), "-f", "{tracknumber:02d}_{title}.{extension}"],
        )

        assert result.exit_code == 0
        run = tmp_path
        assert (run / "01_A.flac").exists()
        assert (run / "02_B.flac").exists()
        assert (run / "01_C.flac").exists()
        _, log = self._read_log(tmp_path)
        assert [t["track_number"] for t in log["tracks"]] == [1, 2, 1]
        assert [t["position"] for t in log["tracks"]] == [1, 2, 3]

    def test_download_embeds_album_relative_tracknumber(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """The embedded track number is the album-relative one, not the queue position."""
        tracks = [
            {"title": "A", "artist": "Art1", "album": "Alb1", "tracknumber": 1},
            {"title": "C", "artist": "Art2", "album": "Alb2", "tracknumber": 1},
        ]
        self._mock_services(
            mocker,
            tracks,
            ["http://h/a.flac", "http://h/c.flac"],
            states=[
                {"title": "A", "artist": "Art1", "album": "Alb1", "position": 0},
                {"title": "C", "artist": "Art2", "album": "Alb2", "position": 1},
            ],
        )
        embed = mocker.patch("volumito.cli.click_helpers.embed_metadata_and_cover")
        mocker.patch("volumito.cli.click_helpers.fetch_cover", return_value=None)

        result = runner.invoke(
            main, ["queue", "download", "--no-create-download-manifest", "-d", str(tmp_path)]
        )

        assert result.exit_code == 0
        # Both tracks are the first of their album: embedded number 1, not queue 1 and 2
        assert [c.kwargs["track_number"] for c in embed.call_args_list] == [1, 1]

    def test_download_retries_until_metadata_current(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """Stale metadata after moving to the next track are retried until current."""
        states = [
            {"title": "Song A", "artist": "Artist", "album": "Album", "position": 0},
            # track 2, first attempt: stale (still the first track's metadata)
            {"title": "Song A", "artist": "Artist", "album": "Album", "position": 0},
            # track 2, retry: fresh
            {"title": "Song B", "artist": "Artist", "album": "Album", "position": 1},
        ]
        uris = ["http://h/a.flac", "http://h/a.flac", "http://h/b.flac"]
        client = self._mock_services(mocker, self._queue_tracks(), uris, states=states)

        result = runner.invoke(main, ["-v", *self._BASE, "-d", str(tmp_path)])

        assert result.exit_code == 0
        assert "retrying (1/10)" in result.output
        run = tmp_path
        assert (run / "a.flac").exists()
        assert (run / "b.flac").exists()
        _, log = self._read_log(tmp_path)
        assert [t["status"] for t in log["tracks"]] == ["downloaded", "downloaded"]
        # The retry replays position 1; the final reposition plays 0 again
        assert _played_positions(client) == [0, 1, 1, 0]

    def test_download_metadata_never_current_marks_error(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """A track whose metadata never update is recorded as an error after the retries."""
        stale = {"title": "Song A", "artist": "Artist", "album": "Album", "position": 0}
        states = [dict(stale) for _ in range(12)]
        uris = ["http://h/a.flac"] * 12
        self._mock_services(mocker, self._queue_tracks(), uris, states=states)

        result = runner.invoke(main, [*self._BASE, "-d", str(tmp_path)])

        assert result.exit_code == 1
        _, log = self._read_log(tmp_path)
        assert log["tracks"][0]["status"] == "downloaded"
        assert log["tracks"][1]["status"] == "error"
        assert "after 10 retries" in log["tracks"][1]["error"]

    def test_download_number_retries_option(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """--number-retries-next-track 0 fails immediately on stale metadata."""
        stale = {"title": "Song A", "artist": "Artist", "album": "Album", "position": 0}
        states = [dict(stale), dict(stale)]
        uris = ["http://h/a.flac", "http://h/a.flac"]
        client = self._mock_services(mocker, self._queue_tracks(), uris, states=states)

        result = runner.invoke(
            main, [*self._BASE, "-d", str(tmp_path), "--number-retries-next-track", "0"]
        )

        assert result.exit_code == 1
        _, log = self._read_log(tmp_path)
        assert "after 0 retries" in log["tracks"][1]["error"]
        # No retry: one play per track plus the final reposition
        assert _played_positions(client) == [0, 1, 0]

    def test_download_no_check_next_track(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """--no-check-next-track accepts the metadata without any verification."""
        states = [
            {"title": "Song A", "position": 0},
            {"title": "Song A", "position": 0},  # stale, but the check is off
        ]
        uris = ["http://h/a.flac", "http://h/b.flac"]
        client = self._mock_services(mocker, self._queue_tracks(), uris, states=states)

        result = runner.invoke(main, [*self._BASE, "-d", str(tmp_path), "--no-check-next-track"])

        assert result.exit_code == 0
        _, log = self._read_log(tmp_path)
        assert [t["status"] for t in log["tracks"]] == ["downloaded", "downloaded"]
        assert _played_positions(client) == [0, 1, 0]

    def test_download_duplicate_adjacent_tracks_accepted(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """Two adjacent queue entries with the same URI do not trigger retries."""
        tracks = [
            {"title": "Song A", "artist": "Artist", "album": "Album", "uri": "x/a.flac"},
            {"title": "Song A", "artist": "Artist", "album": "Album", "uri": "x/a.flac"},
        ]
        states = [
            {"title": "Song A", "artist": "Artist", "album": "Album", "position": 0},
            {"title": "Song A", "artist": "Artist", "album": "Album", "position": 1},
        ]
        uris = ["http://h/a.flac", "http://h/a.flac"]
        client = self._mock_services(mocker, tracks, uris, states=states)

        result = runner.invoke(main, [*self._BASE, "-d", str(tmp_path)])

        assert result.exit_code == 0
        _, log = self._read_log(tmp_path)
        assert [t["status"] for t in log["tracks"]] == ["downloaded", "skipped"]
        assert _played_positions(client) == [0, 1, 0]

    def test_download_album_volume_key(self, runner: CliRunner, mocker: MockerFixture, tmp_path):
        """{album_volume} creates per-volume subdirectories for multi-volume albums."""
        tracks = [
            {
                "title": "A",
                "artist": "Art",
                "album": "Elegia",
                "tracknumber": 1,
                "volumeNumber": 1,
            },
            {
                "title": "B",
                "artist": "Art",
                "album": "Elegia",
                "tracknumber": 1,
                "volumeNumber": 2,
            },
            {
                "title": "C",
                "artist": "Art",
                "album": "Allegria",
                "tracknumber": 1,
                "volumeNumber": 1,
            },
        ]
        states = [
            {
                "title": "A",
                "artist": "Art",
                "album": "Elegia",
                "albumart": "http://e.com/c1.jpg",
                "position": 0,
            },
            {
                "title": "B",
                "artist": "Art",
                "album": "Elegia",
                "albumart": "http://e.com/c2.jpg",
                "position": 1,
            },
            {
                "title": "C",
                "artist": "Art",
                "album": "Allegria",
                "albumart": "http://e.com/c3.jpg",
                "position": 2,
            },
        ]
        self._mock_services(
            mocker,
            tracks,
            ["http://h/a.flac", "http://h/b.flac", "http://h/c.flac"],
            states=states,
        )

        result = runner.invoke(
            main,
            [
                *self._BASE,
                "-d",
                str(tmp_path),
                "-f",
                "{album_volume}/{tracknumber:02d}_{title}.{extension}",
                "--albumart-file-name-template",
                "{album_volume}/cover.{extension}",
            ],
        )

        assert result.exit_code == 0
        run = tmp_path
        assert (run / "Elegia" / "1" / "01_A.flac").exists()
        assert (run / "Elegia" / "2" / "01_B.flac").exists()
        assert (run / "Allegria" / "01_C.flac").exists()
        assert (run / "Elegia" / "1" / "cover.jpg").exists()
        assert (run / "Elegia" / "2" / "cover.jpg").exists()
        assert (run / "Allegria" / "cover.jpg").exists()
        _, log = self._read_log(tmp_path)
        assert [t["volume_number"] for t in log["tracks"]] == [1, 2, 1]
        assert [t["track_number"] for t in log["tracks"]] == [1, 1, 1]

    def test_download_albumart_copied_per_volume(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """One cover URI shared by two volumes lands in both volume directories."""
        cover_uri = "http://e.com/c.jpg"
        tracks = [
            {
                "title": "A",
                "artist": "Art",
                "album": "Elegia",
                "tracknumber": 1,
                "volumeNumber": 1,
            },
            {
                "title": "B",
                "artist": "Art",
                "album": "Elegia",
                "tracknumber": 1,
                "volumeNumber": 2,
            },
        ]
        states = [
            {
                "title": "A",
                "artist": "Art",
                "album": "Elegia",
                "albumart": cover_uri,
                "position": 0,
            },
            {
                "title": "B",
                "artist": "Art",
                "album": "Elegia",
                "albumart": cover_uri,
                "position": 1,
            },
        ]
        self._mock_services(
            mocker, tracks, ["http://h/a.flac", "http://h/b.flac"], states=states
        )
        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"data"]
        http_get = mocker.patch(
            "volumito.cli.click_helpers.requests.get", return_value=mock_response
        )

        result = runner.invoke(
            main,
            [
                *self._BASE,
                "-d",
                str(tmp_path),
                "-f",
                "{album_volume}/{tracknumber:02d}_{title}.{extension}",
                "--albumart-file-name-template",
                "{album_volume}/cover.{extension}",
            ],
        )

        assert result.exit_code == 0
        run = tmp_path
        assert (run / "Elegia" / "1" / "cover.jpg").read_bytes() == b"data"
        assert (run / "Elegia" / "2" / "cover.jpg").read_bytes() == b"data"
        # The album directory itself also gets a copy of the cover
        assert (run / "Elegia" / "cover.jpg").read_bytes() == b"data"
        # Two audio fetches plus a single cover fetch: the other covers are local copies
        assert http_get.call_count == 3
        _, log = self._read_log(tmp_path)
        assert [t["albumart_file_path"] for t in log["tracks"]] == [
            str(run / "Elegia" / "1" / "cover.jpg"),
            str(run / "Elegia" / "2" / "cover.jpg"),
        ]

    def test_download_albumart_deduplicates(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """The cover of an album is downloaded only once for all its tracks."""
        cover_uri = "http://example.com/images/c.jpg"
        states = [
            {
                "title": "Song A",
                "artist": "Artist",
                "album": "Album",
                "albumart": cover_uri,
                "position": 0,
            },
            {
                "title": "Song B",
                "artist": "Artist",
                "album": "Album",
                "albumart": cover_uri,
                "position": 1,
            },
        ]
        self._mock_services(
            mocker, self._queue_tracks(), ["http://h/a.flac", "http://h/b.flac"], states=states
        )
        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"data"]
        http_get = mocker.patch(
            "volumito.cli.click_helpers.requests.get", return_value=mock_response
        )

        result = runner.invoke(
            main,
            [*self._BASE, "-d", str(tmp_path), "-f", "{artist}/{album}/{title}.{extension}"],
        )

        assert result.exit_code == 0
        run = tmp_path
        # Default albumart template: the file name from the album-art URI
        assert (run / "c.jpg").read_bytes() == b"data"
        # Two audio downloads plus a single cover download
        assert http_get.call_count == 3
        _, log = self._read_log(tmp_path)
        cover = str(run / "c.jpg")
        assert [t["albumart_file_path"] for t in log["tracks"]] == [cover, cover]

    def test_download_albumart_per_album(self, runner: CliRunner, mocker: MockerFixture, tmp_path):
        """Each album of the queue gets its own cover in its own directory."""
        tracks = [
            {"title": "A", "artist": "Art1", "album": "Alb1", "tracknumber": 1},
            {"title": "C", "artist": "Art2", "album": "Alb2", "tracknumber": 1},
        ]
        states = [
            {
                "title": "A",
                "artist": "Art1",
                "album": "Alb1",
                "albumart": "http://example.com/c1.jpg",
                "position": 0,
            },
            {
                "title": "C",
                "artist": "Art2",
                "album": "Alb2",
                "albumart": "http://example.com/c2.jpg",
                "position": 1,
            },
        ]
        self._mock_services(
            mocker, tracks, ["http://h/a.flac", "http://h/c.flac"], states=states
        )
        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"data"]
        http_get = mocker.patch(
            "volumito.cli.click_helpers.requests.get", return_value=mock_response
        )

        result = runner.invoke(
            main,
            [*self._BASE, "-d", str(tmp_path), "-f", "{artist}/{album}/{title}.{extension}"],
        )

        assert result.exit_code == 0
        run = tmp_path
        assert (run / "c1.jpg").exists()
        assert (run / "c2.jpg").exists()
        assert http_get.call_count == 4

    def test_download_albumart_existing_file_reused(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """An existing cover file at the rendered path is not re-downloaded."""
        states = [
            {
                "title": "Song A",
                "artist": "Artist",
                "album": "Album",
                "albumart": "http://h1/img/cover.jpg",
                "position": 0,
            },
            {
                "title": "Song B",
                "artist": "Artist",
                "album": "Album",
                "albumart": "http://h2/img/cover.jpg",
                "position": 1,
            },
        ]
        self._mock_services(
            mocker, self._queue_tracks(), ["http://h/a.flac", "http://h/b.flac"], states=states
        )
        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"data"]
        http_get = mocker.patch(
            "volumito.cli.click_helpers.requests.get", return_value=mock_response
        )

        result = runner.invoke(main, [*self._BASE, "-d", str(tmp_path)])

        assert result.exit_code == 0
        run = tmp_path
        assert (run / "cover.jpg").exists()
        # Two distinct URIs render the same name: the existing file is reused
        assert http_get.call_count == 3
        _, log = self._read_log(tmp_path)
        cover = str(run / "cover.jpg")
        assert [t["albumart_file_path"] for t in log["tracks"]] == [cover, cover]

    def test_download_albumart_failure_warns(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """A failed cover download warns but does not fail the track."""
        states = [
            {
                "title": "Song A",
                "artist": "Artist",
                "album": "Album",
                "albumart": "http://example.com/c.jpg",
                "position": 0,
            },
        ]
        self._mock_services(mocker, self._queue_tracks()[:1], ["http://h/a.flac"], states=states)
        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"data"]
        mocker.patch(
            "volumito.cli.click_helpers.requests.get",
            side_effect=[mock_response, requests.exceptions.RequestException("cover boom")],
        )

        result = runner.invoke(main, [*self._BASE, "-d", str(tmp_path)])

        assert result.exit_code == 0
        assert "Cannot download album art" in result.output
        _, log = self._read_log(tmp_path)
        assert log["tracks"][0]["status"] == "downloaded"
        assert "albumart_file_path" not in log["tracks"][0]

    def test_download_no_with_albumart_option(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """--no-with-albumart skips the cover downloads entirely."""
        states = [
            {
                "title": "Song A",
                "artist": "Artist",
                "album": "Album",
                "albumart": "http://example.com/c.jpg",
                "position": 0,
            },
        ]
        self._mock_services(mocker, self._queue_tracks()[:1], ["http://h/a.flac"], states=states)
        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"data"]
        http_get = mocker.patch(
            "volumito.cli.click_helpers.requests.get", return_value=mock_response
        )

        result = runner.invoke(main, [*self._BASE, "-d", str(tmp_path), "--no-with-albumart"])

        assert result.exit_code == 0
        run = tmp_path
        assert not (run / "c.jpg").exists()
        assert http_get.call_count == 1

    def test_download_config_with_albumart_disabled(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """A shared downloads.with-albumart: false disables the cover downloads."""
        out = tmp_path / "out"
        config = tmp_path / "volumito.yaml"
        config.write_text("downloads:\n  with-albumart: false\n")
        states = [
            {
                "title": "Song A",
                "artist": "Artist",
                "album": "Album",
                "albumart": "http://example.com/c.jpg",
                "position": 0,
            },
        ]
        self._mock_services(mocker, self._queue_tracks()[:1], ["http://h/a.flac"], states=states)

        result = runner.invoke(main, ["-c", str(config), *self._BASE, "-d", str(out)])

        assert result.exit_code == 0
        assert not (out / "c.jpg").exists()

    def test_download_config_number_retries(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """downloads.queue-download.number-retries-next-track is respected."""
        out = tmp_path / "out"
        config = tmp_path / "volumito.yaml"
        config.write_text("downloads:\n  queue-download:\n    number-retries-next-track: 0\n")
        stale = {"title": "Song A", "artist": "Artist", "album": "Album", "position": 0}
        states = [dict(stale), dict(stale)]
        uris = ["http://h/a.flac", "http://h/a.flac"]
        client = self._mock_services(mocker, self._queue_tracks(), uris, states=states)

        result = runner.invoke(main, ["-c", str(config), *self._BASE, "-d", str(out)])

        assert result.exit_code == 1
        _, log = self._read_log(out)
        assert "after 0 retries" in log["tracks"][1]["error"]
        # No retry: one play per track plus the final reposition
        assert _played_positions(client) == [0, 1, 0]

    def test_download_albumart_custom_template(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """--albumart-file-name-template renders the cover path, creating subdirectories."""
        states = [
            {
                "title": "Song A",
                "artist": "Artist",
                "album": "Album",
                "albumart": "http://example.com/c.jpg",
                "position": 0,
            },
        ]
        self._mock_services(mocker, self._queue_tracks()[:1], ["http://h/a.flac"], states=states)

        result = runner.invoke(
            main,
            [
                *self._BASE,
                "-d",
                str(tmp_path),
                "--albumart-file-name-template",
                "{artist}/{album}/000___{album}.{extension}",
            ],
        )

        assert result.exit_code == 0
        run = tmp_path
        assert (run / "Artist" / "Album" / "000___Album.jpg").read_bytes() == b"data"
        _, log = self._read_log(tmp_path)
        expected = str(run / "Artist" / "Album" / "000___Album.jpg")
        assert log["tracks"][0]["albumart_file_path"] == expected

    def test_download_albumart_config_template(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """The queue-download albumart-file-name-template configuration key is respected."""
        out = tmp_path / "out"
        config = tmp_path / "volumito.yaml"
        config.write_text(
            "downloads:\n"
            "  queue-download:\n"
            '    albumart-file-name-template: "{album}_cover.{extension}"\n'
        )
        states = [
            {
                "title": "Song A",
                "artist": "Artist",
                "album": "Album",
                "albumart": "http://example.com/c.jpg",
                "position": 0,
            },
        ]
        self._mock_services(mocker, self._queue_tracks()[:1], ["http://h/a.flac"], states=states)

        result = runner.invoke(main, ["-c", str(config), *self._BASE, "-d", str(out)])

        assert result.exit_code == 0
        assert (out / "Album_cover.jpg").exists()

    def test_download_albumart_template_escape_rejected(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """An albumart template escaping the run directory is a usage error."""
        states = [
            {
                "title": "Song A",
                "artist": "Artist",
                "album": "Album",
                "albumart": "http://example.com/c.jpg",
                "position": 0,
            },
        ]
        self._mock_services(mocker, self._queue_tracks()[:1], ["http://h/a.flac"], states=states)

        result = runner.invoke(
            main,
            [
                *self._BASE,
                "-d",
                str(tmp_path),
                "--albumart-file-name-template",
                "x/../../{album}.{extension}",
            ],
        )

        assert result.exit_code == 2
        assert "Invalid --albumart-file-name-template" in result.output
        assert "escapes the output directory" in result.output

    def test_download_albumart_unresolvable_name_warns(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """A cover whose name cannot be determined warns without failing the track."""
        states = [
            {
                "title": "Song A",
                "artist": "Artist",
                "album": "Album",
                "albumart": "http://example.com/",
                "position": 0,
            },
        ]
        self._mock_services(mocker, self._queue_tracks()[:1], ["http://h/a.flac"], states=states)

        result = runner.invoke(main, [*self._BASE, "-d", str(tmp_path)])

        assert result.exit_code == 0
        assert "Cannot determine a file name for the album art" in result.output
        _, log = self._read_log(tmp_path)
        assert log["tracks"][0]["status"] == "downloaded"
        assert "albumart_file_path" not in log["tracks"][0]

    def test_download_config_check_next_track(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """miscellaneous.check-next-track: false disables the verification."""
        out = tmp_path / "out"
        config = tmp_path / "volumito.yaml"
        config.write_text("miscellaneous:\n  check-next-track: false\n")
        states = [
            {"title": "Song A", "position": 0},
            {"title": "Song A", "position": 0},  # stale, but the config disables the check
        ]
        uris = ["http://h/a.flac", "http://h/b.flac"]
        client = self._mock_services(mocker, self._queue_tracks(), uris, states=states)

        result = runner.invoke(main, ["-c", str(config), *self._BASE, "-d", str(out)])

        assert result.exit_code == 0
        assert _played_positions(client) == [0, 1, 0]


class TestPlaylistDownload:
    """Test cases for the playlist download command."""

    _BASE = [
        "playlist",
        "download",
        "Rock",
        "--no-create-download-manifest",
        "--no-add-cover-and-metadata",
        "--no-print-resulting-status",
    ]

    @pytest.fixture
    def runner(self):
        """Create a CliRunner instance."""
        return CliRunner()

    def _queue_tracks(self):
        return [
            {"title": "Song A", "artist": "Artist", "album": "Album", "tracknumber": 1},
            {"title": "Song B", "artist": "Artist", "album": "Album", "tracknumber": 2},
        ]

    def _mock_services(self, mocker: MockerFixture, tracks, uris, states=None):
        """Mock the REST client, the MPD client, the HTTP download, and the sleep."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "playlists", return_value=["Rock", "Jazz"])
        _attach_property(mock_client, "queue", return_value={"queue": tracks})
        if states is not None:
            _attach_property(mock_client, "state", side_effect=states)
        else:
            _attach_property(
                mock_client,
                "state",
                side_effect=[
                    {**track, "position": index} for index, track in enumerate(tracks)
                ],
            )
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        mpd = mocker.Mock()
        mpd.get_track_uri.side_effect = list(uris)
        mpd_class = mocker.Mock(return_value=mpd)
        mpd_class.return_value.__enter__ = mocker.Mock(return_value=mpd)
        mpd_class.return_value.__exit__ = mocker.Mock(return_value=None)
        mocker.patch("volumito.cli.volumito.VolumioMPDClient", new=mpd_class)

        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"data"]
        mocker.patch("volumito.cli.click_helpers.requests.get", return_value=mock_response)
        mocker.patch("volumito.cli.click_helpers.time.sleep")
        return mock_client

    def _read_log(self, base):
        """Return the run's download manifest (path, parsed content)."""
        log_path = base / "manifest.json"
        with open(log_path, encoding="utf-8") as log_file:
            return log_path, json.load(log_file)

    def test_download_happy_path(self, runner: CliRunner, mocker: MockerFixture, tmp_path):
        """The playlist is checked, played, and its queue downloaded."""
        client = self._mock_services(
            mocker, self._queue_tracks(), ["http://h/a.flac", "http://h/b.flac"]
        )

        result = runner.invoke(main, ["-v", *self._BASE, "-d", str(tmp_path)])

        assert result.exit_code == 0
        assert 'Playing playlist "Rock"...' in result.output
        client.playlists_property.assert_called_once()
        client.clear.assert_called_once()
        client.play_playlist.assert_called_once_with("Rock")
        # The queue is cleared and the playlist played before the download starts
        # (the queue fetch is a property read, so "stop" -- the download's first
        # playback command -- is the anchor visible in method_calls)
        calls = [name for name, _, _ in client.method_calls]
        assert calls.index("clear") < calls.index("play_playlist") < calls.index("stop")
        run = tmp_path
        assert (run / "a.flac").read_bytes() == b"data"
        assert (run / "b.flac").read_bytes() == b"data"
        _, log = self._read_log(tmp_path)
        assert [t["status"] for t in log["tracks"]] == ["downloaded", "downloaded"]

    def test_download_unknown_playlist(self, runner: CliRunner, mocker: MockerFixture, tmp_path):
        """An unknown playlist name fails before touching the queue."""
        client = self._mock_services(mocker, [], [])

        result = runner.invoke(main, ["playlist", "download", "Nope", "-d", str(tmp_path)])

        assert result.exit_code == 1
        assert 'Playlist not found: "Nope"' in result.output
        client.clear.assert_not_called()
        client.play_playlist.assert_not_called()

    def test_download_no_check_playlist_name(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """--no-check-playlist-name skips the playlist lookup."""
        client = self._mock_services(mocker, self._queue_tracks()[:1], ["http://h/a.flac"])

        result = runner.invoke(
            main, [*self._BASE, "--no-check-playlist-name", "-d", str(tmp_path)]
        )

        assert result.exit_code == 0
        client.playlists_property.assert_not_called()
        client.play_playlist.assert_called_once_with("Rock")

    def test_download_requires_output_directory(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """The -d requirement of queue download applies."""
        client = self._mock_services(mocker, self._queue_tracks()[:1], ["http://h/a.flac"])

        result = runner.invoke(main, [*self._BASE])

        assert result.exit_code == 2
        assert "is required" in result.output
        # The playlist was already played when the requirement is checked
        client.play_playlist.assert_called_once_with("Rock")

    def test_download_prints_resulting_status(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """By default, the resulting playback status is printed after the run."""
        tracks = self._queue_tracks()[:1]
        states = [
            {"title": "Song A", "artist": "Artist", "album": "Album", "position": 0},
            {"title": "Song A", "artist": "StatusMarkerArtist"},
        ]
        self._mock_services(mocker, tracks, ["http://h/a.flac"], states=states)

        result = runner.invoke(
            main,
            [
                "playlist",
                "download",
                "Rock",
                "--no-create-download-manifest",
                "--no-add-cover-and-metadata",
                "-d",
                str(tmp_path),
            ],
        )

        assert result.exit_code == 0
        assert "StatusMarkerArtist" in result.output

    def test_download_config_subsection(self, runner: CliRunner, mocker: MockerFixture, tmp_path):
        """The playlist-download configuration subsection supplies directory and template."""
        out = tmp_path / "out"
        config = tmp_path / "volumito.yaml"
        config.write_text(
            "downloads:\n"
            "  playlist-download:\n"
            f"    output-directory: {out}\n"
            '    audio-file-name-template: "{title}.{extension}"\n'
        )
        self._mock_services(
            mocker,
            [{"title": "Song", "artist": "A", "album": "B"}],
            ["http://h/a.flac"],
            states=[{"title": "Song", "artist": "A", "album": "B", "position": 0}],
        )

        result = runner.invoke(main, ["-c", str(config), *self._BASE])

        assert result.exit_code == 0
        assert (out / "Song.flac").read_bytes() == b"data"

    def test_download_manifest_file_forwarded(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """--manifest-file is forwarded to the queue download logic."""
        self._mock_services(
            mocker,
            [{"title": "Song", "artist": "A", "album": "B"}],
            ["http://h/a.flac"],
            states=[{"title": "Song", "artist": "A", "album": "B", "position": 0}],
        )
        manifest = tmp_path / "reports" / "playlist.json"

        result = runner.invoke(
            main, [*self._BASE, "-d", str(tmp_path), "--manifest-file", str(manifest)]
        )

        assert result.exit_code == 0
        with open(manifest, encoding="utf-8") as manifest_handle:
            log = json.load(manifest_handle)
        assert log["tracks"][0]["status"] == "downloaded"
        assert not (tmp_path / "manifest.json").exists()

    def test_download_only_tracks_forwarded(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """--only-tracks is forwarded to the queue download logic."""
        tracks = [
            {"title": "Song A", "artist": "A", "album": "B"},
            {"title": "Song B", "artist": "A", "album": "B"},
        ]
        client = self._mock_services(
            mocker,
            tracks,
            ["http://h/b.flac"],
            states=[{**tracks[1], "position": 1}],
        )

        result = runner.invoke(main, [*self._BASE, "-d", str(tmp_path), "-T", "2"])

        assert result.exit_code == 0
        assert "Downloading 1 of 2 tracks" in result.output
        assert _played_positions(client) == [1, 0]

    def test_download_resume_keeps_downloaded_tracks(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """An existing manifest with all tracks downloaded skips every download."""
        client = self._mock_services(mocker, self._queue_tracks()[:1], [])
        mock_get = mocker.patch("volumito.cli.click_helpers.requests.get")
        manifest = tmp_path / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "first_download_date": "2026-01-01T00:00:00+00:00",
                    "updates": 1,
                    "tracks": [
                        {
                            "title": "Song A",
                            "artist": "Artist",
                            "album": "Album",
                            "status": "downloaded",
                            "output_file_path": str(tmp_path / "a.flac"),
                        }
                    ],
                }
            )
        )

        result = runner.invoke(main, [*self._BASE, "-d", str(tmp_path)])

        assert result.exit_code == 0
        assert "(kept)" in result.output
        mock_get.assert_not_called()
        # Nothing to download: the playback is left untouched
        client.stop.assert_not_called()
        with open(manifest, encoding="utf-8") as manifest_handle:
            log = json.load(manifest_handle)
        assert log["updates"] == 2

    def test_download_connection_error(self, runner: CliRunner, mocker: MockerFixture, tmp_path):
        """A connection failure while clearing the queue exits with an error."""
        client = self._mock_services(mocker, self._queue_tracks()[:1], ["http://h/a.flac"])
        client.clear.side_effect = VolumioConnectionError("no route")

        result = runner.invoke(main, [*self._BASE, "-d", str(tmp_path)])

        assert result.exit_code == 1
        assert "Connection error" in result.output

    def test_download_api_error(self, runner: CliRunner, mocker: MockerFixture, tmp_path):
        """An API failure while playing the playlist exits with an error."""
        client = self._mock_services(mocker, self._queue_tracks()[:1], ["http://h/a.flac"])
        client.play_playlist.side_effect = VolumioAPIError("nope")

        result = runner.invoke(main, [*self._BASE, "-d", str(tmp_path)])

        assert result.exit_code == 1
        assert "API error" in result.output


class TestQueueActions:
    """Test cases for the queue clear/repeat/randomize action commands."""

    @pytest.fixture
    def runner(self):
        """Create a CliRunner instance."""
        return CliRunner()

    def _mock_client(self, mocker: MockerFixture):
        """Mock VolumioRESTAPIClient with usable queue-action methods; patch out the sleep."""
        mock_client = mocker.Mock()
        mock_client.clear.return_value = {"response": "clearQueue"}
        mock_client.repeat.return_value = {"response": "repeat"}
        mock_client.randomize.return_value = {"response": "random"}
        # The resulting print is the playback status (getState), like the playback actions.
        _attach_property(mock_client, "state", return_value={
            "title": "Test Song",
            "artist": "StatusMarkerArtist",
            "status": "stop",
            "random": False,
            "repeat": True,
            "repeatSingle": False,
        })
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        mock_sleep = mocker.patch("volumito.cli.click_helpers.time.sleep")
        return mock_client, mock_sleep

    def test_clear_default_prints_resulting_status(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """By default, queue clear stops the playback and prints the resulting status."""
        mock_client, mock_sleep = self._mock_client(mocker)

        result = runner.invoke(main, ["queue", "clear"])

        assert result.exit_code == 0
        # The messages carry their level, on the standard error
        assert "[INFO] Command 'clear' executed successfully" in result.output
        assert "[INFO] Command 'stop' executed successfully" in result.output
        assert "StatusMarkerArtist" in result.output
        # The status settles on the first read, so no retry: one read plus the print
        assert "retrying" not in result.output
        mock_client.clear.assert_called_once()
        mock_client.stop.assert_called_once()
        assert mock_client.state_property.call_count == 2
        # One sleep between clear and stop, one before the settle read
        assert mock_sleep.call_args_list == [mocker.call(2.0), mocker.call(2.0)]

    def test_clear_no_print_resulting_status(self, runner: CliRunner, mocker: MockerFixture):
        """--no-print-resulting-status skips the status print, not the stop."""
        mock_client, mock_sleep = self._mock_client(mocker)

        result = runner.invoke(main, ["queue", "clear", "--no-print-resulting-status"])

        assert result.exit_code == 0
        assert "Command 'clear' executed successfully" in result.output
        assert "Command 'stop' executed successfully" in result.output
        assert "StatusMarkerArtist" not in result.output
        mock_client.clear.assert_called_once()
        mock_client.stop.assert_called_once()
        mock_client.state_property.assert_not_called()
        # The configured sleep separates the two calls
        mock_sleep.assert_called_once_with(2.0)

    def _mock_client_with_states(self, mocker: MockerFixture, statuses: list[str]):
        """Mock VolumioRESTAPIClient whose state reads walk the given statuses."""
        mock_client = mocker.Mock()
        mock_client.clear.return_value = {"response": "clearQueue"}
        mock_client.stop.return_value = {"response": "stop"}
        _attach_property(mock_client, "state", side_effect=[
            {"title": "Test Song", "artist": "StatusMarkerArtist", "status": status}
            for status in statuses
        ])
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        mock_sleep = mocker.patch("volumito.cli.click_helpers.time.sleep")
        return mock_client, mock_sleep

    def test_clear_retries_until_the_status_settles(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """queue clear re-reads the status until it leaves the unexpected state."""
        mock_client, mock_sleep = self._mock_client_with_states(
            mocker, ["play", "stop", "stop"]
        )

        result = runner.invoke(main, ["--verbose", "queue", "clear"])

        assert result.exit_code == 0
        assert (
            "Playback status 'play' does not match the expected 'stop', retrying (1/3)"
            in result.output
        )
        assert "Sending a stop as a workaround for a Volumio-side issue" in result.output
        assert "StatusMarkerArtist" in result.output
        # One unexpected read, one settled read, one read for the print
        assert mock_client.state_property.call_count == 3
        # One sleep between clear and stop, one before each of the first two reads
        assert mock_sleep.call_count == 3

    def test_clear_warns_when_the_status_never_settles(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """After the configured retries the warning fires and the status prints anyway."""
        mock_client, mock_sleep = self._mock_client_with_states(mocker, ["play"] * 5)

        result = runner.invoke(main, ["queue", "clear"])

        assert result.exit_code == 0
        assert (
            "[WARN] Playback status 'play' still does not match the expected 'stop' "
            "after 3 retries"
        ) in result.output
        # The retry messages stay at the debug level
        assert "retrying" not in result.output
        assert "StatusMarkerArtist" in result.output
        # One initial read, three retried reads, one read for the print
        assert mock_client.state_property.call_count == 5
        # One sleep between clear and stop, one before each of the first four reads
        assert mock_sleep.call_count == 5

    def test_clear_respects_the_retries_option(self, runner: CliRunner, mocker: MockerFixture):
        """--retries-on-unexpected-state bounds the re-reads."""
        mock_client, mock_sleep = self._mock_client_with_states(mocker, ["play"] * 3)

        result = runner.invoke(
            main, ["--retries-on-unexpected-state", "1", "queue", "clear"]
        )

        assert result.exit_code == 0
        assert (
            "Playback status 'play' still does not match the expected 'stop' "
            "after 1 retries"
        ) in result.output
        # One initial read, one retried read, one read for the print
        assert mock_client.state_property.call_count == 3
        # One sleep between clear and stop, one before each of the first two reads
        assert mock_sleep.call_count == 3

    def test_repeat_prints_the_mode(self, runner: CliRunner, mocker: MockerFixture):
        """queue repeat with no value prints the repeat mode, read off the state."""
        mock_client, mock_sleep = self._mock_client(mocker)
        _attach_property(
            mock_client, "state", return_value={"repeat": True, "repeatSingle": False}
        )

        result = runner.invoke(main, ["queue", "repeat"])

        assert result.exit_code == 0
        assert json.loads(result.output) == {"repeat": True, "repeatSingle": False}
        mock_client.repeat.assert_not_called()
        mock_sleep.assert_not_called()

    def test_repeat_prints_the_mode_as_a_table(self, runner: CliRunner, mocker: MockerFixture):
        """-F table heads the repeat mode fields."""
        mock_client, _ = self._mock_client(mocker)
        _attach_property(
            mock_client, "state", return_value={"repeat": False, "repeatSingle": True}
        )

        result = runner.invoke(main, ["queue", "repeat", "-F", "table"])

        assert result.exit_code == 0
        assert "Volumio Repeat Mode" in result.output
        assert f"{'Repeat':20}: False" in result.output
        assert f"{'Repeatsingle':20}: True" in result.output

    @pytest.mark.parametrize(
        ("spelling", "expected"),
        [
            ("on", True),
            ("true", True),
            ("yes", True),
            ("1", True),
            ("off", False),
            ("false", False),
            ("no", False),
            ("0", False),
        ],
    )
    def test_repeat_with_value(
        self, runner: CliRunner, mocker: MockerFixture, spelling, expected
    ):
        """queue repeat accepts on/true/yes/1 and off/false/no/0, then prints the mode."""
        mock_client, mock_sleep = self._mock_client(mocker)

        result = runner.invoke(main, ["queue", "repeat", spelling])

        label = "on" if expected else "off"
        assert result.exit_code == 0
        assert f"Command 'repeat {label}' executed successfully" in result.output
        assert '"repeat": true' in result.output
        assert "StatusMarkerArtist" not in result.output
        mock_client.repeat.assert_called_once_with(expected)
        mock_client.state_property.assert_called_once()
        mock_sleep.assert_not_called()

    def test_repeat_invalid_value(self, runner: CliRunner, mocker: MockerFixture):
        """queue repeat rejects a value that is not an accepted on/off spelling."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["queue", "repeat", "maybe"])

        assert result.exit_code == 2
        assert "must be one of" in result.output

    def test_randomize_prints_the_mode(self, runner: CliRunner, mocker: MockerFixture):
        """queue randomize with no value prints the random mode, read off the state."""
        mock_client, mock_sleep = self._mock_client(mocker)
        _attach_property(mock_client, "state", return_value={"random": True})

        result = runner.invoke(main, ["queue", "randomize"])

        assert result.exit_code == 0
        assert json.loads(result.output) == {"random": True}
        mock_client.randomize.assert_not_called()
        mock_sleep.assert_not_called()

    def test_randomize_prints_the_mode_as_a_table(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """-F table heads the random mode field."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["queue", "randomize", "-F", "table"])

        assert result.exit_code == 0
        assert "Volumio Random Mode" in result.output
        assert "Random" in result.output

    @pytest.mark.parametrize(
        ("spelling", "expected"),
        [
            ("on", True),
            ("true", True),
            ("yes", True),
            ("1", True),
            ("off", False),
            ("false", False),
            ("no", False),
            ("0", False),
        ],
    )
    def test_randomize_with_value(
        self, runner: CliRunner, mocker: MockerFixture, spelling, expected
    ):
        """queue randomize accepts on/true/yes/1 and off/false/no/0, then prints the mode."""
        mock_client, mock_sleep = self._mock_client(mocker)

        result = runner.invoke(main, ["queue", "randomize", spelling])

        label = "on" if expected else "off"
        assert result.exit_code == 0
        assert f"Command 'randomize {label}' executed successfully" in result.output
        assert '"random": false' in result.output
        assert "StatusMarkerArtist" not in result.output
        mock_client.randomize.assert_called_once_with(expected)
        mock_client.state_property.assert_called_once()
        mock_sleep.assert_not_called()

    def test_machine_readable_suppresses_success_message(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """In machine-readable mode the success message is suppressed."""
        mock_client, _ = self._mock_client(mocker)

        result = runner.invoke(
            main, ["--machine-readable", "queue", "clear", "--no-print-resulting-status"]
        )

        assert result.exit_code == 0
        assert "executed successfully" not in result.output
        mock_client.clear.assert_called_once()


class TestQueueNavigationFlags:
    """Test cases for the queue track has_previous/has_next commands."""

    @pytest.fixture
    def runner(self):
        """Create a CliRunner instance."""
        return CliRunner()

    def _mock_client(self, mocker: MockerFixture, name: str, value: object):
        """Mock VolumioRESTAPIClient whose named property returns value."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, name, return_value=value)
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        return mock_client

    @pytest.mark.parametrize("command", ["has_next", "has_previous"])
    @pytest.mark.parametrize("value", [True, False])
    def test_the_flag_is_printed(
        self, runner: CliRunner, mocker: MockerFixture, command: str, value: bool
    ):
        """queue track has_next/has_previous print the flag read from the client."""
        mock_client = self._mock_client(mocker, command, value)

        result = runner.invoke(main, ["queue", "track", command])

        assert result.exit_code == 0
        assert result.output.strip() == str(value)
        getattr(mock_client, f"{command}_property").assert_called_once_with()

    @pytest.mark.parametrize("command", ["has_next", "has_previous"])
    def test_the_flag_machine_readable(
        self, runner: CliRunner, mocker: MockerFixture, command: str
    ):
        """In machine-readable mode the flag is printed as a JSON boolean."""
        self._mock_client(mocker, command, True)

        result = runner.invoke(main, ["-m", "queue", "track", command])

        assert result.exit_code == 0
        assert result.output.strip() == "true"

    _QUEUE_STATUS = {
        "has_next": True,
        "has_previous": False,
        "length": 13,
        "position": 0,
        "track": {
            "position": 0,
            "title": "QS Song",
            "artist": "QS Artist",
            "status": "play",
        },
    }

    def test_queue_status_prints_the_short_view(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """By default queue status prints the SHORT fields (dotted track paths)."""
        self._mock_client(mocker, "queue_status", self._QUEUE_STATUS)

        result = runner.invoke(main, ["queue", "status"])

        assert result.exit_code == 0
        # The dotted fields rebuild their nesting; the missing track fields are omitted;
        # every position displays per the one-based convention
        assert json.loads(result.output) == {
            "track": {
                "position": 1,
                "title": "QS Song",
                "artist": "QS Artist",
            },
            "position": 1,
            "length": 13,
            "has_previous": False,
            "has_next": True,
        }

    def test_queue_status_all_fields(self, runner: CliRunner, mocker: MockerFixture):
        """-L ALL prints the whole composite, with the nested track dict."""
        self._mock_client(mocker, "queue_status", self._QUEUE_STATUS)

        result = runner.invoke(main, ["queue", "status", "-L", "ALL"])

        assert result.exit_code == 0
        # The pretty format displays every position per the one-based convention
        assert json.loads(result.output) == {
            **self._QUEUE_STATUS,
            "position": 1,
            "track": {**self._QUEUE_STATUS["track"], "position": 1},
        }

    def test_queue_status_explicit_fields(self, runner: CliRunner, mocker: MockerFixture):
        """An explicit field list mixes the queue keys and the dotted track paths."""
        self._mock_client(mocker, "queue_status", self._QUEUE_STATUS)

        result = runner.invoke(main, ["queue", "status", "-L", "length,track.title"])

        assert result.exit_code == 0
        assert json.loads(result.output) == {"length": 13, "track": {"title": "QS Song"}}

    def test_queue_status_format_table(self, runner: CliRunner, mocker: MockerFixture):
        """The table format shows the heading and the SHORT field labels."""
        self._mock_client(mocker, "queue_status", self._QUEUE_STATUS)

        result = runner.invoke(main, ["queue", "status", "-F", "table"])

        assert result.exit_code == 0
        assert "Volumio Queue Status" in result.output
        assert "Track Position      : 1" in result.output
        assert "Track Title         : QS Song" in result.output
        assert "Position            : 1" in result.output
        assert "Length              : 13" in result.output
        assert "Has Next            : True" in result.output

    def test_queue_status_raw(self, runner: CliRunner, mocker: MockerFixture):
        """The raw format prints the whole compact JSON object, ignoring the fields."""
        self._mock_client(mocker, "queue_status", self._QUEUE_STATUS)

        result = runner.invoke(main, ["-m", "queue", "status", "-F", "raw"])

        assert result.exit_code == 0
        assert json.loads(result.output) == self._QUEUE_STATUS
        assert "\n" not in result.output.strip()

    def test_queue_status_format_from_the_configuration(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """The queue-status subsection of the configuration sets the default format."""
        self._mock_client(mocker, "queue_status", self._QUEUE_STATUS)
        config = tmp_path / "volumito.yaml"
        config.write_text("output:\n  queue-status:\n    format: table\n")

        result = runner.invoke(main, ["-c", str(config), "queue", "status"])

        assert result.exit_code == 0
        assert "Volumio Queue Status" in result.output


class TestPlaybackExtras:
    """Test cases for playback infinity, playback sleep, and playback play --volatile."""

    _SLEEP_TIMER = {"enabled": True, "time": "1:30", "action": {"type": "stop"}}
    """An armed sleep timer, as a Volumio host answers it."""

    _WEBSOCKET = ["-C", "synchronous_websocket"]
    """The global option selecting the WebSocket API client the commands need."""

    @pytest.fixture
    def runner(self):
        """Create a CliRunner instance."""
        return CliRunner()

    def _mock_rest_client(self, mocker: MockerFixture):
        """Mock VolumioRESTAPIClient, the default client, answering the state reads."""
        mock_client = mocker.Mock()
        mock_client.logger = LOGGER
        _attach_property(mock_client, "state", return_value={"title": "Test Song"})
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        return mock_client

    def _mock_websocket_client(self, mocker: MockerFixture, sleep_timer=None):
        """Mock VolumioWebSocketClient answering the reads; patch out the sleep."""
        mock_client = mocker.Mock()
        mock_client.logger = LOGGER
        _attach_property(
            mock_client,
            "sleep_timer",
            return_value=self._SLEEP_TIMER if sleep_timer is None else sleep_timer,
        )
        _attach_property(
            mock_client, "infinity_playback", return_value={"available": True, "enabled": False}
        )
        _attach_property(
            mock_client,
            "state",
            return_value={"title": "Test Song", "artist": "StatusMarkerArtist"},
        )
        mocker.patch(
            "volumito.cli.click_helpers.VolumioWebSocketClient",
            return_value=mock_client,
        )
        mocker.patch("volumito.cli.click_helpers.time.sleep")
        return mock_client

    def test_sleep_prints_the_timer(self, runner: CliRunner, mocker: MockerFixture):
        """Without a value, the timer is printed with the delay left in minutes."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "playback", "sleep"])

        assert result.exit_code == 0
        assert json.loads(result.output) == {"enabled": True, "time": "1:30", "minutes": 90}
        mock_client.sleep_timer_property.assert_called_once()
        mock_client.set_sleep_timer.assert_not_called()

    def test_sleep_prints_a_disarmed_timer(self, runner: CliRunner, mocker: MockerFixture):
        """A timer without a readable delay prints no minutes."""
        self._mock_websocket_client(mocker, sleep_timer={"enabled": False})

        result = runner.invoke(main, [*self._WEBSOCKET, "playback", "sleep", "-F", "json"])

        assert result.exit_code == 0
        assert json.loads(result.output) == {"enabled": False, "time": None, "minutes": None}

    def test_sleep_prints_the_timer_raw(self, runner: CliRunner, mocker: MockerFixture):
        """-F raw prints the answer of the host as it is."""
        self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "playback", "sleep", "-F", "raw"])

        assert result.exit_code == 0
        assert json.loads(result.output) == self._SLEEP_TIMER

    def test_sleep_prints_the_timer_as_a_table(self, runner: CliRunner, mocker: MockerFixture):
        """-F table heads the timer fields."""
        self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "playback", "sleep", "-F", "table"])

        assert result.exit_code == 0
        assert "Volumio Sleep Timer" in result.output
        assert "Minutes" in result.output
        assert "90" in result.output

    def test_sleep_format_from_the_configuration(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """The playback-sleep subsection of the configuration sets the default format."""
        self._mock_websocket_client(mocker)
        config = tmp_path / "volumito.yaml"
        config.write_text("output:\n  playback-sleep:\n    format: table\n")

        result = runner.invoke(main, ["-c", str(config), *self._WEBSOCKET, "playback", "sleep"])

        assert result.exit_code == 0
        assert "Volumio Sleep Timer" in result.output

    @pytest.mark.parametrize(
        ("value", "delay", "label"),
        [
            ("30", timedelta(minutes=30), "sleep 30"),
            ("1:30", timedelta(hours=1, minutes=30), "sleep 90"),
            ("off", None, "sleep off"),
        ],
    )
    def test_sleep_arms_or_disarms_the_timer(
        self, runner: CliRunner, mocker: MockerFixture, value, delay, label
    ):
        """A value arms the timer with the delay, or disarms it, and prints the timer."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "playback", "sleep", value])

        assert result.exit_code == 0
        assert f"Command '{label}' executed successfully" in result.output
        assert '"minutes": 90' in result.output
        mock_client.set_sleep_timer.assert_called_once_with(delay)
        mock_client.sleep_timer_property.assert_called_once()

    def test_sleep_invalid_value(self, runner: CliRunner, mocker: MockerFixture):
        """A value that is not a delay nor off is a usage error."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "playback", "sleep", "tomorrow"])

        assert result.exit_code == 2
        assert "must be a number of minutes, a H:MM delay, or off" in result.output
        mock_client.set_sleep_timer.assert_not_called()

    def test_infinity_prints_the_setting(self, runner: CliRunner, mocker: MockerFixture):
        """Without a value, the infinity playback setting is printed."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "playback", "infinity"])

        assert result.exit_code == 0
        assert json.loads(result.output) == {"available": True, "enabled": False}
        mock_client.infinity_playback_property.assert_called_once()
        mock_client.set_infinity_playback.assert_not_called()

    def test_infinity_prints_the_setting_as_a_table(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """-F table heads the setting fields."""
        self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "playback", "infinity", "-F", "table"])

        assert result.exit_code == 0
        assert "Volumio Infinity Playback" in result.output
        assert "Available" in result.output

    @pytest.mark.parametrize(("spelling", "expected"), [("on", True), ("off", False)])
    def test_infinity_sets_the_mode(
        self, runner: CliRunner, mocker: MockerFixture, spelling, expected
    ):
        """A value turns infinity playback on or off, and prints the setting once set."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "playback", "infinity", spelling])

        assert result.exit_code == 0
        assert f"Command 'infinity {spelling}' executed successfully" in result.output
        assert '"enabled": false' in result.output
        mock_client.set_infinity_playback.assert_called_once_with(expected)
        mock_client.infinity_playback_property.assert_called_once()

    def test_infinity_invalid_value(self, runner: CliRunner, mocker: MockerFixture):
        """A value that is not an on/off spelling is a usage error."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "playback", "infinity", "maybe"])

        assert result.exit_code == 2
        assert "must be one of" in result.output
        mock_client.set_infinity_playback.assert_not_called()

    def test_play_volatile(self, runner: CliRunner, mocker: MockerFixture):
        """--volatile starts the volatile source at the 0-based position."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main,
            [*self._WEBSOCKET, "playback", "play", "3", "--volatile",
             "--no-print-resulting-status"],
        )

        assert result.exit_code == 0
        assert "Command 'play volatile' executed successfully" in result.output
        mock_client.play_volatile.assert_called_once_with(2)
        mock_client.play.assert_not_called()

    def test_play_volatile_without_a_position(self, runner: CliRunner, mocker: MockerFixture):
        """--volatile needs the position to start at."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "playback", "play", "--volatile"])

        assert result.exit_code == 2
        assert "Expected a POSITION argument together with --volatile" in result.output
        mock_client.play_volatile.assert_not_called()
        mock_client.play.assert_not_called()

    @pytest.mark.parametrize(
        ("arguments", "operation"),
        [
            (["infinity"], "the playback extras"),
            (["infinity", "on"], "the playback extras"),
            (["play", "1", "--volatile", "--no-print-resulting-status"], "the playback extras"),
            (["sleep"], "the sleep timer and the alarms"),
            (["sleep", "30"], "the sleep timer and the alarms"),
        ],
    )
    def test_a_rest_client_refuses(
        self, runner: CliRunner, mocker: MockerFixture, arguments, operation
    ):
        """With the default REST API client, the commands fail naming the remedies."""
        self._mock_rest_client(mocker)

        result = runner.invoke(main, ["playback", *arguments])

        assert result.exit_code == 1
        assert (
            f"API client error: The Synchronous REST API client does not offer {operation}: "
            "use --api-client synchronous_websocket or asynchronous_websocket, "
            "or --allow-fallback-to-websocket-api"
        ) in result.output

    def test_a_rest_client_falls_back_when_allowed(self, runner: CliRunner, mocker: MockerFixture):
        """With the switch, the REST API client serves the command through a WebSocket one."""
        rest = self._mock_rest_client(mocker)
        websocket = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, ["--allow-fallback-to-websocket-api", "playback", "sleep", "off"]
        )

        assert result.exit_code == 0
        assert (
            "Falling back to the WebSocket API client for the sleep timer and the alarms"
        ) in result.output
        websocket.set_sleep_timer.assert_called_once_with(None)
        websocket.disconnect.assert_called_once_with()
        rest.close.assert_called_once_with()


class TestQueueTrackGroup:
    """Test cases for the queue track group and its top-level synonym."""

    @pytest.fixture
    def runner(self):
        """Create a CliRunner instance."""
        return CliRunner()

    def _mock_client(self, mocker: MockerFixture):
        """Mock VolumioRESTAPIClient answering the state reads."""
        mock_client = mocker.Mock()
        _attach_property(
            mock_client, "state", return_value={"title": "Test Song", "artist": "Test Artist"}
        )
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        return mock_client

    @pytest.mark.parametrize("path", [["queue", "track"], ["track"]])
    def test_the_synonym_reaches_the_same_command(self, runner: CliRunner, mocker, path):
        """The top-level track group stands in for queue track."""
        self._mock_client(mocker)

        result = runner.invoke(main, [*path, "info", "-F", "json"])

        assert result.exit_code == 0
        assert json.loads(result.output)["title"] == "Test Song"

    @pytest.mark.parametrize("command", ["has_next", "has_previous"])
    def test_the_predicates_left_the_queue_group(self, runner: CliRunner, command: str):
        """queue has_next and queue has_previous no longer exist, without synonyms."""
        result = runner.invoke(main, ["-i", "queue", command])

        assert result.exit_code == 2
        assert f"No such command '{command}'" in result.output

    def test_the_command_list_shows_the_group_under_queue_and_at_the_top(
        self, runner: CliRunner
    ):
        """The tree lists the track group under queue and, as the synonym, at the top level."""
        result = runner.invoke(main, ["-i", "command", "list"])

        assert result.exit_code == 0
        lines = result.output.splitlines()
        assert "        track" in lines
        assert "            has_next" in lines
        assert "    track" in lines
        assert "        has_next" in lines


class TestQueueReplace:
    """Test cases for the queue replace command."""

    URI = "albums://Paolo%20Conte/Aguaplano"
    """A URI of the kind a browse or a search prints."""

    @pytest.fixture
    def runner(self):
        """Create a CliRunner instance."""
        return CliRunner()

    def _mock_client(self, mocker: MockerFixture):
        """Mock VolumioRESTAPIClient with usable replace methods; patch out the sleep."""
        mock_client = mocker.Mock()
        mock_client.add_to_queue.return_value = {"response": "success"}
        mock_client.clear.return_value = {"response": "clearQueue"}
        mock_client.replace_queue_and_play.return_value = {"response": "success"}
        _attach_property(mock_client, "state", return_value={
            "title": "Test Song",
            "artist": "StatusMarkerArtist",
        })
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        mock_sleep = mocker.patch("volumito.cli.click_helpers.time.sleep")
        return mock_client, mock_sleep

    def test_replaces_and_plays_the_first_item(self, runner: CliRunner, mocker: MockerFixture):
        """Without a position the first item plays, and the status is printed."""
        mock_client, mock_sleep = self._mock_client(mocker)

        result = runner.invoke(main, ["queue", "replace", self.URI])

        assert result.exit_code == 0
        assert "Command 'replace' executed successfully" in result.output
        assert "StatusMarkerArtist" in result.output
        mock_client.replace_queue_and_play.assert_called_once_with(self.URI, 0)
        mock_sleep.assert_called_once_with(2.0)

    @pytest.mark.parametrize(("position", "index"), [("1", 0), ("3", 2)])
    def test_the_position_starting_at_one(
        self, runner: CliRunner, mocker: MockerFixture, position, index
    ):
        """The one-based position of the user reaches the client as a 0-based index."""
        mock_client, _ = self._mock_client(mocker)

        result = runner.invoke(
            main,
            ["queue", "replace", self.URI, "-p", position, "--no-print-resulting-status"],
        )

        assert result.exit_code == 0
        mock_client.replace_queue_and_play.assert_called_once_with(self.URI, index)

    def test_the_position_starting_at_zero(self, runner: CliRunner, mocker: MockerFixture):
        """Under the zero-based convention the position is the index."""
        mock_client, _ = self._mock_client(mocker)

        result = runner.invoke(
            main,
            [
                "--position-starting-at-zero",
                "queue",
                "replace",
                self.URI,
                "-p",
                "0",
                "--no-print-resulting-status",
            ],
        )

        assert result.exit_code == 0
        mock_client.replace_queue_and_play.assert_called_once_with(self.URI, 0)

    def test_a_position_below_the_minimum(self, runner: CliRunner, mocker: MockerFixture):
        """A position below the convention minimum is a usage error."""
        mock_client, _ = self._mock_client(mocker)

        result = runner.invoke(main, ["queue", "replace", self.URI, "-p", "0"])

        assert result.exit_code == 2
        assert "position must be 1 or greater" in result.output
        mock_client.replace_queue_and_play.assert_not_called()

    def _mock_websocket_client(self, mocker: MockerFixture):
        """Mock VolumioWebSocketClient, the one the cue track replacement needs."""
        mock_client = mocker.Mock()
        mock_client.logger = LOGGER
        mocker.patch(
            "volumito.cli.click_helpers.VolumioWebSocketClient",
            return_value=mock_client,
        )
        return mock_client

    @pytest.mark.parametrize(("options", "service"), [([], None), (["--service", "mpd"], "mpd")])
    def test_replaces_with_a_cue_track(
        self, runner: CliRunner, mocker: MockerFixture, options, service
    ):
        """--cue-track replaces the queue with one track of the cue sheet."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main,
            ["-C", "sw", "queue", "replace", self.URI, "--cue-track", "3", *options,
             "--no-print-resulting-status"],
        )

        assert result.exit_code == 0
        assert "Command 'replace' executed successfully" in result.output
        mock_client.replace_queue_with_cue_track.assert_called_once_with(self.URI, 3, service)
        mock_client.replace_queue_and_play.assert_not_called()

    @pytest.mark.parametrize("options", [["-p", "1"], ["--no-play"]])
    def test_a_cue_track_with_a_position_or_without_playing(
        self, runner: CliRunner, mocker: MockerFixture, options
    ):
        """A cue track always plays alone: a position or --no-play is a usage error."""
        mock_client, _ = self._mock_client(mocker)

        result = runner.invoke(main, ["queue", "replace", self.URI, "--cue-track", "3", *options])

        assert result.exit_code == 2
        assert "Expected the --cue-track option only together with --play" in result.output
        mock_client.replace_queue_and_play.assert_not_called()

    def test_a_service_without_a_cue_track(self, runner: CliRunner, mocker: MockerFixture):
        """--service only qualifies a cue track."""
        mock_client, _ = self._mock_client(mocker)

        result = runner.invoke(main, ["queue", "replace", self.URI, "--service", "mpd"])

        assert result.exit_code == 2
        assert "Expected the --service option only together with --cue-track" in result.output
        mock_client.replace_queue_and_play.assert_not_called()

    def test_a_rest_client_refuses_a_cue_track(self, runner: CliRunner, mocker: MockerFixture):
        """Without the WebSocket API, a cue track replacement fails naming the remedies."""
        mock_client, _ = self._mock_client(mocker)

        result = runner.invoke(main, ["queue", "replace", self.URI, "--cue-track", "3"])

        assert result.exit_code == 1
        assert (
            "API client error: The Synchronous REST API client does not offer the queue edits: "
            "use --api-client synchronous_websocket or asynchronous_websocket, "
            "or --allow-fallback-to-websocket-api"
        ) in result.output
        mock_client.replace_queue_and_play.assert_not_called()

    def test_no_play_replaces_without_playing(self, runner: CliRunner, mocker: MockerFixture):
        """--no-play clears the queue and adds the URI, never replaceAndPlay."""
        mock_client, mock_sleep = self._mock_client(mocker)

        result = runner.invoke(
            main, ["queue", "replace", self.URI, "--no-play", "--no-print-resulting-status"]
        )

        assert result.exit_code == 0
        assert "Command 'clear' executed successfully" in result.output
        assert "Command 'add' executed successfully" in result.output
        mock_client.clear.assert_called_once()
        mock_client.add_to_queue.assert_called_once_with(self.URI)
        mock_client.replace_queue_and_play.assert_not_called()
        # The configured sleep separates the two calls
        mock_sleep.assert_called_once_with(2.0)

    def test_no_play_with_a_position(self, runner: CliRunner, mocker: MockerFixture):
        """Asking for a position to play while asking not to play is a usage error."""
        mock_client, _ = self._mock_client(mocker)

        result = runner.invoke(main, ["queue", "replace", self.URI, "--no-play", "-p", "2"])

        assert result.exit_code == 2
        assert "only together with --play" in result.output
        mock_client.clear.assert_not_called()
        mock_client.add_to_queue.assert_not_called()
        mock_client.replace_queue_and_play.assert_not_called()

    def test_the_slow_endpoints_timeout_reaches_the_client(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """The global slow-endpoints timeout option is what the client is built with."""
        mock_client = mocker.Mock()
        mock_client.replace_queue_and_play.return_value = {"response": "success"}
        mock_class = mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient", return_value=mock_client
        )

        result = runner.invoke(
            main,
            [
                "--rest-api-timeout-slow-endpoints",
                "120",
                "queue",
                "replace",
                self.URI,
                "--no-print-resulting-status",
            ],
        )

        assert result.exit_code == 0
        assert mock_class.call_args.kwargs == {
            "timeout": 5.0,
            "timeout_slow_endpoints": 120.0,
            "logger": LOGGER,
        }

    def test_a_connection_error(self, runner: CliRunner, mocker: MockerFixture):
        """A host that cannot be reached exits 1."""
        mock_client = mocker.Mock()
        mock_client.replace_queue_and_play.side_effect = VolumioConnectionError(
            "Connection failed"
        )
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["queue", "replace", self.URI])

        assert result.exit_code == 1
        assert "Connection error" in result.output


class TestQueueEditing:
    """Test cases for the queue add/consume/move/remove/save commands."""

    URI = "albums://Paolo%20Conte/Aguaplano"
    """A URI of the kind a browse or a search prints."""

    _NO_STATUS = ["--no-print-resulting-status"]
    """The option skipping the resulting status print."""

    _REFUSAL = (
        "API client error: The Synchronous REST API client does not offer the queue edits: "
        "use --api-client synchronous_websocket or asynchronous_websocket, "
        "or --allow-fallback-to-websocket-api"
    )
    """The error of a REST API client asked for a queue edit, without the fallback."""

    _WEBSOCKET = ["-C", "synchronous_websocket"]
    """The global option selecting the WebSocket API client the commands need."""

    @pytest.fixture
    def runner(self):
        """Create a CliRunner instance."""
        return CliRunner()

    def _mock_rest_client(self, mocker: MockerFixture):
        """Mock VolumioRESTAPIClient, the default client, answering the state reads."""
        mock_client = mocker.Mock()
        mock_client.logger = LOGGER
        _attach_property(
            mock_client, "state", return_value={"title": "Test Song", "consume": False}
        )
        _attach_property(mock_client, "playlists", return_value=["Rock"])
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        return mock_client

    def _mock_websocket_client(self, mocker: MockerFixture, consume: bool | None = False):
        """Mock VolumioWebSocketClient answering the state reads; patch out the sleep."""
        mock_client = mocker.Mock()
        mock_client.logger = LOGGER
        _attach_property(
            mock_client,
            "state",
            return_value={
                "title": "Test Song",
                "artist": "StatusMarkerArtist",
                "consume": consume,
            },
        )
        mocker.patch(
            "volumito.cli.click_helpers.VolumioWebSocketClient",
            return_value=mock_client,
        )
        mocker.patch("volumito.cli.click_helpers.time.sleep")
        return mock_client

    def test_add(self, runner: CliRunner, mocker: MockerFixture):
        """queue add appends the content of the URI, leaving the playback alone."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "queue", "add", self.URI, *self._NO_STATUS]
        )

        assert result.exit_code == 0
        assert "Command 'add' executed successfully" in result.output
        mock_client.add_to_queue.assert_called_once_with(self.URI)
        mock_client.add_and_play.assert_not_called()
        mock_client.state_property.assert_not_called()

    def test_add_prints_the_resulting_status(self, runner: CliRunner, mocker: MockerFixture):
        """By default the resulting playback status is printed."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "queue", "add", self.URI])

        assert result.exit_code == 0
        assert "StatusMarkerArtist" in result.output
        mock_client.add_to_queue.assert_called_once_with(self.URI)
        mock_client.state_property.assert_called_once()

    def test_add_and_play(self, runner: CliRunner, mocker: MockerFixture):
        """--play appends the content and starts playing it."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "queue", "add", self.URI, "--play", *self._NO_STATUS]
        )

        assert result.exit_code == 0
        mock_client.add_and_play.assert_called_once_with(self.URI)
        mock_client.add_to_queue.assert_not_called()

    @pytest.mark.parametrize(
        ("options", "title", "album"),
        [([], None, None), (["--title", "T", "--album", "A"], "T", "A")],
    )
    def test_add_next(self, runner: CliRunner, mocker: MockerFixture, options, title, album):
        """--next queues the URI as one item after the current track, with its details."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main,
            [*self._WEBSOCKET, "queue", "add", self.URI, "--next", *options, *self._NO_STATUS],
        )

        assert result.exit_code == 0
        mock_client.play_next.assert_called_once_with(self.URI, title, album)

    @pytest.mark.parametrize(("options", "service"), [([], None), (["--service", "mpd"], "mpd")])
    def test_add_cue_track(self, runner: CliRunner, mocker: MockerFixture, options, service):
        """--cue-track queues one track of the cue sheet, of the given service."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main,
            [*self._WEBSOCKET, "queue", "add", self.URI, "--cue-track", "3", *options,
             *self._NO_STATUS],
        )

        assert result.exit_code == 0
        mock_client.add_cue_track.assert_called_once_with(self.URI, 3, service)

    def test_add_by_uid(self, runner: CliRunner, mocker: MockerFixture):
        """--by-uid reads every argument as a local library identifier."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "queue", "add", "12", "34", "--by-uid", *self._NO_STATUS]
        )

        assert result.exit_code == 0
        mock_client.add_uids_to_queue.assert_called_once_with(["12", "34"])

    def test_add_several_uris(self, runner: CliRunner, mocker: MockerFixture):
        """Without --by-uid, a single URI is expected."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "queue", "add", self.URI, self.URI])

        assert result.exit_code == 2
        assert "Expected a single URI argument" in result.output
        mock_client.add_to_queue.assert_not_called()

    @pytest.mark.parametrize(
        "options",
        [
            ["--play", "--next"],
            ["--play", "--cue-track", "1"],
            ["--next", "--by-uid"],
            ["--cue-track", "1", "--by-uid"],
        ],
    )
    def test_add_in_two_ways(self, runner: CliRunner, mocker: MockerFixture, options):
        """The ways of adding are mutually exclusive."""
        self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "queue", "add", self.URI, *options])

        assert result.exit_code == 2
        assert "Expected at most one of the --by-uid, --cue-track, --next, and --play" in (
            result.output
        )

    @pytest.mark.parametrize("options", [["--title", "T"], ["--album", "A"]])
    def test_add_details_without_next(self, runner: CliRunner, mocker: MockerFixture, options):
        """The item details only qualify --next."""
        self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "queue", "add", self.URI, *options])

        assert result.exit_code == 2
        assert "Expected the --album and --title options only together with --next" in (
            result.output
        )

    def test_add_service_without_cue_track(self, runner: CliRunner, mocker: MockerFixture):
        """--service only qualifies a cue track."""
        self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "queue", "add", self.URI, "--service", "mpd"]
        )

        assert result.exit_code == 2
        assert "Expected the --service option only together with --cue-track" in result.output

    @pytest.mark.parametrize(("spelling", "expected"), [("on", True), ("off", False)])
    def test_consume_with_value(
        self, runner: CliRunner, mocker: MockerFixture, spelling, expected
    ):
        """queue consume on/off sets the mode, then prints it off the state."""
        mock_client = self._mock_websocket_client(mocker, consume=expected)

        result = runner.invoke(main, [*self._WEBSOCKET, "queue", "consume", spelling])

        assert result.exit_code == 0
        assert f"Command 'consume {spelling}' executed successfully" in result.output
        assert f'"consume": {json.dumps(expected)}' in result.output
        assert "StatusMarkerArtist" not in result.output
        mock_client.consume.assert_called_once_with(expected)
        mock_client.state_property.assert_called_once()

    @pytest.mark.parametrize("current", [True, False, None])
    def test_consume_prints_the_mode(
        self, runner: CliRunner, mocker: MockerFixture, current
    ):
        """Without a value, the mode read from the state is printed, not inverted."""
        mock_client = self._mock_websocket_client(mocker, consume=current)

        result = runner.invoke(main, [*self._WEBSOCKET, "queue", "consume"])

        assert result.exit_code == 0
        assert json.loads(result.output) == {"consume": current}
        mock_client.consume.assert_not_called()
        mock_client.state_property.assert_called_once()

    def test_consume_prints_the_mode_with_a_rest_client(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """Printing the mode reads the state, which the REST API client offers too."""
        mock_client = self._mock_rest_client(mocker)

        result = runner.invoke(main, ["queue", "consume", "-F", "table"])

        assert result.exit_code == 0
        assert "Volumio Consume Mode" in result.output
        assert f"{'Consume':20}: False" in result.output
        mock_client.consume.assert_not_called()

    def test_move_positions_starting_at_one(self, runner: CliRunner, mocker: MockerFixture):
        """The one-based positions of the user reach the client 0-based."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, [*self._WEBSOCKET, "queue", "move", "3", "1", *self._NO_STATUS]
        )

        assert result.exit_code == 0
        assert "Command 'move' executed successfully" in result.output
        mock_client.move_in_queue.assert_called_once_with(2, 0)

    def test_move_positions_starting_at_zero(self, runner: CliRunner, mocker: MockerFixture):
        """Under the zero-based convention the positions are the indexes."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main,
            ["--position-starting-at-zero", *self._WEBSOCKET, "queue", "move", "3", "0",
             *self._NO_STATUS],
        )

        assert result.exit_code == 0
        mock_client.move_in_queue.assert_called_once_with(3, 0)

    @pytest.mark.parametrize(
        ("arguments", "name"), [(["0", "1"], "source"), (["1", "0"], "target")]
    )
    def test_move_below_the_minimum(
        self, runner: CliRunner, mocker: MockerFixture, arguments, name
    ):
        """A position below the convention minimum is a usage error naming it."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "queue", "move", *arguments])

        assert result.exit_code == 2
        assert f"{name} must be 1 or greater, got 0" in result.output
        mock_client.move_in_queue.assert_not_called()

    def test_remove(self, runner: CliRunner, mocker: MockerFixture):
        """The one-based position of the user reaches the client 0-based."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "queue", "remove", "2", *self._NO_STATUS])

        assert result.exit_code == 0
        assert "Command 'remove' executed successfully" in result.output
        mock_client.remove_from_queue.assert_called_once_with(1)

    def test_remove_below_the_minimum(self, runner: CliRunner, mocker: MockerFixture):
        """A position below the convention minimum is a usage error."""
        mock_client = self._mock_websocket_client(mocker)

        result = runner.invoke(main, [*self._WEBSOCKET, "queue", "remove", "0"])

        assert result.exit_code == 2
        assert "position must be 1 or greater, got 0" in result.output
        mock_client.remove_from_queue.assert_not_called()

    def test_save(self, runner: CliRunner, mocker: MockerFixture):
        """queue save stores the queue under a name not in use, after checking it."""
        mock_client = self._mock_websocket_client(mocker)
        _attach_property(mock_client, "playlists", return_value=["Rock", "Jazz"])

        result = runner.invoke(main, [*self._WEBSOCKET, "queue", "save", "My Queue"])

        assert result.exit_code == 0
        assert "Command 'save' executed successfully" in result.output
        mock_client.playlists_property.assert_called_once()
        mock_client.save_queue_as_playlist.assert_called_once_with("My Queue")

    def test_save_refuses_an_existing_playlist(self, runner: CliRunner, mocker: MockerFixture):
        """A name already in use exits 1, naming the overriding option, without saving."""
        mock_client = self._mock_websocket_client(mocker)
        _attach_property(mock_client, "playlists", return_value=["Rock", "My Queue"])

        result = runner.invoke(main, [*self._WEBSOCKET, "queue", "save", "My Queue"])

        assert result.exit_code == 1
        assert (
            'Playlist already exists: "My Queue" '
            "(use --overwrite-existing-playlist to overwrite)"
        ) in result.output
        mock_client.save_queue_as_playlist.assert_not_called()

    def test_save_overwrites_an_existing_playlist_when_asked(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """With --overwrite-existing-playlist, the name is not checked and the queue is saved."""
        mock_client = self._mock_websocket_client(mocker)
        _attach_property(mock_client, "playlists", return_value=["Rock", "My Queue"])

        result = runner.invoke(
            main,
            [*self._WEBSOCKET, "queue", "save", "My Queue", "--overwrite-existing-playlist"],
        )

        assert result.exit_code == 0
        assert "Command 'save' executed successfully" in result.output
        mock_client.playlists_property.assert_not_called()
        mock_client.save_queue_as_playlist.assert_called_once_with("My Queue")

    def test_save_overwrite_from_the_configuration_file(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """The miscellaneous.overwrite-existing-playlist key turns the option on."""
        mock_client = self._mock_websocket_client(mocker)
        _attach_property(mock_client, "playlists", return_value=["My Queue"])
        config = tmp_path / "volumito.yaml"
        config.write_text("miscellaneous:\n  overwrite-existing-playlist: true\n")

        result = runner.invoke(
            main, ["-c", str(config), *self._WEBSOCKET, "queue", "save", "My Queue"]
        )

        assert result.exit_code == 0
        mock_client.playlists_property.assert_not_called()
        mock_client.save_queue_as_playlist.assert_called_once_with("My Queue")

    def test_save_fails_when_the_playlists_cannot_be_read(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """An API error while checking the name exits 1, without saving."""
        mock_client = self._mock_websocket_client(mocker)
        _attach_property(mock_client, "playlists", side_effect=VolumioAPIError("Bad payload"))

        result = runner.invoke(main, [*self._WEBSOCKET, "queue", "save", "My Queue"])

        assert result.exit_code == 1
        assert "API error" in result.output
        mock_client.save_queue_as_playlist.assert_not_called()

    def test_the_plain_add_works_with_a_rest_client(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """Adding without options is the one queue edit the REST API offers too."""
        mock_client = self._mock_rest_client(mocker)

        result = runner.invoke(main, ["queue", "add", self.URI, *self._NO_STATUS])

        assert result.exit_code == 0
        assert "Command 'add' executed successfully" in result.output
        mock_client.add_to_queue.assert_called_once_with(self.URI)

    @pytest.mark.parametrize(
        "arguments",
        [
            ["add", URI, "--play", "--no-print-resulting-status"],
            ["add", URI, "--next", "--no-print-resulting-status"],
            ["add", URI, "--cue-track", "1", "--no-print-resulting-status"],
            ["add", "12", "--by-uid", "--no-print-resulting-status"],
            ["consume", "on"],
            ["move", "1", "2", "--no-print-resulting-status"],
            ["remove", "1", "--no-print-resulting-status"],
            ["save", "name"],
        ],
    )
    def test_a_rest_client_refuses(self, runner: CliRunner, mocker: MockerFixture, arguments):
        """With the default REST API client, the commands fail naming the remedies."""
        self._mock_rest_client(mocker)

        result = runner.invoke(main, ["queue", *arguments])

        assert result.exit_code == 1
        assert self._REFUSAL in result.output

    def test_a_rest_client_falls_back_when_allowed(self, runner: CliRunner, mocker: MockerFixture):
        """With the switch, the REST API client serves the command through a WebSocket one."""
        rest = self._mock_rest_client(mocker)
        websocket = self._mock_websocket_client(mocker)

        result = runner.invoke(
            main, ["--allow-fallback-to-websocket-api", "queue", "save", "My Queue"]
        )

        assert result.exit_code == 0
        assert "Falling back to the WebSocket API client for the queue edits" in result.output
        rest.playlists_property.assert_called_once()
        websocket.save_queue_as_playlist.assert_called_once_with("My Queue")
        websocket.connect.assert_called_once_with()
        websocket.disconnect.assert_called_once_with()
        rest.close.assert_called_once_with()



class TestSeekCommand:
    """Test cases for the playback seek command."""

    @pytest.fixture
    def runner(self):
        """Create a CliRunner instance."""
        return CliRunner()

    def _mock_client(self, mocker: MockerFixture, state=None):
        """Mock VolumioRESTAPIClient with usable seek and state properties; patch the sleep."""
        mock_client = mocker.Mock()
        state_value = (
            {"seek": 252345, "duration": 4000, "artist": "StatusMarkerArtist"}
            if state is None
            else state
        )
        _attach_property(mock_client, "seek")
        _attach_property(mock_client, "state", return_value=state_value)
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        mock_sleep = mocker.patch("volumito.cli.click_helpers.time.sleep")
        return mock_client, mock_sleep

    def test_help(self, runner: CliRunner):
        """playback seek documents its accepted values."""
        result = runner.invoke(main, ["playback", "seek", "--help"])

        assert result.exit_code == 0
        assert "VALUE" in result.output
        assert "plus" in result.output

    def test_no_value_prints_the_position(self, runner: CliRunner, mocker: MockerFixture):
        """Without a value, the current position is printed as HH:MM:SS.mmm."""
        mock_client, _ = self._mock_client(mocker)

        result = runner.invoke(main, ["playback", "seek"])

        assert result.exit_code == 0
        assert result.output.strip() == "00:04:12.345"
        # No seek command is sent when only querying the current position
        mock_client.seek_property.assert_not_called()

    def test_no_value_machine_readable(self, runner: CliRunner, mocker: MockerFixture):
        """In machine-readable mode the position is printed as a quoted string."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["-m", "playback", "seek"])

        assert result.exit_code == 0
        assert result.output.strip() == '"00:04:12.345"'

    def test_no_value_without_seek_in_state(self, runner: CliRunner, mocker: MockerFixture):
        """A state carrying no integer seek exits 1."""
        self._mock_client(mocker, state={"title": "Test Song"})

        result = runner.invoke(main, ["playback", "seek"])

        assert result.exit_code == 1
        assert "No seek position found" in result.output

    def test_no_value_without_seek_in_state_machine_readable(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """The missing-seek error is silent in machine-readable mode."""
        self._mock_client(mocker, state={"title": "Test Song"})

        result = runner.invoke(main, ["-m", "playback", "seek"])

        assert result.exit_code == 1
        assert result.output == ""

    @pytest.mark.parametrize(
        ("spelling", "method"),
        [
            ("plus", "seek_forward"),
            ("increase", "seek_forward"),
            ("up", "seek_forward"),
            ("forward", "seek_forward"),
            ("minus", "seek_backward"),
            ("decrease", "seek_backward"),
            ("down", "seek_backward"),
            ("backward", "seek_backward"),
        ],
    )
    def test_relative_values(
        self, runner: CliRunner, mocker: MockerFixture, spelling: str, method: str
    ):
        """The relative aliases dispatch to the dedicated client methods."""
        mock_client, _ = self._mock_client(mocker)

        result = runner.invoke(
            main, ["playback", "seek", spelling, "--no-print-resulting-status"]
        )

        assert result.exit_code == 0
        getattr(mock_client, method).assert_called_once_with()
        mock_client.seek_property.assert_not_called()

    @pytest.mark.parametrize(
        ("value", "expected"),
        [("42", 42), ("0", 0), ("04:12", 252), ("01:04:12", 3852)],
    )
    def test_absolute_values(
        self, runner: CliRunner, mocker: MockerFixture, value: str, expected: int
    ):
        """Seconds and colon times reach the client as a number of seconds."""
        mock_client, _ = self._mock_client(mocker)

        result = runner.invoke(
            main, ["playback", "seek", value, "--no-print-resulting-status"]
        )

        assert result.exit_code == 0
        mock_client.seek_property.assert_called_once_with(expected)

    @pytest.mark.parametrize("value", ["-1", "bogus", "1:2:3:4", "00:99", "12s"])
    def test_invalid_values(self, runner: CliRunner, mocker: MockerFixture, value: str):
        """An unparsable or negative value is a usage error."""
        mock_client, _ = self._mock_client(mocker)

        result = runner.invoke(main, ["playback", "seek", "--", value])

        assert result.exit_code != 0
        mock_client.seek_property.assert_not_called()

    def test_default_prints_resulting_status(self, runner: CliRunner, mocker: MockerFixture):
        """By default, playback seek waits and prints the resulting playback status."""
        mock_client, mock_sleep = self._mock_client(mocker)

        result = runner.invoke(main, ["playback", "seek", "42", "--no-check-seek-position"])

        assert result.exit_code == 0
        mock_sleep.assert_called_once_with(2.0)
        mock_client.state_property.assert_called_once()
        assert "StatusMarkerArtist" in result.output

    def test_no_print_resulting_status(self, runner: CliRunner, mocker: MockerFixture):
        """With --no-print-resulting-status the status is not fetched."""
        mock_client, mock_sleep = self._mock_client(mocker)

        result = runner.invoke(
            main,
            [
                "playback",
                "seek",
                "42",
                "--no-check-seek-position",
                "--no-print-resulting-status",
            ],
        )

        assert result.exit_code == 0
        mock_sleep.assert_not_called()
        mock_client.state_property.assert_not_called()

    def test_position_within_the_duration(self, runner: CliRunner, mocker: MockerFixture):
        """A position inside the track duration is checked and sent."""
        mock_client, _ = self._mock_client(mocker, state={"duration": 300})

        result = runner.invoke(
            main, ["playback", "seek", "42", "--no-print-resulting-status"]
        )

        assert result.exit_code == 0
        mock_client.state_property.assert_called_once()
        mock_client.seek_property.assert_called_once_with(42)

    def test_position_equal_to_the_duration(self, runner: CliRunner, mocker: MockerFixture):
        """A position exactly at the end of the track is accepted."""
        mock_client, _ = self._mock_client(mocker, state={"duration": 300})

        result = runner.invoke(
            main, ["playback", "seek", "300", "--no-print-resulting-status"]
        )

        assert result.exit_code == 0
        mock_client.seek_property.assert_called_once_with(300)

    def test_position_past_the_duration(self, runner: CliRunner, mocker: MockerFixture):
        """A position past the track duration exits 1 without sending the command."""
        mock_client, _ = self._mock_client(mocker, state={"duration": 300})

        result = runner.invoke(main, ["playback", "seek", "01:00:00"])

        assert result.exit_code == 1
        assert "Seek position out of range: 01:00:00" in result.output
        assert "current track duration: 00:05:00" in result.output
        mock_client.seek_property.assert_not_called()

    def test_position_past_the_duration_machine_readable(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """The out-of-range error is silent in machine-readable mode."""
        mock_client, _ = self._mock_client(mocker, state={"duration": 300})

        result = runner.invoke(main, ["-m", "playback", "seek", "3600"])

        assert result.exit_code == 1
        assert result.output == ""
        mock_client.seek_property.assert_not_called()

    def test_no_check_seek_position(self, runner: CliRunner, mocker: MockerFixture):
        """With --no-check-seek-position an out-of-range position is sent unchecked."""
        mock_client, _ = self._mock_client(mocker, state={"duration": 300})

        result = runner.invoke(
            main,
            [
                "playback",
                "seek",
                "3600",
                "--no-check-seek-position",
                "--no-print-resulting-status",
            ],
        )

        assert result.exit_code == 0
        mock_client.state_property.assert_not_called()
        mock_client.seek_property.assert_called_once_with(3600)

    @pytest.mark.parametrize(
        ("spelling", "method"),
        [("plus", "seek_forward"), ("minus", "seek_backward")],
    )
    def test_relative_values_are_not_checked(
        self, runner: CliRunner, mocker: MockerFixture, spelling: str, method: str
    ):
        """The relative keywords are exempt from the check."""
        mock_client, _ = self._mock_client(mocker, state={"duration": 300})

        result = runner.invoke(
            main, ["playback", "seek", spelling, "--no-print-resulting-status"]
        )

        assert result.exit_code == 0
        mock_client.state_property.assert_not_called()
        getattr(mock_client, method).assert_called_once_with()
        mock_client.seek_property.assert_not_called()

    @pytest.mark.parametrize(
        "state",
        [{}, {"duration": 0}, {"duration": "unknown"}],
        ids=["missing", "zero", "not-an-integer"],
    )
    def test_unknown_duration_skips_the_check(
        self, runner: CliRunner, mocker: MockerFixture, state: dict
    ):
        """With no usable duration the position cannot be checked, so it is sent."""
        mock_client, _ = self._mock_client(mocker, state=state)

        result = runner.invoke(
            main, ["playback", "seek", "3600", "--no-print-resulting-status"]
        )

        assert result.exit_code == 0
        mock_client.seek_property.assert_called_once_with(3600)

    def test_check_state_connection_error(self, runner: CliRunner, mocker: MockerFixture):
        """A failing state fetch during the check exits 1 without sending the command."""
        mock_client, _ = self._mock_client(mocker)
        _attach_property(
            mock_client, "state", side_effect=VolumioConnectionError("Connection failed")
        )

        result = runner.invoke(main, ["playback", "seek", "42"])

        assert result.exit_code == 1
        assert "Connection error" in result.output
        mock_client.seek_property.assert_not_called()

    def test_connection_error(self, runner: CliRunner, mocker: MockerFixture):
        """playback seek exits 1 on a connection error."""
        mock_client, _ = self._mock_client(mocker)
        _attach_property(
            mock_client, "seek", side_effect=VolumioConnectionError("Connection failed")
        )

        result = runner.invoke(main, ["playback", "seek", "42"])

        assert result.exit_code == 1
        assert "Connection error" in result.output


class TestPrintResultingState:
    """Test cases for the -r/--print-resulting-status option on playback commands."""

    @pytest.fixture
    def runner(self):
        """Create a CliRunner instance."""
        return CliRunner()

    def _mock_client(self, mocker: MockerFixture):
        """Mock VolumioRESTAPIClient with a usable state property, patch out the sleep."""
        mock_client = mocker.Mock()
        mock_client.pause.return_value = {"response": "pause"}
        _attach_property(mock_client, "volume")
        _attach_property(mock_client, "state", return_value={
            "title": "Test Song",
            "artist": "Test Artist",
        })
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        mock_sleep = mocker.patch("volumito.cli.click_helpers.time.sleep")
        return mock_client, mock_sleep

    def test_default_prints_resulting_status(self, runner: CliRunner, mocker: MockerFixture):
        """By default, a playback action waits 1 second and prints the resulting status."""
        mock_client, mock_sleep = self._mock_client(mocker)

        result = runner.invoke(main, ["playback", "pause"])

        assert result.exit_code == 0
        assert "Command 'pause' executed successfully" in result.output
        # The resulting status is printed after the command
        assert "Test Song" in result.output
        mock_sleep.assert_called_once_with(2.0)
        mock_client.state_property.assert_called_once()

    def test_no_print_resulting_status(self, runner: CliRunner, mocker: MockerFixture):
        """--no-print-resulting-status skips the sleep and the state print."""
        mock_client, mock_sleep = self._mock_client(mocker)

        result = runner.invoke(main, ["playback", "pause", "--no-print-resulting-status"])

        assert result.exit_code == 0
        assert "Command 'pause' executed successfully" in result.output
        assert "Test Song" not in result.output
        mock_sleep.assert_not_called()
        mock_client.state_property.assert_not_called()

    def test_short_flag_prints_resulting_status(self, runner: CliRunner, mocker: MockerFixture):
        """The -r short flag behaves like the enabled default."""
        mock_client, mock_sleep = self._mock_client(mocker)

        result = runner.invoke(main, ["playback", "pause", "-r"])

        assert result.exit_code == 0
        assert "Test Song" in result.output
        mock_sleep.assert_called_once_with(2.0)

    def test_command_with_argument_prints_resulting_status(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """A command taking an argument (volume) also prints the resulting status."""
        mock_client, mock_sleep = self._mock_client(mocker)

        result = runner.invoke(main, ["playback", "volume", "50"])

        assert result.exit_code == 0
        assert "Test Song" in result.output
        mock_client.volume_property.assert_called_once_with(50)
        mock_sleep.assert_called_once_with(2.0)

    def test_custom_sleep_before_next_call(self, runner: CliRunner, mocker: MockerFixture):
        """--sleep-before-next-api-call sets the pause before the resulting-status fetch."""
        mock_client, mock_sleep = self._mock_client(mocker)

        result = runner.invoke(
            main, ["--sleep-before-next-api-call", "0.5", "playback", "pause"]
        )

        assert result.exit_code == 0
        assert "Test Song" in result.output
        mock_sleep.assert_called_once_with(0.5)


class TestQueueHelperFunctions:
    """Test cases for queue-related helper functions."""

    def test_filter_queue_fields_all(self):
        """Test filter_queue_fields with 'all' option."""
        queue_data = {
            "queue": [
                {
                    "title": "Song 1",
                    "artist": "Artist 1",
                    "extra_field": "extra",
                },
                {
                    "title": "Song 2",
                    "artist": "Artist 2",
                    "another_field": "data",
                },
            ]
        }

        result = filter_queue_fields(queue_data, "ALL")

        assert len(result) == 2
        assert result[0]["position"] == 1
        assert result[0]["extra_field"] == "extra"
        assert result[1]["position"] == 2
        assert result[1]["another_field"] == "data"

    def test_filter_queue_fields_short(self):
        """Test filter_queue_fields with 'short' option."""
        queue_data = {
            "queue": [
                {
                    "title": "Test Song",
                    "artist": "Test Artist",
                    "album": "Test Album",
                    "duration": 180,
                    "samplerate": "44.1 kHz",
                    "bitdepth": "16 bit",
                    "channels": 2,
                    "service": "mpd",
                    "extra_field": "extra",
                    "another_field": "data",
                }
            ]
        }

        result = filter_queue_fields(queue_data, "SHORT")

        assert len(result) == 1
        assert result[0]["position"] == 1
        # Should include only SHORT_FORMAT_FIELDS_QUEUE_LIST
        for field in SHORT_FORMAT_FIELDS_QUEUE_LIST:
            if field in queue_data["queue"][0]:
                assert field in result[0]
        # Audio-quality fields are no longer part of the queue short field set
        assert "samplerate" not in result[0]
        assert "bitdepth" not in result[0]
        assert "channels" not in result[0]
        assert "service" not in result[0]

        # Should not include non-short fields
        assert "extra_field" not in result[0]
        assert "another_field" not in result[0]

    def test_filter_queue_fields_short_with_a_custom_list(self):
        """A short field list of the caller replaces the queue list one."""
        queue_data = {
            "queue": [
                {"title": "Song", "artist": "A", "uri": "music-library/a.flac", "service": "mpd"}
            ]
        }

        result = filter_queue_fields(queue_data, "SHORT", ["position", "title", "uri"])

        assert result == [{"position": 1, "title": "Song", "uri": "music-library/a.flac"}]

    def test_filter_queue_fields_short_keeps_track_and_volume_numbers(self):
        """The SHORT field set includes tracknumber and volumeNumber when present."""
        queue_data = {
            "queue": [
                {
                    "title": "Song",
                    "artist": "A",
                    "album": "B",
                    "tracknumber": 3,
                    "volumeNumber": 2,
                    "service": "mpd",
                }
            ]
        }

        result = filter_queue_fields(queue_data, "SHORT")

        assert result[0]["tracknumber"] == 3
        assert result[0]["volumeNumber"] == 2
        assert "service" not in result[0]

    def test_filter_queue_fields_custom_omits_position(self):
        """A custom list without 'position' drops the synthetic position field."""
        queue_data = {"queue": [{"title": "Song", "artist": "A", "album": "B"}]}

        result = filter_queue_fields(queue_data, "artist,album")

        assert list(result[0].keys()) == ["artist", "album"]
        assert "position" not in result[0]

    def test_filter_queue_fields_custom_keeps_position(self):
        """A custom list that includes 'position' keeps the synthetic position."""
        queue_data = {"queue": [{"title": "Song", "artist": "A"}]}

        result = filter_queue_fields(queue_data, "artist,position")

        assert result[0] == {"artist": "A", "position": 1}

    def test_filter_zones_fields_short_trims_state_but_custom_keeps_it(self):
        """SHORT drops albumart from the state sub-dict; a custom 'state' keeps it whole."""
        zones_data = {
            "zones": [
                {"name": "Living", "host": "http://x", "state": {"title": "S", "albumart": "a"}}
            ]
        }

        short = filter_zones_fields(zones_data, "SHORT")
        assert short[0]["state"] == {"title": "S"}  # albumart excluded

        custom = filter_zones_fields(zones_data, "name,state")
        assert custom[0] == {"name": "Living", "state": {"title": "S", "albumart": "a"}}

    def test_rebase_queue_positions_starting_at_one(self):
        """The 1-indexed positions are left untouched when displaying from one."""
        tracks = [{"position": 1, "title": "Song 1"}, {"position": 2, "title": "Song 2"}]

        result = rebase_queue_positions(tracks, True)

        assert [track["position"] for track in result] == [1, 2]
        # The input items are not modified
        assert tracks[0]["position"] == 1

    def test_rebase_queue_positions_starting_at_zero(self):
        """The positions are shifted down by one when displaying from zero."""
        tracks = [{"position": 1, "title": "Song 1"}, {"position": 2, "title": "Song 2"}]

        result = rebase_queue_positions(tracks, False)

        assert [track["position"] for track in result] == [0, 1]
        assert tracks[0]["position"] == 1

    def test_rebase_queue_positions_without_position(self):
        """An item without an integer position is copied unchanged."""
        tracks = [{"title": "Song 1"}]

        assert rebase_queue_positions(tracks, False) == [{"title": "Song 1"}]

    def test_format_queue_as_table(self):
        """Test format_queue_as_table function."""
        tracks = [
            {
                "position": 1,
                "title": "Test Song",
                "artist": "Test Artist",
                "album": "Test Album",
                "duration": 180,
            },
            {
                "position": 2,
                "title": "Another Song",
                "artist": "Another Artist",
            },
        ]

        result = format_queue_as_table(tracks)

        assert "Volumio Queue" in result
        assert "=" * 50 in result
        assert "Test Song" in result
        assert "Test Artist" in result
        assert "Another Song" in result

    def test_format_queue_as_table_optional_fields(self):
        """The service, URI, and audio-quality fields are printed when present."""
        tracks = [
            {
                "position": 1,
                "title": "Test Song",
                "artist": "Test Artist",
                "duration": 180,
                "service": "mpd",
                "uri": "music-library/a.flac",
                "samplerate": "44.1 kHz",
                "bitdepth": "16 bit",
                "channels": 2,
            }
        ]

        result = format_queue_as_table(tracks)

        assert "   Duration: 00:03:00" in result
        assert "   Service: mpd" in result
        assert "   URI    : music-library/a.flac" in result
        assert "   Sample Rate: 44.1 kHz" in result
        assert "   Bit Depth: 16 bit" in result
        assert "   Channels: 2" in result

    def test_format_queue_as_table_track_and_volume_numbers(self):
        """The track and volume numbers are printed when present."""
        tracks = [
            {
                "position": 1,
                "title": "Test Song",
                "artist": "Test Artist",
                "album": "Test Album",
                "tracknumber": 3,
                "volumeNumber": 2,
            }
        ]

        result = format_queue_as_table(tracks)

        assert "   Track  : 3" in result
        assert "   Volume : 2" in result

    def test_format_queue_as_table_two_digit_positions(self):
        """With 10+ tracks the numbers are right-aligned and the details indented to match."""
        tracks = [
            {"position": index, "title": f"Song {index}", "artist": "Mango", "duration": 252}
            for index in range(1, 12)
        ]

        lines = format_queue_as_table(tracks).splitlines()

        # Single-digit numbers are padded so that they right-align with the two-digit ones
        assert " 9. Song 9" in lines
        assert "10. Song 10" in lines
        # The keys of every block start at the same column as the track title
        assert lines[lines.index(" 9. Song 9") + 1] == "    Artist : Mango"
        assert lines[lines.index("10. Song 10") + 1] == "    Artist : Mango"
        assert lines.count("    Artist : Mango") == 11
        assert lines.count("    Duration: 00:04:12") == 11

    def test_format_queue_as_table_single_digit_positions_unchanged(self):
        """With fewer than 10 tracks the indentation is the usual three spaces."""
        tracks = [{"position": 1, "title": "Test Song", "artist": "Test Artist"}]

        lines = format_queue_as_table(tracks).splitlines()

        assert "1. Test Song" in lines
        assert "   Artist : Test Artist" in lines

    def test_format_queue_as_table_missing_position(self):
        """A track without a position falls back to '?', padded like the other numbers."""
        tracks = [{"title": "Song 1"}] + [
            {"position": index, "title": f"Song {index}"} for index in range(2, 11)
        ]

        lines = format_queue_as_table(tracks).splitlines()

        assert " ?. Song 1" in lines
        assert "10. Song 10" in lines


class TestPositionIndexing:
    """Test cases for --position-starting-at-one/--position-starting-at-zero."""

    @pytest.fixture
    def runner(self):
        """Create a CliRunner instance."""
        return CliRunner()

    def _mock_state_client(self, mocker: MockerFixture):
        """Mock the REST client, returning a state whose position is the API's second track."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={
            "status": "play",
            "position": 1,
            "title": "Test Song",
        })
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        return mock_client

    def _mock_queue_client(self, mocker: MockerFixture):
        """Mock the REST client, returning a two-track queue."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "queue", return_value={
            "queue": [
                {"title": "Song 1", "artist": "Artist 1"},
                {"title": "Song 2", "artist": "Artist 2"},
            ]
        })
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        return mock_client

    def test_help_lists_the_option(self, runner: CliRunner):
        """Both flags of the option are shown in the top-level help."""
        result = runner.invoke(main, ["--help"])

        assert result.exit_code == 0
        assert "--position-starting-at-one" in result.output
        assert "--position-starting-at-zero" in result.output

    def test_playback_status_pretty(self, runner: CliRunner, mocker: MockerFixture):
        """playback status -F pretty rebases the position."""
        self._mock_state_client(mocker)

        one_based = runner.invoke(main, ["playback", "status", "-F", "pretty"])
        zero_based = runner.invoke(
            main, ["--position-starting-at-zero", "playback", "status", "-F", "pretty"]
        )

        assert json.loads(one_based.output)["position"] == 2
        assert json.loads(zero_based.output)["position"] == 1

    def test_playback_status_table(self, runner: CliRunner, mocker: MockerFixture):
        """playback status -F table rebases the position."""
        self._mock_state_client(mocker)

        one_based = runner.invoke(main, ["playback", "status", "-F", "table"])
        zero_based = runner.invoke(
            main, ["--position-starting-at-zero", "playback", "status", "-F", "table"]
        )

        assert f"{'Position':20}: 2" in one_based.output
        assert f"{'Position':20}: 1" in zero_based.output

    def test_playback_status_json_and_raw_unaffected(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """The json and raw formats always print the position as returned by the API."""
        self._mock_state_client(mocker)

        for output_format in ("json", "raw"):
            one_based = runner.invoke(main, ["playback", "status", "-F", output_format])
            zero_based = runner.invoke(
                main,
                ["--position-starting-at-zero", "playback", "status", "-F", output_format],
            )

            assert json.loads(one_based.output)["position"] == 1
            assert json.loads(zero_based.output)["position"] == 1

    def test_track_info_pretty(self, runner: CliRunner, mocker: MockerFixture):
        """track info -F pretty rebases the position too."""
        self._mock_state_client(mocker)

        zero_based = runner.invoke(
            main, ["--position-starting-at-zero", "queue", "track", "info", "-F", "pretty"]
        )

        assert json.loads(zero_based.output)["position"] == 1

    def test_queue_list_pretty(self, runner: CliRunner, mocker: MockerFixture):
        """queue list -F pretty rebases the synthetic positions."""
        self._mock_queue_client(mocker)

        one_based = runner.invoke(main, ["queue", "list", "-F", "pretty"])
        zero_based = runner.invoke(
            main, ["--position-starting-at-zero", "queue", "list", "-F", "pretty"]
        )

        assert [t["position"] for t in json.loads(one_based.output)] == [1, 2]
        assert [t["position"] for t in json.loads(zero_based.output)] == [0, 1]

    def test_queue_list_table(self, runner: CliRunner, mocker: MockerFixture):
        """queue list -F table rebases the synthetic positions."""
        self._mock_queue_client(mocker)

        one_based = runner.invoke(main, ["queue", "list", "-F", "table"])
        zero_based = runner.invoke(
            main, ["--position-starting-at-zero", "queue", "list", "-F", "table"]
        )

        assert "1. Song 1" in one_based.output
        assert "0. Song 1" in zero_based.output

    def test_queue_list_json_unaffected(self, runner: CliRunner, mocker: MockerFixture):
        """queue list -F json keeps its 1-indexed synthetic positions."""
        self._mock_queue_client(mocker)

        zero_based = runner.invoke(
            main, ["--position-starting-at-zero", "queue", "list", "-F", "json"]
        )

        assert [t["position"] for t in json.loads(zero_based.output)] == [1, 2]

    def test_play_position_starting_at_one(self, runner: CliRunner, mocker: MockerFixture):
        """With the default base, the position is decremented before the API call."""
        mock_client = mocker.Mock()
        mock_client.play.return_value = {"response": "play"}
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["playback", "play", "1", "--no-print-resulting-status"])

        assert result.exit_code == 0
        mock_client.play.assert_called_once_with(0)

    def test_play_position_starting_at_zero(self, runner: CliRunner, mocker: MockerFixture):
        """With the zero base, the position is passed to the API unchanged."""
        mock_client = mocker.Mock()
        mock_client.play.return_value = {"response": "play"}
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(
            main,
            [
                "--position-starting-at-zero",
                "playback",
                "play",
                "0",
                "--no-print-resulting-status",
            ],
        )

        assert result.exit_code == 0
        mock_client.play.assert_called_once_with(0)

    def test_play_position_below_minimum(self, runner: CliRunner, mocker: MockerFixture):
        """A position below the minimum of the current base is a usage error."""
        mock_client = mocker.Mock()
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        one_based = runner.invoke(main, ["playback", "play", "0"])
        zero_based = runner.invoke(
            main, ["--position-starting-at-zero", "playback", "play", "--", "-1"]
        )

        assert one_based.exit_code != 0
        assert "position must be 1 or greater" in one_based.output
        assert zero_based.exit_code != 0
        assert "position must be 0 or greater" in zero_based.output
        mock_client.play.assert_not_called()

    def test_track_audio_template(self, runner: CliRunner, mocker: MockerFixture):
        """The {position} template key follows the indexing base."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={"position": 1, "title": "La rondine"})
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        mock_mpd_instance = mocker.Mock()
        mock_mpd_instance.get_track_uri.return_value = "http://volumio.local:8000/music/test.flac"
        mock_mpd_client_class = mocker.Mock(return_value=mock_mpd_instance)
        mock_mpd_client_class.return_value.__enter__ = mocker.Mock(return_value=mock_mpd_instance)
        mock_mpd_client_class.return_value.__exit__ = mocker.Mock(return_value=None)
        mocker.patch("volumito.cli.volumito.VolumioMPDClient", new=mock_mpd_client_class)

        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"data"]
        mocker.patch("volumito.cli.click_helpers.requests.get", return_value=mock_response)
        mock_open = mocker.patch("builtins.open", mocker.mock_open(read_data=b"fake audio data"))
        mocker.patch("volumito.cli.click_helpers.os.makedirs")

        result = runner.invoke(
            main,
            [
                "--position-starting-at-zero",
                "track",
                "audio",
                "-d",
                "/tmp/music",
                "-f",
                "{position:03d}_{title}.{extension}",
                "--no-create-download-manifest",
                "--no-add-cover-and-metadata",
            ],
        )

        assert result.exit_code == 0
        mock_open.assert_any_call(os.path.join("/tmp/music", "001_La_rondine.flac"), "wb")

    def test_albumart_template(self, runner: CliRunner, mocker: MockerFixture):
        """The {position} template key follows the indexing base for album art too."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={
            "position": 1,
            "title": "La rondine",
            "albumart": "http://volumio.local:3000/albumart?path=/mnt/x/cover.jpg",
        })
        mocker.patch(
            "volumito.cli.click_helpers.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"data"]
        mocker.patch("volumito.cli.click_helpers.requests.get", return_value=mock_response)
        mock_open = mocker.patch("builtins.open", mocker.mock_open())
        mocker.patch("volumito.cli.click_helpers.os.makedirs")

        result = runner.invoke(
            main,
            [
                "--position-starting-at-zero",
                "track",
                "albumart",
                "-d",
                "/tmp/covers",
                "-f",
                "{position:03d}_{title}.{extension}",
                "--no-create-download-manifest",
            ],
        )

        assert result.exit_code == 0
        mock_open.assert_called_once_with(os.path.join("/tmp/covers", "001_La_rondine.jpg"), "wb")


class TestConfigurationFile:
    """Test cases for the -c/--configuration-file option and config loading."""

    @pytest.fixture
    def runner(self):
        """Create a CliRunner instance."""
        return CliRunner()

    def _mock_rest_client(self, mocker: MockerFixture):
        """Patch VolumioRESTAPIClient so `playback status` succeeds with a minimal state."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={"title": "Test Song"})
        mocker.patch("volumito.cli.click_helpers.VolumioRESTAPIClient", return_value=mock_client)
        return mock_client

    def _write_config(self, tmp_path, text: str) -> str:
        """Write a config file and return its path."""
        config = tmp_path / "volumito.yaml"
        config.write_text(text)
        return str(config)

    def test_help_lists_configuration_file_option(self, runner: CliRunner):
        """The -c/--configuration-file option appears in the main help."""
        result = runner.invoke(main, ["--help"])

        assert result.exit_code == 0
        assert "--configuration-file" in result.output
        assert "-c" in result.output
        assert "--ignore-configuration-file" in result.output
        assert "-i" in result.output

    def test_explicit_config_used_as_defaults(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """Values from an explicit -c file become the option defaults."""
        self._mock_rest_client(mocker)
        config = self._write_config(
            tmp_path,
            "volumio:\n  host: myconfig.local\n  scheme: https\n  rest-api-port: 9999\n",
        )

        result = runner.invoke(main, ["-c", config, "-v", "playback", "status"])

        assert result.exit_code == 0
        assert "https://myconfig.local:9999" in result.output
        assert f'Using configuration file: "{config}"' in result.output

    def test_cli_flag_overrides_config(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """An explicit CLI flag wins over the config-file value."""
        self._mock_rest_client(mocker)
        config = self._write_config(
            tmp_path,
            "volumio:\n  host: myconfig.local\n  scheme: https\n  rest-api-port: 9999\n",
        )

        result = runner.invoke(
            main, ["-c", config, "-H", "override.local", "-v", "playback", "status"]
        )

        assert result.exit_code == 0
        assert "https://override.local:9999" in result.output
        assert "myconfig.local" not in result.output

    def test_config_discovered_by_probing(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """A config found in a probed path is loaded without -c."""
        self._mock_rest_client(mocker)
        config = self._write_config(tmp_path, "volumio:\n  host: probed.local\n")
        mocker.patch(
            "volumito.cli.configuration.configuration_paths",
            return_value=[config],
        )

        result = runner.invoke(main, ["-v", "playback", "status"])

        assert result.exit_code == 0
        assert "http://probed.local:3000" in result.output
        assert f'Using configuration file: "{config}"' in result.output

    def test_ignore_configuration_file_skips_probing(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """--ignore-configuration-file skips the lookup even when a config would be found."""
        self._mock_rest_client(mocker)
        config = self._write_config(tmp_path, "volumio:\n  host: probed.local\n")
        mocker.patch(
            "volumito.cli.configuration.configuration_paths",
            return_value=[config],
        )

        result = runner.invoke(
            main, ["-v", "--ignore-configuration-file", "playback", "status"]
        )

        assert result.exit_code == 0
        # The probed config is not applied: the built-in default host is used
        assert "http://volumio.local:3000" in result.output
        assert "Ignoring configuration files" in result.output
        assert "Using configuration file" not in result.output

    def test_ignore_configuration_file_short_flag(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """The -i shorthand behaves like --ignore-configuration-file."""
        self._mock_rest_client(mocker)
        config = self._write_config(tmp_path, "volumio:\n  host: probed.local\n")
        mocker.patch(
            "volumito.cli.configuration.configuration_paths",
            return_value=[config],
        )

        result = runner.invoke(main, ["-v", "-i", "playback", "status"])

        assert result.exit_code == 0
        assert "http://volumio.local:3000" in result.output
        assert "Ignoring configuration files" in result.output
        assert "Using configuration file" not in result.output

    def test_ignore_configuration_file_with_explicit_c_rejected(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """--ignore-configuration-file and -c are mutually exclusive, in either order."""
        config = self._write_config(tmp_path, "volumio:\n  host: explicit.local\n")

        first = runner.invoke(
            main, ["-c", config, "--ignore-configuration-file", "version"]
        )
        second = runner.invoke(
            main, ["--ignore-configuration-file", "-c", config, "version"]
        )

        assert first.exit_code == 2
        assert "mutually exclusive" in first.output
        assert second.exit_code == 2
        assert "mutually exclusive" in second.output

    def test_output_section_enables_verbose(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """The output section can turn on verbose without a CLI flag."""
        self._mock_rest_client(mocker)
        config = self._write_config(tmp_path, "output:\n  verbose: true\n")

        result = runner.invoke(main, ["-c", config, "playback", "status"])

        assert result.exit_code == 0
        # Verbose output only appears because the config enabled it.
        assert "Connecting to" in result.output

    def test_miscellaneous_section_disables_the_playlist_name_check(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """The miscellaneous section can turn off the playlist name check."""
        mock_client = self._mock_rest_client(mocker)
        mock_client.play_playlist.return_value = {"response": "playPlaylist Response"}
        _attach_property(mock_client, "playlists", return_value=["Rock"])
        config = self._write_config(
            tmp_path, "miscellaneous:\n  check-playlist-name: false\n"
        )

        result = runner.invoke(
            main, ["-c", config, "playlist", "play", "Nope", "--no-print-resulting-status"]
        )

        assert result.exit_code == 0
        mock_client.playlists_property.assert_not_called()
        mock_client.play_playlist.assert_called_once_with("Nope")

    def test_miscellaneous_section_disables_the_seek_position_check(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """The miscellaneous section can turn off the seek position check."""
        mock_client = self._mock_rest_client(mocker)
        _attach_property(mock_client, "seek")
        config = self._write_config(
            tmp_path, "miscellaneous:\n  check-seek-position: false\n"
        )

        result = runner.invoke(
            main, ["-c", config, "playback", "seek", "3600", "--no-print-resulting-status"]
        )

        assert result.exit_code == 0
        mock_client.state_property.assert_not_called()
        mock_client.seek_property.assert_called_once_with(3600)

    def test_output_subsection_sets_format_for_playlist_list(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """The playlist-list subsection sets the format of the playlist list command."""
        mock_client = self._mock_rest_client(mocker)
        _attach_property(mock_client, "playlists", return_value=["Rock"])
        config = self._write_config(
            tmp_path, "output:\n  format: json\n  playlist-list:\n    format: table\n"
        )

        result = runner.invoke(main, ["-c", config, "playlist", "list"])

        assert result.exit_code == 0
        assert "Volumio Playlists" in result.output
        assert "1. Rock" in result.output

    def test_output_subsection_sets_format_for_notification_list(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """The notification-list subsection sets the format of the command."""
        mock_client = self._mock_rest_client(mocker)
        _attach_property(mock_client, "notifications", return_value=["http://host/receiver"])
        config = self._write_config(
            tmp_path, "output:\n  format: json\n  notification-list:\n    format: table\n"
        )

        result = runner.invoke(main, ["-c", config, "notification", "list"])

        assert result.exit_code == 0
        assert "Volumio Notification URLs" in result.output
        assert "1. http://host/receiver" in result.output

    def test_output_subsection_sets_format_for_notification_listen(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """The notification-listen subsection sets the format of the command."""
        mock_client = self._mock_rest_client(mocker)
        _attach_property(mock_client, "notifications", return_value=["http://host/receiver"])
        fake = mocker.Mock()
        fake.listen.return_value = iter([PushNotification.from_raw({"item": "state", "data": {}})])
        mocker.patch("volumito.cli.volumito.NotificationListener", return_value=fake)
        mocker.patch("volumito.cli.volumito.receiver_url", return_value="http://host/receiver")
        config = self._write_config(
            tmp_path, "output:\n  format: json\n  notification-listen:\n    format: table\n"
        )

        result = runner.invoke(main, ["-c", config, "notification", "listen"])

        assert result.exit_code == 0
        assert "] state" in result.output

    def test_notification_section_configures_the_listener(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """The notification section configures the notification listen command."""
        advertised = "http://receiver.lan:9000/hook"
        mock_client = self._mock_rest_client(mocker)
        _attach_property(mock_client, "notifications", return_value=[])
        outcome = SuccessResponse.from_raw({"success": True})
        mock_client.register_notification.return_value = outcome
        mock_client.unregister_notification.return_value = outcome
        fake = mocker.Mock()
        fake.idle_timed_out = False
        # As many notifications as the count the configuration asks for
        fake.listen.return_value = iter(
            [PushNotification.from_raw({"item": "state", "data": {}}) for _ in range(4)]
        )
        listener_class = mocker.patch(
            "volumito.cli.volumito.NotificationListener", return_value=fake
        )
        config = self._write_config(
            tmp_path,
            "notification:\n"
            "  endpoint: /hook\n"
            "  port: 9000\n"
            "  listen:\n"
            "    count: 4\n"
            "    idle-timeout: 5.0\n"
            "    register-url: true\n"
            f"    register-url-full: {advertised}\n"
            "    timeout: 30.0\n"
            "    unregister-url-on-exit: false\n",
        )

        result = runner.invoke(main, ["-c", config, "notification", "listen"])

        assert result.exit_code == 0
        assert advertised in result.output
        listener_class.assert_called_once_with(port=9000, endpoint="/hook")
        fake.listen.assert_called_once_with(4, 30.0, 5.0)
        mock_client.register_notification.assert_called_once_with(advertised)
        mock_client.unregister_notification.assert_not_called()

    def test_notification_section_configures_register_and_unregister(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """The port and the endpoint of the notifications section reach the two commands."""
        mock_client = self._mock_rest_client(mocker)
        outcome = SuccessResponse.from_raw({"success": True})
        mock_client.register_notification.return_value = outcome
        mock_client.unregister_notification.return_value = outcome
        composed = mocker.patch(
            "volumito.cli.volumito.receiver_url", return_value="http://receiver.lan:9000/hook"
        )
        config = self._write_config(
            tmp_path, "notification:\n  endpoint: /hook\n  port: 9000\n"
        )

        for command in ("register", "unregister"):
            result = runner.invoke(main, ["-c", config, "notification", command, "-A"])

            assert result.exit_code == 0
            assert composed.call_args.args[1:] == (9000, "/hook")

        mock_client.register_notification.assert_called_once_with("http://receiver.lan:9000/hook")
        mock_client.unregister_notification.assert_called_once_with(
            "http://receiver.lan:9000/hook"
        )

    def test_output_section_sets_position_indexing(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """The output section can select the zero-based position indexing."""
        mock_client = self._mock_rest_client(mocker)
        _attach_property(mock_client, "state", return_value={"title": "Test Song", "position": 1})
        config = self._write_config(tmp_path, "output:\n  position-starting-at-one: false\n")

        result = runner.invoke(main, ["-c", config, "playback", "status"])

        assert result.exit_code == 0
        assert json.loads(result.output)["position"] == 1

    def test_output_section_sets_format_for_playback_status(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """The output section's format applies to the group-nested playback status command."""
        self._mock_rest_client(mocker)
        config = self._write_config(tmp_path, "output:\n  format: table\n")

        result = runner.invoke(main, ["-c", config, "playback", "status"])

        assert result.exit_code == 0
        assert "Volumio Status" in result.output

    def test_cli_format_overrides_config_format(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """An explicit -F on the subcommand overrides the config format."""
        self._mock_rest_client(mocker)
        config = self._write_config(tmp_path, "output:\n  format: table\n")

        result = runner.invoke(main, ["-c", config, "playback", "status", "-F", "json"])

        assert result.exit_code == 0
        assert "Volumio Status" not in result.output
        assert '"title"' in result.output

    def test_output_per_command_format_override(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """A per-command output subsection overrides the format for that command only."""
        self._mock_rest_client(mocker)
        config = self._write_config(
            tmp_path,
            "output:\n  playback-status:\n    format: table\n  track-info:\n    format: json\n",
        )

        # playback-status subsection -> table for `playback status`.
        state_result = runner.invoke(main, ["-c", config, "playback", "status"])
        # track-info subsection -> json (not a table).
        track_result = runner.invoke(main, ["-c", config, "queue", "track", "info"])

        assert state_result.exit_code == 0
        assert "Volumio Status" in state_result.output
        assert track_result.exit_code == 0
        assert "Track Info" not in track_result.output
        assert '"title"' in track_result.output

    def test_format_only_commands_from_config(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """The format of the system and collection commands can be set from the config."""
        mock_client = self._mock_rest_client(mocker)
        _attach_property(mock_client, "system_info", return_value={"name": "Living Room"})
        _attach_property(mock_client, "collection_statistics", return_value={"songs": 105})
        config = self._write_config(
            tmp_path,
            "output:\n"
            "  format: raw\n"
            "  collection-statistics:\n"
            "    format: table\n",
        )

        # The shared format reaches system info and its top-level info synonym.
        system_result = runner.invoke(main, ["-c", config, "system", "info"])
        info_result = runner.invoke(main, ["-c", config, "info"])
        # The subsection overrides it for collection statistics only.
        statistics_result = runner.invoke(main, ["-c", config, "collection", "statistics"])

        assert system_result.exit_code == 0
        assert system_result.output.strip() == '{"name": "Living Room"}'
        assert info_result.output == system_result.output
        assert statistics_result.exit_code == 0
        assert "Collection Statistics" in statistics_result.output

    def test_print_resulting_content_from_config(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """The output section can disable the resulting-content print for playlist edits."""
        mock_client = mocker.Mock()
        mocker.patch("volumito.cli.click_helpers.VolumioWebSocketClient", return_value=mock_client)
        config = self._write_config(tmp_path, "output:\n  print-resulting-content: false\n")

        result = runner.invoke(
            main,
            [
                "-c",
                config,
                "-C",
                "synchronous_websocket",
                "playlist",
                "add",
                "Rock",
                "qobuz://track/3",
                "--no-check-playlist-name",
            ],
        )

        assert result.exit_code == 0
        mock_client.add_to_playlist.assert_called_once_with("Rock", "qobuz://track/3", None)
        mock_client.get_playlist_content.assert_not_called()

    def test_print_resulting_list_from_config(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """The output section can disable the listing after a Web radio edit."""
        mock_client = mocker.Mock()
        mocker.patch("volumito.cli.click_helpers.VolumioWebSocketClient", return_value=mock_client)
        config = self._write_config(tmp_path, "output:\n  print-resulting-list: false\n")

        result = runner.invoke(
            main,
            [
                "-c",
                config,
                "-C",
                "synchronous_websocket",
                "collection",
                "radio",
                "add",
                "Radio Tre",
                "http://radio.example/tre",
            ],
        )

        assert result.exit_code == 0
        mock_client.add_web_radio.assert_called_once_with("Radio Tre", "http://radio.example/tre")
        mock_client.browse.assert_not_called()

    def test_print_resulting_status_from_config(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """The output section can disable the resulting-status print for playback actions."""
        mocker.patch("volumito.cli.click_helpers.VolumioRESTAPIClient", return_value=mocker.Mock())
        mock_maybe = mocker.patch("volumito.cli.volumito.execute_conditionally")
        config = self._write_config(tmp_path, "output:\n  print-resulting-status: false\n")

        result = runner.invoke(main, ["-c", config, "playback", "toggle"])

        assert result.exit_code == 0
        mock_maybe.assert_called_once()
        assert mock_maybe.call_args.args[1] is False

    def test_print_resulting_status_default_true(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """With no config, the resulting-status print keeps its True default."""
        mocker.patch("volumito.cli.click_helpers.VolumioRESTAPIClient", return_value=mocker.Mock())
        mock_maybe = mocker.patch("volumito.cli.volumito.execute_conditionally")

        result = runner.invoke(main, ["playback", "toggle"])

        assert result.exit_code == 0
        mock_maybe.assert_called_once()
        assert mock_maybe.call_args.args[1] is True

    def test_downloads_per_command_output_directory_for_audio(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """A per-command downloads.audio.output-directory sets the track audio download dir."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={"title": "Test Song"})
        mocker.patch("volumito.cli.click_helpers.VolumioRESTAPIClient", return_value=mock_client)

        mpd = mocker.Mock()
        mpd.get_track_uri.return_value = "http://volumio.local:8000/music/test.flac"
        mpd_class = mocker.Mock(return_value=mpd)
        mpd_class.return_value.__enter__ = mocker.Mock(return_value=mpd)
        mpd_class.return_value.__exit__ = mocker.Mock(return_value=None)
        mocker.patch("volumito.cli.volumito.VolumioMPDClient", new=mpd_class)

        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"data"]
        mocker.patch("volumito.cli.click_helpers.requests.get", return_value=mock_response)
        # Patch open only in the volumito module so the config file (read via the
        # configuration module) is still read for real.
        mock_open = mocker.patch("volumito.cli.click_helpers.open", mocker.mock_open())
        mocker.patch("volumito.cli.click_helpers.os.makedirs")

        config = self._write_config(
            tmp_path, "downloads:\n  track-audio:\n    output-directory: /music\n"
        )

        result = runner.invoke(
            main,
            [
                "-c",
                config,
                "track",
                "audio",
                "--no-create-download-manifest",
                "--no-add-cover-and-metadata",
            ],
        )

        assert result.exit_code == 0
        mock_open.assert_called_once_with(os.path.join("/music", "test.flac"), "wb")

    def test_downloads_shared_output_directory_for_albumart(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """A shared downloads.output-directory applies to the track albumart download dir."""
        mock_client = mocker.Mock()
        _attach_property(
            mock_client, "state", return_value={"albumart": "http://example.com/images/cover.jpg"}
        )
        mocker.patch("volumito.cli.click_helpers.VolumioRESTAPIClient", return_value=mock_client)

        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"data"]
        mocker.patch("volumito.cli.click_helpers.requests.get", return_value=mock_response)
        mock_open = mocker.patch("volumito.cli.click_helpers.open", mocker.mock_open())
        mocker.patch("volumito.cli.click_helpers.os.makedirs")

        config = self._write_config(tmp_path, "downloads:\n  output-directory: /covers\n")

        result = runner.invoke(
            main, ["-c", config, "queue", "track", "albumart", "--no-create-download-manifest"]
        )

        assert result.exit_code == 0
        mock_open.assert_called_once_with(os.path.join("/covers", "cover.jpg"), "wb")

    def test_explicit_output_file_overrides_configured_directory(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """An explicit -o wins over a configured output-directory (no exclusivity error)."""
        mock_client = mocker.Mock()
        _attach_property(
            mock_client, "state", return_value={"albumart": "http://example.com/images/cover.jpg"}
        )
        mocker.patch("volumito.cli.click_helpers.VolumioRESTAPIClient", return_value=mock_client)

        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"data"]
        mocker.patch("volumito.cli.click_helpers.requests.get", return_value=mock_response)

        config = self._write_config(tmp_path, "downloads:\n  output-directory: /covers\n")
        out = tmp_path / "out.jpg"

        result = runner.invoke(
            main,
            ["-c", config, "queue", "track", "albumart", "-o", str(out),
             "--no-create-download-manifest"],
        )

        assert result.exit_code == 0
        assert "mutually exclusive" not in result.output
        assert out.read_bytes() == b"data"

    def test_explicit_output_file_overrides_configured_directory_for_audio(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """An explicit -o wins over a configured output-directory for track audio."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={"title": "Test Song"})
        mocker.patch("volumito.cli.click_helpers.VolumioRESTAPIClient", return_value=mock_client)

        mpd = mocker.Mock()
        mpd.get_track_uri.return_value = "http://volumio.local:8000/music/test.flac"
        mpd_class = mocker.Mock(return_value=mpd)
        mpd_class.return_value.__enter__ = mocker.Mock(return_value=mpd)
        mpd_class.return_value.__exit__ = mocker.Mock(return_value=None)
        mocker.patch("volumito.cli.volumito.VolumioMPDClient", new=mpd_class)

        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"data"]
        mocker.patch("volumito.cli.click_helpers.requests.get", return_value=mock_response)

        config = self._write_config(tmp_path, "downloads:\n  output-directory: /music\n")
        out = tmp_path / "out.flac"

        result = runner.invoke(
            main,
            [
                "-c",
                config,
                "track",
                "audio",
                "-o",
                str(out),
                "--no-create-download-manifest",
                "--no-add-cover-and-metadata",
            ],
        )

        assert result.exit_code == 0
        assert "mutually exclusive" not in result.output
        assert out.read_bytes() == b"data"

    def test_explicit_output_directory_overrides_configured_file(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """An explicit -d wins over a configured output-file (no exclusivity error)."""
        mock_client = mocker.Mock()
        _attach_property(
            mock_client, "state", return_value={"albumart": "http://example.com/images/cover.jpg"}
        )
        mocker.patch("volumito.cli.click_helpers.VolumioRESTAPIClient", return_value=mock_client)

        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"data"]
        mocker.patch("volumito.cli.click_helpers.requests.get", return_value=mock_response)

        config = self._write_config(tmp_path, "downloads:\n  output-file: /tmp/elsewhere.jpg\n")
        out = tmp_path / "covers"

        result = runner.invoke(
            main,
            ["-c", config, "queue", "track", "albumart", "-d", str(out),
             "--no-create-download-manifest"],
        )

        assert result.exit_code == 0
        assert "mutually exclusive" not in result.output
        assert (out / "cover.jpg").read_bytes() == b"data"

    def test_configured_output_file_and_directory_conflict(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """Both destinations set in the configuration file still raise the usage error."""
        config = self._write_config(
            tmp_path,
            "downloads:\n  output-directory: /covers\n  output-file: /tmp/out.jpg\n",
        )

        result = runner.invoke(main, ["-c", config, "queue", "track", "albumart"])

        assert result.exit_code == 2
        assert "mutually exclusive" in result.output

    def test_downloads_shared_create_download_manifest_false(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """A shared downloads.create-download-manifest: false reaches the track commands."""
        mock_client = mocker.Mock()
        _attach_property(
            mock_client, "state", return_value={"albumart": "http://example.com/images/cover.jpg"}
        )
        mocker.patch("volumito.cli.click_helpers.VolumioRESTAPIClient", return_value=mock_client)

        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"data"]
        mocker.patch("volumito.cli.click_helpers.requests.get", return_value=mock_response)

        config = self._write_config(tmp_path, "downloads:\n  create-download-manifest: false\n")

        out = tmp_path / "cover.jpg"
        # The default is on, but the config turns it off, so no manifest is written
        result = runner.invoke(main, ["-c", config, "queue", "track", "albumart", "-o", str(out)])

        assert result.exit_code == 0
        assert out.exists()
        assert not (tmp_path / "cover.jpg.json").exists()

    def test_downloads_shared_replace_characters(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """A shared downloads.replace-characters-in-file-names reaches the track commands."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={
            "title": "my cover",
            "albumart": "http://example.com/images/cover.jpg",
        })
        mocker.patch("volumito.cli.click_helpers.VolumioRESTAPIClient", return_value=mock_client)

        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"data"]
        mocker.patch("volumito.cli.click_helpers.requests.get", return_value=mock_response)
        mock_open = mocker.patch("volumito.cli.click_helpers.open", mocker.mock_open())
        mocker.patch("volumito.cli.click_helpers.os.makedirs")

        config = self._write_config(
            tmp_path, 'downloads:\n  replace-characters-in-file-names: ""\n'
        )

        result = runner.invoke(
            main,
            [
                "-c",
                config,
                "track",
                "albumart",
                "-d",
                "/covers",
                "-f",
                "{title}.{extension}",
                "--no-create-download-manifest",
            ],
        )

        assert result.exit_code == 0
        # The config empties the replace list, so the space in the title is kept
        mock_open.assert_called_once_with(os.path.join("/covers", "my cover.jpg"), "wb")

    def test_miscellaneous_add_cover_and_metadata_false(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """A miscellaneous.add-cover-and-metadata: false disables embedding for track audio."""
        mock_client = mocker.Mock()
        _attach_property(mock_client, "state", return_value={"title": "T"})
        mocker.patch("volumito.cli.click_helpers.VolumioRESTAPIClient", return_value=mock_client)

        mpd = mocker.Mock()
        mpd.get_track_uri.return_value = "http://volumio.local:8000/music/test.flac"
        mpd_class = mocker.Mock(return_value=mpd)
        mpd_class.return_value.__enter__ = mocker.Mock(return_value=mpd)
        mpd_class.return_value.__exit__ = mocker.Mock(return_value=None)
        mocker.patch("volumito.cli.volumito.VolumioMPDClient", new=mpd_class)

        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"data"]
        mocker.patch("volumito.cli.click_helpers.requests.get", return_value=mock_response)
        embed = mocker.patch("volumito.cli.click_helpers.embed_metadata_and_cover")

        config = self._write_config(tmp_path, "miscellaneous:\n  add-cover-and-metadata: false\n")

        out = tmp_path / "song.flac"
        # The default is on, but the config turns it off, so no embedding happens
        result = runner.invoke(
            main,
            ["-c", config, "queue", "track", "audio", "-o", str(out),
             "--no-create-download-manifest"],
        )

        assert result.exit_code == 0
        embed.assert_not_called()

    def test_no_config_uses_hardcoded_defaults(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """With no config file anywhere, the hardcoded defaults are used."""
        self._mock_rest_client(mocker)

        result = runner.invoke(main, ["-v", "playback", "status"])

        assert result.exit_code == 0
        assert "http://volumio.local:3000" in result.output
        assert "Using configuration file" not in result.output

    def test_explicit_missing_file_errors(self, runner: CliRunner, tmp_path):
        """An explicit -c path that does not exist exits 2."""
        missing = str(tmp_path / "nope.yaml")

        result = runner.invoke(main, ["-c", missing, "info"])

        assert result.exit_code == 2
        assert "configuration file not found" in result.output

    def test_malformed_config_warns_and_runs(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """Malformed YAML in the config file warns; the command still runs."""
        self._mock_rest_client(mocker)
        config = self._write_config(tmp_path, "volumio: [unterminated\n")

        result = runner.invoke(main, ["-c", config, "playback", "status"])

        assert result.exit_code == 0
        assert "[WARN]" in result.output
        assert "cannot read configuration file" in result.output

    def test_non_utf8_config_warns_and_runs(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """A non-UTF-8 (binary) config file warns; the command still runs."""
        self._mock_rest_client(mocker)
        config = tmp_path / "volumito.yaml"
        config.write_bytes(b"\xff\xfe\x00\x01")

        result = runner.invoke(main, ["-c", str(config), "playback", "status"])

        assert result.exit_code == 0
        assert "is not a valid YAML file" in result.output

    def test_unknown_key_warns_and_runs(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """An unrecognized key warns; the valid keys of the config still apply."""
        self._mock_rest_client(mocker)
        config = self._write_config(
            tmp_path, "volumio:\n  bogus: 1\n  host: lenient.local\n"
        )

        result = runner.invoke(main, ["--verbose", "-c", config, "playback", "status"])

        assert result.exit_code == 0
        assert "unknown key 'bogus'" in result.output
        # The valid host key of the same section still applies
        assert "Connecting to http://lenient.local:3000" in result.output

    def test_config_problems_are_silent_in_machine_readable_mode(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """In machine-readable mode the configuration warnings are suppressed."""
        self._mock_rest_client(mocker)
        config = self._write_config(tmp_path, "volumio:\n  bogus: 1\n")

        result = runner.invoke(main, ["-m", "-c", config, "playback", "status"])

        assert result.exit_code == 0
        assert "unknown key" not in result.output

    def test_strict_parsing_turns_the_problems_into_errors(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """With strict parsing a configuration problem errors the invocation out."""
        mock_client = self._mock_rest_client(mocker)
        config = self._write_config(tmp_path, "volumio:\n  bogus: 1\n")

        result = runner.invoke(
            main,
            ["--strict-parsing-configuration-file", "-c", config, "playback", "status"],
        )

        assert result.exit_code == 1
        assert "[ERRO]" in result.output
        assert "unknown key 'bogus'" in result.output
        mock_client.state_property.assert_not_called()

    def test_strict_parsing_with_a_clean_file(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """With strict parsing a clean configuration runs normally."""
        self._mock_rest_client(mocker)
        config = self._write_config(tmp_path, "volumio:\n  host: clean.local\n")

        result = runner.invoke(
            main,
            ["--strict-parsing-configuration-file", "-c", config, "playback", "status"],
        )

        assert result.exit_code == 0
        assert "Test Song" in result.output

    def test_strict_parsing_machine_readable(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """In machine-readable mode the strict errors are silent, the exit code signals."""
        self._mock_rest_client(mocker)
        config = self._write_config(tmp_path, "volumio:\n  bogus: 1\n")

        result = runner.invoke(
            main,
            ["-m", "--strict-parsing-configuration-file", "-c", config, "playback", "status"],
        )

        assert result.exit_code == 1
        assert "unknown key" not in result.output

    def test_strict_parsing_from_the_configuration_key(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """The configuration key applies the strictness to its own file's problems."""
        self._mock_rest_client(mocker)
        config = self._write_config(
            tmp_path,
            "volumio:\n  bogus: 1\noutput:\n  strict-parsing-configuration-file: true\n",
        )

        result = runner.invoke(main, ["-c", config, "playback", "status"])

        assert result.exit_code == 1
        assert "unknown key 'bogus'" in result.output


class TestConfigurationCommands:
    """Test cases for the `configuration` command group (create/check/search)."""

    @pytest.fixture
    def runner(self):
        """Create a CliRunner instance."""
        return CliRunner()

    def test_create_default_location(self, runner: CliRunner):
        """`configuration create` writes volumito.yaml in the current directory."""
        with runner.isolated_filesystem():
            result = runner.invoke(main, ["configuration", "create"])

            assert result.exit_code == 0
            assert os.path.exists("volumito.yaml")
            assert "Created configuration file" in result.output
            with open("volumito.yaml", encoding="utf-8") as config_file:
                document = yaml.safe_load(config_file)
            assert document == {
                # The aliases section ships with every entry commented out
                "aliases": None,
                "volumio": {
                    "host": "volumio.local",
                    "scheme": "http",
                    "api-client": "synchronous_rest",
                    "allow-fallback-to-rest-api": False,
                    "allow-fallback-to-websocket-api": False,
                    "rest-api-port": 3000,
                    "websocket-port": 3000,
                    "mpd-port": 6600,
                    "ssh-password": None,
                    "ssh-port": 22,
                    "ssh-username": "volumio",
                },
                "timeouts": {
                    "rest-api-timeout": 5.0,
                    "rest-api-timeout-slow-endpoints": 60.0,
                    "websocket-timeout": 5.0,
                    "mpd-timeout": 5.0,
                    "sleep-before-next-api-call": 2.0,
                    "retries-on-unexpected-state": 3,
                },
                "miscellaneous": {
                    "add-cover-and-metadata": True,
                    "allow-local-file-rename": False,
                    "check-next-track": True,
                    "check-playlist-name": True,
                    "check-seek-position": True,
                    "overwrite-existing-playlist": False,
                    "propagate-remote-exit-code": True,
                },
                "notification": {
                    "endpoint": "/volumionotifications",
                    "port": 3003,
                    "event-listen": {
                        "count": None,
                        "idle-timeout": None,
                        "timeout": None,
                    },
                    "listen": {
                        "count": None,
                        "idle-timeout": None,
                        "register-url": False,
                        "register-url-full": None,
                        "timeout": None,
                        "unregister-url-on-exit": True,
                    },
                },
                "output": {
                    "color": True,
                    "fields": "SHORT",
                    "format": "pretty",
                    "machine-readable": False,
                    "pager": False,
                    "position-starting-at-one": True,
                    "print-resulting-content": True,
                    "print-resulting-list": True,
                    "print-resulting-status": True,
                    "strict-parsing-configuration-file": False,
                    "verbose": False,
                    # Subsections are present but empty (null) override placeholders,
                    # except the two collection ones pinning their table format.
                    "collection-browse": {"format": "table"},
                    "collection-favourite-list": {"format": "table"},
                    "collection-radio-list": {"format": "table"},
                    "collection-search": {"format": "table"},
                    "collection-source-list": None,
                    "collection-statistics": None,
                    "command-list": None,
                    "notification-event-listen": None,
                    "notification-event-request": None,
                    "notification-list": None,
                    "notification-listen": None,
                    "playback-infinity": None,
                    "playback-sleep": None,
                    "playback-status": None,
                    "playlist-content": None,
                    "playlist-list": None,
                    "queue-consume": None,
                    "queue-list": None,
                    "queue-randomize": None,
                    "queue-repeat": None,
                    "queue-status": None,
                    "story-album": None,
                    "story-artist": None,
                    "story-credits": None,
                    "story-label": None,
                    "story-place": None,
                    "system-alarm-list": None,
                    "system-audio-device-list": None,
                    "system-audio-dsp": None,
                    "system-audio-inputs": None,
                    "system-audio-outputs": None,
                    "system-backup-create": None,
                    "system-execute": None,
                    "system-network-info": None,
                    "system-network-wireless": None,
                    "system-plugin-configuration": None,
                    "system-plugin-disable": None,
                    "system-plugin-enable": None,
                    "system-plugin-list": None,
                    "system-power-modes": None,
                    "system-share-discover": None,
                    "system-share-info": None,
                    "system-share-list": None,
                    "system-timezone-list": None,
                    "system-ui-background-list": None,
                    "system-ui-experience": None,
                    "system-ui-language-list": None,
                    "system-ui-privacy": None,
                    "system-ui-settings": None,
                    "system-update-channel-list": None,
                    "system-update-check": None,
                    "system-usb-list": None,
                    "system-info": None,
                    "system-version": None,
                    "track-info": None,
                    "multiroom-info": None,
                    "multiroom-set": None,
                    "multiroom-status": None,
                },
                "downloads": {
                    "create-download-manifest": True,
                    "output-directory": None,
                    "output-file": None,
                    "overwrite-existing-files": False,
                    "replace-characters-in-file-names": " :",
                    "replace-characters-in-file-names-with": "_",
                    "playlist-download": {
                        "albumart-file-name-template": _ALBUMART_FILE_NAME_TEMPLATE,
                        "audio-file-name-template": _AUDIO_FILE_NAME_TEMPLATE,
                        "manifest-file": "{output_directory}/manifest.json",
                        "number-retries-next-track": 10,
                        "only-tracks": None,
                        "with-albumart": True,
                    },
                    "queue-download": {
                        "albumart-file-name-template": _QUEUE_ALBUMART_FILE_NAME_TEMPLATE,
                        "audio-file-name-template": _QUEUE_AUDIO_FILE_NAME_TEMPLATE,
                        "manifest-file": "{output_directory}/manifest.json",
                        "number-retries-next-track": 10,
                        "only-tracks": None,
                        "with-albumart": True,
                    },
                    "track-albumart": {
                        "file-name-template": _ALBUMART_FILE_NAME_TEMPLATE,
                    },
                    "track-audio": {
                        "file-name-template": _AUDIO_FILE_NAME_TEMPLATE,
                    },
                },
            }

    def test_create_output_directory(self, runner: CliRunner, tmp_path):
        """`-d DIR` writes DIR/volumito.yaml, creating the directory if needed."""
        target_dir = tmp_path / "nested" / "conf"

        result = runner.invoke(main, ["configuration", "create", "-d", str(target_dir)])

        assert result.exit_code == 0
        assert (target_dir / "volumito.yaml").exists()

    def test_create_output_file(self, runner: CliRunner, tmp_path):
        """`-f FILE` writes exactly FILE."""
        target = tmp_path / "my-config.yaml"

        result = runner.invoke(main, ["configuration", "create", "-o", str(target)])

        assert result.exit_code == 0
        assert target.exists()

    def test_create_volumio_version_3_sets_mpd_port(self, runner: CliRunner, tmp_path):
        """`--volumio-version 3` writes the Volumio 3 MPD port (6599)."""
        target = tmp_path / "volumito.yaml"

        result = runner.invoke(
            main, ["configuration", "create", "-o", str(target), "--volumio-version", "3"]
        )

        assert result.exit_code == 0
        with open(target, encoding="utf-8") as config_file:
            document = yaml.safe_load(config_file)
        assert document["volumio"]["mpd-port"] == MPD_PORT_VOLUMIO_3

    def test_create_volumio_version_short_flag(self, runner: CliRunner, tmp_path):
        """`-V` is the shorthand for --volumio-version."""
        target = tmp_path / "volumito.yaml"

        result = runner.invoke(
            main, ["configuration", "create", "-o", str(target), "-V", "3"]
        )

        assert result.exit_code == 0
        with open(target, encoding="utf-8") as config_file:
            document = yaml.safe_load(config_file)
        assert document["volumio"]["mpd-port"] == MPD_PORT_VOLUMIO_3

    def test_create_volumio_version_dotted(self, runner: CliRunner, tmp_path):
        """A dotted version uses its major: 3.123 -> 6599, 4.119 -> 6600."""
        v3 = tmp_path / "v3.yaml"
        v4 = tmp_path / "v4.yaml"

        result3 = runner.invoke(
            main, ["configuration", "create", "-o", str(v3), "--volumio-version", "3.123"]
        )
        result4 = runner.invoke(
            main, ["configuration", "create", "-o", str(v4), "--volumio-version", "4.119"]
        )

        assert result3.exit_code == 0
        assert result4.exit_code == 0
        with open(v3, encoding="utf-8") as config_file:
            assert yaml.safe_load(config_file)["volumio"]["mpd-port"] == MPD_PORT_VOLUMIO_3
        with open(v4, encoding="utf-8") as config_file:
            assert yaml.safe_load(config_file)["volumio"]["mpd-port"] == MPD_PORT_VOLUMIO_4

    def test_create_volumio_version_invalid(self, runner: CliRunner, tmp_path):
        """A non-version string is a usage error and writes no file."""
        target = tmp_path / "volumito.yaml"

        result = runner.invoke(
            main, ["configuration", "create", "-o", str(target), "--volumio-version", "nope"]
        )

        assert result.exit_code == 2
        assert "is not a valid Volumio version" in result.output
        assert not target.exists()

    def test_create_volumio_version_multi_part(self, runner: CliRunner, tmp_path):
        """A three-component version is parsed by its major (3.1.2 -> 6599)."""
        target = tmp_path / "volumito.yaml"

        result = runner.invoke(
            main, ["configuration", "create", "-o", str(target), "--volumio-version", "3.1.2"]
        )

        assert result.exit_code == 0
        with open(target, encoding="utf-8") as config_file:
            document = yaml.safe_load(config_file)
        assert document["volumio"]["mpd-port"] == MPD_PORT_VOLUMIO_3

    def test_create_machine_readable_prints_path(self, runner: CliRunner, tmp_path):
        """In machine-readable mode create prints the quoted destination path."""
        target = tmp_path / "volumito.yaml"

        result = runner.invoke(main, ["-m", "configuration", "create", "-o", str(target)])

        assert result.exit_code == 0
        assert result.output.strip() == json.dumps(str(target))

    def test_create_mutually_exclusive(self, runner: CliRunner):
        """`-d` and `-f` together is a usage error."""
        result = runner.invoke(main, ["configuration", "create", "-d", "x", "-o", "y"])

        assert result.exit_code == 2
        assert "mutually exclusive" in result.output

    def test_create_rejects_the_old_short_option(self, runner: CliRunner):
        """The destination is -o, as in the other commands, not -f."""
        result = runner.invoke(main, ["configuration", "create", "-f", "y"])

        assert result.exit_code == 2
        # Click quotes the option name of this message since 8.4
        assert "No such option" in result.output
        assert "-f" in result.output

    def test_create_refuses_overwrite(self, runner: CliRunner, tmp_path):
        """Without --overwrite-existing-files, create refuses to clobber."""
        target = tmp_path / "volumito.yaml"
        target.write_text("old\n")

        result = runner.invoke(main, ["configuration", "create", "-o", str(target)])

        assert result.exit_code == 1
        assert f'File already exists: "{target}"' in result.output
        assert target.read_text() == "old\n"

    def test_create_overwrite(self, runner: CliRunner, tmp_path):
        """With --overwrite-existing-files, create replaces an existing file."""
        target = tmp_path / "volumito.yaml"
        target.write_text("previous-content-marker\n")

        result = runner.invoke(
            main,
            ["configuration", "create", "-o", str(target), "--overwrite-existing-files"],
        )

        assert result.exit_code == 0
        assert "previous-content-marker" not in target.read_text()

    def test_create_write_error(self, runner: CliRunner, tmp_path, mocker: MockerFixture):
        """An OSError while writing is reported and exits 1."""
        target = tmp_path / "volumito.yaml"
        mocker.patch("volumito.cli.volumito.open", side_effect=OSError("disk full"))

        result = runner.invoke(main, ["configuration", "create", "-o", str(target)])

        assert result.exit_code == 1
        assert "Cannot write configuration file" in result.output

    def test_check_valid_path(self, runner: CliRunner, tmp_path):
        """`configuration check PATH` validates and prints the values read."""
        config = tmp_path / "volumito.yaml"
        config.write_text(
            "volumio:\n  host: myhost.local\n"
            "output:\n  verbose: true\n  format: table\n  playback-status:\n    format: json\n"
            "downloads:\n  output-directory: /shared\n"
            "  track-audio:\n    file-name-template: 'a.flac'\n"
        )

        result = runner.invoke(main, ["configuration", "check", str(config)])

        assert result.exit_code == 0
        assert "is valid" in result.output
        assert "volumio.host = myhost.local" in result.output
        assert "output.verbose = True" in result.output
        assert "output.format = table" in result.output
        assert "output.playback-status.format = json" in result.output
        assert "downloads.output-directory = /shared" in result.output
        assert "downloads.track-audio.file-name-template = a.flac" in result.output
        # The keys follow the validity line, printed in lexicographic order
        lines = result.output.splitlines()
        assert lines[0].endswith("is valid.")
        assert lines[1:] == sorted(lines[1:])

    def test_check_invalid_content(self, runner: CliRunner, tmp_path):
        """An unrecognized key makes check fail with a clean error."""
        config = tmp_path / "volumito.yaml"
        config.write_text("volumio:\n  bogus: 1\n")

        result = runner.invoke(main, ["configuration", "check", str(config)])

        assert result.exit_code == 1
        lines = result.output.splitlines()
        assert lines[0].endswith("when running in --no-strict-parsing-configuration-file mode:")
        assert "unknown key 'bogus'" in result.output
        assert "Usage:" not in result.output

    def test_check_invalid_yaml(self, runner: CliRunner, tmp_path):
        """A non-YAML file makes check fail with a clean error."""
        config = tmp_path / "notes.md"
        config.write_text("# Title\n\n- a list\nkey: [\n")

        result = runner.invoke(main, ["configuration", "check", str(config)])

        assert result.exit_code == 1
        lines = result.output.splitlines()
        assert lines[0].endswith("when running in --no-strict-parsing-configuration-file mode:")
        assert "cannot read configuration file" in result.output
        assert "Usage:" not in result.output

    def test_check_invalid_yaml_machine_readable(self, runner: CliRunner, tmp_path):
        """With -m, an invalid file is reported as a JSON envelope."""
        config = tmp_path / "notes.md"
        config.write_text("# Title\n\n- a list\nkey: [\n")

        result = runner.invoke(main, ["-m", "configuration", "check", str(config)])

        assert result.exit_code == 1
        envelope = json.loads(result.output)
        assert envelope["valid"] is False
        assert len(envelope["errors"]) == 1
        assert "cannot read configuration file" in envelope["errors"][0]
        assert envelope["path"].endswith("notes.md")

    def test_check_conflicting_destinations(self, runner: CliRunner, tmp_path):
        """A config setting both download destinations makes check fail clearly."""
        config = tmp_path / "volumito.yaml"
        config.write_text("downloads:\n  output-directory: /covers\n  output-file: /tmp/o.jpg\n")

        result = runner.invoke(main, ["configuration", "check", str(config)])

        assert result.exit_code == 1
        lines = result.output.splitlines()
        assert lines[0].endswith("when running in --no-strict-parsing-configuration-file mode:")
        assert (
            "1. output-file and output-directory are mutually exclusive: "
            "'track-albumart' takes output-file from the shared 'downloads' section "
            "and output-directory from the shared 'downloads' section" in result.output
        )
        assert (
            "2. output-file and output-directory are mutually exclusive: "
            "'track-audio' takes output-file from the shared 'downloads' section "
            "and output-directory from the shared 'downloads' section" in result.output
        )

    def test_check_reports_all_problems(self, runner: CliRunner, tmp_path):
        """Unknown keys and destination conflicts are reported together, numbered."""
        config = tmp_path / "volumito.yaml"
        config.write_text(
            "volumio:\n  foo: bar\n"
            "downloads:\n  output-directory: /covers\n"
            "  track-audio:\n    output-file: /tmp/out.flac\n"
        )

        result = runner.invoke(main, ["configuration", "check", str(config)])

        assert result.exit_code == 1
        lines = result.output.splitlines()
        assert lines[0].endswith("when running in --no-strict-parsing-configuration-file mode:")
        assert "1. unknown key 'foo' in section 'volumio'" in result.output
        assert (
            "2. output-file and output-directory are mutually exclusive: "
            "'track-audio' takes output-file from the 'track-audio' subsection "
            "and output-directory from the shared 'downloads' section" in result.output
        )
        # Every line carries its own timestamp and level prefix
        assert all(line.startswith("[2") for line in lines if line)

    def test_check_reports_all_unknown_keys(self, runner: CliRunner, tmp_path):
        """Every unknown key is reported, not only the first one."""
        config = tmp_path / "volumito.yaml"
        config.write_text("volumio:\n  foo: 1\n  bar: 2\n")

        result = runner.invoke(main, ["-m", "configuration", "check", str(config)])

        assert result.exit_code == 1
        envelope = json.loads(result.output)
        assert envelope["valid"] is False
        assert len(envelope["errors"]) == 2
        assert "unknown key 'foo'" in envelope["errors"][0]
        assert "unknown key 'bar'" in envelope["errors"][1]

    def test_check_conflicting_destinations_machine_readable(self, runner: CliRunner, tmp_path):
        """With -m, the destination conflict is reported as a JSON envelope."""
        config = tmp_path / "volumito.yaml"
        config.write_text(
            "downloads:\n  output-file: /tmp/o.flac\n"
            "  track-audio:\n    output-directory: /music\n"
        )

        result = runner.invoke(main, ["-m", "configuration", "check", str(config)])

        assert result.exit_code == 1
        envelope = json.loads(result.output)
        assert envelope["valid"] is False
        assert envelope["errors"] == [
            "output-file and output-directory are mutually exclusive: "
            "'track-audio' takes output-file from the shared 'downloads' section "
            "and output-directory from the 'track-audio' subsection"
        ]

    def test_check_missing_path(self, runner: CliRunner, tmp_path):
        """A nonexistent explicit PATH makes check fail with one self-contained line."""
        missing = tmp_path / "missing.yaml"

        result = runner.invoke(main, ["configuration", "check", str(missing)])

        assert result.exit_code == 1
        lines = result.output.splitlines()
        assert len(lines) == 1
        assert lines[0].endswith(f'Configuration file "{missing}" is not found.')
        assert "Usage:" not in result.output

    def test_check_probe(self, runner: CliRunner, tmp_path, mocker: MockerFixture):
        """Without a path, check probes and validates the file that would be used."""
        config = tmp_path / "volumito.yaml"
        config.write_text("volumio:\n  host: probed.local\n")
        mocker.patch(
            "volumito.cli.configuration.configuration_paths",
            return_value=[str(config)],
        )

        result = runner.invoke(main, ["configuration", "check"])

        assert result.exit_code == 0
        assert "volumio.host = probed.local" in result.output

    def test_check_probe_none_found(self, runner: CliRunner):
        """Without a path and no config anywhere, check exits 1."""
        result = runner.invoke(main, ["configuration", "check"])

        assert result.exit_code == 1
        assert "no configuration file found" in result.output

    def test_check_machine_readable(self, runner: CliRunner, tmp_path):
        """In machine-readable mode check prints an envelope with path and values."""
        config = tmp_path / "volumito.yaml"
        config.write_text("volumio:\n  host: myhost.local\n")

        result = runner.invoke(main, ["-m", "configuration", "check", str(config)])

        assert result.exit_code == 0
        assert json.loads(result.output) == {
            "path": os.path.abspath(config),
            "valid": True,
            "configuration": {"volumio": {"host": "myhost.local"}},
        }

    def test_search_lists_all_paths_with_status(
        self, runner: CliRunner, tmp_path, mocker: MockerFixture
    ):
        """Search lists every probed path, marking found/used and found/NOT used."""
        first = tmp_path / "volumito.yaml"
        first.write_text("")
        second = tmp_path / "other.yaml"
        second.write_text("")
        missing = tmp_path / "gone.yaml"
        mocker.patch(
            "volumito.cli.configuration.configuration_paths",
            return_value=[str(first), str(second), str(missing)],
        )

        result = runner.invoke(main, ["configuration", "search"])

        assert result.exit_code == 0
        assert (
            "Configuration file locations, in probing order, in decreasing order of priority:"
            in result.output
        )
        assert f"{first} (found, used)" in result.output
        assert f"{second} (found, NOT used)" in result.output
        # A path that does not exist is listed without any status annotation.
        assert f"  {missing}\n" in result.output
        assert f"{missing} (" not in result.output

    def test_search_none_found(self, runner: CliRunner, mocker: MockerFixture):
        """Search still lists every probed path, each flagged not found."""
        mocker.patch(
            "volumito.cli.configuration.configuration_paths",
            return_value=["/dir/one/volumito.yaml", "/dir/two/volumito.yaml"],
        )

        result = runner.invoke(main, ["configuration", "search"])

        assert result.exit_code == 0
        assert (
            "Configuration file locations, in probing order, in decreasing order of priority:"
            in result.output
        )
        # No status annotation is shown for paths that do not exist.
        assert "  /dir/one/volumito.yaml\n" in result.output
        assert "  /dir/two/volumito.yaml\n" in result.output
        assert "(not found)" not in result.output

    def test_search_machine_readable(self, runner: CliRunner, tmp_path, mocker: MockerFixture):
        """In machine-readable mode search prints a per-path object array as JSON."""
        found = tmp_path / "volumito.yaml"
        found.write_text("")
        missing = tmp_path / "gone.yaml"
        mocker.patch(
            "volumito.cli.configuration.configuration_paths",
            return_value=[str(found), str(missing)],
        )

        result = runner.invoke(main, ["-m", "configuration", "search"])

        assert result.exit_code == 0
        assert json.loads(result.output) == [
            {"path": str(found), "found": True, "used": True, "ignored": False},
            {"path": str(missing), "found": False, "used": False, "ignored": False},
        ]

    def test_search_ignoring_marks_found_ignored(
        self, runner: CliRunner, tmp_path, mocker: MockerFixture
    ):
        """With --ignore-configuration-file, found files are marked ignored, none used."""
        found = tmp_path / "volumito.yaml"
        found.write_text("")
        missing = tmp_path / "gone.yaml"
        mocker.patch(
            "volumito.cli.configuration.configuration_paths",
            return_value=[str(found), str(missing)],
        )

        result = runner.invoke(
            main, ["--ignore-configuration-file", "configuration", "search"]
        )

        assert result.exit_code == 0
        assert f"{found} (found, ignored)" in result.output
        assert "(found, used)" not in result.output
        assert "NOT used" not in result.output
        assert f"  {missing}\n" in result.output

    def test_search_ignoring_machine_readable(
        self, runner: CliRunner, tmp_path, mocker: MockerFixture
    ):
        """In machine-readable mode the ignored flag is reported per found path."""
        found = tmp_path / "volumito.yaml"
        found.write_text("")
        missing = tmp_path / "gone.yaml"
        mocker.patch(
            "volumito.cli.configuration.configuration_paths",
            return_value=[str(found), str(missing)],
        )

        result = runner.invoke(
            main, ["-m", "--ignore-configuration-file", "configuration", "search"]
        )

        assert result.exit_code == 0
        assert json.loads(result.output) == [
            {"path": str(found), "found": True, "used": False, "ignored": True},
            {"path": str(missing), "found": False, "used": False, "ignored": False},
        ]

    def test_check_fails_when_ignoring(self, runner: CliRunner, tmp_path):
        """With --ignore-configuration-file and no PATH, configuration check fails."""
        config = tmp_path / "volumito.yaml"
        config.write_text("volumio:\n  host: x.local\n")

        without_path = runner.invoke(
            main, ["--ignore-configuration-file", "configuration", "check"]
        )
        with_path = runner.invoke(
            main, ["--ignore-configuration-file", "configuration", "check", str(config)]
        )

        assert without_path.exit_code == 1
        assert "mutually exclusive with an omitted PATH" in without_path.output
        assert with_path.exit_code == 0
        assert f'Configuration file "{config}" is valid.' in with_path.output

    def test_check_invalid_path_when_ignoring(self, runner: CliRunner, tmp_path):
        """With --ignore-configuration-file, an explicit invalid PATH is still checked."""
        config = tmp_path / "volumito.yaml"
        config.write_text("volumio:\n  host: [\n")

        result = runner.invoke(
            main, ["--ignore-configuration-file", "configuration", "check", str(config)]
        )

        assert result.exit_code == 1
        assert (
            f'Configuration file "{config}" contains the following problem(s)'
            in result.output
        )
        assert "mutually exclusive with an omitted PATH" not in result.output

    def test_check_valid_empty_file(self, runner: CliRunner, tmp_path):
        """An empty configuration file is valid and lists no keys."""
        config = tmp_path / "volumito.yaml"
        config.write_text("")

        result = runner.invoke(main, ["configuration", "check", str(config)])

        assert result.exit_code == 0
        assert f'Configuration file "{config}" is valid.' in result.output
        assert "=" not in result.output

    def test_check_fails_when_ignoring_machine_readable(self, runner: CliRunner):
        """In machine-readable mode the ignoring check failure is a JSON envelope."""
        result = runner.invoke(
            main, ["-m", "--ignore-configuration-file", "configuration", "check"]
        )

        assert result.exit_code == 1
        envelope = json.loads(result.output)
        assert envelope["valid"] is False
        assert envelope["path"] is None
        assert len(envelope["errors"]) == 1
        assert "--ignore-configuration-file" in envelope["errors"][0]
