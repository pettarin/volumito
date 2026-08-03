"""Command-line interface for volumito.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

import json
import os
import sys
from datetime import UTC, datetime
from typing import Any, NoReturn

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
    expand_output_directory,
    fetch_or_exit,
    fetch_state_or_exit,
    ignore_configuration_file_callback,
    option_add_cover_and_metadata,
    option_albumart_file_name_template,
    option_audio_file_name_template,
    option_check_next_track,
    option_check_playlist_name,
    option_create_download_manifest,
    option_current_track,
    option_fields,
    option_file_name_template,
    option_format,
    option_manifest_file,
    option_number_retries_next_track,
    option_output_directory,
    option_output_file,
    option_overwrite_existing_files,
    option_print_resulting_status,
    option_replace_characters_in_file_names,
    option_replace_characters_in_file_names_with,
    option_story_type,
    option_with_albumart,
    read_queue_log,
    render_output_filename,
    render_payload,
    render_state,
    render_story,
    resolve_output_conflict,
    resolve_story_album_entities,
    resolve_story_entity,
    rest_api_sleep,
    write_queue_log,
)
from volumito.cli.configuration import (
    CONFIGURATION_FILENAMES,
    default_configuration_template,
    find_destination_conflicts,
    flatten_configuration,
    load_configuration_with_errors,
    probe_configuration_paths,
    resolve_configuration_path,
)
from volumito.cli.constants import (
    DEFAULT_VOLUMIO_VERSION,
    MPD_PORT_VOLUMIO_3,
    MPD_PORT_VOLUMIO_4,
    MUTUALLY_EXCLUSIVE_CREATE_ERROR,
    OUTPUT_DIRECTORY_REQUIRED_ERROR,
    OUTPUT_DIRECTORY_TIMESTAMP_FORMAT,
    SHORT_FORMAT_FIELDS_PLAYER_STATE,
    SHORT_FORMAT_FIELDS_TRACK_INFO,
)
from volumito.cli.pure_helpers import (
    display_position,
    expand_manifest_file,
    expand_timestamp_placeholder,
    filter_queue_fields,
    filter_zones_fields,
    format_duration,
    format_playlists_as_table,
    format_queue_as_table,
    format_seek,
    format_zones_as_table,
    manifest_matches_queue,
    queue_album_volumes,
    queue_track_metadata_current,
    rebase_queue_positions,
    resolve_albumart_uri,
)
from volumito.clients import (
    Artist,
    Label,
    Place,
    Scheme,
    VolumioAPIError,
    VolumioConnectionError,
    VolumioHostConfiguration,
    VolumioMPDClient,
    VolumioRESTAPIClient,
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
        "Path to a YAML configuration file defining option defaults, "
        "overriding the hardcoded defaults. "
        "Explicit command line options override them. "
        "If omitted, configuration files are searched in the locations listed "
        "by the 'configuration search' command."
    ),
)
@click.option(
    "--host",
    "-H",
    type=str,
    default="volumio.local",
    show_default=True,
    help="Hostname or IP address of the Volumio instance.",
)
@click.option(
    "--ignore-configuration-file",
    "-i",
    is_flag=True,
    default=False,
    is_eager=True,
    expose_value=False,
    callback=ignore_configuration_file_callback,
    help="Ignore any configuration file found.",
)
@click.option(
    "--machine-readable",
    "-m",
    is_flag=True,
    default=False,
    help=(
        "Produce machine-readable output only, "
        "superseding the --verbose option if also specified."
    ),
)
@click.option(
    "--mpd-port",
    "-M",
    type=int,
    default=6600,
    show_default=True,
    help="MPD port of the Volumio instance.",
)
@click.option(
    "--mpd-timeout",
    type=float,
    default=5.0,
    show_default=True,
    help="MPD connection timeout, in seconds.",
)
@click.option(
    "--position-starting-at-one/--position-starting-at-zero",
    default=True,
    show_default=True,
    help="Index queue positions starting at one (or at zero).",
)
@click.option(
    "--rest-api-port",
    "-P",
    type=int,
    default=3000,
    show_default=True,
    help="REST API port of the Volumio instance.",
)
@click.option(
    "--rest-api-sleep-before-next-call",
    type=float,
    default=2.0,
    show_default=True,
    help=(
        "When making multiple REST API calls, "
        "sleep these many seconds between two consecutive calls."
    ),
)
@click.option(
    "--rest-api-timeout",
    type=float,
    default=5.0,
    show_default=True,
    help="REST API request timeout, in seconds.",
)
@click.option(
    "--scheme",
    type=SchemeParamType(),
    default="http",
    show_default=True,
    help="URL scheme for connecting to the Volumio instance.",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    default=False,
    help="Enable verbose output.",
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
    """Print the volumito version."""
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
    help="Directory in which to create a 'volumito.yaml' file.",
)
@click.option(
    "--output-file",
    "-f",
    type=str,
    default=None,
    help="Exact path of the configuration file to create.",
)
@click.option(
    "--volumio-version",
    "-V",
    type=VolumioVersionParamType(),
    default=DEFAULT_VOLUMIO_VERSION,
    show_default=True,
    help=(
        "Target Volumio version (e.g., 4.119, 4, 3.123, or 3), "
        "used to determine the MPD port to be set in the configuration file "
        "(6600 for Volumio >= 4, 6599 otherwise)."
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
    """Check that a configuration file is correct and print the values read from it.

    Without PATH, check the file that would be used after probing the standard
    locations. With --ignore-configuration-file, the command fails.
    """
    machine_readable = ctx.obj["machine_readable"]

    def fail(path_value: str | None, message: str, errors: list[str] | None = None) -> NoReturn:
        if machine_readable:
            absolute = os.path.abspath(path_value) if path_value is not None else None
            payload = {
                "path": absolute,
                "valid": False,
                "errors": errors if errors is not None else [message],
            }
            click.echo(json.dumps(payload))
        elif path_value is not None:
            click.echo(f"Configuration file {path_value} is NOT valid.\n", err=True)
            click.echo(message, err=True)
        else:
            click.echo(f"Error: {message}", err=True)
        sys.exit(1)

    if ctx.obj.get("ignore_configuration_file"):
        fail(None, "the --ignore-configuration-file option is selected")

    try:
        resolved = resolve_configuration_path(path)
    except click.BadParameter as error:
        fail(path, error.message)
    if resolved is None:
        fail(None, "no configuration file found")

    config, problems = load_configuration_with_errors(resolved)

    def describe(section: str) -> str:
        if section == "downloads":
            return "the shared 'downloads' section"
        return f"the '{section}' subsection"

    problems.extend(
        f"output-file and output-directory are mutually exclusive: "
        f"'{subsection}' takes output-file from {describe(file_origin)} "
        f"and output-directory from {describe(directory_origin)}"
        for subsection, file_origin, directory_origin in find_destination_conflicts(config)
    )
    if len(problems) == 1:
        fail(resolved, problems[0], errors=problems)
    if problems:
        numbered = "\n".join(f"{index}. {problem}" for index, problem in enumerate(problems, 1))
        fail(resolved, numbered, errors=problems)

    if machine_readable:
        click.echo(
            json.dumps({"path": os.path.abspath(resolved), "valid": True, "configuration": config})
        )
    else:
        click.echo(f"Configuration file {resolved} is valid.\n")
        for dotted, value in flatten_configuration(config):
            click.echo(f"{dotted} = {value}")


@configuration.command("search")
@click.pass_context
def configuration_search(ctx: click.Context) -> None:
    """List every probed configuration path, marking those found and the one used.

    With --ignore-configuration-file, the found files are marked as ignored.
    """
    machine_readable = ctx.obj["machine_readable"]
    ignore = ctx.obj.get("ignore_configuration_file", False)

    rows = probe_configuration_paths()
    if ignore:
        rows = [(path, found, False) for path, found, _ in rows]

    if machine_readable:
        click.echo(
            json.dumps(
                [
                    {"path": path, "found": found, "used": used, "ignored": ignore and found}
                    for path, found, used in rows
                ]
            )
        )
        return

    click.echo("Configuration file locations, in probing order, in decreasing order of priority:")
    for path, found, used in rows:
        if not found:
            click.echo(f"  {path}")
        elif ignore:
            click.echo(f"  {path} (found, ignored)")
        elif used:
            click.echo(f"  {path} (found, used)")
        else:
            click.echo(f"  {path} (found, NOT used)")


@main.group()
@click.pass_context
def playback(ctx: click.Context) -> None:
    """Control the playback."""
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
    """Print the playback status."""
    render_state(ctx, fields, output_format, SHORT_FORMAT_FIELDS_PLAYER_STATE)


@playback.command()
@click.pass_context
@option_print_resulting_status
def toggle(ctx: click.Context, print_resulting_status: bool) -> None:
    """Toggle between play and pause states."""
    execute_command(ctx, "toggle", lambda c: c.toggle())
    execute_conditionally(ctx, print_resulting_status, playback_status)


@playback.command()
@click.pass_context
@click.argument(
    "position",
    required=False,
    default=None,
    type=int,
)
@option_print_resulting_status
def play(ctx: click.Context, position: int | None, print_resulting_status: bool) -> None:
    """Start playback.

    With POSITION, play the track at that position of the queue (indexed according
    to --position-starting-at-one/--position-starting-at-zero).
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
    """Pause playback."""
    execute_command(ctx, "pause", lambda c: c.pause())
    execute_conditionally(ctx, print_resulting_status, playback_status)


