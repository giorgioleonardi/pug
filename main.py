import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from core.architect import chew, chew_merge, plan_to_bone_map_rows, refine_turn, save_bone_map, validate_anthropic_key
from core.barker import bark as run_bark, save_bark_config
from core.sniffer import sniff

console = Console()

# Pug palette: warm tan, dark brown/black, gold accent
TAN = "tan"
GOLD = "gold1"
BROWN = "rgb(139,90,43)"
BORDER = "bold rgb(101,67,33)"
SUCCESS = "green"
ERROR = "red1"
DIM = "dim"

# ASCII pug (compact, fits narrow terminals)
PUG_ART = r"""
    /^ ^\
 / 0 0 \
 V\ Y /V
  / - \
 /    |
V__) ||
"""


def welcome(*, show_ascii_art: bool = False):
    """Print PUG banner. ASCII art only on init; other commands get dog emoji + title."""
    console.print()
    if show_ascii_art:
        art = Text(PUG_ART.strip(), style=TAN)
        title = Text("PUG v1.0", style=f"bold {GOLD}")
        subtitle = Text("The Stubborn API Scraper", style=DIM)
        block = Text("\n").join([art, title, subtitle])
        console.print(Panel(block, border_style=BORDER, padding=(0, 2)))
    else:
        console.print(Panel.fit(
            f"🐶 [bold {GOLD}]PUG v1.0[/] [dim]— The Stubborn API Scraper[/]",
            border_style=BORDER,
        ))
    console.print()


def _load_dotenv_into_env(env_path: Optional[Path] = None) -> None:
    """Load .env into os.environ so smell test and generated CLI can use vars (e.g. BRAVE_SEARCH_TOKEN)."""
    p = (env_path or Path.cwd()) / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val


def _env_for_run(pug_root: Path, config: dict) -> dict:
    """Build env dict for pug run: .env from pug_root + BASE_URL and AUTH from config."""
    env = os.environ.copy()
    env_file = pug_root / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key:
                env[key] = val
    prefix = config.get("env_prefix", "")
    if prefix:
        env[f"{prefix}_BASE_URL"] = config.get("base_url", "")
        env[f"{prefix}_AUTH"] = config.get("auth_type", "none")
    return env


def _env_has_anthropic_key() -> bool:
    """True if .env exists and has a non-empty ANTHROPIC_API_KEY."""
    p = Path(".env")
    if not p.exists():
        return False
    for line in p.read_text().splitlines():
        line = line.strip()
        if line.startswith("ANTHROPIC_API_KEY="):
            val = line.split("=", 1)[1].strip().strip('"').strip("'")
            return bool(val)
    return False


def cmd_init():
    """Ask for Anthropic API Key and save to .env (Pug-themed). Skip prompt if key already set."""
    console.print()
    if _env_has_anthropic_key():
        console.print(
            Panel.fit(
                f"[{SUCCESS}]Huff! Key already set in .env 🦴[/]\n\n"
                "[dim]Run [bold]pug pant[/] to verify, or edit .env to change it.[/]",
                border_style=BORDER,
                title=f"[{GOLD}] init 🐾 [/]",
                title_align="left",
            )
        )
        return
    console.print(
        Panel.fit(
            f"[bold {GOLD}]🐶 Time to sniff out your API key[/]\n\n"
            "[dim]Pug needs your Anthropic API key so he can pant at the docs.\n"
            "Paste it below (input is hidden). 🦴[/]",
            border_style=BORDER,
            title=f"[{GOLD}] init 🐾 [/]",
            title_align="left",
        )
    )
    console.print()

    try:
        api_key = Prompt.ask(
            f"[{GOLD}]🐶 Anthropic API Key[/]",
            password=True,
            default="",
        )
    except (KeyboardInterrupt, EOFError):
        console.print(f"\n[{ERROR}]Bark! You ran away. No treat this time.[/]")
        return

    if not api_key or not api_key.strip():
        console.print(f"[{ERROR}]Bark! Something's stuck in my throat (empty key).[/]")
        return

    env_path = Path(".env")
    line = f'ANTHROPIC_API_KEY="{api_key.strip()}"\n'
    try:
        if env_path.exists():
            content = env_path.read_text()
            if "ANTHROPIC_API_KEY" in content:
                # Replace existing key
                lines = []
                for l in content.splitlines():
                    if l.strip().startswith("ANTHROPIC_API_KEY="):
                        lines.append(line.rstrip())
                    else:
                        lines.append(l)
                env_path.write_text("\n".join(lines) + "\n")
            else:
                env_path.write_text(content.rstrip() + "\n" + line)
        else:
            env_path.write_text(line)
    except OSError as e:
        console.print(f"[{ERROR}]Bark! Something's stuck in my throat ({e}).[/]")
        return

    console.print()
    console.print(
        Panel.fit(
            f"[{SUCCESS}]Huff! I did it. Where's my treat?[/]\n\n"
            f"[dim]Saved to [bold]{env_path.resolve()}[/bold][/]",
            border_style=BORDER,
            title=f"[{GOLD}] 🦴 .env 🐾 [/]",
            title_align="left",
        )
    )
    # Prompt for first bone so user has an active project
    current = _get_current_bone()
    if not current:
        try:
            name = Prompt.ask(
                f"[{GOLD}]Create your first bone?[/] [dim](project name, e.g. api-search-brave-com-cli; Enter to skip)[/]",
                default="",
            ).strip()
            if name:
                _set_current_bone(name)
                _pug_project_dir(name).mkdir(parents=True, exist_ok=True)
                console.print(f"[dim]Active bone: [bold]{name}[/]. Next: [bold]pug sniff <url>[/] 🦴[/]")
        except (KeyboardInterrupt, EOFError):
            pass


