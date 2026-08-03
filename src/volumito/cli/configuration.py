"""Configuration-file loading for the volumito CLI.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

import os
from importlib.resources import files
from typing import Any

import click
import yaml

from volumito.cli.constants import MPD_PORT_VOLUMIO_4

ACTION_COMMAND_PATHS: list[list[str]] = (
    [
        ["playback", name]
        for name in (
            "mute",
            "next",
            "pause",
            "play",
            "previous",
            "seek",
            "stop",
            "toggle",
            "unmute",
            "volume",
        )
    ] +
    [
        ["playlist", "download"],
        ["playlist", "play"],
    ] +
    [
        ["queue", name]
        for name in (
            "clear",
            "randomize",
            "repeat",
        )
    ]
)
"""--print-resulting-status lives on the playback and queue action commands."""

CONFIGURATION_FILENAMES: list[str] = [
    "volumito.yaml",
    ".volumito.yaml",
]
"""Configuration file names tried within each directory, in this order."""

DEFAULT_CONFIGURATION_TEMPLATE: str = "volumito.yaml.template"
"""File name of the packaged default-configuration template (in the cli "res" directory)."""

DISPLAY_KEYS: list[str] = [
    "fields",
    "format",
]
"""The display option keys (fields and format) shared by the display subsections."""

FORMAT_KEYS: list[str] = [
    "format",
]
"""Commands accepting only --format, not --fields."""

DISPLAY_SUBSECTION_KEYS: dict[str, list[str]] = {
    "playback-status": DISPLAY_KEYS,
    "track-info": DISPLAY_KEYS,
    "queue-get": DISPLAY_KEYS,
    "playlist-list": FORMAT_KEYS,
    "zones-get": DISPLAY_KEYS,
    "system-version": FORMAT_KEYS,
    "system-info": FORMAT_KEYS,
    "collection-statistics": FORMAT_KEYS,
    "story-album": DISPLAY_KEYS,
    "story-artist": DISPLAY_KEYS,
    "story-credits": DISPLAY_KEYS,
    "story-label": DISPLAY_KEYS,
    "story-place": DISPLAY_KEYS,
}
"""Display subsection name -> the keys it accepts."""

DISPLAY_SUBSECTIONS: list[str] = list(DISPLAY_SUBSECTION_KEYS)
"""The display subsection names, in the order the keys map defines them."""

DISPLAY_SUBSECTION_PATHS: dict[str, list[list[str]]] = {
    "collection-statistics": [
        ["collection", "statistics"],
    ],
    "playback-status": [
        ["playback", "status"],
    ],
    "playlist-list": [
        ["playlist", "list"],
    ],
    "queue-get": [
        ["queue", "get"],
    ],
    "story-album": [
        ["story", "album"],
    ],
    "story-artist": [
        ["story", "artist"],
    ],
    "story-credits": [
        ["story", "credits"],
    ],
    "story-label": [
        ["story", "label"],
    ],
    "story-place": [
        ["story", "place"],
    ],
    "system-info": [
        ["system", "info"],
        ["info"],
    ],
    "system-version": [
        ["system", "version"],
    ],
    "track-info": [
        ["track", "info"],
    ],
    "zones-get": [
        ["zones", "get"],
    ],
}
"""Hierarchical subsection name -> the default_map path(s) of the command(s) it targets."""

DOWNLOAD_KEYS: list[str] = [
    "create-download-manifest",
    "file-name-template",
    "output-directory",
    "output-file",
    "overwrite-existing-files",
    "replace-characters-in-file-names",
    "replace-characters-in-file-names-with",
]
"""The "downloads" section is hierarchical: its scalar keys are shared by both track
download commands, and optional "audio"/"albumart" subsections (mapping to the
"track audio"/"track albumart" commands) override the shared values per command.
"""

QUEUE_DOWNLOAD_KEYS: list[str] = [
    "albumart-file-name-template",
    "audio-file-name-template",
    "create-download-manifest",
    "number-retries-next-track",
    "output-directory",
    "overwrite-existing-files",
    "replace-characters-in-file-names",
    "replace-characters-in-file-names-with",
    "with-albumart",
]
"""The keys accepted by the "queue-download" subsection (kept before the shared-keys
and subsection maps that reference it): the audio template has its own name, and
there is no output-file since the command has no -o option.
"""

DOWNLOAD_SHARED_KEYS: list[str] = sorted({*DOWNLOAD_KEYS, *QUEUE_DOWNLOAD_KEYS})
"""The keys accepted directly under "downloads": a shared value flows only into the
subsections (commands) that accept the key.
"""

DOWNLOAD_SUBSECTIONS: list[str] = [
    "track-audio",
    "track-albumart",
    "queue-download",
    "playlist-download",
]
"""The download subsection names (the download commands)."""

DOWNLOAD_SUBSECTION_KEYS: dict[str, list[str]] = {
    "playlist-download": QUEUE_DOWNLOAD_KEYS,
    "queue-download": QUEUE_DOWNLOAD_KEYS,
    "track-albumart": DOWNLOAD_KEYS,
    "track-audio": DOWNLOAD_KEYS,
}
"""Each download subsection mapped to the keys it accepts."""

DOWNLOAD_SUBSECTION_PATHS: dict[str, list[list[str]]] = {
    "playlist-download": [
        ["playlist", "download"],
    ],
    "queue-download": [
        ["queue", "download"],
    ],
    "track-albumart": [
        ["track", "albumart"],
    ],
    "track-audio": [
        ["track", "audio"],
    ],
}
"""Download subsection name -> the default_map path(s) of the command(s) it targets."""

GLOBAL_OUTPUT_KEYS: list[str] = [
    "machine-readable",
    "position-starting-at-one",
    "verbose",
]
"""Keys of the "output" section mapping to a global (top-level group) option."""

OUTPUT_SCALAR_KEYS: list[str] = [
    "verbose",
    "machine-readable",
    "position-starting-at-one",
    "fields",
    "format",
    "print-resulting-status",
]
"""The "output" section is hierarchical: its scalar keys are shared, and optional
per-command subsections override the display keys (fields/format). verbose,
machine-readable, and position-starting-at-one are global; print-resulting-status
applies to the playback and queue action commands.
"""

HIERARCHICAL_SPECS: dict[str, tuple[list[str], dict[str, list[str]]]] = {
    "downloads": (DOWNLOAD_SHARED_KEYS, DOWNLOAD_SUBSECTION_KEYS),
    "output": (OUTPUT_SCALAR_KEYS, DISPLAY_SUBSECTION_KEYS),
}
"""Per hierarchical section: (allowed shared scalar keys, per-subsection allowed keys).
Used for validation of the "output" and "downloads" sections.
"""

KEY_PARAM_OVERRIDES: dict[str, str] = {
    "format": "output_format",
}
"""Config keys whose CLI parameter name differs from key.replace("-", "_")."""

MISCELLANEOUS_KEY_PATHS: dict[str, list[list[str]]] = {
    "add-cover-and-metadata": [
        ["playlist", "download"],
        ["queue", "download"],
        ["track", "audio"],
    ],
    "check-next-track": [
        ["playlist", "download"],
        ["queue", "download"],
    ],
    "check-playlist-name": [
        ["playlist", "download"],
        ["playlist", "play"],
    ],
    "check-seek-position": [
        ["playback", "seek"],
    ],
}
"""The "miscellaneous" section holds the keys of options living on a specific command:
key -> the default_map path(s) of the command(s) it targets.
"""

SECTION_KEYS: dict[str, list[str]] = {
    "volumio": [
        "host",
        "scheme",
        "rest-api-port",
        "mpd-port",
    ],
    "timeouts": [
        "rest-api-timeout",
        "mpd-timeout",
        "rest-api-sleep-before-next-call",
    ],
    "miscellaneous": list(MISCELLANEOUS_KEY_PATHS),
}
"""Recognized flat section names and their allowed (hyphenated) keys, in display order.
Keys mirror the CLI long options minus the leading "--".
"""

RECOGNIZED_SECTIONS: list[str] = [
    *SECTION_KEYS,
    "downloads",
    "output",
]
"""Every recognized top-level section."""

RESOURCE_DIRECTORY: str = "res"
"""Name of the package subdirectory holding bundled resource files."""

VERSION_PLACEHOLDER: str = "{VERSION}"
"""Sentinel in the template header replaced with the running version at emit time."""


def _apply_hierarchical(
    result: dict[str, Any],
    shared: dict[str, Any],
    values: dict[str, Any],
    subsection_paths: dict[str, list[list[str]]],
    subsection_keys: dict[str, list[str]],
) -> None:
    """Place ``{**shared, **subsection}`` into each subsection's command path(s).

    Only the keys accepted by a subsection are taken from the shared values, so a
    shared key is not propagated to commands that do not have the matching option.
    """
    for subsection, paths in subsection_paths.items():
        allowed = subsection_keys[subsection]
        merged = {
            **{key: value for key, value in shared.items() if key in allowed},
            **values.get(subsection, {}),
        }
        for key, value in merged.items():
            for path in paths:
                _assign_nested(result, path, _param_name(key), value)


def _assign_nested(result: dict[str, Any], path: list[str], param: str, value: object) -> None:
    """Write ``result[path...][param] = value``, creating intermediate dicts."""
    node = result
    for part in path[:-1]:
        node = node.setdefault(part, {})
    node.setdefault(path[-1], {})[param] = value


def _param_name(key: str) -> str:
    """Return the CLI parameter name for a configuration key."""
    return KEY_PARAM_OVERRIDES.get(key, key.replace("-", "_"))


def _validate_flat_keys(
    section: str, values: dict[str, Any], allowed: list[str], path: str
) -> None:
    """Raise BadParameter if any key in a flat mapping is not allowed."""
    for key in values:
        if key not in allowed:
            raise click.BadParameter(
                f"unknown key {key!r} in section {section!r} of configuration file {path}"
            )


def _validate_hierarchical(
    name: str,
    values: dict[str, Any],
    scalar_keys: list[str],
    subsection_keys: dict[str, list[str]],
    path: str,
) -> dict[str, Any]:
    """Validate a hierarchical section (shared scalars + per-command subsections)."""
    result: dict[str, Any] = {}
    for key, value in values.items():
        if key in subsection_keys:
            if value is None:
                continue
            if not isinstance(value, dict):
                raise click.BadParameter(
                    f"section '{name}.{key}' in configuration file {path} must be a mapping"
                )
            _validate_flat_keys(f"{name}.{key}", value, subsection_keys[key], path)
            result[key] = dict(value)
        elif key in scalar_keys:
            result[key] = value
        else:
            raise click.BadParameter(
                f"unknown key {key!r} in section {name!r} of configuration file {path}"
            )
    return result


def build_click_default_map(config: dict[str, Any]) -> dict[str, Any]:
    """Turn a validated nested configuration into a Click ``default_map``.

    Global option values stay at the top level; per-command options are placed in the
    nested slot of every command that accepts them, since Click reads ``default_map``
    hierarchically by group/subcommand name.
    """
    result: dict[str, Any] = {}

    for section in ("volumio", "timeouts"):
        for key, value in config.get(section, {}).items():
            result[_param_name(key)] = value

    # The miscellaneous keys map to options living on a specific command, not to
    # options of the top-level group
    for key, value in config.get("miscellaneous", {}).items():
        for command_path in MISCELLANEOUS_KEY_PATHS[key]:
            _assign_nested(result, command_path, _param_name(key), value)

    output = config.get("output", {})
    for key, value in output.items():
        if key in GLOBAL_OUTPUT_KEYS:
            result[_param_name(key)] = value
        elif key == "print-resulting-status":
            for command_path in ACTION_COMMAND_PATHS:
                _assign_nested(result, command_path, _param_name(key), value)
    shared_display = {k: v for k, v in output.items() if k in DISPLAY_KEYS}
    _apply_hierarchical(
        result, shared_display, output, DISPLAY_SUBSECTION_PATHS, DISPLAY_SUBSECTION_KEYS
    )

    downloads = config.get("downloads", {})
    shared_download = {k: v for k, v in downloads.items() if k in DOWNLOAD_SHARED_KEYS}
    _apply_hierarchical(
        result, shared_download, downloads, DOWNLOAD_SUBSECTION_PATHS, DOWNLOAD_SUBSECTION_KEYS
    )

    return result


def configuration_directories() -> list[str]:
    """Return the directories probed for a configuration file, highest priority first.

    The order is: the current working directory, the current user's home directory,
    ``~/.volumito``, and ``~/.config/volumito``. On POSIX systems (Linux, macOS) the
    system directories ``/etc`` and ``/etc/volumito`` are appended as the lowest-priority
    locations; they are omitted on non-POSIX systems (e.g., Windows) where they make no sense.
    """
    home = os.path.expanduser("~")
    directories = [
        os.getcwd(),
        home,
        os.path.join(home, ".volumito"),
        os.path.join(home, ".config", "volumito"),
    ]
    if os.name == "posix":
        directories.append("/etc")
        directories.append(os.path.join("/etc", "volumito"))
    return directories


def configuration_paths() -> list[str]:
    """Return the configuration file paths, in search order.

    Each directory from :func:`configuration_directories` is probed for
    ``volumito.yaml`` and then ``.volumito.yaml`` before moving on to the next.
    """
    return [
        os.path.join(directory, filename)
        for directory in configuration_directories()
        for filename in CONFIGURATION_FILENAMES
    ]


def default_configuration_template(version: str, mpd_port: int = MPD_PORT_VOLUMIO_4) -> str:
    """Return the bundled default-configuration template, ready to write out.

    The template lives beside this package under ``res/`` and is read via
    :mod:`importlib.resources` so it works from both the source tree and an installed
    package. The ``{VERSION}`` sentinel in its header is replaced with ``version``, and
    the template's default MPD port (Volumio 4) is replaced with ``mpd_port``. Both use a
    literal :meth:`str.replace`, not :meth:`str.format`, since the body contains other
    ``{...}`` placeholders such as ``{position:03d}``.
    """
    template_path = files(__package__) / RESOURCE_DIRECTORY / DEFAULT_CONFIGURATION_TEMPLATE
    text = template_path.read_text(encoding="utf-8")
    text = text.replace(VERSION_PLACEHOLDER, version)
    text = text.replace(f"mpd-port: {MPD_PORT_VOLUMIO_4}", f"mpd-port: {mpd_port}")
    return text


def flatten_configuration(config: dict[str, Any]) -> list[tuple[str, Any]]:
    """Flatten a validated configuration into ordered ``(dotted-path, value)`` pairs.

    Used to display the values read from a configuration file. Only present keys are
    included, in canonical section/key order.
    """
    pairs: list[tuple[str, Any]] = []
    for section, keys in SECTION_KEYS.items():
        values = config.get(section, {})
        pairs.extend((f"{section}.{key}", values[key]) for key in keys if key in values)
    output = config.get("output", {})
    pairs.extend((f"output.{key}", output[key]) for key in OUTPUT_SCALAR_KEYS if key in output)
    for subsection in DISPLAY_SUBSECTIONS:
        subvalues = output.get(subsection, {})
        pairs.extend(
            (f"output.{subsection}.{key}", subvalues[key])
            for key in DISPLAY_KEYS
            if key in subvalues
        )
    downloads = config.get("downloads", {})
    pairs.extend(
        (f"downloads.{key}", downloads[key]) for key in DOWNLOAD_SHARED_KEYS if key in downloads
    )
    for subsection in DOWNLOAD_SUBSECTIONS:
        subvalues = downloads.get(subsection, {})
        pairs.extend(
            (f"downloads.{subsection}.{key}", subvalues[key])
            for key in DOWNLOAD_SUBSECTION_KEYS[subsection]
            if key in subvalues
        )
    return pairs


def load_configuration(path: str) -> dict[str, Any]:
    """Read and validate a configuration file into a nested, by-section mapping.

    The returned dict mirrors the recognized file structure, keyed by config keys
    (hyphenated), holding only present keys, e.g.
    ``{"volumio": {"host": ...}, "downloads": {"output-directory": ..., "audio": {...}}}``.
    Unknown sections/keys, a non-mapping document/section, or invalid YAML raise
    :class:`click.BadParameter`. An empty file yields an empty mapping.
    """
    try:
        with open(path, encoding="utf-8") as config_file:
            data = yaml.safe_load(config_file)
    except UnicodeDecodeError as error:
        raise click.BadParameter(
            f"configuration file {path} is not a valid YAML file"
        ) from error
    except (OSError, yaml.YAMLError) as error:
        raise click.BadParameter(f"cannot read configuration file {path}: {error}") from error

    if data is None:
        return {}
    if not isinstance(data, dict):
        raise click.BadParameter(
            f"configuration file {path} must contain a mapping at the top level"
        )

    config: dict[str, Any] = {}
    for section, values in data.items():
        if section not in RECOGNIZED_SECTIONS:
            raise click.BadParameter(
                f"unknown section {section!r} in configuration file {path}"
            )
        if values is None:
            continue
        if not isinstance(values, dict):
            raise click.BadParameter(
                f"section {section!r} in configuration file {path} must be a mapping"
            )
        if section in HIERARCHICAL_SPECS:
            scalar_keys, subsection_keys = HIERARCHICAL_SPECS[section]
            config[section] = _validate_hierarchical(
                section, values, scalar_keys, subsection_keys, path
            )
        else:
            _validate_flat_keys(section, values, SECTION_KEYS[section], path)
            config[section] = dict(values)
    return config


def probe_configuration_paths() -> list[tuple[str, bool, bool]]:
    """Return every probed path with (exists, used) flags, in probing order.

    ``used`` is True only for the first existing path (the one that would be loaded).
    """
    rows: list[tuple[str, bool, bool]] = []
    used_assigned = False
    for path in configuration_paths():
        exists = os.path.isfile(path)
        is_used = exists and not used_assigned
        if is_used:
            used_assigned = True
        rows.append((path, exists, is_used))
    return rows


def resolve_configuration_path(explicit: str | None) -> str | None:
    """Resolve which configuration file to read, if any.

    If ``explicit`` is given, it must point to an existing file (otherwise a
    :class:`click.BadParameter` is raised). Otherwise the search paths are
    tried in order and the first existing one is returned, or ``None`` if
    none exists.
    """
    if explicit is not None:
        if not os.path.isfile(explicit):
            raise click.BadParameter(f"configuration file not found: {explicit}")
        return explicit
    for path in configuration_paths():
        if os.path.isfile(path):
            return path
    return None