@playback.command()
@click.pass_context
@option_print_resulting_status
def stop(ctx: click.Context, print_resulting_status: bool) -> None:
    """Stop playback."""
    execute_command(ctx, "stop", lambda c: c.stop())
    execute_conditionally(ctx, print_resulting_status, playback_status)


@playback.command()
@click.pass_context
@option_print_resulting_status
def next(ctx: click.Context, print_resulting_status: bool) -> None:
    """Skip to the next track."""
    execute_command(ctx, "next", lambda c: c.next())
    execute_conditionally(ctx, print_resulting_status, playback_status)


@playback.command()
@click.pass_context
@option_print_resulting_status
def previous(ctx: click.Context, print_resulting_status: bool) -> None:
    """Skip to the previous track."""
    execute_command(ctx, "previous", lambda c: c.previous())
    execute_conditionally(ctx, print_resulting_status, playback_status)


@playback.command()
@click.pass_context
@click.argument("value", required=False, default=None, type=SeekParamType())
@click.option(
    "--check-seek-position/--no-check-seek-position",
    default=True,
    show_default=True,
    help="Check that the seek position is within the duration of the current track.",
)
@option_print_resulting_status
def seek(
    ctx: click.Context,
    value: int | str | None,
    check_seek_position: bool,
    print_resulting_status: bool,
) -> None:
    """Print, set, or adjust the seek position.

    Without VALUE, print the current position as HH:MM:SS.mmm. Otherwise VALUE is
    a number of seconds, a HH:MM:SS (or MM:SS) time, or one of "plus" (also
    "increase"/"up"/"forward") and "minus" (also "decrease"/"down"/"backward")
    to seek relative to the current position.

    Unless --no-check-seek-position is given, an absolute position is checked
    against the duration of the current track.
    """
    if value is None:
        # Read the raw state (not the seek property, which rounds to whole seconds)
        # to keep the millisecond precision of the printed position
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

    if isinstance(value, int):
        target = value

        def set_seek(client: VolumioRESTAPIClient) -> None:
            client.seek = target

        execute_command(ctx, f"seek {value}", set_seek)
    elif value == "plus":
        execute_command(ctx, "seek plus", lambda c: c.seek_forward())
    elif value == "minus":
        execute_command(ctx, "seek minus", lambda c: c.seek_backward())
    execute_conditionally(ctx, print_resulting_status, playback_status)


