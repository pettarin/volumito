"""Logic shared by the WebSocket API clients for Volumio.

The synchronous and the asynchronous WebSocket API clients differ only in their transport:
the names of the events they emit, the payloads those events carry, the answers they wait
for, and the messages they log and raise all live here, so the two cannot drift apart.

A Volumio host answers no event with a Socket.IO acknowledgement: a read emits its request
event and waits for the matching ``push*`` event the host broadcasts, which
``RESPONSE_EVENTS`` maps. The names come from the WebSocket plugin of the Volumio backend
rather than from the published API documentation, which covers roughly a quarter of them
and disagrees with the code on the payloads of ``seek`` and ``volume``.

This module knows nothing about how a client talks to the host: it imports neither
``socketio`` nor ``aiohttp``.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

import re
import string
from datetime import timedelta
from typing import Any, NoReturn

from volumito.clients.common import VolumioCommon
from volumito.clients.errors import VolumioAPIError, VolumioConnectionError
from volumito.clients.models import Alarm, Playlist, QueueTrack

ALARM_TIME_DATE = "2000-01-01"
"""The date the alarm times are rendered on: the host schedules by the time of day alone."""

BACKUP_ACTION_RESTORE = 1
"""The backup flag making the host restore its local backup of the playlists and favourites."""

BACKUP_ACTION_SAVE = 0
"""The backup flag making the host write its local backup of the playlists and favourites."""

BACKUP_KINDS = ("favourites", "my-web-radio", "playlist", "radio-favourites")
"""The kinds of backup a Volumio host reads: the favourite tracks, the Web radios added by
hand, the saved playlists with their content, and the favourite Web radios."""

EVENT_ADD_PLAY = "addPlay"
"""The event appending items to the queue and playing them."""

EVENT_ADD_PLAY_CUE = "addPlayCue"
"""The event appending a track of a cue sheet and playing it."""

EVENT_ADD_QUEUE_UIDS = "addQueueUids"
"""The event appending library items to the queue by identifier."""

EVENT_ADD_SHARE = "addShare"
"""The event mounting a network share."""

EVENT_ADD_TO_FAVOURITES = "addToFavourites"
"""The event adding an item to the favourites."""

EVENT_ADD_TO_PLAYLIST = "addToPlaylist"
"""The event adding an item to a saved playlist."""

EVENT_ADD_TO_QUEUE = "addToQueue"
"""The event appending items to the playback queue."""

EVENT_ADD_TO_RADIO_FAVOURITES = "addToRadioFavourites"
"""The event adding a Web radio to the radio favourites."""

EVENT_ADD_WEB_RADIO = "addWebRadio"
"""The event saving a Web radio of the user."""

EVENT_AUDIO_OUTPUT_PAUSE = "audioOutputPause"
"""The event pausing one audio output."""

EVENT_AUDIO_OUTPUT_PLAY = "audioOutputPlay"
"""The event starting one audio output."""

EVENT_BROWSE_LIBRARY = "browseLibrary"
"""The event listing the content of a URI."""

EVENT_CALL_METHOD = "callMethod"
"""The event calling a method of a plugin directly."""

EVENT_CLEAR_QUEUE = "clearQueue"
"""The event emptying the playback queue."""

EVENT_CREATE_PLAYLIST = "createPlaylist"
"""The event creating an empty saved playlist."""

EVENT_DELETE_BACKGROUND = "deleteBackground"
"""The event deleting a background image."""

EVENT_DELETE_FOLDER = "deleteFolder"
"""The event deleting a folder of the collection."""

EVENT_DELETE_PLAYLIST = "deletePlaylist"
"""The event deleting a saved playlist."""

EVENT_DELETE_SHARE = "deleteShare"
"""The event unmounting a network share."""

EVENT_DELETE_USER_DATA = "deleteUserData"
"""The event erasing the data of the user. Never emitted by the clients."""

EVENT_DISABLE_AUDIO_OUTPUT = "disableAudioOutput"
"""The event disabling one audio output."""

EVENT_DISABLE_PLUGIN = "disablePlugin"
"""The event disabling an installed plugin."""

EVENT_EDIT_SHARE = "editShare"
"""The event changing a mounted network share."""

EVENT_ENABLE_AUDIO_OUTPUT = "enableAudioOutput"
"""The event enabling one audio output."""

EVENT_ENABLE_DISABLE_MY_MUSIC_PLUGIN = "enableDisableMyMusicPlugin"
"""The event enabling or disabling a music source."""

EVENT_ENABLE_PLUGIN = "enablePlugin"
"""The event enabling an installed plugin."""

EVENT_ENQUEUE = "enqueue"
"""The event appending a saved playlist to the queue."""

EVENT_FACTORY_RESET = "factoryReset"
"""The event resetting the host to its factory configuration. Never emitted by the clients."""

EVENT_GET_ALARMS = "getAlarms"
"""The event asking for the alarms set on the host."""

EVENT_GET_AUDIO_OUTPUTS = "getAudioOutputs"
"""The event asking for the audio outputs of the host."""

EVENT_GET_AUTOMATIC_UPDATE_ENABLED = "getAutomaticUpdateEnabled"
"""The event asking whether the host updates itself."""

EVENT_GET_AVAILABLE_LANGUAGES = "getAvailableLanguages"
"""The event asking for the languages of the user interface."""

EVENT_GET_AVAILABLE_PLUGINS = "getAvailablePlugins"
"""The event asking for the plugins the store offers, answered only to a MyVolumio login."""

EVENT_GET_AVAILABLE_TIMEZONES = "getAvailableTimezones"
"""The event asking for the time zones the host can be set to."""

EVENT_GET_BACKGROUNDS = "getBackgrounds"
"""The event asking for the background images of the user interface."""

EVENT_GET_BACKUP = "getBackup"
"""The event asking for a backup of the configuration of the host."""

EVENT_GET_BROWSE_SOURCES = "getBrowseSources"
"""The event asking for the sources the host can browse."""

EVENT_GET_CURRENT_TIMEZONE = "getCurrentTimezone"
"""The event asking for the time zone of the host."""

EVENT_GET_DEVICE_HW_UUID = "getDeviceHWUUID"
"""The event asking for the hardware identifier of the host."""

EVENT_GET_DEVICE_INFO = "getDeviceInfo"
"""The event asking for the identity of the host."""

EVENT_GET_DEVICE_NAME = "getDeviceName"
"""The event asking for the name of the host."""

EVENT_GET_DSP_UI_CONFIG = "getDSPUiConfig"
"""The event asking for the configuration page of the DSP."""

EVENT_GET_EXPERIENCE_ADVANCED_SETTINGS = "getExperienceAdvancedSettings"
"""The event asking how many options the user interface offers."""

EVENT_GET_EXTENDED_OUTPUT_DEVICES = "getExtendedOutputDevices"
"""The event asking for the output devices, with their details."""

EVENT_GET_INFINITY_PLAYBACK = "getInfinityPlayback"
"""The event asking for the infinity playback setting."""

EVENT_GET_INFO_NETWORK = "getInfoNetwork"
"""The event asking for the network interfaces of the host."""

EVENT_GET_INFO_SHARE = "getInfoShare"
"""The event asking for the details of one network share."""

EVENT_GET_INPUT_SOURCES = "getInputSources"
"""The event asking for the input sources of the host."""

EVENT_GET_INSTALLED_PLUGINS = "getInstalledPlugins"
"""The event asking for the plugins installed on the host."""

EVENT_GET_LAST_PUSHED_BROWSE_LIBRARY = "getLastPushedBrowseLibrary"
"""The event asking for the listing the host pushed last."""

EVENT_GET_LIST_SHARES = "getListShares"
"""The event asking for the network shares mounted by the host."""

EVENT_GET_MENU_ITEMS = "getMenuItems"
"""The event asking for the menu the host offers its user interface."""

EVENT_GET_MULTIROOM = "getMultiroom"
"""The event asking for the multiroom configuration of the host."""

EVENT_GET_MULTI_ROOM_DEVICES = "getMultiRoomDevices"
"""The event asking for the Volumio devices on the network."""

EVENT_GET_MY_COLLECTION_STATS = "getMyCollectionStats"
"""The event asking for the statistics of the music collection."""

EVENT_GET_MY_MUSIC_PLUGINS = "getMyMusicPlugins"
"""The event asking for the music sources of the host."""

EVENT_GET_NETWORK_SHARES_DISCOVERY = "getNetworkSharesDiscovery"
"""The event discovering the network shares reachable from the host."""

EVENT_GET_OUTPUT_DEVICES = "getOutputDevices"
"""The event asking for the output devices of the host."""

EVENT_GET_PLAYLIST_CONTENT = "getPlaylistContent"
"""The event asking for the tracks of a saved playlist."""

EVENT_GET_PRIVACY_SETTINGS = "getPrivacySettings"
"""The event asking for the privacy settings of the host."""

EVENT_GET_QUEUE = "getQueue"
"""The event asking for the playback queue."""

EVENT_GET_SHUTDOWN_OR_STANDBY_MODE = "getShutdownOrStandbyMode"
"""The event asking how the host can be powered down."""

EVENT_GET_SLEEP = "getSleep"
"""The event asking for the sleep timer of the host."""

EVENT_GET_STATE = "getState"
"""The event asking for the playback state."""

EVENT_GET_SYSTEM_INFO = "getSystemInfo"
"""The event asking for the system information of the host."""

EVENT_GET_SYSTEM_VERSION = "getSystemVersion"
"""The event asking for the Volumio version the host runs."""

EVENT_GET_UI_CONFIG = "getUiConfig"
"""The event asking for the configuration page of a plugin."""

EVENT_GET_UI_SETTINGS = "getUiSettings"
"""The event asking for the look of the user interface."""

EVENT_GET_UPDATER_CHANNEL = "getUpdaterChannel"
"""The event asking for the update channel the host follows."""

EVENT_GET_WIRELESS_NETWORKS = "getWirelessNetworks"
"""The event scanning for wireless networks."""

EVENT_GET_WIRELESS_NETWORKS_CACHE = "getWirelessNetworksCache"
"""The event asking for the wireless networks seen last."""

EVENT_GO_TO = "goTo"
"""The event browsing to the artist or the album of what is playing."""

EVENT_IMPORT_SERVICE_PLAYLISTS = "importServicePlaylists"
"""The event importing the playlists of the music services."""

EVENT_INSTALL_PLUGIN = "installPlugin"
"""The event installing a plugin from a URL."""

EVENT_INSTALL_TO_DISK = "installToDisk"
"""The event writing Volumio to the internal storage of the host."""

EVENT_LIST_PLAYLIST = "listPlaylist"
"""The event asking for the names of the saved playlists."""

EVENT_MANAGE_BACKUP = "manageBackup"
"""The event restoring a backup of the configuration."""

EVENT_MODIFY_PLUGIN_STATUS = "modifyPluginStatus"
"""The event enabling or disabling a plugin in one call."""

EVENT_MOVE_QUEUE = "moveQueue"
"""The event moving a track to another position of the queue."""

EVENT_MUTE = "mute"
"""The event muting the volume."""

EVENT_NEXT = "next"
"""The event skipping to the next track."""

EVENT_OPEN_MODAL = "openModal"
"""The event pushing a dialog to the user interface, which some reads get as their answer."""

EVENT_PAUSE = "pause"
"""The event pausing the playback."""

EVENT_PINGER = "pinger"
"""The event a host echoes back, unchanged, as ``ponger``."""

EVENT_PLAY = "play"
"""The event starting the playback."""

EVENT_PLAY_FAVOURITES = "playFavourites"
"""The event playing the favourites."""

EVENT_PLAY_ITEMS_LIST = "playItemsList"
"""The event replacing the queue with a list of items and playing it."""

EVENT_PLAY_NEXT = "playNext"
"""The event queueing an item right after the current track."""

EVENT_PLAY_PLAYLIST = "playPlaylist"
"""The event starting the playback of a saved playlist."""

EVENT_PLAY_RADIO_FAVOURITES = "playRadioFavourites"
"""The event playing the radio favourites."""

EVENT_PLUGIN_MANAGER = "pluginManager"
"""The event asking the plugin manager to act on a plugin."""

EVENT_PONGER = "ponger"
"""The event echoing back what ``pinger`` carried."""

EVENT_PREVIOUS = "prev"
"""The event going back to the previous track."""

EVENT_PUSH_ADD_TO_PLAYLIST = "pushAddToPlaylist"
"""The event confirming an item was added to a playlist."""

EVENT_PUSH_ADD_TO_RADIO_FAVOURITES = "pushAddToRadioFavourites"
"""The event confirming a Web radio was made a favourite."""

EVENT_PUSH_ADD_WEB_RADIO = "pushAddWebRadio"
"""The event confirming a Web radio was saved."""

EVENT_PUSH_ALARM = "pushAlarm"
"""The event carrying the alarms set on the host."""

EVENT_PUSH_AUDIO_OUTPUTS = "pushAudioOutputs"
"""The event carrying the audio outputs of the host."""

EVENT_PUSH_AUTOMATIC_UPDATE_ENABLED = "pushAutomaticUpdateEnabled"
"""The event carrying whether the host updates itself."""

EVENT_PUSH_AVAILABLE_LANGUAGES = "pushAvailableLanguages"
"""The event carrying the languages of the user interface."""

EVENT_PUSH_AVAILABLE_PLUGINS = "pushAvailablePlugins"
"""The event carrying the plugins the store offers."""

EVENT_PUSH_AVAILABLE_TIMEZONES = "pushAvailableTimezones"
"""The event carrying the time zones the host can be set to."""

EVENT_PUSH_BACKGROUNDS = "pushBackgrounds"
"""The event carrying the background images of the user interface."""

EVENT_PUSH_BACKUP = "pushBackup"
"""The event carrying a backup of the configuration of the host."""

EVENT_PUSH_BROWSE_LIBRARY = "pushBrowseLibrary"
"""The event carrying a browse listing, and also a search result."""

EVENT_PUSH_BROWSE_SOURCES = "pushBrowseSources"
"""The event carrying the sources the host can browse."""

EVENT_PUSH_CREATE_PLAYLIST = "pushCreatePlaylist"
"""The event confirming a playlist was created."""

EVENT_PUSH_CURRENT_TIMEZONE = "pushCurrentTimezone"
"""The event carrying the time zone of the host."""

EVENT_PUSH_DEVICE_HW_UUID = "pushDeviceHWUUID"
"""The event carrying the hardware identifier of the host."""

EVENT_PUSH_DEVICE_INFO = "pushDeviceInfo"
"""The event carrying the identity of the host."""

EVENT_PUSH_DEVICE_NAME = "pushDeviceName"
"""The event carrying the name of the host."""

EVENT_PUSH_DSP_UI_CONFIG = "pushDSPUiConfig"
"""The event carrying the configuration page of the DSP."""

EVENT_PUSH_ENQUEUE = "pushEnqueue"
"""The event carrying the queue a playlist was appended to."""

EVENT_PUSH_EXPERIENCE_ADVANCED_SETTINGS = "pushExperienceAdvancedSettings"
"""The event carrying how many options the user interface offers."""

EVENT_PUSH_EXTENDED_OUTPUT_DEVICES = "pushExtendedOutputDevices"
"""The event carrying the output devices with their details."""

EVENT_PUSH_INFINITY_PLAYBACK = "pushInfinityPlayback"
"""The event carrying the infinity playback setting."""

EVENT_PUSH_INFO_NETWORK = "pushInfoNetwork"
"""The event carrying the network interfaces of the host."""

EVENT_PUSH_INFO_SHARE = "pushInfoShare"
"""The event carrying the details of one network share."""

EVENT_PUSH_INPUT_SOURCES = "pushInputSources"
"""The event carrying the input sources of the host."""

EVENT_PUSH_INSTALLED_PLUGINS = "pushInstalledPlugins"
"""The event carrying the plugins installed on the host."""

EVENT_PUSH_LIST_PLAYLIST = "pushListPlaylist"
"""The event carrying the names of the saved playlists."""

EVENT_PUSH_LIST_SHARES = "pushListShares"
"""The event carrying the network shares mounted by the host."""

EVENT_PUSH_MENU_ITEMS = "pushMenuItems"
"""The event carrying the menu of the user interface."""

EVENT_PUSH_MULTIROOM = "pushMultiroom"
"""The event carrying the multiroom configuration of the host."""

EVENT_PUSH_MULTI_ROOM_DEVICES = "pushMultiRoomDevices"
"""The event carrying the Volumio devices on the network."""

EVENT_PUSH_MY_COLLECTION_STATS = "pushMyCollectionStats"
"""The event carrying the statistics of the music collection."""

EVENT_PUSH_MY_MUSIC_PLUGINS = "pushMyMusicPlugins"
"""The event carrying the music sources of the host."""

EVENT_PUSH_NETWORK_SHARES_DISCOVERY = "pushNetworkSharesDiscovery"
"""The event carrying the network shares that were discovered."""

EVENT_PUSH_OUTPUT_DEVICES = "pushOutputDevices"
"""The event carrying the output devices of the host."""

EVENT_PUSH_PLAYLIST_CONTENT = "pushPlaylistContent"
"""The event carrying the tracks of a saved playlist."""

EVENT_PUSH_PLAY_FAVOURITES = "pushPlayFavourites"
"""The event confirming the favourites are playing."""

EVENT_PUSH_PLAY_RADIO_FAVOURITES = "pushPlayRadioFavourites"
"""The event confirming the radio favourites are playing."""

EVENT_PUSH_PRIVACY_SETTINGS = "pushPrivacySettings"
"""The event carrying the privacy settings of the host."""

EVENT_PUSH_QUEUE = "pushQueue"
"""The event carrying the playback queue."""

EVENT_PUSH_REMOVE_FROM_RADIO_FAVOURITES = "pushRemoveFromRadioFavourites"
"""The event confirming a Web radio is no longer a favourite."""

EVENT_PUSH_SAVE_QUEUE_TO_PLAYLIST = "pushSaveQueueToPlaylist"
"""The event confirming the queue was saved as a playlist."""

EVENT_PUSH_SET_CONSUME = "pushSetConsume"
"""The event carrying the consume mode."""

EVENT_PUSH_SHUTDOWN_OR_STANDBY_MODE = "pushShutdownOrStandbyMode"
"""The event carrying the ways the host can be powered down."""

EVENT_PUSH_SLEEP = "pushSleep"
"""The event carrying the sleep timer of the host."""

EVENT_PUSH_STATE = "pushState"
"""The event carrying the playback state, broadcast on every change of it."""

EVENT_PUSH_SYSTEM_INFO = "pushSystemInfo"
"""The event carrying the system information of the host."""

EVENT_PUSH_SYSTEM_VERSION = "pushSystemVersion"
"""The event carrying the Volumio version the host runs."""

EVENT_PUSH_UI_CONFIG = "pushUiConfig"
"""The event carrying the configuration page of a plugin."""

EVENT_PUSH_UI_SETTINGS = "pushUiSettings"
"""The event carrying the look of the user interface."""

EVENT_PUSH_UPDATER_CHANNEL = "pushUpdaterChannel"
"""The event carrying the update channel the host follows."""

EVENT_PUSH_WIRELESS_NETWORKS = "pushWirelessNetworks"
"""The event carrying the wireless networks that were scanned for."""

EVENT_PUSH_WIRELESS_NETWORKS_CACHE = "pushWirelessNetworksCache"
"""The event carrying the wireless networks seen last."""

EVENT_PUSH_WRITE_MULTIROOM = "pushWriteMultiroom"
"""The event confirming the multiroom role of the host."""

EVENT_REBOOT = "reboot"
"""The event restarting the host."""

EVENT_REGENERATE_THUMBNAILS = "regenerateThumbnails"
"""The event rebuilding the thumbnails of the album art."""

EVENT_REMOVE_FROM_FAVOURITES = "removeFromFavourites"
"""The event removing an item from the favourites."""

EVENT_REMOVE_FROM_PLAYLIST = "removeFromPlaylist"
"""The event removing an item from a saved playlist."""

EVENT_REMOVE_FROM_RADIO_FAVOURITES = "removeFromRadioFavourites"
"""The event removing a Web radio from the radio favourites."""

EVENT_REMOVE_QUEUE_ITEM = "removeQueueItem"
"""The event removing a track from the queue."""

EVENT_REMOVE_WEB_RADIO = "removeWebRadio"
"""The event deleting a Web radio of the user."""

EVENT_REPLACE_AND_PLAY = "replaceAndPlay"
"""The event replacing the playback queue and starting it."""

EVENT_REPLACE_AND_PLAY_CUE = "replaceAndPlayCue"
"""The event replacing the queue with a track of a cue sheet."""

EVENT_RESCAN_DB = "rescanDb"
"""The event rescanning the music collection from scratch."""

EVENT_RESTORE_CONFIG = "restoreConfig"
"""The event restoring the configuration of the plugins."""

EVENT_SAFE_REMOVE_DRIVE = "safeRemoveDrive"
"""The event unmounting a USB drive before it is unplugged."""

EVENT_SAVE_ALARM = "saveAlarm"
"""The event replacing the whole set of alarms."""

EVENT_SAVE_QUEUE_TO_PLAYLIST = "saveQueueToPlaylist"
"""The event saving the queue as a saved playlist."""

EVENT_SAVE_WIRELESS_NETWORK_SETTINGS = "saveWirelessNetworkSettings"
"""The event joining a wireless network."""

EVENT_SEARCH = "search"
"""The event searching the sources of the host."""

EVENT_SEEK = "seek"
"""The event seeking to an absolute position."""

EVENT_SERVICE_UPDATE_TRACKLIST = "serviceUpdateTracklist"
"""The event refreshing the tracks of one music service."""

EVENT_SET_AS_MULTIROOM_CLIENT = "setAsMultiroomClient"
"""The event making the host a multiroom client."""

EVENT_SET_AS_MULTIROOM_SERVER = "setAsMultiroomServer"
"""The event making the host a multiroom server."""

EVENT_SET_AS_MULTIROOM_SINGLE = "setAsMultiroomSingle"
"""The event taking the host out of multiroom."""

EVENT_SET_AUDIO_OUTPUT_VOLUME = "setAudioOutputVolume"
"""The event setting the volume of one audio output."""

EVENT_SET_BACKGROUNDS = "setBackgrounds"
"""The event choosing the background image of the user interface."""

EVENT_SET_CONSUME = "setConsume"
"""The event setting the consume mode."""

EVENT_SET_DEVICE_NAME = "setDeviceName"
"""The event renaming the host."""

EVENT_SET_EXPERIENCE_ADVANCED_SETTINGS = "setExperienceAdvancedSettings"
"""The event choosing how many options the user interface offers."""

EVENT_SET_INFINITY_PLAYBACK = "setInfinityPlayback"
"""The event turning infinity playback on or off."""

EVENT_SET_LANGUAGE = "setLanguage"
"""The event choosing the language of the user interface."""

EVENT_SET_MULTIROOM = "setMultiroom"
"""The event changing the multiroom configuration of the host."""

EVENT_SET_OUTPUT_DEVICES = "setOutputDevices"
"""The event choosing the output device of the host."""

EVENT_SET_RANDOM = "setRandom"
"""The event setting the random playback mode."""

EVENT_SET_REPEAT = "setRepeat"
"""The event setting the repeat playback mode."""

EVENT_SET_SLEEP = "setSleep"
"""The event arming or disarming the sleep timer."""

EVENT_SET_TIMEZONE = "setTimezone"
"""The event choosing the time zone of the host."""

EVENT_SET_UPDATER_CHANNEL = "setUpdaterChannel"
"""The event choosing the update channel the host follows."""

EVENT_SHUTDOWN = "shutdown"
"""The event powering the host off."""

EVENT_STANDBY = "standby"
"""The event putting the host on standby."""

EVENT_STOP = "stop"
"""The event stopping the playback."""

EVENT_SUPER_SEARCH = "superSearch"
"""The event searching the sources of the host, across all of them."""

EVENT_TOGGLE = "toggle"
"""The event toggling between playing and paused."""

EVENT_UNINSTALL_PLUGIN = "unInstallPlugin"
"""The event removing an installed plugin."""

EVENT_UNMUTE = "unmute"
"""The event unmuting the volume."""

EVENT_UPDATE = "update"
"""The event installing the update the host found."""

EVENT_UPDATE_ALL_METADATA = "updateAllMetadata"
"""The event refreshing the metadata of the whole collection."""

EVENT_UPDATE_CHECK = "updateCheck"
"""The event checking whether an update is available."""

EVENT_UPDATE_CHECK_CACHE = "updateCheckCache"
"""The event checking the cached update information."""

EVENT_UPDATE_DB = "updateDb"
"""The event updating the music collection."""

EVENT_UPDATE_PLUGIN = "updatePlugin"
"""The event updating an installed plugin."""

EVENT_UPDATE_READY_CACHE = "updateReadyCache"
"""The event carrying the cached answer of the updater, in reply to a cached check."""

EVENT_UPDATE_READY_FOR_DAEMON = "updateReadyForDaemon"
"""The event carrying the answer of the updater to a check, pushed whatever the check asked."""

EVENT_URI_FAVOURITES = "urifavourites"
"""The event carrying the favourite status of a URI."""

EVENT_VOLATILE_PLAY = "volatilePlay"
"""The event starting a volatile source at a position."""

EVENT_VOLUME = "volume"
"""The event setting the volume, by level or by increment."""

EVENT_WRITE_MULTIROOM = "writeMultiroom"
"""The event writing the multiroom configuration of the host."""

I2S_OUTPUT_DEVICE_VALUE = 1
"""The sound card number sent beside an I2S DAC, as the setup wizard of the host sends it."""

PENDING_PACKETS_POLL_INTERVAL = 0.01
"""Seconds between two looks at the packets still to be written while disconnecting."""

PLUGIN_STATUS_STARTED = "START"
"""The status starting a plugin, as the plugin status event reads it."""

PLUGIN_STATUS_STOPPED = "STOP"
"""The status stopping a plugin, as the plugin status event reads it."""

RESPONSE_EVENTS = {
    EVENT_BROWSE_LIBRARY: EVENT_PUSH_BROWSE_LIBRARY,
    EVENT_GET_ALARMS: EVENT_PUSH_ALARM,
    EVENT_GET_AUDIO_OUTPUTS: EVENT_PUSH_AUDIO_OUTPUTS,
    EVENT_GET_AUTOMATIC_UPDATE_ENABLED: EVENT_PUSH_AUTOMATIC_UPDATE_ENABLED,
    EVENT_GET_AVAILABLE_LANGUAGES: EVENT_PUSH_AVAILABLE_LANGUAGES,
    EVENT_GET_AVAILABLE_PLUGINS: EVENT_PUSH_AVAILABLE_PLUGINS,
    EVENT_GET_AVAILABLE_TIMEZONES: EVENT_PUSH_AVAILABLE_TIMEZONES,
    EVENT_GET_BACKGROUNDS: EVENT_PUSH_BACKGROUNDS,
    EVENT_GET_BACKUP: EVENT_PUSH_BACKUP,
    EVENT_GET_BROWSE_SOURCES: EVENT_PUSH_BROWSE_SOURCES,
    EVENT_GET_CURRENT_TIMEZONE: EVENT_PUSH_CURRENT_TIMEZONE,
    EVENT_GET_DEVICE_HW_UUID: EVENT_PUSH_DEVICE_HW_UUID,
    EVENT_GET_DEVICE_INFO: EVENT_PUSH_DEVICE_INFO,
    EVENT_GET_DEVICE_NAME: EVENT_PUSH_DEVICE_NAME,
    EVENT_GET_DSP_UI_CONFIG: EVENT_PUSH_DSP_UI_CONFIG,
    EVENT_GET_EXPERIENCE_ADVANCED_SETTINGS: EVENT_PUSH_EXPERIENCE_ADVANCED_SETTINGS,
    EVENT_GET_EXTENDED_OUTPUT_DEVICES: EVENT_PUSH_EXTENDED_OUTPUT_DEVICES,
    EVENT_GET_INFINITY_PLAYBACK: EVENT_PUSH_INFINITY_PLAYBACK,
    EVENT_GET_INFO_NETWORK: EVENT_PUSH_INFO_NETWORK,
    EVENT_GET_INFO_SHARE: EVENT_PUSH_INFO_SHARE,
    EVENT_GET_INPUT_SOURCES: EVENT_PUSH_INPUT_SOURCES,
    EVENT_GET_INSTALLED_PLUGINS: EVENT_PUSH_INSTALLED_PLUGINS,
    EVENT_GET_LAST_PUSHED_BROWSE_LIBRARY: EVENT_PUSH_BROWSE_LIBRARY,
    EVENT_GET_LIST_SHARES: EVENT_PUSH_LIST_SHARES,
    EVENT_GET_MENU_ITEMS: EVENT_PUSH_MENU_ITEMS,
    EVENT_GET_MULTIROOM: EVENT_PUSH_MULTIROOM,
    EVENT_GET_MULTI_ROOM_DEVICES: EVENT_PUSH_MULTI_ROOM_DEVICES,
    EVENT_GET_MY_COLLECTION_STATS: EVENT_PUSH_MY_COLLECTION_STATS,
    EVENT_GET_MY_MUSIC_PLUGINS: EVENT_PUSH_MY_MUSIC_PLUGINS,
    EVENT_GET_NETWORK_SHARES_DISCOVERY: EVENT_PUSH_NETWORK_SHARES_DISCOVERY,
    EVENT_GET_OUTPUT_DEVICES: EVENT_PUSH_OUTPUT_DEVICES,
    EVENT_GET_PLAYLIST_CONTENT: EVENT_PUSH_PLAYLIST_CONTENT,
    EVENT_GET_PRIVACY_SETTINGS: EVENT_PUSH_PRIVACY_SETTINGS,
    EVENT_GET_QUEUE: EVENT_PUSH_QUEUE,
    EVENT_GET_SHUTDOWN_OR_STANDBY_MODE: EVENT_PUSH_SHUTDOWN_OR_STANDBY_MODE,
    EVENT_GET_SLEEP: EVENT_PUSH_SLEEP,
    EVENT_GET_STATE: EVENT_PUSH_STATE,
    EVENT_GET_SYSTEM_INFO: EVENT_PUSH_SYSTEM_INFO,
    EVENT_GET_SYSTEM_VERSION: EVENT_PUSH_SYSTEM_VERSION,
    EVENT_GET_UI_CONFIG: EVENT_PUSH_UI_CONFIG,
    EVENT_GET_UI_SETTINGS: EVENT_PUSH_UI_SETTINGS,
    EVENT_GET_UPDATER_CHANNEL: EVENT_PUSH_UPDATER_CHANNEL,
    EVENT_GET_WIRELESS_NETWORKS: EVENT_PUSH_WIRELESS_NETWORKS,
    EVENT_GET_WIRELESS_NETWORKS_CACHE: EVENT_PUSH_WIRELESS_NETWORKS_CACHE,
    EVENT_GO_TO: EVENT_PUSH_BROWSE_LIBRARY,
    EVENT_LIST_PLAYLIST: EVENT_PUSH_LIST_PLAYLIST,
    EVENT_PINGER: EVENT_PONGER,
    EVENT_PLUGIN_MANAGER: EVENT_PUSH_INSTALLED_PLUGINS,
    EVENT_SEARCH: EVENT_PUSH_BROWSE_LIBRARY,
    EVENT_SET_MULTIROOM: EVENT_PUSH_MULTIROOM,
    EVENT_SUPER_SEARCH: EVENT_PUSH_BROWSE_LIBRARY,
    EVENT_UPDATE_CHECK: EVENT_UPDATE_READY_FOR_DAEMON,
    EVENT_UPDATE_CHECK_CACHE: EVENT_UPDATE_READY_CACHE,
}
"""The event each read waits for, keyed by the event it emits.

