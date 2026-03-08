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
2. **Bone** — `pug bone <name>` creates or switches to a project. All sniff/chew/refine/bark use this **active bone**. Use `pug bone` to list; `pug bone --exit` to clear.
3. **Sniff** — Point Pug at an API docs URL; he scrapes to Markdown (stored under `.pug/<bone>/`).
4. **Chew** — Turn the sniff into a CLI plan (the Bone Map). Pug infers auth and base URL from the docs.
5. **Refine (optional)** — `pug refine` to chat and tweak the Bone Map; say **done** when ready.
6. **Bark** — Smell test (real GET); if auth is needed, Pug prompts. Then he generates the Go CLI, CLAUDE.md, SKILL.md, and MCP in a folder named after your bone.
7. **Run** — `pug run` (or `pug run <project>`) runs the generated CLI with .env and config loaded.

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
pug run web-search --q "hello"              # uses active bone; args go to the CLI
pug run api-search-brave-com-cli --help    # or pass the project name explicitly
```

`pug run` loads your `.env` and the project's base URL and auth, so you don't set env vars by hand.

**Multiple APIs:** Create another bone with `pug bone stripe-cli`, then sniff/chew/bark. Switch back with `pug bone api-search-brave-com-cli`. Each bone has its own `.pug/<name>/` and generated folder.

## Editing after bark

`pug refine` (say `done`) → `pug bark` to regenerate. To add from another doc: `pug sniff <url> --save-as image` → `pug chew .pug/<bone>/sniff_image.md --merge` → `pug bark`.

## Config

- **API key:** `pug init` creates `.env` with `ANTHROPIC_API_KEY`. See `.env.example` for the template.
- **Runtime:** The active bone is stored in `.pug/current`. Each bone's data lives in `.pug/<name>/` (gitignored). For APIs that need auth, bark will prompt for auth type and env var name (e.g. `API_KEY`).

## Project layout

```
pug/
├── main.py          # CLI entry (init, bone, sniff, chew, pant, refine, bark, run)
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
