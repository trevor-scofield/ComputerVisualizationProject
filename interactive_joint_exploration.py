"""Linked PCA projection and timeline for Smash tournament game data.

Run from the project directory:
    python interactive_joint_exploration.py

The first run streams the large CSV files and saves a compact gzip cache. Later
runs reuse that sample unless either source file changes or --rebuild is given.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import random
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import plotly.graph_objects as go
from dash import Dash, Input, Output, State, callback_context, dcc, html
from plotly.colors import qualitative


ROOT = Path(__file__).resolve().parent
DEFAULT_TOURNAMENTS = ROOT / "tournament_info" / "tournament_info.csv"
DEFAULT_SETS = ROOT / "tournament_info" / "sets.csv"
DEFAULT_CACHE = ROOT / "output" / "interactive_joint_sample.json.gz"
CACHE_VERSION = 1
MAX_STAGES = 24
COLORWAY = qualitative.Safe


def set_csv_field_limit() -> None:
    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10


def normalized_header(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.casefold())


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    return {normalized_header(str(k)): v for k, v in row.items() if k is not None}


def get_value(row: dict[str, Any], *names: str, default: Any = "") -> Any:
    for name in names:
        value = row.get(normalized_header(name))
        if value not in (None, "", "null", "None"):
            return value
    return default


def as_int(value: Any, default: int | None = None) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return default


def parse_year(value: Any) -> int | None:
    timestamp = as_int(value)
    if timestamp is None:
        return None
    # Tournament start values are Unix seconds. Reject implausible timestamps.
    try:
        year = datetime.fromtimestamp(timestamp, tz=timezone.utc).year
    except (ValueError, OverflowError, OSError):
        return None
    return year if 2000 <= year <= 2100 else None


def clean_category(value: Any, fallback: str = "Unknown") -> str:
    if not isinstance(value, str) or not value.strip():
        return fallback
    value = value.strip().replace("_", " ").replace("-", " ")
    return value[:80]


def character_name(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip().rsplit("/", 1)[-1]
    normalized = value.replace("_", " ").replace("-", " ").title()
    aliases = {
        "Drmario": "Dr. Mario", "Iceclimbers": "Ice Climbers", "Littlemac": "Little Mac",
        "Megaman": "Mega Man", "Mrgameandwatch": "Mr. Game & Watch", "Pacman": "Pac-Man",
        "Pokemontrainer": "Pokémon Trainer", "Zerosuitsamus": "Zero Suit Samus",
        "Kingdedede": "King Dedede", "Diddykong": "Diddy Kong", "Donkeykong": "Donkey Kong",
        "Duckhunt": "Duck Hunt",
    }
    return aliases.get(normalized, normalized)


def source_signature(tournaments_path: Path, sets_path: Path, sample_size: int, seed: int) -> dict[str, Any]:
    return {
        "version": CACHE_VERSION,
        "sample_size": sample_size,
        "seed": seed,
        "sources": [
            {"path": str(p.resolve()), "size": p.stat().st_size, "mtime_ns": p.stat().st_mtime_ns}
            for p in (tournaments_path, sets_path)
        ],
    }


def load_tournaments(tournaments_path: Path) -> dict[str, dict[str, Any]]:
    """Load compact tournament context needed by sampled game records."""
    set_csv_field_limit()
    events: dict[str, dict[str, Any]] = {}
    with tournaments_path.open("r", newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames:
            raise ValueError(f"Tournament CSV has no header: {tournaments_path}")
        for row in reader:
            row = normalize_row(row)
            key = str(get_value(row, "key", "tournament_key", "tournamentKey")).strip()
            year = parse_year(get_value(row, "start", "start_time", "startTimestamp", "startAt"))
            if not key or year is None:
                continue
            entrants = as_int(get_value(row, "numEntrants", "entrant_count", "num_entrants", "entrants"), None)
            event_name = clean_category(get_value(row, "name", "tournament_name", "tournamentName", "slug"), key)
            location = clean_category(get_value(row, "location", "city", "country"), "Unknown")
            events[key] = {"year": year, "entrants": entrants, "event": event_name, "location": location}
    if not events:
        raise ValueError("No tournaments with usable keys and start dates were found.")
    return events


def sample_game_observations(
    tournaments_path: Path,
    sets_path: Path,
    sample_size: int,
    seed: int,
    progress_every: int = 500_000,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Reservoir-sample player-side game observations with both character labels."""
    events = load_tournaments(tournaments_path)
    rng = random.Random(seed)
    sample: list[dict[str, Any]] = []
    stats = Counter()
    set_csv_field_limit()

    with sets_path.open("r", newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        required = {"tournamentkey", "gamedata"}
        headers = {normalized_header(h) for h in (reader.fieldnames or [])}
        missing = required - headers
        if missing:
            raise ValueError(f"Sets CSV is missing columns: {', '.join(sorted(missing))}")

        for set_number, row in enumerate(reader, 1):
            if progress_every and set_number % progress_every == 0:
                print(f"Scanned {set_number:,} set rows; retained {len(sample):,} player-game samples...", flush=True)
            stats["sets_scanned"] += 1
            row = normalize_row(row)
            tournament_key = str(get_value(row, "tournament_key", "tournamentKey")).strip()
            event = events.get(tournament_key)
            if not event:
                stats["sets_without_tournament_date"] += 1
                continue

            raw = get_value(row, "game_data", "gameData")
            if not raw:
                stats["sets_without_game_data"] += 1
                continue
            try:
                games = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                stats["sets_with_invalid_game_data"] += 1
                continue
            if not isinstance(games, list):
                stats["sets_with_invalid_game_data"] += 1
                continue

            set_id = str(get_value(row, "id", "set_id", "setId", default=set_number))
            game_title = clean_category(get_value(row, "game", "game_name", "gameName"), "Unknown game")
            for game_index, game in enumerate(games, 1):
                if not isinstance(game, dict):
                    continue
                game = normalize_row(game)
                stats["games_parsed"] += 1
                winner_char = character_name(get_value(game, "winner_char", "winnerChar"))
                loser_char = character_name(get_value(game, "loser_char", "loserChar"))
                if not winner_char or not loser_char:
                    stats["games_missing_character_labels"] += 1
                    continue
                stats["games_with_both_character_labels"] += 1
                stage = clean_category(get_value(game, "stage", "stage_name", "stageName"))
                winner_id = str(get_value(game, "winner_id", "winnerId", default="Unknown"))
                loser_id = str(get_value(game, "loser_id", "loserId", default="Unknown"))
                observations = (
                    ("winner", winner_id, winner_char, loser_char, True),
                    ("loser", loser_id, loser_char, winner_char, False),
                )
                for side, player_id, character, opponent, won in observations:
                    stats["player_game_observations_seen"] += 1
                    seen = stats["player_game_observations_seen"]
                    item = {
                        "sample_id": f"{set_id}:{game_index}:{side}",
                        "year": event["year"],
                        "entrants": event["entrants"],
                        "event": event["event"],
                        "location": event["location"],
                        "game": game_title,
                        "player_id": player_id,
                        "character": character,
                        "opponent_character": opponent,
                        "stage": stage,
                        "won": int(won),
                        "set_id": set_id,
                        "game_number": game_index,
                        "side": side,
                    }
                    if len(sample) < sample_size:
                        sample.append(item)
                    else:
                        position = rng.randrange(seen)
                        if position < sample_size:
                            sample[position] = item

    if not sample:
        raise ValueError("No games with both winner and loser character labels were found.")
    stats["sampled_player_game_observations"] = len(sample)
    return sample, dict(stats)


def load_or_prepare_cache(
    tournaments_path: Path,
    sets_path: Path,
    cache_path: Path,
    sample_size: int,
    seed: int,
    rebuild: bool,
) -> dict[str, Any]:
    signature = source_signature(tournaments_path, sets_path, sample_size, seed)
    if not rebuild and cache_path.is_file():
        try:
            with gzip.open(cache_path, "rt", encoding="utf-8") as stream:
                cached = json.load(stream)
            if cached.get("signature") == signature and cached.get("observations"):
                print(f"Using cached sample: {cache_path} ({len(cached['observations']):,} rows)")
                return cached
        except (OSError, json.JSONDecodeError):
            print("Cache could not be read; rebuilding it.")

    print("Reading tournament metadata and streaming sets/game_data for the sample...")
    observations, stats = sample_game_observations(tournaments_path, sets_path, sample_size, seed)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"signature": signature, "stats": stats, "observations": observations}
    with gzip.open(cache_path, "wt", encoding="utf-8", compresslevel=5) as stream:
        json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
    print(f"Saved {len(observations):,} sampled player-game rows to {cache_path}")
    return payload


