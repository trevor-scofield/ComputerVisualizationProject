"""Streaming analysis and seven reproducible figures for Smash tournament data.

Requires Python 3.10+ and Matplotlib. Uses only the Python standard library for
CSV/JSON processing so multi-gigabyte source files are not loaded into memory.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
from matplotlib.patches import PathPatch, Polygon, Rectangle
from matplotlib.path import Path as MplPath
from matplotlib.ticker import PercentFormatter, StrMethodFormatter


def _set_csv_field_limit() -> None:
    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10


def source_fingerprint(*paths: str | Path) -> tuple[tuple[str, int, int], ...]:
    """Stable local cache key based on absolute path, byte size, and mtime."""
    result = []
    for raw_path in paths:
        path = Path(raw_path).resolve()
        stat = path.stat()
        result.append((str(path), stat.st_size, stat.st_mtime_ns))
    return tuple(result)


def _character_name(raw: Any) -> str | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    name = raw.strip().rsplit("/", 1)[-1]
    normalized = name.replace("_", " ").replace("-", " ").title()
    aliases = {
        "Drmario": "Dr. Mario", "Iceclimbers": "Ice Climbers", "Littlemac": "Little Mac",
        "Megaman": "Mega Man", "Mrgameandwatch": "Mr. Game & Watch", "Pacman": "Pac-Man",
        "Pokemontrainer": "Pokémon Trainer", "Zerosuitsamus": "Zero Suit Samus",
        "Kingdedede": "King Dedede", "Diddykong": "Diddy Kong", "Donkeykong": "Donkey Kong",
        "Duckhunt": "Duck Hunt", "Wii Fit Trainer": "Wii Fit Trainer",
    }
    return aliases.get(normalized, normalized)


def character_label(name: str) -> str:
    """Humanize cached slugs as well as names parsed by the current reader."""
    normalized = name.replace("_", " ").replace("-", " ").title()
    aliases = {
        "Drmario": "Dr. Mario", "Iceclimbers": "Ice Climbers", "Littlemac": "Little Mac",
        "Megaman": "Mega Man", "Mrgameandwatch": "Mr. Game & Watch", "Pacman": "Pac-Man",
        "Pokemontrainer": "Pokémon Trainer", "Zerosuitsamus": "Zero Suit Samus",
        "Kingdedede": "King Dedede", "Diddykong": "Diddy Kong", "Donkeykong": "Donkey Kong",
        "Duckhunt": "Duck Hunt",
    }
    return aliases.get(normalized, normalized)


def _player_id(raw: Any) -> str | None:
    if raw is None:
        return None
    value = str(raw).strip()
    return value if value and value.lower() not in {"none", "null", "nan"} else None


def _year_from_epoch(raw: Any) -> int | None:
    try:
        return datetime.fromtimestamp(int(float(raw)), tz=timezone.utc).year
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _load_event_years(tournament_csv: Path) -> tuple[dict[str, int], Counter[int], int]:
    """Read only event keys/start dates, retaining a small event-key lookup."""
    _set_csv_field_limit()
    event_year: dict[str, int] = {}
    events_by_year: Counter[int] = Counter()
    total_events = 0
    with tournament_csv.open("r", newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        required = {"key", "start"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Tournament CSV is missing columns: {', '.join(sorted(missing))}")
        for row in reader:
            total_events += 1
            key = (row.get("key") or "").strip()
            year = _year_from_epoch(row.get("start"))
            if key and year is not None:
                event_year[key] = year
                events_by_year[year] += 1
    if not total_events:
        raise ValueError("The tournament CSV contains no data rows.")
    return event_year, events_by_year, total_events


def analyze_data(tournament_csv: str | Path, sets_csv: str | Path, progress_every: int = 0) -> dict[str, Any]:
    """Stream both CSVs and return compact aggregates used by all figures."""
    tournament_csv, sets_csv = Path(tournament_csv), Path(sets_csv)
    event_year, events_by_year, total_events = _load_event_years(tournament_csv)
    known_years = list(event_year.values())
    if not known_years:
        raise ValueError("No usable tournament start dates were found.")
    midpoint = (min(known_years) + max(known_years)) / 2

    sets_by_year_game: Counter[tuple[int, str]] = Counter()
    character_uses: Counter[str] = Counter()
    character_wins: Counter[str] = Counter()
    character_by_year: Counter[tuple[int, str]] = Counter()
    matchup_wins: Counter[tuple[str, str]] = Counter()
    player_set_wins: Counter[str] = Counter()
    player_game_uses: Counter[str] = Counter()
    player_character_era: dict[str, Counter[tuple[str, str]]] = {
        "Earlier period": Counter(), "Later period": Counter()
    }
    total_sets = 0
    linked_sets = 0
    sets_with_character_data = 0
    games_with_both_characters = 0
    games_missing_character = 0
    unknown_or_bad_game_data = 0
    game_data_games = 0

    _set_csv_field_limit()
    with sets_csv.open("r", newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        required = {"tournament_key", "game", "winner_id", "game_data"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Sets CSV is missing columns: {', '.join(sorted(missing))}")

        for row in reader:
            total_sets += 1
            if progress_every and total_sets % progress_every == 0:
                print(f"Processed {total_sets:,} set rows...", flush=True)
            tournament_key = (row.get("tournament_key") or "").strip()
            year = event_year.get(tournament_key)
            game_name = (row.get("game") or "Unknown").strip() or "Unknown"
            winner_id = _player_id(row.get("winner_id"))
            if winner_id:
                player_set_wins[winner_id] += 1
            if year is None:
                continue
            linked_sets += 1
            sets_by_year_game[(year, game_name)] += 1

            raw_data = (row.get("game_data") or "").strip()
            if not raw_data or raw_data in {"[]", "{}", "null"}:
                continue
            try:
                games_in_set = json.loads(raw_data)
            except (json.JSONDecodeError, TypeError):
                unknown_or_bad_game_data += 1
                continue
            if not isinstance(games_in_set, list):
                unknown_or_bad_game_data += 1
                continue

            set_has_character_data = False
            era = "Earlier period" if year <= midpoint else "Later period"
            for game in games_in_set:
                if not isinstance(game, dict):
                    continue
                game_data_games += 1
                winner_char = _character_name(game.get("winner_char"))
                loser_char = _character_name(game.get("loser_char"))
                winner_player = _player_id(game.get("winner_id"))
                loser_player = _player_id(game.get("loser_id"))
                if winner_char:
                    character_uses[winner_char] += 1
                    character_wins[winner_char] += 1
                    if winner_player:
                        player_game_uses[winner_player] += 1
                        player_character_era[era][(winner_player, winner_char)] += 1
                    set_has_character_data = True
                if loser_char:
                    character_uses[loser_char] += 1
                    if loser_player:
                        player_game_uses[loser_player] += 1
                        player_character_era[era][(loser_player, loser_char)] += 1
                    set_has_character_data = True
                if winner_char and loser_char:
                    character_by_year[(year, winner_char)] += 1
                    character_by_year[(year, loser_char)] += 1
                    matchup_wins[(winner_char, loser_char)] += 1
                    games_with_both_characters += 1
                else:
                    games_missing_character += 1
            if set_has_character_data:
                sets_with_character_data += 1

    if total_sets == 0:
        raise ValueError("The sets CSV contains no data rows.")

    return {
        "tournament_csv": str(tournament_csv),
        "sets_csv": str(sets_csv),
        "source_fingerprint": source_fingerprint(tournament_csv, sets_csv),
        "total_events": total_events,
        "events_by_year": events_by_year,
        "total_sets": total_sets,
        "linked_sets": linked_sets,
        "sets_by_year_game": sets_by_year_game,
        "character_uses": character_uses,
        "character_wins": character_wins,
        "character_by_year": character_by_year,
        "matchup_wins": matchup_wins,
        "player_set_wins": player_set_wins,
        "player_game_uses": player_game_uses,
        "player_character_era": player_character_era,
        "sets_with_character_data": sets_with_character_data,
        "games_with_both_characters": games_with_both_characters,
        "games_missing_character": games_missing_character,
        "unknown_or_bad_game_data": unknown_or_bad_game_data,
        "game_data_games": game_data_games,
        "midpoint_year": midpoint,
    }


def plot_activity_by_year(data: dict[str, Any]):
    years = sorted(data["events_by_year"])
    fig, ax = plt.subplots(figsize=(10, 5.4))
    ax.plot(years, [data["events_by_year"][y] for y in years], marker="o", color="#4263eb", lw=2.2)
    ax.fill_between(years, [data["events_by_year"][y] for y in years], color="#4263eb", alpha=0.12)
    ax.set(title="1. Competitive tournament activity", xlabel="Tournament start year (UTC)", ylabel="Recorded tournaments")
    ax.yaxis.set_major_formatter(StrMethodFormatter("{x:,.0f}"))
    ax.grid(alpha=0.25)
    fig.tight_layout()
    return fig


def plot_sets_by_year(data: dict[str, Any]):
    by_year_game = data["sets_by_year_game"]
    years = sorted({year for year, _ in by_year_game})
    game_totals: Counter[str] = Counter()
    for (_, game), count in by_year_game.items():
        game_totals[game] += count
    game_names = [name for name, _ in game_totals.most_common(6)]
    fig, ax = plt.subplots(figsize=(10, 5.4))
    for game in game_names:
        vals = [by_year_game[(year, game)] for year in years]
        ax.plot(years, vals, marker="o", ms=3, lw=1.8, label=game)
    ax.set(title="2. Recorded tournament sets over time", xlabel="Tournament start year (UTC)", ylabel="Sets")
    ax.yaxis.set_major_formatter(StrMethodFormatter("{x:,.0f}"))
    if game_names:
        ax.legend(title="Game", ncol=2, frameon=False)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    return fig


def plot_character_popularity(data: dict[str, Any], top_n: int = 8):
    by_year = data["character_by_year"]
    years = sorted({year for year, _ in by_year})
    totals = Counter()
    for (year, character), count in by_year.items():
        totals[character] += count
    top_chars = [name for name, _ in totals.most_common(top_n)]
    fig, ax = plt.subplots(figsize=(11, 5.8))
    if years and top_chars:
        yearly_totals = {year: sum(n for (y, _), n in by_year.items() if y == year) for year in years}
        values = [[by_year[(year, char)] / yearly_totals[year] for year in years] for char in top_chars]
        other = [sum(n for (y, c), n in by_year.items() if y == year and c not in top_chars) / yearly_totals[year] for year in years]
        labels = [character_label(name) for name in top_chars] + (["Other characters"] if any(other) else [])
        stacks = values + ([other] if any(other) else [])
        ax.stackplot(years, stacks, labels=labels, alpha=0.88)
        ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1), frameon=False, title="Character")
    ax.set(title="3. Character share across competitive history", xlabel="Year", ylabel="Share of recorded character appearances")
    ax.yaxis.set_major_formatter(PercentFormatter(1))
    ax.grid(axis="y", alpha=0.2)
    fig.tight_layout()
    return fig


def plot_character_usage_winrate(data: dict[str, Any], min_appearances: int = 25):
    uses, wins = data["character_uses"], data["character_wins"]
    names = [name for name, count in uses.items() if count >= min_appearances]
    rates = {name: wins[name] / uses[name] for name in names}
    fig, ax = plt.subplots(figsize=(10, 6))
    if names:
        ax.scatter([uses[n] for n in names], [rates[n] for n in names], s=50, alpha=0.72, color="#e64980", edgecolor="white", linewidth=0.6)
        label_offsets = [10, -16, 22, -28, 34]
        for index, (name, _) in enumerate(uses.most_common(len(label_offsets))):
            if name in rates:
                ax.annotate(character_label(name), (uses[name], rates[name]), xytext=(-10, label_offsets[index]), ha="right", textcoords="offset points", fontsize=8,
                            arrowprops={"arrowstyle": "-", "color": "#868e96", "lw": .5})
        ax.set_xscale("log")
        ax.axhline(0.5, color="#868e96", ls="--", lw=1)
    ax.yaxis.set_major_formatter(PercentFormatter(1))
    ax.set_ylim(.35, .65)
    ax.set(title=f"4. Character usage and game win rate (at least {min_appearances} appearances)", xlabel="Character appearances in recorded individual games (log scale)", ylabel="Game win percentage")
    ax.grid(alpha=0.22)
    fig.tight_layout()
    return fig


def plot_matchup_triangle(data: dict[str, Any], top_n: int = 12):
    """Custom split-cell matchup matrix: each triangle encodes one side's win rate."""
    usage = data["character_uses"]
    raw_characters = [name for name, _ in usage.most_common(top_n)]
    characters = [character_label(name) for name in raw_characters]
    color_map = plt.get_cmap("RdYlGn")
    norm = Normalize(0, 1)
    fig, ax = plt.subplots(figsize=(10.5, 9))
    n = len(characters)
    for i in range(n):
        for j in range(i + 1, n):
            char_a, char_b = raw_characters[i], raw_characters[j]
            a_wins = data["matchup_wins"][(char_a, char_b)]
            b_wins = data["matchup_wins"][(char_b, char_a)]
            total = a_wins + b_wins
            if total == 0:
                continue
            rate_a = a_wins / total
            # upper-right triangle represents row character winning against column character.
            tri_a = Polygon([(j - .5, i - .5), (j + .5, i - .5), (j + .5, i + .5)], closed=True, facecolor=color_map(norm(rate_a)), edgecolor="white", linewidth=.5)
            tri_b = Polygon([(j - .5, i - .5), (j - .5, i + .5), (j + .5, i + .5)], closed=True, facecolor=color_map(norm(1-rate_a)), edgecolor="white", linewidth=.5)
            ax.add_patch(tri_a)
            ax.add_patch(tri_b)
            ax.text(j, i, f"{total}", ha="center", va="center", fontsize=7, color="#202124")
            # Mirror the reciprocal matchup into the lower-left half.
            ax.add_patch(Polygon([(i - .5, j - .5), (i + .5, j - .5), (i + .5, j + .5)], closed=True, facecolor=color_map(norm(1-rate_a)), edgecolor="white", linewidth=.5))
            ax.add_patch(Polygon([(i - .5, j - .5), (i - .5, j + .5), (i + .5, j + .5)], closed=True, facecolor=color_map(norm(rate_a)), edgecolor="white", linewidth=.5))
            ax.text(i, j, f"{total}", ha="center", va="center", fontsize=7, color="#202124")
    for i in range(n):
        ax.add_patch(Rectangle((i-.5, i-.5), 1, 1, facecolor="#e9ecef", edgecolor="white"))
        ax.text(i, i, "—", ha="center", va="center", color="#868e96")
    ax.set_xlim(-.5, n-.5)
    ax.set_ylim(n-.5, -.5)
    ax.set_xticks(range(n), characters, rotation=60, ha="right")
    ax.set_yticks(range(n), characters)
    ax.set_aspect("equal")
    ax.set_title("5. Character matchup record | custom split-cell matrix")
    ax.set_xlabel("Column character (winning character is the row label on each triangle)")
    sm = plt.cm.ScalarMappable(norm=norm, cmap=color_map)
    fig.colorbar(sm, ax=ax, fraction=.035, pad=.04, label="Share of head-to-head game wins for the row character")
    ax.text(0, -0.13, "Cell number = recorded head-to-head games; blank cells have no observed matchup.", transform=ax.transAxes, fontsize=8, va="top")
    fig.tight_layout()
    return fig


