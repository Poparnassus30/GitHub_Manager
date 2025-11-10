# state.py
from dataclasses import dataclass, field
from threading import Lock
from typing import Dict, List
import time
import threading


@dataclass
class RepoStatus:
    name: str
    local_pct: int = 0
    remote_pct: int = 0
    global_pct: int = 0
    delta_commits: str = "-"
    delta_lines: int = 0


@dataclass
class SyncJob:
    repo_name: str
    mode: str
    progress: float
    status: str = "running"
    started_at: float = field(default_factory=time.time)


@dataclass
class AppSnapshot:
    repos: List[RepoStatus]
    jobs: List[SyncJob]
    last_update: float


class Registre:
    """Conteneur thread-safe pour l’état global."""

    def __init__(self,logger_func=None):
        self._lock = threading.Lock()
        self._repos: Dict[str, RepoStatus] = {}
        self._jobs: Dict[str, SyncJob] = {}
        self._last_update = time.time()
        self._threads: dict[str, threading.Thread] = {}
        self._log = logger_func or (lambda msg: None)  # fallback silencieux

    def update_repos_bulk(self, statuses: List[RepoStatus]):
        with self._lock:
            self._repos = {s.name: s for s in statuses}
            self._last_update = time.time()

    def set_job(self, repo: str, mode: str, progress: float, status: str = "running"):
        with self._lock:
            self._jobs[repo] = SyncJob(repo_name=repo, mode=mode, progress=progress, status=status)
            self._last_update = time.time()

    def clear_job(self, repo: str):
        with self._lock:
            self._jobs.pop(repo, None)
            self._last_update = time.time()

    def snapshot(self) -> AppSnapshot:
        with self._lock:
            return AppSnapshot(
                repos=list(self._repos.values()),
                jobs=list(self._jobs.values()),
                last_update=self._last_update,
            )
        
    # --------------------------------------
    # THREAD MANAGEMENT
    # --------------------------------------
    def add_thread(self, name: str, thread: threading.Thread):
        """Enregistre un thread actif."""
        with self._lock:
            self._threads[name] = thread
            self._log(f"[Registre] Thread ajouté : {name}")

    def remove_thread(self, name: str):
        """Supprime un thread du registre."""
        with self._lock:
            if name in self._threads:
                self._threads.pop(name)
                self._log(f"[Registre] Thread retiré : {name}")

    def list_threads(self) -> list[str]:
        """Liste les threads actuellement enregistrés."""
        with self._lock:
            return list(self._threads.keys())

    def cleanup_dead_threads(self):
        """Nettoie les threads terminés (filet de sécurité)."""
        with self._lock:
            dead = [n for n, t in self._threads.items() if not t.is_alive()]
            for name in dead:
                self._threads.pop(name, None)
                self._log(f"[Registre] Thread mort nettoyé : {name}")
