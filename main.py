import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from core.architect import (
    NO_KEY_MESSAGE,
    chew,
    chew_merge,
    find_api_key,
    get_model,
    plan_to_bone_map_rows,
    refine_turn,
    save_bone_map,
    validate_anthropic_key,
)
from core.barker import bark as run_bark, example_command, save_bark_config
from core.errors import PugError, friendly_error
from core.sniffer import sniff
from core.version import __version__

VERSION = __version__

console = Console()
err_console = Console(stderr=True)

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
        art = Text(PUG_ART.strip("\n"), style=TAN)
        title = Text(f"PUG v{VERSION}", style=f"bold {GOLD}")
        subtitle = Text("The Stubborn API Scraper", style=DIM)
        block = Text("\n").join([art, title, subtitle])
        console.print(Panel(block, border_style=BORDER, padding=(0, 2)))
    else:
        console.print(Panel.fit(
            f"🐶 [bold {GOLD}]PUG v{VERSION}[/] [dim]— The Stubborn API Scraper[/]",
            border_style=BORDER,
        ))
    console.print()


def fail(message: str, code: int = 1) -> None:
    """Print a one-line error (Rich markup allowed) to stderr and exit non-zero. 1 = failure, 2 = usage error."""
    err_console.print(f"[{ERROR}]Bark! {message}[/]", soft_wrap=True)
    raise SystemExit(code)


def _stdin_is_interactive() -> bool:
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def _print_bone_status() -> None:
    """Print active bone or 'no active bone' so status is visible on every run."""
    current = _get_current_bone()
    if current:
        console.print(f"[dim]Active bone: [bold]{current}[/] 🦴[/]")
    else:
        console.print("[dim]No active bone. Run [bold]pug bone <name>[/] to create one.[/]")


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


def _check_key(key: str) -> None:
    """Validate a key with one tiny Anthropic call; exit 1 with a one-line reason if it fails."""
    try:
        validate_anthropic_key(api_key=key)
    except Exception as e:
        fail(escape(friendly_error(e, model=get_model()) or f"Couldn't validate the key: {e}"))


def _read_new_key() -> str:
    """Read a key: hidden prompt on a terminal, or one line from stdin when piped (no getpass warning)."""
    if _stdin_is_interactive():
        try:
            return Prompt.ask(f"[{GOLD}]🐶 Anthropic API Key[/]", password=True, default="").strip()
        except (KeyboardInterrupt, EOFError):
            fail("You ran away. No key saved.")
    return (sys.stdin.readline() if sys.stdin else "").strip()


def _save_key(key: str) -> Path:
    env_path = Path(".env")
    line = f'ANTHROPIC_API_KEY="{key}"'
    try:
        if env_path.exists():
            content = env_path.read_text()
            if "ANTHROPIC_API_KEY" in content:
                lines = [line if l.strip().startswith("ANTHROPIC_API_KEY=") else l for l in content.splitlines()]
                env_path.write_text("\n".join(lines) + "\n")
            else:
                env_path.write_text(content.rstrip() + "\n" + line + "\n")
        else:
            env_path.write_text(line + "\n")
    except OSError as e:
        fail(escape(f"Couldn't write {env_path}: {e}"))
    return env_path


