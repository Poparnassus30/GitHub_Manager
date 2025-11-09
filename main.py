#!/usr/bin/env python3
"""
main.py
-------
Point d'entrée de l'application GitHub Manager.
"""

import sys
import traceback
from datetime import datetime
from pathlib import Path

from noyau import Noyau

BASE_DIR = Path(__file__).resolve().parent  # dossier du projet

def main() -> int:
    log_file = BASE_DIR / "error.log"

    try:
        noyau = Noyau()
        noyau.start()

    except KeyboardInterrupt:
        print("\n🛑 Arrêt demandé par l'utilisateur (Ctrl+C).")

    except Exception as e:
        # On logue l'exception dans un fichier + on l'affiche
        msg = f"\n[{datetime.now().isoformat()}] EXCEPTION: {e}\n"
        tb = traceback.format_exc()

        with log_file.open("a", encoding="utf-8") as f:
            f.write(msg)
            f.write(tb)
            f.write("\n" + "=" * 80 + "\n")

        print("❌ Une exception s'est produite. Détails dans error.log")
        print(msg)
        print(tb)

    return 0


if __name__ == "__main__":
    sys.exit(main())
