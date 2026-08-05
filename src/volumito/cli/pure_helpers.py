"""Click-independent helpers for the volumito CLI.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

import json
import os
import re
from typing import Any

from volumito.cli.constants import (
    OUTPUT_DIRECTORY_PLACEHOLDER,
    OUTPUT_DIRECTORY_TIMESTAMP_PLACEHOLDER,
    OUTPUT_FIELDS_ALL,
    OUTPUT_FIELDS_SHORT,
    SHORT_FORMAT_FIELDS_PLAYER_STATE,
    SHORT_FORMAT_FIELDS_QUEUE_LIST,
    SHORT_FORMAT_FIELDS_ZONES_LIST,
    SHORT_FORMAT_FIELDS_ZONES_LIST_EXCLUDED_FROM_STATE,
)
from volumito.clients import VolumioHostConfiguration
from volumito.clients.models import PlayerState, QueueTrack, SearchResultItemKind
from volumito.clients.remote import is_local_file_uri


def _append_result_lists(lines: list[str], lists: list[dict[str, Any]], print_uri: bool) -> None:
    """Append the lists of a navigation payload to the lines of a table.

    The lists a Volumio host titles after the query it answered (e.g., ``Found 12
    Tracks 'Sirtaki'``) are titled after their source instead (``MPD Tracks``), so that
    every list reads alike; the titles the sources give (``QOBUZ Albums``, ``Web
    Radio``) are kept as they are, and a list without a title gets no title line, which
    is how a host lists the content of a browsed URI.

    Args:
        lines: The lines of the table, appended to in place
        lists: The lists of results, as the Volumio host groups them
        print_uri: Whether to print the URI of a result under its line
    """
    for result_list in lists:
        items = result_list.get("items") or []
        if not items:
            continue
        title = str(result_list.get("title") or "")
        found = re.match(r"^Found \d+ (\w+?)s? '.*'$", title)
        service = str(items[0].get("service") or "")
        if found is not None and service:
            title = f"{service.upper()} {found.group(1)}s"
        lines.append("")
        if title:
            lines.append(title)
        width = number_prefix_width([str(index) for index in range(1, len(items) + 1)])
        indent = " " * (width + 2)
        for index, item in enumerate(items, start=1):
            lines.append(f"{index:>{width}}. {_result_details(item)}")
            if print_uri and item.get("uri"):
                lines.append(f"{indent}{item['uri']}")


def _result_details(item: dict[str, Any]) -> str:
    """Return the one-line description of a navigation result.

    Args:
        item: The result, as the Volumio host reports it

    Returns:
        The title (or the name, which is what a root listing has), the artist, and the
        album of the result, joined by dashes
    """
    parts = [item.get("title") or item.get("name"), item.get("artist"), item.get("album")]
    return " - ".join(str(part) for part in parts if part)


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


def expand_manifest_file(path: str, output_directory: str, timestamp: str) -> str:
    """Replace the placeholders in a download manifest file path.

    Each occurrence of ``{output_directory}`` is replaced with ``output_directory``,
    and each occurrence of ``{timestamp}`` with ``timestamp``. The replacements are
    literal :meth:`str.replace` calls, so any other braces in the path are left
    untouched.

    Args:
        path: The manifest file path, possibly containing the placeholders
        output_directory: The (expanded) output directory replacing its placeholder
        timestamp: The timestamp string replacing its placeholder

    Returns:
        The path with every occurrence of the placeholders replaced
    """
    expanded = path.replace(OUTPUT_DIRECTORY_PLACEHOLDER, output_directory)
    return expand_timestamp_placeholder(expanded, timestamp)


def expand_timestamp_placeholder(path: str, timestamp: str) -> str:
    """Replace the ``{timestamp}`` placeholder in an output directory path.

    The replacement is a literal :meth:`str.replace`, not :meth:`str.format`,
    so any other braces in the path are left untouched.

    Args:
        path: The output directory path, possibly containing the placeholder
        timestamp: The timestamp string replacing each occurrence of the placeholder

    Returns:
        The path with every occurrence of the placeholder replaced
    """
    return path.replace(OUTPUT_DIRECTORY_TIMESTAMP_PLACEHOLDER, timestamp)


def extract_filename_from_uri(uri: str) -> str:
    """Extract the file-name component of a URI.

    Returns the basename of the URI's ``path`` query parameter if present
    (e.g., ``/albumart?path=/mnt/x/cover.jpg`` -> ``cover.jpg``), otherwise the
    basename of the URI path (e.g., ``.../music/song.flac`` -> ``song.flac``).

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


