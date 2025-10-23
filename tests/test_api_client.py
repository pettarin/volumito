"""Tests for the API client module."""

import pytest
import requests
from pytest_mock import MockerFixture

from volumito.clients.rest import (
    VolumioAPIError,
    VolumioConnectionError,
    VolumioError,
    VolumioRESTAPIClient,
)


class TestVolumioRESTAPIClient:
    """Test cases for the VolumioRESTAPIClient class."""

    def test_init_default_values(self):
        """Test VolumioRESTAPIClient initialization with default values."""
        client = VolumioRESTAPIClient()

        assert client.scheme == "http"
        assert client.host == "volumio.local"
        assert client.rest_api_port == 3000
        assert client.mpd_port == 6599
        assert client.timeout == 5.0
        assert client.base_url == "http://volumio.local:3000"

    def test_init_custom_values(self):
        """Test VolumioRESTAPIClient initialization with custom values."""
        client = VolumioRESTAPIClient(
            scheme="https",
            host="192.168.1.100",
            rest_api_port=8080,
            mpd_port=7000,
            timeout=10.0,
        )

        assert client.scheme == "https"
        assert client.host == "192.168.1.100"
        assert client.rest_api_port == 8080
        assert client.mpd_port == 7000
        assert client.timeout == 10.0
        assert client.base_url == "https://192.168.1.100:8080"

    def test_get_state_success(self, mocker: MockerFixture):
        """Test successful get_state() call."""
        # Mock response
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "play",
            "position": 0,
            "title": "Test Song",
            "artist": "Test Artist",
            "album": "Test Album",
            "volume": 100,
            "mute": False,
            "service": "mpd",
        }

        # Mock requests.get
        mock_get = mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient()
        state = client.get_state()

        # Verify the request was made correctly
        mock_get.assert_called_once_with(
            "http://volumio.local:3000/api/v1/getState", timeout=5.0
        )

        # Verify the response
        assert state["status"] == "play"
        assert state["title"] == "Test Song"
        assert state["artist"] == "Test Artist"

    def test_get_state_connection_error(self, mocker: MockerFixture):
        """Test get_state() with connection error."""
        # Mock requests.get to raise ConnectionError
        mocker.patch(
            "requests.get",
            side_effect=requests.exceptions.ConnectionError("Connection refused"),
        )

        client = VolumioRESTAPIClient()

        with pytest.raises(VolumioConnectionError) as exc_info:
            client.get_state()

        assert "Failed to connect" in str(exc_info.value)

    def test_get_state_timeout_error(self, mocker: MockerFixture):
        """Test get_state() with timeout error."""
        # Mock requests.get to raise Timeout
        mocker.patch(
            "requests.get", side_effect=requests.exceptions.Timeout("Request timeout")
        )

        client = VolumioRESTAPIClient()

        with pytest.raises(VolumioConnectionError) as exc_info:
            client.get_state()

        assert "timed out" in str(exc_info.value)

    def test_get_state_http_error(self, mocker: MockerFixture):
        """Test get_state() with HTTP error."""
        # Mock response with error status
        mock_response = mocker.Mock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            "404 Not Found"
        )

        # Mock requests.get
        mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient()

        with pytest.raises(VolumioAPIError) as exc_info:
            client.get_state()

        assert "HTTP error 404" in str(exc_info.value)

    def test_get_state_invalid_json(self, mocker: MockerFixture):
        """Test get_state() with invalid JSON response."""
        # Mock response with invalid JSON
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Invalid JSON")

        # Mock requests.get
        mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient()

        with pytest.raises(VolumioAPIError) as exc_info:
            client.get_state()

        assert "Failed to parse JSON" in str(exc_info.value)

    def test_get_state_non_dict_response(self, mocker: MockerFixture):
        """Test get_state() when API returns non-dictionary JSON."""
        # Mock response that returns a list instead of a dict
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = []  # list, not a dictionary

        # Mock requests.get
        mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient()

        with pytest.raises(VolumioAPIError) as exc_info:
            client.get_state()

        assert "Expected JSON object" in str(exc_info.value)
        assert "got list" in str(exc_info.value)

    def test_get_state_generic_request_exception(self, mocker: MockerFixture):
        """Test get_state() with generic RequestException."""
        # Mock requests.get to raise generic RequestException
        mocker.patch(
            "requests.get",
            side_effect=requests.exceptions.RequestException("Generic error"),
        )

        client = VolumioRESTAPIClient()

        with pytest.raises(VolumioConnectionError) as exc_info:
            client.get_state()

        assert "Request to Volumio instance" in str(exc_info.value)

    def test_get_queue_success(self, mocker: MockerFixture):
        """Test successful get_queue() call."""
        # Mock response with queue data
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "queue": [
                {
                    "title": "Song 1",
                    "artist": "Artist 1",
                    "album": "Album 1",
                    "duration": 180,
                    "service": "qobuz",
                },
                {
                    "title": "Song 2",
                    "artist": "Artist 2",
                    "album": "Album 2",
                    "duration": 200,
                    "service": "qobuz",
                },
            ]
        }

        # Mock requests.get
        mock_get = mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient()
        queue_data = client.get_queue()

        # Verify the request was made correctly
        mock_get.assert_called_once_with(
            "http://volumio.local:3000/api/v1/getQueue", timeout=5.0
        )

        # Verify the response
        assert "queue" in queue_data
        assert len(queue_data["queue"]) == 2
        assert queue_data["queue"][0]["title"] == "Song 1"
        assert queue_data["queue"][1]["title"] == "Song 2"

    def test_get_queue_connection_error(self, mocker: MockerFixture):
        """Test get_queue() with connection error."""
        # Mock requests.get to raise ConnectionError
        mocker.patch(
            "requests.get",
            side_effect=requests.exceptions.ConnectionError("Connection refused"),
        )

        client = VolumioRESTAPIClient()

        with pytest.raises(VolumioConnectionError) as exc_info:
            client.get_queue()

        assert "Failed to connect" in str(exc_info.value)

    def test_get_queue_timeout_error(self, mocker: MockerFixture):
        """Test get_queue() with timeout error."""
        # Mock requests.get to raise Timeout
        mocker.patch(
            "requests.get", side_effect=requests.exceptions.Timeout("Request timeout")
        )

        client = VolumioRESTAPIClient()

        with pytest.raises(VolumioConnectionError) as exc_info:
            client.get_queue()

        assert "timed out" in str(exc_info.value)

    def test_get_queue_http_error(self, mocker: MockerFixture):
        """Test get_queue() with HTTP error."""
        # Mock response with error status
        mock_response = mocker.Mock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            "500 Server Error"
        )

        # Mock requests.get
        mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient()

        with pytest.raises(VolumioAPIError) as exc_info:
            client.get_queue()

        assert "HTTP error 500" in str(exc_info.value)

    def test_get_queue_invalid_json(self, mocker: MockerFixture):
        """Test get_queue() with invalid JSON response."""
        # Mock response with invalid JSON
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Invalid JSON")

        # Mock requests.get
        mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient()

        with pytest.raises(VolumioAPIError) as exc_info:
            client.get_queue()

        assert "Failed to parse JSON" in str(exc_info.value)

    def test_get_queue_non_dict_response(self, mocker: MockerFixture):
        """Test get_queue() when API returns non-dictionary JSON."""
        # Mock response that returns a list instead of a dict
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = []  # list, not a dictionary

        # Mock requests.get
        mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient()

        with pytest.raises(VolumioAPIError) as exc_info:
            client.get_queue()

        assert "Expected JSON object" in str(exc_info.value)
        assert "got list" in str(exc_info.value)

    def test_get_queue_generic_request_exception(self, mocker: MockerFixture):
        """Test get_queue() with generic RequestException."""
        # Mock requests.get to raise generic RequestException
        mocker.patch(
            "requests.get",
            side_effect=requests.exceptions.RequestException("Generic error"),
        )

        client = VolumioRESTAPIClient()

        with pytest.raises(VolumioConnectionError) as exc_info:
            client.get_queue()

        assert "Request to Volumio instance" in str(exc_info.value)

    def test_send_command_success(self, mocker: MockerFixture):
        """Test successful send_command() call."""
        # Mock response
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "time": 1234567890,
            "response": "play"
        }

        # Mock requests.get
        mock_get = mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient()
        response = client.send_command("play")

        # Verify the request was made correctly
        mock_get.assert_called_once_with(
            "http://volumio.local:3000/api/v1/commands/?cmd=play", timeout=5.0
        )

        # Verify the response
        assert response["response"] == "play"

    def test_send_command_connection_error(self, mocker: MockerFixture):
        """Test send_command() with connection error."""
        # Mock requests.get to raise ConnectionError
        mocker.patch(
            "requests.get",
            side_effect=requests.exceptions.ConnectionError("Connection refused"),
        )

        client = VolumioRESTAPIClient()

        with pytest.raises(VolumioConnectionError) as exc_info:
            client.send_command("play")

        assert "Failed to connect" in str(exc_info.value)

    def test_send_command_timeout_error(self, mocker: MockerFixture):
        """Test send_command() with timeout error."""
        # Mock requests.get to raise Timeout
        mocker.patch(
            "requests.get", side_effect=requests.exceptions.Timeout("Request timeout")
        )

        client = VolumioRESTAPIClient()

        with pytest.raises(VolumioConnectionError) as exc_info:
            client.send_command("pause")

        assert "timed out" in str(exc_info.value)

    def test_send_command_http_error(self, mocker: MockerFixture):
        """Test send_command() with HTTP error."""
        # Mock response with error status
        mock_response = mocker.Mock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            "500 Server Error"
        )

        # Mock requests.get
        mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient()

        with pytest.raises(VolumioAPIError) as exc_info:
            client.send_command("stop")

        assert "HTTP error 500" in str(exc_info.value)

    def test_send_command_invalid_json(self, mocker: MockerFixture):
        """Test send_command() with invalid JSON response."""
        # Mock response with invalid JSON
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Invalid JSON")

        # Mock requests.get
        mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient()

        with pytest.raises(VolumioAPIError) as exc_info:
            client.send_command("toggle")

        assert "Failed to parse JSON" in str(exc_info.value)

    def test_send_command_non_dict_response(self, mocker: MockerFixture):
        """Test send_command() when API returns non-dictionary JSON."""
        # Mock response that returns a list instead of a dict
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = []  # list, not a dictionary

        # Mock requests.get
        mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient()

        with pytest.raises(VolumioAPIError) as exc_info:
            client.send_command("next")

        assert "Expected JSON object" in str(exc_info.value)
        assert "got list" in str(exc_info.value)

    def test_send_command_generic_request_exception(self, mocker: MockerFixture):
        """Test send_command() with generic RequestException."""
        # Mock requests.get to raise generic RequestException
        mocker.patch(
            "requests.get",
            side_effect=requests.exceptions.RequestException("Generic error"),
        )

        client = VolumioRESTAPIClient()

        with pytest.raises(VolumioConnectionError) as exc_info:
            client.send_command("toggle")

        assert "Request to Volumio instance" in str(exc_info.value)

    def test_toggle(self, mocker: MockerFixture):
        """Test toggle() method."""
        client = VolumioRESTAPIClient()
        mock_send_command = mocker.patch.object(client, "send_command")
        mock_send_command.return_value = {"response": "toggle"}

        result = client.toggle()

        mock_send_command.assert_called_once_with("toggle")
        assert result["response"] == "toggle"

    def test_play(self, mocker: MockerFixture):
        """Test play() method."""
        client = VolumioRESTAPIClient()
        mock_send_command = mocker.patch.object(client, "send_command")
        mock_send_command.return_value = {"response": "play"}

        result = client.play()

        mock_send_command.assert_called_once_with("play")
        assert result["response"] == "play"

    def test_play_with_position(self, mocker: MockerFixture):
        """Test play() method with position parameter."""
        client = VolumioRESTAPIClient()
        mock_send_command = mocker.patch.object(client, "send_command")
        mock_send_command.return_value = {"response": "play"}

        result = client.play(position=5)

        mock_send_command.assert_called_once_with("play&N=5")
        assert result["response"] == "play"

    def test_pause(self, mocker: MockerFixture):
        """Test pause() method."""
        client = VolumioRESTAPIClient()
        mock_send_command = mocker.patch.object(client, "send_command")
        mock_send_command.return_value = {"response": "pause"}

        result = client.pause()

        mock_send_command.assert_called_once_with("pause")
        assert result["response"] == "pause"

    def test_stop(self, mocker: MockerFixture):
        """Test stop() method."""
        client = VolumioRESTAPIClient()
        mock_send_command = mocker.patch.object(client, "send_command")
        mock_send_command.return_value = {"response": "stop"}

        result = client.stop()

        mock_send_command.assert_called_once_with("stop")
        assert result["response"] == "stop"

    def test_next(self, mocker: MockerFixture):
        """Test next() method."""
        client = VolumioRESTAPIClient()
        mock_send_command = mocker.patch.object(client, "send_command")
        mock_send_command.return_value = {"response": "next"}

        result = client.next()

        mock_send_command.assert_called_once_with("next")
        assert result["response"] == "next"

    def test_previous(self, mocker: MockerFixture):
        """Test previous() method."""
        client = VolumioRESTAPIClient()
        mock_send_command = mocker.patch.object(client, "send_command")
        mock_send_command.return_value = {"response": "prev"}

        result = client.previous()

        mock_send_command.assert_called_once_with("prev")
        assert result["response"] == "prev"


class TestVolumioExceptions:
    """Test cases for Volumio exception classes."""

    def test_volumio_error_is_base_exception(self):
        """Test that VolumioError is the base exception."""
        error = VolumioError("Test error")
        assert isinstance(error, Exception)
        assert str(error) == "Test error"

    def test_volumio_connection_error_inherits_from_base(self):
        """Test that VolumioConnectionError inherits from VolumioError."""
        error = VolumioConnectionError("Connection failed")
        assert isinstance(error, VolumioError)
        assert isinstance(error, Exception)

    def test_volumio_api_error_inherits_from_base(self):
        """Test that VolumioAPIError inherits from VolumioError."""
        error = VolumioAPIError("API error")
        assert isinstance(error, VolumioError)
        assert isinstance(error, Exception)
