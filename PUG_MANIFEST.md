# 🐶 PUG_MANIFEST (Rapid API Tooling)
**Concept:** A stubborn AI assistant that sniffs messy docs and huffs out clean Go binaries.

## 🕹️ The Pug-Flow
0. **INIT:** `pug init` — Save your Anthropic API key to `.env` (used by chew + pant).
1. **SNIFF:** `pug sniff [URL]` — Playwright scrapes the URL, strips nav/footer, saves Markdown to `.pug/last_sniff.md`.
2. **CHEW:** `pug chew` — AI reads the Markdown (or last sniff), suggests CLI commands + flags (The Bone Map), saves `.pug/bone_map.json`.
3. **PANT:** `pug pant` — Live auth check. "Is this key a treat or a trick?"
4. **BARK:** `pug bark` — System compiler: smell test (real API call) → then generates Go/Cobra project (`dog-cli/`, `bin/dog-cli`), CLAUDE.md, SKILL.md, mcp.json + MCP server for Cursor/Claude. Refine Chat if smell test fails.
5. **HUFF:** (Future) Ship or install the binary (e.g. to system `/bin`).

## 🎭 Pug Personality Rules
- Use 🐶, 🦴, and 🐾 emojis.
- When waiting for an LLM: `[italic]Pug is thinking... (Heavy breathing noises)[/]`
- When an error occurs: `[red]Bark! Something's stuck in my throat (Error 404).[/]`
- Success message: `[green]Huff! I did it. Where's my treat?[/]`