def cmd_bone(name: Optional[str] = None, exit_bone: bool = False) -> None:
    """Create or switch to a bone (project). All sniff/chew/refine/bark use the active bone.
    pug bone <name> — set active bone (creates .pug/<name>/ if needed)
    pug bone — show active bone and list bones
    pug bone --exit — clear active bone
    """
    if exit_bone:
        _clear_current_bone()
        console.print("[dim]Active bone cleared. Run [bold]pug bone <name>[/] to create or switch. 🦴[/]")
        return
    if name:
        name = name.strip()
        if not name:
            console.print(f"[{ERROR}]Bark! Bone name is required. Example: [bold]pug bone my-api[/] 🐶[/]")
            return
        _set_current_bone(name)
        _pug_project_dir(name).mkdir(parents=True, exist_ok=True)
        console.print(f"[{SUCCESS}]Active bone: [bold]{name}[/]. Sniff, chew, refine, bark now use this project. 🦴[/]")
        return
    # No name: show current and list
    current = _get_current_bone()
    pug = Path(".pug")
    bones = []
    if pug.exists():
        for c in sorted(pug.iterdir()):
            if c.is_dir() and c.name != "current" and not c.name.startswith("."):
                bones.append(c.name)
    if current:
        console.print(f"[dim]Active bone: [bold]{current}[/] 🦴[/]")
    else:
        console.print("[dim]No active bone. Run [bold]pug bone <name>[/] to create one (e.g. [bold]pug bone api-search-brave-com-cli[/]).[/]")
    if bones:
        console.print(f"[dim]Bones: [bold]{', '.join(bones)}[/][/]")


