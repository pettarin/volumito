"""Command-line interface for volumito.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

import http.client
import json
import os
import sys
from datetime import UTC, datetime
from typing import Any, NoReturn

import click

from volumito import __version__
from volumito.cli.click_helpers import (
    AliasedGroup,
    OnOffParamType,
    SchemeParamType,
    SeekParamType,
    VolumeParamType,
    VolumioVersionParamType,
    alias_problems,
    aliases_by_command_path,
    command_nodes,
    command_nodes_flattened,
    configuration_file_callback,
    create_client,
    download_queue_albumart,
    download_queue_track,
    download_uri_to,
    echo_data,
    embed_track_tags,
    execute_command,
    execute_conditionally,
    expand_output_directory,
    fetch_or_exit,
    fetch_state_or_exit,
    ignore_configuration_file_callback,
    option_add_cover_and_metadata,
    option_album,
    option_albumart_file_name_template,
    option_albums_only,
    option_all_notifications,
    option_allow_local_file_rename,
    option_artist,
    option_artists_only,
    option_audio_file_name_template,
    option_autocompose_url,
    option_best_result_only,
    option_check_next_track,
    option_check_playlist_name,
    option_count,
    option_create_download_manifest,
    option_current_track,
    option_endpoint,
    option_fields,
    option_file_name_template,
    option_format,
    option_format_table,
    option_idle_timeout,
    option_limit,
    option_manifest_file,
    option_number_retries_next_track,
    option_offset,
    option_only_tracks,
    option_output_directory,
    option_output_file,
    option_overwrite_existing_files,
    option_play,
    option_playlist,
    option_playlists_only,
    option_port,
    option_position,
    option_print_resulting_status,
    option_print_uri,
    option_print_uri_toggle,
    option_propagate_remote_exit_code,
    option_recursive,
    option_register_url,
    option_register_url_full,
    option_replace_characters_in_file_names,
    option_replace_characters_in_file_names_with,
    option_result_kinds,
    option_service,
    option_story_type,
    option_timeout,
    option_track,
    option_tracks_only,
    option_unregister_url_on_exit,
    option_with_albumart,
    option_yes,
    read_queue_log,
    render_fields,
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
from volumito.cli.console import LOGGER, debug, error, info, setup_console, warning
from volumito.cli.constants import (
    BROWSE_KINDS_ERROR,
    DEFAULT_VOLUMIO_VERSION,
    MAX_HTTP_HEADERS,
    MPD_PORT_VOLUMIO_3,
    MPD_PORT_VOLUMIO_4,
    MUTUALLY_EXCLUSIVE_CREATE_ERROR,
    MUTUALLY_EXCLUSIVE_REGISTER_ERROR,
    MUTUALLY_EXCLUSIVE_UNREGISTER_ERROR,
    NOTIFICATION_ENDPOINT_ERROR,
    NOTIFICATION_TIMESTAMP_FORMAT,
    OUTPUT_DIRECTORY_REQUIRED_ERROR,
    OUTPUT_DIRECTORY_TIMESTAMP_FORMAT,
    PROGRAM_NAME,
    REGISTER_ARGUMENT_ERROR,
    REPLACE_POSITION_ERROR,
    SEARCH_ARGUMENT_ERROR,
    SEARCH_KINDS_ERROR,
    SEARCH_LIMIT_ERROR,
    SHORT_FORMAT_FIELDS_PLAYER_STATE,
    SHORT_FORMAT_FIELDS_QUEUE_STATUS,
    SHORT_FORMAT_FIELDS_TRACK_INFO,
    UNREGISTER_ARGUMENT_ERROR,
)
from volumito.cli.pure_helpers import (
    display_position,
    expand_manifest_file,
    expand_timestamp_placeholder,
    filter_queue_fields,
    filter_zones_fields,
    format_browse_results_as_table,
    format_command_nodes,
    format_duration,
    format_names_as_table,
    format_notification_as_line,
    format_queue_as_table,
    format_search_results_as_table,
    format_seek,
    format_termination_conditions,
    format_zones_as_table,
    manifest_matches_queue,
    preserve_local_file_name,
    queue_album_volumes,
    queue_track_metadata_current,
    rebase_queue_positions,
    resolve_albumart_uri,
)
from volumito.clients import (
    Artist,
    Label,
    NotificationListener,
    Place,
    PushNotification,
    Scheme,
    SearchResultItemKind,
    SuccessResponse,
    VolumioAPIError,
    VolumioConnectionError,
    VolumioHostConfiguration,
    VolumioMPDClient,
    VolumioRESTAPIClient,
    VolumioSCPError,
    VolumioSSHError,
    copy_from_host,
    copy_to_host,
    execute_on_host,
    is_local_file_uri,
    receiver_url,
)


@click.group(cls=AliasedGroup)
@click.option(
    "--color/--no-color",
    default=True,
    show_default=True,
    help="Color the messages of the tool (when the terminal supports it).",
)
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
    "--pager/--no-pager",
    "-G",
    default=False,
    show_default=True,
    help="Print the data output through a pager (when on a terminal).",
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
    "--rest-api-retries-on-unexpected-state",
    type=int,
    default=3,
    show_default=True,
    help=(
        "When a command expects the playback status to reach a given state, "
        "re-read the status up to this many times."
    ),
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
    "--rest-api-timeout-slow-endpoints",
    type=float,
    default=60.0,
    show_default=True,
    help=(
        "REST API request timeout for the endpoints that can take long "
        "(e.g., replacing the queue), in seconds."
    ),
)
@click.option(
    "--scheme",
    type=SchemeParamType(),
    default="http",
    show_default=True,
    help="URL scheme for connecting to the Volumio instance.",
)
@click.option(
    "--ssh-password",
    type=str,
    default=None,
    help=(
        "SSH password of the Volumio instance; it stays in the shell history, "
        "so a private key authorized on the host is preferable."
    ),
)
@click.option(
    "--ssh-port",
    type=int,
    default=22,
    show_default=True,
    help="SSH port of the Volumio instance, used to copy the files it stores.",
)
@click.option(
    "--ssh-username",
    type=str,
    default="volumio",
    show_default=True,
    help="SSH user name on the Volumio instance.",
)
@click.option(
    "--strict-parsing-configuration-file/--no-strict-parsing-configuration-file",
    default=False,
    show_default=True,
    help="Turn the configuration file problems into errors (or warn and continue).",
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
    color: bool,
    host: str,
    machine_readable: bool,
    mpd_port: int,
    mpd_timeout: float,
    pager: bool,
    position_starting_at_one: bool,
    rest_api_port: int,
    rest_api_retries_on_unexpected_state: int,
    rest_api_sleep_before_next_call: float,
    rest_api_timeout: float,
    rest_api_timeout_slow_endpoints: float,
    scheme: Scheme,
    ssh_password: str | None,
    ssh_port: int,
    ssh_username: str,
    strict_parsing_configuration_file: bool,
    verbose: bool,
) -> None:
    """volumito - CLI tool for Volumio."""
    setup_console(verbose=verbose, machine_readable=machine_readable, color=color)
    # Some hosts send more headers than the http.client default limit (100),
    # aborting the connection: to avoid that, raise the limit to 10000
    http.client._MAXHEADERS = MAX_HTTP_HEADERS  # type: ignore[attr-defined]
    # Store common options in context for subcommands to access
    ctx.ensure_object(dict)
    ctx.obj["host_configuration"] = VolumioHostConfiguration(
        scheme=scheme,
        host=host,
        rest_api_port=rest_api_port,
        mpd_port=mpd_port,
        ssh_password=ssh_password,
        ssh_port=ssh_port,
        ssh_username=ssh_username,
    )
    ctx.obj["rest_api_timeout"] = rest_api_timeout
    ctx.obj["rest_api_timeout_slow_endpoints"] = rest_api_timeout_slow_endpoints
    ctx.obj["mpd_timeout"] = mpd_timeout
    ctx.obj["rest_api_retries_on_unexpected_state"] = rest_api_retries_on_unexpected_state
    ctx.obj["rest_api_sleep_before_next_call"] = rest_api_sleep_before_next_call
    ctx.obj["verbose"] = verbose
    ctx.obj["machine_readable"] = machine_readable
    ctx.obj["pager"] = pager
    ctx.obj["position_starting_at_one"] = position_starting_at_one

    configuration_file = ctx.obj.get("configuration_file")
    if configuration_file is not None:
        debug(f'Using configuration file: "{configuration_file}"')
    elif ctx.obj.get("ignore_configuration_file"):
        debug("Ignoring configuration files")
    problems = ctx.obj.get("configuration_problems", [])
    if problems and strict_parsing_configuration_file:
        for problem in problems:
            error(problem)
        sys.exit(1)
    for problem in problems:
        warning(problem)


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
    "-o",
    type=str,
    default=None,
    help="Exact path of the configuration file to create.",
)
@option_overwrite_existing_files
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
def configuration_create(
    ctx: click.Context,
    output_directory: str | None,
    output_file: str | None,
    overwrite_existing_files: bool,
    volumio_version: int,
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
        error(
            f'File already exists: "{destination}" '
            "(use --overwrite-existing-files to overwrite)"
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
        error(f'Cannot write configuration file "{destination}": {e}')
        sys.exit(1)

    if machine_readable:
        click.echo(json.dumps(destination))
    else:
        info(f'Created configuration file "{destination}"')


@configuration.command("check")
@click.pass_context
@click.argument("path", required=False, type=str)
def configuration_check(ctx: click.Context, path: str | None) -> None:
    """Check that a configuration file is correct and print the values read from it.

    Without PATH, check the file that would be used after probing the standard
    locations. With --ignore-configuration-file and no PATH, the command fails.
    """
    machine_readable = ctx.obj["machine_readable"]

    def fail(
        path_value: str | None,
        messages: list[str],
        errors: list[str] | None = None,
        heading: str | None = None,
    ) -> NoReturn:
        if machine_readable:
            absolute = os.path.abspath(path_value) if path_value is not None else None
            payload = {
                "path": absolute,
                "valid": False,
                "errors": errors if errors is not None else messages,
            }
            click.echo(json.dumps(payload))
        else:
            if heading is not None:
                error(heading)
            for message in messages:
                error(message)
        sys.exit(1)

    def problems_heading(path_value: str) -> str:
        return (
            f'Configuration file "{path_value}" contains the following problem(s), '
            f"ignored when running in --no-strict-parsing-configuration-file mode:"
        )

    if path is None and ctx.obj.get("ignore_configuration_file"):
        fail(
            None,
            [
                "option -i/--ignore-configuration-file is mutually exclusive with an "
                "omitted PATH (which probes the default locations)"
            ],
        )

    try:
        resolved = resolve_configuration_path(path)
    except click.BadParameter:
        fail(path, [f'Configuration file "{path}" is not found.'])
    if resolved is None:
        fail(None, ["no configuration file found"])

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
    root = ctx.find_root().command
    if isinstance(root, click.Group):
        problems.extend(
            message for _, message in alias_problems(root, ctx, config.get("aliases", {}), resolved)
        )
    if problems:
        numbered = [f"{index}. {problem}" for index, problem in enumerate(problems, 1)]
        fail(resolved, numbered, errors=problems, heading=problems_heading(resolved))

    if machine_readable:
        click.echo(
            json.dumps({"path": os.path.abspath(resolved), "valid": True, "configuration": config})
        )
    else:
        info(f'Configuration file "{resolved}" is valid.')
        listed = "\n".join(f"{dotted} = {value}" for dotted, value in flatten_configuration(config))
        if listed:
            echo_data(ctx, listed)


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

    lines = ["Configuration file locations, in probing order, in decreasing order of priority:"]
    for path, found, used in rows:
        if not found:
            lines.append(f"  {path}")
        elif ignore:
            lines.append(f"  {path} (found, ignored)")
        elif used:
            lines.append(f"  {path} (found, used)")
        else:
            lines.append(f"  {path} (found, NOT used)")
    echo_data(ctx, "\n".join(lines))


@main.group()
@click.pass_context
def command(ctx: click.Context) -> None:
    """Query the available commands."""
    pass


@command.command("alias")
@click.pass_context
def command_alias(ctx: click.Context) -> None:
    """Print the user-defined aliases and the command paths they resolve to."""
    aliases = dict(sorted(ctx.obj.get("aliases", {}).items()))

    if ctx.obj["machine_readable"]:
        click.echo(json.dumps(aliases))
        return

    if aliases:
        echo_data(ctx, "\n".join(f"{name} : {target}" for name, target in aliases.items()))


@command.command("list")
@click.pass_context
@click.option(
    "--aliases/--no-aliases",
    "-a",
    default=True,
    show_default=True,
    help="Print the aliases next to the command paths they point at.",
)
@click.option(
    "--tree/--no-tree",
    "-t",
    default=True,
    show_default=True,
    help="Print the command tree (or the flat command paths).",
)
def command_list(ctx: click.Context, aliases: bool, tree: bool) -> None:
    """Print the available command paths, with the aliases pointing at them."""
    root = ctx.find_root().command
    indexed = aliases_by_command_path(ctx.obj.get("aliases", {})) if aliases else None
    nodes = command_nodes(root, ctx, indexed) if isinstance(root, click.Group) else []
    if not tree:
        nodes = command_nodes_flattened(nodes)

    if ctx.obj["machine_readable"]:
        click.echo(json.dumps(nodes))
        return

    lines = format_command_nodes(nodes, indent=1) if tree else format_command_nodes(nodes)
    echo_data(ctx, "\n".join([PROGRAM_NAME, *lines] if tree else lines))


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
        # Read the state seek position (not the seek property, which rounds to whole
        # seconds) to keep the millisecond precision of the printed position
        current = fetch_state_or_exit(ctx).seek
        if current is None:
            error("No seek position found in current state")
            sys.exit(1)
        position = format_seek(current)
        click.echo(json.dumps(position) if ctx.obj["machine_readable"] else position)
        return

    if check_seek_position and isinstance(value, int):
        duration = fetch_state_or_exit(ctx).duration
        # The duration is unknown for web radios and streams: skip the check
        if duration is not None and duration > 0 and value > duration:
            error(
                f"Seek position out of range: {format_duration(value)} "
                f"(current track duration: {format_duration(duration)})"
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
@option_allow_local_file_rename
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
    allow_local_file_rename: bool,
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

    debug(f"Connecting to {host_configuration.rest_base_url}...")

    try:
        # Get current track metadata (also validates REST connectivity)
        client = create_client(host_configuration, rest_api_timeout)
        state = client.state

        debug(f"Connecting to {host_configuration.rest_base_url}... done")
        debug("Successfully retrieved state")

        # Connect to MPD to get current track URI; the client logs its own steps
        with VolumioMPDClient(host_configuration, mpd_timeout, LOGGER) as mpd_client:
            uri = mpd_client.get_track_uri()

            # Always print the URI (even in machine-readable mode);
            # in machine-readable mode print it quoted so it can be consumed by jq/yq
            click.echo(json.dumps(uri) if machine_readable else uri)

            # Download the file if -o/--output-file or -d/--output-directory is specified
            if output_file is not None or output_directory is not None:
                if is_local_file_uri(uri):
                    embed_tags = False
                    debug(
                        "Not embedding the album art and the metadata, "
                        "to preserve the file being copied"
                    )
                else:
                    embed_tags = add_cover_and_metadata
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
                    embed_tags,
                    allow_local_file_rename,
                    replace_characters_in_file_names=replace_characters_in_file_names,
                    replace_characters_in_file_names_with=(
                        replace_characters_in_file_names_with
                    ),
                )

                # Embed track metadata and cover art into the downloaded file
                if embed_tags:
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
        error(f"Connection error: {e}")
        sys.exit(1)
    except VolumioAPIError as e:
        error(f"API error: {e}")
        sys.exit(1)
    except Exception as e:  # pragma: no cover
        error(f"Unexpected error: {e}")
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

    debug(f"Connecting to {host_configuration.rest_base_url}...")

    try:
        # Get current state metadata
        client = create_client(host_configuration, rest_api_timeout)
        state = client.state

        debug(f"Connecting to {host_configuration.rest_base_url}... done")
        debug("Successfully retrieved state")

        # Extract albumart URI (relative URIs are made absolute against the base URL)
        albumart_uri = resolve_albumart_uri(state, host_configuration)
        if albumart_uri is None:
            error("No album art URI found in current state")
            sys.exit(1)

        debug(f'Album art URI: "{albumart_uri}"')

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
        error(f"Connection error: {e}")
        sys.exit(1)
    except VolumioAPIError as e:
        error(f"API error: {e}")
        sys.exit(1)
    except Exception as e:  # pragma: no cover
        error(f"Unexpected error: {e}")
        sys.exit(1)


@main.group()
@click.pass_context
def queue(ctx: click.Context) -> None:
    """Manage the playback queue."""
    pass


@queue.command("has_next")
@click.pass_context
def queue_has_next(ctx: click.Context) -> None:
    """Print whether the current track has a next track in the queue."""
    value = fetch_or_exit(ctx, lambda c: c.has_next)
    click.echo(json.dumps(value) if ctx.obj["machine_readable"] else value)


@queue.command("has_previous")
@click.pass_context
def queue_has_previous(ctx: click.Context) -> None:
    """Print whether the current track has a previous track in the queue."""
    value = fetch_or_exit(ctx, lambda c: c.has_previous)
    click.echo(json.dumps(value) if ctx.obj["machine_readable"] else value)


@queue.command("status")
@click.pass_context
@option_fields
@option_format
def queue_status(ctx: click.Context, fields: str, output_format: str) -> None:
    """Print the current track with the position, length, and neighbor flags of the queue."""
    status = fetch_or_exit(ctx, lambda c: c.queue_status)
    render_fields(
        ctx, status, fields, output_format, SHORT_FORMAT_FIELDS_QUEUE_STATUS, "Volumio Queue Status"
    )


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
    position_starting_at_one = ctx.obj["position_starting_at_one"]

    debug(f"Connecting to {host_configuration.rest_base_url}...")

    try:
        client = create_client(host_configuration, rest_api_timeout)
        queue_data = client.queue.raw

        debug(f"Connecting to {host_configuration.rest_base_url}... done")
        debug("Successfully retrieved queue")

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

        echo_data(ctx, output)

    except VolumioConnectionError as e:
        error(f"Connection error: {e}")
        sys.exit(1)
    except VolumioAPIError as e:
        error(f"API error: {e}")
        sys.exit(1)
    except Exception as e:  # pragma: no cover
        error(f"Unexpected error: {e}")
        sys.exit(1)


def _download_summary(entries: list[dict[str, Any]], selected: set[int], errors: int) -> str:
    """Return the summary line of a queue download run.

    Args:
        entries: The manifest entries of every track of the queue
        selected: The indices of the tracks selected for the run
        errors: The number of tracks that could not be downloaded

    Returns:
        The counts of the run, mentioning the tracks left out when there are any
    """
    statuses = [entries[index].get("status") for index in selected]
    downloaded = sum(1 for status in statuses if status == "downloaded")
    skipped = sum(1 for status in statuses if status == "skipped")
    summary = f"Downloaded {downloaded}, skipped {skipped}, errors {errors}"
    not_selected = len(entries) - len(selected)
    if not_selected:
        summary += f", not selected {not_selected}"
    return summary


@queue.command("download")
@click.pass_context
@option_add_cover_and_metadata
@option_albumart_file_name_template
@option_allow_local_file_rename
@option_audio_file_name_template
@option_check_next_track
@option_create_download_manifest
@option_manifest_file
@option_number_retries_next_track
@option_only_tracks
@option_output_directory
@option_overwrite_existing_files
@option_replace_characters_in_file_names
@option_replace_characters_in_file_names_with
@option_with_albumart
def queue_download(
    ctx: click.Context,
    add_cover_and_metadata: bool,
    albumart_file_name_template: str,
    allow_local_file_rename: bool,
    audio_file_name_template: str,
    check_next_track: bool,
    create_download_manifest: bool,
    manifest_file: str,
    number_retries_next_track: int,
    only_tracks: set[int] | None,
    output_directory: str | None,
    overwrite_existing_files: bool,
    replace_characters_in_file_names: str,
    replace_characters_in_file_names_with: str,
    with_albumart: bool,
) -> None:
    """Download every track of the current queue.

    With -T/--only-tracks, only the tracks at the given queue positions are
    downloaded, leaving the other ones for a later run. The download manifest is
    written to --manifest-file, by default manifest.json inside the output
    directory. If the manifest file already exists, only the tracks not yet
    downloaded are retried.
    """
    host_configuration = ctx.obj["host_configuration"]
    rest_api_timeout = ctx.obj["rest_api_timeout"]
    mpd_timeout = ctx.obj["mpd_timeout"]
    verbose = ctx.obj["verbose"]
    machine_readable = ctx.obj["machine_readable"]
    position_starting_at_one = ctx.obj["position_starting_at_one"]

    if output_directory is None:
        raise click.UsageError(OUTPUT_DIRECTORY_REQUIRED_ERROR)

    debug(f"Connecting to {host_configuration.rest_base_url}...")

    try:
        client = create_client(host_configuration, rest_api_timeout)
        tracks = client.queue.tracks

        debug(f"Connecting to {host_configuration.rest_base_url}... done")
        debug("Successfully retrieved queue")

        if not tracks:
            info("The queue is empty, nothing to download")
            return

        # The selected positions follow the indexing of the displayed ones
        offset = 1 if position_starting_at_one else 0
        if only_tracks is None:
            selected = set(range(len(tracks)))
        else:
            selected = {
                position - offset
                for position in only_tracks
                if 0 <= position - offset < len(tracks)
            }
            if not selected:
                error("No track of the queue is selected")
                sys.exit(1)
            info(f"Downloading {len(selected)} of {len(tracks)} tracks")

        timestamp = datetime.now(UTC).strftime(OUTPUT_DIRECTORY_TIMESTAMP_FORMAT)
        run_directory = expand_timestamp_placeholder(output_directory, timestamp)
        log_path = expand_manifest_file(manifest_file, run_directory, timestamp)

        now = datetime.now(UTC).isoformat()
        if os.path.exists(log_path):
            existing = read_queue_log(log_path)
            if existing is None:
                error(f'Cannot read the manifest file "{log_path}"')
                sys.exit(1)
            if not manifest_matches_queue(existing["tracks"], tracks):
                error(
                    f'The manifest file "{log_path}" does not match the current queue'
                )
                sys.exit(1)
            info(f'Reading manifest file "{log_path}"')
            entries: list[dict[str, Any]] = existing["tracks"]
            for index, entry in enumerate(entries):
                # A track left out of this run keeps the status it already had
                if index not in selected or entry.get("status") == "downloaded":
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
            info(f'Creating manifest file "{log_path}"')
            entries = [
                {
                    "album": track.album,
                    "artist": track.artist,
                    "position": display_position(index, position_starting_at_one),
                    "status": "pending",
                    "title": track.title,
                    "track_number": track.tracknumber,
                    "volume_number": track.volume_number,
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

        if all(
            entries[index].get("status") in ("downloaded", "skipped") for index in selected
        ):
            if machine_readable:
                click.echo(json.dumps(log_path))
            else:
                for index in sorted(selected):
                    entry = entries[index]
                    info(
                        f"[{index + 1}/{len(entries)}] {entry['status']}: "
                        f"\"{entry.get('output_file_path')}\" (kept)"
                    )
                info(
                    f"{_download_summary(entries, selected, 0)}; "
                    f'manifest written to "{log_path}"'
                )
            return

        errors = 0
        previous_index: int | None = None
        previous_uri: str | None = None
        downloaded_covers: dict[str, str] = {}
        album_volumes = queue_album_volumes(tracks, replace_characters_in_file_names_with)
        client.stop()
        with VolumioMPDClient(host_configuration, mpd_timeout, LOGGER) as mpd_client:
            for index, entry in enumerate(entries):
                if index not in selected:
                    continue
                if entry.get("status") in ("downloaded", "skipped"):
                    info(
                        f"[{index + 1}/{len(entries)}] {entry['status']}: "
                        f"\"{entry.get('output_file_path')}\" (kept)"
                    )
                    continue
                destination: str | None = None
                try:
                    expect_same_uri = (
                        previous_index is not None
                        and tracks[index].uri == tracks[previous_index].uri
                    )
                    attempt = 0
                    while True:
                        client.play(tracks[index])
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
                        debug(
                            "Track metadata not yet updated, retrying "
                            f"({attempt}/{number_retries_next_track})"
                        )
                    entry["source_uri"] = uri
                    if not fresh:
                        status: str = "error"
                        detail: str | None = (
                            "track metadata still refer to another track after "
                            f"{number_retries_next_track} retries"
                        )
                    else:
                        previous_index = index
                        previous_uri = uri
                        album_volume = album_volumes[index]
                        tracknumber = tracks[index].tracknumber
                        # The values computed here are also recorded in the manifest
                        extra_state = {
                            "album_volume": album_volume,
                            "tracknumber": tracknumber,
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
                            album_volume=album_volume,
                            tracknumber=tracknumber,
                        )
                        if not filename:
                            status = "error"
                            detail = "cannot determine a file name for the download"
                        else:
                            if not allow_local_file_rename:
                                filename = preserve_local_file_name(filename, uri)
                            if is_local_file_uri(uri):
                                embed_tags = False
                                debug(
                                    "Not embedding the album art and the metadata, "
                                    "to preserve the file being copied"
                                )
                            else:
                                embed_tags = add_cover_and_metadata
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
                                embed_tags,
                                extra_state,
                            )
                            if status == "downloaded" and embed_tags:
                                embed_track_tags(
                                    destination,
                                    state,
                                    host_configuration,
                                    rest_api_timeout,
                                    position_starting_at_one,
                                    verbose,
                                    machine_readable,
                                    tracknumber,
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
                                    album_volume,
                                    tracknumber,
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
                outcome = detail if status == "error" else f'"{destination}"'
                info(f"[{index + 1}/{len(entries)}] {status}: {outcome}")

        # Leave the player stopped at the first track
        client.play(0)
        rest_api_sleep(ctx)
        client.stop()

        if machine_readable:
            click.echo(json.dumps(log_path))
        else:
            info(
                f"{_download_summary(entries, selected, errors)}; "
                f'manifest written to "{log_path}"'
            )
        if errors:
            sys.exit(1)

    except click.UsageError:
        # A bad --file-name-template should surface as a usage error, not be
        # swallowed by the generic handler below.
        raise
    except VolumioConnectionError as e:
        error(f"Connection error: {e}")
        sys.exit(1)
    except VolumioAPIError as e:
        error(f"API error: {e}")
        sys.exit(1)
    except Exception as e:  # pragma: no cover
        error(f"Unexpected error: {e}")
        sys.exit(1)


@queue.command()
@click.pass_context
@option_print_resulting_status
def clear(ctx: click.Context, print_resulting_status: bool) -> None:
    """Clear the playback queue."""
    execute_command(ctx, "clear", lambda c: c.clear())
    rest_api_sleep(ctx)
    debug(
        "Sending a stop as a workaround for a Volumio-side issue: without it, the host "
        "keeps reporting the cleared track as playing (consume-mode services, e.g. qobuz)"
    )
    execute_command(ctx, "stop", lambda c: c.stop())
    execute_conditionally(ctx, print_resulting_status, playback_status, expected_status="stop")


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


@queue.command()
@click.pass_context
@click.argument("uri", type=str)
@option_play
@option_position
@option_print_resulting_status
def replace(
    ctx: click.Context,
    uri: str,
    play: bool,
    position: int | None,
    print_resulting_status: bool,
) -> None:
    """Replace the queue with the content of URI, playing it unless --no-play.

    A URI comes from "collection browse" or "collection search". With -p/--position,
    the item at that position among those URI lists plays first (indexed according
    to --position-starting-at-one/--position-starting-at-zero); without, the first.
    """
    if position is not None and not play:
        raise click.UsageError(REPLACE_POSITION_ERROR)
    if play:
        minimum = 1 if ctx.obj["position_starting_at_one"] else 0
        if position is not None and position < minimum:
            raise click.UsageError(f"position must be {minimum} or greater, got {position}")
        index = position - minimum if position is not None else 0
        execute_command(ctx, "replace", lambda c: c.replace_queue_and_play(uri, index))
    else:
        execute_command(ctx, "clear", lambda c: c.clear())
        rest_api_sleep(ctx)
        execute_command(ctx, "add", lambda c: c.add_to_queue(uri))
    execute_conditionally(ctx, print_resulting_status, playback_status)


@main.group()
@click.pass_context
def system(ctx: click.Context) -> None:
    """Query Volumio system utilities."""
    pass


@system.command("execute")
@click.pass_context
@click.argument("command", type=str)
@option_format
@option_propagate_remote_exit_code
@option_yes
def system_execute(
    ctx: click.Context,
    command: str,
    output_format: str,
    propagate_remote_exit_code: bool,
    yes: bool,
) -> None:
    """Execute COMMAND on the Volumio host, printing what it returned.

    IMPORTANT: the command runs on the Volumio host as its SSH user and may damage
    it; it is executed only when -y/--yes is given."""
    host_configuration = ctx.obj["host_configuration"]

    if not yes:
        error(f'Refusing to execute the command without -y/--yes: "{command}"')
        sys.exit(1)

    try:
        result = execute_on_host(host_configuration, command)
    except VolumioSSHError as e:
        error(str(e))
        sys.exit(1)

    render_payload(
        ctx,
        {
            "command": result.command,
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
        },
        output_format,
        heading="Remote Command",
    )

    if propagate_remote_exit_code:
        sys.exit(result.exit_code)


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
    data = fetch_or_exit(ctx, lambda c: c.system_version.raw)
    render_payload(ctx, data, output_format, heading="Volumio System Version")


@system.command("info")
@click.pass_context
@option_format
def system_info(ctx: click.Context, output_format: str) -> None:
    """Print the system information."""
    data = fetch_or_exit(ctx, lambda c: c.system_info.raw)
    render_payload(ctx, data, output_format, heading="Volumio System Info")


@main.group()
@click.pass_context
def collection(ctx: click.Context) -> None:
    """Query the music collection managed by Volumio."""
    pass


@collection.command("browse")
@click.pass_context
@click.argument("uri", required=False, default=None, type=str)
@option_albums_only
@option_artists_only
@option_best_result_only
@option_format_table
@option_limit
@option_offset
@option_playlists_only
@option_print_uri_toggle
@option_result_kinds
@option_tracks_only
def collection_browse(
    ctx: click.Context,
    uri: str | None,
    albums_only: bool,
    artists_only: bool,
    best_result_only: bool,
    output_format: str,
    limit: int | None,
    offset: int | None,
    playlists_only: bool,
    print_uri: bool,
    result_kinds: set[SearchResultItemKind] | None,
    tracks_only: bool,
) -> None:
    """Browse the content that URI lists in the collection of the Volumio host.

    Without URI, the root of the collection is listed: the starting points of the
    sources currently enabled. The URIs to descend into come from the listings
    themselves, printed unless --no-print-uri is given, and from the -u/--print-uri
    option of "collection search". The -o/--offset skip is applied by the host to
    each list, before the kind options act, and not at the root."""
    machine_readable = ctx.obj["machine_readable"]
    if best_result_only and limit is not None:
        raise click.UsageError(SEARCH_LIMIT_ERROR)
    asked = [
        kinds
        for kinds, wanted in (
            (result_kinds or set(), result_kinds is not None),
            ({SearchResultItemKind.ALBUM}, albums_only),
            ({SearchResultItemKind.ARTIST}, artists_only),
            ({SearchResultItemKind.PLAYLIST}, playlists_only),
            ({SearchResultItemKind.TRACK}, tracks_only),
        )
        if wanted
    ]
    if len(asked) > 1:
        raise click.UsageError(BROWSE_KINDS_ERROR)

    results = fetch_or_exit(ctx, lambda c: c.browse(uri, offset))

    if asked:
        results = results.filtered(kinds=asked[0])

    kept = 1 if best_result_only else limit
    if kept is not None:
        results = results.limited(kept)

    if machine_readable or output_format == "raw":
        # The raw format is the payload of the host, as it answered it
        output = json.dumps(results.raw)
    else:
        info = results.info.model_dump(by_alias=True) if results.info else None
        lists = [result_list.model_dump(by_alias=True) for result_list in results.lists]
        if output_format == "table":
            output = format_browse_results_as_table(lists, info, print_uri)
        else:
            navigation = {"info": info, "lists": lists, "prev": results.prev}
            if output_format == "json":
                output = json.dumps(navigation, indent=2)
            else:  # pretty
                output = json.dumps(navigation, indent=4, sort_keys=True, ensure_ascii=False)

    echo_data(ctx, output)


@collection.command("search")
@click.pass_context
@click.argument("query", required=False, default=None, type=str)
@option_album
@option_albums_only
@option_artist
@option_artists_only
@option_best_result_only
@option_format_table
@option_limit
@option_offset
@option_playlist
@option_playlists_only
@option_print_uri
@option_result_kinds
@option_service
@option_track
@option_tracks_only
def collection_search(
    ctx: click.Context,
    query: str | None,
    album: str | None,
    albums_only: bool,
    artist: str | None,
    artists_only: bool,
    best_result_only: bool,
    output_format: str,
    limit: int | None,
    offset: int | None,
    playlist: str | None,
    playlists_only: bool,
    print_uri: bool,
    result_kinds: set[SearchResultItemKind] | None,
    service: str | None,
    track: str | None,
    tracks_only: bool,
) -> None:
    """Search QUERY in the Volumio sources currently enabled.

    Without QUERY, the text of the --album, --artist, --playlist, and --track options
    is searched for; --album, --artist, and --track also keep the matching results
    only. With --result-kinds, or one of --albums-only, --artists-only, --playlist,
    --playlists-only, and --tracks-only, the results of the kinds asked for are all
    kept, and the other options only say what to search for."""
    machine_readable = ctx.obj["machine_readable"]
    terms = [term for term in (artist, album, track, playlist) if term]
    searched = query or " ".join(terms)
    if not searched:
        raise click.UsageError(SEARCH_ARGUMENT_ERROR)
    if best_result_only and limit is not None:
        raise click.UsageError(SEARCH_LIMIT_ERROR)
    asked = [
        kinds
        for kinds, wanted in (
            (result_kinds, result_kinds is not None),
            ({SearchResultItemKind.ALBUM}, albums_only),
            ({SearchResultItemKind.ARTIST}, artists_only),
            ({SearchResultItemKind.PLAYLIST}, playlists_only or playlist is not None),
            ({SearchResultItemKind.TRACK}, tracks_only),
        )
        if wanted
    ]
    if len(asked) > 1:
        raise click.UsageError(SEARCH_KINDS_ERROR)

    results = fetch_or_exit(ctx, lambda c: c.search(searched))

    if asked:
        # The kinds are asked for, so the other options only feed the query, and the
        # results of those kinds are all kept: a source answers a query with what it
        # finds related to it, whose titles rarely carry the query
        results = results.filtered(service=service, kinds=asked[0])
    else:
        results = results.filtered(service=service, artist=artist, album=album, track=track)

    if offset:
        results = results.offset(offset)

    kept = 1 if best_result_only else limit
    if kept is not None:
        results = results.limited(kept)

    if machine_readable or output_format == "raw":
        # The raw format is the payload of the host, as it answered it
        output = json.dumps(results.raw)
    else:
        lists = [result_list.model_dump(by_alias=True) for result_list in results.lists]
        if output_format == "json":
            output = json.dumps(lists, indent=2)
        elif output_format == "table":
            output = format_search_results_as_table(lists, print_uri)
        else:  # pretty
            output = json.dumps(lists, indent=4, sort_keys=True, ensure_ascii=False)

    echo_data(ctx, output)


@collection.command("statistics")
@click.pass_context
@option_format
def collection_statistics(ctx: click.Context, output_format: str) -> None:
    """Print the statistics of the music collection."""
    data = fetch_or_exit(ctx, lambda c: c.collection_statistics.raw)
    render_payload(ctx, data, output_format, heading="Collection Statistics")


@main.group()
@click.pass_context
def multiroom(ctx: click.Context) -> None:
    """Query the multiroom state."""
    pass


@multiroom.command("zones")
@click.pass_context
@option_fields
@option_format
def multiroom_zones(ctx: click.Context, fields: str, output_format: str) -> None:
    """Print the multiroom zones seen by the Volumio instance."""
    data = fetch_or_exit(ctx, lambda c: c.zones.raw)

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

    echo_data(ctx, output)


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
    names = fetch_or_exit(ctx, lambda c: c.playlists.names)

    if output_format == "raw":
        output = json.dumps(names)
    elif output_format == "json":
        output = json.dumps(names, indent=2)
    elif output_format == "table":
        output = format_names_as_table(names, "Volumio Playlists")
    else:  # pretty
        output = json.dumps(names, indent=4, ensure_ascii=False)

    echo_data(ctx, output)


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
        names = fetch_or_exit(ctx, lambda c: c.playlists.names)
        if name not in names:
            error(f'Playlist not found: "{name}"')
            error("Available playlists:")
            for available in names:
                error(f'  "{available}"')
            if not names:
                error("  (none)")
            sys.exit(1)

    execute_command(ctx, f'playplaylist "{name}"', lambda c: c.play_playlist(name))
    execute_conditionally(ctx, print_resulting_status, playback_status)


@playlist.command("download")
@click.pass_context
@click.argument("name", type=str)
@option_add_cover_and_metadata
@option_albumart_file_name_template
@option_allow_local_file_rename
@option_audio_file_name_template
@option_check_next_track
@option_check_playlist_name
@option_create_download_manifest
@option_manifest_file
@option_number_retries_next_track
@option_only_tracks
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
    allow_local_file_rename: bool,
    audio_file_name_template: str,
    check_next_track: bool,
    check_playlist_name: bool,
    create_download_manifest: bool,
    manifest_file: str,
    number_retries_next_track: int,
    only_tracks: set[int] | None,
    output_directory: str | None,
    overwrite_existing_files: bool,
    print_resulting_status: bool,
    replace_characters_in_file_names: str,
    replace_characters_in_file_names_with: str,
    with_albumart: bool,
) -> None:
    """Download every track of the playlist specified by NAME."""

    if check_playlist_name:
        names = fetch_or_exit(ctx, lambda c: c.playlists.names)
        if name not in names:
            error(f'Playlist not found: "{name}"')
            error("Available playlists:")
            for available in names:
                error(f'  "{available}"')
            if not names:
                error("  (none)")
            sys.exit(1)

    host_configuration = ctx.obj["host_configuration"]
    rest_api_timeout = ctx.obj["rest_api_timeout"]

    try:
        client = create_client(host_configuration, rest_api_timeout)
        debug("Clearing the queue...")
        client.clear()
        debug("Clearing the queue... done")
        rest_api_sleep(ctx)
        debug(f'Playing playlist "{name}"...')
        client.play_playlist(name)
        debug(f'Playing playlist "{name}"... done')
        rest_api_sleep(ctx)
    except VolumioConnectionError as e:
        error(f"Connection error: {e}")
        sys.exit(1)
    except VolumioAPIError as e:
        error(f"API error: {e}")
        sys.exit(1)

    ctx.invoke(
        queue_download,
        add_cover_and_metadata=add_cover_and_metadata,
        albumart_file_name_template=albumart_file_name_template,
        allow_local_file_rename=allow_local_file_rename,
        audio_file_name_template=audio_file_name_template,
        check_next_track=check_next_track,
        create_download_manifest=create_download_manifest,
        manifest_file=manifest_file,
        number_retries_next_track=number_retries_next_track,
        only_tracks=only_tracks,
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


def _echo_notification(
    ctx: click.Context, notification: PushNotification, output_format: str
) -> None:
    """Print a received notification per the format option.

    Args:
        ctx: Click context object containing shared options
        notification: The notification received
        output_format: The output format ("json", "pretty", "raw", or "table")
    """
    if ctx.obj["machine_readable"] or output_format == "raw":
        output = json.dumps(notification.raw)
    elif output_format == "json":
        output = json.dumps(notification.raw, indent=2)
    elif output_format == "table":
        # The microseconds of the format are trimmed to milliseconds
        received = f"{datetime.now(UTC).strftime(NOTIFICATION_TIMESTAMP_FORMAT)[:-3]}Z"
        output = format_notification_as_line(notification.item, notification.data, received)
    else:  # pretty
        output = json.dumps(notification.raw, indent=4, sort_keys=True, ensure_ascii=False)

    click.echo(output)


def _exit_on_notification_failure(
    ctx: click.Context, response: SuccessResponse, action: str, url: str
) -> None:
    """Print what the Volumio host reported for a refused notification URL, and exit 1.

    Args:
        ctx: Click context object containing shared options
        response: The response of the Volumio API
        action: The action the host refused (e.g., "register")
        url: The URL the action was requested for
    """
    if response.is_success:
        return

    detail = f" ({response.error})" if response.error else ""
    error(f"The Volumio host did not {action} the URL: {url}{detail}")
    sys.exit(1)


def _listen_and_print(
    ctx: click.Context,
    port: int,
    endpoint: str,
    url: str,
    count: int | None,
    timeout: float | None,
    idle_timeout: float | None,
    output_format: str,
) -> None:
    """Serve the endpoint, printing the notifications until a limit or an interruption.

    Args:
        ctx: Click context object containing shared options
        port: The port to listen on
        endpoint: The path to serve
        url: The URL the Volumio host pushes to
        count: Number of notifications to print before returning, or None
        timeout: Seconds to listen for in total, or None
        idle_timeout: Seconds to wait for each notification, or None
        output_format: The output format ("json", "pretty", "raw", or "table")
    """
    listener = NotificationListener(port=port, endpoint=endpoint)

    try:
        listener.start()
    except OSError as e:
        error(f"Cannot listen on port {port}: {e}")
        sys.exit(1)

    info(f"Listening on port {port} for the notifications sent to {url}")
    info(format_termination_conditions(count, timeout, idle_timeout))

    received = 0
    try:
        for notification in listener.listen(count, timeout, idle_timeout):
            _echo_notification(ctx, notification, output_format)
            received += 1
    except KeyboardInterrupt:
        return
    finally:
        listener.stop()

    if count is not None and received >= count:
        return

    if listener.idle_timed_out and idle_timeout is not None:
        message = f"Timed out after {idle_timeout:g} seconds without notifications"
    elif timeout is not None:
        message = f"Timed out after {timeout:g} seconds"
    else:
        return

    info(message)
    if count is not None:
        sys.exit(1)


def _compose_notification_url(ctx: click.Context, port: int, endpoint: str) -> str:
    """Return the URL of the local listener, as reachable by the Volumio host.

    Args:
        ctx: Click context object containing shared options
        port: The port the local listener binds to
        endpoint: The path the local listener serves

    Returns:
        The composed URL

    Raises:
        click.UsageError: If the endpoint does not start with a slash
    """
    if not endpoint.startswith("/"):
        raise click.UsageError(NOTIFICATION_ENDPOINT_ERROR)

    return fetch_or_exit(ctx, lambda c: receiver_url(c.host_configuration, port, endpoint))


@main.group()
@click.pass_context
def notification(ctx: click.Context) -> None:
    """Manage the URLs receiving the push notifications."""
    pass


@notification.command("list")
@click.pass_context
@option_format
def notification_list(ctx: click.Context, output_format: str) -> None:
    """List the URLs registered to receive the push notifications."""
    urls = fetch_or_exit(ctx, lambda c: c.notifications.urls)

    if output_format == "raw":
        output = json.dumps(urls)
    elif output_format == "json":
        output = json.dumps(urls, indent=2)
    elif output_format == "table":
        output = format_names_as_table(urls, "Volumio Notification URLs")
    else:  # pretty
        output = json.dumps(urls, indent=4, ensure_ascii=False)

    echo_data(ctx, output)


@notification.command("listen")
@click.pass_context
@option_count
@option_endpoint
@option_format
@option_idle_timeout
@option_port
@option_register_url
@option_register_url_full
@option_timeout
@option_unregister_url_on_exit
def notification_listen(
    ctx: click.Context,
    count: int | None,
    endpoint: str,
    output_format: str,
    idle_timeout: float | None,
    port: int,
    register_url: bool,
    register_url_full: str | None,
    timeout: float | None,
    unregister_url_on_exit: bool,
) -> None:
    """Print the notifications the Volumio host pushes to this machine.

    The URL the host pushes to must be registered: with --register-url it is
    registered if missing, and unregistered again on exit unless
    --no-unregister-url-on-exit is given.

    The command keeps listening until it is interrupted with Ctrl-C, or until one
    of -n/--count, --idle-timeout, and --timeout is reached."""
    url = register_url_full or _compose_notification_url(ctx, port, endpoint)

    registered = fetch_or_exit(ctx, lambda c: url in c.notifications)
    if not registered and not register_url:
        error(
            f"The URL is not registered on the Volumio host: {url} "
            f"(use --register-url to register it)"
        )
        sys.exit(1)

    if not registered:
        response = fetch_or_exit(ctx, lambda c: c.register_notification(url))
        _exit_on_notification_failure(ctx, response, "register", url)
        info(f"Registered notification URL: {url}")

    try:
        _listen_and_print(
            ctx, port, endpoint, url, count, timeout, idle_timeout, output_format
        )
    finally:
        if not registered and unregister_url_on_exit:
            response = fetch_or_exit(ctx, lambda c: c.unregister_notification(url))
            _exit_on_notification_failure(ctx, response, "unregister", url)
            info(f"Unregistered notification URL: {url}")


@notification.command("register")
@click.pass_context
@click.argument("url", required=False, default=None, type=str)
@option_autocompose_url
@option_endpoint
@option_port
def notification_register(
    ctx: click.Context,
    url: str | None,
    autocompose_url: bool,
    endpoint: str,
    port: int,
) -> None:
    """Register URL to receive the push notifications.

    With -A/--autocompose-url, the URL of the local listener is registered."""
    if autocompose_url:
        if url is not None:
            raise click.UsageError(MUTUALLY_EXCLUSIVE_REGISTER_ERROR)
        target = _compose_notification_url(ctx, port, endpoint)
    elif url is None:
        raise click.UsageError(REGISTER_ARGUMENT_ERROR)
    else:
        target = url

    response = fetch_or_exit(ctx, lambda c: c.register_notification(target))
    _exit_on_notification_failure(ctx, response, "register", target)

    info(f"Registered notification URL: {target}")


@notification.command("unregister")
@click.pass_context
@click.argument("url", required=False, default=None, type=str)
@option_all_notifications
@option_autocompose_url
@option_endpoint
@option_port
def notification_unregister(
    ctx: click.Context,
    url: str | None,
    all_notifications: bool,
    autocompose_url: bool,
    endpoint: str,
    port: int,
) -> None:
    """Stop pushing the notifications to URL.

    With -A/--autocompose-url, the URL of the local listener is unregistered;
    with -a/--all, every registered URL is."""
    ways = [all_notifications, autocompose_url, url is not None]
    if sum(ways) > 1:
        raise click.UsageError(MUTUALLY_EXCLUSIVE_UNREGISTER_ERROR)
    if not any(ways):
        raise click.UsageError(UNREGISTER_ARGUMENT_ERROR)

    if url is not None:
        targets = [url]
    elif autocompose_url:
        targets = [_compose_notification_url(ctx, port, endpoint)]
    else:
        targets = fetch_or_exit(ctx, lambda c: c.notifications.urls)

    if not targets:
        info("No notification URL is registered, nothing to unregister")
        return

    outcomes = fetch_or_exit(
        ctx, lambda c: [(target, c.unregister_notification(target)) for target in targets]
    )

    for target, response in outcomes:
        _exit_on_notification_failure(ctx, response, "unregister", target)
        info(f"Unregistered notification URL: {target}")


@main.group("scp")
@click.pass_context
def scp(ctx: click.Context) -> None:
    """Copy files and directories from and to the Volumio host.

    IMPORTANT: copying to the Volumio host may damage its integrity;
    please proceed with caution."""
    pass


@scp.command("get")
@click.pass_context
@click.argument("remote_path", type=str)
@click.argument("local_path", type=str)
@option_recursive
def scp_get(ctx: click.Context, remote_path: str, local_path: str, recursive: bool) -> None:
    """Copy REMOTE_PATH of the Volumio host to LOCAL_PATH."""
    host_configuration = ctx.obj["host_configuration"]

    try:
        copy_from_host(host_configuration, remote_path, local_path, recursive=recursive)
    except VolumioSCPError as e:
        error(str(e))
        sys.exit(1)

    info(f'Copied "{remote_path}" from the Volumio host to "{local_path}"')


@scp.command("put")
@click.pass_context
@click.argument("local_path", type=str)
@click.argument("remote_path", type=str)
@option_recursive
@option_yes
def scp_put(
    ctx: click.Context, local_path: str, remote_path: str, recursive: bool, yes: bool
) -> None:
    """Copy LOCAL_PATH to REMOTE_PATH of the Volumio host.

    IMPORTANT: this command writes to the Volumio host and may damage its
    integrity; the copy is made only when -y/--yes is given."""
    host_configuration = ctx.obj["host_configuration"]

    if not yes:
        error(f'Refusing to copy to the Volumio host without -y/--yes: "{remote_path}"')
        sys.exit(1)

    try:
        copy_to_host(host_configuration, local_path, remote_path, recursive=recursive)
    except VolumioSCPError as e:
        error(str(e))
        sys.exit(1)

    info(f'Copied "{local_path}" to "{remote_path}" on the Volumio host')


# "info" is a top-level synonym for "system info"
main.add_command(system_info, name="info")


if __name__ == "__main__":  # pragma: no cover
    main()
