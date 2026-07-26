# CLI Usage

This document describes the `volumito` command-line tool.
For using `volumito` as a Python library, see [LIBRARY_USAGE.md](LIBRARY_USAGE.md).

**IMPORTANT**: this document needs to be reworked,
               it might contain wrong pieces of information.

## Basic Command

Query a Volumio instance at the default location (`volumio.local:3000`):

```bash
volumito playback status
```

`volumito info` is a synonym for `volumito system info`.

## Version

Print the `volumito` version:

```bash
volumito version

# Quoted version string, consumable by jq/yq (e.g. "0.0.9")
volumito --machine-readable version
```

## System

Query the Volumio instance's system utilities:

```bash
# Health check (prints "pong")
volumito system ping

# System version and system information (pretty JSON by default)
volumito system version
volumito system info
volumito system info --format table
volumito system info --format raw
```

`volumito info` is a synonym for `volumito system info`.

## Collection

Query the music collection of the Volumio instance:

```bash
# Number of artists, albums, and songs, and the total playtime
volumito collection statistics
volumito collection statistics --format table
```

## Zones

List the multiroom zones seen by the Volumio instance:

```bash
# Host, name, isSelf, and playback state of every zone (default short fields)
volumito zones get
volumito zones get --format table

# All available fields
volumito zones get --fields ALL
```

## Playlists

List and play the playlists saved on the Volumio instance:

```bash
# Names of the saved playlists
volumito playlist list
volumito playlist list --format table

# Play a playlist by name (quote names containing spaces)
volumito playlist play Rock
volumito playlist play "Jazz Classics"

# The name is checked against the saved playlists first, since the Volumio API
# reports no error for a name matching no playlist; skip the check with:
volumito playlist play Rock --no-check-playlist-name
```

## Connection Options

Specify custom connection parameters:

```bash
# Custom host (-H is a shorthand for --host)
volumito playback status --host my-volumio.local
volumito playback status -H 192.168.1.100

# HTTPS connection
volumito playback status --scheme https

# Custom ports (-P for --rest-api-port, -M for --mpd-port)
volumito playback status --rest-api-port 8080 --mpd-port 7000
volumito playback status -P 8080 -M 7000

# Custom timeouts (in seconds)
volumito playback status --rest-api-timeout 10
volumito track audio --mpd-timeout 3

# Pause before the resulting-status fetch (default 1.0 s; see Resulting Status)
volumito --rest-api-sleep-before-next-call 0.5 playback pause
```

The default MPD port is `6600`, as used by Volumio 4.
For Volumio 3 and earlier, which use MPD port `6599`,
pass `--mpd-port 6599`.

## Configuration File

Rather than passing connection and output options on every invocation, you can store them in a
YAML configuration file. Its values are used as **defaults**: an explicit command-line option always
overrides the file, and if neither is given the built-in defaults apply. The precedence is:

```
command-line option  >  configuration file  >  built-in default
```

Point at an explicit file with `-c`/`--configuration-file`:

```bash
volumito -c /path/to/volumito.yaml playback status
```

If `-c` is omitted, the following directories are probed in order (highest priority first), and within
each directory `volumito.yaml` is tried before `.volumito.yaml`. The first file that exists is used:

1. the current working directory
2. the home directory (`~`)
3. `~/.volumito`
4. `~/.config/volumito`
5. `/etc` (POSIX only)
6. `/etc/volumito` (POSIX only, lowest priority)

The `/etc` locations are probed only on POSIX systems (Linux, macOS); they are skipped on Windows.

If none exists, the built-in defaults are used. A file named with `-c` that does not exist, invalid
YAML, or an unrecognized section/key is an error.

All sections and keys are optional. Keys mirror the CLI long options (without the leading `--`):

