# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).


## [0.0.31] - 2026-08-03

### Added

- Option `-T`/`--only-tracks` for `queue download` and `playlist download`, downloading
  only the tracks at the given queue positions (e.g., `1-3,6-8,12`)

### Fixed

- The stale-metadata check compares the fetched track with the previously played one,
  instead of the queue entry before it


## [0.0.30] - 2026-08-03

### Added

- Pydantic models of the Volumio API responses (`PlayerState`, `Queue`, `QueueTrack`,
  `Playlists`, `Playlist`, `SystemInfo`, `SystemVersion`, `DeviceState`,
  `CollectionStatistics`, `Zones`, `Zone`, `Story`, `CommandResponse`), each keeping
  the payload it was parsed from in its `raw` attribute
- Exception `VolumioStoryError`, raised when the Volumio host reports a failed story query
- Flags `is_playing`, `is_paused`, and `is_stopped` on the playback state model
- The queue tracks carry their position, so the client plays a `QueueTrack` (and a
  `Playlist`) directly

### Changed

- The REST API client returns the response models instead of the raw JSON (including
  the playlists, which are now a `Playlists` collection instead of a list of names):
  the model fields are snake_case (with the Volumio names as aliases), and a value
  that does not fit its field is ignored instead of failing the whole response
- The story query methods return the story itself, raising `VolumioStoryError` when the
  Volumio host reports a failure
- The CLI works on the response models, reading the raw payload only where the output
  is the payload itself (the display formats and the download manifests)

### Fixed

- A story query the Volumio host cannot answer exits 1 reporting the error, instead of
  printing an empty result


## [0.0.29] - 2026-08-03

### Added

- Option `--manifest-file` for `queue download` and `playlist download`, setting the
  path of the download manifest with the `{output_directory}` and `{timestamp}`
  placeholders
- The `queue download` and `playlist download` commands resume from an existing
  manifest file: tracks already downloaded, or skipped with their file still present,
  are kept without replaying them, and with nothing to retry the playback is left
  untouched
- The download commands print the path of the manifest file being created or read

### Changed

- The download manifest of `queue download` and `playlist download` is written to
  `manifest.json` (was `queue.json`) inside the output directory by default
- The manifest records `first_download_date`, `last_update_date`, and the `updates`
  visit counter, instead of `download_date`
- Increased the default of `--rest-api-sleep-before-next-call` to 2.0 seconds and of
  `--number-retries-next-track` to 10


## [0.0.28] - 2026-08-03

### Changed

- The `playback play` command takes the queue position as an optional positional
  argument, instead of the `-p`/`--position` option


## [0.0.27] - 2026-08-03

### Added

- The `configuration check` command reports the download subsections whose effective
  values set both the output file and the output directory
- The `configuration check` command reports every problem found in the file as a
  numbered list, instead of stopping at the first one

### Changed

- The machine-readable error output of `configuration check` carries an `errors` list
  instead of a single `error` string

### Fixed

- An explicit `-o`/`--output-file` or `-d`/`--output-directory` option overrides the
  other destination set in the configuration file, instead of raising the
  mutual-exclusivity error


## [0.0.26] - 2026-08-03

### Changed

- Renamed the `queue get` command to `queue list` and the corresponding configuration key
- Renamed the `zones get` command to `zones list` and the corresponding configuration key


## [0.0.25] - 2026-08-03

### Added

- Shorthand `-i` for the global `--ignore-configuration-file` option

### Changed

- Reviewed the help messages of all CLI commands for conciseness and uniform style
- The machine-readable output of `configuration check` is an envelope with the file
  path, the validity flag, and the configuration or the error

### Fixed

- The `configuration check` command prints the keys in lexicographic order, separated
  from the validity line by a blank line
- The `configuration check` command reports an invalid or missing configuration file
  with a "NOT valid" message and exit code 1, instead of a usage error


## [0.0.24] - 2026-08-03

### Added

- Placeholder `{timestamp}` in the download output directory path, replaced with the
  current UTC time

### Changed

- Commands `queue download` and `playlist download` no longer create a timestamped
  directory inside the output directory
- The download commands create the output directory if missing


## [0.0.23] - 2026-07-28

### Added

