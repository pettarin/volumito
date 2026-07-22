# volumito

Python client library and CLI tool for Volumio.


## Overview

`volumito` is a Python library and a command-line tool
that allows you to interact with your
[Volumio](https://volumio.com/)
player, programmatically or on a shell.


## Features

- Clean Python API to connect to and control a Volumio player
- Built-in comprehensive command-line tool with a lot of options
- Optional YAML configuration file for connection and output defaults
- Type-safe implementation with full type hints
- Comprehensive test coverage (100%)


## Requirements

- Python 3.13 or later
- A running Volumio player


## Installation

### From PyPI

Activate your virtual environment (`volumito_env`),
and install:

```bash
(volumito_env) $ pip install volumito
```

### From Source

Clone the repository and install from source
in a virtual environment:

```bash
$ git clone https://github.com/pettarin/volumito
$ cd volumito

$ # here Micromamba is used, choose your favorite
$ # package/virtual environment manager
$ micromamba env create -f environment.yml
$ micromamba activate volumito_dev

(volumito_dev) $ pip install -e .
(volumito_dev) $ # or
(volumito_dev) $ make install-e-this

(volumito_dev) $ # for developing volumito, use the dev configuration:
(volumito_dev) $ pip install -e .[dev]
(volumito_dev) $ # or
(volumito_dev) $ make install-e-this-dev
```

## Usage

### Basic Command

Query a Volumio instance at the default location (`volumio.local:3000`):

```bash
volumito playback status
```

`volumito info` is a synonym for `volumito playback status`.

### Version

Print the `volumito` version:

```bash
volumito version

# Quoted version string, consumable by jq/yq (e.g. "0.0.9")
volumito --machine-readable version
```

### Connection Options

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

### Configuration File

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
5. `/etc` (lowest priority)

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
output:
  verbose: true
  machine-readable: false
  print-resulting-status: true
  # fields/format/raw here apply to all display commands...
  format: pretty
  playback-status:
    # ...and can be overridden per command.
    format: table
  track-info:
    format: json
downloads:
  # Keys here apply to both track download commands...
  overwrite-existing-files: false
  track-audio:
    # ...and can be overridden per command.
    file-name-template: "{position:03d}_{title}.{extension}"
    output-directory: ~/Music
  track-albumart:
    file-name-template: "{album}.{extension}"
    output-directory: ~/Covers
```

The `output` section's `fields`, `format`, and `raw` keys set the defaults for the corresponding
`--fields`/`--format`/`--raw` options of the commands that support them (`playback status`, `info`,
`track info`, and `queue list`). A key placed directly under `output` applies to all of them; the optional
`playback-status`, `track-info`, and `queue-list` subsections hold the same keys and override the shared value
for that command (`playback-status` also governs the `info` synonym). The `print-resulting-status` key sets the
default for the `-r` option of the `playback` action commands (`toggle`, `play`, `pause`, `stop`, `next`,
`previous`, `volume`, `mute`, `unmute`).

The `downloads` section sets the defaults for the `--file-name-template`, `--output-directory`,
`--output-file`, and `--overwrite-existing-files` options of `track audio` and `track albumart`. A key
placed directly under `downloads` applies to both commands; the optional `track-audio` and `track-albumart`
subsections hold the same keys and override the shared value for that command (so each can have its own
`file-name-template`).

The `configuration` command group helps manage these files:

```bash
# Create a volumito.yaml with all keys set to their default values
volumito configuration create                       # in the current directory
volumito configuration create -d ~/.config/volumito # in a directory (created if needed)
volumito configuration create -f ./my-config.yaml   # at an exact path
# By default an existing file is not overwritten; pass --overwrite-existing-files to force it.

# Validate a configuration file and print the values read from it
volumito configuration check ./volumito.yaml
volumito configuration check            # no path: check the file that would be used

# List every probed configuration path, in probing order, showing which exist and which is used
volumito configuration search
```

### Output Formats

Choose from multiple output formats:

```bash
# Pretty JSON with 4-space indentation (default)
volumito playback status --format pretty

# Compact JSON with 2-space indentation
volumito playback status --format json

# Human-readable table (-F is a shorthand for --format)
volumito playback status --format table
volumito playback status -F table

# Raw unformatted JSON (-R is a shorthand for --raw)
volumito playback status --raw
volumito playback status -R
```

### Field Filtering

Control which fields are displayed:

```bash
# Show only key playback information (default)
volumito playback status --fields short

# Show all available fields (-L is a shorthand for --fields)
volumito playback status --fields all
volumito playback status -L all
```

Short fields include:
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

### Verbosity Control

```bash
# Verbose mode
volumito playback status --verbose

# Machine-readable mode (always supersedes the verbose option)
volumito playback status --machine-readable
```

### Volume Control

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

### Playing A Queue Position

Start playback of a specific track in the queue (1-indexed):

```bash
# -p is a shorthand for --position
volumito playback play --position 3
volumito playback play -p 3
```

### Resulting Status

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

### Examples

Combine options for specific use cases:

```bash
# Table format with all fields
volumito playback status --format table --fields all

# Pipe to jq for advanced JSON processing
volumito playback status --raw | jq '.title, .artist'

# Save state to file
volumito playback status --format json > volumio_state.json

# Monitor playback every 5 seconds
while true; do
    clear
    volumito playback status --format table
    sleep 5
done
```

### Track Information

Show metadata for the currently playing track. This works like `playback status`
(same `--fields`/`--format`/`--raw` options, and their `-L`/`-F`/`-R` shorthands),
but its default `short` field set is track-oriented:

```bash
# Track-oriented short fields (default)
volumito track info

# All available fields, as compact JSON
volumito track info -L all -F json

# Raw unfiltered JSON
volumito track info -R
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

### Album Art

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

When downloading into a directory with `-d`, the file name is built from
`-f`/`--file-name-template` (Python `str.format` syntax, default
`{file_name_from_uri}`). Any space in the resulting name becomes an underscore:

```bash
# e.g. writes /path/to/music/001_La_rondine.flac
volumito track audio -d /path/to/music/ -f "{position:03d}_{title}.{extension}"
```

Supported template keys:
- `file_name_from_uri` — the file name taken from the URI (the default)
- `position` — 1-indexed track position (e.g. `{position:03d}` → `001`)
- `title`, `album`, `artist`, `trackType`, `bitdepth`, `samplerate` — strings
- `duration` — track length as `HH:MM:SS`
- `channels` — integer
- `extension` — the file extension from the URI, defaulting to `flac` for
  `track audio` and `jpg` for `track albumart`

## API Reference

TODO


## Releases And Changelog

See the [CHANGELOG](CHANGELOG.md) file for the list of releases and their changes.


## Development

See [DEVELOPMENT.md](DEVELOPMENT.md) for how to set up a development environment,
run the tests, the project structure, and contributing.


## License

This project is licensed under
the GNU General Public License v3.0 or later (GPLv3+).

See the [LICENSE](LICENSE) file for details.


## Authors

- Alberto Pettarin ([Web](https://www.albertopettarin.it))


## Legal Disclaimers

Volumio and Volumio logo are a registered trademark of Volumio SRL,
a company registered in Italy (VAT ID: IT07009020483).

Please refer to the [Volumio Terms Of Service](https://volumio.com/terms-of-service/).

This project and its authors are not affiliated
nor endorsed by Volumio SRL.
