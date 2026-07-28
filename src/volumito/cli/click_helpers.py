"""Click-dependent helpers for the volumito CLI.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

import json
import os
import shutil
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from string import Formatter
from typing import Any, get_args

import click
import requests
from packaging.version import InvalidVersion, Version

from volumito import __version__
from volumito.cli.configuration import (
    build_click_default_map,
    load_configuration,
    resolve_configuration_path,
)
from volumito.cli.constants import (
    DEFAULT_NUMBER_RETRIES_NEXT_TRACK,
    DEFAULT_REPLACE_CHARACTERS_IN_FILE_NAMES,
    DEFAULT_REPLACE_CHARACTERS_IN_FILE_NAMES_WITH,
    DEFAULT_STORY_ARGUMENT_TYPE,
    FILE_WRITE_CHUNK_SIZE,
    MUTUALLY_EXCLUSIVE_CONFIGURATION_ERROR,
    MUTUALLY_EXCLUSIVE_CURRENT_TRACK_ERROR,
    OUTPUT_FIELDS_SHORT,
    OUTPUT_FORMATS,
    SHORT_FORMAT_FIELDS_STORY,
    STORY_ARGUMENT_TYPES,
    STORY_ARTIST_ALBUM_ARGUMENTS_ERROR,
    STORY_ARTIST_ARGUMENT_ERROR,
    STORY_CURRENT_TRACK_METADATA_ERROR,
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
    sanitize_filename_component,
    story_query_reference,
)
from volumito.clients import (
    Album,
    Artist,
    Scheme,
    VolumioAPIError,
    VolumioConnectionError,
    VolumioHostConfiguration,
    VolumioRESTAPIClient,
)
from volumito.clients.entities import MusicEntity


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


class VolumioVersionParamType(click.ParamType):
    """Click parameter type for a Volumio version string.

    Parses the version with :class:`packaging.version.Version` and returns its integer
    major version (e.g. "4" -> 4, "3.123" -> 3). Anything that is not a valid version
    is a usage error.
    """

    name = "volumio_version"

    def convert(
        self,
        value: object,
        param: click.Parameter | None,
        ctx: click.Context | None,
    ) -> int:
        text = str(value)
        try:
            return Version(text).major
        except InvalidVersion:
            self.fail(
                f"{text!r} is not a valid Volumio version (e.g. 4, 3, 4.119, 3.123)",
                param,
                ctx,
            )


def _materialize_albumart(
    albumart_uri: str,
    cover_path: str,
    overwrite: bool,
    timeout: float,
    machine_readable: bool,
    downloaded_covers: dict[str, str],
) -> str | None:
    """Place the album art at ``cover_path``, downloading or copying it.

    The first materialization of ``albumart_uri`` downloads it (recording the file
    in ``downloaded_covers``); further destinations are copied locally from that
    file. An existing destination is reused unless ``overwrite`` is true; a failure
    is reported as a warning.

    Args:
        albumart_uri: The album-art URI
        cover_path: The destination file path
        overwrite: Whether to overwrite an existing cover file
        timeout: Request timeout in seconds
        machine_readable: Whether machine-readable mode is active (suppresses messages)
        downloaded_covers: Cache of album-art URIs already downloaded, updated in place

    Returns:
        The cover file path, or None if the download or the copy failed
    """
    if downloaded_covers.get(albumart_uri) == cover_path:
        return cover_path
    if not overwrite and os.path.exists(cover_path):
        downloaded_covers.setdefault(albumart_uri, cover_path)
        return cover_path
    try:
        parent = os.path.dirname(cover_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        cached = downloaded_covers.get(albumart_uri)
        if cached is not None and os.path.exists(cached):
            shutil.copyfile(cached, cover_path)
        else:
            fetch_uri_to_file(albumart_uri, cover_path, timeout)
    except (requests.exceptions.RequestException, OSError) as e:
        if not machine_readable:
            click.echo(f"\nWarning: cannot download album art to {cover_path} ({e})", err=True)
        return None
    downloaded_covers.setdefault(albumart_uri, cover_path)
    return cover_path


def _story_current_track_values(ctx: click.Context, keys: tuple[str, ...]) -> tuple[str, ...]:
    """Fetch the current track's values for the given state keys, exiting on failure.

    Args:
        ctx: Click context object containing shared options
        keys: The state keys to read (e.g. ("artist", "album"))

    Returns:
        The (stripped) state values, one per key; a missing, non-string, or blank
        value is an error (exit code 1, message suppressed in machine-readable mode)
    """
    state = fetch_state_or_exit(ctx)
    values = []
    for key in keys:
        value = state.get(key)
        if not isinstance(value, str) or not value.strip():
            if not ctx.obj["machine_readable"]:
                click.echo(f"Error: {STORY_CURRENT_TRACK_METADATA_ERROR}", err=True)
            sys.exit(1)
        values.append(value.strip())
    return tuple(values)


def configuration_file_callback(
    ctx: click.Context, param: click.Parameter, value: str | None
) -> str | None:
    """Load the configuration file (if any) and use its values as option defaults.

    Runs eagerly, before the other options resolve, so the loaded values populate
    ``ctx.default_map`` and are only used where the user did not pass an explicit flag.
    With ``--ignore-configuration-file`` the lookup is skipped entirely (an explicit
    ``-c`` combined with it is a usage error; both eager callbacks perform the check,
    since Click processes eager parameters in command-line order).
    """
    ctx.ensure_object(dict)
    ctx.obj["configuration_file_option"] = value
    if ctx.obj.get("ignore_configuration_file"):
        if value is not None:
            raise click.UsageError(MUTUALLY_EXCLUSIVE_CONFIGURATION_ERROR)
        ctx.obj["configuration_file"] = None
        return value
    path = resolve_configuration_path(value)
    if path is not None:
        config = load_configuration(path)
        ctx.default_map = {**(ctx.default_map or {}), **build_click_default_map(config)}
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


def download_queue_albumart(
    state: dict[str, Any],
    run_directory: str,
    albumart_file_name_template: str,
    host_configuration: VolumioHostConfiguration,
    timeout: float,
    overwrite: bool,
    machine_readable: bool,
    downloaded_covers: dict[str, str],
    position_starting_at_one: bool,
    replace_characters_in_file_names: str,
    replace_characters_in_file_names_with: str,
) -> str | None:
    """Download the current track's album art into the run directory.

    The cover is saved under the name rendered from ``albumart_file_name_template``
    (relative to ``run_directory``; the template may lay covers out in
    subdirectories, which are created as needed but must stay inside the run
    directory). Each distinct album-art URI is downloaded at most once per run
    (``downloaded_covers`` maps the URIs already downloaded to their file paths);
    when the same URI renders to further destinations (e.g. one per volume of a
    multi-volume album), the already-downloaded file is copied there locally. For
    a multi-volume track, the cover is also placed at the path rendered with the
    album-only ``album_volume`` component (e.g. ``Elegia/cover.jpg`` next to
    ``Elegia/1/cover.jpg`` and ``Elegia/2/cover.jpg``). An existing cover file is
    reused unless ``overwrite`` is true. A download failure is reported as a
    warning and otherwise ignored.

    Args:
        state: The current player state dictionary (source of the album-art URI)
        run_directory: The per-run download directory
        albumart_file_name_template: Template for the cover file name
        host_configuration: The Volumio host configuration (to resolve relative URIs)
        timeout: Request timeout in seconds
        overwrite: Whether to overwrite an existing cover file
        machine_readable: Whether machine-readable mode is active (suppresses messages)
        downloaded_covers: Cache of album-art URIs already handled, updated in place
        position_starting_at_one: Whether the template ``position`` key starts at one
        replace_characters_in_file_names: Characters replaced in the rendered file name
        replace_characters_in_file_names_with: Replacement for the replaced characters

    Returns:
        The cover file path, or None if the track has no album art or the download failed

    Raises:
        click.UsageError: If the template is invalid or renders to a path escaping
            the run directory
    """
    albumart_uri = resolve_albumart_uri(state, host_configuration)
    if albumart_uri is None:
        return None

    def resolve_cover_path(cover_state: dict[str, Any]) -> str | None:
        filename = render_output_filename(
            albumart_file_name_template,
            albumart_uri,
            cover_state,
            "jpg",
            position_starting_at_one,
            replace_characters_in_file_names,
            replace_characters_in_file_names_with,
            allow_subdirectories=True,
            option_label="--albumart-file-name-template",
        )
        if not filename:
            return None
        path = os.path.join(run_directory, filename)
        base = os.path.realpath(run_directory)
        if os.path.commonpath([base, os.path.realpath(path)]) != base:
            raise click.UsageError(
                f"Invalid --albumart-file-name-template {albumart_file_name_template!r}: "
                f"the file name {filename!r} escapes the output directory"
            )
        return path

    cover_path = resolve_cover_path(state)
    if cover_path is None:
        if not machine_readable:
            click.echo("\nWarning: cannot determine a file name for the album art", err=True)
        return None
    result = _materialize_albumart(
        albumart_uri, cover_path, overwrite, timeout, machine_readable, downloaded_covers
    )

    # For a multi-volume track, also place the cover in the album directory itself
    album_volume = str(state.get("album_volume") or "")
    if result is not None and "/" in album_volume:
        album_state = {**state, "album_volume": album_volume.split("/", 1)[0]}
        album_cover_path = resolve_cover_path(album_state)
        if album_cover_path is not None and album_cover_path != cover_path:
            _materialize_albumart(
                albumart_uri,
                album_cover_path,
                overwrite,
                timeout,
                machine_readable,
                downloaded_covers,
            )
    return result


def download_queue_track(
    uri: str,
    destination: str,
    overwrite: bool,
    timeout: float,
    create_manifest: bool,
    state: dict[str, Any],
    host_configuration: VolumioHostConfiguration,
    add_cover_and_metadata: bool,
) -> tuple[str, str | None]:
    """Download one queue track to ``destination``, reporting the outcome.

    Unlike :func:`download_uri_to`, this never exits: the caller (the ``queue
    download`` loop) records the outcome and moves on to the next track. Any
    missing parent directories of ``destination`` are created, so the file-name
    template can lay tracks out in subdirectories.

    Args:
        uri: The URI to download
        destination: The destination file path
        overwrite: Whether to overwrite the destination file if it already exists
        timeout: Request timeout in seconds
        create_manifest: Whether to write a ``<destination>.json`` download manifest
        state: The current player state dictionary (recorded in the manifest)
        host_configuration: The Volumio host configuration (recorded in the manifest)
        add_cover_and_metadata: Recorded in the manifest

    Returns:
        A ``(status, error)`` pair: ``("skipped", None)`` if the destination exists
        and ``overwrite`` is false, ``("downloaded", None)`` on success, or
        ``("error", message)`` on a download or write failure
    """
    if not overwrite and os.path.exists(destination):
        return "skipped", None
    try:
        parent = os.path.dirname(destination)
        if parent:
            os.makedirs(parent, exist_ok=True)
        fetch_uri_to_file(uri, destination, timeout)
        if create_manifest:
            write_download_manifest(
                destination, uri, state, host_configuration, "track", "audio",
                add_cover_and_metadata,
            )
    except (requests.exceptions.RequestException, OSError) as e:
        return "error", str(e)
    return "downloaded", None


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
    replace_characters_in_file_names: str = DEFAULT_REPLACE_CHARACTERS_IN_FILE_NAMES,
    replace_characters_in_file_names_with: str = DEFAULT_REPLACE_CHARACTERS_IN_FILE_NAMES_WITH,
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
        replace_characters_in_file_names: Characters replaced in the rendered file name
        replace_characters_in_file_names_with: Replacement for the replaced characters

    Returns:
        The path the URI was downloaded to
    """
    if output_file is not None:
        destination = output_file
    else:  # output_directory is not None
        filename = render_output_filename(
            file_name_template,
            uri,
            state,
            default_extension,
            position_starting_at_one,
            replace_characters_in_file_names,
            replace_characters_in_file_names_with,
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
        fetch_uri_to_file(uri, destination, timeout)

        if not machine_readable:
            click.echo(f"\n{label.capitalize()} successfully downloaded to {destination}")

        if create_manifest:
            manifest_path = write_download_manifest(
                destination, uri, state, host_configuration, entity, kind, add_cover_and_metadata
            )
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

    The metadata and cover come from ``state``. The embedded track number comes from
    the state's ``tracknumber`` key when present (the track number from the queue
    metadata, used verbatim — injected by ``queue download``), falling back to
    ``position`` (indexed according to ``position_starting_at_one``). Any problem
    (an unsupported format, a cover-download failure, or a tagging error) is
    reported as a warning and otherwise ignored: the already-downloaded file is
    left in place.

    Args:
        destination: The downloaded audio file to tag, modified in place
        state: The current player state dictionary (source of the metadata)
        host_configuration: The Volumio host configuration (to resolve the cover URI)
        timeout: Request timeout for fetching the cover image, in seconds
        position_starting_at_one: Whether the embedded track number starts at one
        verbose: Whether to print progress messages
        machine_readable: Whether machine-readable mode is active (suppresses messages)
    """
    tracknumber = state.get("tracknumber")
    if tracknumber is not None:
        track_number: int | None = int(tracknumber)
    else:
        position = state.get("position")
        track_number = (
            display_position(int(position), position_starting_at_one)
            if position is not None
            else None
        )

    cover = fetch_cover(state, host_configuration, timeout, machine_readable)

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


def fetch_cover(
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
    state: dict[str, Any] = fetch_or_exit(ctx, lambda c: c.state)
    return state


def fetch_uri_to_file(uri: str, destination: str, timeout: float) -> None:
    """Stream ``uri`` into the ``destination`` file.

    Args:
        uri: The URI to download
        destination: The destination file path
        timeout: Request timeout in seconds

    Raises:
        requests.exceptions.RequestException: If the HTTP request fails
        OSError: If the destination file cannot be written
    """
    response = requests.get(uri, timeout=timeout, stream=True)
    response.raise_for_status()

    with open(destination, "wb") as f:
        for chunk in response.iter_content(chunk_size=FILE_WRITE_CHUNK_SIZE):
            f.write(chunk)


def ignore_configuration_file_callback(
    ctx: click.Context, param: click.Parameter, value: bool
) -> bool:
    """Record the ``--ignore-configuration-file`` flag for the configuration lookup.

    Runs eagerly. When the flag is set and an explicit ``-c`` was already processed
    (Click processes eager parameters in command-line order, so either callback may
    run first), the combination is a usage error; otherwise the stored flag makes
    ``configuration_file_callback`` skip the lookup entirely.
    """
    ctx.ensure_object(dict)
    ctx.obj["ignore_configuration_file"] = value
    if value and ctx.obj.get("configuration_file_option") is not None:
        raise click.UsageError(MUTUALLY_EXCLUSIVE_CONFIGURATION_ERROR)
    return value


def option_add_cover_and_metadata(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``--add-cover-and-metadata`` option to the ``track audio`` subcommand."""
    return click.option(
        "--add-cover-and-metadata/--no-add-cover-and-metadata",
        default=True,
        show_default=True,
        help="Embed track metadata and cover art into the downloaded file "
        "(FLAC, MP3, MP4/M4A)",
    )(func)