def build_feature_matrix(observations: list[dict[str, Any]]) -> tuple[np.ndarray, list[str]]:
    """Encode date, event size, character, opponent character, and common stages."""
    characters = sorted({o["character"] for o in observations})
    opponents = sorted({o["opponent_character"] for o in observations})
    stage_counts = Counter(o["stage"] for o in observations)
    stages = [name for name, _ in stage_counts.most_common(MAX_STAGES)]
    stage_lookup = {name: i for i, name in enumerate(stages)}

    columns = ["year", "log_entrants"]
    columns += [f"character:{name}" for name in characters]
    columns += [f"opponent:{name}" for name in opponents]
    columns += [f"stage:{name}" for name in stages]
    columns += ["stage:Other"]
    X = np.zeros((len(observations), len(columns)), dtype=np.float32)

    char_offset = 2
    opp_offset = char_offset + len(characters)
    stage_offset = opp_offset + len(opponents)
    char_index = {name: char_offset + i for i, name in enumerate(characters)}
    opp_index = {name: opp_offset + i for i, name in enumerate(opponents)}
    stage_other_index = stage_offset + len(stages)
    years = np.asarray([o["year"] for o in observations], dtype=np.float32)
    entrant_values = [max(1, int(o["entrants"])) for o in observations if o.get("entrants")]
    entrant_median = float(np.median(entrant_values)) if entrant_values else 1.0
    entrants = np.asarray([
        math.log1p(max(1, int(o["entrants"]))) if o.get("entrants") else math.log1p(entrant_median)
        for o in observations
    ], dtype=np.float32)
    X[:, 0] = years
    X[:, 1] = entrants
    for i, obs in enumerate(observations):
        X[i, char_index[obs["character"]]] = 1.0
        X[i, opp_index[obs["opponent_character"]]] = 1.0
        stage_idx = stage_lookup.get(obs["stage"])
        X[i, stage_offset + stage_idx if stage_idx is not None else stage_other_index] = 1.0

    # Standardize continuous fields and center all columns before PCA. Binary
    # indicator columns stay on a common 0/1 scale to keep categories interpretable.
    for column in range(2):
        mean = float(X[:, column].mean())
        std = float(X[:, column].std())
        X[:, column] = (X[:, column] - mean) / (std if std > 1e-8 else 1.0)
    X -= X.mean(axis=0, keepdims=True)
    return X, columns