@playback.command()
@click.pass_context
@click.argument("value", required=False, default=None, type=VolumeParamType())
@option_print_resulting_status
def volume(ctx: click.Context, value: int | str | None, print_resulting_status: bool) -> None:
    """Print, set, or adjust the volume.

    Without VALUE, print the current volume. Otherwise VALUE is an integer
    between 0 and 100, or one of "mute", "unmute", "plus" (also "increase"/"up"),
    and "minus" (also "decrease"/"down").
    """
    if value is None:
        click.echo(fetch_or_exit(ctx, lambda c: c.volume))
        return
    if isinstance(value, int):
        level = value

        def set_volume(client: VolumioRESTAPIClient) -> None:
            client.volume = level

        execute_command(ctx, f"volume {value}", set_volume)
    elif value == "mute":
        execute_command(ctx, "volume mute", lambda c: c.mute())
    elif value == "unmute":
        execute_command(ctx, "volume unmute", lambda c: c.unmute())
    elif value == "plus":
        execute_command(ctx, "volume plus", lambda c: c.increase_volume())
    elif value == "minus":
        execute_command(ctx, "volume minus", lambda c: c.decrease_volume())
    execute_conditionally(ctx, print_resulting_status, playback_status)


@playback.command()
@click.pass_context
@option_print_resulting_status
def mute(ctx: click.Context, print_resulting_status: bool) -> None:
    """Mute the volume."""
    execute_command(ctx, "volume mute", lambda c: c.mute())
    execute_conditionally(ctx, print_resulting_status, playback_status)


