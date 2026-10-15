# 🐶 PUG — The Stubborn API Scraper

[![CI](https://github.com/giorgioleonardi/pug/actions/workflows/ci.yml/badge.svg)](https://github.com/giorgioleonardi/pug/actions/workflows/ci.yml)

Scrapes one docs URL, asks Claude for a command map, and generates a thin local Go Cobra CLI wrapper plus agent notes. Local only; not MCP.

## Requirements

- **Python 3.10+**
- **Go** to build the generated CLI ([install Go](https://go.dev/dl/)). Without Go, `pug bark` still writes the Go source and docs but exits with an error because there's no binary.
- **Chromium for Playwright** (used by `pug sniff`). This is a separate step; see Install.
- **Anthropic API key** for `pug chew` and `pug refine`. Set `ANTHROPIC_API_KEY` in your environment, or save it with `pug init` (validated first, then written to `./.env`). The environment variable wins over `.env`.
- **Model** (optional): Pug uses `claude-sonnet-5-5` by default. Set `PUG_MODEL` (env var or `.env`) to use a different Claude model id.

## Install

Pug is **not on PyPI yet**. Install it from GitHub:

```bash
pipx install git+https://github.com/giorgioleonardi/pug
"$(pipx environment --value PIPX_LOCAL_VENVS)/pug-cli/bin/playwright" install chromium
```

Or with pip (in a virtual environment):

```bash
pip install git+https://github.com/giorgioleonardi/pug
playwright install chromium
```

Only Chromium is needed; you don't need all of Playwright's browsers. The Python package is called `pug-cli`, and the command is `pug`.

For contributors:

```bash
git clone https://github.com/giorgioleonardi/pug.git
cd pug
python3 -m venv venv && source venv/bin/activate
pip install -e . -r requirements-dev.txt
playwright install chromium
```

## Quick start (JSONPlaceholder, no API key needed for the API itself)

Run these in an empty working directory. Pug keeps everything under `./bones/`.

**1. Anthropic key.** `chew` needs one. Either export it:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

or let Pug validate and save it to `./.env`:

```bash
pug init
```

**2. Create a bone** (one per API):

```console
$ pug bone jp
Active bone: jp. Sniff, chew, refine, bark now use this project. 🦴
```

**3. Sniff the docs:**

```console
$ pug sniff https://jsonplaceholder.typicode.com/guide/
╭─  sniff 🐾  ─────────────────────────────────────────────────────────────────╮
│ Saved to bones/jp/last_sniff.md (6,447 chars, 216 lines)                     │
│ Title: Fake data you can rely on.                                            │
│ ...                                                                          │
│ … 139 more lines. Use pug sniff --verbose to print everything.               │
╰──────────────────────────────────────────────────────────────────────────────╯
Huff! I did it. Where's my treat?
Next: pug chew then pug bark. 🦴
```

**4. Chew:** Claude reads `bones/jp/last_sniff.md` and writes the Bone Map:

```bash
pug chew
```

This writes `bones/jp/bone_map.json` (commands, methods, paths, flags, and the API's original parameter names) and `bones/jp/bark_config.json` (base URL and auth, when the docs state them), then prints the Bone Map as a table. The model's output varies; review the table, or run `pug refine` to change it. See [`tests/fixtures/jsonplaceholder_bone_map.json`](tests/fixtures/jsonplaceholder_bone_map.json) for what a Bone Map looks like.

**5. Bark:** a smell test (one real GET), then generate and build the CLI:

```console
$ pug bark
Smell test: GET https://jsonplaceholder.typicode.com/posts → OK 🦴
Generated /tmp/pug-pr5-qs/bones/jp/cli/: Go source, CLAUDE.md, SKILL.md
Huff! I did it. Where's my treat?
Try it: pug run list-posts (loads .env + base URL + auth for you). All commands: pug run jp --help.
To add or change commands later: pug refine then pug bark. 🦴
$ ls bones/jp/cli
CLAUDE.md  SKILL.md  bin  cmd  go.mod  go.sum  main.go
```

**6. Run it.** The response body goes to stdout and the status line to stderr:

```console
$ pug run list-posts --user-id 1 | jq length
200 OK
10
$ pug run get-post --id 1
200 OK
{
  "userId": 1,
  "id": 1,
  "title": "sunt aut facere repellat provident occaecati excepturi optio reprehenderit",
  "body": "quia et suscipit\nsuscipit recusandae consequuntur expedita et cum\nreprehenderit molestiae ut ut quas totam\nnostrum rerum est autem sunt rem eveniet architecto"
}
$ pug run get-post --id 99999; echo $?
404 Not Found
{}
1
```

(Pug's banner, also on stderr, is trimmed from these examples.) The same flow works for APIs that need a key; `pug bark` asks for the auth env var if the smell test gets a 401/403.

## The generated CLI

The binary lives at `bones/<bone>/cli/bin/<bone>`. Run it through `pug run` (which loads `.env` and the bone's config), or call it directly.

- **stdout** is only the response body, pretty-printed JSON, so `| jq` works. The **status line** (`200 OK`) and error bodies go to **stderr**.
- **Exit codes:** `0` on success; `1` on HTTP 4xx/5xx, network errors, invalid `--data`, or a missing required flag.
- **Flags:** path params are required flags (e.g. `--id`). Query and body flags map back to the API's original names (e.g. `--user-id` → `userId`, `--limit` → `_limit`).
- **Bodies:** POST/PUT/PATCH send JSON. Use per-field flags, or `--data '{"title":"x"}'` (also `--data @file.json`, or `@-` for stdin); field flags override `--data`.
- **Base URL:** built in from the Bone Map. Override it with `<BONE>_BASE_URL` (e.g. `JP_BASE_URL`) or `--base-url`.
- **Auth:** one env var, the Bone Map's `api_key_env` (shown in `--help` and in `CLAUDE.md`), used for bearer, API-key header, or basic auth.

`CLAUDE.md` and `SKILL.md` in the same folder describe every command and this contract, so you can give them to an agent.

## Commands

| Command | Description |
|--------|-------------|
| `pug init [--force]` | Validate your Anthropic key, then save it to `.env`. `--force` replaces a saved key; you can also pipe a key in (`echo $KEY \| pug init --force`). |
| `pug bone [name] [--exit]` | Create or switch to a bone; omit the name to list bones. Names are lowercase letters, digits, `-` and `_`. |
| `pug sniff <url> [--resniff] [--save-as name] [--verbose]` | Scrape a docs URL to Markdown under the active bone. |
| `pug chew [file\|-] [--merge]` | Claude turns the Markdown into a Bone Map. |
| `pug refine` | Chat with Claude to edit the Bone Map. |
| `pug bark` | Smell test, then generate and build the CLI and agent docs. |
| `pug run [project] [args...]` | Run a generated CLI (active bone by default); the args go to the CLI. |

`pug --version` prints the version. Add `--debug` (or set `PUG_DEBUG=1`) to see full tracebacks. Every failure exits non-zero.

## Editing after bark

`pug refine` (say `done`) → `pug bark` to regenerate. To add commands from another doc page: `pug sniff <url> --save-as more` → `pug chew bones/<bone>/sniff_more.md --merge` → `pug bark`.

## Config

- **API key:** `ANTHROPIC_API_KEY` in your environment, or in `./.env` (written by `pug init`; see `.env.example`).
- **Model:** `PUG_MODEL` in your environment or `.env` (default `claude-sonnet-5-5`).
- **Runtime:** the active bone is stored in `bones/current`. Each bone's data lives in `bones/<name>/` (bone_map.json, last_sniff.md, bark_config.json), and the generated output in `bones/<name>/cli/`. `bones/` is gitignored.

MCP server output is not supported.

## Security

Do not commit `.env`. Use `.env.example` as a template and keep keys local.

## Project layout

```
pug/
├── main.py              # CLI entry point (init, bone, sniff, chew, refine, bark, run)
├── core/
│   ├── sniffer.py       # Playwright scrape → Markdown
│   ├── architect.py     # Claude "chew"/"refine" → Bone Map JSON; key validation
│   ├── barker.py        # Smell test, Go/Cobra generation, CLAUDE.md/SKILL.md
│   ├── errors.py        # One-line error messages
│   └── version.py       # Version (used by setup.py and pug --version)
├── tests/               # pytest (offline by default; see CONTRIBUTING.md)
├── .github/workflows/   # CI
├── requirements.txt
├── requirements-dev.txt
└── setup.py             # Package "pug-cli", command "pug"
```

Runtime output (gitignored), per bone: `bones/<name>/{bone_map.json, bark_config.json, last_sniff.md, cli/}`.

## License

MIT. See [LICENSE](LICENSE).