def plot_top_players(data: dict[str, Any], top_n: int = 15):
    players = data["player_set_wins"].most_common(top_n)
    fig, ax = plt.subplots(figsize=(10, 6))
    if players:
        shown = list(reversed(players))
        ax.barh([f"{player}" for player, _ in shown], [wins for _, wins in shown], color="#15aabf")
    ax.set(title=f"6. Players with the most recorded set wins (top {len(players)})", xlabel="Won sets", ylabel="Recorded player ID / handle")
    ax.xaxis.set_major_formatter(StrMethodFormatter("{x:,.0f}"))
    ax.grid(axis="x", alpha=.22)
    fig.tight_layout()
    return fig


def _main_characters_by_era(data: dict[str, Any], min_games: int = 10, player_limit: int = 100):
    early = data["player_character_era"]["Earlier period"]
    late = data["player_character_era"]["Later period"]
    counts: dict[tuple[str, str], int] = defaultdict(int)
    early_total: Counter[str] = Counter()
    late_total: Counter[str] = Counter()
    early_by_player: dict[str, Counter[str]] = defaultdict(Counter)
    late_by_player: dict[str, Counter[str]] = defaultdict(Counter)
    for (player, character), n in early.items():
        early_total[player] += n
        early_by_player[player][character] += n
    for (player, character), n in late.items():
        late_total[player] += n
        late_by_player[player][character] += n
    selected = [p for p, _ in data["player_set_wins"].most_common(player_limit)]
    flows: Counter[tuple[str, str]] = Counter()
    eligible = 0
    for player in selected:
        if early_total[player] < min_games or late_total[player] < min_games:
            continue
        early_char = early_by_player[player].most_common(1)[0][0] if early_by_player[player] else None
        late_char = late_by_player[player].most_common(1)[0][0] if late_by_player[player] else None
        if early_char and late_char:
            flows[(early_char, late_char)] += 1
            eligible += 1
    return flows, eligible


