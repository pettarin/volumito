"""Command-line interface for volumito.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

import json
import os
import sys
import time
from collections.abc import Callable
from typing import Any, Literal

import click
import requests

from volumito.cli.configuration import load_default_map, resolve_configuration_path
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
    "Options -o/--output-file and -d/--output-dir are mutually exclusive."
)

# Short fields list for the "player state" command
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

# Version of the CLI (and of the underlying library)
VERSION = "0.0.10"


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


def format_as_pretty(state: dict[str, Any]) -> str:
    """Format the state dictionary as pretty JSON with 4-space indentation.

    Keys are sorted alphabetically, Unicode escape sequences are unescaped,
    leading/trailing spaces are removed from string values, and duration
    is formatted as HH:MM:SS.

    Args:
        state: The (potentially filtered) state dictionary from the Volumio API

    Returns:
        A formatted JSON string with 4-space indentation
    """
    # Strip leading/trailing spaces from string values and format duration
    cleaned_state = {}
    for key, value in state.items():
        if isinstance(value, str):
            cleaned_state[key] = value.strip()
        elif key == "position" and isinstance(value, int):
            cleaned_state[key] = str(value + 1)
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
    template: str, uri: str, state: dict[str, Any], default_extension: str
) -> str:
    """Render an output file name from a template, track metadata, and the URI.

    The template uses Python ``str.format`` syntax. Supported keys are:
    ``file_name_from_uri``, ``position`` (1-indexed int), ``title``, ``album``,
    ``artist``, ``trackType``, ``duration`` (HH:MM:SS), ``bitdepth``,
    ``samplerate``, ``channels`` (int), and ``extension``. The ``extension`` is
    taken from the URI file name, falling back to ``default_extension`` when the
    URI file has none. Spaces in the rendered name are replaced with underscores.

    Args:
        template: The file-name template (``str.format`` syntax)
        uri: The URI being downloaded (source of ``file_name_from_uri`` and ``extension``)
        state: The current player state dictionary
        default_extension: Extension to use when the URI file has none (no leading dot)

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
        "position": int(state.get("position") or 0) + 1,
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
    output_dir: str | None,
    file_name_template: str,
    default_extension: str,
    state: dict[str, Any],
    overwrite: bool,
    label: str,
    timeout: float,
    verbose: bool,
    machine_readable: bool,
) -> None:
    """Download ``uri`` to a file, printing errors and exiting (1) on failure.

    Exactly one of ``output_file`` / ``output_dir`` is expected to be set. With
    ``output_file`` the URI is saved to that exact path; with ``output_dir`` it is
    saved into that directory under the file name produced by rendering
    ``file_name_template`` against ``state`` (see ``render_output_filename``).
    Unless ``overwrite`` is true, an existing destination file is left untouched.

    Args:
        uri: The URI to download
        output_file: Exact destination file path, or None
        output_dir: Destination directory (file name from the template), or None
        file_name_template: Template for the ``output_dir`` file name
        default_extension: Extension for the ``{extension}`` key when the URI has none
        state: The current player state dictionary (source of template values)
        overwrite: Whether to overwrite the destination file if it already exists
        label: Human-readable noun for messages ("track" or "album art")
        timeout: Request timeout in seconds
        verbose: Whether to print progress messages
        machine_readable: Whether machine-readable mode is active (suppresses messages)
    """
    if output_file is not None:
        destination = output_file
    else:  # output_dir is not None
        filename = render_output_filename(file_name_template, uri, state, default_extension)
        if not filename:
            if not machine_readable:
                click.echo("\nError: cannot determine a file name for the download", err=True)
            sys.exit(1)
        destination = os.path.join(output_dir, filename)  # type: ignore[arg-type]

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

    except requests.exceptions.RequestException as e:
        if not machine_readable:
            click.echo(f"\nDownload error: {e}", err=True)
        sys.exit(1)
    except OSError as e:
        if not machine_readable:
            click.echo(f"\nFile write error: {e}", err=True)
        sys.exit(1)


