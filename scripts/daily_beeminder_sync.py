"""Read a local Anki collection and upsert ``reviews_today`` to Beeminder."""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from metrics import anki_day_datestr, get_reviews_today


class WorkerError(RuntimeError):
    """An expected, user-actionable daily-worker failure."""


@dataclass(frozen=True)
class WorkerConfig:
    """Credentials and non-secret settings for one local-worker invocation."""

    collection_path: Path
    beeminder_user: str
    beeminder_token: str
    beeminder_goal: str
    deck_filter: str | None
    timezone: str


REQUIRED_ENV = (
    "ANKI_COLLECTION_PATH",
    "BEEMINDER_USER",
    "BEEMINDER_TOKEN",
    "BEEMINDER_GOAL",
)


def load_config(environment: Mapping[str, str] | None = None) -> WorkerConfig:
    """Load and validate local-worker settings from environment variables."""
    environment = os.environ if environment is None else environment
    missing = [name for name in REQUIRED_ENV if not environment.get(name)]
    if missing:
        raise WorkerError("Missing required environment variables: " + ", ".join(missing))

    return WorkerConfig(
        collection_path=Path(environment["ANKI_COLLECTION_PATH"].strip()).expanduser(),
        beeminder_user=environment["BEEMINDER_USER"].strip(),
        beeminder_token=environment["BEEMINDER_TOKEN"],
        beeminder_goal=environment["BEEMINDER_GOAL"].strip(),
        deck_filter=environment.get("ANKI_DECK_FILTER", "").strip() or None,
        timezone=environment.get("ANKI_TIMEZONE", "Europe/Ljubljana").strip()
        or "Europe/Ljubljana",
    )


def _request_id(goal: str, anki_day: str) -> str:
    raw_request_id = f"anki-{goal}-{anki_day}"
    return re.sub(r"[^a-zA-Z0-9_-]", "-", raw_request_id)


def build_datapoint_payload(
    config: WorkerConfig, value: int | float, anki_day: str
) -> dict[str, float | str]:
    """Build the idempotent Beeminder datapoint form payload."""
    return {
        "auth_token": config.beeminder_token,
        "value": float(value),
        "comment": "Auto-sync from Anki (reviews_today) via Linux self-hosted worker",
        "requestid": _request_id(config.beeminder_goal, anki_day),
    }


def _beeminder_url(config: WorkerConfig) -> str:
    user = urllib.parse.quote(config.beeminder_user, safe="")
    goal = urllib.parse.quote(config.beeminder_goal, safe="")
    return f"https://www.beeminder.com/api/v1/users/{user}/goals/{goal}/datapoints.json"


def post_beeminder(
    config: WorkerConfig,
    value: int | float,
    anki_day: str,
    *,
    urlopen: Callable | None = None,
) -> int:
    """POST one datapoint and raise ``WorkerError`` for non-success responses."""
    payload = build_datapoint_payload(config, value, anki_day)
    request = urllib.request.Request(
        _beeminder_url(config),
        data=urllib.parse.urlencode(payload).encode("utf-8"),
        method="POST",
        headers={"User-Agent": "AnkiBeeminderLinuxWorker/1.0"},
    )
    opener = urllib.request.urlopen if urlopen is None else urlopen

    try:
        with opener(request, timeout=15) as response:
            status = int(response.status)
    except urllib.error.HTTPError as error:
        raise WorkerError(f"Beeminder API returned HTTP {error.code}") from error
    except urllib.error.URLError as error:
        raise WorkerError("Beeminder API request failed") from error
    except OSError as error:
        raise WorkerError("Beeminder API request failed") from error

    if status not in (200, 201):
        raise WorkerError(f"Beeminder API returned HTTP {status}")
    return status


def snapshot_collection(source_path: str | Path, snapshot_path: str | Path) -> None:
    """Create a consistent read-only SQLite snapshot of an Anki collection."""
    source = Path(source_path).expanduser()
    target = Path(snapshot_path).expanduser()
    if not source.is_file():
        raise WorkerError(f"Anki collection not found: {source}")

    target.parent.mkdir(parents=True, exist_ok=True)
    source_uri = f"{source.resolve().as_uri()}?mode=ro"
    try:
        with closing(sqlite3.connect(source_uri, uri=True)) as source_db:
            source_db.execute("PRAGMA query_only = 1")
            with closing(sqlite3.connect(target)) as target_db:
                source_db.backup(target_db)
                target_db.commit()
    except sqlite3.Error as error:
        raise WorkerError(f"Could not snapshot Anki collection: {source}") from error


def _default_collection_factory():
    try:
        from anki.collection import Collection
    except ImportError as error:
        raise WorkerError(
            "The headless Anki package is unavailable; install requirements-worker.txt"
        ) from error
    return Collection


def run(
    config: WorkerConfig,
    *,
    dry_run: bool = False,
    collection_factory: Callable | None = None,
    snapshotter: Callable[[str | Path, str | Path], None] = snapshot_collection,
    urlopen: Callable | None = None,
    output: Callable[[str], None] = print,
) -> int:
    """Read one local Anki snapshot and optionally write its metric to Beeminder."""
    factory = _default_collection_factory() if collection_factory is None else collection_factory
    with tempfile.TemporaryDirectory(prefix="anki-beeminder-") as temporary_directory:
        snapshot_path = Path(temporary_directory) / "collection.anki2"
        snapshotter(config.collection_path, snapshot_path)
        collection = factory(str(snapshot_path))
        try:
            value = get_reviews_today(collection, config.deck_filter)
            anki_day = anki_day_datestr(collection, config.timezone)
            payload = build_datapoint_payload(config, value, anki_day)

            if dry_run:
                output(
                    "dry-run: "
                    f"reviews_today={value} anki_day={anki_day} "
                    f"requestid={payload['requestid']}"
                )
                return value

            status = post_beeminder(
                config,
                value,
                anki_day,
                urlopen=urlopen,
            )
            output(
                f"synced: reviews_today={value} anki_day={anki_day} "
                f"beeminder_http={status}"
            )
            return value
        finally:
            collection.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="calculate the metric without writing to Beeminder",
    )
    parser.add_argument(
        "--collection-path",
        help="override ANKI_COLLECTION_PATH for this invocation",
    )
    args = parser.parse_args(argv)

    try:
        if args.collection_path:
            environment = dict(os.environ)
            environment["ANKI_COLLECTION_PATH"] = args.collection_path
            config = load_config(environment)
        else:
            config = load_config()
        run(config, dry_run=args.dry_run)
    except WorkerError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    except Exception as error:
        print(
            f"ERROR: daily sync failed ({type(error).__name__})",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
