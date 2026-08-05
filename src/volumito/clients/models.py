"""Response models for the Volumio clients.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

from collections.abc import Iterator
from typing import Any, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from volumito.clients.errors import VolumioAPIError, VolumioStoryError

_VALUE_ADAPTERS: dict[type["VolumioModel"], dict[str, TypeAdapter[Any]]] = {}
"""Cache of the per-model type adapters validating the incoming values."""


def _value_adapters(model: type["VolumioModel"]) -> dict[str, TypeAdapter[Any]]:
    """Return the type adapters of a model, keyed by field name and by alias.

    Args:
        model: The model class to build (or read the cached) adapters for

    Returns:
        The type adapter of each field, keyed by both its name and its alias
    """
    adapters = _VALUE_ADAPTERS.get(model)
    if adapters is None:
        adapters = {}
        for name, field in model.model_fields.items():
            adapter: TypeAdapter[Any] = TypeAdapter(field.annotation)
            adapters[name] = adapter
            if field.alias is not None:
                adapters[field.alias] = adapter
        _VALUE_ADAPTERS[model] = adapters
    return adapters


class VolumioModel(BaseModel):
    """Base class of the response models: a typed view over a raw JSON payload.

    The fields documented by the Volumio API are exposed as typed attributes, while
    the payload the model was parsed from remains available in :attr:`raw`. A value
    whose type does not match its field is ignored, leaving the attribute at its
    ``None`` default, so that one unexpected value cannot make a whole response
    unreadable: that value is still readable in :attr:`raw`, together with any key
    the model does not describe.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    raw: Any = Field(default=None, exclude=True, repr=False)
    """The raw JSON payload this model was parsed from, whatever its shape."""

    @model_validator(mode="before")
    @classmethod
    def _accept_valid_values(cls, data: object) -> object:
        """Keep the values matching their field, and capture the raw payload.

        Args:
            data: The value being validated (a raw payload, when it is a mapping)

        Returns:
            The payload with the unusable values dropped and ``raw`` populated
        """
        if not isinstance(data, dict):
            return data
        adapters = _value_adapters(cls)
        accepted: dict[str, Any] = {}
        for key, value in data.items():
            adapter = adapters.get(key)
            if adapter is None:
                # A key the model does not describe: available in raw only
                continue
            try:
                adapter.validate_python(value)
            except ValidationError:
                # A value the field cannot hold: available in raw only
                continue
            accepted[key] = value
        accepted.setdefault("raw", data)
        return accepted

    @classmethod
    def from_raw(cls, payload: dict[str, Any]) -> Self:
        """Parse a raw JSON payload into the model.

        Args:
            payload: The raw JSON payload returned by the Volumio API

        Returns:
            The model, holding the payload in its ``raw`` attribute

        Raises:
            VolumioAPIError: If the payload cannot be parsed into the model
        """
        try:
            return cls.model_validate(payload)
        except ValidationError as e:
            raise VolumioAPIError(f"Unexpected response from the Volumio API: {e}") from e


class CollectionStatistics(VolumioModel):
    """The statistics of the music collection of a Volumio instance."""

    albums: int | None = None
    """The number of albums in the collection."""

    artists: int | None = None
    """The number of artists in the collection."""

    playtime: str | None = None
    """The total playing time of the collection, as ``H:MM:SS``."""

    songs: int | None = None
    """The number of songs in the collection."""


class CommandResponse(VolumioModel):
    """The response of a Volumio playback or queue command."""

    response: str | None = None
    """The outcome reported by the Volumio API (e.g., ``"play Success"``)."""

    time: int | None = None
    """The time the command was served, as a Unix timestamp in milliseconds."""


class DeviceState(VolumioModel):
    """The reduced playback state a Volumio instance reports for a device.

    This is the shape nested in the system information and in the multiroom zones;
    see :class:`PlayerState` for the full playback state.
    """

    albumart: str | None = None
    """The album art URI, absolute or relative to the host."""

    artist: str | None = None
    """The artist of the track playing."""

    mute: bool | None = None
    """Whether the volume is muted."""

    status: str | None = None
    """The playback status (``"play"``, ``"pause"``, or ``"stop"``)."""

    track: str | None = None
    """The title of the track playing."""

    volume: int | None = None
    """The volume level, between 0 and 100."""


