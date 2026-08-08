"""Sync an ephemeral AnkiWeb collection and upsert reviews_today to Beeminder."""

from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from metrics import anki_day_datestr, get_reviews_today


class WorkerError(RuntimeError):
    """An expected, user-actionable daily-worker failure."""


@dataclass(frozen=True)
class WorkerConfig:
    """Credentials and non-secret settings for one worker invocation."""

    ankiweb_username: str
    ankiweb_password: str
    beeminder_user: str
    beeminder_token: str
    beeminder_goal: str
    deck_filter: str | None
    timezone: str


REQUIRED_ENV = (
    "ANKIWEB_USERNAME",
    "ANKIWEB_PASSWORD",
    "BEEMINDER_USER",
    "BEEMINDER_TOKEN",
    "BEEMINDER_GOAL",
)


def load_config(environment: Mapping[str, str] | None = None) -> WorkerConfig:
    """Load and validate worker settings from environment variables."""
    environment = os.environ if environment is None else environment
    missing = [name for name in REQUIRED_ENV if not environment.get(name)]
    if missing:
        raise WorkerError("Missing required environment variables: " + ", ".join(missing))

    return WorkerConfig(
        ankiweb_username=environment["ANKIWEB_USERNAME"],
        ankiweb_password=environment["ANKIWEB_PASSWORD"],
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
        "comment": "Auto-sync from Anki (reviews_today) via GitHub Actions",
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
        headers={"User-Agent": "AnkiBeeminderGitHubActions/1.0"},
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


def _sync_state_matches(result, name: str) -> bool:
    required = getattr(result, "required", None)
    if required is None:
        return False

    descriptor = getattr(type(result), "DESCRIPTOR", None)
    fields_by_name = getattr(descriptor, "fields_by_name", {})
    required_field = fields_by_name.get("required")
    enum_type = getattr(required_field, "enum_type", None)
    values_by_name = getattr(enum_type, "values_by_name", {})
    enum_value = values_by_name.get(name)
    if enum_value is not None and required == getattr(enum_value, "number", None):
        return True

    expected = [
        getattr(result, name, None),
        getattr(type(result), name, None),
    ]
    if any(value is not None and required == value for value in expected):
        return True
    return str(getattr(required, "name", "")).upper() == name


def _default_collection_factory():
    try:
        from anki.collection import Collection
    except ImportError as error:
        raise WorkerError(
            "The headless Anki package is unavailable; install requirements-worker.txt"
        ) from error
    return Collection


def sync_collection(
    config: WorkerConfig,
    collection_path: str | Path,
    *,
    collection_factory: Callable | None = None,
):
    """Open and sync a temporary collection from AnkiWeb without media."""
    factory = _default_collection_factory() if collection_factory is None else collection_factory
    collection = factory(str(collection_path))
    try:
        auth = collection.sync_login(
            config.ankiweb_username,
            config.ankiweb_password,
            endpoint=None,
        )
        result = collection.sync_collection(auth, sync_media=False)

        if _sync_state_matches(result, "FULL_DOWNLOAD"):
            collection.close_for_full_sync()
            collection.full_upload_or_download(
                auth=auth,
                server_usn=None,
                upload=False,
            )
            collection.reopen(after_full_sync=True)
        elif _sync_state_matches(result, "FULL_UPLOAD"):
            raise WorkerError(
                "AnkiWeb requested a full upload; refusing to upload from an empty runner collection"
            )
        elif _sync_state_matches(result, "FULL_SYNC"):
            raise WorkerError(
                "AnkiWeb reported a full-sync conflict; refusing to choose upload or download automatically"
            )
        return collection
    except WorkerError:
        try:
            collection.close()
        except Exception:
            pass
        raise
    except Exception as error:
        try:
            collection.close()
        except Exception:
            pass
        raise WorkerError("AnkiWeb sync failed") from error


def run(
    config: WorkerConfig,
    *,
    dry_run: bool = False,
    collection_factory: Callable | None = None,
    urlopen: Callable | None = None,
    output: Callable[[str], None] = print,
) -> int:
    """Run one temporary AnkiWeb sync and optional Beeminder write."""
    with tempfile.TemporaryDirectory(prefix="anki-beeminder-") as temporary_directory:
        collection_path = Path(temporary_directory) / "collection.anki2"
        collection = sync_collection(
            config,
            collection_path,
            collection_factory=collection_factory,
        )
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
        help="sync and calculate the metric without writing to Beeminder",
    )
    args = parser.parse_args(argv)

    try:
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