def cmd_sniff(url: Optional[str] = None, save_as: Optional[str] = None, resniff: bool = False):
    """Sniff a URL with Playwright; strip nav/footer; return clean Markdown.
    Uses the active bone (set with pug bone <name>). Use --resniff to re-fetch the last URL.
    """
    project = _get_current_bone()
    if not project:
        console.print(f"[{ERROR}]Bark! No active bone. Run [bold]pug bone <name>[/] first (e.g. [bold]pug bone api-search-brave-com-cli[/]). 🐶[/]")
        return
    if resniff:
        pug_dir = _pug_project_dir(project)
        full_url_path = pug_dir / "last_sniff_full_url"
        if not full_url_path.exists():
            console.print(f"[{ERROR}]Bark! No previous sniff URL for [bold]{project}[/]. Run [bold]pug sniff <url>[/] first. 🐶[/]")
            return
        url = full_url_path.read_text(encoding="utf-8").strip()
        if not url:
            console.print(f"[{ERROR}]Bark! Stored sniff URL is empty. Run [bold]pug sniff {project} <url>[/] again. 🐶[/]")
            return
        console.print(f"[dim]Resniffing [bold]{url}[/] 🐶[/]")
    elif not url or not url.strip():
        console.print(f"[{ERROR}]Bark! Give me a URL to sniff: [bold]pug sniff {project} <url>[/], or use [bold]--resniff[/] to re-fetch the last one. 🐶[/]")
        return
    else:
        url = url.strip()

    progress = Progress(
        SpinnerColumn(),
        console=console,
    )
    task_id = None

    def progress_cb(show: bool):
        nonlocal task_id
        if show:
            progress.start()
            task_id = progress.add_task(
                "[tan]Sniffing around the bushes... 🐶[/]",
                total=None,
            )
        else:
            progress.stop()

    try:
        md = sniff(url, progress_callback=progress_cb, show_progress_after_seconds=5.0)
    except Exception as e:
        console.print(
            f"[{ERROR}]Bark! Something's stuck in my throat ({e}).[/]"
        )
        return

    console.print()
    # Escape so paths like [/posts/1/comments] aren't parsed as Rich tags
    body = escape(md) if md else "[dim](No content sniffed)[/]"
    console.print(
        Panel.fit(
            body,
            border_style=BORDER,
            title=f"[{GOLD}] sniff 🐾 [/]",
            title_align="left",
        )
    )
    if md:
        pug_dir = _pug_project_dir(project)
        pug_dir.mkdir(parents=True, exist_ok=True)
        if save_as:
            out_path = pug_dir / f"sniff_{save_as.strip()}.md"
            out_path.write_text(md, encoding="utf-8")
            console.print(f"[{SUCCESS}]Huff! I did it. Where's my treat?[/] [dim]Saved to [bold]{out_path}[/].[/]")
        else:
            (pug_dir / "last_sniff.md").write_text(md, encoding="utf-8")
            (pug_dir / "last_sniff_full_url").write_text(url, encoding="utf-8")
            try:
                from urllib.parse import urlparse
                base = urlparse(url)
                base_url = f"{base.scheme or 'https'}://{base.netloc or base.path.split('/')[0]}".rstrip("/")
                (pug_dir / "last_sniff_url").write_text(base_url, encoding="utf-8")
            except Exception:
                pass
            console.print(f"[{SUCCESS}]Huff! I did it. Where's my treat?[/]")
        console.print(f"[dim]Next: [bold]pug chew[/] then [bold]pug bark[/]. 🦴[/]")


# Current bone (project): .pug/current stores the active project name
CURRENT_BONE_FILE = Path(".pug") / "current"


def _get_current_bone() -> Optional[str]:
    """Return the active bone name from .pug/current, or None."""
    if not CURRENT_BONE_FILE.exists():
        return None
    name = CURRENT_BONE_FILE.read_text(encoding="utf-8").strip()
    return name if name else None


def _set_current_bone(name: str) -> None:
    """Set the active bone; creates .pug if needed."""
    Path(".pug").mkdir(exist_ok=True)
    CURRENT_BONE_FILE.write_text(name.strip(), encoding="utf-8")


def _clear_current_bone() -> None:
    """Clear the active bone."""
    if CURRENT_BONE_FILE.exists():
        CURRENT_BONE_FILE.write_text("", encoding="utf-8")


def _pug_project_dir(project: str) -> Path:
    """Return .pug/<project>/."""
    return Path(".pug") / project.strip()