class Notification(VolumioModel):
    """A URL registered on a Volumio instance to receive push notifications."""

    url: str | None = None
    """The URL the Volumio instance pushes its notifications to."""

    @classmethod
    def from_url(cls, url: str) -> Self:
        """Build the notification listed by the Volumio instance under a URL.

        Args:
            url: The URL, as listed by the Volumio instance

        Returns:
            The notification, holding the URL it was listed as in its ``raw`` attribute
        """
        return cls.model_validate({"url": url, "raw": url})


class Notifications(VolumioModel):
    """The URLs registered on a Volumio instance to receive push notifications.

    The collection is a sequence of its notifications: it can be iterated, indexed, and
    measured with ``len()``; testing for membership accepts either a notification or the
    URL of one (``"http://192.168.1.100/receiver" in notifications``).
    """

    notifications: list[Notification] = Field(default_factory=list)
    """The registered notifications, in the order reported by the Volumio instance."""

    @classmethod
    def from_urls(cls, urls: list[str]) -> Self:
        """Build the collection from the URLs listed by the Volumio instance.

        Args:
            urls: The registered URLs

        Returns:
            The collection, holding the listed URLs in its ``raw`` attribute
        """
        notifications = [{"url": url, "raw": url} for url in urls]
        return cls.model_validate({"notifications": notifications, "raw": urls})

    @property
    def urls(self) -> list[str]:
        """The registered URLs, in the order reported."""
        return [
            notification.url
            for notification in self.notifications
            if notification.url is not None
        ]

    def __contains__(self, item: object) -> bool:
        """Return whether a notification, or one with the given URL, is registered."""
        if isinstance(item, str):
            return item in self.urls
        return item in self.notifications

    def __getitem__(self, index: int) -> Notification:
        """Return the notification at the given position."""
        return self.notifications[index]

    def __iter__(self) -> Iterator[Notification]:  # type: ignore[override]
        """Iterate over the registered notifications."""
        return iter(self.notifications)

    def __len__(self) -> int:
        """Return the number of registered notifications."""
        return len(self.notifications)


class PlayerState(VolumioModel):
    """The playback state of a Volumio instance."""

    album: str | None = None
    """The album of the track playing."""

    albumart: str | None = None
    """The album art URI, absolute or relative to the host."""

    albumartist: str | None = None
    """The album artist of the track playing, when the host reports one."""

    artist: str | None = None
    """The artist of the track playing."""

    bitdepth: str | None = None
    """The bit depth of the track playing (e.g., ``"16 bit"``)."""

    bitrate: str | None = None
    """The bit rate of the track playing (e.g., ``"1347 Kbps"``)."""

    channels: int | None = None
    """The number of audio channels of the track playing."""

    consume: bool | None = None
    """Whether the consume mode is enabled."""

    db_volume: float | None = Field(default=None, alias="dbVolume")
    """The volume level in decibels, when the host reports one."""

    disable_volume_control: bool | None = Field(default=None, alias="disableVolumeControl")
    """Whether the volume control is disabled."""

    duration: int | None = None
    """The duration of the track playing, in seconds."""

    mute: bool | None = None
    """Whether the volume is muted."""

    position: int | None = None
    """The position of the track playing in the queue, starting from zero."""

    random: bool | None = None
    """Whether the random (shuffle) mode is enabled."""

    repeat: bool | None = None
    """Whether the repeat mode is enabled."""

    repeat_single: bool | None = Field(default=None, alias="repeatSingle")
    """Whether the repeat mode repeats the current track only."""

    samplerate: str | None = None
    """The sample rate of the track playing (e.g., ``"44.1 kHz"``)."""

    seek: int | None = None
    """The seek position in the track playing, in milliseconds."""

    service: str | None = None
    """The service playing the track (e.g., ``"mpd"`` or ``"qobuz"``)."""

    status: str | None = None
    """The playback status (``"play"``, ``"pause"``, or ``"stop"``)."""

    stream: bool | str | None = None
    """Whether the track playing is a stream, or the kind of stream it is."""

    title: str | None = None
    """The title of the track playing."""

    track_type: str | None = Field(default=None, alias="trackType")
    """The type of the track playing (e.g., ``"qobuz"``)."""

    tracknumber: int | None = None
    """The number of the track within its album, when the host reports it."""

    updatedb: bool | None = None
    """Whether the music collection database is being updated."""

    uri: str | None = None
    """The URI of the track playing."""

    volatile: bool | None = None
    """Whether the playback is volatile (controlled by another service)."""

    volume: int | None = None
    """The volume level, between 0 and 100."""

    @property
    def is_paused(self) -> bool:
        """Whether the playback is paused (the status is ``"pause"``)."""
        return self.status == "pause"

    @property
    def is_playing(self) -> bool:
        """Whether the playback is playing (the status is ``"play"``)."""
        return self.status == "play"

    @property
    def is_stopped(self) -> bool:
        """Whether the playback is stopped (the status is ``"stop"``)."""
        return self.status == "stop"


