"""Configuration-file loading for the volumito CLI.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

import os
from typing import Any

import click
import yaml

# Recognized flat section names and their allowed (hyphenated) keys, in display order.
# Keys mirror the CLI long options minus the leading "--".
SECTION_KEYS: dict[str, list[str]] = {
    "volumio": ["host", "scheme", "rest-api-port", "mpd-port"],
    "timeouts": ["rest-api-timeout", "mpd-timeout", "rest-api-sleep-before-next-call"],
}

# The "output" section is hierarchical: its scalar keys are shared, and optional
# per-command subsections override the display keys (fields/format/raw). verbose and
# machine-readable are global; print-resulting-status applies to the playback actions.
OUTPUT_SCALAR_KEYS = [
    "verbose",
    "machine-readable",
    "fields",
    "format",
    "raw",
    "print-resulting-status",
]
DISPLAY_KEYS = ["fields", "format", "raw"]
DISPLAY_SUBSECTIONS = ["playback-status", "track-info", "queue-list"]

# The "downloads" section is hierarchical: its scalar keys are shared by both track
# download commands, and optional "audio"/"albumart" subsections (mapping to the
# "track audio"/"track albumart" commands) override the shared values per command.
DOWNLOAD_KEYS = [
    "file-name-template",
    "output-directory",
    "output-file",
    "overwrite-existing-files",
]
DOWNLOAD_SUBSECTIONS = ["track-audio", "track-albumart"]

# Every recognized top-level section.
RECOGNIZED_SECTIONS = [*SECTION_KEYS, "output", "downloads"]

# One-line description of each key, used as a comment in the generated file.
KEY_COMMENTS: dict[str, str] = {
    "host": "Hostname or IP address of the Volumio instance",
    "scheme": "URL scheme used to connect: http or https",
    "rest-api-port": "REST API port of the Volumio instance",
    "mpd-port": "MPD port of the Volumio instance",
    "rest-api-timeout": "REST API request timeout, in seconds",
    "mpd-timeout": "MPD connection timeout, in seconds",
    "rest-api-sleep-before-next-call": "Seconds to sleep before the next REST API call",
    "verbose": "Enable verbose output",
    "machine-readable": "Produce machine-readable output only",
    "fields": "Fields to display: short or all",
    "format": "Output format: json, pretty, or table",
    "raw": "Output raw JSON, overriding the format",
    "print-resulting-status": (
        "After a playback command like pause or volume, print the resulting playback status"
    ),
    "file-name-template": "Template (Python str.format) for the -d output file name",
    "output-directory": "Directory to download into (mutually exclusive with output-file)",
    "output-file": "Exact file path to download to (mutually exclusive with output-directory)",
    "overwrite-existing-files": "Overwrite the destination file if it already exists",
}

# Config keys whose CLI parameter name differs from key.replace("-", "_").
_KEY_PARAM_OVERRIDES = {"format": "output_format"}

# --print-resulting-status lives on the playback action commands.
ACTION_COMMAND_PATHS = [
    ["playback", name]
    for name in ("toggle", "play", "pause", "stop", "next", "previous", "volume", "mute", "unmute")
]

# Hierarchical subsection name -> the default_map path(s) of the command(s) it targets.
# The "playback-status" subsection also governs the top-level "info" synonym.
DISPLAY_SUBSECTION_PATHS = {
    "playback-status": [["playback", "status"], ["info"]],
    "track-info": [["track", "info"]],
    "queue-list": [["queue", "list"]],
}
DOWNLOAD_SUBSECTION_PATHS = {
    "track-audio": [["track", "audio"]],
    "track-albumart": [["track", "albumart"]],
}

# Per hierarchical section: (allowed shared scalar keys, subsection names, allowed
# subsection keys). Used for validation of the "output" and "downloads" sections.
_HIERARCHICAL_SPECS: dict[str, tuple[list[str], list[str], list[str]]] = {
    "output": (OUTPUT_SCALAR_KEYS, DISPLAY_SUBSECTIONS, DISPLAY_KEYS),
    "downloads": (DOWNLOAD_KEYS, DOWNLOAD_SUBSECTIONS, DOWNLOAD_KEYS),
}


def _param_name(key: str) -> str:
    """Return the CLI parameter name for a configuration key."""
    return _KEY_PARAM_OVERRIDES.get(key, key.replace("-", "_"))

# Configuration file names tried within each directory, in this order.
CONFIGURATION_FILENAMES = ["volumito.yaml", ".volumito.yaml"]


def configuration_directories() -> list[str]:
    """Return the directories probed for a configuration file, highest priority first.

    The order is: the current working directory, the current user's home directory,
    ``~/.volumito``, ``~/.config/volumito``, and finally ``/etc`` (lowest priority).
    """
    home = os.path.expanduser("~")
    return [
        os.getcwd(),
        home,
        os.path.join(home, ".volumito"),
        os.path.join(home, ".config", "volumito"),
        "/etc",
    ]


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


def _validate_flat_keys(
    section: str, values: dict[str, Any], allowed: list[str], path: str
) -> None:
    """Raise BadParameter if any key in a flat mapping is not allowed."""
    for key in values:
        if key not in allowed:
            raise click.BadParameter(
                f"unknown key {key!r} in section {section!r} of configuration file {path}"
            )


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
        if section in _HIERARCHICAL_SPECS:
            scalar_keys, subsections, subsection_keys = _HIERARCHICAL_SPECS[section]
            config[section] = _validate_hierarchical(
                section, values, scalar_keys, subsections, subsection_keys, path
            )
        else:
            _validate_flat_keys(section, values, SECTION_KEYS[section], path)
            config[section] = dict(values)
    return config


def _validate_hierarchical(
    name: str,
    values: dict[str, Any],
    scalar_keys: list[str],
    subsections: list[str],
    subsection_keys: list[str],
    path: str,
) -> dict[str, Any]:
    """Validate a hierarchical section (shared scalars + per-command subsections)."""
    result: dict[str, Any] = {}
    for key, value in values.items():
        if key in subsections:
            if value is None:
                continue
            if not isinstance(value, dict):
                raise click.BadParameter(
                    f"section '{name}.{key}' in configuration file {path} must be a mapping"
                )
            _validate_flat_keys(f"{name}.{key}", value, subsection_keys, path)
            result[key] = dict(value)
        elif key in scalar_keys:
            result[key] = value
        else:
            raise click.BadParameter(
                f"unknown key {key!r} in section {name!r} of configuration file {path}"
            )
    return result


def _assign_nested(result: dict[str, Any], path: list[str], param: str, value: object) -> None:
    """Write ``result[path...][param] = value``, creating intermediate dicts."""
    node = result
    for part in path[:-1]:
        node = node.setdefault(part, {})
    node.setdefault(path[-1], {})[param] = value


def _apply_hierarchical(
    result: dict[str, Any],
    shared: dict[str, Any],
    values: dict[str, Any],
    subsection_paths: dict[str, list[list[str]]],
) -> None:
    """Place ``{**shared, **subsection}`` into each subsection's command path(s)."""
    for subsection, paths in subsection_paths.items():
        merged = {**shared, **values.get(subsection, {})}
        for key, value in merged.items():
            for path in paths:
                _assign_nested(result, path, _param_name(key), value)


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

    output = config.get("output", {})
    for key, value in output.items():
        if key in ("verbose", "machine-readable"):
            result[_param_name(key)] = value
        elif key == "print-resulting-status":
            for command_path in ACTION_COMMAND_PATHS:
                _assign_nested(result, command_path, _param_name(key), value)
    shared_display = {k: v for k, v in output.items() if k in DISPLAY_KEYS}
    _apply_hierarchical(result, shared_display, output, DISPLAY_SUBSECTION_PATHS)

    downloads = config.get("downloads", {})
    shared_download = {k: v for k, v in downloads.items() if k in DOWNLOAD_KEYS}
    _apply_hierarchical(result, shared_download, downloads, DOWNLOAD_SUBSECTION_PATHS)

    return result


