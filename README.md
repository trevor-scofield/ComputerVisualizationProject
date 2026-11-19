# Smash History Visualizations

This project explores competitive Super Smash Bros. tournament activity, character use and results, and player histories. It includes a Jupyter report with seven static visualizations and a separate interactive app that links a PCA projection of game records to a timeline.

## 1. Get the project files ready

Place the two source CSV files in the `tournament_info` folder:

```text
tournament_info/
├── tournament_info.csv
└── sets.csv
```

The interactive exploration reads per-game character, opponent, stage, and result fields from the `game_data` column in `sets.csv`, and joins tournament dates and entrant counts from `tournament_info.csv`.

## 2. Install Python dependencies

From the project root in PowerShell, create a virtual environment and install the packages:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

If `py -3` is unavailable, use your installed Python command in its place. Keep using `.venv\Scripts\python.exe` below so the project uses the environment where the requirements were installed.

## 3. Start the interactive joint exploration

```powershell
.\.venv\Scripts\python.exe interactive_joint_exploration.py
```

Open [http://127.0.0.1:8050](http://127.0.0.1:8050) in a browser. Stop the app with **Ctrl+C** in the PowerShell window.

The first run scans the source CSVs, which takes time because `sets.csv` contains millions of rows and `game_data` must be parsed. It creates a compressed sample cache at `output/interactive_joint_sample.json.gz`. Later launches reuse the cache when the source paths, sizes, modification times, sample size, and random seed still match. Use `--rebuild` to rescan and replace the sample.

In the app:

- Adjust the year range or choose characters to filter both views.
- Use box or lasso selection in the PCA projection or timeline to link selected records across views.
- Hover over projection points for game and tournament details; use the result color option to distinguish wins and losses.
- Use **Clear selections** to clear linked selections while keeping filters.

The PCA uses year, entrant count, character, opponent character, and stage features. It excludes win/loss from the projection; outcomes are available only for color and record details. The timeline is calculated from the same fixed-size sample, so its counts represent sampled player-game records rather than every source game. See [INTERACTIVE_JOINT_EXPLORATION.md](INTERACTIVE_JOINT_EXPLORATION.md) for the feature mapping, caveats, command-line options, and additional detail.

### Run with CSV files elsewhere

Pass the CSV paths explicitly:

```powershell
.\.venv\Scripts\python.exe interactive_joint_exploration.py `
  --tournaments "D:\data\tournament_info.csv" `
  --sets "D:\data\sets.csv"
```

For example, to create a larger sample and refresh the cache:

```powershell
.\.venv\Scripts\python.exe interactive_joint_exploration.py --rebuild --sample-size 24000 --seed 23
```

## 4. Generate the seven static figures

```powershell
.\.venv\Scripts\python.exe visualize_tournaments.py
```

The seven PNGs are saved under `output/smash_history_figures/`. This command reads and analyzes the source CSVs each time it runs. To use a different location:

```powershell
.\.venv\Scripts\python.exe visualize_tournaments.py "D:\data\tournament_info.csv" `
  --sets "D:\data\sets.csv" `
  --output-dir "D:\results\smash_history_figures"
```

## 5. Open the notebook report

```powershell
.\.venv\Scripts\python.exe -m jupyter notebook smash_history_report.ipynb
```

The notebook documents the research questions, data preparation, seven figures, case studies, peer evaluation, and the interactive joint exploration. Run cells in order if you want to regenerate the analysis and outputs.

## Project files

| File or folder | Purpose |
|---|---|
| `interactive_joint_exploration.py` | Interactive PCA and timeline app |
| `INTERACTIVE_JOINT_EXPLORATION.md` | Detailed interactive-app method and CLI reference |
| `assets/interactive_joint_exploration.css` | Styling for the Dash app |
| `visualize_tournaments.py` | Generates seven static PNG visualizations |
| `smash_history_analysis.py` | Streaming CSV analysis and Matplotlib chart code |
| `smash_history_report.ipynb` | Notebook report with seven embedded figures and methodology |
| `requirements.txt` | Python dependencies |
| `tournament_info/` | Source CSV files (not included in version control) |
| `output/` | Generated figures and local interactive sample cache |

## Interpretation notes

The projection is a descriptive map of the selected features, not a player skill rating. Character results are not adjusted for skill, matchup selection, event level, or incomplete reporting. The sampled time view should not be read as a full-data count. The notebook and interactive guide discuss these limitations in more detail.