class Playlist(VolumioModel):
    """A playlist saved on a Volumio instance."""

    name: str | None = None
    """The name of the playlist."""

    @classmethod
    def from_name(cls, name: str) -> Self:
        """Build the playlist listed by the Volumio instance under a name.

        Args:
            name: The name of the playlist, as listed by the Volumio instance

        Returns:
            The playlist, holding the name it was listed as in its ``raw`` attribute
        """
        return cls.model_validate({"name": name, "raw": name})


class Playlists(VolumioModel):
    """The playlists saved on a Volumio instance.

    The collection is a sequence of its playlists: it can be iterated, indexed, and
    measured with ``len()``; testing for membership accepts either a playlist or the
    name of one (``"Jazz Classics" in playlists``).
    """

    playlists: list[Playlist] = Field(default_factory=list)
    """The saved playlists, in the order reported by the Volumio instance."""

    @classmethod
    def from_names(cls, names: list[str]) -> Self:
        """Build the collection from the names listed by the Volumio instance.

        Args:
            names: The names of the saved playlists

        Returns:
            The collection, holding the listed names in its ``raw`` attribute
        """
        playlists = [{"name": name, "raw": name} for name in names]
        return cls.model_validate({"playlists": playlists, "raw": names})

    @property
    def names(self) -> list[str]:
        """The names of the saved playlists, in the order reported."""
        return [playlist.name for playlist in self.playlists if playlist.name is not None]

    def __contains__(self, item: object) -> bool:
        """Return whether a playlist, or a playlist with the given name, is saved."""
        if isinstance(item, str):
            return item in self.names
        return item in self.playlists

    def __getitem__(self, index: int) -> Playlist:
        """Return the playlist at the given position."""
        return self.playlists[index]

    def __iter__(self) -> Iterator[Playlist]:  # type: ignore[override]
        """Iterate over the saved playlists."""
        return iter(self.playlists)

    def __len__(self) -> int:
        """Return the number of saved playlists."""
        return len(self.playlists)


class PushNotification(VolumioModel):
    """A notification a Volumio instance pushes to a registered URL."""

    data: Any = None
    """The updated information: a mapping for a state, an array for a queue or the zones."""

    item: str | None = None
    """The kind of event (``"state"``, ``"queue"``, or ``"zones"``)."""


class QueueTrack(VolumioModel):
    """A track of the playback queue of a Volumio instance."""

    album: str | None = None
    """The album of the track."""

    album_uri: str | None = Field(default=None, alias="albumUri")
    """The URI of the album of the track."""

    albumart: str | None = None
    """The album art URI, absolute or relative to the host."""

    artist: str | None = None
    """The artist of the track."""

    artist_uri: str | None = Field(default=None, alias="artistUri")
    """The URI of the artist of the track."""

    audio_quality: str | None = Field(default=None, alias="audioQuality")
    """The audio quality reported for the track."""

    bitdepth: str | None = None
    """The bit depth of the track (e.g., ``"16 bit"``)."""

    duration: int | None = None
    """The duration of the track, in seconds."""

    explicit: bool | None = None
    """Whether the track is marked as explicit."""

    name: str | None = None
    """The name of the track (usually the same as its title)."""

    position: int | None = None
    """The position of the track in the queue, starting from zero.

    Assigned by the :class:`Queue` the track belongs to (the Volumio API reports the
    queue as an array, without positions), and None for a track parsed on its own.
    """

    samplerate: str | None = None
    """The sample rate of the track (e.g., ``"44 KHz"``)."""

    service: str | None = None
    """The service providing the track (e.g., ``"mpd"`` or ``"qobuz"``)."""

    tag_image: str | None = Field(default=None, alias="tagImage")
    """The URI of the tag image of the track."""

    title: str | None = None
    """The title of the track."""

    track_type: str | None = Field(default=None, alias="trackType")
    """The type of the track (e.g., ``"qobuz"``)."""

    tracknumber: int | None = None
    """The number of the track within its album."""

    type: str | None = None
    """The type of the queue entry (e.g., ``"track"``)."""

    uri: str | None = None
    """The URI of the track."""

    volume_number: int | None = Field(default=None, alias="volumeNumber")
    """The number of the volume (disc) of the album the track belongs to."""