@playback.command()
@click.pass_context
@option_print_resulting_status
def unmute(ctx: click.Context, print_resulting_status: bool) -> None:
    """Unmute the volume."""
    execute_command(ctx, "volume unmute", lambda c: c.unmute())
    execute_conditionally(ctx, print_resulting_status, playback_status)


@playback.command("is_muted")
@click.pass_context
def is_muted(ctx: click.Context) -> None:
    """Print whether the volume is muted."""
    muted = fetch_or_exit(ctx, lambda c: c.is_muted)
    click.echo(json.dumps(muted) if ctx.obj["machine_readable"] else muted)


@playback.command("is_paused")
@click.pass_context
def is_paused(ctx: click.Context) -> None:
    """Print whether the playback is paused."""
    paused = fetch_or_exit(ctx, lambda c: c.is_paused)
    click.echo(json.dumps(paused) if ctx.obj["machine_readable"] else paused)


@playback.command("is_playing")
@click.pass_context
def is_playing(ctx: click.Context) -> None:
    """Print whether the playback is playing."""
    playing = fetch_or_exit(ctx, lambda c: c.is_playing)
    click.echo(json.dumps(playing) if ctx.obj["machine_readable"] else playing)


@playback.command("is_stopped")
@click.pass_context
def is_stopped(ctx: click.Context) -> None:
    """Print whether the playback is stopped."""
    stopped = fetch_or_exit(ctx, lambda c: c.is_stopped)
    click.echo(json.dumps(stopped) if ctx.obj["machine_readable"] else stopped)


@main.group()
@click.pass_context
def track(ctx: click.Context) -> None:
    """Query the current track (information, audio, album art)."""
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
    """Print the URI of and/or download the audio of the current track."""
    output_file, output_directory = resolve_output_conflict(ctx, output_file, output_directory)
    output_directory = expand_output_directory(output_directory)

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
        state = client.state

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
    """Print the URI of and/or download the album art of the current track."""
    output_file, output_directory = resolve_output_conflict(ctx, output_file, output_directory)
    output_directory = expand_output_directory(output_directory)

    host_configuration = ctx.obj["host_configuration"]
    rest_api_timeout = ctx.obj["rest_api_timeout"]
    verbose = ctx.obj["verbose"]
    machine_readable = ctx.obj["machine_readable"]

    if verbose and not machine_readable:
        click.echo(f"Connecting to {host_configuration.rest_base_url}...", err=True)

    try:
        # Get current state metadata
        client = create_client(host_configuration, rest_api_timeout)
        state = client.state

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
    """Manage the playback queue."""
    pass