def cmd_chew(markdown_source: str = "-", merge: bool = False):
    """CHEW: AI reads Markdown and suggests CLI structure; show 'The Bone Map' table.
    Uses the active bone. If merge is True, merge new commands from the doc into the existing bone map.
    """
    project = _get_current_bone()
    if not project:
        console.print(f"[{ERROR}]Bark! No active bone. Run [bold]pug bone <name>[/] first. 🐶[/]")
        return
    pug_dir = _pug_project_dir(project)
    last_sniff_path = pug_dir / "last_sniff.md"
    bone_map_path = pug_dir / "bone_map.json"

    if markdown_source == "-" or not markdown_source:
        if last_sniff_path.exists():
            md = last_sniff_path.read_text(encoding="utf-8")
        else:
            md = sys.stdin.read()
    else:
        path = Path(markdown_source)
        if not path.exists():
            console.print(f"[{ERROR}]Bark! Something's stuck in my throat (file not found: {path}).[/]")
            return
        md = path.read_text()

    if not md.strip():
        console.print(f"[{ERROR}]Bark! Something's stuck in my throat (empty Markdown).[/]")
        return

    do_merge = merge and bone_map_path.exists()
    if do_merge:
        existing = json.loads(bone_map_path.read_text(encoding="utf-8"))
        if not isinstance(existing, list):
            existing = []
        console.print("[italic]Pug is thinking... (Merging new bones into the map) 🦴[/]")
    else:
        console.print("[italic]Pug is thinking... (Heavy breathing noises)[/]")

    try:
        if do_merge:
            plan = chew_merge(md, existing)
            config = None  # keep existing bark config
        else:
            plan, config = chew(md)
    except FileNotFoundError as e:
        console.print(f"[{ERROR}]Bark! Something's stuck in my throat ({e}).[/]")
        return
    except ValueError as e:
        console.print(f"[{ERROR}]Bark! Something's stuck in my throat ({e}).[/]")
        return
    except Exception as e:
        console.print(f"[{ERROR}]Bark! Something's stuck in my throat ({e}).[/]")
        return

    pug_dir.mkdir(parents=True, exist_ok=True)
    save_bone_map(plan, bone_map_path)

    if config:
        save_bark_config(
            pug_dir,
            base_url=config.get("base_url") or (pug_dir / "last_sniff_url").read_text(encoding="utf-8").strip() if (pug_dir / "last_sniff_url").exists() else "https://api.example.com",
            auth_type=config.get("auth_type", "none"),
            api_key_env=config.get("api_key_env", "API_KEY"),
            auth_header=config.get("auth_header"),
        )
        if config.get("base_url"):
            (pug_dir / "last_sniff_url").write_text(config["base_url"], encoding="utf-8")

    rows = plan_to_bone_map_rows(plan)
    table = Table(
        title=f"[bold {GOLD}]🦴 The Bone Map 🐾[/]",
        title_style=f"bold {BROWN}",
        border_style=BORDER,
        header_style=f"bold {TAN}",
        show_header=True,
    )
    table.add_column("Command", style=TAN)
    table.add_column("Method", style="dim")
    table.add_column("Path", style="dim")
    table.add_column("Flags", style="dim")
    table.add_column("Notes", style="dim")
    for row in rows:
        table.add_row(*row)

    console.print()
    console.print(table)
    console.print(f"[dim]Saved to [bold]{bone_map_path.resolve()}[/bold][/dim]")
    if do_merge:
        console.print(f"[dim]Merged [bold]{len(rows)}[/] commands. Run [bold]pug bark[/] to regenerate the CLI. 🦴[/]")
    else:
        base_hint = ""
        if (pug_dir / "last_sniff_url").exists():
            base_hint = (pug_dir / "last_sniff_url").read_text(encoding="utf-8").strip()
        if config and config.get("base_url"):
            console.print(f"[dim]Insights: [bold]{len(rows)}[/] commands · API base URL from docs: [bold]{config['base_url']}[/][/]")
            if config.get("auth_type") != "none":
                console.print(f"[dim]Auth from docs: [bold]{config['auth_type']}[/] (header: {config.get('auth_header', '')}, env: {config.get('api_key_env', '')})[/]")
        else:
            console.print(f"[dim]Insights: [bold]{len(rows)}[/] commands · base URL: [bold]{base_hint or '(set in bark)'}[/][/]")
        console.print(f"[dim]Run [bold]pug bark[/] to verify (smell test) and generate CLI + docs + MCP. 🦴[/]")
    console.print(f"[dim]Bone map: [bold].pug/{project}/[/].[/]")
    console.print(f"[{SUCCESS}]Huff! I did it. Where's my treat?[/]")


def cmd_pant():
    """PANT: Live auth validation — is the API key a treat or a trick?"""
    console.print()
    console.print(
        Panel.fit(
            f"[bold {GOLD}]🐶 Panting at the key...[/]\n\n"
            "[dim]Is this key a treat or a trick? 🦴[/]",
            border_style=BORDER,
            title=f"[{GOLD}] pant 🐾 [/]",
            title_align="left",
        )
    )
    console.print()
    try:
        validate_anthropic_key()
        console.print(f"[{SUCCESS}]Huff! I did it. Where's my treat?[/] [dim](Key is valid.)[/]")
    except FileNotFoundError as e:
        console.print(f"[{ERROR}]Bark! Something's stuck in my throat ({e}).[/]")
    except ValueError as e:
        console.print(f"[{ERROR}]Bark! Something's stuck in my throat ({e}).[/]")
    except Exception as e:
        console.print(f"[{ERROR}]Bark! Something's stuck in my throat ({e}).[/] [dim](Key might be invalid or rate-limited.)[/]")


