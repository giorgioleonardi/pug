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

1. **Init** — Add your LLM (Anthropic) API key. If `.env` already has a key, Pug skips the prompt.
2. **Validate** — `pug pant` checks the key works (treat or trick?).
3. **Sniff** — You point Pug at an API docs URL; he scrapes and cleans it to Markdown (`.pug/last_sniff.md`).
4. **Review** — You review the cleaned file, then run **chew** to turn it into a CLI plan (the Bone Map). Pug infers **auth requirements from the docs** (Bearer token, API key in a header like X-Subscription-Token, or Basic auth) and the API base URL, and saves them for bark. He prefers read-only (GET) commands and notes limits/pagination where relevant.
5. **Insights** — After chew, Pug shows the Bone Map table plus a short summary (command count, base URL, auth from docs when detected). You decide if you’re ready to generate or want to tweak.
6. **Refine (optional)** — Run `pug refine` to chat with Pug in the terminal. Ask to add/remove/rename commands, change flags, etc. He updates the Bone Map; when you say **done** or **ready**, you’re set for bark.
7. **Bark** — Pug runs a **smell test** (real read-only GET). If the API needs auth and it wasn’t set from chew, he’ll prompt (paste key to .env, or set env var). Then he generates the Go CLI, CLAUDE.md, SKILL.md, and MCP artifacts in one folder per API.

## Quick start

1. **Init** — Save your Anthropic API key (writes `.env`; skips if already set):
   ```bash
   pug init
   ```

2. **Pant** — Verify the key (optional but recommended):
   ```bash
   pug pant
   ```

3. **Sniff** — Scrape a docs URL to Markdown (saved to `.pug/last_sniff.md`):
   ```bash
   pug sniff https://jsonplaceholder.typicode.com
   ```

4. **Chew** — AI suggests CLI commands and flags from the sniff (saves `.pug/bone_map.json`); shows insights and base URL:
   ```bash
   pug chew
   ```

5. **Refine** (optional) — Chat with Pug to tweak the Bone Map; say `done` when ready:
   ```bash
   pug refine
   ```

6. **Bark** — Smell test (read-only GET; prompts for auth if needed), then generate Go CLI + docs + MCP:
   ```bash
   pug bark                    # folder name from API base URL
   pug bark my-api-cli         # or pass a name
   ```

Output: `bin/<name>`, `CLAUDE.md`, `SKILL.md`, `mcp.json`, `mcp-server.cjs` in a directory named from the API or the name you gave.

## Commands

| Command | Description |
|--------|-------------|
| `pug init` | Set Anthropic API key (stored in `.env`); skips if already set |
| `pug sniff [url] [--resniff] [--save-as name] [--project name]` | Scrape URL → Markdown; `--resniff` re-fetches the last URL (no url needed); use `--project` for per-API dirs |
| `pug chew [file\|-] [--merge] [--project name]` | LLM builds Bone Map; use `--project` to match sniff (same `<name>` as bark) |
| `pug pant` | Validate API key (treat or trick?) |
| `pug refine [--project name]` | Chat to edit Bone Map; use `--project` when you have multiple APIs |
| `pug bark [name]` | Smell test → generate CLI; uses `.pug/<name>/bone_map.json` if present, else legacy `.pug/bone_map.json` |
| `pug run <project> [args...]` | Run a generated CLI with `.env` and config (base URL, auth) already set — no manual env vars |

## Testing the generated CLI

From the **pug repo root**, run the generated CLI with everything configured for you:

```bash
pug run api-search-brave-com-cli web-search --q "hello"
pug run api-search-brave-com-cli --help
```

`pug run` loads your `.env` (e.g. `BRAVE_API_KEY`) and the project’s base URL and auth type, so you don’t set any env vars by hand. (Projects generated before this feature need a fresh `pug bark` to get the run config.)

## Multiple APIs (per-project bone maps)

To work on **several APIs** (e.g. Brave and Stripe) without sharing one bone map, use **`--project <name>`** on sniff, chew, and refine. Each API gets its own dir: `.pug/<name>/` (e.g. `.pug/api-search-brave-com-cli/`, `.pug/stripe-cli/`). Use the same `<name>` for sniff, chew, refine, and bark. Bark uses `.pug/<name>/bone_map.json` when it exists.

## Editing after bark

Everything runs from the **pug repo**. Use `pug refine` or `pug refine --project <name>`; the Bone Map drives your generated CLI. After editing, `pug bark` or `pug bark <name>` regenerates the same project folder.

**Add another Brave search method (e.g. image search):** (1) **Chat:** Run `pug refine`, say e.g. *"add command image-search, GET /res/v1/images/search, flags --q --count"*, say `done`, then `pug bark`. (2) **From docs:** `pug sniff "https://api.search.brave.com/app/documentation/images-search-api" --save-as image` then `pug chew .pug/sniff_image.md --merge` then `pug bark`.

**Change or trim commands:** Run `pug refine`, edit in chat (e.g. "only keep web-search"), say `done`, then `pug bark`.

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
