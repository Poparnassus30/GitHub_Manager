# config.py
from __future__ import annotations

from pathlib import Path
import configparser
from threading import Lock
from typing import Any
import time
import sys


class Config:
    # Valeurs par défaut
    BASE_DEFAULT = Path(r"D:\github") if sys.platform.startswith("win") else Path.home() / "github"

    DEFAULT_CONTENT = {
        "general": {
            "base_path": str(BASE_DEFAULT),
            "github_user": "Poparnassus30",
            "refresh_rate": "4",   # secondes entre deux refresh auto
        },
        "auth": {
            "key_path": str(Path.home() / ".ssh" / "id_ed25519"),
        },
    }

    def __init__(self, path: str | Path | None = None):
        # Si aucun chemin n'est donné, on force config.ini à côté de config.py
        if path is None:
            path = Path(__file__).with_name("config.ini")
        self.path = Path(path).resolve()

        self._parser = configparser.ConfigParser()
        self._lock = Lock()
        self._last_mtime: float | None = None

        self._load_or_create()

    # ------------------------------------------------------------------ #
    # Gestion du fichier physique
    # ------------------------------------------------------------------ #
    def _write_default(self) -> None:
        """Écrit un fichier de config tout neuf avec les valeurs par défaut."""
        self._parser.clear()
        for sec, opts in self.DEFAULT_CONTENT.items():
            self._parser[sec] = opts

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as f:
            self._parser.write(f)

    def _load_or_create(self) -> None:
        """Crée le fichier si besoin, puis le charge."""
        if not self.path.exists():
            self._write_default()
            print(f"⚙️  Fichier config créé : {self.path}")
        self._load()

    def _load(self) -> None:
        """Charge la config, et se protège contre les fichiers corrompus."""
        with self._lock:
            try:
                self._parser.read(self.path, encoding="utf-8")
            except configparser.Error as e:
                # Fichier pourri (options dupliquées, etc.)
                backup = self.path.with_suffix(".bak")
                try:
                    self.path.replace(backup)
                    print(f"⚠️  Config corrompue, sauvegardée sous {backup.name}, recréation par défaut.")
                except OSError:
                    print("⚠️  Config corrompue, impossible de faire une sauvegarde propre, recréation par défaut.")
                self._write_default()
                self._parser.read(self.path, encoding="utf-8")

            try:
                self._last_mtime = self.path.stat().st_mtime
            except FileNotFoundError:
                self._last_mtime = None

    # ------------------------------------------------------------------ #
    # Détection de changement externe
    # ------------------------------------------------------------------ #
    def poll_changes(self) -> bool:
        """Retourne True si le fichier config.ini a été modifié sur le disque."""
        try:
            mtime = self.path.stat().st_mtime
        except FileNotFoundError:
            return False

        if self._last_mtime is None or mtime > self._last_mtime:
            self._load()
            return True
        return False

    # ------------------------------------------------------------------ #
    # Accès aux valeurs
    # ------------------------------------------------------------------ #
    def get(self, section: str, option: str, fallback: Any = None) -> str:
        with self._lock:
            return self._parser.get(section, option, fallback=fallback)

    @property
    def base_path(self) -> Path:
        return Path(self.get("general", "base_path", str(self.BASE_DEFAULT)))

    @property
    def github_user(self) -> str:
        return self.get("general", "github_user", "Poparnassus30")

    @property
    def key_path(self) -> Path:
        return Path(self.get("auth", "key_path", str(Path.home() / ".ssh" / "id_ed25519")))

    @property
    def refresh_rate(self) -> float:
        return float(self.get("general", "refresh_rate", "4"))