- Commands `playback is_muted`, `is_paused`, `is_playing`, and `is_stopped`, printing
  the corresponding playback flags
- Methods `get_story` and `get_album_credits` to the REST API client, taking the new
  entity dataclasses `Album`, `Artist`, `Label`, and `Place` (by free text or MBID)
- Methods `increase_volume` and `decrease_volume` to the REST API client
- Methods `mute` and `unmute` to the REST API client
- Methods `seek_forward` and `seek_backward` to the REST API client
- Read-only properties `is_muted`, `is_paused`, `is_playing`, and `is_stopped`
  to the REST API client

### Changed

- The CLI mute/unmute operations call the new client methods instead of passing the special
  `mute`/`unmute` values to the volume method
- The REST API client seek is now a read/write property, working in seconds: reading it
  returns the current position from the playback state (rounded down to whole seconds),
  and assigning it seeks to an absolute position; the CLI relative seeking calls the new
  seek methods instead of passing the special `plus`/`minus` values
- The REST API client volume is now a read/write property: reading it returns the current
  level from the playback state, and assigning it sets an integer level, validated to be
  between 0 and 100; the CLI volume stepping calls the new volume methods instead of
  passing the special `plus`/`minus` values
- The REST API client query methods are now read-only properties: `get_state` -> `state`,
  `get_queue` -> `queue`, `get_system_version` -> `system_version`, `get_system_info` ->
  `system_info`, `collectionstats` -> `collection_statistics`, `get_zones` -> `zones`,
  `list_playlists` -> `playlists`
- The REST API client `send_command` method is now private (`_send_command`), proxied by
  the public playback and queue methods
- The REST API client `plugin_endpoint` method is now private (`_plugin_endpoint`), proxied
  by the story query methods, which the CLI story commands now call


## [0.0.22] - 2026-07-27

### Added

- Command group `story` with subcommands `album`, `artist`, `credits`, `label`, and `place`,
  querying the Volumio Premium metavolumio plugin endpoint
- Option `--current-track` for `story album`, `story artist`, and `story credits`,
  taking the values from the currently playing track
- Subsections for the `story` subcommands of the `output` section of the configuration file
- Dotted field names (e.g., `data.value`) in the `--fields` option, selecting fields nested
  inside the response


## [0.0.21] - 2026-07-26

### Added

- Command `playlist download`, clearing the queue, playing the given playlist, and downloading
  the resulting queue like `queue download`, with the options of both commands
- Subsection for the `playlist download` subcommand of the `downloads` section
  of the configuration file

### Fixed

- The album art is saved in every directory it renders to (e.g., one per volume of a
  multi-volume album, plus the album directory itself), copying the already-downloaded
  cover instead of re-downloading it


## [0.0.20] - 2026-07-26

### Added

- Template key `{album_volume}` for `queue download`, rendering the album name with the volume
  number appended when the queue holds several volumes of the same album
- Fields `tracknumber` and `volumeNumber` to the `queue get` default short field set

### Changed

- The queue download log records the track number under `track_number` and adds `volume_number`


## [0.0.19] - 2026-07-26

### Changed

- Moved the queue-download retry and album-art defaults from the `miscellaneous` section
  to the `downloads` section of the configuration file


## [0.0.18] - 2026-07-26

### Added

- Global option `--ignore-configuration-file`, skipping the configuration file lookup
  and application (`configuration search` marks the found files as ignored, and
  `configuration check` fails)


## [0.0.17] - 2026-07-26

### Added

- Command `queue download`, downloading every track of the current queue into a timestamped
  per-run directory of the output directory, with a `queue.json` log of each download's status
- For `queue download`, the file-name template may contain path separators to lay the files
  out in subdirectories of the output directory, created as needed
- Options `--check-next-track`/`--no-check-next-track` (default on) and
  `--number-retries-next-track` for `queue download`, verifying with retries that each track's
  metadata are current before downloading it
- Option `--with-albumart`/`--no-with-albumart` (default on) for `queue download`, saving each
  album's cover under the `--albumart-file-name-template` name, downloading every distinct
  cover only once
- The next-track-check and with-albumart defaults can be set in the `miscellaneous` section
  of the configuration file
