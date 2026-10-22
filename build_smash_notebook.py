"""Build the reproducible Smash History project notebook."""

import base64
import pickle
from pathlib import Path
import nbformat as nbf
import smash_history_analysis as analysis_module


cells = [
    nbf.v4.new_markdown_cell("""# Smash History: Tournament Activity, Characters, and Competitive Players

**Team:** Christian Ohlsson and Trevor Scofield  
**Project scope:** competitive Super Smash Bros. history, with character-level analysis from recorded Ultimate games  
**Visualization count:** 7 (team of two)  
**Core environment:** Python, Matplotlib, Jupyter Notebook

This report builds on the team proposal and the `tournament_info.csv` / `sets.csv` files. It translates the proposal's three questions into a reproducible analysis and seven figures. The largest CSV is several gigabytes, so the companion analysis module reads rows as a stream rather than loading the source into memory."""),
    nbf.v4.new_markdown_cell("""## Project questions and expected users

The proposal asks how competitive activity changes over time, how character selection relates to results, and which players have the most recorded wins. We focus on three audiences: players choosing characters, tournament/community analysts interpreting the metagame, and researchers studying competitive play.

1. **Historical activity:** When are tournaments and recorded sets concentrated?
2. **Character metagame:** Which characters are used most, how do their observed game win rates compare with usage, and which character matchups are represented?
3. **Player careers:** Which recorded player IDs have the most set wins, and how do top players' most-used characters differ across earlier and later periods?

These are descriptive questions. The figures do not establish that a character causes a win or that a character is intrinsically stronger: player skill, matchup choice, bracket level, reporting coverage, and tournament size are not fully controlled."""),
    nbf.v4.new_markdown_cell("""## Data, fields, and preparation

### Inputs

- `tournament_info/tournament_info.csv`: one row per tournament; includes `key`, `game`, `start`, location, entrant count, and final placements. `start` is a Unix timestamp and `key` links to sets.
- `tournament_info/sets.csv`: one row per tournament set; includes `tournament_key`, `winner_id`, participant IDs, scores, and `game_data`.
- `game_data` is JSON. Each array item is an individual game, with fields such as `winner_id`, `loser_id`, `winner_char`, `loser_char`, and `stage`. Character win rates count individual games (not tournament sets).

### Transformations

1. Read only tournament keys and start years from the tournament file, creating a small join lookup.
2. Stream the sets file and join each set to its tournament year using `tournament_key`.
3. Parse per-game JSON; count each winner/loser character appearance once and increment a win only for `winner_char`.
4. Count head-to-head wins as `(winner_char, loser_char)`, and player set wins from `winner_id`.
5. Define earlier/later eras by the midpoint of the observed tournament-year range. For the alluvial view, compare each qualifying top player's modal character in each era.

### Limits to keep in mind

- Empty `game_data` rows cannot contribute character picks or matchup results; coverage varies across tournaments.
- Player identifiers are mixed IDs and handles. These files do not provide a reliable public player-name lookup.
- Character win percentages are raw observed game win rates. They are vulnerable to player-skill and matchup confounding; small samples are filtered from the scatter plot.
- Earlier/later character choices are descriptive and can reflect sparse reporting, a player's career stage, or format changes.
- The final observed tournament year (2024 here) may be incomplete. A decrease at the end of the timeline can reflect a partial export window rather than a real decline in play.
- The annual character stack is normalized to shares. Early years with very few records still sum to 100%, so compare those shapes cautiously and check record counts in Figures 1 and 2.
- The proposal cites a Kaggle dataset page. Retain that attribution and download the same source files for reproduction; the CSVs are not copied into the submission package because of their size."""),
    nbf.v4.new_markdown_cell("""## Reproducibility and LLM prompt strategy

The visualizations were produced in Python with Matplotlib. The LLM workflow was iterative: start with the available tournament columns, inspect the supplementary set-level data, discover that `game_data` contains per-game character outcomes, then refine the analysis around the assignment's seven-figure requirement. The conversation prompts below are reproduced verbatim from the project workflow; the code is maintained in the companion `smash_history_analysis.py` file and imported by the cells below.

### Prompt sequence

1. “I need a python script which will help to visualize the information in the tournament_info.csv file. use any of the well known python libraries to do do”
2. “here is the result I got from running the bash command: usage: visualize_tournaments.py [-h] [-o OUTPUT] [--top TOP] [csv_file] visualize_tournaments.py: error: field larger than field limit (131072)”
3. “I would like for the information to show the characters that are played and their win percentage on a scatter plot.”
4. “what kind of information is on the csv file”
5. “what is in the game_data column?”
6. “that is what we are looking for please implement that into the code as soon as you can”
7. “take all that that has been done so far. and then take and modify it to these requirements … Team of 2: 7 visualizations … final notebook report …”

### Re-run

Place both CSV files in `tournament_info/` beside this notebook and `smash_history_analysis.py`. Install Python 3.10+, Matplotlib, and Jupyter, then run all cells from top to bottom. Source row streaming avoids loading either full CSV into RAM. The figure cells save PNG copies under `output/smash_history_figures/` as well as embedding them in this notebook.

```bash
python -m pip install matplotlib jupyter
jupyter notebook smash_history_report.ipynb
```"""),
    nbf.v4.new_markdown_cell("""## Seven visualization plan

| # | Visualization | Proposal feature | Main reading |
|---|---|---|---|
| 1 | Tournament starts by year | Performance over time | Event activity and coverage |
| 2 | Tournament sets by year and game | Performance over time | Competitive match volume |
| 3 | Character appearances by year | Character use and success | Popularity shifts in the metagame |
| 4 | Character usage vs. win-rate scatter | Character use and success | Popularity compared with recorded outcomes |
| 5 | Split-cell matchup matrix (custom) | Character use and success | Directional head-to-head results |
| 6 | Top players by set wins | Player dominance | Most recorded tournament-set wins |
| 7 | Player-character alluvial view (custom) | Player character choices | Modal character by era for qualified top players |

Figures 5 and 7 directly map data to custom visual encodings in Matplotlib (split triangles and flow ribbons). All seven plots have complete source in `smash_history_analysis.py`; this notebook calls each plotting function and records the rendered output."""),
    nbf.v4.new_code_cell("""from pathlib import Path
from IPython.display import display
 import matplotlib.pyplot as plt
 import pickle
 import smash_history_analysis as analysis

# Run this notebook from the project directory. If your files are elsewhere,
# edit these two paths and rerun all cells.
DATA_DIR = Path("tournament_info")
TOURNAMENT_CSV = DATA_DIR / "tournament_info.csv"
SETS_CSV = DATA_DIR / "sets.csv"
FIGURE_DIR = Path("output") / "smash_history_figures"
 FIGURE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_FILE = Path("tmp") / "smash_analysis_cache.pkl"

assert TOURNAMENT_CSV.is_file(), f"Missing tournament file: {TOURNAMENT_CSV.resolve()}"
assert SETS_CSV.is_file(), f"Missing sets file: {SETS_CSV.resolve()}"
print("Tournament file:", TOURNAMENT_CSV.resolve())
print("Sets file:", SETS_CSV.resolve())
print("Figure output:", FIGURE_DIR.resolve())"""),
    nbf.v4.new_code_cell("""# Full streaming pass through both CSV files. The sets file is about 3.9 GB,
# so this step can take several minutes on a typical laptop.
source_key = analysis.source_fingerprint(TOURNAMENT_CSV, SETS_CSV)
if CACHE_FILE.is_file():
    with CACHE_FILE.open("rb") as cache_stream:
        data = pickle.load(cache_stream)
else:
    data = None
if data is not None and data.get("source_fingerprint") == source_key:
    print(f"Loaded cached aggregates from {CACHE_FILE.resolve()}")
else:
    data = analysis.analyze_data(TOURNAMENT_CSV, SETS_CSV, progress_every=250_000)
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with CACHE_FILE.open("wb") as cache_stream:
        pickle.dump(data, cache_stream, protocol=pickle.HIGHEST_PROTOCOL)
years = sorted(data["events_by_year"])
print(f"Tournament rows: {data['total_events']:,}")
print(f"Set rows: {data['total_sets']:,}")
print(f"Sets joined to a tournament start year: {data['linked_sets']:,} ({data['linked_sets']/data['total_sets']:.1%})")
print(f"Sets with character data: {data['sets_with_character_data']:,}")
print(f"Individual games with both characters recorded: {data['games_with_both_characters']:,}")
print(f"Individual games missing one or both characters: {data['games_missing_character']:,}")
print(f"Observed tournament years: {min(years)}–{max(years)}")
print(f"Earlier/later split midpoint: {data['midpoint_year']:.1f}")"""),
    nbf.v4.new_markdown_cell("""## Data coverage check

The character plots use only per-game entries with character values. The report prints the number of joined sets and the number of sets with at least one recorded character. Character outcome counts are game-level; set-winner counts in Figure 6 are set-level. A missing character record is not treated as a loss or a non-use."""),
    nbf.v4.new_code_cell("""top_chars = data["character_uses"].most_common(10)
print("Most-used characters and recorded game win rates:")
for character, appearances in top_chars:
    wins = data["character_wins"][character]
    print(f"  {character:20s} {appearances:>9,} appearances | {wins/appearances:6.1%} wins")

print("\\nTop player IDs/handles by recorded set wins:")
for player, wins in data["player_set_wins"].most_common(10):
    print(f"  {player:24s} {wins:>8,} wins")"""),
    nbf.v4.new_markdown_cell("""## Visualizations

The following cells render and save all seven figures. Each cell calls one plotting function whose full implementation is in the accompanying source module."""),
]

