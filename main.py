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

from core.architect import chew, plan_to_bone_map_rows, refine_turn, save_bone_map, validate_anthropic_key
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


def cmd_sniff(url: str):
    """Sniff a URL with Playwright; strip nav/footer; return clean Markdown."""
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
        # Save for chew and bark: last sniff markdown + base URL
        pug_dir = Path(".pug")
        pug_dir.mkdir(exist_ok=True)
        (pug_dir / "last_sniff.md").write_text(md, encoding="utf-8")
        try:
            from urllib.parse import urlparse
            base = urlparse(url)
            base_url = f"{base.scheme or 'https'}://{base.netloc or base.path.split('/')[0]}".rstrip("/")
            (pug_dir / "last_sniff_url").write_text(base_url, encoding="utf-8")
        except Exception:
            pass
        console.print(f"[{SUCCESS}]Huff! I did it. Where's my treat?[/]")


# Path to last sniff output and Bone Map JSON
PUG_DIR = Path(".pug")
LAST_SNIFF_PATH = PUG_DIR / "last_sniff.md"
BONE_MAP_PATH = PUG_DIR / "bone_map.json"


def cmd_chew(markdown_source: str):
    """CHEW: AI reads Markdown and suggests CLI structure; show 'The Bone Map' table."""
    if markdown_source == "-" or not markdown_source:
        # Use last sniff if available, else stdin
        if LAST_SNIFF_PATH.exists():
            md = LAST_SNIFF_PATH.read_text(encoding="utf-8")
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

    console.print("[italic]Pug is thinking... (Heavy breathing noises)[/]")
    try:
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

    # Persist Bone Map JSON for pant/huff
    save_bone_map(plan, BONE_MAP_PATH)

    # If the LLM extracted base URL and/or auth from the docs, save for bark
    if config:
        save_bark_config(
            PUG_DIR,
            base_url=config.get("base_url") or (PUG_DIR / "last_sniff_url").read_text(encoding="utf-8").strip() if (PUG_DIR / "last_sniff_url").exists() else "https://api.example.com",
            auth_type=config.get("auth_type", "none"),
            api_key_env=config.get("api_key_env", "API_KEY"),
            auth_header=config.get("auth_header"),
        )
        if config.get("base_url"):
            (PUG_DIR / "last_sniff_url").write_text(config["base_url"], encoding="utf-8")

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
    console.print(f"[dim]Saved to [bold]{BONE_MAP_PATH.resolve()}[/bold][/dim]")
    # Insights: command count, base URL and auth from docs when extracted
    base_hint = ""
    if (PUG_DIR / "last_sniff_url").exists():
        base_hint = (PUG_DIR / "last_sniff_url").read_text(encoding="utf-8").strip()
    if config and config.get("base_url"):
        console.print(f"[dim]Insights: [bold]{len(rows)}[/] commands · API base URL from docs: [bold]{config['base_url']}[/][/]")
        if config.get("auth_type") != "none":
            console.print(f"[dim]Auth from docs: [bold]{config['auth_type']}[/] (header: {config.get('auth_header', '')}, env: {config.get('api_key_env', '')})[/]")
    else:
        console.print(f"[dim]Insights: [bold]{len(rows)}[/] commands · base URL: [bold]{base_hint or '(set in bark)'}[/][/]")
    console.print(f"[dim]Run [bold]pug bark[/] to verify (smell test) and generate CLI + docs + MCP. 🦴[/]")
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


