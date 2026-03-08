# 🐶 PUG — The Stubborn API Scraper

PUG sniffs messy API docs, chews them into a structured “Bone Map” with an LLM, and barks out a **Go Cobra CLI** plus **CLAUDE.md**, **SKILL.md**, and **MCP** server config — one folder per API.

## Requirements

- **Python 3.10+**
- **Anthropic API key** (for `chew`; validated automatically when you run `pug init`)
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
3. **Sniff** — Point Pug at an API docs URL; he scrapes to Markdown (stored under `bones/<bone>/`).
4. **Chew** — Turn the sniff into a CLI plan (the Bone Map). Pug infers auth and base URL from the docs.
5. **Refine (optional)** — `pug refine` to chat and tweak the Bone Map; say **done** when ready.
6. **Bark** — Smell test (real GET); if auth is needed, Pug prompts. Then he generates the Go CLI, CLAUDE.md, SKILL.md, and MCP in `bones/<bone>/cli/`.
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

3. **Sniff** — Scrape a docs URL (saved under `bones/<bone>/`):
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

Output: `bones/<bone>/cli/` with `bin/<name>`, `CLAUDE.md`, `SKILL.md`, `mcp.json`, `mcp-server.cjs`. To work on another API: `pug bone stripe-cli` (or any name), then sniff/chew/bark again.

## Commands

| Command | Description |
|--------|-------------|
| `pug init` | Set Anthropic API key (stored in `.env`); may prompt for first bone name |
| `pug bone [name] [--exit]` | Create or switch to a bone (project); omit name to list. Sniff/chew/refine/bark use the **active bone**. `--exit` clears it. |
| `pug sniff [url] [--resniff] [--save-as name]` | Scrape URL → Markdown (uses active bone); `--resniff` re-fetches last URL |
| `pug chew [file\|-] [--merge]` | LLM builds Bone Map (uses active bone) |
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

**Multiple APIs:** Create another bone with `pug bone stripe-cli`, then sniff/chew/bark. Switch back with `pug bone api-search-brave-com-cli`. Each bone has its own `bones/<name>/` (bone_map, last_sniff, etc.) and `bones/<name>/cli/` (generated output).

## Using the outputs in Claude, ChatGPT, or other AI tools

The generated CLI lives in `bones/<bone>/cli/` (e.g. `bones/brave-search/cli/`) — no download unless you need it elsewhere.

| Output | Use in Claude | Use in ChatGPT / others |
|--------|----------------|--------------------------|
| **CLAUDE.md** | Paste or attach in a chat so Claude knows the API and commands. | Same: paste or attach when you want the AI to use the API. |
| **MCP** (`mcp.json` + `mcp-server.cjs`) | In **Claude desktop** (or any app that supports MCP): add the server from `mcp.json` to your MCP config and set the required env vars (e.g. `BRAVE_API_KEY`). Then Claude can call the API as a tool. | ChatGPT doesn’t support MCP; use the CLI manually or paste CLAUDE.md. |
| **SKILL.md** | For **Cursor**: add as an Agent Skill so the editor can use this API. | N/A (Cursor-specific). |
| **CLI binary** | Run in terminal, paste results into the chat. | Same. |

**Summary:** For **Claude** or **OpenClaw** (or any MCP client): merge the `mcpServers` from the project’s `mcp.json` into your app’s MCP config, fix the server path if you moved the folder, and set the API key in the server’s `env`. For **ChatGPT** or tools without MCP: use **CLAUDE.md** as context and run the CLI yourself when needed.

## Editing after bark

`pug refine` (say `done`) → `pug bark` to regenerate. To add from another doc: `pug sniff <url> --save-as image` → `pug chew bones/<bone>/sniff_image.md --merge` → `pug bark`.

## Config

- **API key:** `pug init` creates `.env` with `ANTHROPIC_API_KEY`. See `.env.example` for the template.
- **Runtime:** The active bone is stored in `bones/current`. Each bone's data lives in `bones/<name>/` (bone_map.json, last_sniff.md, bark_config.json; gitignored). Generated output is in `bones/<name>/cli/`. For APIs that need auth, bark will prompt for auth type and env var name (e.g. `API_KEY`).

## Security

Do not commit `.env`. Use `.env.example` as a template and keep keys local. On GitHub, enable [push protection for secrets](https://docs.github.com/en/code-security/secret-scanning/protecting-pushes-with-secret-scanning) and consider [Dependabot](https://docs.github.com/en/code-security/dependabot) for dependency updates.

## Project layout

```
pug/
├── main.py          # CLI entry (init, bone, sniff, chew, refine, bark, run)
├── core/
│   ├── sniffer.py   # Playwright scrape → Markdown
│   ├── architect.py # LLM “chew” → Bone Map JSON
│   ├── barker.py    # Smell test + Go/Cobra + CLAUDE/SKILL/MCP
│   └── (API key validated in init via architect)
├── templates/       # Go and doc templates
├── bones/           # Runtime (gitignored): one dir per bone
│   ├── current      # Active bone name
│   ├── brave-search/
│   │   ├── bone_map.json
│   │   ├── bark_config.json
│   │   ├── last_sniff.md
│   │   ├── last_sniff_full_url
│   │   └── cli/     # Generated: bin/, CLAUDE.md, SKILL.md, mcp.json, mcp-server.cjs
│   └── stripe/
│       └── ...
├── requirements.txt
└── setup.py
```

## License

MIT. See [LICENSE](LICENSE).