@queue.command("list")
@click.pass_context
@option_fields
@option_format
def queue_list(
    ctx: click.Context,
    fields: str,
    output_format: str,
) -> None:
    """Print the playback queue."""
    host_configuration = ctx.obj["host_configuration"]
    rest_api_timeout = ctx.obj["rest_api_timeout"]
    verbose = ctx.obj["verbose"]
    machine_readable = ctx.obj["machine_readable"]
    position_starting_at_one = ctx.obj["position_starting_at_one"]

    if verbose and not machine_readable:
        click.echo(f"Connecting to {host_configuration.rest_base_url}...", err=True)

    try:
        client = create_client(host_configuration, rest_api_timeout)
        queue_data = client.queue

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
@option_check_next_track
@option_create_download_manifest
@option_manifest_file
@option_number_retries_next_track
@option_output_directory
@option_overwrite_existing_files
@option_replace_characters_in_file_names
@option_replace_characters_in_file_names_with
@option_with_albumart
def queue_download(
    ctx: click.Context,
    add_cover_and_metadata: bool,
    albumart_file_name_template: str,
    audio_file_name_template: str,
    check_next_track: bool,
    create_download_manifest: bool,
    manifest_file: str,
    number_retries_next_track: int,
    output_directory: str | None,
    overwrite_existing_files: bool,
    replace_characters_in_file_names: str,
    replace_characters_in_file_names_with: str,
    with_albumart: bool,
) -> None:
    """Download every track of the current queue.

    The download manifest is written to --manifest-file, by default manifest.json
    inside the output directory. If the manifest file already exists, only the
    tracks not yet downloaded are retried.
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
        tracks = client.queue.get("queue", [])

        if verbose and not machine_readable:
            click.echo("Successfully retrieved queue", err=True)

        if not tracks:
            if not machine_readable:
                click.echo("The queue is empty, nothing to download")
            return

        timestamp = datetime.now(UTC).strftime(OUTPUT_DIRECTORY_TIMESTAMP_FORMAT)
        run_directory = expand_timestamp_placeholder(output_directory, timestamp)
        log_path = expand_manifest_file(manifest_file, run_directory, timestamp)

        now = datetime.now(UTC).isoformat()
        if os.path.exists(log_path):
            existing = read_queue_log(log_path)
            if existing is None:
                if not machine_readable:
                    click.echo(f"Error: cannot read the manifest file {log_path}", err=True)
                sys.exit(1)
            if not manifest_matches_queue(existing["tracks"], tracks):
                if not machine_readable:
                    click.echo(
                        f"Error: the manifest file {log_path} does not match "
                        "the current queue",
                        err=True,
                    )
                sys.exit(1)
            if not machine_readable:
                click.echo(f"Reading manifest file {log_path}")
            entries: list[dict[str, Any]] = existing["tracks"]
            for entry in entries:
                if entry.get("status") == "downloaded":
                    continue
                # A skipped track is kept when its file is still present (unless
                # the files are to be overwritten); anything else is retried
                output_file_path = entry.get("output_file_path")
                if (
                    entry.get("status") == "skipped"
                    and not overwrite_existing_files
                    and isinstance(output_file_path, str)
                    and os.path.exists(output_file_path)
                ):
                    continue
                entry["status"] = "pending"
                entry.pop("error", None)
            log: dict[str, Any] = {
                "entity": "queue",
                "first_download_date": existing.get(
                    "first_download_date", existing.get("download_date", now)
                ),
                "kind": "download",
                "last_update_date": now,
                "output_directory": run_directory,
                "tracks": entries,
                "updates": existing.get("updates", 0) + 1,
                "volumio_host": host_configuration.rest_base_url,
                "volumito_version": __version__,
            }
        else:
            if not machine_readable:
                click.echo(f"Creating manifest file {log_path}")
            entries = [
                {
                    "album": track.get("album"),
                    "artist": track.get("artist"),
                    "position": display_position(index, position_starting_at_one),
                    "status": "pending",
                    "title": track.get("title"),
                    "track_number": track.get("tracknumber"),
                    "volume_number": track.get("volumeNumber"),
                }
                for index, track in enumerate(tracks)
            ]
            log = {
                "entity": "queue",
                "first_download_date": now,
                "kind": "download",
                "last_update_date": now,
                "output_directory": run_directory,
                "tracks": entries,
                "updates": 1,
                "volumio_host": host_configuration.rest_base_url,
                "volumito_version": __version__,
            }
        os.makedirs(run_directory, exist_ok=True)
        log_parent = os.path.dirname(log_path)
        if log_parent:
            os.makedirs(log_parent, exist_ok=True)
        write_queue_log(log_path, log)

        if all(entry.get("status") in ("downloaded", "skipped") for entry in entries):
            if machine_readable:
                click.echo(json.dumps(log_path))
            else:
                for index, entry in enumerate(entries):
                    click.echo(
                        f"[{index + 1}/{len(entries)}] {entry['status']}: "
                        f"{entry.get('output_file_path')} (kept)"
                    )
                downloaded = sum(1 for e in entries if e["status"] == "downloaded")
                skipped = sum(1 for e in entries if e["status"] == "skipped")
                click.echo(
                    f"\nDownloaded {downloaded}, skipped {skipped}, errors 0; "
                    f"manifest written to {log_path}"
                )
            return

        errors = 0
        previous_uri: str | None = None
        downloaded_covers: dict[str, str] = {}
        album_volumes = queue_album_volumes(tracks, replace_characters_in_file_names_with)
        client.stop()
        with VolumioMPDClient(host_configuration, mpd_timeout) as mpd_client:
            for index, entry in enumerate(entries):
                if entry.get("status") in ("downloaded", "skipped"):
                    if not machine_readable:
                        click.echo(
                            f"[{index + 1}/{len(entries)}] {entry['status']}: "
                            f"{entry.get('output_file_path')} (kept)"
                        )
                    continue
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
                        state = client.state
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
                        state = {
                            **state,
                            "album_volume": album_volumes[index],
                            "tracknumber": tracks[index].get("tracknumber"),
                        }
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
                f"manifest written to {log_path}"
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
    """Clear the playback queue."""
    execute_command(ctx, "clear", lambda c: c.clear())
    execute_conditionally(ctx, print_resulting_status, playback_status)


@queue.command()
@click.pass_context
@click.argument("value", required=False, default=None, type=OnOffParamType())
@option_print_resulting_status
def repeat(ctx: click.Context, value: bool | None, print_resulting_status: bool) -> None:
    """Set or toggle the repeat mode.

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
    """Set or toggle the random (shuffle) mode.

    Without VALUE, toggle the current mode. Otherwise VALUE is "on"/"true"/"yes"/"1"
    or "off"/"false"/"no"/"0".
    """
    label = "randomize" if value is None else f"randomize {'on' if value else 'off'}"
    execute_command(ctx, label, lambda c: c.randomize(value))
    execute_conditionally(ctx, print_resulting_status, playback_status)


