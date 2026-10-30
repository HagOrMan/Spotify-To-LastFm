import argparse
import csv
import hashlib
import os
import time
from datetime import datetime, timezone
from secrets import API_KEY, SESSION_KEY, SHARED_SECRET

import requests

API_URL = "https://ws.audioscrobbler.com/2.0/"

# Default behavior: change to False if you want unshifted by default without flags
SHIFT_OLD_TIMESTAMPS_DEFAULT = True


def get_signature(params: dict, secret: str) -> str:
    """Computes the Last.fm MD5 API signature."""
    sorted_keys = sorted(params.keys())
    sig_string = "".join(f"{k}{params[k]}" for k in sorted_keys if k != "format")
    sig_string += secret
    return hashlib.md5(sig_string.encode("utf-8")).hexdigest()


def to_unix_timestamp(ts_str: str) -> int:
    """Converts 'YYYY-MM-DD HH:MM:SS' into an integer Unix epoch timestamp."""
    dt = datetime.strptime(ts_str.strip(), "%Y-%m-%d %H:%M:%S")
    return int(dt.replace(tzinfo=timezone.utc).timestamp())


def scrobble_batch(batch_rows: list):
    """
    Submits a batch of up to 50 tracks to track.scrobble.
    batch_rows: list of dicts with keys: artist, track, album, timestamp, duration
    """
    params = {
        "method": "track.scrobble",
        "api_key": API_KEY,
        "sk": SESSION_KEY,
    }

    # Last.fm indexes batched items as artist[0], track[0], timestamp[0], etc.
    for i, item in enumerate(batch_rows):
        params[f"artist[{i}]"] = item["artist"]
        params[f"track[{i}]"] = item["track"]
        params[f"timestamp[{i}]"] = str(item["timestamp"])

        if item.get("album"):
            params[f"album[{i}]"] = item["album"]
        if item.get("duration") and item["duration"] != "0":
            params[f"duration[{i}]"] = str(item["duration"])

    # Sign the payload
    params["api_sig"] = get_signature(params, SHARED_SECRET)
    params["format"] = "json"

    # POST payload
    response = requests.post(API_URL, data=params)
    return response.json()


def prepare_scrobble_records(all_rows: list, shift_old: bool) -> list:
    """
    Converts raw CSV rows into prepared dictionaries.
    If shift_old is True, tracks older than 14 days have their timestamps
    remapped toward the current time so they are accepted by Last.fm.
    """
    now = int(time.time())
    # 14 days in seconds = 14 * 86400 = 1,209,600 seconds
    # Use 13.5 days (1,166,400s) as the cutoff boundary to avoid border race conditions
    cutoff_boundary = now - (13 * 86400 + 43200)

    prepared = []
    for row in all_rows:
        artist, track, album, ts_str, _, duration = row
        unix_ts = to_unix_timestamp(ts_str)
        prepared.append(
            {
                "artist": artist,
                "track": track,
                "album": album,
                "original_ts": unix_ts,
                "timestamp": unix_ts,
                "duration": duration,
            }
        )

    if not shift_old:
        return prepared

    # Identify tracks falling past the 14-day limit
    old_indices = [
        idx
        for idx, item in enumerate(prepared)
        if item["original_ts"] < cutoff_boundary
    ]

    if not old_indices:
        print(
            "All records fall within the 14-day window. No timestamp shifting required."
        )
        return prepared

    print(
        f"Found {len(old_indices)} tracks older than 14 days. Shifting timestamps forward to recent dates..."
    )

    # We shift timestamps by calculating a synthetic window ending roughly 10 minutes ago
    # spaced backwards sequentially by each track's duration (or 3 minutes if missing).
    # This prevents stacking 1,000 songs onto the exact same second, which Last.fm would reject as spam.
    current_synthetic_time = now - 600

    # Walk backwards through old tracks to preserve chronological playback ordering
    for idx in reversed(old_indices):
        item = prepared[idx]
        item["timestamp"] = current_synthetic_time

        try:
            dur = int(item["duration"])
            step = dur if dur > 30 else 180
        except (ValueError, TypeError):
            step = 180

        current_synthetic_time -= step

    return prepared


def main():
    parser = argparse.ArgumentParser(
        description="Upload Last.fm scrobbles from CSV via API with automatic 14-day timestamp shifting."
    )
    parser.add_argument(
        "--file",
        "-f",
        type=str,
        default=os.path.join("output", "output.csv"),
        help="Path to CSV scrobble file (default: output.csv).",
    )
    parser.add_argument(
        "--no_shift_old",
        action="store_true",
        help="Disable default behavior: do not alter timestamps older than 14 days (records will likely be ignored by Last.fm).",
    )
    args = parser.parse_args()

    # Default is True unless --no_shift_old flag is passed
    shift_old = False if args.no_shift_old else SHIFT_OLD_TIMESTAMPS_DEFAULT

    with open(args.file, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        all_rows = [row for row in reader if row]

    total_scrobbles = len(all_rows)
    print(f"Loaded {total_scrobbles} scrobbles from {args.file}")
    print(f"Timestamp shift enabled: {shift_old}")

    prepared_records = prepare_scrobble_records(all_rows, shift_old=shift_old)

    batch_size = 50
    for i in range(0, total_scrobbles, batch_size):
        batch = prepared_records[i : i + batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = (total_scrobbles + batch_size - 1) // batch_size
        print(f"Scrobbling batch {batch_num}/{total_batches} ({len(batch)} tracks)...")

        result = scrobble_batch(batch)

        if "scrobbles" in result:
            attr = result["scrobbles"].get("@attr", {})
            accepted = attr.get("accepted", 0)
            ignored = attr.get("ignored", 0)
            print(f"  -> Result: {accepted} accepted, {ignored} ignored.")
        else:
            print(f"  -> API Error on batch {batch_num}: {result}")

        # Pause to respect Last.fm rate limits
        time.sleep(1)

    print("Finished uploading!")


if __name__ == "__main__":
    main()
