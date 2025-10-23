"""API client for interacting with Volumio instances."""

from typing import Any, Literal

import requests

from volumito.clients.errors import VolumioAPIError, VolumioConnectionError


class VolumioRESTAPIClient:
    """Client for interacting with Volumio API."""

    def __init__(
        self,
        scheme: Literal["http", "https"] = "http",
        host: str = "volumio.local",
        rest_api_port: int = 3000,
        mpd_port: int = 6599,
        timeout: float = 5.0,
    ) -> None:
        """Initialize the Volumio client.

        Args:
            scheme: The URL scheme (http or https)
            host: The hostname or IP address of the Volumio instance
            rest_api_port: The REST API port (default: 3000)
            mpd_port: The MPD port (default: 6599)
            timeout: Request timeout in seconds (default: 5.0)
        """
        self.scheme = scheme
        self.host = host
        self.rest_api_port = rest_api_port
        self.mpd_port = mpd_port
        self.timeout = timeout
        self.base_url = f"{self.scheme}://{self.host}:{self.rest_api_port}"

    def get_state(self) -> dict[str, Any]:
        """Query the /api/v1/getState endpoint.

        Returns:
            A dictionary containing the current state of the Volumio instance

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        url = f"{self.base_url}/api/v1/getState"

        try:
            response = requests.get(url, timeout=self.timeout)
            response.raise_for_status()
        except requests.exceptions.ConnectionError as e:
            raise VolumioConnectionError(
                f"Failed to connect to Volumio instance at {self.base_url}: {e}"
            ) from e
        except requests.exceptions.Timeout as e:
            raise VolumioConnectionError(
                f"Connection to Volumio instance at {self.base_url} timed out after "
                f"{self.timeout} seconds: {e}"
            ) from e
        except requests.exceptions.HTTPError as e:
            raise VolumioAPIError(
                f"Volumio API returned HTTP error {response.status_code}: {e}"
            ) from e
        except requests.exceptions.RequestException as e:
            raise VolumioConnectionError(
                f"Request to Volumio instance at {self.base_url} failed: {e}"
            ) from e

        try:
            data = response.json()
        except ValueError as e:
            raise VolumioAPIError(
                f"Failed to parse JSON response from Volumio API: {e}"
            ) from e

        if not isinstance(data, dict):
            raise VolumioAPIError(
                f"Expected JSON object from Volumio API, got {type(data).__name__}"
            )

        return data

    def get_queue(self) -> dict[str, Any]:
        """Query the /api/v1/getQueue endpoint.

        Returns:
            A dictionary containing the current playback queue

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        url = f"{self.base_url}/api/v1/getQueue"

        try:
            response = requests.get(url, timeout=self.timeout)
            response.raise_for_status()
        except requests.exceptions.ConnectionError as e:
            raise VolumioConnectionError(
                f"Failed to connect to Volumio instance at {self.base_url}: {e}"
            ) from e
        except requests.exceptions.Timeout as e:
            raise VolumioConnectionError(
                f"Connection to Volumio instance at {self.base_url} timed out after "
                f"{self.timeout} seconds: {e}"
            ) from e
        except requests.exceptions.HTTPError as e:
            raise VolumioAPIError(
                f"Volumio API returned HTTP error {response.status_code}: {e}"
            ) from e
        except requests.exceptions.RequestException as e:
            raise VolumioConnectionError(
                f"Request to Volumio instance at {self.base_url} failed: {e}"
            ) from e

        try:
            data = response.json()
        except ValueError as e:
            raise VolumioAPIError(
                f"Failed to parse JSON response from Volumio API: {e}"
            ) from e

        if not isinstance(data, dict):
            raise VolumioAPIError(
                f"Expected JSON object from Volumio API, got {type(data).__name__}"
            )

        return data

    def send_command(self, cmd: str) -> dict[str, Any]:
        """Send a command to the /api/v1/commands endpoint.

        Args:
            cmd: The command to send (e.g., "play", "pause", "stop", "toggle", "next", "prev")

        Returns:
            A dictionary containing the response from the Volumio API

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        url = f"{self.base_url}/api/v1/commands/?cmd={cmd}"

        try:
            response = requests.get(url, timeout=self.timeout)
            response.raise_for_status()
        except requests.exceptions.ConnectionError as e:
            raise VolumioConnectionError(
                f"Failed to connect to Volumio instance at {self.base_url}: {e}"
            ) from e
        except requests.exceptions.Timeout as e:
            raise VolumioConnectionError(
                f"Connection to Volumio instance at {self.base_url} timed out after "
                f"{self.timeout} seconds: {e}"
            ) from e
        except requests.exceptions.HTTPError as e:
            raise VolumioAPIError(
                f"Volumio API returned HTTP error {response.status_code}: {e}"
            ) from e
        except requests.exceptions.RequestException as e:
            raise VolumioConnectionError(
                f"Request to Volumio instance at {self.base_url} failed: {e}"
            ) from e

        try:
            data = response.json()
        except ValueError as e:
            raise VolumioAPIError(
                f"Failed to parse JSON response from Volumio API: {e}"
            ) from e

        if not isinstance(data, dict):
            raise VolumioAPIError(
                f"Expected JSON object from Volumio API, got {type(data).__name__}"
            )

        return data

    def toggle(self) -> dict[str, Any]:
        """Toggle between play and pause states.

        Returns:
            A dictionary containing the response from the Volumio API

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return self.send_command("toggle")

    def play(self, position: int | None = None) -> dict[str, Any]:
        """Start playback.

        Args:
            position: Optional position in the queue to play (0-indexed)

        Returns:
            A dictionary containing the response from the Volumio API

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        if position is not None:
            return self.send_command(f"play&N={position}")
        return self.send_command("play")

    def pause(self) -> dict[str, Any]:
        """Pause playback.

        Returns:
            A dictionary containing the response from the Volumio API

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return self.send_command("pause")

    def stop(self) -> dict[str, Any]:
        """Stop playback.

        Returns:
            A dictionary containing the response from the Volumio API

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return self.send_command("stop")

    def next(self) -> dict[str, Any]:
        """Skip to the next track.

        Returns:
            A dictionary containing the response from the Volumio API

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return self.send_command("next")

    def previous(self) -> dict[str, Any]:
        """Skip to the previous track.

        Returns:
            A dictionary containing the response from the Volumio API

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return self.send_command("prev")
