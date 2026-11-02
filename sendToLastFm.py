import argparse
import csv
import hashlib
import json
import math
import os
import time
from datetime import datetime, timezone
from secrets import API_KEY, SESSION_KEY, SHARED_SECRET

import requests

API_URL = "https://ws.audioscrobbler.com/2.0/"

# Default behavior: change to False if you want unshifted by default without flags
SHIFT_OLD_TIMESTAMPS_DEFAULT = True

# Spacing used for shifted tracks whose play time is missing or implausibly short
DEFAULT_STEP_SECONDS = 180

# Service offline, temporarily unavailable, rate limit exceeded
RETRYABLE_ERRORS = {11, 16, 29}
MAX_ATTEMPTS = 3

DAILY_LIMIT_IGNORED_CODE = "5"

BATCH_SIZE = 50

# Rows timestamp-shifted together. Big enough to cover a day's uploads, small enough
# (~7 days of listening) to fit the 14-day window at real spacing.
SHIFT_CHUNK_ROWS = 3000

# Commonly reported Last.fm daily cap; only used for estimates when a run doesn't hit it
ESTIMATED_DAILY_LIMIT = 2800

PROGRESS_FILE = "upload_progress.json"


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


def post_with_retries(params: dict) -> dict:
    """POSTs to the API, retrying network failures and transient Last.fm errors with backoff."""
    reason = ""
    for attempt in range(MAX_ATTEMPTS):
        try:
            result = requests.post(API_URL, data=params, timeout=30).json()
            if result.get("error") not in RETRYABLE_ERRORS:
                return result
            reason = f"Last.fm error {result['error']}: {result.get('message')}"
        except (requests.RequestException, ValueError) as e:
            reason = str(e)

        if attempt < MAX_ATTEMPTS - 1:
            delay = 10 * 2**attempt
            print(f"  -> {reason}. Retrying in {delay}s...")
            time.sleep(delay)

    return {
        "error": None,
        "message": f"Gave up after {MAX_ATTEMPTS} attempts: {reason}",
    }


def scrobble_batch(batch_rows: list) -> dict:
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

    return post_with_retries(params)


def first_daily_limit_index(scrobbles: dict):
    """Returns the in-batch index of the first track ignored for the daily limit, or None."""
    items = scrobbles.get("scrobble", [])
    # Last.fm returns a bare object instead of a list when the batch has one track
    if isinstance(items, dict):
        items = [items]
    for idx, item in enumerate(items):
        code = (item.get("ignoredMessage") or {}).get("code")
        if str(code) == DAILY_LIMIT_IGNORED_CODE:
            return idx
    return None


def playback_step(duration) -> int:
    """Seconds between a shifted track and the next one, based on how long it played."""
    try:
        dur = int(duration)
    except (ValueError, TypeError):
        return DEFAULT_STEP_SECONDS
    return dur if dur > 30 else DEFAULT_STEP_SECONDS


