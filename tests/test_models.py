"""Tests for the Volumio response models.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

import json
from datetime import timedelta

import pytest

from volumito.clients.errors import VolumioAPIError, VolumioStoryError
from volumito.clients.models import (
    Alarms,
    AudioOutputs,
    Backgrounds,
    BrowseResults,
    BrowseSources,
    CollectionStatistics,
    CommandResponse,
    DeviceInfo,
    DeviceState,
    ExperienceSettings,
    InfinityPlayback,
    InputSources,
    Languages,
    MenuItems,
    Multiroom,
    MusicSources,
    NetworkInfo,
    Notification,
    Notifications,
    OutputDevices,
    PlayerState,
    Playlist,
    PlaylistContent,
    Playlists,
    Plugins,
    PowerModes,
    PrivacySettings,
    PushNotification,
    Queue,
    QueueTrack,
    SearchResultItem,
    SearchResultItemKind,
    SearchResultList,
    SearchResults,
    Shares,
    SleepTimer,
    Story,
    SuccessResponse,
    SystemInfo,
    SystemVersion,
    Timezones,
    UiConfig,
    UiSettings,
    UpdaterChannel,
    UsbDrives,
    WirelessNetworks,
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


class TestNotifications:
    """Test cases for the Notifications and Notification models."""

    _URLS = [
        "http://192.168.1.100/receiver",
        "http://192.168.1.101/other",
    ]

    def test_parses_the_urls(self):
        """Every listed URL becomes a notification, in the order reported."""
        notifications = Notifications.from_urls(self._URLS)

        assert notifications.urls == self._URLS
        assert notifications.notifications[0].url == "http://192.168.1.100/receiver"

    def test_keeps_the_listed_urls_as_raw(self):
        """The collection keeps the array, and each notification its own URL."""
        notifications = Notifications.from_urls(self._URLS)

        assert notifications.raw == self._URLS
        assert notifications[1].raw == "http://192.168.1.101/other"

    def test_is_a_sequence_of_its_notifications(self):
        """The collection can be measured, indexed, and iterated."""
        notifications = Notifications.from_urls(self._URLS)

        assert len(notifications) == 2
        assert notifications[1].url == "http://192.168.1.101/other"
        assert [notification.url for notification in notifications] == self._URLS

    def test_membership_by_url_and_by_notification(self):
        """Membership accepts either a URL or a notification."""
        notifications = Notifications.from_urls(self._URLS)

        assert "http://192.168.1.100/receiver" in notifications
        assert "http://192.168.1.102/none" not in notifications
        assert notifications[0] in notifications
        assert Notification.from_url("http://192.168.1.102/none") not in notifications

    def test_urls_skip_the_notifications_without_one(self):
        """A notification without a URL is not listed among the URLs."""
        notifications = Notifications.from_raw(
            {"notifications": [{"url": "http://192.168.1.100/receiver"}, {}]}
        )

        assert len(notifications) == 2
        assert notifications.urls == ["http://192.168.1.100/receiver"]

    def test_no_notifications(self):
        """An empty listing has no notifications."""
        notifications = Notifications.from_urls([])

        assert len(notifications) == 0
        assert notifications.urls == []
        assert notifications.raw == []

    def test_notification_from_url(self):
        """A notification built from a URL keeps it as its raw payload."""
        notification = Notification.from_url("http://192.168.1.100/receiver")

        assert notification.url == "http://192.168.1.100/receiver"
        assert notification.raw == "http://192.168.1.100/receiver"


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


class TestPushNotification:
    """Test cases for the PushNotification model."""

    def test_parses_a_state_notification(self):
        """A state notification carries the playback state as a mapping."""
        payload = {"item": "state", "data": {"status": "play", "title": "Caterina"}}

        notification = PushNotification.from_raw(payload)

        assert notification.item == "state"
        assert notification.data == {"status": "play", "title": "Caterina"}
        assert notification.raw == payload

    def test_parses_a_queue_notification(self):
        """A queue notification carries the queue as an array."""
        payload = {"item": "queue", "data": [{"title": "Caterina"}, {"title": "Titanic"}]}

        notification = PushNotification.from_raw(payload)

        assert notification.item == "queue"
        assert notification.data == payload["data"]

    def test_parses_a_zones_notification(self):
        """A zones notification carries the zones as an array."""
        payload = {"item": "zones", "data": [{"name": "volumio"}]}

        notification = PushNotification.from_raw(payload)

        assert notification.item == "zones"
        assert notification.data == payload["data"]

    def test_missing_values_default_to_none(self):
        """A payload reporting neither an item nor data parses to a bare notification."""
        notification = PushNotification.from_raw({})

        assert notification.item is None
        assert notification.data is None

    def test_an_unusable_item_is_ignored(self):
        """An item that is not a string is ignored, and stays in raw."""
        notification = PushNotification.from_raw({"item": 42, "data": {}})

        assert notification.item is None
        assert notification.raw == {"item": 42, "data": {}}


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

    def test_the_queue_numbers_its_tracks(self):
        """Every track knows its position in the queue, starting from zero."""
        queue = Queue.from_raw(self._PAYLOAD)

        assert [track.position for track in queue] == [0, 1]

    def test_the_position_is_not_part_of_the_payload(self):
        """The assigned position does not enter the raw payloads."""
        queue = Queue.from_raw(self._PAYLOAD)

        assert "position" not in queue.raw["queue"][0]
        assert "position" not in queue[0].raw

    def test_a_track_outside_a_queue_has_no_position(self):
        """A track parsed on its own does not know any position."""
        assert QueueTrack.from_raw({"title": "A Song"}).position is None

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


class TestSearchResults:
    """Test cases for the SearchResults, SearchResultList, and SearchResultItem models."""

    _ENVELOPE = {
        "navigation": {
            "isSearchResult": True,
            "lists": [
                {
                    "title": "Found 1 Artist 'paolo conte'",
                    "availableListViews": ["list", "grid"],
                    "items": [
                        {
                            "service": "mpd",
                            "type": "folder",
                            "title": "Paolo Conte",
                            "uri": "artists://Paolo%20Conte",
                        }
                    ],
                },
                {
                    "title": "Found 1 Album 'paolo conte'",
                    "items": [
                        {
                            "service": "mpd",
                            "type": "folder",
                            "title": "Paris Milonga",
                            "artist": "Paolo Conte",
                            "uri": "albums://Paolo%20Conte/Paris%20Milonga",
                        }
                    ],
                },
                {
                    "title": "Found 2 Tracks 'paolo conte'",
                    "items": [
                        {
                            "service": "mpd",
                            "type": "song",
                            "title": "1 - Aguaplano",
                            "artist": "Paolo Conte",
                            "album": "Aguaplano",
                            "uri": "music-library/INTERNAL/music/001___Aguaplano.flac",
                        },
                        {
                            "service": "mpd",
                            "type": "song",
                            "title": "2 - Come Di",
                            "artist": "Paolo Conte",
                            "album": "Aguaplano",
                            "uri": "music-library/INTERNAL/music/002___Come_Di.flac",
                        },
                    ],
                },
                {
                    "title": "Web Radio",
                    "icon": "fa icon",
                    "items": [
                        {
                            "service": "webradio",
                            "type": "webradio",
                            "title": "RADIO ATHENABEAT",
                            "artist": "",
                            "album": "",
                            "uri": "http://opml.radiotime.com/Tune.ashx?id=s339255",
                        }
                    ],
                },
                {
                    "title": "QOBUZ Artists",
                    "type": "",
                    "items": [
                        {
                            "service": "qobuz",
                            "type": "folder-with-favourites",
                            "title": "Paolo Conte",
                            "explicit": False,
                            "favourite": False,
                            "audioQuality": "",
                            "uri": "qobuz://artist/31776",
                        }
                    ],
                },
                {
                    "title": "QOBUZ Playlists",
                    "items": [
                        {
                            "service": "qobuz",
                            "type": "folder-with-favourites",
                            "title": "Paolo Conte Essentials",
                            "trackType": "qobuz",
                            "uri": "qobuz://playlist/13980206",
                        }
                    ],
                },
                {
                    "title": "QOBUZ Tracks",
                    "items": [
                        {
                            "service": "qobuz",
                            "type": "song",
                            "title": "Aguaplano",
                            "artist": "Paolo Conte",
                            "album": "Aguaplano",
                            "duration": 251,
                            "track_number": 1,
                            "trackType": "qobuz",
                            "uri": "qobuz://song/11665865",
                        }
                    ],
                },
            ],
        }
    }
    """A payload of the shape a Volumio host answers a search with."""

    def _results(self) -> SearchResults:
        return SearchResults.from_envelope(self._ENVELOPE)

    def test_parses_the_envelope(self):
        """The lists and their items are parsed, and the envelope is kept in raw."""
        results = self._results()

        assert results.is_search_result is True
        assert len(results) == 7
        assert results.raw == self._ENVELOPE
        assert [result_list.title for result_list in results][:2] == [
            "Found 1 Artist 'paolo conte'",
            "Found 1 Album 'paolo conte'",
        ]

    def test_an_envelope_without_a_navigation(self):
        """A payload that carries no navigation parses to empty results."""
        results = SearchResults.from_envelope({"unexpected": True})

        assert len(results) == 0
        assert results.raw == {"unexpected": True}

    def test_the_lists_are_sequences_of_their_items(self):
        """A list can be measured, indexed, and iterated."""
        tracks = self._results()[2]

        assert isinstance(tracks, SearchResultList)
        assert isinstance(tracks[0], SearchResultItem)
        assert len(tracks) == 2
        assert tracks[0].title == "1 - Aguaplano"
        assert [item.title for item in tracks] == ["1 - Aguaplano", "2 - Come Di"]

    def test_the_fields_of_an_item(self):
        """The camelCase keys of an item are read into their snake_case fields."""
        track = self._results()[6][0]

        assert track.service == "qobuz"
        assert track.artist == "Paolo Conte"
        assert track.duration == 251
        assert track.track_number == 1
        assert track.track_type == "qobuz"
        assert track.uri == "qobuz://song/11665865"

    def test_the_items_of_every_list(self):
        """The items property flattens the lists, in the order reported."""
        items = self._results().items

        assert len(items) == 8
        assert items[0].title == "Paolo Conte"
        assert items[-1].service == "qobuz"

    @pytest.mark.parametrize(
        ("index", "kind"),
        [
            (0, SearchResultItemKind.ARTIST),
            (1, SearchResultItemKind.ALBUM),
            (2, SearchResultItemKind.TRACK),
            (3, SearchResultItemKind.TRACK),
            (4, SearchResultItemKind.OTHER),
            (5, SearchResultItemKind.ARTIST),
            (6, SearchResultItemKind.PLAYLIST),
            (7, SearchResultItemKind.TRACK),
        ],
    )
    def test_the_kind_of_an_item(self, index, kind):
        """The kind of an item is read from its URI and its type."""
        assert self._results().items[index].kind is kind

    @pytest.mark.parametrize(
        ("payload", "kind"),
        [
            ({"type": "artist", "uri": "artists://Paolo Conte"}, SearchResultItemKind.ARTIST),
            ({"type": "album", "uri": ""}, SearchResultItemKind.ALBUM),
            ({"type": "playlist", "uri": ""}, SearchResultItemKind.PLAYLIST),
            (
                {"type": "folder", "uri": "artists://Paolo%20Conte"},
                SearchResultItemKind.ARTIST,
            ),
            (
                {"type": "folder", "uri": "artists://Paolo%20Conte/Aguaplano"},
                SearchResultItemKind.ALBUM,
            ),
        ],
    )
    def test_the_kind_of_a_browsed_item(self, payload, kind):
        """The explicit type wins, and an album inside an artist tree is told apart."""
        assert SearchResultItem.from_raw(payload).kind is kind

    def test_a_kind_is_its_own_string(self):
        """A kind is a member of the enumeration, and the string the member holds."""
        kind = self._results().items[0].kind

        assert isinstance(kind, SearchResultItemKind)
        assert kind == "artist"
        assert json.dumps({"kind": kind}) == '{"kind": "artist"}'

    def test_filtered_by_service(self):
        """The service filter keeps the results of that source only."""
        filtered = self._results().filtered(service="qobuz")

        assert [result_list.title for result_list in filtered] == [
            "QOBUZ Artists",
            "QOBUZ Playlists",
            "QOBUZ Tracks",
        ]

    def test_filtered_by_artist(self):
        """The artist filter keeps the artist entries too, whose field is empty."""
        filtered = self._results().filtered(artist="paolo conte")

        assert [item.kind for item in filtered.items] == [
            SearchResultItemKind.ARTIST,
            SearchResultItemKind.ALBUM,
            SearchResultItemKind.TRACK,
            SearchResultItemKind.TRACK,
            SearchResultItemKind.ARTIST,
            SearchResultItemKind.TRACK,
        ]

    def test_filtered_by_album(self):
        """The album filter matches the album field and the album entries."""
        filtered = self._results().filtered(album="aguaplano")

        assert [item.title for item in filtered.items] == [
            "1 - Aguaplano",
            "2 - Come Di",
            "Aguaplano",
        ]

    def test_filtered_by_track(self):
        """The track filter keeps the tracks with that title."""
        filtered = self._results().filtered(track="come di")

        assert [item.title for item in filtered.items] == ["2 - Come Di"]

    def test_filtered_by_playlist(self):
        """The playlist filter keeps the playlists with that title."""
        assert [item.title for item in self._results().filtered(playlist="essentials").items] == [
            "Paolo Conte Essentials"
        ]

    def test_filtered_by_any_playlist(self):
        """An empty playlist filter keeps every playlist."""
        filtered = self._results().filtered(playlist="")

        assert [item.kind for item in filtered.items] == [SearchResultItemKind.PLAYLIST]

    def test_filtered_by_kind(self):
        """The kinds filter keeps the results that are of one of them."""
        filtered = self._results().filtered(kinds={SearchResultItemKind.ARTIST})

        assert [item.title for item in filtered.items] == ["Paolo Conte", "Paolo Conte"]

    def test_filtered_by_several_kinds(self):
        """Every kind listed is kept."""
        filtered = self._results().filtered(
            kinds={SearchResultItemKind.ALBUM, SearchResultItemKind.PLAYLIST}
        )

        assert [item.kind for item in filtered.items] == [
            SearchResultItemKind.ALBUM,
            SearchResultItemKind.PLAYLIST,
        ]

    def test_filtered_by_kind_and_service(self):
        """The kinds filter combines with the other filters."""
        filtered = self._results().filtered(
            service="qobuz", kinds={SearchResultItemKind.ARTIST}
        )

        assert [result_list.title for result_list in filtered] == ["QOBUZ Artists"]
        assert filtered.raw == self._ENVELOPE

    def test_filtered_by_a_kind_without_a_match(self):
        """A kind no result is leaves no list."""
        assert len(self._results().filtered(kinds=set())) == 0

    def test_the_filters_combine(self):
        """Every filter given must match."""
        filtered = self._results().filtered(service="mpd", artist="conte", track="aguaplano")

        assert [item.title for item in filtered.items] == ["1 - Aguaplano"]

    def test_filtering_keeps_the_raw_payload(self):
        """The filtered results still carry the payload the host answered."""
        filtered = self._results().filtered(service="mpd")

        assert len(filtered) == 3
        assert filtered.raw == self._ENVELOPE

    def test_filtering_without_a_match(self):
        """Filters matching nothing leave no list."""
        assert len(self._results().filtered(artist="no such artist")) == 0

    def test_filtering_nothing(self):
        """Without a filter every list is kept."""
        assert len(self._results().filtered()) == 7

    def test_limited_to_the_first_items(self):
        """Each list keeps its first items, in the order the host reported them."""
        results = self._results()

        limited = results.limited(1)

        assert len(limited) == 7
        # The list of two tracks is the only one the limit shortens
        assert [len(result_list) for result_list in limited] == [1] * 7
        assert [item.title for item in limited.items][2] == "1 - Aguaplano"
        # The results the method was called on are left alone
        assert [len(result_list) for result_list in results] == [1, 1, 2, 1, 1, 1, 1]

    def test_limited_to_more_than_there_is(self):
        """A limit above the length of every list changes nothing."""
        limited = self._results().limited(10)

        assert [len(result_list) for result_list in limited] == [1, 1, 2, 1, 1, 1, 1]

    def test_limited_to_nothing(self):
        """A limit of zero, or less, leaves no list."""
        assert len(self._results().limited(0)) == 0
        assert len(self._results().limited(-1)) == 0

    def test_limiting_keeps_the_raw_payload(self):
        """The limited results still carry the payload the host answered."""
        limited = self._results().limited(1)

        assert limited.raw == self._ENVELOPE

    def test_limiting_what_is_filtered(self):
        """The two methods compose, the limit applying to what the filters left."""
        limited = self._results().filtered(service="mpd").limited(1)

        assert [item.title for item in limited.items] == [
            "Paolo Conte",
            "Paris Milonga",
            "1 - Aguaplano",
        ]

    def test_offset_skips_the_first_items(self):
        """Each list loses its first items, and the emptied lists are dropped."""
        results = self._results()

        skipped = results.offset(1)

        # Only the list of two tracks holds a second item
        assert [item.title for item in skipped.items] == ["2 - Come Di"]
        assert skipped.raw == self._ENVELOPE
        # The results the method was called on are left alone
        assert len(results.items) == 8

    def test_offset_by_nothing(self):
        """An offset of zero, or less, changes nothing."""
        assert len(self._results().offset(0)) == 7
        assert len(self._results().offset(-1)) == 7

    def test_offset_and_limit_open_a_window(self):
        """The two methods compose: skip, then keep."""
        window = self._results().offset(1).limited(1)

        assert [item.title for item in window.items] == ["2 - Come Di"]

    def test_the_count_and_filters_of_a_host_filtered_list(self):
        """The count and filters fields a host adds when offsetting are parsed."""
        result_list = SearchResultList.from_raw(
            {
                "title": "Tracks",
                "count": 19,
                "filters": {"offset": 2},
                "items": [{"title": "Third", "service": "mpd", "type": "song"}],
            }
        )

        assert result_list.count == 19
        assert result_list.filters == {"offset": 2}
        assert len(result_list) == 1


class TestBrowseResults:
    """Test cases for the BrowseResults model."""

    _ROOT_ENVELOPE = {
        "navigation": {
            "lists": [
                {
                    "name": "Music Library",
                    "uri": "music-library",
                    "plugin_type": "music_service",
                    "plugin_name": "mpd",
                    "albumart": "/albumart?sourceicon=music_library.svg",
                },
                {
                    "name": "QOBUZ",
                    "uri": "qobuz://",
                    "plugin_type": "music_service",
                    "plugin_name": "qobuz",
                },
            ],
        }
    }
    """A payload of the shape a Volumio host answers a root browse with: the items sit
    directly in the lists array, without list objects around them."""

    _ALBUM_ENVELOPE = {
        "navigation": {
            "lists": [
                {
                    "availableListViews": ["list"],
                    "items": [
                        {
                            "service": "mpd",
                            "type": "song",
                            "title": "Aguaplano",
                            "artist": "Paolo Conte",
                            "album": "Aguaplano",
                            "uri": "music-library/INTERNAL/music/001___Aguaplano.flac",
                        },
                        {
                            "service": "mpd",
                            "type": "folder",
                            "title": "A Folder",
                            "uri": "music-library/INTERNAL/music/folder",
                        },
                    ],
                }
            ],
            "prev": {"uri": "albums://Paolo%20Conte"},
            "info": {
                "uri": "albums://Paolo%20Conte/Aguaplano",
                "title": "Aguaplano",
                "artist": "Paolo Conte",
                "service": "mpd",
                "type": "album",
            },
        }
    }
    """A payload of the shape a Volumio host answers an album browse with."""

    def test_parses_a_root_envelope(self):
        """The loose items are gathered into one untitled list, and the envelope kept in raw."""
        results = BrowseResults.from_envelope(self._ROOT_ENVELOPE)

        assert len(results) == 1
        assert results[0].title is None
        assert [item.name for item in results.items] == ["Music Library", "QOBUZ"]
        assert results.items[0].plugin_name == "mpd"
        assert results.items[0].plugin_type == "music_service"
        assert results.info is None
        assert results.prev_uri is None
        assert results.raw == self._ROOT_ENVELOPE

    def test_a_mix_of_loose_items_and_lists(self):
        """The loose items come first as one list, and the real lists follow."""
        results = BrowseResults.from_envelope(
            {
                "navigation": {
                    "lists": [
                        {"title": "A List", "items": [{"title": "Listed"}]},
                        {"name": "Loose", "uri": "loose://"},
                    ],
                }
            }
        )

        assert [result_list.title for result_list in results] == [None, "A List"]
        assert [item.title or item.name for item in results.items] == ["Loose", "Listed"]

    def test_parses_an_album_envelope(self):
        """The entity being browsed and the step back up are parsed with the lists."""
        results = BrowseResults.from_envelope(self._ALBUM_ENVELOPE)

        assert results.info is not None
        assert results.info.title == "Aguaplano"
        assert results.info.artist == "Paolo Conte"
        assert results.info.kind == SearchResultItemKind.ALBUM
        assert results.prev_uri == "albums://Paolo%20Conte"
        assert [item.kind for item in results.items] == [
            SearchResultItemKind.TRACK,
            SearchResultItemKind.OTHER,
        ]

    def test_an_envelope_without_a_navigation(self):
        """A payload that carries no navigation parses to empty content."""
        results = BrowseResults.from_envelope({"unexpected": True})

        assert len(results) == 0
        assert results.raw == {"unexpected": True}

    def test_the_content_is_a_sequence_of_its_lists(self):
        """The content can be indexed, iterated, and measured."""
        results = BrowseResults.from_envelope(self._ALBUM_ENVELOPE)

        assert len(results) == 1
        assert results[0] is results.lists[0]
        assert [len(result_list) for result_list in results] == [2]

    def test_filtered_by_kind(self):
        """The kinds filter keeps the items of those kinds, dropping the emptied lists."""
        results = BrowseResults.from_envelope(self._ALBUM_ENVELOPE)

        filtered = results.filtered(kinds={SearchResultItemKind.TRACK})

        assert [item.title for item in filtered.items] == ["Aguaplano"]
        assert filtered.raw == self._ALBUM_ENVELOPE
        assert len(results.filtered(kinds={SearchResultItemKind.PLAYLIST})) == 0

    def test_limited(self):
        """The limit keeps the first items of each list and preserves the raw payload."""
        results = BrowseResults.from_envelope(self._ROOT_ENVELOPE)

        limited = results.limited(1)

        assert [item.name for item in limited.items] == ["Music Library"]
        assert limited.raw == self._ROOT_ENVELOPE
        assert len(results.limited(0)) == 0
        assert len(results.items) == 2

    def test_offset(self):
        """The offset skips the first items of each list and preserves the raw payload."""
        results = BrowseResults.from_envelope(self._ROOT_ENVELOPE)

        skipped = results.offset(1)

        assert [item.name for item in skipped.items] == ["QOBUZ"]
        assert skipped.raw == self._ROOT_ENVELOPE
        # An offset of zero, or less, changes nothing
        assert len(results.offset(0).items) == 2
        assert len(results.offset(-1).items) == 2
        # Skipping everything drops the emptied list
        assert len(results.offset(2)) == 0
        # The results the method was called on are left alone
        assert len(results.items) == 2

    def test_offset_and_limit_open_a_window(self):
        """The two methods compose: skip, then keep."""
        window = BrowseResults.from_envelope(self._ROOT_ENVELOPE).offset(1).limited(1)

        assert [item.name for item in window.items] == ["QOBUZ"]


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


class TestSuccessResponse:
    """Test cases for the SuccessResponse model."""

    def test_parses_a_successful_response(self):
        """The success flag is parsed, and the payload is kept in raw."""
        response = SuccessResponse.from_raw({"success": True})

        assert response.success is True
        assert response.error is None
        assert response.is_success
        assert response.raw == {"success": True}

    def test_a_failed_response(self):
        """A response denying the success is not a success."""
        response = SuccessResponse.from_raw({"success": False})

        assert response.success is False
        assert not response.is_success

    def test_a_reported_error_is_a_failure(self):
        """A response carrying an error is not a success, flag or no flag."""
        response = SuccessResponse.from_raw({"error": "No such URL is present"})

        assert response.error == "No such URL is present"
        assert response.success is None
        assert not response.is_success

    def test_a_response_reporting_nothing(self):
        """A response reporting neither a flag nor an error is read as a success."""
        response = SuccessResponse.from_raw({})

        assert response.success is None
        assert response.error is None
        assert response.is_success

    def test_an_unusable_flag_is_ignored(self):
        """A success flag that is not a boolean is ignored, and stays in raw."""
        response = SuccessResponse.from_raw({"success": "maybe"})

        assert response.success is None
        assert response.is_success
        assert response.raw == {"success": "maybe"}


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


class TestAlarms:
    """Test cases for the Alarms and Alarm models."""

    _PAYLOAD = {
        "alarms": [
            {"id": 1, "name": "Weekday", "enabled": True, "time": "07:30", "playlist": "jazz"},
            {"id": 2, "enabled": False},
        ]
    }

    def test_parses_the_alarms(self):
        """The alarms are parsed, and a missing field stays None."""
        alarms = Alarms.from_raw(self._PAYLOAD)

        assert alarms[0].id == 1
        assert alarms[0].name == "Weekday"
        assert alarms[0].time == "07:30"
        assert alarms[0].playlist == "jazz"
        assert alarms[1].enabled is False
        assert alarms[1].playlist is None

    def test_is_a_sequence_of_its_alarms(self):
        """The collection can be measured, indexed, and iterated."""
        alarms = Alarms.from_raw(self._PAYLOAD)

        assert len(alarms) == 2
        assert [alarm.id for alarm in alarms] == [1, 2]

    def test_a_host_with_no_alarm(self):
        """A host reporting no alarm is an empty collection."""
        assert len(Alarms.from_raw({"alarms": []})) == 0


class TestAudioOutputs:
    """Test cases for the AudioOutputs and AudioOutput models."""

    _PAYLOAD = {
        "availableOutputs": [
            {"id": "0", "name": "Living room", "type": "alsa", "enabled": True, "volume": 40}
        ]
    }

    def test_parses_the_outputs(self):
        """The outputs are parsed from the aliased key."""
        outputs = AudioOutputs.from_raw(self._PAYLOAD)

        assert len(outputs) == 1
        assert outputs[0].name == "Living room"
        assert outputs[0].volume == 40
        assert [output.id for output in outputs] == ["0"]

    def test_a_host_with_no_audio_output(self):
        """A host with no output plugin answers an empty collection."""
        assert len(AudioOutputs.from_raw({"availableOutputs": []})) == 0


class TestBrowseSources:
    """Test cases for the BrowseSources and BrowseSource models."""

    _PAYLOAD = {
        "sources": [
            {
                "albumart": "/albumart?sourceicon=x.png",
                "name": "Playlists",
                "uri": "playlists",
                "plugin_type": "music_service",
                "plugin_name": "mpd",
            }
        ]
    }

    def test_parses_the_sources(self):
        """The sources are parsed; the plugin keys are snake_case on the wire already."""
        sources = BrowseSources.from_raw(self._PAYLOAD)

        assert len(sources) == 1
        assert sources[0].name == "Playlists"
        assert sources[0].uri == "playlists"
        assert sources[0].plugin_type == "music_service"
        assert sources[0].plugin_name == "mpd"
        assert [source.uri for source in sources] == ["playlists"]


class TestDeviceInfo:
    """Test cases for the DeviceInfo model."""

    def test_parses_the_identity(self):
        """The name and the hardware identifier are parsed."""
        info = DeviceInfo.from_raw({"uuid": "5dc4ca49-7678", "name": "kitchen"})

        assert info.uuid == "5dc4ca49-7678"
        assert info.name == "kitchen"


class TestInputSources:
    """Test cases for the InputSources model."""

    def test_a_host_with_no_input_source(self):
        """A host with none answers an empty mapping, kept in raw."""
        sources = InputSources.from_raw({})

        assert sources.raw == {}

    def test_keeps_whatever_the_host_reported(self):
        """The payload stays readable through raw, whatever its keys."""
        sources = InputSources.from_raw({"spdif": {"enabled": True}})

        assert sources.raw == {"spdif": {"enabled": True}}


class TestMenuItems:
    """Test cases for the MenuItems and MenuItem models."""

    _PAYLOAD = {
        "items": [
            {"id": "my-volumio"},
            {
                "id": "mymusic",
                "name": "Sources",
                "state": "volumio.plugin",
                "params": {"pluginName": "miscellanea/my_music"},
            },
        ]
    }

    def test_parses_the_entries(self):
        """The entries are parsed, parameters included."""
        items = MenuItems.from_raw(self._PAYLOAD)

        assert len(items) == 2
        assert items[0].id == "my-volumio"
        assert items[0].name is None
        assert items[1].state == "volumio.plugin"
        assert items[1].params == {"pluginName": "miscellanea/my_music"}
        assert [item.id for item in items] == ["my-volumio", "mymusic"]


class TestMusicSources:
    """Test cases for the MusicSources and MusicSource models."""

    _PAYLOAD = {
        "plugins": [
            {
                "prettyName": "UPNP Renderer",
                "name": "upnp",
                "category": "audio_interface",
                "hasConfiguration": False,
                "active": False,
                "enabled": True,
            }
        ]
    }

    def test_parses_the_sources(self):
        """The sources are parsed, aliases included."""
        sources = MusicSources.from_raw(self._PAYLOAD)

        assert len(sources) == 1
        assert sources[0].pretty_name == "UPNP Renderer"
        assert sources[0].has_configuration is False
        assert sources[0].enabled is True
        assert [source.name for source in sources] == ["upnp"]


class TestOutputDevices:
    """Test cases for the OutputDevices and OutputDevice models."""

    _ENVELOPE = {
        "devices": {
            "active": {"name": "HDMI Out", "id": "0"},
            "available": [{"id": "0", "name": "HDMI Out"}, {"id": "1", "name": "Headphones"}],
        },
        "i2s": False,
    }

    def test_unwraps_the_devices_envelope(self):
        """The devices are read out of the envelope, beside the I2S flag."""
        devices = OutputDevices.from_envelope(self._ENVELOPE)

        assert devices.active is not None
        assert devices.active.name == "HDMI Out"
        assert devices.i2s is False
        assert len(devices) == 2
        assert devices[1].name == "Headphones"
        assert [device.name for device in devices] == ["HDMI Out", "Headphones"]
        assert devices.raw == self._ENVELOPE

    def test_an_envelope_without_devices(self):
        """An answer carrying no devices object is refused."""
        with pytest.raises(VolumioAPIError) as exc_info:
            OutputDevices.from_envelope({"i2s": True})

        assert "Expected a devices object" in str(exc_info.value)


class TestPlaylistContent:
    """Test cases for the PlaylistContent model."""

    _ENVELOPE = {
        "name": "qobuz fdg",
        "lists": [
            [
                {"title": "So What", "artist": "Miles Davis", "uri": "qobuz://1"},
                {"title": "Blue in Green", "uri": "qobuz://2"},
            ]
        ],
    }

    def test_flattens_the_lists(self):
        """The tracks are read out of the one list per source the host groups them in."""
        content = PlaylistContent.from_envelope(self._ENVELOPE)

        assert content.name == "qobuz fdg"
        assert len(content) == 2
        assert content[0].title == "So What"
        assert [track.uri for track in content] == ["qobuz://1", "qobuz://2"]
        assert content.raw == self._ENVELOPE

    def test_flattens_several_lists(self):
        """Tracks from every list end up in one sequence, in order."""
        content = PlaylistContent.from_envelope(
            {"name": "mixed", "lists": [[{"title": "a"}], [{"title": "b"}]]}
        )

        assert [track.title for track in content] == ["a", "b"]

    def test_accepts_a_flat_list(self):
        """A host answering the tracks unnested is read the same way."""
        content = PlaylistContent.from_envelope({"name": "flat", "lists": [{"title": "a"}]})

        assert [track.title for track in content] == ["a"]

    def test_an_empty_playlist(self):
        """A playlist with no track, or no lists at all, is empty."""
        assert len(PlaylistContent.from_envelope({"name": "empty", "lists": []})) == 0
        assert len(PlaylistContent.from_envelope({"name": "none"})) == 0


class TestPowerModes:
    """Test cases for the PowerModes model."""

    def test_parses_the_modes(self):
        """Both flags are parsed from their aliases."""
        modes = PowerModes.from_raw({"hasPowerOffMode": True, "hasStandbyMode": False})

        assert modes.has_power_off_mode is True
        assert modes.has_standby_mode is False


class TestSleepTimer:
    """Test cases for the SleepTimer model."""

    def test_parses_the_timer(self):
        """The timer is parsed, the action included."""
        timer = SleepTimer.from_raw(
            {"enabled": False, "time": "0:0", "action": {"val": "stop", "text": "Stop Music"}}
        )

        assert timer.enabled is False
        assert timer.time == "0:0"
        assert timer.action == {"val": "stop", "text": "Stop Music"}

    @pytest.mark.parametrize(
        ("time", "expected"),
        [
            ("0:0", timedelta(0)),
            ("0:30", timedelta(minutes=30)),
            ("1:30", timedelta(hours=1, minutes=30)),
            ("12:05", timedelta(hours=12, minutes=5)),
        ],
    )
    def test_the_delay_is_read_as_a_duration(self, time, expected):
        """The Volumio API reports a delay from now, not a clock time."""
        assert SleepTimer.from_raw({"enabled": True, "time": time}).delay == expected

    @pytest.mark.parametrize("time", [None, "", "nope", "1:2:3", "a:b"])
    def test_a_delay_that_cannot_be_read(self, time):
        """A missing or unreadable delay is None rather than an error."""
        payload = {"enabled": True} if time is None else {"enabled": True, "time": time}

        assert SleepTimer.from_raw(payload).delay is None


class TestUiSettings:
    """Test cases for the UiSettings model."""

    def test_parses_the_settings(self):
        """The interface settings are parsed."""
        settings = UiSettings.from_raw({"color": "#000", "language": "en", "theme": "default"})

        assert settings.color == "#000"
        assert settings.language == "en"
        assert settings.theme == "default"


class TestTierCModels:
    """The models of the administration surfaces, whose shapes came from a live host."""

    def test_network_info(self):
        """The interfaces are answered as a bare array, which the model wraps."""
        info = NetworkInfo.from_raw(
            {
                "interfaces": [
                    {"type": "Wired", "ip": "192.168.1.122", "status": "connected",
                     "speed": "1Gb/s"}
                ]
            }
        )

        assert len(info) == 1
        assert info[0].ip == "192.168.1.122"
        assert [i.type for i in info] == ["Wired"]

    def test_backgrounds(self):
        """The background in use is read beside the available ones."""
        backgrounds = Backgrounds.from_raw(
            {
                "current": {"name": "Darkness", "path": "darkness.jpg"},
                "available": [
                    {"name": "Aurora", "path": "aurora.jpg", "thumbnail": "thumb.jpg"}
                ],
            }
        )

        assert backgrounds.current is not None
        assert backgrounds.current.name == "Darkness"
        assert len(backgrounds) == 1
        assert backgrounds[0].thumbnail == "thumb.jpg"
        assert [b.name for b in backgrounds] == ["Aurora"]

    def test_timezones(self):
        """The time zones are answered as bare strings, which the model wraps."""
        zones = Timezones.from_raw({"timezones": ["Europe/Rome", "UTC"]})

        assert len(zones) == 2
        assert zones[0] == "Europe/Rome"
        assert list(zones) == ["Europe/Rome", "UTC"]

    def test_languages(self):
        """The language in use is read beside the available ones."""
        languages = Languages.from_raw(
            {
                "defaultLanguage": {"language": "English", "code": "en"},
                "available": [{"language": "Catala", "code": "ca"}],
            }
        )

        assert languages.default_language is not None
        assert languages.default_language.code == "en"
        assert len(languages) == 1
        assert languages[0].language == "Catala"
        assert [lang.code for lang in languages] == ["ca"]

    def test_updater_channel(self):
        """The channel in use is read beside the available ones."""
        channel = UpdaterChannel.from_raw(
            {"availableChannels": ["stable", "test"], "currentChannel": "stable"}
        )

        assert channel.current_channel == "stable"
        assert channel.available_channels == ["stable", "test"]

    def test_privacy_settings(self):
        """The statistics flag is read from its alias."""
        assert PrivacySettings.from_raw({"allowUIStatistics": False}).allow_ui_statistics is False

    def test_infinity_playback(self):
        """Both flags are parsed."""
        playback = InfinityPlayback.from_raw({"available": True, "enabled": False})

        assert playback.available is True
        assert playback.enabled is False

    def test_experience_settings(self):
        """The setting in use is reported as the whole option, label included."""
        settings = ExperienceSettings.from_raw(
            {
                "options": [
                    {"id": False, "label": "Simplified"},
                    {"id": True, "label": "Full"},
                ],
                "status": {"id": True, "label": "Full"},
            }
        )

        assert settings.status is not None
        assert settings.status.label == "Full"
        assert settings.advanced is True
        assert settings.options[0].label == "Simplified"

    def test_experience_settings_without_a_status(self):
        """A host reporting no setting in use reads as None rather than failing."""
        assert ExperienceSettings.from_raw({"options": []}).advanced is None

    def test_ui_config(self):
        """The page and its sections are parsed."""
        config = UiConfig.from_raw(
            {"page": {"label": "System Settings"}, "sections": [{"id": "language_selector"}]}
        )

        assert config.page == {"label": "System Settings"}
        assert config.sections[0]["id"] == "language_selector"

    def test_plugins(self):
        """The plugins are parsed, aliases included."""
        plugins = Plugins.from_raw(
            {
                "plugins": [
                    {"name": "spop", "prettyName": "Spotify", "category": "music_service",
                     "version": "1.0", "enabled": True, "active": True}
                ]
            }
        )

        assert len(plugins) == 1
        assert plugins[0].pretty_name == "Spotify"
        assert [p.name for p in plugins] == ["spop"]

    def test_shares(self):
        """The shares are parsed with the fields the networkfs plugin reports."""
        shares = Shares.from_raw(
            {
                "shares": [
                    {"id": "uuid", "name": "NAS", "path": "Music", "fstype": "cifs",
                     "username": "guest", "options": "ro", "size": ""}
                ]
            }
        )

        assert len(shares) == 1
        assert shares[0].fstype == "cifs"
        assert [s.name for s in shares] == ["NAS"]

    def test_wireless_networks(self):
        """The networks are parsed."""
        networks = WirelessNetworks.from_raw(
            {"available": [{"ssid": "home", "signal": 70, "security": "wpa", "configured": True}]}
        )

        assert len(networks) == 1
        assert networks[0].signal == 70
        assert [n.ssid for n in networks] == ["home"]

    def test_usb_drives(self):
        """The drives are parsed."""
        drives = UsbDrives.from_raw(
            {"drives": [{"name": "USB", "device": "sda1", "mountpoint": "/media/USB"}]}
        )

        assert len(drives) == 1
        assert drives[0].mountpoint == "/media/USB"
        assert [d.name for d in drives] == ["USB"]

    def test_multiroom(self):
        """The multiroom configuration keeps whatever the plugin reported."""
        multiroom = Multiroom.from_raw({"enabled": True, "mode": "server", "extra": 1})

        assert multiroom.enabled is True
        assert multiroom.mode == "server"
        assert multiroom.raw["extra"] == 1

    def test_the_empty_collections(self):
        """Every Tier C collection reads an empty answer as empty."""
        assert len(NetworkInfo.from_raw({"interfaces": []})) == 0
        assert len(Plugins.from_raw({"plugins": []})) == 0
        assert len(Shares.from_raw({"shares": []})) == 0
        assert len(Timezones.from_raw({"timezones": []})) == 0
        assert len(UsbDrives.from_raw({"drives": []})) == 0
        assert len(WirelessNetworks.from_raw({"available": []})) == 0
        assert len(Backgrounds.from_raw({"available": []})) == 0
        assert len(Languages.from_raw({"available": []})) == 0
