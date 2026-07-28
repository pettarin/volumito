"""Entity references for the Volumio metadata queries.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class MusicEntity:
    """A reference to a music entity, by free-text value or by MusicBrainz ID."""

    value: str
    """The free-text value (e.g., a name or title), or the MusicBrainz ID."""

    is_mbid: bool = False
    """Whether ``value`` is a MusicBrainz ID (MBID) instead of free text."""


@dataclass(frozen=True)
class Album(MusicEntity):
    """An album reference, by title (free text) or by MBID."""


@dataclass(frozen=True)
class Artist(MusicEntity):
    """An artist reference, by name (free text) or by MBID."""


@dataclass(frozen=True)
class Label(MusicEntity):
    """A record label reference, by name (free text) or by MBID."""


@dataclass(frozen=True)
class Place(MusicEntity):
    """A place reference, by name (free text) or by MBID."""
