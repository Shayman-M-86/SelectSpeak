"""
setup_project.py

Usage:
  python setup_project.py               # prompts for the name
  python setup_project.py --name myproj
  python setup_project.py --name myproj --dry-run
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

TOKEN = "input_name"

FILES_TO_EDIT = [
    Path("pyproject.toml"),
    Path("README.md"),
    # We'll also edit the .code-workspace file's contents after we locate/rename it.
]

VSCODE_DIR = Path(".vscode")
WORKSPACE_BASENAME = f"{TOKEN}.code-workspace"  # template filename we expect


def validate_project_name(name: str) -> str:
    """
    Keep it simple: letters, numbers, dashes, underscores, dots allowed.
    No spaces, must start with alnum.
    """
    name = name.strip()
    if not name:
        raise ValueError("Project name cannot be empty.")
    if " " in name:
        raise ValueError("Project name cannot contain spaces.")
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*$", name):
        raise ValueError(
            "Invalid project name. Use letters/numbers and . _ - ;"
            " must start with a letter/number."
        )
    return name


def replace_token_in_text(text: str, token: str, replacement: str) -> str:
    # Exact literal replacement (case-sensitive)
    return text.replace(token, replacement)


def replace_token_in_file(
    path: Path, token: str, replacement: str, dry_run: bool = False
) -> bool:
    if not path.exists():
        print(f"  - Skipping missing file: {path}")
        return False
    original = path.read_text(encoding="utf-8", errors="replace")
    updated = replace_token_in_text(original, token, replacement)
    if updated != original:
        if dry_run:
            print(f"  - Would update: {path}")
        else:
            path.write_text(updated, encoding="utf-8")
            print(f"  - Updated: {path}")
        return True
    else:
        print(f"  - No changes needed: {path}")
        return False


def update_pyproject_name_line(
    path: Path, new_name: str, dry_run: bool = False
) -> bool:
    """
    Optional helper: If the template didn't use TOKEN on the name line,
    also try to rewrite the [project] name line robustly.
    """
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8", errors="replace")

    # Try to replace the name= line within the [project] table
    # This is a conservative regex: it finds name="...".
    def repl(m):
        return f'{m.group(1)}"{new_name}"'

    updated = text
    # Limit to lines that look like: name = "something"
    updated = re.sub(r'^(\s*name\s*=\s*)"(.*?)"', repl, updated, flags=re.MULTILINE)

    if updated != text:
        if dry_run:
            print(f"  - Would normalize project.name in: {path}")
        else:
            path.write_text(updated, encoding="utf-8")
            print(f"  - Normalized project.name in: {path}")
        return True
    return False


def find_or_expect_workspace_file(vscode_dir: Path, expected_name: str) -> Path | None:
    """
    Prefer the expected template name. If not present, try to find a .code-workspace
    that still contains the TOKEN in its filename. Otherwise return None.
    """
    candidate = vscode_dir / expected_name
    if candidate.exists():
        return candidate

    if not vscode_dir.exists():
        return None

    for p in vscode_dir.glob("*.code-workspace"):
        if TOKEN in p.name:
            return p

    return None


def rename_workspace_file(
    old_path: Path, new_project_name: str, dry_run: bool = False
) -> Path:
    new_path = old_path.with_name(f"{new_project_name}.code-workspace")
    if old_path == new_path:
        print(f"  - Workspace filename already correct: {old_path.name}")
        return old_path

    if dry_run:
        print(f"  - Would rename workspace: {old_path} -> {new_path}")
    else:
        # Ensure target doesn't exist or is same file
        if new_path.exists():
            print(f"  - Removing existing workspace to replace: {new_path}")
            new_path.unlink()
        old_path.rename(new_path)
        print(f"  - Renamed workspace: {old_path} -> {new_path}")
    return new_path


def run_uv_sync(dry_run: bool = False) -> int:
    print("\nRunning `uv sync`...")
    uv = shutil.which("uv")
    if uv is None:
        print(
            "  ! Could not find `uv` on PATH. Install it first: https://docs.astral.sh/uv/"
        )
        return 127
    cmd = [uv, "sync"]
    print(f"  > {' '.join(cmd)}")
    if dry_run:
        print("  - Dry-run: not executing.")
        return 0
    proc = subprocess.run(cmd)
    return proc.returncode


def open_vscode(workspace_file: Path, dry_run: bool = False) -> int:
    """
    Try to launch VS Code with the given workspace.
    """
    print(f"\nOpening VS Code workspace: {workspace_file}")
    code = shutil.which("code")
    if code is None:
        print(
            "! Could not find `code` on PATH. Is VS Code installed and"
            " `code` command enabled?"
        )
        print(
            "    See: https://code.visualstudio.com/docs/setup/setup-overview#_launching-from-command-line"
        )
        return 127

    cmd = [code, str(workspace_file)]
    print(f"  > {' '.join(cmd)}")
    if dry_run:
        print("  - Dry-run: not launching VS Code.")
        return 0
    return subprocess.call(cmd)


def main():
    parser = argparse.ArgumentParser(
        description="Set up a templated project by replacing 'input_name'"
        " and syncing deps with `uv sync`."
    )
    parser.add_argument("--name", help="Project name (if omitted, you'll be prompted).")
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would change without writing."
    )
    parser.add_argument(
        "--no-vscode", action="store_true", help="Do not open VS Code at the end."
    )
    args = parser.parse_args()

    project_root = Path.cwd()
    print(f"Project root: {project_root}")

    if args.name:
        project_name = args.name
    else:
        project_name = input("Enter your project name: ").strip()

    try:
        project_name = validate_project_name(project_name)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    print(f"\nUsing project name: {project_name}\n")

    # 1) Replace TOKEN in the known files
    any_changes = False
    for f in FILES_TO_EDIT:
        any_changes |= replace_token_in_file(
            f, TOKEN, project_name, dry_run=args.dry_run
        )

    # 2) Normalize pyproject name line even if template didn't use TOKEN there
    pyproject = Path("pyproject.toml")
    if pyproject.exists():
        any_changes |= update_pyproject_name_line(
            pyproject, project_name, dry_run=args.dry_run
        )

    # 3) Handle the .vscode workspace file rename + content replacement
    ws_old = find_or_expect_workspace_file(VSCODE_DIR, WORKSPACE_BASENAME)
    if ws_old is None:
        print("  - No .vscode workspace template found to rename. (Skipping)")
    else:
        ws_new = rename_workspace_file(ws_old, project_name, dry_run=args.dry_run)
        # Replace token within the workspace file too
        any_changes |= replace_token_in_file(
            ws_new, TOKEN, project_name, dry_run=args.dry_run
        )

    if args.dry_run:
        print("\nDry-run complete. No files were modified.")
        print("Everything look good? Run again without --dry-run to apply changes.")
        return

    # 4) Finally, run `uv sync`
    code = run_uv_sync(dry_run=False)
    if code != 0:
        print(f"`uv sync` exited with status {code}.")
        sys.exit(code)

    # 5) Open VS Code workspace if we created/renamed it
    if not args.no_vscode and ws_old is not None:
        ws_new = ws_old.with_name(f"{project_name}.code-workspace")
        if ws_new.exists():
            open_vscode(ws_new, dry_run=args.dry_run)

    print("\n✅ Done!")
    if not any_changes:
        print(
            "(Note: No token replacements were needed."
            " Template might already be renamed.)"
        )


if __name__ == "__main__":
    main()
