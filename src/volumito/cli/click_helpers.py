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
from typing import Any, get_args, overload

import click
import requests
from click.core import ParameterSource
from packaging.version import InvalidVersion, Version

from volumito import __version__
from volumito.cli.api_client import (
    APIClient,
    AsyncRESTAPIClient,
    AsyncWebSocketAPIClient,
    SyncRESTAPIClient,
    SyncWebSocketAPIClient,
    UnsupportedOperationError,
)
from volumito.cli.configuration import (
    build_click_default_map,
    load_configuration_with_errors,
    resolve_configuration_path,
)
from volumito.cli.console import LOGGER, debug, error, info, warning
from volumito.cli.constants import (
    API_CLIENT_ASYNCHRONOUS_REST,
    API_CLIENT_ASYNCHRONOUS_WEBSOCKET,
    API_CLIENT_SHORT_FORMS,
    API_CLIENT_SYNCHRONOUS_REST,
    API_CLIENT_SYNCHRONOUS_WEBSOCKET,
    API_CLIENTS,
    API_CLIENTS_WEBSOCKET,
    DEFAULT_API_CLIENT,
    DEFAULT_MANIFEST_FILE,
    DEFAULT_NUMBER_RETRIES_NEXT_TRACK,
    DEFAULT_REPLACE_CHARACTERS_IN_FILE_NAMES,
    DEFAULT_REPLACE_CHARACTERS_IN_FILE_NAMES_WITH,
    DEFAULT_STORY_ARGUMENT_TYPE,
    FILE_WRITE_CHUNK_SIZE,
    MUTUALLY_EXCLUSIVE_CONFIGURATION_ERROR,
    MUTUALLY_EXCLUSIVE_CURRENT_TRACK_ERROR,
    MUTUALLY_EXCLUSIVE_OUTPUT_ERROR,
    OUTPUT_DIRECTORY_TIMESTAMP_FORMAT,
    OUTPUT_FIELDS_SHORT,
    OUTPUT_FORMATS,
    SEARCH_SERVICES,
    SHORT_FORMAT_FIELDS_STORY,
    STORY_ARGUMENT_TYPES,
    STORY_ARTIST_ALBUM_ARGUMENTS_ERROR,
    STORY_ARTIST_ARGUMENT_ERROR,
    STORY_CURRENT_TRACK_METADATA_ERROR,
)
from volumito.cli.metadata import (
    UnsupportedAudioFormatError,
    detect_audio_extension,
    embed_metadata_and_cover,
)
from volumito.cli.pure_helpers import (
    display_position,
    expand_timestamp_placeholder,
    extract_filename_from_uri,
    filter_fields,
    format_as_json,
    format_as_pretty,
    format_as_table,
    format_duration,
    parse_result_kinds,
    parse_time_to_seconds,
    parse_track_selection,
    preserve_local_file_name,
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
    VolumioAsyncError,
    VolumioAsyncRESTAPIClient,
    VolumioAsyncWebSocketClient,
    VolumioConnectionError,
    VolumioHostConfiguration,
    VolumioRESTAPIClient,
    VolumioSSHError,
    VolumioStoryError,
    VolumioWebSocketClient,
    VolumioWebSocketError,
    copy_from_host,
    is_local_file_uri,
    remote_music_path,
)
from volumito.clients.entities import MusicEntity
from volumito.clients.listener import DEFAULT_ENDPOINT, DEFAULT_PORT
from volumito.clients.models import PlayerState, SearchResultItemKind, Story


class AliasedGroup(click.Group):
    """A group resolving also the aliases defined in the configuration file.

    A built-in command always wins over an alias of the same name; an alias maps a new
    top-level name to an existing command path (a group or a subcommand), and loading
    the configuration refuses the aliases that shadow a command or target a path that
    does not resolve. The aliases are not listed in the group help.
    """

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        """Return the built-in command, or the target of the matching alias.

        Invoking an alias dropped at configuration load time fails with the problem
        that dropped it, instead of an unexplained unknown-command error.
        """
        command = super().get_command(ctx, cmd_name)
        if command is not None:
            return command
        target = ((ctx.obj or {}).get("aliases") or {}).get(cmd_name)
        if target is None:
            problem = ((ctx.obj or {}).get("dropped_aliases") or {}).get(cmd_name)
            if problem is not None:
                raise click.UsageError(problem)
            return None
        return resolve_command_path(self, ctx, target)


class APIClientParamType(click.ParamType):
    """Click parameter type for the API client.

    Accepts the values of ``API_CLIENTS``, and the short forms of
    ``API_CLIENT_SHORT_FORMS``, which convert to the value they stand for; anything
    else is a usage error.
    """

    name = "api_client"

    def convert(
        self,
        value: object,
        param: click.Parameter | None,
        ctx: click.Context | None,
    ) -> str:
        text = str(value)
        if text in API_CLIENTS:
            return text
        if text in API_CLIENT_SHORT_FORMS:
            return API_CLIENT_SHORT_FORMS[text]
        accepted = ", ".join(API_CLIENTS)
        short_forms = ", ".join(API_CLIENT_SHORT_FORMS)
        self.fail(
            f"{text!r} must be one of {accepted} (or the short forms {short_forms})", param, ctx
        )

    def get_metavar(self, param: click.Parameter, ctx: click.Context) -> str:
        return f"[{'|'.join(API_CLIENTS)}]"


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


class ResultKindsParamType(click.ParamType):
    """Click parameter type for a selection of search result kinds.

    Accepts a comma-separated list of the kinds a search result can be (e.g.,
    ``"album,track"``); anything else is a usage error.
    """

    name = "kinds"

    def convert(
        self,
        value: object,
        param: click.Parameter | None,
        ctx: click.Context | None,
    ) -> set[SearchResultItemKind]:
        try:
            return parse_result_kinds(str(value))
        except ValueError as e:
            self.fail(str(e), param, ctx)

    def get_metavar(self, param: click.Parameter, ctx: click.Context) -> str:
        return f"[{'|'.join(kind.value for kind in SearchResultItemKind)}]"


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


class TrackSelectionParamType(click.ParamType):
    """Click parameter type for a selection of queue tracks.

    Accepts a comma-separated list of queue positions, each a positive integer or an
    inclusive ``start-end`` range (e.g., ``"1-3,6-8,12"``); anything else is a usage
    error.
    """

    name = "selection"

    def convert(
        self,
        value: object,
        param: click.Parameter | None,
        ctx: click.Context | None,
    ) -> set[int]:
        try:
            return parse_track_selection(str(value))
        except ValueError as e:
            self.fail(str(e), param, ctx)

    def get_metavar(self, param: click.Parameter, ctx: click.Context) -> str:
        return "[SELECTION]"


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
    major version (e.g., "4" -> 4, "3.123" -> 3). Anything that is not a valid version
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
                f"{text!r} is not a valid Volumio version (e.g., 4, 3, 4.119, 3.123)",
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
    host_configuration: VolumioHostConfiguration,
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
        host_configuration: The Volumio host configuration (passed to the download)

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
            fetch_uri_to_file(albumart_uri, cover_path, timeout, host_configuration)
    except (requests.exceptions.RequestException, VolumioSSHError, OSError) as e:
        warning(f'Cannot download album art to "{cover_path}" ({e})')
        return None
    downloaded_covers.setdefault(albumart_uri, cover_path)
    return cover_path


def _story_current_track_values(ctx: click.Context, keys: tuple[str, ...]) -> tuple[str, ...]:
    """Fetch the current track's values for the given state keys, exiting on failure.

    Args:
        ctx: Click context object containing shared options
        keys: The state keys to read (e.g., ("artist", "album"))

    Returns:
        The (stripped) state values, one per key; a missing, non-string, or blank
        value is an error (exit code 1, message suppressed in machine-readable mode)
    """
    state = fetch_state_or_exit(ctx)
    values = []
    for key in keys:
        value = getattr(state, key, None)
        if not isinstance(value, str) or not value.strip():
            error(STORY_CURRENT_TRACK_METADATA_ERROR)
            sys.exit(1)
        values.append(value.strip())
    return tuple(values)