def filter_fields(
    state: dict[str, Any],
    fields: str,
    short_fields: list[str] = SHORT_FORMAT_FIELDS_PLAYER_STATE,
) -> dict[str, Any]:
    """Filter the state dictionary based on the fields option.

    A requested field that is not a top-level key but contains ``.`` is resolved as a
    dotted path into nested dictionaries (e.g., ``data.value``); when the full path
    resolves, the value appears in the output keyed by the dotted string. Fields that
    cannot be resolved are silently omitted.

    Args:
        state: The state dictionary from the Volumio API
        fields: The fields option (``ALL``, ``SHORT``, or a comma-separated field list)
        short_fields: The list of keys to keep for the ``SHORT`` keyword

    Returns:
        A filtered dictionary containing only the requested fields, in the requested order
    """
    selected = resolve_output_fields(fields, short_fields)
    if selected is None:  # ALL
        return state
    filtered: dict[str, Any] = {}
    for key in selected:
        if key in state:
            filtered[key] = state[key]
        elif "." in key:
            current: Any = state
            for part in key.split("."):
                if isinstance(current, dict) and part in current:
                    current = current[part]
                else:
                    break
            else:
                filtered[key] = current
    return filtered


def filter_queue_fields(
    queue_data: dict[str, Any], fields: str
) -> list[dict[str, Any]]:
    """Filter queue items based on the fields option.

    Each item gets a synthetic 1-indexed "position" (see ``rebase_queue_positions``
    for the display rebasing). ``ALL`` and ``SHORT`` keep it; a comma-separated field
    list keeps it only when "position" is listed explicitly.

    Args:
        queue_data: The queue data dictionary from the Volumio API (contains "queue" key)
        fields: The fields option (``ALL``, ``SHORT``, or a comma-separated field list)

    Returns:
        A list of filtered queue item dictionaries, in the requested order
    """
    queue = queue_data.get("queue", [])
    selected = resolve_output_fields(fields, SHORT_FORMAT_FIELDS_QUEUE_LIST)
    filtered_queue = []

    for index, item in enumerate(queue):
        full = item.copy()
        full["position"] = index + 1  # synthetic, 1-indexed
        if selected is None:  # ALL
            filtered_item = full
        else:
            filtered_item = {key: full[key] for key in selected if key in full}
        filtered_queue.append(filtered_item)

    return filtered_queue


def filter_zones_fields(
    zones_data: dict[str, Any], fields: str
) -> list[dict[str, Any]]:
    """Filter the zones based on the fields option.

    Args:
        zones_data: The zones data dictionary from the Volumio API (contains "zones" key)
        fields: The fields option (``ALL``, ``SHORT``, or a comma-separated field list)

    Returns:
        A list of filtered zone dictionaries, in the requested order; for the ``SHORT``
        keyword the "state" subdictionary is trimmed too
    """
    zones = zones_data.get("zones", [])
    selected = resolve_output_fields(fields, SHORT_FORMAT_FIELDS_ZONES_LIST)
    if selected is None:  # ALL
        return [zone.copy() for zone in zones]

    filtered_zones = []
    for zone in zones:
        filtered_zone = {key: zone[key] for key in selected if key in zone}
        # The SHORT keyword also trims the state subdictionary (e.g., drops albumart)
        state = filtered_zone.get("state")
        if fields == OUTPUT_FIELDS_SHORT and isinstance(state, dict):
            filtered_zone["state"] = {
                key: value
                for key, value in state.items()
                if key not in SHORT_FORMAT_FIELDS_ZONES_LIST_EXCLUDED_FROM_STATE
            }
        filtered_zones.append(filtered_zone)
    return filtered_zones


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
        field_list = [
            (key.replace("_", " ").replace(".", " ").title(), key) for key in field_order
        ]
    elif set(state.keys()).issubset(set(SHORT_FORMAT_FIELDS_PLAYER_STATE)):
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