- Subsection for the `queue download` subcommand of the `downloads` section
  of the configuration file


## [0.0.16] - 2026-07-26

### Added

- Options `--replace-characters-in-file-names`/`--replace-characters-in-file-names-with` for
  `track audio` and `track albumart`, selecting the characters replaced in the generated file
  name and their replacement (by default, spaces and colons become underscores)
- The replace-characters defaults can be set in the `downloads` section of the configuration file

### Security

- Path separators and control characters in the metadata interpolated into the generated file
  name are neutralized, and the template must render to a plain file name, so a download cannot
  escape the output directory


## [0.0.15] - 2026-07-26

### Added

- Option `--volumio-version` for `configuration create`, setting the MPD port from the target
  Volumio version
- Probe `/etc` and `/etc/volumito` for a configuration file on POSIX systems

### Changed

- The `configuration create` command now writes a bundled, curated configuration template


## [0.0.14] - 2026-07-24

### Added

- Option `--create-download-manifest`/`--no-create-download-manifest` (default on) for `track audio`
  and `track albumart`, writing a JSON manifest next to the downloaded file
- The download-manifest default can be set in the `downloads` section of the configuration file
- Option `--add-cover-and-metadata`/`--no-add-cover-and-metadata` (default on) for `track audio`,
  embedding the track metadata and cover art into the downloaded FLAC, MP3, or MP4/M4A file
- The cover-and-metadata default can be set in the `miscellaneous` section of the configuration file

### Changed

- Moved the documentation to the `docs` directory, with the CLI usage and the new library usage
  in their own files
- Cleaned `volumito.py` module up, breaking it into several modules
- The `-L`/`--fields` option now takes the uppercase keywords `ALL` or `SHORT`, or a comma-separated
  list of field names to display exactly those fields


## [0.0.13] - 2026-07-23

### Added

- Command `playback seek`: with no value prints the current position as HH:MM:SS.mmm; otherwise
  accepts `plus`, `minus`, a number of seconds, or a HH:MM:SS (or MM:SS) time
- Option `--check-seek-position`/`--no-check-seek-position` (default on) for `playback seek`,
  checking that an absolute position is within the duration of the current track
- Command group `playlist` with the `list` and `play` commands
- Option `--check-playlist-name`/`--no-check-playlist-name` (default on) for `playlist play`,
  checking that the given name matches an existing playlist
- Subsection for the `playlist list` subcommand of the `output` section
  of the configuration file
- Configuration file section `miscellaneous` for the defaults of the options belonging
  to a single command

### Changed

- In verbose mode, the connection message prints the base URL instead of the full endpoint


## [0.0.12] - 2026-07-23

### Added

- Global option `--position-starting-at-one`/`--position-starting-at-zero` selecting the indexing
  of the `--position` option and of the displayed positions

### Changed

- The `--position` option of `playback play` now rejects a position below the minimum of the
  selected indexing

### Fixed

- In `pretty` format, `position` is printed as an integer instead of a string
- In `table` format, the entry numbers of the queue and of the zones are right-aligned and their
  key/value lines are indented accordingly


## [0.0.11] - 2026-07-22

### Added

- Command group `collection` with the `statistics` command
- Command group `zones` with the `get` command
- Command group `system` with `ping`, `version`, and `info` commands
- Commands `queue clear`, `queue repeat`, and `queue randomize` to clear the queue and set the
  repeat and random modes
- Subsections for the `system` and `collection` subcommands of the `output` section
  of the configuration file

### Changed

- The top-level `info` command is now an alias for `system info` instead of `playback status`
- Renamed the `queue list` command to `queue get` and the corresponding configuration key
- Renamed the `player` command group to `playback` and its `state` subcommand to `status`
  and the corresponding configuration key
- Renamed the `Volumio State` heading in table format output to `Volumio Status`
- Renamed the `-r`/`--print-resulting-state` option to `-r`/`--print-resulting-status`
  and the corresponding configuration key
- `configuration search` now lists every probed path (directory and file name) in probing order,
  marking the existing files as used or not used, instead of stopping at the first one found
- The `-F`/`--format` option accepts the new value `raw`
- The `system version` and `system info` commands now accept `-F`/`--format`
- In table format, nested objects are printed one key/value per line and indented

