"""Tests for the CLI module.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

import json
import os

import click
import pytest
import requests
import yaml
from click.testing import CliRunner
from pytest_mock import MockerFixture

from volumito.cli.volumito import (
    PLAYER_STATE_SHORT_FIELDS,
    QUEUE_LIST_SHORT_FIELDS,
    TRACK_INFO_SHORT_FIELDS,
    OnOffParamType,
    VolumeParamType,
    display_position,
    extract_filename_from_uri,
    filter_fields,
    filter_queue_fields,
    format_as_json,
    format_as_pretty,
    format_as_table,
    format_queue_as_table,
    main,
    rebase_queue_positions,
    render_output_filename,
)
from volumito.clients.rest import (
    VolumioAPIError,
    VolumioConnectionError,
)

# The four download keys with their default values, as generated per subsection.
_DOWNLOAD_DEFAULTS = {
    "file-name-template": "{file_name_from_uri}",
    "output-directory": None,
    "output-file": None,
    "overwrite-existing-files": False,
}

# The display keys with their default values, as generated per subsection.
_DISPLAY_DEFAULTS = {"fields": "short", "format": "pretty"}

# The keys generated for the subsections of the commands that accept only --format.
_FORMAT_DEFAULTS = {"format": "pretty"}


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

        result = filter_fields(state, "all")

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

        result = filter_fields(state, "short")

        # Should only include PLAYER_STATE_SHORT_FIELDS
        for field in PLAYER_STATE_SHORT_FIELDS:
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

        result = filter_fields(state, "short")

        assert "title" in result
        assert "artist" in result
        assert len(result) == 2

    def test_filter_fields_short_track(self):
        """Test filter_fields with a custom short-field list (TRACK_INFO_SHORT_FIELDS)."""
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

        result = filter_fields(state, "short", TRACK_INFO_SHORT_FIELDS)

        # Track-oriented fields are kept
        for field in TRACK_INFO_SHORT_FIELDS:
            assert field in result

        # Player-only and unknown fields are dropped
        assert "status" not in result
        assert "volume" not in result
        assert "extra" not in result


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

    def _state(self):
        return {
            "position": 0,
            "title": "La rondine",
            "album": "Puccini",
            "artist": "Anna",
            "trackType": "flac",
            "duration": 200,
            "bitdepth": "16 bit",
            "samplerate": "44.1 kHz",
            "channels": 2,
        }

    def test_default_template(self):
        """The default template reproduces the URI basename."""
        uri = "http://volumio.local:8000/music/song.flac"
        assert render_output_filename("{file_name_from_uri}", uri, {}, "flac") == "song.flac"

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
        """The duration key is formatted as HH:MM:SS."""
        result = render_output_filename(
            "{duration}.{extension}", "http://x/y", self._state(), "flac"
        )
        assert result == "00:03:20.flac"

    def test_extension_from_uri(self):
        """The extension key is taken from the URI file name."""
        result = render_output_filename("{extension}", "http://x/song.mp3", self._state(), "flac")
        assert result == "mp3"

    def test_extension_default_when_uri_has_none(self):
        """The default extension is used when the URI file has no extension."""
        assert render_output_filename("{extension}", "http://x/song", {}, "flac") == "flac"
        assert render_output_filename("{extension}", "http://x/albumart", {}, "jpg") == "jpg"

    def test_bad_template_unknown_key(self):
        """An unknown template key raises a UsageError."""
        with pytest.raises(click.UsageError):
            render_output_filename("{unknown}", "http://x/y.flac", self._state(), "flac")

    def test_bad_template_bad_spec(self):
        """An invalid format specification raises a UsageError."""
        with pytest.raises(click.UsageError):
            render_output_filename("{title:03d}", "http://x/y.flac", self._state(), "flac")


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
        mocker.patch("volumito.cli.volumito.maybe_print_resulting_status")

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
        assert "--machine-readable" in result.output
        assert "--rest-api-timeout" in result.output
        assert "--mpd-timeout" in result.output
        assert "--rest-api-sleep-before-next-call" in result.output
        # Short options
        assert "-H" in result.output
        assert "-M" in result.output
        assert "-P" in result.output

    def test_version_command(self, runner: CliRunner):
        """Test the version subcommand."""
        result = runner.invoke(main, ["version"])

        assert result.exit_code == 0
        assert "volumito, version 0.0.13" in result.output

    def test_version_command_machine_readable(self, runner: CliRunner):
        """Test --machine-readable version prints the quoted version string."""
        result = runner.invoke(main, ["--machine-readable", "version"])

        assert result.exit_code == 0
        assert result.output.strip() == '"0.0.13"'
        assert "volumito" not in result.output
        assert "version" not in result.output

    def test_version_command_machine_readable_shorthand(self, runner: CliRunner):
        """Test the -m shorthand for --machine-readable with the version subcommand."""
        result = runner.invoke(main, ["-m", "version"])

        assert result.exit_code == 0
        assert result.output.strip() == '"0.0.13"'

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
        mock_client.get_system_info.return_value = {
            "name": "Living Room",
            "systemversion": "3.601",
        }

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["info"])

        assert result.exit_code == 0
        assert "Living Room" in result.output
        mock_client.get_system_info.assert_called_once()

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
        mock_client.get_state.return_value = {
            "position": 0,
            "title": "Test Song",
            "artist": "Test Artist",
        }

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["playback", "status"])

        assert result.exit_code == 0
        assert "Test Song" in result.output

    def test_info_with_custom_host(self, runner: CliRunner, mocker: MockerFixture):
        """Test info command with custom host."""
        mock_client = mocker.Mock()
        mock_client.get_system_info.return_value = {"name": "Test"}

        mock_client_class = mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
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
        mock_client.get_system_info.return_value = {"name": "Test", "systemversion": "3.601"}

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
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
        mock_client.get_system_info.return_value = {"name": "Test"}

        mock_client_class = mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["-H", "192.168.1.100", "info"])

        assert result.exit_code == 0
        host_configuration = mock_client_class.call_args[0][0]
        assert host_configuration.host == "192.168.1.100"

    def test_short_option_ports(self, runner: CliRunner, mocker: MockerFixture):
        """Test the -M/-P shorthands for --mpd-port/--rest-api-port."""
        mock_client = mocker.Mock()
        mock_client.get_system_info.return_value = {"name": "Test"}

        mock_client_class = mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
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
        mock_client.get_state.return_value = {"title": "Test Song"}

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["playback", "status", "-F", "table"])

        assert result.exit_code == 0
        assert "Volumio Status" in result.output
        assert "Test Song" in result.output

    def test_short_option_fields(self, runner: CliRunner, mocker: MockerFixture):
        """Test the -L shorthand for --fields (on playback status)."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {
            "title": "Test",
            "volume": 100,
            "extra": "data",
        }

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["playback", "status", "-L", "all"])

        assert result.exit_code == 0
        output_data = json.loads(result.output)
        assert "extra" in output_data

    def test_short_option_format_raw(self, runner: CliRunner, mocker: MockerFixture):
        """Test the -F shorthand with the raw format (on the info/system info command)."""
        mock_client = mocker.Mock()
        mock_client.get_system_info.return_value = {"name": "Test", "systemversion": "3.601"}

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
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
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["playback", "play", "-p", "3"])

        assert result.exit_code == 0
        # Position is 1-indexed on the CLI, 0-indexed to the client
        mock_client.play.assert_called_once_with(2)

    def test_info_with_verbose(self, runner: CliRunner, mocker: MockerFixture):
        """Test info command with --verbose flag."""
        mock_client = mocker.Mock()
        mock_client.get_system_info.return_value = {"name": "Test"}

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["--verbose", "info"])

        assert result.exit_code == 0
        # Verbose messages go to stderr
        assert "Connecting to" in result.output or "Successfully retrieved" in result.output

    def test_info_connection_error(self, runner: CliRunner, mocker: MockerFixture):
        """Test info command with connection error."""
        mock_client = mocker.Mock()
        mock_client.get_system_info.side_effect = VolumioConnectionError("Connection failed")

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["info"])

        assert result.exit_code == 1
        assert "Connection error" in result.output

    def test_info_api_error(self, runner: CliRunner, mocker: MockerFixture):
        """Test info command with API error."""
        mock_client = mocker.Mock()
        mock_client.get_system_info.side_effect = VolumioAPIError("API error")

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
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
        mock_client.get_system_info.side_effect = VolumioConnectionError("Connection failed")

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
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
            "volumito.cli.volumito.VolumioRESTAPIClient",
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
            "volumito.cli.volumito.VolumioRESTAPIClient",
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
            "volumito.cli.volumito.VolumioRESTAPIClient",
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
            "volumito.cli.volumito.VolumioRESTAPIClient",
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
            "volumito.cli.volumito.VolumioRESTAPIClient",
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
            "volumito.cli.volumito.VolumioRESTAPIClient",
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
            "volumito.cli.volumito.VolumioRESTAPIClient",
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
            "volumito.cli.volumito.VolumioRESTAPIClient",
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
            "volumito.cli.volumito.VolumioRESTAPIClient",
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
            "volumito.cli.volumito.VolumioRESTAPIClient",
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
            "volumito.cli.volumito.VolumioRESTAPIClient",
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
            "volumito.cli.volumito.VolumioRESTAPIClient",
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
            "volumito.cli.volumito.VolumioRESTAPIClient",
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
            "volumito.cli.volumito.VolumioRESTAPIClient",
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
            "volumito.cli.volumito.VolumioRESTAPIClient",
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
        timeout = mock_client_class.call_args[0][1]
        assert host_configuration.host == "192.168.1.100"
        assert host_configuration.rest_api_port == 8080
        assert timeout == 10.0

    def test_previous_success_default(self, runner: CliRunner, mocker: MockerFixture):
        """Test successful previous command with default options."""
        mock_client = mocker.Mock()
        mock_client.previous.return_value = {"response": "prev"}

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
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
            "volumito.cli.volumito.VolumioRESTAPIClient",
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
            "volumito.cli.volumito.VolumioRESTAPIClient",
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
            "volumito.cli.volumito.VolumioRESTAPIClient",
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
            "volumito.cli.volumito.VolumioRESTAPIClient",
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
            "volumito.cli.volumito.VolumioRESTAPIClient",
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
            "volumito.cli.volumito.VolumioRESTAPIClient",
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
            "volumito.cli.volumito.VolumioRESTAPIClient",
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
            "volumito.cli.volumito.VolumioRESTAPIClient",
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
            "volumito.cli.volumito.VolumioRESTAPIClient",
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
            "volumito.cli.volumito.VolumioRESTAPIClient",
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
            "volumito.cli.volumito.VolumioRESTAPIClient",
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
            "volumito.cli.volumito.VolumioRESTAPIClient",
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
            "volumito.cli.volumito.VolumioRESTAPIClient",
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
        mock_client.volume.return_value = {"response": "volume"}

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["playback", "volume", "50"])

        assert result.exit_code == 0
        assert "Command 'volume 50' executed successfully" in result.output
        # The value reaches the client as an int
        mock_client.volume.assert_called_once_with(50)

    def test_volume_no_value_prints_current(self, runner: CliRunner, mocker: MockerFixture):
        """Test playback volume without a value prints the current volume."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {"volume": 42, "title": "Test"}

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["playback", "volume"])

        assert result.exit_code == 0
        assert "42" in result.output
        # No volume command is sent when only querying the current level
        mock_client.volume.assert_not_called()

    @pytest.mark.parametrize(
        ("spelling", "canonical"),
        [
            ("up", "plus"),
            ("increase", "plus"),
            ("down", "minus"),
            ("decrease", "minus"),
        ],
    )
    def test_volume_alias_success(
        self, runner: CliRunner, mocker: MockerFixture, spelling: str, canonical: str
    ):
        """Test playback volume normalizes step aliases to the canonical keyword."""
        mock_client = mocker.Mock()
        mock_client.volume.return_value = {"response": "volume"}

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["playback", "volume", spelling])

        assert result.exit_code == 0
        mock_client.volume.assert_called_once_with(canonical)

    @pytest.mark.parametrize("keyword", ["mute", "unmute", "plus", "minus"])
    def test_volume_keyword_success(
        self, runner: CliRunner, mocker: MockerFixture, keyword: str
    ):
        """Test playback volume with each accepted keyword value."""
        mock_client = mocker.Mock()
        mock_client.volume.return_value = {"response": "volume"}

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["playback", "volume", keyword])

        assert result.exit_code == 0
        mock_client.volume.assert_called_once_with(keyword)

    @pytest.mark.parametrize("level", ["0", "100"])
    def test_volume_boundaries(self, runner: CliRunner, mocker: MockerFixture, level: str):
        """Test playback volume accepts the 0 and 100 boundary levels."""
        mock_client = mocker.Mock()
        mock_client.volume.return_value = {"response": "volume"}

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["playback", "volume", level])

        assert result.exit_code == 0
        mock_client.volume.assert_called_once_with(int(level))

    @pytest.mark.parametrize("bad_value", ["101", "-1", "foo", "UP", "+"])
    def test_volume_invalid(self, runner: CliRunner, mocker: MockerFixture, bad_value: str):
        """Test playback volume rejects out-of-range, non-numeric, and non-lowercase values."""
        mock_client = mocker.Mock()

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["playback", "volume", bad_value])

        # Click reports a usage error (exit code 2) and never calls the client
        assert result.exit_code == 2
        mock_client.volume.assert_not_called()

    def test_mute_synonym(self, runner: CliRunner, mocker: MockerFixture):
        """Test playback mute is a synonym for playback volume mute."""
        mock_client = mocker.Mock()
        mock_client.volume.return_value = {"response": "volume"}

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["playback", "mute"])

        assert result.exit_code == 0
        assert "Command 'volume mute' executed successfully" in result.output
        mock_client.volume.assert_called_once_with("mute")

    def test_unmute_synonym(self, runner: CliRunner, mocker: MockerFixture):
        """Test playback unmute is a synonym for playback volume unmute."""
        mock_client = mocker.Mock()
        mock_client.volume.return_value = {"response": "volume"}

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["playback", "unmute"])

        assert result.exit_code == 0
        assert "Command 'volume unmute' executed successfully" in result.output
        mock_client.volume.assert_called_once_with("unmute")

    def test_track_info_help(self, runner: CliRunner):
        """Test track info command with --help."""
        result = runner.invoke(main, ["track", "info", "--help"])

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
        mock_client.get_state.return_value = {
            "position": 0,
            "title": "Test Song",
            "artist": "Test Artist",
        }

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["track", "info"])

        assert result.exit_code == 0
        assert "Test Song" in result.output

    def test_track_info_fields_short(self, runner: CliRunner, mocker: MockerFixture):
        """Test track info with the track-oriented short field set."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {
            "title": "Test",
            "artist": "Test Artist",
            "samplerate": "44.1 kHz",
            "bitdepth": "16 bit",
            "trackType": "flac",
            "status": "play",
            "volume": 100,
            "extra": "data",
        }

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["track", "info", "--format", "json"])

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
        mock_client.get_state.return_value = {
            "title": "Test",
            "status": "play",
            "extra": "data",
        }

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["track", "info", "-L", "all"])

        assert result.exit_code == 0
        output_data = json.loads(result.output)
        assert "extra" in output_data
        assert "status" in output_data

    def test_track_info_format_table(self, runner: CliRunner, mocker: MockerFixture):
        """Test track info --format table: 'Track Info' heading and track short-field order."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {
            "position": 0,
            "title": "Test Song",
            "artist": "Test Artist",
            "trackType": "flac",
            "samplerate": "44.1 kHz",
            "bitdepth": "16 bit",
        }

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["track", "info", "-F", "table"])

        assert result.exit_code == 0
        # Heading is "Track Info", not the playback's "Volumio Status"
        assert "Track Info" in result.output
        assert "Volumio Status" not in result.output
        assert "Test Song" in result.output
        assert "Samplerate" in result.output
        # Fields appear in TRACK_INFO_SHORT_FIELDS order, not sorted alphabetically
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
        mock_client.get_state.return_value = {"title": "Test", "extra": "data"}

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["track", "info", "-F", "raw"])

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
        result = runner.invoke(main, ["track", "audio", "--help"])

        assert result.exit_code == 0
        assert "audio" in result.output.lower()
        assert "uri" in result.output.lower()

    def test_audio_success_default(self, runner: CliRunner, mocker: MockerFixture):
        """Test successful audio command with default options."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {
            "title": "Test Song",
            "artist": "Test Artist",
            "album": "Test Album",
            "service": "mpd",
        }

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        self._mock_mpd_client(mocker, track_uri="http://volumio.local:8000/music/test.flac")

        result = runner.invoke(main, ["track", "audio"])

        assert result.exit_code == 0
        assert "http://volumio.local:8000/music/test.flac" in result.output
        # Without --machine-readable, the URI is printed bare (not quoted)
        assert '"http://volumio.local:8000/music/test.flac"' not in result.output

    def test_audio_with_custom_host(self, runner: CliRunner, mocker: MockerFixture):
        """Test audio command with custom host."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {
            "title": "Test Song",
            "artist": "Test Artist",
        }

        mock_client_class = mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        # The MPD client's get_track_uri() would replace 127.0.0.1 with the actual host
        self._mock_mpd_client(mocker, track_uri="http://192.168.1.100:8000/music/test.flac")

        result = runner.invoke(main, ["--host", "192.168.1.100", "track", "audio"])

        assert result.exit_code == 0
        host_configuration = mock_client_class.call_args[0][0]
        assert host_configuration.host == "192.168.1.100"
        # Check that localhost was replaced with the custom host
        assert "192.168.1.100" in result.output
        assert "127.0.0.1" not in result.output

    def test_audio_with_custom_mpd_port(self, runner: CliRunner, mocker: MockerFixture):
        """Test audio command with custom MPD port."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {"title": "Test"}

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        # The MPD client's get_track_uri() would replace localhost with volumio.local (default host)
        self._mock_mpd_client(mocker, track_uri="http://volumio.local:8000/music/test.flac")

        result = runner.invoke(main, ["--mpd-port", "6600", "track", "audio"])

        assert result.exit_code == 0

    def test_audio_with_custom_timeouts(self, runner: CliRunner, mocker: MockerFixture):
        """Test audio command routes --rest-api-timeout and --mpd-timeout to the right clients."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {"title": "Test"}

        mock_rest_class = mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
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
            ["--rest-api-timeout", "10", "--mpd-timeout", "3", "track", "audio"],
        )

        assert result.exit_code == 0
        # REST client receives the REST API timeout
        assert mock_rest_class.call_args[0][1] == 10.0
        # MPD client receives the MPD timeout
        assert mock_mpd_class.call_args[0][1] == 3.0

    def test_audio_replaces_localhost(self, runner: CliRunner, mocker: MockerFixture):
        """Test audio command replaces localhost with host value."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {"title": "Test Song"}

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        # The MPD client's get_track_uri() would replace localhost with myhost.local
        self._mock_mpd_client(mocker, track_uri="http://myhost.local:8000/music/test.flac")

        result = runner.invoke(main, ["--host", "myhost.local", "track", "audio"])

        assert result.exit_code == 0
        assert "myhost.local" in result.output
        assert "localhost" not in result.output or "localhost" in result.output.lower()

    def test_audio_replaces_127_0_0_1(self, runner: CliRunner, mocker: MockerFixture):
        """Test audio command replaces 127.0.0.1 with host value."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {"title": "Test Song"}

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        # The MPD client's get_track_uri() would replace 127.0.0.1 with myhost.local
        self._mock_mpd_client(mocker, track_uri="http://myhost.local:8000/music/test.flac")

        result = runner.invoke(main, ["--host", "myhost.local", "track", "audio"])

        assert result.exit_code == 0
        assert "myhost.local" in result.output
        assert "127.0.0.1" not in result.output

    def test_audio_with_verbose(self, runner: CliRunner, mocker: MockerFixture):
        """Test audio command with --verbose flag."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {"title": "Test Song"}

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        # The MPD client's get_track_uri() would replace localhost with volumio.local (default host)
        self._mock_mpd_client(mocker, track_uri="http://volumio.local:8000/music/test.flac")

        result = runner.invoke(main, ["--verbose", "track", "audio"])

        assert result.exit_code == 0
        assert "Connecting to" in result.output
        assert "Successfully retrieved state" in result.output
        assert "Connecting to MPD" in result.output

    def test_audio_with_machine_readable(self, runner: CliRunner, mocker: MockerFixture):
        """Test audio command with --machine-readable flag."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {"title": "Test Song"}

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        # The MPD client's get_track_uri() would replace localhost with volumio.local (default host)
        self._mock_mpd_client(mocker, track_uri="http://volumio.local:8000/music/test.flac")

        result = runner.invoke(main, ["--machine-readable", "track", "audio"])

        assert result.exit_code == 0
        # In machine-readable mode, only the quoted URI should be printed
        assert result.output.strip() == '"http://volumio.local:8000/music/test.flac"'
        assert "Title" not in result.output
        assert "Artist" not in result.output

    def test_audio_connection_error(self, runner: CliRunner, mocker: MockerFixture):
        """Test audio command with connection error."""
        mock_client = mocker.Mock()
        mock_client.get_state.side_effect = VolumioConnectionError("Connection failed")

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["track", "audio"])

        assert result.exit_code == 1
        assert "Connection error" in result.output

    def test_audio_api_error(self, runner: CliRunner, mocker: MockerFixture):
        """Test audio command with API error."""
        mock_client = mocker.Mock()
        mock_client.get_state.side_effect = VolumioAPIError("API error")

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["track", "audio"])

        assert result.exit_code == 1
        assert "API error" in result.output

    def test_audio_mpd_connection_refused(self, runner: CliRunner, mocker: MockerFixture):
        """Test audio command with MPD connection refused."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {"title": "Test Song"}

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
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

        result = runner.invoke(main, ["track", "audio"])

        assert result.exit_code == 1
        assert "Connection refused to MPD" in result.output

    def test_audio_mpd_os_error(self, runner: CliRunner, mocker: MockerFixture):
        """Test audio command with MPD OS error."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {"title": "Test Song"}

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
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

        result = runner.invoke(main, ["track", "audio"])

        assert result.exit_code == 1
        assert "MPD connection error" in result.output

    def test_audio_mpd_no_current_song(self, runner: CliRunner, mocker: MockerFixture):
        """Test audio command when no track is playing."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {"title": "Test Song"}

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        self._mock_mpd_client(
            mocker,
            side_effect=VolumioConnectionError("No track currently playing")
        )

        result = runner.invoke(main, ["track", "audio"])

        assert result.exit_code == 1
        assert "No track currently playing" in result.output

    def test_audio_machine_readable_suppresses_errors(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """Test audio command with --machine-readable flag suppresses errors."""
        mock_client = mocker.Mock()
        mock_client.get_state.side_effect = VolumioConnectionError("Connection failed")

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["--machine-readable", "track", "audio"])

        assert result.exit_code == 1
        assert result.output == ""

    def test_audio_with_minimal_metadata(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """Test audio command with minimal metadata."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {"status": "play"}

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        # The MPD client's get_track_uri() would replace localhost with volumio.local (default host)
        self._mock_mpd_client(mocker, track_uri="http://volumio.local:8000/music/test.flac")

        result = runner.invoke(main, ["track", "audio"])

        assert result.exit_code == 0
        # Should still print the URI even without metadata fields
        assert "http://volumio.local:8000/music/test.flac" in result.output

    def test_audio_mpd_generic_exception(self, runner: CliRunner, mocker: MockerFixture):
        """Test audio command with generic MPD exception after connection."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {"title": "Test Song"}

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        self._mock_mpd_client(
            mocker,
            side_effect=VolumioConnectionError("MPD error: MPD protocol error")
        )

        result = runner.invoke(main, ["track", "audio"])

        assert result.exit_code == 1
        assert "MPD error" in result.output

    def test_audio_mpd_exception_with_machine_readable(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """Test audio command with generic MPD exception and --machine-readable flag."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {"title": "Test Song"}

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        self._mock_mpd_client(
            mocker,
            side_effect=VolumioConnectionError("MPD error: Unexpected MPD response")
        )

        result = runner.invoke(main, ["--machine-readable", "track", "audio"])

        assert result.exit_code == 1
        # Error should be suppressed in machine-readable mode
        assert result.output == ""

    def test_audio_with_output_directory(self, runner: CliRunner, mocker: MockerFixture):
        """Test audio command with -d flag (filename taken from the URI)."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {"title": "Test Song"}

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        self._mock_mpd_client(mocker, track_uri="http://volumio.local:8000/music/test.flac")

        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"fake", b"audio", b"data"]
        mock_get = mocker.patch("volumito.cli.volumito.requests.get", return_value=mock_response)
        mock_open = mocker.patch("builtins.open", mocker.mock_open())

        result = runner.invoke(main, ["track", "audio", "-d", "/tmp/music"])

        assert result.exit_code == 0
        assert "successfully downloaded" in result.output
        mock_get.assert_called_once()
        # Filename derived from the URI basename
        mock_open.assert_called_once_with(os.path.join("/tmp/music", "test.flac"), "wb")

    def test_audio_output_directory_with_template(self, runner: CliRunner, mocker: MockerFixture):
        """Test audio -d with a -f/--file-name-template."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {"position": 0, "title": "La rondine"}

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        self._mock_mpd_client(mocker, track_uri="http://volumio.local:8000/music/test.flac")

        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"data"]
        mocker.patch("volumito.cli.volumito.requests.get", return_value=mock_response)
        mock_open = mocker.patch("builtins.open", mocker.mock_open())

        result = runner.invoke(
            main,
            ["track", "audio", "-d", "/tmp/music", "-f", "{position:03d}_{title}.{extension}"],
        )

        assert result.exit_code == 0
        mock_open.assert_called_once_with(os.path.join("/tmp/music", "001_La_rondine.flac"), "wb")

    def test_audio_output_directory_bad_template(self, runner: CliRunner, mocker: MockerFixture):
        """Test audio -d with an invalid -f template errors out."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {"title": "Test Song"}

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        self._mock_mpd_client(mocker, track_uri="http://volumio.local:8000/music/test.flac")

        result = runner.invoke(main, ["track", "audio", "-d", "/tmp/music", "-f", "{unknown}"])

        assert result.exit_code == 2
        assert "Invalid --file-name-template" in result.output

    def test_audio_output_file_and_dir_mutually_exclusive(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """Test audio command rejects combining -o and -d."""
        result = runner.invoke(main, ["track", "audio", "-o", "/tmp/a.flac", "-d", "/tmp"])

        assert result.exit_code == 2
        assert "mutually exclusive" in result.output

    def test_audio_no_overwrite_existing_file(self, runner: CliRunner, mocker: MockerFixture):
        """Test audio command refuses to overwrite an existing file by default."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {"title": "Test Song"}

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        self._mock_mpd_client(mocker, track_uri="http://volumio.local:8000/music/test.flac")
        # Only the destination path "exists" (a blanket True would corrupt gettext lookups)
        mocker.patch(
            "volumito.cli.volumito.os.path.exists",
            side_effect=lambda p: p == "/tmp/track.flac",
        )

        mock_get = mocker.patch("volumito.cli.volumito.requests.get")
        mock_open = mocker.patch("builtins.open", mocker.mock_open())

        result = runner.invoke(main, ["track", "audio", "-o", "/tmp/track.flac"])

        assert result.exit_code == 1
        assert "already exists" in result.output
        # Nothing is downloaded or written
        mock_get.assert_not_called()
        mock_open.assert_not_called()

    def test_audio_overwrite_existing_file(self, runner: CliRunner, mocker: MockerFixture):
        """Test audio command overwrites an existing file with --overwrite-existing-files."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {"title": "Test Song"}

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        self._mock_mpd_client(mocker, track_uri="http://volumio.local:8000/music/test.flac")
        mocker.patch(
            "volumito.cli.volumito.os.path.exists",
            side_effect=lambda p: p == "/tmp/track.flac",
        )

        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"fake", b"audio", b"data"]
        mocker.patch("volumito.cli.volumito.requests.get", return_value=mock_response)
        mock_open = mocker.patch("builtins.open", mocker.mock_open())

        result = runner.invoke(
            main, ["track", "audio", "-o", "/tmp/track.flac", "--overwrite-existing-files"]
        )

        assert result.exit_code == 0
        assert "successfully downloaded" in result.output
        mock_open.assert_called_once_with("/tmp/track.flac", "wb")

    def test_audio_with_output_file_explicit_path(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """Test audio command with -o and explicit file path."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {
            "title": "Test Song",
            "artist": "Test Artist",
        }

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        self._mock_mpd_client(mocker, track_uri="http://volumio.local:8000/music/test.flac")

        # Mock requests.get
        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"fake", b"audio", b"data"]
        mock_get = mocker.patch("volumito.cli.volumito.requests.get", return_value=mock_response)

        # Mock file operations
        mock_open = mocker.patch("builtins.open", mocker.mock_open())

        result = runner.invoke(main, ["track", "audio", "-o", "/tmp/my_track.flac"])

        assert result.exit_code == 0
        assert "http://volumio.local:8000/music/test.flac" in result.output
        assert "successfully downloaded" in result.output
        mock_get.assert_called_once()
        mock_open.assert_called_once_with("/tmp/my_track.flac", "wb")

    def test_audio_with_output_file_verbose(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """Test audio command with --verbose and -o option."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {
            "title": "Test Song",
        }

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        self._mock_mpd_client(mocker, track_uri="http://volumio.local:8000/music/test.flac")

        # Mock requests.get
        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"fake", b"audio", b"data"]
        mocker.patch("volumito.cli.volumito.requests.get", return_value=mock_response)

        # Mock file operations
        mocker.patch("builtins.open", mocker.mock_open())

        result = runner.invoke(main, ["--verbose", "track", "audio", "-o", "/tmp/track.flac"])

        assert result.exit_code == 0
        assert "Connecting to" in result.output
        assert "Downloading track to /tmp/track.flac" in result.output
        assert "successfully downloaded" in result.output

    def test_audio_file_write_error(self, runner: CliRunner, mocker: MockerFixture):
        """Test audio command with file write error."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {
            "title": "Test Song",
        }

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        self._mock_mpd_client(mocker, track_uri="http://volumio.local:8000/music/test.flac")

        # Mock requests.get
        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"fake", b"data"]
        mocker.patch("volumito.cli.volumito.requests.get", return_value=mock_response)

        # Mock open to raise OSError
        mocker.patch("builtins.open", side_effect=OSError("Permission denied"))

        result = runner.invoke(main, ["track", "audio", "-o", "/tmp/track.flac"])

        assert result.exit_code == 1
        assert "File write error" in result.output

    def test_audio_download_error(self, runner: CliRunner, mocker: MockerFixture):
        """Test audio command with download error."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {
            "title": "Test Song",
        }

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        self._mock_mpd_client(mocker, track_uri="http://volumio.local:8000/music/test.flac")

        # Mock requests.get to raise an exception
        mocker.patch(
            "volumito.cli.volumito.requests.get",
            side_effect=requests.exceptions.RequestException("Download failed"),
        )

        result = runner.invoke(main, ["track", "audio", "-o", "/tmp/track.flac"])

        assert result.exit_code == 1
        assert "Download error" in result.output

    def test_albumart_help(self, runner: CliRunner):
        """Test albumart command with --help."""
        result = runner.invoke(main, ["track", "albumart", "--help"])

        assert result.exit_code == 0
        assert "albumart" in result.output.lower()
        assert "album art" in result.output.lower()

    def test_albumart_success_default(self, runner: CliRunner, mocker: MockerFixture):
        """Test successful albumart command with default options."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {
            "albumart": "/albumart?path=image.jpg",
        }

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["track", "albumart"])

        assert result.exit_code == 0
        assert "http://volumio.local:3000/albumart?path=image.jpg" in result.output
        # Without --machine-readable, the URI is printed bare (not quoted)
        assert '"http://volumio.local:3000/albumart?path=image.jpg"' not in result.output

    def test_albumart_with_custom_host(self, runner: CliRunner, mocker: MockerFixture):
        """Test albumart command with custom host."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {
            "albumart": "/albumart?path=image.jpg",
        }

        mock_client_class = mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["--host", "192.168.1.100", "track", "albumart"])

        assert result.exit_code == 0
        host_configuration = mock_client_class.call_args[0][0]
        assert host_configuration.host == "192.168.1.100"
        assert "192.168.1.100" in result.output

    def test_albumart_with_absolute_uri(self, runner: CliRunner, mocker: MockerFixture):
        """Test albumart command with absolute URI."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {
            "albumart": "http://example.com/albumart.jpg",
        }

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["track", "albumart"])

        assert result.exit_code == 0
        assert "http://example.com/albumart.jpg" in result.output

    def test_albumart_with_relative_uri(self, runner: CliRunner, mocker: MockerFixture):
        """Test albumart command with relative URI path."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {
            "albumart": "/albumart",
        }

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["track", "albumart"])

        assert result.exit_code == 0
        # Should prepend scheme://host:port
        assert "http://volumio.local:3000/albumart" in result.output

    def test_albumart_with_output_file(self, runner: CliRunner, mocker: MockerFixture):
        """Test albumart command with -o/--output-file option."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {
            "albumart": "http://example.com/albumart.jpg",
        }

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        # Mock requests.get
        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"fake", b"image", b"data"]
        mock_get = mocker.patch("volumito.cli.volumito.requests.get", return_value=mock_response)

        # Mock file operations
        mock_open = mocker.patch("builtins.open", mocker.mock_open())

        result = runner.invoke(main, ["track", "albumart", "-o", "/tmp/albumart.jpg"])

        assert result.exit_code == 0
        assert "http://example.com/albumart.jpg" in result.output
        assert "successfully downloaded" in result.output
        mock_get.assert_called_once()
        mock_open.assert_called_once_with("/tmp/albumart.jpg", "wb")

    def test_albumart_missing_albumart(self, runner: CliRunner, mocker: MockerFixture):
        """Test albumart command when albumart field is missing."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {
            "title": "Test Song",
        }

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["track", "albumart"])

        assert result.exit_code == 1
        assert "No album art URI found" in result.output

    def test_albumart_with_verbose(self, runner: CliRunner, mocker: MockerFixture):
        """Test albumart command with --verbose flag."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {
            "albumart": "http://example.com/albumart.jpg",
        }

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["--verbose", "track", "albumart"])

        assert result.exit_code == 0
        assert "Connecting to" in result.output
        assert "Successfully retrieved state" in result.output
        assert "Album art URI:" in result.output

    def test_albumart_with_machine_readable(self, runner: CliRunner, mocker: MockerFixture):
        """Test albumart command with --machine-readable flag."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {
            "albumart": "http://example.com/albumart.jpg",
        }

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["--machine-readable", "track", "albumart"])

        assert result.exit_code == 0
        # In machine-readable mode, only the quoted URI should be printed
        assert result.output.strip() == '"http://example.com/albumart.jpg"'
        assert "Connecting" not in result.output

    def test_albumart_connection_error(self, runner: CliRunner, mocker: MockerFixture):
        """Test albumart command with connection error."""
        mock_client = mocker.Mock()
        mock_client.get_state.side_effect = VolumioConnectionError("Connection failed")

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["track", "albumart"])

        assert result.exit_code == 1
        assert "Connection error" in result.output

    def test_albumart_api_error(self, runner: CliRunner, mocker: MockerFixture):
        """Test albumart command with API error."""
        mock_client = mocker.Mock()
        mock_client.get_state.side_effect = VolumioAPIError("API error")

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["track", "albumart"])

        assert result.exit_code == 1
        assert "API error" in result.output

    def test_albumart_download_error(self, runner: CliRunner, mocker: MockerFixture):
        """Test albumart command with download error."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {
            "albumart": "http://example.com/albumart.jpg",
        }

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        # Mock requests.get to raise an exception
        mocker.patch(
            "volumito.cli.volumito.requests.get",
            side_effect=requests.exceptions.RequestException("Download failed"),
        )

        result = runner.invoke(main, ["track", "albumart", "-o", "/tmp/albumart.jpg"])

        assert result.exit_code == 1
        assert "Download error" in result.output

    def test_albumart_file_write_error(self, runner: CliRunner, mocker: MockerFixture):
        """Test albumart command with file write error."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {
            "albumart": "http://example.com/albumart.jpg",
        }

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        # Mock requests.get
        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"fake", b"data"]
        mocker.patch("volumito.cli.volumito.requests.get", return_value=mock_response)

        # Mock open to raise OSError
        mocker.patch("builtins.open", side_effect=OSError("Permission denied"))

        result = runner.invoke(main, ["track", "albumart", "-o", "/tmp/albumart.jpg"])

        assert result.exit_code == 1
        assert "File write error" in result.output

    def test_albumart_machine_readable_suppresses_errors(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """Test albumart command with --machine-readable flag suppresses errors."""
        mock_client = mocker.Mock()
        mock_client.get_state.side_effect = VolumioConnectionError("Connection failed")

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["--machine-readable", "track", "albumart"])

        assert result.exit_code == 1
        # Error should be suppressed in machine-readable mode
        assert result.output == ""

    def test_albumart_with_output_directory_query_param(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """Test albumart -d flag: filename from the URI 'path' query parameter."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {
            "albumart": "/albumart?path=/mnt/USB/Album/cover.png",
        }

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"fake", b"image", b"data"]
        mock_get = mocker.patch("volumito.cli.volumito.requests.get", return_value=mock_response)
        mock_open = mocker.patch("builtins.open", mocker.mock_open())

        result = runner.invoke(main, ["track", "albumart", "-d", "/tmp/covers"])

        assert result.exit_code == 0
        assert "successfully downloaded" in result.output
        mock_get.assert_called_once()
        mock_open.assert_called_once_with(os.path.join("/tmp/covers", "cover.png"), "wb")

    def test_albumart_with_output_directory_direct_path(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """Test albumart -d flag: filename from a direct URI path."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {
            "albumart": "http://example.com/images/cover.jpg",
        }

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"fake", b"image", b"data"]
        mocker.patch("volumito.cli.volumito.requests.get", return_value=mock_response)
        mock_open = mocker.patch("builtins.open", mocker.mock_open())

        result = runner.invoke(main, ["track", "albumart", "-d", "/tmp/covers"])

        assert result.exit_code == 0
        mock_open.assert_called_once_with(os.path.join("/tmp/covers", "cover.jpg"), "wb")

    def test_albumart_output_directory_with_template(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """Test albumart -d with a -f/--file-name-template."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {
            "position": 0,
            "title": "La rondine",
            "albumart": "http://example.com/images/cover.jpg",
        }

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"data"]
        mocker.patch("volumito.cli.volumito.requests.get", return_value=mock_response)
        mock_open = mocker.patch("builtins.open", mocker.mock_open())

        result = runner.invoke(
            main,
            ["track", "albumart", "-d", "/tmp/covers", "-f", "{position:03d}_{title}.{extension}"],
        )

        assert result.exit_code == 0
        # Extension derived from the album art URI (cover.jpg -> jpg)
        mock_open.assert_called_once_with(os.path.join("/tmp/covers", "001_La_rondine.jpg"), "wb")

    def test_albumart_output_directory_template_default_extension(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """Test albumart {extension} defaults to jpg when the URI has no extension."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {
            "title": "La rondine",
            "albumart": "http://example.com/albumart",
        }

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"data"]
        mocker.patch("volumito.cli.volumito.requests.get", return_value=mock_response)
        mock_open = mocker.patch("builtins.open", mocker.mock_open())

        result = runner.invoke(
            main, ["track", "albumart", "-d", "/tmp/covers", "-f", "{title}.{extension}"]
        )

        assert result.exit_code == 0
        mock_open.assert_called_once_with(os.path.join("/tmp/covers", "La_rondine.jpg"), "wb")

    def test_albumart_output_directory_bad_template(self, runner: CliRunner, mocker: MockerFixture):
        """Test albumart -d with an invalid -f template errors out."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {"albumart": "http://example.com/cover.jpg"}

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["track", "albumart", "-d", "/tmp/covers", "-f", "{unknown}"])

        assert result.exit_code == 2
        assert "Invalid --file-name-template" in result.output

    def test_albumart_output_directory_no_filename(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """Test albumart -d flag errors when no file name can be derived from the URI."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {
            "albumart": "http://example.com/",
        }

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["track", "albumart", "-d", "/tmp/covers"])

        assert result.exit_code == 1
        assert "cannot determine a file name" in result.output

    def test_albumart_output_file_and_dir_mutually_exclusive(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """Test albumart command rejects combining -o and -d."""
        result = runner.invoke(main, ["track", "albumart", "-o", "/tmp/a.jpg", "-d", "/tmp"])

        assert result.exit_code == 2
        assert "mutually exclusive" in result.output

    def test_albumart_no_overwrite_existing_file(self, runner: CliRunner, mocker: MockerFixture):
        """Test albumart command refuses to overwrite an existing file by default."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {"albumart": "http://example.com/cover.jpg"}

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        # Only the destination path "exists" (a blanket True would corrupt gettext lookups)
        mocker.patch(
            "volumito.cli.volumito.os.path.exists",
            side_effect=lambda p: p == "/tmp/cover.jpg",
        )

        mock_get = mocker.patch("volumito.cli.volumito.requests.get")
        mock_open = mocker.patch("builtins.open", mocker.mock_open())

        result = runner.invoke(main, ["track", "albumart", "-o", "/tmp/cover.jpg"])

        assert result.exit_code == 1
        assert "already exists" in result.output
        # Nothing is downloaded or written
        mock_get.assert_not_called()
        mock_open.assert_not_called()

    def test_albumart_overwrite_existing_file(self, runner: CliRunner, mocker: MockerFixture):
        """Test albumart command overwrites an existing file with --overwrite-existing-files."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {"albumart": "http://example.com/cover.jpg"}

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        mocker.patch(
            "volumito.cli.volumito.os.path.exists",
            side_effect=lambda p: p == "/tmp/cover.jpg",
        )

        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"fake", b"image", b"data"]
        mocker.patch("volumito.cli.volumito.requests.get", return_value=mock_response)
        mock_open = mocker.patch("builtins.open", mocker.mock_open())

        result = runner.invoke(
            main, ["track", "albumart", "-o", "/tmp/cover.jpg", "--overwrite-existing-files"]
        )

        assert result.exit_code == 0
        assert "successfully downloaded" in result.output
        mock_open.assert_called_once_with("/tmp/cover.jpg", "wb")

    def test_queue_help(self, runner: CliRunner):
        """Test queue group with --help."""
        result = runner.invoke(main, ["queue", "--help"])

        assert result.exit_code == 0
        assert "queue" in result.output.lower()
        assert "get" in result.output.lower()

    def test_queue_no_subcommand(self, runner: CliRunner):
        """Test queue group without subcommand."""
        result = runner.invoke(main, ["queue"])

        # Click returns exit code 2 when a group is invoked without a subcommand
        assert result.exit_code == 2
        assert "queue" in result.output.lower()
        # Should show usage/error information when no subcommand is provided
        assert "get" in result.output.lower()

    def test_queue_get_help(self, runner: CliRunner):
        """Test queue get command with --help."""
        result = runner.invoke(main, ["queue", "get", "--help"])

        assert result.exit_code == 0
        assert "get" in result.output.lower()
        assert "--format" in result.output
        assert "--fields" in result.output

    def test_queue_get_success_default(self, runner: CliRunner, mocker: MockerFixture):
        """Test successful queue get command with default options."""
        mock_client = mocker.Mock()
        mock_client.get_queue.return_value = {
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
        }

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["queue", "get"])

        assert result.exit_code == 0
        assert "Song 1" in result.output
        assert "Song 2" in result.output

    def test_queue_get_with_custom_host(self, runner: CliRunner, mocker: MockerFixture):
        """Test queue get command with custom host."""
        mock_client = mocker.Mock()
        mock_client.get_queue.return_value = {
            "queue": [
                {"title": "Test Song", "artist": "Test Artist"}
            ]
        }

        mock_client_class = mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["--host", "192.168.1.100", "queue", "get"])

        assert result.exit_code == 0
        host_configuration = mock_client_class.call_args[0][0]
        assert host_configuration.host == "192.168.1.100"

    def test_queue_get_with_format_json(self, runner: CliRunner, mocker: MockerFixture):
        """Test queue get command with --format json."""
        mock_client = mocker.Mock()
        mock_client.get_queue.return_value = {
            "queue": [
                {"title": "Test Song", "artist": "Test Artist", "duration": 180}
            ]
        }

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["queue", "get", "--format", "json"])

        assert result.exit_code == 0
        # Should be valid JSON
        output_data = json.loads(result.output)
        assert isinstance(output_data, list)
        assert len(output_data) == 1
        assert output_data[0]["title"] == "Test Song"
        assert output_data[0]["position"] == 1

    def test_queue_get_with_format_table(self, runner: CliRunner, mocker: MockerFixture):
        """Test queue get command with --format table."""
        mock_client = mocker.Mock()
        mock_client.get_queue.return_value = {
            "queue": [
                {"title": "Test Song", "artist": "Test Artist", "duration": 180}
            ]
        }

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["queue", "get", "--format", "table"])

        assert result.exit_code == 0
        assert "Volumio Queue" in result.output
        assert "Test Song" in result.output

    def test_queue_get_with_fields_all(self, runner: CliRunner, mocker: MockerFixture):
        """Test queue get command with --fields all."""
        mock_client = mocker.Mock()
        mock_client.get_queue.return_value = {
            "queue": [
                {
                    "title": "Test",
                    "artist": "Artist",
                    "extra_field": "extra_data",
                }
            ]
        }

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["queue", "get", "--fields", "all"])

        assert result.exit_code == 0
        output_data = json.loads(result.output)
        assert "extra_field" in output_data[0]

    def test_queue_get_with_fields_short(self, runner: CliRunner, mocker: MockerFixture):
        """Test queue get command with --fields short."""
        mock_client = mocker.Mock()
        mock_client.get_queue.return_value = {
            "queue": [
                {
                    "title": "Test",
                    "artist": "Artist",
                    "extra_field": "extra_data",
                }
            ]
        }

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["queue", "get", "--fields", "short"])

        assert result.exit_code == 0
        output_data = json.loads(result.output)
        assert "title" in output_data[0]
        assert "artist" in output_data[0]
        assert "extra_field" not in output_data[0]

    def test_queue_get_with_raw_format(self, runner: CliRunner, mocker: MockerFixture):
        """Test queue get command with --format raw."""
        mock_client = mocker.Mock()
        mock_client.get_queue.return_value = {
            "queue": [
                {"title": "Test", "artist": "Artist", "extra_field": "data"}
            ]
        }

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["queue", "get", "--format", "raw"])

        assert result.exit_code == 0
        output_data = json.loads(result.output)
        # Raw should include all fields from the original response
        assert "queue" in output_data
        assert "extra_field" in output_data["queue"][0]

    def test_queue_get_with_verbose(self, runner: CliRunner, mocker: MockerFixture):
        """Test queue get command with --verbose flag."""
        mock_client = mocker.Mock()
        mock_client.get_queue.return_value = {
            "queue": [
                {"title": "Test Song"}
            ]
        }

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["--verbose", "queue", "get"])

        assert result.exit_code == 0
        assert "Connecting to" in result.output or "Successfully retrieved" in result.output

    def test_queue_get_connection_error(self, runner: CliRunner, mocker: MockerFixture):
        """Test queue get command with connection error."""
        mock_client = mocker.Mock()
        mock_client.get_queue.side_effect = VolumioConnectionError("Connection failed")

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["queue", "get"])

        assert result.exit_code == 1
        assert "Connection error" in result.output

    def test_queue_get_api_error(self, runner: CliRunner, mocker: MockerFixture):
        """Test queue get command with API error."""
        mock_client = mocker.Mock()
        mock_client.get_queue.side_effect = VolumioAPIError("API error")

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["queue", "get"])

        assert result.exit_code == 1
        assert "API error" in result.output

    def test_queue_get_machine_readable_suppresses_errors(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """Test queue get command with --machine-readable flag suppresses errors."""
        mock_client = mocker.Mock()
        mock_client.get_queue.side_effect = VolumioConnectionError("Connection failed")

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["--machine-readable", "queue", "get"])

        assert result.exit_code == 1
        # No error output with machine-readable flag
        assert result.output == ""

    def test_queue_get_empty_queue(self, runner: CliRunner, mocker: MockerFixture):
        """Test queue get command with empty queue."""
        mock_client = mocker.Mock()
        mock_client.get_queue.return_value = {"queue": []}

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["queue", "get", "--format", "table"])

        assert result.exit_code == 0
        assert "Volumio Queue" in result.output
        assert "(empty)" in result.output


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
        mock_client.get_system_version.return_value = {
            "systemversion": "3.601",
            "hardware": "pi",
        }
        mock_client.get_system_info.return_value = {
            "name": "Living Room",
            "systemversion": "3.601",
        }
        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
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
        mock_client.get_system_version.side_effect = VolumioAPIError("API error")

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


