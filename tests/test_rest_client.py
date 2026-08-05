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
from volumito.clients.models import (
    CommandResponse,
    Notification,
    Playlist,
    Playlists,
    Queue,
    QueueTrack,
)
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


    def test_notifications_success(self, mocker: MockerFixture):
        """Test successful notifications property access."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = ["http://192.168.1.100/receiver"]
        mock_get = mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        data = client.notifications

        mock_get.assert_called_once_with(
            "http://volumio.local:3000/api/v1/pushNotificationUrls", timeout=5.0
        )
        assert data.urls == ["http://192.168.1.100/receiver"]
        assert data[0].url == "http://192.168.1.100/receiver"
        assert "http://192.168.1.100/receiver" in data
        # The listed URLs stay available on the model
        assert data.raw == ["http://192.168.1.100/receiver"]

    def test_notifications_connection_error(self, mocker: MockerFixture):
        """Test the notifications property translates a connection error."""
        mocker.patch(
            "requests.get",
            side_effect=requests.exceptions.ConnectionError("Connection failed"),
        )

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioConnectionError) as exc_info:
            _ = client.notifications

        assert "Failed to connect to Volumio instance" in str(exc_info.value)

    def test_notifications_invalid_json(self, mocker: MockerFixture):
        """Test the notifications property with an invalid JSON response."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioAPIError) as exc_info:
            _ = client.notifications

        assert "Failed to parse JSON" in str(exc_info.value)

    def test_notifications_non_list_response(self, mocker: MockerFixture):
        """Test the notifications property rejects a payload that is not a JSON array."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"urls": []}
        mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioAPIError) as exc_info:
            _ = client.notifications

        assert "Expected JSON array from Volumio API, got dict" in str(exc_info.value)

    def test_register_notification_success(self, mocker: MockerFixture):
        """Test register_notification() posts the URL and reads the outcome."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True}
        mock_post = mocker.patch("requests.post", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        result = client.register_notification("http://192.168.1.100/receiver")

        mock_post.assert_called_once_with(
            "http://volumio.local:3000/api/v1/pushNotificationUrls",
            json={"url": "http://192.168.1.100/receiver"},
            timeout=5.0,
        )
        assert result.success is True
        assert result.is_success

    def test_register_notification_accepts_a_notification(self, mocker: MockerFixture):
        """Test register_notification() accepts a notification instead of a URL."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True}
        mock_post = mocker.patch("requests.post", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        client.register_notification(Notification.from_url("http://192.168.1.100/receiver"))

        mock_post.assert_called_once_with(
            "http://volumio.local:3000/api/v1/pushNotificationUrls",
            json={"url": "http://192.168.1.100/receiver"},
            timeout=5.0,
        )

    def test_register_notification_without_a_url(self, mocker: MockerFixture):
        """Test register_notification() rejects a notification carrying no URL."""
        mock_post = mocker.patch("requests.post")

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(ValueError) as exc_info:
            client.register_notification(Notification())

        assert "The notification has no URL" in str(exc_info.value)
        mock_post.assert_not_called()

    def test_register_notification_connection_error(self, mocker: MockerFixture):
        """Test register_notification() translates a connection error."""
        mocker.patch(
            "requests.post",
            side_effect=requests.exceptions.ConnectionError("Connection failed"),
        )

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioConnectionError) as exc_info:
            client.register_notification("http://192.168.1.100/receiver")

        assert "Failed to connect to Volumio instance" in str(exc_info.value)

    def test_unregister_notification_success(self, mocker: MockerFixture):
        """Test unregister_notification() deletes the URL and reads the outcome."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.text = '{"success": true}'
        mock_response.json.return_value = {"success": True}
        mock_delete = mocker.patch("requests.delete", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        result = client.unregister_notification("http://192.168.1.100/receiver")

        mock_delete.assert_called_once_with(
            "http://volumio.local:3000/api/v1/pushNotificationUrls",
            json={"url": "http://192.168.1.100/receiver"},
            timeout=5.0,
        )
        assert result.success is True

    def test_unregister_notification_accepts_a_notification(self, mocker: MockerFixture):
        """Test unregister_notification() accepts a notification instead of a URL."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.text = '{"success": true}'
        mock_response.json.return_value = {"success": True}
        mock_delete = mocker.patch("requests.delete", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        client.unregister_notification(Notification.from_url("http://192.168.1.100/receiver"))

        mock_delete.assert_called_once_with(
            "http://volumio.local:3000/api/v1/pushNotificationUrls",
            json={"url": "http://192.168.1.100/receiver"},
            timeout=5.0,
        )

    def test_unregister_notification_refused(self, mocker: MockerFixture):
        """Test unregister_notification() reads the error of a refused request."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.text = '{"error": "No such URL is present"}'
        mock_response.json.return_value = {"error": "No such URL is present"}
        mocker.patch("requests.delete", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        result = client.unregister_notification("http://192.168.1.100/receiver")

        assert result.error == "No such URL is present"
        assert not result.is_success

    def test_unregister_notification_empty_response(self, mocker: MockerFixture):
        """Test unregister_notification() accepts a response without a body."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.text = ""
        mocker.patch("requests.delete", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        result = client.unregister_notification("http://192.168.1.100/receiver")

        assert result.success is None
        assert result.is_success
        assert result.raw == {}

    def test_unregister_notification_without_a_url(self, mocker: MockerFixture):
        """Test unregister_notification() rejects a notification carrying no URL."""
        mock_delete = mocker.patch("requests.delete")

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(ValueError) as exc_info:
            client.unregister_notification(Notification())

        assert "The notification has no URL" in str(exc_info.value)
        mock_delete.assert_not_called()

    def test_unregister_notification_http_error(self, mocker: MockerFixture):
        """Test unregister_notification() translates an HTTP error."""
        mock_response = mocker.Mock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            "500 Server Error"
        )
        mocker.patch("requests.delete", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioAPIError) as exc_info:
            client.unregister_notification("http://192.168.1.100/receiver")

        assert "HTTP error 500" in str(exc_info.value)

    def test_unregister_notification_non_dict_response(self, mocker: MockerFixture):
        """Test unregister_notification() rejects a payload that is not a JSON object."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.text = "[]"
        mock_response.json.return_value = []
        mocker.patch("requests.delete", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioAPIError) as exc_info:
            client.unregister_notification("http://192.168.1.100/receiver")

        assert "Expected JSON object from Volumio API, got list" in str(exc_info.value)


    def test_search_success(self, mocker: MockerFixture):
        """Test successful search() call."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "navigation": {
                "isSearchResult": True,
                "lists": [
                    {
                        "title": "Found 1 Artist 'paolo conte'",
                        "items": [
                            {
                                "service": "mpd",
                                "type": "folder",
                                "title": "Paolo Conte",
                                "uri": "artists://Paolo%20Conte",
                            }
                        ],
                    }
                ],
            }
        }
        mock_get = mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        results = client.search("Paolo Conte")

        mock_get.assert_called_once_with(
            "http://volumio.local:3000/api/v1/search?query=Paolo%20Conte", timeout=5.0
        )
        assert len(results) == 1
        assert results[0].title == "Found 1 Artist 'paolo conte'"
        assert results.items[0].kind == "artist"
        # The whole envelope stays available on the model
        assert results.raw == mock_response.json.return_value

    def test_search_connection_error(self, mocker: MockerFixture):
        """Test search() translates a connection error."""
        mocker.patch(
            "requests.get",
            side_effect=requests.exceptions.ConnectionError("Connection failed"),
        )

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioConnectionError) as exc_info:
            client.search("Paolo Conte")

        assert "Failed to connect to Volumio instance" in str(exc_info.value)

    def test_search_non_dict_response(self, mocker: MockerFixture):
        """Test search() rejects a payload that is not a JSON object."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = []
        mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioAPIError) as exc_info:
            client.search("Paolo Conte")

        assert "Expected JSON object from Volumio API, got list" in str(exc_info.value)

    def test_browse_root(self, mocker: MockerFixture):
        """Test browse() asking for the root when no URI is given."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "navigation": {
                # The root answers with its items directly in the lists array
                "lists": [
                    {
                        "name": "Music Library",
                        "uri": "music-library",
                        "plugin_type": "music_service",
                        "plugin_name": "mpd",
                    }
                ],
                "prev": {"uri": "/"},
            }
        }
        mock_get = mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        results = client.browse()

        mock_get.assert_called_once_with(
            "http://volumio.local:3000/api/v1/browse?uri=/", timeout=5.0
        )
        assert len(results) == 1
        assert results.items[0].name == "Music Library"
        assert results.items[0].plugin_name == "mpd"
        assert results.prev_uri == "/"
        # The whole envelope stays available on the model
        assert results.raw == mock_response.json.return_value

    def test_browse_the_root_uri(self, mocker: MockerFixture):
        """Test browse("/") asking for the root explicitly."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"navigation": {"lists": []}}
        mock_get = mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        client.browse("/")

        mock_get.assert_called_once_with(
            "http://volumio.local:3000/api/v1/browse?uri=/", timeout=5.0
        )

    def test_browse_encodes_the_uri(self, mocker: MockerFixture):
        """Test browse() encoding a URI without touching its escapes and structure."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"navigation": {"lists": []}}
        mock_get = mocker.patch("requests.get", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        # The %20 the host itself wrote stays; the bare space and the accent are encoded
        client.browse("albums://Paolo%20Conte/Città vuota")

        mock_get.assert_called_once_with(
            "http://volumio.local:3000/api/v1/browse"
            "?uri=albums://Paolo%20Conte/Citt%C3%A0%20vuota",
            timeout=5.0,
        )

    def test_browse_connection_error(self, mocker: MockerFixture):
        """Test browse() translates a connection error."""
        mocker.patch(
            "requests.get",
            side_effect=requests.exceptions.ConnectionError("Connection failed"),
        )

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioConnectionError) as exc_info:
            client.browse("music-library")

        assert "Failed to connect to Volumio instance" in str(exc_info.value)

    def test_add_to_queue_success(self, mocker: MockerFixture):
        """Test add_to_queue() posts the URI as an item and reads the outcome."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": "success"}
        mock_post = mocker.patch("requests.post", return_value=mock_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        result = client.add_to_queue("albums://Paolo%20Conte/Aguaplano")

        mock_post.assert_called_once_with(
            "http://volumio.local:3000/api/v1/addToQueue",
            json={"service": "mpd", "uri": "albums://Paolo%20Conte/Aguaplano"},
            timeout=5.0,
        )
        assert result.response == "success"

    @pytest.mark.parametrize(
        ("uri", "service"),
        [
            ("music-library/INTERNAL/music/track.flac", "mpd"),
            ("albums://Paolo%20Conte/Aguaplano", "mpd"),
            ("artists://Paolo%20Conte", "mpd"),
            ("genres://Jazz", "mpd"),
            ("playlists", "mpd"),
            ("qobuz://album/0884977674569", "qobuz"),
            ("tidal://song/123", "tidal"),
            ("http://opml.radiotime.com/Tune.ashx?id=s339255", "webradio"),
            ("https://stream.example/radio", "webradio"),
            ("spotify:track:abc", "spop"),
        ],
    )
    def test_the_service_of_a_uri(self, mocker: MockerFixture, uri, service):
        """The service is read from the URI, since the host defaults to mpd silently."""
        browse_response = mocker.Mock()
        browse_response.status_code = 200
        browse_response.json.return_value = {}
        mocker.patch("requests.get", return_value=browse_response)
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": "success"}
        mock_post = mocker.patch("requests.post", return_value=mock_response)

        VolumioRESTAPIClient(VolumioHostConfiguration()).add_to_queue(uri)

        mock_post.assert_called_once_with(
            "http://volumio.local:3000/api/v1/addToQueue",
            json={"service": service, "uri": uri},
            timeout=5.0,
        )

    def test_add_to_queue_a_container_of_another_source(self, mocker: MockerFixture):
        """A non-local container is browsed and queued as its items: only mpd explodes."""
        first = {"service": "qobuz", "type": "song", "title": "One", "uri": "qobuz://song/1"}
        second = {"service": "qobuz", "type": "song", "title": "Two", "uri": "qobuz://song/2"}
        browse_response = mocker.Mock()
        browse_response.status_code = 200
        browse_response.json.return_value = {"navigation": {"lists": [{"items": [first, second]}]}}
        mock_get = mocker.patch("requests.get", return_value=browse_response)
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": "success"}
        mock_post = mocker.patch("requests.post", return_value=mock_response)

        VolumioRESTAPIClient(VolumioHostConfiguration()).add_to_queue("qobuz://album/123")

        mock_get.assert_called_once_with(
            "http://volumio.local:3000/api/v1/browse?uri=qobuz://album/123", timeout=5.0
        )
        mock_post.assert_called_once_with(
            "http://volumio.local:3000/api/v1/addToQueue",
            json=[first, second],
            timeout=5.0,
        )

    def test_add_to_queue_of_the_local_library_is_not_browsed(self, mocker: MockerFixture):
        """A local URI is queued as itself: the host explodes its own containers."""
        mock_get = mocker.patch("requests.get")
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": "success"}
        mocker.patch("requests.post", return_value=mock_response)

        VolumioRESTAPIClient(VolumioHostConfiguration()).add_to_queue("artists://Paolo%20Conte")

        mock_get.assert_not_called()

    def test_add_to_queue_connection_error(self, mocker: MockerFixture):
        """Test add_to_queue() translates a connection error."""
        mocker.patch(
            "requests.post",
            side_effect=requests.exceptions.ConnectionError("Connection failed"),
        )

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioConnectionError) as exc_info:
            client.add_to_queue("albums://Paolo%20Conte/Aguaplano")

        assert "Failed to connect to Volumio instance" in str(exc_info.value)

    def test_replace_queue_and_play_without_an_index(self, mocker: MockerFixture):
        """Test replace_queue_and_play() posts the item form, without browsing."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": "success"}
        mock_post = mocker.patch("requests.post", return_value=mock_response)
        mock_get = mocker.patch("requests.get")

        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        result = client.replace_queue_and_play("albums://Paolo%20Conte/Aguaplano")

        mock_post.assert_called_once_with(
            "http://volumio.local:3000/api/v1/replaceAndPlay",
            json={"item": {"service": "mpd", "uri": "albums://Paolo%20Conte/Aguaplano"}},
            timeout=5.0,
        )
        mock_get.assert_not_called()
        assert result.response == "success"

    def test_replace_queue_and_play_a_container_of_another_source(self, mocker: MockerFixture):
        """Without an index, a non-local container is still browsed and sent as its items."""
        item = {"service": "qobuz", "type": "song", "title": "One", "uri": "qobuz://song/1"}
        browse_response = mocker.Mock()
        browse_response.status_code = 200
        browse_response.json.return_value = {"navigation": {"lists": [{"items": [item]}]}}
        mocker.patch("requests.get", return_value=browse_response)
        play_response = mocker.Mock()
        play_response.status_code = 200
        play_response.json.return_value = {"response": "success"}
        mock_post = mocker.patch("requests.post", return_value=play_response)

        VolumioRESTAPIClient(VolumioHostConfiguration()).replace_queue_and_play(
            "qobuz://album/123"
        )

        mock_post.assert_called_once_with(
            "http://volumio.local:3000/api/v1/replaceAndPlay",
            json={"list": [item], "index": 0},
            timeout=5.0,
        )

    def test_replace_queue_and_play_a_single_of_another_source(self, mocker: MockerFixture):
        """Without an index, a non-local URI listing nothing is sent as an item."""
        browse_response = mocker.Mock()
        browse_response.status_code = 200
        browse_response.json.return_value = {}
        mocker.patch("requests.get", return_value=browse_response)
        play_response = mocker.Mock()
        play_response.status_code = 200
        play_response.json.return_value = {"response": "success"}
        mock_post = mocker.patch("requests.post", return_value=play_response)

        VolumioRESTAPIClient(VolumioHostConfiguration()).replace_queue_and_play(
            "qobuz://song/2210819"
        )

        mock_post.assert_called_once_with(
            "http://volumio.local:3000/api/v1/replaceAndPlay",
            json={"item": {"service": "qobuz", "uri": "qobuz://song/2210819"}},
            timeout=5.0,
        )

    def test_replace_queue_and_play_with_an_index(self, mocker: MockerFixture):
        """Test replace_queue_and_play() browses the URI and posts its items untouched."""
        first = {"service": "mpd", "type": "song", "title": "One", "uri": "music-library/1.flac"}
        second = {"service": "mpd", "type": "song", "title": "Two", "uri": "music-library/2.flac"}
        browse_response = mocker.Mock()
        browse_response.status_code = 200
        browse_response.json.return_value = {"navigation": {"lists": [{"items": [first, second]}]}}
        mock_get = mocker.patch("requests.get", return_value=browse_response)
        play_response = mocker.Mock()
        play_response.status_code = 200
        play_response.json.return_value = {"response": "success"}
        mock_post = mocker.patch("requests.post", return_value=play_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        result = client.replace_queue_and_play("albums://X/Y", 1)

        mock_get.assert_called_once_with(
            "http://volumio.local:3000/api/v1/browse?uri=albums://X/Y", timeout=5.0
        )
        mock_post.assert_called_once_with(
            "http://volumio.local:3000/api/v1/replaceAndPlay",
            json={"list": [first, second], "index": 1},
            timeout=5.0,
        )
        assert result.response == "success"

    def test_replace_queue_and_play_index_zero_of_a_listing(self, mocker: MockerFixture):
        """Test replace_queue_and_play() uses the list form for index 0 too."""
        item = {"service": "mpd", "type": "song", "title": "One", "uri": "music-library/1.flac"}
        browse_response = mocker.Mock()
        browse_response.status_code = 200
        browse_response.json.return_value = {"navigation": {"lists": [{"items": [item]}]}}
        mocker.patch("requests.get", return_value=browse_response)
        play_response = mocker.Mock()
        play_response.status_code = 200
        play_response.json.return_value = {"response": "success"}
        mock_post = mocker.patch("requests.post", return_value=play_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        client.replace_queue_and_play("albums://X/Y", 0)

        mock_post.assert_called_once_with(
            "http://volumio.local:3000/api/v1/replaceAndPlay",
            json={"list": [item], "index": 0},
            timeout=5.0,
        )

    def test_replace_queue_and_play_index_zero_of_a_single_track(self, mocker: MockerFixture):
        """Test replace_queue_and_play() falls back to the item form for an unbrowsable URI."""
        browse_response = mocker.Mock()
        browse_response.status_code = 200
        browse_response.json.return_value = {}
        mocker.patch("requests.get", return_value=browse_response)
        play_response = mocker.Mock()
        play_response.status_code = 200
        play_response.json.return_value = {"response": "success"}
        mock_post = mocker.patch("requests.post", return_value=play_response)

        client = VolumioRESTAPIClient(VolumioHostConfiguration())
        client.replace_queue_and_play("music-library/INTERNAL/music/track.flac", 0)

        mock_post.assert_called_once_with(
            "http://volumio.local:3000/api/v1/replaceAndPlay",
            json={"item": {"service": "mpd", "uri": "music-library/INTERNAL/music/track.flac"}},
            timeout=5.0,
        )

    @pytest.mark.parametrize(
        ("lists", "index"),
        [
            ([], 1),
            ([{"items": [{"title": "One", "uri": "music-library/1.flac"}]}], 1),
        ],
        ids=["nothing-listed", "beyond-the-items"],
    )
    def test_replace_queue_and_play_not_enough_items(
        self, mocker: MockerFixture, lists, index
    ):
        """Test replace_queue_and_play() refuses an index the URI has no item for."""
        browse_response = mocker.Mock()
        browse_response.status_code = 200
        browse_response.json.return_value = {"navigation": {"lists": lists}}
        mocker.patch("requests.get", return_value=browse_response)
        mock_post = mocker.patch("requests.post")

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioAPIError) as exc_info:
            client.replace_queue_and_play("albums://X/Y", index)

        assert "not enough to play" in str(exc_info.value)
        mock_post.assert_not_called()

    def test_replace_queue_and_play_negative_index(self, mocker: MockerFixture):
        """Test replace_queue_and_play() rejects a negative index without any request."""
        mock_get = mocker.patch("requests.get")
        mock_post = mocker.patch("requests.post")

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(ValueError) as exc_info:
            client.replace_queue_and_play("albums://X/Y", -1)

        assert "must be 0 or greater" in str(exc_info.value)
        mock_get.assert_not_called()
        mock_post.assert_not_called()

    def test_replace_queue_and_play_connection_error(self, mocker: MockerFixture):
        """Test replace_queue_and_play() translates a connection error."""
        mocker.patch(
            "requests.post",
            side_effect=requests.exceptions.ConnectionError("Connection failed"),
        )

        client = VolumioRESTAPIClient(VolumioHostConfiguration())

        with pytest.raises(VolumioConnectionError) as exc_info:
            client.replace_queue_and_play("albums://X/Y")

        assert "Failed to connect to Volumio instance" in str(exc_info.value)


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
