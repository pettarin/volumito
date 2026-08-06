"""MPD client for interacting with Volumio's MPD interface.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

import logging
from types import TracebackType
from typing import Any

from mpd import MPDClient

from volumito.clients.base import VolumioBaseClient
from volumito.clients.errors import VolumioConnectionError
from volumito.clients.host_configuration import VolumioHostConfiguration


class VolumioMPDClient(VolumioBaseClient):
    """Client for interacting with Volumio's MPD interface."""

    def __init__(
        self,
        host_configuration: VolumioHostConfiguration,
        timeout: float = 5.0,
        logger: logging.Logger | None = None,
    ) -> None:
        """Initialize the MPD client.

        Args:
            host_configuration: The host configuration (scheme, host, and ports)
            timeout: Connection timeout in seconds (default: 5.0)
            logger: The logger the client writes to; without one, the client logs
                under its own name in the ``volumito`` hierarchy
        """
        super().__init__(logger)
        self._log_debug("Initializing the MPD client...")
        self.host_configuration = host_configuration
        self.timeout = timeout
        self._client = MPDClient()
        self._client.timeout = timeout
        self._connected = False
        self._log_debug("Initializing the MPD client... done")

    def connect(self) -> None:
        """Connect to the MPD server.

        Raises:
            VolumioConnectionError: If connection to MPD fails
        """
        host = self.host_configuration.host
        mpd_port = self.host_configuration.mpd_port
        self._log_debug(f"Connecting to MPD at {host}:{mpd_port}...")
        try:
            self._client.connect(host, mpd_port)
            self._connected = True
        except ConnectionRefusedError as e:
            self._log_warning(f"Connection refused by MPD at {host}:{mpd_port}: {e}")
            raise VolumioConnectionError(
                f"Connection refused to MPD at {host}:{mpd_port}: {e}"
            ) from e
        except OSError as e:
            self._log_warning(f"MPD connection error at {host}:{mpd_port}: {e}")
            raise VolumioConnectionError(
                f"MPD connection error at {host}:{mpd_port}: {e}"
            ) from e
        except Exception as e:
            self._log_exception(f"Unexpected error connecting to MPD at {host}:{mpd_port}")
            raise VolumioConnectionError(
                f"Failed to connect to MPD at {host}:{mpd_port}: {e}"
            ) from e
        self._log_debug(f"Connecting to MPD at {host}:{mpd_port}... done")
        self._log_debug("Connected to MPD")

    def disconnect(self) -> None:
        """Disconnect from the MPD server.

        This method is safe to call multiple times and will not raise exceptions.
        """
        if self._connected:
            self._log_debug("Disconnecting from MPD...")
            try:
                self._client.close()
                self._client.disconnect()
            except Exception as e:
                self._log_warning(f"Ignoring an error while disconnecting from MPD: {e}")
            finally:
                self._connected = False
            self._log_debug("Disconnecting from MPD... done")
            self._log_debug("Disconnected from MPD")

    def get_current_song(self) -> dict[str, Any]:
        """Get information about the current song.

        Returns:
            A dictionary containing the current song information, whose keys depend
            on what is playing (see :meth:`get_track_uri` for the file URI)

        Raises:
            VolumioConnectionError: If not connected or no track is playing
        """
        self._log_debug("Reading the current song from MPD...")
        if not self._connected:
            self._log_debug("Not connected to MPD")
            raise VolumioConnectionError("Not connected to MPD")

        try:
            current_song = self._client.currentsong()
        except Exception as e:
            self._log_exception("Unexpected error reading the current song from MPD")
            raise VolumioConnectionError(f"MPD error: {e}") from e

        if not current_song:
            self._log_debug("No track currently playing")
            raise VolumioConnectionError("No track currently playing")

        song = dict(current_song)
        self._log_debug(f"Current song: {song}")
        self._log_debug("Reading the current song from MPD... done")
        return song

    def get_track_uri(self) -> str:
        """Get the URI of the current track, as the Volumio host reports it.

        A track of the library of the host is reported by path, without a scheme
        (e.g., ``INTERNAL/music/album/01-track.flac``); everything else carries one.

        Returns:
            The URI of the current track

        Raises:
            VolumioConnectionError: If not connected, no track is playing, or the
                current song carries no file URI
        """
        song = self.get_current_song()
        if "file" not in song:
            self._log_warning("The current song carries no file URI")
            raise VolumioConnectionError("No track currently playing")
        return str(song["file"])

    def __enter__(self) -> "VolumioMPDClient":
        """Context manager entry - connects to MPD.

        Returns:
            The VolumioMPDClient instance

        Raises:
            VolumioConnectionError: If connection fails
        """
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Context manager exit - disconnects from MPD.

        Args:
            exc_type: Exception type (if any)
            exc_val: Exception value (if any)
            exc_tb: Exception traceback (if any)
        """
        self.disconnect()
