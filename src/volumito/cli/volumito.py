"""Command-line interface for volumito.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

import json
import os
import sys
from datetime import UTC, datetime
from typing import Any

import click

from volumito import __version__
from volumito.cli.click_helpers import (
    OnOffParamType,
    SchemeParamType,
    SeekParamType,
    VolumeParamType,
    VolumioVersionParamType,
    configuration_file_callback,
    create_client,
    download_queue_albumart,
    download_queue_track,
    download_uri_to,
    embed_track_tags,
    execute_command,
    execute_conditionally,
    fetch_or_exit,
    fetch_state_or_exit,
    ignore_configuration_file_callback,
    option_add_cover_and_metadata,
    option_albumart_file_name_template,
    option_audio_file_name_template,
    option_create_download_manifest,
    option_fields,
    option_file_name_template,
    option_format,
    option_output_directory,
    option_output_file,
    option_overwrite_existing_files,
    option_print_resulting_status,
    option_replace_characters_in_file_names,
    option_replace_characters_in_file_names_with,
    render_output_filename,
    render_payload,
    render_state,
    rest_api_sleep,
    write_queue_log,
)
from volumito.cli.configuration import (
    CONFIGURATION_FILENAMES,
    default_configuration_template,
    flatten_configuration,
    load_configuration,
    probe_configuration_paths,
    resolve_configuration_path,
)
from volumito.cli.constants import (
    DEFAULT_NUMBER_RETRIES_NEXT_TRACK,
    DEFAULT_VOLUMIO_VERSION,
    MPD_PORT_VOLUMIO_3,
    MPD_PORT_VOLUMIO_4,
    MUTUALLY_EXCLUSIVE_CREATE_ERROR,
    MUTUALLY_EXCLUSIVE_OUTPUT_ERROR,
    OUTPUT_DIRECTORY_REQUIRED_ERROR,
    QUEUE_LOG_FILENAME,
    QUEUE_LOG_TIMESTAMP_FORMAT,
    SHORT_FORMAT_FIELDS_PLAYER_STATE,
    SHORT_FORMAT_FIELDS_TRACK_INFO,
)
from volumito.cli.pure_helpers import (
    display_position,
    filter_queue_fields,
    filter_zones_fields,
    format_duration,
    format_playlists_as_table,
    format_queue_as_table,
    format_seek,
    format_zones_as_table,
    queue_track_metadata_current,
    rebase_queue_positions,
    resolve_albumart_uri,
)
from volumito.clients import (
    Scheme,
    VolumioAPIError,
    VolumioConnectionError,
    VolumioHostConfiguration,
    VolumioMPDClient,
)


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
    "--ignore-configuration-file",
    is_flag=True,
    default=False,
    is_eager=True,
    expose_value=False,
    callback=ignore_configuration_file_callback,
    help="Ignore any configuration file (skip the lookup and apply the built-in defaults)",
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
    help="Index queue positions starting at one (or at zero)",
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
    type=SchemeParamType(),
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
    scheme: Scheme,
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
    elif verbose and not machine_readable and ctx.obj.get("ignore_configuration_file"):
        click.echo("Ignoring configuration files", err=True)


@main.command()
@click.pass_context
def version(ctx: click.Context) -> None:
    """Show the volumito version.

    In machine-readable mode the version string is printed quoted (e.g. ``"0.0.10"``)
    so it can be consumed by jq/yq; otherwise the program name is included.
    """
    if ctx.obj["machine_readable"]:
        msg = f'"{__version__}"'
    else:
        msg = f"volumito, version {__version__}"
    click.echo(msg)


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
@click.option(
    "--volumio-version",
    "-V",
    type=VolumioVersionParamType(),
    default=DEFAULT_VOLUMIO_VERSION,
    show_default=True,
    help=(
        "Target Volumio version (e.g. 4, 4.119, 3, 3.123); selects the MPD port "
        "(6599 for versions below 4, otherwise 6600)"
    ),
)
@option_overwrite_existing_files
def configuration_create(
    ctx: click.Context,
    output_directory: str | None,
    output_file: str | None,
    volumio_version: int,
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

    mpd_port = MPD_PORT_VOLUMIO_3 if volumio_version < 4 else MPD_PORT_VOLUMIO_4
    content = default_configuration_template(__version__, mpd_port)
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


@main.group()
@click.pass_context
def playback(ctx: click.Context) -> None:
    """Commands for controlling the playback of the Volumio instance."""
    pass


@playback.command("status")
@click.pass_context
@option_fields
@option_format
def playback_status(
    ctx: click.Context,
    fields: str,
    output_format: str,
) -> None:
    """Get the current playback status from a Volumio instance.

    Retrieves and displays the current state of a Volumio music player instance,
    including playback status, volume, track information, and more.
    """
    render_state(ctx, fields, output_format, SHORT_FORMAT_FIELDS_PLAYER_STATE)


@playback.command()
@click.pass_context
@option_print_resulting_status
def toggle(ctx: click.Context, print_resulting_status: bool) -> None:
    """Toggle between play and pause states of the Volumio instance."""
    execute_command(ctx, "toggle", lambda c: c.toggle())
    execute_conditionally(ctx, print_resulting_status, playback_status)


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
@option_print_resulting_status
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
    execute_conditionally(ctx, print_resulting_status, playback_status)


@playback.command()
@click.pass_context
@option_print_resulting_status
def pause(ctx: click.Context, print_resulting_status: bool) -> None:
    """Pause playback of the Volumio instance."""
    execute_command(ctx, "pause", lambda c: c.pause())
    execute_conditionally(ctx, print_resulting_status, playback_status)


@playback.command()
@click.pass_context
@option_print_resulting_status
def stop(ctx: click.Context, print_resulting_status: bool) -> None:
    """Stop playback of the Volumio instance."""
    execute_command(ctx, "stop", lambda c: c.stop())
    execute_conditionally(ctx, print_resulting_status, playback_status)


@playback.command()
@click.pass_context
@option_print_resulting_status
def next(ctx: click.Context, print_resulting_status: bool) -> None:
    """Skip to the next track of the Volumio instance."""
    execute_command(ctx, "next", lambda c: c.next())
    execute_conditionally(ctx, print_resulting_status, playback_status)


@playback.command()
@click.pass_context
@option_print_resulting_status
def previous(ctx: click.Context, print_resulting_status: bool) -> None:
    """Skip to the previous track of the Volumio instance."""
    execute_command(ctx, "previous", lambda c: c.previous())
    execute_conditionally(ctx, print_resulting_status, playback_status)


@playback.command()
@click.pass_context
@click.argument("value", required=False, default=None, type=SeekParamType())
@click.option(
    "--check-seek-position/--no-check-seek-position",
    default=True,
    show_default=True,
    help="Check that the seek position is within the duration of the current track",
)
@option_print_resulting_status
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
    execute_conditionally(ctx, print_resulting_status, playback_status)


@playback.command()
@click.pass_context
@click.argument("value", required=False, default=None, type=VolumeParamType())
@option_print_resulting_status
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
    execute_conditionally(ctx, print_resulting_status, playback_status)


@playback.command()
@click.pass_context
@option_print_resulting_status
def mute(ctx: click.Context, print_resulting_status: bool) -> None:
    """Mute the volume of the Volumio instance (synonym for `playback volume mute`)."""
    execute_command(ctx, "volume mute", lambda c: c.volume("mute"))
    execute_conditionally(ctx, print_resulting_status, playback_status)


@playback.command()
@click.pass_context
@option_print_resulting_status
def unmute(ctx: click.Context, print_resulting_status: bool) -> None:
    """Unmute the volume of the Volumio instance (synonym for `playback volume unmute`)."""
    execute_command(ctx, "volume unmute", lambda c: c.volume("unmute"))
    execute_conditionally(ctx, print_resulting_status, playback_status)


@main.group()
@click.pass_context
def track(ctx: click.Context) -> None:
    """Retrieve information, audio, and album art of the current track of the Volumio instance."""
    pass


@track.command("info")
@click.pass_context
@option_fields
@option_format
def track_info(
    ctx: click.Context,
    fields: str,
    output_format: str,
) -> None:
    """Print the information of the current track."""
    render_state(ctx, fields, output_format, SHORT_FORMAT_FIELDS_TRACK_INFO, heading="Track Info")


@track.command()
@click.pass_context
@option_add_cover_and_metadata
@option_create_download_manifest
@option_file_name_template
@option_output_directory
@option_output_file
@option_overwrite_existing_files
@option_replace_characters_in_file_names
@option_replace_characters_in_file_names_with
def audio(
    ctx: click.Context,
    add_cover_and_metadata: bool,
    create_download_manifest: bool,
    file_name_template: str,
    output_directory: str | None,
    output_file: str | None,
    overwrite_existing_files: bool,
    replace_characters_in_file_names: str,
    replace_characters_in_file_names_with: str,
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
                    replace_characters_in_file_names=replace_characters_in_file_names,
                    replace_characters_in_file_names_with=(
                        replace_characters_in_file_names_with
                    ),
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
@option_create_download_manifest
@option_file_name_template
@option_output_directory
@option_output_file
@option_overwrite_existing_files
@option_replace_characters_in_file_names
@option_replace_characters_in_file_names_with
def albumart(
    ctx: click.Context,
    create_download_manifest: bool,
    file_name_template: str,
    output_directory: str | None,
    output_file: str | None,
    overwrite_existing_files: bool,
    replace_characters_in_file_names: str,
    replace_characters_in_file_names_with: str,
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
                replace_characters_in_file_names=replace_characters_in_file_names,
                replace_characters_in_file_names_with=(
                    replace_characters_in_file_names_with
                ),
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
@option_fields
@option_format
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
            tracks = filter_queue_fields(queue_data, fields)

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


@queue.command("download")
@click.pass_context
@option_add_cover_and_metadata
@option_albumart_file_name_template
@option_audio_file_name_template
@click.option(
    "--check-next-track/--no-check-next-track",
    default=True,
    show_default=True,
    help="Check that each track's metadata are current before downloading it",
)
@option_create_download_manifest
@click.option(
    "--number-retries-next-track",
    type=int,
    default=DEFAULT_NUMBER_RETRIES_NEXT_TRACK,
    show_default=True,
    help="Number of retries waiting for a track's metadata to become current",
)
@option_output_directory
@option_overwrite_existing_files
@option_replace_characters_in_file_names
@option_replace_characters_in_file_names_with
@click.option(
    "--with-albumart/--no-with-albumart",
    default=True,
    show_default=True,
    help="Download each album's cover, named from --albumart-file-name-template "
    "(once per cover)",
)
def queue_download(
    ctx: click.Context,
    add_cover_and_metadata: bool,
    albumart_file_name_template: str,
    audio_file_name_template: str,
    check_next_track: bool,
    create_download_manifest: bool,
    number_retries_next_track: int,
    output_directory: str | None,
    overwrite_existing_files: bool,
    replace_characters_in_file_names: str,
    replace_characters_in_file_names_with: str,
    with_albumart: bool,
) -> None:
    """Download every track of the current queue into a directory.

    Each run creates a timestamped directory (e.g. 20260726121314) inside
    -d/--output-directory (required) and downloads into it. Playback is stopped,
    then each queue position is played, paused after the configured sleep
    (--rest-api-sleep-before-next-call), and downloaded under the name rendered
    from -f/--audio-file-name-template. The {tracknumber} template key renders the
    track's number within its album (taken from the queue metadata), so with
    several albums queued every album keeps its own numbering, unlike
    {position} (the queue position). Unlike the track downloads, the template may
    contain path separators to lay the files out in subdirectories (e.g.
    "{artist}/{album}/{tracknumber:03d}_{title}.{extension}"); the resulting path
    must stay inside the run directory. Before each download, the fetched metadata
    are checked against the queue listing (title, artist, album, and position must
    match the entry just played, retrying up to --number-retries-next-track times;
    disable with --no-check-next-track). With --with-albumart (the default), each
    album's cover is saved under the name rendered from
    --albumart-file-name-template (relative to the run directory), downloading
    every distinct cover only once.
    A queue.json log listing every track and
    its download status (pending, downloaded, skipped, or error) is written to
    the run directory and updated after each track. At the end, playback is left
    stopped at the first track; the exit code is 1 if any track failed.
    """
    host_configuration = ctx.obj["host_configuration"]
    rest_api_timeout = ctx.obj["rest_api_timeout"]
    mpd_timeout = ctx.obj["mpd_timeout"]
    verbose = ctx.obj["verbose"]
    machine_readable = ctx.obj["machine_readable"]
    position_starting_at_one = ctx.obj["position_starting_at_one"]

    if output_directory is None:
        raise click.UsageError(OUTPUT_DIRECTORY_REQUIRED_ERROR)

    if verbose and not machine_readable:
        click.echo(f"Connecting to {host_configuration.rest_base_url}...", err=True)

    try:
        client = create_client(host_configuration, rest_api_timeout)
        tracks = client.get_queue().get("queue", [])

        if verbose and not machine_readable:
            click.echo("Successfully retrieved queue", err=True)

        if not tracks:
            if not machine_readable:
                click.echo("The queue is empty, nothing to download")
            return

        timestamp = datetime.now(UTC).strftime(QUEUE_LOG_TIMESTAMP_FORMAT)
        run_directory = os.path.join(output_directory, timestamp)
        log_path = os.path.join(run_directory, QUEUE_LOG_FILENAME)
        if not overwrite_existing_files and os.path.exists(run_directory):
            if not machine_readable:
                click.echo(
                    f"Error: directory already exists: {run_directory} "
                    "(use --overwrite-existing-files to overwrite)",
                    err=True,
                )
            sys.exit(1)

        entries: list[dict[str, Any]] = [
            {
                "album": track.get("album"),
                "artist": track.get("artist"),
                "position": display_position(index, position_starting_at_one),
                "status": "pending",
                "title": track.get("title"),
                "track-number": track.get("tracknumber"),
            }
            for index, track in enumerate(tracks)
        ]
        log: dict[str, Any] = {
            "download_date": datetime.now(UTC).isoformat(),
            "entity": "queue",
            "kind": "download",
            "output_directory": run_directory,
            "tracks": entries,
            "volumio_host": host_configuration.rest_base_url,
            "volumito_version": __version__,
        }
        os.makedirs(run_directory, exist_ok=True)
        write_queue_log(log_path, log)

        errors = 0
        previous_uri: str | None = None
        downloaded_covers: dict[str, str] = {}
        client.stop()
        with VolumioMPDClient(host_configuration, mpd_timeout) as mpd_client:
            for index, entry in enumerate(entries):
                destination: str | None = None
                try:
                    expect_same_uri = (
                        index > 0 and tracks[index].get("uri") == tracks[index - 1].get("uri")
                    )
                    attempt = 0
                    while True:
                        client.play(index)
                        rest_api_sleep(ctx)
                        client.pause()
                        rest_api_sleep(ctx)
                        state = client.get_state()
                        uri = mpd_client.get_track_uri()
                        if not check_next_track or queue_track_metadata_current(
                            state, uri, tracks[index], index, previous_uri, expect_same_uri
                        ):
                            fresh = True
                            break
                        if attempt >= number_retries_next_track:
                            fresh = False
                            break
                        attempt += 1
                        if verbose and not machine_readable:
                            click.echo(
                                "Track metadata not yet updated, retrying "
                                f"({attempt}/{number_retries_next_track})...",
                                err=True,
                            )
                    entry["source_uri"] = uri
                    if not fresh:
                        status: str = "error"
                        detail: str | None = (
                            "track metadata still refer to another track after "
                            f"{number_retries_next_track} retries"
                        )
                    else:
                        previous_uri = uri
                        state = {**state, "tracknumber": tracks[index].get("tracknumber")}
                        filename = render_output_filename(
                            audio_file_name_template,
                            uri,
                            state,
                            "flac",
                            position_starting_at_one,
                            replace_characters_in_file_names,
                            replace_characters_in_file_names_with,
                            allow_subdirectories=True,
                            option_label="--audio-file-name-template",
                        )
                        if not filename:
                            status = "error"
                            detail = "cannot determine a file name for the download"
                        else:
                            destination = os.path.join(run_directory, filename)
                            base = os.path.realpath(run_directory)
                            if os.path.commonpath([base, os.path.realpath(destination)]) != base:
                                raise click.UsageError(
                                    "Invalid --audio-file-name-template "
                                    f"{audio_file_name_template!r}: "
                                    f"the file name {filename!r} escapes the output directory"
                                )
                            status, detail = download_queue_track(
                                uri,
                                destination,
                                overwrite_existing_files,
                                rest_api_timeout,
                                create_download_manifest,
                                state,
                                host_configuration,
                                add_cover_and_metadata,
                            )
                            if status == "downloaded" and add_cover_and_metadata:
                                embed_track_tags(
                                    destination,
                                    state,
                                    host_configuration,
                                    rest_api_timeout,
                                    position_starting_at_one,
                                    verbose,
                                    machine_readable,
                                )
                            if with_albumart and status != "error":
                                cover_path = download_queue_albumart(
                                    state,
                                    run_directory,
                                    albumart_file_name_template,
                                    host_configuration,
                                    rest_api_timeout,
                                    overwrite_existing_files,
                                    machine_readable,
                                    downloaded_covers,
                                    position_starting_at_one,
                                    replace_characters_in_file_names,
                                    replace_characters_in_file_names_with,
                                )
                                if cover_path is not None:
                                    entry["albumart_file_path"] = cover_path
                except (VolumioConnectionError, VolumioAPIError) as e:
                    status, detail = "error", str(e)

                entry["status"] = status
                if destination is not None and status != "error":
                    entry["output_file_path"] = destination
                if status == "error":
                    errors += 1
                    entry["error"] = detail
                write_queue_log(log_path, log)
                if not machine_readable:
                    outcome = detail if status == "error" else destination
                    click.echo(f"[{index + 1}/{len(entries)}] {status}: {outcome}")

        # Leave the player stopped at the first track
        client.play(0)
        rest_api_sleep(ctx)
        client.stop()

        if machine_readable:
            click.echo(json.dumps(log_path))
        else:
            downloaded = sum(1 for e in entries if e["status"] == "downloaded")
            skipped = sum(1 for e in entries if e["status"] == "skipped")
            click.echo(
                f"\nDownloaded {downloaded}, skipped {skipped}, errors {errors}; "
                f"log written to {log_path}"
            )
        if errors:
            sys.exit(1)

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


@queue.command()
@click.pass_context
@option_print_resulting_status
def clear(ctx: click.Context, print_resulting_status: bool) -> None:
    """Clear the playback queue of the Volumio instance."""
    execute_command(ctx, "clear", lambda c: c.clear())
    execute_conditionally(ctx, print_resulting_status, playback_status)


@queue.command()
@click.pass_context
@click.argument("value", required=False, default=None, type=OnOffParamType())
@option_print_resulting_status
def repeat(ctx: click.Context, value: bool | None, print_resulting_status: bool) -> None:
    """Set or toggle the repeat mode of the Volumio instance.

    Without VALUE, toggle the current mode. Otherwise VALUE is "on"/"true"/"yes"/"1"
    or "off"/"false"/"no"/"0".
    """
    label = "repeat" if value is None else f"repeat {'on' if value else 'off'}"
    execute_command(ctx, label, lambda c: c.repeat(value))
    execute_conditionally(ctx, print_resulting_status, playback_status)


@queue.command()
@click.pass_context
@click.argument("value", required=False, default=None, type=OnOffParamType())
@option_print_resulting_status
def randomize(ctx: click.Context, value: bool | None, print_resulting_status: bool) -> None:
    """Set or toggle the random (shuffle) mode of the Volumio instance.

    Without VALUE, toggle the current mode. Otherwise VALUE is "on"/"true"/"yes"/"1"
    or "off"/"false"/"no"/"0".
    """
    label = "randomize" if value is None else f"randomize {'on' if value else 'off'}"
    execute_command(ctx, label, lambda c: c.randomize(value))
    execute_conditionally(ctx, print_resulting_status, playback_status)


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
@option_format
def system_version(ctx: click.Context, output_format: str) -> None:
    """Get the system version of the Volumio instance."""
    data = fetch_or_exit(ctx, lambda c: c.get_system_version())
    render_payload(ctx, data, output_format, heading="Volumio System Version")


@system.command("info")
@click.pass_context
@option_format
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
@option_format
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
@option_fields
@option_format
def zones_get(ctx: click.Context, fields: str, output_format: str) -> None:
    """Get the multiroom zones seen by the Volumio instance."""
    data = fetch_or_exit(ctx, lambda c: c.get_zones())

    if output_format == "raw":
        # Raw JSON without formatting (ignores fields filter)
        output = json.dumps(data)
    else:
        filtered_zones = filter_zones_fields(data, fields)
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
@option_format
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
@option_print_resulting_status
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
    execute_conditionally(ctx, print_resulting_status, playback_status)


# "info" is a top-level synonym for "system info"
main.add_command(system_info, name="info")


if __name__ == "__main__":  # pragma: no cover
    main()
