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
    DOWNLOAD_KEYS,
    KEY_COMMENTS,
    OUTPUT_SCALAR_KEYS,
    SECTION_KEYS,
    build_click_default_map,
    configuration_paths,
    flatten_configuration,
    load_configuration,
    probe_configuration_paths,
    render_default_configuration,
    resolve_configuration_path,
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

# Flat param-name -> default value map, as produced from the CLI option defaults.
_DEFAULTS = {
    "host": "volumio.local",
    "scheme": "http",
    "rest_api_port": 3000,
    "mpd_port": 6600,
    "rest_api_timeout": 5.0,
    "mpd_timeout": 5.0,
    "rest_api_sleep_before_next_call": 1.0,
    "check_playlist_name": True,
    "verbose": False,
    "machine_readable": False,
    "position_starting_at_one": True,
    "fields": "short",
    "output_format": "pretty",
    "print_resulting_status": True,
    "file_name_template": "{file_name_from_uri}",
    "output_directory": None,
    "output_file": None,
    "overwrite_existing_files": False,
}


class TestConfigurationPaths:
    """Test cases for configuration_paths."""

    def test_order_and_locations(self, mocker: MockerFixture):
        """Each directory is probed for volumito.yaml then .volumito.yaml, in order."""
        mocker.patch("volumito.cli.configuration.os.getcwd", return_value="/work")
        mocker.patch("volumito.cli.configuration.os.path.expanduser", return_value="/home/user")

        paths = configuration_paths()

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