def format_as_table(
    state: dict[str, Any],
    heading: str = "Volumio State",
    field_order: list[str] | None = None,
) -> str:
    """Format the state dictionary as a readable table.

    Args:
        state: The (potentially filtered) state dictionary from the Volumio API
        heading: The heading line printed above the table
        field_order: When given, the keys to display in this exact order (with
            title-cased labels); otherwise labels and order are derived from the
            state (predefined labels for the short set, sorted keys otherwise)

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
            # The Volumio HTTP API returns "position" starting from zero
            if key == "position" and isinstance(value, int):
                value += 1
            # Format duration as HH:MM:SS
            if key == "duration" and isinstance(value, int):
                value = format_duration(value)
            # Format seek (milliseconds) as HH:MM:SS.mmm
            if key == "seek" and isinstance(value, int):
                value = format_seek(value)
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
        A list of filtered queue item dictionaries with synthetic "position" field added
    """
    queue = queue_data.get("queue", [])
    filtered_queue = []

    for index, item in enumerate(queue):
        if fields == "all":
            filtered_item = item.copy()
        else:  # short
            filtered_item = {key: item[key] for key in QUEUE_LIST_SHORT_FIELDS if key in item}

        # Add synthetic 1-indexed position
        filtered_item["position"] = index + 1
        filtered_queue.append(filtered_item)

    return filtered_queue


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

    for track in tracks:
        position = track.get("position", "?")
        title = track.get("title", "Unknown")
        artist = track.get("artist", "Unknown")
        album = track.get("album", "")
        duration = track.get("duration")
        service = track.get("service", "")

        lines.append(f"\n{position}. {title}")
        if artist:
            lines.append(f"   Artist : {artist}")
        if album:
            lines.append(f"   Album  : {album}")
        if duration and isinstance(duration, int):
            lines.append(f"   Duration: {format_duration(duration)}")
        if service:
            lines.append(f"   Service: {service}")

        # Add optional audio quality fields if present
        samplerate = track.get("samplerate")
        bitdepth = track.get("bitdepth")
        channels = track.get("channels")

        if samplerate:
            lines.append(f"   Sample Rate: {samplerate}")
        if bitdepth:
            lines.append(f"   Bit Depth: {bitdepth}")
        if channels:
            lines.append(f"   Channels: {channels}")

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
    endpoint: str,
) -> None:
    """Execute a playback control command.

    Args:
        ctx: Click context object containing shared options
        command_name: Name of the command (for messages)
        command_func: Function to call on the VolumioRESTAPIClient
        endpoint: API endpoint being called (for verbose output)
    """
    host_configuration = ctx.obj["host_configuration"]
    rest_api_timeout = ctx.obj["rest_api_timeout"]
    verbose = ctx.obj["verbose"]
    machine_readable = ctx.obj["machine_readable"]

    if verbose and not machine_readable:
        click.echo(f"Connecting to {host_configuration.rest_base_url}{endpoint}...", err=True)

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


def fetch_state_or_exit(ctx: click.Context) -> dict[str, Any]:
    """Fetch the current state, printing errors and exiting (1) on failure.

    Args:
        ctx: Click context object containing shared options

    Returns:
        The state dictionary from the /api/v1/getState endpoint
    """
    host_configuration = ctx.obj["host_configuration"]
    rest_api_timeout = ctx.obj["rest_api_timeout"]
    verbose = ctx.obj["verbose"]
    machine_readable = ctx.obj["machine_readable"]

    if verbose and not machine_readable:
        click.echo(f"Connecting to {host_configuration.rest_base_url}/api/v1/getState...", err=True)

    try:
        client = create_client(host_configuration, rest_api_timeout)
        return client.get_state()
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


