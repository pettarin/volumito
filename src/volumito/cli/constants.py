"""Module constants for the volumito CLI.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

ALARM_FILE_ERROR = "Expected FILE to hold a JSON list of alarm objects."
"""Error message when "system alarm set" is given a file of another shape."""

API_CLIENTS = [
    "synchronous_rest",
    "asynchronous_rest",
    "synchronous_websocket",
    "asynchronous_websocket",
]
"""Accepted values of the -C/--api-client option, in the order --help lists them."""

API_CLIENTS_WEBSOCKET = [
    "asynchronous_websocket",
    "synchronous_websocket",
]
"""The -C/--api-client values selecting a WebSocket API client."""

API_CLIENT_ASYNCHRONOUS_REST = "asynchronous_rest"
"""The -C/--api-client value selecting the asynchronous REST API client."""

API_CLIENT_ASYNCHRONOUS_WEBSOCKET = "asynchronous_websocket"
"""The -C/--api-client value selecting the asynchronous WebSocket API client."""

API_CLIENT_SHORT_FORMS = {
    "sync_rest": "synchronous_rest",
    "sr": "synchronous_rest",
    "async_rest": "asynchronous_rest",
    "ar": "asynchronous_rest",
    "sync_websocket": "synchronous_websocket",
    "sw": "synchronous_websocket",
    "async_websocket": "asynchronous_websocket",
    "aw": "asynchronous_websocket",
}
"""The short forms accepted by the -C/--api-client option, mapped to the values they stand for."""

API_CLIENT_SYNCHRONOUS_REST = "synchronous_rest"
"""The -C/--api-client value selecting the synchronous REST API client."""

API_CLIENT_SYNCHRONOUS_WEBSOCKET = "synchronous_websocket"
"""The -C/--api-client value selecting the synchronous WebSocket API client."""

BROWSE_ALONE_OPTIONS_ERROR = (
    "Expected the -b/--current-track-album, -a/--current-track-artist, --last, and --root "
    "options alone: without each other, the URI argument, and the -o/--offset option."
)
"""Error message when "collection browse" combines a standalone option with the other inputs."""

BROWSE_CURRENT_TRACK_ERROR = "The current track does not provide the {kind} to browse to."
"""Error message when "collection browse" is asked for metadata the current track lacks."""

BROWSE_KINDS_ERROR = (
    "Expected the --result-kinds, --albums-only, --artists-only, --playlists-only, "
    "and --tracks-only options to agree on the kinds to keep."
)
"""Error message when "collection browse" is asked for two different kinds of result."""

COLLECTION_UPDATE_MODES_ERROR = "Expected at most one of the --rescan and --thumbnails options."
"""Error message when "collection update" is asked for two refreshes at once."""

COLLECTION_UPDATE_URI_ERROR = (
    "Expected the URI argument only without the --rescan and --thumbnails options."
)
"""Error message when "collection update" is given a URI together with a refresh option."""

DEFAULT_API_CLIENT = "synchronous_rest"
"""Default value of the -C/--api-client option."""

DEFAULT_MANIFEST_FILE = "{output_directory}/manifest.json"
"""Default path template of the queue/playlist download manifest file."""

DEFAULT_NUMBER_RETRIES_NEXT_TRACK = 10
"""Default number of retries waiting for a queue track's metadata to become current."""

DEFAULT_REPLACE_CHARACTERS_IN_FILE_NAMES = " :"
"""Characters replaced by default in file names generated from the template."""

DEFAULT_REPLACE_CHARACTERS_IN_FILE_NAMES_WITH = "_"
"""Default replacement string for the characters replaced in generated file names."""

DEFAULT_STORY_ARGUMENT_TYPE = "autodetect"
"""Default value of the -T/--type option of the "story" subcommands."""

DEFAULT_VOLUMIO_VERSION = "4"
"""Default target Volumio version for the "configuration create" command."""

