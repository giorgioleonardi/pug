# 🐶 PUG — The Stubborn API Scraper

PUG sniffs messy API docs, chews them into a structured “Bone Map” with an LLM, and barks out a **Go Cobra CLI** plus **CLAUDE.md**, **SKILL.md**, and **MCP** server config — one folder per API.

## Requirements

- **Python 3.10+**
- **Anthropic API key** (for `chew` and `pant`)
- **Playwright** (browser for scraping): installed automatically by `pip install -e .`; on headless systems run `playwright install` if needed
- **Go** (for the generated CLI): when you run `pug bark`, Pug builds the CLI binary automatically **if Go is installed** ([install Go](https://go.dev/dl/)). Without Go, you still get the Go source, CLAUDE.md, SKILL.md, and MCP; install Go and run `go build -o bin/<name> .` in the generated folder to create the binary.

## Install

Use a virtual environment so dependencies stay isolated (recommended):

```bash
git clone git@github.com:giorgioleonardi/pug.git
cd pug
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -e .
```

The install step automatically runs `playwright install` so browser binaries are ready. If you're in a headless environment or it fails, run `playwright install` yourself.

## Full flow (what PUG covers)

1. **Init** — Add your LLM (Anthropic) API key. Pug may prompt for a **bone** (project) name so you have an active project.
2. **Validate** — `pug pant` checks the key works (treat or trick?).
3. **Sniff** — You point Pug at an API docs URL; he scrapes and cleans it to Markdown (`.pug/last_sniff.md`).
4. **Review** — You review the cleaned file, then run **chew** to turn it into a CLI plan (the Bone Map). Pug infers **auth requirements from the docs** (Bearer token, API key in a header like X-Subscription-Token, or Basic auth) and the API base URL, and saves them for bark. He prefers read-only (GET) commands and notes limits/pagination where relevant.
5. **Insights** — After chew, Pug shows the Bone Map table plus a short summary (command count, base URL, auth from docs when detected). You decide if you’re ready to generate or want to tweak.
6. **Refine (optional)** — Run `pug refine` to chat with Pug in the terminal. Ask to add/remove/rename commands, change flags, etc. He updates the Bone Map; when you say **done** or **ready**, you’re set for bark.
7. **Bark** — Pug runs a **smell test** (real read-only GET). If the API needs auth and it wasn’t set from chew, he’ll prompt (paste key to .env, or set env var). Then he generates the Go CLI, CLAUDE.md, SKILL.md, and MCP artifacts in one folder per API.

## Quick start

1. **Init** — Save your Anthropic API key; Pug may ask for a bone name (or create one later):
   ```bash
   pug init
   ```

2. **Bone** — Create or switch to a project (everything else uses this active bone):
   ```bash
   pug bone api-search-brave-com-cli
   ```

3. **Sniff** — Scrape a docs URL (saved under `.pug/<bone>/`):
   ```bash
   pug sniff "https://api.search.brave.com/app/documentation/web-search-api"
   ```

4. **Chew** — AI suggests CLI commands and flags from the sniff:
   ```bash
   pug chew
   ```

5. **Refine** (optional) — Chat to tweak the Bone Map; say `done` when ready:
   ```bash
   pug refine
   ```

6. **Bark** — Smell test, then generate Go CLI + docs + MCP:
   ```bash
   pug bark
   ```

7. **Run** — Use the CLI (active bone by default, or pass the project name):
   ```bash
   pug run web-search --q hello
   pug run api-search-brave-com-cli --help
   ```

Output: a folder named after your bone with `bin/<name>`, `CLAUDE.md`, `SKILL.md`, `mcp.json`, `mcp-server.cjs`. To work on another API: `pug bone stripe-cli` (or any name), then sniff/chew/bark again.

## Commands

| Command | Description |
|--------|-------------|
| `pug init` | Set Anthropic API key (stored in `.env`); may prompt for first bone name |
| `pug bone [name] [--exit]` | Create or switch to a bone (project); omit name to list. Sniff/chew/refine/bark use the **active bone**. `--exit` clears it. |
| `pug sniff [url] [--resniff] [--save-as name]` | Scrape URL → Markdown (uses active bone); `--resniff` re-fetches last URL |
| `pug chew [file\|-] [--merge]` | LLM builds Bone Map (uses active bone) |
| `pug pant` | Validate API key (treat or trick?) |
| `pug refine` | Chat to edit Bone Map (uses active bone) |
| `pug bark` | Smell test → generate CLI (uses active bone; folder = bone name) |
| `pug run [project] [args...]` | Run a generated CLI; omit project to use active bone. Args passed to the CLI (e.g. `pug run web-search --q hello`) |

## Testing the generated CLI

From the **pug repo root**, run the generated CLI with everything configured for you:

```bash
pug run api-search-brave-com-cli web-search --q "hello"
pug run api-search-brave-com-cli --help
```

`pug run` loads your `.env` (e.g. `BRAVE_API_KEY`) and the project’s base URL and auth type, so you don’t set any env vars by hand. (Projects generated before this feature need a fresh `pug bark` to get the run config.)

Every API has its own **project name**. Use the same name for sniff, chew, refine, and bark; everything is stored under `.pug/<project>/` (e.g. `.pug/api-search-brave-com-cli/`, `.pug/stripe-cli/`). Example flow for one API: `pug sniff api-search-brave-com-cli "https://api.search.brave.com/.../web-search-api"` → `pug chew api-search-brave-com-cli` → `pug bark api-search-brave-com-cli`. For another API: pick a different project name (e.g. `stripe-cli`) and repeat.

## Editing after bark

`pug refine` (say `done`) → `pug bark` to regenerate. To add from another doc: `pug sniff <url> --save-as image` → `pug chew .pug/<bone>/sniff_image.md --merge` → `pug bark`.

## Config

- **API key:** `pug init` creates `.env` with `ANTHROPIC_API_KEY`. See `.env.example` for the template.
- **Runtime:** Sniff and Bone Map live under `.pug/` (gitignored). For APIs that need auth, bark will prompt for auth type and env var name (e.g. `API_KEY`); set that env var before re-running the smell test.

## Project layout

```
pug/
├── main.py          # CLI entry (init, sniff, chew, pant, refine, bark)
├── core/
│   ├── sniffer.py   # Playwright scrape → Markdown
│   ├── architect.py # LLM “chew” → Bone Map JSON
│   ├── barker.py    # Smell test + Go/Cobra + CLAUDE/SKILL/MCP
│   └── pant.py      # API key validation
├── templates/       # Go and doc templates
├── requirements.txt
└── setup.py
```

## License

MIT (or your choice).