def cmd_init(force: bool = False):
    """Ask for the Anthropic API key, validate it, and only then save it to .env.
    If a key is already set (environment or .env), validate that one instead unless --force is given."""
    console.print()
    existing, source = find_api_key()
    if existing and not force:
        where = "ANTHROPIC_API_KEY in your environment" if source == "environment" else "the key in .env"
        console.print(f"[dim]Checking {where}... (use [bold]pug init --force[/] to replace it)[/]")
        _check_key(existing)
        console.print(f"[{SUCCESS}]Key validated. Treat! 🦴[/]")
        return
    console.print(
        Panel.fit(
            f"[bold {GOLD}]🐶 Time to sniff out your API key[/]\n\n"
            "[dim]Pug needs your Anthropic API key so he can chew the docs.\n"
            "Paste it below (input is hidden), or pipe it in: echo $KEY | pug init --force 🦴[/]",
            border_style=BORDER,
            title=f"[{GOLD}] init 🐾 [/]",
            title_align="left",
        )
    )
    console.print()
    api_key = _read_new_key()
    if not api_key:
        fail("No key entered. Paste your Anthropic API key, or set ANTHROPIC_API_KEY instead.")

    console.print("[dim]Validating key...[/]")
    _check_key(api_key)
    env_path = _save_key(api_key)
    console.print()
    console.print(
        Panel.fit(
            f"[{SUCCESS}]Key validated. Huff! I did it. Where's my treat?[/]\n\n"
            f"[dim]Saved to [bold]{env_path.resolve()}[/bold][/]",
            border_style=BORDER,
            title=f"[{GOLD}] 🦴 .env 🐾 [/]",
            title_align="left",
        )
    )
    # Prompt for first bone so user has an active project
    current = _get_current_bone()
    if not current and _stdin_is_interactive():
        try:
            name = Prompt.ask(
                f"[{GOLD}]Create your first bone?[/] [dim](project name, e.g. api-search-brave-com-cli; Enter to skip)[/]",
                default="",
            ).strip()
            if name:
                _check_bone_name(name)
                _set_current_bone(name)
                _pug_project_dir(name).mkdir(parents=True, exist_ok=True)
                console.print(f"[dim]Active bone: [bold]{name}[/]. Next: [bold]pug sniff <url>[/] 🦴[/]")
        except (KeyboardInterrupt, EOFError):
            pass


def cmd_bone(name: Optional[str] = None, exit_bone: bool = False) -> None:
    """Create or switch to a bone (project). All sniff/chew/refine/bark use the active bone.
    pug bone <name> — set active bone (creates bones/<name>/ if needed)
    pug bone — show active bone and list bones
    pug bone --exit — clear active bone
    """
    if exit_bone:
        _clear_current_bone()
        console.print("[dim]Active bone cleared. Run [bold]pug bone <name>[/] to create or switch. 🦴[/]")
        return
    if name is not None:
        name = name.strip()
        _check_bone_name(name)
        _set_current_bone(name)
        _pug_project_dir(name).mkdir(parents=True, exist_ok=True)
        console.print(f"[{SUCCESS}]Active bone: [bold]{name}[/]. Sniff, chew, refine, bark now use this project. 🦴[/]")
        return
    # No name: show current and list
    current = _get_current_bone()
    bones_list = []
    if BONES_DIR.exists():
        for c in sorted(BONES_DIR.iterdir()):
            if c.is_dir() and not c.name.startswith("."):
                bones_list.append(c.name)
    if current:
        console.print(f"[dim]Active bone: [bold]{current}[/] 🦴[/]")
    else:
        console.print("[dim]No active bone. Run [bold]pug bone <name>[/] to create one (e.g. [bold]pug bone api-search-brave-com-cli[/]).[/]")
    if bones_list:
        console.print(f"[dim]Bones: [bold]{', '.join(bones_list)}[/][/]")


def cmd_sniff(url: Optional[str] = None, save_as: Optional[str] = None, resniff: bool = False, verbose: bool = False):
    """Sniff a URL with Playwright; strip nav/footer; return clean Markdown.
    Uses the active bone (set with pug bone <name>). Use --resniff to re-fetch the last URL.
    """
    project = _require_bone()
    if save_as is not None:
        save_as = save_as.strip()
        if not BONE_NAME_RE.match(save_as):
            fail(f"Invalid --save-as name {escape(repr(save_as))}: use lowercase letters, digits, - and _ only.", code=2)
    if resniff:
        pug_dir = _pug_project_dir(project)
        full_url_path = pug_dir / "last_sniff_full_url"
        if not full_url_path.exists():
            fail(f"No previous sniff URL for [bold]{project}[/]. Run [bold]pug sniff <url>[/] first.")
        url = full_url_path.read_text(encoding="utf-8").strip()
        if not url:
            fail("Stored sniff URL is empty. Run [bold]pug sniff <url>[/] again.")
        console.print(f"[dim]Resniffing [bold]{url}[/] 🐶[/]")
    elif not url or not url.strip():
        fail("Give me a URL to sniff: [bold]pug sniff <url>[/], or use [bold]--resniff[/] to re-fetch the last one.", code=2)
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
    finally:
        progress.stop()
    if not md:
        fail(escape(f"No content found at {url} (the page was empty after removing nav/footer)."))

    pug_dir = _pug_project_dir(project)
    pug_dir.mkdir(parents=True, exist_ok=True)
    out_path = pug_dir / (f"sniff_{save_as}.md" if save_as else "last_sniff.md")
    out_path.write_text(md, encoding="utf-8")
    console.print()
    # Escape so paths like [/posts/1/comments] aren't parsed as Rich tags
    console.print(
        Panel.fit(
            escape(md) if verbose else _sniff_summary(md, out_path),
            border_style=BORDER,
            title=f"[{GOLD}] sniff 🐾 [/]",
            title_align="left",
        )
    )
    if md:
        if save_as:
            console.print(f"[{SUCCESS}]Huff! I did it. Where's my treat?[/] [dim]Saved to [bold]{out_path}[/].[/]")
        else:
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


