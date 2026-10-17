# Hermes plugin: squeez-fallback

`squeez setup --host=hermes` installs this plugin to
`$HERMES_HOME/plugins/squeez-fallback/` (`~/.hermes/plugins/` when
`HERMES_HOME` is unset). Enable it once with
`hermes plugins enable squeez-fallback`, then restart Hermes or its gateway.

## What it does

The plugin uses the Hermes `transform_terminal_output` hook. After a terminal
command finishes, its output goes through `squeez filter <command>` before the
model reads it.

- The command is not rewritten, so the shell, the working directory and the
  exit code are the same as without the plugin.
- It works on any command shape, including pipes, chains, redirects and
  `$(...)`.

Earlier versions used `pre_tool_call` to rewrite a command to
`squeez wrap <cmd>`. That rewrite had to skip every command with a pipe,
`&&`, `||`, `;`, a redirect, `$(...)` or a newline, because `squeez wrap`
takes one simple command. Agents chain commands, so it skipped most of them.
On one Hermes install, 33 of 4,044 recent terminal calls were simple enough
to wrap, and those calls held about 0% of the output. On the same calls, the
output hook compressed 163 of the 303 outputs that were 4,000 characters or
longer. Those outputs went from 3,297,676 to 1,827,821 characters (45% less),
which is 25% less of all terminal output.

## Nothing is lost

`squeez filter` drops lines. So the plugin saves the full output to
`$HERMES_HOME/cache/squeez-raw/<hash>.txt` (mode 0600, removed after 24 h)
and ends the compressed text with that path. The model can read the file if
something it needs is missing.

The hook runs before Hermes redacts secrets. The plugin passes the saved
copy through the same redactor Hermes uses for its own spill files
(`agent.redact.redact_terminal_output`). If that redactor cannot be
imported, the plugin keeps the raw output and saves nothing.

The plugin leaves the output unchanged when:

- the output is shorter than `SQUEEZ_OUTPUT_MIN_CHARS` (default 4000)
- squeez saves less than 20%
- the squeez binary is missing, fails, or takes more than 10 s
- `SQUEEZ_OUTPUT_DISABLE=1` is set

The plugin looks for the squeez binary at `$SQUEEZ_BIN`, then on `PATH`,
then at `$HERMES_HOME/squeez/bin/squeez`, then at
`~/.claude/squeez/bin/squeez` (where `install.sh` puts it). It looks on
every call, so when it finds none the output is left as is, and a binary
installed later works without a restart.

## Test

`tests/e2e_hermes.py` runs commands through the real Hermes terminal tool,
first without the plugin and then with it. Run it from a hermes-agent
checkout with its venv:

```bash
cd path/to/hermes-agent
.venv/bin/python path/to/squeez/plugins/hermes/tests/e2e_hermes.py
```

It checks that:

- without the plugin, the output is raw
- with the plugin, the output is smaller and has the footer
- the saved file has the full output and mode 0600
- short output is unchanged
- `SQUEEZ_OUTPUT_DISABLE=1` leaves output unchanged
- a planted token is redacted in the saved file and in what the model sees

To confirm that the redaction check can fail, replace
`agent.redact.redact_terminal_output` with a function that returns its
input unchanged. The two redaction checks then fail.
