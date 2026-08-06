"""Tests for the CLI configuration-file loading module.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

import os

import click
import pytest
from pytest_mock import MockerFixture

from volumito.cli.configuration import (
    build_click_default_map,
    configuration_paths,
    default_configuration_template,
    find_destination_conflicts,
    flatten_configuration,
    load_configuration,
    load_configuration_with_errors,
    probe_configuration_paths,
    resolve_configuration_path,
)
from volumito.cli.constants import MPD_PORT_VOLUMIO_3

# The per-command file-name-template defaults emitted in the bundled template.
_ALBUMART_FILE_NAME_TEMPLATE = "000___{album}___{artist}.{extension}"
_AUDIO_FILE_NAME_TEMPLATE = "{position:03d}___{title}___{album}___{artist}.{extension}"
_QUEUE_ALBUMART_FILE_NAME_TEMPLATE = "{artist}/{album_volume}/000___{album}.{extension}"
_QUEUE_AUDIO_FILE_NAME_TEMPLATE = (
    "{artist}/{album_volume}/{tracknumber:03d}___{title}.{extension}"
)


class TestConfigurationPaths:
    """Test cases for configuration_paths."""

    def test_order_and_locations(self, mocker: MockerFixture):
        """On POSIX each directory is probed for volumito.yaml then .volumito.yaml, in order."""
        mocker.patch("volumito.cli.configuration.os.getcwd", return_value="/work")
        mocker.patch("volumito.cli.configuration.os.path.expanduser", return_value="/home/user")
        mocker.patch("volumito.cli.configuration.os.name", "posix")

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
            os.path.join("/etc", "volumito", "volumito.yaml"),
            os.path.join("/etc", "volumito", ".volumito.yaml"),
        ]

    def test_the_working_directory_is_probed_once(self, mocker: MockerFixture):
        """A working directory that is the home directory is probed once, at the top."""
        mocker.patch("volumito.cli.configuration.os.getcwd", return_value="/home/user")
        mocker.patch("volumito.cli.configuration.os.path.expanduser", return_value="/home/user")
        mocker.patch("volumito.cli.configuration.os.name", "posix")

        paths = configuration_paths()

        assert paths == [
            os.path.join("/home/user", "volumito.yaml"),
            os.path.join("/home/user", ".volumito.yaml"),
            os.path.join("/home/user", ".volumito", "volumito.yaml"),
            os.path.join("/home/user", ".volumito", ".volumito.yaml"),
            os.path.join("/home/user", ".config", "volumito", "volumito.yaml"),
            os.path.join("/home/user", ".config", "volumito", ".volumito.yaml"),
            os.path.join("/etc", "volumito.yaml"),
            os.path.join("/etc", ".volumito.yaml"),
            os.path.join("/etc", "volumito", "volumito.yaml"),
            os.path.join("/etc", "volumito", ".volumito.yaml"),
        ]

    def test_a_probed_subdirectory_as_the_working_directory(self, mocker: MockerFixture):
        """A working directory that is one of the probed subdirectories is probed once."""
        mocker.patch(
            "volumito.cli.configuration.os.getcwd",
            return_value=os.path.join("/home/user", ".volumito"),
        )
        mocker.patch("volumito.cli.configuration.os.path.expanduser", return_value="/home/user")
        mocker.patch("volumito.cli.configuration.os.name", "posix")

        paths = configuration_paths()

        assert paths[:2] == [
            os.path.join("/home/user", ".volumito", "volumito.yaml"),
            os.path.join("/home/user", ".volumito", ".volumito.yaml"),
        ]
        assert paths.count(os.path.join("/home/user", ".volumito", "volumito.yaml")) == 1
        assert len(paths) == 10

    def test_a_symlinked_working_directory_is_probed_once(
        self, mocker: MockerFixture, tmp_path
    ):
        """A working directory reaching a probed directory by symlink is probed once."""
        home = tmp_path / "home"
        home.mkdir()
        link = tmp_path / "link"
        os.symlink(home, link)
        mocker.patch("volumito.cli.configuration.os.getcwd", return_value=str(link))
        mocker.patch("volumito.cli.configuration.os.path.expanduser", return_value=str(home))
        mocker.patch("volumito.cli.configuration.os.name", "nt")

        paths = configuration_paths()

        assert paths[:2] == [
            os.path.join(str(link), "volumito.yaml"),
            os.path.join(str(link), ".volumito.yaml"),
        ]
        assert not any(path.startswith(f"{home}{os.sep}volumito") for path in paths)
        assert len(paths) == 6

    def test_etc_omitted_on_non_posix(self, mocker: MockerFixture):
        """On non-POSIX systems (e.g., Windows) the /etc directories are not probed."""
        mocker.patch("volumito.cli.configuration.os.getcwd", return_value="/work")
        mocker.patch("volumito.cli.configuration.os.path.expanduser", return_value="/home/user")
        mocker.patch("volumito.cli.configuration.os.name", "nt")

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
        ]
        assert not any("etc" in path for path in paths)


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

    def test_miscellaneous_section_seek(self, tmp_path):
        """The miscellaneous section accepts check-seek-position."""
        config = tmp_path / "volumito.yaml"
        config.write_text("miscellaneous:\n  check-seek-position: false\n")

        assert load_configuration(str(config)) == {
            "miscellaneous": {"check-seek-position": False}
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

    def test_notification_listen_unknown_key_raises(self, tmp_path):
        """An unrecognized key in the listen subsection raises BadParameter."""
        config = tmp_path / "volumito.yaml"
        config.write_text("notification:\n  listen:\n    bogus: 1\n")

        with pytest.raises(
            click.BadParameter, match="unknown key 'bogus' in section 'notification.listen'"
        ):
            load_configuration(str(config))

    def test_notification_listen_key_at_the_section_level_raises(self, tmp_path):
        """A key of the listen subsection is not accepted at the section level."""
        config = tmp_path / "volumito.yaml"
        config.write_text("notification:\n  register-url: true\n")

        with pytest.raises(
            click.BadParameter,
            match="unknown key 'register-url' in section 'notification'",
        ):
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

    def test_queue_download_rejects_file_name_template(self, tmp_path):
        """The queue-download subsection takes audio-file-name-template only."""
        config = tmp_path / "volumito.yaml"
        config.write_text("downloads:\n  queue-download:\n    file-name-template: '{title}'\n")

        with pytest.raises(click.BadParameter, match="unknown key 'file-name-template'"):
            load_configuration(str(config))

    def test_miscellaneous_rejects_moved_download_keys(self, tmp_path):
        """The keys moved to the downloads section are unknown under miscellaneous."""
        config = tmp_path / "volumito.yaml"
        config.write_text("miscellaneous:\n  with-albumart: true\n")

        with pytest.raises(click.BadParameter, match="unknown key 'with-albumart'"):
            load_configuration(str(config))

    def test_malformed_yaml_raises(self, tmp_path):
        """Invalid YAML raises BadParameter."""
        config = tmp_path / "volumito.yaml"
        config.write_text("host: [unterminated\n")

        with pytest.raises(click.BadParameter, match="cannot read configuration file"):
            load_configuration(str(config))

    def test_non_utf8_file_raises(self, tmp_path):
        """A non-UTF-8 (e.g., binary) file raises BadParameter, not UnicodeDecodeError."""
        config = tmp_path / "volumito.yaml"
        config.write_bytes(b"\xff\xfe\x00\x01")

        with pytest.raises(click.BadParameter, match="is not a valid YAML file"):
            load_configuration(str(config))


class TestDefaultConfigurationTemplate:
    """Test cases for default_configuration_template."""

    def test_header_version_substituted(self):
        """The {VERSION} sentinel in the header is replaced with the given version."""
        result = default_configuration_template("1.2.3")

        assert result.startswith("# volumito CLI configuration file\n#\n")
        assert (
            "# Generated with default values for version 1.2.3: "
            "edit as needed (and remove this comment)"
        ) in result
        assert "{VERSION}" not in result

    def test_round_trips_through_load(self, tmp_path):
        """The emitted template loads back to the curated default values."""
        config = tmp_path / "volumito.yaml"
        config.write_text(default_configuration_template("1.2.3"))

        assert load_configuration(str(config)) == {
            "volumio": {
                "host": "volumio.local",
                "scheme": "http",
                "rest-api-port": 3000,
                "mpd-port": 6600,
                "ssh-password": None,
                "ssh-port": 22,
                "ssh-username": "volumio",
            },
            "timeouts": {
                "rest-api-timeout": 5.0,
                "rest-api-timeout-slow-endpoints": 60.0,
                "mpd-timeout": 5.0,
                "rest-api-sleep-before-next-call": 2.0,
                "rest-api-retries-on-unexpected-state": 3,
            },
            "miscellaneous": {
                "add-cover-and-metadata": True,
                "allow-local-file-rename": False,
                "check-next-track": True,
                "check-playlist-name": True,
                "check-seek-position": True,
                "propagate-remote-exit-code": True,
            },
            "notification": {
                "endpoint": "/volumionotifications",
                "port": 3003,
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
                "print-resulting-status": True,
                "verbose": False,
                # The two collection subsections pin their table format
                "collection-browse": {"format": "table"},
                "collection-search": {"format": "table"},
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

    def test_mpd_port_substituted(self, tmp_path):
        """A non-default MPD port replaces the template's Volumio 4 port."""
        config = tmp_path / "volumito.yaml"
        config.write_text(default_configuration_template("1.2.3", MPD_PORT_VOLUMIO_3))

        assert load_configuration(str(config))["volumio"]["mpd-port"] == MPD_PORT_VOLUMIO_3