class Queue(VolumioModel):
    """The playback queue of a Volumio instance.

    The queue is a sequence of its tracks: it can be iterated, indexed, and measured
    with ``len()``. Each track is given its ``position`` in the queue, so it can be
    played directly (see the ``play`` method of the REST API client).
    """

    tracks: list[QueueTrack] = Field(default_factory=list, alias="queue")
    """The tracks of the queue, in queue order."""

    @model_validator(mode="after")
    def _assign_positions(self) -> Self:
        """Give each track its position in the queue.

        Returns:
            The queue, with the position of every track assigned
        """
        for position, track in enumerate(self.tracks):
            track.position = position
        return self

    def __getitem__(self, index: int) -> QueueTrack:
        """Return the track at the given position of the queue."""
        return self.tracks[index]

    def __iter__(self) -> Iterator[QueueTrack]:  # type: ignore[override]
        """Iterate over the tracks of the queue."""
        return iter(self.tracks)

    def __len__(self) -> int:
        """Return the number of tracks in the queue."""
        return len(self.tracks)


class Story(VolumioModel):
    """A story (or the credits) of an album, artist, label, or place.

    Requires the Volumio host to be running with a Premium (or better) subscription.
    The :attr:`raw` attribute holds the whole response envelope.
    """

    type: str | None = None
    """The type of the text (e.g., ``"story"``)."""

    value: str | None = None
    """The text of the story or of the credits."""

    @classmethod
    def from_envelope(cls, envelope: dict[str, Any]) -> Self:
        """Parse the response envelope of a metavolumio query.

        Args:
            envelope: The response envelope (``{"success": ..., "data": ...}``)

        Returns:
            The story, holding the whole envelope in its ``raw`` attribute

        Raises:
            VolumioStoryError: If the Volumio host reports a failed query
            VolumioAPIError: If the envelope cannot be parsed into the model
        """
        if envelope.get("success") is not True:
            raise VolumioStoryError(str(envelope.get("error", "unknown error")))
        data = envelope.get("data")
        if not isinstance(data, dict):
            raise VolumioStoryError("unknown error")
        if data.get("success") is False:
            raise VolumioStoryError(str(data.get("error", "unknown error")))
        # The story text comes from the data, while raw keeps the whole envelope
        return cls.from_raw({**data, "raw": envelope})


class SearchResultItem(VolumioModel):
    """One result of a search on a Volumio instance."""

    album: str | None = None
    """The album of the result, when it has one."""

    albumart: str | None = None
    """The album art URI, absolute or relative to the host."""

    artist: str | None = None
    """The artist of the result, when it has one."""

    audio_quality: str | None = Field(default=None, alias="audioQuality")
    """The audio quality reported by the source (e.g., ``"hires"``)."""

    duration: int | None = None
    """The duration of the result, in seconds, when it is a track."""

    explicit: bool | None = None
    """Whether the source marks the result as explicit."""

    favourite: bool | None = None
    """Whether the result is among the favourites of the source."""

    icon: str | None = None
    """The icon of the result, when the source gives one."""

    service: str | None = None
    """The source the result comes from (e.g., ``"mpd"``, ``"webradio"``, ``"qobuz"``)."""

    title: str | None = None
    """The title of the result: the name of the artist, album, playlist, or track."""

    track_number: int | None = None
    """The number of the track within its album, when the source gives one."""

    track_type: str | None = Field(default=None, alias="trackType")
    """The type of the track (e.g., ``"flac"``, ``"qobuz"``)."""

    type: str | None = None
    """The type reported by the host (e.g., ``"folder"``, ``"song"``, ``"webradio"``)."""

    uri: str | None = None
    """The URI the result can be played or browsed from."""

    @property
    def kind(self) -> str:
        """The kind of entity the result is, read from its URI and its type.

        A Volumio host names its entities by URI (``artists://…`` and ``qobuz://artist/…``
        for the artists, and likewise for the albums and the playlists), and reports the
        tracks with the ``song`` type, whatever the source.

        Returns:
            One of ``"artist"``, ``"album"``, ``"playlist"``, ``"song"``, and ``"other"``
        """
        if self.type == "song":
            return "song"
        uri = self.uri or ""
        for kind in ("artist", "album", "playlist"):
            if uri.startswith(f"{kind}s://") or f"://{kind}/" in uri:
                return kind
        return "other"