```yaml
volumio:
  host: volumio.local
  scheme: https
  rest-api-port: 3000
  mpd-port: 6600
timeouts:
  rest-api-timeout: 5.0
  mpd-timeout: 5.0
  rest-api-sleep-before-next-call: 1.0
miscellaneous:
  check-playlist-name: true
  check-seek-position: true
output:
  verbose: true
  machine-readable: false
  position-starting-at-one: true
  print-resulting-status: true
  # fields/format here apply to all display commands...
  format: pretty
  playback-status:
    # ...and can be overridden per command.
    format: table
  track-info:
    format: json
  playlist-list:
    format: table
  collection-statistics:
    format: table
downloads:
  # Keys here apply to both track download commands...
  overwrite-existing-files: false
  create-download-manifest: true
  track-audio:
    # ...and can be overridden per command.
    file-name-template: "{position:03d}_{title}.{extension}"
    output-directory: ~/Music
  track-albumart:
    file-name-template: "{album}.{extension}"
    output-directory: ~/Covers
```

The `output` section's `fields` and `format` keys set the defaults for the corresponding
`--fields`/`--format` options of the commands that support them: `format` applies to `playback status`,
`track info`, `queue get`, `zones get`, `playlist list`, `system version`, `system info`, and
`collection statistics`, while `fields` applies to the first four only. A key placed directly under
`output` applies to all the commands accepting it; the optional `playback-status`, `track-info`,
`queue-get`, `playlist-list`, `zones-get`, `system-version`, `system-info`, and
`collection-statistics` subsections hold the same keys and override the shared value
for that command
(`system-info` also covers the top-level `info` synonym). The `print-resulting-status` key sets the
default for the `-r` option of the `playback` action commands (`toggle`, `play`, `pause`, `stop`, `next`,
`previous`, `seek`, `volume`, `mute`, `unmute`), the `queue` action commands (`clear`, `repeat`, `randomize`),
and `playlist play`.
The `verbose`, `machine-readable`, and `position-starting-at-one` keys set the defaults for the
corresponding global options and cannot be overridden per command.

The `miscellaneous` section holds the defaults of options belonging to specific commands: its
`add-cover-and-metadata` key sets the default for `track audio` and `queue download`;
`with-albumart`, `check-next-track`, and `number-retries-next-track` set the defaults for the
corresponding `queue download` options; and `check-playlist-name` and `check-seek-position`
set the defaults for the corresponding options of `playlist play` and `playback seek`.

The `downloads` section sets the defaults for the `--file-name-template`, `--output-directory`,
`--output-file`, `--overwrite-existing-files`, `--create-download-manifest`,
`--replace-characters-in-file-names`, and `--replace-characters-in-file-names-with` options of
`track audio`, `track albumart`, and `queue download`. A key
placed directly under `downloads` applies to all of them; the optional `track-audio`,
`track-albumart`, and `queue-download`
subsections hold the same keys and override the shared value for that command (so each can have its own
`file-name-template`). The `queue-download` subsection takes `audio-file-name-template` and
`albumart-file-name-template` instead of
`file-name-template` (matching its `--audio-file-name-template` and
`--albumart-file-name-template` options) and has no `output-file`.

The `configuration` command group helps manage these files:

```bash
# Create a volumito.yaml pre-filled with the default configuration
volumito configuration create                       # in the current directory
volumito configuration create -d ~/.config/volumito # in a directory (created if needed)
volumito configuration create -f ./my-config.yaml   # at an exact path
# Target a Volumio version to set the MPD port (6599 for < 4, otherwise 6600; default 4)
volumito configuration create --volumio-version 3   # Volumio 3 -> mpd-port 6599
# By default an existing file is not overwritten; pass --overwrite-existing-files to force it.

# Validate a configuration file and print the values read from it
volumito configuration check ./volumito.yaml
volumito configuration check            # no path: check the file that would be used

# List every probed configuration path, in probing order, showing which exist and which is used
volumito configuration search
```

## Output Formats

Choose from multiple output formats:

```bash
# Pretty JSON with 4-space indentation (default)
volumito playback status --format pretty

# Compact JSON with 2-space indentation
volumito playback status --format json

# Human-readable table (-F is a shorthand for --format)
volumito playback status --format table
volumito playback status -F table

# Raw unformatted JSON, exactly as returned by the API
volumito playback status --format raw
volumito playback status -F raw
```

## Position Indexing

