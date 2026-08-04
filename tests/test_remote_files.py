"""Tests for the access to the files stored on a Volumio host.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

import sys

import pytest
from pytest_mock import MockerFixture

from volumito.clients import (
    VOLUMIO_INTERNAL_ROOT,
    VOLUMIO_MNT_ROOT,
    VolumioHostConfiguration,
    VolumioSCPError,
    copy_file_from_host,
    is_local_file_uri,
    remote_music_path,
)
from volumito.clients.remote_files import _load_scp

URI = "INTERNAL/music/album/01-track.flac"
"""A URI of the shape a Volumio host reports for a track of its library."""


class TestRoots:
    """Test cases for the directories of a Volumio host."""

    def test_the_roots(self):
        """The internal storage is a directory of the mount root."""
        assert VOLUMIO_MNT_ROOT == "/mnt"
        assert VOLUMIO_INTERNAL_ROOT == "/mnt/INTERNAL"


class TestIsLocalFileUri:
    """Test cases for the is_local_file_uri function."""

    def test_a_path(self):
        """A URI without a scheme names a file of the host."""
        assert is_local_file_uri(URI)

    @pytest.mark.parametrize(
        "uri",
        [
            "http://volumio.local/music/track.flac",
            "https://static.qobuz.com/track.flac",
            "spotify://track/1234",
        ],
    )
    def test_a_uri_with_a_scheme(self, uri):
        """A URI carrying a scheme is not a file of the host."""
        assert not is_local_file_uri(uri)


class TestRemoteMusicPath:
    """Test cases for the remote_music_path function."""

    def test_the_path_on_the_host(self):
        """The URI is resolved against the mount root of the host."""
        assert remote_music_path(URI) == "/mnt/INTERNAL/music/album/01-track.flac"

    def test_a_leading_slash(self):
        """A leading slash does not make the URI absolute."""
        assert remote_music_path(f"/{URI}") == "/mnt/INTERNAL/music/album/01-track.flac"

    def test_another_music_root(self):
        """The mount root can be given."""
        assert remote_music_path(URI, "/media") == "/media/INTERNAL/music/album/01-track.flac"


class TestLoadScp:
    """Test cases for the lazy import of the optional dependencies."""

    def test_the_packages_are_imported(self):
        """The paramiko module and the SCPClient class are returned."""
        paramiko, scp_client_class = _load_scp()

        assert hasattr(paramiko, "SSHClient")
        assert scp_client_class.__name__ == "SCPClient"

    @pytest.mark.parametrize("missing", ["paramiko", "scp"])
    def test_a_missing_package(self, mocker: MockerFixture, missing):
        """A missing package is reported with the way to install it."""
        mocker.patch.dict(sys.modules, {missing: None})

        with pytest.raises(VolumioSCPError) as exc_info:
            _load_scp()

        assert "needs the scp package" in str(exc_info.value)
        assert "pip install volumito[scp]" in str(exc_info.value)


class TestCopyFileFromHost:
    """Test cases for the copy_file_from_host function."""

    def _mock_scp(self, mocker: MockerFixture):
        """Patch the optional dependencies with mocks, returning them."""
        paramiko = mocker.MagicMock()
        scp_client_class = mocker.MagicMock()
        mocker.patch(
            "volumito.clients.remote_files._load_scp",
            return_value=(paramiko, scp_client_class),
        )
        return paramiko, scp_client_class

    def test_copies_the_file(self, mocker: MockerFixture):
        """The file is fetched over an SSH connection to the host."""
        paramiko, scp_client_class = self._mock_scp(mocker)
        host_configuration = VolumioHostConfiguration(host="volumio.local", ssh_port=2222)

        copy_file_from_host(host_configuration, "/mnt/INTERNAL/a.flac", "/tmp/a.flac", 7.0)

        ssh_client = paramiko.SSHClient.return_value.__enter__.return_value
        ssh_client.load_system_host_keys.assert_called_once_with()
        ssh_client.set_missing_host_key_policy.assert_called_once_with(
            paramiko.AutoAddPolicy.return_value
        )
        ssh_client.connect.assert_called_once_with(
            "volumio.local", port=2222, username="volumio", timeout=7.0
        )
        scp_client_class.assert_called_once_with(ssh_client.get_transport.return_value)
        scp_client_class.return_value.__enter__.return_value.get.assert_called_once_with(
            "/mnt/INTERNAL/a.flac", "/tmp/a.flac"
        )

    def test_the_configured_user_name(self, mocker: MockerFixture):
        """The SSH user name of the host configuration is the one used."""
        paramiko, _ = self._mock_scp(mocker)

        copy_file_from_host(
            VolumioHostConfiguration(ssh_username="pi"), "/mnt/INTERNAL/a.flac", "/tmp/a.flac"
        )

        ssh_client = paramiko.SSHClient.return_value.__enter__.return_value
        assert ssh_client.connect.call_args.kwargs["username"] == "pi"

    def test_a_failed_copy(self, mocker: MockerFixture):
        """A failure of the SSH connection or of the copy is reported."""
        paramiko, _ = self._mock_scp(mocker)
        paramiko.SSHClient.return_value.__enter__.return_value.connect.side_effect = OSError(
            "No route to host"
        )

        with pytest.raises(VolumioSCPError) as exc_info:
            copy_file_from_host(
                VolumioHostConfiguration(host="volumio.local"),
                "/mnt/INTERNAL/a.flac",
                "/tmp/a.flac",
            )

        assert "Failed to copy /mnt/INTERNAL/a.flac" in str(exc_info.value)
        assert "No route to host" in str(exc_info.value)
