"""Tests for the CLI configuration-file loading module.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

import os

import click
import pytest
import yaml
from pytest_mock import MockerFixture

from volumito.cli.configuration import (
    KEY_COMMENTS,
    SECTION_KEYS,
    build_click_default_map,
    canonical_configuration_paths,
    configuration_values_by_section,
    load_default_map,
    render_default_configuration,
    resolve_configuration_path,
)

# Flat param-name -> default value map, as produced from the CLI option defaults.
_DEFAULTS = {
    "host": "volumio.local",
    "scheme": "http",
    "rest_api_port": 3000,
    "mpd_port": 6600,
    "rest_api_timeout": 5.0,
    "mpd_timeout": 5.0,
    "rest_api_sleep_before_next_call": 1.0,
    "verbose": False,
    "machine_readable": False,
    "fields": "short",
    "output_format": "pretty",
    "raw": False,
    "print_resulting_state": True,
}


class TestCanonicalConfigurationPaths:
    """Test cases for canonical_configuration_paths."""

    def test_order_and_locations(self, mocker: MockerFixture):
        """Each directory is probed for volumito.yaml then .volumito.yaml, in order."""
        mocker.patch("volumito.cli.configuration.os.getcwd", return_value="/work")
        mocker.patch("volumito.cli.configuration.os.path.expanduser", return_value="/home/user")

        paths = canonical_configuration_paths()

        assert paths == [
            os.path.join("/work", "volumito.yaml"),
            os.path.join("/work", ".volumito.yaml"),
            os.path.join("/home/user", "volumito.yaml"),
            os.path.join("/home/user", ".volumito.yaml"),
            os.path.join("/home/user", ".volumito", "volumito.yaml"),
            os.path.join("/home/user", ".volumito", ".volumito.yaml"),
            os.path.join("/home/user", ".config", "volumito", "volumito.yaml"),
            os.path.join("/home/user", ".config", "volumito", ".volumito.yaml"),
            os.path.join("/etc", "volumito.yaml"),
            os.path.join("/etc", ".volumito.yaml"),
        ]


class TestResolveConfigurationPath:
    """Test cases for resolve_configuration_path."""

    def test_explicit_existing(self, tmp_path):
        """An explicit path that exists is returned as-is."""
        config = tmp_path / "custom.yaml"
        config.write_text("")

        assert resolve_configuration_path(str(config)) == str(config)

    def test_explicit_missing_raises(self, tmp_path):
        """An explicit path that does not exist raises BadParameter."""
        missing = str(tmp_path / "nope.yaml")

        with pytest.raises(click.BadParameter, match="configuration file not found"):
            resolve_configuration_path(missing)

    def test_canonical_first_existing_wins(self, mocker: MockerFixture):
        """Without an explicit path, the first existing canonical path is returned."""
        mocker.patch(
            "volumito.cli.configuration.canonical_configuration_paths",
            return_value=["/a.yaml", "/b.yaml", "/c.yaml"],
        )
        mocker.patch(
            "volumito.cli.configuration.os.path.isfile",
            side_effect=lambda p: p == "/b.yaml",
        )

        assert resolve_configuration_path(None) == "/b.yaml"

    def test_canonical_none_found(self, mocker: MockerFixture):
        """Without an explicit path and no canonical file, None is returned."""
        mocker.patch(
            "volumito.cli.configuration.canonical_configuration_paths",
            return_value=["/a.yaml", "/b.yaml"],
        )
        mocker.patch("volumito.cli.configuration.os.path.isfile", return_value=False)

        assert resolve_configuration_path(None) is None


class TestLoadDefaultMap:
    """Test cases for load_default_map."""

    def test_full_file(self, tmp_path):
        """A full config maps every hyphenated key to its underscore param name."""
        config = tmp_path / "volumito.yaml"
        config.write_text(
            "volumio:\n"
            "  host: myconfig.local\n"
            "  scheme: https\n"
            "  rest-api-port: 9999\n"
            "  mpd-port: 6601\n"
            "timeouts:\n"
            "  rest-api-timeout: 7.5\n"
            "  mpd-timeout: 8.5\n"
            "  rest-api-sleep-before-next-call: 2.0\n"
            "output:\n"
            "  verbose: true\n"
            "  machine-readable: false\n"
            "  fields: all\n"
            "  format: table\n"
            "  raw: true\n"
            "  print-resulting-state: false\n"
        )

        result = load_default_map(str(config))

        assert result == {
            "host": "myconfig.local",
            "scheme": "https",
            "rest_api_port": 9999,
            "mpd_port": 6601,
            "rest_api_timeout": 7.5,
            "mpd_timeout": 8.5,
            "rest_api_sleep_before_next_call": 2.0,
            "verbose": True,
            "machine_readable": False,
            "fields": "all",
            "output_format": "table",
            "raw": True,
            "print_resulting_state": False,
        }

    def test_empty_file(self, tmp_path):
        """An empty file yields an empty mapping."""
        config = tmp_path / "volumito.yaml"
        config.write_text("")

        assert load_default_map(str(config)) == {}

    def test_null_section_skipped(self, tmp_path):
        """A section present but empty (null) contributes nothing."""
        config = tmp_path / "volumito.yaml"
        config.write_text("volumio:\n")

        assert load_default_map(str(config)) == {}

    def test_non_mapping_top_level_raises(self, tmp_path):
        """A top-level document that is not a mapping raises BadParameter."""
        config = tmp_path / "volumito.yaml"
        config.write_text("- a\n- b\n")

        with pytest.raises(click.BadParameter, match="must contain a mapping"):
            load_default_map(str(config))

    def test_unknown_section_raises(self, tmp_path):
        """An unrecognized section raises BadParameter."""
        config = tmp_path / "volumito.yaml"
        config.write_text("bogus:\n  host: x\n")

        with pytest.raises(click.BadParameter, match="unknown section 'bogus'"):
            load_default_map(str(config))

    def test_non_mapping_section_raises(self, tmp_path):
        """A section whose value is not a mapping raises BadParameter."""
        config = tmp_path / "volumito.yaml"
        config.write_text("volumio: 5\n")

        with pytest.raises(click.BadParameter, match="must be a mapping"):
            load_default_map(str(config))

    def test_unknown_key_raises(self, tmp_path):
        """An unrecognized key within a known section raises BadParameter."""
        config = tmp_path / "volumito.yaml"
        config.write_text("volumio:\n  bad-key: 1\n")

        with pytest.raises(click.BadParameter, match="unknown key 'bad-key'"):
            load_default_map(str(config))

    def test_malformed_yaml_raises(self, tmp_path):
        """Invalid YAML raises BadParameter."""
        config = tmp_path / "volumito.yaml"
        config.write_text("host: [unterminated\n")

        with pytest.raises(click.BadParameter, match="cannot read configuration file"):
            load_default_map(str(config))

    def test_non_utf8_file_raises(self, tmp_path):
        """A non-UTF-8 (e.g. binary) file raises BadParameter, not UnicodeDecodeError."""
        config = tmp_path / "volumito.yaml"
        config.write_bytes(b"\xff\xfe\x00\x01")

        with pytest.raises(click.BadParameter, match="is not a valid YAML file"):
            load_default_map(str(config))


class TestRenderDefaultConfiguration:
    """Test cases for render_default_configuration."""

    def test_header_present(self):
        """The header has the title, an empty comment line, then the versioned comment."""
        result = render_default_configuration(_DEFAULTS, "1.2.3")

        assert result.startswith("# volumito CLI configuration file\n#\n")
        assert (
            "# Generated with default values for version 1.2.3: "
            "edit as needed (and remove this comment)"
        ) in result
        # A blank line separates the header from the first (lexicographically) section.
        assert "(and remove this comment)\n\noutput:\n" in result

    def test_key_comments_present(self):
        """Each key is preceded by its explanatory comment, with units where relevant."""
        result = render_default_configuration(_DEFAULTS, "1.2.3")

        assert "# Hostname or IP address of the Volumio instance" in result
        assert "# REST API request timeout, in seconds" in result
        assert "in seconds" in result
        assert "# Fields to display: short or all" in result
        assert "# Output format: json, pretty, or table" in result

    def test_comments_cover_all_keys(self):
        """KEY_COMMENTS covers exactly the keys declared in SECTION_KEYS, all non-empty."""
        all_keys = {key for keys in SECTION_KEYS.values() for key in keys}

        assert set(KEY_COMMENTS) == all_keys
        assert all(comment.strip() for comment in KEY_COMMENTS.values())

    def test_blank_line_after_each_key(self):
        """A single blank line follows every key within a section."""
        result = render_default_configuration(_DEFAULTS, "1.2.3")

        # Pairs valid under lexicographic ordering.
        assert "  host: volumio.local\n\n  # MPD port of the Volumio instance" in result
        assert "  fields: short\n\n  # Output format" in result

    def test_two_blank_lines_between_sections(self):
        """Two blank lines separate each section from the next."""
        result = render_default_configuration(_DEFAULTS, "1.2.3")

        assert "\n\n\ntimeouts:\n" in result
        assert "\n\n\nvolumio:\n" in result

    def test_round_trips_through_load(self, tmp_path):
        """A rendered file loaded back yields exactly the input defaults."""
        config = tmp_path / "volumito.yaml"
        config.write_text(render_default_configuration(_DEFAULTS, "1.2.3"))

        assert load_default_map(str(config)) == _DEFAULTS

    def test_all_sections_and_keys_present(self):
        """Every recognized section and key appears in the rendered document."""
        document = yaml.safe_load(render_default_configuration(_DEFAULTS, "1.2.3"))

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
            "output": {
                "verbose": False,
                "machine-readable": False,
                "fields": "short",
                "format": "pretty",
                "raw": False,
                "print-resulting-state": True,
            },
        }


class TestConfigurationValuesBySection:
    """Test cases for configuration_values_by_section."""

    def test_groups_present_keys(self):
        """A flat default map is regrouped into sections with hyphenated keys."""
        result = configuration_values_by_section(
            {
                "host": "myhost.local",
                "rest_api_port": 9999,
                "verbose": True,
                "output_format": "table",
            }
        )

        assert result == {
            "volumio": {"host": "myhost.local", "rest-api-port": 9999},
            "output": {"verbose": True, "format": "table"},
        }

    def test_empty_map_yields_empty(self):
        """An empty default map groups to an empty dict."""
        assert configuration_values_by_section({}) == {}


class TestBuildClickDefaultMap:
    """Test cases for build_click_default_map."""

    def test_global_keys_stay_top_level(self):
        """Non-formatting keys remain at the top level unchanged."""
        result = build_click_default_map(
            {"host": "myhost.local", "verbose": True}
        )

        assert result == {"host": "myhost.local", "verbose": True}

    def test_formatting_keys_replicated_under_each_command(self):
        """fields/output_format/raw are nested under every output command path."""
        result = build_click_default_map(
            {"host": "myhost.local", "fields": "all", "output_format": "table", "raw": True}
        )

        formatting = {"fields": "all", "output_format": "table", "raw": True}
        assert result == {
            "host": "myhost.local",
            "info": formatting,
            "player": {"state": formatting},
            "track": {"info": formatting},
            "queue": {"list": formatting},
        }

    def test_print_resulting_state_replicated_under_player_actions(self):
        """print_resulting_state is nested under every player action, not the display paths."""
        result = build_click_default_map({"print_resulting_state": False})

        assert result == {
            "player": {
                "toggle": {"print_resulting_state": False},
                "play": {"print_resulting_state": False},
                "pause": {"print_resulting_state": False},
                "stop": {"print_resulting_state": False},
                "next": {"print_resulting_state": False},
                "previous": {"print_resulting_state": False},
                "volume": {"print_resulting_state": False},
                "mute": {"print_resulting_state": False},
                "unmute": {"print_resulting_state": False},
            }
        }
        # Not applied to the display commands.
        assert "info" not in result
        assert "state" not in result["player"]

    def test_no_formatting_keys_no_nesting(self):
        """Without any command-scoped key, no command sub-dicts are added."""
        result = build_click_default_map({"host": "myhost.local"})

        assert result == {"host": "myhost.local"}