def pca_projection(observations: list[dict[str, Any]]) -> tuple[np.ndarray, float]:
    X, _ = build_feature_matrix(observations)
    # SVD gives the first two principal components without a separate ML library.
    _, singular_values, right_vectors = np.linalg.svd(X, full_matrices=False)
    coords = X @ right_vectors[:2].T
    total_variance = float(np.square(singular_values).sum())
    explained = float(np.square(singular_values[:2]).sum() / total_variance) if total_variance else 0.0
    return coords, explained


def make_app(payload: dict[str, Any], title: str = "Smash History Interactive Joint Exploration") -> Dash:
    observations = payload["observations"]
    coords, explained = pca_projection(observations)
    years = sorted({int(o["year"]) for o in observations})
    all_characters = sorted({o["character"] for o in observations})
    min_year, max_year = min(years), max(years)

    for index, (obs, point) in enumerate(zip(observations, coords)):
        obs["_index"] = index
        obs["_x"] = float(point[0])
        obs["_y"] = float(point[1])

    app = Dash(__name__, title=title)
    app.layout = html.Div(
        className="page",
        children=[
            html.Header([
                html.H1("Smash History: Interactive Joint Exploration"),
                html.P("Explore game-level similarities in the PCA projection and locate selected records in time."),
            ]),
            html.Div(className="controls", children=[
                html.Label(["Year range", dcc.RangeSlider(
                    id="year-range", min=min_year, max=max_year, step=1, value=[min_year, max_year],
                    marks={year: str(year) for year in years if year % 2 == 0 or year in {min_year, max_year}},
                    allowCross=False, tooltip={"placement": "bottom", "always_visible": False},
                )]),
                html.Label(["Character filter", dcc.Dropdown(
                    id="character-filter", options=[{"label": c, "value": c} for c in all_characters],
                    value=[], multi=True, placeholder="All characters",
                )]),
                html.Label(["Projection color", dcc.Dropdown(
                    id="color-mode", options=[
                        {"label": "Tournament year", "value": "year"},
                        {"label": "Character", "value": "character"},
                        {"label": "Game result", "value": "result"},
                    ], value="year", clearable=False,
                )]),
                html.Button("Clear selections", id="clear-selection", n_clicks=0),
            ]),
            html.Div(id="selection-summary", className="summary"),
            html.Div(className="views", children=[
                html.Section([html.H2("Projection space"), html.P("Box or lasso select samples; hover for record detail."), dcc.Graph(
                    id="projection", config={"displaylogo": False, "modeBarButtonsToAdd": ["select2d", "lasso2d"]},
                )]),
                html.Section([html.H2("Time space"), html.P("Each marker is a year-character group; select markers to inspect those records."), dcc.Graph(
                    id="timeline", config={"displaylogo": False, "modeBarButtonsToAdd": ["select2d", "lasso2d"]},
                )]),
            ]),
            html.Section(className="details", children=[html.H2("Selected sample details"), html.Div(id="detail-table")]),
            html.Footer([
                html.P(f"PCA of standardized year and log entrant count plus centered character, opponent-character, and common-stage indicators. First two components explain {explained:.1%} of variance in this sample."),
                html.P("The sample includes only player-game observations with both character labels recorded. Win/loss is excluded from PCA and is shown only for interpretation. Similarity is descriptive, not a skill or causal score."),
                html.P(f"Source set rows scanned: {payload['stats'].get('sets_scanned', 0):,}; sampled player-game observations: {len(observations):,}; linked, parsed games missing either character label: {payload['stats'].get('games_missing_character_labels', 0):,}."),
            ]),
            dcc.Store(id="selection-store", data={"indices": [], "timeline": []}),
        ],
    )

    @app.callback(
        Output("projection", "figure"),
        Output("timeline", "figure"),
        Output("selection-summary", "children"),
        Output("detail-table", "children"),
        Output("selection-store", "data"),
        Input("year-range", "value"),
        Input("character-filter", "value"),
        Input("color-mode", "value"),
        Input("projection", "selectedData"),
        Input("timeline", "selectedData"),
        Input("clear-selection", "n_clicks"),
        State("selection-store", "data"),
    )
    def update_views(year_range, selected_characters, color_mode, projection_selection, timeline_selection, clear_clicks, prior_selection):
        trigger = callback_context.triggered_id
        selected_characters = set(selected_characters or [])
        low_year, high_year = year_range or [min_year, max_year]
        filtered = [
            o for o in observations
            if low_year <= o["year"] <= high_year
            and (not selected_characters or o["character"] in selected_characters)
        ]
        if not filtered:
            empty = go.Figure().update_layout(template="plotly_white", annotations=[{
                "text": "No sampled records match these filters", "showarrow": False, "xref": "paper", "yref": "paper", "x": .5, "y": .5,
            }])
            return empty, empty, "No records in the current filter.", html.P("Adjust the year or character filter."), {"indices": [], "timeline": []}

        prior_selection = prior_selection or {"indices": [], "timeline": []}
        if trigger == "clear-selection":
            selected_indices, timeline_keys = set(), set()
        elif trigger == "projection":
            selected_indices = {
                int(point["customdata"][0]) for point in (projection_selection or {}).get("points", [])
                if point.get("customdata") is not None
            }
            timeline_keys = set()
        elif trigger == "timeline":
            selected_indices = set()
            timeline_keys = {
                (int(point["customdata"][0]), str(point["customdata"][1]))
                for point in (timeline_selection or {}).get("points", [])
                if point.get("customdata") is not None
            }
        else:
            selected_indices = set(prior_selection.get("indices", []))
            timeline_keys = {tuple(x) for x in prior_selection.get("timeline", [])}

        if timeline_keys:
            selected_character_groups = {name for name, _ in Counter(o["character"] for o in filtered).most_common(10)}
            selected_indices = {
                o["_index"] for o in filtered
                if (o["year"], o["character"]) in timeline_keys
                or ((o["year"], "Other characters") in timeline_keys and o["character"] not in selected_character_groups)
            }
        elif selected_indices:
            timeline_keys = {
                (o["year"], o["character"]) for o in filtered if o["_index"] in selected_indices
            }

        projection = go.Figure()
        if color_mode == "character":
            common_groups = {name for name, _ in Counter(o["character"] for o in filtered).most_common(12)}
            display_group = lambda obs: obs["character"] if obs["character"] in common_groups else "Other characters"
            groups = sorted({display_group(o) for o in filtered})
            for group_index, group in enumerate(groups):
                rows = [o for o in filtered if display_group(o) == group]
                projection.add_trace(go.Scattergl(
                    x=[o["_x"] for o in rows], y=[o["_y"] for o in rows], mode="markers", name=group,
                    marker={"color": COLORWAY[group_index % len(COLORWAY)], "size": 6, "opacity": .72},
                    customdata=[[o["_index"], o["year"], o["character"], o["opponent_character"], o["stage"], o["won"], o["event"], o["player_id"]] for o in rows],
                    hovertemplate="Year %{customdata[1]}<br>%{customdata[2]} vs %{customdata[3]}<br>Stage %{customdata[4]}<br>Won %{customdata[5]}<br>%{customdata[6]}<br>Player %{customdata[7]}<extra></extra>",
                    selected={"marker": {"opacity": 1, "size": 9}}, unselected={"marker": {"opacity": .17}},
                ))
        else:
            values = [o["year"] if color_mode == "year" else ("Win" if o["won"] else "Loss") for o in filtered]
            color = values if color_mode == "year" else ["#248A5A" if o["won"] else "#C35A55" for o in filtered]
            projection.add_trace(go.Scattergl(
                x=[o["_x"] for o in filtered], y=[o["_y"] for o in filtered], mode="markers", name="Player-game sample",
                marker={"color": color, "colorscale": "Viridis" if color_mode == "year" else None, "showscale": color_mode == "year", "size": 6, "opacity": .7},
                customdata=[[o["_index"], o["year"], o["character"], o["opponent_character"], o["stage"], o["won"], o["event"], o["player_id"]] for o in filtered],
                hovertemplate="Year %{customdata[1]}<br>%{customdata[2]} vs %{customdata[3]}<br>Stage %{customdata[4]}<br>Won %{customdata[5]}<br>%{customdata[6]}<br>Player %{customdata[7]}<extra></extra>",
                selected={"marker": {"opacity": 1, "size": 9}}, unselected={"marker": {"opacity": .13}},
            ))
        selected_positions = [i for i, o in enumerate(filtered) if o["_index"] in selected_indices]
        if selected_positions:
            for trace in projection.data:
                # Per-character traces use row-local point indexes.
                trace_custom = trace.customdata or []
                trace.selectedpoints = [i for i, value in enumerate(trace_custom) if int(value[0]) in selected_indices]
        projection.update_layout(
            template="plotly_white", height=560, margin={"l": 35, "r": 15, "t": 20, "b": 35},
            dragmode="lasso", clickmode="event+select", legend={"orientation": "h", "y": -0.18},
            xaxis_title=f"PC1 ({explained:.1%} across PC1-PC2)", yaxis_title="PC2", uirevision="projection",
        )

        yearly = Counter((o["year"], o["character"]) for o in filtered)
        timeline = go.Figure()
        timeline_groups = sorted({character for _, character in yearly}, key=lambda c: (-sum(n for (y, ch), n in yearly.items() if ch == c), c))[:10]
        visible_timeline_characters = set(timeline_groups)
        def key_is_selected(year: int, character: str) -> bool:
            if (year, character) in timeline_keys:
                return True
            return character == "Other characters" and any(
                selected_year == year and selected_character not in visible_timeline_characters
                for selected_year, selected_character in timeline_keys
            )

        for group_index, group in enumerate(timeline_groups):
            xs = [year for year in years if low_year <= year <= high_year]
            ys = [yearly.get((year, group), 0) for year in xs]
            timeline.add_trace(go.Scatter(
                x=xs, y=ys, mode="lines+markers", name=group,
                marker={"size": 8, "color": COLORWAY[group_index % len(COLORWAY)]},
                line={"width": 2, "color": COLORWAY[group_index % len(COLORWAY)]},
                customdata=[[year, group] for year in xs],
                hovertemplate="Year %{customdata[0]}<br>%{customdata[1]}: %{y:,} player-game samples<extra></extra>",
            ))
        other_counts = {
            year: sum(count for (y, char), count in yearly.items() if y == year and char not in timeline_groups)
            for year in years if low_year <= year <= high_year
        }
        if any(other_counts.values()):
            xs = list(other_counts)
            timeline.add_trace(go.Scatter(
                x=xs, y=[other_counts[x] for x in xs], mode="lines+markers", name="Other characters",
                marker={"size": 7, "color": "#7A8794"}, line={"width": 1.5, "color": "#7A8794"},
                customdata=[[year, "Other characters"] for year in xs],
                hovertemplate="Year %{customdata[0]}<br>Other characters: %{y:,} samples<extra></extra>",
            ))
        if selected_indices:
            selected_by_year = Counter((o["year"], o["character"]) for o in filtered if o["_index"] in selected_indices)
            for year, char in selected_by_year:
                timeline.add_trace(go.Scatter(
                    x=[year], y=[yearly[(year, char)]], mode="markers", showlegend=False,
                    marker={"size": 15, "symbol": "circle-open", "color": "#111827", "line": {"width": 2}},
                    hoverinfo="skip",
                ))
        timeline_selectedpoints = []
        for trace_index, trace in enumerate(timeline.data):
            if getattr(trace, "customdata", None):
                for point_index, key in enumerate(trace.customdata):
                    if key_is_selected(int(key[0]), str(key[1])):
                        timeline_selectedpoints.append((trace_index, point_index))
        for trace_index, point_index in timeline_selectedpoints:
            trace = timeline.data[trace_index]
            current = list(trace.selectedpoints or [])
            current.append(point_index)
            trace.selectedpoints = current
            trace.selected = {"marker": {"opacity": 1, "size": 11}}
            trace.unselected = {"marker": {"opacity": .25}}
        timeline.update_layout(
            template="plotly_white", height=560, margin={"l": 55, "r": 15, "t": 20, "b": 75},
            dragmode="lasso", clickmode="event+select", legend={"orientation": "h", "y": -0.22},
            xaxis_title="Tournament year (UTC)", yaxis_title="Sampled player-game appearances", uirevision="timeline",
        )

        selected_rows = [o for o in filtered if o["_index"] in selected_indices]
        if selected_rows:
            selected_wins = sum(o["won"] for o in selected_rows)
            headline = f"Selected {len(selected_rows):,} player-game samples | observed game win rate {selected_wins / len(selected_rows):.1%} | years {min(o['year'] for o in selected_rows)}-{max(o['year'] for o in selected_rows)}"
            counts = Counter(o["character"] for o in selected_rows)
            detail = html.Div([
                html.P(headline),
                html.P("Most common characters: " + ", ".join(f"{name} ({count:,})" for name, count in counts.most_common(8))),
                html.Table([
                    html.Thead(html.Tr([html.Th(x) for x in ["Year", "Event", "Player ID", "Character", "Opponent", "Stage", "Result"]])),
                    html.Tbody([
                        html.Tr([html.Td(str(o[key])) for key in ["year", "event", "player_id", "character", "opponent_character", "stage"]] + [html.Td("Win" if o["won"] else "Loss")])
                        for o in selected_rows[:30]
                    ]),
                ], className="details-table"),
                html.P(f"Showing up to 30 of {len(selected_rows):,} selected records."),
            ])
        else:
            headline = f"Showing {len(filtered):,} of {len(observations):,} sampled player-game observations ({low_year}-{high_year}). Select points in either view to link records across projection and time."
            detail = html.P("No samples selected. Use box or lasso selection in either chart; the other chart will highlight matching year-character groups.")

        selection_data = {"indices": sorted(selected_indices), "timeline": [list(x) for x in sorted(timeline_keys)]}
        return projection, timeline, headline, detail, selection_data

    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tournaments", type=Path, default=DEFAULT_TOURNAMENTS, help="Tournament metadata CSV")
    parser.add_argument("--sets", type=Path, default=DEFAULT_SETS, help="Sets CSV containing game_data JSON")
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE, help="Compressed local sample cache")
    parser.add_argument("--sample-size", type=int, default=18_000, help="Number of player-game observations to keep (default: 18000)")
    parser.add_argument("--seed", type=int, default=23, help="Reservoir sample seed")
    parser.add_argument("--rebuild", action="store_true", help="Rebuild sample cache from CSV files")
    parser.add_argument("--host", default="127.0.0.1", help="Dash server host")
    parser.add_argument("--port", type=int, default=8050, help="Dash server port")
    parser.add_argument("--debug", action="store_true", help="Enable Dash debug mode")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    for path in (args.tournaments, args.sets):
        if not path.is_file():
            raise SystemExit(f"Input file not found: {path}")
    if args.sample_size < 500:
        raise SystemExit("--sample-size must be at least 500 for a useful projection.")
    payload = load_or_prepare_cache(args.tournaments, args.sets, args.cache, args.sample_size, args.seed, args.rebuild)
    app = make_app(payload)
    print(f"Open http://{args.host}:{args.port} in a browser. Press Ctrl+C here to stop.")
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
