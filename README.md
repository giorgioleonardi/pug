# 🐶 PUG — The Stubborn API Scraper

PUG sniffs messy API docs, chews them into a structured “Bone Map” with an LLM, and barks out a **Go Cobra CLI** plus **CLAUDE.md**, **SKILL.md**, and **MCP** server config — one folder per API.

## Requirements

- **Python 3.10+**
- **Anthropic API key** (for `chew` and `pant`)
- **Playwright** (browser for scraping): after installing deps, run `playwright install` once

## Install

```bash
git clone git@github.com:giorgioleonardi/pug.git
cd pug
pip install -e .
playwright install
```

## Quick start

1. **Init** — Save your Anthropic API key (writes `.env`):
   ```bash
   pug init
   ```

2. **Sniff** — Scrape a docs URL to Markdown (saved to `.pug/last_sniff.md`):
   ```bash
   pug sniff https://jsonplaceholder.typicode.com
   ```

3. **Chew** — AI suggests CLI commands and flags from the sniff (saves `.pug/bone_map.json`):
   ```bash
   pug chew
   ```

4. **Pant** — Check that your API key works:
   ```bash
   pug pant
   ```

5. **Bark** — Smell test (real GET), then generate Go CLI + docs + MCP in a new folder:
   ```bash
   pug bark                    # folder name from API base URL
   pug bark my-api-cli         # or pass a name
   ```

Output: `bin/<name>`, `CLAUDE.md`, `SKILL.md`, `mcp.json`, `mcp-server.cjs` in a directory named from the API or the name you gave.

## Commands

| Command | Description |
|--------|-------------|
| `pug init` | Set Anthropic API key (stored in `.env`) |
| `pug sniff <url>` | Scrape URL → clean Markdown → `.pug/last_sniff.md` |
| `pug chew [file\|-]` | LLM builds Bone Map from Markdown (default: last sniff) |
| `pug pant` | Validate API key (treat or trick?) |
| `pug bark [name]` | Smell test → generate Go CLI + CLAUDE.md + SKILL.md + MCP |

## Config

- **API key:** `pug init` creates `.env` with `ANTHROPIC_API_KEY`. See `.env.example` for the template.
- **Runtime:** Sniff and Bone Map live under `.pug/` (gitignored).

## Project layout

```
pug/
├── main.py          # CLI entry (init, sniff, chew, pant, bark)
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
