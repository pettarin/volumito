"""Click-dependent helpers for the volumito CLI.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

import json
import os
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, get_args

import click
import requests

from volumito import __version__
from volumito.cli.configuration import (
    build_click_default_map,
    load_configuration,
    resolve_configuration_path,
)
from volumito.cli.constants import (
    FILE_WRITE_CHUNK_SIZE,
    OUTPUT_FIELDS_SHORT,
    OUTPUT_FORMATS,
)
from volumito.cli.metadata import (
    UnsupportedAudioFormatError,
    embed_metadata_and_cover,
)
from volumito.cli.pure_helpers import (
    display_position,
    extract_filename_from_uri,
    filter_fields,
    format_as_json,
    format_as_pretty,
    format_as_table,
    format_duration,
    parse_time_to_seconds,
    resolve_albumart_uri,
    resolve_output_fields,
)
from volumito.clients import (
    Scheme,
    VolumioAPIError,
    VolumioConnectionError,
    VolumioHostConfiguration,
    VolumioRESTAPIClient,
)


class OnOffParamType(click.ParamType):
    """Click parameter type for an on/off toggle value.

    Accepts "on"/"true"/"yes"/"1" (True) or "off"/"false"/"no"/"0" (False),
    lowercase only; anything else is a usage error.
    """

    name = "on/off"

    # Boolean value -> accepted spellings (lowercase only)
    ALIASES = {
        True: ["on", "true", "yes", "1"],
        False: ["off", "false", "no", "0"],
    }

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


class SchemeParamType(click.ParamType):
    """Click parameter type for the URL scheme.

    Accepts the (lowercase) values of the ``Scheme`` alias, currently "http" and
    "https"; anything else is a usage error.
    """

    name = "scheme"

    # Accepted schemes, derived from the Scheme type alias (the single source)
    SCHEMES = get_args(Scheme)

    def convert(
        self,
        value: object,
        param: click.Parameter | None,
        ctx: click.Context | None,
    ) -> str:
        text = str(value)
        if text in self.SCHEMES:
            return text
        accepted = ", ".join(self.SCHEMES)
        self.fail(f"{text!r} must be one of {accepted}", param, ctx)

    def get_metavar(self, param: click.Parameter, ctx: click.Context) -> str:
        return f"[{'|'.join(self.SCHEMES)}]"


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
                "volumito_version": __version__,
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
        embed_metadata_and_cover(
            destination,
            title=state.get("title"),
            artist=state.get("artist"),
            album=state.get("album"),
            albumartist=state.get("albumartist"),
            track_number=track_number,
            cover=cover,
        )
    except UnsupportedAudioFormatError:
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


def execute_conditionally(ctx: click.Context, enabled: bool, command: click.Command) -> None:
    """When enabled, wait the configured delay and invoke the given command.

    Args:
        ctx: Click context object (its ``obj`` is inherited by the invoked command)
        enabled: Whether to invoke the command
        command: The Click command to invoke
    """
    if enabled:
        rest_api_sleep(ctx)
        ctx.invoke(command)


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


def option_add_cover_and_metadata(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``--add-cover-and-metadata`` option to the ``track audio`` subcommand."""
    return click.option(
        "--add-cover-and-metadata/--no-add-cover-and-metadata",
        default=True,
        show_default=True,
        help="Embed track metadata and cover art into the downloaded file "
        "(FLAC, MP3, MP4/M4A)",
    )(func)


def option_create_download_manifest(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``--create-download-manifest`` option to a track download subcommand."""
    return click.option(
        "--create-download-manifest/--no-create-download-manifest",
        default=True,
        show_default=True,
        help="Write a JSON manifest next to the downloaded file (e.g. out.flac.json)",
    )(func)


def option_fields(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``-L``/``--fields`` option to a display subcommand."""
    return click.option(
        "--fields",
        "-L",
        type=str,
        default=OUTPUT_FIELDS_SHORT,
        show_default=True,
        help="Fields to display: ALL, SHORT, or a comma-separated list of field names",
    )(func)


def option_file_name_template(func: Callable[..., None]) -> Callable[..., None]:
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


def option_format(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``-F``/``--format`` option to a display subcommand."""
    return click.option(
        "--format",
        "-F",
        "output_format",
        type=click.Choice(OUTPUT_FORMATS, case_sensitive=True),
        default="pretty",
        show_default=True,
        help="Output format",
    )(func)


def option_output_directory(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``-d``/``--output-directory`` option to a track download subcommand."""
    return click.option(
        "-d",
        "--output-directory",
        type=str,
        default=None,
        help="Download into this directory, using the file name from the template "
        "(mutually exclusive with -o)",
    )(func)


def option_output_file(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``-o``/``--output-file`` option to a track download subcommand."""
    return click.option(
        "-o",
        "--output-file",
        type=str,
        default=None,
        help="Download to this exact file path (mutually exclusive with -d)",
    )(func)


def option_overwrite_existing_files(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``--overwrite-existing-files`` option to a download or create subcommand."""
    return click.option(
        "--overwrite-existing-files/--no-overwrite-existing-files",
        default=False,
        show_default=True,
        help="Overwrite the destination file if it already exists",
    )(func)


def option_print_resulting_status(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``-r``/``--print-resulting-status`` option to a playback subcommand."""
    return click.option(
        "--print-resulting-status/--no-print-resulting-status",
        "-r",
        default=True,
        show_default=True,
        help="After the command, wait 1 second and print the resulting playback status",
    )(func)


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
        filtered_state = filter_fields(state, fields, short_fields)

        if output_format == "table":
            # Preserve the requested field order (and labels) in the table; None => all
            field_order = resolve_output_fields(fields, short_fields)
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


def rest_api_sleep(ctx: click.Context) -> None:
    """Sleep for the configured delay before making the next REST API call.

    Args:
        ctx: Click context object holding the shared options
    """
    time.sleep(ctx.obj["rest_api_sleep_before_next_call"])


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