Queue positions are indexed starting at one by default; the global
`--position-starting-at-zero` flag switches to the zero-based indexing used by the Volumio API
(track numbers coming from the track metadata, like the `{tracknumber}` template key, are
absolute and unaffected):

```bash
# Positions start at one (default)
volumito playback status -F table
volumito queue get -F table

# Positions start at zero
volumito --position-starting-at-zero playback status -F table
volumito --position-starting-at-zero queue get -F table
```

The flag applies to the `--position` option of `playback play`, to the positions shown by the
`pretty` and `table` formats, and to the `{position}` key of `-f`/`--file-name-template`.
The `json` and `raw` formats are unaffected: they always print the position as returned by the API.

## Field Filtering

Control which fields are displayed. The `-L`/`--fields` value is one of the uppercase keywords
`SHORT` or `ALL`, or a comma-separated list of field names to show exactly those fields (in the
given order; unknown or absent names are silently skipped):

```bash
# Show only key playback information (the default, SHORT)
volumito playback status --fields SHORT

# Show all available fields (-L is a shorthand for --fields)
volumito playback status --fields ALL
volumito playback status -L ALL

# Show only the given fields, in order
volumito playback status -L artist,album,title
```

The `SHORT` fields include:
- status
- position
- title
- artist
- album
- duration
- seek
- volume
- mute
- trackType
- samplerate
- bitdepth
- channels

## Verbosity Control

```bash
# Verbose mode
volumito playback status --verbose

# Machine-readable mode (always supersedes the verbose option)
volumito playback status --machine-readable
```

## Volume Control

Set, adjust, or show the playback volume:

```bash
# Print the current volume (no value)
volumito playback volume

# Set an absolute level (integer between 0 and 100)
volumito playback volume 75

# Step the volume one click up or down
volumito playback volume plus     # also: increase, up
volumito playback volume minus    # also: decrease, down

# Mute and unmute
volumito playback volume mute
volumito playback volume unmute

# `playback mute` and `playback unmute` are synonyms for the two commands above
volumito playback mute
volumito playback unmute
```

## Seek Control

Print, set, or adjust the position within the track being played:

```bash
# Print the current position as HH:MM:SS.mmm (no value)
volumito playback seek

# Seek to an absolute position, in seconds or as a HH:MM:SS (or MM:SS) time
volumito playback seek 252
volumito playback seek 04:12
volumito playback seek 01:04:12

# Seek relatively (the step is the one applied by the Volumio instance)
volumito playback seek plus     # also: increase, up, forward
volumito playback seek minus    # also: decrease, down, backward

# An absolute position is checked against the duration of the current track
# (when known: web radios and streams report none); skip the check with:
volumito playback seek 3600 --no-check-seek-position
```

## Playing A Queue Position

Start playback of a specific track in the queue (indexed as per Position Indexing above,
i.e. starting at one by default):

```bash
# -p is a shorthand for --position
volumito playback play --position 3
volumito playback play -p 3

# The same track, with the zero-based indexing
volumito --position-starting-at-zero playback play -p 2
```

## Queue

Inspect and manage the playback queue:

```bash
# Print the current queue (same --fields/--format options as playback status)
volumito queue get
volumito queue get --format table

# Clear the queue
volumito queue clear

# Toggle the repeat and random (shuffle) modes (no value toggles the current mode)
volumito queue repeat
volumito queue randomize

# Set the modes explicitly with on/true/yes/1 or off/false/no/0
volumito queue repeat on
volumito queue randomize off
```

The `repeat` and `random` modes are properties of playback, so — like the `playback` action commands —
`queue clear`, `queue repeat`, and `queue randomize` wait and print the resulting `playback status`
afterward by default. Disable that with `--no-print-resulting-status` (short flag `-r` /
`--print-resulting-status`):

```bash
# Clear the queue without printing the resulting playback status
volumito queue clear --no-print-resulting-status
```

### Downloading the Queue