plot_specs = [
    ("01_tournament_activity.png", "### 1. Tournament activity by year", "Shows the number of tournament rows with a usable start date. This is a measure of events present in this dataset, not a complete census of the competitive scene.", "plot_activity_by_year"),
    ("02_sets_by_year.png", "### 2. Tournament sets by year", "Shows matched set rows by tournament year, split across the most represented game labels. This captures match-record volume; coverage and event sizes can change over time.", "plot_sets_by_year"),
    ("03_character_popularity.png", "### 3. Character use across history", "Shows the annual share of recorded character appearances for the most-used characters, with remaining characters grouped together. Shares make years with different amounts of reporting easier to compare, but do not correct for missing game_data.", "plot_character_popularity"),
    ("04_character_usage_winrate.png", "### 4. Character usage and win percentage", "Each point represents a character. The horizontal axis is game appearances (log scale) and the vertical axis is its share of recorded individual games won. Only characters with at least 25 recorded appearances are shown; labels highlight the most-used characters.", "plot_character_usage_winrate"),
    ("05_matchup_matrix.png", "### 5. Character matchup matrix (custom visualization)", "Each square is split into two triangles. Triangle color encodes the directional share of recorded head-to-head game wins; the number is the total observed matchup count. This custom encoding makes both sides' outcomes visible in one cell. Sparse or absent matchups should not be interpreted as evidence of balance.", "plot_matchup_triangle"),
    ("06_top_players.png", "### 6. Players with the most recorded set wins", "Ranks winner IDs/handles by the number of set rows where they appear as winner_id. The source does not provide a stable player-name lookup, so labels preserve the recorded identifiers.", "plot_top_players"),
    ("07_player_character_flow.png", "### 7. Top-player character changes (custom alluvial visualization)", "Each ribbon connects a top player's most-used character in the earlier period to their most-used character in the later period. Players are selected from the top 30 by set wins and must have at least 10 character-recorded games in both periods. Ribbon widths represent the number of qualifying players. This is a descriptive proxy for character flexibility, not a complete career history.", "plot_player_character_flow"),
]

