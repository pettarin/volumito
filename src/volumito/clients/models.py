"""Response models for the Volumio clients.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

from collections.abc import Callable, Collection, Iterator
from datetime import timedelta
from enum import StrEnum
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


def _lists_with_first_items(
    lists: list["SearchResultList"], count: int
) -> list["SearchResultList"]:
    """Return copies of the lists holding their first items, dropping the emptied ones.

    Args:
        lists: The lists of results to limit
        count: The number of items to keep in each list, at most

    Returns:
        The limited copies of the lists still holding an item
    """
    # A negative count would keep the items but the last ones, which is not a limit
    kept = max(count, 0)
    return [
        result_list.model_copy(update={"items": result_list.items[:kept]})
        for result_list in lists
        if result_list.items[:kept]
    ]


def _lists_without_first_items(
    lists: list["SearchResultList"], count: int
) -> list["SearchResultList"]:
    """Return copies of the lists without their first items, dropping the emptied ones.

    Args:
        lists: The lists of results to offset
        count: The number of items to skip in each list

    Returns:
        The offset copies of the lists still holding an item
    """
    # A negative count would drop the items but the last ones, which is not an offset
    skipped = max(count, 0)
    return [
        result_list.model_copy(update={"items": result_list.items[skipped:]})
        for result_list in lists
        if result_list.items[skipped:]
    ]


def _lists_with_items_kept(
    lists: list["SearchResultList"],
    keep: Callable[["SearchResultItem"], bool],
) -> list["SearchResultList"]:
    """Return copies of the lists holding their items passing the check, dropping the emptied ones.

    Args:
        lists: The lists of results to filter
        keep: The check an item must pass to be kept

    Returns:
        The filtered copies of the lists still holding an item
    """
    kept_lists = []
    for result_list in lists:
        items = [item for item in result_list.items if keep(item)]
        if items:
            kept_lists.append(result_list.model_copy(update={"items": items}))
    return kept_lists


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


class Alarm(VolumioModel):
    """An alarm set on a Volumio instance."""

    enabled: bool | None = None
    """Whether the alarm is armed."""

    id: int | None = None
    """The identifier of the alarm."""

    name: str | None = None
    """The name of the alarm."""

    playlist: str | None = None
    """The name of the playlist the alarm plays."""

    time: str | None = None
    """The time the alarm goes off, as ``"HH:MM"``."""


class Alarms(VolumioModel):
    """The alarms set on a Volumio instance.

    The collection is a sequence of its alarms: it can be iterated, indexed, and
    measured with ``len()``.
    """

    alarms: list[Alarm] = Field(default_factory=list)
    """The alarms, in the order reported by the Volumio instance."""

    def __getitem__(self, index: int) -> Alarm:
        """Return the alarm at the given position."""
        return self.alarms[index]

    def __iter__(self) -> Iterator[Alarm]:  # type: ignore[override]
        """Iterate over the alarms."""
        return iter(self.alarms)

    def __len__(self) -> int:
        """Return the number of alarms."""
        return len(self.alarms)


class AudioOutput(VolumioModel):
    """An audio output a Volumio instance can play to.

    The shape comes from the ``outputs`` plugin of the host, so a field that plugin does
    not report stays None; whatever it did report is readable through ``raw``.
    """

    enabled: bool | None = None
    """Whether the output is enabled."""

    id: str | None = None
    """The identifier of the output."""

    name: str | None = None
    """The name of the output."""

    type: str | None = None
    """The type of the output."""

    volume: int | None = None
    """The volume level of the output."""


class AudioOutputs(VolumioModel):
    """The audio outputs a Volumio instance can play to.

    The collection is a sequence of its outputs: it can be iterated, indexed, and
    measured with ``len()``.
    """

    available_outputs: list[AudioOutput] = Field(
        default_factory=list, alias="availableOutputs"
    )
    """The available outputs, in the order reported by the Volumio instance."""

    def __getitem__(self, index: int) -> AudioOutput:
        """Return the output at the given position."""
        return self.available_outputs[index]

    def __iter__(self) -> Iterator[AudioOutput]:  # type: ignore[override]
        """Iterate over the available outputs."""
        return iter(self.available_outputs)

    def __len__(self) -> int:
        """Return the number of available outputs."""
        return len(self.available_outputs)


class Background(VolumioModel):
    """A background image of the user interface of a Volumio instance."""

    name: str | None = None
    """The name of the background."""

    path: str | None = None
    """The path of the image, relative to the host."""

    thumbnail: str | None = None
    """The path of its thumbnail, relative to the host."""


class Backgrounds(VolumioModel):
    """The background images of the user interface of a Volumio instance.

    The collection is a sequence of the available backgrounds: it can be iterated,
    indexed, and measured with ``len()``; the one in use is :attr:`current`.
    """

    available: list[Background] = Field(default_factory=list)
    """The backgrounds that can be chosen."""

    current: Background | None = None
    """The background in use."""

    def __getitem__(self, index: int) -> Background:
        """Return the available background at the given position."""
        return self.available[index]

    def __iter__(self) -> Iterator[Background]:  # type: ignore[override]
        """Iterate over the available backgrounds."""
        return iter(self.available)

    def __len__(self) -> int:
        """Return the number of available backgrounds."""
        return len(self.available)


class BrowseSource(VolumioModel):
    """A source a Volumio instance can browse."""

    albumart: str | None = None
    """The URL of the icon of the source, relative to the host."""

    name: str | None = None
    """The name of the source."""

    plugin_name: str | None = None
    """The name of the plugin serving the source."""

    plugin_type: str | None = None
    """The type of the plugin serving the source (e.g., ``"music_service"``)."""

    uri: str | None = None
    """The URI the source is browsed at."""


class BrowseSources(VolumioModel):
    """The sources a Volumio instance can browse.

    The collection is a sequence of its sources: it can be iterated, indexed, and
    measured with ``len()``.
    """

    sources: list[BrowseSource] = Field(default_factory=list)
    """The browsable sources, in the order reported by the Volumio instance."""

    def __getitem__(self, index: int) -> BrowseSource:
        """Return the source at the given position."""
        return self.sources[index]

    def __iter__(self) -> Iterator[BrowseSource]:  # type: ignore[override]
        """Iterate over the browsable sources."""
        return iter(self.sources)

    def __len__(self) -> int:
        """Return the number of browsable sources."""
        return len(self.sources)


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


class ExperienceOption(VolumioModel):
    """One of the ways the user interface of a Volumio instance can be shown."""

    id: bool | None = None
    """True for the full set of options, False for the simplified one."""

    label: str | None = None
    """The setting as it is displayed."""


class ExperienceSettings(VolumioModel):
    """How many options the user interface of a Volumio instance offers.

    The Volumio API reports the setting in use as the whole option, label included;
    :attr:`advanced` reads the flag out of it.
    """

    options: list[ExperienceOption] = Field(default_factory=list)
    """The settings that can be chosen."""

    status: ExperienceOption | None = None
    """The setting in use."""

    @property
    def advanced(self) -> bool | None:
        """Whether the full set of options is in use, None when unreported."""
        return self.status.id if self.status is not None else None


class DeviceInfo(VolumioModel):
    """The identity of a Volumio instance."""

    name: str | None = None
    """The name of the device."""

    uuid: str | None = None
    """The hardware identifier of the device."""


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


class InputSources(VolumioModel):
    """The input sources a Volumio instance exposes.

    A Volumio host reports these as a mapping whose keys depend on the plugins it runs,
    and answers an empty one where there is no input source at all. The payload is
    readable through ``raw``.
    """


class InfinityPlayback(VolumioModel):
    """The infinity playback setting of a Volumio instance."""

    available: bool | None = None
    """Whether the host offers infinity playback at all."""

    enabled: bool | None = None
    """Whether infinity playback is on."""


class Language(VolumioModel):
    """A language the user interface of a Volumio instance can be shown in."""

    code: str | None = None
    """The code of the language (e.g., ``"en"``)."""

    language: str | None = None
    """The name of the language, in the language itself."""


class Languages(VolumioModel):
    """The languages the user interface of a Volumio instance can be shown in.

    The collection is a sequence of the available languages: it can be iterated,
    indexed, and measured with ``len()``; the one in use is :attr:`default_language`.
    """

    available: list[Language] = Field(default_factory=list)
    """The languages that can be chosen."""

    default_language: Language | None = Field(default=None, alias="defaultLanguage")
    """The language in use."""

    def __getitem__(self, index: int) -> Language:
        """Return the available language at the given position."""
        return self.available[index]

    def __iter__(self) -> Iterator[Language]:  # type: ignore[override]
        """Iterate over the available languages."""
        return iter(self.available)

    def __len__(self) -> int:
        """Return the number of available languages."""
        return len(self.available)


class MenuItem(VolumioModel):
    """An entry of the menu a Volumio instance offers its user interface."""

    id: str | None = None
    """The identifier of the entry."""

    name: str | None = None
    """The name of the entry."""

    params: dict[str, Any] | None = None
    """The parameters the entry carries, when it names a plugin page."""

    state: str | None = None
    """The user interface state the entry leads to."""


class MenuItems(VolumioModel):
    """The menu a Volumio instance offers its user interface.

    The collection is a sequence of its entries: it can be iterated, indexed, and
    measured with ``len()``.
    """

    items: list[MenuItem] = Field(default_factory=list)
    """The menu entries, in the order reported by the Volumio instance."""

    def __getitem__(self, index: int) -> MenuItem:
        """Return the entry at the given position."""
        return self.items[index]

    def __iter__(self) -> Iterator[MenuItem]:  # type: ignore[override]
        """Iterate over the menu entries."""
        return iter(self.items)

    def __len__(self) -> int:
        """Return the number of menu entries."""
        return len(self.items)


class MusicSource(VolumioModel):
    """A music source plugin of a Volumio instance."""

    active: bool | None = None
    """Whether the source is currently active."""

    category: str | None = None
    """The plugin category the source belongs to (e.g., ``"music_service"``)."""

    enabled: bool | None = None
    """Whether the source is enabled."""

    has_configuration: bool | None = Field(default=None, alias="hasConfiguration")
    """Whether the source offers a configuration page."""

    name: str | None = None
    """The name of the source, as the plugin is identified."""

    pretty_name: str | None = Field(default=None, alias="prettyName")
    """The name of the source, as it is displayed."""


class MusicSources(VolumioModel):
    """The music source plugins of a Volumio instance.

    The collection is a sequence of its sources: it can be iterated, indexed, and
    measured with ``len()``.
    """

    plugins: list[MusicSource] = Field(default_factory=list)
    """The music sources, in the order reported by the Volumio instance."""

    def __getitem__(self, index: int) -> MusicSource:
        """Return the source at the given position."""
        return self.plugins[index]

    def __iter__(self) -> Iterator[MusicSource]:  # type: ignore[override]
        """Iterate over the music sources."""
        return iter(self.plugins)

    def __len__(self) -> int:
        """Return the number of music sources."""
        return len(self.plugins)


class Multiroom(VolumioModel):
    """The multiroom configuration of a Volumio instance.

    The shape comes from the ``multiroom`` plugin, so a host without it never answers;
    whatever it did report is readable through ``raw``.
    """

    enabled: bool | None = None
    """Whether multiroom is on."""

    mode: str | None = None
    """The role the host plays (e.g., ``"client"``, ``"server"``, ``"single"``)."""


class NetworkInterface(VolumioModel):
    """A network interface of a Volumio instance."""

    ip: str | None = None
    """The address the interface holds."""

    speed: str | None = None
    """The speed the interface negotiated (e.g., ``"1Gb/s"``)."""

    status: str | None = None
    """The state of the interface (e.g., ``"connected"``)."""

    type: str | None = None
    """The kind of interface (e.g., ``"Wired"``, ``"Wireless"``)."""


class NetworkInfo(VolumioModel):
    """The network interfaces of a Volumio instance.

    The collection is a sequence of its interfaces: it can be iterated, indexed, and
    measured with ``len()``.
    """

    interfaces: list[NetworkInterface] = Field(default_factory=list)
    """The interfaces, in the order reported by the Volumio instance."""

    def __getitem__(self, index: int) -> NetworkInterface:
        """Return the interface at the given position."""
        return self.interfaces[index]

    def __iter__(self) -> Iterator[NetworkInterface]:  # type: ignore[override]
        """Iterate over the interfaces."""
        return iter(self.interfaces)

    def __len__(self) -> int:
        """Return the number of interfaces."""
        return len(self.interfaces)


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


class OutputDevice(VolumioModel):
    """An output device a Volumio instance can play through."""

    id: str | None = None
    """The identifier of the device."""

    name: str | None = None
    """The name of the device."""


class OutputDevices(VolumioModel):
    """The output devices a Volumio instance can play through.

    The collection is a sequence of the available devices: it can be iterated, indexed,
    and measured with ``len()``; the one in use is :attr:`active`.
    """

    active: OutputDevice | None = None
    """The device currently in use."""

    available: list[OutputDevice] = Field(default_factory=list)
    """The devices that can be selected, in the order reported by the instance."""

    i2s: bool | None = None
    """Whether an I2S DAC is configured on the host."""

    @classmethod
    def from_envelope(cls, payload: dict[str, Any]) -> Self:
        """Build the devices from the envelope a Volumio instance answers with.

        The instance nests the devices under a ``devices`` key, beside the I2S flag.

        Args:
            payload: The answer of the Volumio instance

        Returns:
            The output devices

        Raises:
            VolumioAPIError: If the answer carries no ``devices`` object
        """
        devices = payload.get("devices")
        if not isinstance(devices, dict):
            raise VolumioAPIError(
                f"Expected a devices object from the Volumio API, "
                f"got {type(devices).__name__}"
            )
        return cls.model_validate({**devices, "i2s": payload.get("i2s"), "raw": payload})

    def __getitem__(self, index: int) -> OutputDevice:
        """Return the available device at the given position."""
        return self.available[index]

    def __iter__(self) -> Iterator[OutputDevice]:  # type: ignore[override]
        """Iterate over the available devices."""
        return iter(self.available)

    def __len__(self) -> int:
        """Return the number of available devices."""
        return len(self.available)


class Plugin(VolumioModel):
    """A plugin installed on a Volumio instance."""

    active: bool | None = None
    """Whether the plugin is running."""

    category: str | None = None
    """The category the plugin belongs to (e.g., ``"music_service"``)."""

    enabled: bool | None = None
    """Whether the plugin is enabled."""

    icon: str | None = None
    """The icon of the plugin."""

    name: str | None = None
    """The name of the plugin, as it is identified."""

    pretty_name: str | None = Field(default=None, alias="prettyName")
    """The name of the plugin, as it is displayed."""

    version: str | None = None
    """The version of the plugin."""


class Plugins(VolumioModel):
    """The plugins installed on a Volumio instance.

    The collection is a sequence of its plugins: it can be iterated, indexed, and
    measured with ``len()``.
    """

    plugins: list[Plugin] = Field(default_factory=list)
    """The installed plugins, in the order reported by the Volumio instance."""

    def __getitem__(self, index: int) -> Plugin:
        """Return the plugin at the given position."""
        return self.plugins[index]

    def __iter__(self) -> Iterator[Plugin]:  # type: ignore[override]
        """Iterate over the installed plugins."""
        return iter(self.plugins)

    def __len__(self) -> int:
        """Return the number of installed plugins."""
        return len(self.plugins)


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


class PowerModes(VolumioModel):
    """The ways a Volumio instance can be powered down."""

    has_power_off_mode: bool | None = Field(default=None, alias="hasPowerOffMode")
    """Whether the host can be shut down."""

    has_standby_mode: bool | None = Field(default=None, alias="hasStandbyMode")
    """Whether the host can be put on standby."""


class PrivacySettings(VolumioModel):
    """The privacy settings of a Volumio instance."""

    allow_ui_statistics: bool | None = Field(default=None, alias="allowUIStatistics")
    """Whether the host may report how its user interface is used."""


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


class PlaylistContent(VolumioModel):
    """The tracks of a playlist saved on a Volumio instance.

    The collection is a sequence of its tracks: it can be iterated, indexed, and
    measured with ``len()``.

    The class is defined here, out of alphabetical order, because it holds
    :class:`QueueTrack`.
    """

    name: str | None = None
    """The name of the playlist."""

    tracks: list[QueueTrack] = Field(default_factory=list)
    """The tracks of the playlist, in playlist order."""

    @classmethod
    def from_envelope(cls, payload: dict[str, Any]) -> Self:
        """Build the content from the envelope a Volumio instance answers with.

        The instance groups the tracks in one list per source, so the lists are flattened
        into a single sequence.

        Args:
            payload: The answer of the Volumio instance

        Returns:
            The content of the playlist
        """
        lists = payload.get("lists")
        tracks: list[Any] = []
        if isinstance(lists, list):
            for entry in lists:
                if isinstance(entry, list):
                    tracks.extend(track for track in entry if isinstance(track, dict))
                elif isinstance(entry, dict):
                    tracks.append(entry)
        return cls.model_validate(
            {"name": payload.get("name"), "tracks": tracks, "raw": payload}
        )

    def __getitem__(self, index: int) -> QueueTrack:
        """Return the track at the given position of the playlist."""
        return self.tracks[index]

    def __iter__(self) -> Iterator[QueueTrack]:  # type: ignore[override]
        """Iterate over the tracks of the playlist."""
        return iter(self.tracks)

    def __len__(self) -> int:
        """Return the number of tracks in the playlist."""
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

    name: str | None = None
    """The name of the result, which is what a browsed root listing has for a title."""

    plugin_name: str | None = None
    """The plugin serving the result (e.g., ``"mpd"``), in a browsed root listing."""

    plugin_type: str | None = None
    """The type of that plugin (e.g., ``"music_service"``), in a browsed root listing."""

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
    def kind(self) -> "SearchResultItemKind":
        """The kind of entity the result is, read from its type and its URI.

        A Volumio host reports the tracks with the ``song`` type, and sometimes names
        the kind in the type outright (the entity a browse describes, for instance);
        otherwise the URI tells (``artists://...`` and ``qobuz://artist/...`` for the
        artists, and likewise for the albums and the playlists), knowing that
        ``artists://X/Y`` is not an artist but an album of one, which is how a browsed
        artist lists its albums.

        Returns:
            The kind of the result, :attr:`SearchResultItemKind.OTHER` when it is none of
            the kinds the model knows
        """
        if self.type == "song":
            return SearchResultItemKind.TRACK
        entity_kinds = (
            SearchResultItemKind.ARTIST,
            SearchResultItemKind.ALBUM,
            SearchResultItemKind.PLAYLIST,
        )
        for kind in entity_kinds:
            if self.type == kind.value:
                return kind
        uri = self.uri or ""
        if uri.startswith("artists://"):
            in_artist = uri.removeprefix("artists://")
            if "/" in in_artist:
                return SearchResultItemKind.ALBUM
            return SearchResultItemKind.ARTIST
        for kind in entity_kinds:
            if uri.startswith(f"{kind.value}s://") or f"://{kind.value}/" in uri:
                return kind
        return SearchResultItemKind.OTHER


class SearchResultItemKind(StrEnum):
    """The kind of entity a search result is.

    A member is its own lowercase name, so it can be compared to a string and written to
    JSON as it is.
    """

    ALBUM = "album"
    """An album of a source."""

    ARTIST = "artist"
    """An artist of a source."""

    OTHER = "other"
    """Anything else, a web radio for instance."""

    PLAYLIST = "playlist"
    """A playlist of a source."""

    TRACK = "track"
    """A playable track, which a Volumio host types as a song."""


class SearchResultList(VolumioModel):
    """A titled list of search results, as a Volumio instance groups them.

    The list is a sequence of its items: it can be iterated, indexed, and measured
    with ``len()``.
    """

    available_list_views: list[str] | None = Field(default=None, alias="availableListViews")
    """The views the host suggests for the list (e.g., ``["list", "grid"]``)."""

    count: int | None = None
    """The number of items the list held before the host offset or limited it."""

    filters: dict[str, Any] | None = None
    """The offset and limit the host applied to the list, when it applied any."""

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
        track: str | None = None,
        playlist: str | None = None,
        kinds: Collection[SearchResultItemKind] | None = None,
    ) -> "SearchResults":
        """Return the results whose items match every filter given.

        A filter is ignored when it is None. The service is matched by equality, and the
        kind by membership, while the other filters are matched as case-insensitive
        substrings, against the field of the item (``artist``, ``album``) and against the
        title of the entity itself (an artist, an album, a playlist, or a track), which is
        where a Volumio host carries the name of an entity. An empty string matches every
        entity of its kind. The lists left without items are dropped, and the raw payload
        is preserved.

        Args:
            service: The source the results must come from
            artist: The text an artist of a result, or an artist result, must contain
            album: The text an album of a result, or an album result, must contain
            track: The text a track result must contain
            playlist: The text a playlist result must contain
            kinds: The kinds of entity the results must be

        Returns:
            The filtered results, holding the original payload in their ``raw`` attribute
        """

        def matches(item: SearchResultItem) -> bool:
            if service is not None and (item.service or "").lower() != service.lower():
                return False
            if kinds is not None and item.kind not in kinds:
                return False
            for text, field, kind in (
                (artist, item.artist, SearchResultItemKind.ARTIST),
                (album, item.album, SearchResultItemKind.ALBUM),
                (track, None, SearchResultItemKind.TRACK),
                (playlist, None, SearchResultItemKind.PLAYLIST),
            ):
                if text is None:
                    continue
                wanted = text.lower()
                in_field = wanted in (field or "").lower() if field else False
                in_title = item.kind == kind and wanted in (item.title or "").lower()
                if not (in_field or in_title):
                    return False
            return True

        return self.model_copy(update={"lists": _lists_with_items_kept(self.lists, matches)})

    def limited(self, count: int) -> "SearchResults":
        """Return the results with at most the given number of items in each list.

        The items kept are the first ones of each list, in the order the host reported
        them, which is the order of relevance a source answers a query with. The lists
        left without items are dropped, and the raw payload is preserved.

        Args:
            count: The number of items to keep in each list, at most

        Returns:
            The limited results, holding the original payload in their ``raw`` attribute
        """
        return self.model_copy(update={"lists": _lists_with_first_items(self.lists, count)})

    def offset(self, count: int) -> "SearchResults":
        """Return the results without the first items of each list.

        The items skipped are the first ones of each list, in the order the host
        reported them. The lists left without items are dropped, and the raw payload
        is preserved.

        Args:
            count: The number of items to skip in each list

        Returns:
            The offset results, holding the original payload in their ``raw`` attribute
        """
        return self.model_copy(update={"lists": _lists_without_first_items(self.lists, count)})


class BrowseResults(VolumioModel):
    """The content a Volumio instance lists at a browsing URI.

    The content is a sequence of the lists the host grouped it in: the collection can
    be iterated, indexed, and measured with ``len()``. The :attr:`raw` attribute holds
    the whole response envelope, as the host returned it. The class follows
    :class:`SearchResults`, whose list model it shares, instead of its lexicographic
    place.
    """

    info: SearchResultItem | None = None
    """The entity being browsed (e.g., the album of the tracks listed), when given."""

    lists: list[SearchResultList] = Field(default_factory=list)
    """The lists of content, in the order reported by the Volumio instance."""

    prev: dict[str, Any] | None = None
    """The step back up, as the host gives it (see :attr:`prev_uri`)."""

    @classmethod
    def from_envelope(cls, envelope: dict[str, Any]) -> Self:
        """Parse the response envelope of a browse query.

        A root listing puts its items directly into ``lists``, without list objects
        around them: such loose items are gathered into one untitled list, before any
        list the payload also carries.

        Args:
            envelope: The response envelope (``{"navigation": {...}}``)

        Returns:
            The content, holding the whole envelope in its ``raw`` attribute

        Raises:
            VolumioAPIError: If the envelope cannot be parsed into the model
        """
        navigation = envelope.get("navigation")
        if not isinstance(navigation, dict):
            navigation = {}
        lists = navigation.get("lists")
        if isinstance(lists, list):
            loose = [entry for entry in lists if isinstance(entry, dict) and "items" not in entry]
            if loose:
                grouped: list[dict[str, Any]] = [{"items": loose}]
                grouped += [
                    entry for entry in lists if isinstance(entry, dict) and "items" in entry
                ]
                navigation = {**navigation, "lists": grouped}
        # The content comes from the navigation, while raw keeps the whole envelope
        return cls.from_raw({**navigation, "raw": envelope})

    @property
    def items(self) -> list[SearchResultItem]:
        """Every item of every list, in the order reported."""
        return [item for result_list in self.lists for item in result_list.items]

    @property
    def prev_uri(self) -> str | None:
        """The URI of the parent of the browsed URI, when the host gives one."""
        if isinstance(self.prev, dict) and isinstance(self.prev.get("uri"), str):
            return str(self.prev["uri"])
        return None

    def __getitem__(self, index: int) -> SearchResultList:
        """Return the list of content at the given position."""
        return self.lists[index]

    def __iter__(self) -> Iterator[SearchResultList]:  # type: ignore[override]
        """Iterate over the lists of content."""
        return iter(self.lists)

    def __len__(self) -> int:
        """Return the number of lists of content."""
        return len(self.lists)

    def filtered(self, kinds: Collection[SearchResultItemKind]) -> "BrowseResults":
        """Return the content whose items are of one of the given kinds.

        The lists left without items are dropped, and the raw payload is preserved.

        Args:
            kinds: The kinds of entity the items must be

        Returns:
            The filtered content, holding the original payload in its ``raw`` attribute
        """
        return self.model_copy(
            update={"lists": _lists_with_items_kept(self.lists, lambda item: item.kind in kinds)}
        )

    def limited(self, count: int) -> "BrowseResults":
        """Return the content with at most the given number of items in each list.

        The items kept are the first ones of each list, in the order the host reported
        them. The lists left without items are dropped, and the raw payload is
        preserved.

        Args:
            count: The number of items to keep in each list, at most

        Returns:
            The limited content, holding the original payload in its ``raw`` attribute
        """
        return self.model_copy(update={"lists": _lists_with_first_items(self.lists, count)})


class Share(VolumioModel):
    """A network share mounted by a Volumio instance."""

    fstype: str | None = None
    """The kind of the share (e.g., ``"cifs"``, ``"nfs"``)."""

    id: str | None = None
    """The identifier of the share."""

    name: str | None = None
    """The name of the share."""

    options: str | None = None
    """The mount options of the share."""

    path: str | None = None
    """The path of the share on its host."""

    size: str | None = None
    """The size of the share, as the host reports it."""

    username: str | None = None
    """The user the share is mounted as."""


class Shares(VolumioModel):
    """The network shares mounted by a Volumio instance.

    The collection is a sequence of its shares: it can be iterated, indexed, and
    measured with ``len()``.
    """

    shares: list[Share] = Field(default_factory=list)
    """The mounted shares, in the order reported by the Volumio instance."""

    def __getitem__(self, index: int) -> Share:
        """Return the share at the given position."""
        return self.shares[index]

    def __iter__(self) -> Iterator[Share]:  # type: ignore[override]
        """Iterate over the mounted shares."""
        return iter(self.shares)

    def __len__(self) -> int:
        """Return the number of mounted shares."""
        return len(self.shares)


class SleepTimer(VolumioModel):
    """The sleep timer of a Volumio instance.

    The Volumio API reports the timer as a delay from now, not as a clock time, which is
    what :attr:`delay` reads it as.
    """

    action: dict[str, Any] | None = None
    """What the host does when the timer expires."""

    enabled: bool | None = None
    """Whether the timer is armed."""

    time: str | None = None
    """The delay before the timer expires, as ``"H:MM"``."""

    @property
    def delay(self) -> timedelta | None:
        """The delay before the timer expires, None when it carries no readable one."""
        if self.time is None:
            return None
        hours, _, minutes = self.time.partition(":")
        try:
            return timedelta(hours=int(hours), minutes=int(minutes))
        except ValueError:
            return None


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


class Timezones(VolumioModel):
    """The time zones a Volumio instance can be set to.

    The collection is a sequence of their names: it can be iterated, indexed, and
    measured with ``len()``.
    """

    timezones: list[str] = Field(default_factory=list)
    """The names of the time zones (e.g., ``"Europe/Rome"``)."""

    def __getitem__(self, index: int) -> str:
        """Return the time zone at the given position."""
        return self.timezones[index]

    def __iter__(self) -> Iterator[str]:  # type: ignore[override]
        """Iterate over the time zones."""
        return iter(self.timezones)

    def __len__(self) -> int:
        """Return the number of time zones."""
        return len(self.timezones)


class UiConfig(VolumioModel):
    """The configuration page a plugin of a Volumio instance offers."""

    page: dict[str, Any] | None = None
    """The heading of the page."""

    sections: list[dict[str, Any]] = Field(default_factory=list)
    """The sections of the page, each with its settings."""


class UiSettings(VolumioModel):
    """The user interface settings of a Volumio instance."""

    color: str | None = None
    """The accent color of the interface."""

    language: str | None = None
    """The language code of the interface (e.g., ``"en"``)."""

    theme: str | None = None
    """The name of the theme of the interface."""


class UpdaterChannel(VolumioModel):
    """The update channel a Volumio instance follows."""

    available_channels: list[str] = Field(default_factory=list, alias="availableChannels")
    """The channels that can be chosen (e.g., ``"stable"``, ``"test"``)."""

    current_channel: str | None = Field(default=None, alias="currentChannel")
    """The channel in use."""


class UsbDrive(VolumioModel):
    """A USB drive attached to a Volumio instance."""

    device: str | None = None
    """The device node of the drive."""

    mountpoint: str | None = None
    """Where the drive is mounted."""

    name: str | None = None
    """The name of the drive."""

    size: str | None = None
    """The size of the drive, as the host reports it."""


class UsbDrives(VolumioModel):
    """The USB drives attached to a Volumio instance.

    The collection is a sequence of its drives: it can be iterated, indexed, and
    measured with ``len()``.
    """

    drives: list[UsbDrive] = Field(default_factory=list)
    """The attached drives, in the order reported by the Volumio instance."""

    def __getitem__(self, index: int) -> UsbDrive:
        """Return the drive at the given position."""
        return self.drives[index]

    def __iter__(self) -> Iterator[UsbDrive]:  # type: ignore[override]
        """Iterate over the attached drives."""
        return iter(self.drives)

    def __len__(self) -> int:
        """Return the number of attached drives."""
        return len(self.drives)


class WirelessNetwork(VolumioModel):
    """A wireless network a Volumio instance can see."""

    configured: bool | None = None
    """Whether the host holds credentials for the network."""

    security: str | None = None
    """The security of the network (e.g., ``"wpa"``), empty when it is open."""

    signal: int | None = None
    """The strength of the signal."""

    ssid: str | None = None
    """The name of the network."""


class WirelessNetworks(VolumioModel):
    """The wireless networks a Volumio instance can see.

    The collection is a sequence of the networks: it can be iterated, indexed, and
    measured with ``len()``.
    """

    available: list[WirelessNetwork] = Field(default_factory=list)
    """The networks the host can see."""

    def __getitem__(self, index: int) -> WirelessNetwork:
        """Return the network at the given position."""
        return self.available[index]

    def __iter__(self) -> Iterator[WirelessNetwork]:  # type: ignore[override]
        """Iterate over the networks."""
        return iter(self.available)

    def __len__(self) -> int:
        """Return the number of networks."""
        return len(self.available)


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
