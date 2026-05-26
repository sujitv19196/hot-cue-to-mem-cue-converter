# Rekordbox hot cue → memory cue converter

Duplicates every hot cue as a memory cue at the same position. Hot cues are
preserved. Idempotent: running it twice doesn't create duplicate memory cues.

Works via the **Rekordbox XML** round-trip — never touches the encrypted
`master.db`. No dependencies beyond the Python standard library.

## How to use

### 1. Export your library from Rekordbox

1. Rekordbox → **Preferences → Advanced → Database**.
2. Enable **"rekordbox xml"** if it isn't already.
3. **File → Export Collection in xml format** → save somewhere, e.g.
   `~/Desktop/rekordbox.xml`.

### 2. Run the script

```bash
# whole library
python3 convert_cues.py ~/Desktop/rekordbox.xml

# one playlist (case-insensitive name match; works on folders too)
python3 convert_cues.py ~/Desktop/rekordbox.xml --playlist "House Set"

# a single track — pick one of these
python3 convert_cues.py ~/Desktop/rekordbox.xml --track-id 12345
python3 convert_cues.py ~/Desktop/rekordbox.xml --track-name "Strings of Life"
python3 convert_cues.py ~/Desktop/rekordbox.xml --path "/Users/me/Music/track.mp3"

# preview without writing
python3 convert_cues.py ~/Desktop/rekordbox.xml --dry-run
```

Output goes to `<input>.converted.xml` next to the input by default, or pass
`-o /some/path.xml`.

### 3. Import the converted XML back into Rekordbox

1. Rekordbox → **Preferences → Advanced → Database** → under **Imported
   Library**, set **rekordbox xml** to the converted file.
2. The **rekordbox xml** tree appears in the left sidebar.
3. Drag the affected tracks (or a whole playlist) from there into your
   collection. Rekordbox merges the new memory cues into the existing tracks.

**Recommended:** back up `~/Library/Pioneer/rekordbox/master.db` before
importing, just in case.

## What it actually does

- Reads the XML, finds every `<POSITION_MARK>` with `Num != "-1"` (i.e. a hot
  cue) and `Type="0"` (point cue, not a loop).
- For each, appends a duplicate `<POSITION_MARK Num="-1" Type="0">` at the
  same `Start` time, copying `Red`/`Green`/`Blue` color attributes if set.
- Skips if a memory cue already exists at that exact `Start` time.
- Loops (hot-cue loops with an `End` attribute) are intentionally not
  converted in this version.
