"""Configuration-file loading for the volumito CLI.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

import os
from typing import Any

import click
import yaml

# Recognized section names and their allowed (hyphenated) keys, in display order.
# Keys mirror the CLI long options minus the leading "--".
SECTION_KEYS: dict[str, list[str]] = {
    "volumio": ["host", "scheme", "rest-api-port", "mpd-port"],
    "timeouts": ["rest-api-timeout", "mpd-timeout", "rest-api-sleep-before-next-call"],
    "output": ["verbose", "machine-readable", "fields", "format", "raw", "print-resulting-state"],
}

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
}

# Config keys whose CLI parameter name differs from key.replace("-", "_").
_KEY_PARAM_OVERRIDES = {"format": "output_format"}

# CLI parameter names that are per-command options (not global), mapped to the
# default_map paths of the commands that accept them. Display options live on the
# state/info/list commands; --print-resulting-state lives on the player actions.
OUTPUT_COMMAND_PATHS = [["info"], ["player", "state"], ["track", "info"], ["queue", "list"]]
ACTION_COMMAND_PATHS = [
    ["player", name]
    for name in ("toggle", "play", "pause", "stop", "next", "previous", "volume", "mute", "unmute")
]
COMMAND_SCOPED_PARAMS: dict[str, list[list[str]]] = {
    "fields": OUTPUT_COMMAND_PATHS,
    "output_format": OUTPUT_COMMAND_PATHS,
    "raw": OUTPUT_COMMAND_PATHS,
    "print_resulting_state": ACTION_COMMAND_PATHS,
}


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


def load_default_map(path: str) -> dict[str, Any]:
    """Read a configuration file and return a flat Click ``default_map``.

    The returned mapping is keyed by the CLI parameter names (with underscores)
    and holds the values found in the recognized sections. Unknown sections or
    keys, a non-mapping document, or invalid YAML raise
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

    default_map: dict[str, Any] = {}
    for section, values in data.items():
        if section not in SECTION_KEYS:
            raise click.BadParameter(
                f"unknown section {section!r} in configuration file {path}"
            )
        if values is None:
            continue
        if not isinstance(values, dict):
            raise click.BadParameter(
                f"section {section!r} in configuration file {path} must be a mapping"
            )
        allowed = SECTION_KEYS[section]
        for key, value in values.items():
            if key not in allowed:
                raise click.BadParameter(
                    f"unknown key {key!r} in section {section!r} of configuration file {path}"
                )
            default_map[_param_name(key)] = value
    return default_map


def build_click_default_map(flat_defaults: dict[str, Any]) -> dict[str, Any]:
    """Turn a flat param->value map into a Click ``default_map``.

    Global option values stay at the top level; each per-command option is replicated
    into the nested slot of every command that accepts it, since Click reads
    ``default_map`` hierarchically by group/subcommand name.
    """
    result: dict[str, Any] = {
        k: v for k, v in flat_defaults.items() if k not in COMMAND_SCOPED_PARAMS
    }
    for param, paths in COMMAND_SCOPED_PARAMS.items():
        if param not in flat_defaults:
            continue
        for path in paths:
            node = result
            for part in path[:-1]:
                node = node.setdefault(part, {})
            node.setdefault(path[-1], {})[param] = flat_defaults[param]
    return result


def render_default_configuration(defaults: dict[str, Any], version: str) -> str:
    """Render a configuration file holding every known key and its default value.

    ``defaults`` is a flat mapping keyed by CLI parameter names (with underscores),
    as produced from the ``main`` group option defaults; ``version`` is recorded in
    the header. The result is a YAML document with the recognized sections and
    hyphenated keys, in canonical order, annotated with a header (followed by a blank
    line) and an explanatory comment above each key, a blank line after each key, and
    two blank lines between sections.
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
    for index, (section, keys) in enumerate(SECTION_KEYS.items()):
        if index > 0:
            lines.append("")
        lines.append(f"{section}:")
        for key in keys:
            value = defaults[_param_name(key)]
            scalar = yaml.safe_dump(
                {key: value}, sort_keys=False, default_flow_style=False
            ).strip()
            lines.append(f"  # {KEY_COMMENTS[key]}")
            lines.append(f"  {scalar}")
            lines.append("")
    return "\n".join(lines)


def configuration_values_by_section(default_map: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Regroup a flat ``default_map`` into ``{section: {hyphenated-key: value}}``.

    Only keys actually present in ``default_map`` are included, preserving the
    canonical section and key order.
    """
    grouped: dict[str, dict[str, Any]] = {}
    for section, keys in SECTION_KEYS.items():
        section_values = {
            key: default_map[_param_name(key)]
            for key in keys
            if _param_name(key) in default_map
        }
        if section_values:
            grouped[section] = section_values
    return grouped