def _key_lines(key: str, value: object, indent: int) -> list[str]:
    """Return the comment/value/blank lines for one config key at the given indent."""
    pad = " " * indent
    scalar = yaml.safe_dump({key: value}, sort_keys=False, default_flow_style=False).strip()
    return [f"{pad}# {KEY_COMMENTS[key]}", f"{pad}{scalar}", ""]


def _shared_note_lines(subsections: list[str]) -> list[str]:
    """Return the shared-key comment lines listing the override subsections."""
    return [
        "  # A key here applies to all relevant commands;",
        "  # overrides can be specified under the following sections:",
        f"  # {', '.join(sorted(subsections))}",
    ]


def _render_hierarchical(
    defaults: dict[str, Any],
    name: str,
    scalar_keys: list[str],
    subsections: list[str],
    subsection_keys: list[str],
) -> list[str]:
    """Render a hierarchical section (shared note + shared scalars + subsections)."""
    lines = [f"{name}:", *_shared_note_lines(subsections), ""]
    for key in sorted(scalar_keys):
        lines.extend(_key_lines(key, defaults[_param_name(key)], 2))
    for sub_index, subsection in enumerate(sorted(subsections)):
        if sub_index > 0:
            lines.append("")
        lines.append(f"  {subsection}:")
        for key in sorted(subsection_keys):
            lines.extend(_key_lines(key, defaults[_param_name(key)], 4))
    return lines


def render_default_configuration(defaults: dict[str, Any], version: str) -> str:
    """Render a configuration file holding every known key and its default value.

    ``defaults`` is a flat mapping keyed by CLI parameter names (with underscores),
    as produced from the CLI option defaults; ``version`` is recorded in the header.
    The result is a YAML document with the recognized sections and hyphenated keys,
    sorted lexicographically at every level, annotated with a header (followed by a
    blank line) and an explanatory comment above each key, a blank line after each key,
    and two blank lines between sections. The hierarchical ``output`` and ``downloads``
    sections are generated with per-command subsections.
    """
    header_third = (
        f"# Generated with default values for version {version}: "
        "edit as needed (and remove this comment)"
    )
    lines = [
        "# volumito CLI configuration file",
        "#",
        header_third,
        "",
    ]
    for index, section in enumerate(sorted(RECOGNIZED_SECTIONS)):
        if index > 0:
            lines.append("")
        if section == "output":
            non_display = [key for key in OUTPUT_SCALAR_KEYS if key not in DISPLAY_KEYS]
            lines.extend(
                _render_hierarchical(
                    defaults, "output", non_display, DISPLAY_SUBSECTIONS, DISPLAY_KEYS
                )
            )
        elif section == "downloads":
            lines.extend(
                _render_hierarchical(
                    defaults, "downloads", [], DOWNLOAD_SUBSECTIONS, DOWNLOAD_KEYS
                )
            )
        else:
            lines.append(f"{section}:")
            for key in sorted(SECTION_KEYS[section]):
                lines.extend(_key_lines(key, defaults[_param_name(key)], 2))
    return "\n".join(lines)


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
    pairs.extend((f"downloads.{key}", downloads[key]) for key in DOWNLOAD_KEYS if key in downloads)
    for subsection in DOWNLOAD_SUBSECTIONS:
        subvalues = downloads.get(subsection, {})
        pairs.extend(
            (f"downloads.{subsection}.{key}", subvalues[key])
            for key in DOWNLOAD_KEYS
            if key in subvalues
        )
    return pairs
