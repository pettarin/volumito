# How To Generate The CLI Usage Documentation

The CLI Usage documentation for `volumio`,
specifically the `*.md` files in
[the `docs/cli/` directory](https://github.com/pettarin/volumito/tree/main/docs/cli),
is generated from template files (`*.tmd`) by
[`lucio`](https://github.com/pettarin/lucio).

## Requirements

To (re)generate these documents, we need:

1. a virtual environment (named, say, `volumito_docs`)
   where `volumito[dev]` (and hence `lucio`) is `pip`-installed;
2. the `~/.volumito.yaml` file with aliases enabled
   being present on the machine running `lucio`;
3. a target Volumio host reachable at `volumio.local`.

Note that the examples below assume to run `lucio`
from the current working directory,
so that the replacement rules file `lucio.rules.yaml`
is read implicitly and `make` targets are available.

## Workflow

1. Modify the relevant `*.tmd` template file(s).
2. Build all modified `*.tmd` file(s) and `INDEX.tmd`:
   ```bash
   make build-all
   ```

To force a rebuild of all documents:
```bash
make rebuild-all
```
