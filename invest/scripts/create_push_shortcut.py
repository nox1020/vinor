"""Create Desktop shortcut for invest_push.bat (V+ auto push)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _ps_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    bat = root / "invest_push.bat"
    desktop = Path.home() / "OneDrive" / "Desktop"
    if not desktop.exists():
        desktop = Path.home() / "Desktop"
    lnk = desktop / "V+.bat.lnk"

    if not bat.exists():
        print(f"Missing: {bat}", file=sys.stderr)
        return 1

    ps = f"""
$Wsh = New-Object -ComObject WScript.Shell
$sc = $Wsh.CreateShortcut({_ps_literal(str(lnk))})
$sc.TargetPath = {_ps_literal(str(bat))}
$sc.WorkingDirectory = {_ps_literal(str(root))}
$sc.Description = 'V+ auto commit and push to GitHub'
$sc.Save()
Write-Host "Shortcut ready:" {_ps_literal(str(lnk))}
"""
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
