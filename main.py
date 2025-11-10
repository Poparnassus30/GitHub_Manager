#!/usr/bin/env python3
"""
main.py
-------
Point d'entrée de l'application GitHub Manager.
"""

import sys
import traceback
from pathlib import Path

from config import Config
from noyau import Noyau
from logger import set_verbose, error

BASE_DIR = Path(__file__).resolve().parent  # dossier du projet


def main() -> int:
    cfg = Config()
    set_verbose(cfg.visual_log)

    try:
        noyau = Noyau(cfg)
        noyau.start()

    except KeyboardInterrupt:
        # Pas de print, uniquement log fichier
        error("KeyboardInterrupt : arrêt demandé par l'utilisateur.")

    except Exception as e:
        tb = traceback.format_exc()
        error(f"EXCEPTION dans main : {e}\n{tb}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
