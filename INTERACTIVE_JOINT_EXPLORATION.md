# Interactive Joint Exploration

## Launch

From the project folder, install the project requirements once:

```powershell
python -m pip install -r requirements.txt
```

Then start the app:

```powershell
python interactive_joint_exploration.py
```

On the first run, the app streams `tournament_info/tournament_info.csv` and `tournament_info/sets.csv`. This can take a while because the sets file is several gigabytes. It saves a compressed, reproducible sample at `output/interactive_joint_sample.json.gz`; later launches reuse that cache when source paths, file sizes, modification times, sample size, and seed still match.

Open `http://127.0.0.1:8050` in a browser. Stop the server with Ctrl+C in the terminal.

If the CSVs are stored elsewhere, pass their locations:

```powershell
python interactive_joint_exploration.py --tournaments "D:\data\tournament_info.csv" --sets "D:\data\sets.csv"
```

To regenerate the cache, change the sample size, or use another random seed:

```powershell
python interactive_joint_exploration.py --rebuild --sample-size 24000 --seed 23
```

## Interaction

- The PCA projection represents sampled individual player-games. Hover a point for tournament, player ID, character, opponent, stage, and result.
- Use the box or lasso tool on either chart. Selecting points in the projection highlights their year/character groups in the timeline. Selecting timeline markers highlights matching records in the projection.
- The year-range slider and character filter update both views together. Projection color can show year, character, or game result.
- The details area summarizes the active selection and lists up to 30 matching samples. Clear selections to return to the filtered overview.

## Data and method

The code joins tournament start year and entrant count to sets by tournament key. It parses `game_data` and creates one observation per player-side per game only when both players' character labels are available. A uniform reservoir sample of at most 18,000 observations is used by default, so the browser remains responsive. The default seed is 23 and is recorded in cache metadata. Use `--rebuild` to force a new scan; otherwise matching cache metadata avoids rescanning the source.

PCA uses standardized year and log entrant count plus centered one-hot indicators for character, opponent character, and the 24 most common sample stages; other stages are grouped. The first two principal components provide the projection. Win/loss is deliberately excluded from the projection and is shown only as color or in the record details. The timeline aggregates the same sampled observations by year and character, displaying the ten most common filtered characters and grouping the rest; it does not claim to show all games in the source.

Projection proximity is an exploratory description of these selected features. It does not measure player skill, prove that a character causes wins, or correct for missing character records, player-skill differences, and uneven tournament coverage. The dashboard reports sample size and character-label missingness among linked, parsed games to keep those limits visible.
