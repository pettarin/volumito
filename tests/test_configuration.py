"""Tests for the CLI configuration-file loading module.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

import os

import click
import pytest
from pytest_mock import MockerFixture

from volumito.cli.configuration import (
    canonical_configuration_paths,
    load_default_map,
    resolve_configuration_path,
)


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
            "verbosity:\n"
            "  verbose: true\n"
            "  machine-readable: false\n"
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