class TestCollectionCommands:
    """Test cases for the collection statistics command."""

    @pytest.fixture
    def runner(self):
        """Create a CliRunner instance."""
        return CliRunner()

    def _mock_client(self, mocker: MockerFixture):
        """Mock VolumioRESTAPIClient with a usable collectionstats method."""
        mock_client = mocker.Mock()
        mock_client.collectionstats.return_value = {
            "artists": 3,
            "albums": 4,
            "songs": 105,
            "playtime": "7:11:15",
        }
        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
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
        mock_client.collectionstats.side_effect = VolumioConnectionError("Connection failed")

        result = runner.invoke(main, ["collection", "statistics"])

        assert result.exit_code == 1
        assert "Connection error" in result.output


class TestZonesCommands:
    """Test cases for the zones get command."""

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
        """Mock VolumioRESTAPIClient with a usable get_zones method."""
        mock_client = mocker.Mock()
        mock_client.get_zones.return_value = self.ZONES if zones is None else zones
        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        return mock_client

    def test_get_default_short_fields(self, runner: CliRunner, mocker: MockerFixture):
        """zones get prints pretty JSON with the short fields, including the state."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["zones", "get"])

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
        """zones get -L all keeps every field of each zone."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["zones", "get", "-L", "all"])

        assert result.exit_code == 0
        output_data = json.loads(result.output)
        assert output_data[0]["id"] == "zone-1"
        assert output_data[0]["type"] == "device"
        assert output_data[0]["state"]["status"] == "stop"
        # The albumart of the state is kept with all fields
        assert output_data[0]["state"]["albumart"] == "/art1.png"

    def test_get_json_format(self, runner: CliRunner, mocker: MockerFixture):
        """zones get -F json prints JSON with 2-space indentation."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["zones", "get", "-F", "json"])

        assert result.exit_code == 0
        assert '\n    "' in result.output
        assert json.loads(result.output)[1]["name"] == "Volumio Studio"

    def test_get_table_format(self, runner: CliRunner, mocker: MockerFixture):
        """zones get -F table prints numbered blocks with aligned labels."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["zones", "get", "-F", "table"])
        lines = result.output.splitlines()

        assert result.exit_code == 0
        assert "Volumio Zones" in lines
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

        result = runner.invoke(main, ["zones", "get", "-F", "table"])
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

        result = runner.invoke(main, ["zones", "get", "-F", "table"])
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
        """zones get -F table reports an empty zone list."""
        self._mock_client(mocker, zones={"zones": []})

        result = runner.invoke(main, ["zones", "get", "-F", "table"])

        assert result.exit_code == 0
        assert "Volumio Zones" in result.output
        assert "(empty)" in result.output

    def test_get_raw_format(self, runner: CliRunner, mocker: MockerFixture):
        """zones get -F raw prints the unfiltered payload as compact JSON."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["zones", "get", "-F", "raw"])

        assert result.exit_code == 0
        assert "\n" not in result.output.strip()
        output_data = json.loads(result.output)
        # Raw is the whole response, including the nested state
        assert output_data["zones"][0]["state"]["volume"] == 43

    def test_get_machine_readable(self, runner: CliRunner, mocker: MockerFixture):
        """In machine-readable mode zones get still honors the format option."""
        self._mock_client(mocker)

        result = runner.invoke(main, ["-m", "zones", "get", "-F", "raw"])

        assert result.exit_code == 0
        assert json.loads(result.output)["zones"][1]["name"] == "Volumio Studio"

    def test_get_connection_error(self, runner: CliRunner, mocker: MockerFixture):
        """zones get exits 1 on a connection error."""
        mock_client = self._mock_client(mocker)
        mock_client.get_zones.side_effect = VolumioConnectionError("Connection failed")

        result = runner.invoke(main, ["zones", "get"])

        assert result.exit_code == 1
        assert "Connection error" in result.output


class TestPlaylistCommands:
    """Test cases for the playlist list and playlist play commands."""

    PLAYLISTS = ["Rock", "Jazz Classics", "Ambient"]

    @pytest.fixture
    def runner(self):
        """Create a CliRunner instance."""
        return CliRunner()

    def _mock_client(self, mocker: MockerFixture, playlists=None):
        """Mock VolumioRESTAPIClient with usable playlist methods; patch out the sleep."""
        mock_client = mocker.Mock()
        mock_client.list_playlists.return_value = (
            self.PLAYLISTS if playlists is None else playlists
        )
        mock_client.play_playlist.return_value = {"response": "playPlaylist Response"}
        mock_client.get_state.return_value = {
            "title": "Test Song",
            "artist": "StatusMarkerArtist",
        }
        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        mock_sleep = mocker.patch("volumito.cli.volumito.time.sleep")
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
        mock_client.list_playlists.side_effect = VolumioConnectionError("Connection failed")

        result = runner.invoke(main, ["playlist", "list"])

        assert result.exit_code == 1
        assert "Connection error" in result.output

    def test_list_api_error(self, runner: CliRunner, mocker: MockerFixture):
        """playlist list exits 1 on an API error."""
        mock_client, _ = self._mock_client(mocker)
        mock_client.list_playlists.side_effect = VolumioAPIError("Bad payload")

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
        assert "executed successfully" in result.output

    def test_play_requires_the_name(self, runner: CliRunner, mocker: MockerFixture):
        """playlist play without a name is a usage error."""
        mock_client, _ = self._mock_client(mocker)

        result = runner.invoke(main, ["playlist", "play"])

        assert result.exit_code != 0
        mock_client.play_playlist.assert_not_called()

    def test_play_verbose_shows_the_encoded_endpoint(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """In verbose mode the printed endpoint carries the percent-encoded name."""
        self._mock_client(mocker, playlists=["Rock & Roll"])

        result = runner.invoke(
            main, ["-v", "playlist", "play", "Rock & Roll", "--no-print-resulting-status"]
        )

        assert result.exit_code == 0
        assert "cmd=playplaylist&name=Rock%20%26%20Roll" in result.output

    def test_play_default_prints_resulting_status(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """By default, playlist play waits and prints the resulting playback status."""
        mock_client, mock_sleep = self._mock_client(mocker)

        result = runner.invoke(main, ["playlist", "play", "Rock"])

        assert result.exit_code == 0
        mock_sleep.assert_called_once_with(1.0)
        mock_client.get_state.assert_called_once()
        assert "StatusMarkerArtist" in result.output

    def test_play_no_print_resulting_status(self, runner: CliRunner, mocker: MockerFixture):
        """With --no-print-resulting-status the status is not fetched."""
        mock_client, mock_sleep = self._mock_client(mocker)

        result = runner.invoke(
            main, ["playlist", "play", "Rock", "--no-print-resulting-status"]
        )

        assert result.exit_code == 0
        mock_sleep.assert_not_called()
        mock_client.get_state.assert_not_called()
        assert "StatusMarkerArtist" not in result.output

    def test_play_checks_the_name_by_default(self, runner: CliRunner, mocker: MockerFixture):
        """By default the name is looked up before the command is sent."""
        mock_client, _ = self._mock_client(mocker)

        result = runner.invoke(
            main, ["playlist", "play", "Rock", "--no-print-resulting-status"]
        )

        assert result.exit_code == 0
        mock_client.list_playlists.assert_called_once()
        mock_client.play_playlist.assert_called_once_with("Rock")

    def test_play_unknown_name(self, runner: CliRunner, mocker: MockerFixture):
        """An unknown playlist name exits 1, listing the available names."""
        mock_client, _ = self._mock_client(mocker)

        result = runner.invoke(main, ["playlist", "play", "Nope"])

        assert result.exit_code == 1
        assert "playlist not found: Nope" in result.output
        assert "Available playlists:" in result.output
        for name in self.PLAYLISTS:
            assert f"  {name}" in result.output
        mock_client.play_playlist.assert_not_called()

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
        mock_client.list_playlists.assert_not_called()
        mock_client.play_playlist.assert_called_once_with("Nope")

    def test_play_check_connection_error(self, runner: CliRunner, mocker: MockerFixture):
        """A failing lookup exits 1 without sending the command."""
        mock_client, _ = self._mock_client(mocker)
        mock_client.list_playlists.side_effect = VolumioConnectionError("Connection failed")

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
        mock_client.get_state.return_value = {
            "title": "Test Song",
            "artist": "StatusMarkerArtist",
        }
        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        mock_sleep = mocker.patch("volumito.cli.volumito.time.sleep")
        return mock_client, mock_sleep

    def test_clear_default_prints_resulting_status(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """By default, queue clear waits 1 second and prints the resulting playback status."""
        mock_client, mock_sleep = self._mock_client(mocker)

        result = runner.invoke(main, ["queue", "clear"])

        assert result.exit_code == 0
        assert "Command 'clear' executed successfully" in result.output
        assert "StatusMarkerArtist" in result.output
        mock_client.clear.assert_called_once()
        mock_client.get_state.assert_called_once()
        mock_sleep.assert_called_once_with(1.0)

    def test_clear_no_print_resulting_status(self, runner: CliRunner, mocker: MockerFixture):
        """--no-print-resulting-status skips the sleep and the status print."""
        mock_client, mock_sleep = self._mock_client(mocker)

        result = runner.invoke(main, ["queue", "clear", "--no-print-resulting-status"])

        assert result.exit_code == 0
        assert "Command 'clear' executed successfully" in result.output
        assert "StatusMarkerArtist" not in result.output
        mock_client.clear.assert_called_once()
        mock_client.get_state.assert_not_called()
        mock_sleep.assert_not_called()

    def test_repeat_toggle(self, runner: CliRunner, mocker: MockerFixture):
        """queue repeat with no value toggles the repeat mode (None passed to the client)."""
        mock_client, _ = self._mock_client(mocker)

        result = runner.invoke(main, ["queue", "repeat", "--no-print-resulting-status"])

        assert result.exit_code == 0
        assert "Command 'repeat' executed successfully" in result.output
        mock_client.repeat.assert_called_once_with(None)

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
        """queue repeat accepts on/true/yes/1 and off/false/no/0 to set the mode explicitly."""
        mock_client, _ = self._mock_client(mocker)

        result = runner.invoke(
            main, ["queue", "repeat", spelling, "--no-print-resulting-status"]
        )

        assert result.exit_code == 0
        mock_client.repeat.assert_called_once_with(expected)

    def test_repeat_invalid_value(self, runner: CliRunner, mocker: MockerFixture):
        """queue repeat rejects a value that is not an accepted on/off spelling."""
        self._mock_client(mocker)

        result = runner.invoke(
            main, ["queue", "repeat", "maybe", "--no-print-resulting-status"]
        )

        assert result.exit_code == 2
        assert "must be one of" in result.output

    def test_randomize_toggle(self, runner: CliRunner, mocker: MockerFixture):
        """queue randomize with no value toggles the random mode (None passed to the client)."""
        mock_client, _ = self._mock_client(mocker)

        result = runner.invoke(main, ["queue", "randomize", "--no-print-resulting-status"])

        assert result.exit_code == 0
        assert "Command 'randomize' executed successfully" in result.output
        mock_client.randomize.assert_called_once_with(None)

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
        """queue randomize accepts on/true/yes/1 and off/false/no/0 to set the mode explicitly."""
        mock_client, _ = self._mock_client(mocker)

        result = runner.invoke(
            main, ["queue", "randomize", spelling, "--no-print-resulting-status"]
        )

        assert result.exit_code == 0
        mock_client.randomize.assert_called_once_with(expected)

    def test_short_flag_prints_resulting_status(self, runner: CliRunner, mocker: MockerFixture):
        """The -r short flag prints the resulting playback status after the action."""
        mock_client, mock_sleep = self._mock_client(mocker)

        result = runner.invoke(main, ["queue", "repeat", "-r"])

        assert result.exit_code == 0
        assert "StatusMarkerArtist" in result.output
        mock_client.get_state.assert_called_once()
        mock_sleep.assert_called_once_with(1.0)

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


class TestPrintResultingState:
    """Test cases for the -r/--print-resulting-status option on playback commands."""

    @pytest.fixture
    def runner(self):
        """Create a CliRunner instance."""
        return CliRunner()

    def _mock_client(self, mocker: MockerFixture):
        """Mock VolumioRESTAPIClient with a usable get_state, patch out the sleep."""
        mock_client = mocker.Mock()
        mock_client.pause.return_value = {"response": "pause"}
        mock_client.volume.return_value = {"response": "volume"}
        mock_client.get_state.return_value = {
            "title": "Test Song",
            "artist": "Test Artist",
        }
        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        mock_sleep = mocker.patch("volumito.cli.volumito.time.sleep")
        return mock_client, mock_sleep

    def test_default_prints_resulting_status(self, runner: CliRunner, mocker: MockerFixture):
        """By default, a playback action waits 1 second and prints the resulting status."""
        mock_client, mock_sleep = self._mock_client(mocker)

        result = runner.invoke(main, ["playback", "pause"])

        assert result.exit_code == 0
        assert "Command 'pause' executed successfully" in result.output
        # The resulting status is printed after the command
        assert "Test Song" in result.output
        mock_sleep.assert_called_once_with(1.0)
        mock_client.get_state.assert_called_once()

    def test_no_print_resulting_status(self, runner: CliRunner, mocker: MockerFixture):
        """--no-print-resulting-status skips the sleep and the state print."""
        mock_client, mock_sleep = self._mock_client(mocker)

        result = runner.invoke(main, ["playback", "pause", "--no-print-resulting-status"])

        assert result.exit_code == 0
        assert "Command 'pause' executed successfully" in result.output
        assert "Test Song" not in result.output
        mock_sleep.assert_not_called()
        mock_client.get_state.assert_not_called()

    def test_short_flag_prints_resulting_status(self, runner: CliRunner, mocker: MockerFixture):
        """The -r short flag behaves like the enabled default."""
        mock_client, mock_sleep = self._mock_client(mocker)

        result = runner.invoke(main, ["playback", "pause", "-r"])

        assert result.exit_code == 0
        assert "Test Song" in result.output
        mock_sleep.assert_called_once_with(1.0)

    def test_command_with_argument_prints_resulting_status(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """A command taking an argument (volume) also prints the resulting status."""
        mock_client, mock_sleep = self._mock_client(mocker)

        result = runner.invoke(main, ["playback", "volume", "50"])

        assert result.exit_code == 0
        assert "Test Song" in result.output
        mock_client.volume.assert_called_once_with(50)
        mock_sleep.assert_called_once_with(1.0)

    def test_custom_sleep_before_next_call(self, runner: CliRunner, mocker: MockerFixture):
        """--rest-api-sleep-before-next-call sets the pause before the resulting-status fetch."""
        mock_client, mock_sleep = self._mock_client(mocker)

        result = runner.invoke(
            main, ["--rest-api-sleep-before-next-call", "0.5", "playback", "pause"]
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

        result = filter_queue_fields(queue_data, "all")

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

        result = filter_queue_fields(queue_data, "short")

        assert len(result) == 1
        assert result[0]["position"] == 1
        # Should include only QUEUE_LIST_SHORT_FIELDS
        for field in QUEUE_LIST_SHORT_FIELDS:
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
        """The service and audio-quality fields are printed when present."""
        tracks = [
            {
                "position": 1,
                "title": "Test Song",
                "artist": "Test Artist",
                "duration": 180,
                "service": "mpd",
                "samplerate": "44.1 kHz",
                "bitdepth": "16 bit",
                "channels": 2,
            }
        ]

        result = format_queue_as_table(tracks)

        assert "   Duration: 00:03:00" in result
        assert "   Service: mpd" in result
        assert "   Sample Rate: 44.1 kHz" in result
        assert "   Bit Depth: 16 bit" in result
        assert "   Channels: 2" in result

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
        mock_client.get_state.return_value = {
            "status": "play",
            "position": 1,
            "title": "Test Song",
        }
        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )
        return mock_client

    def _mock_queue_client(self, mocker: MockerFixture):
        """Mock the REST client, returning a two-track queue."""
        mock_client = mocker.Mock()
        mock_client.get_queue.return_value = {
            "queue": [
                {"title": "Song 1", "artist": "Artist 1"},
                {"title": "Song 2", "artist": "Artist 2"},
            ]
        }
        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
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
            main, ["--position-starting-at-zero", "track", "info", "-F", "pretty"]
        )

        assert json.loads(zero_based.output)["position"] == 1

    def test_queue_get_pretty(self, runner: CliRunner, mocker: MockerFixture):
        """queue get -F pretty rebases the synthetic positions."""
        self._mock_queue_client(mocker)

        one_based = runner.invoke(main, ["queue", "get", "-F", "pretty"])
        zero_based = runner.invoke(
            main, ["--position-starting-at-zero", "queue", "get", "-F", "pretty"]
        )

        assert [t["position"] for t in json.loads(one_based.output)] == [1, 2]
        assert [t["position"] for t in json.loads(zero_based.output)] == [0, 1]

    def test_queue_get_table(self, runner: CliRunner, mocker: MockerFixture):
        """queue get -F table rebases the synthetic positions."""
        self._mock_queue_client(mocker)

        one_based = runner.invoke(main, ["queue", "get", "-F", "table"])
        zero_based = runner.invoke(
            main, ["--position-starting-at-zero", "queue", "get", "-F", "table"]
        )

        assert "1. Song 1" in one_based.output
        assert "0. Song 1" in zero_based.output

    def test_queue_get_json_unaffected(self, runner: CliRunner, mocker: MockerFixture):
        """queue get -F json keeps its 1-indexed synthetic positions."""
        self._mock_queue_client(mocker)

        zero_based = runner.invoke(
            main, ["--position-starting-at-zero", "queue", "get", "-F", "json"]
        )

        assert [t["position"] for t in json.loads(zero_based.output)] == [1, 2]

    def test_play_position_starting_at_one(self, runner: CliRunner, mocker: MockerFixture):
        """With the default base, the position is decremented before the API call."""
        mock_client = mocker.Mock()
        mock_client.play.return_value = {"response": "play"}
        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["playback", "play", "-p", "1", "--no-print-resulting-status"])

        assert result.exit_code == 0
        mock_client.play.assert_called_once_with(0)

    def test_play_position_starting_at_zero(self, runner: CliRunner, mocker: MockerFixture):
        """With the zero base, the position is passed to the API unchanged."""
        mock_client = mocker.Mock()
        mock_client.play.return_value = {"response": "play"}
        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(
            main,
            [
                "--position-starting-at-zero",
                "playback",
                "play",
                "-p",
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
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        one_based = runner.invoke(main, ["playback", "play", "-p", "0"])
        zero_based = runner.invoke(
            main, ["--position-starting-at-zero", "playback", "play", "-p", "-1"]
        )

        assert one_based.exit_code != 0
        assert "position must be 1 or greater" in one_based.output
        assert zero_based.exit_code != 0
        assert "position must be 0 or greater" in zero_based.output
        mock_client.play.assert_not_called()

    def test_track_audio_template(self, runner: CliRunner, mocker: MockerFixture):
        """The {position} template key follows the indexing base."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {"position": 1, "title": "La rondine"}
        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
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
        mocker.patch("volumito.cli.volumito.requests.get", return_value=mock_response)
        mock_open = mocker.patch("builtins.open", mocker.mock_open())

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
            ],
        )

        assert result.exit_code == 0
        mock_open.assert_called_once_with(os.path.join("/tmp/music", "001_La_rondine.flac"), "wb")

    def test_albumart_template(self, runner: CliRunner, mocker: MockerFixture):
        """The {position} template key follows the indexing base for album art too."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {
            "position": 1,
            "title": "La rondine",
            "albumart": "http://volumio.local:3000/albumart?path=/mnt/x/cover.jpg",
        }
        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"data"]
        mocker.patch("volumito.cli.volumito.requests.get", return_value=mock_response)
        mock_open = mocker.patch("builtins.open", mocker.mock_open())

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
        mock_client.get_state.return_value = {"title": "Test Song"}
        mocker.patch("volumito.cli.volumito.VolumioRESTAPIClient", return_value=mock_client)
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
        assert "https://myconfig.local:9999/api/v1/getState" in result.output
        assert f"Using configuration file: {config}" in result.output

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
        assert "https://override.local:9999/api/v1/getState" in result.output
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
        assert "http://probed.local:3000/api/v1/getState" in result.output
        assert f"Using configuration file: {config}" in result.output

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
        config = self._write_config(
            tmp_path, "miscellaneous:\n  check-playlist-name: false\n"
        )

        result = runner.invoke(
            main, ["-c", config, "playlist", "play", "Nope", "--no-print-resulting-status"]
        )

        assert result.exit_code == 0
        mock_client.list_playlists.assert_not_called()
        mock_client.play_playlist.assert_called_once_with("Nope")

    def test_output_subsection_sets_format_for_playlist_list(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """The playlist-list subsection sets the format of the playlist list command."""
        mock_client = self._mock_rest_client(mocker)
        mock_client.list_playlists.return_value = ["Rock"]
        config = self._write_config(
            tmp_path, "output:\n  format: json\n  playlist-list:\n    format: table\n"
        )

        result = runner.invoke(main, ["-c", config, "playlist", "list"])

        assert result.exit_code == 0
        assert "Volumio Playlists" in result.output
        assert "1. Rock" in result.output

    def test_output_section_sets_position_indexing(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """The output section can select the zero-based position indexing."""
        mock_client = self._mock_rest_client(mocker)
        mock_client.get_state.return_value = {"title": "Test Song", "position": 1}
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
        track_result = runner.invoke(main, ["-c", config, "track", "info"])

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
        mock_client.get_system_info.return_value = {"name": "Living Room"}
        mock_client.collectionstats.return_value = {"songs": 105}
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

    def test_print_resulting_status_from_config(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """The output section can disable the resulting-status print for playback actions."""
        mocker.patch("volumito.cli.volumito.VolumioRESTAPIClient", return_value=mocker.Mock())
        mock_maybe = mocker.patch("volumito.cli.volumito.maybe_print_resulting_status")
        config = self._write_config(tmp_path, "output:\n  print-resulting-status: false\n")

        result = runner.invoke(main, ["-c", config, "playback", "toggle"])

        assert result.exit_code == 0
        mock_maybe.assert_called_once()
        assert mock_maybe.call_args.args[1] is False

    def test_print_resulting_status_default_true(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """With no config, the resulting-status print keeps its True default."""
        mocker.patch("volumito.cli.volumito.VolumioRESTAPIClient", return_value=mocker.Mock())
        mock_maybe = mocker.patch("volumito.cli.volumito.maybe_print_resulting_status")

        result = runner.invoke(main, ["playback", "toggle"])

        assert result.exit_code == 0
        mock_maybe.assert_called_once()
        assert mock_maybe.call_args.args[1] is True

    def test_downloads_per_command_output_directory_for_audio(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """A per-command downloads.audio.output-directory sets the track audio download dir."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {"title": "Test Song"}
        mocker.patch("volumito.cli.volumito.VolumioRESTAPIClient", return_value=mock_client)

        mpd = mocker.Mock()
        mpd.get_track_uri.return_value = "http://volumio.local:8000/music/test.flac"
        mpd_class = mocker.Mock(return_value=mpd)
        mpd_class.return_value.__enter__ = mocker.Mock(return_value=mpd)
        mpd_class.return_value.__exit__ = mocker.Mock(return_value=None)
        mocker.patch("volumito.cli.volumito.VolumioMPDClient", new=mpd_class)

        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"data"]
        mocker.patch("volumito.cli.volumito.requests.get", return_value=mock_response)
        # Patch open only in the volumito module so the config file (read via the
        # configuration module) is still read for real.
        mock_open = mocker.patch("volumito.cli.volumito.open", mocker.mock_open())

        config = self._write_config(
            tmp_path, "downloads:\n  track-audio:\n    output-directory: /music\n"
        )

        result = runner.invoke(main, ["-c", config, "track", "audio"])

        assert result.exit_code == 0
        mock_open.assert_called_once_with(os.path.join("/music", "test.flac"), "wb")

    def test_downloads_shared_output_directory_for_albumart(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """A shared downloads.output-directory applies to the track albumart download dir."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {"albumart": "http://example.com/images/cover.jpg"}
        mocker.patch("volumito.cli.volumito.VolumioRESTAPIClient", return_value=mock_client)

        mock_response = mocker.Mock()
        mock_response.iter_content.return_value = [b"data"]
        mocker.patch("volumito.cli.volumito.requests.get", return_value=mock_response)
        mock_open = mocker.patch("volumito.cli.volumito.open", mocker.mock_open())

        config = self._write_config(tmp_path, "downloads:\n  output-directory: /covers\n")

        result = runner.invoke(main, ["-c", config, "track", "albumart"])

        assert result.exit_code == 0
        mock_open.assert_called_once_with(os.path.join("/covers", "cover.jpg"), "wb")

    def test_no_config_uses_hardcoded_defaults(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """With no config file anywhere, the hardcoded defaults are used."""
        self._mock_rest_client(mocker)

        result = runner.invoke(main, ["-v", "playback", "status"])

        assert result.exit_code == 0
        assert "http://volumio.local:3000/api/v1/getState" in result.output
        assert "Using configuration file" not in result.output

    def test_explicit_missing_file_errors(self, runner: CliRunner, tmp_path):
        """An explicit -c path that does not exist exits 2."""
        missing = str(tmp_path / "nope.yaml")

        result = runner.invoke(main, ["-c", missing, "info"])

        assert result.exit_code == 2
        assert "configuration file not found" in result.output

    def test_malformed_config_errors(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """Malformed YAML in the config file exits 2."""
        self._mock_rest_client(mocker)
        config = self._write_config(tmp_path, "volumio: [unterminated\n")

        result = runner.invoke(main, ["-c", config, "info"])

        assert result.exit_code == 2
        assert "cannot read configuration file" in result.output

    def test_non_utf8_config_errors(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """A non-UTF-8 (binary) config file exits 2 with a readable message."""
        self._mock_rest_client(mocker)
        config = tmp_path / "volumito.yaml"
        config.write_bytes(b"\xff\xfe\x00\x01")

        result = runner.invoke(main, ["-c", str(config), "info"])

        assert result.exit_code == 2
        assert "is not a valid YAML file" in result.output

    def test_unknown_key_errors(
        self, runner: CliRunner, mocker: MockerFixture, tmp_path
    ):
        """An unrecognized key in the config file exits 2."""
        self._mock_rest_client(mocker)
        config = self._write_config(tmp_path, "volumio:\n  bogus: 1\n")

        result = runner.invoke(main, ["-c", config, "info"])

        assert result.exit_code == 2
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
                "volumio": {
                    "host": "volumio.local",
                    "scheme": "http",
                    "rest-api-port": 3000,
                    "mpd-port": 6600,
                },
                "timeouts": {
                    "rest-api-timeout": 5.0,
                    "mpd-timeout": 5.0,
                    "rest-api-sleep-before-next-call": 1.0,
                },
                "miscellaneous": {"check-playlist-name": True},
                "output": {
                    "verbose": False,
                    "machine-readable": False,
                    "position-starting-at-one": True,
                    "print-resulting-status": True,
                    "playback-status": _DISPLAY_DEFAULTS,
                    "track-info": _DISPLAY_DEFAULTS,
                    "queue-get": _DISPLAY_DEFAULTS,
                    "playlist-list": _FORMAT_DEFAULTS,
                    "zones-get": _DISPLAY_DEFAULTS,
                    "system-version": _FORMAT_DEFAULTS,
                    "system-info": _FORMAT_DEFAULTS,
                    "collection-statistics": _FORMAT_DEFAULTS,
                },
                "downloads": {
                    "track-audio": _DOWNLOAD_DEFAULTS,
                    "track-albumart": _DOWNLOAD_DEFAULTS,
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

        result = runner.invoke(main, ["configuration", "create", "-f", str(target)])

        assert result.exit_code == 0
        assert target.exists()

    def test_create_machine_readable_prints_path(self, runner: CliRunner, tmp_path):
        """In machine-readable mode create prints the quoted destination path."""
        target = tmp_path / "volumito.yaml"

        result = runner.invoke(main, ["-m", "configuration", "create", "-f", str(target)])

        assert result.exit_code == 0
        assert result.output.strip() == json.dumps(str(target))

    def test_create_mutually_exclusive(self, runner: CliRunner):
        """`-d` and `-f` together is a usage error."""
        result = runner.invoke(main, ["configuration", "create", "-d", "x", "-f", "y"])

        assert result.exit_code == 2
        assert "mutually exclusive" in result.output

    def test_create_refuses_overwrite(self, runner: CliRunner, tmp_path):
        """Without --overwrite-existing-files, create refuses to clobber."""
        target = tmp_path / "volumito.yaml"
        target.write_text("old\n")

        result = runner.invoke(main, ["configuration", "create", "-f", str(target)])

        assert result.exit_code == 1
        assert "already exists" in result.output
        assert target.read_text() == "old\n"

    def test_create_overwrite(self, runner: CliRunner, tmp_path):
        """With --overwrite-existing-files, create replaces an existing file."""
        target = tmp_path / "volumito.yaml"
        target.write_text("old\n")

        result = runner.invoke(
            main,
            ["configuration", "create", "-f", str(target), "--overwrite-existing-files"],
        )

        assert result.exit_code == 0
        assert "old" not in target.read_text()

    def test_create_write_error(self, runner: CliRunner, tmp_path, mocker: MockerFixture):
        """An OSError while writing is reported and exits 1."""
        target = tmp_path / "volumito.yaml"
        mocker.patch("volumito.cli.volumito.open", side_effect=OSError("disk full"))

        result = runner.invoke(main, ["configuration", "create", "-f", str(target)])

        assert result.exit_code == 1
        assert "cannot write configuration file" in result.output

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

    def test_check_invalid_content(self, runner: CliRunner, tmp_path):
        """An unrecognized key makes check exit 2."""
        config = tmp_path / "volumito.yaml"
        config.write_text("volumio:\n  bogus: 1\n")

        result = runner.invoke(main, ["configuration", "check", str(config)])

        assert result.exit_code == 2
        assert "unknown key 'bogus'" in result.output

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
        """In machine-readable mode check prints the grouped values as JSON."""
        config = tmp_path / "volumito.yaml"
        config.write_text("volumio:\n  host: myhost.local\n")

        result = runner.invoke(main, ["-m", "configuration", "check", str(config)])

        assert result.exit_code == 0
        assert json.loads(result.output) == {"volumio": {"host": "myhost.local"}}

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
            {"path": str(found), "found": True, "used": True},
            {"path": str(missing), "found": False, "used": False},
        ]