def _sniff_summary(md: str, out_path: Path, preview_lines: int = 10) -> str:
    """Short sniff report: saved path, size, first heading, and a few lines (full text with --verbose)."""
    lines = [l for l in md.splitlines() if l.strip()]
    heading = next((l.lstrip("#").strip() for l in lines if l.startswith("#")), None)
    parts = [
        f"[dim]Saved to[/] [bold]{escape(str(out_path))}[/] [dim]({len(md):,} chars, {len(md.splitlines()):,} lines)[/]",
    ]
    if heading:
        parts.append(f"[dim]Title:[/] [bold]{escape(heading)}[/]")
    preview = "\n".join(l[:120] for l in lines[:preview_lines])
    parts.append("")
    parts.append(escape(preview))
    if len(lines) > preview_lines:
        parts.append(f"[dim]… {len(lines) - preview_lines} more lines. Use [bold]pug sniff --verbose[/] to print everything.[/]")
    return "\n".join(parts)


# All bone data and generated CLIs live under bones/<name>/ (bone_map, last_sniff, etc.) and bones/<name>/cli/ (generated output)
BONES_DIR = Path("bones")
CURRENT_BONE_FILE = BONES_DIR / "current"


BONE_NAME_RE = re.compile(r"^[a-z0-9_-]+$")


def _check_bone_name(name: str) -> None:
    """Allow only lowercase letters, digits, - and _ (no slashes, dots, or empty names). Exits 2 otherwise."""
    if not name:
        fail("Bone name is required. Example: [bold]pug bone my-api[/]", code=2)
    if name == "current" or not BONE_NAME_RE.match(name):
        suggestion = re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-")
        hint = f" Try [bold]{suggestion}[/]." if suggestion and suggestion != "current" and suggestion != name else ""
        fail(f"Invalid bone name {escape(repr(name))}: use lowercase letters, digits, - and _ only.{hint}", code=2)


def _require_bone() -> str:
    """Return the active bone, or exit 1 with a hint."""
    project = _get_current_bone()
    if not project:
        fail("No active bone. Run [bold]pug bone <name>[/] first (e.g. [bold]pug bone my-api[/]).")
    if not BONE_NAME_RE.match(project) or project == "current":
        fail(f"bones/current contains an invalid bone name {escape(repr(project))}. Run [bold]pug bone <name>[/] to fix it.")
    return project


def _get_current_bone() -> Optional[str]:
    """Return the active bone name from bones/current, or None."""
    if not CURRENT_BONE_FILE.exists():
        return None
    name = CURRENT_BONE_FILE.read_text(encoding="utf-8").strip()
    return name if name else None


def _set_current_bone(name: str) -> None:
    """Set the active bone; creates bones/ if needed."""
    BONES_DIR.mkdir(exist_ok=True)
    CURRENT_BONE_FILE.write_text(name.strip(), encoding="utf-8")


def _clear_current_bone() -> None:
    """Clear the active bone."""
    if CURRENT_BONE_FILE.exists():
        CURRENT_BONE_FILE.write_text("", encoding="utf-8")


