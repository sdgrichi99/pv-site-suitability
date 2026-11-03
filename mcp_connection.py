import subprocess
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

ROOT = Path(__file__).resolve().parent
DBT = Path(sys.executable).parent / "dbt.exe"
ALLOWED_DBT = {"parse", "compile", "run", "test", "build", "debug", "ls"}
SKIP_DIRS = {".venv", ".git", "target", "dbt_packages", "logs", "__pycache__"}

mcp = FastMCP("duck_db_trial")


def _safe(rel: str) -> Path:
    p = (ROOT / rel).resolve()
    if p != ROOT and ROOT not in p.parents:
        raise ValueError("Percorso fuori dalla cartella del progetto")
    return p


@mcp.tool()
def list_files(subdir: str = ".") -> str:
    """Elenca ricorsivamente i file del progetto (esclude .venv, .git, target)."""
    base = _safe(subdir)
    out = []
    for p in sorted(base.rglob("*")):
        if p.is_file() and not (set(p.relative_to(ROOT).parts) & SKIP_DIRS):
            out.append(str(p.relative_to(ROOT)))
    return "\n".join(out)


@mcp.tool()
def read_file(path: str) -> str:
    """Legge un file di testo del progetto."""
    return _safe(path).read_text(encoding="utf-8")


@mcp.tool()
def write_file(path: str, content: str) -> str:
    """Scrive (sovrascrive) un file di testo del progetto."""
    p = _safe(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"Scritto {path}"


@mcp.tool()
def dbt(command: str, args: str = "") -> str:
    """Esegue un comando dbt consentito (parse, compile, run, test, build, debug, ls).
    Esempio: command='build', args='--select silver'."""
    if command not in ALLOWED_DBT:
        return f"Comando non consentito. Ammessi: {sorted(ALLOWED_DBT)}"
    r = subprocess.run(
        [str(DBT), command, *args.split()],
        cwd=ROOT, capture_output=True, text=True, timeout=900,
    )
    return (r.stdout + r.stderr)[-8000:]


if __name__ == "__main__":
    mcp.run()