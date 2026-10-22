#!/usr/bin/env python3
"""Create a compact dashboard from the tournament_info.csv dataset.

The input is read a row at a time because the source file can be very large and
contains multiline JSON fields that should not be loaded into memory wholesale.

Install dependencies with: python -m pip install matplotlib
Run with: python visualize_tournaments.py [path/to/tournament_info.csv]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.ticker import StrMethodFormatter


def set_csv_field_size_limit() -> None:
    """Raise csv's default 128 KiB limit, accounting for platform C limits."""
    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10


def parse_bool(value: str) -> str:
    """Normalize common true/false representations into chart labels."""
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "online"}:
        return "Online"
    if normalized in {"0", "false", "no", "n", "offline"}:
        return "Offline"
    return "Unknown"


def display_character(value: str) -> str:
    """Turn a game-prefixed character slug into a readable label."""
    name = value.strip().rsplit("/", 1)[-1]
    return name.replace("_", " ").replace("-", " ").title()


def read_character_results(sets_path: Path) -> tuple[Counter[str], Counter[str], int]:
    """Return character appearances, character wins, and sets with game data."""
    appearances: Counter[str] = Counter()
    wins: Counter[str] = Counter()
    sets_with_game_data = 0

    with sets_path.open("r", newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        if "game_data" not in (reader.fieldnames or []):
            raise ValueError("The sets CSV is missing the required 'game_data' column.")

        for row in reader:
            raw_data = (row.get("game_data") or "").strip()
            if not raw_data or raw_data in {"[]", "{}", "null"}:
                continue
            try:
                games_in_set = json.loads(raw_data)
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(games_in_set, list):
                continue

            set_has_character_data = False
            for game in games_in_set:
                if not isinstance(game, dict):
                    continue
                winner = game.get("winner_char")
                loser = game.get("loser_char")
                if isinstance(winner, str) and winner.strip():
                    winner = display_character(winner)
                    appearances[winner] += 1
                    wins[winner] += 1
                    set_has_character_data = True
                if isinstance(loser, str) and loser.strip():
                    loser = display_character(loser)
                    appearances[loser] += 1
                    set_has_character_data = True
            if set_has_character_data:
                sets_with_game_data += 1

    return appearances, wins, sets_with_game_data


def build_dashboard(csv_path: Path, sets_path: Path, output_path: Path, top_n: int = 10) -> tuple[int, int]:
    set_csv_field_size_limit()
    tournaments_by_year: Counter[str] = Counter()
    games: Counter[str] = Counter()
    countries: Counter[str] = Counter()
    formats: Counter[str] = Counter()
    entrant_bins: Counter[str] = Counter()
    total = 0
    valid_entrants = 0

    with csv_path.open("r", newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        required = {"game", "start", "country", "entrants", "online"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV is missing required columns: {', '.join(sorted(missing))}")

        for row in reader:
            total += 1
            game = (row.get("game") or "").strip() or "Unknown"
            games[game] += 1

            country = (row.get("country") or "").strip().upper() or "Unknown"
            countries[country] += 1
            formats[parse_bool(row.get("online") or "")] += 1

            try:
                timestamp = int(float(row.get("start") or ""))
                year = str(datetime.fromtimestamp(timestamp, tz=timezone.utc).year)
                tournaments_by_year[year] += 1
            except (ValueError, OverflowError, OSError):
                tournaments_by_year["Unknown"] += 1

            try:
                entrants = int(float(row.get("entrants") or ""))
                if entrants < 0:
                    continue
                valid_entrants += 1
                if entrants == 0:
                    bucket = "0"
                elif entrants == 1:
                    bucket = "1"
                elif entrants <= 4:
                    bucket = "2–4"
                elif entrants <= 8:
                    bucket = "5–8"
                elif entrants <= 16:
                    bucket = "9–16"
                elif entrants <= 32:
                    bucket = "17–32"
                elif entrants <= 64:
                    bucket = "33–64"
                elif entrants <= 128:
                    bucket = "65–128"
                else:
                    bucket = "129+"
                entrant_bins[bucket] += 1
            except (ValueError, OverflowError):
                pass

    if total == 0:
        raise ValueError("The CSV contains no data rows.")

    character_appearances, character_wins, sets_with_game_data = read_character_results(sets_path)

    plt.style.use("seaborn-v0_8-whitegrid")
    fig, axes = plt.subplots(2, 3, figsize=(19, 11), constrained_layout=True)
    fig.suptitle(f"Tournament overview · {total:,} tournaments", fontsize=19, fontweight="bold")

    # Tournament activity over time.
    ax = axes[0, 0]
    year_items = sorted((y, n) for y, n in tournaments_by_year.items() if y != "Unknown")
    if year_items:
        ax.plot([x[0] for x in year_items], [x[1] for x in year_items], marker="o", linewidth=2, color="#4263eb")
        ax.tick_params(axis="x", rotation=45)
    else:
        ax.text(0.5, 0.5, "No usable start dates", ha="center", va="center", transform=ax.transAxes)
    ax.set_title("Tournaments by start year")
    ax.set_xlabel("Year (UTC)")
    ax.set_ylabel("Tournaments")
    ax.yaxis.set_major_formatter(StrMethodFormatter("{x:,.0f}"))

    # Most frequently represented games.
    ax = axes[0, 1]
    top_games = games.most_common(top_n)
    ax.barh([x[0] for x in reversed(top_games)], [x[1] for x in reversed(top_games)], color="#15aabf")
    ax.set_title(f"Top {min(top_n, len(top_games))} games")
    ax.set_xlabel("Tournaments")
    ax.xaxis.set_major_formatter(StrMethodFormatter("{x:,.0f}"))

    # Entrant counts are bucketed to keep outliers readable.
    ax = axes[0, 2]
    bin_order = ["0", "1", "2–4", "5–8", "9–16", "17–32", "33–64", "65–128", "129+"]
    present_bins = [label for label in bin_order if entrant_bins[label]]
    ax.bar(present_bins, [entrant_bins[label] for label in present_bins], color="#f59f00")
    ax.set_title(f"Entrants per tournament ({valid_entrants:,} valid records)")
    ax.set_xlabel("Entrant count")
    ax.set_ylabel("Tournaments")
    ax.tick_params(axis="x", rotation=25)
    ax.yaxis.set_major_formatter(StrMethodFormatter("{x:,.0f}"))

    # Tournament mode summary.
    ax = axes[1, 0]
    ax.axis("off")
    mode_order = ["Online", "Offline", "Unknown"]
    mode_lines = [f"{label}: {formats[label]:,} ({formats[label] / total:.1%})" for label in mode_order if formats[label]]
    top_countries = countries.most_common(5)
    country_lines = [f"{country}: {count:,}" for country, count in top_countries]
    summary = "Tournament format\n" + "\n".join(mode_lines or ["No format values"]) + "\n\nTop countries\n" + "\n".join(country_lines)
    ax.text(0.05, 0.95, summary, va="top", ha="left", fontsize=13, linespacing=1.6, transform=ax.transAxes)
    ax.set_title("Format and location", loc="left")

    # Most represented countries.
    ax = axes[1, 1]
    top_countries = countries.most_common(top_n)
    ax.barh([x[0] for x in reversed(top_countries)], [x[1] for x in reversed(top_countries)], color="#845ef7")
    ax.set_title(f"Top {min(top_n, len(top_countries))} countries")
    ax.set_xlabel("Tournaments")
    ax.xaxis.set_major_formatter(StrMethodFormatter("{x:,.0f}"))

    # Character usage versus game win percentage.
    ax = axes[1, 2]
    chars = [name for name, count in character_appearances.items() if count > 0]
    if chars:
        rates = {name: character_wins[name] / character_appearances[name] for name in chars}
        ax.scatter(
            [character_appearances[name] for name in chars],
            [rates[name] for name in chars],
            alpha=0.75,
            s=45,
            color="#e64980",
            edgecolors="white",
            linewidths=0.5,
        )
        ax.set_xscale("log")
        ax.axhline(0.5, color="#868e96", linestyle="--", linewidth=1)
        for name, _ in character_appearances.most_common(15):
            if name in rates:
                ax.annotate(
                    name,
                    (character_appearances[name], rates[name]),
                    xytext=(4, 4),
                    textcoords="offset points",
                    fontsize=8,
                )
        ax.yaxis.set_major_formatter(StrMethodFormatter("{x:.0%}"))
    else:
        ax.text(0.5, 0.5, "No character results found in game_data", ha="center", va="center", transform=ax.transAxes)
    ax.set_title(f"Character usage vs. win rate ({sets_with_game_data:,} sets with character data)")
    ax.set_xlabel("Character appearances in individual games (log scale)")
    ax.set_ylabel("Win percentage per game")
    ax.set_ylim(0, 1)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return total, sum(character_appearances.values())


def main() -> None:
    parser = argparse.ArgumentParser(description="Visualize tournament_info.csv as a dashboard PNG.")
    parser.add_argument(
        "csv_file",
        nargs="?",
        type=Path,
        default=Path(__file__).parent / "tournament_info" / "tournament_info.csv",
        help="Tournament CSV (default: tournament_info/tournament_info.csv beside this script)",
    )
    parser.add_argument("--sets", type=Path, help="Sets CSV containing per-game character data (default: sets.csv beside the tournament CSV)")
    parser.add_argument("-o", "--output", type=Path, default=Path("tournament_dashboard.png"), help="Output PNG path")
    parser.add_argument("--top", type=int, default=10, help="Number of games to show (default: 10)")
    args = parser.parse_args()

    if args.top < 1:
        parser.error("--top must be at least 1")
    if not args.csv_file.is_file():
        parser.error(f"CSV file not found: {args.csv_file}")
    sets_path = args.sets or args.csv_file.parent / "sets.csv"
    if not sets_path.is_file():
        parser.error(f"Sets CSV not found: {sets_path}. Use --sets to provide its path.")

    try:
        count, character_games = build_dashboard(args.csv_file, sets_path, args.output, args.top)
    except (OSError, ValueError, csv.Error) as error:
        parser.error(str(error))
    print(
        f"Visualized {count:,} tournaments and {character_games:,} character game appearances. "
        f"Dashboard saved to {args.output.resolve()}"
    )


if __name__ == "__main__":
    main()
