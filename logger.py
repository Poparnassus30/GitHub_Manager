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
import sys
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

RUNTIME_LOG = LOG_DIR / "runtime.log"
ERROR_LOG = LOG_DIR / "error.log"
GIT_LOG = LOG_DIR / "git.log"

_VERBOSE = False
_lock = threading.Lock()

# Console Rich optionnelle (par ex. live.console)
_CONSOLE = None


def set_verbose(enabled: bool) -> None:
    """Active ou désactive le mode verbeux (visual_log=True/False)."""
    global _VERBOSE
    _VERBOSE = bool(enabled)
    
def _safe_print(line: str, style: str | None = None) -> None:
    """
    Affiche un message :
    - via Rich (console.log) si une console a été fournie,
    - sinon ne fait rien (plus d'impression brute dans sys.__stdout__).
    """
    try:
        if _CONSOLE is not None:
            if style:
                _CONSOLE.log(line, style=style)
            else:
                _CONSOLE.log(line)
        # Si pas de console Rich, on ne fait rien (les logs vont dans les fichiers)
    except Exception:
        pass


def _write_log(file_path: Path, msg: str) -> None:
    """Écrit un message horodaté dans le fichier spécifié."""
    with _lock:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] {msg}\n"
        file_path.parent.mkdir(exist_ok=True)
        with file_path.open("a", encoding="utf-8") as f:
            f.write(line+ "\n")

# -------------------------------------------------------
# NIVEAUX DE LOG
# -------------------------------------------------------
def info(msg: str) -> None:
    """
    Log d'information standard.
    - Toujours écrit dans runtime.log
    - Affiché à l'écran uniquement si _VERBOSE=True
    """
    if _VERBOSE:
        _safe_print(msg)
    _write_log(RUNTIME_LOG, msg)


def log(msg: str) -> None:
    """Alias historique vers info(), pour compatibilité."""
    info(msg)

def warning(msg: str) -> None:
    """
    Log d'avertissement.
    - Toujours écrit dans runtime.log (préfixé [WARN])
    - Affiché à l'écran si _VERBOSE=True
    """
    line = f"[WARN] {msg}"
    if _VERBOSE:
        _safe_print(line)
    _write_log(RUNTIME_LOG, line)

def error(msg: str) -> None:
    """
    Log d'erreur.
    - Toujours écrit dans error.log (et runtime.log)
    - Toujours affiché en console, même si _VERBOSE=False
    """
    line = f"[ERROR] {msg}"
    _safe_print(line)
    _write_log(ERROR_LOG, line)
    _write_log(RUNTIME_LOG, line)


def git(msg: str) -> None:
    """
    Log spécifique aux commandes Git.
    - Toujours écrit dans git.log
    - Affiché si _VERBOSE=True (préfixé [GIT])
    """
    line = f"[GIT] {msg}"
    if _VERBOSE:
        _safe_print(line)
    _write_log(GIT_LOG, msg)
