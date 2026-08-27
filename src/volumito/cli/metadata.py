"""Audio metadata and cover-art embedding for the volumito CLI.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

import os

from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, ID3, TALB, TIT2, TPE1, TPE2, TRCK, ID3NoHeaderError
from mutagen.mp4 import MP4, MP4Cover

# Picture type for a front cover, per the ID3v2 / FLAC picture-type enumeration.
_FRONT_COVER_TYPE = 3

# Bytes read from the beginning of a file to recognize its audio format.
_MAGIC_BYTES_LENGTH = 12

# Audio file extensions into which metadata and cover art can be embedded.
SUPPORTED_AUDIO_EXTENSIONS = (".flac", ".m4a", ".mp3", ".mp4")


class UnsupportedAudioFormatError(Exception):
    """Raised when a file's extension is not one supported for embedding."""


def _cover_mime(cover: bytes) -> str:
    """Return the MIME type of the cover image, sniffed from its magic bytes."""
    if cover.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    return "image/jpeg"


def detect_audio_extension(path: str) -> str | None:
    """Return the file extension matching the audio format of ``path``, or None.

    The format is sniffed from the magic bytes opening the file, so a file whose
    name does not match its content (e.g., an MP3 stream saved as ".flac") is still
    recognized. Only the formats metadata can be embedded into are detected: an
    unrecognized content, an unreadable file, and a missing one all give None.

    Args:
        path: The audio file to sniff

    Returns:
        The extension of the detected format, leading dot included, or None
    """
    try:
        with open(path, "rb") as f:
            header = f.read(_MAGIC_BYTES_LENGTH)
    except OSError:
        return None
    if header.startswith(b"fLaC"):
        return ".flac"
    # An MP3 file opens with an ID3v2 tag, or directly with an MPEG frame sync
    if header.startswith(b"ID3") or (
        len(header) >= 2 and header[0] == 0xFF and header[1] & 0xE0 == 0xE0
    ):
        return ".mp3"
    if header[4:8] == b"ftyp":
        return ".m4a"
    return None


def embed_metadata_and_cover(
    path: str,
    *,
    title: str | None,
    artist: str | None,
    album: str | None,
    albumartist: str | None,
    track_number: int | None,
    cover: bytes | None,
) -> None:
    """Embed the given track metadata and cover art into the audio file at ``path``.

    The file format is sniffed from the content of ``path``, falling back to its
    (lowercased) extension when the content is not recognized: FLAC, MP3, and MP4/M4A
    are supported. Text fields that are ``None`` are left untouched, and the cover art
    is written only when ``cover`` is not ``None``.

    Args:
        path: The audio file to tag, modified in place
        title: The track title, or None to skip it
        artist: The track artist, or None to skip it
        album: The album name, or None to skip it
        albumartist: The album artist, or None to skip it
        track_number: The track number, or None to skip it
        cover: The cover image bytes (JPEG or PNG), or None to skip it

    Raises:
        UnsupportedAudioFormatError: If the audio format is not supported
    """
    extension = detect_audio_extension(path) or os.path.splitext(path)[1].lower()
    if extension == ".flac":
        _embed_flac(path, title, artist, album, albumartist, track_number, cover)
    elif extension == ".mp3":
        _embed_mp3(path, title, artist, album, albumartist, track_number, cover)
    elif extension in (".m4a", ".mp4"):
        _embed_mp4(path, title, artist, album, albumartist, track_number, cover)
    else:
        msg = f"unsupported audio format: {extension or path}"
        raise UnsupportedAudioFormatError(msg)


def _embed_flac(
    path: str,
    title: str | None,
    artist: str | None,
    album: str | None,
    albumartist: str | None,
    track_number: int | None,
    cover: bytes | None,
) -> None:
    """Embed metadata and cover art into a FLAC file (Vorbis comments + picture block)."""
    audio = FLAC(path)
    fields = {
        "title": title,
        "artist": artist,
        "album": album,
        "albumartist": albumartist,
        "tracknumber": None if track_number is None else str(track_number),
    }
    for key, value in fields.items():
        if value is not None:
            audio[key] = value
    if cover is not None:
        picture = Picture()
        picture.type = _FRONT_COVER_TYPE
        picture.mime = _cover_mime(cover)
        picture.data = cover
        audio.clear_pictures()
        audio.add_picture(picture)
    audio.save()


def _embed_mp3(
    path: str,
    title: str | None,
    artist: str | None,
    album: str | None,
    albumartist: str | None,
    track_number: int | None,
    cover: bytes | None,
) -> None:
    """Embed metadata and cover art into an MP3 file (ID3v2 frames)."""
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()
    frames = [
        (TIT2, title),
        (TPE1, artist),
        (TALB, album),
        (TPE2, albumartist),
        (TRCK, None if track_number is None else str(track_number)),
    ]
    for frame_class, value in frames:
        if value is not None:
            tags.add(frame_class(encoding=3, text=value))
    if cover is not None:
        tags.delall("APIC")
        tags.add(
            APIC(
                encoding=3,
                mime=_cover_mime(cover),
                type=_FRONT_COVER_TYPE,
                desc="Cover",
                data=cover,
            )
        )
    tags.save(path)


def _embed_mp4(
    path: str,
    title: str | None,
    artist: str | None,
    album: str | None,
    albumartist: str | None,
    track_number: int | None,
    cover: bytes | None,
) -> None:
    """Embed metadata and cover art into an MP4/M4A file (iTunes-style atoms)."""
    audio = MP4(path)
    atoms = {
        "\xa9nam": title,
        "\xa9ART": artist,
        "\xa9alb": album,
        "aART": albumartist,
    }
    for key, value in atoms.items():
        if value is not None:
            audio[key] = value
    if track_number is not None:
        audio["trkn"] = [(track_number, 0)]
    if cover is not None:
        image_format = (
            MP4Cover.FORMAT_PNG if _cover_mime(cover) == "image/png" else MP4Cover.FORMAT_JPEG
        )
        audio["covr"] = [MP4Cover(cover, imageformat=image_format)]
    audio.save()