def cmd_bark():
    """BARK: System compiler — smell test, then generate Go CLI + CLAUDE.md, SKILL.md, MCP. Uses the active bone."""
    _load_dotenv_into_env()
    project_name = _get_current_bone()
    if not project_name:
        console.print(f"[{ERROR}]Bark! No active bone. Run [bold]pug bone <name>[/] first. 🐶[/]")
        return
    pug_root = Path(".pug")
    pug_dir = pug_root / project_name
    bone_map_path = pug_dir / "bone_map.json"
    if not bone_map_path.exists():
        console.print(f"[{ERROR}]Bark! No Bone Map for [bold]{project_name}[/]. Run [bold]pug sniff <url>[/] then [bold]pug chew[/] first. 🐶[/]")
        return

    console.print()
    console.print(
        Panel.fit(
            f"[bold {GOLD}]🐶 Barking at the Bone Map...[/]\n\n"
            "[dim]Smell test → Go/Cobra, CLAUDE.md, SKILL.md, mcp.json (one folder per API). 🦴[/]",
            border_style=BORDER,
            title=f"[{GOLD}] bark 🐾 [/]",
            title_align="left",
        )
    )
    console.print()

    def _looks_like_key(s: str) -> bool:
        """True if input looks like a secret key rather than an env var name (e.g. BRAVE_SEARCH_TOKEN)."""
        s = (s or "").strip()
        if len(s) > 35 and s.replace("_", "").isalnum():
            return True
        if len(s) > 25 and "_" not in s and s.isalnum():
            return True
        return False

    def refine_chat(err: str, pug_dir: Path, config: dict):
        console.print(f"[{ERROR}]Bark! Smell test failed: {err}[/]")
        if "422" in err:
            console.print("[dim]422 often means a required parameter is missing (e.g. ?q= for search APIs). Auth may still be correct.[/]")
        try:
            # 404 often means base URL is the docs page, not the API — offer to fix
            if "404" in err:
                console.print(
                    "[dim]The base URL might be the docs page, not the API. "
                    "Your sniff URL was used; the real API may be different (e.g. https://api.search.brave.com/res).[/]"
                )
                new_base = Prompt.ask(
                    f"[tan]Enter API base URL (or Enter to keep [bold]{config['base_url']}[/])[/]",
                    default="",
                )
                if new_base.strip():
                    save_bark_config(
                        pug_dir,
                        base_url=new_base.strip().rstrip("/"),
                        auth_type=config.get("auth_type", "none"),
                        api_key_env=config.get("api_key_env", "API_KEY"),
                        auth_header=config.get("auth_header"),
                    )
                    console.print("[dim]Saved. Retrying smell test.[/]")
                    return {"retry": True}
            suggested = (config.get("api_key_env") or "API_KEY").strip()
            if _looks_like_key(suggested):
                suggested = "API_KEY"
            console.print(
                "[dim]Add auth: [1] Paste API key now (saved to .env, used for smell test)  "
                "[2] I'll set the env var myself (enter var name only)  [n] Skip[/]"
            )
            choice = Prompt.ask("[tan]Choice (1 / 2 / n)[/]", default="n").strip().lower()
            if choice == "1":
                key_val = Prompt.ask("[tan]Paste API key (input hidden)[/]", password=True, default="")
                if not key_val.strip():
                    console.print("[dim]No key entered. Skipping.[/]")
                else:
                    var_name = Prompt.ask(
                        f"[tan]Env var name to save in .env (e.g. BRAVE_SEARCH_TOKEN)[/]",
                        default=suggested,
                    ).strip() or suggested
                    if _looks_like_key(var_name):
                        var_name = suggested
                    env_file = Path(".env")
                    content = env_file.read_text(encoding="utf-8") if env_file.exists() else ""
                    lines = [l for l in content.splitlines() if l.strip() and not l.strip().startswith(var_name + "=")]
                    lines.append(f'{var_name}="{key_val.strip()}"')
                    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
                    os.environ[var_name] = key_val.strip()
                    save_bark_config(
                        pug_dir,
                        base_url=config["base_url"],
                        auth_type=config.get("auth_type") or "api_key_header",
                        api_key_env=var_name,
                        auth_header=config.get("auth_header"),
                    )
                    console.print(f"[dim]Saved to .env as [bold]{var_name}[/]. Retrying smell test.[/]")
                    return {"retry": True}
            elif choice == "2":
                auth_type_choice = Prompt.ask(
                    "[tan]Auth type: bearer / api_key_header / basic[/]",
                    default=config.get("auth_type") or "api_key_header",
                ).strip().lower() or "api_key_header"
                var_name = Prompt.ask(
                    f"[tan]Env var **name** only (e.g. BRAVE_SEARCH_TOKEN). Not the key value.[/]",
                    default=suggested,
                ).strip() or suggested
                if _looks_like_key(var_name):
                    console.print("[dim]That looks like a key, not a var name. Use a name like BRAVE_SEARCH_TOKEN. Skipping.[/]")
                else:
                    save_bark_config(
                        pug_dir,
                        base_url=config["base_url"],
                        auth_type=auth_type_choice if auth_type_choice in ("bearer", "api_key_header", "basic") else "api_key_header",
                        api_key_env=var_name,
                        auth_header=config.get("auth_header"),
                    )
                    console.print(f"[dim]Saved. In this shell run: [bold]export {var_name}=your_key[/] then run [bold]pug bark[/] again.[/]")
                    return {"retry": True}
            answer = Prompt.ask("[tan]Continue and generate anyway? (y/N)[/]", default="n")
            return answer.strip().lower() in ("y", "yes")
        except (KeyboardInterrupt, EOFError):
            return False

    def _on_smell_test(url: str, success: bool, err: str):
        if success:
            console.print(f"[dim]Smell test: [bold]GET[/] [dim]{url}[/] → [green]OK[/] 🦴[/]")
        else:
            console.print(f"[dim]Smell test: [bold]GET[/] [dim]{url}[/] → [red]failed[/] ({err})[/]")

    try:
        out_dir = run_bark(
            bone_map_path,
            pug_dir,
            project_name,
            refine_chat_on_fail=refine_chat,
            on_smell_test=_on_smell_test,
        )
        cli_name = out_dir.name
        bin_path = out_dir / "bin" / cli_name
        console.print(f"[{SUCCESS}]Huff! I did it. Where's my treat?[/]")
        console.print(f"[dim]Generated [bold]{out_dir.resolve()}/[/]: CLAUDE.md, SKILL.md, mcp.json, mcp-server.cjs[/]")
        if bin_path.exists():
            console.print(f"[dim]Test it: [bold]pug run {cli_name} web-search --q hello[/] (loads .env + base URL + auth for you). Or [bold]pug run {cli_name} --help[/].[/]")
            console.print(f"[dim]To add or change commands later: [bold]pug refine[/] then [bold]pug bark[/]. Run it: [bold]pug run[/] or [bold]pug run {cli_name} ...[/]. 🦴[/]")
        else:
            build_log = out_dir / "build.log"
            hint = f" See [bold]{build_log}[/] for errors." if build_log.exists() else ""
            console.print(
                f"[dim][yellow]Binary not built[/] (Pug builds it automatically when [bold]Go[/] is installed).{hint} "
                f"Install Go from [bold]https://go.dev/dl/[/] then run [bold]pug bark {cli_name}[/] again, or build now: [bold]cd {out_dir} && go build -o bin/{cli_name} .[/][/]"
            )
    except SystemExit:
        raise
    except FileNotFoundError as e:
        console.print(f"[{ERROR}]Bark! Something's stuck in my throat ({e}).[/]")
    except ValueError as e:
        console.print(f"[{ERROR}]Bark! Something's stuck in my throat ({e}).[/]")
    except Exception as e:
        console.print(f"[{ERROR}]Bark! Something's stuck in my throat ({e}).[/]")


