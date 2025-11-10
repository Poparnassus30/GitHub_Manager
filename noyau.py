# noyau.py
from __future__ import annotations

import threading
import time
import traceback
from queue import Queue, Empty

from config import Config
from state import Registre
from github_service import GithubService
from rich_graph import RichGraph
from rich.live import Live
from rich.prompt import Prompt
from logger import log, info, error, set_verbose
from mythread import MyThread


class Noyau:
    """Cerveau principal : gère threads, GitHub, UI et synchronisation."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.state = Registre(logger_func=log)
        self.github = GithubService(self.cfg, self.state)
        self.ui = RichGraph()

        self.commands: Queue[tuple[str, str | None]] = Queue()
        self.shutdown_event = threading.Event()

        # Threads de fond (kbd, refresh, etc.)
        self._threads: dict[str, MyThread] = {}

        log(
            f"Noyau initialisé : base_path={self.cfg.base_path}, "
            f"github_user={self.cfg.github_user}"
        )

    # ------------------------------------------------------------------
    # Lancement général
    # ------------------------------------------------------------------
    def start(self) -> None:
        log("Noyau.start() : démarrage des threads de fond et de l'UI.")
        self._start_background_threads()
        self._ui_loop()
        log("Noyau.start() : boucle UI terminée.")

    def stop(self) -> None:
        """Arrêt global du noyau."""
        log("Noyau.stop() : arrêt demandé.")
        self.shutdown_event.set()
        # On demande aussi l'arrêt explicite des threads MyThread
        for t in list(self._threads.values()):
            t.stop()
        log(f"Noyau.stop() : threads de fond stoppés. Threads restants dans le registre : {self.state.list_threads()}")

    def _start_background_threads(self) -> None:
        """Lance les threads de fond (clavier + refresh GitHub)."""

        log("Lancement des threads de fond (kbd, refresh).")
        # Thread clavier
        t_kb = MyThread(
            name="kbd",
            target=self._keyboard_loop,
            registre=self.state,
            logger=log,
        )
        self._threads["kbd"] = t_kb

        # Thread de refresh GitHub
        t_refresh = MyThread(
            name="refresh",
            target=self._refresh_loop,
            registre=self.state,
            logger=log,
        )
        self._threads["refresh"] = t_refresh

        for t in self._threads.values():
            t.start()
        log("Threads de fond démarrés.")
    # ------------------------------------------------------------------
    # Threads de fond
    # ------------------------------------------------------------------
    def _keyboard_loop(self, thread: MyThread) -> None:
        """Écoute clavier (non bloquante, Windows uniquement)."""
        try:
            import msvcrt  # dispo que sous Windows
        except ImportError:
            log("Clavier: msvcrt indisponible sur cette plateforme, écoute désactivée.")
            return

        while not self.shutdown_event.is_set() and not thread.stopped():
            if msvcrt.kbhit():
                ch = msvcrt.getch().lower()
                if ch == b"q":
                    log("Clavier: Q (quit)")
                    self.commands.put(("quit", None))
                elif ch == b"1":
                    log("Clavier: 1 (refresh)")
                    self.commands.put(("refresh", None))
                elif ch == b"2":
                    log("Clavier: 2 (import)")
                    self.commands.put(("import", None))
                elif ch == b"3":
                    log("Clavier: 3 (export)")
                    self.commands.put(("export", None))
            time.sleep(0.05)

    def _refresh_loop(self, thread: MyThread) -> None:
        """Thread de refresh périodique GitHub + reload config."""
        while not self.shutdown_event.is_set() and not thread.stopped():
            log("refresh_loop: tick de rafraîchissement.")
            try:
                if self.cfg.poll_changes():
                    set_verbose(self.cfg.visual_log)
                    log(f"Config rechargée : visual_log={self.cfg.visual_log}")
                    self.github.on_config_changed(self.cfg)

                self.github.refresh_repos()
                info("refresh_loop: Refresh GitHub OK")

                # Si jamais on avait des threads non-MyThread dans le registre :
                self.state.cleanup_dead_threads()

            except Exception as e:
                tb = traceback.format_exc()
                error(f"EXCEPTION refresh_loop: {e}\n{tb}")

            time.sleep(self.cfg.refresh_rate)

    # ------------------------------------------------------------------
    # Saisie utilisateur (nom de dépôt)
    # ------------------------------------------------------------------
    def _ask_repo_name(self, live: Live) -> str | None:
        """
        Stoppe l'affichage Live, demande le nom du dépôt
        (Entrée vide = tous les dépôts), puis relance l'affichage.
        """
        live.stop()
        try:
            name = Prompt.ask("Nom du dépôt à traiter ([Entrée] = tous)")
            name = name.strip()
            return name or None
        finally:
            live.start()

    # ------------------------------------------------------------------
    # Boucle principale UI
    # ------------------------------------------------------------------
    def _ui_loop(self) -> None:
        """Affiche l'état en temps réel avec Rich et gère les commandes."""
        with Live(
            self.ui.render(self.state.snapshot()),
            refresh_per_second=4,
            screen=True,
        ) as live:
            while not self.shutdown_event.is_set():
                # Lecture non bloquante des commandes
                try:
                    cmd, arg = self.commands.get_nowait()
                except Empty:
                    cmd = None
                    arg = None

                if cmd is not None:
                    log(f"UI: commande reçue {cmd!r} arg={arg!r}")

                # -------------------
                # Gestion des commandes
                # -------------------
                if cmd == "quit":
                    self.stop()
                    break

                elif cmd == "refresh":
                    self.github.refresh_repos()

                elif cmd == "import":
                    target = self._ask_repo_name(live)

                    def import_worker(thread: MyThread, repo_target: str | None):
                        try:
                            log(f"import_worker: début (target={repo_target})")
                            self.github.import_missing_repos(repo_target)
                            log(f"import_worker: fin (target={repo_target})")
                        except Exception as e:
                            tb = traceback.format_exc()
                            error(f"EXCEPTION import_job: {e}\n{tb}")
                        else:
                            log("import_job terminé avec succès.")

                        # Rien de spécial à faire ici pour le registre :
                        # MyThread s'en occupe via add_thread/remove_thread.

                    job_name = f"import_job_{target or 'all'}"
                    log(f"Lancement job d'import : {job_name}")
                    t = MyThread(
                        name=job_name,
                        target=import_worker,
                        registre=self.state,
                        logger=log,
                        args=(target,),
                    )
                    t.start()

                elif cmd == "export":
                    target = self._ask_repo_name(live)

                    def export_worker(thread: MyThread, repo_target: str | None):
                        try:
                            self.github.export_local_repos(repo_target)
                        except Exception as e:
                            tb = traceback.format_exc()
                            error(f"EXCEPTION export_job: {e}\n{tb}")
                        else:
                            log("export_job terminé avec succès.")

                    job_name = f"export_job_{target or 'all'}"
                    log(f"Lancement job d'export : {job_name}")
                    t = MyThread(
                        name=job_name,
                        target=export_worker,
                        registre=self.state,
                        logger=log,
                        args=(target,),
                    )
                    t.start()

                # -------------------
                # MAJ de l'affichage
                # -------------------
                snapshot = self.state.snapshot()
                live.update(self.ui.render(snapshot))
                time.sleep(0.2)
