# Development

**IMPORTANT**: the examples in the documentation use `micromamba`
               to manage virtual environments; feel free to replace it
               with your favorite tool (`conda`, `uv`, etc.).

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

You should be able to run:

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

# Run unit tests with coverage (HTML report in htmlcov/)
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
│   ├── CHANGELOG.md                        # releases and their changes
│   ├── CLI_USAGE.md                        # volumito CLI tool documentation
│   ├── DEVELOPMENT.md                      # this file
│   ├── LIBRARY_USAGE.md                    # Python library documentation
│   └── TODO.md                             # planned work, broken down by future milestone
├── res/
│   └── copyright_header.txt                # header prepended to every source file
├── src/
│   └── volumito/
│       ├── __init__.py                     # public API re-exports and version
│       ├── cli/
│       │   ├── click_helpers.py            # Click-dependent helpers and shared options
│       │   ├── configuration.py            # YAML configuration file loading
│       │   ├── constants.py                # module constants for the CLI
│       │   ├── metadata.py                 # audio metadata and cover-art embedding (mutagen)
│       │   ├── pure_helpers.py             # Click-independent formatting/parsing helpers
│       │   ├── res/
│       │   │   └── volumito.yaml.template  # configuration file template
│       │   └── volumito.py                 # Click-based CLI
│       └── clients/
│           ├── errors.py                   # VolumioError and its subclasses
│           ├── host_configuration.py       # VolumioHostConfiguration helper data class
│           ├── mpd/client.py               # MPD client (track URI)
│           └── rest/client.py              # REST API client
├── tests/                                  # unit tests
│   ├── test_cli.py
│   ├── test_configuration.py
│   ├── test_host_configuration.py
│   ├── test_metadata.py
│   ├── test_mpd_client.py
│   └── test_rest_client.py
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
- Other contributors should open pull requests (see `Contributing` below)
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

**Code contributions are not currently being accepted,
as the Python API is not stable yet (version < 1.0.0).**
(This message will be removed as soon as version 1.0.0 is published.)

### GitHub Issues

Bug reports, requests for new features, and comments
are handled by creating a new issue in
[GitHub Issues](https://github.com/pettarin/volumito/issues).

- Search the existing issues (both open and closed!)
  before submitting a new issue, to check if your issue has already been
  reported, fixed, or discussed.
- If not, feel free to open a new one.
- If you want to introduce a new feature, please file a GitHub issue first,
  so that the maintainer can discuss
  its purpose/design/implementation with you.
- When reporting a defect, please state the Volumio and `volumito` versions
  you are using, and the steps to reproduce your problem
  (e.g., a code snippet or a sequence of commands, etc.).


### Code Contributions

Before submitting a PR, please make sure:

- You read carefully this page.
- You are legally able to and comfortable with applying the current
  [license](../LICENSE)
  to your code contribution.
- If you used an automated tool (e.g., a LLM/AI tool) to generate it,
  you reviewed and understand the implementation,
  and you took care of removing any unnecessary code (a.k.a., "AI slop").
- You run all the tests with the `make test-all` command as explained above,
  and they all pass.
- Your PR is from a fix branch or feature branch (ideally branched off
  a recent state of the `devel` branch), and its target is the `devel` branch.

