#!/usr/bin/env python3

"""
Poparnassus GitHub Manager - V0
-------------------------------

Outils Github :
  - vérifie la connexion ssh
  - Affiche un récapitulatif des projets distants et locaux.
  - (à venir) exporter / importer les projets depuis Github.
"""

import os
import platform
import configparser
import subprocess
import sys
import urllib.request
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple
import re
from rich.console import Console
from rich.table import Table
from rich import box

console = Console()
# ============================================================
# COULEURS TERMINAL (ANSI)
# ============================================================
COLORS = {
    "reset": "\033[0m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "cyan": "\033[36m",
    "bold": "\033[1m",
    "grey": "\033[90m",
}


def color(text: str, color_name: str) -> str:
    """Retourne un texte coloré pour le terminal."""
    code = COLORS.get(color_name, "")
    reset = COLORS["reset"]
    return f"{code}{text}{reset}"


# ============================================================
# CLASSE CONFIG
# ============================================================
class Config:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.parser = configparser.ConfigParser()
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config introuvable : {self.config_path}")
        self.parser.read(self.config_path, encoding="utf-8")

    @property
    def github_user(self) -> str:
        return self.parser.get("general", "github_user", fallback="")

    @property
    def github_name(self) -> str:
        return self.parser.get("general", "github_name", fallback="")

    @property
    def base_path(self) -> Path:
        """Définit le chemin local selon l'OS."""
        if sys.platform.startswith("win"):
            return Path(r"D:\github")
        return Path.home() / "github"


# ============================================================
# UTILITAIRES GIT / SHELL
# ============================================================
def run(cmd: List[str], cwd: Path | None = None) -> Tuple[int, str]:
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        return result.returncode, result.stdout.strip()
    except FileNotFoundError:
        return 1, f"Commande introuvable : {cmd[0]}"


def git_global_config() -> Dict[str, str]:
    keys = ["user.name", "user.email"]
    conf: Dict[str, str] = {}
    for k in keys:
        code, out = run(["git", "config", "--global", k])
        conf[k] = out.strip() if code == 0 and out else "(non défini)"
    return conf


def check_github_connection() -> Tuple[str, str]:
    """
    Teste la connexion SSH à GitHub.

    - Autorise SSH à poser la passphrase si nécessaire
    - Analyse uniquement le message de retour
    """
    code, out = run(["ssh", "-T", "git@github.com"])
    text = out or ""
    lower = text.lower()

    if "successfully authenticated" in lower:
        return "EN LIGNE", text
    if "permission denied" in lower:
        return "ERREUR", "Permission refusée (publickey) : clé pas acceptée ou passphrase incorrecte."
    if "could not resolve" in lower or "name or service not known" in lower:
        return "HORS LIGNE", "Impossible de joindre github.com (DNS / réseau)."
    if code == 0:
        return "EN LIGNE", text

    return "ERREUR", text or f"Code retour SSH : {code}"


# ============================================================
# FONCTIONS GITHUB EN LIGNE
# ============================================================
def get_github_repos(user: str) -> List[Dict]:
    """Récupère la liste des dépôts publics via l’API GitHub."""
    url = f"https://api.github.com/users/{user}/repos?per_page=100"
    with urllib.request.urlopen(url) as resp:
        data = json.loads(resp.read().decode())
    return data


def has_uncommitted_changes(repo_path: Path) -> bool:
    """
    Vérifie si un dépôt Git contient des changements non commités.
    Retourne True si le dépôt a des fichiers modifiés, non ajoutés ou supprimés.
    """
    code, out = run(["git", "status", "--porcelain"], cwd=repo_path)
    if code != 0:
        return False  # Si erreur (pas un dépôt git ou inaccessible)
    return bool(out.strip())  # True si la sortie contient du texte → changements détectés

def get_ahead_behind_and_lines(repo_path: Path) -> Tuple[int, int, int]:
    """
    Retourne (ahead_local, ahead_remote, lines_changed) pour le dépôt git donné.
    - ahead_local  : commits présents en local uniquement
    - ahead_remote : commits présents sur le remote uniquement
    - lines_changed: nb total de lignes modifiées (insertions + deletions)
    """
    # Déterminer la branche de suivi (@{u})
    code, out = run(
        ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
        cwd=repo_path,
    )
    if code != 0:
        # Pas de branche de suivi configurée
        return 0, 0, 0

    # Compter les commits en avance de chaque côté
    code, out = run(
        ["git", "rev-list", "--left-right", "--count", "HEAD...@{u}"],
        cwd=repo_path,
    )
    ahead_local = 0
    ahead_remote = 0
    if code == 0 and out:
        parts = out.split()
        if len(parts) >= 2:
            try:
                ahead_local = int(parts[0])
                ahead_remote = int(parts[1])
            except ValueError:
                pass

    # Compter les lignes modifiées (insertions + deletions)
    code, out = run(
        ["git", "diff", "--shortstat", "HEAD...@{u}"],
        cwd=repo_path,
    )
    lines_changed = 0
    if code == 0 and out:
        nums = [int(x) for x in re.findall(r"(\d+)", out)]
        if len(nums) >= 3:
            # ex : "1 file changed, 3 insertions(+), 1 deletion(-)"
            lines_changed = nums[-2] + nums[-1]
        elif nums:
            lines_changed = nums[-1]

    return ahead_local, ahead_remote, lines_changed


def compute_sync(
    local_exists: bool,
    remote_exists: bool,
    ahead_local: int,
    ahead_remote: int,
) -> Tuple[float, float, float]:
    """
    Calcule (local_sync, remote_sync, global_sync) en % (0–100).

    - local_exists / remote_exists : présence des côtés
    - ahead_local  : commits uniquement en local
    - ahead_remote : commits uniquement sur le remote
    """
    # Aucun des deux n'existe
    if not local_exists and not remote_exists:
        return 0.0, 0.0, 0.0

    # Uniquement local
    if local_exists and not remote_exists:
        local_sync = 100.0
        remote_sync = 0.0
        return local_sync, remote_sync, (local_sync + remote_sync) / 2.0

    # Uniquement distant
    if not local_exists and remote_exists:
        local_sync = 0.0
        remote_sync = 100.0
        return local_sync, remote_sync, (local_sync + remote_sync) / 2.0

    # Les deux existent
    total = ahead_local + ahead_remote
    if total == 0:
        return 100.0, 100.0, 100.0

    # Répartition : plus un côté a de commits uniques, plus son % est élevé
    local_sync = 100.0 * (ahead_local / total)
    remote_sync = 100.0 * (ahead_remote / total)
    global_sync = (local_sync + remote_sync) / 2.0
    return local_sync, remote_sync, global_sync


def fmt_percent(value: float) -> str:
    """Formate un pourcentage avec couleur Rich."""
    val = int(round(value))
    if val >= 90:
        color_name = "green"
    elif val >= 50:
        color_name = "yellow"
    else:
        color_name = "red"
    return f"[{color_name}]{val:3d}%[/]"

# ============================================================
# SCAN LOCAL
# ============================================================
def scan_local_dirs(base_path: Path) -> Dict[str, Path]:
    """Retourne tous les sous-dossiers locaux, même ceux sans .git."""
    dirs: Dict[str, Path] = {}
    if not base_path.exists():
        return dirs

    for child in base_path.iterdir():
        if child.is_dir() and child.name != ".git":
            dirs[child.name] = child
    return dirs


def scan_local_repos(base_path: Path) -> Dict[str, Path]:
    """Retourne les dépôts trouvés en local (avec .git)."""
    repos: Dict[str, Path] = {}
    if not base_path.exists():
        return repos
    for child in base_path.iterdir():
        if (child / ".git").is_dir():
            repos[child.name] = child
    return repos


# ============================================================
# AFFICHAGE
# ============================================================
def print_header(title: str) -> None:
    """Affiche un titre encadré avec Rich."""
    console.rule(f"[bold cyan]{title}")

def make_sync_bar(percent: int) -> str:
    """
    Construit une petite barre de synchro en ASCII avec couleur Rich.
    0, 25, 50, 75, 100% suffisent pour l'instant.
    """
    percent = max(0, min(100, percent))
    total_blocks = 10
    filled = int(total_blocks * percent / 100)
    empty = total_blocks - filled

    if percent >= 100:
        color_name = "green"
    elif percent >= 50:
        color_name = "yellow"
    else:
        color_name = "red"

    bar = "█" * filled + "·" * empty
    return f"[{color_name}]{bar}[/] {percent:3d}%"


def afficher_statut_general(cfg: Config) -> None:
    """Affiche l'état complet : configuration, connexion et synchro GitHub."""
    from datetime import datetime

    # --- [1] CONFIG GLOBALE ---
    conf = git_global_config()
    base_path = cfg.base_path
    github_user = cfg.github_user or "(non défini)"

    console.rule("[bold cyan]CONFIG GIT LOCALE[/]")
    console.print(f"user.name  : [green]{conf.get('user.name')}[/]")
    console.print(f"user.email : [green]{conf.get('user.email')}[/]\n")

        # --- [2] CONNEXION GITHUB ---
    console.rule("[bold cyan]CONNEXION GITHUB[/]")
    status_text, status_details = check_github_connection()
    console.print(f"Statut : [bold]{status_text}[/]")
    console.print(f"Compte GitHub : [cyan]{github_user}[/]")
    if status_details:
        console.print(f"[grey50]{status_details}[/]")
    console.print()  # ligne vide


    # --- [3] RÉCUPÉRATION DES DÉPÔTS EN LIGNE ---
    console.rule(f"[bold cyan]RÉCUPÉRATION DES DÉPÔTS EN LIGNE ({github_user})[/]")
    try:
        repos_online = get_github_repos(github_user)
    except Exception as e:
        console.print(f"[red]❌ Erreur d'accès à GitHub : {e}[/]")
        return

    local_git_repos = scan_local_repos(base_path)
    local_dirs = scan_local_dirs(base_path)
    all_repo_names = sorted(set(local_dirs.keys()) | {r["name"] for r in repos_online})

    # --- [4] TABLEAU RICH (Local % / Distant % / Δ commits / Δ lignes / Global %) ---
    table = Table(
        show_header=True,
        header_style="bold white",
        box=box.SIMPLE_HEAVY,
        expand=False,
    )
    table.add_column("Nom du dépôt", style="bold", no_wrap=True)
    table.add_column("Local %", justify="right")
    table.add_column("Distant %", justify="right")
    table.add_column("Δ commits", justify="center")
    table.add_column("Δ lignes", justify="right")
    table.add_column("Global %", justify="right")

    # --- [5] BOUCLE SUR LES DÉPÔTS ---
    for name in all_repo_names:
        name_display = name if len(name) <= 32 else name[:29] + "..."

        local_exists = name in local_dirs
        has_git = name in local_git_repos
        repo_distant = next((r for r in repos_online if r["name"] == name), None)
        remote_exists = repo_distant is not None

        ahead_local = 0
        ahead_remote = 0
        lines_changed = 0

        # Calcul commits / lignes si dépôt git local + distant existant
        if has_git and remote_exists:
            ahead_local, ahead_remote, lines_changed = get_ahead_behind_and_lines(
                local_git_repos[name]
            )
            local_sync, remote_sync, global_sync = compute_sync(
                True, True, ahead_local, ahead_remote
            )
        elif has_git and not remote_exists:
            # Git en local seulement
            local_sync, remote_sync, global_sync = compute_sync(
                True, False, 0, 0
            )
        elif (not has_git) and remote_exists:
            # GitHub seulement
            local_sync, remote_sync, global_sync = compute_sync(
                False, True, 0, 0
            )
        else:
            # Ni dépôt git, ni remote (ou dossier non git)
            local_sync, remote_sync, global_sync = compute_sync(
                local_exists, remote_exists, 0, 0
            )

        # Formatage des % avec couleur
        local_pct_str = fmt_percent(local_sync)
        remote_pct_str = fmt_percent(remote_sync)
        global_pct_str = fmt_percent(global_sync)

        # Δ commits = "L / R" si calculable, sinon "-"
        if has_git and remote_exists:
            delta_commits_str = f"{ahead_local} / {ahead_remote}"
            delta_lines_str = str(lines_changed)
        else:
            delta_commits_str = "-"
            delta_lines_str = "-"

        table.add_row(
            name_display,
            local_pct_str,
            remote_pct_str,
            delta_commits_str,
            delta_lines_str,
            global_pct_str,
        )

    console.print(table)

    # --- [6] RÉSUMÉ FINAL ---
    locaux_uniques = len([n for n in local_dirs if n not in {r["name"] for r in repos_online}])
    distants_uniques = len([r for r in repos_online if r["name"] not in local_dirs])
    communs = len(all_repo_names) - locaux_uniques - distants_uniques

    console.print("\n[bold]📊 Résumé :[/]")
    console.print(f"  Locaux uniquement  : [yellow]{locaux_uniques}[/]")
    console.print(f"  Distants uniquement : [cyan]{distants_uniques}[/]")
    console.print(f"  Présents des deux côtés : [green]{communs}[/]\n")

    # --- [7] LISTE DES DOSSIERS LOCAUX NON GIT ---
    if locaux_uniques > 0:
        console.print("[green]🧩 Dépôts locaux non présents sur GitHub :[/]")
        for name, path in local_dirs.items():
            if name not in {r['name'] for r in repos_online}:
                console.print(f"  - [yellow]{name}[/] ([dim]{path}[/])")

    console.print()



# ============================================================
# MENU & MAIN
# ============================================================
def clear_screen() -> None:
    """Efface l'écran selon le système d'exploitation."""
    if platform.system().lower().startswith("win"):
        os.system("cls")
    else:
        os.system("clear")
def importer_github():
    pass  # Fonction à implémenter

def exporter_github():
    pass  # Fonction à implémenter

def afficher_menu(cfg: Config) -> None:
    while True:
        clear_screen()
        afficher_statut_general(cfg)
        console.rule("[bold cyan]POPARNASSUS GITHUB MANAGER[/]")
        console.print("[1] Vérifier l'état GitHub")
        console.print("[2] Importer depuis le Cloud")
        console.print("[3] Exporter vers le Cloud")
        console.print("[Q] Quitter")


        choix = input("\nChoix : ").strip().lower()

        if choix == "1":
            continue
        elif choix == "2": 
            clear_screen()
            print("⚙️  Fonction Import (Cloud -> Local) à venir...")
            input("\nAppuyez sur Entrée pour revenir au menu...")
        elif choix == "3":
            clear_screen()
            print("⚙️  Fonction Export (Local -> Cloud) à venir...")
            input("\nAppuyez sur Entrée pour revenir au menu...")
        elif choix == "q":
            print("Fermeture du programme.")
            break
        else:
            print("❌ Option invalide, réessaie.")


def start_windows(cfg: Config) -> None:
    print_header("DÉMARRAGE WINDOWS")
    afficher_menu(cfg)


def start_linux(cfg: Config) -> None:
    print_header("DÉMARRAGE LINUX")
    afficher_menu(cfg)


def main() -> int:
    config_path = Path(__file__).parent / "config.ini"
    cfg = Config(config_path)
    if sys.platform.startswith("win"):
        start_windows(cfg)
    else:
        start_linux(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
