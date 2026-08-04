"""Access to the files a Volumio host stores locally.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

import os
from typing import Any

from volumito.clients.errors import VolumioSCPError
from volumito.clients.host_configuration import VolumioHostConfiguration

VOLUMIO_MNT_ROOT = "/mnt"
"""Directory a Volumio host mounts its music sources under."""

VOLUMIO_INTERNAL_ROOT = os.path.join(VOLUMIO_MNT_ROOT, "INTERNAL")
"""Directory of the internal storage of a Volumio host."""


def _load_scp() -> tuple[Any, Any]:
    """Import the optional SCP dependencies, when a copy is about to be made.

    Returns:
        The paramiko module and the SCPClient class

    Raises:
        VolumioSCPError: If the packages are not installed
    """
    try:
        import paramiko
        from scp import SCPClient
    except ImportError as e:
        raise VolumioSCPError(
            "Copying a file from the Volumio host needs the scp package: "
            "install it with 'pip install volumito[scp]'"
        ) from e

    return paramiko, SCPClient


def copy_file_from_host(
    host_configuration: VolumioHostConfiguration,
    remote_path: str,
    destination: str,
    timeout: float = 5.0,
) -> None:
    """Copy a file of the Volumio host to a local path, over SCP.

    The SSH connection is made with the user name and the port of the host
    configuration, authenticating with the keys of the current user: the known hosts
    of the system are loaded, and a host key not among them is accepted and added.

    Args:
        host_configuration: The host configuration (host, SSH port, and SSH user name)
        remote_path: The path of the file on the Volumio host
        destination: The local path to copy the file to
        timeout: Connection timeout in seconds (default: 5.0)

    Raises:
        VolumioSCPError: If the packages are not installed, or the copy fails
    """
    paramiko, scp_client_class = _load_scp()

    try:
        with paramiko.SSHClient() as ssh_client:
            ssh_client.load_system_host_keys()
            ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh_client.connect(
                host_configuration.host,
                port=host_configuration.ssh_port,
                username=host_configuration.ssh_username,
                timeout=timeout,
            )
            with scp_client_class(ssh_client.get_transport()) as scp_client:
                scp_client.get(remote_path, destination)
    except Exception as e:
        raise VolumioSCPError(
            f"Failed to copy {remote_path} from the Volumio host at "
            f"{host_configuration.host}: {e}"
        ) from e


def is_local_file_uri(uri: str) -> bool:
    """Return whether a URI names a file stored on the Volumio host.

    The Volumio host reports the tracks of its own library by path, without a scheme
    (e.g., ``INTERNAL/music/album/01-track.flac``), and everything else with one.

    Args:
        uri: The URI reported by the Volumio host

    Returns:
        True if the URI is the path of a file of the host
    """
    return "://" not in uri


def remote_music_path(uri: str, music_root: str = VOLUMIO_MNT_ROOT) -> str:
    """Return the path a local-file URI has on the Volumio host.

    Args:
        uri: The URI reported by the Volumio host (e.g., ``INTERNAL/music/song.flac``)
        music_root: Directory the music sources are mounted under

    Returns:
        The path of the file on the Volumio host (e.g., ``/mnt/INTERNAL/music/song.flac``)
    """
    return os.path.join(music_root, uri.lstrip("/"))
