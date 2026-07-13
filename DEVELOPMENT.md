# Development

## Setup Development Environment

```bash
# Create micromamba environment
micromamba create -n volumito_dev python=3.13

# Activate environment
micromamba activate volumito_dev

# Install in development mode
pip install -e .
```

## Running Tests

```bash
# Run all checks (tests, linter, and type checker)
make test
# OR equivalently
make test-all

# Run unit tests only
make test-unit

# Run tests with coverage
make coverage

# Run linter
make lint

# Run type checker
make check-type-hints
```

## Project Structure

TODO

```
volumito/
├── src/
│   └── volumito/
│       ├── __init__.py
│       ├── api_client.py    # Volumio API client
│       └── cli.py           # Click-based CLI
├── tests/
│   ├── test_api_client.py
│   └── test_cli.py
├── CHANGELOG.md
├── DEVELOPMENT.md
├── LICENSE
├── Makefile
├── pyproject.toml
└── README.md
```

## Contributing

Contributions are not currently being accepted,
as the Python API is not stable yet.