def format_browse_results_as_table(
    lists: list[dict[str, Any]],
    info: dict[str, Any] | None = None,
    print_uri: bool = False,
) -> str:
    """Format the content listed at a browsing URI as a readable table.

    The entity being browsed (e.g., the album of the tracks listed), when the host
    describes it, follows the heading; its URI is not repeated, being the very URI
    that was browsed.

    Args:
        lists: The lists of content, as the Volumio host groups them
        info: The entity being browsed, when the host describes it
        print_uri: Whether to print the URI of a result under its line

    Returns:
        A formatted string representation of the content
    """
    lines = ["Volumio Browse Results", "=" * 50]

    details = _result_details(info) if info else ""
    if details:
        lines.append(details)

    if not any(result_list.get("items") for result_list in lists):
        lines.append("(no result)")
        return "\n".join(lines)

    _append_result_lists(lines, lists, print_uri)

    return "\n".join(lines)


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


def format_names_as_table(names: list[Any], heading: str) -> str:
    """Format a list of names as a readable, numbered table.

    Args:
        names: List of names (e.g., the playlist names)
        heading: The heading line of the table

    Returns:
        A formatted string representation of the names
    """
    lines = []
    lines.append(heading)
    lines.append("=" * 50)

    if not names:
        lines.append("(empty)")
        return "\n".join(lines)

    width = number_prefix_width([str(index) for index in range(1, len(names) + 1)])

    for index, name in enumerate(names, start=1):
        lines.append(f"{index:>{width}}. {name}")

    return "\n".join(lines)


def format_notification_as_line(item: str | None, data: object, timestamp: str) -> str:
    """Format a received push notification as a single readable line.

    Args:
        item: The kind of event (e.g., "state"), or None when the host reported none
        data: The information carried by the notification
        timestamp: The UTC time the notification was received, already formatted

    Returns:
        A line such as
        ``[2026-08-04T10:15:32.123Z] state    play | Caterina - Francesco De Gregori``
    """
    if isinstance(data, list):
        summary = f"{len(data)} items"
    elif isinstance(data, dict):
        status = str(data["status"]) if data.get("status") is not None else ""
        track = " - ".join(
            str(data[key]) for key in ("title", "artist") if data.get(key) is not None
        )
        summary = " | ".join(part for part in (status, track) if part)
        if not summary:
            summary = json.dumps(data, ensure_ascii=False)
    else:
        summary = json.dumps(data, ensure_ascii=False)

    return f"[{timestamp}] {item or '?':<8} {summary}"


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
        tracknumber = track.get("tracknumber")
        volume_number = track.get("volumeNumber")
        duration = track.get("duration")
        service = track.get("service", "")

        lines.append(f"\n{position:>{width}}. {title}")
        if artist:
            lines.append(f"{indent}Artist : {artist}")
        if album:
            lines.append(f"{indent}Album  : {album}")
        if volume_number:
            lines.append(f"{indent}Volume : {volume_number}")
        if tracknumber:
            lines.append(f"{indent}Track  : {tracknumber}")
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