def aliases_by_command_path(aliases: dict[str, str]) -> dict[str, list[str]]:
    """Invert an alias mapping into the alias names of each aliased command path.

    Args:
        aliases: The alias name -> command path mapping read from the configuration

    Returns:
        Each aliased command path mapped to its alias names, sorted
    """
    result: dict[str, list[str]] = {}
    for name in sorted(aliases):
        result.setdefault(" ".join(aliases[name].split()), []).append(name)
    return result


def alias_problems(
    root: click.Group, ctx: click.Context, aliases: dict[str, str], path: str
) -> list[tuple[str, str]]:
    """Return the name and a problem message for every alias that shadows or does not resolve.

    Args:
        root: The top-level command group holding the built-in commands
        ctx: Click context used to resolve the command tree
        aliases: The alias name -> command path mapping read from the configuration
        path: Path of the configuration file (for the messages)

    Returns:
        The problems found, one (alias name, message) pair per broken alias
    """
    problems: list[tuple[str, str]] = []
    for name, target in aliases.items():
        if click.Group.get_command(root, ctx, name) is not None:
            problems.append(
                (
                    name,
                    f'alias {name!r} in configuration file "{path}" '
                    f"shadows the command {name!r}",
                )
            )
        elif resolve_command_path(root, ctx, target) is None:
            problems.append(
                (
                    name,
                    f"alias {name!r} in configuration file \"{path}\" "
                    f"targets the unknown command {target!r}",
                )
            )
    return problems


def api_position(ctx: click.Context, position: int, name: str = "position") -> int:
    """Convert a queue position as the user gives it to the 0-based one of the API.

    The user indexes the positions according to
    ``--position-starting-at-one``/``--position-starting-at-zero``.

    Args:
        ctx: Click context object holding the shared options
        position: The position as the user gave it
        name: How the usage error names the position

    Returns:
        The 0-based position

    Raises:
        click.UsageError: If the position is below the minimum of the indexing in use
    """
    minimum = 1 if ctx.obj["position_starting_at_one"] else 0
    if position < minimum:
        raise click.UsageError(f"{name} must be {minimum} or greater, got {position}")
    return position - minimum