def prepare_scrobble_records(all_rows: list, shift_old: bool) -> list:
    """
    Converts raw CSV rows into prepared dictionaries.
    If shift_old is True, tracks older than 14 days have their timestamps
    remapped toward the current time so they are accepted by Last.fm.
    Rows must be in chronological order.
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

    # Old tracks are laid out in order, ending roughly 10 minutes ago and spaced by
    # each track's play time. If that doesn't fit between the cutoff and now, the
    # spacing is compressed so no track lands outside the window Last.fm accepts.
    window_end = now - 600
    steps = [playback_step(prepared[idx]["duration"]) for idx in old_indices]
    # The newest track sits at window_end, so its own step takes up no room
    needed = sum(steps[:-1])
    available = window_end - cutoff_boundary

    scale = 1.0
    if needed > available:
        scale = available / needed
        avg_gap = available / max(len(old_indices) - 1, 1)
        print(
            f"  Warning: {len(old_indices)} tracks don't fit in the 14-day window at real "
            f"spacing; compressing to an average of {avg_gap:.0f}s apart."
        )

    synthetic_time = float(window_end)
    prepared[old_indices[-1]]["timestamp"] = window_end
    for idx, step in zip(reversed(old_indices[:-1]), reversed(steps[:-1])):
        synthetic_time -= step * scale
        prepared[idx]["timestamp"] = int(synthetic_time)

    return prepared


def load_progress() -> dict:
    """Reads saved upload positions, keyed by CSV path."""
    if not os.path.exists(PROGRESS_FILE):
        return {}
    with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_progress(progress: dict, key: str, next_row: int, total_rows: int):
    """Records where the upload for this CSV should pick up next time."""
    progress[key] = {
        "next_row": next_row,
        "total_rows": total_rows,
        "last_run": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    tmp_path = PROGRESS_FILE + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(progress, f, indent=2)
    # Swap in whole so an interrupted run can't leave a half-written progress file
    os.replace(tmp_path, PROGRESS_FILE)


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
    parser.add_argument(
        "--start_row",
        "-r",
        type=int,
        default=None,
        help=f"Row of the CSV to start from, overriding the position saved in {PROGRESS_FILE}.",
    )
    args = parser.parse_args()

    # Default is True unless --no_shift_old flag is passed
    shift_old = False if args.no_shift_old else SHIFT_OLD_TIMESTAMPS_DEFAULT

    with open(args.file, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        all_rows = [row for row in reader if row]

    total_rows = len(all_rows)
    print(f"Loaded {total_rows} songs from {args.file}")
    print(f"Timestamp shift enabled: {shift_old}")

    progress = load_progress()
    progress_key = os.path.normpath(args.file)
    saved = progress.get(progress_key)

    if saved:
        last_run = datetime.fromisoformat(saved["last_run"])
        hours_since = (datetime.now(timezone.utc) - last_run).total_seconds() / 3600
        print(f"Last upload from this file was {hours_since:.1f} hours ago.")
        if hours_since < 24:
            print(
                "  Warning: Last.fm's daily limit may not have reset yet. Trying anyway..."
            )

    if args.start_row is not None:
        start_row = args.start_row
    elif saved:
        if saved["total_rows"] != total_rows:
            print(
                f"{args.file} has {total_rows} songs, but the saved progress was for "
                f"{saved['total_rows']}. The file may have been regenerated, so the saved "
                f"position can't be trusted."
            )
            print(
                f"Pass --start_row to choose where to start, or remove its entry from {PROGRESS_FILE}."
            )
            return
        start_row = saved["next_row"]
    else:
        start_row = 0

    if start_row >= total_rows:
        print(f"All {total_rows} songs in {args.file} have already been uploaded.")
        return

    print(f"Starting from song {start_row + 1} of {total_rows}")

    next_row = start_row
    stop_reason = None
    while next_row < total_rows and stop_reason is None:
        chunk = all_rows[next_row : next_row + SHIFT_CHUNK_ROWS]
        prepared_records = prepare_scrobble_records(chunk, shift_old=shift_old)

        for i in range(0, len(prepared_records), BATCH_SIZE):
            batch = prepared_records[i : i + BATCH_SIZE]
            print(
                f"Scrobbling songs {next_row + 1}-{next_row + len(batch)} of {total_rows}..."
            )

            result = scrobble_batch(batch)

            if "scrobbles" not in result:
                print(f"  -> API Error: {result}")
                stop_reason = "error"
                break

            scrobbles = result["scrobbles"]
            attr = scrobbles.get("@attr", {})
            accepted = attr.get("accepted", 0)
            ignored = attr.get("ignored", 0)
            print(f"  -> Result: {accepted} accepted, {ignored} ignored.")

            limit_idx = first_daily_limit_index(scrobbles)
            if limit_idx is not None:
                print("Hit Last.fm's daily scrobble limit.")
                next_row += limit_idx
                stop_reason = "limit"
                break

            next_row += len(batch)
            save_progress(progress, progress_key, next_row, total_rows)

            # Pause to respect Last.fm rate limits
            time.sleep(1)

    save_progress(progress, progress_key, next_row, total_rows)

    sent = next_row - start_row
    remaining = total_rows - next_row
    print(f"Sent {sent} songs this run.")
    if remaining == 0:
        print(f"Finished uploading! All {total_rows} songs from {args.file} are done.")
        return

    per_day = sent if stop_reason == "limit" and sent > 0 else ESTIMATED_DAILY_LIMIT
    days = math.ceil(remaining / per_day)
    print(
        f"{remaining} songs to go, estimated {days} more day(s) at ~{per_day} per day."
    )
    if stop_reason == "error":
        print(f"Stopped on an API error. Run again to retry from song {next_row + 1}.")
    else:
        print("Run this again tomorrow to pick up where it left off.")


if __name__ == "__main__":
    main()