def option_albumart_file_name_template(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``--albumart-file-name-template`` option to the queue download subcommand."""
    return click.option(
        "--albumart-file-name-template",
        type=str,
        default="{file_name_from_uri}",
        show_default=True,
        help="Template (Python str.format syntax) for the album art file names. Keys: "
        "file_name_from_uri, position, tracknumber, title, album, album_volume, "
        "artist, trackType, duration, bitdepth, samplerate, channels, extension. "
        "Some characters are replaced (see --replace-characters-in-file-names).",
    )(func)


def option_audio_file_name_template(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``-f``/``--audio-file-name-template`` option to the queue download subcommand."""
    return click.option(
        "-f",
        "--audio-file-name-template",
        type=str,
        default="{file_name_from_uri}",
        show_default=True,
        help="Template (Python str.format syntax) for the audio file names. Keys: "
        "file_name_from_uri, position, tracknumber, title, album, album_volume, "
        "artist, trackType, duration, bitdepth, samplerate, channels, extension. "
        "Some characters are replaced (see --replace-characters-in-file-names).",
    )(func)


def option_check_next_track(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``--check-next-track`` option to a queue/playlist download subcommand."""
    return click.option(
        "--check-next-track/--no-check-next-track",
        default=True,
        show_default=True,
        help="Check that each track's metadata are current before downloading it",
    )(func)


def option_check_playlist_name(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``--check-playlist-name`` option to a playlist subcommand."""
    return click.option(
        "--check-playlist-name/--no-check-playlist-name",
        default=True,
        show_default=True,
        help="Check that the playlist name exists before playing it",
    )(func)


def option_create_download_manifest(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``--create-download-manifest`` option to a track download subcommand."""
    return click.option(
        "--create-download-manifest/--no-create-download-manifest",
        default=True,
        show_default=True,
        help="Write a JSON manifest next to the downloaded file (e.g. out.flac.json)",
    )(func)


def option_current_track(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``--current-track`` option to a story subcommand."""
    return click.option(
        "--current-track",
        is_flag=True,
        default=False,
        help=(
            "Use the currently playing track's metadata instead of the "
            "positional argument(s)"
        ),
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
        "file_name_from_uri, position, tracknumber, title, album, album_volume, "
        "artist, trackType, duration, bitdepth, samplerate, channels, extension. "
        "Some characters are replaced (see --replace-characters-in-file-names).",
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


def option_number_retries_next_track(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``--number-retries-next-track`` option to a queue/playlist download subcommand."""
    return click.option(
        "--number-retries-next-track",
        type=int,
        default=DEFAULT_NUMBER_RETRIES_NEXT_TRACK,
        show_default=True,
        help="Number of retries waiting for a track's metadata to become current",
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


def option_replace_characters_in_file_names(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``--replace-characters-in-file-names`` option to a track download subcommand."""
    return click.option(
        "--replace-characters-in-file-names",
        type=str,
        default=DEFAULT_REPLACE_CHARACTERS_IN_FILE_NAMES,
        show_default=True,
        help="Characters to replace in the file name generated from -f/--file-name-template",
    )(func)


def option_replace_characters_in_file_names_with(
    func: Callable[..., None],
) -> Callable[..., None]:
    """Add the ``--replace-characters-in-file-names-with`` option to a download subcommand."""
    return click.option(
        "--replace-characters-in-file-names-with",
        type=str,
        default=DEFAULT_REPLACE_CHARACTERS_IN_FILE_NAMES_WITH,
        show_default=True,
        help=(
            "Replacement string for the characters selected by "
            "--replace-characters-in-file-names"
        ),
    )(func)


def option_story_type(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``-T/--type`` option to a story subcommand."""
    return click.option(
        "-T",
        "--type",
        "argument_type",
        type=click.Choice(STORY_ARGUMENT_TYPES),
        default=DEFAULT_STORY_ARGUMENT_TYPE,
        show_default=True,
        help=(
            "How to interpret the positional argument(s): name, mbid, or "
            "autodetect (mbid iff a single UUID-shaped argument)"
        ),
    )(func)


def option_with_albumart(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``--with-albumart`` option to a queue/playlist download subcommand."""
    return click.option(
        "--with-albumart/--no-with-albumart",
        default=True,
        show_default=True,
        help="Download each album's cover, named from --albumart-file-name-template "
        "(once per cover)",
    )(func)


def render_output_filename(
    template: str,
    uri: str,
    state: dict[str, Any],
    default_extension: str,
    position_starting_at_one: bool = True,
    replace_characters_in_file_names: str = DEFAULT_REPLACE_CHARACTERS_IN_FILE_NAMES,
    replace_characters_in_file_names_with: str = DEFAULT_REPLACE_CHARACTERS_IN_FILE_NAMES_WITH,
    allow_subdirectories: bool = False,
    option_label: str = "--file-name-template",
) -> str:
    """Render a safe output file name from a template, track metadata, and the URI.

    The template uses Python ``str.format`` syntax. Supported keys are:
    ``file_name_from_uri``, ``position`` (int, indexed according to
    ``position_starting_at_one``), ``tracknumber`` (int, the track number of the
    track, taken verbatim from the state's ``tracknumber`` key — injected from the
    queue metadata by ``queue download``), ``title``, ``album``, ``album_volume``
    (the album name with ``/<volumeNumber>`` appended for multi-volume albums,
    injected by ``queue download``; its path separator is preserved, so the key is
    meant for subdirectory-capable templates), ``artist``,
    ``trackType``, ``duration`` (HH:MM:SS), ``bitdepth``, ``samplerate``,
    ``channels`` (int), and ``extension``. The ``extension`` is
    taken from the URI file name, falling back to ``default_extension`` when the
    URI file has none.

    The name is rendered defensively, since the metadata values and the URI are
    untrusted: template fields must be exactly the supported keys (no attribute or
    index access), path separators in the interpolated values are replaced and
    control characters removed, leading dots are stripped from the result, and the
    rendered name must be a plain file name without path separators — unless
    ``allow_subdirectories`` is true, in which case separators coming from the
    template literals are kept (so the template can lay files out in
    subdirectories) and the caller is expected to verify that the final path stays
    inside the output directory.

    After rendering, every character of ``replace_characters_in_file_names`` is
    replaced with ``replace_characters_in_file_names_with`` (which must not itself
    contain path separators or control characters).

    Args:
        template: The file-name template (``str.format`` syntax)
        uri: The URI being downloaded (source of ``file_name_from_uri`` and ``extension``)
        state: The current player state dictionary
        default_extension: Extension to use when the URI file has none (no leading dot)
        position_starting_at_one: Whether the ``position`` key starts at one
        replace_characters_in_file_names: Characters replaced in the rendered name
        replace_characters_in_file_names_with: Replacement for the replaced characters
        allow_subdirectories: Whether template-literal path separators are allowed
        option_label: Name of the template option, used in the error messages

    Returns:
        The rendered, sanitized file name

    Raises:
        click.UsageError: If the template references an unknown key, uses an invalid
            format specification, or renders to a name containing a path separator
            (unless ``allow_subdirectories`` is true), or if the replacement string
            contains a path separator or control character
    """
    replacement = replace_characters_in_file_names_with
    if sanitize_filename_component(replacement, "") != replacement:
        raise click.UsageError(
            f"Invalid --replace-characters-in-file-names-with {replacement!r}: "
            "it must not contain path separators or control characters"
        )

    def as_text(key: str) -> str:
        value = state.get(key)
        text = str(value).strip() if value is not None else ""
        return sanitize_filename_component(text, replacement)

    try:
        position = int(state.get("position") or 0)
    except (TypeError, ValueError):
        position = 0

    try:
        tracknumber = int(state.get("tracknumber") or 0)
    except (TypeError, ValueError):
        tracknumber = 0

    file_name_from_uri = sanitize_filename_component(extract_filename_from_uri(uri), replacement)
    uri_extension = os.path.splitext(file_name_from_uri)[1].lstrip(".")

    # Sanitize the album/volume value per component, keeping its deliberate separator
    album_volume = "/".join(
        sanitize_filename_component(part, replacement)
        for part in str(state.get("album_volume") or "").split("/")
    )

    duration = state.get("duration")
    keys: dict[str, object] = {
        "file_name_from_uri": file_name_from_uri,
        "position": display_position(position, position_starting_at_one),
        "tracknumber": tracknumber,
        "title": as_text("title"),
        "album": as_text("album"),
        "album_volume": album_volume,
        "artist": as_text("artist"),
        "trackType": as_text("trackType"),
        "duration": format_duration(int(duration)) if isinstance(duration, int) else "",
        "bitdepth": as_text("bitdepth"),
        "samplerate": as_text("samplerate"),
        "channels": int(state["channels"]) if isinstance(state.get("channels"), int) else 0,
        "extension": uri_extension or default_extension,
    }

    try:
        fields = [field for _, field, _, _ in Formatter().parse(template) if field is not None]
    except ValueError as e:
        raise click.UsageError(f"Invalid {option_label} {template!r}: {e}") from e
    unknown = [field for field in fields if field not in keys]
    if unknown:
        accepted = ", ".join(sorted(keys))
        raise click.UsageError(
            f"Invalid {option_label} {template!r}: "
            f"unknown key {unknown[0]!r} (valid keys: {accepted})"
        )

    try:
        rendered = template.format(**keys)
    except (KeyError, ValueError, IndexError) as e:
        raise click.UsageError(f"Invalid {option_label} {template!r}: {e}") from e

    for character in replace_characters_in_file_names:
        rendered = rendered.replace(character, replacement)

    rendered = rendered.lstrip(".")
    if not allow_subdirectories and ("/" in rendered or "\\" in rendered):
        raise click.UsageError(
            f"Invalid {option_label} {template!r}: "
            f"it must render to a plain file name, got {rendered!r}"
        )
    return rendered


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


def render_story(
    ctx: click.Context,
    fetch: Callable[[VolumioRESTAPIClient], dict[str, Any]],
    fields: str,
    output_format: str,
    heading: str,
) -> None:
    """Fetch a metavolumio story payload and print it per the fields/format options.

    A response whose "success" flag is not true is reported as an error (exit
    code 1). The successful response envelope is rendered like the other query
    commands, honoring the fields and format options.

    Args:
        ctx: Click context object containing shared options
        fetch: Function querying the story on the VolumioRESTAPIClient (e.g. calling
            its get_story or get_album_credits method)
        fields: The fields option ("short" or "all")
        output_format: The output format ("json", "pretty", "raw", or "table")
        heading: The heading line for the table output format
    """
    verbose = ctx.obj["verbose"]
    machine_readable = ctx.obj["machine_readable"]
    position_starting_at_one = ctx.obj["position_starting_at_one"]

    response = fetch_or_exit(ctx, fetch)

    if response.get("success") is not True:
        if not machine_readable:
            error = response.get("error", "unknown error")
            click.echo(f"Story error: {error}", err=True)
        sys.exit(1)

    if verbose and not machine_readable:
        click.echo("Successfully retrieved story", err=True)

    if output_format == "raw":
        # Raw JSON without formatting (ignores fields filter)
        output = json.dumps(response)
    else:
        # Apply fields filter for all formatted outputs
        filtered_response = filter_fields(response, fields, SHORT_FORMAT_FIELDS_STORY)

        if output_format == "table":
            # Preserve the requested field order (and labels) in the table; None => all
            field_order = resolve_output_fields(fields, SHORT_FORMAT_FIELDS_STORY)
            output = format_as_table(
                filtered_response,
                heading=heading,
                field_order=field_order,
                position_starting_at_one=position_starting_at_one,
            )
        elif output_format == "json":
            output = format_as_json(filtered_response)
        else:  # pretty
            output = format_as_pretty(filtered_response, position_starting_at_one)

    click.echo(output)


def resolve_story_album_entities(
    ctx: click.Context,
    arguments: tuple[str, ...],
    argument_type: str,
    current_track: bool = False,
) -> tuple[Artist | None, Album]:
    """Resolve the "story album"/"story credits" arguments into entity references.

    With ``current_track`` set (the --current-track option, mutually exclusive with
    the positional arguments), the artist and album are taken from the currently
    playing track, bypassing the argument-type interpretation. Otherwise, see
    :func:`volumito.cli.pure_helpers.story_query_reference` for the resolution
    rules: an MBID argument yields the album only (with no artist), and an ARTIST
    ALBUM argument pair yields both entities by name.

    Args:
        ctx: Click context object containing shared options
        arguments: The positional arguments of the command
        argument_type: How to interpret the arguments ("autodetect", "mbid", or "name")
        current_track: Whether to take the entity values from the current track

    Returns:
        The artist (or None for an album by MBID) and the album

    Raises:
        click.UsageError: If the arguments cannot be resolved or combined with
            --current-track (exit code 2)
    """
    if current_track:
        if arguments:
            raise click.UsageError(MUTUALLY_EXCLUSIVE_CURRENT_TRACK_ERROR)
        artist_value, album_value = _story_current_track_values(ctx, ("artist", "album"))
        return (Artist(artist_value), Album(album_value))
    reference = story_query_reference(arguments, argument_type, pair=True)
    if reference is None:
        raise click.UsageError(STORY_ARTIST_ALBUM_ARGUMENTS_ERROR)
    kind, values = reference
    if kind == "mbid":
        return (None, Album(values[0], is_mbid=True))
    return (Artist(values[0]), Album(values[1]))


def resolve_story_entity[E: MusicEntity](
    ctx: click.Context,
    arguments: tuple[str, ...],
    argument_type: str,
    entity_class: type[E],
    current_track: bool = False,
) -> E:
    """Resolve a single-entity "story" argument into an entity reference.

    With ``current_track`` set (the --current-track option, mutually exclusive with
    the positional arguments), the entity value is taken from the currently playing
    track (using the lowercased entity class name as the state key), bypassing the
    argument-type interpretation. Otherwise, see
    :func:`volumito.cli.pure_helpers.story_query_reference` for the resolution
    rules.

    Args:
        ctx: Click context object containing shared options
        arguments: The positional arguments of the command
        argument_type: How to interpret the arguments ("autodetect", "mbid", or "name")
        entity_class: The entity class (e.g. Artist, Label, or Place)
        current_track: Whether to take the entity value from the current track

    Returns:
        The entity reference

    Raises:
        click.UsageError: If the arguments cannot be resolved or combined with
            --current-track (exit code 2)
    """
    if current_track:
        if arguments:
            raise click.UsageError(MUTUALLY_EXCLUSIVE_CURRENT_TRACK_ERROR)
        (value,) = _story_current_track_values(ctx, (entity_class.__name__.lower(),))
        return entity_class(value)
    reference = story_query_reference(arguments, argument_type, pair=False)
    if reference is None:
        raise click.UsageError(STORY_ARTIST_ARGUMENT_ERROR)
    kind, values = reference
    return entity_class(values[0], is_mbid=kind == "mbid")


def rest_api_sleep(ctx: click.Context) -> None:
    """Sleep for the configured delay before making the next REST API call.

    Args:
        ctx: Click context object holding the shared options
    """
    time.sleep(ctx.obj["rest_api_sleep_before_next_call"])


def write_download_manifest(
    destination: str,
    uri: str,
    state: dict[str, Any],
    host_configuration: VolumioHostConfiguration,
    entity: str,
    kind: str,
    add_cover_and_metadata: bool | None,
) -> str:
    """Write the ``<destination>.json`` manifest describing a download.

    Args:
        destination: The path the URI was downloaded to
        uri: The downloaded URI
        state: The current player state dictionary
        host_configuration: The Volumio host configuration
        entity: The manifest ``entity`` value (e.g. "track")
        kind: The manifest ``kind`` value (e.g. "audio" or "albumart")
        add_cover_and_metadata: Recorded in the manifest when not None

    Returns:
        The path of the written manifest file
    """
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
    return manifest_path


def write_queue_log(path: str, log: dict[str, Any]) -> None:
    """Write the queue download log as sorted, indented JSON.

    Args:
        path: The path of the log file
        log: The log dictionary to serialize
    """
    with open(path, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, sort_keys=True, ensure_ascii=False)
