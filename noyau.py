# noyau.py
from __future__ import annotations
from logger import log
import threading
import time
from queue import Queue, Empty

from config import Config
from state import Registre
from github_service import GithubService
from rich_graph import RichGraph
from rich.live import Live


class Noyau:
    """Cerveau principal : gère threads, GitHub, UI et synchronisation."""

    def __init__(self) -> None:
        self.cfg = Config()
        self.state = Registre()
        self.github = GithubService(self.cfg, self.state)
        self.ui = RichGraph()

        self.commands: Queue[tuple[str, str | None]] = Queue()
        self.shutdown_event = threading.Event()
        self._threads: list[threading.Thread] = []

    # ------------------------------------------------------------------
    # Lancement général
    # ------------------------------------------------------------------
    def start(self) -> None:
        self._start_background_threads()
        self._ui_loop()

    def _start_background_threads(self) -> None:
        # Thread clavier
        t_kb = threading.Thread(target=self._keyboard_loop, name="kbd", daemon=True)
        self._threads.append(t_kb)

        # Thread de refresh GitHub
        t_refresh = threading.Thread(target=self._refresh_loop, name="refresh", daemon=True)
        self._threads.append(t_refresh)

        for t in self._threads:
            t.start()

    def stop(self) -> None:
        self.shutdown_event.set()

    # ------------------------------------------------------------------
    # Threads de fond
    # ------------------------------------------------------------------
    def _keyboard_loop(self) -> None:
        """Écoute clavier (non bloquante)."""
        import msvcrt
        while not self.shutdown_event.is_set():
            if msvcrt.kbhit():
                ch = msvcrt.getch().lower()
                if ch == b"q":
                    self.commands.put(("quit", None))
                elif ch == b"1":
                    self.commands.put(("refresh", None))
                elif ch == b"2":
                    self.commands.put(("import", None))
                elif ch == b"3":
                    self.commands.put(("export", None))
            time.sleep(0.05)

    def _refresh_loop(self) -> None:
        ...
        from pathlib import Path

        base_dir = Path(__file__).resolve().parent
        log_file = base_dir / "error_threads.log"

        while not self.shutdown_event.is_set():
            try:
                if self.cfg.poll_changes():
                    self.github.on_config_changed(self.cfg)

                self.github.refresh_repos()
                # log "normal" pour voir que ça tourne
                log("Refresh GitHub OK")

            except Exception as e:
                msg = f"EXCEPTION refresh_loop: {e}"
                import traceback
                tb = traceback.format_exc()

                # log détaillé dans app.log
                log(msg)
                log(tb)

                # en plus: fichier d'erreur "brut"
                with log_file.open("a", encoding="utf-8") as f:
                    f.write(msg + "\n")
                    f.write(tb + "\n" + "=" * 80 + "\n")

            time.sleep(self.cfg.refresh_rate)



    # ------------------------------------------------------------------
    # Jobs spécifiques (import/export)
    # ------------------------------------------------------------------
    def _launch_import_job(self) -> None:
        t = threading.Thread(target=self.github.import_missing_repos, name="import_job", daemon=True)
        t.start()

    def _launch_export_job(self) -> None:
        t = threading.Thread(target=self.github.export_local_repos, name="export_job", daemon=True)
        t.start()

    # ------------------------------------------------------------------
    # Boucle principale UI
    # ------------------------------------------------------------------
    def _ui_loop(self) -> None:
        """Affiche l'état en temps réel avec Rich."""
        with Live(self.ui.render(self.state.snapshot()), refresh_per_second=4, screen=True) as live:
            while not self.shutdown_event.is_set():
                try:
                    cmd, arg = self.commands.get_nowait()
                except Empty:
                    cmd = None

                if cmd == "quit":
                    self.stop()
                    break
                elif cmd == "refresh":
                    self.github.refresh_repos()
                elif cmd == "import":
                    self._launch_import_job()
                elif cmd == "export":
                    self._launch_export_job()

                # Met à jour l'affichage
                snapshot = self.state.snapshot()
                live.update(self.ui.render(snapshot))
                time.sleep(0.2)
