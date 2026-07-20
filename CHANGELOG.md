# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).


## [0.0.9] - 2026-07-20

### Added

- Fields `trackType`, `samplerate`, `bitdepth`, and `channels` to the `player state`
  default short field set (`player state --fields short`)
- Command `track info`: show the current track's metadata with the same
  `--fields`/`--format`/`--raw` (`-L`/`-F`/`-R`) options as `player state`, but a
  track-oriented default `short` field set (position, title, artist, album, duration,
  trackType, samplerate, bitdepth, channels)
- Short options for frequently used options: `-H` (`--host`), `-M` (`--mpd-port`),
  `-P` (`--rest-api-port`), `-p` (`--position`), `-F` (`--format`), `-L` (`--fields`),
  and `-R` (`--raw`)

### Changed

- In machine-readable mode, `track audio` and `track albumart` now print their URI as a
  quoted string (consistent with `version`) so it can be consumed by tools like `jq` and `yq`


## [0.0.8] - 2026-07-19

### Changed

- Sort the CLI options alphabetically in `--help` (global options and every subcommand)
- In machine-readable mode, `version` now prints the version as a quoted string (e.g. `"0.0.8"`)
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
  version` prints only the bare version string (e.g. `0.0.6`)


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