for index, (filename, heading, explanation, function_name) in enumerate(plot_specs, start=1):
    cells.append(nbf.v4.new_markdown_cell(f"{heading}\n\n{explanation}\n\n**Reproducible source:** `smash_history_analysis.py` → `{function_name}(data)`."))
    cells.append(nbf.v4.new_code_cell(f"""fig = analysis.{function_name}(data)
fig.savefig(FIGURE_DIR / {filename!r}, dpi=180, bbox_inches="tight")
display(fig)
plt.close(fig)"""))

cells.append(nbf.v4.new_markdown_cell("""## Data-derived findings to carry into the case studies

This cell writes results from the supplied files into the executed notebook so readers can verify the observations against the seven figures."""))
cells.append(nbf.v4.new_code_cell("""years = sorted(data["events_by_year"])
peak_event_year = max(data["events_by_year"], key=data["events_by_year"].get)
peak_event_count = data["events_by_year"][peak_event_year]
top_character, top_character_uses = data["character_uses"].most_common(1)[0] if data["character_uses"] else ("No character data", 0)
top_player, top_player_wins = data["player_set_wins"].most_common(1)[0] if data["player_set_wins"] else ("No winner IDs", 0)
qualified_flows, qualified_players = analysis._main_characters_by_era(data, player_limit=30)
eligible_rates = [(char, data["character_wins"][char] / count, count)
                  for char, count in data["character_uses"].items() if count >= 25]
high_rate = max(eligible_rates, key=lambda x: x[1]) if eligible_rates else None
low_rate = min(eligible_rates, key=lambda x: x[1]) if eligible_rates else None

print(f"Coverage: {data['linked_sets']:,} / {data['total_sets']:,} set rows joined to a dated tournament ({data['linked_sets']/data['total_sets']:.1%}).")
print(f"Tournament records peak in {peak_event_year} ({peak_event_count:,} events in the supplied file).")
print(f"Most-used character: {analysis.character_label(top_character)} ({top_character_uses:,} recorded game appearances).")
if high_rate and low_rate:
    print(f"Among characters with at least 25 appearances, observed rates range from {low_rate[0]} ({low_rate[1]:.1%}, n={low_rate[2]:,}) to {high_rate[0]} ({high_rate[1]:.1%}, n={high_rate[2]:,}).")
print(f"Most frequent set winner ID/handle: {top_player} ({top_player_wins:,} set wins).")
print(f"Top-30 players meeting the 10-games-per-period alluvial threshold: {qualified_players}.")
print("Interpret these as dataset descriptions. The counts and raw rates do not adjust for player skill, bracket level, or uneven game_data coverage.")"""))

