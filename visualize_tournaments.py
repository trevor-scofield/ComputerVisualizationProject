#!/usr/bin/env python3
"""Generate all seven Smash History figures from the supplied CSV files.

Install with: python -m pip install -r requirements.txt
Run with: python visualize_tournaments.py
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib.pyplot as plt

import smash_history_analysis as analysis


FIGURE_NAMES = [
    "01_tournament_activity.png",
    "02_sets_by_year.png",
    "03_character_popularity.png",
    "04_character_usage_winrate.png",
    "05_matchup_matrix.png",
    "06_top_players.png",
    "07_player_character_flow.png",
]


def main() -> None:
    base = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Generate the seven Smash History visualizations.")
    parser.add_argument(
        "tournament_csv",
        nargs="?",
        type=Path,
        default=base / "tournament_info" / "tournament_info.csv",
        help="Tournament metadata CSV",
    )
    parser.add_argument("--sets", type=Path, help="Sets CSV (default: sets.csv beside tournament CSV)")
    parser.add_argument("-o", "--output-dir", type=Path, default=base / "output" / "smash_history_figures", help="Folder for PNG figures")
    args = parser.parse_args()
    sets_csv = args.sets or args.tournament_csv.parent / "sets.csv"

    if not args.tournament_csv.is_file():
        parser.error(f"Tournament CSV not found: {args.tournament_csv}")
    if not sets_csv.is_file():
        parser.error(f"Sets CSV not found: {sets_csv}. Use --sets to provide its path.")

    try:
        data = analysis.analyze_data(args.tournament_csv, sets_csv, progress_every=500_000)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        figures = analysis.build_all_figures(data)
        for figure, name in zip(figures, FIGURE_NAMES):
            destination = args.output_dir / name
            figure.savefig(destination, dpi=180, bbox_inches="tight")
            plt.close(figure)
            print(f"Saved {destination.resolve()}")
    except (OSError, ValueError, csv.Error) as error:
        parser.error(str(error))

    print(
        f"Analyzed {data['total_events']:,} tournament rows and {data['total_sets']:,} set rows; "
        f"{data['sets_with_character_data']:,} sets include character data."
    )


if __name__ == "__main__":
    main()
