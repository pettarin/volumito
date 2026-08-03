"""Tests for the Volumio response models.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

import pytest

from volumito.clients.errors import VolumioAPIError, VolumioStoryError
from volumito.clients.models import (
    CollectionStatistics,
    CommandResponse,
    DeviceState,
    PlayerState,
    Playlist,
    Playlists,
    Queue,
    QueueTrack,
    Story,
    SystemInfo,
    SystemVersion,
    Zone,
    Zones,
)


class TestVolumioModel:
    """Test cases for the behavior shared by every response model."""

    def test_raw_is_preserved(self):
        """The whole payload is available in raw, including the unknown keys."""
        payload = {"status": "play", "title": "A Song", "brandNewKey": [1, 2]}

        state = PlayerState.from_raw(payload)

        assert state.raw == payload
        assert state.raw["brandNewKey"] == [1, 2]

    def test_unknown_keys_are_not_attributes(self):
        """A key the model does not describe does not become an attribute."""
        state = PlayerState.from_raw({"brandNewKey": 1})

        assert not hasattr(state, "brandNewKey")

    def test_raw_is_excluded_from_the_dump(self):
        """The raw payload is not part of the serialized model."""
        state = PlayerState.from_raw({"status": "play"})

        dumped = state.model_dump()

        assert "raw" not in dumped
        assert dumped["status"] == "play"
        assert "raw" not in repr(state)

    def test_missing_values_default_to_none(self):
        """Every field of an empty payload defaults to None."""
        state = PlayerState.from_raw({})

        assert state.status is None
        assert state.title is None
        assert state.raw == {}

    def test_unusable_value_is_dropped(self):
        """A value that does not fit its field is dropped, but kept in raw."""
        state = PlayerState.from_raw({"volume": "loud", "seek": "early", "title": "A Song"})

        assert state.volume is None
        assert state.seek is None
        assert state.title == "A Song"
        assert state.raw["volume"] == "loud"

    def test_unusable_value_in_a_list_drops_the_list(self):
        """A list the field cannot hold is dropped, but kept in raw."""
        queue = Queue.from_raw({"queue": "not a list of tracks"})

        assert queue.tracks == []
        assert queue.raw["queue"] == "not a list of tracks"

    def test_from_raw_rejects_a_non_mapping(self):
        """A payload that is not a JSON object is reported as an API error."""
        with pytest.raises(VolumioAPIError) as exc_info:
            PlayerState.from_raw(["not", "an", "object"])  # type: ignore[arg-type]

        assert "Unexpected response from the Volumio API" in str(exc_info.value)

    def test_values_are_accepted_by_field_name(self):
        """A value can also be given by field name instead of by alias."""
        state = PlayerState.from_raw({"track_type": "qobuz"})

        assert state.track_type == "qobuz"


class TestCollectionStatistics:
    """Test cases for the CollectionStatistics model."""

    def test_parses_the_payload(self):
        """The statistics are parsed, with the playtime kept as text."""
        statistics = CollectionStatistics.from_raw(
            {"artists": 3, "albums": 4, "songs": 105, "playtime": "7:11:15"}
        )

        assert statistics.artists == 3
        assert statistics.albums == 4
        assert statistics.songs == 105
        assert statistics.playtime == "7:11:15"


class TestCommandResponse:
    """Test cases for the CommandResponse model."""

    def test_parses_the_payload(self):
        """The command outcome and its timestamp are parsed."""
        response = CommandResponse.from_raw({"time": 1785775249407, "response": "volume Success"})

        assert response.response == "volume Success"
        assert response.time == 1785775249407


class TestPlayerState:
    """Test cases for the PlayerState model."""

    def test_parses_a_full_payload(self):
        """A full playback state is parsed, mapping the camelCase keys to aliases."""
        state = PlayerState.from_raw(
            {
                "status": "play",
                "position": 0,
                "title": "Va tutto bene",
                "artist": "Enrico Ruggeri",
                "album": "Polvere",
                "albumart": "https://example.com/cover.jpg",
                "uri": "qobuz://song/2833718",
                "trackType": "qobuz",
                "seek": 250,
                "duration": 196,
                "samplerate": "44.1 kHz",
                "bitdepth": "16 bit",
                "channels": 2,
                "bitrate": "1 Kbps",
                "random": False,
                "repeat": False,
                "repeatSingle": False,
                "consume": True,
                "volume": 50,
                "dbVolume": None,
                "mute": False,
                "disableVolumeControl": False,
                "stream": False,
                "updatedb": False,
                "volatile": False,
                "service": "mpd",
            }
        )

        assert state.title == "Va tutto bene"
        assert state.track_type == "qobuz"
        assert state.repeat_single is False
        assert state.disable_volume_control is False
        assert state.db_volume is None
        assert state.seek == 250
        assert state.duration == 196
        assert state.channels == 2
        assert state.service == "mpd"

    def test_parses_the_optional_track_fields(self):
        """The album artist and track number are parsed when the host reports them."""
        state = PlayerState.from_raw({"albumartist": "Mango", "tracknumber": 3})

        assert state.albumartist == "Mango"
        assert state.tracknumber == 3

    def test_optional_track_fields_default_to_none(self):
        """The album artist and track number are absent from most payloads."""
        state = PlayerState.from_raw({"title": "A Song"})

        assert state.albumartist is None
        assert state.tracknumber is None

    def test_stream_accepts_a_flag_or_a_name(self):
        """The stream field holds either a boolean flag or the kind of stream."""
        assert PlayerState.from_raw({"stream": False}).stream is False
        assert PlayerState.from_raw({"stream": "qobuz"}).stream == "qobuz"

    @pytest.mark.parametrize(
        ("status", "playing", "paused", "stopped"),
        [
            ("play", True, False, False),
            ("pause", False, True, False),
            ("stop", False, False, True),
            (None, False, False, False),
        ],
        ids=["play", "pause", "stop", "missing"],
    )
    def test_playback_flags(self, status, playing, paused, stopped):
        """The playback flags are true only for their own status."""
        state = PlayerState.from_raw({} if status is None else {"status": status})

        assert state.is_playing is playing
        assert state.is_paused is paused
        assert state.is_stopped is stopped


class TestPlaylists:
    """Test cases for the Playlists and Playlist models."""

    _NAMES = ["Jazz Classics", "Rock", "Sunday Morning"]

    def test_parses_the_names(self):
        """Every listed name becomes a playlist, in the order reported."""
        playlists = Playlists.from_names(self._NAMES)

        assert playlists.names == self._NAMES
        assert playlists.playlists[0].name == "Jazz Classics"

    def test_keeps_the_listed_names_as_raw(self):
        """The collection keeps the array, and each playlist the name it was listed as."""
        playlists = Playlists.from_names(self._NAMES)

        assert playlists.raw == self._NAMES
        assert playlists[1].raw == "Rock"

    def test_is_a_sequence_of_its_playlists(self):
        """The collection can be measured, indexed, and iterated."""
        playlists = Playlists.from_names(self._NAMES)

        assert len(playlists) == 3
        assert playlists[2].name == "Sunday Morning"
        assert [playlist.name for playlist in playlists] == self._NAMES

    def test_membership_by_name_and_by_playlist(self):
        """Membership accepts either a name or a playlist."""
        playlists = Playlists.from_names(self._NAMES)

        assert "Rock" in playlists
        assert "No Such Playlist" not in playlists
        assert playlists[0] in playlists
        assert Playlist.from_name("No Such Playlist") not in playlists

    def test_names_skip_the_unnamed_playlists(self):
        """A playlist without a name is not listed among the names."""
        playlists = Playlists.from_raw({"playlists": [{"name": "Rock"}, {}]})

        assert len(playlists) == 2
        assert playlists.names == ["Rock"]

    def test_no_playlists(self):
        """An empty listing has no playlists."""
        playlists = Playlists.from_names([])

        assert len(playlists) == 0
        assert playlists.names == []
        assert playlists.raw == []

    def test_playlist_from_name(self):
        """A playlist can also be built on its own."""
        playlist = Playlist.from_name("Rock")

        assert playlist.name == "Rock"
        assert playlist.raw == "Rock"


class TestQueue:
    """Test cases for the Queue and QueueTrack models."""

    _PAYLOAD = {
        "queue": [
            {
                "album": "Polvere",
                "albumUri": "qobuz://album/0090317058467",
                "artist": "Enrico Ruggeri",
                "artistUri": "qobuz://artist/178398",
                "audioQuality": "",
                "duration": 195,
                "explicit": False,
                "name": "Va tutto bene",
                "tagImage": "",
                "title": "Va tutto bene",
                "trackType": "qobuz",
                "tracknumber": 1,
                "type": "track",
                "volumeNumber": 1,
            },
            {"title": "Fuoco sui giocattoli", "tracknumber": 2},
        ]
    }

    def test_parses_the_tracks(self):
        """The queue entries are parsed into tracks, aliases included."""
        queue = Queue.from_raw(self._PAYLOAD)

        assert queue.tracks[0].title == "Va tutto bene"
        assert queue.tracks[0].album_uri == "qobuz://album/0090317058467"
        assert queue.tracks[0].artist_uri == "qobuz://artist/178398"
        assert queue.tracks[0].audio_quality == ""
        assert queue.tracks[0].tag_image == ""
        assert queue.tracks[0].track_type == "qobuz"
        assert queue.tracks[0].volume_number == 1
        assert queue.tracks[0].explicit is False

    def test_is_a_sequence_of_its_tracks(self):
        """The queue can be measured, indexed, and iterated."""
        queue = Queue.from_raw(self._PAYLOAD)

        assert len(queue) == 2
        assert queue[1].title == "Fuoco sui giocattoli"
        assert [track.tracknumber for track in queue] == [1, 2]

    def test_each_track_keeps_its_raw_payload(self):
        """Every nested track holds the payload it was parsed from."""
        queue = Queue.from_raw(self._PAYLOAD)

        assert queue[0].raw["albumUri"] == "qobuz://album/0090317058467"
        assert queue.raw == self._PAYLOAD

    def test_empty_queue(self):
        """A queue without entries has no tracks."""
        queue = Queue.from_raw({"queue": []})

        assert len(queue) == 0
        assert list(queue) == []

    def test_track_from_raw(self):
        """A queue track can also be parsed on its own."""
        track = QueueTrack.from_raw({"title": "A Song", "volumeNumber": 2})

        assert track.title == "A Song"
        assert track.volume_number == 2


class TestStory:
    """Test cases for the Story model."""

    def test_parses_a_successful_envelope(self):
        """The story text is parsed, and the whole envelope is kept in raw."""
        envelope = {"success": True, "data": {"type": "story", "value": "A story."}}

        story = Story.from_envelope(envelope)

        assert story.type == "story"
        assert story.value == "A story."
        assert story.raw == envelope

    def test_failed_envelope(self):
        """A failed query is reported as a story error."""
        with pytest.raises(VolumioStoryError, match="Metavolumio not available"):
            Story.from_envelope({"success": False, "error": "Metavolumio not available"})

    def test_envelope_without_the_success_flag(self):
        """An envelope without the success flag falls back to a generic error."""
        with pytest.raises(VolumioStoryError, match="unknown error"):
            Story.from_envelope({"data": {"value": "A story."}})

    def test_nested_failure(self):
        """A query the host could not resolve is reported as a story error."""
        with pytest.raises(VolumioStoryError, match="not found"):
            Story.from_envelope({"success": True, "data": {"success": False, "error": "not found"}})

    def test_nested_failure_without_the_error(self):
        """A nested failure without a message falls back to a generic error."""
        with pytest.raises(VolumioStoryError, match="unknown error"):
            Story.from_envelope({"success": True, "data": {"success": False}})

    def test_envelope_without_a_data_object(self):
        """An envelope whose data is not an object is reported as a story error."""
        with pytest.raises(VolumioStoryError, match="unknown error"):
            Story.from_envelope({"success": True, "data": "not an object"})

    def test_the_envelope_is_kept_as_raw(self):
        """A "raw" key inside the data does not shadow the response envelope."""
        envelope = {"success": True, "data": {"value": "A story.", "raw": "ignored"}}

        story = Story.from_envelope(envelope)

        assert story.value == "A story."
        assert story.raw == envelope


class TestSystemInfo:
    """Test cases for the SystemInfo and DeviceState models."""

    def test_parses_the_payload(self):
        """The system information is parsed, including its nested device state."""
        info = SystemInfo.from_raw(
            {
                "id": "5dc4ca49",
                "host": "http://192.168.1.122",
                "name": "volumio",
                "type": "device",
                "serviceName": "Volumio",
                "state": {
                    "status": "play",
                    "volume": 50,
                    "mute": False,
                    "artist": "Enrico Ruggeri",
                    "track": "Va tutto bene",
                    "albumart": "https://example.com/cover.jpg",
                },
                "systemversion": "4.119",
                "builddate": "Tue Mar 24 17:20:52 UTC 2026",
                "variant": "volumio",
                "hardware": "pi",
                "os": "12",
                "isPremiumDevice": False,
                "isVolumioProduct": False,
                "hwUuid": "1d16b25a",
            }
        )

        assert info.name == "volumio"
        assert info.service_name == "Volumio"
        assert info.system_version == "4.119"
        assert info.build_date == "Tue Mar 24 17:20:52 UTC 2026"
        assert info.is_premium_device is False
        assert info.is_volumio_product is False
        assert info.hw_uuid == "1d16b25a"
        assert isinstance(info.state, DeviceState)
        assert info.state.track == "Va tutto bene"
        assert info.state.volume == 50
        assert info.state.raw["albumart"] == "https://example.com/cover.jpg"

    def test_without_the_nested_state(self):
        """The nested state is optional."""
        info = SystemInfo.from_raw({"name": "volumio"})

        assert info.state is None


class TestSystemVersion:
    """Test cases for the SystemVersion model."""

    def test_parses_the_payload(self):
        """The system version is parsed, mapping its keys to aliases."""
        version = SystemVersion.from_raw(
            {
                "systemversion": "4.119",
                "builddate": "Tue Mar 24 17:20:52 UTC 2026",
                "variant": "volumio",
                "hardware": "pi",
                "os": "12",
            }
        )

        assert version.system_version == "4.119"
        assert version.build_date == "Tue Mar 24 17:20:52 UTC 2026"
        assert version.variant == "volumio"
        assert version.hardware == "pi"
        assert version.os == "12"


class TestZones:
    """Test cases for the Zones and Zone models."""

    _PAYLOAD = {
        "zones": [
            {
                "id": "5dc4ca49",
                "host": "http://192.168.1.122",
                "name": "volumio",
                "isSelf": True,
                "type": "device",
                "volumeAvailable": True,
                "state": {"status": "play", "volume": 50, "mute": False},
            },
            {"name": "Kitchen", "isSelf": False},
        ]
    }

    def test_parses_the_zones(self):
        """The zones are parsed, aliases and nested state included."""
        zones = Zones.from_raw(self._PAYLOAD)

        assert zones.zones[0].name == "volumio"
        assert zones.zones[0].is_self is True
        assert zones.zones[0].volume_available is True
        assert zones.zones[0].state is not None
        assert zones.zones[0].state.status == "play"
        assert zones.zones[1].state is None

    def test_is_a_sequence_of_its_zones(self):
        """The collection can be measured, indexed, and iterated."""
        zones = Zones.from_raw(self._PAYLOAD)

        assert len(zones) == 2
        assert zones[1].name == "Kitchen"
        assert [zone.name for zone in zones] == ["volumio", "Kitchen"]

    def test_zone_from_raw(self):
        """A zone can also be parsed on its own."""
        zone = Zone.from_raw({"name": "Kitchen", "isSelf": False})

        assert zone.name == "Kitchen"
        assert zone.is_self is False
