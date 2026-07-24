"""Tests for the volumito.cli.metadata audio-tagging helpers."""

from unittest.mock import call

import pytest
from mutagen.id3 import ID3NoHeaderError
from pytest_mock import MockerFixture

from volumito.cli.metadata import UnsupportedAudioFormatError, embed_metadata_and_cover

_JPEG = b"\xff\xd8\xff\xe0" + b"jpegbody"
_PNG = b"\x89PNG\r\n\x1a\n" + b"pngbody"


class TestEmbedFlac:
    def test_sets_all_tags_and_jpeg_cover(self, mocker: MockerFixture):
        audio = mocker.MagicMock()
        flac = mocker.patch("volumito.cli.metadata.FLAC", return_value=audio)
        picture = mocker.MagicMock()
        mocker.patch("volumito.cli.metadata.Picture", return_value=picture)

        embed_metadata_and_cover(
            "song.flac",
            title="T",
            artist="A",
            album="Al",
            albumartist="AA",
            track_number=3,
            cover=_JPEG,
        )

        flac.assert_called_once_with("song.flac")
        assert audio.__setitem__.call_args_list == [
            call("title", "T"),
            call("artist", "A"),
            call("album", "Al"),
            call("albumartist", "AA"),
            call("tracknumber", "3"),
        ]
        assert picture.type == 3
        assert picture.mime == "image/jpeg"
        assert picture.data == _JPEG
        audio.clear_pictures.assert_called_once_with()
        audio.add_picture.assert_called_once_with(picture)
        audio.save.assert_called_once_with()

    def test_skips_none_fields_and_no_cover(self, mocker: MockerFixture):
        audio = mocker.MagicMock()
        mocker.patch("volumito.cli.metadata.FLAC", return_value=audio)
        picture = mocker.patch("volumito.cli.metadata.Picture")

        embed_metadata_and_cover(
            "song.flac",
            title="T",
            artist=None,
            album=None,
            albumartist=None,
            track_number=None,
            cover=None,
        )

        assert audio.__setitem__.call_args_list == [call("title", "T")]
        picture.assert_not_called()
        audio.add_picture.assert_not_called()
        audio.save.assert_called_once_with()


class TestEmbedMp3:
    def test_sets_frames_and_png_cover(self, mocker: MockerFixture):
        tags = mocker.MagicMock()
        mocker.patch("volumito.cli.metadata.ID3", return_value=tags)
        tit2 = mocker.patch("volumito.cli.metadata.TIT2")
        tpe1 = mocker.patch("volumito.cli.metadata.TPE1")
        talb = mocker.patch("volumito.cli.metadata.TALB")
        tpe2 = mocker.patch("volumito.cli.metadata.TPE2")
        trck = mocker.patch("volumito.cli.metadata.TRCK")
        apic = mocker.patch("volumito.cli.metadata.APIC")

        embed_metadata_and_cover(
            "song.mp3",
            title="T",
            artist="A",
            album="Al",
            albumartist="AA",
            track_number=5,
            cover=_PNG,
        )

        tit2.assert_called_once_with(encoding=3, text="T")
        tpe1.assert_called_once_with(encoding=3, text="A")
        talb.assert_called_once_with(encoding=3, text="Al")
        tpe2.assert_called_once_with(encoding=3, text="AA")
        trck.assert_called_once_with(encoding=3, text="5")
        tags.delall.assert_called_once_with("APIC")
        apic.assert_called_once_with(
            encoding=3, mime="image/png", type=3, desc="Cover", data=_PNG
        )
        tags.save.assert_called_once_with("song.mp3")

    def test_creates_tags_when_no_header(self, mocker: MockerFixture):
        tags = mocker.MagicMock()
        mocker.patch("volumito.cli.metadata.ID3", side_effect=[ID3NoHeaderError(), tags])
        mocker.patch("volumito.cli.metadata.TIT2")

        embed_metadata_and_cover(
            "song.mp3",
            title="T",
            artist=None,
            album=None,
            albumartist=None,
            track_number=None,
            cover=None,
        )

        tags.delall.assert_not_called()
        tags.save.assert_called_once_with("song.mp3")


class TestEmbedMp4:
    def test_sets_atoms_and_jpeg_cover(self, mocker: MockerFixture):
        audio = mocker.MagicMock()
        mocker.patch("volumito.cli.metadata.MP4", return_value=audio)
        cover_cls = mocker.patch("volumito.cli.metadata.MP4Cover")

        embed_metadata_and_cover(
            "song.mp4",
            title="T",
            artist="A",
            album="Al",
            albumartist="AA",
            track_number=7,
            cover=_JPEG,
        )

        setitem_calls = audio.__setitem__.call_args_list
        assert call("\xa9nam", "T") in setitem_calls
        assert call("\xa9ART", "A") in setitem_calls
        assert call("\xa9alb", "Al") in setitem_calls
        assert call("aART", "AA") in setitem_calls
        assert call("trkn", [(7, 0)]) in setitem_calls
        assert [c.args[0] for c in setitem_calls][-1] == "covr"
        cover_cls.assert_called_once_with(_JPEG, imageformat=cover_cls.FORMAT_JPEG)
        audio.save.assert_called_once_with()

    def test_m4a_png_cover(self, mocker: MockerFixture):
        audio = mocker.MagicMock()
        mocker.patch("volumito.cli.metadata.MP4", return_value=audio)
        cover_cls = mocker.patch("volumito.cli.metadata.MP4Cover")

        embed_metadata_and_cover(
            "song.m4a",
            title="T",
            artist=None,
            album=None,
            albumartist=None,
            track_number=2,
            cover=_PNG,
        )

        cover_cls.assert_called_once_with(_PNG, imageformat=cover_cls.FORMAT_PNG)
        audio.save.assert_called_once_with()

    def test_skips_none_track_number_and_no_cover(self, mocker: MockerFixture):
        audio = mocker.MagicMock()
        mocker.patch("volumito.cli.metadata.MP4", return_value=audio)
        cover_cls = mocker.patch("volumito.cli.metadata.MP4Cover")

        embed_metadata_and_cover(
            "song.mp4",
            title="T",
            artist=None,
            album=None,
            albumartist=None,
            track_number=None,
            cover=None,
        )

        setitem_keys = [c.args[0] for c in audio.__setitem__.call_args_list]
        assert setitem_keys == ["\xa9nam"]
        assert "trkn" not in setitem_keys
        assert "covr" not in setitem_keys
        cover_cls.assert_not_called()
        audio.save.assert_called_once_with()


class TestDispatch:
    def test_unsupported_extension_raises(self):
        with pytest.raises(UnsupportedAudioFormatError):
            embed_metadata_and_cover(
                "song.ogg",
                title="T",
                artist=None,
                album=None,
                albumartist=None,
                track_number=None,
                cover=None,
            )

    def test_extension_is_case_insensitive(self, mocker: MockerFixture):
        audio = mocker.MagicMock()
        flac = mocker.patch("volumito.cli.metadata.FLAC", return_value=audio)

        embed_metadata_and_cover(
            "SONG.FLAC",
            title="T",
            artist=None,
            album=None,
            albumartist=None,
            track_number=None,
            cover=None,
        )

        flac.assert_called_once_with("SONG.FLAC")
