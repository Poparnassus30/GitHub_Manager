# github_service.py
from __future__ import annotations

from typing import List
from pathlib import Path
import time

from config import Config
from state import Registre, RepoStatus
from github_client import GithubClient
from logger import info, error


def compute_sync(local_has_git: bool, remote_exists: bool,
                 ahead_local: int, ahead_remote: int) -> tuple[int, int, int]:
    """
    Calcule (local_pct, remote_pct, global_pct) en % à partir des commits d'avance.
    Logique:
    - ni local git ni remote -> (0, 0, 0)
    - local git seulement -> (100, 0, 50)
    - remote seulement -> (0, 100, 50)
    - les deux -> plus il y a de commits uniques, plus le % baisse.
    """
    if not local_has_git and not remote_exists:
        return 0, 0, 0
    if local_has_git and not remote_exists:
        return 100, 0, 50
    if (not local_has_git) and remote_exists:
        return 0, 100, 50

    # Les deux existent
    total = ahead_local + ahead_remote
    if total == 0:
        # mêmes commits des deux côtés
        return 100, 100, 100

    # plus on a de commits uniques, plus on "s'éloigne" de l'autre
    local_sync = int(round(100.0 * (1.0 - (ahead_local / total))))
    remote_sync = int(round(100.0 * (1.0 - (ahead_remote / total))))
    global_sync = int(round((local_sync + remote_sync) / 2.0))
    return local_sync, remote_sync, global_sync


class GithubService:
    """
    Service qui:
    - lit la config
    - utilise GithubClient pour scanner local + distant
    - met à jour le Registre avec l'état des dépôts
    - lance des jobs import/export (avec progression)
    """

    def __init__(self, cfg: Config, registre: Registre):
        self.cfg = cfg
        self.registre = registre
        self.client = GithubClient(self.cfg.base_path, self.cfg.github_user)

    # ------------------------------------------------------------------
    # Réaction à changement de config
    # ------------------------------------------------------------------
    def on_config_changed(self, cfg: Config):
        self.cfg = cfg
        self.client = GithubClient(self.cfg.base_path, self.cfg.github_user)
        info(f"Config rechargée. base_path={self.cfg.base_path}, user={self.cfg.github_user}")

    # ------------------------------------------------------------------
    # Rafraîchissement général des dépôts
    # ------------------------------------------------------------------
    def refresh_repos(self):
        """
        Scan des dépôts locaux/distant, calcul des % et Δ,
        puis envoie le tout au Registre.
        """
        base_path: Path = self.cfg.base_path
        info("refresh_repos: début")

        local_dirs = self.client.scan_local_dirs()
        local_git = self.client.scan_local_git_repos()
        remote_repos = self.client.get_remote_repos()
        remote_by_name = {r["name"]: r for r in remote_repos}

        all_names = sorted(set(local_dirs.keys()) | set(remote_by_name.keys()))

        statuses: List[RepoStatus] = []

        for name in all_names:
            local_path = local_dirs.get(name)
            has_git = name in local_git
            remote_info = remote_by_name.get(name)
            remote_exists = remote_info is not None

            ahead_local = ahead_remote = lines_changed = 0

            if has_git and remote_exists:
                self.client._ensure_https_remote(local_git[name])  # conversion auto si besoin
                ahead_local, ahead_remote, lines_changed = self.client.get_ahead_behind_and_lines(
                    local_git[name]
                )

            local_pct, remote_pct, global_pct = compute_sync(
                local_has_git=has_git,
                remote_exists=remote_exists,
                ahead_local=ahead_local,
                ahead_remote=ahead_remote,
            )

            if has_git and remote_exists:
                delta_commits = f"{ahead_local} / {ahead_remote}"
            else:
                delta_commits = "-"

            status = RepoStatus(
                name=name,
                local_pct=local_pct,
                remote_pct=remote_pct,
                global_pct=global_pct,
                delta_commits=delta_commits,
                delta_lines=lines_changed if has_git and remote_exists else 0,
            )
            statuses.append(status)

        self.registre.update_repos_bulk(statuses)
        info(f"refresh_repos: {len(statuses)} dépôts mis à jour.")

    # ------------------------------------------------------------------
    # Import (cloud -> local) avec progression
    # ------------------------------------------------------------------
    def import_missing_repos(self, target_repo: str | None = None):
        """
        Clone les dépôts distants qui n'existent pas encore localement.
        Affiche la progression par dépôt via Registre.set_job().
        """
        info(f"import_missing_repos: start target_repo={target_repo}")
        remote_repos = self.client.get_remote_repos()
        local_dirs = self.client.scan_local_dirs()

        for repo in remote_repos:
            name = repo["name"]

            if target_repo and name != target_repo:
                continue  # pas le dépôt ciblé

            if name in local_dirs:
                continue  # déjà présent

            # Job de sync pour ce dépôt
            self.registre.set_job(name, "import", 0.0)

            # Étape 1 : préparation
            time.sleep(0.1)
            self.registre.set_job(name, "import", 0.2)

            # Étape 2 : git clone
            info(f"import: tentative clone {name}")
            code = self.client.clone_repo(name)
            if code != 0:
                error(f"import: clone échoué pour {name}")
                self.registre.set_job(name, "import", 1.0, status="error")
                time.sleep(0.5)
                self.registre.clear_job(name)
                continue
            else:
                info(f"import: clone réussi pour {name}")

            # Étape 3 : finalisation
            self.registre.set_job(name, "import", 0.8)
            time.sleep(0.2)

            # Étape 4 : terminé
            self.registre.set_job(name, "import", 1.0, status="done")
            time.sleep(0.5)
            self.registre.clear_job(name)

        # Après import, on rafraîchit les stats
        info("import_missing_repos: terminé, refresh_repos()")
        self.refresh_repos()

    # ------------------------------------------------------------------
    # Export (local -> cloud) avec progression
    # ------------------------------------------------------------------
    def export_local_repos(self, target_repo: str | None = None):
        """
        Fait un push des dépôts git locaux vers leur remote 'origin'.
        (Suppose que les remotes sont déjà configurés côté Git.)
        """
        info(f"export_local_repos: start target_repo={target_repo}")
        local_git = self.client.scan_local_git_repos()

        for name, path in local_git.items():
            if target_repo and name != target_repo:
                continue  # pas le dépôt ciblé

            self.registre.set_job(name, "export", 0.0)

            # Étape 1 : petite pause
            time.sleep(0.1)
            self.registre.set_job(name, "export", 0.3)

            # Étape 2 : git push
            info(f"export: tentative push {name}")
            code = self.client.push_repo(path)
            if code != 0:
                error(f"export: push échoué pour {name}")
                self.registre.set_job(name, "export", 1.0, status="error")
                time.sleep(0.5)
                self.registre.clear_job(name)
                continue
            else:
                info(f"export: push réussi pour {name}")

            # Étape 3 : terminé
            self.registre.set_job(name, "export", 1.0, status="done")
            time.sleep(0.5)
            self.registre.clear_job(name)
            
        # Après export, on rafraîchit les stats
        info("export_local_repos: terminé, refresh_repos()")
        self.refresh_repos()
