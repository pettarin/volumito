"""MPD client for interacting with Volumio's MPD interface."""

from types import TracebackType
from typing import Any

from mpd import MPDClient

from volumito.clients.errors import VolumioConnectionError


class VolumioMPDClient:
    """Client for interacting with Volumio's MPD interface."""

    def __init__(
        self,
        host: str = "volumio.local",
        port: int = 6599,
        timeout: float = 5.0,
    ) -> None:
        """Initialize the MPD client.

        Args:
            host: The hostname or IP address of the Volumio instance
            port: The MPD port (default: 6599)
            timeout: Connection timeout in seconds (default: 5.0)
        """
        self.host = host
        self.port = port
        self.timeout = timeout
        self._client = MPDClient()
        self._client.timeout = timeout
        self._connected = False

    def connect(self) -> None:
        """Connect to the MPD server.

        Raises:
            VolumioConnectionError: If connection to MPD fails
        """
        try:
            self._client.connect(self.host, self.port)
            self._connected = True
        except ConnectionRefusedError as e:
            raise VolumioConnectionError(
                f"Connection refused to MPD at {self.host}:{self.port}: {e}"
            ) from e
        except OSError as e:
            raise VolumioConnectionError(
                f"MPD connection error at {self.host}:{self.port}: {e}"
            ) from e
        except Exception as e:
            raise VolumioConnectionError(
                f"Failed to connect to MPD at {self.host}:{self.port}: {e}"
            ) from e

    def disconnect(self) -> None:
        """Disconnect from the MPD server.

        This method is safe to call multiple times and will not raise exceptions.
        """
        if self._connected:
            try:
                self._client.close()
                self._client.disconnect()
            except Exception:  # pragma: no cover
                # Ignore errors during cleanup
                pass
            finally:
                self._connected = False

    def get_current_song(self) -> dict[str, Any]:
        """Get information about the current song.

        Returns:
            A dictionary containing the current song information

        Raises:
            VolumioConnectionError: If not connected or no track is playing
        """
        if not self._connected:
            raise VolumioConnectionError("Not connected to MPD")

        try:
            current_song = self._client.currentsong()
        except Exception as e:
            raise VolumioConnectionError(f"MPD error: {e}") from e

        if not current_song or "file" not in current_song:
            raise VolumioConnectionError("No track currently playing")

        return dict(current_song)

    def get_track_uri(self) -> str:
        """Get the URI of the current track with localhost replaced by actual host.

        Returns:
            The track URI with localhost/127.0.0.1 replaced by the actual host

        Raises:
            VolumioConnectionError: If not connected or no track is playing
        """
        current_song = self.get_current_song()
        uri = str(current_song["file"])

        # Replace localhost or 127.0.0.1 with the actual host
        uri = uri.replace("127.0.0.1", self.host)
        uri = uri.replace("localhost", self.host)

        return uri

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
