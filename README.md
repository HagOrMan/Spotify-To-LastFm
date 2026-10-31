# Spotify History → Last.fm

Converts your Spotify streaming history export into scrobbles and uploads them to Last.fm.

Have you ever wanted to get day-to-day metrics on your listening? Are you already on Last.fm but Spotify disconnected and left you with weeks, or even months of missed data? Worry no longer, for this codebase has everything you need to fill in your data.

Some fun things you can do:

- Get your entire listening history from Spotify to LastFm (see [Uploading your entire history](#uploading-your-entire-history))
- Filter for specific days in your listening history when Last.fm missed your scrobbles

## Exporting Spotify data

1. Go to https://www.spotify.com/account/privacy/ and scroll to **Download your data**.
2. Pick one or both:
   - **Account data**: covers the past year only. Usually ready within about 5 days. Use the `StreamingHistory_music_*.json` files from the `Spotify Account Data` folder.
   - **Extended streaming history**: covers your whole account history and includes album names. Can take up to 30 days. Use the `Streaming_History_Audio_*.json` files from the `Spotify Extended Streaming History` folder.
3. Click **Request data** and confirm via the email Spotify sends.
4. When the download link arrives by email, unzip it and copy the JSON files above into `spotify-data/`.

Use one export or the other, not both. They overlap, so using both would upload duplicate scrobbles.

## Setup

1. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
2. Create a Last.fm API account at https://www.last.fm/api/account/create to get an **API key** and **shared secret**.
   1. Fill in "Application Name", leave Callback URL and the rest blank.
   2. Submit the form and you should get a page showing your details.
3. Copy `secrets_example.py` to `secrets.py` and fill in `API_KEY` and `SHARED_SECRET`.
4. Get a session key:
   ```
   python authSetup.py
   ```
   Approve access in the browser that opens, press Enter, then paste the printed session key into `SESSION_KEY` in `secrets.py`.

## Usage

1. Put your exported JSON files in `spotify-data/` (see [Exporting Spotify data](#exporting-spotify-data)).
2. Convert to CSV (written to `output/`):

   ```
   python spotifyHistoryToLastFmCsvConverter.py
   ```

   | Flag                    | Default | Description                                                                                 |
   | ----------------------- | ------- | ------------------------------------------------------------------------------------------- |
   | `-t`, `--threshold`     | `30000` | Minimum ms played for a track to count                                                      |
   | `-s`, `--start_date`    | none    | Include plays on/after this date (`YYYYMMDD`, UTC)                                          |
   | `-e`, `--end_date`      | none    | Include plays on/before this date (`YYYYMMDD`, UTC)                                         |
   | `-m`, `--max_scrobbles` | `0`     | Split into `output_1.csv`, `output_2.csv`, … of this many rows; `0` writes one `output.csv` |

3. Upload to Last.fm:
   ```
   python sendToLastFm.py
   ```
   | Flag             | Default             | Description                                           |
   | ---------------- | ------------------- | ----------------------------------------------------- |
   | `-f`, `--file`   | `output/output.csv` | CSV to upload                                         |
   | `--no_shift_old` | off                 | Keep original timestamps for plays older than 14 days |
   | `-r`, `--start_row` | saved progress   | Row to start from, overriding the position saved in `upload_progress.json` |

   The uploader sends songs in batches of 50 until it finishes the file or hits Last.fm's daily limit, saving its position in `upload_progress.json` as it goes. Run the same command again later and it picks up where it left off.

## Notes

- Last.fm rejects scrobbles older than 14 days. By default, older plays are re-timestamped to recent times (kept in order, spaced by track duration) so they are accepted. Use `--no_shift_old` to keep real timestamps; those plays will likely be ignored.
- Songs are re-timestamped 3,000 at a time, which fits the 14-day window at real spacing.
- Last.fm has a daily scrobble limit (commonly reported as about 2,800). When an upload hits it, the uploader stops, saves its position and estimates how many days are left. Progress is tracked per CSV, so splitting with `-m` still works if you prefer smaller files. My command for ensuring it didn't go over the limit and filtered for a given date range, March 10 to April 21 in 2026, was `python spotifyHistoryToLastFmCsvConverter.py -m 2500 -s 20260310 -e 20260421`
- `secrets.py`, `upload_progress.json` and the contents of `spotify-data/` and `output/` are gitignored.

## Uploading your entire history

A full history can be hundreds of thousands of plays, and Last.fm only accepts a few thousand a day, so this is a daily routine that can run for weeks or months. Get comfortable.

1. Request the **Extended streaming history** export (see [Exporting Spotify data](#exporting-spotify-data)) and put its JSON files in `spotify-data/`.
2. Convert everything once:

   ```
   python spotifyHistoryToLastFmCsvConverter.py
   ```

   This writes every play to `output/output.csv`, oldest first.

3. Run the uploader once a day with the same command, every day:

   ```
   python sendToLastFm.py
   ```

   - **Day 1:** starts from song 1 and keeps sending until Last.fm's daily limit stops it, e.g. `Sent 2800 songs this run. 97200 songs to go, estimated 35 more day(s) at ~2800 per day.`
   - **Day 2:** reads `upload_progress.json`, prints `Starting from song 2801 of 100000` and carries on.
   - **Every day after:** same command, until it prints `Finished uploading!`

   If you run it again too soon, it warns that the daily limit may not have reset and tries anyway; any songs Last.fm refuses are retried on the next run. If an API error stops a run, run it again and it retries from where it stopped.

   Don't regenerate `output.csv` partway through. The saved position is a row number, so the uploader refuses to continue if the file's row count changes. Use `--start_row` to set the position yourself if you need to.

Older plays are re-timestamped to land in the last 14 days, so on Last.fm your full history shows up as recent listening rather than on the dates you actually played it. Total play counts per artist, album and track still come out right.
