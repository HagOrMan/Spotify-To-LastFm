import argparse
import csv
import glob
import json
import os
import time
from datetime import datetime, timezone

import pandas as pd

OUTPUT_FOLDER = "output"


def parse_date_arg(date_str: str) -> datetime:
    """Parses a CLI date string in YYYYMMDD format into an aware UTC datetime."""
    try:
        dt = datetime.strptime(date_str, "%Y%m%d")
        return dt.replace(tzinfo=timezone.utc)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"Invalid date format: '{date_str}'. Expected format is YYYYMMDD (e.g., 20260810)."
        )


def parse_spotify_timestamp(ts_raw: str):
    """
    Parses various Spotify timestamp formats into a UTC-aware datetime.
    Supports:
      - Simple format: 'YYYY-MM-DD HH:MM'
      - Extended format: 'YYYY-MM-DDTHH:MM:SSZ'
      - ISO formats with offsets
    """
    if not ts_raw:
        return None

    ts_raw = ts_raw.strip()

    # Try common explicit string patterns first
    patterns = [
        "%Y-%m-%d %H:%M",  # Standard format: 2026-05-03 00:34
        "%Y-%m-%d %H:%M:%S",  # Standard with seconds
        "%Y-%m-%dT%H:%M:%SZ",  # Extended UTC format: 2026-05-03T00:34:00Z
    ]
    for fmt in patterns:
        try:
            return datetime.strptime(ts_raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    # Fallback to ISO-8601
    try:
        normalized_ts = ts_raw[:-1] + "+00:00" if ts_raw.endswith("Z") else ts_raw
        dt = datetime.fromisoformat(normalized_ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser(
        description="Convert Spotify streaming history JSON to CSV for Last.fm import with date filtering."
    )
    parser.add_argument(
        "-t",
        "--threshold",
        type=int,
        default=30000,
        help="Minimum play time in milliseconds to consider a song (default: 30000).",
    )
    parser.add_argument(
        "-m",
        "--max_scrobbles",
        type=int,
        default=0,
        help="Maximum number of scrobbles (rows) per CSV file. If 0, no splitting occurs (default: 0).",
    )
    parser.add_argument(
        "-s",
        "--start_date",
        type=parse_date_arg,
        default=None,
        help="Start date filter (inclusive) in YYYYMMDD format (e.g., 20260501).",
    )
    parser.add_argument(
        "-e",
        "--end_date",
        type=parse_date_arg,
        default=None,
        help="End date filter (inclusive) in YYYYMMDD format (e.g., 20260531). Covers through 23:59:59 UTC.",
    )
    args = parser.parse_args()

    # Expand end date to include the full final day up to 23:59:59.999999 UTC
    end_date_limit = None
    if args.end_date:
        end_date_limit = args.end_date.replace(
            hour=23, minute=59, second=59, microsecond=999999
        )

    print("Starting convert...")
    start_time = time.perf_counter()
    all_rows = []

    # Check both potential Spotify export naming conventions
    input_folder = "spotify-data"
    files = sorted(
        glob.glob(os.path.join(input_folder, "Streaming_History*.json"))
        + glob.glob(os.path.join(input_folder, "StreamingHistory*.json"))
        + glob.glob(os.path.join(input_folder, "endsong_*.json"))
    )
    # Deduplicate in case patterns overlap
    files = list(dict.fromkeys(files))

    if not files:
        print(
            "No matching JSON files found (checked 'Streaming_History*.json', 'StreamingHistory*.json', 'endsong_*.json')."
        )
        return

    for filename in files:
        print(f"Processing file: {filename}")
        try:
            with open(filename, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"Error reading {filename}: {e}")
            continue

        if not isinstance(data, list):
            print(f"Warning: {filename} does not contain a JSON array. Skipping.")
            continue

        for record in data:
            if not isinstance(record, dict):
                continue

            # 1. Play duration check (Supports both msPlayed and ms_played)
            raw_ms = (
                record.get("msPlayed")
                if "msPlayed" in record
                else record.get("ms_played", 0)
            )
            try:
                ms_played = int(raw_ms)
            except (ValueError, TypeError):
                ms_played = 0

            if ms_played < args.threshold:
                continue

            # 2. Timestamp extraction & parsing (Supports endTime and ts)
            ts_raw = record.get("endTime") or record.get("ts") or ""
            record_dt = parse_spotify_timestamp(ts_raw)
            if not record_dt:
                continue

            # Date Range Filter
            if args.start_date and record_dt < args.start_date:
                continue
            if end_date_limit and record_dt > end_date_limit:
                continue

            # Format to standard Last.fm SQL timestamp
            timestamp_str = record_dt.strftime("%Y-%m-%d %H:%M:%S")

            # 3. Track and Artist metadata (Supports standard and extended keys)
            track = (
                record.get("trackName")
                or record.get("master_metadata_track_name")
                or ""
            ).strip()

            artist = (
                record.get("artistName")
                or record.get("master_metadata_album_artist_name")
                or ""
            ).strip()

            if not track or not artist:
                continue

            # 4. Optional fields: Album (Standard export doesn't have album; fallback to empty string)
            album = (record.get("master_metadata_album_album_name") or "").strip()
            album_artist = artist
            duration = str(ms_played // 1000)

            # Last.fm CSV batch format:
            # Artist, Track, Album, Timestamp, Album Artist, Duration
            all_rows.append(
                [artist, track, album, timestamp_str, album_artist, duration]
            )

    total_scrobbles = len(all_rows)
    print(f"Total valid scrobbles collected: {total_scrobbles}")

    if total_scrobbles == 0:
        print("No scrobbles matched your criteria. No CSV files created.")
        return

    csv_columns = ["artist", "track", "album", "timestamp", "album_artist", "duration"]

    if args.max_scrobbles > 0:
        num_files = (total_scrobbles + args.max_scrobbles - 1) // args.max_scrobbles
        for i in range(num_files):
            start_idx = i * args.max_scrobbles
            end_idx = min((i + 1) * args.max_scrobbles, total_scrobbles)
            chunk = all_rows[start_idx:end_idx]

            df = pd.DataFrame(chunk, columns=csv_columns)
            filename = f"output_{i + 1}.csv"
            df.to_csv(
                os.path.join(OUTPUT_FOLDER, filename),
                index=False,
                header=False,
                quoting=csv.QUOTE_ALL,
            )
            print(f"Wrote {filename} with {len(df)} rows.")
    else:
        df = pd.DataFrame(all_rows, columns=csv_columns)
        df.to_csv(
            os.path.join(OUTPUT_FOLDER, "output.csv"),
            index=False,
            header=False,
            quoting=csv.QUOTE_ALL,
        )
        print(f"Wrote output.csv with {len(df)} rows.")

    elapsed = time.perf_counter() - start_time
    print(f"Convert finished in {elapsed:.2f} seconds")


if __name__ == "__main__":
    main()
