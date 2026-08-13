# Generating The CLI Usage Documentation

The CLI Usage documentation for `volumio`,
specifically the `*.md` files in
[the `docs/cli/` directory](https://github.com/pettarin/volumito/tree/main/docs/cli),
is generated from template files (`*.tmd`) by
[`lucio`](https://github.com/pettarin/lucio).

This requires a virtual environment
where both `volumito[dev]` and `lucio` are installed,
and a target Volumio host reachable at `volumio.local`.

The workflow is the following:

1. Modify the relevant `*.tmd` file(s).
2. Regenerate the `.md` file for each of the modified files, for example:
   ```bash
   lucio -O -v COMMANDS.tmd
   ```
3. Regenerate the `INDEX.md` file:
   ```bash
   lucio -O -v -R INDEX.tmd
   ```

Currently the generation of the documentation is _almost_ automated,
except for two aspects:

1. Certain portions of the output returned by executed `volumito` commands
   present in the `*.tmd` files are redacted,
   manually replaced by a literal `<REDACTED>` in the output `.md` file.
   These files are `DOWNLOAD.md`, `SETUP_VERIFY_INSTALLATION.md`,
   and `SYSTEM.md`, and `INDEX.md` by inclusion of those three files.

2. To show notification events, while `lucio ... NOTIFICATIONS.tmd` is running,
   the user needs to toggle between play and pause,
   so that the events are captured by the block
   running the `volumito notification listen` command.

Problem 1 can be easily solved by extending the `lucio` tool.
Problem 2 cannot be easily solved, but perhaps some examples of events
can be captured statically "once-and-forever",
instead of reproducing them for real each time
the documentation is regenerated.

Once Problem 1 is addressed by extending the `lucio` tool,
a suitable `Makefile` target `generate-cli-usage-docs` can be added.