EVENT_PAYLOAD_ERROR = "Expected PAYLOAD to be JSON."
"""Error message when a "notification event" subcommand is given a payload that is not JSON."""

EXPERIENCE_VALUES = [
    "advanced",
    "simple",
]
"""Accepted values of the VALUE argument of the "system ui experience" command."""

FAVOURITE_KEPT_BY_SOURCE_INFO = (
    'The Volumio host did not list "{uri}" among its own favourites: a source with '
    "favourites of its own (Qobuz, Tidal) keeps them, browse them from its root."
)
"""Message when "collection favourite add" finds the favourite kept by its source."""

FAVOURITE_PLAY_NAME_ERROR = "Expected the NAME argument without --radio."
"""Error message when "collection favourite play" is given no name without --radio."""

FAVOURITE_RADIO_ADD_NOT_LISTED_ERROR = (
    'The Volumio host does not list "{uri}" among its radio favourites after the add.'
)
"""Error message when "collection favourite add --radio" finds the radio not listed."""

FAVOURITE_RADIO_OPTIONS_ERROR = "Expected the --service option only without --radio."
"""Error message when a "collection favourite" subcommand gives a Web radio a service."""

FAVOURITE_RADIO_TITLE_ERROR = (
    "Expected the --title option with --radio, unless URI is the name or the URL of a "
    'Web radio of the host ("collection radio list").'
)
"""Error message when "collection favourite add --radio" cannot name a Web radio."""

FAVOURITE_RADIO_UNKNOWN_ERROR = (
    'The Volumio host lists no radio favourite named, or streaming from, "{radio}".'
)
"""Error message when "collection favourite remove --radio" finds no such radio."""

FAVOURITE_REMOVE_STILL_LISTED_ERROR = (
    'The Volumio host still lists "{uri}" among its favourites after the removal: '
    "the URI may not match the one listed, or a MyVolumio cloud device may not save "
    "an empty list of favourites."
)
"""Error message when "collection favourite remove" finds the favourite still listed."""

FILE_WRITE_CHUNK_SIZE = 8192
"""Default chunk size in bytes when writing files."""

MAX_HTTP_HEADERS = 10000
"""Maximum number of headers accepted in an HTTP response (the Python default is 100)."""

MPD_PORT_VOLUMIO_3 = 6599
"""MPD port used by Volumio 3 (major version below 4)."""

MPD_PORT_VOLUMIO_4 = 6600
"""MPD port used by Volumio 4 (major version 4 and above)."""

MULTIROOM_SETTINGS_ERROR = (
    "Expected the SETTINGS argument to be a JSON object, or the path of a file holding one."
)
"""Error message when a "multiroom" subcommand is given settings of another shape."""

MUTUALLY_EXCLUSIVE_CONFIGURATION_ERROR = (
    "Options -c/--configuration-file and --ignore-configuration-file are mutually exclusive."
)
"""Error message when the configuration-file selection options are combined."""

MUTUALLY_EXCLUSIVE_CREATE_ERROR = (
    "Options -d/--output-directory and -o/--output-file are mutually exclusive."
)
"""Error message when the "configuration create" destination options are combined."""

MUTUALLY_EXCLUSIVE_CURRENT_TRACK_ERROR = (
    "Option --current-track and positional arguments are mutually exclusive."
)
"""Error message when a "story" subcommand combines --current-track with arguments."""

MUTUALLY_EXCLUSIVE_OUTPUT_ERROR = (
    "Options -d/--output-directory and -o/--output-file are mutually exclusive."
)
"""Error message when the download destination options are combined."""

MUTUALLY_EXCLUSIVE_REGISTER_ERROR = (
    "Option -A/--autocompose-url and the URL argument are mutually exclusive."
)
"""Error message when "notification register" combines --autocompose-url with a URL."""

