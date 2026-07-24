"""Click-independent helpers for the volumito CLI.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

import json
import os
import re
from typing import Any, Literal

from volumito.clients import VolumioHostConfiguration

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


def filter_fields(
    state: dict[str, Any],
    fields: Literal["short", "all"],
    short_fields: list[str] = PLAYER_STATE_SHORT_FIELDS,
) -> dict[str, Any]:
    """Filter the state dictionary based on the fields option.

    Args:
        state: The state dictionary from the Volumio API
        fields: The fields option ("short" or "all")
        short_fields: The list of keys to keep when ``fields`` is "short"

    Returns:
        A filtered dictionary containing only the requested fields
    """
    if fields == "all":
        return state
    else:  # short
        return {key: state[key] for key in short_fields if key in state}


def format_as_json(state: dict[str, Any]) -> str:
    """Format the state dictionary as JSON with 2-space indentation.

    Args:
        state: The (potentially filtered) state dictionary from the Volumio API

    Returns:
        A formatted JSON string with 2-space indentation
    """
    return json.dumps(state, indent=2)


def format_as_pretty(state: dict[str, Any], position_starting_at_one: bool = True) -> str:
    """Format the state dictionary as pretty JSON with 4-space indentation.

    Keys are sorted alphabetically, Unicode escape sequences are unescaped,
    leading/trailing spaces are removed from string values, position is
    rebased for display, and duration is formatted as HH:MM:SS.

    Args:
        state: The (potentially filtered) state dictionary from the Volumio API
        position_starting_at_one: Whether the displayed positions start at one

    Returns:
        A formatted JSON string with 4-space indentation
    """
    # Strip leading/trailing spaces from string values and format duration
    cleaned_state: dict[str, Any] = {}
    for key, value in state.items():
        if isinstance(value, str):
            cleaned_state[key] = value.strip()
        elif key == "position" and isinstance(value, int):
            cleaned_state[key] = display_position(value, position_starting_at_one)
        elif key == "duration" and isinstance(value, int):
            cleaned_state[key] = format_duration(value)
        elif key == "seek" and isinstance(value, int):
            cleaned_state[key] = format_seek(value)
        else:
            cleaned_state[key] = value

    return json.dumps(cleaned_state, indent=4, sort_keys=True, ensure_ascii=False)


def format_duration(seconds: int) -> str:
    """Convert duration in seconds to HH:MM:SS format.

    Args:
        seconds: Duration in seconds

    Returns:
        A formatted string in HH:MM:SS format
    """
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def display_position(api_position: int, starting_at_one: bool) -> int:
    """Convert a position as returned by the Volumio API to the displayed one.

    The Volumio HTTP API indexes queue positions starting from zero.

    Args:
        api_position: The position as returned by the API (starting from zero)
        starting_at_one: Whether the displayed positions start at one

    Returns:
        The position to display
    """
    return api_position + 1 if starting_at_one else api_position


def format_seek(milliseconds: int) -> str:
    """Convert a seek position in milliseconds to HH:MM:SS.mmm format.

    Args:
        milliseconds: Seek position in milliseconds

    Returns:
        A formatted string in HH:MM:SS.mmm format
    """
    seconds, millis = divmod(milliseconds, 1000)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def parse_time_to_seconds(text: str) -> int | None:
    """Convert a colon time to the corresponding number of seconds.

    Accepts HH:MM:SS and MM:SS, where the minutes and seconds components are
    below 60 and the hours component is unbounded.

    Args:
        text: The colon time to convert

    Returns:
        The number of seconds, or None if ``text`` is not a colon time
    """
    components = text.split(":")
    if len(components) not in (2, 3):
        return None
    if not all(component.isdigit() for component in components):
        return None

    values = [int(component) for component in components]
    if any(value > 59 for value in values[1:]):
        return None

    seconds = 0
    for value in values:
        seconds = seconds * 60 + value
    return seconds


def extract_filename_from_uri(uri: str) -> str:
    """Extract the file-name component of a URI.

    Returns the basename of the URI's ``path`` query parameter if present
    (e.g. ``/albumart?path=/mnt/x/cover.jpg`` -> ``cover.jpg``), otherwise the
    basename of the URI path (e.g. ``.../music/song.flac`` -> ``song.flac``).

    Args:
        uri: The URI to extract the file name from

    Returns:
        The file name, or an empty string if none can be determined
    """
    from urllib.parse import parse_qs, urlparse

    parsed = urlparse(uri)

    # Prefer the basename of the 'path' query parameter when present
    if parsed.query:
        qs = parse_qs(parsed.query)
        if "path" in qs:
            return os.path.basename(qs["path"][0])

    # Otherwise use the basename of the URI path
    return os.path.basename(parsed.path)


def resolve_albumart_uri(
    state: dict[str, Any], host_configuration: VolumioHostConfiguration
) -> str | None:
    """Return the absolute album-art URI for the current state, or None if absent.

    A relative URI (starting with "/") is made absolute by prepending the REST base URL.

    Args:
        state: The current player state dictionary
        host_configuration: The Volumio host configuration

    Returns:
        The absolute album-art URI, or None when the state has no album art
    """
    albumart: str | None = state.get("albumart")
    if not albumart:
        return None
    if albumart.startswith("/"):
        return f"{host_configuration.rest_base_url}{albumart}"
    return albumart


def format_as_table(
    state: dict[str, Any],
    heading: str = "Volumio Status",
    field_order: list[str] | None = None,
    position_starting_at_one: bool = True,
) -> str:
    """Format the state dictionary as a readable table.

    Args:
        state: The (potentially filtered) state dictionary from the Volumio API
        heading: The heading line printed above the table
        field_order: When given, the keys to display in this exact order (with
            title-cased labels); otherwise labels and order are derived from the
            state (predefined labels for the short set, sorted keys otherwise)
        position_starting_at_one: Whether the displayed positions start at one

    Returns:
        A formatted string representation of the state
    """
    lines = []
    lines.append(heading)
    lines.append("=" * 50)

    if field_order is not None:
        # Display the requested fields in the given order, with title-cased labels
        field_list = [(key.replace("_", " ").title(), key) for key in field_order]
    elif set(state.keys()).issubset(set(PLAYER_STATE_SHORT_FIELDS)):
        # Use predefined labels for the player short field set
        field_list = [
            ("Status", "status"),
            ("Position", "position"),
            ("Title", "title"),
            ("Artist", "artist"),
            ("Album", "album"),
            ("Duration", "duration"),
            ("Seek", "seek"),
            ("Volume", "volume"),
            ("Mute", "mute"),
        ]
    else:
        # Display all fields from the state
        field_list = [(key.replace("_", " ").title(), key) for key in sorted(state.keys())]

    for label, key in field_list:
        value = state.get(key)
        if value is not None:
            if key == "position" and isinstance(value, int):
                value = display_position(value, position_starting_at_one)
            # Format duration as HH:MM:SS
            if key == "duration" and isinstance(value, int):
                value = format_duration(value)
            # Format seek (milliseconds) as HH:MM:SS.mmm
            if key == "seek" and isinstance(value, int):
                value = format_seek(value)
            if isinstance(value, dict):
                # Print a nested object as one indented key/value line per sub-key,
                # in the order returned by the API
                lines.append(f"{label:20}:")
                for sub_key, sub_value in value.items():
                    sub_label = sub_key.replace("_", " ").title()
                    lines.append(f"  {sub_label:18}: {sub_value}")
            else:
                lines.append(f"{label:20}: {value}")

    return "\n".join(lines)


def filter_queue_fields(
    queue_data: dict[str, Any], fields: Literal["short", "all"]
) -> list[dict[str, Any]]:
    """Filter queue items based on the fields option.

    Args:
        queue_data: The queue data dictionary from the Volumio API (contains "queue" key)
        fields: The fields option ("short" or "all")

    Returns:
        A list of filtered queue item dictionaries with a synthetic "position" field
        added, always starting at one (see ``rebase_queue_positions`` for the
        display rebasing)
    """
    queue = queue_data.get("queue", [])
    filtered_queue = []

    for index, item in enumerate(queue):
        if fields == "all":
            filtered_item = item.copy()
        else:  # short
            filtered_item = {key: item[key] for key in QUEUE_LIST_SHORT_FIELDS if key in item}

        # Add synthetic position, always 1-indexed here
        filtered_item["position"] = index + 1
        filtered_queue.append(filtered_item)

    return filtered_queue


def rebase_queue_positions(
    tracks: list[dict[str, Any]], starting_at_one: bool
) -> list[dict[str, Any]]:
    """Return copies of the queue items with "position" rebased for display.

    The items produced by ``filter_queue_fields`` carry a 1-indexed position;
    this shifts it when the displayed positions start at zero.

    Args:
        tracks: List of (potentially filtered) queue item dictionaries
        starting_at_one: Whether the displayed positions start at one

    Returns:
        A list of copies of the queue items, with the position rebased
    """
    rebased = []
    for track in tracks:
        item = track.copy()
        if isinstance(item.get("position"), int):
            item["position"] = display_position(item["position"] - 1, starting_at_one)
        rebased.append(item)
    return rebased


def number_prefix_width(numbers: list[str]) -> int:
    """Return the width of the widest entry number of a numbered table block.

    The numbers are right-aligned to this width, so that the detail lines of every
    block, indented by this width plus two (the dot and the following space), start
    at the same column as the entry name.

    Args:
        numbers: The entry numbers, as rendered

    Returns:
        The width of the widest entry number
    """
    return max(len(number) for number in numbers)


def format_queue_as_table(tracks: list[dict[str, Any]]) -> str:
    """Format the queue as a readable table.

    Args:
        tracks: List of (potentially filtered) queue item dictionaries

    Returns:
        A formatted string representation of the queue
    """
    lines = []
    lines.append("Volumio Queue")
    lines.append("=" * 50)

    if not tracks:
        lines.append("(empty)")
        return "\n".join(lines)

    width = number_prefix_width([str(track.get("position", "?")) for track in tracks])
    indent = " " * (width + 2)

    for track in tracks:
        position = track.get("position", "?")
        title = track.get("title", "Unknown")
        artist = track.get("artist", "Unknown")
        album = track.get("album", "")
        duration = track.get("duration")
        service = track.get("service", "")

        lines.append(f"\n{position:>{width}}. {title}")
        if artist:
            lines.append(f"{indent}Artist : {artist}")
        if album:
            lines.append(f"{indent}Album  : {album}")
        if duration and isinstance(duration, int):
            lines.append(f"{indent}Duration: {format_duration(duration)}")
        if service:
            lines.append(f"{indent}Service: {service}")

        # Add optional audio quality fields if present
        samplerate = track.get("samplerate")
        bitdepth = track.get("bitdepth")
        channels = track.get("channels")

        if samplerate:
            lines.append(f"{indent}Sample Rate: {samplerate}")
        if bitdepth:
            lines.append(f"{indent}Bit Depth: {bitdepth}")
        if channels:
            lines.append(f"{indent}Channels: {channels}")

    return "\n".join(lines)


def filter_zones_fields(
    zones_data: dict[str, Any], fields: Literal["short", "all"]
) -> list[dict[str, Any]]:
    """Filter the zones based on the fields option.

    Args:
        zones_data: The zones data dictionary from the Volumio API (contains "zones" key)
        fields: The fields option ("short" or "all")

    Returns:
        A list of filtered zone dictionaries; in short mode the "state" subdictionary
        is filtered too
    """
    zones = zones_data.get("zones", [])
    if fields == "all":
        return [zone.copy() for zone in zones]

    filtered_zones = []
    for zone in zones:
        filtered_zone = {key: zone[key] for key in ZONES_GET_SHORT_FIELDS if key in zone}
        state = filtered_zone.get("state")
        if isinstance(state, dict):
            filtered_zone["state"] = {
                key: value
                for key, value in state.items()
                if key not in ZONES_GET_SHORT_STATE_EXCLUDED_FIELDS
            }
        filtered_zones.append(filtered_zone)
    return filtered_zones


def split_camel_case(key: str) -> str:
    """Turn a key into a readable label, splitting underscores and camel case.

    For example, ``isSelf`` becomes ``Is Self`` and ``output_file`` becomes ``Output File``.

    Args:
        key: The key to turn into a label

    Returns:
        The label for the key
    """
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", key.replace("_", " "))
    return spaced.title()


def format_zones_as_table(zones: list[dict[str, Any]]) -> str:
    """Format the zones as a readable table.

    Each zone is printed as a numbered block whose key/value lines are indented to
    start at the same column as the zone name.

    Args:
        zones: List of (potentially filtered) zone dictionaries

    Returns:
        A formatted string representation of the zones
    """
    lines = []
    lines.append("Volumio Zones")
    lines.append("=" * 50)

    if not zones:
        lines.append("(empty)")
        return "\n".join(lines)

    width = number_prefix_width([str(index) for index in range(1, len(zones) + 1)])
    indent = " " * (width + 2)

    for index, zone in enumerate(zones, start=1):
        lines.append(f"\n{index:>{width}}. {zone.get('name', 'Unknown')}")
        for key, value in zone.items():
            if key == "name":
                # The name is already the heading of the block
                continue
            label = split_camel_case(key)
            if isinstance(value, dict):
                lines.append(f"{indent}{label:17}:")
                for sub_key, sub_value in value.items():
                    lines.append(f"{indent}  {split_camel_case(sub_key):15}: {sub_value}")
            else:
                lines.append(f"{indent}{label:17}: {value}")

    return "\n".join(lines)


def format_playlists_as_table(names: list[Any]) -> str:
    """Format the playlists as a readable table.

    Args:
        names: List of playlist names

    Returns:
        A formatted string representation of the playlists
    """
    lines = []
    lines.append("Volumio Playlists")
    lines.append("=" * 50)

    if not names:
        lines.append("(empty)")
        return "\n".join(lines)

    width = number_prefix_width([str(index) for index in range(1, len(names) + 1)])

    for index, name in enumerate(names, start=1):
        lines.append(f"{index:>{width}}. {name}")

    return "\n".join(lines)
