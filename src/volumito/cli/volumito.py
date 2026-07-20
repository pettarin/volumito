"""Command-line interface for volumito.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

import json
import sys
import time
from collections.abc import Callable
from typing import Any, Literal

import click
import requests

from volumito.clients import (
    VolumioAPIError,
    VolumioConnectionError,
    VolumioHostConfiguration,
    VolumioMPDClient,
    VolumioRESTAPIClient,
)

# Default chunk size when writing files
FILE_WRITE_CHUNK_SIZE = 8192

# Short fields list (same as table format)
SHORT_FIELDS = [
    "status",
    "position",
    "title",
    "artist",
    "album",
    "duration",
    "seek",
    "volume",
    "mute",
]

# Short fields list for queue items
QUEUE_SHORT_FIELDS = [
    "title",
    "artist",
    "album",
    "duration",
]

# Version of the CLI (and of the underlying library)
VERSION = "0.0.9"


def filter_fields(state: dict[str, Any], fields: Literal["short", "all"]) -> dict[str, Any]:
    """Filter the state dictionary based on the fields option.

    Args:
        state: The state dictionary from the Volumio API
        fields: The fields option ("short" or "all")

    Returns:
        A filtered dictionary containing only the requested fields
    """
    if fields == "all":
        return state
    else:  # short
        return {key: state[key] for key in SHORT_FIELDS if key in state}


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


def sanitize_filename(text: str) -> str:
    """Sanitize a string to be used as a filename.

    Replaces spaces and punctuation with underscores.

    Args:
        text: The text to sanitize

    Returns:
        A sanitized string suitable for use in filenames
    """
    import re
    # Replace any character that is not alphanumeric or underscore with underscore
    sanitized = re.sub(r"[^\w]", "_", text)
    # Collapse multiple underscores into one
    sanitized = re.sub(r"_+", "_", sanitized)
    # Remove leading/trailing underscores
    return sanitized.strip("_")


def extract_extension_from_url(url: str) -> str:
    """Extract file extension from a URL (without leading dot).

    Handles URLs with query parameters (e.g., /albumart?path=image.jpg).
    Defaults to 'jpg' if no extension found.

    Args:
        url: The URL to extract extension from

    Returns:
        File extension without the dot (e.g., 'jpg', 'png')
    """
    import os
    from urllib.parse import parse_qs, urlparse

    parsed = urlparse(url)

    # Try to get extension from query parameter 'path' first
    if parsed.query:
        qs = parse_qs(parsed.query)
        if "path" in qs:
            path = qs["path"][0]
            _, ext = os.path.splitext(path)
            if ext:
                return ext.lstrip(".")  # Remove leading dot

    # If no extension from query, try from the URL path
    _, ext = os.path.splitext(parsed.path)

    # Return extension without dot, default to 'jpg' if none found
    return ext.lstrip(".") if ext else "jpg"


def format_as_table(state: dict[str, Any]) -> str:
    """Format the state dictionary as a readable table.

    Args:
        state: The (potentially filtered) state dictionary from the Volumio API

    Returns:
        A formatted string representation of the state
    """
    lines = []
    lines.append("Volumio State")
    lines.append("=" * 50)

    # Check if this is the short field set
    state_keys = set(state.keys())
    short_keys = set(SHORT_FIELDS)

    if state_keys.issubset(short_keys):
        # Use predefined labels for short fields
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
            filtered_item = {key: item[key] for key in QUEUE_SHORT_FIELDS if key in item}

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


@click.group()
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


@main.command()
@click.pass_context
def version(ctx: click.Context) -> None:
    """Show the volumito version.

    In machine-readable mode the version string is printed quoted (e.g. ``"0.0.9"``)
    so it can be consumed by jq/yq; otherwise the program name is included.
    """
    if ctx.obj["machine_readable"]:
        msg = f'"{VERSION}"'
    else:
        msg = f"volumito, version {VERSION}"
    click.echo(msg)


@main.group()
@click.pass_context
def player(ctx: click.Context) -> None:
    """Commands for controlling playback on a Volumio instance."""
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
        filtered_state = filter_fields(state, fields)  # type: ignore[arg-type]

        # Map output format to formatting function
        format_functions = {
            "json": format_as_json,
            "pretty": format_as_pretty,
            "table": format_as_table,
        }

        formatter = format_functions[output_format]
        output = formatter(filtered_state)

    click.echo(output)


# "info" is a top-level synonym for "player state"
main.add_command(player_state, name="info")


@player.command()
@click.pass_context
@print_resulting_state_option
def toggle(ctx: click.Context, print_resulting_state: bool) -> None:
    """Toggle between play and pause states on a Volumio instance."""
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
    """Start playback on a Volumio instance.

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
    """Pause playback on a Volumio instance."""
    execute_command(ctx, "pause", lambda c: c.pause(), "/api/v1/commands/?cmd=pause")
    maybe_print_resulting_state(ctx, print_resulting_state)


@player.command()
@click.pass_context
@print_resulting_state_option
def stop(ctx: click.Context, print_resulting_state: bool) -> None:
    """Stop playback on a Volumio instance."""
    execute_command(ctx, "stop", lambda c: c.stop(), "/api/v1/commands/?cmd=stop")
    maybe_print_resulting_state(ctx, print_resulting_state)


@player.command()
@click.pass_context
@print_resulting_state_option
def next(ctx: click.Context, print_resulting_state: bool) -> None:
    """Skip to the next track on a Volumio instance."""
    execute_command(ctx, "next", lambda c: c.next(), "/api/v1/commands/?cmd=next")
    maybe_print_resulting_state(ctx, print_resulting_state)