MUTUALLY_EXCLUSIVE_UNREGISTER_ERROR = (
    "Options -a/--all, -A/--autocompose-url, and the URL argument are mutually exclusive."
)
"""Error message when "notification unregister" combines its ways of naming a URL."""

NOTIFICATION_ENDPOINT_ERROR = "The endpoint must start with a slash."
"""Error message when a "notification" subcommand is given an endpoint without a slash."""

NOTIFICATION_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S.%f"
"""strftime format of the UTC time a notification was received, trimmed to milliseconds."""

OUTPUT_DIRECTORY_PLACEHOLDER = "{output_directory}"
"""Placeholder in manifest file paths replaced with the expanded output directory."""

OUTPUT_DIRECTORY_REQUIRED_ERROR = "Option -d/--output-directory is required."
"""Error message when a command requiring the output directory is run without it."""

OUTPUT_DIRECTORY_TIMESTAMP_FORMAT = "%Y%m%d%H%M%S"
"""strftime format of the value replacing the timestamp placeholder in output directories."""

OUTPUT_DIRECTORY_TIMESTAMP_PLACEHOLDER = "{timestamp}"
"""Placeholder in output directory paths replaced with the current UTC timestamp."""

OUTPUT_FIELDS_ALL = "ALL"
"""The -L/--fields keyword selecting every field."""

OUTPUT_FIELDS_SHORT = "SHORT"
"""The -L/--fields keyword selecting the short field set."""

OUTPUT_FORMATS = [
    "json",
    "pretty",
    "raw",
    "table",
]
"""Accepted values of the -F/--format option."""

PLAY_VOLATILE_ERROR = "Expected a POSITION argument together with --volatile."
"""Error message when "playback play" is asked for the volatile source without a position."""

PLAYLIST_FILE_ERROR = 'Expected FILE to hold a JSON list of playlist items, each with a "uri".'
"""Error message when "playlist create" is given a file of another shape to import."""

PLAYLIST_REMOVE_ARGUMENTS_ERROR = (
    "Expected either a URI argument or the -p/--position option, and not both."
)
"""Error message when "playlist remove" is given neither a URI nor a position, or both."""

PLAYLIST_REMOVE_EMPTY_WARNING = (
    'The removal would leave the playlist "{name}" empty, which the Volumio host may '
    'refuse: to empty a playlist, delete it with "playlist delete" and create it again '
    'with "playlist create".'
)
"""Warning when "playlist remove" is asked to remove every item of a playlist."""

PLAYLIST_REMOVE_SERVICE_ERROR = (
    "Expected the --service option only together with a URI argument."
)
"""Error message when "playlist remove" is given a service with a position instead of a URI."""

PLUGIN_INSTALL_WAIT_INTERVAL = 5.0
"""Seconds between two looks at the installed plugins while waiting for an install."""

PLUGIN_INSTALL_WAIT_RETRIES = 120
"""Number of looks at the installed plugins while waiting for an install: ten minutes."""

PROGRAM_NAME = "volumito"
"""Name of the CLI tool, heading the command tree."""

QUEUE_ADD_ARGUMENTS_ERROR = (
    "Expected a single URI argument (several are accepted only with --by-uid)."
)
"""Error message when "queue add" is given several arguments without --by-uid."""

QUEUE_ADD_MODES_ERROR = (
    "Expected at most one of the --by-uid, --cue-track, --next, and --play options."
)
"""Error message when "queue add" is asked to add in two ways at once."""

QUEUE_ADD_NEXT_OPTIONS_ERROR = "Expected the --album and --title options only together with --next."
"""Error message when "queue add" is given the item details without --next."""

QUEUE_CUE_TRACK_SERVICE_ERROR = "Expected the --service option only together with --cue-track."
"""Error message when a "queue" subcommand is given a service without a cue track."""

RADIO_REMOVE_STILL_LISTED_ERROR = (
    'The Volumio host still lists the Web radio "{name}" after the removal: '
    "a MyVolumio cloud device does not save an empty list of Web radios."
)
"""Error message when "collection radio remove" finds the Web radio still listed."""

