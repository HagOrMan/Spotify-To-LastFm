# Spotify History → Last.fm

Converts your Spotify streaming history export into scrobbles and uploads them to Last.fm.

## Setup

1. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
2. Create a Last.fm API account at https://www.last.fm/api/account/create to get an **API key** and **shared secret**.
3. Copy `secrets_example.py` to `secrets.py` and fill in `API_KEY` and `SHARED_SECRET`.
4. Get a session key:
   ```
   python authSetup.py
   ```
   Approve access in the browser that opens, press Enter, then paste the printed session key into `SESSION_KEY` in `secrets.py`.

## Usage

1. Request your data from Spotify (Account → Privacy settings → Download your data). Put the `StreamingHistory*.json`, `Streaming_History*.json`, or `endsong_*.json` files in `spotify-data/`.
2. Convert to CSV (written to `output/`):
   ```
   python spotifyHistoryToLastFmCsvConverter.py
   ```
   | Flag | Default | Description |
   |---|---|---|
   | `-t`, `--threshold` | `30000` | Minimum ms played for a track to count |
   | `-s`, `--start_date` | none | Include plays on/after this date (`YYYYMMDD`, UTC) |
   | `-e`, `--end_date` | none | Include plays on/before this date (`YYYYMMDD`, UTC) |
   | `-m`, `--max_scrobbles` | `0` | Split into `output_1.csv`, `output_2.csv`, … of this many rows; `0` writes one `output.csv` |

3. Upload to Last.fm:
   ```
   python sendToLastFm.py
   ```
   | Flag | Default | Description |
   |---|---|---|
   | `-f`, `--file` | `output/output.csv` | CSV to upload |
   | `--no_shift_old` | off | Keep original timestamps for plays older than 14 days |

## Notes

- Last.fm rejects scrobbles older than 14 days. By default, older plays are re-timestamped to recent times (kept in order, spaced by track duration) so they are accepted. Use `--no_shift_old` to keep real timestamps; those plays will be ignored.
- Last.fm has a daily scrobble limit. For large histories, split with `-m` and upload one file per day.
- `secrets.py` and the contents of `spotify-data/` and `output/` are gitignored.