@main.group()
@click.pass_context
def system(ctx: click.Context) -> None:
    """Query Volumio system utilities."""
    pass


@system.command("ping")
@click.pass_context
def system_ping(ctx: click.Context) -> None:
    """Ping the Volumio instance, printing 'pong' on success."""
    text = fetch_or_exit(ctx, lambda c: c.ping()).strip()
    if ctx.obj["machine_readable"]:
        click.echo(json.dumps(text))
    else:
        click.echo(text)


@system.command("version")
@click.pass_context
@option_format
def system_version(ctx: click.Context, output_format: str) -> None:
    """Print the system version."""
    data = fetch_or_exit(ctx, lambda c: c.system_version)
    render_payload(ctx, data, output_format, heading="Volumio System Version")


@system.command("info")
@click.pass_context
@option_format
def system_info(ctx: click.Context, output_format: str) -> None:
    """Print the system information."""
    data = fetch_or_exit(ctx, lambda c: c.system_info)
    render_payload(ctx, data, output_format, heading="Volumio System Info")


@main.group()
@click.pass_context
def collection(ctx: click.Context) -> None:
    """Query the local music collection managed by Volumio."""
    pass


@collection.command("statistics")
@click.pass_context
@option_format
def collection_statistics(ctx: click.Context, output_format: str) -> None:
    """Print the statistics of the music collection."""
    data = fetch_or_exit(ctx, lambda c: c.collection_statistics)
    render_payload(ctx, data, output_format, heading="Collection Statistics")


