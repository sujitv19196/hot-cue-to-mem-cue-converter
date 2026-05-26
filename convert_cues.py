#!/usr/bin/env python3
"""Duplicate Rekordbox hot cues as memory cues in an exported XML library.

Hot cues are preserved. A memory cue at the same Start time as an existing
memory cue is not added (idempotent). Run on a Rekordbox-exported XML, then
re-import the output into Rekordbox.
"""

from __future__ import annotations

import argparse
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path


HOT_CUE_COLOR_ATTRS = ("Red", "Green", "Blue")


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("input", help="Path to Rekordbox-exported XML file")
    p.add_argument(
        "-o",
        "--output",
        help="Output XML path (default: <input>.converted.xml)",
    )
    p.add_argument(
        "--playlist",
        help="Only process tracks inside this playlist (case-insensitive name match). "
        "If the name matches a folder, all tracks under it are included.",
    )
    g = p.add_mutually_exclusive_group()
    g.add_argument("--track-id", help="Only process the track with this TrackID")
    g.add_argument(
        "--track-name",
        help="Only process tracks whose Name attribute matches (case-insensitive)",
    )
    g.add_argument(
        "--path",
        help="Only process the track whose Location matches this filesystem path",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing output",
    )
    args = p.parse_args(argv)
    if args.playlist and (args.track_id or args.track_name or args.path):
        p.error("--playlist cannot be combined with --track-id/--track-name/--path")
    return args


def location_to_path(location: str) -> str:
    """Convert a Rekordbox Location URL (file://localhost/...) to a filesystem path."""
    if not location:
        return ""
    parsed = urllib.parse.urlparse(location)
    return urllib.parse.unquote(parsed.path)


def find_playlist_node(playlists_root: ET.Element, name: str) -> ET.Element | None:
    """Return the first NODE under <PLAYLISTS> whose Name matches (case-insensitive)."""
    target = name.casefold()
    for node in playlists_root.iter("NODE"):
        node_name = node.get("Name", "")
        if node_name.casefold() == target:
            return node
    return None


def collect_track_keys(node: ET.Element) -> set[str]:
    """Collect every TRACK Key under a playlist NODE, descending into subfolders."""
    keys: set[str] = set()
    for track_ref in node.iter("TRACK"):
        key = track_ref.get("Key")
        if key:
            keys.add(key)
    return keys


def select_tracks(
    root: ET.Element, args: argparse.Namespace
) -> tuple[list[ET.Element], str]:
    """Return the list of <TRACK> elements in scope, plus a human-readable scope label."""
    collection = root.find("./COLLECTION")
    if collection is None:
        raise SystemExit("error: no <COLLECTION> element in XML")
    all_tracks = collection.findall("TRACK")

    if args.playlist:
        playlists_root = root.find("./PLAYLISTS")
        if playlists_root is None:
            raise SystemExit("error: no <PLAYLISTS> element in XML")
        node = find_playlist_node(playlists_root, args.playlist)
        if node is None:
            raise SystemExit(f"error: playlist not found: {args.playlist!r}")
        keys = collect_track_keys(node)
        selected = [t for t in all_tracks if t.get("TrackID") in keys]
        return selected, f"playlist {args.playlist!r} ({len(selected)} tracks)"

    if args.track_id:
        selected = [t for t in all_tracks if t.get("TrackID") == args.track_id]
        if not selected:
            raise SystemExit(f"error: no track with TrackID={args.track_id}")
        return selected, f"track id {args.track_id}"

    if args.track_name:
        target = args.track_name.casefold()
        selected = [t for t in all_tracks if t.get("Name", "").casefold() == target]
        if not selected:
            raise SystemExit(f"error: no track with Name={args.track_name!r}")
        return selected, f"track name {args.track_name!r} ({len(selected)} match)"

    if args.path:
        target = str(Path(args.path).resolve())
        selected = [
            t for t in all_tracks
            if location_to_path(t.get("Location", "")) == target
        ]
        if not selected:
            raise SystemExit(f"error: no track with Location matching {args.path!r}")
        return selected, f"path {args.path!r}"

    return all_tracks, f"entire collection ({len(all_tracks)} tracks)"


def convert_track(track: ET.Element) -> tuple[int, int]:
    """Add memory-cue duplicates for each point-type hot cue.

    Returns (added, skipped_duplicates).
    """
    existing_mem_starts: set[str] = {
        p.get("Start", "")
        for p in track.findall('POSITION_MARK[@Num="-1"]')
    }

    added = 0
    skipped = 0
    for mark in list(track.findall("POSITION_MARK")):
        num = mark.get("Num", "-1")
        if num == "-1":
            continue  # already a memory cue
        if mark.get("Type", "0") != "0":
            continue  # not a point cue (e.g. loop)
        start = mark.get("Start")
        if start is None:
            continue
        if start in existing_mem_starts:
            skipped += 1
            continue

        new_mark = ET.SubElement(track, "POSITION_MARK")
        new_mark.set("Name", "")
        new_mark.set("Type", "0")
        new_mark.set("Start", start)
        new_mark.set("Num", "-1")
        for color_attr in HOT_CUE_COLOR_ATTRS:
            val = mark.get(color_attr)
            if val is not None:
                new_mark.set(color_attr, val)

        existing_mem_starts.add(start)
        added += 1

    return added, skipped


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)

    input_path = Path(args.input)
    if not input_path.is_file():
        raise SystemExit(f"error: input file not found: {input_path}")

    output_path = (
        Path(args.output)
        if args.output
        else input_path.with_suffix(input_path.suffix + ".converted.xml")
        if input_path.suffix != ".xml"
        else input_path.with_name(input_path.stem + ".converted.xml")
    )

    tree = ET.parse(input_path)
    root = tree.getroot()

    tracks, scope_label = select_tracks(root, args)
    print(f"Scope: {scope_label}")

    total_added = 0
    total_skipped = 0
    touched_tracks = 0
    for track in tracks:
        added, skipped = convert_track(track)
        if added or skipped:
            title = track.get("Name", "(untitled)")
            print(f"  {title}: +{added} mem cues, {skipped} skipped (dup)")
        if added:
            touched_tracks += 1
        total_added += added
        total_skipped += skipped

    print(
        f"Done. {touched_tracks} tracks modified, "
        f"{total_added} memory cues added, {total_skipped} skipped."
    )

    if args.dry_run:
        print("Dry run: no file written.")
        return 0

    tree.write(output_path, encoding="UTF-8", xml_declaration=True)
    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
