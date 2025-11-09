# github_client.py
from __future__ import annotations
from logger import log
from pathlib import Path
from typing import Dict, List, Tuple
import subprocess
import json
import urllib.request
import urllib.error
import re


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
            return result
        for p in self.base_path.iterdir():
            if p.is_dir() and p.name != ".git":   # ← on ignore .git
                result[p.name] = p
        return result

    def scan_local_git_repos(self) -> Dict[str, Path]:
        """Dossiers qui contiennent un .git (donc dépôts git locaux)."""
        repos: Dict[str, Path] = {}
        for name, path in self.scan_local_dirs().items():
            if (path / ".git").exists():
                repos[name] = path
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
        log(f"Appel API GitHub: {url}")

        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Poparnassus-GitHubManager"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                status = resp.getcode()
                log(f"Réponse HTTP GitHub: {status}")
                data = resp.read().decode("utf-8")
            payload = json.loads(data)
        except Exception as e:
            log(f"❌ Erreur API GitHub pour {self.github_user} : {e}")
            return []

        if not isinstance(payload, list):
            log(f"⚠️ Réponse GitHub inattendue pour {self.github_user}: {payload}")
            return []

        normalized: List[dict] = []
        for r in payload:
            name = r.get("name", "")
            updated_at = r.get("updated_at", "")
            if not name:
                continue
            normalized.append({"name": name, "updated_at": updated_at})

        log(f"🔎 GitHub: {len(normalized)} dépôts distants trouvés pour {self.github_user}")
        return normalized


    # ------------------------------------------------------------------
    # Git : ahead/behind + diff lignes
    # ------------------------------------------------------------------
    def get_ahead_behind_and_lines(self, repo_path: Path) -> Tuple[int, int, int]:
        """
        Retourne (ahead_local, ahead_remote, lines_changed) pour HEAD vs branche distante.
        - ahead_local = commits présents en local uniquement
        - ahead_remote = commits présents sur le remote uniquement
        - lines_changed = insertions + deletions entre les deux.
        """
        # On récupère la branche de suivi @{u} (upstream)
        code, out, err = run_git(repo_path, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
        if code != 0:
            # Pas de remote configuré
            return 0, 0, 0

        upstream = out.strip()  # ex: origin/main

        # Met à jour les références distantes
        run_git(repo_path, "fetch", "--all", "--quiet")

        # Compter commits ahead/behind
        # git rev-list --left-right --count HEAD...@{u}
        code, out, err = run_git(repo_path, "rev-list", "--left-right", "--count", f"HEAD...{upstream}")
        ahead_local = ahead_remote = 0
        if code == 0 and out:
            parts = out.split()
            if len(parts) >= 2:
                # Format: "<only_HEAD> <only_upstream>"
                try:
                    ahead_local = int(parts[0])
                    ahead_remote = int(parts[1])
                except ValueError:
                    pass

        # Lignes modifiées (insertions + deletions)
        # git diff --shortstat HEAD...@{u}
        code, out, err = run_git(repo_path, "diff", "--shortstat", f"HEAD...{upstream}")
        lines_changed = 0
        if code == 0 and out:
            nums = [int(x) for x in re.findall(r"(\d+)", out)]
            if len(nums) >= 3:
                # ex: "1 file changed, 3 insertions(+), 1 deletion(-)"
                lines_changed = nums[-2] + nums[-1]
            elif nums:
                lines_changed = nums[-1]

        return ahead_local, ahead_remote, lines_changed

    # ------------------------------------------------------------------
    # Git : clone / push
    # ------------------------------------------------------------------
    def clone_repo(self, repo_name: str) -> int:
        """
        Clone un dépôt GitHub dans base_path.
        Utilise l'URL SSH (git@github.com:user/repo.git).
        """
        url = f"git@github.com:{self.github_user}/{repo_name}.git"
        target = self.base_path / repo_name
        if target.exists():
            return 0  # déjà présent
        code, out, err = run_cmd(self.base_path, "git", "clone", url, str(target))
        if code != 0:
            print(f"❌ Échec du clone de {repo_name} : {err}")
        return code

    def push_repo(self, repo_path: Path) -> int:
        """
        Fait un git push du dépôt vers son 'origin'.
        """
        # On essaie de détecter la branche courante
        code, out, err = run_git(repo_path, "rev-parse", "--abbrev-ref", "HEAD")
        if code != 0:
            print(f"❌ Impossible de déterminer la branche pour {repo_path}: {err}")
            return code
        branch = out.strip()
        code, out, err = run_git(repo_path, "push", "origin", branch)
        if code != 0:
            print(f"❌ Échec du push de {repo_path.name}: {err}")
        return code