REGISTER_ARGUMENT_ERROR = "Expected a URL argument, or the -A/--autocompose-url option."
"""Error message when "notification register" is given neither a URL nor --autocompose-url."""

REPLACE_CUE_TRACK_ERROR = (
    "Expected the --cue-track option only together with --play, and without -p/--position."
)
"""Error message when "queue replace" combines a cue track with a position or --no-play."""

REPLACE_POSITION_ERROR = "Expected the -p/--position option only together with --play."
"""Error message when "queue replace" is asked for a position without playing."""

SEARCH_ARGUMENT_ERROR = (
    "Expected a QUERY argument, or one of the --album, --artist, --playlist, and --track options."
)
"""Error message when "collection search" is given nothing to search for."""

SEARCH_KINDS_ERROR = (
    "Expected the --result-kinds, --albums-only, --artists-only, --playlist, --playlists-only, "
    "and --tracks-only options to agree on the kinds to keep."
)
"""Error message when "collection search" is asked for two different kinds of result."""

SEARCH_LIMIT_ERROR ="Expected the -1/--best-result-only or the -l/--limit option, not both."
"""Error message when "collection search" is given two limits on the results."""

SEARCH_SERVICES = [
    "highresaudio",  # not verified
    "mpd",
    "qobuz",
    "soundcloud",    # not verified
    "spop",          # the Spotify plugin, not verified
    "tidal",         # not verified
    "webradio",
    "youtube2",      # the YouTube2 plugin, not verified
]
"""Accepted values of the --service option of the "collection search" command.

Only "mpd", "qobuz", and "webradio" are verified against a host: each value marked as not
verified is the name its plugin registers itself with, or a guess where the plugin is not
public.
"""

SHARE_EDIT_FIELDS_ERROR = (
    "Expected at least one of the --fstype, --name, --options, --password, --path, "
    "and --username options."
)
"""Error message when "system share edit" is given nothing to change."""

SHORT_FORMAT_FIELDS_COLLECTION_SOURCE_LIST = [
    "name",
    "prettyName",
    "category",
    "active",
    "enabled",
    "hasConfiguration",
]
"""Short fields list for the "collection source list" command."""

SHORT_FORMAT_FIELDS_MULTIROOM_INFO = [
    "host",
    "name",
    "isSelf",
    "state",
]
"""Short fields list for the "multiroom info" command."""

SHORT_FORMAT_FIELDS_MULTIROOM_INFO_EXCLUDED_FROM_STATE = [
    "albumart",
]
"""Keys of the "state" subdictionary omitted by the short fields of "multiroom info"."""

SHORT_FORMAT_FIELDS_PLAYER_STATE = [
    "status",
    "position",
    "title",
    "artist",
    "album",
    "duration",
    "seek",
    "volume",
    "mute",
    "trackType",
    "samplerate",
    "bitdepth",
    "channels",
]
"""Short fields list for the "playback status" command."""

# The track fields must stay in sync with SHORT_FORMAT_FIELDS_QUEUE_LIST
SHORT_FORMAT_FIELDS_PLAYLIST_CONTENT = [
    "position",
    "title",
    # The local files (the "mpd" service) report their title under "name"
    "name",
    "artist",
    "album",
    "volumeNumber",
    "tracknumber",
    "duration",
    "uri",
]
"""Short fields list for the "playlist content" command: the queue list ones, and the URI."""

SHORT_FORMAT_FIELDS_QUEUE_LIST = [
    "position",
    "title",
    # The local files (the "mpd" service) report their title under "name"
    "name",
    "artist",
    "album",
    "volumeNumber",
    "tracknumber",
    "duration",
]
"""Short fields list for the "queue list" command."""