def format_search_results_as_table(lists: list[dict[str, Any]], print_uri: bool = False) -> str:
    """Format the results of a search as a readable table.

    The lists a Volumio host titles after the query it answered (e.g., ``Found 12
    Tracks 'Sirtaki'``) are titled after their source instead (``MPD Tracks``), so that
    every list reads alike; the titles the sources give (``QOBUZ Albums``, ``Web
    Radio``) are kept as they are.

    Args:
        lists: The lists of results, as the Volumio host groups them
        print_uri: Whether to print the URI of a result under its line

    Returns:
        A formatted string representation of the results
    """
    lines = ["Volumio Search Results", "=" * 50]

    if not any(result_list.get("items") for result_list in lists):
        lines.append("(no result)")
        return "\n".join(lines)

    _append_result_lists(lines, lists, print_uri)

    return "\n".join(lines)


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


def format_termination_conditions(
    count: int | None, timeout: float | None, idle_timeout: float | None
) -> str:
    """Return the message listing what ends a listening.

    Args:
        count: Number of notifications ending the listening, or None
        timeout: Seconds of listening ending it, or None
        idle_timeout: Seconds without a notification ending it, or None

    Returns:
        A line such as ``Terminate as soon as: CTRL+C is issued, or 3 notifications received``
    """
    conditions = ["CTRL+C is issued"]

    if timeout is not None:
        seconds = "second" if timeout == 1 else "seconds"
        conditions.append(f"a total of {timeout:g} {seconds} elapsed")
    if idle_timeout is not None:
        seconds = "second" if idle_timeout == 1 else "seconds"
        conditions.append(f"no notifications received for {idle_timeout:g} {seconds}")
    if count is not None:
        notifications = "notification" if count == 1 else "notifications"
        conditions.append(f"{count} {notifications} received")

    if len(conditions) > 1:
        conditions[-1] = f"or {conditions[-1]}"

    return f"Terminate as soon as: {', '.join(conditions)}"


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


def is_mbid(text: str) -> bool:
    """Check whether the text has the shape of a MusicBrainz identifier (MBID).

    An MBID is a UUID: five groups of 8, 4, 4, 4, and 12 hexadecimal digits
    separated by hyphens.

    Args:
        text: The text to check

    Returns:
        True if the text is UUID-shaped, False otherwise
    """
    return (
        re.fullmatch(r"[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", text) is not None
    )


def manifest_matches_queue(
    manifest_tracks: list[dict[str, Any]], queue_tracks: list[QueueTrack]
) -> bool:
    """Check whether the manifest tracks describe the current queue.

    The manifest matches when it holds one entry per queue track and, at every
    position, the title, artist, and album are equal.

    Args:
        manifest_tracks: The "tracks" entries of an existing download manifest
        queue_tracks: The tracks of the current queue

    Returns:
        True if the manifest matches the queue, False otherwise
    """
    if len(manifest_tracks) != len(queue_tracks):
        return False
    return all(
        entry.get("title") == track.title
        and entry.get("artist") == track.artist
        and entry.get("album") == track.album
        for entry, track in zip(manifest_tracks, queue_tracks, strict=True)
    )


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


def parse_track_selection(value: str) -> set[int]:
    """Parse a track selection such as ``"1-3,6-8,12"`` into its positions.

    The selection is a comma-separated list of items, each a positive integer or an
    inclusive ``start-end`` range; blanks around the items are ignored, and a position
    listed more than once is kept once. The positions are returned as written: it is
    up to the caller to interpret them (see ``display_position`` for the indexing).

    Args:
        value: The track selection to parse

    Returns:
        The selected positions

    Raises:
        ValueError: If the selection is empty or malformed
    """
    positions: set[int] = set()
    items = [item.strip() for item in value.split(",")]
    if not any(items):
        raise ValueError("the track selection is empty")
    for item in items:
        if not item:
            raise ValueError(f"empty item in the track selection {value!r}")
        first, separator, last = item.partition("-")
        first, last = first.strip(), last.strip()
        if not first.isdigit() or (separator and not last.isdigit()):
            raise ValueError(f"invalid item {item!r} in the track selection {value!r}")
        if not separator:
            positions.add(int(first))
            continue
        if int(last) < int(first):
            raise ValueError(f"reversed range {item!r} in the track selection {value!r}")
        positions.update(range(int(first), int(last) + 1))
    return positions


