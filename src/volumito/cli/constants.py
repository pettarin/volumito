"""Module constants for the volumito CLI.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

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

LISTEN_ENDPOINT_ERROR = "The endpoint must start with a slash."
"""Error message when "notifications listen" is given an endpoint without a leading slash."""

MPD_PORT_VOLUMIO_3 = 6599
"""MPD port used by Volumio 3 (major version below 4)."""

MPD_PORT_VOLUMIO_4 = 6600
"""MPD port used by Volumio 4 (major version 4 and above)."""

MUTUALLY_EXCLUSIVE_CONFIGURATION_ERROR = (
    "Options -c/--configuration-file and --ignore-configuration-file are mutually exclusive."
)
"""Error message when the configuration-file selection options are combined."""

MUTUALLY_EXCLUSIVE_CREATE_ERROR = (
    "Options -d/--output-directory and -f/--output-file are mutually exclusive."
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

MUTUALLY_EXCLUSIVE_UNREGISTER_ERROR = (
    "Option -a/--all and the URL argument are mutually exclusive."
)
"""Error message when "notifications unregister" combines --all with a URL."""

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
    "artist",
    "album",
    "volumeNumber",
    "tracknumber",
    "duration",
]
"""Short fields list for the "queue list" command."""

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

SHORT_FORMAT_FIELDS_ZONES_LIST = [
    "host",
    "name",
    "isSelf",
    "state",
]
"""Short fields list for the "zones list" command."""

SHORT_FORMAT_FIELDS_ZONES_LIST_EXCLUDED_FROM_STATE = [
    "albumart",
]
"""Keys of the "state" subdictionary omitted by the short fields of "zones list"."""

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

UNREGISTER_ARGUMENT_ERROR = "Expected a URL argument, or the -a/--all option."
"""Error message when "notifications unregister" is given neither a URL nor --all."""
