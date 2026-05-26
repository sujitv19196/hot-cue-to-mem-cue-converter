import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

import convert_cues as cc


SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<DJ_PLAYLISTS Version="1.0.0">
  <COLLECTION Entries="3">
    <TRACK TrackID="1" Name="Track With Hot Cues" Location="file://localhost/Users/me/a.mp3">
      <POSITION_MARK Name="Intro" Type="0" Start="10.000" Num="0" Red="40" Green="226" Blue="20"/>
      <POSITION_MARK Name="Drop" Type="0" Start="60.500" Num="1" Red="226" Green="20" Blue="20"/>
      <POSITION_MARK Name="OldMem" Type="0" Start="120.0" Num="-1"/>
    </TRACK>
    <TRACK TrackID="2" Name="Track No Cues" Location="file://localhost/Users/me/b.mp3"/>
    <TRACK TrackID="3" Name="Track With Loop" Location="file://localhost/Users/me/c.mp3">
      <POSITION_MARK Name="Loop" Type="4" Start="30.000" End="32.000" Num="2"/>
      <POSITION_MARK Name="Point" Type="0" Start="90.000" Num="3"/>
    </TRACK>
    <TRACK TrackID="4" Name="Hot Cue Sharing Time" Location="file://localhost/Users/me/d.mp3">
      <POSITION_MARK Name="A" Type="0" Start="5.000" Num="0"/>
      <POSITION_MARK Name="MemAtSame" Type="0" Start="5.000" Num="-1"/>
    </TRACK>
  </COLLECTION>
  <PLAYLISTS>
    <NODE Type="0" Name="ROOT" Count="1">
      <NODE Name="House Set" Type="1" KeyType="0" Entries="2">
        <TRACK Key="1"/>
        <TRACK Key="3"/>
      </NODE>
    </NODE>
  </PLAYLISTS>
