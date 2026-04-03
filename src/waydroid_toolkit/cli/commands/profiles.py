"""wdt profiles — manage Waydroid image profiles and Incus profiles.

Image profiles (system.img + vendor.img pairs):
  wdt profiles list              List available image profiles
  wdt profiles show <name>       Show details for an image profile
  wdt profiles switch <name>     Switch the active image profile
  wdt profiles active            Print the currently active image profile
  wdt profiles add <path>        Register a directory as a named image profile

Incus profiles (YAML config applied to containers):
  wdt profiles incus list              List available Incus profile files
  wdt profiles incus show <name>       Print a profile's YAML
  wdt profiles incus install [--all] [name]  Install profile(s) into Incus
  wdt profiles incus diff              Compare local files with Incus
  wdt profiles incus apply <ct> <name> Apply a profile to a container
  wdt profiles incus remove <ct> <name> Remove a profile from a container
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from waydroid_toolkit.modules.images import (
    get_active_profile,
    scan_profiles,
    switch_profile,
)

console = Console()

_DEFAULT_BASE = Path.home() / "waydroid-images"

# Search order for bundled Incus profile YAML files
_INCUS_PROFILE_DIRS = [
    Path(__file__).parents[4] / "data" / "profiles",
    Path.home() / ".local" / "share" / "waydroid-toolkit" / "profiles",
    Path("/usr/local/share/waydroid-toolkit/profiles"),
    Path("/usr/share/waydroid-toolkit/profiles"),
]


def _find_incus_profile_dir() -> Path:
    for d in _INCUS_PROFILE_DIRS:
        if d.is_dir():
            return d
    raise RuntimeError(
        "No Incus profile directory found. "
        "Expected one of: " + ", ".join(str(d) for d in _INCUS_PROFILE_DIRS)
    )


def _find_incus_profile_file(name: str) -> Path:
    for d in _INCUS_PROFILE_DIRS:
        f = d / f"{name}.yaml"
        if f.exists():
            return f
    raise FileNotFoundError(f"Incus profile not found: {name}")


def _require_incus() -> None:
    if not shutil.which("incus"):
        console.print("[red]incus is not installed or not in PATH.[/red]")
        raise SystemExit(1)


def _install_one(name: str, path: Path) -> None:
    exists = subprocess.run(
        ["incus", "profile", "show", name],
        capture_output=True,
    ).returncode == 0
    if exists:
        with path.open() as fh:
            subprocess.run(["incus", "profile", "edit", name], stdin=fh, check=True)
        console.print(f"  [cyan]updated[/cyan] : {name}")
    else:
        subprocess.run(["incus", "profile", "create", name], check=True)
        with path.open() as fh:
            subprocess.run(["incus", "profile", "edit", name], stdin=fh, check=True)
        console.print(f"  [green]created[/green] : {name}")


@click.group("profiles")
def cmd() -> None:
    """Manage Waydroid image profiles (system.img + vendor.img pairs)."""


@cmd.command("list")
@click.option("--base", default=None,
              help="Directory to scan for profiles (default: ~/waydroid-images).")
def profiles_list(base: str | None) -> None:
    """List available image profiles."""
    scan_dir = Path(base) if base else _DEFAULT_BASE
    profiles = scan_profiles(scan_dir)
    active = get_active_profile()

    if not profiles:
        console.print(f"[yellow]No profiles found under {scan_dir}[/yellow]")
        console.print("Place system.img + vendor.img pairs in subdirectories there.")
        console.print("Or specify a different base: wdt profiles list --base <dir>")
        return

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("NAME", style="cyan")
    table.add_column("PATH")
    table.add_column("ACTIVE")
    table.add_column("SIZE")

    for p in profiles:
        is_active = active and str(p.path) in active
        # Sum system.img + vendor.img sizes
        size_mb = 0
        for img in ("system.img", "vendor.img"):
            f = p.path / img
            if f.exists():
                size_mb += f.stat().st_size // (1024 * 1024)
        size_str = f"{size_mb} MiB" if size_mb else "?"
        table.add_row(
            p.name,
            str(p.path),
            "[green]✓[/green]" if is_active else "",
            size_str,
        )

    console.print(table)
    console.print(f"\n{len(profiles)} profile(s) found under {scan_dir}")


@cmd.command("show")
@click.argument("name")
@click.option("--base", default=None, help="Directory to scan for profiles.")
def profiles_show(name: str, base: str | None) -> None:
    """Show details for a named profile."""
    scan_dir = Path(base) if base else _DEFAULT_BASE
    profiles = scan_profiles(scan_dir)
    match = next((p for p in profiles if p.name == name), None)

    if match is None:
        console.print(f"[red]Profile '{name}' not found.[/red]")
        console.print("List profiles with: wdt profiles list")
        raise SystemExit(1)

    active = get_active_profile()
    is_active = active and str(match.path) in active

    console.print(f"[bold]Name:[/bold]   {match.name}")
    console.print(f"[bold]Path:[/bold]   {match.path}")
    console.print(f"[bold]Active:[/bold] {'yes' if is_active else 'no'}")

    for img in ("system.img", "vendor.img"):
        f = match.path / img
        if f.exists():
            size_mb = f.stat().st_size // (1024 * 1024)
            console.print(f"[bold]{img}:[/bold] {size_mb} MiB")
        else:
            console.print(f"[bold]{img}:[/bold] [yellow]missing[/yellow]")


@cmd.command("active")
def profiles_active() -> None:
    """Print the currently active profile path."""
    active = get_active_profile()
    if active:
        console.print(active)
    else:
        console.print("[yellow]No active profile set.[/yellow]")
        raise SystemExit(1)


@cmd.command("switch")
@click.argument("name")
@click.option("--base", default=None, help="Directory to scan for profiles.")
def profiles_switch(name: str, base: str | None) -> None:
    """Switch the active Waydroid image profile to NAME.

    Waydroid must be stopped before switching profiles.

    \b
    Examples:
      wdt profiles switch vanilla
      wdt profiles switch gapps --base ~/my-images
    """
    scan_dir = Path(base) if base else _DEFAULT_BASE
    profiles = scan_profiles(scan_dir)
    match = next((p for p in profiles if p.name == name), None)

    if match is None:
        console.print(f"[red]Profile '{name}' not found.[/red]")
        console.print("List profiles with: wdt profiles list")
        raise SystemExit(1)

    console.print(f"Switching to profile [bold]{name}[/bold]...")
    try:
        switch_profile(
            match,
            progress=lambda msg: console.print(f"  [cyan]→[/cyan] {msg}"),
        )
    except Exception as exc:
        console.print(f"[red]Switch failed: {exc}[/red]")
        raise SystemExit(1) from exc

    console.print(f"[green]Active profile: {name}[/green]")
    console.print(f"Path: {match.path}")


@cmd.command("add")
@click.argument("path")
@click.option("--name", "-n", default="",
              help="Profile name (default: directory basename).")
def profiles_add(path: str, name: str) -> None:  # noqa: A002
    """Register PATH as a named profile by symlinking it under ~/waydroid-images.

    PATH must contain system.img and vendor.img.

    \b
    Examples:
      wdt profiles add /mnt/external/waydroid-gapps
      wdt profiles add /mnt/external/waydroid-gapps --name gapps
    """
    src = Path(path).resolve()
    if not src.is_dir():
        console.print(f"[red]Not a directory: {src}[/red]")
        raise SystemExit(1)

    missing = [img for img in ("system.img", "vendor.img") if not (src / img).exists()]
    if missing:
        console.print(f"[yellow]Warning: missing in {src}: {', '.join(missing)}[/yellow]")

    profile_name = name or src.name
    dest = _DEFAULT_BASE / profile_name

    if dest.exists() or dest.is_symlink():
        console.print(f"[yellow]Profile '{profile_name}' already exists at {dest}[/yellow]")
        console.print("Remove it first or choose a different name with --name.")
        raise SystemExit(1)

    _DEFAULT_BASE.mkdir(parents=True, exist_ok=True)
    dest.symlink_to(src)
    console.print(f"[green]Registered profile '{profile_name}'[/green]")
    console.print(f"  {dest} → {src}")
    console.print(f"Switch with: wdt profiles switch {profile_name}")


# ── incus subgroup ────────────────────────────────────────────────────────────

@cmd.group("incus")
def profiles_incus() -> None:
    """Manage Incus profiles for Waydroid containers."""


@profiles_incus.command("list")
def incus_list() -> None:
    """List available Incus profile files."""
    try:
        profile_dir = _find_incus_profile_dir()
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        raise SystemExit(1)

    files = sorted(profile_dir.glob("*.yaml"))
    if not files:
        console.print(f"[yellow]No profile files found in {profile_dir}[/yellow]")
        return

    console.print(f"Available profiles ({profile_dir}):\n")
    for f in files:
        pname = f.stem
        desc = ""
        for line in f.read_text().splitlines():
            if line.startswith("description:"):
                desc = line.split(":", 1)[-1].strip().strip('"')
                break
        if desc:
            console.print(f"  [cyan]{pname:<30}[/cyan]  {desc}")
        else:
            console.print(f"  [cyan]{pname}[/cyan]")

    console.print("\nInstall with: wdt profiles incus install")


@profiles_incus.command("show")
@click.argument("name")
def incus_show(name: str) -> None:
    """Print the YAML for a named Incus profile."""
    try:
        path = _find_incus_profile_file(name)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise SystemExit(1)
    console.print(path.read_text(), end="")


@profiles_incus.command("install")
@click.argument("names", nargs=-1)
@click.option("--all", "install_all", is_flag=True,
              help="Install all available profiles.")
def incus_install(names: tuple[str, ...], install_all: bool) -> None:
    """Install Incus profile(s) into the local Incus daemon.

    With no arguments, installs all profiles found in the profile directory.
    """
    _require_incus()
    try:
        profile_dir = _find_incus_profile_dir()
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        raise SystemExit(1)

    if install_all or not names:
        files = sorted(profile_dir.glob("*.yaml"))
        if not files:
            console.print(f"[yellow]No profile files found in {profile_dir}[/yellow]")
            return
        for f in files:
            _install_one(f.stem, f)
    else:
        for name in names:
            try:
                path = _find_incus_profile_file(name)
            except FileNotFoundError as e:
                console.print(f"[red]{e}[/red]")
                raise SystemExit(1)
            _install_one(name, path)


@profiles_incus.command("diff")
def incus_diff() -> None:
    """Compare local profile files with what is installed in Incus."""
    _require_incus()
    try:
        profile_dir = _find_incus_profile_dir()
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        raise SystemExit(1)

    files = sorted(profile_dir.glob("*.yaml"))
    if not files:
        console.print(f"[yellow]No profile files found in {profile_dir}[/yellow]")
        return

    for f in files:
        pname = f.stem
        result = subprocess.run(
            ["incus", "profile", "show", pname],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            console.print(
                f"  [yellow]{pname}[/yellow]: not installed in Incus "
                f"(run: wdt profiles incus install {pname})"
            )
            continue

        import difflib
        incus_lines = result.stdout.splitlines(keepends=True)
        local_lines = f.read_text().splitlines(keepends=True)
        diff = list(difflib.unified_diff(
            incus_lines, local_lines,
            fromfile=f"incus:{pname}", tofile=f"local:{f}",
        ))
        if diff:
            console.print(f"[bold]--- {pname} (incus vs local) ---[/bold]")
            for line in diff:
                line = line.rstrip("\n")
                if line.startswith("+"):
                    console.print(f"[green]{line}[/green]")
                elif line.startswith("-"):
                    console.print(f"[red]{line}[/red]")
                else:
                    console.print(line)
        else:
            console.print(f"  [green]{pname}[/green]: in sync")


@profiles_incus.command("apply")
@click.argument("container")
@click.argument("profile")
def incus_apply(container: str, profile: str) -> None:
    """Apply PROFILE to CONTAINER."""
    _require_incus()
    exists = subprocess.run(
        ["incus", "profile", "show", profile],
        capture_output=True,
    ).returncode == 0
    if not exists:
        console.print(
            f"[red]Profile '{profile}' not installed in Incus.[/red]\n"
            f"Run: wdt profiles incus install {profile}"
        )
        raise SystemExit(1)
    subprocess.run(["incus", "profile", "add", container, profile], check=True)
    console.print(f"[green]Applied profile '{profile}' to '{container}'[/green]")


@profiles_incus.command("remove")
@click.argument("container")
@click.argument("profile")
def incus_remove(container: str, profile: str) -> None:
    """Remove PROFILE from CONTAINER."""
    _require_incus()
    subprocess.run(["incus", "profile", "remove", container, profile], check=True)
    console.print(f"[green]Removed profile '{profile}' from '{container}'[/green]")