class TestLoadConfigurationWithErrors:
    """Test cases for load_configuration_with_errors."""

    def test_collects_all_errors(self, tmp_path):
        """Every problem is collected; the valid parts are still returned."""
        config = tmp_path / "volumito.yaml"
        config.write_text(
            "volumio:\n  host: myhost.local\n  foo: 1\n"
            "bogus-section:\n  key: 1\n"
            "downloads:\n  bar: 2\n  output-directory: /music\n"
        )

        result, errors = load_configuration_with_errors(str(config))

        assert result == {
            "volumio": {"host": "myhost.local", "foo": 1},
            "downloads": {"output-directory": "/music"},
        }
        assert len(errors) == 3
        assert "unknown key 'foo'" in errors[0]
        assert "unknown section 'bogus-section'" in errors[1]
        assert "unknown key 'bar'" in errors[2]

    def test_valid_file_has_no_errors(self, tmp_path):
        """A valid file yields the mapping and an empty error list."""
        config = tmp_path / "volumito.yaml"
        config.write_text("volumio:\n  host: myhost.local\n")

        assert load_configuration_with_errors(str(config)) == (
            {"volumio": {"host": "myhost.local"}},
            [],
        )

    def test_unreadable_file_is_a_single_error(self, tmp_path):
        """A file that does not parse yields an empty mapping and one error."""
        config = tmp_path / "notes.md"
        config.write_text("# Title\n\n- a list\nkey: [\n")

        result, errors = load_configuration_with_errors(str(config))

        assert result == {}
        assert len(errors) == 1
        assert "cannot read configuration file" in errors[0]

    def test_non_mapping_subsection_is_skipped(self, tmp_path):
        """A non-mapping subsection is reported and the rest is kept."""
        config = tmp_path / "volumito.yaml"
        config.write_text("downloads:\n  track-audio: 5\n  output-directory: /music\n")

        result, errors = load_configuration_with_errors(str(config))

        assert result == {"downloads": {"output-directory": "/music"}}
        assert len(errors) == 1
        assert "must be a mapping" in errors[0]

    def test_valid_aliases_are_kept(self, tmp_path):
        """The aliases section maps free-form names to command path strings."""
        config = tmp_path / "volumito.yaml"
        config.write_text("aliases:\n  cover: track albumart\n  play: playback play\n")

        assert load_configuration_with_errors(str(config)) == (
            {"aliases": {"cover": "track albumart", "play": "playback play"}},
            [],
        )

    def test_invalid_aliases_are_reported(self, tmp_path):
        """A non-string alias name, and a non-string or blank target, are reported."""
        config = tmp_path / "volumito.yaml"
        config.write_text(
            "aliases:\n  1: playback play\n  bad: [not, a, string]\n"
            '  blank: "  "\n  cover: track albumart\n'
        )

        result, errors = load_configuration_with_errors(str(config))

        assert result == {"aliases": {"cover": "track albumart"}}
        assert len(errors) == 3
        assert "alias name 1 in configuration file" in errors[0]
        assert "alias 'bad' in configuration file" in errors[1]
        assert "alias 'blank' in configuration file" in errors[2]


