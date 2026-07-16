"""Host configuration for Volumio clients.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

from dataclasses import dataclass
from typing import Literal


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
    """

    scheme: Literal["http", "https"] = "http"
    host: str = "volumio.local"
    rest_api_port: int = 3000
    mpd_port: int = 6600

    @property
    def rest_base_url(self) -> str:
        """Return the base URL for the REST API, e.g. http://volumio.local:3000."""
        return f"{self.scheme}://{self.host}:{self.rest_api_port}"