class SearchResultList(VolumioModel):
    """A titled list of search results, as a Volumio instance groups them.

    The list is a sequence of its items: it can be iterated, indexed, and measured
    with ``len()``.
    """

    available_list_views: list[str] | None = Field(default=None, alias="availableListViews")
    """The views the host suggests for the list (e.g., ``["list", "grid"]``)."""

    icon: str | None = None
    """The icon of the list, when the host gives one."""

    items: list[SearchResultItem] = Field(default_factory=list)
    """The results of the list, in the order reported by the Volumio instance."""

    title: str | None = None
    """The title of the list (e.g., ``"QOBUZ Albums"``)."""

    type: str | None = None
    """The type of the list, when the host gives one."""

    def __getitem__(self, index: int) -> SearchResultItem:
        """Return the result at the given position."""
        return self.items[index]

    def __iter__(self) -> Iterator[SearchResultItem]:  # type: ignore[override]
        """Iterate over the results of the list."""
        return iter(self.items)

    def __len__(self) -> int:
        """Return the number of results in the list."""
        return len(self.items)


class SearchResults(VolumioModel):
    """The results of a search on a Volumio instance.

    The results are a sequence of the lists the host grouped them in: the collection can
    be iterated, indexed, and measured with ``len()``. The :attr:`raw` attribute holds
    the whole response envelope, as the host returned it.
    """

    is_search_result: bool | None = Field(default=None, alias="isSearchResult")
    """Whether the host reports the payload as the result of a search."""

    lists: list[SearchResultList] = Field(default_factory=list)
    """The lists of results, in the order reported by the Volumio instance."""

    @classmethod
    def from_envelope(cls, envelope: dict[str, Any]) -> Self:
        """Parse the response envelope of a search query.

        Args:
            envelope: The response envelope (``{"navigation": {...}}``)

        Returns:
            The results, holding the whole envelope in their ``raw`` attribute

        Raises:
            VolumioAPIError: If the envelope cannot be parsed into the model
        """
        navigation = envelope.get("navigation")
        if not isinstance(navigation, dict):
            navigation = {}
        # The results come from the navigation, while raw keeps the whole envelope
        return cls.from_raw({**navigation, "raw": envelope})

    @property
    def items(self) -> list[SearchResultItem]:
        """Every result of every list, in the order reported."""
        return [item for result_list in self.lists for item in result_list.items]

    def __getitem__(self, index: int) -> SearchResultList:
        """Return the list of results at the given position."""
        return self.lists[index]

    def __iter__(self) -> Iterator[SearchResultList]:  # type: ignore[override]
        """Iterate over the lists of results."""
        return iter(self.lists)

    def __len__(self) -> int:
        """Return the number of lists of results."""
        return len(self.lists)

    def filtered(
        self,
        service: str | None = None,
        artist: str | None = None,
        album: str | None = None,
        song: str | None = None,
        playlist: str | None = None,
    ) -> "SearchResults":
        """Return the results whose items match every filter given.

        A filter is ignored when it is None. The service is matched by equality, while
        the other filters are matched as case-insensitive substrings, against the field
        of the item (``artist``, ``album``) and against the title of the entity itself
        (an artist, an album, a playlist, or a song), which is where a Volumio host
        carries the name of an entity. An empty string matches every entity of its kind.
        The lists left without items are dropped, and the raw payload is preserved.

        Args:
            service: The source the results must come from
            artist: The text an artist of a result, or an artist result, must contain
            album: The text an album of a result, or an album result, must contain
            song: The text a song result must contain
            playlist: The text a playlist result must contain

        Returns:
            The filtered results, holding the original payload in their ``raw`` attribute
        """

        def matches(item: SearchResultItem) -> bool:
            if service is not None and (item.service or "").lower() != service.lower():
                return False
            for text, field, kind in (
                (artist, item.artist, "artist"),
                (album, item.album, "album"),
                (song, None, "song"),
                (playlist, None, "playlist"),
            ):
                if text is None:
                    continue
                wanted = text.lower()
                in_field = wanted in (field or "").lower() if field else False
                in_title = item.kind == kind and wanted in (item.title or "").lower()
                if not (in_field or in_title):
                    return False
            return True

        filtered_lists = []
        for result_list in self.lists:
            items = [item for item in result_list.items if matches(item)]
            if items:
                filtered_lists.append(result_list.model_copy(update={"items": items}))

        return self.model_copy(update={"lists": filtered_lists})


