"""Tests for the MPD client module."""

import pytest
from pytest_mock import MockerFixture

from volumito.clients.errors import VolumioConnectionError
from volumito.clients.mpd import VolumioMPDClient


class TestVolumioMPDClient:
    """Test cases for the VolumioMPDClient class."""

    def test_init_default_values(self):
        """Test VolumioMPDClient initialization with default values."""
        client = VolumioMPDClient()

        assert client.host == "volumio.local"
        assert client.port == 6599
        assert client.timeout == 5.0
        assert client._connected is False

    def test_init_custom_values(self):
        """Test VolumioMPDClient initialization with custom values."""
        client = VolumioMPDClient(
            host="192.168.1.100",
            port=7000,
            timeout=10.0,
        )

        assert client.host == "192.168.1.100"
        assert client.port == 7000
        assert client.timeout == 10.0

    def test_connect_success(self, mocker: MockerFixture):
        """Test successful connection to MPD."""
        mock_mpd = mocker.Mock()
        mocker.patch("volumito.clients.mpd.client.MPDClient", return_value=mock_mpd)

        client = VolumioMPDClient()
        client.connect()

        mock_mpd.connect.assert_called_once_with("volumio.local", 6599)
        assert client._connected is True

    def test_connect_connection_refused(self, mocker: MockerFixture):
        """Test connection with ConnectionRefusedError."""
        mock_mpd = mocker.Mock()
        mock_mpd.connect.side_effect = ConnectionRefusedError("Connection refused")
        mocker.patch("volumito.clients.mpd.client.MPDClient", return_value=mock_mpd)

        client = VolumioMPDClient()

        with pytest.raises(VolumioConnectionError) as exc_info:
            client.connect()

        assert "Connection refused to MPD" in str(exc_info.value)
        assert client._connected is False

    def test_connect_os_error(self, mocker: MockerFixture):
        """Test connection with OSError."""
        mock_mpd = mocker.Mock()
        mock_mpd.connect.side_effect = OSError("Network unreachable")
        mocker.patch("volumito.clients.mpd.client.MPDClient", return_value=mock_mpd)

        client = VolumioMPDClient()

        with pytest.raises(VolumioConnectionError) as exc_info:
            client.connect()

        assert "MPD connection error" in str(exc_info.value)

    def test_connect_generic_exception(self, mocker: MockerFixture):
        """Test connection with generic exception."""
        mock_mpd = mocker.Mock()
        mock_mpd.connect.side_effect = Exception("Unexpected error")
        mocker.patch("volumito.clients.mpd.client.MPDClient", return_value=mock_mpd)

        client = VolumioMPDClient()

        with pytest.raises(VolumioConnectionError) as exc_info:
            client.connect()

        assert "Failed to connect to MPD" in str(exc_info.value)

    def test_disconnect_when_connected(self, mocker: MockerFixture):
        """Test disconnect when connected."""
        mock_mpd = mocker.Mock()
        mocker.patch("volumito.clients.mpd.client.MPDClient", return_value=mock_mpd)

        client = VolumioMPDClient()
        client.connect()
        client.disconnect()

        mock_mpd.close.assert_called_once()
        mock_mpd.disconnect.assert_called_once()
        assert client._connected is False

    def test_disconnect_when_not_connected(self, mocker: MockerFixture):
        """Test disconnect when not connected (should be no-op)."""
        mock_mpd = mocker.Mock()
        mocker.patch("volumito.clients.mpd.client.MPDClient", return_value=mock_mpd)

        client = VolumioMPDClient()
        client.disconnect()

        mock_mpd.close.assert_not_called()
        mock_mpd.disconnect.assert_not_called()

    def test_get_current_song_success(self, mocker: MockerFixture):
        """Test successful get_current_song() call."""
        mock_mpd = mocker.Mock()
        mock_mpd.currentsong.return_value = {
            "file": "http://localhost:8000/music/test.flac",
            "title": "Test Song",
            "artist": "Test Artist",
        }
        mocker.patch("volumito.clients.mpd.client.MPDClient", return_value=mock_mpd)

        client = VolumioMPDClient()
        client.connect()
        song = client.get_current_song()

        assert song["file"] == "http://localhost:8000/music/test.flac"
        assert song["title"] == "Test Song"
        assert song["artist"] == "Test Artist"

    def test_get_current_song_not_connected(self):
        """Test get_current_song() when not connected."""
        client = VolumioMPDClient()

        with pytest.raises(VolumioConnectionError) as exc_info:
            client.get_current_song()

        assert "Not connected to MPD" in str(exc_info.value)

    def test_get_current_song_no_track_playing(self, mocker: MockerFixture):
        """Test get_current_song() when no track is playing."""
        mock_mpd = mocker.Mock()
        mock_mpd.currentsong.return_value = {}
        mocker.patch("volumito.clients.mpd.client.MPDClient", return_value=mock_mpd)

        client = VolumioMPDClient()
        client.connect()

        with pytest.raises(VolumioConnectionError) as exc_info:
            client.get_current_song()

        assert "No track currently playing" in str(exc_info.value)

    def test_get_current_song_no_file_field(self, mocker: MockerFixture):
        """Test get_current_song() when response has no file field."""
        mock_mpd = mocker.Mock()
        mock_mpd.currentsong.return_value = {"title": "Test"}
        mocker.patch("volumito.clients.mpd.client.MPDClient", return_value=mock_mpd)

        client = VolumioMPDClient()
        client.connect()

        with pytest.raises(VolumioConnectionError) as exc_info:
            client.get_current_song()

        assert "No track currently playing" in str(exc_info.value)

    def test_get_current_song_mpd_error(self, mocker: MockerFixture):
        """Test get_current_song() with MPD error."""
        mock_mpd = mocker.Mock()
        mock_mpd.currentsong.side_effect = Exception("MPD protocol error")
        mocker.patch("volumito.clients.mpd.client.MPDClient", return_value=mock_mpd)

        client = VolumioMPDClient()
        client.connect()

        with pytest.raises(VolumioConnectionError) as exc_info:
            client.get_current_song()

        assert "MPD error" in str(exc_info.value)

    def test_get_track_uri_with_localhost(self, mocker: MockerFixture):
        """Test get_track_uri() replaces localhost with actual host."""
        mock_mpd = mocker.Mock()
        mock_mpd.currentsong.return_value = {
            "file": "http://localhost:8000/music/test.flac"
        }
        mocker.patch("volumito.clients.mpd.client.MPDClient", return_value=mock_mpd)

        client = VolumioMPDClient(host="volumio.local")
        client.connect()
        uri = client.get_track_uri()

        assert uri == "http://volumio.local:8000/music/test.flac"
        assert "localhost" not in uri

    def test_get_track_uri_with_127_0_0_1(self, mocker: MockerFixture):
        """Test get_track_uri() replaces 127.0.0.1 with actual host."""
        mock_mpd = mocker.Mock()
        mock_mpd.currentsong.return_value = {
            "file": "http://127.0.0.1:8000/music/test.flac"
        }
        mocker.patch("volumito.clients.mpd.client.MPDClient", return_value=mock_mpd)

        client = VolumioMPDClient(host="192.168.1.100")
        client.connect()
        uri = client.get_track_uri()

        assert uri == "http://192.168.1.100:8000/music/test.flac"
        assert "127.0.0.1" not in uri

    def test_get_track_uri_with_both_localhost_and_ip(self, mocker: MockerFixture):
        """Test get_track_uri() replaces both localhost and 127.0.0.1."""
        mock_mpd = mocker.Mock()
        mock_mpd.currentsong.return_value = {
            "file": "http://localhost:8000/music/test.flac?host=127.0.0.1"
        }
        mocker.patch("volumito.clients.mpd.client.MPDClient", return_value=mock_mpd)

        client = VolumioMPDClient(host="myhost.local")
        client.connect()
        uri = client.get_track_uri()

        assert "localhost" not in uri
        assert "127.0.0.1" not in uri
        assert "myhost.local" in uri

    def test_context_manager_success(self, mocker: MockerFixture):
        """Test context manager with successful connection."""
        mock_mpd = mocker.Mock()
        mock_mpd.currentsong.return_value = {"file": "http://localhost:8000/test.flac"}
        mocker.patch("volumito.clients.mpd.client.MPDClient", return_value=mock_mpd)

        with VolumioMPDClient() as client:
            assert client._connected is True
            uri = client.get_track_uri()
            assert "volumio.local" in uri

        # Should be disconnected after exiting context
        assert client._connected is False
        mock_mpd.close.assert_called_once()
        mock_mpd.disconnect.assert_called_once()

    def test_context_manager_with_exception(self, mocker: MockerFixture):
        """Test context manager disconnects even when exception occurs."""
        mock_mpd = mocker.Mock()
        mock_mpd.currentsong.side_effect = Exception("Test error")
        mocker.patch("volumito.clients.mpd.client.MPDClient", return_value=mock_mpd)

        with pytest.raises(VolumioConnectionError):
            with VolumioMPDClient() as client:
                assert client._connected is True
                client.get_current_song()

        # Should still be disconnected after exception
        assert client._connected is False
        mock_mpd.close.assert_called_once()
        mock_mpd.disconnect.assert_called_once()

    def test_context_manager_connection_failure(self, mocker: MockerFixture):
        """Test context manager when connection fails."""
        mock_mpd = mocker.Mock()
        mock_mpd.connect.side_effect = ConnectionRefusedError("Connection refused")
        mocker.patch("volumito.clients.mpd.client.MPDClient", return_value=mock_mpd)

        client = VolumioMPDClient()
        with pytest.raises(VolumioConnectionError):
            with client:
                pass  # Should not reach here

        # Should not call disconnect if connection failed
        assert client._connected is False
        mock_mpd.close.assert_not_called()
        mock_mpd.disconnect.assert_not_called()