def plot_player_character_flow(data: dict[str, Any], min_games: int = 10, player_limit: int = 30):
    """Custom alluvial ribbons connect each top player's modal character across eras."""
    flows, eligible = _main_characters_by_era(data, min_games, player_limit)
    fig, ax = plt.subplots(figsize=(11, 7))
    if not flows:
        ax.text(.5, .5, "Too few top players have character data in both periods\nfor the selected minimum-game threshold.", ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()
        ax.set_title("7. Character choices among top players | custom alluvial view")
        return fig

    left_counts: Counter[str] = Counter()
    right_counts: Counter[str] = Counter()
    for (left, right), count in flows.items():
        left_counts[left] += count
        right_counts[right] += count
    left_order = [x for x, _ in left_counts.most_common()]
    right_order = [x for x, _ in right_counts.most_common()]
    height, top = .72, .90
    gap = .08 / max(len(left_order), len(right_order), 1)
    left_pos, right_pos = {}, {}
    for order, counts, pos in ((left_order, left_counts, left_pos), (right_order, right_counts, right_pos)):
        y = top
        for char in order:
            h = height * counts[char] / eligible
            pos[char] = [y - h, y]
            y -= h + gap
    left_cursor = {char: left_pos[char][0] for char in left_order}
    right_cursor = {char: right_pos[char][0] for char in right_order}
    palette = plt.get_cmap("tab20")
    left_color = {char: palette(i % 20) for i, char in enumerate(left_order)}

    for (left, right), count in sorted(flows.items(), key=lambda item: (left_order.index(item[0][0]), right_order.index(item[0][1]))):
        h = height * count / eligible
        y0a, y0b = left_cursor[left], left_cursor[left] + h
        y1a, y1b = right_cursor[right], right_cursor[right] + h
        left_cursor[left] = y0b
        right_cursor[right] = y1b
        x0, x1, curve = .08, .92, .33
        verts = [
            (x0, y0a), (x0+curve, y0a), (x1-curve, y1a), (x1, y1a),
            (x1, y1b), (x1-curve, y1b), (x0+curve, y0b), (x0, y0b), (0, 0),
        ]
        codes = [MplPath.MOVETO, MplPath.CURVE4, MplPath.CURVE4, MplPath.CURVE4, MplPath.LINETO, MplPath.CURVE4, MplPath.CURVE4, MplPath.CURVE4, MplPath.CLOSEPOLY]
        ax.add_patch(PathPatch(MplPath(verts, codes), facecolor=left_color[left], edgecolor="none", alpha=.42))

    for x, order, counts, pos, label in ((.04, left_order, left_counts, left_pos, "Earlier period"), (.92, right_order, right_counts, right_pos, "Later period")):
        for char in order:
            low, high = pos[char]
            ax.add_patch(Rectangle((x, low), .04, high-low, facecolor=left_color.get(char, "#868e96"), edgecolor="white", linewidth=.6))
            ax.text(x + (.05 if x < .5 else -.02), (low+high)/2, f"{character_label(char)} ({counts[char]})", ha="left" if x < .5 else "right", va="center", fontsize=8)
        ax.text(x+.02, .97, label, ha="center", va="bottom", fontsize=11, fontweight="bold")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.set_title(f"7. Dominant character shifts among {eligible} top-ranked players | custom alluvial view", pad=18)
    ax.text(.5, .02, f"Top {player_limit} players by set wins; at least {min_games} recorded character games in each period. Each ribbon connects earlier-period and later-period most-used characters.", ha="center", va="bottom", fontsize=8, wrap=True, transform=ax.transAxes)
    fig.tight_layout()
    return fig


def build_all_figures(data: dict[str, Any]) -> list[plt.Figure]:
    """Return the seven report figures in their documented order."""
    return [
        plot_activity_by_year(data),
        plot_sets_by_year(data),
        plot_character_popularity(data),
        plot_character_usage_winrate(data),
        plot_matchup_triangle(data),
        plot_top_players(data),
        plot_player_character_flow(data),
    ]