class SuccessResponse(VolumioModel):
    """The outcome a Volumio instance reports as a success flag."""

    error: str | None = None
    """The reason the Volumio instance gives for not carrying the request out."""

    success: bool | None = None
    """Whether the Volumio instance carried the request out."""

    @property
    def is_success(self) -> bool:
        """Whether the request was carried out, as far as the instance reports.

        A Volumio instance can answer a request it refuses with an HTTP 200 carrying
        an error, so a reported error means failure even without a success flag; an
        answer reporting neither is read as a success.
        """
        return self.success is not False and self.error is None


class SystemInfo(VolumioModel):
    """The system information of a Volumio instance."""

    build_date: str | None = Field(default=None, alias="builddate")
    """The build date of the Volumio system."""

    hardware: str | None = None
    """The hardware the Volumio system runs on (e.g., ``"pi"``)."""

    host: str | None = None
    """The base URL of the Volumio instance."""

    hw_uuid: str | None = Field(default=None, alias="hwUuid")
    """The hardware UUID of the Volumio instance."""

    id: str | None = None
    """The identifier of the Volumio instance."""

    is_premium_device: bool | None = Field(default=None, alias="isPremiumDevice")
    """Whether the Volumio instance runs with a Premium (or better) subscription."""

    is_volumio_product: bool | None = Field(default=None, alias="isVolumioProduct")
    """Whether the Volumio instance runs on a Volumio-branded product."""

    name: str | None = None
    """The name of the Volumio instance."""

    os: str | None = None
    """The version of the operating system of the Volumio instance."""

    service_name: str | None = Field(default=None, alias="serviceName")
    """The name of the service (e.g., ``"Volumio"``)."""

    state: DeviceState | None = None
    """The reduced playback state of the Volumio instance."""

    system_version: str | None = Field(default=None, alias="systemversion")
    """The version of the Volumio system."""

    type: str | None = None
    """The type of the Volumio instance (e.g., ``"device"``)."""

    variant: str | None = None
    """The variant of the Volumio system (e.g., ``"volumio"``)."""


class SystemVersion(VolumioModel):
    """The system version of a Volumio instance."""

    build_date: str | None = Field(default=None, alias="builddate")
    """The build date of the Volumio system."""

    hardware: str | None = None
    """The hardware the Volumio system runs on (e.g., ``"pi"``)."""

    os: str | None = None
    """The version of the operating system of the Volumio instance."""

    system_version: str | None = Field(default=None, alias="systemversion")
    """The version of the Volumio system."""

    variant: str | None = None
    """The variant of the Volumio system (e.g., ``"volumio"``)."""


class Zone(VolumioModel):
    """A multiroom zone seen by a Volumio instance."""

    host: str | None = None
    """The base URL of the zone."""

    id: str | None = None
    """The identifier of the zone."""

    is_self: bool | None = Field(default=None, alias="isSelf")
    """Whether the zone is the Volumio instance being queried."""

    name: str | None = None
    """The name of the zone."""

    state: DeviceState | None = None
    """The reduced playback state of the zone."""

    type: str | None = None
    """The type of the zone (e.g., ``"device"``)."""

    volume_available: bool | None = Field(default=None, alias="volumeAvailable")
    """Whether the volume of the zone can be controlled."""


class Zones(VolumioModel):
    """The multiroom zones seen by a Volumio instance.

    The collection is a sequence of its zones: it can be iterated, indexed, and
    measured with ``len()``.
    """

    zones: list[Zone] = Field(default_factory=list)
    """The multiroom zones, in the order reported by the Volumio instance."""

    def __getitem__(self, index: int) -> Zone:
        """Return the zone at the given position."""
        return self.zones[index]

    def __iter__(self) -> Iterator[Zone]:  # type: ignore[override]
        """Iterate over the zones."""
        return iter(self.zones)

    def __len__(self) -> int:
        """Return the number of zones."""
        return len(self.zones)