def cmd_bark(project_name: Optional[str] = None):
    """BARK: System compiler — smell test, then generate Go CLI + CLAUDE.md, SKILL.md, MCP (one folder per API)."""
    _load_dotenv_into_env()
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
            BONE_MAP_PATH,
            PUG_DIR,
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
        else:
            build_log = out_dir / "build.log"
            hint = f" See [bold]{build_log}[/] for errors." if build_log.exists() else ""
            console.print(
                f"[dim][yellow]Binary not built[/] (Pug builds it automatically when [bold]Go[/] is installed).{hint} "
                f"Install Go from [bold]https://go.dev/dl/[/] then run [bold]pug bark[/] again, or build now: [bold]cd {out_dir} && go build -o bin/{cli_name} .[/][/]"
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
    """REFINE: Chat with Pug (LLM) to tweak the Bone Map until ready; then run pug bark."""
    if not BONE_MAP_PATH.exists():
        console.print(f"[{ERROR}]Bark! No Bone Map. Run [bold]pug chew[/] first. 🐶[/]")
        return
    bone_map = json.loads(BONE_MAP_PATH.read_text(encoding="utf-8"))
    if not isinstance(bone_map, list):
        console.print(f"[{ERROR}]Bark! bone_map.json must be a JSON array.[/]")
        return
    console.print()
    console.print(
        Panel.fit(
            f"[bold {GOLD}]🐶 Refine the Bone Map 🦴[/]\n\n"
            "[dim]Ask Pug to add, remove, or change commands. Say [bold]done[/] or [bold]ready[/] when you want to run [bold]pug bark[/].[/]",
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
            console.print("[dim]Bye. Run [bold]pug bark[/] when ready. 🐶[/]")
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
            save_bone_map(updated, BONE_MAP_PATH)
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
            console.print("[dim]Bone Map updated. Say [bold]done[/] when ready for [bold]pug bark[/].[/]")
        history.append({"role": "user", "content": user_input})
        history.append({"role": "assistant", "content": reply})


def cmd_run(project_name: str, run_args: list[str]) -> None:
    """Run a generated CLI with .env and project config (base URL, auth) already set."""
    pug_root = Path.cwd()
    project_dir = pug_root / project_name
    if not project_dir.is_dir():
        console.print(f"[{ERROR}]Bark! No such project: [bold]{project_name}[/]. Run [bold]pug bark[/] first. 🐶[/]")
        return
    config_path = project_dir / ".pug-config.json"
    if config_path.exists():
        config = json.loads(config_path.read_text(encoding="utf-8"))
    else:
        # Old build: try .pug/bark_config.json and write .pug-config.json into project
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
    cmd = [str(bin_path)] + run_args
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

    # sniff: scrape URL, strip trash, return Markdown
    sniff_parser = subparsers.add_parser("sniff", help="🐾 Sniff a URL (scrape and clean to Markdown)")
    sniff_parser.add_argument("url", help="URL to sniff")

    # chew: AI suggests CLI structure from Markdown; show The Bone Map
    chew_parser = subparsers.add_parser("chew", help="🐾 CHEW: suggest CLI from Markdown (query params → flags)")
    chew_parser.add_argument(
        "source",
        nargs="?",
        default="-",
        help="Markdown file, or '-' for stdin; if omitted, use last sniff (.pug/last_sniff.md)",
    )

    # pant: live auth validation (is the key a treat or a trick?)
    subparsers.add_parser("pant", help="🐾 PANT: test API key (treat or trick?)")

    # bark: system compiler — Go CLI, CLAUDE.md, SKILL.md, MCP; smell test + refine chat; one folder per API
    bark_parser = subparsers.add_parser("bark", help="🐾 BARK: generate Go CLI + docs + MCP (folder per API, or pass name)")
    bark_parser.add_argument(
        "name",
        nargs="?",
        default=None,
        help="Project directory name (e.g. spotify-cli); default: derived from API base URL",
    )

    # refine: chat with Pug to tweak Bone Map until ready, then bark
    subparsers.add_parser("refine", help="🐾 REFINE: chat with Pug to improve Bone Map, then run bark when ready")

    # run: execute a generated CLI with .env + config (base URL, auth) set
    run_parser = subparsers.add_parser("run", help="🐾 RUN: run a generated CLI (loads .env + config so you don't set env by hand)")
    run_parser.add_argument("project", help="Project name (e.g. api-search-brave-com-cli)")
    run_parser.add_argument("args", nargs="*", help="Arguments passed to the CLI (e.g. web-search --q hello)")

    args = parser.parse_args()

    welcome(show_ascii_art=(args.command == "init"))

    if args.command == "init":
        cmd_init()
    elif args.command == "sniff":
        cmd_sniff(args.url)
    elif args.command == "chew":
        cmd_chew(args.source)
    elif args.command == "pant":
        cmd_pant()
    elif args.command == "bark":
        cmd_bark(project_name=args.name)
    elif args.command == "refine":
        cmd_refine()
    elif args.command == "run":
        cmd_run(args.project, args.args or [])
    elif args.command is None:
        console.print(f"[dim]Use [bold {GOLD}]pug init[/] to set your API key. 🐶[/]")
        console.print("[dim]Commands: sniff, chew, pant, refine, bark, run, huff (coming soon).[/]")


if __name__ == "__main__":
    main()