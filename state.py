# state.py
from dataclasses import dataclass, field
from threading import Lock
from typing import Dict, List
import time


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

    def __init__(self):
        self._lock = Lock()
        self._repos: Dict[str, RepoStatus] = {}
        self._jobs: Dict[str, SyncJob] = {}
        self._last_update = time.time()

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