def cmd_refine():
    """REFINE: Chat with Pug (LLM) to tweak the Bone Map until ready; then run pug bark. Uses the active bone."""
    project = _get_current_bone()
    if not project:
        console.print(f"[{ERROR}]Bark! No active bone. Run [bold]pug bone <name>[/] first. 🐶[/]")
        return
    pug_dir = _pug_project_dir(project)
    bone_map_path = pug_dir / "bone_map.json"
    if not bone_map_path.exists():
        console.print(f"[{ERROR}]Bark! No Bone Map for [bold]{project}[/]. Run [bold]pug chew[/] first. 🐶[/]")
        return
    bone_map = json.loads(bone_map_path.read_text(encoding="utf-8"))
    if not isinstance(bone_map, list):
        console.print(f"[{ERROR}]Bark! bone_map.json must be a JSON array.[/]")
        return
    console.print()
    console.print(
        Panel.fit(
            f"[bold {GOLD}]🐶 Refine the Bone Map 🦴[/]\n\n"
            f"[dim]Project [bold]{project}[/]: [bold].pug/{project}/[/]\n"
            "This Bone Map drives [bold]pug bark[/]. Ask Pug to add, remove, or change commands (e.g. \"add image-search GET /res/v1/images/search with --q\").\n"
            "Say [bold]done[/] or [bold]ready[/] when you want to run [bold]pug bark[/] (same folder regenerated).[/]",
            border_style=BORDER,
            title=f"[{GOLD}] refine 🐾 [/]",
            title_align="left",
        )
    )
    console.print()
    history = []
    table_args = {
        "title": f"[bold {GOLD}]🦴 The Bone Map 🐾[/]",
        "title_style": f"bold {BROWN}",
        "border_style": BORDER,
        "header_style": f"bold {TAN}",
        "show_header": True,
    }
    while True:
        try:
            user_input = Prompt.ask(f"[{GOLD}]You[/]")
        except (KeyboardInterrupt, EOFError):
            console.print(f"[dim]Bye. Run [bold]pug bark[/] when ready. 🐶[/]")
            break
        line = (user_input or "").strip().lower()
        if line in ("done", "ready", "exit", "quit", "q") or not user_input.strip():
            console.print(f"[dim]Run [bold]pug bark[/] to verify and generate. 🐶[/]")
            break
        console.print("[italic]Pug is thinking... (Heavy breathing noises)[/]")
        try:
            reply, updated = refine_turn(user_input, history, bone_map)
        except FileNotFoundError:
            console.print(f"[{ERROR}]Bark! No API key. Run [bold]pug init[/].[/]")
            break
        except Exception as e:
            console.print(f"[{ERROR}]Bark! Something's stuck in my throat ({e}).[/]")
            continue
        console.print(f"[tan]Pug[/]: {reply}")
        if updated:
            save_bone_map(updated, bone_map_path)
            bone_map = updated
            rows = plan_to_bone_map_rows(bone_map)
            table = Table(**table_args)
            table.add_column("Command", style=TAN)
            table.add_column("Method", style="dim")
            table.add_column("Path", style="dim")
            table.add_column("Flags", style="dim")
            table.add_column("Notes", style="dim")
            for row in rows:
                table.add_row(*row)
            console.print()
            console.print(table)
            console.print(f"[dim]Bone Map updated. Say [bold]done[/] when ready for [bold]pug bark[/].[/]")
        history.append({"role": "user", "content": user_input})
        history.append({"role": "assistant", "content": reply})


