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
    RemoteCommandResult,
    VolumioHostConfiguration,
    VolumioSCPError,
    VolumioSSHError,
    copy_from_host,
    copy_to_host,
    execute_on_host,
    is_local_file_uri,
    remote_music_path,
)
from volumito.clients.remote import _load_paramiko, _load_scp

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

    def test_a_missing_scp_package(self, mocker: MockerFixture):
        """A missing scp package is reported with the way to install it."""
        mocker.patch.dict(sys.modules, {"scp": None})

        with pytest.raises(VolumioSCPError) as exc_info:
            _load_scp()

        assert "needs the scp package" in str(exc_info.value)
        assert "pip install volumito[scp]" in str(exc_info.value)

    def test_a_missing_paramiko_package(self, mocker: MockerFixture):
        """A missing paramiko is reported by the loader the SSH session uses."""
        mocker.patch.dict(sys.modules, {"paramiko": None})

        with pytest.raises(VolumioSSHError) as exc_info:
            _load_paramiko()

        assert "needs the scp package" in str(exc_info.value)
        assert "pip install volumito[scp]" in str(exc_info.value)


class TestCopyFromHost:
    """Test cases for the copy_from_host function."""

    def _mock_scp(self, mocker: MockerFixture):
        """Patch the optional dependencies with mocks, returning them."""
        paramiko = mocker.MagicMock()
        scp_client_class = mocker.MagicMock()
        mocker.patch("volumito.clients.remote._load_paramiko", return_value=paramiko)
        mocker.patch(
            "volumito.clients.remote._load_scp",
            return_value=(paramiko, scp_client_class),
        )
        return paramiko, scp_client_class

    def test_copies_the_file(self, mocker: MockerFixture):
        """The file is fetched over an SSH connection to the host."""
        paramiko, scp_client_class = self._mock_scp(mocker)
        host_configuration = VolumioHostConfiguration(host="volumio.local", ssh_port=2222)

        copy_from_host(
            host_configuration, "/mnt/INTERNAL/a.flac", "/tmp/a.flac", timeout=7.0
        )

        ssh_client = paramiko.SSHClient.return_value.__enter__.return_value
        ssh_client.load_system_host_keys.assert_called_once_with()
        ssh_client.set_missing_host_key_policy.assert_called_once_with(
            paramiko.AutoAddPolicy.return_value
        )
        ssh_client.connect.assert_called_once_with(
            "volumio.local", port=2222, username="volumio", password=None, timeout=7.0
        )
        scp_client_class.assert_called_once_with(ssh_client.get_transport.return_value)
        scp_client_class.return_value.__enter__.return_value.get.assert_called_once_with(
            "/mnt/INTERNAL/a.flac", "/tmp/a.flac", recursive=False
        )

    def test_the_configured_user_name(self, mocker: MockerFixture):
        """The SSH user name of the host configuration is the one used."""
        paramiko, _ = self._mock_scp(mocker)

        copy_from_host(
            VolumioHostConfiguration(ssh_username="pi"), "/mnt/INTERNAL/a.flac", "/tmp/a.flac"
        )

        ssh_client = paramiko.SSHClient.return_value.__enter__.return_value
        assert ssh_client.connect.call_args.kwargs["username"] == "pi"

    def test_the_configured_password(self, mocker: MockerFixture):
        """The SSH password of the host configuration is the one used."""
        paramiko, _ = self._mock_scp(mocker)

        copy_from_host(
            VolumioHostConfiguration(ssh_password="hunter2"),
            "/mnt/INTERNAL/a.flac",
            "/tmp/a.flac",
        )

        ssh_client = paramiko.SSHClient.return_value.__enter__.return_value
        assert ssh_client.connect.call_args.kwargs["password"] == "hunter2"

    def test_a_recursive_copy(self, mocker: MockerFixture):
        """A directory is copied with its content."""
        _, scp_client_class = self._mock_scp(mocker)

        copy_from_host(
            VolumioHostConfiguration(), "/mnt/INTERNAL/music", "./music", recursive=True
        )

        scp_client_class.return_value.__enter__.return_value.get.assert_called_once_with(
            "/mnt/INTERNAL/music", "./music", recursive=True
        )

    def test_a_missing_package(self, mocker: MockerFixture):
        """The error of the lazy import is reported as it is."""
        mocker.patch(
            "volumito.clients.remote._load_scp",
            side_effect=VolumioSCPError("needs the scp package"),
        )

        with pytest.raises(VolumioSCPError) as exc_info:
            copy_from_host(VolumioHostConfiguration(), "/mnt/a.flac", "/tmp/a.flac")

        assert str(exc_info.value) == "needs the scp package"

    def test_a_failed_copy(self, mocker: MockerFixture):
        """A failure of the SSH connection or of the copy is reported."""
        paramiko, _ = self._mock_scp(mocker)
        paramiko.SSHClient.return_value.__enter__.return_value.connect.side_effect = OSError(
            "No route to host"
        )

        with pytest.raises(VolumioSCPError) as exc_info:
            copy_from_host(
                VolumioHostConfiguration(host="volumio.local"),
                "/mnt/INTERNAL/a.flac",
                "/tmp/a.flac",
            )

        assert "Failed to copy /mnt/INTERNAL/a.flac" in str(exc_info.value)
        assert "No route to host" in str(exc_info.value)