def configuration_file_callback(
    ctx: click.Context, param: click.Parameter, value: str | None
) -> str | None:
    """Load the configuration file (if any) and use its values as option defaults.

    Runs eagerly, before the other options resolve, so the loaded values populate
    ``ctx.default_map`` and are only used where the user did not pass an explicit flag.
    With ``--ignore-configuration-file`` the lookup is skipped entirely (an explicit
    ``-c`` combined with it is a usage error; both eager callbacks perform the check,
    since Click processes eager parameters in command-line order).

    The file is parsed leniently: an unreadable file, an unknown key, or a broken
    alias never refuses the invocation -- the broken parts are ignored, the valid
    ones apply, and each problem is warned about once the console is up.
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
        config, problems = load_configuration_with_errors(path)
        aliases = dict(config.get("aliases", {}))
        dropped: dict[str, str] = {}
        if isinstance(ctx.command, click.Group):
            for name, problem in alias_problems(ctx.command, ctx, aliases, path):
                problems.append(problem)
                dropped[name] = problem
                del aliases[name]
        ctx.obj["aliases"] = aliases
        ctx.obj["dropped_aliases"] = dropped
        # The console is not set up yet (this callback is eager), so the problems are
        # stashed here and warned about by the group callback
        ctx.obj["configuration_problems"] = problems
        default_map = build_click_default_map(config)
        # Click reads default_map by invocation path, and an aliased command runs under
        # the alias name, so the target's branch must also be reachable under it
        for name, target in aliases.items():
            branch: Any = default_map
            for token in target.split():
                branch = branch.get(token) if isinstance(branch, dict) else None
            if isinstance(branch, dict) and branch:
                default_map[name] = branch
        ctx.default_map = {**(ctx.default_map or {}), **default_map}
    ctx.obj["configuration_file"] = path
    return value


def command_nodes(
    root: click.Group,
    ctx: click.Context,
    aliases: dict[str, list[str]] | None = None,
    prefix: str = "",
) -> list[dict[str, Any]]:
    """Describe the built-in commands of a group, as a list of nested node mappings.

    Each node carries the ``aliases`` pointing at it (unless ``aliases`` is None),
    its ``path``, its ``type`` ("group" or "command"), and, for a group, the
    ``subcommands`` it holds. Only the built-in names are walked, so the aliases the
    configuration defines (which :class:`AliasedGroup` resolves but never lists) stay
    out of the tree, and each level is sorted lexicographically.

    Args:
        root: The group to walk
        ctx: Click context used by the lookups
        aliases: The alias names of each command path, or None to omit them
        prefix: The path of the group being walked (empty at the top level)

    Returns:
        The nodes of the group, one per command it holds
    """
    nodes: list[dict[str, Any]] = []
    for name in sorted(click.Group.list_commands(root, ctx)):
        command = click.Group.get_command(root, ctx, name)
        path = f"{prefix} {name}" if prefix else name
        node: dict[str, Any] = {}
        if aliases is not None:
            node["aliases"] = aliases.get(path, [])
        node["path"] = name
        node["type"] = "group" if isinstance(command, click.Group) else "command"
        if isinstance(command, click.Group):
            node["subcommands"] = command_nodes(command, ctx, aliases, path)
        nodes.append(node)
    return nodes


def command_nodes_flattened(
    nodes: list[dict[str, Any]], prefix: str = ""
) -> list[dict[str, Any]]:
    """Flatten nested command nodes into one node per command, holding its full path.

    The groups are kept (typed as such), before the commands they hold, so the
    flattened nodes are ordered by their path.

    Args:
        nodes: The nested nodes, as :func:`command_nodes` returns them
        prefix: The path of the group holding the nodes (empty at the top level)

    Returns:
        The flattened nodes, without their ``subcommands``
    """
    flat: list[dict[str, Any]] = []
    for node in nodes:
        path = f"{prefix} {node['path']}" if prefix else node["path"]
        flat.append(
            {
                key: (path if key == "path" else value)
                for key, value in node.items()
                if key != "subcommands"
            }
        )
        flat.extend(command_nodes_flattened(node.get("subcommands", []), path))
    return flat


def connection_url(ctx: click.Context) -> str:
    """Return the URL of the API endpoint the selected API client connects to.

    Args:
        ctx: Click context object holding the shared options

    Returns:
        The WebSocket base URL for the WebSocket API clients, the REST one otherwise
    """
    host_configuration: VolumioHostConfiguration = ctx.obj["host_configuration"]
    if ctx.obj["api_client"] in API_CLIENTS_WEBSOCKET:
        return host_configuration.websocket_base_url
    return host_configuration.rest_base_url


def correct_audio_extension(destination: str, overwrite: bool) -> str:
    """Rename a downloaded audio file to the extension its own content calls for.

    The file name is rendered before the download, so the extension can only be the
    one the URI carries or the default of the command (e.g., a Qobuz stream URI has
    no extension, and an MP3 track of it is named ".flac"). The format is therefore
    sniffed from the downloaded file itself: a file whose extension already matches,
    or whose format is not recognized, is left alone, and so is one whose corrected
    name is taken by another file, unless ``overwrite`` is true.

    Args:
        destination: The path the audio file was downloaded to
        overwrite: Whether an existing file at the corrected path can be replaced

    Returns:
        The path of the file, renamed or not
    """
    extension = detect_audio_extension(destination)
    stem, current = os.path.splitext(destination)
    if extension is None or extension == current.lower():
        return destination
    corrected = f"{stem}{extension}"
    if not overwrite and os.path.exists(corrected):
        warning(
            f'Cannot rename "{destination}" to "{corrected}": the file already exists '
            "(use --overwrite-existing-files to overwrite)"
        )
        return destination
    os.replace(destination, corrected)
    info(f'Renamed "{destination}" to "{corrected}", matching the format of its content')
    return corrected


def create_client(
    host_configuration: VolumioHostConfiguration,
    rest_api_timeout: float,
    rest_api_timeout_slow_endpoints: float = 60.0,
    *,
    websocket_timeout: float = 5.0,
    api_client: str = DEFAULT_API_CLIENT,
    allow_fallback_to_rest_api: bool = False,
    allow_fallback_to_websocket_api: bool = False,
) -> APIClient:
    """Create the API client the -C/--api-client option selects, not yet open.

    Every client logs to the CLI console. A WebSocket API client gets a REST API client
    of the same kind (synchronous or asynchronous) to fall back to, when allowed, for
    the operations the WebSocket API does not offer; a REST API client gets a WebSocket
    API client of the same kind, when allowed, for the operations the REST API does not
    offer. A client built to fall back to falls back to nothing itself.

    Args:
        host_configuration: The host configuration (scheme, host, and ports)
        rest_api_timeout: REST API request timeout, in seconds
        rest_api_timeout_slow_endpoints: REST API request timeout, in seconds, for the
            endpoints that can take long, like replacing the queue
        websocket_timeout: The seconds a WebSocket API read waits for its answer
        api_client: The name of the API client, one of the -C/--api-client values
        allow_fallback_to_rest_api: Whether a WebSocket API client falls back to a REST
            API client for the operations the WebSocket API does not offer
        allow_fallback_to_websocket_api: Whether a REST API client falls back to a
            WebSocket API client for the operations the REST API does not offer

    Returns:
        The API client, to be opened before its first use

    Raises:
        ValueError: If the name is not one of the -C/--api-client values
    """

    def asynchronous_rest(fallback: Callable[[], APIClient] | None = None) -> APIClient:
        return AsyncRESTAPIClient(
            VolumioAsyncRESTAPIClient(
                host_configuration,
                timeout=rest_api_timeout,
                timeout_slow_endpoints=rest_api_timeout_slow_endpoints,
                logger=LOGGER,
            ),
            fallback=fallback,
        )

    def asynchronous_websocket(fallback: Callable[[], APIClient] | None = None) -> APIClient:
        return AsyncWebSocketAPIClient(
            VolumioAsyncWebSocketClient(host_configuration, websocket_timeout, LOGGER),
            fallback=fallback,
        )

    def synchronous_rest(fallback: Callable[[], APIClient] | None = None) -> APIClient:
        return SyncRESTAPIClient(
            VolumioRESTAPIClient(
                host_configuration,
                timeout=rest_api_timeout,
                timeout_slow_endpoints=rest_api_timeout_slow_endpoints,
                logger=LOGGER,
            ),
            fallback=fallback,
        )

    def synchronous_websocket(fallback: Callable[[], APIClient] | None = None) -> APIClient:
        return SyncWebSocketAPIClient(
            VolumioWebSocketClient(host_configuration, websocket_timeout, LOGGER),
            fallback=fallback,
        )

    if api_client == API_CLIENT_SYNCHRONOUS_REST:
        return synchronous_rest(
            synchronous_websocket if allow_fallback_to_websocket_api else None
        )
    if api_client == API_CLIENT_ASYNCHRONOUS_REST:
        return asynchronous_rest(
            asynchronous_websocket if allow_fallback_to_websocket_api else None
        )
    if api_client == API_CLIENT_SYNCHRONOUS_WEBSOCKET:
        return synchronous_websocket(synchronous_rest if allow_fallback_to_rest_api else None)
    if api_client == API_CLIENT_ASYNCHRONOUS_WEBSOCKET:
        return asynchronous_websocket(asynchronous_rest if allow_fallback_to_rest_api else None)
    raise ValueError(f"Unknown API client {api_client!r}")


def download_queue_albumart(
    state: PlayerState,
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
    album_volume: str = "",
    tracknumber: int | None = None,
) -> str | None:
    """Download the current track's album art into the output directory.

    The cover is saved under the name rendered from ``albumart_file_name_template``
    (relative to ``run_directory``; the template may lay covers out in
    subdirectories, which are created as needed but must stay inside the output
    directory). Each distinct album-art URI is downloaded at most once per run
    (``downloaded_covers`` maps the URIs already downloaded to their file paths);
    when the same URI renders to further destinations (e.g., one per volume of a
    multi-volume album), the already-downloaded file is copied there locally. For
    a multi-volume track, the cover is also placed at the path rendered with the
    album-only ``album_volume`` component (e.g., ``Elegia/cover.jpg`` next to
    ``Elegia/1/cover.jpg`` and ``Elegia/2/cover.jpg``). An existing cover file is
    reused unless ``overwrite`` is true. A download failure is reported as a
    warning and otherwise ignored.

    Args:
        state: The current player state (source of the album-art URI)
        run_directory: The download output directory of the run
        albumart_file_name_template: Template for the cover file name
        host_configuration: The Volumio host configuration (to resolve relative URIs)
        timeout: Request timeout in seconds
        overwrite: Whether to overwrite an existing cover file
        machine_readable: Whether machine-readable mode is active (suppresses messages)
        downloaded_covers: Cache of album-art URIs already handled, updated in place
        position_starting_at_one: Whether the template ``position`` key starts at one
        replace_characters_in_file_names: Characters replaced in the rendered file name
        replace_characters_in_file_names_with: Replacement for the replaced characters
        album_volume: The album/volume path component of the track being downloaded
        tracknumber: The number of the track within its album

    Returns:
        The cover file path, or None if the track has no album art or the download failed

    Raises:
        click.UsageError: If the template is invalid or renders to a path escaping
            the output directory
    """
    albumart_uri = resolve_albumart_uri(state, host_configuration)
    if albumart_uri is None:
        return None

    def resolve_cover_path(cover_album_volume: str) -> str | None:
        filename = render_output_filename(
            albumart_file_name_template,
            albumart_uri,
            state,
            "jpg",
            position_starting_at_one,
            replace_characters_in_file_names,
            replace_characters_in_file_names_with,
            allow_subdirectories=True,
            option_label="--albumart-file-name-template",
            album_volume=cover_album_volume,
            tracknumber=tracknumber,
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

    cover_path = resolve_cover_path(album_volume)
    if cover_path is None:
        warning("Cannot determine a file name for the album art")
        return None
    result = _materialize_albumart(
        albumart_uri,
        cover_path,
        overwrite,
        timeout,
        machine_readable,
        downloaded_covers,
        host_configuration,
    )

    # For a multi-volume track, also place the cover in the album directory itself
    if result is not None and "/" in album_volume:
        album_cover_path = resolve_cover_path(album_volume.split("/", 1)[0])
        if album_cover_path is not None and album_cover_path != cover_path:
            _materialize_albumart(
                albumart_uri,
                album_cover_path,
                overwrite,
                timeout,
                machine_readable,
                downloaded_covers,
                host_configuration,
            )
    return result


def download_queue_track(
    uri: str,
    destination: str,
    overwrite: bool,
    timeout: float,
    create_manifest: bool,
    state: PlayerState,
    host_configuration: VolumioHostConfiguration,
    add_cover_and_metadata: bool,
    extra_state: dict[str, Any] | None = None,
) -> tuple[str, str | None, str]:
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
        A ``(status, error, path)`` triple: ``("skipped", None, path)`` if the
        destination exists and ``overwrite`` is false, ``("downloaded", None, path)``
        on success, or ``("error", message, path)`` on a download or write failure.
        The path is ``destination``, unless the downloaded file was renamed to match
        the audio format of its content (see ``correct_audio_extension``)
    """
    if not overwrite and os.path.exists(destination):
        return "skipped", None, destination
    try:
        parent = os.path.dirname(destination)
        if parent:
            os.makedirs(parent, exist_ok=True)
        fetch_uri_to_file(uri, destination, timeout, host_configuration)
        if not is_local_file_uri(uri):
            destination = correct_audio_extension(destination, overwrite)
        if create_manifest:
            write_download_manifest(
                destination, uri, state, host_configuration, "track", "audio",
                add_cover_and_metadata, extra_state,
            )
    except (requests.exceptions.RequestException, VolumioSSHError, OSError) as e:
        return "error", str(e), destination
    return "downloaded", None, destination