``search`` and ``browseLibrary`` share their answer, which is why a client serializes its
reads: two of them in flight at once could take each other's result."""

UPDATE_CHECK_TIMEOUT = 60.0
"""Seconds an update check is waited for at least: the host asks its updater, which is slow."""

UPDATE_SETTINGS_ENDPOINT = "system_controller/system"
"""The plugin whose method saves the update settings, as the method call names it."""

UPDATE_SETTINGS_METHOD = "saveUpdateSettings"
"""The method of the system plugin saving the update settings."""

UPDATE_WINDOW_IDS = ("automatic_updates_start_time", "automatic_updates_stop_time")
"""The settings of the automatic update window, which saving the update settings wants too."""

USB_BROWSE_URI = "music-library/USB"
"""The URI of the USB music source, which lists the attached drives as its folders."""

VOLUME_DOWN = "-"
"""The volume argument lowering the level by one step of the host."""

VOLUME_UP = "+"
"""The volume argument raising the level by one step of the host."""


class VolumioWebSocketCommon(VolumioCommon):
    """The transport-independent half of a WebSocket API client for Volumio.

    The clients inherit from this class rather than instantiating it: it names the events
    their requests emit and the answers they wait for, builds the payloads those events
    carry, and owns the messages they log and raise, leaving them only the connection.
    """

    _CLIENT_DESCRIPTION: str = "WebSocket API client"
    """The name a client logs itself under while initializing."""

    def _alarm_added(
        self, alarms: list[Alarm], name: str, time: str, playlist: str, enabled: bool
    ) -> tuple[list[Alarm], Alarm]:
        """Build the set of alarms with one more, numbered by its position as the host does.

        Args:
            alarms: The alarms the host holds
            name: The name of the alarm
            time: The time it goes off, as :meth:`_alarm_time` rendered it
            playlist: The name of the playlist it plays
            enabled: Whether the alarm is armed

        Returns:
            The alarms to send back, and the one added (with identifier 0 when the host
            held none)
        """
        alarm = Alarm.from_raw(
            {
                "id": len(alarms),
                "name": name,
                "enabled": enabled,
                "time": time,
                "playlist": playlist,
            }
        )
        return [*alarms, alarm], alarm

    def _alarm_removed(self, alarms: list[Alarm], alarm_id: int) -> list[Alarm]:
        """Build the set of alarms without one.

        Args:
            alarms: The alarms the host holds
            alarm_id: The identifier of the alarm to drop

        Returns:
            The alarms to send back

        Raises:
            ValueError: If no alarm has the identifier
        """
        kept = [alarm for alarm in alarms if alarm.id != alarm_id]
        if len(kept) == len(alarms):
            self._fail_no_alarm(alarm_id)
        return kept

    def _alarm_time(self, time: str) -> str:
        """Check a time of day as ``"HH:MM"``, and render it as the host reads it.

        A Volumio host reads the time of an alarm as a date-time, keeping its hour and
        minute in its own time zone: the time is rendered on a fixed date as an ISO
        date-time without offset, which the host takes as its local time.

        Args:
            time: The time to check

        Returns:
            The time, as the alarm payload carries it

        Raises:
            ValueError: If the time is not a time of day as ``"HH:MM"``
        """
        hours, separator, minutes = time.partition(":")
        valid = (
            bool(separator)
            and hours.isdigit()
            and minutes.isdigit()
            and len(minutes) == 2
            and int(hours) < 24
            and int(minutes) < 60
        )
        if not valid:
            self._log_warning(f'Refusing the alarm time "{time}"')
            raise ValueError(f'The alarm time must be a time of day as "HH:MM", got "{time}"')
        return f"{ALARM_TIME_DATE}T{int(hours):02d}:{minutes}:00"

    def _alarm_toggled(self, alarms: list[Alarm], alarm_id: int, enabled: bool) -> list[Alarm]:
        """Build the set of alarms with one armed or disarmed.

        Args:
            alarms: The alarms the host holds
            alarm_id: The identifier of the alarm to arm or disarm
            enabled: Whether the alarm is armed

        Returns:
            The alarms to send back

        Raises:
            ValueError: If no alarm has the identifier
        """
        if all(alarm.id != alarm_id for alarm in alarms):
            self._fail_no_alarm(alarm_id)
        return [
            alarm.model_copy(update={"enabled": enabled}) if alarm.id == alarm_id else alarm
            for alarm in alarms
        ]

    def _alarms_payload(self, alarms: list[Alarm]) -> list[dict[str, Any]]:
        """Build the payload replacing the whole set of alarms.

        Args:
            alarms: The alarms to keep

        Returns:
            The payload the alarm event carries
        """
        return [alarm.model_dump(by_alias=True, exclude_none=True) for alarm in alarms]


    def _audio_output_listed(self, outputs: dict[str, Any], output_id: str) -> dict[str, Any]:
        """Pick one audio output out of those the host lists.

        The host acts on an output only when sent the entry it listed, kind and host
        name included: the play, pause, and volume events carry that entry.

        Args:
            outputs: The audio outputs the host lists, as :attr:`audio_outputs` reads them
            output_id: The identifier of the output

        Returns:
            The entry of the output, as the host listed it

        Raises:
            ValueError: If no output has the identifier
        """
        for output in outputs.get("availableOutputs") or []:
            if isinstance(output, dict) and output.get("id") == output_id:
                return dict(output)
        self._fail_no_audio_output(output_id)

    def _audio_output_payload(self, output_id: str) -> dict[str, str]:
        """Build the payload naming one audio output of the host.

        Args:
            output_id: The identifier of the output

        Returns:
            The payload the enable and disable events carry
        """
        return {"id": output_id}

    def _audio_output_volume_payload(self, output: dict[str, Any], volume: int) -> dict[str, Any]:
        """Build the payload setting the volume of one audio output.

        The host refuses the payload without a mute flag, and reads the kind and the
        host name of the output: the payload carries what its user interface sends.

        Args:
            output: The entry of the output, as the host listed it
            volume: The volume level to set on it, already checked

        Returns:
            The payload the volume event carries
        """
        payload = {key: output[key] for key in ("host", "id", "isSelf", "type") if key in output}
        return {**payload, "mute": False, "volume": volume}

    def _background_color_payload(self, color: str) -> dict[str, str]:
        """Build the payload making a solid colour the background.

        Args:
            color: The colour, hexadecimal with three or six digits (e.g., ``"#000"``)

        Returns:
            The payload the background event carries

        Raises:
            ValueError: If the colour is not hexadecimal
        """
        if not re.fullmatch(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})", color):
            self._log_warning(f'Refusing the background colour "{color}"')
            raise ValueError(
                f'The background colour must be hexadecimal, like "#000" or "#1a2b3c", '
                f'got "{color}"'
            )
        return {"color": color}

    def _background_listed(self, backgrounds: dict[str, Any], name: str) -> dict[str, Any]:
        """Pick one background out of those the host lists.

        The host applies a background only when sent the entry it listed, path
        included: the background event carries that entry.

        Args:
            backgrounds: The backgrounds the host lists, as :attr:`backgrounds` reads them
            name: The name of the background

        Returns:
            The entry of the background, as the host listed it

        Raises:
            ValueError: If no background has the name
        """
        for background in backgrounds.get("available") or []:
            if isinstance(background, dict) and background.get("name") == name:
                return dict(background)
        self._fail_no_background(name)

    def _backup_payload(self, kind: str) -> dict[str, str]:
        """Build the payload asking for a backup of one kind.

        A Volumio host answers nothing to a kind it does not know, so the kind is checked
        before sending.

        Args:
            kind: The kind of backup, one of :data:`BACKUP_KINDS`

        Returns:
            The payload the backup event carries

        Raises:
            ValueError: If the kind is not one a Volumio host reads
        """
        if kind not in BACKUP_KINDS:
            self._log_warning(f'Refusing the unknown backup kind "{kind}"')
            kinds = ", ".join(BACKUP_KINDS)
            raise ValueError(f'The backup kind must be one of {kinds}, got "{kind}"')
        return {"type": kind}

    def _browse_payload(self, uri: str | None) -> dict[str, str]:
        """Build the payload browsing a URI.

        Args:
            uri: The URI to browse, the root when not given

        Returns:
            The payload the browse event carries
        """
        browsed = uri if uri is not None else "/"
        self._log_debug(f'Browsing "{browsed}"')
        return {"uri": browsed}

    def _cue_payload(self, uri: str, number: int, service: str | None = None) -> dict[str, Any]:
        """Build the payload naming a track inside a cue sheet.

        Args:
            uri: The URI of the cue sheet
            number: The position of the track inside the cue sheet
            service: The service the URI belongs to, derived from it when not given

        Returns:
            The payload the cue events carry
        """
        return {
            "number": number,
            "service": service if service is not None else self._uri_service(uri),
            "uri": uri,
        }

    @property
    def _endpoint_description(self) -> str:
        """The base URL a failing connection names as unreachable."""
        return self.host_configuration.websocket_base_url

    def _fail_bad_update_hour(self, hour: int) -> NoReturn:
        """Refuse an hour outside the day for the automatic update window.

        Args:
            hour: The hour refused

        Raises:
            ValueError: Always
        """
        self._log_warning(f"Refusing the automatic update hour {hour}")
        raise ValueError(f"The automatic update hours must be between 0 and 23, got {hour}")

    def _fail_bad_wireless_password(self) -> NoReturn:
        """Refuse a wireless password the host would not save.

        Raises:
            ValueError: Always
        """
        self._log_warning("Refusing a wireless password the host would not save")
        raise ValueError(
            "The wireless password must be a WPA passphrase of 8 to 63 characters, or a "
            "WEP key of 5, 13, or 16 characters, or of 10, 26, or 32 hexadecimal digits"
        )

    def _fail_dialog(self, event: str, dialog: object) -> NoReturn:
        """Refuse a dialog the host pushed in place of the answer to a read.

        A Volumio host answers some reads with a dialog for its user interface when it
        cannot serve them: the plugin store, for instance, wants a MyVolumio login.

        Args:
            event: The event the host was answering
            dialog: What the dialog event carried, a ``title`` and a ``message`` when
                an object

        Raises:
            VolumioAPIError: Always
        """
        title, message = "", ""
        if isinstance(dialog, dict):
            title = re.sub(r"<[^>]+>", "", str(dialog.get("title", "")))
            message = re.sub(r"<[^>]+>", "", str(dialog.get("message", "")))
        reason = f'The host answered "{event}" with a dialog: "{title}" "{message}"'
        self._log_warning(reason)
        raise VolumioAPIError(reason)

    def _fail_emit(self, event: str, error: Exception) -> NoReturn:
        """Report that an event could not be sent to the Volumio instance.

        Args:
            event: The event that could not be sent
            error: The transport failure being translated

        Raises:
            VolumioConnectionError: Always
        """
        self._log_warning(f'Cannot emit "{event}" to the Volumio API: {error}')
        raise VolumioConnectionError(
            f'Failed to emit "{event}" to Volumio instance at '
            f"{self._endpoint_description}: {error}"
        ) from error

    def _fail_no_alarm(self, alarm_id: int) -> NoReturn:
        """Refuse to act on an alarm the host does not hold.

        Args:
            alarm_id: The identifier no alarm has

        Raises:
            ValueError: Always
        """
        self._log_warning(f"No alarm has the identifier {alarm_id}")
        raise ValueError(f"No alarm has the identifier {alarm_id}")


    def _fail_no_audio_output(self, output_id: str) -> NoReturn:
        """Refuse to act on an audio output the host does not list.

        Args:
            output_id: The identifier no output has

        Raises:
            ValueError: Always
        """
        self._log_warning(f'No audio output has the identifier "{output_id}"')
        raise ValueError(f'No audio output has the identifier "{output_id}"')

    def _fail_no_background(self, name: str) -> NoReturn:
        """Refuse to act on a background the host does not list.

        Args:
            name: The name no background has

        Raises:
            ValueError: Always
        """
        self._log_warning(f'No background is named "{name}"')
        raise ValueError(f'No background is named "{name}"')

    def _fail_no_music_source(self, name: str) -> NoReturn:
        """Refuse to act on a music source the host does not list.

        Args:
            name: The name no source has

        Raises:
            ValueError: Always
        """
        self._log_warning(f'No music source is named "{name}"')
        raise ValueError(f'No music source is named "{name}"')

    def _fail_no_output_device(self, device_id: str) -> NoReturn:
        """Refuse to act on an output device the host does not list.

        Args:
            device_id: The identifier no device has

        Raises:
            ValueError: Always
        """
        self._log_warning(f'No output device has the identifier "{device_id}"')
        raise ValueError(f'No output device has the identifier "{device_id}"')

    def _fail_no_response(self, event: str, response_event: str, waited: float) -> NoReturn:
        """Report that a Volumio instance did not answer an event in time.

        Args:
            event: The event that was emitted
            response_event: The event its answer was awaited on
            waited: The number of seconds the read waited

        Raises:
            VolumioConnectionError: Always
        """
        self._log_warning(
            f'The Volumio API did not answer "{event}" with "{response_event}" '
            f"within {waited} seconds"
        )
        raise VolumioConnectionError(
            f'Volumio instance at {self._endpoint_description} did not answer "{event}" '
            f'with "{response_event}" within {waited} seconds'
        )

    def _fail_no_update_window(self) -> NoReturn:
        """Refuse to save the update settings when the host does not report its window.

        Raises:
            ValueError: Always
        """
        self._log_warning("The host does not report the automatic update window")
        raise ValueError("The host does not report the automatic update window")

    def _fail_not_connected(self, action: str) -> NoReturn:
        """Report that an operation needs a connection the client does not have.

        Args:
            action: What the client was asked to do

        Raises:
            VolumioConnectionError: Always
        """
        self._log_warning(f"Refusing to {action} while not connected")
        raise VolumioConnectionError(
            f"Not connected to the Volumio WebSocket API at {self._endpoint_description}"
        )

    def _favourite_payload(
        self,
        uri: str,
        title: str | None = None,
        service: str | None = None,
        albumart: str | None = None,
    ) -> dict[str, str]:
        """Build the payload naming an item of the favourites.

        Args:
            uri: The URI of the item
            title: The title to show for it, when known
            service: The service the URI belongs to, derived from it when not given
            albumart: The URL of the cover to show for it, when known

        Returns:
            The payload the favourite events carry
        """
        payload = {
            "service": service if service is not None else self._uri_service(uri),
            "uri": uri,
        }
        if title is not None:
            payload["title"] = title
        if albumart is not None:
            payload["albumart"] = albumart
        return payload

    def _goto_payload(self, kind: str, value: str) -> dict[str, str]:
        """Build the payload browsing to the artist or the album of what is playing.

        Args:
            kind: What to browse to (``"artist"`` or ``"album"``)
            value: The name to browse to

        Returns:
            The payload the goto event carries
        """
        return {"type": kind, "value": value}

    def _index_payload(self, index: int) -> dict[str, int]:
        """Build the payload naming a position of the queue.

        Args:
            index: The position, 0-based

        Returns:
            The payload the event carries

        Raises:
            ValueError: If the position is negative
        """
        self._check_play_index(index)
        return {"value": index}

    def _mode_payload(self, value: bool) -> dict[str, bool]:
        """Build the payload setting a playback mode.

        Args:
            value: True to enable the mode, False to disable it

        Returns:
            The payload the mode event carries
        """
        return {"value": value}

    def _move_payload(self, source: int, target: int) -> dict[str, int]:
        """Build the payload moving a track to another position of the queue.

        Args:
            source: The position the track is at, 0-based
            target: The position to move it to, 0-based

        Returns:
            The payload the move event carries

        Raises:
            ValueError: If either position is negative
        """
        self._check_play_index(source)
        self._check_play_index(target)
        return {"from": source, "to": target}


    def _music_source_toggled(
        self, sources: list[Any], name: str, enabled: bool
    ) -> dict[str, Any]:
        """Build the payload enabling or disabling one music source.

        The host reads the category and the kind of the source beside its name: the
        payload is the entry the host listed, with the flag replaced.

        Args:
            sources: The music sources the host lists, as :attr:`music_sources` reads them
            name: The name of the source
            enabled: Whether the source is enabled

        Returns:
            The payload the event carries

        Raises:
            ValueError: If no source has the name
        """
        for source in sources:
            if isinstance(source, dict) and source.get("name") == name:
                return {**source, "enabled": enabled}
        self._fail_no_music_source(name)

    def _output_device_payload(self, devices: dict[str, Any], device_id: str) -> dict[str, Any]:
        """Build the payload choosing the output device of the host.

        The host reads the device as its setup wizard sends it: the identifier and the
        name of a sound card, or those of an I2S DAC under their own key.

        Args:
            devices: The output devices the host lists, as :attr:`output_devices` reads them
            device_id: The identifier of the device, a sound card or an I2S DAC

        Returns:
            The payload the output device event carries

        Raises:
            ValueError: If no device has the identifier
        """
        cards = (devices.get("devices") or {}).get("available") or []
        for card in cards:
            if isinstance(card, dict) and card.get("id") == device_id:
                return {
                    "i2s": False,
                    "output_device": {"value": device_id, "label": card.get("name")},
                }
        dacs = (devices.get("i2s") or {}).get("available") or []
        for dac in dacs:
            if isinstance(dac, dict) and dac.get("id") == device_id:
                return {
                    "i2s": True,
                    "i2sid": {"value": device_id, "label": dac.get("name")},
                    "output_device": {"value": I2S_OUTPUT_DEVICE_VALUE, "label": dac.get("name")},
                }
        self._fail_no_output_device(device_id)

    def _play_next_payload(
        self, uri: str, title: str | None = None, album: str | None = None
    ) -> dict[str, str]:
        """Build the payload queueing an item right after the current track.

        Args:
            uri: The URI to queue
            title: The title to show for it, when known
            album: The album to show for it, when known

        Returns:
            The payload the play-next event carries
        """
        payload = {"uri": uri}
        if title is not None:
            payload["title"] = title
        if album is not None:
            payload["album"] = album
        return payload

    def _play_payload(self, position: int | QueueTrack | None) -> dict[str, int] | None:
        """Build the payload starting the playback, optionally at a queue position.

        Args:
            position: Optional position in the queue to play (0-indexed), or a track
                of the queue

        Returns:
            The payload the play event carries, or None to play where the queue stands

        Raises:
            ValueError: If the given track does not know its position in the queue
        """
        played = self._play_position(position)
        if played is None:
            return None
        return {"value": played}

    def _playlist_item_payload(
        self, name: str | Playlist, uri: str, service: str | None = None
    ) -> dict[str, str]:
        """Build the payload naming an item inside a saved playlist.

        Args:
            name: The name of the playlist, or the playlist itself
            uri: The URI of the item
            service: The service the URI belongs to, derived from it when not given

        Returns:
            The payload the playlist item events carry

        Raises:
            ValueError: If the given playlist has no name
        """
        return {
            "name": self._playlist_name(name),
            "service": service if service is not None else self._uri_service(uri),
            "uri": uri,
        }

    def _playlist_payload(self, name: str | Playlist) -> dict[str, str]:
        """Build the payload starting the playback of a saved playlist.

        Args:
            name: The name of the playlist to play, or the playlist itself

        Returns:
            The payload the playlist event carries

        Raises:
            ValueError: If the given playlist has no name
        """
        return {"name": self._playlist_name(name)}

    def _plugin_payload(self, category: str, name: str) -> dict[str, str]:
        """Build the payload naming a plugin of the host.

        Args:
            category: The category the plugin belongs to (e.g., ``"music_service"``)
            name: The name of the plugin

        Returns:
            The payload the plugin events carry
        """
        return {"category": category, "name": name}


    def _plugin_status_payload(
        self, category: str, name: str, started: bool | None = None
    ) -> dict[str, str]:
        """Build the payload switching a plugin, as the switch events read it.

        The enable, disable, and status events read the name of the plugin under
        ``plugin``, unlike the other plugin events.

        Args:
            category: The category the plugin belongs to
            name: The name of the plugin
            started: Whether the plugin is started, when the event carries a status

        Returns:
            The payload the switch events carry
        """
        payload = {"category": category, "plugin": name}
        if started is not None:
            payload["status"] = PLUGIN_STATUS_STARTED if started else PLUGIN_STATUS_STOPPED
        return payload

    def _response_event(self, event: str) -> str:
        """Return the event a read waits for after emitting one.

        Args:
            event: The event about to be emitted

        Returns:
            The event carrying its answer

        Raises:
            ValueError: If the event is not one a Volumio host answers
        """
        if event not in RESPONSE_EVENTS:
            self._log_warning(f'Refusing to wait for an answer to "{event}"')
            raise ValueError(
                f"The Volumio API answers no {event!r} event: emit it, or name the "
                f"event carrying its answer"
            )
        return RESPONSE_EVENTS[event]

    def _search_payload(self, query: str) -> dict[str, str]:
        """Build the payload searching the sources of the Volumio instance.

        Args:
            query: The text to search for

        Returns:
            The payload the search event carries
        """
        return {"value": query}

    def _seek_payload(self, value: int) -> int:
        """Build the payload seeking to an absolute position.

        The seek event carries the number of seconds itself, not an object holding it.

        Args:
            value: The position to seek to, in seconds

        Returns:
            The payload the seek event carries
        """
        return value

    def _sleep_payload(self, delay: timedelta | None) -> dict[str, Any]:
        """Build the payload arming or disarming the sleep timer.

        A Volumio host reads the time of a sleep timer as a delay from now, not as a
        clock time, so a duration is rendered to the ``"H:MM"`` it expects.

        Args:
            delay: How long from now the host should stop, or None to disarm the timer

        Returns:
            The payload the sleep event carries

        Raises:
            ValueError: If the delay is negative
        """
        if delay is None:
            return {"enabled": False, "time": "0:00"}
        if delay < timedelta(0):
            self._log_warning(f"Refusing the negative sleep delay {delay}")
            raise ValueError(f"The sleep delay must not be negative, got {delay}")
        minutes = int(delay.total_seconds() // 60)
        return {"enabled": True, "time": f"{minutes // 60}:{minutes % 60:02d}"}

    def _update_window_given(
        self, start_time: int | None, end_time: int | None
    ) -> dict[str, dict[str, int]]:
        """Build the window settings out of the hours given, as the save wants them.

        Args:
            start_time: The hour the window opens, or None to keep the one of the host
            end_time: The hour the window closes, or None to keep the one of the host

        Returns:
            The settings of the hours given, each as the value and label pair the host
            stores

        Raises:
            ValueError: If an hour is not between 0 and 23
        """
        window: dict[str, dict[str, int]] = {}
        for key, hour in zip(UPDATE_WINDOW_IDS, (start_time, end_time), strict=True):
            if hour is None:
                continue
            if not 0 <= hour <= 23:
                self._fail_bad_update_hour(hour)
            window[key] = {"value": hour, "label": hour}
        return window

    def _update_window_listed(self, sections: list[dict[str, Any]]) -> dict[str, Any]:
        """Pick the window settings out of the configuration page of the system plugin.

        The method saving the update settings wants the window too, which the page
        reports as it stands.

        Args:
            sections: The sections of the page, as :meth:`get_plugin_config` reads them

        Returns:
            The settings of the window, as the host listed them

        Raises:
            ValueError: If the page does not report the window
        """
        window: dict[str, Any] = {}
        for section in sections:
            for entry in section.get("content") or []:
                if isinstance(entry, dict) and entry.get("id") in UPDATE_WINDOW_IDS:
                    window[entry["id"]] = entry.get("value")
        if any(not isinstance(window.get(key), dict) for key in UPDATE_WINDOW_IDS):
            self._fail_no_update_window()
        return window

    def _volume_payload(self, value: int) -> int:
        """Build the payload setting the volume to an absolute level.

        The volume event carries the level itself, not an object holding it.

        Args:
            value: The volume level, an integer between 0 and 100 (inclusive)

        Returns:
            The payload the volume event carries

        Raises:
            ValueError: If the volume level is out of range
        """
        self._check_volume_level(value)
        return value

    def _web_radio_payload(self, name: str, uri: str | None = None) -> dict[str, str]:
        """Build the payload naming a Web radio of the user.

        Args:
            name: The name of the Web radio
            uri: The URL it streams from, when the event needs it

        Returns:
            The payload the Web radio events carry
        """
        payload = {"name": name}
        if uri is not None:
            payload["uri"] = uri
        return payload

    def _wireless_password_checked(self, password: str) -> str:
        """Check a wireless password the way the host does before it saves a network.

        Args:
            password: The password of the network

        Returns:
            The password, unchanged

        Raises:
            ValueError: If the password is neither a WPA passphrase nor a WEP key
        """
        length = len(password)
        is_hex = all(char in string.hexdigits for char in password)
        wep = length in (10, 26, 32) if is_hex else length in (5, 13, 16)
        wpa = 8 <= length <= 63
        hashed = length == 70 and "hash::" in password
        if not (wep or wpa or hashed):
            self._fail_bad_wireless_password()
        return password

    def _wireless_security_listed(self, networks: dict[str, Any], ssid: str) -> str | None:
        """Pick the security of a wireless network out of those the host sees.

        The host hashes a WPA passphrase only when told the security of the network,
        as its user interface does; a network it does not see has none to tell.

        Args:
            networks: The wireless networks the host sees, as :attr:`wireless_networks`
                reads them
            ssid: The name of the network

        Returns:
            The security of the network, or None when the host does not see it
        """
        for network in networks.get("available") or []:
            if isinstance(network, dict) and network.get("ssid") == ssid:
                security = network.get("security")
                return security if isinstance(security, str) else None
        return None
