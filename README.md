# 🐶 PUG — The Stubborn API Scraper

PUG sniffs messy API docs, chews them into a structured “Bone Map” with an LLM, and barks out a **Go Cobra CLI** plus **CLAUDE.md**, **SKILL.md**, and **MCP** server config — one folder per API.

## Requirements

- **Python 3.10+**
- **Anthropic API key** (for `chew` and `pant`)
- **Playwright** (browser for scraping): installed automatically by `pip install -e .`; on headless systems run `playwright install` if needed

## Install

```bash
git clone git@github.com:giorgioleonardi/pug.git
cd pug
pip install -e .
```

The install step automatically runs `playwright install` so browser binaries are ready. If you're in a headless environment or it fails, run `playwright install` yourself.

## Full flow (what PUG covers)

1. **Init** — Add your LLM (Anthropic) API key. If `.env` already has a key, Pug skips the prompt.
2. **Validate** — `pug pant` checks the key works (treat or trick?).
3. **Sniff** — You point Pug at an API docs URL; he scrapes and cleans it to Markdown (`.pug/last_sniff.md`).
4. **Review** — You review the cleaned file, then run **chew** to turn it into a CLI plan (the Bone Map). Pug prefers read-only (GET) commands and notes limits/pagination where relevant.
5. **Insights** — After chew, Pug shows the Bone Map table plus a short summary (command count, base URL). You decide if you’re ready to generate or want to tweak.
6. **Refine (optional)** — Run `pug refine` to chat with Pug in the terminal. Ask to add/remove/rename commands, change flags, etc. He updates the Bone Map; when you say **done** or **ready**, you’re set for bark.
7. **Bark** — Pug runs a **smell test** (real read-only GET). If the API needs auth, he’ll prompt for auth type (bearer / api_key_header) and env var name, save config, and retry. Then he generates the Go CLI, CLAUDE.md, SKILL.md, and MCP artifacts in one folder per API.

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
| `pug sniff <url>` | Scrape URL → clean Markdown → `.pug/last_sniff.md` |
| `pug chew [file\|-]` | LLM builds Bone Map from Markdown (default: last sniff); read-only–aware, notes limits |
| `pug pant` | Validate API key (treat or trick?) |
| `pug refine` | Chat with Pug to improve the Bone Map; say `done` when ready for bark |
| `pug bark [name]` | Smell test (prompts for auth if needed) → generate Go CLI + CLAUDE.md + SKILL.md + MCP |

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