def parse_result_kinds(value: str) -> set[SearchResultItemKind]:
    """Parse a list of search result kinds such as ``"album,track"``.

    The list is comma-separated; blanks around the items are ignored, and a kind listed
    more than once is kept once.

    Args:
        value: The list of kinds to parse

    Returns:
        The kinds listed

    Raises:
        ValueError: If the list is empty or names a kind that does not exist
    """
    accepted = ", ".join(kind.value for kind in SearchResultItemKind)
    kinds = set()
    items = [item.strip() for item in value.split(",")]
    if not any(items):
        raise ValueError("the list of kinds is empty")
    for item in items:
        try:
            kinds.add(SearchResultItemKind(item))
        except ValueError:
            raise ValueError(f"unknown kind {item!r}: expected one of {accepted}") from None
    return kinds


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


def preserve_local_file_name(filename: str, uri: str) -> str:
    """Return the file name to write a URI to, keeping the name a local file already has.

    A file of the library of the Volumio host is copied as it is, so renaming it after a
    template only makes its name worse: the directories of the rendered name are kept,
    and its last component becomes the name the file has on the host. Anything fetched
    over HTTP keeps the rendered name.

    Args:
        filename: The file name rendered from the template
        uri: The URI the file is downloaded from

    Returns:
        The file name to use, relative to the output directory
    """
    if not is_local_file_uri(uri):
        return filename
    return os.path.join(os.path.dirname(filename), os.path.basename(uri))


def queue_album_volumes(tracks: list[QueueTrack], replacement: str) -> list[str]:
    """Return each queue track's album/volume path component, in queue order.

    A track's ``(artist, album)`` group is multi-volume when the queue holds more
    than one distinct volume number for it. A multi-volume track renders
    as ``<album>/<volumeNumber>`` (a per-volume subdirectory) and any other track as
    ``<album>`` alone. The album name and the volume number are sanitized separately
    with ``replacement`` (see ``sanitize_filename_component``), so only the deliberate
    separator between them survives; a missing album yields an empty string.

    Args:
        tracks: The queue items, in queue order
        replacement: The string substituted for path separators in the components

    Returns:
        The album/volume component of each track, in queue order
    """
    volumes: dict[tuple[str | None, str | None], set[int]] = {}
    for track in tracks:
        key = (track.artist, track.album)
        volume = track.volume_number
        if volume is not None:
            volumes.setdefault(key, set()).add(volume)

    components = []
    for track in tracks:
        key = (track.artist, track.album)
        album = sanitize_filename_component(track.album or "", replacement)
        volume = track.volume_number
        if volume is not None and len(volumes.get(key, set())) > 1:
            components.append(f"{album}/{sanitize_filename_component(str(volume), replacement)}")
        else:
            components.append(album)
    return components


def queue_track_metadata_current(
    state: PlayerState,
    uri: str,
    expected_track: QueueTrack,
    index: int,
    previous_uri: str | None,
    expect_same_uri: bool,
) -> bool:
    """Return True if the fetched metadata refer to the queue track at ``index``.

    The state is compared against ``expected_track``, the corresponding entry of the
    queue listing: every ``album``/``artist``/``title`` value present in the queue
    entry must appear identically in the state. The state's ``position`` must equal
    ``index`` (a missing position fails the check), and ``uri`` must
    differ from ``previous_uri`` (the URI of the previously fetched track) unless
    there is no previous track or the queue itself lists the same URI for both
    tracks (``expect_same_uri``).

    Args:
        state: The player state fetched after playing the track
        uri: The track URI fetched after playing the track
        expected_track: The queue-listing entry of the track that was played
        index: The 0-based queue position that was played
        previous_uri: The URI fetched for the previous track, or None for the first
        expect_same_uri: Whether the queue lists the same URI for this track and the previous one

    Returns:
        True if the metadata are current, False if they look stale
    """
    expected_values = (expected_track.album, expected_track.artist, expected_track.title)
    values = (state.album, state.artist, state.title)
    for expected_value, value in zip(expected_values, values, strict=True):
        if expected_value is not None and value != expected_value:
            return False
    if state.position is None or state.position != index:
        return False
    if previous_uri is not None and not expect_same_uri and uri == previous_uri:
        return False
    return True


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


