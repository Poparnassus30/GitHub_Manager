# github_client.py
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple
import subprocess
import json
import urllib.request
import urllib.error
import re

from logger import info, error, git


def run_cmd(cwd: Path | None, *args: str) -> Tuple[int, str, str]:
    """Exécute une commande dans cwd, retourne (code, stdout, stderr)."""
    proc = subprocess.Popen(
        list(args),
        cwd=str(cwd) if cwd is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    out, err = proc.communicate()
    return proc.returncode, out.strip(), err.strip()


def run_git(cwd: Path, *args: str) -> Tuple[int, str, str]:
    return run_cmd(cwd, "git", *args)


class GithubClient:
    """
    Client bas niveau pour :
    - scanner les dépôts locaux
    - parler à git (ahead/behind, diff, push, clone)
    - appeler l'API GitHub (liste des dépôts distants)
    """

    def __init__(self, base_path: Path, github_user: str):
        self.base_path = Path(base_path)
        self.github_user = github_user

    # ------------------------------------------------------------------
    # Scan local
    # ------------------------------------------------------------------
    def scan_local_dirs(self) -> Dict[str, Path]:
        """Tous les dossiers sous base_path (qu'ils soient git ou non)."""
        result: Dict[str, Path] = {}
        if not self.base_path.exists():
            info(f"scan_local_dirs: base_path {self.base_path} introuvable.")
            return result
        for p in self.base_path.iterdir():
            if p.is_dir() and p.name != ".git":
                result[p.name] = p
        info(f"scan_local_dirs: {len(result)} dossiers trouvés.")
        return result

    def scan_local_git_repos(self) -> Dict[str, Path]:
        """Dossiers qui contiennent un .git (donc dépôts git locaux)."""
        repos: Dict[str, Path] = {}
        for name, path in self.scan_local_dirs().items():
            if (path / ".git").exists():
                repos[name] = path
        info(f"scan_local_git_repos: {len(repos)} dépôts git locaux.")
        return repos

    # ------------------------------------------------------------------
    # API GitHub (dépôts distants)
    # ------------------------------------------------------------------
    def get_remote_repos(self) -> List[dict]:
        """
        Retourne la liste des dépôts publics du user.
        Utilise l'API publique GitHub (pas besoin de token).
        En cas d'erreur, logue le problème et renvoie [].
        """
        url = f"https://api.github.com/users/{self.github_user}/repos?per_page=100"
        info(f"Appel API GitHub: {url}")

        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Poparnassus-GitHubManager"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                status = resp.getcode()
                info(f"Réponse HTTP GitHub: {status}")
                data = resp.read().decode("utf-8")
            payload = json.loads(data)
        except Exception as e:
            error(f"Erreur API GitHub pour {self.github_user} : {e}")
            return []

        if not isinstance(payload, list):
            error(f"Réponse GitHub inattendue pour {self.github_user}: {payload}")
            return []

        normalized: List[dict] = []
        for r in payload:
            name = r.get("name", "")
            updated_at = r.get("updated_at", "")
            if not name:
                continue
            normalized.append({"name": name, "updated_at": updated_at})

        info(f"GitHub: {len(normalized)} dépôts distants trouvés pour {self.github_user}")
        return normalized

    # ------------------------------------------------------------------
    # Git : ahead/behind + diff lignes
    # ------------------------------------------------------------------
    def get_ahead_behind_and_lines(self, repo_path: Path) -> Tuple[int, int, int]:
        """
        Retourne (ahead_local, ahead_remote, lines_changed) pour HEAD vs branche distante.
        """
        code, out, err = run_git(repo_path, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
        if code != 0:
            git(f"[{repo_path.name}] pas de remote @{{u}} configuré (rc={code}, err={err})")
            return 0, 0, 0

        upstream = out.strip()  # ex: origin/main

        run_git(repo_path, "fetch", "--all", "--quiet")

        code, out, err = run_git(repo_path, "rev-list", "--left-right", "--count", f"HEAD...{upstream}")
        ahead_local = ahead_remote = 0
        if code == 0 and out:
            parts = out.split()
            if len(parts) >= 2:
                try:
                    ahead_local = int(parts[0])
                    ahead_remote = int(parts[1])
                except ValueError:
                    pass

        code, out, err = run_git(repo_path, "diff", "--shortstat", f"HEAD...{upstream}")
        lines_changed = 0
        if code == 0 and out:
            nums = [int(x) for x in re.findall(r"(\d+)", out)]
            if len(nums) >= 3:
                lines_changed = nums[-2] + nums[-1]
            elif nums:
                lines_changed = nums[-1]

        git(
            f"[{repo_path.name}] ahead_local={ahead_local}, "
            f"ahead_remote={ahead_remote}, lines_changed={lines_changed}"
        )
        return ahead_local, ahead_remote, lines_changed

    # ------------------------------------------------------------------
    # Git : clone / push HTTPS
    # ------------------------------------------------------------------
    def clone_repo(self, repo_name: str) -> int:
        """Clone un dépôt GitHub dans base_path (URL HTTPS)."""
        url = f"https://github.com/{self.github_user}/{repo_name}.git"
        target = self.base_path / repo_name
        if target.exists():
            info(f"clone_repo: {repo_name} déjà présent localement.")
            return 0

        info(f"clone_repo: {repo_name} -> {target} (URL={url})")
        code, out, err = run_cmd(self.base_path, "git", "clone", url, str(target))
        git(f"[clone {repo_name}] rc={code}\nstdout:\n{out}\nstderr:\n{err}")
        if code != 0:
            error(f"Échec du clone de {repo_name} : {err}")
        else:
            info(f"clone_repo OK: {repo_name}")
        return code
    
    def _ensure_https_remote(self, repo_path: Path) -> None:
        """
        Si origin est en SSH (git@github.com:...), convertit en HTTPS.
        Ne fait rien si déjà en HTTPS ou si origin n'existe pas.
        """
        code, out, err = run_git(repo_path, "remote")
        if code != 0 or "origin" not in out.split():
            return

        code, url, err = run_git(repo_path, "remote", "get-url", "origin")
        if code != 0:
            return

        url = url.strip()
        if url.startswith("git@github.com:"):
            # git@github.com:User/Repo.git  ->  https://github.com/User/Repo.git
            https_url = "https://github.com/" + url.split("git@github.com:")[1]
            info(f"Migrate remote to HTTPS: {repo_path.name} -> {https_url}")
            run_git(repo_path, "remote", "set-url", "origin", https_url)

    def push_repo(self, repo_path: Path) -> int:
        """Fait un git push du dépôt vers son 'origin'."""
        self._ensure_https_remote(repo_path)
        code, out, err = run_git(repo_path, "rev-parse", "--abbrev-ref", "HEAD")
        if code != 0:
            error(f"Impossible de déterminer la branche pour {repo_path}: {err}")
            return code

        branch = out.strip()
        info(f"push_repo: {repo_path.name} sur branche {branch}")
        code, out, err = run_git(repo_path, "push", "origin", branch)
        git(f"[push {repo_path.name}] rc={code}\nstdout:\n{out}\nstderr:\n{err}")
        if code != 0:
            error(f"Échec du push de {repo_path.name}: {err}")
        else:
            info(f"push_repo OK: {repo_path.name}")
        return code