class TestCopyToHost:
    """Test cases for the copy_to_host function."""

    def _mock_scp(self, mocker: MockerFixture):
        """Patch the optional dependencies with mocks, returning them."""
        paramiko = mocker.MagicMock()
        scp_client_class = mocker.MagicMock()
        mocker.patch("volumito.clients.remote._load_paramiko", return_value=paramiko)
        mocker.patch(
            "volumito.clients.remote._load_scp",
            return_value=(paramiko, scp_client_class),
        )
        return paramiko, scp_client_class

    def test_copies_the_file(self, mocker: MockerFixture):
        """The file is sent over an SSH connection to the host."""
        paramiko, scp_client_class = self._mock_scp(mocker)
        host_configuration = VolumioHostConfiguration(host="volumio.local", ssh_port=2222)

        copy_to_host(host_configuration, "/tmp/a.flac", "/mnt/INTERNAL/a.flac", timeout=7.0)

        ssh_client = paramiko.SSHClient.return_value.__enter__.return_value
        ssh_client.load_system_host_keys.assert_called_once_with()
        ssh_client.connect.assert_called_once_with(
            "volumio.local", port=2222, username="volumio", password=None, timeout=7.0
        )
        scp_client_class.return_value.__enter__.return_value.put.assert_called_once_with(
            "/tmp/a.flac", "/mnt/INTERNAL/a.flac", recursive=False
        )

    def test_a_recursive_copy(self, mocker: MockerFixture):
        """A directory is copied with its content."""
        _, scp_client_class = self._mock_scp(mocker)

        copy_to_host(
            VolumioHostConfiguration(), "./album", "/mnt/INTERNAL/music/album", recursive=True
        )

        scp_client_class.return_value.__enter__.return_value.put.assert_called_once_with(
            "./album", "/mnt/INTERNAL/music/album", recursive=True
        )

    def test_a_failed_copy(self, mocker: MockerFixture):
        """A failure of the SSH connection or of the copy is reported."""
        paramiko, _ = self._mock_scp(mocker)
        paramiko.SSHClient.return_value.__enter__.return_value.connect.side_effect = OSError(
            "No route to host"
        )

        with pytest.raises(VolumioSCPError) as exc_info:
            copy_to_host(
                VolumioHostConfiguration(host="volumio.local"), "/tmp/a.flac", "/mnt/a.flac"
            )

        assert "Failed to copy /tmp/a.flac to the Volumio host" in str(exc_info.value)

    def test_a_missing_package(self, mocker: MockerFixture):
        """The error of the lazy import is reported as it is."""
        mocker.patch(
            "volumito.clients.remote._load_scp",
            side_effect=VolumioSCPError("needs the scp package"),
        )

        with pytest.raises(VolumioSCPError) as exc_info:
            copy_to_host(VolumioHostConfiguration(), "/tmp/a.flac", "/mnt/a.flac")

        assert str(exc_info.value) == "needs the scp package"