### Removed

- The `-R`/`--raw` option and the corresponding configuration key
- The `configuration locations` subcommand, superseded by the new behavior
  of `configuration search`


## [0.0.10] - 2026-07-20

### Added

- Support for a YAML configuration file, whose values are used as option defaults (explicit
  command-line options still override them)
- Option `-c`/`--configuration-file` to select a configuration file, with probing of standard
  locations in the current and home directories when omitted
- Configuration file sections `volumio`, `timeouts`, and `output` for connection, timeout, and
  output-formatting defaults (the `output` display options can be set per command)
- Configuration file section `downloads` for the `track audio`/`track albumart` download-option
  defaults, shared or set per command
- Command group `configuration` with `create`, `check`, `search`, and `locations` subcommands to
  manage configuration files

### Changed

- Renamed the `-d`/`--output-dir` option to `-d`/`--output-directory` on `track audio`, `track albumart`,
  and `configuration create` (the `-d` short flag is unchanged)


## [0.0.9] - 2026-07-20

### Added

- Fields `trackType`, `samplerate`, `bitdepth`, and `channels` to the `player state` default
  short field set
- Command `track info` to show the current track's metadata (with `--fields`/`--format`/`--raw`)
- Short options for frequently used options (`-H`, `-M`, `-P`, `-p`, `-F`, `-L`, `-R`)
- Option `-d`/`--output-dir` for `track audio` and `track albumart` to download into a directory
- Option `--overwrite-existing-files`/`--no-overwrite-existing-files` for `track audio` and
  `track albumart`
- Option `-f`/`--file-name-template` for `track audio` and `track albumart` to build the output
  file name from a template

### Changed

- In machine-readable mode, `track audio` and `track albumart` now print their URI as a quoted string
- The `-o`/`--output-file` option of `track audio` and `track albumart` now downloads to the exact
  path given


## [0.0.8] - 2026-07-19

### Changed

- Sort the CLI options alphabetically in `--help` (global options and every subcommand)
- In machine-readable mode, `version` now prints the version as a quoted string (e.g., `"0.0.8"`)
  so it can be consumed by tools like `jq` and `yq`


## [0.0.7] - 2026-07-19

### Added

- Fields `status`, `seek`, `volume`, and `mute` to the default short field set
  (`info --fields short`)
- Command `player volume`: with no value prints the current volume; otherwise accepts `mute`,
  `unmute`, `plus` (also `increase`/`up`), `minus` (also `decrease`/`down`), or an integer 0-100;
  includes `player mute` and `player unmute` synonyms, backed by the volume REST API
- Option `-r`/`--print-resulting-state` (default on) for `player` action subcommands: after the
  action, wait and print the resulting `player state`
- Global option `--rest-api-sleep-before-next-call` (float, default 1.0) controlling the pause before
  the resulting-state fetch

### Changed

- The `info` command is now available as `player state`; `info` is kept as a synonym

### Removed

- Fields `samplerate`, `bitdepth`, `channels`, and `service` from the short field sets
  (`info --fields short` and `queue list --fields short`)


## [0.0.6] - 2026-07-16

### Changed

- Split the single `--timeout` CLI option into `--rest-api-timeout` and `--mpd-timeout`
- Rename the `--quiet` CLI option to `--machine-readable` (with `-m` shorthand)
- Show the version via a `version` subcommand instead of a `--version` option; `--machine-readable
  version` prints only the bare version string (e.g., `0.0.6`)


## [0.0.5] - 2026-07-16

### Added

- Class VolumioHostConfiguration bundling host connection parameters (scheme, host, ports)

### Changed

- Client constructors now take a VolumioHostConfiguration object plus timeout, instead of individual connection parameters


## [0.0.4] - 2026-07-13

### Added

- File MANIFEST.in for better control of files in sdist tarballs


## [0.0.3] - 2026-07-13

### Added

- Sphinx-compatible copyright headers to all Python source files


## [0.0.2] - 2026-07-13

### Added

- File DEVELOPMENT.md with development and contributing docs

### Changed

- Default MPD port from 6599 (Volumio 3) to 6600 (Volumio 4)


## [0.0.1] - 2025-10-23

### Added

- Initial release
