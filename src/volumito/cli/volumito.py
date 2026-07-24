"""Command-line interface for volumito.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

import json
import os
import sys
from typing import Any, Literal

import click

from volumito import __version__
from volumito.cli.click_helpers import (
    OnOffParamType,
    SeekParamType,
    VolumeParamType,
    configuration_file_callback,
    create_client,
    download_uri_to,
    embed_track_tags,
    execute_command,
    execute_conditionally,
    fetch_or_exit,
    fetch_state_or_exit,
    option_add_cover_and_metadata,
    option_create_download_manifest,
    option_fields,
    option_file_name_template,
    option_format,
    option_output_directory,
    option_output_file,
    option_overwrite_existing_files,
    option_print_resulting_status,
    render_payload,
    render_state,
    root_option_defaults,
)
from volumito.cli.configuration import (
    CONFIGURATION_FILENAMES,
    flatten_configuration,
    load_configuration,
    probe_configuration_paths,
    render_default_configuration,
    resolve_configuration_path,
)
from volumito.cli.constants import (
    MUTUALLY_EXCLUSIVE_CREATE_ERROR,
    MUTUALLY_EXCLUSIVE_OUTPUT_ERROR,
    SHORT_FORMAT_FIELDS_PLAYER_STATE,
    SHORT_FORMAT_FIELDS_TRACK_INFO,
)
from volumito.cli.pure_helpers import (
    filter_queue_fields,
    filter_zones_fields,
    format_duration,
    format_playlists_as_table,
    format_queue_as_table,
    format_seek,
    format_zones_as_table,
    rebase_queue_positions,
    resolve_albumart_uri,
)
from volumito.clients import (
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
        msg = f'"{__version__}"'
    else:
        msg = f"volumito, version {__version__}"
    click.echo(msg)


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
@option_overwrite_existing_files
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
    content = render_default_configuration(defaults, __version__)
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
@option_file_name_template
@option_output_directory
@option_output_file
@option_overwrite_existing_files
@option_create_download_manifest
@option_add_cover_and_metadata
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
@option_file_name_template
@option_output_directory
@option_output_file
@option_overwrite_existing_files
@option_create_download_manifest
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