</DJ_PLAYLISTS>
"""


@pytest.fixture
def sample_xml(tmp_path: Path) -> Path:
    path = tmp_path / "collection.xml"
    path.write_text(SAMPLE_XML, encoding="utf-8")
    return path


@pytest.fixture
def root() -> ET.Element:
    return ET.fromstring(SAMPLE_XML)


def memcue_starts(track: ET.Element) -> list[str]:
    return [p.get("Start", "") for p in track.findall('POSITION_MARK[@Num="-1"]')]


def hotcue_marks(track: ET.Element) -> list[ET.Element]:
    return [p for p in track.findall("POSITION_MARK") if p.get("Num", "-1") != "-1"]


class TestConvertTrack:
    def test_adds_memcue_for_each_hotcue(self, root: ET.Element) -> None:
        track = root.find('.//TRACK[@TrackID="1"]')
        added, skipped = cc.convert_track(track)
        assert (added, skipped) == (2, 0)
        assert sorted(memcue_starts(track)) == ["10.000", "120.0", "60.500"]

    def test_preserves_existing_hot_cues(self, root: ET.Element) -> None:
        track = root.find('.//TRACK[@TrackID="1"]')
        cc.convert_track(track)
        nums = sorted(int(m.get("Num")) for m in hotcue_marks(track))
        assert nums == [0, 1]

    def test_copies_color_attributes(self, root: ET.Element) -> None:
        track = root.find('.//TRACK[@TrackID="1"]')
        cc.convert_track(track)
        new_at_10 = [
            p for p in track.findall('POSITION_MARK[@Num="-1"]')
            if p.get("Start") == "10.000"
        ][0]
        assert (new_at_10.get("Red"), new_at_10.get("Green"), new_at_10.get("Blue")) == (
            "40",
            "226",
            "20",
        )

    def test_skips_when_memcue_exists_at_same_start(self, root: ET.Element) -> None:
        track = root.find('.//TRACK[@TrackID="4"]')
        added, skipped = cc.convert_track(track)
        assert (added, skipped) == (0, 1)
        assert memcue_starts(track) == ["5.000"]  # the original, no dup

    def test_skips_loop_cues(self, root: ET.Element) -> None:
        track = root.find('.//TRACK[@TrackID="3"]')
        added, skipped = cc.convert_track(track)
        assert (added, skipped) == (1, 0)
        assert memcue_starts(track) == ["90.000"]

    def test_track_with_no_cues_is_noop(self, root: ET.Element) -> None:
        track = root.find('.//TRACK[@TrackID="2"]')
        added, skipped = cc.convert_track(track)
        assert (added, skipped) == (0, 0)

    def test_idempotent(self, root: ET.Element) -> None:
        track = root.find('.//TRACK[@TrackID="1"]')
        cc.convert_track(track)
        added, skipped = cc.convert_track(track)
        assert added == 0
        assert skipped == 2


class TestSelectTracks:
    def _args(self, **kw):
        defaults = dict(
            playlist=None,
            track_id=None,
            track_name=None,
            path=None,
            dry_run=False,
            input="x",
            output=None,
        )
        defaults.update(kw)
        return type("A", (), defaults)()

    def test_whole_collection_default(self, root: ET.Element) -> None:
        tracks, label = cc.select_tracks(root, self._args())
        assert len(tracks) == 4
        assert "entire collection" in label

    def test_playlist_filter_case_insensitive(self, root: ET.Element) -> None:
        tracks, label = cc.select_tracks(root, self._args(playlist="house set"))
        ids = {t.get("TrackID") for t in tracks}
        assert ids == {"1", "3"}
        assert "house set" in label

    def test_playlist_not_found_exits(self, root: ET.Element) -> None:
        with pytest.raises(SystemExit, match="playlist not found"):
            cc.select_tracks(root, self._args(playlist="nope"))

    def test_track_id_filter(self, root: ET.Element) -> None:
        tracks, _ = cc.select_tracks(root, self._args(track_id="3"))
        assert [t.get("TrackID") for t in tracks] == ["3"]

    def test_track_id_not_found_exits(self, root: ET.Element) -> None:
        with pytest.raises(SystemExit, match="no track with TrackID"):
            cc.select_tracks(root, self._args(track_id="999"))

    def test_track_name_filter_case_insensitive(self, root: ET.Element) -> None:
        tracks, _ = cc.select_tracks(
            root, self._args(track_name="track with hot cues")
        )
        assert [t.get("TrackID") for t in tracks] == ["1"]

    def test_path_filter(self, root: ET.Element) -> None:
        tracks, _ = cc.select_tracks(root, self._args(path="/Users/me/b.mp3"))
        assert [t.get("TrackID") for t in tracks] == ["2"]


class TestLocationToPath:
    def test_unescapes_and_strips_scheme(self) -> None:
        assert (
            cc.location_to_path("file://localhost/Users/me/My%20Song.mp3")
            == "/Users/me/My Song.mp3"
        )

    def test_empty(self) -> None:
        assert cc.location_to_path("") == ""


class TestParseArgs:
    def test_playlist_and_track_id_are_mutually_exclusive(self) -> None:
        with pytest.raises(SystemExit):
            cc.parse_args(["in.xml", "--playlist", "X", "--track-id", "1"])

    def test_defaults(self) -> None:
        ns = cc.parse_args(["in.xml"])
        assert ns.input == "in.xml"
        assert ns.playlist is None
        assert ns.dry_run is False


class TestMainEndToEnd:
    def test_writes_converted_xml(self, sample_xml: Path, tmp_path: Path) -> None:
        out = tmp_path / "out.xml"
        rc = cc.main([str(sample_xml), "-o", str(out)])
        assert rc == 0
        assert out.is_file()
        written = ET.parse(out).getroot()
        t1 = written.find('.//TRACK[@TrackID="1"]')
        assert sorted(memcue_starts(t1)) == ["10.000", "120.0", "60.500"]

    def test_dry_run_does_not_write(self, sample_xml: Path, tmp_path: Path) -> None:
        out = tmp_path / "out.xml"
        rc = cc.main([str(sample_xml), "-o", str(out), "--dry-run"])
        assert rc == 0
        assert not out.exists()

    def test_default_output_path(self, sample_xml: Path) -> None:
        rc = cc.main([str(sample_xml)])
        assert rc == 0
        expected = sample_xml.with_name(sample_xml.stem + ".converted.xml")
        assert expected.is_file()

    def test_idempotent_via_main(self, sample_xml: Path, tmp_path: Path) -> None:
        out1 = tmp_path / "out1.xml"
        out2 = tmp_path / "out2.xml"
        cc.main([str(sample_xml), "-o", str(out1)])
        cc.main([str(out1), "-o", str(out2)])
        first = ET.parse(out1).getroot().find('.//TRACK[@TrackID="1"]')
        second = ET.parse(out2).getroot().find('.//TRACK[@TrackID="1"]')
        assert sorted(memcue_starts(first)) == sorted(memcue_starts(second))
