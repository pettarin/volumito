"""Module constants for the volumito CLI.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

API_CLIENTS = [
    "rest_synchronous",
    "rest_asynchronous",
    "websocket_synchronous",
    "websocket_asynchronous",
]
"""Accepted values of the -C/--api-client option, in the order --help lists them."""

API_CLIENTS_WEBSOCKET = [
    "websocket_asynchronous",
    "websocket_synchronous",
]
"""The -C/--api-client values selecting a WebSocket API client."""

API_CLIENT_REST_ASYNCHRONOUS = "rest_asynchronous"
"""The -C/--api-client value selecting the asynchronous REST API client."""

API_CLIENT_REST_SYNCHRONOUS = "rest_synchronous"
"""The -C/--api-client value selecting the synchronous REST API client."""

API_CLIENT_WEBSOCKET_ASYNCHRONOUS = "websocket_asynchronous"
"""The -C/--api-client value selecting the asynchronous WebSocket API client."""

API_CLIENT_WEBSOCKET_SYNCHRONOUS = "websocket_synchronous"
"""The -C/--api-client value selecting the synchronous WebSocket API client."""

BROWSE_KINDS_ERROR = (
    "Expected the --result-kinds, --albums-only, --artists-only, --playlists-only, "
    "and --tracks-only options to agree on the kinds to keep."
)
"""Error message when "collection browse" is asked for two different kinds of result."""

DEFAULT_API_CLIENT = "rest_synchronous"
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

FILE_WRITE_CHUNK_SIZE = 8192
"""Default chunk size in bytes when writing files."""

MAX_HTTP_HEADERS = 10000
"""Maximum number of headers accepted in an HTTP response (the Python default is 100)."""

MPD_PORT_VOLUMIO_3 = 6599
"""MPD port used by Volumio 3 (major version below 4)."""

MPD_PORT_VOLUMIO_4 = 6600
"""MPD port used by Volumio 4 (major version 4 and above)."""

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

PROGRAM_NAME = "volumito"
"""Name of the CLI tool, heading the command tree."""

REGISTER_ARGUMENT_ERROR = "Expected a URL argument, or the -A/--autocompose-url option."
"""Error message when "notification register" is given neither a URL nor --autocompose-url."""

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

SHORT_FORMAT_FIELDS_MULTIROOM_ZONES = [
    "host",
    "name",
    "isSelf",
    "state",
]
"""Short fields list for the "multiroom zones" command."""

SHORT_FORMAT_FIELDS_MULTIROOM_ZONES_EXCLUDED_FROM_STATE = [
    "albumart",
]
"""Keys of the "state" subdictionary omitted by the short fields of "multiroom zones"."""

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
"""Short fields list for the "track info" command."""

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
