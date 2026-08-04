"""Host configuration for Volumio clients.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

from dataclasses import dataclass
from typing import Literal

# The single source of the accepted URL schemes (used for both typing and validation)
Scheme = Literal["http", "https"]


@dataclass(frozen=True)
class VolumioHostConfiguration:
    """Connection parameters identifying a Volumio host.

    Bundles the host identity (scheme, hostname, and ports) so it can be passed
    to a client instead of separate parameters.

    Attributes:
        scheme: The URL scheme (http or https)
        host: The hostname or IP address of the Volumio instance
        rest_api_port: The REST API port (default: 3000)
        mpd_port: The MPD port (default: 6600)
        ssh_password: The SSH password, when no key of the current user is authorized
            on the host (default: None, authenticating with the keys of the user)
        ssh_port: The SSH port, used to copy the files of the host (default: 22)
        ssh_username: The SSH user name (default: volumio, the default user of a host)
    """

    scheme: Scheme = "http"
    host: str = "volumio.local"
    rest_api_port: int = 3000
    mpd_port: int = 6600
    ssh_password: str | None = None
    ssh_port: int = 22
    ssh_username: str = "volumio"

    @property
    def rest_base_url(self) -> str:
        """Return the base URL for the REST API, e.g. http://volumio.local:3000."""
        return f"{self.scheme}://{self.host}:{self.rest_api_port}"
