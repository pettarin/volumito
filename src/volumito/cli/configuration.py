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
    "output": ["verbose", "machine-readable", "fields", "format", "raw", "print-resulting-state"],
}

# The "downloads" section is hierarchical: its scalar keys are shared by both track
# download commands, and optional "audio"/"albumart" subsections (mapping to the
# "track audio"/"track albumart" commands) override the shared values per command.
DOWNLOAD_KEYS = ["file-name-template", "output-dir", "output-file", "overwrite-existing-files"]
DOWNLOAD_SUBSECTIONS = ["audio", "albumart"]

# Every recognized top-level section.
RECOGNIZED_SECTIONS = [*SECTION_KEYS, "downloads"]

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
    "print-resulting-state": (
        "After a player command like pause or volume, print the resulting player state"
    ),
    "file-name-template": "Template (Python str.format) for the -d output file name",
    "output-dir": "Directory to download into (mutually exclusive with output-file)",
    "output-file": "Exact file path to download to (mutually exclusive with output-dir)",
    "overwrite-existing-files": "Overwrite the destination file if it already exists",
}

# Config keys whose CLI parameter name differs from key.replace("-", "_").
_KEY_PARAM_OVERRIDES = {"format": "output_format"}

# default_map paths of the commands that accept the "output" section options.
# The display options live on the state/info/list commands; --print-resulting-state
# lives on the player action commands.
OUTPUT_COMMAND_PATHS = [["info"], ["player", "state"], ["track", "info"], ["queue", "list"]]
ACTION_COMMAND_PATHS = [
    ["player", name]
    for name in ("toggle", "play", "pause", "stop", "next", "previous", "volume", "mute", "unmute")
]

# "output" section config keys that are per-command display options.
_DISPLAY_KEYS = {"fields", "format", "raw"}

# "downloads" subsection name -> the command's default_map path.
_DOWNLOAD_COMMAND_PATHS = {"audio": ["track", "audio"], "albumart": ["track", "albumart"]}


def _param_name(key: str) -> str:
    """Return the CLI parameter name for a configuration key."""
    return _KEY_PARAM_OVERRIDES.get(key, key.replace("-", "_"))

# Configuration file names tried within each directory, in this order.
CONFIGURATION_FILENAMES = ["volumito.yaml", ".volumito.yaml"]


def canonical_configuration_directories() -> list[str]:
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


def canonical_configuration_paths() -> list[str]:
    """Return the canonical configuration file paths, in search order.

    Each directory from :func:`canonical_configuration_directories` is probed for
    ``volumito.yaml`` and then ``.volumito.yaml`` before moving on to the next.
    """
    return [
        os.path.join(directory, filename)
        for directory in canonical_configuration_directories()
        for filename in CONFIGURATION_FILENAMES
    ]


def found_and_used_configuration_paths() -> tuple[list[str], str | None]:
    """Probe the canonical paths and report which files exist and which is used.

    Returns a tuple ``(found, used)`` where ``found`` lists every existing
    canonical configuration file (in search order) and ``used`` is the first of
    them (the one that would be loaded), or ``None`` if none exists.
    """
    found = [path for path in canonical_configuration_paths() if os.path.isfile(path)]
    used = found[0] if found else None
    return found, used


def resolve_configuration_path(explicit: str | None) -> str | None:
    """Resolve which configuration file to read, if any.

    If ``explicit`` is given, it must point to an existing file (otherwise a
    :class:`click.BadParameter` is raised). Otherwise the canonical paths are
    searched in order and the first existing one is returned, or ``None`` if
    none exists.
    """
    if explicit is not None:
        if not os.path.isfile(explicit):
            raise click.BadParameter(f"configuration file not found: {explicit}")
        return explicit
    for path in canonical_configuration_paths():
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
    ``{"volumio": {"host": ...}, "downloads": {"output-dir": ..., "audio": {...}}}``.
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
        if section == "downloads":
            config[section] = _validate_downloads(values, path)
        else:
            _validate_flat_keys(section, values, SECTION_KEYS[section], path)
            config[section] = dict(values)
    return config


def _validate_downloads(values: dict[str, Any], path: str) -> dict[str, Any]:
    """Validate the hierarchical ``downloads`` section and return it unchanged."""
    downloads: dict[str, Any] = {}
    for key, value in values.items():
        if key in DOWNLOAD_SUBSECTIONS:
            if value is None:
                continue
            if not isinstance(value, dict):
                raise click.BadParameter(
                    f"section 'downloads.{key}' in configuration file {path} must be a mapping"
                )
            _validate_flat_keys(f"downloads.{key}", value, DOWNLOAD_KEYS, path)
            downloads[key] = dict(value)
        elif key in DOWNLOAD_KEYS:
            downloads[key] = value
        else:
            raise click.BadParameter(
                f"unknown key {key!r} in section 'downloads' of configuration file {path}"
            )
    return downloads


def _assign_nested(result: dict[str, Any], path: list[str], param: str, value: object) -> None:
    """Write ``result[path...][param] = value``, creating intermediate dicts."""
    node = result
    for part in path[:-1]:
        node = node.setdefault(part, {})
    node.setdefault(path[-1], {})[param] = value


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

    for key, value in config.get("output", {}).items():
        param = _param_name(key)
        if key in _DISPLAY_KEYS:
            for command_path in OUTPUT_COMMAND_PATHS:
                _assign_nested(result, command_path, param, value)
        elif key == "print-resulting-state":
            for command_path in ACTION_COMMAND_PATHS:
                _assign_nested(result, command_path, param, value)
        else:
            result[param] = value

    downloads = config.get("downloads", {})
    shared = {k: v for k, v in downloads.items() if k in DOWNLOAD_KEYS}
    for subsection, command_path in _DOWNLOAD_COMMAND_PATHS.items():
        merged = {**shared, **downloads.get(subsection, {})}
        for key, value in merged.items():
            _assign_nested(result, command_path, _param_name(key), value)

    return result


def _key_lines(key: str, value: object, indent: int) -> list[str]:
    """Return the comment/value/blank lines for one config key at the given indent."""
    pad = " " * indent
    scalar = yaml.safe_dump({key: value}, sort_keys=False, default_flow_style=False).strip()
    return [f"{pad}# {KEY_COMMENTS[key]}", f"{pad}{scalar}", ""]


def render_default_configuration(defaults: dict[str, Any], version: str) -> str:
    """Render a configuration file holding every known key and its default value.

    ``defaults`` is a flat mapping keyed by CLI parameter names (with underscores),
    as produced from the CLI option defaults; ``version`` is recorded in the header.
    The result is a YAML document with the recognized sections and hyphenated keys,
    sorted lexicographically at every level, annotated with a header (followed by a
    blank line) and an explanatory comment above each key, a blank line after each key,
    and two blank lines between sections. The hierarchical ``downloads`` section is
    generated with per-command ``audio``/``albumart`` subsections.
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
        if section == "downloads":
            shared_note = (
                "  # A key here applies to both commands; "
                "per-command overrides go under audio/albumart."
            )
            lines.append("downloads:")
            lines.append(shared_note)
            lines.append("")
            for sub_index, subsection in enumerate(sorted(DOWNLOAD_SUBSECTIONS)):
                if sub_index > 0:
                    lines.append("")
                lines.append(f"  {subsection}:")
                for key in sorted(DOWNLOAD_KEYS):
                    lines.extend(_key_lines(key, defaults[_param_name(key)], 4))
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