def resolve_albumart_uri(
    state: PlayerState, host_configuration: VolumioHostConfiguration
) -> str | None:
    """Return the absolute album-art URI for the current state, or None if absent.

    A relative URI (starting with "/") is made absolute by prepending the REST base URL.

    Args:
        state: The current player state
        host_configuration: The Volumio host configuration

    Returns:
        The absolute album-art URI, or None when the state has no album art
    """
    albumart = state.albumart
    if not albumart:
        return None
    if albumart.startswith("/"):
        return f"{host_configuration.rest_base_url}{albumart}"
    return albumart


def resolve_output_fields(fields: str, short_fields: list[str]) -> list[str] | None:
    """Resolve the ``--fields`` value into the ordered list of fields to show.

    Returns ``None`` for the ``ALL`` keyword (meaning "show every field"), the given
    ``short_fields`` for the ``SHORT`` keyword, or the parsed comma-separated field list
    otherwise (whitespace trimmed, empty entries dropped, order preserved).

    Args:
        fields: The raw ``--fields`` value
        short_fields: The field list to use for the ``SHORT`` keyword

    Returns:
        The ordered list of field names to keep, or None to keep every field
    """
    if fields == OUTPUT_FIELDS_ALL:
        return None
    if fields == OUTPUT_FIELDS_SHORT:
        return short_fields
    return [name.strip() for name in fields.split(",") if name.strip()]


def sanitize_filename_component(text: str, replacement: str) -> str:
    """Neutralize path separators and control characters in a file-name component.

    Replaces ``/`` and ``\\`` with ``replacement`` and removes control characters
    (ASCII codes below 32, and 127), so an untrusted value (e.g., track metadata or a
    URI-derived name) cannot introduce new path components or unprintable characters
    into a file name.

    Args:
        text: The untrusted text to sanitize
        replacement: The string substituted for each path separator

    Returns:
        The sanitized text
    """
    sanitized = text.replace("/", replacement).replace("\\", replacement)
    return "".join(char for char in sanitized if ord(char) >= 32 and ord(char) != 127)


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


def story_query_reference(
    arguments: tuple[str, ...],
    argument_type: str,
    pair: bool,
) -> tuple[str, tuple[str, ...]] | None:
    """Resolve the "story" positional arguments into an interpreted reference.

    A "mbid" interpretation takes a single argument; a "name" interpretation takes
    one argument (or an ARTIST ALBUM argument pair when ``pair`` is set). The
    "autodetect" type selects "mbid" for a single UUID-shaped argument and "name"
    when the argument count matches. Any other combination is invalid.

    Args:
        arguments: The positional arguments of the command
        argument_type: How to interpret the arguments ("autodetect", "mbid", or "name")
        pair: Whether the "name" interpretation takes an ARTIST ALBUM argument pair

    Returns:
        The pair ("mbid", (value,)) or ("name", values), or None if the arguments
        are invalid
    """
    name_count = 2 if pair else 1
    if argument_type == "autodetect":
        if len(arguments) == 1 and is_mbid(arguments[0]):
            argument_type = "mbid"
        elif len(arguments) == name_count:
            argument_type = "name"
    if argument_type == "mbid" and len(arguments) == 1:
        return ("mbid", arguments)
    if argument_type == "name" and len(arguments) == name_count:
        return ("name", arguments)
    return None
