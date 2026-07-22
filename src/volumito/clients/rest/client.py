"""API client for interacting with Volumio instances.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

from typing import Any

import requests

from volumito.clients.errors import VolumioAPIError, VolumioConnectionError
from volumito.clients.host_configuration import VolumioHostConfiguration


class VolumioRESTAPIClient:
    """Client for interacting with Volumio API."""

    def __init__(
        self,
        host_configuration: VolumioHostConfiguration,
        timeout: float = 5.0,
    ) -> None:
        """Initialize the Volumio client.

        Args:
            host_configuration: The host configuration (scheme, host, and ports)
            timeout: Request timeout in seconds (default: 5.0)
        """
        self.host_configuration = host_configuration
        self.timeout = timeout

    def get_state(self) -> dict[str, Any]:
        """Query the /api/v1/getState endpoint.

        Returns:
            A dictionary containing the current state of the Volumio instance

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        url = f"{self.host_configuration.rest_base_url}/api/v1/getState"

        try:
            response = requests.get(url, timeout=self.timeout)
            response.raise_for_status()
        except requests.exceptions.ConnectionError as e:
            raise VolumioConnectionError(
                f"Failed to connect to Volumio instance at "
                f"{self.host_configuration.rest_base_url}: {e}"
            ) from e
        except requests.exceptions.Timeout as e:
            raise VolumioConnectionError(
                f"Connection to Volumio instance at "
                f"{self.host_configuration.rest_base_url} "
                f"timed out after {self.timeout} seconds: {e}"
            ) from e
        except requests.exceptions.HTTPError as e:
            raise VolumioAPIError(
                f"Volumio API returned HTTP error {response.status_code}: {e}"
            ) from e
        except requests.exceptions.RequestException as e:
            raise VolumioConnectionError(
                f"Request to Volumio instance at "
                f"{self.host_configuration.rest_base_url} failed: {e}"
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
        url = f"{self.host_configuration.rest_base_url}/api/v1/getQueue"

        try:
            response = requests.get(url, timeout=self.timeout)
            response.raise_for_status()
        except requests.exceptions.ConnectionError as e:
            raise VolumioConnectionError(
                f"Failed to connect to Volumio instance at "
                f"{self.host_configuration.rest_base_url}: {e}"
            ) from e
        except requests.exceptions.Timeout as e:
            raise VolumioConnectionError(
                f"Connection to Volumio instance at "
                f"{self.host_configuration.rest_base_url} "
                f"timed out after {self.timeout} seconds: {e}"
            ) from e
        except requests.exceptions.HTTPError as e:
            raise VolumioAPIError(
                f"Volumio API returned HTTP error {response.status_code}: {e}"
            ) from e
        except requests.exceptions.RequestException as e:
            raise VolumioConnectionError(
                f"Request to Volumio instance at "
                f"{self.host_configuration.rest_base_url} failed: {e}"
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
        url = f"{self.host_configuration.rest_base_url}/api/v1/commands/?cmd={cmd}"

        try:
            response = requests.get(url, timeout=self.timeout)
            response.raise_for_status()
        except requests.exceptions.ConnectionError as e:
            raise VolumioConnectionError(
                f"Failed to connect to Volumio instance at "
                f"{self.host_configuration.rest_base_url}: {e}"
            ) from e
        except requests.exceptions.Timeout as e:
            raise VolumioConnectionError(
                f"Connection to Volumio instance at "
                f"{self.host_configuration.rest_base_url} "
                f"timed out after {self.timeout} seconds: {e}"
            ) from e
        except requests.exceptions.HTTPError as e:
            raise VolumioAPIError(
                f"Volumio API returned HTTP error {response.status_code}: {e}"
            ) from e
        except requests.exceptions.RequestException as e:
            raise VolumioConnectionError(
                f"Request to Volumio instance at "
                f"{self.host_configuration.rest_base_url} failed: {e}"
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

    def volume(self, value: int | str) -> dict[str, Any]:
        """Set or adjust the playback volume.

        Args:
            value: An integer between 0 and 100 (inclusive) to set an absolute
                volume level, or one of the strings "mute", "unmute", "plus",
                "minus"

        Returns:
            A dictionary containing the response from the Volumio API

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return self.send_command(f"volume&volume={value}")

    def clear(self) -> dict[str, Any]:
        """Clear the playback queue.

        Returns:
            A dictionary containing the response from the Volumio API

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return self.send_command("clearQueue")

    def repeat(self, value: bool | None = None) -> dict[str, Any]:
        """Set or toggle the repeat mode.

        Args:
            value: True to enable, False to disable, or None (the default) to let
                the Volumio API toggle the current repeat mode

        Returns:
            A dictionary containing the response from the Volumio API

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        if value is None:
            return self.send_command("repeat")
        return self.send_command(f"repeat&value={str(value).lower()}")

    def randomize(self, value: bool | None = None) -> dict[str, Any]:
        """Set or toggle the random (shuffle) mode.

        Args:
            value: True to enable, False to disable, or None (the default) to let
                the Volumio API toggle the current random mode

        Returns:
            A dictionary containing the response from the Volumio API

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        if value is None:
            return self.send_command("random")
        return self.send_command(f"random&value={str(value).lower()}")

    def _get(self, path: str) -> requests.Response:
        """GET ``{rest_base_url}{path}``, translating request failures to Volumio errors.

        Args:
            path: The URL path (including any query string) to request

        Returns:
            The successful :class:`requests.Response`

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an HTTP error response
        """
        url = f"{self.host_configuration.rest_base_url}{path}"

        try:
            response = requests.get(url, timeout=self.timeout)
            response.raise_for_status()
        except requests.exceptions.ConnectionError as e:
            raise VolumioConnectionError(
                f"Failed to connect to Volumio instance at "
                f"{self.host_configuration.rest_base_url}: {e}"
            ) from e
        except requests.exceptions.Timeout as e:
            raise VolumioConnectionError(
                f"Connection to Volumio instance at "
                f"{self.host_configuration.rest_base_url} "
                f"timed out after {self.timeout} seconds: {e}"
            ) from e
        except requests.exceptions.HTTPError as e:
            raise VolumioAPIError(
                f"Volumio API returned HTTP error {response.status_code}: {e}"
            ) from e
        except requests.exceptions.RequestException as e:
            raise VolumioConnectionError(
                f"Request to Volumio instance at "
                f"{self.host_configuration.rest_base_url} failed: {e}"
            ) from e

        return response

    def _get_json(self, path: str) -> dict[str, Any]:
        """GET ``path`` and parse the response as a JSON object.

        Args:
            path: The URL path (including any query string) to request

        Returns:
            The parsed JSON object

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error or a non-object response
        """
        response = self._get(path)

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

    def _get_text(self, path: str) -> str:
        """GET ``path`` and return the response body as text.

        Args:
            path: The URL path (including any query string) to request

        Returns:
            The response body text

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an HTTP error response
        """
        return self._get(path).text

    def ping(self) -> str:
        """Query the /api/v1/ping endpoint.

        Returns:
            The response body text (``"pong"`` from a healthy Volumio instance)

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return self._get_text("/api/v1/ping")

    def get_system_version(self) -> dict[str, Any]:
        """Query the /api/v1/getSystemVersion endpoint.

        Returns:
            A dictionary containing the Volumio system version information

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return self._get_json("/api/v1/getSystemVersion")

    def get_system_info(self) -> dict[str, Any]:
        """Query the /api/v1/getSystemInfo endpoint.

        Returns:
            A dictionary containing the Volumio system information

        Raises:
            VolumioConnectionError: If connection to the Volumio instance fails
            VolumioAPIError: If the API returns an error response
        """
        return self._get_json("/api/v1/getSystemInfo")
