"""Create/update Invest.lnk launcher with app icon.

Prefers project .venv pythonw so the shortcut matches pip-installed deps.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def _pythonw(root: Path) -> Path:
    venv = root / ".venv" / "Scripts" / "pythonw.exe"
    if venv.exists():
        return venv
    found = shutil.which("pythonw")
    if found:
        return Path(found)
    raise FileNotFoundError(
        "pythonw یافت نشد. ابتدا .venv را بسازید و وابستگی‌ها را نصب کنید."
    )


def _ps_literal(value: str) -> str:
    """Single-quoted PowerShell string (safe for paths with spaces)."""
    return "'" + value.replace("'", "''") + "'"


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    ico = root / "assets" / "app.ico"
    lnk = root / "V+.lnk"
    main_py = root / "main.py"
    if not ico.exists():
        print(f"Missing icon: {ico}", file=sys.stderr)
        return 1
    if not main_py.exists():
        print(f"Missing entry: {main_py}", file=sys.stderr)
        return 1

    try:
        pyw = _pythonw(root)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1

    ps = f"""
$Wsh = New-Object -ComObject WScript.Shell
$sc = $Wsh.CreateShortcut({_ps_literal(str(lnk))})
$sc.TargetPath = {_ps_literal(str(pyw))}
$sc.Arguments = {_ps_literal(f'"{main_py}"')}
$sc.WorkingDirectory = {_ps_literal(str(root))}
$sc.IconLocation = {_ps_literal(f"{ico},0")}
$sc.Description = 'V+'
$sc.Save()
Write-Host "Shortcut ready:" {_ps_literal(str(lnk))}
Write-Host "Target:" $sc.TargetPath
"""
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