`queue download` downloads every track of the current queue. Each run creates a timestamped
directory (e.g. `20260726121314`, UTC) inside `-d`/`--output-directory` (required) and downloads
into it; an existing directory with the same timestamp is only reused with
`--overwrite-existing-files`. Playback is stopped, then each queue position is played,
paused after the configured `--rest-api-sleep-before-next-call` (default 1.0 s), and downloaded;
at the end, playback is left stopped at the first track. The exit code is 1 if any track failed.

Before each download, the fetched metadata are verified against the queue listing retrieved at
the start of the run: the state's title, artist, and album must match the queue entry of the
position just played, the state position must match, and the track URI must differ from the
previous track's (unless the queue really lists the same URI twice); on a stale read, the
play/pause/fetch cycle is retried up to `--number-retries-next-track` times (default 5) before
recording an `error` for that track. Disable the verification with `--no-check-next-track`
(`--check-next-track` restores it).

```bash
# Download the whole queue into per-artist/per-album subdirectories
volumito queue download -d ~/Music -f "{artist}/{album}/{tracknumber:03d}_{title}.{extension}"
```

The file name is rendered from `-f`/`--audio-file-name-template` exactly as for `track audio`'s
`--file-name-template`
(same keys, character replacement, and sanitization). The `{tracknumber}` key renders the
track's number within its album, taken from the queue metadata, so with several albums queued
each album keeps its own numbering (while `{position}` stays the queue position); the same
number is embedded
as the track-number tag when `--add-cover-and-metadata` is on. One further difference: the
template may
contain path separators to lay the files out in subdirectories, which are created as needed.
The resulting path must stay inside the output directory (values interpolated from the
metadata still cannot introduce path components). The other download options
(`--overwrite-existing-files`, `--create-download-manifest`, `--add-cover-and-metadata`,
`--replace-characters-in-file-names`, `--replace-characters-in-file-names-with`) apply per
track.