# The track fields must stay in sync with SHORT_FORMAT_FIELDS_TRACK_INFO
SHORT_FORMAT_FIELDS_QUEUE_STATUS = [
    "track.position",
    "track.title",
    "track.artist",
    "track.album",
    "track.duration",
    "track.trackType",
    "track.samplerate",
    "track.bitdepth",
    "track.channels",
    "position",
    "length",
    "has_previous",
    "has_next",
]
"""Short fields list for the "queue status" command."""

SHORT_FORMAT_FIELDS_SYSTEM_ALARM_LIST = [
    "id",
    "name",
    "enabled",
    "time",
    "playlist",
]
"""Short fields list for the "system alarm list" command."""

SHORT_FORMAT_FIELDS_SYSTEM_AUDIO_OUTPUTS = [
    "id",
    "name",
    "type",
    "enabled",
    "volume",
]
"""Short fields list for the "system audio outputs" command."""

SHORT_FORMAT_FIELDS_SYSTEM_NETWORK_INFO = [
    "type",
    "ip",
    "status",
    "speed",
]
"""Short fields list for the "system network info" command."""

SHORT_FORMAT_FIELDS_SYSTEM_NETWORK_WIRELESS = [
    "ssid",
    "signal",
    "security",
    "configured",
]
"""Short fields list for the "system network wireless" command."""

SHORT_FORMAT_FIELDS_SYSTEM_PLUGIN_AVAILABLE = [
    "category",
    "name",
    "prettyName",
    "version",
    "installed",
    "updateAvailable",
    "url",
]
"""Short fields list for the "system plugin available" command printing the store."""

SHORT_FORMAT_FIELDS_SYSTEM_PLUGIN_LIST = [
    "category",
    "name",
    "prettyName",
    "version",
    "enabled",
    "active",
]
"""Short fields list for the "system plugin" commands printing the installed plugins."""

SHORT_FORMAT_FIELDS_SYSTEM_SHARE_LIST = [
    "id",
    "name",
    "path",
    "fstype",
    "size",
    "username",
    "options",
]
"""Short fields list for the "system share list" command."""

SHORT_FORMAT_FIELDS_SYSTEM_USB_LIST = [
    "title",
    "uri",
]
"""Short fields list for the "system usb list" command."""

SHORT_FORMAT_FIELDS_STORY = [
    "data.value",
]
"""Short fields list for the "story" subcommands."""

SHORT_FORMAT_FIELDS_TRACK_INFO = [
    "position",
    "title",
    "artist",
    "album",
    "duration",
    "trackType",
    "samplerate",
    "bitdepth",
    "channels",
]
"""Short fields list for the "queue track info" command."""

STORY_ARGUMENT_TYPES = [
    "autodetect",
    "mbid",
    "name",
]
"""Accepted values of the -T/--type option of the "story" subcommands."""

STORY_ARTIST_ALBUM_ARGUMENTS_ERROR = (
    "Expected ARTIST ALBUM arguments, or a single MBID argument."
)
"""Error message when the "story album"/"story credits" arguments cannot be resolved."""

STORY_ARTIST_ARGUMENT_ERROR = "Expected a NAME or MBID argument."
"""Error message when the "story artist" argument is missing."""

STORY_CURRENT_TRACK_METADATA_ERROR = "The current track does not provide the required metadata."
"""Error message when the current track lacks the metadata a "story" subcommand needs."""

UNREGISTER_ARGUMENT_ERROR = (
    "Expected a URL argument, or one of the -a/--all and -A/--autocompose-url options."
)
"""Error message when "notification unregister" is given no way of naming a URL."""

URI_FAVOURITES = "favourites"
"""The URI the Favourites browse source of a Volumio host lists the favourites at."""

URI_RADIO_FAVOURITES = "radio/favourites"
"""The URI the Web radio plugin of a Volumio host lists the radio favourites at."""

URI_WEB_RADIOS = "radio/myWebRadio"
"""The URI the Web radio plugin of a Volumio host lists the Web radios of the user at."""