class TestFindDestinationConflicts:
    """Test cases for find_destination_conflicts."""

    def test_no_downloads_section(self):
        """A configuration without downloads has no conflicts."""
        assert find_destination_conflicts({}) == []

    def test_shared_both_destinations(self):
        """Shared output-file and output-directory conflict for both track commands."""
        config = {"downloads": {"output-directory": "/covers", "output-file": "/tmp/out.jpg"}}

        assert find_destination_conflicts(config) == [
            ("track-albumart", "downloads", "downloads"),
            ("track-audio", "downloads", "downloads"),
        ]

    def test_shared_file_with_subsection_directory(self):
        """A shared output-file conflicts with a subsection output-directory."""
        config = {
            "downloads": {
                "output-file": "/tmp/out.flac",
                "track-audio": {"output-directory": "/music"},
            }
        }

        assert find_destination_conflicts(config) == [("track-audio", "downloads", "track-audio")]

    def test_subsection_both_destinations(self):
        """A subsection setting both destinations conflicts only for that command."""
        config = {
            "downloads": {
                "track-albumart": {
                    "output-directory": "/covers",
                    "output-file": "/tmp/out.jpg",
                }
            }
        }

        assert find_destination_conflicts(config) == [
            ("track-albumart", "track-albumart", "track-albumart")
        ]

    def test_null_values_do_not_conflict(self):
        """Explicit nulls (as in the bundled template) do not count as set."""
        config = {"downloads": {"output-directory": "/covers", "output-file": None}}

        assert find_destination_conflicts(config) == []

    def test_shared_file_does_not_reach_queue_download(self):
        """A shared output-file never conflicts with a queue/playlist download directory."""
        config = {
            "downloads": {
                "output-file": "/tmp/out.flac",
                "queue-download": {"output-directory": "/music"},
            }
        }

        assert find_destination_conflicts(config) == []


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
                "queue-download": {"audio-file-name-template": "{album}/{title}.{extension}"},
            },
        }

        assert flatten_configuration(config) == [
            ("downloads.output-directory", "/shared"),
            ("downloads.queue-download.audio-file-name-template", "{album}/{title}.{extension}"),
            ("downloads.track-albumart.file-name-template", "{title}.{extension}"),
            ("downloads.track-audio.output-directory", "/music"),
            ("output.format", "table"),
            ("output.playback-status.format", "json"),
            ("output.verbose", True),
            ("volumio.host", "myhost.local"),
            ("volumio.rest-api-port", 9999),
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
            "alias": {"list": format_only},
            "playback": {"status": formatting},
            "track": {"info": formatting},
            "queue": {"list": formatting, "status": formatting},
            "notification": {"list": format_only, "listen": format_only},
            "playlist": {"list": format_only},
            "multiroom": {"zones": formatting},
            "system": {
                "execute": format_only,
                "version": format_only,
                "info": format_only,
            },
            "collection": {
                "browse": format_only,
                "search": format_only,
                "statistics": format_only,
            },
            "story": {
                "album": formatting,
                "artist": formatting,
                "credits": formatting,
                "label": formatting,
                "place": formatting,
            },
            # "info" is the top-level synonym of "system info"
            "info": format_only,
        }

    def test_notification_keys_reach_their_commands(self):
        """The scalars reach the three subcommands, the listen keys only that one."""
        result = build_click_default_map(
            {
                "notification": {
                    "endpoint": "/hook",
                    "port": 9000,
                    "listen": {"count": 4, "idle-timeout": 5.0, "register-url": True},
                }
            }
        )

        assert result["notification"] == {
            "listen": {
                "endpoint": "/hook",
                "port": 9000,
                "count": 4,
                "idle_timeout": 5.0,
                "register_url": True,
            },
            "register": {"endpoint": "/hook", "port": 9000},
            "unregister": {"endpoint": "/hook", "port": 9000},
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
        # queue-list has no override, so it keeps the shared value.
        assert result["queue"]["list"] == {"output_format": "pretty"}

    def test_shared_manifest_file_reaches_only_queue_and_playlist_download(self):
        """A shared downloads.manifest-file flows to the queue/playlist downloads only."""
        result = build_click_default_map(
            {"downloads": {"manifest-file": "/reports/run.json"}}
        )

        assert result["queue"]["download"]["manifest_file"] == "/reports/run.json"
        assert result["playlist"]["download"]["manifest_file"] == "/reports/run.json"
        # The key never reaches the track commands (nothing else is shared here,
        # so their default-map entries are not even created).
        assert "manifest_file" not in result.get("track", {}).get("audio", {})
        assert "manifest_file" not in result.get("track", {}).get("albumart", {})

    def test_story_subsection_overrides_shared(self):
        """A per-command story subsection overrides the shared display value."""
        result = build_click_default_map(
            {
                "output": {
                    "format": "pretty",
                    "story-album": {"format": "table"},
                }
            }
        )

        assert result["story"]["album"] == {"output_format": "table"}
        # The sibling story commands keep the shared value.
        assert result["story"]["artist"] == {"output_format": "pretty"}

    def test_miscellaneous_keys_nested_under_their_command(self):
        """The miscellaneous keys land in their command slot, not at the top level."""
        result = build_click_default_map(
            {
                "miscellaneous": {
                    "check-playlist-name": False,
                    "check-seek-position": False,
                }
            }
        )

        assert result == {
            "playlist": {
                "download": {"check_playlist_name": False},
                "play": {"check_playlist_name": False},
            },
            "playback": {"seek": {"check_seek_position": False}},
        }

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
                "download": {"print_resulting_status": False},
                "play": {"print_resulting_status": False},
            },
        }

    def test_downloads_shared_applies_to_both_commands(self):
        """A shared downloads key applies to every download command."""
        result = build_click_default_map({"downloads": {"overwrite-existing-files": True}})

        assert result == {
            "playlist": {"download": {"overwrite_existing_files": True}},
            "queue": {"download": {"overwrite_existing_files": True}},
            "track": {
                "audio": {"overwrite_existing_files": True},
                "albumart": {"overwrite_existing_files": True},
            },
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
