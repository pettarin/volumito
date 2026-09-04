# Development

> [!NOTE]
> The examples in the documentation use `micromamba`
> to manage virtual environments; feel free to replace it
> with your favorite tool (`conda`, `uv`, etc.).

## Setup Development Environment

Clone this repository and install from source
in a virtual environment, with development extras:

```bash
$ git clone https://github.com/pettarin/volumito
$ cd volumito

$ micromamba create -n volumito_dev python=3.13
$ micromamba activate volumito_dev

(volumito_dev) $ pip install -e ".[dev]"
(volumito_dev) $ # or
(volumito_dev) $ make install-e-this-dev
```

> [!NOTE]
> The `dev` option installs all the extras
> of the regular PyPI package `volumito`,
> plus additional tools (e.g., `coverage`, `mypy`, `ruff`, etc.)
> needed for development activities.

You should be able to run the `volumito` CLI tool,
automatically installed in the virtual environment:

```bash
(volumito_dev) $ volumito version
volumito, version 0.1.0
```


## Running Tests

```bash
# Run all checks (unit tests, linter, and type checker)
(volumito_dev) $ make test-all
# OR equivalently
(volumito_dev) $ make test

# Run unit tests only
(volumito_dev) $ make test-unit

# Run unit tests with coverage (HTML report produced in the `htmlcov/` directory)
(volumito_dev) $ make coverage

# Run linter
(volumito_dev) $ make lint

# Run type checker
(volumito_dev) $ make check-type-hints
```


## Project Structure

```
volumito/
├── docs/
│   ├── cli/
│   │   └── INDEX.md                        # volumito CLI tool documentation
│   ├── CHANGELOG.md                        # releases and their changes
│   ├── CODE_OF_CONDUCT.md                  # ground rules of the project spaces
│   ├── CONTRIBUTING.md                     # how to report issues and contribute code
│   ├── DEVELOPMENT.md                      # this file
│   ├── LIBRARY_USAGE.md                    # Python library documentation
│   ├── ROADMAP.md                          # planned work, broken down by future milestone
│   └── SECURITY.md                         # supported versions and how to report a vulnerability
├── res/
│   └── copyright_header.txt                # header prepended to every source file
├── src/
│   └── volumito/
│       ├── __init__.py                     # public API re-exports and version
│       ├── cli/
│       │   ├── __init__.py                 # CLI entry point re-export
│       │   ├── api_client.py               # adapters giving the four API clients one surface
│       │   ├── click_helpers.py            # Click-dependent helpers and shared options
│       │   ├── configuration.py            # YAML configuration file loading
│       │   ├── console.py                  # timestamped, colored console logging on stderr
│       │   ├── constants.py                # module constants for the CLI
│       │   ├── metadata.py                 # audio metadata and cover-art embedding (mutagen)
│       │   ├── pure_helpers.py             # Click-independent formatting/parsing helpers
│       │   ├── res/
│       │   │   └── volumito.yaml.template  # configuration file template
│       │   └── volumito.py                 # Click-based CLI
│       └── clients/
│           ├── __init__.py                 # clients package re-exports
│           ├── base.py                     # base client holding the logger of the clients
│           ├── common.py                   # logic shared by every client of a host
│           ├── entities.py                 # music entity references for the story queries
│           ├── errors.py                   # VolumioError and its subclasses
│           ├── host_configuration.py       # VolumioHostConfiguration helper data class
│           ├── listener.py                 # receiver of the push notifications of a host
│           ├── models.py                   # pydantic models of the Volumio API responses
│           ├── mpd/
│           │   ├── __init__.py             # MPD client re-exports
│           │   └── client.py               # MPD client (track URI)
│           ├── remote.py                   # access to the files and to the shell of a host
│           ├── rest/
│           │   ├── __init__.py             # REST API client re-exports
│           │   ├── asyncclient.py          # async REST API client (aiohttp)
│           │   ├── client.py               # sync REST API client (requests)
│           │   └── common.py               # logic shared by the REST API clients
│           └── websocket/
│               ├── __init__.py             # WebSocket API client re-exports
│               ├── asyncclient.py          # async WebSocket API client (python-socketio)
│               ├── client.py               # sync WebSocket API client (python-socketio)
│               └── common.py               # logic shared by the WebSocket API clients
├── tests/                                  # unit tests
│   ├── __init__.py
│   ├── test_api_client.py
│   ├── test_base_client.py
│   ├── test_cli.py
│   ├── test_configuration.py
│   ├── test_console.py
│   ├── test_host_configuration.py
│   ├── test_listener.py
│   ├── test_metadata.py
│   ├── test_models.py
│   ├── test_mpd_client.py
│   ├── test_remote.py
│   ├── test_rest_asyncclient.py
│   ├── test_rest_client.py
│   ├── test_websocket_asyncclient.py
│   └── test_websocket_client.py
├── LICENSE                                 # full text of the license for this project
├── Makefile                                # make commands for the developer
├── MANIFEST.in                             # include/exclude additional files in the PyPI package
├── pyproject.toml                          # descriptor for building the PyPI package
└── README.md                               # main README file
```


## Branching And Versioning Policy

### Branch `main`

- Branch `main` is protected, and it represents the sources of the latest stable release.
- Only the maintainer is allowed to push there directly,
  usually merging the `devel` branch when preparing a new release.
- Published packages on PyPI are from commit tagged `vX.Y.Z`.

### Branch `devel`

- Branch `devel` is protected, and it accumulates fixes and features for the next release.
- The maintainer is allowed to push there directly,
  usually merging feature or fix branches.
- Other contributors should open pull requests
  (see the [CONTRIBUTING](CONTRIBUTING.md) document)
  against the `devel` branch, which will be reviewed and, if appropriate, merged.

### Other Branches

- Fix branches should be named `fix/gh_#123_short_description`
  where `#123` is the ID of the GitHub issue being fixed.
- Feature branches should be named `feature/gh_#456_short_description`
  where `#456` is the ID of the GitHub issue describing the requested feature.
- In both cases, it is mandatory to have a GitHub issue
  describing the issue being fixed or the new feature being added.
- No need to squash commits on a fix or feature branch,
  just try to have meaningful commit messages if you have more than one commit.
  Usually it is preferable referencing the GitHub issue
  (`Fixes #123 ...` or `Implement #456 ...`) in the commit message.

### Versioning

- This project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).
- Each released version is published on PyPI as package
[volumito](https://pypi.org/project/volumito/)
and the corresponding commit tagged with `vX.Y.Z`,
where `volumito==X.Y.Z` is the released version.


## Contributing

See the
[CONTRIBUTING](CONTRIBUTING.md)
document.