def _pug_project_dir(project: str) -> Path:
    """Return bones/<project>/ (bone data: bone_map, last_sniff, bark_config; generated CLI is in cli/)."""
    return BONES_DIR / project.strip()


def cmd_chew(markdown_source: str = "-", merge: bool = False):
    """CHEW: AI reads Markdown and suggests CLI structure; show 'The Bone Map' table.
    Uses the active bone. If merge is True, merge new commands from the doc into the existing bone map.
    """
    project = _require_bone()
    pug_dir = _pug_project_dir(project)
    last_sniff_path = pug_dir / "last_sniff.md"
    bone_map_path = pug_dir / "bone_map.json"
    if not find_api_key()[0]:
        fail(NO_KEY_MESSAGE)

    if markdown_source == "-" or not markdown_source:
        if last_sniff_path.exists():
            md = last_sniff_path.read_text(encoding="utf-8")
        elif _stdin_is_interactive():
            fail(f"Nothing to chew for [bold]{project}[/]. Run [bold]pug sniff <url>[/] first, or pipe Markdown in: [bold]pug chew - < docs.md[/]")
        else:
            md = sys.stdin.read()
    else:
        path = Path(markdown_source)
        if not path.exists():
            fail(escape(f"File not found: {path}"))
        md = path.read_text()

    if not md.strip():
        fail(f"Nothing to chew: the Markdown is empty. Run [bold]pug sniff <url>[/] first.")

    do_merge = merge and bone_map_path.exists()
    if do_merge:
        existing = json.loads(bone_map_path.read_text(encoding="utf-8"))
        if not isinstance(existing, list):
            existing = []
        console.print("[italic]Pug is thinking... (Merging new bones into the map) 🦴[/]")
    else:
        console.print("[italic]Pug is thinking... (Heavy breathing noises)[/]")

    # Errors (bad key, rate limit, unknown model, unparseable reply) become one-line messages in main()
    if do_merge:
        plan = chew_merge(md, existing)
        config = None  # keep existing bark config
    else:
        plan, config = chew(md)

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
        console.print(f"[dim]Run [bold]pug bark[/] to verify (smell test) and generate the CLI + agent docs. 🦴[/]")
    console.print(f"[dim]Bone map: [bold]{_pug_project_dir(project)}/[/].[/]")
    console.print(f"[{SUCCESS}]Huff! I did it. Where's my treat?[/]")


