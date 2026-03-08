import argparse
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

from core.architect import chew, plan_to_bone_map_rows, save_bone_map, validate_anthropic_key
from core.barker import bark as run_bark
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


def cmd_init():
    """Ask for Anthropic API Key and save to .env (Pug-themed)."""
    console.print()
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
        plan = chew(md)
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

    def refine_chat(err: str):
        console.print(f"[{ERROR}]Bark! Smell test failed: {err}[/]")
        console.print("[dim]Edit .pug/bone_map.json or .pug/bark_config.json (base_url, auth_type), then run [bold]pug bark[/] again.[/]")
        try:
            answer = Prompt.ask("[tan]Continue and generate anyway? (y/N)[/]", default="n")
            return answer.strip().lower() in ("y", "yes")
        except (KeyboardInterrupt, EOFError):
            return False

    try:
        out_dir = run_bark(BONE_MAP_PATH, PUG_DIR, project_name, refine_chat_on_fail=refine_chat)
        cli_name = out_dir.name
        console.print(f"[{SUCCESS}]Huff! I did it. Where's my treat?[/]")
        console.print(f"[dim]Generated [bold]{out_dir.resolve()}/[/]: bin/{cli_name}, CLAUDE.md, SKILL.md, mcp.json, mcp-server.cjs[/]")
    except SystemExit:
        raise
    except FileNotFoundError as e:
        console.print(f"[{ERROR}]Bark! Something's stuck in my throat ({e}).[/]")
    except ValueError as e:
        console.print(f"[{ERROR}]Bark! Something's stuck in my throat ({e}).[/]")
    except Exception as e:
        console.print(f"[{ERROR}]Bark! Something's stuck in my throat ({e}).[/]")


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
    elif args.command is None:
        console.print(f"[dim]Use [bold {GOLD}]pug init[/] to set your API key. 🐶[/]")
        console.print("[dim]Commands: sniff, chew, pant, bark, huff (coming soon).[/]")


if __name__ == "__main__":
    main()