def cmd_run(project_or_first_arg: Optional[str], run_args: list[str]) -> None:
    """Run a generated CLI. If project is omitted, use active bone. Pass-through args go to the CLI."""
    pug_root = Path.cwd()
    # If first token is a valid project (dir exists), use it; else use current bone and treat token as first CLI arg
    project_name = None
    args = list(run_args)
    if project_or_first_arg:
        if (pug_root / project_or_first_arg).is_dir() or (pug_root / ".pug" / project_or_first_arg).exists():
            project_name = project_or_first_arg
        else:
            project_name = _get_current_bone()
            args = [project_or_first_arg] + args
    if not project_name:
        project_name = _get_current_bone()
    if not project_name:
        console.print(f"[{ERROR}]Bark! No active bone and no project given. Run [bold]pug bone <name>[/] or [bold]pug run <project> [args...][/]. 🐶[/]")
        return
    project_dir = pug_root / project_name
    if not project_dir.is_dir():
        console.print(f"[{ERROR}]Bark! No such project: [bold]{project_name}[/]. Run [bold]pug bark[/] first. 🐶[/]")
        return
    config_path = project_dir / ".pug-config.json"
    if config_path.exists():
        config = json.loads(config_path.read_text(encoding="utf-8"))
    else:
        # Old build: try .pug/<project>/bark_config.json then .pug/bark_config.json
        bark_config = pug_root / ".pug" / project_name / "bark_config.json"
        if not bark_config.exists():
            bark_config = pug_root / ".pug" / "bark_config.json"
        if bark_config.exists():
            config = json.loads(bark_config.read_text(encoding="utf-8"))
            env_prefix = project_name.upper().replace("-", "_")
            config["env_prefix"] = env_prefix
            config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
        else:
            console.print(f"[{ERROR}]Bark! [bold]{project_name}[/] has no .pug-config.json and no .pug/bark_config.json. Re-run [bold]pug bark[/]. 🐶[/]")
            return
    bin_path = project_dir / "bin" / project_name
    if not bin_path.exists():
        console.print(f"[{ERROR}]Bark! No binary at [bold]{bin_path}[/]. Install Go and run [bold]go build -o bin/{project_name} .[/] in [bold]{project_dir}[/]. 🐶[/]")
        return
    env = _env_for_run(pug_root, config)
    cmd = [str(bin_path)] + args
    try:
        subprocess.run(cmd, env=env, cwd=str(project_dir))
    except KeyboardInterrupt:
        pass