@player.command()
@click.pass_context
@print_resulting_state_option
def previous(ctx: click.Context, print_resulting_state: bool) -> None:
    """Skip to the previous track on a Volumio instance."""
    execute_command(
        ctx, "previous", lambda c: c.previous(), "/api/v1/commands/?cmd=prev"
    )
    maybe_print_resulting_state(ctx, print_resulting_state)


@player.command()
@click.pass_context
@click.argument("value", required=False, default=None, type=VolumeParamType())
@print_resulting_state_option
def volume(ctx: click.Context, value: int | str | None, print_resulting_state: bool) -> None:
    """Set, adjust, or show the volume on a Volumio instance.

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
    """Mute the volume on a Volumio instance (synonym for `player volume mute`)."""
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
    """Unmute the volume on a Volumio instance (synonym for `player volume unmute`)."""
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
    """Commands for retrieving track audio and album art information."""
    pass


@track.command()
@click.pass_context
@click.option(
    "-o",
    "--output-file",
    type=str,
    default=None,
    help=(
        "Download the track to a file. "
        "Optionally specify a path, "
        "or let it auto-generate from metadata."
    ),
)
def audio(ctx: click.Context, output_file: str | None) -> None:
    """Get the current track audio URI from a Volumio instance.

    This command uses MPD to get the track URI, replacing localhost/127.0.0.1
    with the actual host. The URI is printed to stdout. Optionally download the
    track to a file (auto-generates filename if path not provided).
    """
    host_configuration = ctx.obj["host_configuration"]
    rest_api_timeout = ctx.obj["rest_api_timeout"]
    mpd_timeout = ctx.obj["mpd_timeout"]
    verbose = ctx.obj["verbose"]
    machine_readable = ctx.obj["machine_readable"]

    if verbose and not machine_readable:
        click.echo(f"Connecting to {host_configuration.rest_base_url}/api/v1/getState...", err=True)

    try:
        # Get current track metadata
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

            # Always print the URI (even in machine-readable mode)
            click.echo(uri)

            # Download the file if -o/--output-file is specified
            if output_file is not None:
                # Generate filename if not provided by user or empty string
                if not output_file or output_file == "":
                    # Auto-generate filename from metadata
                    position = int(state.get("position", 0)) + 1
                    title = state.get("title", "unknown")

                    # Format position with leading zero if needed
                    position_str = f"{position:03d}"

                    # Sanitize title
                    sanitized_title = sanitize_filename(title)

                    # Create filename
                    output_file = f"{position_str}_{sanitized_title}.flac"

                if verbose and not machine_readable:
                    click.echo(f"\nDownloading track to {output_file}...", err=True)

                try:
                    response = requests.get(uri, timeout=rest_api_timeout, stream=True)
                    response.raise_for_status()

                    with open(output_file, "wb") as f:
                        for chunk in response.iter_content(chunk_size=FILE_WRITE_CHUNK_SIZE):
                            f.write(chunk)

                    if not machine_readable:
                        click.echo(f"\nTrack successfully downloaded to {output_file}")

                except requests.exceptions.RequestException as e:
                    if not machine_readable:
                        click.echo(f"\nDownload error: {e}", err=True)
                    sys.exit(1)
                except OSError as e:
                    if not machine_readable:
                        click.echo(f"\nFile write error: {e}", err=True)
                    sys.exit(1)

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
    "-o",
    "--output-file",
    type=str,
    default=None,
    help=(
        "Download the album art to a file. "
        "Optionally specify a path, "
        "or let it auto-generate from metadata."
    ),
)
def albumart(ctx: click.Context, output_file: str | None) -> None:
    """Get the album art URL from a Volumio instance.

    This command retrieves the current album art URL from the Volumio API.
    The URL is always printed to stdout. Optionally download the image to a
    file using the -o/--output-file option (auto-generates filename if path not provided).
    """
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

        # Extract albumart URL
        albumart = state.get("albumart")
        if not albumart:
            if not machine_readable:
                click.echo("Error: No album art URL found in current state", err=True)
            sys.exit(1)

        # Handle relative URLs by prepending the base URL
        if albumart.startswith("/"):
            albumart_url = f"{host_configuration.rest_base_url}{albumart}"
        else:
            albumart_url = albumart

        if verbose and not machine_readable:
            click.echo(f"Album art URL: {albumart_url}", err=True)

        # Always print the URL (even in machine-readable mode)
        click.echo(albumart_url)

        # Download the file if -o/--output-file is specified
        if output_file is not None:
            # Generate filename if not provided by user or empty string
            if not output_file or output_file == "":
                # Auto-generate filename from metadata
                album = state.get("album", "unknown")

                # Sanitize album name
                sanitized_album = sanitize_filename(album)

                # Extract extension from album art URL (without leading dot)
                extension = extract_extension_from_url(albumart_url)

                # Create filename with "000" prefix
                output_file = f"000_{sanitized_album}.{extension}"

            if verbose and not machine_readable:
                click.echo(f"\nDownloading album art to {output_file}...", err=True)

            try:
                response = requests.get(albumart_url, timeout=rest_api_timeout, stream=True)
                response.raise_for_status()

                with open(output_file, "wb") as f:
                    for chunk in response.iter_content(chunk_size=FILE_WRITE_CHUNK_SIZE):
                        f.write(chunk)

                if not machine_readable:
                    click.echo(f"\nAlbum art successfully downloaded to {output_file}")

            except requests.exceptions.RequestException as e:
                if not machine_readable:
                    click.echo(f"\nDownload error: {e}", err=True)
                sys.exit(1)
            except OSError as e:
                if not machine_readable:
                    click.echo(f"\nFile write error: {e}", err=True)
                sys.exit(1)

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
    """Commands for managing the playback queue on a Volumio instance."""
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
    """Get the playback queue from a Volumio instance.

    This command retrieves and displays the current playback queue,
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