class TestProbeConfigurationPaths:
    """Test cases for probe_configuration_paths."""

    def test_flags_found_and_used(self, tmp_path, mocker: MockerFixture):
        """Every path is annotated; only the first existing one is marked used."""
        first_missing = tmp_path / "volumito.yaml"
        used = tmp_path / ".volumito.yaml"
        used.write_text("")
        also_found = tmp_path / "other.yaml"
        also_found.write_text("")
        mocker.patch(
            "volumito.cli.configuration.configuration_paths",
            return_value=[str(first_missing), str(used), str(also_found)],
        )

        assert probe_configuration_paths() == [
            (str(first_missing), False, False),
            (str(used), True, True),
            (str(also_found), True, False),
        ]

    def test_none_existing(self, mocker: MockerFixture):
        """When nothing exists, every path is flagged not found and not used."""
        mocker.patch(
            "volumito.cli.configuration.configuration_paths",
            return_value=["/a.yaml", "/b.yaml"],
        )
        mocker.patch("volumito.cli.configuration.os.path.isfile", return_value=False)

        assert probe_configuration_paths() == [
            ("/a.yaml", False, False),
            ("/b.yaml", False, False),
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

    def test_first_existing_wins(self, mocker: MockerFixture):
        """Without an explicit path, the first existing search path is returned."""
        mocker.patch(
            "volumito.cli.configuration.configuration_paths",
            return_value=["/a.yaml", "/b.yaml", "/c.yaml"],
        )
        mocker.patch(
            "volumito.cli.configuration.os.path.isfile",
            side_effect=lambda p: p == "/b.yaml",
        )

        assert resolve_configuration_path(None) == "/b.yaml"

    def test_none_found(self, mocker: MockerFixture):
        """Without an explicit path and no existing file, None is returned."""
        mocker.patch(
            "volumito.cli.configuration.configuration_paths",
            return_value=["/a.yaml", "/b.yaml"],
        )
        mocker.patch("volumito.cli.configuration.os.path.isfile", return_value=False)

        assert resolve_configuration_path(None) is None


class TestLoadDefaultMap:
    """Test cases for load_configuration."""

    def test_full_file(self, tmp_path):
        """A full config is returned as a validated nested, by-section mapping."""
        config = tmp_path / "volumito.yaml"
        config.write_text(
            "volumio:\n"
            "  host: myconfig.local\n"
            "  scheme: https\n"
            "timeouts:\n"
            "  rest-api-timeout: 7.5\n"
            "output:\n"
            "  verbose: true\n"
            "  format: table\n"
            "  playback-status:\n"
            "    format: json\n"
            "downloads:\n"
            "  output-directory: /shared\n"
            "  track-audio:\n"
            "    output-directory: /music\n"
            "  track-albumart:\n"
            "    file-name-template: '{title}.{extension}'\n"
        )

        result = load_configuration(str(config))

        assert result == {
            "volumio": {"host": "myconfig.local", "scheme": "https"},
            "timeouts": {"rest-api-timeout": 7.5},
            "output": {"verbose": True, "format": "table", "playback-status": {"format": "json"}},
            "downloads": {
                "output-directory": "/shared",
                "track-audio": {"output-directory": "/music"},
                "track-albumart": {"file-name-template": "{title}.{extension}"},
            },
        }

    def test_output_unknown_key_raises(self, tmp_path):
        """An unrecognized key directly under output raises BadParameter."""
        config = tmp_path / "volumito.yaml"
        config.write_text("output:\n  bogus: 1\n")

        with pytest.raises(click.BadParameter, match="unknown key 'bogus' in section 'output'"):
            load_configuration(str(config))

    def test_output_raw_key_no_longer_recognized(self, tmp_path):
        """The removed raw key is now reported as an unrecognized key."""
        config = tmp_path / "volumito.yaml"
        config.write_text("output:\n  raw: true\n")

        with pytest.raises(click.BadParameter, match="unknown key 'raw' in section 'output'"):
            load_configuration(str(config))

    def test_output_subsection_unknown_key_raises(self, tmp_path):
        """An unrecognized key in an output subsection raises BadParameter."""
        config = tmp_path / "volumito.yaml"
        config.write_text("output:\n  playback-status:\n    verbose: true\n")

        with pytest.raises(
            click.BadParameter, match="unknown key 'verbose' in section 'output.playback-status'"
        ):
            load_configuration(str(config))

    def test_output_subsection_non_mapping_raises(self, tmp_path):
        """An output subsection that is not a mapping raises BadParameter."""
        config = tmp_path / "volumito.yaml"
        config.write_text("output:\n  track-info: 5\n")

        with pytest.raises(click.BadParameter, match="'output.track-info'.*must be a mapping"):
            load_configuration(str(config))

    def test_miscellaneous_section(self, tmp_path):
        """The miscellaneous section accepts check-playlist-name."""
        config = tmp_path / "volumito.yaml"
        config.write_text("miscellaneous:\n  check-playlist-name: false\n")

        assert load_configuration(str(config)) == {
            "miscellaneous": {"check-playlist-name": False}
        }

    def test_miscellaneous_unknown_key_raises(self, tmp_path):
        """An unrecognized key under miscellaneous raises BadParameter."""
        config = tmp_path / "volumito.yaml"
        config.write_text("miscellaneous:\n  check-name: false\n")

        with pytest.raises(
            click.BadParameter, match="unknown key 'check-name' in section 'miscellaneous'"
        ):
            load_configuration(str(config))

    def test_downloads_unknown_key_raises(self, tmp_path):
        """An unrecognized key directly under downloads raises BadParameter."""
        config = tmp_path / "volumito.yaml"
        config.write_text("downloads:\n  bogus: 1\n")

        with pytest.raises(click.BadParameter, match="unknown key 'bogus' in section 'downloads'"):
            load_configuration(str(config))

    def test_downloads_subsection_unknown_key_raises(self, tmp_path):
        """An unrecognized key in a downloads subsection raises BadParameter."""
        config = tmp_path / "volumito.yaml"
        config.write_text("downloads:\n  track-audio:\n    bogus: 1\n")

        with pytest.raises(
            click.BadParameter, match="unknown key 'bogus' in section 'downloads.track-audio'"
        ):
            load_configuration(str(config))

    def test_downloads_null_subsection_skipped(self, tmp_path):
        """A downloads subsection present but empty (null) contributes nothing."""
        config = tmp_path / "volumito.yaml"
        config.write_text("downloads:\n  track-audio:\n")

        assert load_configuration(str(config)) == {"downloads": {}}

    def test_downloads_subsection_non_mapping_raises(self, tmp_path):
        """A downloads subsection that is not a mapping raises BadParameter."""
        config = tmp_path / "volumito.yaml"
        config.write_text("downloads:\n  track-audio: 5\n")

        with pytest.raises(click.BadParameter, match="'downloads.track-audio'.*must be a mapping"):
            load_configuration(str(config))

    def test_empty_file(self, tmp_path):
        """An empty file yields an empty mapping."""
        config = tmp_path / "volumito.yaml"
        config.write_text("")

        assert load_configuration(str(config)) == {}

    def test_null_section_skipped(self, tmp_path):
        """A section present but empty (null) contributes nothing."""
        config = tmp_path / "volumito.yaml"
        config.write_text("volumio:\n")

        assert load_configuration(str(config)) == {}

    def test_non_mapping_top_level_raises(self, tmp_path):
        """A top-level document that is not a mapping raises BadParameter."""
        config = tmp_path / "volumito.yaml"
        config.write_text("- a\n- b\n")

        with pytest.raises(click.BadParameter, match="must contain a mapping"):
            load_configuration(str(config))

    def test_unknown_section_raises(self, tmp_path):
        """An unrecognized section raises BadParameter."""
        config = tmp_path / "volumito.yaml"
        config.write_text("bogus:\n  host: x\n")

        with pytest.raises(click.BadParameter, match="unknown section 'bogus'"):
            load_configuration(str(config))

    def test_non_mapping_section_raises(self, tmp_path):
        """A section whose value is not a mapping raises BadParameter."""
        config = tmp_path / "volumito.yaml"
        config.write_text("volumio: 5\n")

        with pytest.raises(click.BadParameter, match="must be a mapping"):
            load_configuration(str(config))

    def test_unknown_key_raises(self, tmp_path):
        """An unrecognized key within a known section raises BadParameter."""
        config = tmp_path / "volumito.yaml"
        config.write_text("volumio:\n  bad-key: 1\n")

        with pytest.raises(click.BadParameter, match="unknown key 'bad-key'"):
            load_configuration(str(config))

    def test_malformed_yaml_raises(self, tmp_path):
        """Invalid YAML raises BadParameter."""
        config = tmp_path / "volumito.yaml"
        config.write_text("host: [unterminated\n")

        with pytest.raises(click.BadParameter, match="cannot read configuration file"):
            load_configuration(str(config))

    def test_non_utf8_file_raises(self, tmp_path):
        """A non-UTF-8 (e.g. binary) file raises BadParameter, not UnicodeDecodeError."""
        config = tmp_path / "volumito.yaml"
        config.write_bytes(b"\xff\xfe\x00\x01")

        with pytest.raises(click.BadParameter, match="is not a valid YAML file"):
            load_configuration(str(config))


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
        assert "(and remove this comment)\n\ndownloads:\n" in result

    def test_key_comments_present(self):
        """Each key is preceded by its explanatory comment, with units where relevant."""
        result = render_default_configuration(_DEFAULTS, "1.2.3")

        assert "# Hostname or IP address of the Volumio instance" in result
        assert "# REST API request timeout, in seconds" in result
        assert "in seconds" in result
        assert "# Fields to display: short or all" in result
        assert "# Output format: json, pretty, raw, or table" in result

    def test_comments_cover_all_keys(self):
        """KEY_COMMENTS covers exactly the flat, output, and download keys, all non-empty."""
        all_keys = (
            {key for keys in SECTION_KEYS.values() for key in keys}
            | set(OUTPUT_SCALAR_KEYS)
            | set(DOWNLOAD_KEYS)
        )

        assert set(KEY_COMMENTS) == all_keys
        assert all(comment.strip() for comment in KEY_COMMENTS.values())

    def test_downloads_subsections_rendered(self):
        """The downloads section is generated with sorted audio/albumart subsections."""
        result = render_default_configuration(_DEFAULTS, "1.2.3")
        document = yaml.safe_load(result)

        assert document["downloads"]["track-audio"] == _DOWNLOAD_DEFAULTS
        assert document["downloads"]["track-albumart"] == _DOWNLOAD_DEFAULTS
        # downloads sorts first; track-albumart before track-audio within it.
        assert "(and remove this comment)\n\ndownloads:\n" in result
        assert result.index("  track-albumart:") < result.index("  track-audio:")

    def test_output_subsections_rendered(self):
        """The output section is generated with shared scalars and display subsections."""
        result = render_default_configuration(_DEFAULTS, "1.2.3")
        document = yaml.safe_load(result)

        assert document["output"]["playback-status"] == _DISPLAY_DEFAULTS
        assert document["output"]["track-info"] == _DISPLAY_DEFAULTS
        assert document["output"]["queue-get"] == _DISPLAY_DEFAULTS
        # Shared scalars stay at the top level; fields/format only in subsections.
        assert document["output"]["verbose"] is False
        assert "fields" not in document["output"]

    def test_blank_line_after_each_key(self):
        """A single blank line follows every key within a section."""
        result = render_default_configuration(_DEFAULTS, "1.2.3")

        # Pairs valid under lexicographic ordering.
        assert "  host: volumio.local\n\n  # MPD port of the Volumio instance" in result
        # Within a subsection, keys are indented four spaces.
        assert "    fields: short\n\n    # Output format" in result

    def test_two_blank_lines_between_sections(self):
        """Two blank lines separate each section from the next."""
        result = render_default_configuration(_DEFAULTS, "1.2.3")

        assert "\n\n\ntimeouts:\n" in result
        assert "\n\n\nvolumio:\n" in result

    def test_round_trips_through_load(self, tmp_path):
        """A rendered file loaded back yields the nested config of the input defaults."""
        config = tmp_path / "volumito.yaml"
        config.write_text(render_default_configuration(_DEFAULTS, "1.2.3"))

        assert load_configuration(str(config)) == {
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


class TestFlattenConfiguration:
    """Test cases for flatten_configuration."""

    def test_flattens_nested_config(self):
        """A nested config flattens to ordered dotted-path/value pairs."""
        config = {
            "volumio": {"host": "myhost.local", "rest-api-port": 9999},
            "output": {
                "verbose": True,
                "format": "table",
                "playback-status": {"format": "json"},
            },
            "downloads": {
                "output-directory": "/shared",
                "track-audio": {"output-directory": "/music"},
                "track-albumart": {"file-name-template": "{title}.{extension}"},
            },
        }

        assert flatten_configuration(config) == [
            ("volumio.host", "myhost.local"),
            ("volumio.rest-api-port", 9999),
            ("output.verbose", True),
            ("output.format", "table"),
            ("output.playback-status.format", "json"),
            ("downloads.output-directory", "/shared"),
            ("downloads.track-audio.output-directory", "/music"),
            ("downloads.track-albumart.file-name-template", "{title}.{extension}"),
        ]

    def test_empty_config_yields_empty(self):
        """An empty config flattens to an empty list."""
        assert flatten_configuration({}) == []


class TestBuildClickDefaultMap:
    """Test cases for build_click_default_map."""

    def test_global_keys_stay_top_level(self):
        """volumio/timeouts keys and output verbose/machine-readable stay top-level."""
        result = build_click_default_map(
            {"volumio": {"host": "myhost.local"}, "output": {"verbose": True}}
        )

        assert result == {"host": "myhost.local", "verbose": True}

    def test_display_keys_replicated_under_each_command(self):
        """fields/format are nested under every command accepting them, and only those."""
        result = build_click_default_map(
            {"output": {"fields": "all", "format": "table"}}
        )

        formatting = {"fields": "all", "output_format": "table"}
        # The commands accepting only --format do not receive the shared fields value.
        format_only = {"output_format": "table"}
        assert result == {
            "playback": {"status": formatting},
            "track": {"info": formatting},
            "queue": {"get": formatting},
            "playlist": {"list": format_only},
            "zones": {"get": formatting},
            "system": {"version": format_only, "info": format_only},
            "collection": {"statistics": format_only},
            # "info" is the top-level synonym of "system info"
            "info": format_only,
        }

    def test_format_only_subsection_overrides_shared(self):
        """A subsection of a format-only command overrides the shared format value."""
        result = build_click_default_map(
            {
                "output": {
                    "format": "pretty",
                    "collection-statistics": {"format": "table"},
                }
            }
        )

        assert result["collection"]["statistics"] == {"output_format": "table"}
        assert result["system"]["info"] == {"output_format": "pretty"}

    def test_output_subsection_overrides_shared(self):
        """A per-command output subsection overrides the shared display value."""
        result = build_click_default_map(
            {
                "output": {
                    "format": "pretty",
                    "playback-status": {"format": "table"},
                    "track-info": {"format": "json"},
                }
            }
        )

        # playback-status override reaches the playback.status command.
        assert result["playback"]["status"] == {"output_format": "table"}
        assert result["track"]["info"] == {"output_format": "json"}
        # queue-get has no override, so it keeps the shared value.
        assert result["queue"]["get"] == {"output_format": "pretty"}

    def test_miscellaneous_keys_nested_under_their_command(self):
        """A miscellaneous key lands in its command slot, not at the top level."""
        result = build_click_default_map(
            {"miscellaneous": {"check-playlist-name": False}}
        )

        assert result == {"playlist": {"play": {"check_playlist_name": False}}}

    def test_print_resulting_status_replicated_under_action_commands(self):
        """print-resulting-status is nested under every playback, queue, and playlist action."""
        result = build_click_default_map({"output": {"print-resulting-status": False}})

        assert result == {
            "playback": {
                "toggle": {"print_resulting_status": False},
                "play": {"print_resulting_status": False},
                "pause": {"print_resulting_status": False},
                "stop": {"print_resulting_status": False},
                "next": {"print_resulting_status": False},
                "previous": {"print_resulting_status": False},
                "seek": {"print_resulting_status": False},
                "volume": {"print_resulting_status": False},
                "mute": {"print_resulting_status": False},
                "unmute": {"print_resulting_status": False},
            },
            "queue": {
                "clear": {"print_resulting_status": False},
                "repeat": {"print_resulting_status": False},
                "randomize": {"print_resulting_status": False},
            },
            "playlist": {
                "play": {"print_resulting_status": False},
            },
        }

    def test_downloads_shared_applies_to_both_commands(self):
        """A shared downloads key applies to both track audio and track albumart."""
        result = build_click_default_map({"downloads": {"overwrite-existing-files": True}})

        assert result == {
            "track": {
                "audio": {"overwrite_existing_files": True},
                "albumart": {"overwrite_existing_files": True},
            }
        }

    def test_downloads_per_command_overrides_shared(self):
        """A per-command subsection value overrides the shared value; templates differ."""
        result = build_click_default_map(
            {
                "downloads": {
                    "output-directory": "/shared",
                    "track-audio": {
                        "output-directory": "/music",
                        "file-name-template": "{position}.{extension}",
                    },
                    "track-albumart": {"file-name-template": "{title}.{extension}"},
                }
            }
        )

        assert result["track"]["audio"] == {
            "output_directory": "/music",
            "file_name_template": "{position}.{extension}",
        }
        assert result["track"]["albumart"] == {
            "output_directory": "/shared",
            "file_name_template": "{title}.{extension}",
        }

    def test_empty_config_no_nesting(self):
        """An empty config yields an empty default_map."""
        assert build_click_default_map({}) == {}