class TestExecuteOnHost:
    """Test cases for the execute_on_host function."""

    def _mock_paramiko(self, mocker: MockerFixture, stdout=b"", stderr=b"", exit_code=0):
        """Patch paramiko with a client whose exec_command returns the given streams."""
        paramiko = mocker.MagicMock()
        ssh_client = paramiko.SSHClient.return_value.__enter__.return_value
        out, err = mocker.MagicMock(), mocker.MagicMock()
        out.read.return_value = stdout
        out.channel.recv_exit_status.return_value = exit_code
        err.read.return_value = stderr
        ssh_client.exec_command.return_value = (mocker.MagicMock(), out, err)
        mocker.patch("volumito.clients.remote._load_paramiko", return_value=paramiko)
        return paramiko, ssh_client

    def test_executes_the_command(self, mocker: MockerFixture):
        """The command is executed, and its outcome is returned."""
        _, ssh_client = self._mock_paramiko(
            mocker, stdout=b"up 3 days\n", stderr=b"a warning\n", exit_code=0
        )

        result = execute_on_host(VolumioHostConfiguration(host="volumio.local"), "uptime")

        ssh_client.exec_command.assert_called_once_with("uptime")
        assert result == RemoteCommandResult(
            command="uptime", exit_code=0, stdout="up 3 days\n", stderr="a warning\n"
        )

    def test_the_exit_code_of_the_command(self, mocker: MockerFixture):
        """The exit code the command returned on the host is reported."""
        self._mock_paramiko(mocker, stdout=b"inactive\n", exit_code=3)

        result = execute_on_host(VolumioHostConfiguration(), "systemctl is-active mpd")

        assert result.exit_code == 3
        assert result.stdout == "inactive\n"

    def test_the_ssh_parameters(self, mocker: MockerFixture):
        """The connection uses the SSH parameters of the host configuration."""
        _, ssh_client = self._mock_paramiko(mocker)

        execute_on_host(
            VolumioHostConfiguration(host="volumio.local", ssh_port=2222, ssh_username="pi"),
            "uptime",
            timeout=7.0,
        )

        ssh_client.connect.assert_called_once_with(
            "volumio.local", port=2222, username="pi", password=None, timeout=7.0
        )

    def test_an_undecodable_byte(self, mocker: MockerFixture):
        """Bytes that are not UTF-8 are replaced instead of failing the command."""
        self._mock_paramiko(mocker, stdout=b"\xff\xfe")

        result = execute_on_host(VolumioHostConfiguration(), "cat /dev/urandom")

        assert result.stdout == "\ufffd\ufffd"

    def test_a_failed_execution(self, mocker: MockerFixture):
        """A failure of the connection or of the execution is reported."""
        paramiko, _ = self._mock_paramiko(mocker)
        paramiko.SSHClient.return_value.__enter__.return_value.connect.side_effect = OSError(
            "No route to host"
        )

        with pytest.raises(VolumioSSHError) as exc_info:
            execute_on_host(VolumioHostConfiguration(host="volumio.local"), "uptime")

        assert "Failed to execute 'uptime' on the Volumio host" in str(exc_info.value)
        assert "No route to host" in str(exc_info.value)

    def test_a_missing_package(self, mocker: MockerFixture):
        """The error of the lazy import is reported as it is."""
        mocker.patch(
            "volumito.clients.remote._load_paramiko",
            side_effect=VolumioSSHError("needs the scp package"),
        )

        with pytest.raises(VolumioSSHError) as exc_info:
            execute_on_host(VolumioHostConfiguration(), "uptime")

        assert str(exc_info.value) == "needs the scp package"
