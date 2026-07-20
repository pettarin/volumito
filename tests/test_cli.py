"""Tests for the CLI module.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

import json

import click
import pytest
import requests
from click.testing import CliRunner
from pytest_mock import MockerFixture

from volumito.cli.volumito import (
    QUEUE_SHORT_FIELDS,
    SHORT_FIELDS,
    VolumeParamType,
    filter_fields,
    filter_queue_fields,
    format_as_json,
    format_as_pretty,
    format_as_table,
    format_queue_as_table,
    main,
)
from volumito.clients.rest import (
    VolumioAPIError,
    VolumioConnectionError,
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

        # Should only include SHORT_FIELDS
        for field in SHORT_FIELDS:
            if field in state:
                assert field in result

        # volume and mute are now part of the short field set
        assert "volume" in result
        assert "mute" in result

        # Audio-quality fields are no longer part of the short field set
        assert "samplerate" not in result
        assert "bitdepth" not in result
        assert "channels" not in result
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

        assert "Volumio State" in result
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

        assert "Volumio State" in result
        assert "Test" in result


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


class TestCLICommands:
    """Test cases for CLI commands using CliRunner."""

    @pytest.fixture
    def runner(self):
        """Create a CliRunner instance."""
        return CliRunner()

    @pytest.fixture(autouse=True)
    def _no_resulting_state(self, mocker: MockerFixture):
        """Isolate per-command tests from the print-resulting-state feature.

        Player action subcommands print the resulting "player state" by default;
        no-op the helper here so these tests stay focused (and fast). The feature
        itself is covered by TestPrintResultingState.
        """
        mocker.patch("volumito.cli.volumito.maybe_print_resulting_state")

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
        assert "volumito, version 0.0.9" in result.output

    def test_version_command_machine_readable(self, runner: CliRunner):
        """Test --machine-readable version prints the quoted version string."""
        result = runner.invoke(main, ["--machine-readable", "version"])

        assert result.exit_code == 0
        assert result.output.strip() == '"0.0.9"'
        assert "volumito" not in result.output
        assert "version" not in result.output

    def test_version_command_machine_readable_shorthand(self, runner: CliRunner):
        """Test the -m shorthand for --machine-readable with the version subcommand."""
        result = runner.invoke(main, ["-m", "version"])

        assert result.exit_code == 0
        assert result.output.strip() == '"0.0.9"'

    def test_info_help(self, runner: CliRunner):
        """Test info command with --help."""
        result = runner.invoke(main, ["info", "--help"])

        assert result.exit_code == 0
        assert "--format" in result.output
        assert "--fields" in result.output
        # Global options like --scheme and --host are shown in main --help, not subcommand help

    def test_info_success_default(self, runner: CliRunner, mocker: MockerFixture):
        """Test successful info command with default options."""
        # Mock VolumioRESTAPIClient
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

        result = runner.invoke(main, ["info"])

        assert result.exit_code == 0
        assert "Test Song" in result.output

    def test_player_state_help(self, runner: CliRunner):
        """Test player state command with --help."""
        result = runner.invoke(main, ["player", "state", "--help"])

        assert result.exit_code == 0
        assert "--format" in result.output
        assert "--fields" in result.output
        # Short options
        assert "-F" in result.output
        assert "-L" in result.output
        assert "-R" in result.output

    def test_player_state_success_default(self, runner: CliRunner, mocker: MockerFixture):
        """Test player state (the canonical form of info) with default options."""
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

        result = runner.invoke(main, ["player", "state"])

        assert result.exit_code == 0
        assert "Test Song" in result.output

    def test_info_with_custom_host(self, runner: CliRunner, mocker: MockerFixture):
        """Test info command with custom host."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {"title": "Test"}

        mock_client_class = mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["--host", "192.168.1.100", "info"])

        assert result.exit_code == 0
        mock_client_class.assert_called_once()
        host_configuration = mock_client_class.call_args[0][0]
        assert host_configuration.host == "192.168.1.100"

    def test_info_with_format_json(self, runner: CliRunner, mocker: MockerFixture):
        """Test info command with --format json."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {"title": "Test"}

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["info", "--format", "json"])

        assert result.exit_code == 0
        # Should be valid JSON
        output_data = json.loads(result.output)
        assert output_data["title"] == "Test"

    def test_info_with_format_table(self, runner: CliRunner, mocker: MockerFixture):
        """Test info command with --format table."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {"title": "Test Song"}

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["info", "--format", "table"])

        assert result.exit_code == 0
        assert "Volumio State" in result.output
        assert "Test Song" in result.output

    def test_info_with_fields_all(self, runner: CliRunner, mocker: MockerFixture):
        """Test info command with --fields all."""
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

        result = runner.invoke(main, ["info", "--fields", "all"])

        assert result.exit_code == 0
        output_data = json.loads(result.output)
        assert "extra" in output_data

    def test_info_with_fields_short(self, runner: CliRunner, mocker: MockerFixture):
        """Test info command with --fields short."""
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

        result = runner.invoke(main, ["info", "--fields", "short"])

        assert result.exit_code == 0
        output_data = json.loads(result.output)
        assert "title" in output_data
        assert "volume" in output_data
        assert "extra" not in output_data

    def test_info_with_raw_flag(self, runner: CliRunner, mocker: MockerFixture):
        """Test info command with --raw flag."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {"title": "Test", "volume": 100}

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["info", "--raw"])

        assert result.exit_code == 0
        output_data = json.loads(result.output)
        # Raw should include all fields
        assert "title" in output_data
        assert "volume" in output_data

    def test_short_option_host(self, runner: CliRunner, mocker: MockerFixture):
        """Test the -H shorthand for --host."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {"title": "Test"}

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
        mock_client.get_state.return_value = {"title": "Test"}

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
        """Test the -F shorthand for --format."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {"title": "Test Song"}

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["info", "-F", "table"])

        assert result.exit_code == 0
        assert "Volumio State" in result.output
        assert "Test Song" in result.output

    def test_short_option_fields(self, runner: CliRunner, mocker: MockerFixture):
        """Test the -L shorthand for --fields."""
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

        result = runner.invoke(main, ["info", "-L", "all"])

        assert result.exit_code == 0
        output_data = json.loads(result.output)
        assert "extra" in output_data

    def test_short_option_raw(self, runner: CliRunner, mocker: MockerFixture):
        """Test the -R shorthand for --raw."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {"title": "Test", "volume": 100}

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["info", "-R"])

        assert result.exit_code == 0
        output_data = json.loads(result.output)
        assert "title" in output_data
        assert "volume" in output_data

    def test_short_option_position(self, runner: CliRunner, mocker: MockerFixture):
        """Test the -p shorthand for --position on player play."""
        mock_client = mocker.Mock()
        mock_client.play.return_value = {"response": "play"}

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["player", "play", "-p", "3"])

        assert result.exit_code == 0
        # Position is 1-indexed on the CLI, 0-indexed to the client
        mock_client.play.assert_called_once_with(2)

    def test_info_with_verbose(self, runner: CliRunner, mocker: MockerFixture):
        """Test info command with --verbose flag."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {"title": "Test"}

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
        mock_client.get_state.side_effect = VolumioConnectionError("Connection failed")

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
        mock_client.get_state.side_effect = VolumioAPIError("API error")

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
        mock_client.get_state.side_effect = VolumioConnectionError("Connection failed")

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["--machine-readable", "info"])

        assert result.exit_code == 1
        # No error output with machine-readable flag
        assert result.output == ""

    def test_player_help(self, runner: CliRunner):
        """Test player group with --help."""
        result = runner.invoke(main, ["player", "--help"])

        assert result.exit_code == 0
        assert "player" in result.output.lower()
        assert "state" in result.output.lower()
        assert "toggle" in result.output.lower()
        assert "play" in result.output.lower()
        assert "pause" in result.output.lower()
        assert "volume" in result.output.lower()
        assert "mute" in result.output.lower()
        assert "unmute" in result.output.lower()

    def test_player_no_subcommand(self, runner: CliRunner):
        """Test player group without subcommand."""
        result = runner.invoke(main, ["player"])

        # Click returns exit code 2 when a group is invoked without a subcommand
        assert result.exit_code == 2
        assert "player" in result.output.lower()
        # Should show usage/error information when no subcommand is provided
        assert "toggle" in result.output.lower() or "play" in result.output.lower()

    def test_toggle_help(self, runner: CliRunner):
        """Test toggle command with --help."""
        result = runner.invoke(main, ["player", "toggle", "--help"])

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

        result = runner.invoke(main, ["player", "toggle"])

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

        result = runner.invoke(main, ["--host", "192.168.1.50", "player", "toggle"])

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

        result = runner.invoke(main, ["--verbose", "player", "toggle"])

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

        result = runner.invoke(main, ["player", "toggle"])

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

        result = runner.invoke(main, ["player", "toggle"])

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

        result = runner.invoke(main, ["player", "play"])

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

        result = runner.invoke(main, ["player", "play"])

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

        result = runner.invoke(main, ["--verbose", "player", "play"])

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

        result = runner.invoke(main, ["player", "pause"])

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

        result = runner.invoke(main, ["player", "pause"])

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

        result = runner.invoke(main, ["--machine-readable", "player", "pause"])

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

        result = runner.invoke(main, ["player", "stop"])

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

        result = runner.invoke(main, ["player", "stop"])

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

        result = runner.invoke(main, ["player", "next"])

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
                "player", "next"
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

        result = runner.invoke(main, ["player", "previous"])

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

        result = runner.invoke(main, ["player", "previous"])

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

        result = runner.invoke(main, ["--machine-readable", "player", "play"])

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

        result = runner.invoke(main, ["--verbose", "player", "stop"])

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

        result = runner.invoke(main, ["player", "next"])

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

        result = runner.invoke(main, ["player", "previous"])

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

        result = runner.invoke(main, ["--machine-readable", "player", "toggle"])

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

        result = runner.invoke(main, ["player", "play"])

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

        result = runner.invoke(main, ["player", "pause"])

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

        result = runner.invoke(main, ["player", "stop"])

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

        result = runner.invoke(main, ["player", "next"])

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

        result = runner.invoke(main, ["--verbose", "player", "pause"])

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

        result = runner.invoke(main, ["--verbose", "player", "next"])

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

        result = runner.invoke(main, ["--verbose", "player", "previous"])

        assert result.exit_code == 0
        assert "Connecting to" in result.output
        assert "Response:" in result.output

    def test_volume_help(self, runner: CliRunner):
        """Test player volume command with --help."""
        result = runner.invoke(main, ["player", "volume", "--help"])

        assert result.exit_code == 0
        assert "volume" in result.output.lower()

    def test_volume_absolute_success(self, runner: CliRunner, mocker: MockerFixture):
        """Test player volume with an absolute integer level."""
        mock_client = mocker.Mock()
        mock_client.volume.return_value = {"response": "volume"}

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["player", "volume", "50"])

        assert result.exit_code == 0
        assert "Command 'volume 50' executed successfully" in result.output
        # The value reaches the client as an int
        mock_client.volume.assert_called_once_with(50)

    def test_volume_no_value_prints_current(self, runner: CliRunner, mocker: MockerFixture):
        """Test player volume without a value prints the current volume."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {"volume": 42, "title": "Test"}

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["player", "volume"])

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
        """Test player volume normalizes step aliases to the canonical keyword."""
        mock_client = mocker.Mock()
        mock_client.volume.return_value = {"response": "volume"}

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["player", "volume", spelling])

        assert result.exit_code == 0
        mock_client.volume.assert_called_once_with(canonical)

    @pytest.mark.parametrize("keyword", ["mute", "unmute", "plus", "minus"])
    def test_volume_keyword_success(
        self, runner: CliRunner, mocker: MockerFixture, keyword: str
    ):
        """Test player volume with each accepted keyword value."""
        mock_client = mocker.Mock()
        mock_client.volume.return_value = {"response": "volume"}

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["player", "volume", keyword])

        assert result.exit_code == 0
        mock_client.volume.assert_called_once_with(keyword)

    @pytest.mark.parametrize("level", ["0", "100"])
    def test_volume_boundaries(self, runner: CliRunner, mocker: MockerFixture, level: str):
        """Test player volume accepts the 0 and 100 boundary levels."""
        mock_client = mocker.Mock()
        mock_client.volume.return_value = {"response": "volume"}

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["player", "volume", level])

        assert result.exit_code == 0
        mock_client.volume.assert_called_once_with(int(level))

    @pytest.mark.parametrize("bad_value", ["101", "-1", "foo", "UP", "+"])
    def test_volume_invalid(self, runner: CliRunner, mocker: MockerFixture, bad_value: str):
        """Test player volume rejects out-of-range, non-numeric, and non-lowercase values."""
        mock_client = mocker.Mock()

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["player", "volume", bad_value])

        # Click reports a usage error (exit code 2) and never calls the client
        assert result.exit_code == 2
        mock_client.volume.assert_not_called()

    def test_mute_synonym(self, runner: CliRunner, mocker: MockerFixture):
        """Test player mute is a synonym for player volume mute."""
        mock_client = mocker.Mock()
        mock_client.volume.return_value = {"response": "volume"}

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["player", "mute"])

        assert result.exit_code == 0
        assert "Command 'volume mute' executed successfully" in result.output
        mock_client.volume.assert_called_once_with("mute")

    def test_unmute_synonym(self, runner: CliRunner, mocker: MockerFixture):
        """Test player unmute is a synonym for player volume unmute."""
        mock_client = mocker.Mock()
        mock_client.volume.return_value = {"response": "volume"}

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["player", "unmute"])

        assert result.exit_code == 0
        assert "Command 'volume unmute' executed successfully" in result.output
        mock_client.volume.assert_called_once_with("unmute")

    def test_track_help(self, runner: CliRunner):
        """Test track group with --help."""
        result = runner.invoke(main, ["track", "--help"])

        assert result.exit_code == 0
        assert "track" in result.output.lower()
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
        # In machine-readable mode, only the URI should be printed
        assert "http://volumio.local:8000/music/test.flac" in result.output
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

    def test_audio_with_output_file_auto_generated(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """Test audio command with -o flag (auto-generates filename)."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {
            "position": 2,
            "title": "My Song!",
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

        result = runner.invoke(main, ["track", "audio", "-o", ""])

        assert result.exit_code == 0
        assert "http://volumio.local:8000/music/test.flac" in result.output
        assert "successfully downloaded" in result.output
        mock_get.assert_called_once()
        # Verify filename was auto-generated (position 2 = track 3, sanitized title)
        mock_open.assert_called_once_with("003_My_Song.flac", "wb")

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

    def test_albumart_with_absolute_url(self, runner: CliRunner, mocker: MockerFixture):
        """Test albumart command with absolute URL."""
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

    def test_albumart_with_relative_url(self, runner: CliRunner, mocker: MockerFixture):
        """Test albumart command with relative URL path."""
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
        assert "No album art URL found" in result.output

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
        assert "Album art URL:" in result.output

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
        # In machine-readable mode, only the URL should be printed
        assert "http://example.com/albumart.jpg" in result.output
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

    def test_albumart_with_output_file_auto_generated_from_query_param(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """Test albumart command with -o flag auto-generates filename from query param URL."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {
            "album": "Due, la nostra storia",
            "albumart": "/albumart?path=albumart.jpg",
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

        result = runner.invoke(main, ["track", "albumart", "-o", ""])

        assert result.exit_code == 0
        assert "http://volumio.local:3000/albumart?path=albumart.jpg" in result.output
        assert "successfully downloaded" in result.output
        mock_get.assert_called_once()
        # Verify filename was auto-generated from album with extension from query param
        mock_open.assert_called_once_with("000_Due_la_nostra_storia.jpg", "wb")

    def test_albumart_with_output_file_auto_generated_from_path(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """Test albumart command with -o flag auto-generates filename from direct path URL."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {
            "album": "Test Album",
            "albumart": "http://example.com/images/cover.png",
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

        result = runner.invoke(main, ["track", "albumart", "-o", ""])

        assert result.exit_code == 0
        assert "http://example.com/images/cover.png" in result.output
        assert "successfully downloaded" in result.output
        mock_get.assert_called_once()
        # Verify filename was auto-generated from album with extension from path
        mock_open.assert_called_once_with("000_Test_Album.png", "wb")

    def test_albumart_with_output_file_auto_generated_no_extension(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """Test albumart command auto-generates filename with no extension (defaults to jpg)."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {
            "album": "Unknown Album",
            "albumart": "/albumart",
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

        result = runner.invoke(main, ["track", "albumart", "-o", ""])

        assert result.exit_code == 0
        assert "http://volumio.local:3000/albumart" in result.output
        assert "successfully downloaded" in result.output
        mock_get.assert_called_once()
        # Verify filename was auto-generated with default 'jpg' extension
        mock_open.assert_called_once_with("000_Unknown_Album.jpg", "wb")

    def test_albumart_with_output_file_auto_generated_missing_album(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """Test albumart command with -o flag auto-generates filename when album is missing."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {
            "albumart": "/albumart?path=image.jpg",
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

        result = runner.invoke(main, ["track", "albumart", "-o", ""])

        assert result.exit_code == 0
        assert "http://volumio.local:3000/albumart?path=image.jpg" in result.output
        assert "successfully downloaded" in result.output
        mock_get.assert_called_once()
        # Verify filename was auto-generated with 'unknown' as album name
        mock_open.assert_called_once_with("000_unknown.jpg", "wb")

    def test_albumart_with_output_file_auto_generated_special_chars(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """Test albumart command with -o flag sanitizes special characters in album name."""
        mock_client = mocker.Mock()
        mock_client.get_state.return_value = {
            "album": "My Album: Special/Edition (2023)!",
            "albumart": "/albumart?path=albumart.jpg",
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

        result = runner.invoke(main, ["track", "albumart", "-o", ""])

        assert result.exit_code == 0
        assert "http://volumio.local:3000/albumart?path=albumart.jpg" in result.output
        assert "successfully downloaded" in result.output
        mock_get.assert_called_once()
        # Verify filename was auto-generated with sanitized album name
        mock_open.assert_called_once_with("000_My_Album_Special_Edition_2023.jpg", "wb")

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

        result = runner.invoke(main, ["queue", "list"])

        assert result.exit_code == 0
        assert "Song 1" in result.output
        assert "Song 2" in result.output

    def test_queue_list_with_custom_host(self, runner: CliRunner, mocker: MockerFixture):
        """Test queue list command with custom host."""
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

        result = runner.invoke(main, ["--host", "192.168.1.100", "queue", "list"])

        assert result.exit_code == 0
        host_configuration = mock_client_class.call_args[0][0]
        assert host_configuration.host == "192.168.1.100"

    def test_queue_list_with_format_json(self, runner: CliRunner, mocker: MockerFixture):
        """Test queue list command with --format json."""
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
        mock_client.get_queue.return_value = {
            "queue": [
                {"title": "Test Song", "artist": "Test Artist", "duration": 180}
            ]
        }

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["queue", "list", "--format", "table"])

        assert result.exit_code == 0
        assert "Volumio Queue" in result.output
        assert "Test Song" in result.output

    def test_queue_list_with_fields_all(self, runner: CliRunner, mocker: MockerFixture):
        """Test queue list command with --fields all."""
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

        result = runner.invoke(main, ["queue", "list", "--fields", "all"])

        assert result.exit_code == 0
        output_data = json.loads(result.output)
        assert "extra_field" in output_data[0]

    def test_queue_list_with_fields_short(self, runner: CliRunner, mocker: MockerFixture):
        """Test queue list command with --fields short."""
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

        result = runner.invoke(main, ["queue", "list", "--fields", "short"])

        assert result.exit_code == 0
        output_data = json.loads(result.output)
        assert "title" in output_data[0]
        assert "artist" in output_data[0]
        assert "extra_field" not in output_data[0]

    def test_queue_list_with_raw_flag(self, runner: CliRunner, mocker: MockerFixture):
        """Test queue list command with --raw flag."""
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

        result = runner.invoke(main, ["queue", "list", "--raw"])

        assert result.exit_code == 0
        output_data = json.loads(result.output)
        # Raw should include all fields from the original response
        assert "queue" in output_data
        assert "extra_field" in output_data["queue"][0]

    def test_queue_list_with_verbose(self, runner: CliRunner, mocker: MockerFixture):
        """Test queue list command with --verbose flag."""
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

        result = runner.invoke(main, ["--verbose", "queue", "list"])

        assert result.exit_code == 0
        assert "Connecting to" in result.output or "Successfully retrieved" in result.output

    def test_queue_list_connection_error(self, runner: CliRunner, mocker: MockerFixture):
        """Test queue list command with connection error."""
        mock_client = mocker.Mock()
        mock_client.get_queue.side_effect = VolumioConnectionError("Connection failed")

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["queue", "list"])

        assert result.exit_code == 1
        assert "Connection error" in result.output

    def test_queue_list_api_error(self, runner: CliRunner, mocker: MockerFixture):
        """Test queue list command with API error."""
        mock_client = mocker.Mock()
        mock_client.get_queue.side_effect = VolumioAPIError("API error")

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
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
        mock_client.get_queue.side_effect = VolumioConnectionError("Connection failed")

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["--machine-readable", "queue", "list"])

        assert result.exit_code == 1
        # No error output with machine-readable flag
        assert result.output == ""

    def test_queue_list_empty_queue(self, runner: CliRunner, mocker: MockerFixture):
        """Test queue list command with empty queue."""
        mock_client = mocker.Mock()
        mock_client.get_queue.return_value = {"queue": []}

        mocker.patch(
            "volumito.cli.volumito.VolumioRESTAPIClient",
            return_value=mock_client,
        )

        result = runner.invoke(main, ["queue", "list", "--format", "table"])

        assert result.exit_code == 0
        assert "Volumio Queue" in result.output
        assert "(empty)" in result.output


class TestPrintResultingState:
    """Test cases for the -r/--print-resulting-state option on player commands."""

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

    def test_default_prints_resulting_state(self, runner: CliRunner, mocker: MockerFixture):
        """By default, a player action waits 1 second and prints the resulting state."""
        mock_client, mock_sleep = self._mock_client(mocker)

        result = runner.invoke(main, ["player", "pause"])

        assert result.exit_code == 0
        assert "Command 'pause' executed successfully" in result.output
        # The resulting state is printed after the command
        assert "Test Song" in result.output
        mock_sleep.assert_called_once_with(1.0)
        mock_client.get_state.assert_called_once()

    def test_no_print_resulting_state(self, runner: CliRunner, mocker: MockerFixture):
        """--no-print-resulting-state skips the sleep and the state print."""
        mock_client, mock_sleep = self._mock_client(mocker)

        result = runner.invoke(main, ["player", "pause", "--no-print-resulting-state"])

        assert result.exit_code == 0
        assert "Command 'pause' executed successfully" in result.output
        assert "Test Song" not in result.output
        mock_sleep.assert_not_called()
        mock_client.get_state.assert_not_called()

    def test_short_flag_prints_resulting_state(self, runner: CliRunner, mocker: MockerFixture):
        """The -r short flag behaves like the enabled default."""
        mock_client, mock_sleep = self._mock_client(mocker)

        result = runner.invoke(main, ["player", "pause", "-r"])

        assert result.exit_code == 0
        assert "Test Song" in result.output
        mock_sleep.assert_called_once_with(1.0)

    def test_command_with_argument_prints_resulting_state(
        self, runner: CliRunner, mocker: MockerFixture
    ):
        """A command taking an argument (volume) also prints the resulting state."""
        mock_client, mock_sleep = self._mock_client(mocker)

        result = runner.invoke(main, ["player", "volume", "50"])

        assert result.exit_code == 0
        assert "Test Song" in result.output
        mock_client.volume.assert_called_once_with(50)
        mock_sleep.assert_called_once_with(1.0)

    def test_custom_sleep_before_next_call(self, runner: CliRunner, mocker: MockerFixture):
        """--rest-api-sleep-before-next-call sets the pause before the resulting-state fetch."""
        mock_client, mock_sleep = self._mock_client(mocker)

        result = runner.invoke(
            main, ["--rest-api-sleep-before-next-call", "0.5", "player", "pause"]
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
        # Should include only SHORT_FIELDS
        for field in QUEUE_SHORT_FIELDS:
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
