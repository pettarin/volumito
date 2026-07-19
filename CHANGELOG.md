# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).


## [0.0.7] - 2026-07-19

### Added

- Fields `status`, `seek`, `volume`, and `mute` to the default short field set
  (`info --fields short`)
- Command `player volume` (accepting `mute`, `unmute`, `plus`, `minus`, or an integer 0-100),
  with `player mute` and `player unmute` synonyms, backed by the volume REST API

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