def print_resulting_state_option(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``-r``/``--print-resulting-state`` option to a player subcommand."""
    return click.option(
        "--print-resulting-state/--no-print-resulting-state",
        "-r",
        default=True,
        show_default=True,
        help="After the command, wait 1 second and print the resulting player state",
    )(func)


def rest_api_sleep(ctx: click.Context) -> None:
    """Sleep for the configured delay before making the next REST API call.

    Args:
        ctx: Click context object holding the shared options
    """
    time.sleep(ctx.obj["rest_api_sleep_before_next_call"])


def maybe_print_resulting_state(ctx: click.Context, enabled: bool) -> None:
    """When enabled, wait the configured number of seconds and invoke "player state".

    Args:
        ctx: Click context object (its ``obj`` is inherited by the invoked command)
        enabled: Whether to print the resulting state
    """
    if enabled:
        rest_api_sleep(ctx)
        ctx.invoke(player_state)


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


def configuration_file_callback(
    ctx: click.Context, param: click.Parameter, value: str | None
) -> str | None:
    """Load the configuration file (if any) and use its values as option defaults.

    Runs eagerly, before the other options resolve, so the loaded values populate
    ``ctx.default_map`` and are only used where the user did not pass an explicit flag.
    """
    path = resolve_configuration_path(value)
    if path is not None:
        mapping = load_default_map(path)
        ctx.default_map = {**(ctx.default_map or {}), **mapping}
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
        "(explicit options still override them); if omitted, canonical locations in the "
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


def render_state(
    ctx: click.Context,
    fields: str,
    output_format: str,
    raw: bool,
    short_fields: list[str],
    heading: str = "Volumio State",
) -> None:
    """Fetch the current state and print it per the fields/format/raw options.

    Args:
        ctx: Click context object containing shared options
        fields: The fields option ("short" or "all")
        output_format: The output format ("json", "pretty", or "table")
        raw: When True, print the raw unfiltered JSON (ignores fields/format)
        short_fields: The list of keys to keep when ``fields`` is "short"
        heading: The heading line for the table output format
    """
    verbose = ctx.obj["verbose"]
    machine_readable = ctx.obj["machine_readable"]

    state = fetch_state_or_exit(ctx)

    if verbose and not machine_readable:
        click.echo("Successfully retrieved state", err=True)

    # Determine output format
    if raw:
        # Raw JSON without formatting (ignores fields filter)
        output = json.dumps(state)
    else:
        # Apply fields filter for all formatted outputs
        filtered_state = filter_fields(state, fields, short_fields)  # type: ignore[arg-type]

        if output_format == "table":
            # Preserve the short_fields order (and their labels) in the table
            field_order = short_fields if fields == "short" else None
            output = format_as_table(filtered_state, heading=heading, field_order=field_order)
        elif output_format == "json":
            output = format_as_json(filtered_state)
        else:  # pretty
            output = format_as_pretty(filtered_state)

    click.echo(output)


@main.group()
@click.pass_context
def player(ctx: click.Context) -> None:
    """Commands for controlling the playback of the Volumio instance."""
    pass


@player.command("state")
@click.pass_context
@click.option(
    "--fields",
    "-L",
    type=click.Choice(["short", "all"], case_sensitive=False),
    default="short",
    show_default=True,
    help="Fields to display (applies to json and pretty formats)",
)
@click.option(
    "--format",
    "-F",
    "output_format",
    type=click.Choice(["json", "pretty", "table"], case_sensitive=False),
    default="pretty",
    show_default=True,
    help="Output format for the state information",
)
@click.option(
    "--raw",
    "-R",
    is_flag=True,
    default=False,
    help="Output raw JSON without formatting (overrides --format)",
)
def player_state(
    ctx: click.Context,
    fields: str,
    output_format: str,
    raw: bool,
) -> None:
    """Get the current player state from a Volumio instance.

    Retrieves and displays the current state of a Volumio music player instance,
    including playback status, volume, track information, and more. Also available
    as the top-level ``info`` command.
    """
    render_state(ctx, fields, output_format, raw, PLAYER_STATE_SHORT_FIELDS)


# "info" is a top-level synonym for "player state"
main.add_command(player_state, name="info")


@player.command()
@click.pass_context
@print_resulting_state_option
def toggle(ctx: click.Context, print_resulting_state: bool) -> None:
    """Toggle between play and pause states of the Volumio instance."""
    execute_command(
        ctx, "toggle", lambda c: c.toggle(), "/api/v1/commands/?cmd=toggle"
    )
    maybe_print_resulting_state(ctx, print_resulting_state)


@player.command()
@click.pass_context
@click.option(
    "--position",
    "-p",
    type=int,
    default=None,
    help="Position in the queue to play (1-indexed)",
)
@print_resulting_state_option
def play(ctx: click.Context, position: int | None, print_resulting_state: bool) -> None:
    """Start playback of the Volumio instance.

    Optionally specify a position to play a specific track in the queue.
    """
    if position is not None:
        position -= 1
        endpoint = f"/api/v1/commands/?cmd=play&N={position}"
        execute_command(ctx, "play", lambda c: c.play(position), endpoint)
    else:
        execute_command(ctx, "play", lambda c: c.play(), "/api/v1/commands/?cmd=play")
    maybe_print_resulting_state(ctx, print_resulting_state)


@player.command()
@click.pass_context
@print_resulting_state_option
def pause(ctx: click.Context, print_resulting_state: bool) -> None:
    """Pause playback of the Volumio instance."""
    execute_command(ctx, "pause", lambda c: c.pause(), "/api/v1/commands/?cmd=pause")
    maybe_print_resulting_state(ctx, print_resulting_state)


@player.command()
@click.pass_context
@print_resulting_state_option
def stop(ctx: click.Context, print_resulting_state: bool) -> None:
    """Stop playback of the Volumio instance."""
    execute_command(ctx, "stop", lambda c: c.stop(), "/api/v1/commands/?cmd=stop")
    maybe_print_resulting_state(ctx, print_resulting_state)


@player.command()
@click.pass_context
@print_resulting_state_option
def next(ctx: click.Context, print_resulting_state: bool) -> None:
    """Skip to the next track of the Volumio instance."""
    execute_command(ctx, "next", lambda c: c.next(), "/api/v1/commands/?cmd=next")
    maybe_print_resulting_state(ctx, print_resulting_state)


@player.command()
@click.pass_context
@print_resulting_state_option
def previous(ctx: click.Context, print_resulting_state: bool) -> None:
    """Skip to the previous track of the Volumio instance."""
    execute_command(
        ctx, "previous", lambda c: c.previous(), "/api/v1/commands/?cmd=prev"
    )
    maybe_print_resulting_state(ctx, print_resulting_state)


@player.command()
@click.pass_context
@click.argument("value", required=False, default=None, type=VolumeParamType())
@print_resulting_state_option
def volume(ctx: click.Context, value: int | str | None, print_resulting_state: bool) -> None:
    """Set, adjust, or show the volume of the Volumio instance.

    Without VALUE, print the current volume. Otherwise VALUE is an integer
    between 0 and 100 (inclusive) to set an absolute level, or one of "mute",
    "unmute", "plus" (also "increase"/"up"), "minus" (also "decrease"/"down").
    """
    if value is None:
        state = fetch_state_or_exit(ctx)
        click.echo(state.get("volume"))
        return
    endpoint = f"/api/v1/commands/?cmd=volume&volume={value}"
    execute_command(ctx, f"volume {value}", lambda c: c.volume(value), endpoint)
    maybe_print_resulting_state(ctx, print_resulting_state)


@player.command()
@click.pass_context
@print_resulting_state_option
def mute(ctx: click.Context, print_resulting_state: bool) -> None:
    """Mute the volume of the Volumio instance (synonym for `player volume mute`)."""
    execute_command(
        ctx,
        "volume mute",
        lambda c: c.volume("mute"),
        "/api/v1/commands/?cmd=volume&volume=mute",
    )
    maybe_print_resulting_state(ctx, print_resulting_state)


@player.command()
@click.pass_context
@print_resulting_state_option
def unmute(ctx: click.Context, print_resulting_state: bool) -> None:
    """Unmute the volume of the Volumio instance (synonym for `player volume unmute`)."""
    execute_command(
        ctx,
        "volume unmute",
        lambda c: c.volume("unmute"),
        "/api/v1/commands/?cmd=volume&volume=unmute",
    )
    maybe_print_resulting_state(ctx, print_resulting_state)


@main.group()
@click.pass_context
def track(ctx: click.Context) -> None:
    """Retrieve information, audio, and album art of the current track of the Volumio instance."""
    pass


@track.command("info")
@click.pass_context
@click.option(
    "--fields",
    "-L",
    type=click.Choice(["short", "all"], case_sensitive=False),
    default="short",
    show_default=True,
    help="Fields to display (applies to json and pretty formats)",
)
@click.option(
    "--format",
    "-F",
    "output_format",
    type=click.Choice(["json", "pretty", "table"], case_sensitive=False),
    default="pretty",
    show_default=True,
    help="Output format for the track information",
)
@click.option(
    "--raw",
    "-R",
    is_flag=True,
    default=False,
    help="Output raw JSON without formatting (overrides --format)",
)
def track_info(
    ctx: click.Context,
    fields: str,
    output_format: str,
    raw: bool,
) -> None:
    """Print the information of the current track."""
    render_state(ctx, fields, output_format, raw, TRACK_INFO_SHORT_FIELDS, heading="Track Info")


@track.command()
@click.pass_context
@click.option(
    "-f",
    "--file-name-template",
    type=str,
    default="{file_name_from_uri}",
    show_default=True,
    help="Template (Python str.format syntax) for the -d output file name. Keys: "
    "file_name_from_uri, position, title, album, artist, trackType, duration, "
    "bitdepth, samplerate, channels, extension. Spaces become underscores.",
)
@click.option(
    "-d",
    "--output-dir",
    type=str,
    default=None,
    help="Download the track into this directory, using the file name from the template "
    "(mutually exclusive with -o)",
)
@click.option(
    "-o",
    "--output-file",
    type=str,
    default=None,
    help="Download the track to this exact file path (mutually exclusive with -d)",
)
@click.option(
    "--overwrite-existing-files/--no-overwrite-existing-files",
    default=False,
    show_default=True,
    help="Overwrite the destination file if it already exists",
)
def audio(
    ctx: click.Context,
    file_name_template: str,
    output_dir: str | None,
    output_file: str | None,
    overwrite_existing_files: bool,
) -> None:
    """Print the URI of the audio of the current track.

    Optionally download the track to a file with -o/--output-file (an exact file
    path) or into a directory with -d/--output-dir (the file name is rendered from
    -f/--file-name-template); the -o and -d options are mutually exclusive.
    """
    if output_file is not None and output_dir is not None:
        raise click.UsageError(MUTUALLY_EXCLUSIVE_OUTPUT_ERROR)

    host_configuration = ctx.obj["host_configuration"]
    rest_api_timeout = ctx.obj["rest_api_timeout"]
    mpd_timeout = ctx.obj["mpd_timeout"]
    verbose = ctx.obj["verbose"]
    machine_readable = ctx.obj["machine_readable"]

    if verbose and not machine_readable:
        click.echo(f"Connecting to {host_configuration.rest_base_url}/api/v1/getState...", err=True)

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

            # Download the file if -o/--output-file or -d/--output-dir is specified
            if output_file is not None or output_dir is not None:
                download_uri_to(
                    uri,
                    output_file,
                    output_dir,
                    file_name_template,
                    "flac",
                    state,
                    overwrite_existing_files,
                    "track",
                    rest_api_timeout,
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
@click.option(
    "-f",
    "--file-name-template",
    type=str,
    default="{file_name_from_uri}",
    show_default=True,
    help="Template (Python str.format syntax) for the -d output file name. Keys: "
    "file_name_from_uri, position, title, album, artist, trackType, duration, "
    "bitdepth, samplerate, channels, extension. Spaces become underscores.",
)
@click.option(
    "-d",
    "--output-dir",
    type=str,
    default=None,
    help="Download the album art into this directory, using the file name from the template "
    "(mutually exclusive with -o)",
)
@click.option(
    "-o",
    "--output-file",
    type=str,
    default=None,
    help="Download the album art to this exact file path (mutually exclusive with -d)",
)
@click.option(
    "--overwrite-existing-files/--no-overwrite-existing-files",
    default=False,
    show_default=True,
    help="Overwrite the destination file if it already exists",
)
def albumart(
    ctx: click.Context,
    file_name_template: str,
    output_dir: str | None,
    output_file: str | None,
    overwrite_existing_files: bool,
) -> None:
    """Print the URI of the album art of the current track.

    Optionally download the image to a file with -o/--output-file (an exact file
    path) or into a directory with -d/--output-dir (the file name is rendered from
    -f/--file-name-template); the -o and -d options are mutually exclusive.
    """
    if output_file is not None and output_dir is not None:
        raise click.UsageError(MUTUALLY_EXCLUSIVE_OUTPUT_ERROR)

    host_configuration = ctx.obj["host_configuration"]
    rest_api_timeout = ctx.obj["rest_api_timeout"]
    verbose = ctx.obj["verbose"]
    machine_readable = ctx.obj["machine_readable"]

    if verbose and not machine_readable:
        click.echo(f"Connecting to {host_configuration.rest_base_url}/api/v1/getState...", err=True)

    try:
        # Get current state metadata
        client = create_client(host_configuration, rest_api_timeout)
        state = client.get_state()

        if verbose and not machine_readable:
            click.echo("Successfully retrieved state", err=True)

        # Extract albumart URI
        albumart = state.get("albumart")
        if not albumart:
            if not machine_readable:
                click.echo("Error: No album art URI found in current state", err=True)
            sys.exit(1)

        # Handle relative URIs by prepending the base URL
        if albumart.startswith("/"):
            albumart_uri = f"{host_configuration.rest_base_url}{albumart}"
        else:
            albumart_uri = albumart

        if verbose and not machine_readable:
            click.echo(f"Album art URI: {albumart_uri}", err=True)

        # Always print the URI (even in machine-readable mode);
        # in machine-readable mode print it quoted so it can be consumed by jq/yq
        click.echo(json.dumps(albumart_uri) if machine_readable else albumart_uri)

        # Download the file if -o/--output-file or -d/--output-dir is specified
        if output_file is not None or output_dir is not None:
            download_uri_to(
                albumart_uri,
                output_file,
                output_dir,
                file_name_template,
                "jpg",
                state,
                overwrite_existing_files,
                "album art",
                rest_api_timeout,
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


@main.group()
@click.pass_context
def queue(ctx: click.Context) -> None:
    """Commands for managing the playback queue of the Volumio instance."""
    pass


@queue.command("list")
@click.pass_context
@click.option(
    "--fields",
    "-L",
    type=click.Choice(["short", "all"], case_sensitive=False),
    default="short",
    show_default=True,
    help="Fields to display (applies to json and pretty formats)",
)
@click.option(
    "--format",
    "-F",
    "output_format",
    type=click.Choice(["json", "pretty", "table"], case_sensitive=False),
    default="pretty",
    show_default=True,
    help="Output format for the queue information",
)
@click.option(
    "--raw",
    "-R",
    is_flag=True,
    default=False,
    help="Output raw JSON without formatting (overrides --format)",
)
def queue_list(
    ctx: click.Context,
    fields: str,
    output_format: str,
    raw: bool,
) -> None:
    """List the playback queue.

    This command retrieves and prints the current playback queue,
    showing all queued tracks with their metadata.
    """
    host_configuration = ctx.obj["host_configuration"]
    rest_api_timeout = ctx.obj["rest_api_timeout"]
    verbose = ctx.obj["verbose"]
    machine_readable = ctx.obj["machine_readable"]

    if verbose and not machine_readable:
        click.echo(f"Connecting to {host_configuration.rest_base_url}/api/v1/getQueue...", err=True)

    try:
        client = create_client(host_configuration, rest_api_timeout)
        queue_data = client.get_queue()

        if verbose and not machine_readable:
            click.echo("Successfully retrieved queue", err=True)

        # Determine output format
        if raw:
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
                for track in tracks:
                    pretty_track = track.copy()
                    if "duration" in pretty_track and isinstance(pretty_track["duration"], int):
                        pretty_track["duration"] = format_duration(pretty_track["duration"])
                    pretty_tracks.append(pretty_track)
                output = json.dumps(pretty_tracks, indent=4, sort_keys=True, ensure_ascii=False)
            elif output_format == "table":
                output = format_queue_as_table(tracks)
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


if __name__ == "__main__":  # pragma: no cover
    main()
