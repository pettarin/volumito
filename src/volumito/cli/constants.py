"""Module constants for the volumito CLI.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

DEFAULT_VOLUMIO_VERSION = "4"
"""Default target Volumio version for the "configuration create" command."""

FILE_WRITE_CHUNK_SIZE = 8192
"""Default chunk size in bytes when writing files."""

MPD_PORT_VOLUMIO_3 = 6599
"""MPD port used by Volumio 3 (major version below 4)."""

MPD_PORT_VOLUMIO_4 = 6600
"""MPD port used by Volumio 4 (major version 4 and above)."""

MUTUALLY_EXCLUSIVE_CREATE_ERROR = (
    "Options -d/--output-directory and -f/--output-file are mutually exclusive."
)
"""Error message when the "configuration create" destination options are combined."""

MUTUALLY_EXCLUSIVE_OUTPUT_ERROR = (
    "Options -d/--output-directory and -o/--output-file are mutually exclusive."
)
"""Error message when the download destination options are combined."""

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
    "title",
    "artist",
    "album",
    "duration",
    "position",
]
"""Short fields list for the "queue list" command."""

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

SHORT_FORMAT_FIELDS_ZONES_GET = [
    "host",
    "name",
    "isSelf",
    "state",
]
"""Short fields list for the "zones get" command."""

SHORT_FORMAT_FIELDS_ZONES_GET_EXCLUDED_FROM_STATE = [
    "albumart",
]
"""Keys of the "state" subdictionary omitted by the short fields of "zones get"."""
