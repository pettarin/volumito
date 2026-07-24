"""Module constants for the volumito CLI.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

# Default chunk size when writing files
FILE_WRITE_CHUNK_SIZE = 8192

# Error message when the "configuration create" destination options are combined
MUTUALLY_EXCLUSIVE_CREATE_ERROR = (
    "Options -d/--output-directory and -f/--output-file are mutually exclusive."
)

# Error message when the download destination options are combined
MUTUALLY_EXCLUSIVE_OUTPUT_ERROR = (
    "Options -o/--output-file and -d/--output-directory are mutually exclusive."
)

# Accepted values of the -F/--format option
OUTPUT_FORMATS = ["json", "pretty", "raw", "table"]

# Short fields list for the "playback status" command
PLAYER_STATE_SHORT_FIELDS = [
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

# Short fields list for the "queue list" command
QUEUE_LIST_SHORT_FIELDS = [
    "title",
    "artist",
    "album",
    "duration",
]

# Short fields list for the "track info" command
TRACK_INFO_SHORT_FIELDS = [
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

# Short fields list for the "zones get" command
ZONES_GET_SHORT_FIELDS = [
    "host",
    "name",
    "isSelf",
    "state",
]

# Keys of the "state" subdictionary omitted by the short fields of "zones get"
ZONES_GET_SHORT_STATE_EXCLUDED_FIELDS = [
    "albumart",
]
