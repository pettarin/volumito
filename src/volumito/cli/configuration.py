"""Configuration-file loading for the volumito CLI.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

import os
from typing import Any

import click
import yaml

# Recognized section names and their allowed (hyphenated) keys.
# Keys mirror the CLI long options minus the leading "--".
SECTION_KEYS: dict[str, set[str]] = {
    "volumio": {"host", "scheme", "rest-api-port", "mpd-port"},
    "timeouts": {"rest-api-timeout", "mpd-timeout", "rest-api-sleep-before-next-call"},
    "verbosity": {"verbose", "machine-readable"},
}

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
            default_map[key.replace("-", "_")] = value
    return default_map
