# logger.py
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent
LOG_FILE = BASE_DIR / "app.log"


def log(msg: str) -> None:
    """Ajoute un message horodaté dans app.log et l'affiche en console."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    # Affichage console
    print(line)
    # Écriture fichier
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