def download_uri_to(
    uri: str,
    output_file: str | None,
    output_directory: str | None,
    file_name_template: str,
    default_extension: str,
    state: PlayerState,
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
    allow_local_file_rename: bool = False,
    replace_characters_in_file_names: str = DEFAULT_REPLACE_CHARACTERS_IN_FILE_NAMES,
    replace_characters_in_file_names_with: str = DEFAULT_REPLACE_CHARACTERS_IN_FILE_NAMES_WITH,
) -> str:
    """Download ``uri`` to a file, printing errors and exiting (1) on failure.

    Exactly one of ``output_file`` / ``output_directory`` is expected to be set. With
    ``output_file`` the URI is saved to that exact path; with ``output_directory`` it is
    saved into that directory (created if missing) under the file name produced by
    rendering ``file_name_template`` against ``state`` (see ``render_output_filename``).
    Unless ``overwrite`` is true, an existing destination file is left untouched.

    When ``create_manifest`` is true, a JSON manifest describing the download is written
    next to the downloaded file (``<destination>.json``) after a successful download.

    Args:
        uri: The URI to download
        output_file: Exact destination file path, or None
        output_directory: Destination directory (file name from the template), or None
        file_name_template: Template for the ``output_directory`` file name
        default_extension: Extension for the ``{extension}`` key when the URI has none
        state: The current player state (source of the template values)
        overwrite: Whether to overwrite the destination file if it already exists
        label: Human-readable noun for messages ("track" or "album art")
        timeout: Request timeout in seconds
        verbose: Whether to print progress messages
        machine_readable: Whether machine-readable mode is active (suppresses messages)
        create_manifest: Whether to write a ``<destination>.json`` download manifest
        host_configuration: The Volumio host configuration (recorded in the manifest)
        entity: The manifest ``entity`` value (e.g., "track")
        kind: The manifest ``kind`` value (e.g., "audio" or "albumart")
        position_starting_at_one: Whether the template ``position`` key starts at one
        add_cover_and_metadata: Recorded in the manifest when not None (audio downloads only)
        allow_local_file_rename: Whether a file copied from the Volumio host is renamed
            after the template, instead of keeping the name it has there
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
            error("Cannot determine a file name for the download")
            sys.exit(1)
        if not allow_local_file_rename:
            filename = preserve_local_file_name(filename, uri)
        destination = os.path.join(output_directory, filename)  # type: ignore[arg-type]

    if not overwrite and os.path.exists(destination):
        error(
            f'File already exists: "{destination}" '
            "(use --overwrite-existing-files to overwrite)"
        )
        sys.exit(1)

    info(f'Downloading {label} to "{destination}"...')

    try:
        if output_directory is not None:
            os.makedirs(output_directory, exist_ok=True)
        fetch_uri_to_file(uri, destination, timeout, host_configuration)

        info(f'Downloading {label} to "{destination}"... done')

        # The name of a download into a directory comes from the template, so it can
        # carry an extension the content of the file disagrees with; an explicit
        # --output-file path is the one asked for, and is left alone
        if kind == "audio" and output_directory is not None and not is_local_file_uri(uri):
            destination = correct_audio_extension(destination, overwrite)

        info(f'{label.capitalize()} successfully downloaded to "{destination}"')

        if create_manifest:
            manifest_path = write_download_manifest(
                destination, uri, state, host_configuration, entity, kind, add_cover_and_metadata
            )
            debug(f'Manifest written to "{manifest_path}"')

    except (requests.exceptions.RequestException, VolumioSSHError) as e:
        error(f"Download error: {e}")
        sys.exit(1)
    except OSError as e:
        error(f"File write error: {e}")
        sys.exit(1)

    return destination


def echo_data(ctx: click.Context, output: str) -> None:
    """Print a rendered output, through the pager when enabled.

    Machine-readable output bypasses the pager.

    Args:
        ctx: Click context object containing shared options
        output: The rendered output to print
    """
    if ctx.obj.get("pager") and not ctx.obj["machine_readable"]:
        click.echo_via_pager(output)
    else:
        click.echo(output)


def embed_track_tags(
    destination: str,
    state: PlayerState,
    host_configuration: VolumioHostConfiguration,
    timeout: float,
    position_starting_at_one: bool,
    verbose: bool,
    machine_readable: bool,
    tracknumber: int | None = None,
) -> None:
    """Embed the current track metadata and cover art into a downloaded audio file.

    The metadata and cover come from ``state``. The embedded track number is the
    ``tracknumber`` argument when given (the track number from the queue metadata,
    used verbatim and passed by ``queue download``), then the one the state reports,
    falling back to ``position`` (indexed according to ``position_starting_at_one``). Any problem
    (an unsupported format, a cover-download failure, or a tagging error) is
    reported as a warning and otherwise ignored: the already-downloaded file is
    left in place.

    Args:
        destination: The downloaded audio file to tag, modified in place
        state: The current player state (source of the metadata)
        host_configuration: The Volumio host configuration (to resolve the cover URI)
        timeout: Request timeout for fetching the cover image, in seconds
        position_starting_at_one: Whether the embedded track number starts at one
        verbose: Whether to print progress messages
        machine_readable: Whether machine-readable mode is active (suppresses messages)
        tracknumber: The number of the track within its album, when known
    """
    number = tracknumber if tracknumber is not None else state.tracknumber
    if number is not None:
        track_number: int | None = number
    else:
        track_number = (
            display_position(state.position, position_starting_at_one)
            if state.position is not None
            else None
        )

    cover = fetch_cover(state, host_configuration, timeout, machine_readable)

    try:
        embed_metadata_and_cover(
            destination,
            title=state.title,
            artist=state.artist,
            album=state.album,
            albumartist=state.albumartist,
            track_number=track_number,
            cover=cover,
        )
    except UnsupportedAudioFormatError:
        warning(f'Cannot embed metadata into "{destination}" (unsupported format)')
        return
    except Exception as e:
        warning(f'Cannot embed metadata into "{destination}" ({e})')
        return

    debug(f'Embedded metadata and cover into "{destination}"')


def execute_command(
    ctx: click.Context,
    command_name: str,
    command_func: Callable[[APIClient], object],
) -> None:
    """Execute a playback control command.

    Args:
        ctx: Click context object containing shared options
        command_name: Name of the command (for messages)
        command_func: Function to call on the API client
    """
    url = connection_url(ctx)

    debug(f"Connecting to {url}...")

    try:
        client = get_client(ctx)
        response = command_func(client)

        debug(f"Connecting to {url}... done")
        if response is not None:
            debug(f"Response: {response}")

        info(f"Command '{command_name}' executed successfully")

    except VolumioConnectionError as e:
        error(f"Connection error: {e}")
        sys.exit(1)
    except VolumioAPIError as e:
        error(f"API error: {e}")
        sys.exit(1)
    except (VolumioAsyncError, VolumioWebSocketError, UnsupportedOperationError) as e:
        error(f"API client error: {e}")
        sys.exit(1)
    except Exception as e:  # pragma: no cover
        error(f"Unexpected error: {e}")
        sys.exit(1)


def execute_conditionally(
    ctx: click.Context,
    enabled: bool,
    command: click.Command,
    expected_status: str | None = None,
) -> None:
    """When enabled, wait the configured delay and invoke the given command.

    Args:
        ctx: Click context object (its ``obj`` is inherited by the invoked command)
        enabled: Whether to invoke the command
        command: The Click command to invoke
        expected_status: When set, re-read the playback status, up to the configured
            number of retries, until it matches this value before invoking the command
    """
    if enabled:
        sleep_between_api_calls(ctx)
        if expected_status is not None:
            retries = ctx.obj["retries_on_unexpected_state"]
            attempt = 0
            status = fetch_state_or_exit(ctx).status
            while status != expected_status and attempt < retries:
                attempt += 1
                debug(
                    f"Playback status '{status}' does not match the expected "
                    f"'{expected_status}', retrying ({attempt}/{retries})"
                )
                sleep_between_api_calls(ctx)
                status = fetch_state_or_exit(ctx).status
            if status != expected_status:
                warning(
                    f"Playback status '{status}' still does not match the expected "
                    f"'{expected_status}' after {retries} retries"
                )
        ctx.invoke(command)


@overload
def expand_output_directory(output_directory: str) -> str: ...


@overload
def expand_output_directory(output_directory: None) -> None: ...


def expand_output_directory(output_directory: str | None) -> str | None:
    """Expand the ``{timestamp}`` placeholder in an output directory path.

    Each occurrence of the placeholder is replaced with the current UTC time,
    formatted as ``YYYYMMDDHHMMSS``.

    Args:
        output_directory: The output directory path, or None if not given

    Returns:
        The expanded path, or None if ``output_directory`` is None
    """
    if output_directory is None:
        return None
    timestamp = datetime.now(UTC).strftime(OUTPUT_DIRECTORY_TIMESTAMP_FORMAT)
    return expand_timestamp_placeholder(output_directory, timestamp)


def fetch_cover(
    state: PlayerState,
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
        warning(f"Cannot fetch cover art ({e})")
        return None


def fetch_or_exit[T](
    ctx: click.Context,
    fetch: Callable[[APIClient], T],
) -> T:
    """Fetch data from the Volumio instance, printing errors and exiting (1) on failure.

    Args:
        ctx: Click context object containing shared options
        fetch: Function to call on the API client, returning the payload

    Returns:
        Whatever ``fetch`` returns (a response model for the JSON endpoints, text
        for ping)
    """
    url = connection_url(ctx)

    debug(f"Connecting to {url}...")

    try:
        client = get_client(ctx)
        fetched = fetch(client)
        debug(f"Connecting to {url}... done")
        return fetched
    except VolumioConnectionError as e:
        error(f"Connection error: {e}")
        sys.exit(1)
    except VolumioStoryError as e:
        error(f"Story error: {e}")
        sys.exit(1)
    except VolumioAPIError as e:
        error(f"API error: {e}")
        sys.exit(1)
    except (VolumioAsyncError, VolumioWebSocketError, UnsupportedOperationError) as e:
        error(f"API client error: {e}")
        sys.exit(1)
    except Exception as e:  # pragma: no cover
        error(f"Unexpected error: {e}")
        sys.exit(1)


def fetch_state_or_exit(ctx: click.Context) -> PlayerState:
    """Fetch the current state, printing errors and exiting (1) on failure.

    Args:
        ctx: Click context object containing shared options

    Returns:
        The playback state returned by the client
    """
    return fetch_or_exit(ctx, lambda c: c.state)


def fetch_uri_to_file(
    uri: str,
    destination: str,
    timeout: float,
    host_configuration: VolumioHostConfiguration,
) -> None:
    """Stream ``uri`` into the ``destination`` file.

    A URI naming a file of the Volumio host library (one without a scheme) is copied
    from the host over SCP; everything else is fetched over HTTP.

    Args:
        uri: The URI to download
        destination: The destination file path
        timeout: Request timeout in seconds
        host_configuration: The Volumio host configuration (used by the SCP copy)

    Raises:
        requests.exceptions.RequestException: If the HTTP request fails
        VolumioSSHError: If the file cannot be copied from the Volumio host
        OSError: If the destination file cannot be written
    """
    if is_local_file_uri(uri):
        copy_from_host(
            host_configuration, remote_music_path(uri), destination, timeout=timeout
        )
        return

    response = requests.get(uri, timeout=timeout, stream=True)
    response.raise_for_status()

    with open(destination, "wb") as f:
        for chunk in response.iter_content(chunk_size=FILE_WRITE_CHUNK_SIZE):
            f.write(chunk)


def get_client(ctx: click.Context) -> APIClient:
    """Return the API client of this invocation, created and opened on the first call.

    The client is kept in the context object, so every command and helper of the
    invocation shares it, and closed when the root context closes, that is when the
    tool exits, however it exits. A client that fails to open is not kept, so the
    next call tries again.

    Args:
        ctx: Click context object holding the shared options

    Returns:
        The open API client
    """
    client: APIClient | None = ctx.obj.get("client")
    if client is None:
        client = create_client(
            ctx.obj["host_configuration"],
            ctx.obj["rest_api_timeout"],
            ctx.obj["rest_api_timeout_slow_endpoints"],
            websocket_timeout=ctx.obj["websocket_timeout"],
            api_client=ctx.obj["api_client"],
            allow_fallback_to_rest_api=ctx.obj["allow_fallback_to_rest_api"],
            allow_fallback_to_websocket_api=ctx.obj["allow_fallback_to_websocket_api"],
        )
        debug(f"Using the {client.description}")
        client.open()
        ctx.obj["client"] = client
        ctx.find_root().call_on_close(client.close)
    return client


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
        help="Embed track metadata and cover art into the downloaded file.",
    )(func)


def option_album(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``-b``/``--album`` option to the collection search subcommand."""
    return click.option(
        "--album",
        "-b",
        type=str,
        default=None,
        help="Keep the results of this album, and search for it when no query is given.",
    )(func)