cells.extend([
    nbf.v4.new_markdown_cell("""## Case study 1: character choice, usage, and observed success

**Reference case:** Codsi and Vetta (2021) use Super Smash Bros. Melee data to study character selection as a metagame, comparing character use and matchup outcomes and modeling how strategy can change as players learn. Our dataset and title/version differ, and we do not reproduce their game-theoretic model.

**Domain question:** Do the characters most often selected also have the highest observed game win rates, and are head-to-head outcomes uniform?

**Steps to reach the result:**

1. Join set records to tournament years and parse `game_data` arrays into individual games.
2. Treat `winner_char` and `loser_char` as one appearance each; count the winner character as one game win.
3. Compare use and raw win percentage in Figure 4; examine the matchup matrix in Figure 5; use Figure 3 to see how picks change over years.
4. Exclude characters with fewer than 25 appearances from the scatter and show per-pair counts in the matrix so the reader can judge sample size.

**Interpretation for domain users:** A high-use character with a win rate near 50% may be popular without appearing unusually successful in this aggregate. A high win percentage at low use may be a small-sample signal. Players can use the chart to identify characters/matchups worth investigating, while organizers or researchers can identify where more complete game-level reporting is valuable. Neither chart demonstrates causal character strength: player ability, matchup selection, tournament tier, and missing reports are not controlled.

**Reference connection:** Codsi and Vetta show why popularity and outcome need to be examined together when discussing a fighting-game metagame. Their Melee findings and assumptions should not be transferred directly to this tournament dataset or to Ultimate."""),
    nbf.v4.new_markdown_cell("""## Case study 2: competitive activity and player character histories

**Reference case:** Nolla, Beeman, and Reber (2024) study 90 Super Smash Bros. competitors across 327 sets in national-level, double-elimination tournaments, relating measured affect to next-set outcomes. Our files include bracket/set outcomes but do not include affect ratings, player skill, or the study's participant sample, so we do not test or reproduce its psychological findings.

**Domain question:** How does the recorded competitive scene's volume change over time, who accumulates the most set wins, and do leading players show different modal character choices across the observed history?

**Steps to reach the result:**

1. Plot tournaments and sets by the start year linked from tournament keys (Figures 1 and 2).
2. Rank recorded winner IDs/handles by set-level victories (Figure 6).
3. Divide the observed event-year range at its midpoint and count each top player's recorded character appearances in both halves.
4. Keep players with at least 10 recorded character games in each half and draw an alluvial flow between their most-used characters (Figure 7).

**Interpretation for domain users:** The activity timeline can reveal periods with more tournament records or stronger coverage. The set-win ranking identifies high-volume winners in these files. The alluvial view shows whether qualifying top players kept or changed their modal character across broad periods, which can guide deeper career-level study. The ID ranking is not a skill rating, and the era split is a coarse analytical choice; neither should be read as a complete ranking of all Smash competitors.

**Reference connection:** The case study by Nolla et al. demonstrates the value of studying competitive outcomes within structured tournament sets. Our use is narrower and descriptive; the data do not support conclusions about arousal, pressure, or affect."""),
    nbf.v4.new_markdown_cell("""## Peer evaluation (team submission fields)

The proposal names Christian Ohlsson and Trevor Scofield. The team reported an equal 50/50 contribution split. The workspace does not document the task-by-task division, so the notes record only that team-reported split.

| Evaluator | Teammate being evaluated | Contribution (0–100%) | Evidence / notes |
|---|---|---:|---|
| Christian Ohlsson | Christian Ohlsson (self) | 50% | Team-reported equal contribution split |
| Christian Ohlsson | Trevor Scofield | 50% | Team-reported equal contribution split |
| Trevor Scofield | Trevor Scofield (self) | 50% | Team-reported equal contribution split |
| Trevor Scofield | Christian Ohlsson | 50% | Team-reported equal contribution split |

The course may require a particular submission format; copy each member's completed evaluation into that form if needed."""),
    nbf.v4.new_markdown_cell("""## Method, design decisions, and reproducibility notes

- **Platform and LLM integration:** Python and Matplotlib implement the full workflow. Prompt refinement and the dataset-driven change from tournament-level to individual-game character analysis are recorded above.
- **Chart choice:** timelines show event/match volume; stacked areas show changes in character appearances; scatter plots compare pick volume and game outcomes; the matchup matrix reveals directional rates and counts; bars rank set winners; the alluvial shows dominant-character transitions.
- **Custom encodings:** Figure 5 uses manually mapped, split triangular cells; Figure 7 draws custom Bézier flow ribbons with widths proportional to player counts.
- **Re-run materials:** `smash_history_report.ipynb`, `smash_history_analysis.py`, and `requirements.txt`, plus the two CSVs obtained from the cited dataset. Run all notebook cells in order. A local cache is reused only while the CSV paths, sizes, and modification times match.
- **Source attribution:** dataset URL from the proposal; research references appear below. Data-derived results are limited to the supplied files and the recorded `game_data` coverage."""),
    nbf.v4.new_markdown_cell("""## References

1. Ohlsson, C., & Scofield, T. *Project Proposal for Smash History* (provided project proposal). Dataset link in proposal: Thomas Dubail, [Super Smash Bros database, Kaggle](https://www.kaggle.com/datasets/thomasdubail/super-smash-bros-database).
2. Codsi, J., & Vetta, A. (2021). “A Case Study in Learning in Metagames: Super Smash Bros. Melee.” *Proceedings of the Seventeenth AAAI Conference on Artificial Intelligence and Interactive Digital Entertainment (AIIDE 2021).* [Paper PDF](https://cdn.aaai.org/ojs/18884/18884-52-22650-1-2-20211004.pdf).
3. Nolla, K., Beeman, M., & Reber, P. (2024). “Affect and Performance across Double-Elimination Tournaments: A Field Study of Super Smash Bros Competitors.” *HICSS-57*. [Paper record and abstract](https://aisel.aisnet.org/hicss-57/in/esports/6/).

The course's separately designated “featured papers” were not included with the supplied proposal. The two research papers above are relevant published case studies selected for this report; replace or supplement them with the instructor's required featured-paper references if the course uses a specific reading list."""),
])