@main.group()
@click.pass_context
def zones(ctx: click.Context) -> None:
    """Query the multiroom zones."""
    pass


@zones.command("list")
@click.pass_context
@option_fields
@option_format
def zones_list(ctx: click.Context, fields: str, output_format: str) -> None:
    """Print the multiroom zones seen by the Volumio instance."""
    data = fetch_or_exit(ctx, lambda c: c.zones)

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
    """Query, play, and download the saved playlists."""
    pass


@playlist.command("list")
@click.pass_context
@option_format
def playlist_list(ctx: click.Context, output_format: str) -> None:
    """List the Volumio playlists saved by the current user."""
    names = fetch_or_exit(ctx, lambda c: c.playlists)

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
@option_check_playlist_name
@option_print_resulting_status
def playlist_play(
    ctx: click.Context,
    name: str,
    check_playlist_name: bool,
    print_resulting_status: bool,
) -> None:
    """Start playback of the playlist specified by NAME."""
    if check_playlist_name:
        names = fetch_or_exit(ctx, lambda c: c.playlists)
        if name not in names:
            if not ctx.obj["machine_readable"]:
                click.echo(f"Error: playlist not found: {name}", err=True)
                click.echo("Available playlists:", err=True)
                for available in names or ["(none)"]:
                    click.echo(f"  {available}", err=True)
            sys.exit(1)

    execute_command(ctx, f"playplaylist {name}", lambda c: c.play_playlist(name))
    execute_conditionally(ctx, print_resulting_status, playback_status)


@playlist.command("download")
@click.pass_context
@click.argument("name", type=str)
@option_add_cover_and_metadata
@option_albumart_file_name_template
@option_audio_file_name_template
@option_check_next_track
@option_check_playlist_name
@option_create_download_manifest
@option_manifest_file
@option_number_retries_next_track
@option_output_directory
@option_overwrite_existing_files
@option_print_resulting_status
@option_replace_characters_in_file_names
@option_replace_characters_in_file_names_with
@option_with_albumart
def playlist_download(
    ctx: click.Context,
    name: str,
    add_cover_and_metadata: bool,
    albumart_file_name_template: str,
    audio_file_name_template: str,
    check_next_track: bool,
    check_playlist_name: bool,
    create_download_manifest: bool,
    manifest_file: str,
    number_retries_next_track: int,
    output_directory: str | None,
    overwrite_existing_files: bool,
    print_resulting_status: bool,
    replace_characters_in_file_names: str,
    replace_characters_in_file_names_with: str,
    with_albumart: bool,
) -> None:
    """Download every track of the playlist specified by NAME."""
    machine_readable = ctx.obj["machine_readable"]
    verbose = ctx.obj["verbose"]

    if check_playlist_name:
        names = fetch_or_exit(ctx, lambda c: c.playlists)
        if name not in names:
            if not machine_readable:
                click.echo(f"Error: playlist not found: {name}", err=True)
                click.echo("Available playlists:", err=True)
                for available in names or ["(none)"]:
                    click.echo(f"  {available}", err=True)
            sys.exit(1)

    host_configuration = ctx.obj["host_configuration"]
    rest_api_timeout = ctx.obj["rest_api_timeout"]

    try:
        client = create_client(host_configuration, rest_api_timeout)
        if verbose and not machine_readable:
            click.echo("Clearing the queue...", err=True)
        client.clear()
        rest_api_sleep(ctx)
        if verbose and not machine_readable:
            click.echo(f"Playing playlist {name}...", err=True)
        client.play_playlist(name)
        rest_api_sleep(ctx)
    except VolumioConnectionError as e:
        if not machine_readable:
            click.echo(f"Connection error: {e}", err=True)
        sys.exit(1)
    except VolumioAPIError as e:
        if not machine_readable:
            click.echo(f"API error: {e}", err=True)
        sys.exit(1)

    ctx.invoke(
        queue_download,
        add_cover_and_metadata=add_cover_and_metadata,
        albumart_file_name_template=albumart_file_name_template,
        audio_file_name_template=audio_file_name_template,
        check_next_track=check_next_track,
        create_download_manifest=create_download_manifest,
        manifest_file=manifest_file,
        number_retries_next_track=number_retries_next_track,
        output_directory=output_directory,
        overwrite_existing_files=overwrite_existing_files,
        replace_characters_in_file_names=replace_characters_in_file_names,
        replace_characters_in_file_names_with=replace_characters_in_file_names_with,
        with_albumart=with_albumart,
    )
    execute_conditionally(ctx, print_resulting_status, playback_status)


