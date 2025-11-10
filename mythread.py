# mythread.py
"""
Classe MyThread : thread supervisé avec :
- stop() / stopped()
- enregistrement automatique dans le Registre
- logging via la fonction passée
"""
from __future__ import annotations

import threading
import traceback
from typing import Callable, Any

from state import Registre
from logger import log  # fallback si aucun logger fourni


class MyThread(threading.Thread):
    """
    Thread supervisé, avec contrôle d'arrêt et auto-enregistrement dans le registre.
    Le `target` doit accepter au moins un argument : l'objet thread lui-même.
    (En pratique : def ma_fonction(thread, ...) )
    """

    def __init__(
        self,
        name: str,
        target: Callable[..., Any],
        registre: Registre | None = None,
        logger: Callable[[str], None] | None = None,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
    ):
        super().__init__(name=name, daemon=True)
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}
        self._stop_event = threading.Event()
        self._registre = registre
        self._log = logger or log

    # ----------------------------
    # API publique
    # ----------------------------
    def stop(self) -> None:
        """Demande l'arrêt du thread."""
        self._stop_event.set()

    def stopped(self) -> bool:
        """Retourne True si un arrêt a été demandé."""
        return self._stop_event.is_set()

    # ----------------------------
    # Cycle de vie
    # ----------------------------
    def run(self) -> None:
        """Exécute la fonction cible sous supervision."""
        self._log(f"[THREAD] {self.name} démarré.")
        if self._registre:
            self._registre.add_thread(self.name, self)

        try:
            # IMPORTANT : on passe `self` (MyThread) au target
            self._target(self, *self._args, **self._kwargs)
        except Exception as e:
            self._log(f"[THREAD] {self.name} a crashé : {e}")
            traceback.print_exc()
        finally:
            if self._registre:
                self._registre.remove_thread(self.name)
            self._log(f"[THREAD] {self.name} terminé.")
