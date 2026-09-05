"""The API client adapters of the volumito CLI.

The library offers four clients for the APIs of a Volumio host: the synchronous and the
asynchronous REST API clients, and the synchronous and the asynchronous WebSocket API
clients. The commands of the CLI are written against the synchronous REST API client:
properties for the reads, plain methods for the commands, and the assignable ``seek``
and ``volume``. The adapters of this module give the other three clients that same
surface, so the commands run unchanged whichever client the ``--api-client`` option
selects.

The asynchronous clients run on a private event loop, served by a daemon thread for the
whole life of the adapter, so the session of the REST client and the heartbeat of the
WebSocket client survive the long synchronous stretches of a command (e.g., the
downloads between two calls of ``queue download``).

Each API lacks something the other offers. The WebSocket API offers neither the story
queries nor the notification URLs: the WebSocket adapters serve them through a REST API
client when the CLI allows the fallback, and raise :class:`UnsupportedOperationError`
otherwise. The REST API offers none of the members the *Beyond The REST API* section of
the library usage document lists (the queue and playlist edits, the favourites, the
sleep timer, the system settings, and so on): the REST adapters serve them through a
WebSocket API client when the CLI allows that fallback, and raise the same error
otherwise.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

import asyncio
import logging
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable, Coroutine
from datetime import timedelta
from typing import Any, Self

from volumito.clients import (
    Alarm,
    Alarms,
    Album,
    Artist,
    AudioOutputs,
    Backgrounds,
    BrowseResults,
    BrowseSources,
    CollectionStatistics,
    CommandResponse,
    ExperienceSettings,
    InfinityPlayback,
    InputSources,
    Label,
    Languages,
    MenuItems,
    Multiroom,
    MusicSources,
    NetworkInfo,
    Notification,
    Notifications,
    OutputDevices,
    Place,
    PlayerState,
    Playlist,
    PlaylistContent,
    Playlists,
    Plugins,
    PowerModes,
    PrivacySettings,
    Queue,
    QueueTrack,
    SearchResults,
    Share,
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
    VolumioAsyncRESTAPIClient,
    VolumioAsyncWebSocketClient,
    VolumioHostConfiguration,
    VolumioRESTAPIClient,
    VolumioWebSocketClient,
    WirelessNetworks,
    Zones,
)
from volumito.clients.common import VolumioCommon

ALARM_OPERATION = "the sleep timer and the alarms"
"""How the messages name the sleep timer and alarm members the REST API does not offer."""

AUDIO_OPERATION = "the audio outputs and devices"
"""How the messages name the audio output and device members the REST API does not offer."""

COLLECTION_OPERATION = "the collection extras"
"""How the messages name the collection members the REST API does not offer."""

EVENT_LOOP_THREAD_NAME = "volumito-event-loop"
"""The name of the thread serving the event loop of an asynchronous client."""

EVENT_OPERATION = "the events"
"""How the messages name the event members the REST API does not offer."""

FAVOURITE_OPERATION = "the favourites and the web radios"
"""How the messages name the favourite and web radio members the REST API does not offer."""

MULTIROOM_OPERATION = "the multiroom settings"
"""How the messages name the multiroom members the REST API does not offer."""

NETWORK_OPERATION = "the network settings"
"""How the messages name the network members the REST API does not offer."""

NOTIFICATION_OPERATION = "the notification URLs"
"""How the messages name the notification members the WebSocket API does not offer."""

PLAYBACK_OPERATION = "the playback extras"
"""How the messages name the playback members the REST API does not offer."""

PLAYLIST_OPERATION = "the playlist edits"
"""How the messages name the playlist members the REST API does not offer."""

PLUGIN_OPERATION = "the plugins"
"""How the messages name the plugin members the REST API does not offer."""

QUEUE_OPERATION = "the queue edits"
"""How the messages name the queue members the REST API does not offer."""

SHARE_OPERATION = "the network shares and the USB drives"
"""How the messages name the share and USB drive members the REST API does not offer."""

STORY_OPERATION = "the story queries"
"""How the messages name the story members the WebSocket API does not offer."""

SYSTEM_OPERATION = "the system settings"
"""How the messages name the system members the REST API does not offer."""

UI_OPERATION = "the user interface settings"
"""How the messages name the user interface members the REST API does not offer."""

UPDATE_OPERATION = "the updates"
"""How the messages name the update members the REST API does not offer."""


def _story_arguments(
    album: Album | None,
    artist: Artist | None,
    label: Label | None,
    place: Place | None,
) -> dict[str, Any]:
    """Return the entities of a story query given, keyed by their parameter name.

    The clients take the missing entities as None, so the ones left out are the same
    to them; passing only the given ones keeps the calls as the commands make them.

    Args:
        album: The album whose story to get, when given
        artist: The artist whose story to get, when given
        label: The label whose story to get, when given
        place: The place whose story to get, when given

    Returns:
        The entities given, by parameter name
    """
    given = {"album": album, "artist": artist, "label": label, "place": place}
    return {name: entity for name, entity in given.items() if entity is not None}


class UnsupportedOperationError(Exception):
    """Raised when the selected API client does not offer an operation a command needs."""


class APIClient(ABC):
    """The surface of a Volumio API client the commands of the CLI run against.

    It is the one of the synchronous REST API client: the reads are properties, the
    commands are methods returning what the host answered (the WebSocket API answers
    nothing, so those return None), and ``seek`` and ``volume`` can be assigned. The
    lifecycle is explicit: :meth:`open` before the first use, :meth:`close` after the
    last one, or a ``with`` statement doing both.

    The forwarders of the concrete adapters inherit the docstrings of the abstract
    members below.
    """

    DESCRIPTION: str = "API client"
    """How the adapter names itself in the messages."""

    def __init__(self, client: VolumioCommon) -> None:
        """Initialize the adapter.

        Args:
            client: The client the adapter wraps
        """
        self._wrapped = client

    def _close_quietly(self, action: Callable[[], None]) -> None:
        """Run a closing action, turning its failure into a warning.

        The adapters close from the exit callbacks of the CLI, also while an exit
        unwinds: a failure there must not replace the outcome of the command.

        Args:
            action: The closing action to run
        """
        try:
            action()
        except Exception as e:
            self.logger.warning(f"Closing the {self.description} failed ({e})")

    @abstractmethod
    def add_and_play(self, uri: str) -> None:
        """Add the content of a URI to the queue and start playing it.

        Like :meth:`add_to_queue`, the URI of a container of a source other than the
        local library is browsed first and queued as the items it lists.

        Args:
            uri: The URI whose content to add and play, from a browse or a search
        """

    @abstractmethod
    def add_cue_track(self, uri: str, number: int, service: str | None = None) -> None:
        """Add one track of a cue sheet to the queue and play it.

        Args:
            uri: The URI of the cue sheet
            number: The position of the track inside the cue sheet
            service: The service the URI belongs to, derived from it when not given
        """

    @abstractmethod
    def add_radio_favourite(self, uri: str) -> None:
        """Add a web radio to the radio favourites.

        Args:
            uri: The URL the web radio streams from
        """

    @abstractmethod
    def add_share(self, name: str, path: str, fstype: str, **options: str) -> None:
        """Mount a network share on the Volumio instance.

        Args:
            name: The name to mount the share under
            path: The path of the share on its host (e.g., ``"192.168.1.2/Music"``)
            fstype: The kind of the share (e.g., ``"cifs"``, ``"nfs"``)
            **options: The remaining fields the share needs (``username``, ``password``,
                ``options``)
        """

    @abstractmethod
    def add_to_favourites(
        self,
        uri: str,
        title: str | None = None,
        service: str | None = None,
        albumart: str | None = None,
    ) -> None:
        """Add an item to the favourites.

        Args:
            uri: The URI of the item, from a browse or a search
            title: The title to show for it, when known
            service: The service the URI belongs to, derived from it when not given
            albumart: The URL of the cover to show for it, when known
        """

    @abstractmethod
    def add_to_playlist(self, name: str | Playlist, uri: str, service: str | None = None) -> None:
        """Add an item to a saved playlist, creating the playlist if it does not exist.

        Args:
            name: The name of the playlist, or the playlist itself
            uri: The URI of the item to add, from a browse or a search
            service: The service the URI belongs to, derived from it when not given
        """

    @abstractmethod
    def add_to_queue(self, uri: str) -> CommandResponse | None:
        """Add the content of a URI to the queue.

        Args:
            uri: The URI to add
        """

    @abstractmethod
    def add_uids_to_queue(self, uids: list[str]) -> None:
        """Add items of the local library to the queue, by identifier.

        Args:
            uids: The identifiers of the items to queue
        """

    @abstractmethod
    def add_web_radio(self, name: str, uri: str) -> None:
        """Save a web radio of the user.

        Args:
            name: The name to save the web radio under
            uri: The URL it streams from
        """

    @property
    @abstractmethod
    def alarms(self) -> Alarms:
        """The alarms set on the Volumio instance.

        Each access emits a fresh event. The alarms come from the ``alarm-clock``
        plugin: a host without it never answers, and the read times out.

        Returns:
            The alarms set on the host
        """

    @abstractmethod
    def audio_output_pause(self, output_id: str) -> None:
        """Pause one audio output of the Volumio instance.

        Args:
            output_id: The identifier of the output to pause
        """

    @abstractmethod
    def audio_output_play(self, output_id: str) -> None:
        """Start one audio output of the Volumio instance.

        Args:
            output_id: The identifier of the output to start
        """

    @property
    @abstractmethod
    def audio_outputs(self) -> AudioOutputs:
        """The audio outputs the Volumio instance can play to.

        Each access emits a fresh event.

        Returns:
            The audio outputs of the host
        """

    @property
    @abstractmethod
    def automatic_update_enabled(self) -> bool:
        """Whether the Volumio instance updates itself.

        Each access emits a fresh event.

        Returns:
            True if the host updates itself, False otherwise
        """

    @property
    @abstractmethod
    def available_timezones(self) -> Timezones:
        """The time zones the Volumio instance can be set to.

        Each access emits a fresh event.

        Returns:
            The names of the time zones
        """

    @property
    @abstractmethod
    def backgrounds(self) -> Backgrounds:
        """The background images of the user interface of the Volumio instance.

        Each access emits a fresh event.

        Returns:
            The background images, and the one in use
        """

    @abstractmethod
    def backup(self) -> dict[str, Any]:
        """Read a backup of the configuration of the Volumio instance.

        Returns:
            The backup, as the host reported it
        """

    @property
    @abstractmethod
    def base_url(self) -> str:
        """The URL of the API endpoint the client talks to."""

    @abstractmethod
    def browse(self, uri: str | None = None, offset: int | None = None) -> BrowseResults:
        """Browse the content the Volumio instance lists at a URI.

        Args:
            uri: The URI to browse, the root when not given
            offset: The number of items to skip in each list, when given
        """

    @property
    @abstractmethod
    def browse_sources(self) -> BrowseSources:
        """The sources the Volumio instance can browse.

        Each access emits a fresh event. These are the roots the URIs of :meth:`browse`
        descend from.

        Returns:
            The browsable sources
        """

    @abstractmethod
    def call_plugin_method(
        self,
        endpoint: str,
        method: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        """Call a method of a plugin of the Volumio instance directly.

        This is the generic plugin call: a Volumio host answers it with nothing, and
        whatever the plugin pushes arrives at the handlers registered with :meth:`on`.

        Args:
            endpoint: The plugin, as ``"category/name"`` (e.g., ``"music_service/mpd"``)
            method: The name of the method to call
            data: The arguments to call it with, when it takes any
        """

    @abstractmethod
    def check_for_update(self) -> None:
        """Ask the Volumio instance to check whether an update is available.

        The host reports what it found through the events its user interface listens
        for, which :meth:`on` can be registered for.
        """

    @abstractmethod
    def check_update_cache(self) -> None:
        """Ask the Volumio instance to check the update information it cached."""

    @abstractmethod
    def clear(self) -> CommandResponse | None:
        """Clear the queue."""

    @abstractmethod
    def close(self) -> None:
        """Release the connection, if the client holds one. Closing twice is harmless."""

    @property
    @abstractmethod
    def collection_statistics(self) -> CollectionStatistics:
        """The statistics of the music collection."""

    @abstractmethod
    def consume(self, value: bool) -> None:
        """Set the consume mode, which drops each track from the queue once played.

        Args:
            value: True to enable the consume mode, False to disable it
        """

    @abstractmethod
    def create_playlist(self, name: str | Playlist) -> None:
        """Create an empty saved playlist.

        Args:
            name: The name to give the playlist, or the playlist itself
        """

    @abstractmethod
    def decrease_volume(self) -> CommandResponse | None:
        """Decrease the playback volume by one step."""

    @abstractmethod
    def delete_background(self, name: str) -> None:
        """Delete a background image of the user interface.

        Args:
            name: The name of the background to delete
        """

    @abstractmethod
    def delete_folder(self, path: str) -> None:
        """Delete a folder of the collection of the Volumio instance.

        Args:
            path: The path of the folder to delete
        """

    @abstractmethod
    def delete_playlist(self, name: str | Playlist) -> None:
        """Delete a saved playlist.

        Args:
            name: The name of the playlist to delete, or the playlist itself
        """

    @abstractmethod
    def delete_share(self, share_id: str) -> None:
        """Unmount a network share of the Volumio instance.

        Args:
            share_id: The identifier of the share, from :attr:`shares`
        """

    @property
    def description(self) -> str:
        """How the adapter names itself in the messages."""
        return self.DESCRIPTION

    @property
    @abstractmethod
    def device_name(self) -> str | None:
        """The name of the Volumio instance; assign it to rename the instance."""

    @device_name.setter
    @abstractmethod
    def device_name(self, value: str) -> None: ...

    @abstractmethod
    def disable_audio_output(self, output_id: str) -> None:
        """Disable one audio output of the Volumio instance.

        Args:
            output_id: The identifier of the output to disable
        """

    @abstractmethod
    def disable_plugin(self, category: str, name: str) -> None:
        """Disable an installed plugin of the Volumio instance.

        Args:
            category: The category the plugin belongs to
            name: The name of the plugin
        """

    @abstractmethod
    def discover_network_shares(self) -> dict[str, Any]:
        """Discover the network shares reachable from the Volumio instance.

        Returns:
            The shares the host found, as it reported them
        """

    @property
    @abstractmethod
    def dsp_config(self) -> UiConfig:
        """The configuration page of the DSP of the Volumio instance.

        Each access emits a fresh event.

        Returns:
            The configuration page of the DSP
        """

    @abstractmethod
    def edit_share(self, share_id: str, **fields: str) -> None:
        """Change a network share mounted by the Volumio instance.

        Args:
            share_id: The identifier of the share, from :attr:`shares`
            **fields: The fields to change (``name``, ``path``, ``fstype``, ``username``,
                ``password``, ``options``)
        """

    @abstractmethod
    def emit(self, event: str, payload: object = None) -> None:
        """Send an event to the Volumio instance, without waiting for anything.

        This is the way to reach the events the client exposes no member for: a Volumio
        host listens for far more of them than the REST API has endpoints.

        Args:
            event: The name of the event to emit
            payload: What the event carries, when it carries anything
        """

    @abstractmethod
    def enable_audio_output(self, output_id: str) -> None:
        """Enable one audio output of the Volumio instance.

        Args:
            output_id: The identifier of the output to enable
        """

    @abstractmethod
    def enable_plugin(self, category: str, name: str) -> None:
        """Enable an installed plugin of the Volumio instance.

        Args:
            category: The category the plugin belongs to
            name: The name of the plugin
        """

    @abstractmethod
    def enqueue_playlist(self, name: str | Playlist) -> None:
        """Append a saved playlist to the queue, without touching the playback.

        Args:
            name: The name of the playlist to append, or the playlist itself
        """

    @property
    @abstractmethod
    def experience_settings(self) -> ExperienceSettings:
        """How many options the user interface of the Volumio instance offers.

        Each access emits a fresh event.

        Returns:
            The experience settings of the host
        """

    @property
    @abstractmethod
    def extended_output_devices(self) -> OutputDevices:
        """The output devices of the Volumio instance, with their details.

        Each access emits a fresh event.

        Returns:
            The output devices, with their details
        """

    @abstractmethod
    def get_album_credits(self, artist: Artist | None, album: Album) -> Story:
        """Get the credits of an album.

        Args:
            artist: The artist of the album, when needed to tell it apart
            album: The album
        """

    @abstractmethod
    def get_playlist_content(self, name: str | Playlist) -> PlaylistContent:
        """Read the tracks of a saved playlist.

        Args:
            name: The name of the playlist to read, or the playlist itself

        Returns:
            The tracks of the playlist
        """

    @abstractmethod
    def get_plugin_config(self, page: str) -> UiConfig:
        """Read the configuration page a plugin of the Volumio instance offers.

        Args:
            page: The plugin, as ``"category/name"`` (e.g., ``"system_controller/system"``)

        Returns:
            The configuration page of the plugin
        """

    @abstractmethod
    def get_share(self, share_id: str) -> Share:
        """Read the details of one network share of the Volumio instance.

        Args:
            share_id: The identifier of the share, from :attr:`shares`

        Returns:
            The details of the share
        """

    @abstractmethod
    def get_story(
        self,
        album: Album | None = None,
        artist: Artist | None = None,
        label: Label | None = None,
        place: Place | None = None,
    ) -> Story:
        """Get the story of an album, artist, label, or place.

        Args:
            album: The album whose story to get
            artist: The artist whose story to get
            label: The label whose story to get
            place: The place whose story to get
        """

    @abstractmethod
    def goto(self, kind: str, value: str) -> BrowseResults:
        """Browse to the artist or the album of the track currently playing.

        Args:
            kind: What to browse to (``"artist"`` or ``"album"``)
            value: The name to browse to

        Returns:
            The content listed for it
        """

    @property
    @abstractmethod
    def has_next(self) -> bool:
        """Whether the current track has a next one in the queue."""

    @property
    @abstractmethod
    def has_previous(self) -> bool:
        """Whether the current track has a previous one in the queue."""

    @property
    def host_configuration(self) -> VolumioHostConfiguration:
        """The host configuration of the wrapped client."""
        return self._wrapped.host_configuration

    @abstractmethod
    def import_service_playlists(self) -> None:
        """Import the playlists the music services of the host expose."""

    @abstractmethod
    def increase_volume(self) -> CommandResponse | None:
        """Increase the playback volume by one step."""

    @property
    @abstractmethod
    def infinity_playback(self) -> InfinityPlayback:
        """The infinity playback setting of the Volumio instance.

        Each access emits a fresh event.

        Returns:
            The infinity playback setting
        """

    @property
    @abstractmethod
    def input_sources(self) -> InputSources:
        """The input sources the Volumio instance exposes.

        Each access emits a fresh event.

        Returns:
            The input sources of the host
        """

    @abstractmethod
    def install_plugin(self, url: str) -> None:
        """Install a plugin on the Volumio instance, from a URL.

        The host reports its progress through the events its user interface listens
        for, which :meth:`on` can be registered for.

        Args:
            url: The URL of the plugin package
        """

    @property
    @abstractmethod
    def installed_plugins(self) -> Plugins:
        """The plugins installed on the Volumio instance.

        Each access emits a fresh event.

        Returns:
            The installed plugins
        """

    @property
    @abstractmethod
    def is_muted(self) -> bool:
        """Whether the playback is muted."""

    @property
    @abstractmethod
    def is_paused(self) -> bool:
        """Whether the playback is paused."""

    @property
    @abstractmethod
    def is_playing(self) -> bool:
        """Whether the playback is running."""

    @property
    @abstractmethod
    def is_stopped(self) -> bool:
        """Whether the playback is stopped."""

    @property
    @abstractmethod
    def languages(self) -> Languages:
        """The languages the user interface of the Volumio instance can be shown in.

        Each access emits a fresh event.

        Returns:
            The languages, and the one in use
        """

    @property
    @abstractmethod
    def last_browse(self) -> BrowseResults:
        """The listing the Volumio instance pushed last, to any of its clients.

        Each access emits a fresh event.

        Returns:
            The last listing the host pushed
        """

    @property
    def logger(self) -> logging.Logger:
        """The logger of the wrapped client."""
        return self._wrapped.logger

    @abstractmethod
    def manage_plugin(self, action: str, category: str, name: str) -> Plugins:
        """Ask the plugin manager of the Volumio instance to act on a plugin.

        Args:
            action: What to do (e.g., ``"enable"``, ``"disable"``, ``"uninstall"``)
            category: The category the plugin belongs to
            name: The name of the plugin

        Returns:
            The installed plugins, as they stand after the action
        """

    @property
    @abstractmethod
    def menu_items(self) -> MenuItems:
        """The menu the Volumio instance offers its user interface.

        Each access emits a fresh event.

        Returns:
            The menu entries
        """

    @abstractmethod
    def modify_plugin_status(self, category: str, name: str, enabled: bool) -> None:
        """Enable or disable an installed plugin in one call.

        Args:
            category: The category the plugin belongs to
            name: The name of the plugin
            enabled: True to enable the plugin, False to disable it
        """

    @abstractmethod
    def move_in_queue(self, source: int, target: int) -> None:
        """Move a track to another position of the queue.

        Args:
            source: The position the track is at (0-based)
            target: The position to move it to (0-based)
        """

    @property
    @abstractmethod
    def multiroom(self) -> Multiroom:
        """The multiroom configuration of the Volumio instance.

        Each access emits a fresh event. The configuration comes from the ``multiroom``
        plugin: a host without it never answers, and the read times out.

        Returns:
            The multiroom configuration of the host
        """

    @property
    @abstractmethod
    def music_sources(self) -> MusicSources:
        """The music source plugins of the Volumio instance.

        Each access emits a fresh event.

        Returns:
            The music sources of the host
        """

    @abstractmethod
    def mute(self) -> CommandResponse | None:
        """Mute the playback."""

    @property
    @abstractmethod
    def network_info(self) -> NetworkInfo:
        """The network interfaces of the Volumio instance.

        Each access emits a fresh event.

        Returns:
            The network interfaces of the host
        """

    @abstractmethod
    def next(self) -> CommandResponse | None:
        """Skip to the next track."""

    @property
    @abstractmethod
    def notifications(self) -> Notifications:
        """The URLs the Volumio instance pushes its notifications to."""

    @abstractmethod
    def off(self, event: str, handler: Callable[[Any], None] | None = None) -> None:
        """Stop calling a handler, or every handler, when an event arrives.

        Args:
            event: The name of the event
            handler: The handler to remove; without one, every handler of the event
                is removed
        """

    @abstractmethod
    def on(self, event: str, handler: Callable[[Any], None]) -> None:
        """Call a handler with the payload of an event whenever the host pushes it.

        A Volumio host pushes some events on its own -- ``pushState`` on every change of
        the playback state, and a few more the moment the connection opens -- and pushes
        others as the answer to a read, in which case the handler is called too.

        The handlers run on the thread the connection reads on, and an exception one
        raises is logged and swallowed, so one failing handler does not stop the others.

        Args:
            event: The name of the event to listen for (e.g., ``"pushState"``)
            handler: The callable receiving the payload of the event
        """

    @abstractmethod
    def open(self) -> None:
        """Acquire the connection, if the client needs one, before the first use."""

    @property
    @abstractmethod
    def output_devices(self) -> OutputDevices:
        """The output devices the Volumio instance can play through.

        Each access emits a fresh event.

        Returns:
            The output devices of the host
        """

    @abstractmethod
    def pause(self) -> CommandResponse | None:
        """Pause the playback."""

    @abstractmethod
    def ping(self) -> str:
        """Ping the Volumio instance, returning its answer."""

    @abstractmethod
    def play(self, position: int | QueueTrack | None = None) -> CommandResponse | None:
        """Start the playback, of a given queue position when given.

        Args:
            position: The queue position, or track, to play
        """

    @abstractmethod
    def play_favourites(self, name: str | None = None) -> None:
        """Play the favourites, optionally starting at one of them.

        Args:
            name: The name of the favourite to start at, the first when not given
        """

    @abstractmethod
    def play_next(self, uri: str, title: str | None = None, album: str | None = None) -> None:
        """Queue an item right after the track currently playing.

        Args:
            uri: The URI to queue
            title: The title to show for it, when known
            album: The album to show for it, when known
        """

    @abstractmethod
    def play_playlist(self, name: str | Playlist) -> CommandResponse | None:
        """Play a playlist.

        Args:
            name: The name of the playlist, or the playlist itself
        """

    @abstractmethod
    def play_radio_favourites(self) -> None:
        """Play the radio favourites."""

    @abstractmethod
    def play_volatile(self, position: int) -> None:
        """Start a volatile source (e.g., Spotify Connect) at a position.

        Args:
            position: The position to start at (0-based)
        """

    @property
    @abstractmethod
    def playlists(self) -> Playlists:
        """The playlists of the Volumio instance."""

    @property
    @abstractmethod
    def power_modes(self) -> PowerModes:
        """The ways the Volumio instance can be powered down.

        Each access emits a fresh event. A host that reports no standby mode answers
        :meth:`standby` by powering off instead.

        Returns:
            The power modes of the host
        """

    @abstractmethod
    def previous(self) -> CommandResponse | None:
        """Skip to the previous track."""

    @property
    @abstractmethod
    def privacy_settings(self) -> PrivacySettings:
        """The privacy settings of the Volumio instance.

        Each access emits a fresh event.

        Returns:
            The privacy settings of the host
        """

    @property
    @abstractmethod
    def queue(self) -> Queue:
        """The queue of the Volumio instance."""

    @property
    @abstractmethod
    def queue_status(self) -> dict[str, Any]:
        """The current track, with its position and the neighbor flags of the queue."""

    @abstractmethod
    def randomize(self, value: bool | None = None) -> CommandResponse | None:
        """Set, or toggle, the random mode.

        Args:
            value: The mode to set, toggled when not given
        """

    @abstractmethod
    def reboot(self) -> None:
        """Restart the Volumio host.

        The host drops the connection as it goes down; reconnect once it is back.
        """

    @abstractmethod
    def regenerate_thumbnails(self) -> None:
        """Rebuild the thumbnails of the album art of the collection."""

    @abstractmethod
    def register_notification(self, url: str | Notification) -> SuccessResponse:
        """Register a URL the Volumio instance pushes its notifications to.

        Args:
            url: The URL to register
        """

    @abstractmethod
    def remove_from_favourites(self, uri: str, service: str | None = None) -> None:
        """Remove an item from the favourites.

        Args:
            uri: The URI of the item to remove
            service: The service the URI belongs to, derived from it when not given
        """

    @abstractmethod
    def remove_from_playlist(
        self,
        name: str | Playlist,
        uri: str,
        service: str | None = None,
    ) -> None:
        """Remove an item from a saved playlist.

        Args:
            name: The name of the playlist, or the playlist itself
            uri: The URI of the item to remove
            service: The service the URI belongs to, derived from it when not given
        """

    @abstractmethod
    def remove_from_queue(self, position: int) -> None:
        """Remove a track from the queue.

        Args:
            position: The position of the track to remove (0-based)
        """

    @abstractmethod
    def remove_radio_favourite(self, uri: str, name: str | None = None) -> None:
        """Remove a web radio from the radio favourites.

        Args:
            uri: The URL the web radio streams from
            name: The name it is a favourite under, when known
        """

    @abstractmethod
    def remove_web_radio(self, name: str) -> None:
        """Delete a web radio of the user.

        Args:
            name: The name the web radio was saved under
        """

    @abstractmethod
    def repeat(self, value: bool | None = None) -> CommandResponse | None:
        """Set, or toggle, the repeat mode.

        Args:
            value: The mode to set, toggled when not given
        """

    @abstractmethod
    def replace_queue_and_play(self, uri: str, index: int | None = None) -> CommandResponse | None:
        """Replace the queue with the content of a URI and play it.

        Args:
            uri: The URI whose content replaces the queue
            index: The position to start playing from, when given
        """

    @abstractmethod
    def replace_queue_with_cue_track(
        self,
        uri: str,
        number: int,
        service: str | None = None,
    ) -> None:
        """Replace the queue with one track of a cue sheet and play it.

        Args:
            uri: The URI of the cue sheet
            number: The position of the track inside the cue sheet
            service: The service the URI belongs to, derived from it when not given
        """

    @abstractmethod
    def request(
        self,
        event: str,
        response_event: str | None = None,
        payload: object = None,
        timeout: float | None = None,
    ) -> object:
        """Emit an event and return the payload of the answer the host pushes back.

        This is the way to read through the events the client exposes no member for.

        Args:
            event: The event to emit
            response_event: The event carrying the answer; needed for the events the
                client does not already know the answer of
            payload: What the emitted event carries, when it carries anything
            timeout: The number of seconds to wait, the timeout of the client when
                not given

        Returns:
            What the answer carried
        """

    @abstractmethod
    def rescan_library(self) -> None:
        """Rescan the music collection of the Volumio instance from scratch.

        This is the slower of the two: :meth:`update_library` only looks for changes.
        """

    @abstractmethod
    def restore_backup(self, backup: dict[str, Any]) -> None:
        """Restore a backup of the configuration of the Volumio instance.

        Args:
            backup: The backup to restore, as :meth:`backup` reported it
        """

    @abstractmethod
    def restore_config(self) -> None:
        """Restore the configuration of the plugins of the Volumio instance."""

    @abstractmethod
    def safe_remove_drive(self, name: str) -> None:
        """Unmount a USB drive of the Volumio instance before it is unplugged.

        Args:
            name: The name of the drive, from :attr:`usb_drives`
        """

    @abstractmethod
    def save_queue_as_playlist(self, name: str | Playlist) -> None:
        """Save the current queue as a saved playlist.

        Args:
            name: The name to save the queue under, or the playlist to overwrite
        """

    @abstractmethod
    def save_wireless_settings(self, ssid: str, password: str = '') -> None:
        """Join a wireless network with the Volumio instance.

        Args:
            ssid: The name of the network
            password: The password of the network, empty for an open one
        """

    @abstractmethod
    def search(self, query: str) -> SearchResults:
        """Search the sources of the Volumio instance.

        Args:
            query: The text to search for
        """

    @property
    @abstractmethod
    def seek(self) -> int:
        """The playback position, in seconds; assign it to seek."""

    @seek.setter
    @abstractmethod
    def seek(self, value: int) -> None: ...

    @abstractmethod
    def seek_backward(self) -> CommandResponse | None:
        """Seek backward by one step."""

    @abstractmethod
    def seek_forward(self) -> CommandResponse | None:
        """Seek forward by one step."""

    @abstractmethod
    def set_alarms(self, alarms: list[Alarm]) -> None:
        """Replace the whole set of alarms of the Volumio instance.

        The Volumio API takes the alarms as a set rather than one at a time, so this
        replaces every alarm the host holds: read :attr:`alarms` first and send back the
        list you want to keep.

        Args:
            alarms: The alarms to keep
        """

    @abstractmethod
    def set_as_multiroom_client(self, server: str) -> None:
        """Make the Volumio instance a multiroom client of another host.

        Args:
            server: The address of the host to follow
        """

    @abstractmethod
    def set_as_multiroom_server(self) -> None:
        """Make the Volumio instance a multiroom server."""

    @abstractmethod
    def set_as_multiroom_single(self) -> None:
        """Take the Volumio instance out of multiroom."""

    @abstractmethod
    def set_audio_output_volume(self, output_id: str, volume: int) -> None:
        """Set the volume of one audio output of the Volumio instance.

        This is the volume of one output; :attr:`volume` is the volume of the host.

        Args:
            output_id: The identifier of the output
            volume: The volume level, an integer between 0 and 100 (inclusive)
        """

    @abstractmethod
    def set_background(self, name: str, path: str | None = None) -> None:
        """Choose the background image of the user interface.

        Args:
            name: The name of the background, from :attr:`backgrounds`
            path: The path of its image, when the host needs it named too
        """

    @abstractmethod
    def set_experience_settings(self, advanced: bool) -> None:
        """Choose how many options the user interface of the Volumio instance offers.

        Args:
            advanced: True for the full set of options, False for the simplified one
                (the host stores the flag itself, and reports it back wrapped in its label)
        """

    @abstractmethod
    def set_infinity_playback(self, enabled: bool) -> None:
        """Turn infinity playback on or off.

        Args:
            enabled: True to enable infinity playback, False to disable it
        """

    @abstractmethod
    def set_language(self, code: str, language: str | None = None) -> None:
        """Choose the language of the user interface of the Volumio instance.

        Args:
            code: The code of the language (e.g., ``"en"``), from :attr:`languages`
            language: The name of the language, when the host needs it named too
        """

    @abstractmethod
    def set_multiroom(self, settings: dict[str, Any]) -> Multiroom:
        """Change the multiroom configuration of the Volumio instance.

        Args:
            settings: The configuration to apply

        Returns:
            The configuration as it stands afterwards
        """

    @abstractmethod
    def set_music_source_enabled(self, name: str, enabled: bool) -> None:
        """Enable or disable one music source of the Volumio instance.

        Args:
            name: The name of the source, from :attr:`music_sources`
            enabled: True to enable the source, False to disable it
        """

    @abstractmethod
    def set_output_device(self, device_id: str, mixer: str | None = None) -> None:
        """Choose the output device the Volumio instance plays through.

        Args:
            device_id: The identifier of the device, from :attr:`output_devices`
            mixer: The mixer to drive its volume with, left to the host when not given
        """

    @abstractmethod
    def set_sleep_timer(self, delay: timedelta | None) -> None:
        """Arm or disarm the sleep timer of the Volumio instance.

        The Volumio API reads the time of a sleep timer as a delay from now, not as a
        clock time, so ``timedelta(minutes=30)`` stops the host in half an hour.

        The timer comes from the ``alarm-clock`` plugin, and so does :attr:`sleep_timer`.

        Args:
            delay: How long from now the host should stop, or None to disarm the timer
        """

    @property
    @abstractmethod
    def shares(self) -> Shares:
        """The network shares mounted by the Volumio instance.

        Each access emits a fresh event.

        Returns:
            The mounted shares
        """

    @abstractmethod
    def shutdown(self) -> None:
        """Power the Volumio host off.

        The host drops the connection as it goes down, and does not come back on its
        own.
        """

    @property
    @abstractmethod
    def sleep_timer(self) -> SleepTimer:
        """The sleep timer of the Volumio instance.

        Each access emits a fresh event. Read the remaining delay off
        :attr:`SleepTimer.delay`, which parses it as the duration it is.

        Returns:
            The sleep timer of the host
        """

    @abstractmethod
    def standby(self) -> None:
        """Put the Volumio host on standby.

        A host whose :attr:`power_modes` report no standby mode powers off instead.
        """

    @property
    @abstractmethod
    def state(self) -> PlayerState:
        """The playback state of the Volumio instance."""

    @abstractmethod
    def stop(self) -> CommandResponse | None:
        """Stop the playback."""

    @abstractmethod
    def super_search(self, query: str) -> SearchResults:
        """Search every source of the Volumio instance at once.

        Unlike :meth:`search`, which the sources answer one by one, this asks the host
        to search them together.

        The search is served by the ``metavolumio`` plugin (Volumio Premium), as the
        story queries of the REST API clients are: a host without it answers an empty
        result rather than an error.

        Args:
            query: The text to search for

        Returns:
            The results of the search
        """

    @property
    @abstractmethod
    def system_info(self) -> SystemInfo:
        """The system information of the Volumio instance."""

    @property
    @abstractmethod
    def system_version(self) -> SystemVersion:
        """The system version of the Volumio instance."""

    @property
    @abstractmethod
    def timezone(self) -> str:
        """The time zone of the Volumio instance; assign it to move the instance to another."""

    @timezone.setter
    @abstractmethod
    def timezone(self, value: str) -> None: ...

    @abstractmethod
    def toggle(self) -> CommandResponse | None:
        """Toggle between playing and pausing."""

    @property
    @abstractmethod
    def ui_settings(self) -> UiSettings:
        """The look of the user interface of the Volumio instance.

        Each access emits a fresh event.

        Returns:
            The colour, language, and theme of the interface
        """

    @abstractmethod
    def uninstall_plugin(self, category: str, name: str) -> None:
        """Remove an installed plugin from the Volumio instance.

        Args:
            category: The category the plugin belongs to
            name: The name of the plugin
        """

    @abstractmethod
    def unmute(self) -> CommandResponse | None:
        """Unmute the playback."""

    @abstractmethod
    def unregister_notification(self, url: str | Notification) -> SuccessResponse:
        """Unregister a URL the Volumio instance pushes its notifications to.

        Args:
            url: The URL to unregister
        """

    @abstractmethod
    def update(self, ignore_integrity_check: bool = False) -> None:
        """Install the update the Volumio instance found.

        The host reports its progress through the events its user interface listens
        for, and restarts when it is done.

        Args:
            ignore_integrity_check: True to install even when the check fails
        """

    @abstractmethod
    def update_all_metadata(self) -> None:
        """Refresh the metadata of the whole collection of the Volumio instance."""

    @abstractmethod
    def update_library(self, uri: str | None = None) -> None:
        """Update the music collection of the Volumio instance, looking for changes.

        Args:
            uri: The URI to update, the whole collection when not given
        """

    @abstractmethod
    def update_plugin(self, category: str, name: str) -> None:
        """Update an installed plugin of the Volumio instance.

        Args:
            category: The category the plugin belongs to
            name: The name of the plugin
        """

    @abstractmethod
    def update_service_tracklist(self, service: str) -> None:
        """Refresh the tracks one music service of the Volumio instance offers.

        Args:
            service: The name of the service to refresh
        """

    @property
    @abstractmethod
    def updater_channel(self) -> UpdaterChannel:
        """The update channel the Volumio instance follows; assign it to change the channel."""

    @updater_channel.setter
    @abstractmethod
    def updater_channel(self, value: str) -> None: ...

    @property
    @abstractmethod
    def usb_drives(self) -> UsbDrives:
        """The USB drives attached to the Volumio instance.

        Each access emits a fresh event.

        Returns:
            The attached drives
        """

    @property
    @abstractmethod
    def volume(self) -> int:
        """The playback volume, from 0 to 100; assign it to set the volume."""

    @volume.setter
    @abstractmethod
    def volume(self, value: int) -> None: ...

    @property
    @abstractmethod
    def wireless_networks(self) -> WirelessNetworks:
        """The wireless networks the Volumio instance can see, scanning for them.

        Each access emits a fresh event, and a scan takes a moment: a host with no
        wireless interface never answers, and the read times out. See
        :attr:`wireless_networks_cache` for the networks it saw last.

        Returns:
            The wireless networks the host can see
        """

    @property
    @abstractmethod
    def wireless_networks_cache(self) -> WirelessNetworks:
        """The wireless networks the Volumio instance saw last, without scanning again.

        Each access emits a fresh event.

        Returns:
            The wireless networks the host saw last
        """

    @abstractmethod
    def write_multiroom(self, settings: dict[str, Any]) -> None:
        """Write the multiroom configuration of the Volumio instance.

        Args:
            settings: The configuration to write
        """

    @property
    @abstractmethod
    def zones(self) -> Zones:
        """The multiroom zones of the Volumio instance."""

    def __enter__(self) -> Self:
        """Open the client, and return it."""
        self.open()
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        """Close the client."""
        self.close()


class _Fallback:
    """The client of the other API an adapter serves the operations its own API lacks with.

    Without a factory there is no fallback: the operations raise. With one, the client
    is built and opened on the first operation, kept for the following ones, and
    closed with the adapter owning it.
    """

    API = ""
    """The API of the client falling back to, as the messages name it."""

    OWNER_API = ""
    """The API of the adapter falling back, as the messages name it."""

    REMEDIES = ""
    """The options offering the operations, as the error message lists them."""

    def __init__(self, owner: APIClient, factory: Callable[[], APIClient] | None) -> None:
        """Initialize the fallback.

        Args:
            owner: The adapter falling back
            factory: The function building the client of the other API, or None to
                forbid the fallback
        """
        self._owner = owner
        self._factory = factory
        self._client: APIClient | None = None

    def client(self, operation: str) -> APIClient:
        """Return the client of the other API serving an operation.

        Args:
            operation: How the messages name the operation (e.g., "the story queries")

        Returns:
            The opened client

        Raises:
            UnsupportedOperationError: If the fallback is not allowed
        """
        if self._factory is None:
            raise UnsupportedOperationError(
                f"The {self._owner.description} does not offer {operation}: use {self.REMEDIES}"
            )
        if self._client is None:
            self._owner.logger.debug(f"Opening the {self.API} API client to fall back to...")
            client = self._factory()
            client.open()
            self._client = client
            self._owner.logger.debug(f"Opening the {self.API} API client to fall back to... done")
        self._owner.logger.warning(
            f"Falling back to the {self.API} API client for {operation} "
            f"(the {self.OWNER_API} API does not offer them)"
        )
        return self._client

    def close(self) -> None:
        """Close the client of the other API, if one was built."""
        if self._client is not None:
            client, self._client = self._client, None
            client.close()


class _RESTFallback(_Fallback):
    """The REST API client a WebSocket adapter serves the REST-only operations with."""

    API = "REST"
    OWNER_API = "WebSocket"
    REMEDIES = (
        "--api-client synchronous_rest or asynchronous_rest, or --allow-fallback-to-rest-api"
    )


class _WebSocketFallback(_Fallback):
    """The WebSocket API client a REST adapter serves the WebSocket-only operations with."""

    API = "WebSocket"
    OWNER_API = "REST"
    REMEDIES = (
        "--api-client synchronous_websocket or asynchronous_websocket, "
        "or --allow-fallback-to-websocket-api"
    )


class RESTAPIClient(APIClient):
    """The members the REST API lacks, as the two REST adapters serve them.

    Each goes through the WebSocket API client of the fallback, when the CLI allows it,
    and raises :class:`UnsupportedOperationError` otherwise. The concrete REST adapters
    build the fallback from the factory they are given, and close it with themselves.
    """

    _fallback: _WebSocketFallback

    def add_and_play(self, uri: str) -> None:
        return self._fallback.client(QUEUE_OPERATION).add_and_play(uri)

    def add_cue_track(self, uri: str, number: int, service: str | None = None) -> None:
        return self._fallback.client(QUEUE_OPERATION).add_cue_track(uri, number, service)

    def add_radio_favourite(self, uri: str) -> None:
        return self._fallback.client(FAVOURITE_OPERATION).add_radio_favourite(uri)

    def add_share(self, name: str, path: str, fstype: str, **options: str) -> None:
        return self._fallback.client(SHARE_OPERATION).add_share(name, path, fstype, **options)

    def add_to_favourites(
        self,
        uri: str,
        title: str | None = None,
        service: str | None = None,
        albumart: str | None = None,
    ) -> None:
        return self._fallback.client(FAVOURITE_OPERATION).add_to_favourites(
            uri, title, service, albumart
        )

    def add_to_playlist(self, name: str | Playlist, uri: str, service: str | None = None) -> None:
        return self._fallback.client(PLAYLIST_OPERATION).add_to_playlist(name, uri, service)

    def add_uids_to_queue(self, uids: list[str]) -> None:
        return self._fallback.client(QUEUE_OPERATION).add_uids_to_queue(uids)

    def add_web_radio(self, name: str, uri: str) -> None:
        return self._fallback.client(FAVOURITE_OPERATION).add_web_radio(name, uri)

    @property
    def alarms(self) -> Alarms:
        return self._fallback.client(ALARM_OPERATION).alarms

    def audio_output_pause(self, output_id: str) -> None:
        return self._fallback.client(AUDIO_OPERATION).audio_output_pause(output_id)

    def audio_output_play(self, output_id: str) -> None:
        return self._fallback.client(AUDIO_OPERATION).audio_output_play(output_id)

    @property
    def audio_outputs(self) -> AudioOutputs:
        return self._fallback.client(AUDIO_OPERATION).audio_outputs

    @property
    def automatic_update_enabled(self) -> bool:
        return self._fallback.client(UPDATE_OPERATION).automatic_update_enabled

    @property
    def available_timezones(self) -> Timezones:
        return self._fallback.client(SYSTEM_OPERATION).available_timezones

    @property
    def backgrounds(self) -> Backgrounds:
        return self._fallback.client(UI_OPERATION).backgrounds

    def backup(self) -> dict[str, Any]:
        return self._fallback.client(SYSTEM_OPERATION).backup()

    @property
    def browse_sources(self) -> BrowseSources:
        return self._fallback.client(COLLECTION_OPERATION).browse_sources

    def call_plugin_method(
        self,
        endpoint: str,
        method: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        return self._fallback.client(PLUGIN_OPERATION).call_plugin_method(endpoint, method, data)

    def check_for_update(self) -> None:
        return self._fallback.client(UPDATE_OPERATION).check_for_update()

    def check_update_cache(self) -> None:
        return self._fallback.client(UPDATE_OPERATION).check_update_cache()

    def consume(self, value: bool) -> None:
        return self._fallback.client(QUEUE_OPERATION).consume(value)

    def create_playlist(self, name: str | Playlist) -> None:
        return self._fallback.client(PLAYLIST_OPERATION).create_playlist(name)

    def delete_background(self, name: str) -> None:
        return self._fallback.client(UI_OPERATION).delete_background(name)

    def delete_folder(self, path: str) -> None:
        return self._fallback.client(COLLECTION_OPERATION).delete_folder(path)

    def delete_playlist(self, name: str | Playlist) -> None:
        return self._fallback.client(PLAYLIST_OPERATION).delete_playlist(name)

    def delete_share(self, share_id: str) -> None:
        return self._fallback.client(SHARE_OPERATION).delete_share(share_id)

    @property
    def device_name(self) -> str | None:
        return self._fallback.client(SYSTEM_OPERATION).device_name

    @device_name.setter
    def device_name(self, value: str) -> None:
        self._fallback.client(SYSTEM_OPERATION).device_name = value

    def disable_audio_output(self, output_id: str) -> None:
        return self._fallback.client(AUDIO_OPERATION).disable_audio_output(output_id)

    def disable_plugin(self, category: str, name: str) -> None:
        return self._fallback.client(PLUGIN_OPERATION).disable_plugin(category, name)

    def discover_network_shares(self) -> dict[str, Any]:
        return self._fallback.client(SHARE_OPERATION).discover_network_shares()

    @property
    def dsp_config(self) -> UiConfig:
        return self._fallback.client(AUDIO_OPERATION).dsp_config

    def edit_share(self, share_id: str, **fields: str) -> None:
        return self._fallback.client(SHARE_OPERATION).edit_share(share_id, **fields)

    def emit(self, event: str, payload: object = None) -> None:
        return self._fallback.client(EVENT_OPERATION).emit(event, payload)

    def enable_audio_output(self, output_id: str) -> None:
        return self._fallback.client(AUDIO_OPERATION).enable_audio_output(output_id)

    def enable_plugin(self, category: str, name: str) -> None:
        return self._fallback.client(PLUGIN_OPERATION).enable_plugin(category, name)

    def enqueue_playlist(self, name: str | Playlist) -> None:
        return self._fallback.client(PLAYLIST_OPERATION).enqueue_playlist(name)

    @property
    def experience_settings(self) -> ExperienceSettings:
        return self._fallback.client(UI_OPERATION).experience_settings

    @property
    def extended_output_devices(self) -> OutputDevices:
        return self._fallback.client(AUDIO_OPERATION).extended_output_devices

    def get_playlist_content(self, name: str | Playlist) -> PlaylistContent:
        return self._fallback.client(PLAYLIST_OPERATION).get_playlist_content(name)

    def get_plugin_config(self, page: str) -> UiConfig:
        return self._fallback.client(PLUGIN_OPERATION).get_plugin_config(page)

    def get_share(self, share_id: str) -> Share:
        return self._fallback.client(SHARE_OPERATION).get_share(share_id)

    def goto(self, kind: str, value: str) -> BrowseResults:
        return self._fallback.client(COLLECTION_OPERATION).goto(kind, value)

    def import_service_playlists(self) -> None:
        return self._fallback.client(PLAYLIST_OPERATION).import_service_playlists()

    @property
    def infinity_playback(self) -> InfinityPlayback:
        return self._fallback.client(PLAYBACK_OPERATION).infinity_playback

    @property
    def input_sources(self) -> InputSources:
        return self._fallback.client(AUDIO_OPERATION).input_sources

    def install_plugin(self, url: str) -> None:
        return self._fallback.client(PLUGIN_OPERATION).install_plugin(url)

    @property
    def installed_plugins(self) -> Plugins:
        return self._fallback.client(PLUGIN_OPERATION).installed_plugins

    @property
    def languages(self) -> Languages:
        return self._fallback.client(UI_OPERATION).languages

    @property
    def last_browse(self) -> BrowseResults:
        return self._fallback.client(COLLECTION_OPERATION).last_browse

    def manage_plugin(self, action: str, category: str, name: str) -> Plugins:
        return self._fallback.client(PLUGIN_OPERATION).manage_plugin(action, category, name)

    @property
    def menu_items(self) -> MenuItems:
        return self._fallback.client(UI_OPERATION).menu_items

    def modify_plugin_status(self, category: str, name: str, enabled: bool) -> None:
        return self._fallback.client(PLUGIN_OPERATION).modify_plugin_status(category, name, enabled)

    def move_in_queue(self, source: int, target: int) -> None:
        return self._fallback.client(QUEUE_OPERATION).move_in_queue(source, target)

    @property
    def multiroom(self) -> Multiroom:
        return self._fallback.client(MULTIROOM_OPERATION).multiroom

    @property
    def music_sources(self) -> MusicSources:
        return self._fallback.client(COLLECTION_OPERATION).music_sources

    @property
    def network_info(self) -> NetworkInfo:
        return self._fallback.client(NETWORK_OPERATION).network_info

    def off(self, event: str, handler: Callable[[Any], None] | None = None) -> None:
        return self._fallback.client(EVENT_OPERATION).off(event, handler)

    def on(self, event: str, handler: Callable[[Any], None]) -> None:
        return self._fallback.client(EVENT_OPERATION).on(event, handler)

    @property
    def output_devices(self) -> OutputDevices:
        return self._fallback.client(AUDIO_OPERATION).output_devices

    def play_favourites(self, name: str | None = None) -> None:
        return self._fallback.client(FAVOURITE_OPERATION).play_favourites(name)

    def play_next(self, uri: str, title: str | None = None, album: str | None = None) -> None:
        return self._fallback.client(QUEUE_OPERATION).play_next(uri, title, album)

    def play_radio_favourites(self) -> None:
        return self._fallback.client(FAVOURITE_OPERATION).play_radio_favourites()

    def play_volatile(self, position: int) -> None:
        return self._fallback.client(PLAYBACK_OPERATION).play_volatile(position)

    @property
    def power_modes(self) -> PowerModes:
        return self._fallback.client(SYSTEM_OPERATION).power_modes

    @property
    def privacy_settings(self) -> PrivacySettings:
        return self._fallback.client(UI_OPERATION).privacy_settings

    def reboot(self) -> None:
        return self._fallback.client(SYSTEM_OPERATION).reboot()

    def regenerate_thumbnails(self) -> None:
        return self._fallback.client(COLLECTION_OPERATION).regenerate_thumbnails()

    def remove_from_favourites(self, uri: str, service: str | None = None) -> None:
        return self._fallback.client(FAVOURITE_OPERATION).remove_from_favourites(uri, service)

    def remove_from_playlist(
        self,
        name: str | Playlist,
        uri: str,
        service: str | None = None,
    ) -> None:
        return self._fallback.client(PLAYLIST_OPERATION).remove_from_playlist(name, uri, service)

    def remove_from_queue(self, position: int) -> None:
        return self._fallback.client(QUEUE_OPERATION).remove_from_queue(position)

    def remove_radio_favourite(self, uri: str, name: str | None = None) -> None:
        return self._fallback.client(FAVOURITE_OPERATION).remove_radio_favourite(uri, name)

    def remove_web_radio(self, name: str) -> None:
        return self._fallback.client(FAVOURITE_OPERATION).remove_web_radio(name)

    def replace_queue_with_cue_track(
        self,
        uri: str,
        number: int,
        service: str | None = None,
    ) -> None:
        return self._fallback.client(QUEUE_OPERATION).replace_queue_with_cue_track(
            uri, number, service
        )

    def request(
        self,
        event: str,
        response_event: str | None = None,
        payload: object = None,
        timeout: float | None = None,
    ) -> object:
        return self._fallback.client(EVENT_OPERATION).request(
            event, response_event, payload, timeout
        )

    def rescan_library(self) -> None:
        return self._fallback.client(COLLECTION_OPERATION).rescan_library()

    def restore_backup(self, backup: dict[str, Any]) -> None:
        return self._fallback.client(SYSTEM_OPERATION).restore_backup(backup)

    def restore_config(self) -> None:
        return self._fallback.client(SYSTEM_OPERATION).restore_config()

    def safe_remove_drive(self, name: str) -> None:
        return self._fallback.client(SHARE_OPERATION).safe_remove_drive(name)

    def save_queue_as_playlist(self, name: str | Playlist) -> None:
        return self._fallback.client(QUEUE_OPERATION).save_queue_as_playlist(name)

    def save_wireless_settings(self, ssid: str, password: str = '') -> None:
        return self._fallback.client(NETWORK_OPERATION).save_wireless_settings(ssid, password)

    def set_alarms(self, alarms: list[Alarm]) -> None:
        return self._fallback.client(ALARM_OPERATION).set_alarms(alarms)

    def set_as_multiroom_client(self, server: str) -> None:
        return self._fallback.client(MULTIROOM_OPERATION).set_as_multiroom_client(server)

    def set_as_multiroom_server(self) -> None:
        return self._fallback.client(MULTIROOM_OPERATION).set_as_multiroom_server()

    def set_as_multiroom_single(self) -> None:
        return self._fallback.client(MULTIROOM_OPERATION).set_as_multiroom_single()

    def set_audio_output_volume(self, output_id: str, volume: int) -> None:
        return self._fallback.client(AUDIO_OPERATION).set_audio_output_volume(output_id, volume)

    def set_background(self, name: str, path: str | None = None) -> None:
        return self._fallback.client(UI_OPERATION).set_background(name, path)

    def set_experience_settings(self, advanced: bool) -> None:
        return self._fallback.client(UI_OPERATION).set_experience_settings(advanced)

    def set_infinity_playback(self, enabled: bool) -> None:
        return self._fallback.client(PLAYBACK_OPERATION).set_infinity_playback(enabled)

    def set_language(self, code: str, language: str | None = None) -> None:
        return self._fallback.client(UI_OPERATION).set_language(code, language)

    def set_multiroom(self, settings: dict[str, Any]) -> Multiroom:
        return self._fallback.client(MULTIROOM_OPERATION).set_multiroom(settings)

    def set_music_source_enabled(self, name: str, enabled: bool) -> None:
        return self._fallback.client(COLLECTION_OPERATION).set_music_source_enabled(name, enabled)

    def set_output_device(self, device_id: str, mixer: str | None = None) -> None:
        return self._fallback.client(AUDIO_OPERATION).set_output_device(device_id, mixer)

    def set_sleep_timer(self, delay: timedelta | None) -> None:
        return self._fallback.client(ALARM_OPERATION).set_sleep_timer(delay)

    @property
    def shares(self) -> Shares:
        return self._fallback.client(SHARE_OPERATION).shares

    def shutdown(self) -> None:
        return self._fallback.client(SYSTEM_OPERATION).shutdown()

    @property
    def sleep_timer(self) -> SleepTimer:
        return self._fallback.client(ALARM_OPERATION).sleep_timer

    def standby(self) -> None:
        return self._fallback.client(SYSTEM_OPERATION).standby()

    def super_search(self, query: str) -> SearchResults:
        return self._fallback.client(COLLECTION_OPERATION).super_search(query)

    @property
    def timezone(self) -> str:
        return self._fallback.client(SYSTEM_OPERATION).timezone

    @timezone.setter
    def timezone(self, value: str) -> None:
        self._fallback.client(SYSTEM_OPERATION).timezone = value

    @property
    def ui_settings(self) -> UiSettings:
        return self._fallback.client(UI_OPERATION).ui_settings

    def uninstall_plugin(self, category: str, name: str) -> None:
        return self._fallback.client(PLUGIN_OPERATION).uninstall_plugin(category, name)

    def update(self, ignore_integrity_check: bool = False) -> None:
        return self._fallback.client(UPDATE_OPERATION).update(ignore_integrity_check)

    def update_all_metadata(self) -> None:
        return self._fallback.client(COLLECTION_OPERATION).update_all_metadata()

    def update_library(self, uri: str | None = None) -> None:
        return self._fallback.client(COLLECTION_OPERATION).update_library(uri)

    def update_plugin(self, category: str, name: str) -> None:
        return self._fallback.client(PLUGIN_OPERATION).update_plugin(category, name)

    def update_service_tracklist(self, service: str) -> None:
        return self._fallback.client(COLLECTION_OPERATION).update_service_tracklist(service)

    @property
    def updater_channel(self) -> UpdaterChannel:
        return self._fallback.client(UPDATE_OPERATION).updater_channel

    @updater_channel.setter
    def updater_channel(self, value: str) -> None:
        self._fallback.client(UPDATE_OPERATION).updater_channel = value

    @property
    def usb_drives(self) -> UsbDrives:
        return self._fallback.client(SHARE_OPERATION).usb_drives

    @property
    def wireless_networks(self) -> WirelessNetworks:
        return self._fallback.client(NETWORK_OPERATION).wireless_networks

    @property
    def wireless_networks_cache(self) -> WirelessNetworks:
        return self._fallback.client(NETWORK_OPERATION).wireless_networks_cache

    def write_multiroom(self, settings: dict[str, Any]) -> None:
        return self._fallback.client(MULTIROOM_OPERATION).write_multiroom(settings)


class SyncAPIClient[C: VolumioRESTAPIClient | VolumioWebSocketClient](APIClient):
    """The adapter of a synchronous client, forwarding the members the two share.

    The members one of the two clients lacks, or defines differently, are left to the
    concrete adapters.
    """

    def __init__(self, client: C) -> None:
        """Initialize the adapter.

        Args:
            client: The synchronous client the adapter wraps
        """
        super().__init__(client)
        self._client = client

    def add_to_queue(self, uri: str) -> CommandResponse | None:
        return self._client.add_to_queue(uri)

    def clear(self) -> CommandResponse | None:
        return self._client.clear()

    @property
    def collection_statistics(self) -> CollectionStatistics:
        return self._client.collection_statistics

    def decrease_volume(self) -> CommandResponse | None:
        return self._client.decrease_volume()

    @property
    def has_next(self) -> bool:
        return self._client.has_next

    @property
    def has_previous(self) -> bool:
        return self._client.has_previous

    def increase_volume(self) -> CommandResponse | None:
        return self._client.increase_volume()

    @property
    def is_muted(self) -> bool:
        return self._client.is_muted

    @property
    def is_paused(self) -> bool:
        return self._client.is_paused

    @property
    def is_playing(self) -> bool:
        return self._client.is_playing

    @property
    def is_stopped(self) -> bool:
        return self._client.is_stopped

    def mute(self) -> CommandResponse | None:
        return self._client.mute()

    def next(self) -> CommandResponse | None:
        return self._client.next()

    def pause(self) -> CommandResponse | None:
        return self._client.pause()

    def ping(self) -> str:
        return self._client.ping()

    def play(self, position: int | QueueTrack | None = None) -> CommandResponse | None:
        return self._client.play(position)

    def play_playlist(self, name: str | Playlist) -> CommandResponse | None:
        return self._client.play_playlist(name)

    @property
    def playlists(self) -> Playlists:
        return self._client.playlists

    def previous(self) -> CommandResponse | None:
        return self._client.previous()

    @property
    def queue(self) -> Queue:
        return self._client.queue

    @property
    def queue_status(self) -> dict[str, Any]:
        return self._client.queue_status

    def randomize(self, value: bool | None = None) -> CommandResponse | None:
        return self._client.randomize(value)

    def repeat(self, value: bool | None = None) -> CommandResponse | None:
        return self._client.repeat(value)

    def replace_queue_and_play(self, uri: str, index: int | None = None) -> CommandResponse | None:
        return self._client.replace_queue_and_play(uri, index)

    def search(self, query: str) -> SearchResults:
        return self._client.search(query)

    @property
    def seek(self) -> int:
        return self._client.seek

    @seek.setter
    def seek(self, value: int) -> None:
        self._client.seek = value

    def seek_backward(self) -> CommandResponse | None:
        return self._client.seek_backward()

    def seek_forward(self) -> CommandResponse | None:
        return self._client.seek_forward()

    @property
    def state(self) -> PlayerState:
        return self._client.state

    def stop(self) -> CommandResponse | None:
        return self._client.stop()

    @property
    def system_info(self) -> SystemInfo:
        return self._client.system_info

    @property
    def system_version(self) -> SystemVersion:
        return self._client.system_version

    def toggle(self) -> CommandResponse | None:
        return self._client.toggle()

    def unmute(self) -> CommandResponse | None:
        return self._client.unmute()

    @property
    def volume(self) -> int:
        return self._client.volume

    @volume.setter
    def volume(self, value: int) -> None:
        self._client.volume = value

    @property
    def zones(self) -> Zones:
        return self._client.zones


class SyncRESTAPIClient(RESTAPIClient, SyncAPIClient[VolumioRESTAPIClient]):
    """The adapter of the synchronous REST API client.

    The client opens its HTTP session on the first request and closes it on
    :meth:`close`; the members the REST API lacks go through the WebSocket API client
    of the fallback, when allowed.
    """

    DESCRIPTION = "synchronous REST API client"

    def __init__(
        self,
        client: VolumioRESTAPIClient,
        fallback: Callable[[], APIClient] | None = None,
    ) -> None:
        """Initialize the adapter.

        Args:
            client: The synchronous REST API client the adapter wraps
            fallback: The function building the WebSocket API client serving the
                operations the REST API does not offer, or None to have them fail
        """
        super().__init__(client)
        self._fallback = _WebSocketFallback(self, fallback)

    @property
    def base_url(self) -> str:
        return self.host_configuration.rest_base_url

    def browse(self, uri: str | None = None, offset: int | None = None) -> BrowseResults:
        return self._client.browse(uri, offset)

    def close(self) -> None:
        self._close_quietly(self._fallback.close)
        self._close_quietly(self._client.close)

    def get_album_credits(self, artist: Artist | None, album: Album) -> Story:
        return self._client.get_album_credits(artist, album)

    def get_story(
        self,
        album: Album | None = None,
        artist: Artist | None = None,
        label: Label | None = None,
        place: Place | None = None,
    ) -> Story:
        return self._client.get_story(**_story_arguments(album, artist, label, place))

    @property
    def notifications(self) -> Notifications:
        return self._client.notifications

    def open(self) -> None:
        """Nothing to acquire: the client opens its session on the first request."""

    def register_notification(self, url: str | Notification) -> SuccessResponse:
        return self._client.register_notification(url)

    def unregister_notification(self, url: str | Notification) -> SuccessResponse:
        return self._client.unregister_notification(url)


class SyncWebSocketAPIClient(SyncAPIClient[VolumioWebSocketClient]):
    """The adapter of the synchronous WebSocket API client.

    The client connects on :meth:`open` and disconnects on :meth:`close`. The offset of
    :meth:`browse` is applied to the answer, the root included, since the WebSocket API
    takes none; the story queries and the notification URLs go through the REST API
    client of the fallback, when allowed.
    """

    DESCRIPTION = "synchronous WebSocket API client"

    def __init__(
        self,
        client: VolumioWebSocketClient,
        fallback: Callable[[], APIClient] | None = None,
    ) -> None:
        """Initialize the adapter.

        Args:
            client: The synchronous WebSocket API client the adapter wraps
            fallback: The function building the REST API client serving the operations
                the WebSocket API does not offer, or None to have them fail
        """
        super().__init__(client)
        self._fallback = _RESTFallback(self, fallback)

    def add_and_play(self, uri: str) -> None:
        return self._client.add_and_play(uri)

    def add_cue_track(self, uri: str, number: int, service: str | None = None) -> None:
        return self._client.add_cue_track(uri, number, service)

    def add_radio_favourite(self, uri: str) -> None:
        return self._client.add_radio_favourite(uri)

    def add_share(self, name: str, path: str, fstype: str, **options: str) -> None:
        return self._client.add_share(name, path, fstype, **options)

    def add_to_favourites(
        self,
        uri: str,
        title: str | None = None,
        service: str | None = None,
        albumart: str | None = None,
    ) -> None:
        return self._client.add_to_favourites(uri, title, service, albumart)

    def add_to_playlist(self, name: str | Playlist, uri: str, service: str | None = None) -> None:
        return self._client.add_to_playlist(name, uri, service)

    def add_uids_to_queue(self, uids: list[str]) -> None:
        return self._client.add_uids_to_queue(uids)

    def add_web_radio(self, name: str, uri: str) -> None:
        return self._client.add_web_radio(name, uri)

    @property
    def alarms(self) -> Alarms:
        return self._client.alarms

    def audio_output_pause(self, output_id: str) -> None:
        return self._client.audio_output_pause(output_id)

    def audio_output_play(self, output_id: str) -> None:
        return self._client.audio_output_play(output_id)

    @property
    def audio_outputs(self) -> AudioOutputs:
        return self._client.audio_outputs

    @property
    def automatic_update_enabled(self) -> bool:
        return self._client.automatic_update_enabled

    @property
    def available_timezones(self) -> Timezones:
        return self._client.available_timezones

    @property
    def backgrounds(self) -> Backgrounds:
        return self._client.backgrounds

    def backup(self) -> dict[str, Any]:
        return self._client.backup()

    @property
    def base_url(self) -> str:
        return self.host_configuration.websocket_base_url

    def browse(self, uri: str | None = None, offset: int | None = None) -> BrowseResults:
        results = self._client.browse(uri)
        return results.offset(offset) if offset else results

    @property
    def browse_sources(self) -> BrowseSources:
        return self._client.browse_sources

    def call_plugin_method(
        self,
        endpoint: str,
        method: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        return self._client.call_plugin_method(endpoint, method, data)

    def check_for_update(self) -> None:
        return self._client.check_for_update()

    def check_update_cache(self) -> None:
        return self._client.check_update_cache()

    def close(self) -> None:
        self._close_quietly(self._fallback.close)
        self._close_quietly(self._client.disconnect)

    def consume(self, value: bool) -> None:
        return self._client.consume(value)

    def create_playlist(self, name: str | Playlist) -> None:
        return self._client.create_playlist(name)

    def delete_background(self, name: str) -> None:
        return self._client.delete_background(name)

    def delete_folder(self, path: str) -> None:
        return self._client.delete_folder(path)

    def delete_playlist(self, name: str | Playlist) -> None:
        return self._client.delete_playlist(name)

    def delete_share(self, share_id: str) -> None:
        return self._client.delete_share(share_id)

    @property
    def device_name(self) -> str | None:
        return self._client.device_name

    @device_name.setter
    def device_name(self, value: str) -> None:
        self._client.device_name = value

    def disable_audio_output(self, output_id: str) -> None:
        return self._client.disable_audio_output(output_id)

    def disable_plugin(self, category: str, name: str) -> None:
        return self._client.disable_plugin(category, name)

    def discover_network_shares(self) -> dict[str, Any]:
        return self._client.discover_network_shares()

    @property
    def dsp_config(self) -> UiConfig:
        return self._client.dsp_config

    def edit_share(self, share_id: str, **fields: str) -> None:
        return self._client.edit_share(share_id, **fields)

    def emit(self, event: str, payload: object = None) -> None:
        return self._client.emit(event, payload)

    def enable_audio_output(self, output_id: str) -> None:
        return self._client.enable_audio_output(output_id)

    def enable_plugin(self, category: str, name: str) -> None:
        return self._client.enable_plugin(category, name)

    def enqueue_playlist(self, name: str | Playlist) -> None:
        return self._client.enqueue_playlist(name)

    @property
    def experience_settings(self) -> ExperienceSettings:
        return self._client.experience_settings

    @property
    def extended_output_devices(self) -> OutputDevices:
        return self._client.extended_output_devices

    def get_album_credits(self, artist: Artist | None, album: Album) -> Story:
        return self._fallback.client(STORY_OPERATION).get_album_credits(artist, album)

    def get_playlist_content(self, name: str | Playlist) -> PlaylistContent:
        return self._client.get_playlist_content(name)

    def get_plugin_config(self, page: str) -> UiConfig:
        return self._client.get_plugin_config(page)

    def get_share(self, share_id: str) -> Share:
        return self._client.get_share(share_id)

    def get_story(
        self,
        album: Album | None = None,
        artist: Artist | None = None,
        label: Label | None = None,
        place: Place | None = None,
    ) -> Story:
        return self._fallback.client(STORY_OPERATION).get_story(
            album=album, artist=artist, label=label, place=place
        )

    def goto(self, kind: str, value: str) -> BrowseResults:
        return self._client.goto(kind, value)

    def import_service_playlists(self) -> None:
        return self._client.import_service_playlists()

    @property
    def infinity_playback(self) -> InfinityPlayback:
        return self._client.infinity_playback

    @property
    def input_sources(self) -> InputSources:
        return self._client.input_sources

    def install_plugin(self, url: str) -> None:
        return self._client.install_plugin(url)

    @property
    def installed_plugins(self) -> Plugins:
        return self._client.installed_plugins

    @property
    def languages(self) -> Languages:
        return self._client.languages

    @property
    def last_browse(self) -> BrowseResults:
        return self._client.last_browse

    def manage_plugin(self, action: str, category: str, name: str) -> Plugins:
        return self._client.manage_plugin(action, category, name)

    @property
    def menu_items(self) -> MenuItems:
        return self._client.menu_items

    def modify_plugin_status(self, category: str, name: str, enabled: bool) -> None:
        return self._client.modify_plugin_status(category, name, enabled)

    def move_in_queue(self, source: int, target: int) -> None:
        return self._client.move_in_queue(source, target)

    @property
    def multiroom(self) -> Multiroom:
        return self._client.multiroom

    @property
    def music_sources(self) -> MusicSources:
        return self._client.music_sources

    @property
    def network_info(self) -> NetworkInfo:
        return self._client.network_info

    @property
    def notifications(self) -> Notifications:
        return self._fallback.client(NOTIFICATION_OPERATION).notifications

    def off(self, event: str, handler: Callable[[Any], None] | None = None) -> None:
        return self._client.off(event, handler)

    def on(self, event: str, handler: Callable[[Any], None]) -> None:
        return self._client.on(event, handler)

    def open(self) -> None:
        self._client.connect()

    @property
    def output_devices(self) -> OutputDevices:
        return self._client.output_devices

    def play_favourites(self, name: str | None = None) -> None:
        return self._client.play_favourites(name)

    def play_next(self, uri: str, title: str | None = None, album: str | None = None) -> None:
        return self._client.play_next(uri, title, album)

    def play_radio_favourites(self) -> None:
        return self._client.play_radio_favourites()

    def play_volatile(self, position: int) -> None:
        return self._client.play_volatile(position)

    @property
    def power_modes(self) -> PowerModes:
        return self._client.power_modes

    @property
    def privacy_settings(self) -> PrivacySettings:
        return self._client.privacy_settings

    def reboot(self) -> None:
        return self._client.reboot()

    def regenerate_thumbnails(self) -> None:
        return self._client.regenerate_thumbnails()

    def register_notification(self, url: str | Notification) -> SuccessResponse:
        return self._fallback.client(NOTIFICATION_OPERATION).register_notification(url)

    def remove_from_favourites(self, uri: str, service: str | None = None) -> None:
        return self._client.remove_from_favourites(uri, service)

    def remove_from_playlist(
        self,
        name: str | Playlist,
        uri: str,
        service: str | None = None,
    ) -> None:
        return self._client.remove_from_playlist(name, uri, service)

    def remove_from_queue(self, position: int) -> None:
        return self._client.remove_from_queue(position)

    def remove_radio_favourite(self, uri: str, name: str | None = None) -> None:
        return self._client.remove_radio_favourite(uri, name)

    def remove_web_radio(self, name: str) -> None:
        return self._client.remove_web_radio(name)

    def replace_queue_with_cue_track(
        self,
        uri: str,
        number: int,
        service: str | None = None,
    ) -> None:
        return self._client.replace_queue_with_cue_track(uri, number, service)

    def request(
        self,
        event: str,
        response_event: str | None = None,
        payload: object = None,
        timeout: float | None = None,
    ) -> object:
        return self._client.request(event, response_event, payload, timeout)

    def rescan_library(self) -> None:
        return self._client.rescan_library()

    def restore_backup(self, backup: dict[str, Any]) -> None:
        return self._client.restore_backup(backup)

    def restore_config(self) -> None:
        return self._client.restore_config()

    def safe_remove_drive(self, name: str) -> None:
        return self._client.safe_remove_drive(name)

    def save_queue_as_playlist(self, name: str | Playlist) -> None:
        return self._client.save_queue_as_playlist(name)

    def save_wireless_settings(self, ssid: str, password: str = '') -> None:
        return self._client.save_wireless_settings(ssid, password)

    def set_alarms(self, alarms: list[Alarm]) -> None:
        return self._client.set_alarms(alarms)

    def set_as_multiroom_client(self, server: str) -> None:
        return self._client.set_as_multiroom_client(server)

    def set_as_multiroom_server(self) -> None:
        return self._client.set_as_multiroom_server()

    def set_as_multiroom_single(self) -> None:
        return self._client.set_as_multiroom_single()

    def set_audio_output_volume(self, output_id: str, volume: int) -> None:
        return self._client.set_audio_output_volume(output_id, volume)

    def set_background(self, name: str, path: str | None = None) -> None:
        return self._client.set_background(name, path)

    def set_experience_settings(self, advanced: bool) -> None:
        return self._client.set_experience_settings(advanced)

    def set_infinity_playback(self, enabled: bool) -> None:
        return self._client.set_infinity_playback(enabled)

    def set_language(self, code: str, language: str | None = None) -> None:
        return self._client.set_language(code, language)

    def set_multiroom(self, settings: dict[str, Any]) -> Multiroom:
        return self._client.set_multiroom(settings)

    def set_music_source_enabled(self, name: str, enabled: bool) -> None:
        return self._client.set_music_source_enabled(name, enabled)

    def set_output_device(self, device_id: str, mixer: str | None = None) -> None:
        return self._client.set_output_device(device_id, mixer)

    def set_sleep_timer(self, delay: timedelta | None) -> None:
        return self._client.set_sleep_timer(delay)

    @property
    def shares(self) -> Shares:
        return self._client.shares

    def shutdown(self) -> None:
        return self._client.shutdown()

    @property
    def sleep_timer(self) -> SleepTimer:
        return self._client.sleep_timer

    def standby(self) -> None:
        return self._client.standby()

    def super_search(self, query: str) -> SearchResults:
        return self._client.super_search(query)

    @property
    def timezone(self) -> str:
        return self._client.timezone

    @timezone.setter
    def timezone(self, value: str) -> None:
        self._client.timezone = value

    @property
    def ui_settings(self) -> UiSettings:
        return self._client.ui_settings

    def uninstall_plugin(self, category: str, name: str) -> None:
        return self._client.uninstall_plugin(category, name)

    def unregister_notification(self, url: str | Notification) -> SuccessResponse:
        return self._fallback.client(NOTIFICATION_OPERATION).unregister_notification(url)

    def update(self, ignore_integrity_check: bool = False) -> None:
        return self._client.update(ignore_integrity_check)

    def update_all_metadata(self) -> None:
        return self._client.update_all_metadata()

    def update_library(self, uri: str | None = None) -> None:
        return self._client.update_library(uri)

    def update_plugin(self, category: str, name: str) -> None:
        return self._client.update_plugin(category, name)

    def update_service_tracklist(self, service: str) -> None:
        return self._client.update_service_tracklist(service)

    @property
    def updater_channel(self) -> UpdaterChannel:
        return self._client.updater_channel

    @updater_channel.setter
    def updater_channel(self, value: str) -> None:
        self._client.updater_channel = value

    @property
    def usb_drives(self) -> UsbDrives:
        return self._client.usb_drives

    @property
    def wireless_networks(self) -> WirelessNetworks:
        return self._client.wireless_networks

    @property
    def wireless_networks_cache(self) -> WirelessNetworks:
        return self._client.wireless_networks_cache

    def write_multiroom(self, settings: dict[str, Any]) -> None:
        return self._client.write_multiroom(settings)


class AsyncAPIClient[C: VolumioAsyncRESTAPIClient | VolumioAsyncWebSocketClient](APIClient):
    """The adapter of an asynchronous client, running its coroutines on a private loop.

    The loop is served by a daemon thread started by :meth:`open` and stopped by
    :meth:`close`, so the whole life of the client, from the session or connection it
    opens to the one it closes, happens on the same loop, which keeps running between
    the calls. Each member forwards to its asynchronous counterpart: the nouns to the
    ``get_*`` coroutines, the assignments to ``set_seek`` and ``set_volume``, the
    predicates and the commands to the coroutines of the same name.
    """

    def __init__(self, client: C) -> None:
        """Initialize the adapter.

        Args:
            client: The asynchronous client the adapter wraps
        """
        super().__init__(client)
        self._client = client
        self._loop_thread: tuple[asyncio.AbstractEventLoop, threading.Thread] | None = None

    @abstractmethod
    def _close_client(self) -> None:
        """Close the session, or connection, of the client, on the running loop."""

    @abstractmethod
    def _open_client(self) -> None:
        """Open the session, or connection, of the client, on the running loop."""

    def _run[T](self, coroutine: Coroutine[Any, Any, T]) -> T:
        """Run a coroutine of the client on the loop, waiting for its outcome.

        Args:
            coroutine: The coroutine to run

        Returns:
            What the coroutine returned

        Raises:
            RuntimeError: If the adapter is not open
        """
        if self._loop_thread is None:
            coroutine.close()
            raise RuntimeError(f"The {self.description} is not open")
        loop, _ = self._loop_thread
        return asyncio.run_coroutine_threadsafe(coroutine, loop).result()

    def _stop_loop(self) -> None:
        """Stop the loop and its thread, if running, cancelling the tasks still pending."""
        if self._loop_thread is None:
            return
        loop, thread = self._loop_thread
        self._loop_thread = None
        self.logger.debug(f"Stopping the event loop of the {self.description}...")
        loop.call_soon_threadsafe(loop.stop)
        thread.join()
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
        self.logger.debug(f"Stopping the event loop of the {self.description}... done")

    def add_to_queue(self, uri: str) -> CommandResponse | None:
        return self._run(self._client.add_to_queue(uri))

    def clear(self) -> CommandResponse | None:
        return self._run(self._client.clear())

    def close(self) -> None:
        if self._loop_thread is not None:
            self._close_quietly(self._close_client)
        self._stop_loop()

    @property
    def collection_statistics(self) -> CollectionStatistics:
        return self._run(self._client.get_collection_statistics())

    def decrease_volume(self) -> CommandResponse | None:
        return self._run(self._client.decrease_volume())

    @property
    def has_next(self) -> bool:
        return self._run(self._client.has_next())

    @property
    def has_previous(self) -> bool:
        return self._run(self._client.has_previous())

    def increase_volume(self) -> CommandResponse | None:
        return self._run(self._client.increase_volume())

    @property
    def is_muted(self) -> bool:
        return self._run(self._client.is_muted())

    @property
    def is_paused(self) -> bool:
        return self._run(self._client.is_paused())

    @property
    def is_playing(self) -> bool:
        return self._run(self._client.is_playing())

    @property
    def is_stopped(self) -> bool:
        return self._run(self._client.is_stopped())

    def mute(self) -> CommandResponse | None:
        return self._run(self._client.mute())

    def next(self) -> CommandResponse | None:
        return self._run(self._client.next())

    def open(self) -> None:
        if self._loop_thread is None:
            self.logger.debug(f"Starting the event loop of the {self.description}...")
            loop = asyncio.new_event_loop()
            thread = threading.Thread(
                target=loop.run_forever, name=EVENT_LOOP_THREAD_NAME, daemon=True
            )
            thread.start()
            self._loop_thread = (loop, thread)
            self.logger.debug(f"Starting the event loop of the {self.description}... done")
        try:
            self._open_client()
        except BaseException:
            self._stop_loop()
            raise

    def pause(self) -> CommandResponse | None:
        return self._run(self._client.pause())

    def ping(self) -> str:
        return self._run(self._client.ping())

    def play(self, position: int | QueueTrack | None = None) -> CommandResponse | None:
        return self._run(self._client.play(position))

    def play_playlist(self, name: str | Playlist) -> CommandResponse | None:
        return self._run(self._client.play_playlist(name))

    @property
    def playlists(self) -> Playlists:
        return self._run(self._client.get_playlists())

    def previous(self) -> CommandResponse | None:
        return self._run(self._client.previous())

    @property
    def queue(self) -> Queue:
        return self._run(self._client.get_queue())

    @property
    def queue_status(self) -> dict[str, Any]:
        return self._run(self._client.get_queue_status())

    def randomize(self, value: bool | None = None) -> CommandResponse | None:
        return self._run(self._client.randomize(value))

    def repeat(self, value: bool | None = None) -> CommandResponse | None:
        return self._run(self._client.repeat(value))

    def replace_queue_and_play(self, uri: str, index: int | None = None) -> CommandResponse | None:
        return self._run(self._client.replace_queue_and_play(uri, index))

    def search(self, query: str) -> SearchResults:
        return self._run(self._client.search(query))

    @property
    def seek(self) -> int:
        return self._run(self._client.get_seek())

    @seek.setter
    def seek(self, value: int) -> None:
        self._run(self._client.set_seek(value))

    def seek_backward(self) -> CommandResponse | None:
        return self._run(self._client.seek_backward())

    def seek_forward(self) -> CommandResponse | None:
        return self._run(self._client.seek_forward())

    @property
    def state(self) -> PlayerState:
        return self._run(self._client.get_state())

    def stop(self) -> CommandResponse | None:
        return self._run(self._client.stop())

    @property
    def system_info(self) -> SystemInfo:
        return self._run(self._client.get_system_info())

    @property
    def system_version(self) -> SystemVersion:
        return self._run(self._client.get_system_version())

    def toggle(self) -> CommandResponse | None:
        return self._run(self._client.toggle())

    def unmute(self) -> CommandResponse | None:
        return self._run(self._client.unmute())

    @property
    def volume(self) -> int:
        return self._run(self._client.get_volume())

    @volume.setter
    def volume(self, value: int) -> None:
        self._run(self._client.set_volume(value))

    @property
    def zones(self) -> Zones:
        return self._run(self._client.get_zones())


class AsyncRESTAPIClient(RESTAPIClient, AsyncAPIClient[VolumioAsyncRESTAPIClient]):
    """The adapter of the asynchronous REST API client.

    The client opens its session on the first request and closes it on :meth:`close`;
    the members the REST API lacks go through the WebSocket API client of the fallback,
    when allowed.
    """

    DESCRIPTION = "asynchronous REST API client"

    def __init__(
        self,
        client: VolumioAsyncRESTAPIClient,
        fallback: Callable[[], APIClient] | None = None,
    ) -> None:
        """Initialize the adapter.

        Args:
            client: The asynchronous REST API client the adapter wraps
            fallback: The function building the WebSocket API client serving the
                operations the REST API does not offer, or None to have them fail
        """
        super().__init__(client)
        self._fallback = _WebSocketFallback(self, fallback)

    def _close_client(self) -> None:
        self._close_quietly(self._fallback.close)
        self._run(self._client.close())

    def _open_client(self) -> None:
        """Nothing to open: the client opens its session on the first request."""

    @property
    def base_url(self) -> str:
        return self.host_configuration.rest_base_url

    def browse(self, uri: str | None = None, offset: int | None = None) -> BrowseResults:
        return self._run(self._client.browse(uri, offset))

    def get_album_credits(self, artist: Artist | None, album: Album) -> Story:
        return self._run(self._client.get_album_credits(artist, album))

    def get_story(
        self,
        album: Album | None = None,
        artist: Artist | None = None,
        label: Label | None = None,
        place: Place | None = None,
    ) -> Story:
        return self._run(self._client.get_story(**_story_arguments(album, artist, label, place)))

    @property
    def notifications(self) -> Notifications:
        return self._run(self._client.get_notifications())

    def register_notification(self, url: str | Notification) -> SuccessResponse:
        return self._run(self._client.register_notification(url))

    def unregister_notification(self, url: str | Notification) -> SuccessResponse:
        return self._run(self._client.unregister_notification(url))


class AsyncWebSocketAPIClient(AsyncAPIClient[VolumioAsyncWebSocketClient]):
    """The adapter of the asynchronous WebSocket API client.

    The client connects on :meth:`open` and disconnects on :meth:`close`. The offset of
    :meth:`browse` is applied to the answer, the root included, since the WebSocket API
    takes none; the story queries and the notification URLs go through the REST API
    client of the fallback, when allowed.
    """

    DESCRIPTION = "asynchronous WebSocket API client"

    def __init__(
        self,
        client: VolumioAsyncWebSocketClient,
        fallback: Callable[[], APIClient] | None = None,
    ) -> None:
        """Initialize the adapter.

        Args:
            client: The asynchronous WebSocket API client the adapter wraps
            fallback: The function building the REST API client serving the operations
                the WebSocket API does not offer, or None to have them fail
        """
        super().__init__(client)
        self._fallback = _RESTFallback(self, fallback)

    def _close_client(self) -> None:
        self._close_quietly(self._fallback.close)
        self._run(self._client.disconnect())

    def _open_client(self) -> None:
        self._run(self._client.connect())

    def add_and_play(self, uri: str) -> None:
        return self._run(self._client.add_and_play(uri))

    def add_cue_track(self, uri: str, number: int, service: str | None = None) -> None:
        return self._run(self._client.add_cue_track(uri, number, service))

    def add_radio_favourite(self, uri: str) -> None:
        return self._run(self._client.add_radio_favourite(uri))

    def add_share(self, name: str, path: str, fstype: str, **options: str) -> None:
        return self._run(self._client.add_share(name, path, fstype, **options))

    def add_to_favourites(
        self,
        uri: str,
        title: str | None = None,
        service: str | None = None,
        albumart: str | None = None,
    ) -> None:
        return self._run(self._client.add_to_favourites(uri, title, service, albumart))

    def add_to_playlist(self, name: str | Playlist, uri: str, service: str | None = None) -> None:
        return self._run(self._client.add_to_playlist(name, uri, service))

    def add_uids_to_queue(self, uids: list[str]) -> None:
        return self._run(self._client.add_uids_to_queue(uids))

    def add_web_radio(self, name: str, uri: str) -> None:
        return self._run(self._client.add_web_radio(name, uri))

    @property
    def alarms(self) -> Alarms:
        return self._run(self._client.get_alarms())

    def audio_output_pause(self, output_id: str) -> None:
        return self._run(self._client.audio_output_pause(output_id))

    def audio_output_play(self, output_id: str) -> None:
        return self._run(self._client.audio_output_play(output_id))

    @property
    def audio_outputs(self) -> AudioOutputs:
        return self._run(self._client.get_audio_outputs())

    @property
    def automatic_update_enabled(self) -> bool:
        return self._run(self._client.is_automatic_update_enabled())

    @property
    def available_timezones(self) -> Timezones:
        return self._run(self._client.get_available_timezones())

    @property
    def backgrounds(self) -> Backgrounds:
        return self._run(self._client.get_backgrounds())

    def backup(self) -> dict[str, Any]:
        return self._run(self._client.backup())

    @property
    def base_url(self) -> str:
        return self.host_configuration.websocket_base_url

    def browse(self, uri: str | None = None, offset: int | None = None) -> BrowseResults:
        results = self._run(self._client.browse(uri))
        return results.offset(offset) if offset else results

    @property
    def browse_sources(self) -> BrowseSources:
        return self._run(self._client.get_browse_sources())

    def call_plugin_method(
        self,
        endpoint: str,
        method: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        return self._run(self._client.call_plugin_method(endpoint, method, data))

    def check_for_update(self) -> None:
        return self._run(self._client.check_for_update())

    def check_update_cache(self) -> None:
        return self._run(self._client.check_update_cache())

    def consume(self, value: bool) -> None:
        return self._run(self._client.consume(value))

    def create_playlist(self, name: str | Playlist) -> None:
        return self._run(self._client.create_playlist(name))

    def delete_background(self, name: str) -> None:
        return self._run(self._client.delete_background(name))

    def delete_folder(self, path: str) -> None:
        return self._run(self._client.delete_folder(path))

    def delete_playlist(self, name: str | Playlist) -> None:
        return self._run(self._client.delete_playlist(name))

    def delete_share(self, share_id: str) -> None:
        return self._run(self._client.delete_share(share_id))

    @property
    def device_name(self) -> str | None:
        return self._run(self._client.get_device_name())

    @device_name.setter
    def device_name(self, value: str) -> None:
        self._run(self._client.set_device_name(value))

    def disable_audio_output(self, output_id: str) -> None:
        return self._run(self._client.disable_audio_output(output_id))

    def disable_plugin(self, category: str, name: str) -> None:
        return self._run(self._client.disable_plugin(category, name))

    def discover_network_shares(self) -> dict[str, Any]:
        return self._run(self._client.discover_network_shares())

    @property
    def dsp_config(self) -> UiConfig:
        return self._run(self._client.get_dsp_config())

    def edit_share(self, share_id: str, **fields: str) -> None:
        return self._run(self._client.edit_share(share_id, **fields))

    def emit(self, event: str, payload: object = None) -> None:
        return self._run(self._client.emit(event, payload))

    def enable_audio_output(self, output_id: str) -> None:
        return self._run(self._client.enable_audio_output(output_id))

    def enable_plugin(self, category: str, name: str) -> None:
        return self._run(self._client.enable_plugin(category, name))

    def enqueue_playlist(self, name: str | Playlist) -> None:
        return self._run(self._client.enqueue_playlist(name))

    @property
    def experience_settings(self) -> ExperienceSettings:
        return self._run(self._client.get_experience_settings())

    @property
    def extended_output_devices(self) -> OutputDevices:
        return self._run(self._client.get_extended_output_devices())

    def get_album_credits(self, artist: Artist | None, album: Album) -> Story:
        return self._fallback.client(STORY_OPERATION).get_album_credits(artist, album)

    def get_playlist_content(self, name: str | Playlist) -> PlaylistContent:
        return self._run(self._client.get_playlist_content(name))

    def get_plugin_config(self, page: str) -> UiConfig:
        return self._run(self._client.get_plugin_config(page))

    def get_share(self, share_id: str) -> Share:
        return self._run(self._client.get_share(share_id))

    def get_story(
        self,
        album: Album | None = None,
        artist: Artist | None = None,
        label: Label | None = None,
        place: Place | None = None,
    ) -> Story:
        return self._fallback.client(STORY_OPERATION).get_story(
            album=album, artist=artist, label=label, place=place
        )

    def goto(self, kind: str, value: str) -> BrowseResults:
        return self._run(self._client.goto(kind, value))

    def import_service_playlists(self) -> None:
        return self._run(self._client.import_service_playlists())

    @property
    def infinity_playback(self) -> InfinityPlayback:
        return self._run(self._client.get_infinity_playback())

    @property
    def input_sources(self) -> InputSources:
        return self._run(self._client.get_input_sources())

    def install_plugin(self, url: str) -> None:
        return self._run(self._client.install_plugin(url))

    @property
    def installed_plugins(self) -> Plugins:
        return self._run(self._client.get_installed_plugins())

    @property
    def languages(self) -> Languages:
        return self._run(self._client.get_languages())

    @property
    def last_browse(self) -> BrowseResults:
        return self._run(self._client.get_last_browse())

    def manage_plugin(self, action: str, category: str, name: str) -> Plugins:
        return self._run(self._client.manage_plugin(action, category, name))

    @property
    def menu_items(self) -> MenuItems:
        return self._run(self._client.get_menu_items())

    def modify_plugin_status(self, category: str, name: str, enabled: bool) -> None:
        return self._run(self._client.modify_plugin_status(category, name, enabled))

    def move_in_queue(self, source: int, target: int) -> None:
        return self._run(self._client.move_in_queue(source, target))

    @property
    def multiroom(self) -> Multiroom:
        return self._run(self._client.get_multiroom())

    @property
    def music_sources(self) -> MusicSources:
        return self._run(self._client.get_music_sources())

    @property
    def network_info(self) -> NetworkInfo:
        return self._run(self._client.get_network_info())

    @property
    def notifications(self) -> Notifications:
        return self._fallback.client(NOTIFICATION_OPERATION).notifications

    def off(self, event: str, handler: Callable[[Any], None] | None = None) -> None:
        return self._client.off(event, handler)

    def on(self, event: str, handler: Callable[[Any], None]) -> None:
        return self._client.on(event, handler)

    @property
    def output_devices(self) -> OutputDevices:
        return self._run(self._client.get_output_devices())

    def play_favourites(self, name: str | None = None) -> None:
        return self._run(self._client.play_favourites(name))

    def play_next(self, uri: str, title: str | None = None, album: str | None = None) -> None:
        return self._run(self._client.play_next(uri, title, album))

    def play_radio_favourites(self) -> None:
        return self._run(self._client.play_radio_favourites())

    def play_volatile(self, position: int) -> None:
        return self._run(self._client.play_volatile(position))

    @property
    def power_modes(self) -> PowerModes:
        return self._run(self._client.get_power_modes())

    @property
    def privacy_settings(self) -> PrivacySettings:
        return self._run(self._client.get_privacy_settings())

    def reboot(self) -> None:
        return self._run(self._client.reboot())

    def regenerate_thumbnails(self) -> None:
        return self._run(self._client.regenerate_thumbnails())

    def register_notification(self, url: str | Notification) -> SuccessResponse:
        return self._fallback.client(NOTIFICATION_OPERATION).register_notification(url)

    def remove_from_favourites(self, uri: str, service: str | None = None) -> None:
        return self._run(self._client.remove_from_favourites(uri, service))

    def remove_from_playlist(
        self,
        name: str | Playlist,
        uri: str,
        service: str | None = None,
    ) -> None:
        return self._run(self._client.remove_from_playlist(name, uri, service))

    def remove_from_queue(self, position: int) -> None:
        return self._run(self._client.remove_from_queue(position))

    def remove_radio_favourite(self, uri: str, name: str | None = None) -> None:
        return self._run(self._client.remove_radio_favourite(uri, name))

    def remove_web_radio(self, name: str) -> None:
        return self._run(self._client.remove_web_radio(name))

    def replace_queue_with_cue_track(
        self,
        uri: str,
        number: int,
        service: str | None = None,
    ) -> None:
        return self._run(self._client.replace_queue_with_cue_track(uri, number, service))

    def request(
        self,
        event: str,
        response_event: str | None = None,
        payload: object = None,
        timeout: float | None = None,
    ) -> object:
        return self._run(self._client.request(event, response_event, payload, timeout))

    def rescan_library(self) -> None:
        return self._run(self._client.rescan_library())

    def restore_backup(self, backup: dict[str, Any]) -> None:
        return self._run(self._client.restore_backup(backup))

    def restore_config(self) -> None:
        return self._run(self._client.restore_config())

    def safe_remove_drive(self, name: str) -> None:
        return self._run(self._client.safe_remove_drive(name))

    def save_queue_as_playlist(self, name: str | Playlist) -> None:
        return self._run(self._client.save_queue_as_playlist(name))

    def save_wireless_settings(self, ssid: str, password: str = '') -> None:
        return self._run(self._client.save_wireless_settings(ssid, password))

    def set_alarms(self, alarms: list[Alarm]) -> None:
        return self._run(self._client.set_alarms(alarms))

    def set_as_multiroom_client(self, server: str) -> None:
        return self._run(self._client.set_as_multiroom_client(server))

    def set_as_multiroom_server(self) -> None:
        return self._run(self._client.set_as_multiroom_server())

    def set_as_multiroom_single(self) -> None:
        return self._run(self._client.set_as_multiroom_single())

    def set_audio_output_volume(self, output_id: str, volume: int) -> None:
        return self._run(self._client.set_audio_output_volume(output_id, volume))

    def set_background(self, name: str, path: str | None = None) -> None:
        return self._run(self._client.set_background(name, path))

    def set_experience_settings(self, advanced: bool) -> None:
        return self._run(self._client.set_experience_settings(advanced))

    def set_infinity_playback(self, enabled: bool) -> None:
        return self._run(self._client.set_infinity_playback(enabled))

    def set_language(self, code: str, language: str | None = None) -> None:
        return self._run(self._client.set_language(code, language))

    def set_multiroom(self, settings: dict[str, Any]) -> Multiroom:
        return self._run(self._client.set_multiroom(settings))

    def set_music_source_enabled(self, name: str, enabled: bool) -> None:
        return self._run(self._client.set_music_source_enabled(name, enabled))

    def set_output_device(self, device_id: str, mixer: str | None = None) -> None:
        return self._run(self._client.set_output_device(device_id, mixer))

    def set_sleep_timer(self, delay: timedelta | None) -> None:
        return self._run(self._client.set_sleep_timer(delay))

    @property
    def shares(self) -> Shares:
        return self._run(self._client.get_shares())

    def shutdown(self) -> None:
        return self._run(self._client.shutdown())

    @property
    def sleep_timer(self) -> SleepTimer:
        return self._run(self._client.get_sleep_timer())

    def standby(self) -> None:
        return self._run(self._client.standby())

    def super_search(self, query: str) -> SearchResults:
        return self._run(self._client.super_search(query))

    @property
    def timezone(self) -> str:
        return self._run(self._client.get_timezone())

    @timezone.setter
    def timezone(self, value: str) -> None:
        self._run(self._client.set_timezone(value))

    @property
    def ui_settings(self) -> UiSettings:
        return self._run(self._client.get_ui_settings())

    def uninstall_plugin(self, category: str, name: str) -> None:
        return self._run(self._client.uninstall_plugin(category, name))

    def unregister_notification(self, url: str | Notification) -> SuccessResponse:
        return self._fallback.client(NOTIFICATION_OPERATION).unregister_notification(url)

    def update(self, ignore_integrity_check: bool = False) -> None:
        return self._run(self._client.update(ignore_integrity_check))

    def update_all_metadata(self) -> None:
        return self._run(self._client.update_all_metadata())

    def update_library(self, uri: str | None = None) -> None:
        return self._run(self._client.update_library(uri))

    def update_plugin(self, category: str, name: str) -> None:
        return self._run(self._client.update_plugin(category, name))

    def update_service_tracklist(self, service: str) -> None:
        return self._run(self._client.update_service_tracklist(service))

    @property
    def updater_channel(self) -> UpdaterChannel:
        return self._run(self._client.get_updater_channel())

    @updater_channel.setter
    def updater_channel(self, value: str) -> None:
        self._run(self._client.set_updater_channel(value))

    @property
    def usb_drives(self) -> UsbDrives:
        return self._run(self._client.get_usb_drives())

    @property
    def wireless_networks(self) -> WirelessNetworks:
        return self._run(self._client.get_wireless_networks())

    @property
    def wireless_networks_cache(self) -> WirelessNetworks:
        return self._run(self._client.get_wireless_networks_cache())

    def write_multiroom(self, settings: dict[str, Any]) -> None:
        return self._run(self._client.write_multiroom(settings))