def cmd_bark():
    """BARK: System compiler — smell test, then generate Go CLI + CLAUDE.md, SKILL.md. Uses the active bone."""
    _load_dotenv_into_env()
    project_name = _require_bone()
    pug_dir = _pug_project_dir(project_name)
    bone_map_path = pug_dir / "bone_map.json"
    if not bone_map_path.exists():
        fail(f"No Bone Map for [bold]{project_name}[/]. Run [bold]pug sniff <url>[/] then [bold]pug chew[/] first.")

    console.print()
    console.print(
        Panel.fit(
            f"[bold {GOLD}]🐶 Barking at the Bone Map...[/]\n\n"
            "[dim]Smell test → Go/Cobra, CLAUDE.md, SKILL.md (one folder per API). 🦴[/]",
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
        err_console.print(f"[{ERROR}]Bark! Smell test failed: {escape(err)}[/]", soft_wrap=True)
        if "422" in err:
            console.print("[dim]422 often means a required parameter is missing (e.g. ?q= for search APIs). Auth may still be correct.[/]")
        if "404" in err:
            console.print(
                f"[dim]The base URL ([bold]{escape(config['base_url'])}[/]) might be the docs site, not the API. "
                f"Set the real API base URL (e.g. https://api.example.com/v1) in [bold]{pug_dir / 'bark_config.json'}[/] or enter it below.[/]"
            )
        if not _stdin_is_interactive():
            return False  # no one to ask: fail (exit 1) instead of hanging on a prompt
        try:
            # 404 often means base URL is the docs page, not the API — offer to fix
            if "404" in err:
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
                "[2] I'll set the env var myself (enter var name only)  \\[n] Skip[/]"
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
        if not url:
            console.print("[dim]Smell test: [yellow]skipped[/] (no GET endpoint in the Bone Map)[/]")
        elif success:
            console.print(f"[dim]Smell test: [bold]GET[/] [dim]{url}[/] → [green]OK[/] 🦴[/]")
        else:
            console.print(f"[dim]Smell test: [bold]GET[/] [dim]{url}[/] → [red]failed[/][/]")

    out_dir = run_bark(
        bone_map_path,
        pug_dir,
        project_name,
        refine_chat_on_fail=refine_chat,
        on_smell_test=_on_smell_test,
    )
    cli_name = project_name
    bin_path = out_dir / "bin" / cli_name
    console.print(f"[dim]Generated [bold]{out_dir.resolve()}/[/]: Go source, CLAUDE.md, SKILL.md[/]")
    if not bin_path.exists():
        build_log = out_dir / "build.log"
        if shutil.which("go") is None:
            fail(
                f"Binary not built: [bold]go[/] is not on your PATH. Install Go from [bold]https://go.dev/dl/[/] "
                f"then run [bold]pug bark[/] again, or build by hand: [bold]cd {out_dir} && go build -o bin/{cli_name} .[/]"
            )
        hint = f"See [bold]{build_log}[/] for the compiler errors." if build_log.exists() else "No build.log was written."
        fail(f"The Go build failed. {hint} Retry by hand: [bold]cd {out_dir} && go build -o bin/{cli_name} .[/]")
    console.print(f"[{SUCCESS}]Huff! I did it. Where's my treat?[/]")
    try:
        example = example_command(json.loads(bone_map_path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        example = None
    if example:
        console.print(f"[dim]Try it: [bold]pug run {escape(example)}[/] (loads .env + base URL + auth for you). All commands: [bold]pug run {cli_name} --help[/].[/]")
    else:
        console.print(f"[dim]Try it: [bold]pug run {cli_name} --help[/].[/]")
    console.print(f"[dim]To add or change commands later: [bold]pug refine[/] then [bold]pug bark[/]. 🦴[/]")


def cmd_refine():
    """REFINE: Chat with Pug (LLM) to tweak the Bone Map until ready; then run pug bark. Uses the active bone."""
    project = _require_bone()
    pug_dir = _pug_project_dir(project)
    bone_map_path = pug_dir / "bone_map.json"
    if not bone_map_path.exists():
        fail(f"No Bone Map for [bold]{project}[/]. Run [bold]pug sniff <url>[/] then [bold]pug chew[/] first.")
    try:
        bone_map = json.loads(bone_map_path.read_text(encoding="utf-8"))
    except ValueError as e:
        fail(escape(f"{bone_map_path} is not valid JSON ({e}). Fix it or run pug chew again."))
    if not isinstance(bone_map, list):
        fail(escape(f"{bone_map_path} must be a JSON array."))
    if not find_api_key()[0]:
        fail(NO_KEY_MESSAGE)
    console.print()
    console.print(
        Panel.fit(
            f"[bold {GOLD}]🐶 Refine the Bone Map 🦴[/]\n\n"
            f"[dim]Project [bold]{project}[/]: [bold]{_pug_project_dir(project)}/[/]\n"
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
        # API errors exit with a one-line message (main()); the Bone Map is saved after every turn
        reply, updated = refine_turn(user_input, history, bone_map)
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


def cmd_run(project_or_first_arg: Optional[str], run_args: list[str]) -> Optional[int]:
    """Run a generated CLI. If project is omitted, use active bone. Pass-through args go to the CLI.
    Returns the generated CLI's exit code (None if it was not started)."""
    pug_root = Path.cwd()
    # If first token is a bone name (bones/<name>/cli exists), use it; else use current bone and treat token as first CLI arg
    project_name = None
    args = list(run_args)
    if project_or_first_arg:
        cli_dir = BONES_DIR / project_or_first_arg / "cli"
        if BONE_NAME_RE.match(project_or_first_arg) and cli_dir.is_dir():
            project_name = project_or_first_arg
        else:
            project_name = _get_current_bone()
            args = [project_or_first_arg] + args
    if not project_name:
        project_name = _get_current_bone()
    if not project_name:
        fail("No active bone and no project given. Run [bold]pug bone <name>[/] or [bold]pug run <project> \\[args...][/].")
    if not BONE_NAME_RE.match(project_name) or project_name == "current":
        fail(f"bones/current contains an invalid bone name {escape(repr(project_name))}. Run [bold]pug bone <name>[/] to fix it.")
    project_dir = BONES_DIR / project_name / "cli"
    if not project_dir.is_dir():
        fail(f"No generated CLI for [bold]{project_name}[/]. Run [bold]pug bark[/] first.")
    config_path = project_dir / ".pug-config.json"
    if config_path.exists():
        config = json.loads(config_path.read_text(encoding="utf-8"))
    else:
        bark_config = BONES_DIR / project_name / "bark_config.json"
        if bark_config.exists():
            config = json.loads(bark_config.read_text(encoding="utf-8"))
            env_prefix = project_name.upper().replace("-", "_")
            config["env_prefix"] = env_prefix
            config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
        else:
            fail(f"[bold]{project_name}[/] has no .pug-config.json. Re-run [bold]pug bark[/].")
    bin_path = (project_dir / "bin" / project_name).resolve()
    if not bin_path.exists():
        fail(f"No binary at [bold]{bin_path}[/]. Run [bold]pug bark[/] (needs Go) to build it.")
    env = _env_for_run(pug_root, config)
    cmd = [str(bin_path)] + args
    try:
        return subprocess.run(cmd, env=env, cwd=str(project_dir)).returncode
    except KeyboardInterrupt:
        return 130


def main():
    parser = argparse.ArgumentParser(
        prog="pug",
        description="🐶 PUG — The Stubborn API Scraper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"pug {VERSION}")
    parser.add_argument("--debug", action="store_true", help="Show full tracebacks on errors (or set PUG_DEBUG=1)")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # init: save Anthropic API key to .env
    init_parser = subparsers.add_parser(
        "init",
        help="🐾 Set up API key (validated, then saved to .env)",
        description="Validate your Anthropic API key and save it to ./.env. With a key already set (ANTHROPIC_API_KEY or .env), "
        "checks that key instead. Pipe a key in for non-interactive use: echo $KEY | pug init --force",
    )
    init_parser.add_argument("--force", action="store_true", help="Ask for a new key even if one is already set, and replace it")

    # bone: create/switch/exit active project (all other commands use this)
    bone_parser = subparsers.add_parser(
        "bone",
        help="🦴 Create or switch to a bone (project). Sniff/chew/refine/bark use the active bone.",
        description="Create or switch to a bone (project) under bones/<name>/. Names: lowercase letters, digits, - and _.",
    )
    bone_parser.add_argument("name", nargs="?", default=None, help="Bone name (e.g. my-api); omit to list, or use --exit to clear")
    bone_parser.add_argument("--exit", dest="exit_bone", action="store_true", help="Clear active bone (exit bone)")

    # sniff: uses active bone
    sniff_parser = subparsers.add_parser(
        "sniff",
        help="🐾 Sniff a URL (scrape and clean to Markdown)",
        description="Load an API docs URL in headless Chromium, strip nav/footer, and save it as Markdown under bones/<bone>/.",
    )
    sniff_parser.add_argument("url", nargs="?", default=None, help="URL to sniff (omit when using --resniff)")
    sniff_parser.add_argument("--resniff", action="store_true", help="Re-fetch the last sniffed URL for this bone (no URL needed)")
    sniff_parser.add_argument("--save-as", metavar="name", help="Save to bones/<bone>/sniff_<name>.md instead of last_sniff.md (for adding from another URL)")
    sniff_parser.add_argument("--verbose", action="store_true", help="Print the full sniffed Markdown instead of a short summary")

    # chew: uses active bone
    chew_parser = subparsers.add_parser(
        "chew",
        help="🐾 CHEW: suggest CLI from Markdown (query params → flags)",
        description="Ask Claude to turn the sniffed Markdown into a Bone Map (commands, paths, flags). Needs an Anthropic API key.",
    )
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

    # bark: uses active bone
    subparsers.add_parser(
        "bark",
        help="🐾 BARK: generate Go CLI + agent docs (uses active bone)",
        description="Smell-test the API (one real GET), then generate the Go CLI, CLAUDE.md and SKILL.md in bones/<bone>/cli/ and build the binary.",
    )

    # refine: uses active bone
    subparsers.add_parser(
        "refine",
        help="🐾 REFINE: chat with Pug to improve Bone Map, then run bark when ready",
        description="Chat with Claude to add, remove or change commands in the Bone Map. Say done when ready, then run pug bark.",
    )

    # run: optional project (defaults to active bone); rest is pass-through to the CLI
    run_parser = subparsers.add_parser(
        "run",
        help="🐾 RUN: run a generated CLI (loads .env + config); omit project to use active bone",
        description="Run a generated CLI. If you omit the project name, the active bone is used. Everything after is passed to that CLI (e.g. pug run get-post --id 1).",
        add_help=False,
    )
    run_parser.add_argument("project", nargs="?", default=None, help="Project name (optional; uses active bone if omitted)")

    args, unknown = parser.parse_known_args()
    debug = bool(args.debug) or os.environ.get("PUG_DEBUG", "").strip() not in ("", "0")
    if args.command != "run":
        if "--debug" in unknown:
            unknown = [u for u in unknown if u != "--debug"]
            debug = True
        if unknown:
            parser.error(f"unrecognized arguments: {' '.join(unknown)}")  # exits 2

    if args.command == "run":
        # Keep stdout for the generated CLI's response body (so `pug run ... | jq` works):
        # Pug's banner and status lines go to stderr.
        global console
        console = Console(stderr=True)

    try:
        _dispatch(args, unknown, run_parser)
    except (SystemExit, KeyboardInterrupt) as e:
        if isinstance(e, KeyboardInterrupt):
            err_console.print("\n[dim]Interrupted.[/]")
            raise SystemExit(130)
        raise
    except Exception as e:
        if debug:
            traceback.print_exc()
        message = friendly_error(e, model=get_model())
        if message is None:
            if isinstance(e, (ValueError, RuntimeError, OSError)) and str(e):
                message = str(e)
            else:
                message = f"Unexpected error: {type(e).__name__}: {e}"
            if not debug:
                message += " (re-run with --debug or PUG_DEBUG=1 for the full traceback)"
        fail(escape(message))


def _dispatch(args, unknown, run_parser):
    welcome(show_ascii_art=(args.command == "init"))
    if args.command in ("sniff", "chew", "refine", "bark", "run"):
        _print_bone_status()

    if args.command == "init":
        cmd_init(force=getattr(args, "force", False))
    elif args.command == "bone":
        cmd_bone(name=getattr(args, "name", None), exit_bone=getattr(args, "exit_bone", False))
    elif args.command == "sniff":
        cmd_sniff(
            url=args.url,
            save_as=getattr(args, "save_as", None),
            resniff=getattr(args, "resniff", False),
            verbose=getattr(args, "verbose", False),
        )
    elif args.command == "chew":
        cmd_chew(markdown_source=args.source, merge=getattr(args, "merge", False))
    elif args.command == "bark":
        cmd_bark()
    elif args.command == "refine":
        cmd_refine()
    elif args.command == "run":
        # `pug run --help` / `-h` with nothing else shows Pug's own run usage;
        # `pug run <command> --help` is forwarded to the generated CLI.
        project_arg = getattr(args, "project", None)
        if (project_arg in ("--help", "-h") and not unknown) or (project_arg is None and unknown in (["--help"], ["-h"])):
            Console().print(escape(run_parser.format_help()))
            return
        code = cmd_run(getattr(args, "project", None), unknown or [])
        if code:
            sys.exit(code)
    elif args.command is None:
        console.print(f"[dim]Use [bold {GOLD}]pug init[/] to set your API key, then [bold]pug bone <name>[/] to create a project. 🐶[/]")
        console.print("[dim]Commands: bone, sniff, chew, refine, bark, run. See [bold]pug --help[/].[/]")


if __name__ == "__main__":
    main()