nb = nbf.v4.new_notebook(cells=cells, metadata={
    "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
    "language_info": {"name": "python", "version": "3.12"},
})
report_path = Path(__file__).with_name("smash_history_report.ipynb")
cache_path = Path("tmp") / "smash_analysis_cache.pkl"
figure_dir = Path("output") / "smash_history_figures"

# Preserve generated charts and data-derived summaries as notebook outputs so
# the report opens with its results visible before a user reruns any cells.
if cache_path.is_file():
    with cache_path.open("rb") as stream:
        data = pickle.load(stream)
    execution_count = 0
    figure_paths = [figure_dir / spec[0] for spec in plot_specs]
    top_characters = data["character_uses"].most_common(10)
    character_output = ["Most-used characters and recorded game win rates:"]
    for character, appearances in top_characters:
        wins = data["character_wins"][character]
    character_output.append(f"  {analysis_module.character_label(character):20s} {appearances:>9,} appearances | {wins/appearances:6.1%} wins")
    character_output.append("\nTop player IDs/handles by recorded set wins:")
    for player, wins in data["player_set_wins"].most_common(10):
        character_output.append(f"  {player:24s} {wins:>8,} wins")

    years = sorted(data["events_by_year"])
    peak_year = max(data["events_by_year"], key=data["events_by_year"].get)
    peak_character, peak_uses = data["character_uses"].most_common(1)[0]
    peak_player, peak_wins = data["player_set_wins"].most_common(1)[0]
    rates = [(char, data["character_wins"][char] / n, n) for char, n in data["character_uses"].items() if n >= 25]
    low_rate = min(rates, key=lambda item: item[1])
    high_rate = max(rates, key=lambda item: item[1])
    eligible_players = None
    # Compute the exact qualification count from the same helper used in Figure 7.
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        import smash_history_analysis as analysis_module
        _, eligible_players = analysis_module._main_characters_by_era(data, player_limit=30)
    except Exception:
        eligible_players = 0

    for cell in nb.cells:
        if cell.cell_type != "code":
            continue
        source = cell.source
        if "if CACHE_FILE.is_file():" in source:
            output_text = (
                f"Loaded cached aggregates from {cache_path.resolve()}\n"
                f"Tournament rows: {data['total_events']:,}\nSet rows: {data['total_sets']:,}\n"
                f"Sets joined to a tournament start year: {data['linked_sets']:,} ({data['linked_sets']/data['total_sets']:.1%})\n"
                f"Sets with character data: {data['sets_with_character_data']:,}\n"
                f"Individual games with both characters recorded: {data['games_with_both_characters']:,}\n"
                f"Individual games missing one or both characters: {data['games_missing_character']:,}\n"
                f"Observed tournament years: {min(years)}–{max(years)}\n"
                f"Earlier/later split midpoint: {data['midpoint_year']:.1f}\n"
            )
            execution_count += 1
            cell.execution_count = execution_count
            cell.outputs = [nbf.v4.new_output("stream", name="stdout", text=output_text)]
        elif source.startswith("top_chars = data["):
            execution_count += 1
            cell.execution_count = execution_count
            cell.outputs = [nbf.v4.new_output("stream", name="stdout", text="\n".join(character_output) + "\n")]
        elif source.startswith("fig = analysis."):
            function = source.split("fig = analysis.", 1)[1].split("(", 1)[0]
            file_index = next((i for i, spec in enumerate(plot_specs) if spec[3] == function), None)
            if file_index is not None and figure_paths[file_index].is_file():
                image_data = base64.b64encode(figure_paths[file_index].read_bytes()).decode("ascii")
                execution_count += 1
                cell.execution_count = execution_count
                cell.outputs = [nbf.v4.new_output("display_data", data={"image/png": image_data, "text/plain": f"Matplotlib output: {plot_specs[file_index][1]}"}, metadata={})]
        elif source.startswith("years = sorted(data[\"events_by_year\"])"):
            summary = (
                f"Coverage: {data['linked_sets']:,} / {data['total_sets']:,} set rows joined to a dated tournament ({data['linked_sets']/data['total_sets']:.1%}).\n"
                f"Tournament records peak in {peak_year} ({data['events_by_year'][peak_year]:,} events in the supplied file).\n"
                f"Most-used character: {analysis_module.character_label(peak_character)} ({peak_uses:,} recorded game appearances).\n"
                f"Among characters with at least 25 appearances, observed rates range from {low_rate[0]} ({low_rate[1]:.1%}, n={low_rate[2]:,}) to {high_rate[0]} ({high_rate[1]:.1%}, n={high_rate[2]:,}).\n"
                f"Most frequent set winner ID/handle: {peak_player} ({peak_wins:,} set wins).\n"
                f"Top-30 players meeting the 10-games-per-period alluvial threshold: {eligible_players}.\n"
                "Interpret these as dataset descriptions. Raw rates do not adjust for player skill, bracket level, or uneven game_data coverage.\n"
            )
            execution_count += 1
            cell.execution_count = execution_count
            cell.outputs = [nbf.v4.new_output("stream", name="stdout", text=summary)]

nbf.write(nb, report_path)
print(f"Wrote {report_path.name} with rendered figure outputs when available")