def main():
    parser = argparse.ArgumentParser(
        description="🐶 PUG — The Stubborn API Scraper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # init: save Anthropic API key to .env
    subparsers.add_parser("init", help="🐾 Set up API key (saved to .env)")

    # bone: create/switch/exit active project (all other commands use this)
    bone_parser = subparsers.add_parser("bone", help="🦴 Create or switch to a bone (project). Sniff/chew/refine/bark use the active bone.")
    bone_parser.add_argument("name", nargs="?", default=None, help="Bone name (e.g. api-search-brave-com-cli); omit to list, or use --exit to clear")
    bone_parser.add_argument("--exit", dest="exit_bone", action="store_true", help="Clear active bone (exit bone)")

    # sniff: uses active bone
    sniff_parser = subparsers.add_parser("sniff", help="🐾 Sniff a URL (scrape and clean to Markdown)")
    sniff_parser.add_argument("url", nargs="?", default=None, help="URL to sniff (omit when using --resniff)")
    sniff_parser.add_argument("--resniff", action="store_true", help="Re-fetch the last sniffed URL for this bone (no URL needed)")
    sniff_parser.add_argument("--save-as", metavar="name", help="Save to .pug/<bone>/sniff_<name>.md instead of last_sniff.md (for adding from another URL)")

    # chew: uses active bone
    chew_parser = subparsers.add_parser("chew", help="🐾 CHEW: suggest CLI from Markdown (query params → flags)")
    chew_parser.add_argument(
        "source",
        nargs="?",
        default="-",
        help="Markdown file, or '-' for stdin; if omitted, use last sniff",
    )
    chew_parser.add_argument(
        "--merge",
        action="store_true",
        help="Merge new commands from the doc into the existing Bone Map (use after sniff --save-as)",
    )

    # pant: live auth validation (is the key a treat or a trick?)
    subparsers.add_parser("pant", help="🐾 PANT: test API key (treat or trick?)")

    # bark: uses active bone
    bark_parser = subparsers.add_parser("bark", help="🐾 BARK: generate Go CLI + docs + MCP (uses active bone)")

    # refine: uses active bone
    refine_parser = subparsers.add_parser("refine", help="🐾 REFINE: chat with Pug to improve Bone Map, then run bark when ready")

    # run: optional project (defaults to active bone); rest is pass-through to the CLI
    run_parser = subparsers.add_parser(
        "run",
        help="🐾 RUN: run a generated CLI (loads .env + config); omit project to use active bone",
        description="Run a generated CLI. If you omit the project name, the active bone is used. Everything after is passed to that CLI (e.g. pug run web-search --q hello).",
        add_help=False,
    )
    run_parser.add_argument("project", nargs="?", default=None, help="Project name (optional; uses active bone if omitted)")

    args, unknown = parser.parse_known_args()

    welcome(show_ascii_art=(args.command == "init"))

    if args.command == "init":
        cmd_init()
    elif args.command == "bone":
        cmd_bone(name=getattr(args, "name", None), exit_bone=getattr(args, "exit_bone", False))
    elif args.command == "sniff":
        cmd_sniff(
            url=args.url,
            save_as=getattr(args, "save_as", None),
            resniff=getattr(args, "resniff", False),
        )
    elif args.command == "chew":
        cmd_chew(markdown_source=args.source, merge=getattr(args, "merge", False))
    elif args.command == "pant":
        cmd_pant()
    elif args.command == "bark":
        cmd_bark()
    elif args.command == "refine":
        cmd_refine()
    elif args.command == "run":
        if getattr(args, "project", None) in ("--help", "-h") and not unknown:
            console.print(run_parser.format_help())
            return
        cmd_run(getattr(args, "project", None), unknown or [])
    elif args.command is None:
        console.print(f"[dim]Use [bold {GOLD}]pug init[/] to set your API key, then [bold]pug bone <name>[/] to create a project. 🐶[/]")
        console.print("[dim]Commands: bone, sniff, chew, pant, refine, bark, run.[/]")


if __name__ == "__main__":
    main()