@main.group()
@click.pass_context
def story(ctx: click.Context) -> None:
    """Retrieve stories about albums, artists, labels, or places.

    Requires a Premium (or better) subscription on the Volumio instance.
    """
    pass


@story.command("album")
@click.pass_context
@click.argument("arguments", nargs=-1, type=str)
@option_current_track
@option_fields
@option_format
@option_story_type
def story_album(
    ctx: click.Context,
    arguments: tuple[str, ...],
    current_track: bool,
    fields: str,
    output_format: str,
    argument_type: str,
) -> None:
    """Print the story of an album.

    The album can be specified by ARTIST ALBUM (free strings),
    a single MBID, or detected from the current track
    if --current-track is specified."""
    artist, album = resolve_story_album_entities(
        ctx, arguments, argument_type, current_track=current_track
    )
    render_story(
        ctx,
        lambda c: c.get_story(album=album, artist=artist),
        fields,
        output_format,
        heading="Album Story",
    )


@story.command("artist")
@click.pass_context
@click.argument("value", required=False, default=None, type=str)
@option_current_track
@option_fields
@option_format
@option_story_type
def story_artist(
    ctx: click.Context,
    value: str | None,
    current_track: bool,
    fields: str,
    output_format: str,
    argument_type: str,
) -> None:
    """Print the story of an artist.

    The artist can be specified by VALUE (free string),
    a single MBID, or detected from the current track
    if --current-track is specified."""
    arguments = () if value is None else (value,)
    artist = resolve_story_entity(
        ctx, arguments, argument_type, Artist, current_track=current_track
    )
    render_story(
        ctx,
        lambda c: c.get_story(artist=artist),
        fields,
        output_format,
        heading="Artist Story",
    )


@story.command("credits")
@click.pass_context
@click.argument("arguments", nargs=-1, type=str)
@option_current_track
@option_fields
@option_format
@option_story_type
def story_credits(
    ctx: click.Context,
    arguments: tuple[str, ...],
    current_track: bool,
    fields: str,
    output_format: str,
    argument_type: str,
) -> None:
    """Print the credits of an album.

    The album can be specified by ARTIST ALBUM (free strings),
    a single MBID, or detected from the current track
    if --current-track is specified."""
    artist, album = resolve_story_album_entities(
        ctx, arguments, argument_type, current_track=current_track
    )
    render_story(
        ctx,
        lambda c: c.get_album_credits(artist, album),
        fields,
        output_format,
        heading="Album Credits",
    )


@story.command("label")
@click.pass_context
@click.argument("value", type=str)
@option_fields
@option_format
@option_story_type
def story_label(
    ctx: click.Context,
    value: str,
    fields: str,
    output_format: str,
    argument_type: str,
) -> None:
    """Print the story of a label.

    The label can be specified by VALUE (free string) or a single MBID."""
    label = resolve_story_entity(ctx, (value,), argument_type, Label)
    render_story(
        ctx,
        lambda c: c.get_story(label=label),
        fields,
        output_format,
        heading="Label Story",
    )


@story.command("place")
@click.pass_context
@click.argument("value", type=str)
@option_fields
@option_format
@option_story_type
def story_place(
    ctx: click.Context,
    value: str,
    fields: str,
    output_format: str,
    argument_type: str,
) -> None:
    """Print the story of a place.

    The place can be specified by VALUE (free string) or a single MBID."""
    place = resolve_story_entity(ctx, (value,), argument_type, Place)
    render_story(
        ctx,
        lambda c: c.get_story(place=place),
        fields,
        output_format,
        heading="Place Story",
    )


# "info" is a top-level synonym for "system info"
main.add_command(system_info, name="info")


if __name__ == "__main__":  # pragma: no cover
    main()
