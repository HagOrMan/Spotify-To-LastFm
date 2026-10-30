# Spotify History → Last.fm

Converts your Spotify streaming history export into scrobbles and uploads them to Last.fm.

Have you ever wanted to get day-to-day metrics on your listening? Are you already on Last.fm but Spotify disconnected and left you with weeks, or even months of missed data? Worry no longer, for this codebase has everything you need to fill in your data.

Some fun things you can do:

- Get your entire listening history from Spotify to LastFm
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

## Notes

- Last.fm rejects scrobbles older than 14 days. By default, older plays are re-timestamped to recent times (kept in order, spaced by track duration) so they are accepted. Use `--no_shift_old` to keep real timestamps; those plays will likely be ignored.
- Last.fm has a daily scrobble limit. For large histories, split with `-m` and upload one file per day. My command for ensuring it didn't go over the limit and filtered for a given date range, March 10 to April 21 in 2026, was `python spotifyHistoryToLastFmCsvConverter.py -m 2500 -s 20260310 -e 20260421`
- `secrets.py` and the contents of `spotify-data/` and `output/` are gitignored.
