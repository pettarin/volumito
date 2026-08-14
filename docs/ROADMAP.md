# Roadmap

Rough plan, broken down by milestone:

## v0.1.0

- Released
  - Sync REST API client essentially feature complete.
  - CLI tool `volumito` fully usable and essentially feature complete.
- To be improved
  - Code can use some cleanup.
  - Some logic currently implemented
    for the CLI tool can probably be moved in the client library
    (directly or as helper/misc functions).
  - (Semi) Automated generation (via `lucio`) of the CLI Usage documentation.
  - No CI/CD.
  - No automated generation of Sphinx documentation for the Python library.

## v0.2.0

- Library: add async REST API client

## v0.3.0

- Library: add WebSocket client

## v0.4.0

- CLI: allow choosing any of the implemented clients

## v1.0.0

- CLI: code review/cleanup
- Establish a CI/CD workflow for the `volumito` package
- Establish a CI/CD workflow for the Sphinx documentation
- Review info for contributors

## v2.0.0

- Add an interactive TUI for human users (in addition to the one-shot CLI)

