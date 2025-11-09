# rich_graph.py
from __future__ import annotations

from rich.table import Table
from rich.panel import Panel
from rich.console import Group
from rich import box

from config import Config  # pour afficher les infos de config


def make_bar(p: float, length: int = 10) -> str:
    p = max(0.0, min(1.0, p))
    filled = int(length * p)
    empty = length - filled
    if p >= 0.99:
        color = "green"
    elif p >= 0.5:
        color = "yellow"
    else:
        color = "red"
    return f"[{color}]" + "█" * filled + "·" * empty + f"[/] {int(p*100):3d}%"


class RichGraph:
    """Construit le rendu Rich à partir du snapshot."""

    def __init__(self):
        # On charge juste la config pour l'affichage (pas pour la logique)
        self.cfg = Config()

    def render(self, snapshot):
        # ---------- Panel CONFIG / CONNEXION ----------
        config_lines = [
            f"user.name  : [cyan]{self.cfg.github_user}[/]",
            f"base_path : [cyan]{self.cfg.base_path}[/]",
        ]
        header_panel = Panel(
            "\n".join(config_lines),
            title="[bold]CONFIG / CONNEXION GITHUB[/]",
            border_style="green",
        )

        # ---------- Tableau des dépôts ----------
        jobs_by_repo = {job.repo_name: job for job in snapshot.jobs}

        table = Table(box=box.SIMPLE_HEAVY, expand=True)
        table.add_column("Nom dépôt", style="bold cyan")
        table.add_column("Local %", justify="right")
        table.add_column("Distant %", justify="right")
        table.add_column("Δ commits", justify="center")
        table.add_column("Δ lignes", justify="right")
        table.add_column("Global %", justify="right")
        table.add_column("Sync", justify="center")

        for repo in snapshot.repos:
            job = jobs_by_repo.get(repo.name)
            if job:
                bar = make_bar(job.progress)
                sync_cell = f"{job.mode.upper()} {bar}"
            else:
                sync_cell = "-"

            table.add_row(
                repo.name,
                f"{repo.local_pct:3d}%",
                f"{repo.remote_pct:3d}%",
                repo.delta_commits,
                str(repo.delta_lines),
                f"{repo.global_pct:3d}%",
                sync_cell,
            )

        main_panel = Panel(
            table,
            title="[bold yellow]Dépôts GitHub[/]",
            border_style="cyan",
        )

        layout = Group(
            header_panel,
            main_panel,
        )
        return layout
