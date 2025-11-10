# logger.py

"""
runtime.log : reçoit tous les info(), log() et warning(), que visual_log soit True ou False.

error.log : reçoit tous les error().

git.log : reçoit tous les git().

visual_log (set_verbose(True/False)) ne contrôle plus que l’affichage en console, pas l’écriture disque.
"""

from pathlib import Path
from datetime import datetime
import threading

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

RUNTIME_LOG = LOG_DIR / "runtime.log"
ERROR_LOG = LOG_DIR / "error.log"
GIT_LOG = LOG_DIR / "git.log"

_VERBOSE = False
_lock = threading.Lock()


def set_verbose(enabled: bool) -> None:
    """Active ou désactive le mode verbeux (visual_log=True/False)."""
    global _VERBOSE
    _VERBOSE = bool(enabled)
    

def _write_log(file_path: Path, msg: str) -> None:
    """Écrit un message horodaté dans le fichier spécifié."""
    with _lock:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] {msg}\n"
        file_path.parent.mkdir(exist_ok=True)
        with file_path.open("a", encoding="utf-8") as f:
            f.write(line)


def info(msg: str) -> None:
    """Log normal (uniquement si verbose)."""
    if _VERBOSE:
        _write_log(RUNTIME_LOG, msg)


def log(msg: str) -> None:
    """Alias historique vers info(), pour compatibilité."""
    info(msg)


def error(msg: str) -> None:
    """Log toujours, même si pas verbeux."""
    _write_log(ERROR_LOG, msg)


def git(msg: str) -> None:
    """Log des commandes git (stdout, stderr)."""
    _write_log(GIT_LOG, msg)
