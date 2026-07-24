"""Command-line interface for volumito.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

import json
import os
import re
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal

import click
import requests

from volumito.cli import metadata
from volumito.cli.configuration import (
    CONFIGURATION_FILENAMES,
    build_click_default_map,
    flatten_configuration,
    load_configuration,
    probe_configuration_paths,
    render_default_configuration,
    resolve_configuration_path,
)
from volumito.clients import (
    VolumioAPIError,
    VolumioConnectionError,
    VolumioHostConfiguration,
    VolumioMPDClient,
    VolumioRESTAPIClient,
)

# Default chunk size when writing files
FILE_WRITE_CHUNK_SIZE = 8192

# Error message when the download destination options are combined
MUTUALLY_EXCLUSIVE_OUTPUT_ERROR = (
    "Options -o/--output-file and -d/--output-directory are mutually exclusive."
)

# Error message when the "configuration create" destination options are combined
MUTUALLY_EXCLUSIVE_CREATE_ERROR = (
    "Options -d/--output-directory and -f/--output-file are mutually exclusive."
)

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

# Accepted values of the -F/--format option
OUTPUT_FORMATS = ["json", "pretty", "raw", "table"]

# Version of the CLI (and of the underlying library)
VERSION = "0.0.14"


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


def render_output_filename(
    template: str,
    uri: str,
    state: dict[str, Any],
    default_extension: str,
    position_starting_at_one: bool = True,
) -> str:
    """Render an output file name from a template, track metadata, and the URI.

    The template uses Python ``str.format`` syntax. Supported keys are:
    ``file_name_from_uri``, ``position`` (int, indexed according to
    ``position_starting_at_one``), ``title``, ``album``, ``artist``,
    ``trackType``, ``duration`` (HH:MM:SS), ``bitdepth``, ``samplerate``,
    ``channels`` (int), and ``extension``. The ``extension`` is
    taken from the URI file name, falling back to ``default_extension`` when the
    URI file has none. Spaces in the rendered name are replaced with underscores.

    Args:
        template: The file-name template (``str.format`` syntax)
        uri: The URI being downloaded (source of ``file_name_from_uri`` and ``extension``)
        state: The current player state dictionary
        default_extension: Extension to use when the URI file has none (no leading dot)
        position_starting_at_one: Whether the ``position`` key starts at one

    Returns:
        The rendered file name, with spaces replaced by underscores

    Raises:
        click.UsageError: If the template references an unknown key or uses an
            invalid format specification
    """

    def as_text(key: str) -> str:
        value = state.get(key)
        return str(value).strip() if value is not None else ""

    file_name_from_uri = extract_filename_from_uri(uri)
    uri_extension = os.path.splitext(file_name_from_uri)[1].lstrip(".")

    duration = state.get("duration")
    keys: dict[str, object] = {
        "file_name_from_uri": file_name_from_uri,
        "position": display_position(
            int(state.get("position") or 0), position_starting_at_one
        ),
        "title": as_text("title"),
        "album": as_text("album"),
        "artist": as_text("artist"),
        "trackType": as_text("trackType"),
        "duration": format_duration(int(duration)) if isinstance(duration, int) else "",
        "bitdepth": as_text("bitdepth"),
        "samplerate": as_text("samplerate"),
        "channels": int(state["channels"]) if isinstance(state.get("channels"), int) else 0,
        "extension": uri_extension or default_extension,
    }

    try:
        rendered = template.format(**keys)
    except (KeyError, ValueError, IndexError) as e:
        raise click.UsageError(f"Invalid --file-name-template {template!r}: {e}") from e

    return rendered.replace(" ", "_")


def download_uri_to(
    uri: str,
    output_file: str | None,
    output_directory: str | None,
    file_name_template: str,
    default_extension: str,
    state: dict[str, Any],
    overwrite: bool,
    label: str,
    timeout: float,
    verbose: bool,
    machine_readable: bool,
    create_manifest: bool,
    host_configuration: VolumioHostConfiguration,
    entity: str,
    kind: str,
    position_starting_at_one: bool = True,
    add_cover_and_metadata: bool | None = None,
) -> str:
    """Download ``uri`` to a file, printing errors and exiting (1) on failure.

    Exactly one of ``output_file`` / ``output_directory`` is expected to be set. With
    ``output_file`` the URI is saved to that exact path; with ``output_directory`` it is
    saved into that directory under the file name produced by rendering
    ``file_name_template`` against ``state`` (see ``render_output_filename``).
    Unless ``overwrite`` is true, an existing destination file is left untouched.

    When ``create_manifest`` is true, a JSON manifest describing the download is written
    next to the downloaded file (``<destination>.json``) after a successful download.

    Args:
        uri: The URI to download
        output_file: Exact destination file path, or None
        output_directory: Destination directory (file name from the template), or None
        file_name_template: Template for the ``output_directory`` file name
        default_extension: Extension for the ``{extension}`` key when the URI has none
        state: The current player state dictionary (source of template values)
        overwrite: Whether to overwrite the destination file if it already exists
        label: Human-readable noun for messages ("track" or "album art")
        timeout: Request timeout in seconds
        verbose: Whether to print progress messages
        machine_readable: Whether machine-readable mode is active (suppresses messages)
        create_manifest: Whether to write a ``<destination>.json`` download manifest
        host_configuration: The Volumio host configuration (recorded in the manifest)
        entity: The manifest ``entity`` value (e.g. "track")
        kind: The manifest ``kind`` value (e.g. "audio" or "albumart")
        position_starting_at_one: Whether the template ``position`` key starts at one
        add_cover_and_metadata: Recorded in the manifest when not None (audio downloads only)

    Returns:
        The path the URI was downloaded to
    """
    if output_file is not None:
        destination = output_file
    else:  # output_directory is not None
        filename = render_output_filename(
            file_name_template, uri, state, default_extension, position_starting_at_one
        )
        if not filename:
            if not machine_readable:
                click.echo("\nError: cannot determine a file name for the download", err=True)
            sys.exit(1)
        destination = os.path.join(output_directory, filename)  # type: ignore[arg-type]

    if not overwrite and os.path.exists(destination):
        if not machine_readable:
            click.echo(
                f"\nError: file already exists: {destination} "
                "(use --overwrite-existing-files to overwrite)",
                err=True,
            )
        sys.exit(1)

    if verbose and not machine_readable:
        click.echo(f"\nDownloading {label} to {destination}...", err=True)

    try:
        response = requests.get(uri, timeout=timeout, stream=True)
        response.raise_for_status()

        with open(destination, "wb") as f:
            for chunk in response.iter_content(chunk_size=FILE_WRITE_CHUNK_SIZE):
                f.write(chunk)

        if not machine_readable:
            click.echo(f"\n{label.capitalize()} successfully downloaded to {destination}")

        if create_manifest:
            manifest_path = f"{destination}.json"
            manifest: dict[str, Any] = {
                "download_date": datetime.now(UTC).isoformat(),
                "entity": entity,
                "kind": kind,
                "output_file_name": os.path.basename(destination),
                "output_file_path": destination,
                "source_uri": uri,
                "state": state,
                "volumio_host": host_configuration.rest_base_url,
                "volumito_version": VERSION,
            }
            if add_cover_and_metadata is not None:
                manifest["add_cover_and_metadata"] = add_cover_and_metadata
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2, sort_keys=True, ensure_ascii=False)
            if verbose and not machine_readable:
                click.echo(f"\nManifest written to {manifest_path}...", err=True)

    except requests.exceptions.RequestException as e:
        if not machine_readable:
            click.echo(f"\nDownload error: {e}", err=True)
        sys.exit(1)
    except OSError as e:
        if not machine_readable:
            click.echo(f"\nFile write error: {e}", err=True)
        sys.exit(1)

    return destination


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


def _fetch_cover(
    state: dict[str, Any],
    host_configuration: VolumioHostConfiguration,
    timeout: float,
    machine_readable: bool,
) -> bytes | None:
    """Fetch the album-art image bytes for the current state, or None on absence/failure."""
    albumart_uri = resolve_albumart_uri(state, host_configuration)
    if albumart_uri is None:
        return None
    try:
        response = requests.get(albumart_uri, timeout=timeout, stream=True)
        response.raise_for_status()
        return b"".join(response.iter_content(chunk_size=FILE_WRITE_CHUNK_SIZE))
    except requests.exceptions.RequestException as e:
        if not machine_readable:
            click.echo(f"\nWarning: cannot fetch cover art ({e})", err=True)
        return None


def embed_track_tags(
    destination: str,
    state: dict[str, Any],
    host_configuration: VolumioHostConfiguration,
    timeout: float,
    position_starting_at_one: bool,
    verbose: bool,
    machine_readable: bool,
) -> None:
    """Embed the current track metadata and cover art into a downloaded audio file.

    The metadata and cover come from ``state``. Any problem (an unsupported format, a
    cover-download failure, or a tagging error) is reported as a warning and otherwise
    ignored: the already-downloaded file is left in place.

    Args:
        destination: The downloaded audio file to tag, modified in place
        state: The current player state dictionary (source of the metadata)
        host_configuration: The Volumio host configuration (to resolve the cover URI)
        timeout: Request timeout for fetching the cover image, in seconds
        position_starting_at_one: Whether the embedded track number starts at one
        verbose: Whether to print progress messages
        machine_readable: Whether machine-readable mode is active (suppresses messages)
    """
    position = state.get("position")
    track_number = (
        display_position(int(position), position_starting_at_one)
        if position is not None
        else None
    )

    cover = _fetch_cover(state, host_configuration, timeout, machine_readable)

    try:
        metadata.embed_metadata_and_cover(
            destination,
            title=state.get("title"),
            artist=state.get("artist"),
            album=state.get("album"),
            albumartist=state.get("albumartist"),
            track_number=track_number,
            cover=cover,
        )
    except metadata.UnsupportedAudioFormatError:
        if not machine_readable:
            click.echo(
                f"\nWarning: cannot embed metadata into {destination} (unsupported format)",
                err=True,
            )
        return
    except Exception as e:
        if not machine_readable:
            click.echo(f"\nWarning: cannot embed metadata into {destination} ({e})", err=True)
        return

    if verbose and not machine_readable:
        click.echo(f"\nEmbedded metadata and cover into {destination}...", err=True)


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


def create_client(
    host_configuration: VolumioHostConfiguration, timeout: float
) -> VolumioRESTAPIClient:
    """Create a VolumioRESTAPIClient with the given host configuration.

    Args:
        host_configuration: The host configuration (scheme, host, and ports)
        timeout: Request timeout in seconds

    Returns:
        A configured VolumioRESTAPIClient instance
    """
    return VolumioRESTAPIClient(host_configuration, timeout)


def execute_command(
    ctx: click.Context,
    command_name: str,
    command_func: Callable[[VolumioRESTAPIClient], dict[str, Any]],
) -> None:
    """Execute a playback control command.

    Args:
        ctx: Click context object containing shared options
        command_name: Name of the command (for messages)
        command_func: Function to call on the VolumioRESTAPIClient
    """
    host_configuration = ctx.obj["host_configuration"]
    rest_api_timeout = ctx.obj["rest_api_timeout"]
    verbose = ctx.obj["verbose"]
    machine_readable = ctx.obj["machine_readable"]

    if verbose and not machine_readable:
        click.echo(f"Connecting to {host_configuration.rest_base_url}...", err=True)

    try:
        client = create_client(host_configuration, rest_api_timeout)
        response = command_func(client)

        if verbose and not machine_readable:
            click.echo(f"Response: {response}", err=True)

        if not machine_readable:
            click.echo(f"Command '{command_name}' executed successfully")

    except VolumioConnectionError as e:
        if not machine_readable:
            click.echo(f"Connection error: {e}", err=True)
        sys.exit(1)
    except VolumioAPIError as e:
        if not machine_readable:
            click.echo(f"API error: {e}", err=True)
        sys.exit(1)
    except Exception as e:  # pragma: no cover
        if not machine_readable:
            click.echo(f"Unexpected error: {e}", err=True)
        sys.exit(1)


def fetch_or_exit[T](
    ctx: click.Context,
    fetch: Callable[[VolumioRESTAPIClient], T],
) -> T:
    """Fetch data from the Volumio instance, printing errors and exiting (1) on failure.

    Args:
        ctx: Click context object containing shared options
        fetch: Function to call on the VolumioRESTAPIClient, returning the payload

    Returns:
        Whatever ``fetch`` returns (a dict for the JSON endpoints, text for ping)
    """
    host_configuration = ctx.obj["host_configuration"]
    rest_api_timeout = ctx.obj["rest_api_timeout"]
    verbose = ctx.obj["verbose"]
    machine_readable = ctx.obj["machine_readable"]

    if verbose and not machine_readable:
        click.echo(f"Connecting to {host_configuration.rest_base_url}...", err=True)

    try:
        client = create_client(host_configuration, rest_api_timeout)
        return fetch(client)
    except VolumioConnectionError as e:
        if not machine_readable:
            click.echo(f"Connection error: {e}", err=True)
        sys.exit(1)
    except VolumioAPIError as e:
        if not machine_readable:
            click.echo(f"API error: {e}", err=True)
        sys.exit(1)
    except Exception as e:  # pragma: no cover
        if not machine_readable:
            click.echo(f"Unexpected error: {e}", err=True)
        sys.exit(1)


def fetch_state_or_exit(ctx: click.Context) -> dict[str, Any]:
    """Fetch the current state, printing errors and exiting (1) on failure.

    Args:
        ctx: Click context object containing shared options

    Returns:
        The state dictionary returned by the client
    """
    state: dict[str, Any] = fetch_or_exit(ctx, lambda c: c.get_state())
    return state


def print_resulting_status_option(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``-r``/``--print-resulting-status`` option to a playback subcommand."""
    return click.option(
        "--print-resulting-status/--no-print-resulting-status",
        "-r",
        default=True,
        show_default=True,
        help="After the command, wait 1 second and print the resulting playback status",
    )(func)


