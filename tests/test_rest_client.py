"""Tests for the REST client module.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

import pytest
import requests
from pytest_mock import MockerFixture

from volumito.clients import (
    Album,
    Artist,
    Label,
    Place,
    VolumioHostConfiguration,
)
from volumito.clients.models import CommandResponse, Playlist, Playlists, Queue, QueueTrack
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
        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        assert client.timeout == 5.0

    def test_init_custom_values(self):
        """Test VolumioRESTAPIClient initialization with custom values."""
        client = VolumioRESTAPIClient(
            VolumioHostConfiguration(
                scheme="https",
                host="192.168.1.100",
                rest_api_port=8080,
                mpd_port=7000,
            ),
            timeout=10.0,
        )

        assert client.timeout == 10.0

    def test_state_success(self, mocker: MockerFixture):
        """Test successful state property access."""
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

        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        state = client.state

        # Verify the request was made correctly
        mock_get.assert_called_once_with(
            "http://volumio.local:3000/api/v1/getState", timeout=5.0
        )

        # Verify the response
        assert state.status == "play"
        assert state.title == "Test Song"
        assert state.artist == "Test Artist"
        # The raw payload stays available on the model
        assert state.raw["service"] == "mpd"

    def test_state_connection_error(self, mocker: MockerFixture):
        """Test the state property with connection error."""
        # Mock requests.get to raise ConnectionError
        mocker.patch(
            "requests.get",
            side_effect=requests.exceptions.ConnectionError("Connection refused"),
        )

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioConnectionError) as exc_info:
            _ = client.state

        assert "Failed to connect" in str(exc_info.value)

    def test_state_timeout_error(self, mocker: MockerFixture):
        """Test the state property with timeout error."""
        # Mock requests.get to raise Timeout
        mocker.patch(
            "requests.get", side_effect=requests.exceptions.Timeout("Request timeout")
        )

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioConnectionError) as exc_info:
            _ = client.state

        assert "timed out" in str(exc_info.value)

    def test_state_http_error(self, mocker: MockerFixture):
        """Test the state property with HTTP error."""
        # Mock response with error status
        mock_response = mocker.Mock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            "404 Not Found"
        )

        # Mock requests.get
        mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioAPIError) as exc_info:
            _ = client.state

        assert "HTTP error 404" in str(exc_info.value)

    def test_state_invalid_json(self, mocker: MockerFixture):
        """Test the state property with invalid JSON response."""
        # Mock response with invalid JSON
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Invalid JSON")

        # Mock requests.get
        mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioAPIError) as exc_info:
            _ = client.state

        assert "Failed to parse JSON" in str(exc_info.value)

    def test_state_non_dict_response(self, mocker: MockerFixture):
        """Test the state property when API returns non-dictionary JSON."""
        # Mock response that returns a list instead of a dict
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = []  # list, not a dictionary

        # Mock requests.get
        mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioAPIError) as exc_info:
            _ = client.state

        assert "Expected JSON object" in str(exc_info.value)
        assert "got list" in str(exc_info.value)

    def test_state_generic_request_exception(self, mocker: MockerFixture):
        """Test the state property with generic RequestException."""
        # Mock requests.get to raise generic RequestException
        mocker.patch(
            "requests.get",
            side_effect=requests.exceptions.RequestException("Generic error"),
        )

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioConnectionError) as exc_info:
            _ = client.state

        assert "Request to Volumio instance" in str(exc_info.value)

    def test_queue_success(self, mocker: MockerFixture):
        """Test successful queue property access."""
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

        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        queue_data = client.queue

        # Verify the request was made correctly
        mock_get.assert_called_once_with(
            "http://volumio.local:3000/api/v1/getQueue", timeout=5.0
        )

        # Verify the response
        assert isinstance(queue_data, Queue)
        assert len(queue_data) == 2
        assert queue_data[0].title == "Song 1"
        assert queue_data.tracks[1].title == "Song 2"
        assert queue_data.raw["queue"][0]["service"] == "qobuz"

    def test_queue_connection_error(self, mocker: MockerFixture):
        """Test the queue property with connection error."""
        # Mock requests.get to raise ConnectionError
        mocker.patch(
            "requests.get",
            side_effect=requests.exceptions.ConnectionError("Connection refused"),
        )

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioConnectionError) as exc_info:
            _ = client.queue

        assert "Failed to connect" in str(exc_info.value)

    def test_queue_timeout_error(self, mocker: MockerFixture):
        """Test the queue property with timeout error."""
        # Mock requests.get to raise Timeout
        mocker.patch(
            "requests.get", side_effect=requests.exceptions.Timeout("Request timeout")
        )

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioConnectionError) as exc_info:
            _ = client.queue

        assert "timed out" in str(exc_info.value)

    def test_queue_http_error(self, mocker: MockerFixture):
        """Test the queue property with HTTP error."""
        # Mock response with error status
        mock_response = mocker.Mock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            "500 Server Error"
        )

        # Mock requests.get
        mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioAPIError) as exc_info:
            _ = client.queue

        assert "HTTP error 500" in str(exc_info.value)

    def test_queue_invalid_json(self, mocker: MockerFixture):
        """Test the queue property with invalid JSON response."""
        # Mock response with invalid JSON
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Invalid JSON")

        # Mock requests.get
        mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioAPIError) as exc_info:
            _ = client.queue

        assert "Failed to parse JSON" in str(exc_info.value)

    def test_queue_non_dict_response(self, mocker: MockerFixture):
        """Test the queue property when API returns non-dictionary JSON."""
        # Mock response that returns a list instead of a dict
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = []  # list, not a dictionary

        # Mock requests.get
        mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioAPIError) as exc_info:
            _ = client.queue

        assert "Expected JSON object" in str(exc_info.value)
        assert "got list" in str(exc_info.value)

    def test_queue_generic_request_exception(self, mocker: MockerFixture):
        """Test the queue property with generic RequestException."""
        # Mock requests.get to raise generic RequestException
        mocker.patch(
            "requests.get",
            side_effect=requests.exceptions.RequestException("Generic error"),
        )

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioConnectionError) as exc_info:
            _ = client.queue

        assert "Request to Volumio instance" in str(exc_info.value)

    def test_ping_success(self, mocker: MockerFixture):
        """Test successful ping() returns the response body text."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.text = "pong"
        mock_get = mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        result = client.ping()

        mock_get.assert_called_once_with(
            "http://volumio.local:3000/api/v1/ping", timeout=5.0
        )
        assert result == "pong"

    def test_ping_connection_error(self, mocker: MockerFixture):
        """Test ping() translates a connection error."""
        mocker.patch(
            "requests.get",
            side_effect=requests.exceptions.ConnectionError("Connection refused"),
        )

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioConnectionError) as exc_info:
            client.ping()

        assert "Failed to connect" in str(exc_info.value)

    def test_ping_http_error(self, mocker: MockerFixture):
        """Test ping() translates an HTTP error."""
        mock_response = mocker.Mock()
        mock_response.status_code = 503
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            "503 Service Unavailable"
        )
        mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioAPIError) as exc_info:
            client.ping()

        assert "HTTP error 503" in str(exc_info.value)

    def test_system_version_success(self, mocker: MockerFixture):
        """Test successful system_version property access."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "systemversion": "3.601",
            "builddate": "2023-01-01",
            "variant": "volumio",
            "hardware": "pi",
        }
        mock_get = mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        data = client.system_version

        mock_get.assert_called_once_with(
            "http://volumio.local:3000/api/v1/getSystemVersion", timeout=5.0
        )
        assert data.system_version == "3.601"

    def test_system_version_timeout_error(self, mocker: MockerFixture):
        """Test the system_version property translates a timeout error."""
        mocker.patch(
            "requests.get", side_effect=requests.exceptions.Timeout("Request timeout")
        )

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioConnectionError) as exc_info:
            _ = client.system_version

        assert "timed out" in str(exc_info.value)

    def test_system_version_invalid_json(self, mocker: MockerFixture):
        """Test the system_version property with an invalid JSON response."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioAPIError) as exc_info:
            _ = client.system_version

        assert "Failed to parse JSON" in str(exc_info.value)

    def test_system_info_success(self, mocker: MockerFixture):
        """Test successful system_info property access."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "abc",
            "host": "http://volumio.local",
            "name": "volumio",
            "systemversion": "3.601",
        }
        mock_get = mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        data = client.system_info

        mock_get.assert_called_once_with(
            "http://volumio.local:3000/api/v1/getSystemInfo", timeout=5.0
        )
        assert data.name == "volumio"

    def test_system_info_non_dict_response(self, mocker: MockerFixture):
        """Test the system_info property when the API returns non-dictionary JSON."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = []
        mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioAPIError) as exc_info:
            _ = client.system_info

        assert "Expected JSON object" in str(exc_info.value)

    def test_system_info_generic_request_exception(self, mocker: MockerFixture):
        """Test the system_info property with a generic RequestException."""
        mocker.patch(
            "requests.get",
            side_effect=requests.exceptions.RequestException("Generic error"),
        )

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioConnectionError) as exc_info:
            _ = client.system_info

        assert "Request to Volumio instance" in str(exc_info.value)

    def test_collection_statistics_success(self, mocker: MockerFixture):
        """Test successful collection_statistics property access."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "artists": 3,
            "albums": 4,
            "songs": 105,
            "playtime": "7:11:15",
        }
        mock_get = mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        data = client.collection_statistics

        mock_get.assert_called_once_with(
            "http://volumio.local:3000/api/v1/collectionstats", timeout=5.0
        )
        assert data.songs == 105

    def test_collection_statistics_connection_error(self, mocker: MockerFixture):
        """Test the collection_statistics property translates a connection error."""
        mocker.patch(
            "requests.get",
            side_effect=requests.exceptions.ConnectionError("Connection failed"),
        )

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioConnectionError) as exc_info:
            _ = client.collection_statistics

        assert "Failed to connect to Volumio instance" in str(exc_info.value)

    def test_collection_statistics_invalid_json(self, mocker: MockerFixture):
        """Test the collection_statistics property with an invalid JSON response."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioAPIError) as exc_info:
            _ = client.collection_statistics

        assert "Failed to parse JSON" in str(exc_info.value)

    def test_zones_success(self, mocker: MockerFixture):
        """Test successful zones property access."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "zones": [
                {"id": "abc", "host": "http://192.168.1.1", "name": "Volumio", "isSelf": True}
            ]
        }
        mock_get = mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        data = client.zones

        mock_get.assert_called_once_with(
            "http://volumio.local:3000/api/v1/getzones", timeout=5.0
        )
        assert data[0].name == "Volumio"
        assert data.zones[0].is_self is True

    def test_zones_connection_error(self, mocker: MockerFixture):
        """Test the zones property translates a connection error."""
        mocker.patch(
            "requests.get",
            side_effect=requests.exceptions.ConnectionError("Connection failed"),
        )

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioConnectionError) as exc_info:
            _ = client.zones

        assert "Failed to connect to Volumio instance" in str(exc_info.value)

    def test_zones_invalid_json(self, mocker: MockerFixture):
        """Test the zones property with an invalid JSON response."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioAPIError) as exc_info:
            _ = client.zones

        assert "Failed to parse JSON" in str(exc_info.value)

    def test_playlists_success(self, mocker: MockerFixture):
        """Test successful playlists property access."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = ["Rock", "Jazz"]
        mock_get = mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        data = client.playlists

        mock_get.assert_called_once_with(
            "http://volumio.local:3000/api/v1/listplaylists", timeout=5.0
        )
        assert data.names == ["Rock", "Jazz"]
        assert data[0].name == "Rock"
        assert "Jazz" in data
        # The listed names stay available on the model
        assert data.raw == ["Rock", "Jazz"]

    def test_playlists_connection_error(self, mocker: MockerFixture):
        """Test the playlists property translates a connection error."""
        mocker.patch(
            "requests.get",
            side_effect=requests.exceptions.ConnectionError("Connection failed"),
        )

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioConnectionError) as exc_info:
            _ = client.playlists

        assert "Failed to connect to Volumio instance" in str(exc_info.value)

    def test_playlists_invalid_json(self, mocker: MockerFixture):
        """Test the playlists property with an invalid JSON response."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioAPIError) as exc_info:
            _ = client.playlists

        assert "Failed to parse JSON" in str(exc_info.value)

    def test_playlists_non_list_response(self, mocker: MockerFixture):
        """Test the playlists property rejects a payload that is not a JSON array."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"playlists": ["Rock"]}
        mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioAPIError) as exc_info:
            _ = client.playlists

        assert "Expected JSON array from Volumio API, got dict" in str(exc_info.value)

    def test_play_playlist_success(self, mocker: MockerFixture):
        """Test successful play_playlist() call."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": "playPlaylist Response"}
        mock_get = mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        data = client.play_playlist("Rock")

        mock_get.assert_called_once_with(
            "http://volumio.local:3000/api/v1/commands/?cmd=playplaylist&name=Rock",
            timeout=5.0,
        )
        assert data.response == "playPlaylist Response"

    def test_play_playlist_with_a_playlist(self, mocker: MockerFixture):
        """Test play_playlist() call with one of the saved playlists."""
        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        mock_send_command = mocker.patch.object(client, "_send_command")
        mock_send_command.return_value = CommandResponse.from_raw({"response": "playPlaylist"})
        playlists = Playlists.from_names(["Jazz Classics", "Rock"])

        result = client.play_playlist(playlists[0])

        mock_send_command.assert_called_once_with("playplaylist&name=Jazz%20Classics")
        assert result.response == "playPlaylist"

    def test_play_playlist_with_a_nameless_playlist(self, mocker: MockerFixture):
        """Test play_playlist() call with a playlist that has no name."""
        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        mock_send_command = mocker.patch.object(client, "_send_command")

        with pytest.raises(ValueError, match="no name"):
            client.play_playlist(Playlist.from_raw({}))

        mock_send_command.assert_not_called()

    def test_play_playlist_name_is_percent_encoded(self, mocker: MockerFixture):
        """Test play_playlist() percent-encodes the playlist name."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": "playPlaylist Response"}
        mock_get = mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        client.play_playlist("Rock & Roll/Best")

        mock_get.assert_called_once_with(
            "http://volumio.local:3000/api/v1/commands/"
            "?cmd=playplaylist&name=Rock%20%26%20Roll%2FBest",
            timeout=5.0,
        )

    def test_play_playlist_connection_error(self, mocker: MockerFixture):
        """Test play_playlist() translates a connection error."""
        mocker.patch(
            "requests.get",
            side_effect=requests.exceptions.ConnectionError("Connection failed"),
        )

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioConnectionError) as exc_info:
            client.play_playlist("Rock")

        assert "Failed to connect to Volumio instance" in str(exc_info.value)

    def test_plugin_endpoint_success(self, mocker: MockerFixture):
        """Test successful _plugin_endpoint() call."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "success": True,
            "data": {"type": "story", "value": "A story."},
        }
        mock_post = mocker.patch("requests.post", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        data = client._plugin_endpoint(
            "metavolumio", {"mode": "storyAlbum", "artist": "Mango", "album": "Sirtaki"}
        )

        mock_post.assert_called_once_with(
            "http://volumio.local:3000/api/v1/pluginEndpoint",
            json={
                "endpoint": "metavolumio",
                "data": {"mode": "storyAlbum", "artist": "Mango", "album": "Sirtaki"},
            },
            timeout=5.0,
        )
        assert data["success"] is True
        assert data["data"]["value"] == "A story."

    def test_plugin_endpoint_connection_error(self, mocker: MockerFixture):
        """Test _plugin_endpoint() with connection error."""
        mocker.patch(
            "requests.post",
            side_effect=requests.exceptions.ConnectionError("Connection refused"),
        )

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioConnectionError) as exc_info:
            client._plugin_endpoint("metavolumio", {"mode": "storyArtist", "artist": "Mango"})

        assert "Failed to connect" in str(exc_info.value)

    def test_plugin_endpoint_timeout_error(self, mocker: MockerFixture):
        """Test _plugin_endpoint() with timeout error."""
        mocker.patch(
            "requests.post", side_effect=requests.exceptions.Timeout("Request timeout")
        )

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioConnectionError) as exc_info:
            client._plugin_endpoint("metavolumio", {"mode": "storyArtist", "artist": "Mango"})

        assert "timed out" in str(exc_info.value)

    def test_plugin_endpoint_http_error(self, mocker: MockerFixture):
        """Test _plugin_endpoint() with HTTP error."""
        mock_response = mocker.Mock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            "404 Not Found"
        )
        mocker.patch("requests.post", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioAPIError) as exc_info:
            client._plugin_endpoint("metavolumio", {"mode": "storyArtist", "artist": "Mango"})

        assert "HTTP error 404" in str(exc_info.value)

    def test_plugin_endpoint_invalid_json(self, mocker: MockerFixture):
        """Test _plugin_endpoint() with invalid JSON response."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mocker.patch("requests.post", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioAPIError) as exc_info:
            client._plugin_endpoint("metavolumio", {"mode": "storyArtist", "artist": "Mango"})

        assert "Failed to parse JSON" in str(exc_info.value)

    def test_plugin_endpoint_non_dict_response(self, mocker: MockerFixture):
        """Test _plugin_endpoint() when API returns non-dictionary JSON."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = []  # list, not a dictionary
        mocker.patch("requests.post", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioAPIError) as exc_info:
            client._plugin_endpoint("metavolumio", {"mode": "storyArtist", "artist": "Mango"})

        assert "Expected JSON object" in str(exc_info.value)
        assert "got list" in str(exc_info.value)

    def test_plugin_endpoint_generic_request_exception(self, mocker: MockerFixture):
        """Test _plugin_endpoint() with generic RequestException."""
        mocker.patch(
            "requests.post",
            side_effect=requests.exceptions.RequestException("Generic error"),
        )

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioConnectionError) as exc_info:
            client._plugin_endpoint("metavolumio", {"mode": "storyArtist", "artist": "Mango"})

        assert "Request to Volumio instance" in str(exc_info.value)

    def _mock_story_post(self, mocker: MockerFixture):
        """Mock requests.post with a successful metavolumio envelope response."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "success": True,
            "data": {"type": "story", "value": "A story."},
        }
        return mocker.patch("requests.post", return_value=mock_response)

    def _assert_story_posted(self, mock_post, data):
        """Assert that the metavolumio endpoint was called with the given data payload."""
        mock_post.assert_called_once_with(
            "http://volumio.local:3000/api/v1/pluginEndpoint",
            json={"endpoint": "metavolumio", "data": data},
            timeout=5.0,
        )

    def test_get_story_artist_name(self, mocker: MockerFixture):
        """Test get_story() with an artist by name."""
        mock_post = self._mock_story_post(mocker)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        story = client.get_story(artist=Artist("Mango"))

        self._assert_story_posted(mock_post, {"mode": "storyArtist", "artist": "Mango"})
        assert story.type == "story"
        assert story.value == "A story."
        # The whole response envelope stays available on the model
        assert story.raw == {"success": True, "data": {"type": "story", "value": "A story."}}

    def test_get_story_artist_mbid(self, mocker: MockerFixture):
        """Test get_story() with an artist by MBID."""
        mock_post = self._mock_story_post(mocker)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        client.get_story(artist=Artist("83d91898-7763-47d7-b03b-b92132375c47", is_mbid=True))

        self._assert_story_posted(
            mock_post,
            {"mode": "storyArtist", "mbid": "83d91898-7763-47d7-b03b-b92132375c47"},
        )

    def test_get_story_album_pair(self, mocker: MockerFixture):
        """Test get_story() with an album by title and its artist."""
        mock_post = self._mock_story_post(mocker)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        client.get_story(album=Album("Sirtaki"), artist=Artist("Mango"))

        self._assert_story_posted(
            mock_post, {"mode": "storyAlbum", "artist": "Mango", "album": "Sirtaki"}
        )

    def test_get_story_album_mbid(self, mocker: MockerFixture):
        """Test get_story() with an album by MBID."""
        mock_post = self._mock_story_post(mocker)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        client.get_story(album=Album("mbid-value", is_mbid=True))

        self._assert_story_posted(mock_post, {"mode": "storyAlbum", "mbid": "mbid-value"})

    def test_get_story_label_name(self, mocker: MockerFixture):
        """Test get_story() with a label by name."""
        mock_post = self._mock_story_post(mocker)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        client.get_story(label=Label("Blue Note"))

        self._assert_story_posted(mock_post, {"mode": "storyLabel", "label": "Blue Note"})

    def test_get_story_label_mbid(self, mocker: MockerFixture):
        """Test get_story() with a label by MBID."""
        mock_post = self._mock_story_post(mocker)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        client.get_story(label=Label("mbid-value", is_mbid=True))

        self._assert_story_posted(mock_post, {"mode": "storyLabel", "mbid": "mbid-value"})

    def test_get_story_place_name(self, mocker: MockerFixture):
        """Test get_story() with a place by name."""
        mock_post = self._mock_story_post(mocker)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        client.get_story(place=Place("Abbey Road Studios"))

        self._assert_story_posted(
            mock_post, {"mode": "storyPlace", "place": "Abbey Road Studios"}
        )

    def test_get_story_no_entities(self, mocker: MockerFixture):
        """Test get_story() without any entity."""
        mock_post = self._mock_story_post(mocker)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(ValueError, match="One of album, artist, label, or place"):
            client.get_story()
        mock_post.assert_not_called()

    def test_get_story_label_and_place(self, mocker: MockerFixture):
        """Test get_story() with both a label and a place."""
        mock_post = self._mock_story_post(mocker)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(ValueError, match="mutually exclusive"):
            client.get_story(label=Label("Blue Note"), place=Place("Abbey Road Studios"))
        mock_post.assert_not_called()

    def test_get_story_album_and_label(self, mocker: MockerFixture):
        """Test get_story() with both an album and a label."""
        mock_post = self._mock_story_post(mocker)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(ValueError, match="does not take a label or place"):
            client.get_story(
                album=Album("Sirtaki"), artist=Artist("Mango"), label=Label("Blue Note")
            )
        mock_post.assert_not_called()

    def test_get_story_artist_and_place(self, mocker: MockerFixture):
        """Test get_story() with both an artist and a place."""
        mock_post = self._mock_story_post(mocker)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(ValueError, match="does not take a label or place"):
            client.get_story(artist=Artist("Mango"), place=Place("Abbey Road Studios"))
        mock_post.assert_not_called()

    def test_get_story_album_without_artist(self, mocker: MockerFixture):
        """Test get_story() with an album by title but no artist."""
        mock_post = self._mock_story_post(mocker)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(ValueError, match="requires an artist"):
            client.get_story(album=Album("Sirtaki"))
        mock_post.assert_not_called()

    def test_get_story_album_mbid_with_artist(self, mocker: MockerFixture):
        """Test get_story() with an album by MBID and an artist."""
        mock_post = self._mock_story_post(mocker)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(ValueError, match="does not take an artist"):
            client.get_story(album=Album("mbid-value", is_mbid=True), artist=Artist("Mango"))
        mock_post.assert_not_called()

    def test_get_story_album_with_mbid_artist(self, mocker: MockerFixture):
        """Test get_story() with an album by title and an artist by MBID."""
        mock_post = self._mock_story_post(mocker)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(ValueError, match="artist by name, not by MBID"):
            client.get_story(
                album=Album("Sirtaki"), artist=Artist("mbid-value", is_mbid=True)
            )
        mock_post.assert_not_called()

    def test_get_album_credits_pair(self, mocker: MockerFixture):
        """Test get_album_credits() with an album by title and its artist."""
        mock_post = self._mock_story_post(mocker)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        story = client.get_album_credits(Artist("Mango"), Album("Sirtaki"))

        self._assert_story_posted(
            mock_post, {"mode": "creditsAlbum", "artist": "Mango", "album": "Sirtaki"}
        )
        assert story.value == "A story."

    def test_get_album_credits_mbid(self, mocker: MockerFixture):
        """Test get_album_credits() with an album by MBID."""
        mock_post = self._mock_story_post(mocker)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        client.get_album_credits(None, Album("mbid-value", is_mbid=True))

        self._assert_story_posted(mock_post, {"mode": "creditsAlbum", "mbid": "mbid-value"})

    def test_get_album_credits_album_without_artist(self, mocker: MockerFixture):
        """Test get_album_credits() with an album by title but no artist."""
        mock_post = self._mock_story_post(mocker)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(ValueError, match="requires an artist"):
            client.get_album_credits(None, Album("Sirtaki"))
        mock_post.assert_not_called()

    def test_send_command_success(self, mocker: MockerFixture):
        """Test successful _send_command() call."""
        # Mock response
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "time": 1234567890,
            "response": "play"
        }

        # Mock requests.get
        mock_get = mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        response = client._send_command("play")

        # Verify the request was made correctly
        mock_get.assert_called_once_with(
            "http://volumio.local:3000/api/v1/commands/?cmd=play", timeout=5.0
        )

        # Verify the response
        assert response.response == "play"
        assert response.time == 1234567890

    def test_send_command_connection_error(self, mocker: MockerFixture):
        """Test _send_command() with connection error."""
        # Mock requests.get to raise ConnectionError
        mocker.patch(
            "requests.get",
            side_effect=requests.exceptions.ConnectionError("Connection refused"),
        )

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioConnectionError) as exc_info:
            client._send_command("play")

        assert "Failed to connect" in str(exc_info.value)

    def test_send_command_timeout_error(self, mocker: MockerFixture):
        """Test _send_command() with timeout error."""
        # Mock requests.get to raise Timeout
        mocker.patch(
            "requests.get", side_effect=requests.exceptions.Timeout("Request timeout")
        )

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioConnectionError) as exc_info:
            client._send_command("pause")

        assert "timed out" in str(exc_info.value)

    def test_send_command_http_error(self, mocker: MockerFixture):
        """Test _send_command() with HTTP error."""
        # Mock response with error status
        mock_response = mocker.Mock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            "500 Server Error"
        )

        # Mock requests.get
        mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioAPIError) as exc_info:
            client._send_command("stop")

        assert "HTTP error 500" in str(exc_info.value)

    def test_send_command_invalid_json(self, mocker: MockerFixture):
        """Test _send_command() with invalid JSON response."""
        # Mock response with invalid JSON
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Invalid JSON")

        # Mock requests.get
        mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioAPIError) as exc_info:
            client._send_command("toggle")

        assert "Failed to parse JSON" in str(exc_info.value)

    def test_send_command_non_dict_response(self, mocker: MockerFixture):
        """Test _send_command() when API returns non-dictionary JSON."""
        # Mock response that returns a list instead of a dict
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = []  # list, not a dictionary

        # Mock requests.get
        mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioAPIError) as exc_info:
            client._send_command("next")

        assert "Expected JSON object" in str(exc_info.value)
        assert "got list" in str(exc_info.value)

    def test_send_command_generic_request_exception(self, mocker: MockerFixture):
        """Test _send_command() with generic RequestException."""
        # Mock requests.get to raise generic RequestException
        mocker.patch(
            "requests.get",
            side_effect=requests.exceptions.RequestException("Generic error"),
        )

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioConnectionError) as exc_info:
            client._send_command("toggle")

        assert "Request to Volumio instance" in str(exc_info.value)

    def test_toggle(self, mocker: MockerFixture):
        """Test toggle() method."""
        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        mock_send_command = mocker.patch.object(client, "_send_command")
        mock_send_command.return_value = CommandResponse.from_raw({"response": "toggle"})

        result = client.toggle()

        mock_send_command.assert_called_once_with("toggle")
        assert result.response == "toggle"

    def test_play(self, mocker: MockerFixture):
        """Test play() method."""
        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        mock_send_command = mocker.patch.object(client, "_send_command")
        mock_send_command.return_value = CommandResponse.from_raw({"response": "play"})

        result = client.play()

        mock_send_command.assert_called_once_with("play")
        assert result.response == "play"

    def test_play_with_position(self, mocker: MockerFixture):
        """Test play() method with position parameter."""
        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        mock_send_command = mocker.patch.object(client, "_send_command")
        mock_send_command.return_value = CommandResponse.from_raw({"response": "play"})

        result = client.play(position=5)

        mock_send_command.assert_called_once_with("play&N=5")
        assert result.response == "play"

    def test_play_with_queue_track(self, mocker: MockerFixture):
        """Test play() method with a track of the queue."""
        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        mock_send_command = mocker.patch.object(client, "_send_command")
        mock_send_command.return_value = CommandResponse.from_raw({"response": "play"})
        queue = Queue.from_raw({"queue": [{"title": "A"}, {"title": "B"}, {"title": "C"}]})

        result = client.play(queue[2])

        mock_send_command.assert_called_once_with("play&N=2")
        assert result.response == "play"

    def test_play_with_a_track_outside_a_queue(self, mocker: MockerFixture):
        """Test play() method with a track that does not know its position."""
        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        mock_send_command = mocker.patch.object(client, "_send_command")

        with pytest.raises(ValueError, match="does not belong to a queue"):
            client.play(QueueTrack.from_raw({"title": "A"}))

        mock_send_command.assert_not_called()

    def test_pause(self, mocker: MockerFixture):
        """Test pause() method."""
        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        mock_send_command = mocker.patch.object(client, "_send_command")
        mock_send_command.return_value = CommandResponse.from_raw({"response": "pause"})

        result = client.pause()

        mock_send_command.assert_called_once_with("pause")
        assert result.response == "pause"

    def test_stop(self, mocker: MockerFixture):
        """Test stop() method."""
        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        mock_send_command = mocker.patch.object(client, "_send_command")
        mock_send_command.return_value = CommandResponse.from_raw({"response": "stop"})

        result = client.stop()

        mock_send_command.assert_called_once_with("stop")
        assert result.response == "stop"

    def test_next(self, mocker: MockerFixture):
        """Test next() method."""
        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        mock_send_command = mocker.patch.object(client, "_send_command")
        mock_send_command.return_value = CommandResponse.from_raw({"response": "next"})

        result = client.next()

        mock_send_command.assert_called_once_with("next")
        assert result.response == "next"

    def test_previous(self, mocker: MockerFixture):
        """Test previous() method."""
        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        mock_send_command = mocker.patch.object(client, "_send_command")
        mock_send_command.return_value = CommandResponse.from_raw({"response": "prev"})

        result = client.previous()

        mock_send_command.assert_called_once_with("prev")
        assert result.response == "prev"

    def test_volume_setter(self, mocker: MockerFixture):
        """Test setting the volume property to an absolute integer level."""
        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        mock_send_command = mocker.patch.object(client, "_send_command")
        mock_send_command.return_value = CommandResponse.from_raw({"response": "volume"})

        client.volume = 50

        mock_send_command.assert_called_once_with("volume&volume=50")

    @pytest.mark.parametrize("value", [-1, 101])
    def test_volume_setter_out_of_range(self, mocker: MockerFixture, value: int):
        """Test setting the volume property rejects an out-of-range level."""
        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        mock_send_command = mocker.patch.object(client, "_send_command")

        with pytest.raises(ValueError, match="between 0 and 100"):
            client.volume = value

        mock_send_command.assert_not_called()

    def test_volume_getter(self, mocker: MockerFixture):
        """Test reading the volume property from the playback state."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "play", "volume": 49}
        mock_get = mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        assert client.volume == 49
        mock_get.assert_called_once_with(
            "http://volumio.local:3000/api/v1/getState", timeout=5.0
        )

    @pytest.mark.parametrize(
        "state",
        [{"status": "play"}, {"status": "play", "volume": "loud"}],
        ids=["missing", "not-an-integer"],
    )
    def test_volume_getter_invalid_level(self, mocker: MockerFixture, state: dict):
        """Test reading the volume property with a missing or non-integer level."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = state
        mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioAPIError, match="integer volume level"):
            _ = client.volume

    def test_increase_volume(self, mocker: MockerFixture):
        """Test increase_volume() method."""
        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        mock_send_command = mocker.patch.object(client, "_send_command")
        mock_send_command.return_value = CommandResponse.from_raw({"response": "volume"})

        result = client.increase_volume()

        mock_send_command.assert_called_once_with("volume&volume=plus")
        assert result.response == "volume"

    def test_decrease_volume(self, mocker: MockerFixture):
        """Test decrease_volume() method."""
        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        mock_send_command = mocker.patch.object(client, "_send_command")
        mock_send_command.return_value = CommandResponse.from_raw({"response": "volume"})

        result = client.decrease_volume()

        mock_send_command.assert_called_once_with("volume&volume=minus")
        assert result.response == "volume"

    @pytest.mark.parametrize("value", [True, False])
    def test_is_muted(self, mocker: MockerFixture, value: bool):
        """Test reading the is_muted property from the playback state."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "play", "mute": value}
        mock_get = mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        assert client.is_muted is value
        mock_get.assert_called_once_with(
            "http://volumio.local:3000/api/v1/getState", timeout=5.0
        )

    @pytest.mark.parametrize(
        "state",
        [{"status": "play"}, {"status": "play", "mute": "maybe"}],
        ids=["missing", "not-a-boolean"],
    )
    def test_is_muted_invalid_flag(self, mocker: MockerFixture, state: dict):
        """Test reading the is_muted property with a missing or non-boolean flag."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = state
        mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioAPIError, match="boolean mute flag"):
            _ = client.is_muted

    @pytest.mark.parametrize(
        ("status", "playing", "paused", "stopped"),
        [
            ("play", True, False, False),
            ("pause", False, True, False),
            ("stop", False, False, True),
        ],
    )
    def test_is_playing_is_paused_is_stopped(
        self,
        mocker: MockerFixture,
        status: str,
        playing: bool,
        paused: bool,
        stopped: bool,
    ):
        """Test reading the status-based boolean properties from the playback state."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": status, "volume": 49}
        mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        assert client.is_playing is playing
        assert client.is_paused is paused
        assert client.is_stopped is stopped

    @pytest.mark.parametrize(
        "state",
        [{"volume": 49}, {"volume": 49, "status": 1}],
        ids=["missing", "not-a-string"],
    )
    @pytest.mark.parametrize("name", ["is_playing", "is_paused", "is_stopped"])
    def test_is_playing_is_paused_invalid_status(
        self, mocker: MockerFixture, name: str, state: dict
    ):
        """Test the status-based boolean properties with a missing or non-string status."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = state
        mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioAPIError, match="string status"):
            _ = getattr(client, name)

    def test_mute(self, mocker: MockerFixture):
        """Test mute() method."""
        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        mock_send_command = mocker.patch.object(client, "_send_command")
        mock_send_command.return_value = CommandResponse.from_raw({"response": "volume"})

        result = client.mute()

        mock_send_command.assert_called_once_with("volume&volume=mute")
        assert result.response == "volume"

    def test_unmute(self, mocker: MockerFixture):
        """Test unmute() method."""
        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        mock_send_command = mocker.patch.object(client, "_send_command")
        mock_send_command.return_value = CommandResponse.from_raw({"response": "volume"})

        result = client.unmute()

        mock_send_command.assert_called_once_with("volume&volume=unmute")
        assert result.response == "volume"

    def test_seek_setter(self, mocker: MockerFixture):
        """Test setting the seek property to a number of seconds."""
        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        mock_send_command = mocker.patch.object(client, "_send_command")
        mock_send_command.return_value = CommandResponse.from_raw({"response": "seek"})

        client.seek = 252

        mock_send_command.assert_called_once_with("seek&position=252")

    def test_seek_getter(self, mocker: MockerFixture):
        """Test reading the seek property from the playback state, in whole seconds."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "play", "seek": 125029}
        mock_get = mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        # The state reports milliseconds, rounded down to seconds
        assert client.seek == 125
        mock_get.assert_called_once_with(
            "http://volumio.local:3000/api/v1/getState", timeout=5.0
        )

    @pytest.mark.parametrize(
        "state",
        [{"status": "play"}, {"status": "play", "seek": "early"}],
        ids=["missing", "not-an-integer"],
    )
    def test_seek_getter_invalid_position(self, mocker: MockerFixture, state: dict):
        """Test reading the seek property with a missing or non-integer position."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = state
        mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioAPIError, match="integer seek position"):
            _ = client.seek

    def test_seek_backward(self, mocker: MockerFixture):
        """Test seek_backward() method."""
        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        mock_send_command = mocker.patch.object(client, "_send_command")
        mock_send_command.return_value = CommandResponse.from_raw({"response": "seek"})

        result = client.seek_backward()

        mock_send_command.assert_called_once_with("seek&position=minus")
        assert result.response == "seek"

    def test_seek_forward(self, mocker: MockerFixture):
        """Test seek_forward() method."""
        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        mock_send_command = mocker.patch.object(client, "_send_command")
        mock_send_command.return_value = CommandResponse.from_raw({"response": "seek"})

        result = client.seek_forward()

        mock_send_command.assert_called_once_with("seek&position=plus")
        assert result.response == "seek"

    def test_seek_connection_error(self, mocker: MockerFixture):
        """Test the seek setter translates a connection error."""
        mocker.patch(
            "requests.get",
            side_effect=requests.exceptions.ConnectionError("Connection failed"),
        )

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioConnectionError) as exc_info:
            client.seek = 10

        assert "Failed to connect to Volumio instance" in str(exc_info.value)

    def test_clear(self, mocker: MockerFixture):
        """Test clear() method sends the clearQueue command."""
        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        mock_send_command = mocker.patch.object(client, "_send_command")
        mock_send_command.return_value = CommandResponse.from_raw({"response": "clearQueue"})

        result = client.clear()

        mock_send_command.assert_called_once_with("clearQueue")
        assert result.response == "clearQueue"

    def test_repeat_toggle(self, mocker: MockerFixture):
        """Test repeat() with no value sends the bare repeat command (toggle)."""
        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        mock_send_command = mocker.patch.object(client, "_send_command")
        mock_send_command.return_value = CommandResponse.from_raw({"response": "repeat"})

        result = client.repeat()

        mock_send_command.assert_called_once_with("repeat")
        assert result.response == "repeat"

    def test_repeat_on(self, mocker: MockerFixture):
        """Test repeat(True) sends the repeat command with value=true."""
        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        mock_send_command = mocker.patch.object(client, "_send_command")
        mock_send_command.return_value = CommandResponse.from_raw({"response": "repeat"})

        client.repeat(True)

        mock_send_command.assert_called_once_with("repeat&value=true")

    def test_repeat_off(self, mocker: MockerFixture):
        """Test repeat(False) sends the repeat command with value=false."""
        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        mock_send_command = mocker.patch.object(client, "_send_command")
        mock_send_command.return_value = CommandResponse.from_raw({"response": "repeat"})

        client.repeat(False)

        mock_send_command.assert_called_once_with("repeat&value=false")

    def test_randomize_toggle(self, mocker: MockerFixture):
        """Test randomize() with no value sends the bare random command (toggle)."""
        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        mock_send_command = mocker.patch.object(client, "_send_command")
        mock_send_command.return_value = CommandResponse.from_raw({"response": "random"})

        result = client.randomize()

        mock_send_command.assert_called_once_with("random")
        assert result.response == "random"

    def test_randomize_on(self, mocker: MockerFixture):
        """Test randomize(True) sends the random command with value=true."""
        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        mock_send_command = mocker.patch.object(client, "_send_command")
        mock_send_command.return_value = CommandResponse.from_raw({"response": "random"})

        client.randomize(True)

        mock_send_command.assert_called_once_with("random&value=true")

    def test_randomize_off(self, mocker: MockerFixture):
        """Test randomize(False) sends the random command with value=false."""
        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        mock_send_command = mocker.patch.object(client, "_send_command")
        mock_send_command.return_value = CommandResponse.from_raw({"response": "random"})

        client.randomize(False)

        mock_send_command.assert_called_once_with("random&value=false")


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
