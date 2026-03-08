# 🐶 PUG_MANIFEST (Rapid API Tooling)
**Concept:** A stubborn AI assistant that sniffs messy docs and huffs out clean Go binaries.

## 🕹️ The Pug-Flow
0. **INIT:** `pug init` — Save your Anthropic API key to `.env`; key is validated automatically (treat or trick?).
1. **BONE:** `pug bone [name]` — Create or switch active project; sniff/chew/refine/bark use it.
2. **SNIFF:** `pug sniff [URL]` — Playwright scrapes the URL, saves Markdown under `.pug/<bone>/`.
3. **CHEW:** `pug chew` — AI reads the sniff, suggests CLI commands + flags (Bone Map), saves `.pug/<bone>/bone_map.json`.
4. **BARK:** `pug bark` — Smell test (real API call) → generates Go/Cobra project, CLAUDE.md, SKILL.md, mcp.json + MCP server. Refine if needed.
5. **RUN:** `pug run [project] [args...]` — Run the generated CLI with .env + config loaded.
6. **HUFF:** (Future) Ship or install the binary (e.g. to system `/bin`).

## 🎭 Pug Personality Rules
- Use 🐶, 🦴, and 🐾 emojis.
- When waiting for an LLM: `[italic]Pug is thinking... (Heavy breathing noises)[/]`
- When an error occurs: `[red]Bark! Something's stuck in my throat (Error 404).[/]`
- Success message: `[green]Huff! I did it. Where's my treat?[/]`