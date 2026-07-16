"""Tests for the host configuration module.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

import dataclasses

import pytest

from volumito.clients import VolumioHostConfiguration


class TestVolumioHostConfiguration:
    """Test cases for the VolumioHostConfiguration dataclass."""

    def test_default_values(self):
        """Test VolumioHostConfiguration with default values."""
        host_configuration = VolumioHostConfiguration()

        assert host_configuration.scheme == "http"
        assert host_configuration.host == "volumio.local"
        assert host_configuration.rest_api_port == 3000
        assert host_configuration.mpd_port == 6600

    def test_custom_values(self):
        """Test VolumioHostConfiguration with custom values."""
        host_configuration = VolumioHostConfiguration(
            scheme="https",
            host="192.168.1.100",
            rest_api_port=8080,
            mpd_port=7000,
        )

        assert host_configuration.scheme == "https"
        assert host_configuration.host == "192.168.1.100"
        assert host_configuration.rest_api_port == 8080
        assert host_configuration.mpd_port == 7000

    def test_rest_base_url_default(self):
        """Test rest_base_url with default values."""
        host_configuration = VolumioHostConfiguration()

        assert host_configuration.rest_base_url == "http://volumio.local:3000"

    def test_rest_base_url_https(self):
        """Test rest_base_url with an https scheme and custom host/port."""
        host_configuration = VolumioHostConfiguration(
            scheme="https",
            host="192.168.1.100",
            rest_api_port=8080,
        )

        assert host_configuration.rest_base_url == "https://192.168.1.100:8080"

    def test_equality(self):
        """Test that two host configurations with the same values compare equal."""
        host_configuration_a = VolumioHostConfiguration(host="myhost.local", mpd_port=6599)
        host_configuration_b = VolumioHostConfiguration(host="myhost.local", mpd_port=6599)
        host_configuration_c = VolumioHostConfiguration(host="otherhost.local")

        assert host_configuration_a == host_configuration_b
        assert host_configuration_a != host_configuration_c

    def test_is_immutable(self):
        """Test that the host configuration is frozen (immutable)."""
        host_configuration = VolumioHostConfiguration()

        with pytest.raises(dataclasses.FrozenInstanceError):
            host_configuration.host = "changed.local"  # type: ignore[misc]
