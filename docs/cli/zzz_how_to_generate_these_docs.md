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
2. Regenerate the `.md` file for each of the modified `*.tmd` template files
   using the provided `Makefile`:
   ```bash
   make build-only-setup-verify-installation
   lucio -r lucio.rules.yaml -O -v -R SETUP_VERIFY_INSTALLATION.tmd
   [2026-09-08T07:48:18.462Z] [DEBU] Input file: "/home/alberto/projects/volumito/volumito/docs/cli/SETUP_VERIFY_INSTALLATION.tmd"
   [2026-09-08T07:48:18.462Z] [DEBU] Output file: "/home/alberto/projects/volumito/volumito/docs/cli/SETUP_VERIFY_INSTALLATION.md"
   [2026-09-08T07:48:18.463Z] [DEBU] Check language: False
   [2026-09-08T07:48:18.463Z] [DEBU] Omit do-not-edit comment: False
   [2026-09-08T07:48:18.463Z] [DEBU] Overwrite files: True
   [2026-09-08T07:48:18.463Z] [DEBU] Pager: False
   [2026-09-08T07:48:18.463Z] [DEBU] Remove do-not-edit comment on include: True
   [2026-09-08T07:48:18.463Z] [DEBU] Rules file: "/home/alberto/projects/volumito/volumito/docs/cli/lucio.rules.yaml"
   [2026-09-08T07:48:18.463Z] [DEBU] Block timeout: 60.0 seconds
   [2026-09-08T07:48:18.463Z] [DEBU] Total timeout: 300.0 seconds
   [2026-09-08T07:48:18.467Z] [DEBU] Loaded 2 rule(s) from "lucio.rules.yaml"
   [2026-09-08T07:48:18.467Z] [INFO] Rendering "SETUP_VERIFY_INSTALLATION.tmd" into "SETUP_VERIFY_INSTALLATION.md"...
   [2026-09-08T07:48:18.468Z] [DEBU] SETUP_VERIFY_INSTALLATION.tmd:13: executing bash block
   [2026-09-08T07:48:19.015Z] [DEBU] SETUP_VERIFY_INSTALLATION.tmd:13: exit code 0
   [2026-09-08T07:48:19.015Z] [DEBU] SETUP_VERIFY_INSTALLATION.tmd:19: executing bash block
   [2026-09-08T07:48:19.587Z] [DEBU] SETUP_VERIFY_INSTALLATION.tmd:19: exit code 0
   [2026-09-08T07:48:19.587Z] [DEBU] SETUP_VERIFY_INSTALLATION.tmd:19: rule 'replace_hwUuid' rewrote 1 match on stdout
   [2026-09-08T07:48:19.587Z] [DEBU] SETUP_VERIFY_INSTALLATION.tmd:19: rule 'replace_id' rewrote 1 match on stdout
   [2026-09-08T07:48:19.588Z] [INFO] Rendering "SETUP_VERIFY_INSTALLATION.tmd" into "SETUP_VERIFY_INSTALLATION.md"... done
   ```
3. Regenerate the `INDEX.md` file:
   ```bash
   make build-only-index
   lucio -r lucio.rules.yaml -O -v -R INDEX.tmd
   [2026-09-08T07:49:41.270Z] [DEBU] Input file: "/home/alberto/projects/volumito/volumito/docs/cli/INDEX.tmd"
   [2026-09-08T07:49:41.270Z] [DEBU] Output file: "/home/alberto/projects/volumito/volumito/docs/cli/INDEX.md"
   [2026-09-08T07:49:41.271Z] [DEBU] Check language: False
   [2026-09-08T07:49:41.271Z] [DEBU] Omit do-not-edit comment: False
   [2026-09-08T07:49:41.271Z] [DEBU] Overwrite files: True
   [2026-09-08T07:49:41.271Z] [DEBU] Pager: False
   [2026-09-08T07:49:41.271Z] [DEBU] Remove do-not-edit comment on include: True
   [2026-09-08T07:49:41.271Z] [DEBU] Rules file: "/home/alberto/projects/volumito/volumito/docs/cli/lucio.rules.yaml"
   [2026-09-08T07:49:41.271Z] [DEBU] Block timeout: 60.0 seconds
   [2026-09-08T07:49:41.271Z] [DEBU] Total timeout: 300.0 seconds
   [2026-09-08T07:49:41.275Z] [DEBU] Loaded 2 rule(s) from "lucio.rules.yaml"
   [2026-09-08T07:49:41.275Z] [INFO] Rendering "INDEX.tmd" into "INDEX.md"...
   [2026-09-08T07:49:41.276Z] [DEBU] INDEX.tmd:92: including "SETUP_VERIFY_INSTALLATION.md"
   [2026-09-08T07:49:41.277Z] [DEBU] INDEX.tmd:96: including "SETUP_CONFIGURATION_FILE.md"
   [2026-09-08T07:49:41.277Z] [DEBU] INDEX.tmd:100: including "GET_HELP.md"
   [2026-09-08T07:49:41.277Z] [DEBU] INDEX.tmd:104: including "CONTROL_PLAYBACK.md"
   [2026-09-08T07:49:41.278Z] [DEBU] INDEX.tmd:108: including "INSPECT_CURRENT_TRACK.md"
   [2026-09-08T07:49:41.278Z] [DEBU] INDEX.tmd:112: including "INSPECT_CURRENT_QUEUE.md"
   [2026-09-08T07:49:41.278Z] [DEBU] INDEX.tmd:116: including "PLAYLISTS.md"
   [2026-09-08T07:49:41.279Z] [DEBU] INDEX.tmd:120: including "SEARCH_COLLECTION.md"
   [2026-09-08T07:49:41.279Z] [DEBU] INDEX.tmd:124: including "BROWSE_COLLECTION.md"
   [2026-09-08T07:49:41.280Z] [DEBU] INDEX.tmd:128: including "DOWNLOAD.md"
   [2026-09-08T07:49:41.280Z] [DEBU] INDEX.tmd:132: including "STORY.md"
   [2026-09-08T07:49:41.281Z] [DEBU] INDEX.tmd:138: including "COMMANDS.md"
   [2026-09-08T07:49:41.281Z] [DEBU] INDEX.tmd:141: including "CONFIGURATION_FILE.md"
   [2026-09-08T07:49:41.281Z] [DEBU] INDEX.tmd:144: including "MULTIROOM.md"
   [2026-09-08T07:49:41.281Z] [DEBU] INDEX.tmd:147: including "NOTIFICATIONS.md"
   [2026-09-08T07:49:41.282Z] [DEBU] INDEX.tmd:150: including "SCP.md"
   [2026-09-08T07:49:41.282Z] [DEBU] INDEX.tmd:153: including "SYSTEM.md"
   [2026-09-08T07:49:41.285Z] [INFO] Rendering "INDEX.tmd" into "INDEX.md"... done
   ```

Alternatively to steps 2+3, you can rebuild all the documents
with the `build-all` target:

```bash
make build-all
```