def create_download_manifest_option(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``--create-download-manifest`` option to a track download subcommand."""
    return click.option(
        "--create-download-manifest/--no-create-download-manifest",
        default=True,
        show_default=True,
        help="Write a JSON manifest next to the downloaded file (e.g. out.flac.json)",
    )(func)


def add_cover_and_metadata_option(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``--add-cover-and-metadata`` option to the ``track audio`` subcommand."""
    return click.option(
        "--add-cover-and-metadata/--no-add-cover-and-metadata",
        default=True,
        show_default=True,
        help="Embed track metadata and cover art into the downloaded file "
        "(FLAC, MP3, MP4/M4A)",
    )(func)


def fields_option(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``-L``/``--fields`` option to a display subcommand."""
    return click.option(
        "--fields",
        "-L",
        type=click.Choice(["short", "all"], case_sensitive=False),
        default="short",
        show_default=True,
        help="Fields to display (applies to json, pretty, and table formats)",
    )(func)


def file_name_template_option(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``-f``/``--file-name-template`` option to a track download subcommand."""
    return click.option(
        "-f",
        "--file-name-template",
        type=str,
        default="{file_name_from_uri}",
        show_default=True,
        help="Template (Python str.format syntax) for the -d output file name. Keys: "
        "file_name_from_uri, position, title, album, artist, trackType, duration, "
        "bitdepth, samplerate, channels, extension. Spaces become underscores.",
    )(func)


def output_directory_option(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``-d``/``--output-directory`` option to a track download subcommand."""
    return click.option(
        "-d",
        "--output-directory",
        type=str,
        default=None,
        help="Download into this directory, using the file name from the template "
        "(mutually exclusive with -o)",
    )(func)


def output_file_option(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``-o``/``--output-file`` option to a track download subcommand."""
    return click.option(
        "-o",
        "--output-file",
        type=str,
        default=None,
        help="Download to this exact file path (mutually exclusive with -d)",
    )(func)


def overwrite_existing_files_option(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``--overwrite-existing-files`` option to a download or create subcommand."""
    return click.option(
        "--overwrite-existing-files/--no-overwrite-existing-files",
        default=False,
        show_default=True,
        help="Overwrite the destination file if it already exists",
    )(func)


def format_option(help_text: str) -> Callable[[Callable[..., None]], Callable[..., None]]:
    """Return the ``-F``/``--format`` option decorator with the given help text.

    Args:
        help_text: The help text shown for the option

    Returns:
        A Click option decorator adding ``-F``/``--format``
    """
    return click.option(
        "--format",
        "-F",
        "output_format",
        type=click.Choice(OUTPUT_FORMATS, case_sensitive=False),
        default="pretty",
        show_default=True,
        help=help_text,
    )


def rest_api_sleep(ctx: click.Context) -> None:
    """Sleep for the configured delay before making the next REST API call.

    Args:
        ctx: Click context object holding the shared options
    """
    time.sleep(ctx.obj["rest_api_sleep_before_next_call"])


def maybe_print_resulting_status(ctx: click.Context, enabled: bool) -> None:
    """When enabled, wait the configured number of seconds and invoke "playback status".

    Args:
        ctx: Click context object (its ``obj`` is inherited by the invoked command)
        enabled: Whether to print the resulting status
    """
    if enabled:
        rest_api_sleep(ctx)
        ctx.invoke(playback_status)


class SeekParamType(click.ParamType):
    """Click parameter type for the seek position value.

    Accepts any (lowercase) spelling in ``ALIASES``, normalized to its canonical
    keyword, a colon time (HH:MM:SS or MM:SS), or a non-negative integer number
    of seconds; anything else is a usage error.
    """

    name = "seek"

    # Canonical seek keyword -> accepted spellings (lowercase only)
    ALIASES = {
        "minus": ["backward", "decrease", "down", "minus"],
        "plus": ["forward", "increase", "plus", "up"],
    }

    def convert(
        self,
        value: object,
        param: click.Parameter | None,
        ctx: click.Context | None,
    ) -> int | str:
        if isinstance(value, int):
            seconds = value
        else:
            text = str(value)
            for canonical, spellings in self.ALIASES.items():
                if text in spellings:
                    return canonical

            parsed = parse_time_to_seconds(text)
            if parsed is None:
                try:
                    parsed = int(text)
                except ValueError:
                    accepted = ", ".join(
                        sorted(s for spellings in self.ALIASES.values() for s in spellings)
                    )
                    self.fail(
                        f"{text!r} must be a number of seconds, a HH:MM:SS or MM:SS time, "
                        f"or one of {accepted}",
                        param,
                        ctx,
                    )
            seconds = parsed

        if seconds < 0:
            self.fail(f"seek position must be 0 or greater, got {seconds}", param, ctx)
        return seconds


class VolumeParamType(click.ParamType):
    """Click parameter type for the volume value.

    Accepts any (lowercase) spelling in ``ALIASES``, normalized to its canonical
    keyword, or an integer between 0 and 100 (inclusive); anything else is a
    usage error.
    """

    name = "volume"

    # Canonical volume keyword -> accepted spellings (lowercase only)
    ALIASES = {
        "mute": ["mute"],
        "unmute": ["unmute"],
        "plus": ["plus", "increase", "up"],
        "minus": ["minus", "decrease", "down"],
    }

    def convert(
        self,
        value: object,
        param: click.Parameter | None,
        ctx: click.Context | None,
    ) -> int | str:
        if isinstance(value, int):
            return value
        text = str(value)
        for canonical, spellings in self.ALIASES.items():
            if text in spellings:
                return canonical
        try:
            level = int(text)
        except ValueError:
            accepted = ", ".join(
                sorted(s for spellings in self.ALIASES.values() for s in spellings)
            )
            self.fail(
                f"{text!r} must be an integer between 0 and 100 or one of {accepted}",
                param,
                ctx,
            )
        if not 0 <= level <= 100:
            self.fail(f"volume level must be between 0 and 100, got {level}", param, ctx)
        return level


class OnOffParamType(click.ParamType):
    """Click parameter type for an on/off toggle value.

    Accepts "on"/"true"/"yes"/"1" (True) or "off"/"false"/"no"/"0" (False),
    lowercase only; anything else is a usage error.
    """

    name = "on/off"

    # Boolean value -> accepted spellings (lowercase only)
    ALIASES = {True: ["on", "true", "yes", "1"], False: ["off", "false", "no", "0"]}

    def convert(
        self,
        value: object,
        param: click.Parameter | None,
        ctx: click.Context | None,
    ) -> bool:
        if isinstance(value, bool):
            return value
        text = str(value)
        for canonical, spellings in self.ALIASES.items():
            if text in spellings:
                return canonical
        accepted = ", ".join(
            sorted(s for spellings in self.ALIASES.values() for s in spellings)
        )
        self.fail(f"{text!r} must be one of {accepted}", param, ctx)


def configuration_file_callback(
    ctx: click.Context, param: click.Parameter, value: str | None
) -> str | None:
    """Load the configuration file (if any) and use its values as option defaults.

    Runs eagerly, before the other options resolve, so the loaded values populate
    ``ctx.default_map`` and are only used where the user did not pass an explicit flag.
    """
    path = resolve_configuration_path(value)
    if path is not None:
        config = load_configuration(path)
        ctx.default_map = {**(ctx.default_map or {}), **build_click_default_map(config)}
    ctx.ensure_object(dict)
    ctx.obj["configuration_file"] = path
    return value


@click.group()
@click.option(
    "--configuration-file",
    "-c",
    type=str,
    default=None,
    is_eager=True,
    expose_value=False,
    callback=configuration_file_callback,
    help=(
        "Path to a YAML configuration file whose values are used as option defaults "
        "(explicit options still override them); if omitted, standard locations in the "
        "current directory and the home directory are tried (see the documentation)"
    ),
)
@click.option(
    "--host",
    "-H",
    type=str,
    default="volumio.local",
    show_default=True,
    help="Hostname or IP address of the Volumio instance",
)
@click.option(
    "--machine-readable",
    "-m",
    is_flag=True,
    default=False,
    help=(
        "Produce machine-readable output only "
        "(superseding the --verbose option if also specified)"
    ),
)
@click.option(
    "--mpd-port",
    "-M",
    type=int,
    default=6600,
    show_default=True,
    help="MPD port of the Volumio instance",
)
@click.option(
    "--mpd-timeout",
    type=float,
    default=5.0,
    show_default=True,
    help="MPD connection timeout in seconds",
)
@click.option(
    "--position-starting-at-one/--position-starting-at-zero",
    default=True,
    show_default=True,
    help="Index queue positions and track numbers starting at one (or at zero)",
)
@click.option(
    "--rest-api-port",
    "-P",
    type=int,
    default=3000,
    show_default=True,
    help="REST API port of the Volumio instance",
)
@click.option(
    "--rest-api-sleep-before-next-call",
    type=float,
    default=1.0,
    show_default=True,
    help="Seconds to sleep before making the next REST API call",
)
@click.option(
    "--rest-api-timeout",
    type=float,
    default=5.0,
    show_default=True,
    help="REST API request timeout in seconds",
)
@click.option(
    "--scheme",
    type=click.Choice(["http", "https"], case_sensitive=False),
    default="http",
    show_default=True,
    help="URL scheme to use for connecting to Volumio instance",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    default=False,
    help="Enable verbose output",
)
@click.pass_context
def main(
    ctx: click.Context,
    host: str,
    machine_readable: bool,
    mpd_port: int,
    mpd_timeout: float,
    position_starting_at_one: bool,
    rest_api_port: int,
    rest_api_sleep_before_next_call: float,
    rest_api_timeout: float,
    scheme: Literal["http", "https"],
    verbose: bool,
) -> None:
    """volumito - CLI tool for Volumio."""
    # Store common options in context for subcommands to access
    ctx.ensure_object(dict)
    ctx.obj["host_configuration"] = VolumioHostConfiguration(
        scheme=scheme,
        host=host,
        rest_api_port=rest_api_port,
        mpd_port=mpd_port,
    )
    ctx.obj["rest_api_timeout"] = rest_api_timeout
    ctx.obj["mpd_timeout"] = mpd_timeout
    ctx.obj["rest_api_sleep_before_next_call"] = rest_api_sleep_before_next_call
    ctx.obj["verbose"] = verbose
    ctx.obj["machine_readable"] = machine_readable
    ctx.obj["position_starting_at_one"] = position_starting_at_one

    configuration_file = ctx.obj.get("configuration_file")
    if verbose and not machine_readable and configuration_file is not None:
        click.echo(f"Using configuration file: {configuration_file}", err=True)


@main.command()
@click.pass_context
def version(ctx: click.Context) -> None:
    """Show the volumito version.

    In machine-readable mode the version string is printed quoted (e.g. ``"0.0.10"``)
    so it can be consumed by jq/yq; otherwise the program name is included.
    """
    if ctx.obj["machine_readable"]:
        msg = f'"{VERSION}"'
    else:
        msg = f"volumito, version {VERSION}"
    click.echo(msg)


def root_option_defaults(ctx: click.Context) -> dict[str, Any]:
    """Return the hardcoded default of each option declared on the top-level group.

    Keyed by CLI parameter name (with underscores). Used to render a configuration
    file that mirrors the built-in defaults, avoiding any duplication of values.
    """
    root_command = ctx.find_root().command
    return {
        param.name: param.default
        for param in root_command.params
        if isinstance(param, click.Option) and param.name is not None
    }


def command_scoped_option_defaults() -> dict[str, Any]:
    """Return the defaults of the per-command options used in the configuration file.

    These options live on subcommands, not the top-level group: fields/format on
    ``playback status``, print-resulting-status on the playback and queue action commands,
    the download options on ``track audio``, check-playlist-name on ``playlist play``,
    and check-seek-position on ``playback seek``. Read them from the ``playback_status``,
    ``toggle``, ``audio``, ``playlist_play``, and ``seek`` command objects so the
    generated configuration mirrors the real defaults without duplication.
    """
    wanted = {
        "add_cover_and_metadata",
        "check_playlist_name",
        "check_seek_position",
        "create_download_manifest",
        "fields",
        "output_format",
        "print_resulting_status",
        "file_name_template",
        "output_directory",
        "output_file",
        "overwrite_existing_files",
    }
    defaults: dict[str, Any] = {}
    for command in (playback_status, toggle, audio, playlist_play, seek):
        for param in command.params:
            if isinstance(param, click.Option) and param.name in wanted:
                defaults[param.name] = param.default
    return defaults


@main.group()
@click.pass_context
def configuration(ctx: click.Context) -> None:
    """Create, check, and search for volumito configuration files."""
    pass


@configuration.command("create")
@click.pass_context
@click.option(
    "--output-directory",
    "-d",
    type=str,
    default=None,
    help="Directory in which to create a volumito.yaml file",
)
@click.option(
    "--output-file",
    "-f",
    type=str,
    default=None,
    help="Exact path of the configuration file to create",
)
@overwrite_existing_files_option
def configuration_create(
    ctx: click.Context,
    output_directory: str | None,
    output_file: str | None,
    overwrite_existing_files: bool,
) -> None:
    """Create a configuration file with all known keys set to their default values."""
    machine_readable = ctx.obj["machine_readable"]

    if output_directory is not None and output_file is not None:
        raise click.UsageError(MUTUALLY_EXCLUSIVE_CREATE_ERROR)

    if output_file is not None:
        destination = output_file
    elif output_directory is not None:
        destination = os.path.join(output_directory, CONFIGURATION_FILENAMES[0])
    else:
        destination = os.path.join(os.getcwd(), CONFIGURATION_FILENAMES[0])

    if not overwrite_existing_files and os.path.exists(destination):
        if not machine_readable:
            click.echo(
                f"Error: file already exists: {destination} "
                "(use --overwrite-existing-files to overwrite)",
                err=True,
            )
        sys.exit(1)

    defaults = {**root_option_defaults(ctx), **command_scoped_option_defaults()}
    content = render_default_configuration(defaults, VERSION)
    try:
        parent = os.path.dirname(destination)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(destination, "w", encoding="utf-8") as config_file:
            config_file.write(content)
    except OSError as e:
        if not machine_readable:
            click.echo(f"Error: cannot write configuration file {destination}: {e}", err=True)
        sys.exit(1)

    if machine_readable:
        click.echo(json.dumps(destination))
    else:
        click.echo(f"Created configuration file {destination}")


@configuration.command("check")
@click.pass_context
@click.argument("path", required=False, type=str)
def configuration_check(ctx: click.Context, path: str | None) -> None:
    """Verify that a configuration file is correct and print the values read from it.

    If PATH is omitted, the standard locations are probed and the file that would
    be used is checked.
    """
    machine_readable = ctx.obj["machine_readable"]

    if path is not None:
        resolved = resolve_configuration_path(path)
    else:
        resolved = resolve_configuration_path(None)
        if resolved is None:
            if not machine_readable:
                click.echo("Error: no configuration file found", err=True)
            sys.exit(1)

    config = load_configuration(resolved)  # type: ignore[arg-type]

    if machine_readable:
        click.echo(json.dumps(config))
    else:
        click.echo(f"Configuration file {resolved} is valid.")
        for dotted, value in flatten_configuration(config):
            click.echo(f"{dotted} = {value}")


@configuration.command("search")
@click.pass_context
def configuration_search(ctx: click.Context) -> None:
    """List every probed configuration path, marking those found and the one used."""
    machine_readable = ctx.obj["machine_readable"]

    rows = probe_configuration_paths()

    if machine_readable:
        click.echo(
            json.dumps(
                [{"path": path, "found": found, "used": used} for path, found, used in rows]
            )
        )
        return

    click.echo("Configuration file locations, in probing order, in decreasing order of priority:")
    for path, found, used in rows:
        if not found:
            click.echo(f"  {path}")
        elif used:
            click.echo(f"  {path} (found, used)")
        else:
            click.echo(f"  {path} (found, NOT used)")


def render_state(
    ctx: click.Context,
    fields: str,
    output_format: str,
    short_fields: list[str],
    heading: str = "Volumio Status",
) -> None:
    """Fetch the current state and print it per the fields/format options.

    Args:
        ctx: Click context object containing shared options
        fields: The fields option ("short" or "all")
        output_format: The output format ("json", "pretty", "raw", or "table")
        short_fields: The list of keys to keep when ``fields`` is "short"
        heading: The heading line for the table output format
    """
    verbose = ctx.obj["verbose"]
    machine_readable = ctx.obj["machine_readable"]
    position_starting_at_one = ctx.obj["position_starting_at_one"]

    state = fetch_state_or_exit(ctx)

    if verbose and not machine_readable:
        click.echo("Successfully retrieved state", err=True)

    # Determine output format
    if output_format == "raw":
        # Raw JSON without formatting (ignores fields filter)
        output = json.dumps(state)
    else:
        # Apply fields filter for all formatted outputs
        filtered_state = filter_fields(state, fields, short_fields)  # type: ignore[arg-type]

        if output_format == "table":
            # Preserve the short_fields order (and their labels) in the table
            field_order = short_fields if fields == "short" else None
            output = format_as_table(
                filtered_state,
                heading=heading,
                field_order=field_order,
                position_starting_at_one=position_starting_at_one,
            )
        elif output_format == "json":
            output = format_as_json(filtered_state)
        else:  # pretty
            output = format_as_pretty(filtered_state, position_starting_at_one)

    click.echo(output)


def render_payload(
    ctx: click.Context,
    data: dict[str, Any],
    output_format: str,
    heading: str,
) -> None:
    """Print a JSON payload per the format option, or compact in machine-readable mode.

    Args:
        ctx: Click context object containing shared options
        data: The JSON object to print
        output_format: The output format ("json", "pretty", "raw", or "table")
        heading: The heading line for the table output format
    """
    if ctx.obj["machine_readable"] or output_format == "raw":
        output = json.dumps(data)
    elif output_format == "json":
        output = format_as_json(data)
    elif output_format == "table":
        output = format_as_table(
            data,
            heading=heading,
            position_starting_at_one=ctx.obj["position_starting_at_one"],
        )
    else:  # pretty
        output = format_as_pretty(data, ctx.obj["position_starting_at_one"])

    click.echo(output)


@main.group()
@click.pass_context
def playback(ctx: click.Context) -> None:
    """Commands for controlling the playback of the Volumio instance."""
    pass


@playback.command("status")
@click.pass_context
@fields_option
@format_option("Output format for the state information")
def playback_status(
    ctx: click.Context,
    fields: str,
    output_format: str,
) -> None:
    """Get the current playback status from a Volumio instance.

    Retrieves and displays the current state of a Volumio music player instance,
    including playback status, volume, track information, and more.
    """
    render_state(ctx, fields, output_format, PLAYER_STATE_SHORT_FIELDS)


@playback.command()
@click.pass_context
@print_resulting_status_option
def toggle(ctx: click.Context, print_resulting_status: bool) -> None:
    """Toggle between play and pause states of the Volumio instance."""
    execute_command(ctx, "toggle", lambda c: c.toggle())
    maybe_print_resulting_status(ctx, print_resulting_status)


@playback.command()
@click.pass_context
@click.option(
    "--position",
    "-p",
    type=int,
    default=None,
    help=(
        "Position in the queue to play (indexed according to "
        "--position-starting-at-one/--position-starting-at-zero)"
    ),
)
@print_resulting_status_option
def play(ctx: click.Context, position: int | None, print_resulting_status: bool) -> None:
    """Start playback of the Volumio instance.

    Optionally specify a position to play a specific track in the queue.
    """
    if position is not None:
        starting_at_one = ctx.obj["position_starting_at_one"]
        minimum = 1 if starting_at_one else 0
        if position < minimum:
            raise click.UsageError(f"position must be {minimum} or greater, got {position}")
        if starting_at_one:
            position -= 1
        execute_command(ctx, "play", lambda c: c.play(position))
    else:
        execute_command(ctx, "play", lambda c: c.play())
    maybe_print_resulting_status(ctx, print_resulting_status)


@playback.command()
@click.pass_context
@print_resulting_status_option
def pause(ctx: click.Context, print_resulting_status: bool) -> None:
    """Pause playback of the Volumio instance."""
    execute_command(ctx, "pause", lambda c: c.pause())
    maybe_print_resulting_status(ctx, print_resulting_status)


@playback.command()
@click.pass_context
@print_resulting_status_option
def stop(ctx: click.Context, print_resulting_status: bool) -> None:
    """Stop playback of the Volumio instance."""
    execute_command(ctx, "stop", lambda c: c.stop())
    maybe_print_resulting_status(ctx, print_resulting_status)


@playback.command()
@click.pass_context
@print_resulting_status_option
def next(ctx: click.Context, print_resulting_status: bool) -> None:
    """Skip to the next track of the Volumio instance."""
    execute_command(ctx, "next", lambda c: c.next())
    maybe_print_resulting_status(ctx, print_resulting_status)


@playback.command()
@click.pass_context
@print_resulting_status_option
def previous(ctx: click.Context, print_resulting_status: bool) -> None:
    """Skip to the previous track of the Volumio instance."""
    execute_command(ctx, "previous", lambda c: c.previous())
    maybe_print_resulting_status(ctx, print_resulting_status)


@playback.command()
@click.pass_context
@click.argument("value", required=False, default=None, type=SeekParamType())
@click.option(
    "--check-seek-position/--no-check-seek-position",
    default=True,
    show_default=True,
    help="Check that the seek position is within the duration of the current track",
)
@print_resulting_status_option
def seek(
    ctx: click.Context,
    value: int | str | None,
    check_seek_position: bool,
    print_resulting_status: bool,
) -> None:
    """Print, set, or adjust the seek position of the Volumio instance.

    Without VALUE, print the current position as HH:MM:SS.mmm. Otherwise VALUE is
    the position to seek to, as a number of seconds or as a HH:MM:SS (or MM:SS)
    time, or one of "plus" (also "increase"/"up"/"forward") and "minus" (also
    "decrease"/"down"/"backward") to seek relatively to the current position.

    Unless --no-check-seek-position is given, an absolute position is checked
    against the duration of the current track, when the latter is known.
    """
    if value is None:
        state = fetch_state_or_exit(ctx)
        current = state.get("seek")
        if not isinstance(current, int):
            if not ctx.obj["machine_readable"]:
                click.echo("Error: no seek position found in current state", err=True)
            sys.exit(1)
        position = format_seek(current)
        click.echo(json.dumps(position) if ctx.obj["machine_readable"] else position)
        return

    if check_seek_position and isinstance(value, int):
        duration = fetch_state_or_exit(ctx).get("duration")
        # The duration is unknown for web radios and streams: skip the check
        if isinstance(duration, int) and duration > 0 and value > duration:
            if not ctx.obj["machine_readable"]:
                click.echo(
                    f"Error: seek position out of range: {format_duration(value)} "
                    f"(current track duration: {format_duration(duration)})",
                    err=True,
                )
            sys.exit(1)

    execute_command(ctx, f"seek {value}", lambda c: c.seek(value))
    maybe_print_resulting_status(ctx, print_resulting_status)


@playback.command()
@click.pass_context
@click.argument("value", required=False, default=None, type=VolumeParamType())
@print_resulting_status_option
def volume(ctx: click.Context, value: int | str | None, print_resulting_status: bool) -> None:
    """Set, adjust, or show the volume of the Volumio instance.

    Without VALUE, print the current volume. Otherwise VALUE is an integer
    between 0 and 100 (inclusive) to set an absolute level, or one of "mute",
    "unmute", "plus" (also "increase"/"up"), "minus" (also "decrease"/"down").
    """
    if value is None:
        state = fetch_state_or_exit(ctx)
        click.echo(state.get("volume"))
        return
    execute_command(ctx, f"volume {value}", lambda c: c.volume(value))
    maybe_print_resulting_status(ctx, print_resulting_status)


@playback.command()
@click.pass_context
@print_resulting_status_option
def mute(ctx: click.Context, print_resulting_status: bool) -> None:
    """Mute the volume of the Volumio instance (synonym for `playback volume mute`)."""
    execute_command(ctx, "volume mute", lambda c: c.volume("mute"))
    maybe_print_resulting_status(ctx, print_resulting_status)


@playback.command()
@click.pass_context
@print_resulting_status_option
def unmute(ctx: click.Context, print_resulting_status: bool) -> None:
    """Unmute the volume of the Volumio instance (synonym for `playback volume unmute`)."""
    execute_command(ctx, "volume unmute", lambda c: c.volume("unmute"))
    maybe_print_resulting_status(ctx, print_resulting_status)


@main.group()
@click.pass_context
def track(ctx: click.Context) -> None:
    """Retrieve information, audio, and album art of the current track of the Volumio instance."""
    pass


@track.command("info")
@click.pass_context
@fields_option
@format_option("Output format for the track information")
def track_info(
    ctx: click.Context,
    fields: str,
    output_format: str,
) -> None:
    """Print the information of the current track."""
    render_state(ctx, fields, output_format, TRACK_INFO_SHORT_FIELDS, heading="Track Info")


@track.command()
@click.pass_context
@file_name_template_option
@output_directory_option
@output_file_option
@overwrite_existing_files_option
@create_download_manifest_option
@add_cover_and_metadata_option
def audio(
    ctx: click.Context,
    file_name_template: str,
    output_directory: str | None,
    output_file: str | None,
    overwrite_existing_files: bool,
    create_download_manifest: bool,
    add_cover_and_metadata: bool,
) -> None:
    """Print the URI of the audio of the current track.

    Optionally download the track to a file with -o/--output-file (an exact file
    path) or into a directory with -d/--output-directory (the file name is rendered from
    -f/--file-name-template); the -o and -d options are mutually exclusive.
    """
    if output_file is not None and output_directory is not None:
        raise click.UsageError(MUTUALLY_EXCLUSIVE_OUTPUT_ERROR)

    host_configuration = ctx.obj["host_configuration"]
    rest_api_timeout = ctx.obj["rest_api_timeout"]
    mpd_timeout = ctx.obj["mpd_timeout"]
    verbose = ctx.obj["verbose"]
    machine_readable = ctx.obj["machine_readable"]

    if verbose and not machine_readable:
        click.echo(f"Connecting to {host_configuration.rest_base_url}...", err=True)

    try:
        # Get current track metadata (also validates REST connectivity)
        client = create_client(host_configuration, rest_api_timeout)
        state = client.get_state()

        if verbose and not machine_readable:
            click.echo("Successfully retrieved state", err=True)
            click.echo(
                f"Connecting to MPD at "
                f"{host_configuration.host}:{host_configuration.mpd_port}...",
                err=True,
            )

        # Connect to MPD to get current track URI
        with VolumioMPDClient(host_configuration, mpd_timeout) as mpd_client:
            if verbose and not machine_readable:
                click.echo("Successfully connected to MPD", err=True)

            # Get track URI with localhost replaced
            uri = mpd_client.get_track_uri()

            if verbose and not machine_readable:
                click.echo(f"Track URI: {uri}", err=True)

            # Always print the URI (even in machine-readable mode);
            # in machine-readable mode print it quoted so it can be consumed by jq/yq
            click.echo(json.dumps(uri) if machine_readable else uri)

            # Download the file if -o/--output-file or -d/--output-directory is specified
            if output_file is not None or output_directory is not None:
                destination = download_uri_to(
                    uri,
                    output_file,
                    output_directory,
                    file_name_template,
                    "flac",
                    state,
                    overwrite_existing_files,
                    "track",
                    rest_api_timeout,
                    verbose,
                    machine_readable,
                    create_download_manifest,
                    host_configuration,
                    "track",
                    "audio",
                    ctx.obj["position_starting_at_one"],
                    add_cover_and_metadata,
                )

                # Embed track metadata and cover art into the downloaded file
                if add_cover_and_metadata:
                    embed_track_tags(
                        destination,
                        state,
                        host_configuration,
                        rest_api_timeout,
                        ctx.obj["position_starting_at_one"],
                        verbose,
                        machine_readable,
                    )

    except click.UsageError:
        # A bad --file-name-template should surface as a usage error, not be
        # swallowed by the generic handler below.
        raise
    except VolumioConnectionError as e:
        if not machine_readable:
            click.echo(f"Connection error: {e}", err=True)
        sys.exit(1)
    except VolumioAPIError as e:
        if not machine_readable:
            click.echo(f"API error: {e}", err=True)
        sys.exit(1)
    except Exception as e:  # pragma: no cover
        if not machine_readable:
            click.echo(f"Unexpected error: {e}", err=True)
        sys.exit(1)


@track.command()
@click.pass_context
@file_name_template_option
@output_directory_option
@output_file_option
@overwrite_existing_files_option
@create_download_manifest_option
def albumart(
    ctx: click.Context,
    file_name_template: str,
    output_directory: str | None,
    output_file: str | None,
    overwrite_existing_files: bool,
    create_download_manifest: bool,
) -> None:
    """Print the URI of the album art of the current track.

    Optionally download the image to a file with -o/--output-file (an exact file
    path) or into a directory with -d/--output-directory (the file name is rendered from
    -f/--file-name-template); the -o and -d options are mutually exclusive.
    """
    if output_file is not None and output_directory is not None:
        raise click.UsageError(MUTUALLY_EXCLUSIVE_OUTPUT_ERROR)

    host_configuration = ctx.obj["host_configuration"]
    rest_api_timeout = ctx.obj["rest_api_timeout"]
    verbose = ctx.obj["verbose"]
    machine_readable = ctx.obj["machine_readable"]

    if verbose and not machine_readable:
        click.echo(f"Connecting to {host_configuration.rest_base_url}...", err=True)

    try:
        # Get current state metadata
        client = create_client(host_configuration, rest_api_timeout)
        state = client.get_state()

        if verbose and not machine_readable:
            click.echo("Successfully retrieved state", err=True)

        # Extract albumart URI (relative URIs are made absolute against the base URL)
        albumart_uri = resolve_albumart_uri(state, host_configuration)
        if albumart_uri is None:
            if not machine_readable:
                click.echo("Error: No album art URI found in current state", err=True)
            sys.exit(1)

        if verbose and not machine_readable:
            click.echo(f"Album art URI: {albumart_uri}", err=True)

        # Always print the URI (even in machine-readable mode);
        # in machine-readable mode print it quoted so it can be consumed by jq/yq
        click.echo(json.dumps(albumart_uri) if machine_readable else albumart_uri)

        # Download the file if -o/--output-file or -d/--output-directory is specified
        if output_file is not None or output_directory is not None:
            download_uri_to(
                albumart_uri,
                output_file,
                output_directory,
                file_name_template,
                "jpg",
                state,
                overwrite_existing_files,
                "album art",
                rest_api_timeout,
                verbose,
                machine_readable,
                create_download_manifest,
                host_configuration,
                "track",
                "albumart",
                ctx.obj["position_starting_at_one"],
            )

    except click.UsageError:
        # A bad --file-name-template should surface as a usage error, not be
        # swallowed by the generic handler below.
        raise
    except VolumioConnectionError as e:
        if not machine_readable:
            click.echo(f"Connection error: {e}", err=True)
        sys.exit(1)
    except VolumioAPIError as e:
        if not machine_readable:
            click.echo(f"API error: {e}", err=True)
        sys.exit(1)
    except Exception as e:  # pragma: no cover
        if not machine_readable:
            click.echo(f"Unexpected error: {e}", err=True)
        sys.exit(1)


@main.group()
@click.pass_context
def queue(ctx: click.Context) -> None:
    """Commands for managing the playback queue of the Volumio instance."""
    pass


@queue.command("get")
@click.pass_context
@fields_option
@format_option("Output format for the queue information")
def queue_get(
    ctx: click.Context,
    fields: str,
    output_format: str,
) -> None:
    """Get the playback queue.

    This command retrieves and prints the current playback queue,
    showing all queued tracks with their metadata.
    """
    host_configuration = ctx.obj["host_configuration"]
    rest_api_timeout = ctx.obj["rest_api_timeout"]
    verbose = ctx.obj["verbose"]
    machine_readable = ctx.obj["machine_readable"]
    position_starting_at_one = ctx.obj["position_starting_at_one"]

    if verbose and not machine_readable:
        click.echo(f"Connecting to {host_configuration.rest_base_url}...", err=True)

    try:
        client = create_client(host_configuration, rest_api_timeout)
        queue_data = client.get_queue()

        if verbose and not machine_readable:
            click.echo("Successfully retrieved queue", err=True)

        # Determine output format
        if output_format == "raw":
            # Raw JSON without formatting (ignores fields filter)
            output = json.dumps(queue_data)
        else:
            # Apply fields filter for all formatted outputs
            tracks = filter_queue_fields(queue_data, fields)  # type: ignore[arg-type]

            # Map output format to formatting function
            if output_format == "json":
                output = json.dumps(tracks, indent=2)
            elif output_format == "pretty":
                # Format durations as HH:MM:SS for pretty output
                pretty_tracks = []
                for track in rebase_queue_positions(tracks, position_starting_at_one):
                    pretty_track = track.copy()
                    if "duration" in pretty_track and isinstance(pretty_track["duration"], int):
                        pretty_track["duration"] = format_duration(pretty_track["duration"])
                    pretty_tracks.append(pretty_track)
                output = json.dumps(pretty_tracks, indent=4, sort_keys=True, ensure_ascii=False)
            elif output_format == "table":
                output = format_queue_as_table(
                    rebase_queue_positions(tracks, position_starting_at_one)
                )
            else:  # pragma: no cover
                output = json.dumps(tracks, indent=2)

        click.echo(output)

    except VolumioConnectionError as e:
        if not machine_readable:
            click.echo(f"Connection error: {e}", err=True)
        sys.exit(1)
    except VolumioAPIError as e:
        if not machine_readable:
            click.echo(f"API error: {e}", err=True)
        sys.exit(1)
    except Exception as e:  # pragma: no cover
        if not machine_readable:
            click.echo(f"Unexpected error: {e}", err=True)
        sys.exit(1)


@queue.command()
@click.pass_context
@print_resulting_status_option
def clear(ctx: click.Context, print_resulting_status: bool) -> None:
    """Clear the playback queue of the Volumio instance."""
    execute_command(ctx, "clear", lambda c: c.clear())
    maybe_print_resulting_status(ctx, print_resulting_status)


@queue.command()
@click.pass_context
@click.argument("value", required=False, default=None, type=OnOffParamType())
@print_resulting_status_option
def repeat(ctx: click.Context, value: bool | None, print_resulting_status: bool) -> None:
    """Set or toggle the repeat mode of the Volumio instance.

    Without VALUE, toggle the current mode. Otherwise VALUE is "on"/"true"/"yes"/"1"
    or "off"/"false"/"no"/"0".
    """
    label = "repeat" if value is None else f"repeat {'on' if value else 'off'}"
    execute_command(ctx, label, lambda c: c.repeat(value))
    maybe_print_resulting_status(ctx, print_resulting_status)


@queue.command()
@click.pass_context
@click.argument("value", required=False, default=None, type=OnOffParamType())
@print_resulting_status_option
def randomize(ctx: click.Context, value: bool | None, print_resulting_status: bool) -> None:
    """Set or toggle the random (shuffle) mode of the Volumio instance.

    Without VALUE, toggle the current mode. Otherwise VALUE is "on"/"true"/"yes"/"1"
    or "off"/"false"/"no"/"0".
    """
    label = "randomize" if value is None else f"randomize {'on' if value else 'off'}"
    execute_command(ctx, label, lambda c: c.randomize(value))
    maybe_print_resulting_status(ctx, print_resulting_status)


@main.group()
@click.pass_context
def system(ctx: click.Context) -> None:
    """Query system utilities of the Volumio instance."""
    pass


@system.command("ping")
@click.pass_context
def system_ping(ctx: click.Context) -> None:
    """Ping the Volumio instance (prints pong on success)."""
    text = fetch_or_exit(ctx, lambda c: c.ping()).strip()
    if ctx.obj["machine_readable"]:
        click.echo(json.dumps(text))
    else:
        click.echo(text)


@system.command("version")
@click.pass_context
@format_option("Output format for the system version")
def system_version(ctx: click.Context, output_format: str) -> None:
    """Get the system version of the Volumio instance."""
    data = fetch_or_exit(ctx, lambda c: c.get_system_version())
    render_payload(ctx, data, output_format, heading="Volumio System Version")


@system.command("info")
@click.pass_context
@format_option("Output format for the system information")
def system_info(ctx: click.Context, output_format: str) -> None:
    """Get the system information of the Volumio instance."""
    data = fetch_or_exit(ctx, lambda c: c.get_system_info())
    render_payload(ctx, data, output_format, heading="Volumio System Info")


@main.group()
@click.pass_context
def collection(ctx: click.Context) -> None:
    """Query the music collection of the Volumio instance."""
    pass


@collection.command("statistics")
@click.pass_context
@format_option("Output format for the collection statistics")
def collection_statistics(ctx: click.Context, output_format: str) -> None:
    """Get the statistics of the music collection of the Volumio instance."""
    data = fetch_or_exit(ctx, lambda c: c.collectionstats())
    render_payload(ctx, data, output_format, heading="Collection Statistics")


@main.group()
@click.pass_context
def zones(ctx: click.Context) -> None:
    """Query the multiroom zones of the Volumio instance."""
    pass


@zones.command("get")
@click.pass_context
@fields_option
@format_option("Output format for the zones information")
def zones_get(ctx: click.Context, fields: str, output_format: str) -> None:
    """Get the multiroom zones seen by the Volumio instance."""
    data = fetch_or_exit(ctx, lambda c: c.get_zones())

    if output_format == "raw":
        # Raw JSON without formatting (ignores fields filter)
        output = json.dumps(data)
    else:
        filtered_zones = filter_zones_fields(data, fields)  # type: ignore[arg-type]
        if output_format == "json":
            output = json.dumps(filtered_zones, indent=2)
        elif output_format == "table":
            output = format_zones_as_table(filtered_zones)
        else:  # pretty
            output = json.dumps(filtered_zones, indent=4, sort_keys=True, ensure_ascii=False)

    click.echo(output)


@main.group()
@click.pass_context
def playlist(ctx: click.Context) -> None:
    """Query and play the saved playlists of the Volumio instance."""
    pass


@playlist.command("list")
@click.pass_context
@format_option("Output format for the playlists")
def playlist_list(ctx: click.Context, output_format: str) -> None:
    """List the playlists saved on the Volumio instance."""
    names = fetch_or_exit(ctx, lambda c: c.list_playlists())

    if output_format == "raw":
        output = json.dumps(names)
    elif output_format == "json":
        output = json.dumps(names, indent=2)
    elif output_format == "table":
        output = format_playlists_as_table(names)
    else:  # pretty
        output = json.dumps(names, indent=4, ensure_ascii=False)

    click.echo(output)


@playlist.command("play")
@click.pass_context
@click.argument("name", type=str)
@click.option(
    "--check-playlist-name/--no-check-playlist-name",
    default=True,
    show_default=True,
    help="Check that the playlist name exists before playing it",
)
@print_resulting_status_option
def playlist_play(
    ctx: click.Context,
    name: str,
    check_playlist_name: bool,
    print_resulting_status: bool,
) -> None:
    """Start playback of the playlist named NAME.

    The Volumio API does not report an error for a name matching no playlist, so
    unless --no-check-playlist-name is given, the name is looked up first.
    """
    if check_playlist_name:
        names = fetch_or_exit(ctx, lambda c: c.list_playlists())
        if name not in names:
            if not ctx.obj["machine_readable"]:
                click.echo(f"Error: playlist not found: {name}", err=True)
                click.echo("Available playlists:", err=True)
                for available in names or ["(none)"]:
                    click.echo(f"  {available}", err=True)
            sys.exit(1)

    execute_command(ctx, f"playplaylist {name}", lambda c: c.play_playlist(name))
    maybe_print_resulting_status(ctx, print_resulting_status)


# "info" is a top-level synonym for "system info"
main.add_command(system_info, name="info")


if __name__ == "__main__":  # pragma: no cover
    main()