def option_albumart_file_name_template(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``--albumart-file-name-template`` option to the queue download subcommand."""
    return click.option(
        "--albumart-file-name-template",
        type=str,
        default="{file_name_from_uri}",
        show_default=True,
        help="Template, in Python str.format syntax, for the album art file names.",
    )(func)


def option_albums_only(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``-B``/``--albums-only`` option to the collection search subcommand."""
    return click.option(
        "--albums-only",
        "-B",
        is_flag=True,
        default=False,
        help="Keep the albums found, whatever the other options match.",
    )(func)


def option_all_notifications(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``-a``/``--all`` option to the notification unregister subcommand."""
    return click.option(
        "--all",
        "-a",
        "all_notifications",
        is_flag=True,
        default=False,
        help="Unregister every URL registered on the Volumio host.",
    )(func)


def option_allow_local_file_rename(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``--allow-local-file-rename`` option to an audio download subcommand."""
    return click.option(
        "--allow-local-file-rename/--no-allow-local-file-rename",
        default=False,
        show_default=True,
        help="Rename a file copied from the Volumio host after the file name template.",
    )(func)


def option_artist(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``-a``/``--artist`` option to the collection search subcommand."""
    return click.option(
        "--artist",
        "-a",
        type=str,
        default=None,
        help="Keep the results of this artist, and search for it when no query is given.",
    )(func)


def option_artists_only(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``-A``/``--artists-only`` option to the collection search subcommand."""
    return click.option(
        "--artists-only",
        "-A",
        is_flag=True,
        default=False,
        help="Keep the artists found, whatever the other options match.",
    )(func)


def option_audio_file_name_template(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``-f``/``--audio-file-name-template`` option to the queue download subcommand."""
    return click.option(
        "-f",
        "--audio-file-name-template",
        type=str,
        default="{file_name_from_uri}",
        show_default=True,
        help="Template, in Python str.format syntax, for the audio file names.",
    )(func)


def option_autocompose_url(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``-A``/``--autocompose-url`` option to a notification subcommand."""
    return click.option(
        "--autocompose-url",
        "-A",
        is_flag=True,
        default=False,
        help="Act on the URL composed from the port and the endpoint.",
    )(func)


def option_best_result_only(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``-1``/``--best-result-only`` option to the collection search subcommand."""
    return click.option(
        "--best-result-only",
        "-1",
        is_flag=True,
        default=False,
        help="Keep the best result of each list only, as -l/--limit 1 does.",
    )(func)


def option_by_uid(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``--by-uid`` option to the queue add subcommand."""
    return click.option(
        "--by-uid",
        is_flag=True,
        default=False,
        help="Read the arguments as identifiers of local library items, instead of a URI.",
    )(func)


def option_check_next_track(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``--check-next-track`` option to a queue/playlist download subcommand."""
    return click.option(
        "--check-next-track/--no-check-next-track",
        default=True,
        show_default=True,
        help="Check that the next track is selected before downloading it.",
    )(func)


def option_check_playlist_name(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``--check-playlist-name`` option to a playlist subcommand."""
    return click.option(
        "--check-playlist-name/--no-check-playlist-name",
        default=True,
        show_default=True,
        help="Check that the playlist name exists before playing it.",
    )(func)


def option_count(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``-n``/``--count`` option to the notification listen subcommand."""
    return click.option(
        "--count",
        "-n",
        type=int,
        default=None,
        help="Stop after receiving this number of notifications.",
    )(func)


def option_create_download_manifest(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``--create-download-manifest`` option to a track download subcommand."""
    return click.option(
        "--create-download-manifest/--no-create-download-manifest",
        default=True,
        show_default=True,
        help="Write a JSON manifest next to the downloaded file (e.g., out.flac.json).",
    )(func)


def option_cue_track(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``--cue-track`` option to the queue add and replace subcommands."""
    return click.option(
        "--cue-track",
        type=int,
        default=None,
        metavar="NUMBER",
        help=(
            "Read URI as a cue sheet, queue the track at this position of it, and play it "
            "(needs a WebSocket API client)."
        ),
    )(func)


def option_current_track(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``--current-track`` option to a story subcommand."""
    return click.option(
        "--current-track",
        is_flag=True,
        default=False,
        help=(
            "Use the metadata of the current track "
            "instead of the positional argument(s)."
        ),
    )(func)


def option_endpoint(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``-e``/``--endpoint`` option to the notification listen subcommand."""
    return click.option(
        "--endpoint",
        "-e",
        type=str,
        default=DEFAULT_ENDPOINT,
        show_default=True,
        help="Path served by the local notification listener.",
    )(func)


def option_fields(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``-L``/``--fields`` option to a display subcommand."""
    return click.option(
        "--fields",
        "-L",
        type=str,
        default=OUTPUT_FIELDS_SHORT,
        show_default=True,
        help="Fields to display: ALL, SHORT, or a comma-separated list of field names.",
    )(func)


def option_file_name_template(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``-f``/``--file-name-template`` option to a track download subcommand."""
    return click.option(
        "-f",
        "--file-name-template",
        type=str,
        default="{file_name_from_uri}",
        show_default=True,
        help="Template, in Python str.format syntax, for the output file names.",
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
        help="Output format.",
    )(func)


def option_format_table(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``-F``/``--format`` option, defaulting to the table, to a collection subcommand."""
    return click.option(
        "--format",
        "-F",
        "output_format",
        type=click.Choice(OUTPUT_FORMATS, case_sensitive=True),
        default="table",
        show_default=True,
        help="Output format.",
    )(func)


def option_idle_timeout(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``--idle-timeout`` option to the notification listen subcommand."""
    return click.option(
        "--idle-timeout",
        type=float,
        default=None,
        help="Stop after this number of seconds without receiving a notification.",
    )(func)


def option_item_album(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``--album`` option to the subcommands queuing a single item."""
    return click.option(
        "--album",
        type=str,
        default=None,
        help="The album to show for the queued item, when known (only with --next).",
    )(func)


def option_item_title(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``--title`` option to the subcommands queuing a single item."""
    return click.option(
        "--title",
        type=str,
        default=None,
        help="The title to show for the queued item, when known (only with --next).",
    )(func)


def option_limit(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``-l``/``--limit`` option to the collection search subcommand."""
    return click.option(
        "--limit",
        "-l",
        type=click.IntRange(min=1),
        default=None,
        help="Keep at most this number of results in each list.",
    )(func)


def option_manifest_file(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``--manifest-file`` option to a queue/playlist download subcommand."""
    return click.option(
        "--manifest-file",
        type=str,
        default=DEFAULT_MANIFEST_FILE,
        show_default=True,
        help="Write the download manifest to this file path; {output_directory} is "
        "replaced with the output directory, {timestamp} with the current UTC time.",
    )(func)


def option_next(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``--next`` option to the queue add subcommand."""
    return click.option(
        "--next",
        "play_next",
        is_flag=True,
        default=False,
        help="Queue URI as a single item right after the current track, without browsing it.",
    )(func)


def option_number_retries_next_track(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``--number-retries-next-track`` option to a queue/playlist download subcommand."""
    return click.option(
        "--number-retries-next-track",
        type=int,
        default=DEFAULT_NUMBER_RETRIES_NEXT_TRACK,
        show_default=True,
        help="Number of retries to attempt to make sure the next track is selected.",
    )(func)


def option_offset(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``-o``/``--offset`` option to a collection subcommand."""
    return click.option(
        "-o",
        "--offset",
        type=click.IntRange(min=0),
        default=None,
        help="Skip this number of results at the start of each list.",
    )(func)


def option_only_tracks(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``-T``/``--only-tracks`` option to a queue/playlist download subcommand."""
    return click.option(
        "--only-tracks",
        "-T",
        type=TrackSelectionParamType(),
        default=None,
        help="Download only the tracks at these queue positions (e.g., '1-3,6-8,12'); "
        "by default every track of the queue is downloaded.",
    )(func)


def option_output_directory(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``-d``/``--output-directory`` option to a track download subcommand."""
    return click.option(
        "-d",
        "--output-directory",
        type=str,
        default=None,
        help=(
            "Download into this directory, created if missing. "
            "Directory and file name templates will be interpolated. "
            "Mutually exclusive with -o."
        ),
    )(func)


def option_output_file(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``-o``/``--output-file`` option to a track download subcommand."""
    return click.option(
        "-o",
        "--output-file",
        type=str,
        default=None,
        help=(
            "Download to this exact file path. "
            "Mutually exclusive with -d."
        ),
    )(func)


def option_overwrite_existing_files(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``--overwrite-existing-files`` option to a download or create subcommand."""
    return click.option(
        "--overwrite-existing-files/--no-overwrite-existing-files",
        default=False,
        show_default=True,
        help="Overwrite the destination file if it already exists.",
    )(func)


def option_play(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``--play/--no-play`` option to the queue replace subcommand."""
    return click.option(
        "--play/--no-play",
        default=True,
        show_default=True,
        help="Start playing the replaced queue (from the -p/--position item), or only replace it.",
    )(func)


def option_play_added(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``--play`` option to the queue add subcommand."""
    return click.option(
        "--play",
        is_flag=True,
        default=False,
        help="Start playing the added content.",
    )(func)


def option_playlist(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``-y``/``--playlist`` option to the collection search subcommand."""
    return click.option(
        "--playlist",
        "-y",
        type=str,
        default=None,
        help="Search for this text and keep the playlists found for it.",
    )(func)


def option_playlists_only(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``-Y``/``--playlists-only`` option to the collection search subcommand."""
    return click.option(
        "--playlists-only",
        "-Y",
        is_flag=True,
        default=False,
        help="Keep the playlists found, whatever the other options match.",
    )(func)


def option_port(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``-p``/``--port`` option to a notification subcommand."""
    return click.option(
        "--port",
        "-p",
        type=int,
        default=DEFAULT_PORT,
        show_default=True,
        help="Port the local notification listener binds to.",
    )(func)


def option_position(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``-p``/``--position`` option to the queue replace subcommand."""
    return click.option(
        "-p",
        "--position",
        type=int,
        default=None,
        help=(
            "Play the item at this position among those URI lists (indexed according to "
            "--position-starting-at-one/--position-starting-at-zero); the first when not given."
        ),
    )(func)


def option_print_resulting_status(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``-r``/``--print-resulting-status`` option to a playback subcommand."""
    return click.option(
        "--print-resulting-status/--no-print-resulting-status",
        "-r",
        default=True,
        show_default=True,
        help="After executing the command, print the resulting playback status.",
    )(func)


def option_print_uri(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``-u``/``--print-uri`` option to the collection search subcommand."""
    return click.option(
        "--print-uri",
        "-u",
        is_flag=True,
        default=False,
        help="Print the URI of each result, under its line of the -F table output.",
    )(func)


def option_print_uri_toggle(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``--print-uri/--no-print-uri`` option to the collection browse subcommand."""
    return click.option(
        "--print-uri/--no-print-uri",
        default=True,
        show_default=True,
        help="Print the URI of each result, under its line of the -F table output.",
    )(func)


def option_propagate_remote_exit_code(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``--propagate-remote-exit-code`` option to the system execute subcommand."""
    return click.option(
        "--propagate-remote-exit-code/--no-propagate-remote-exit-code",
        default=True,
        show_default=True,
        help="Exit with the code the command returned on the Volumio host.",
    )(func)


def option_recursive(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``-r``/``--recursive`` option to an scp subcommand."""
    return click.option(
        "--recursive",
        "-r",
        is_flag=True,
        default=False,
        help="Copy a directory and its content.",
    )(func)


def option_register_url(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``--register-url`` option to the notification listen subcommand."""
    return click.option(
        "--register-url/--no-register-url",
        default=False,
        show_default=True,
        help="Register the URL on the Volumio host when it is not registered yet.",
    )(func)


def option_register_url_full(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``--register-url-full`` option to the notification listen subcommand."""
    return click.option(
        "--register-url-full",
        type=str,
        default=None,
        help="URL to register, overriding the one composed from --port and --endpoint.",
    )(func)


def option_replace_characters_in_file_names(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``--replace-characters-in-file-names`` option to a track download subcommand."""
    return click.option(
        "--replace-characters-in-file-names",
        type=str,
        default=DEFAULT_REPLACE_CHARACTERS_IN_FILE_NAMES,
        show_default=True,
        help="Characters to replace in the file name generated from -f/--file-name-template.",
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
            "--replace-characters-in-file-names."
        ),
    )(func)


def option_result_kinds(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``-k``/``--result-kinds`` option to the collection search subcommand."""
    return click.option(
        "--result-kinds",
        "-k",
        type=ResultKindsParamType(),
        default=None,
        help=(
            "Keep the results of these kinds only, comma-separated (e.g., 'album,track'); "
            "the other options then only say what to search for."
        ),
    )(func)


def option_service(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``-s``/``--service`` option to the collection search subcommand."""
    return click.option(
        "--service",
        "-s",
        type=click.Choice(SEARCH_SERVICES, case_sensitive=True),
        default=None,
        help="Keep the results of this source only.",
    )(func)


def option_service_of_uri(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``--service`` option to the subcommands taking the URI of a music service."""
    return click.option(
        "--service",
        type=str,
        default=None,
        help="The music service the URI belongs to, derived from the URI when not given.",
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
            "How to interpret the positional argument(s): "
            "autodetect, mbid, or name (free string)."
        ),
    )(func)


def option_timeout(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``--timeout`` option to the notification listen subcommand."""
    return click.option(
        "--timeout",
        type=float,
        default=None,
        help="Stop after listening for this number of seconds.",
    )(func)


def option_track(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``-t``/``--track`` option to the collection search subcommand."""
    return click.option(
        "--track",
        "-t",
        type=str,
        default=None,
        help="Keep the tracks with this title, and search for it when no query is given.",
    )(func)


def option_tracks_only(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``-T``/``--tracks-only`` option to the collection search subcommand."""
    return click.option(
        "--tracks-only",
        "-T",
        is_flag=True,
        default=False,
        help="Keep the tracks found, whatever the other options match.",
    )(func)


def option_unregister_url_on_exit(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``--unregister-url-on-exit`` option to the notification listen subcommand."""
    return click.option(
        "--unregister-url-on-exit/--no-unregister-url-on-exit",
        default=True,
        show_default=True,
        help="On exit, unregister the URL registered by this run.",
    )(func)


def option_with_albumart(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``--with-albumart`` option to a queue/playlist download subcommand."""
    return click.option(
        "--with-albumart/--no-with-albumart",
        default=True,
        show_default=True,
        help="Download the album art of each album in the queue/playlist.",
    )(func)


def option_yes(func: Callable[..., None]) -> Callable[..., None]:
    """Add the ``-y``/``--yes`` option to a subcommand acting on the Volumio host."""
    return click.option(
        "--yes/--no-yes",
        "-y",
        default=False,
        show_default=True,
        help="Really perform the operation on the Volumio host.",
    )(func)


def read_queue_log(path: str) -> dict[str, Any] | None:
    """Read an existing download manifest file.

    Args:
        path: The manifest file path

    Returns:
        The parsed manifest mapping, or None if the file cannot be read or parsed,
        or does not hold a mapping with a "tracks" list of mappings
    """
    try:
        with open(path, encoding="utf-8") as log_file:
            data = json.load(log_file)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    tracks = data.get("tracks")
    if not isinstance(tracks, list) or not all(isinstance(track, dict) for track in tracks):
        return None
    return data


def render_fields(
    ctx: click.Context,
    data: dict[str, Any],
    fields: str,
    output_format: str,
    short_fields: list[str],
    heading: str,
) -> None:
    """Print a payload per the fields/format options.

    The fields and formats are defined over the field names the Volumio host
    returns, so ``data`` is expected to be (or to wrap) a raw payload.

    Args:
        ctx: Click context object containing shared options
        data: The payload to print
        fields: The fields option ("short" or "all")
        output_format: The output format ("json", "pretty", "raw", or "table")
        short_fields: The list of keys to keep when ``fields`` is "short"
        heading: The heading line for the table output format
    """
    position_starting_at_one = ctx.obj["position_starting_at_one"]

    # Determine output format
    if output_format == "raw":
        # Raw JSON without formatting (ignores fields filter)
        output = json.dumps(data)
    else:
        # Apply fields filter for all formatted outputs
        filtered = filter_fields(data, fields, short_fields)

        if output_format == "table":
            # Preserve the requested field order (and labels) in the table; None => all
            field_order = resolve_output_fields(fields, short_fields)
            output = format_as_table(
                filtered,
                heading=heading,
                field_order=field_order,
                position_starting_at_one=position_starting_at_one,
            )
        elif output_format == "json":
            output = format_as_json(filtered)
        else:  # pretty
            output = format_as_pretty(filtered, position_starting_at_one)

    echo_data(ctx, output)


def render_output_filename(
    template: str,
    uri: str,
    state: PlayerState,
    default_extension: str,
    position_starting_at_one: bool = True,
    replace_characters_in_file_names: str = DEFAULT_REPLACE_CHARACTERS_IN_FILE_NAMES,
    replace_characters_in_file_names_with: str = DEFAULT_REPLACE_CHARACTERS_IN_FILE_NAMES_WITH,
    allow_subdirectories: bool = False,
    option_label: str = "--file-name-template",
    album_volume: str = "",
    tracknumber: int | None = None,
) -> str:
    """Render a safe output file name from a template, track metadata, and the URI.

    The template uses Python ``str.format`` syntax. Supported keys are:
    ``file_name_from_uri``, ``position`` (int, indexed according to
    ``position_starting_at_one``), ``tracknumber`` (int, the track number of the
    track, taken verbatim from the ``tracknumber`` argument, which ``queue download``
    fills from the queue metadata), ``title``, ``album``, ``album_volume``
    (the album name with ``/<volumeNumber>`` appended for multi-volume albums, given
    by the ``album_volume`` argument of ``queue download``; its path separator is
    preserved, so the key is meant for subdirectory-capable templates), ``artist``,
    ``trackType``, ``duration`` (HH:MM:SS), ``bitdepth``, ``samplerate``,
    ``channels`` (int), and ``extension``. The ``extension`` is
    taken from the URI file name, falling back to ``default_extension`` when the
    URI file has none; it is the extension the name is rendered with, which an audio
    download then corrects to the format of the file it received, when they disagree
    (see ``correct_audio_extension``).

    The name is rendered defensively, since the metadata values and the URI are
    untrusted: template fields must be exactly the supported keys (no attribute or
    index access), path separators in the interpolated values are replaced and
    control characters removed, leading dots are stripped from the result, and the
    rendered name must be a plain file name without path separators, unless
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
        state: The current player state (source of the metadata values)
        default_extension: Extension to use when the URI file has none (no leading dot)
        position_starting_at_one: Whether the ``position`` key starts at one
        replace_characters_in_file_names: Characters replaced in the rendered name
        replace_characters_in_file_names_with: Replacement for the replaced characters
        allow_subdirectories: Whether template-literal path separators are allowed
        option_label: Name of the template option, used in the error messages
        album_volume: The album/volume path component of the track being downloaded
        tracknumber: The number of the track within its album, when known

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

    def as_text(value: str | None) -> str:
        text = value.strip() if value is not None else ""
        return sanitize_filename_component(text, replacement)

    number = tracknumber if tracknumber is not None else state.tracknumber
    file_name_from_uri = sanitize_filename_component(extract_filename_from_uri(uri), replacement)
    uri_extension = os.path.splitext(file_name_from_uri)[1].lstrip(".")

    # Sanitize the album/volume value per component, keeping its deliberate separator
    album_volume_component = "/".join(
        sanitize_filename_component(part, replacement) for part in album_volume.split("/")
    )

    keys: dict[str, object] = {
        "file_name_from_uri": file_name_from_uri,
        "position": display_position(state.position or 0, position_starting_at_one),
        "tracknumber": number or 0,
        "title": as_text(state.title),
        "album": as_text(state.album),
        "album_volume": album_volume_component,
        "artist": as_text(state.artist),
        "trackType": as_text(state.track_type),
        "duration": format_duration(state.duration) if state.duration is not None else "",
        "bitdepth": as_text(state.bitdepth),
        "samplerate": as_text(state.samplerate),
        "channels": state.channels or 0,
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
    verbatim_labels: bool = False,
) -> None:
    """Print a JSON payload per the format option, or compact in machine-readable mode.

    Args:
        ctx: Click context object containing shared options
        data: The JSON object to print
        output_format: The output format ("json", "pretty", "raw", or "table")
        heading: The heading line for the table output format
        verbatim_labels: When True, the table format prints the keys as they are
            instead of title-casing them
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
            verbatim_labels=verbatim_labels,
        )
    else:  # pretty
        output = format_as_pretty(data, ctx.obj["position_starting_at_one"])

    echo_data(ctx, output)


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
    state = fetch_state_or_exit(ctx).raw

    debug("Successfully retrieved state")

    render_fields(ctx, state, fields, output_format, short_fields, heading)


def render_story(
    ctx: click.Context,
    fetch: Callable[[APIClient], Story],
    fields: str,
    output_format: str,
    heading: str,
) -> None:
    """Fetch a metavolumio story and print it per the fields/format options.

    A failed query is reported as an error (exit code 1) by ``fetch_or_exit``. The
    response envelope of a successful query is rendered like the other query
    commands, honoring the fields and format options.

    Args:
        ctx: Click context object containing shared options
        fetch: Function querying the story on the VolumioRESTAPIClient (e.g., calling
            its get_story or get_album_credits method)
        fields: The fields option ("short" or "all")
        output_format: The output format ("json", "pretty", "raw", or "table")
        heading: The heading line for the table output format
    """
    position_starting_at_one = ctx.obj["position_starting_at_one"]

    response = fetch_or_exit(ctx, fetch).raw

    debug("Successfully retrieved story")

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

    echo_data(ctx, output)


def resolve_output_conflict(
    ctx: click.Context, output_file: str | None, output_directory: str | None
) -> tuple[str | None, str | None]:
    """Resolve -o/--output-file vs -d/--output-directory, honoring precedence.

    When both are set but only one was given explicitly on the command line
    (the other coming from the configuration file), the explicit one wins and
    the configured one is dropped. When both are explicit, or both come from
    the configuration file, raise the usual mutual-exclusivity UsageError.

    Args:
        ctx: Click context object (source of the parameter provenance)
        output_file: The -o/--output-file value, or None
        output_directory: The -d/--output-directory value, or None

    Returns:
        The (output_file, output_directory) pair with at most one value set

    Raises:
        click.UsageError: If both destinations are explicit, or both configured
    """
    if output_file is None or output_directory is None:
        return output_file, output_directory
    file_explicit = ctx.get_parameter_source("output_file") == ParameterSource.COMMANDLINE
    directory_explicit = ctx.get_parameter_source("output_directory") == ParameterSource.COMMANDLINE
    if file_explicit and not directory_explicit:
        return output_file, None
    if directory_explicit and not file_explicit:
        return None, output_directory
    raise click.UsageError(MUTUALLY_EXCLUSIVE_OUTPUT_ERROR)


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
        entity_class: The entity class (e.g., Artist, Label, or Place)
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


def resolve_command_path(
    root: click.Group, ctx: click.Context, path: str
) -> click.Command | None:
    """Resolve a space-separated command path against the command tree.

    Only built-in names are followed, so an alias cannot target another alias.

    Args:
        root: The top-level command group
        ctx: Click context used by the lookups
        path: The command path (e.g., "track albumart")

    Returns:
        The command the path leads to, or None when it does not resolve
    """
    command: click.Command | None = root
    for token in path.split():
        if not isinstance(command, click.Group):
            return None
        command = click.Group.get_command(command, ctx, token)
        if command is None:
            return None
    return command if command is not root else None


def sleep_between_api_calls(ctx: click.Context) -> None:
    """Sleep for the configured delay before making the next API call.

    Args:
        ctx: Click context object holding the shared options
    """
    time.sleep(ctx.obj["sleep_before_next_api_call"])


def write_download_manifest(
    destination: str,
    uri: str,
    state: PlayerState,
    host_configuration: VolumioHostConfiguration,
    entity: str,
    kind: str,
    add_cover_and_metadata: bool | None,
    extra_state: dict[str, Any] | None = None,
) -> str:
    """Write the ``<destination>.json`` manifest describing a download.

    Args:
        destination: The path the URI was downloaded to
        uri: The downloaded URI
        state: The current player state, recorded as the payload the host returned
        host_configuration: The Volumio host configuration
        entity: The manifest ``entity`` value (e.g., "track")
        kind: The manifest ``kind`` value (e.g., "audio" or "albumart")
        add_cover_and_metadata: Recorded in the manifest when not None
        extra_state: Values recorded in the state alongside the payload (the album
            volume and track number computed by ``queue download``)

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
        "state": {**state.raw, **(extra_state or {})},
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