With `--with-albumart` (the default; disable with `--no-with-albumart`), each album's cover is
saved under the name rendered from `--albumart-file-name-template` (default
`{file_name_from_uri}`, same keys and sanitization as the audio template, relative to the run
directory; the generated configuration file showcases
`{artist}/{album}/000___{album}.{extension}`, placing the cover next to its album's tracks).
Every distinct cover is downloaded only once per run, and an existing cover file is reused
unless `--overwrite-existing-files` is given; a failed cover download is reported as a warning
and does not fail the track.

Each run also writes a `queue.json` log into its timestamped directory, listing every track
with its download status (`pending`, `downloaded`, `skipped`, or `error`); the log is updated
after each track, so an interrupted run leaves a valid partial log. In machine-readable mode
the log path is printed as a quoted string.

## Resulting Status

By default, every `playback` action subcommand (`toggle`, `play`, `pause`, `stop`, `next`, `previous`,
`volume`, `mute`, `unmute`) waits before fetching and printing the resulting `playback status`. The pause
is 1 second by default; change it with the global `--rest-api-sleep-before-next-call` option. Disable
the whole behavior with `--no-print-resulting-status`:

```bash
# Pause, then show the resulting status (default)
volumito playback pause

# Use a shorter pause before the resulting status
volumito --rest-api-sleep-before-next-call 0.5 playback pause

# Pause without printing the resulting status
volumito playback pause --no-print-resulting-status
```

## Examples

Combine options for specific use cases:

```bash
# Table format with all fields
volumito playback status --format table --fields ALL

# Pipe to jq for advanced JSON processing
volumito playback status --format raw | jq '.title, .artist'

# Save state to file
volumito playback status --format json > volumio_state.json

# Monitor playback every 5 seconds
while true; do
    clear
    volumito playback status --format table
    sleep 5
done
```

## Track Information

Show metadata for the currently playing track. This works like `playback status`
(same `--fields`/`--format` options, and their `-L`/`-F` shorthands),
but its default `short` field set is track-oriented:

```bash
# Track-oriented short fields (default)
volumito track info

# All available fields, as compact JSON
volumito track info -L ALL -F json

# Raw unfiltered JSON
volumito track info -F raw
```

Its short fields are:
- position
- title
- artist
- album
- duration
- trackType
- samplerate
- bitdepth
- channels

## Album Art

Get the current album art URI:

```bash
# Get URI only
volumito track albumart

# Download to an exact file path (-o)
volumito track albumart -o /path/to/cover.jpg

# Download into a directory, using the file name from the URI (-d)
volumito track albumart -d /path/to/covers/

# Machine-readable mode prints the URI as a quoted string, consumable by jq/yq
volumito -m track albumart          # => "http://volumio.local:3000/albumart?..."
volumito -m track audio             # => "http://volumio.local:8000/music/..."
```

The `-o`/`--output-file` and `-d`/`--output-directory` options are mutually exclusive.
`track audio` accepts the same two download options:

```bash
# Download the current track to an exact file path
volumito track audio -o /path/to/song.flac

# Download the current track into a directory (file name taken from the URI)
volumito track audio -d /path/to/music/
```

By default, a download will not overwrite an existing destination file (it errors
out instead). Pass `--overwrite-existing-files` to allow overwriting:

```bash
volumito track albumart -o /path/to/cover.jpg --overwrite-existing-files
volumito track audio -d /path/to/music/ --overwrite-existing-files
```

By default, each download also writes a JSON manifest next to the downloaded file
(e.g. `song.flac.json` next to `song.flac`) recording the download date, the Volumio
host, the source URI, the output paths, and the full player state at download time.
Pass `--no-create-download-manifest` to skip it:

```bash
# Writes /path/to/song.flac and /path/to/song.flac.json
volumito track audio -o /path/to/song.flac

# Downloads without the sidecar manifest
volumito track audio -o /path/to/song.flac --no-create-download-manifest
```

The manifest is a JSON object with its keys in lexicographic order, for example:

```json
{
  "add_cover_and_metadata": true,
  "download_date": "2026-07-24T10:22:31.123456+00:00",
  "entity": "track",
  "kind": "audio",
  "output_file_name": "song.flac",
  "output_file_path": "/path/to/song.flac",
  "source_uri": "qobuz://song/2581513",
  "state": { "...the full player state..." },
  "volumio_host": "http://volumio.local:3000",
  "volumito_version": "0.0.14"
}
```

The `add_cover_and_metadata` field records whether the download embedded metadata and cover art;
it is present only in the `track audio` manifest.

For `track audio`, the current track's metadata (title, artist, album, album artist, and track
number) and cover art are, by default, embedded into the downloaded file. FLAC, MP3, and MP4/M4A
files are supported; for any other format the download is kept untouched and a warning is printed.
Pass `--no-add-cover-and-metadata` to skip embedding:

```bash
# Downloads and tags the file with metadata and cover art
volumito track audio -o /path/to/song.flac

# Downloads the raw audio without touching its tags
volumito track audio -o /path/to/song.flac --no-add-cover-and-metadata
```

When downloading into a directory with `-d`, the file name is built from
`-f`/`--file-name-template` (Python `str.format` syntax, default
`{file_name_from_uri}`). Each character listed in `--replace-characters-in-file-names`
(default: space and colon) is replaced with the `--replace-characters-in-file-names-with`
string (default: `_`); pass an empty string to the former to disable the replacement:

```bash
# e.g. writes /path/to/music/001_La_rondine.flac
volumito track audio -d /path/to/music/ -f "{position:03d}_{title}.{extension}"
```

Supported template keys:
- `file_name_from_uri` — the file name taken from the URI (the default)
- `position` — track position, indexed as per Position Indexing (e.g. `{position:03d}` → `001`)
- `tracknumber` — the track number of the track within its album, taken from the queue metadata
  by `queue download` (used verbatim, not affected by Position Indexing; 0 when unavailable)
- `title`, `album`, `artist`, `trackType`, `bitdepth`, `samplerate` — strings
- `duration` — track length as `HH:MM:SS`
- `channels` — integer
- `extension` — the file extension from the URI, defaulting to `flac` for
  `track audio` and `jpg` for `track albumart`

The rendered name is sanitized: path separators and control characters in the interpolated
metadata are neutralized, leading dots are stripped, and the template must render to a plain
file name (no path separators), so a download cannot escape the `-d` directory.
