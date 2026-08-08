"""Shared Anki collection metrics used by the add-on and daily worker."""

from __future__ import annotations

import datetime
from zoneinfo import ZoneInfo


def day_start_ms(collection) -> int:
    """Return the current Anki day start as a Unix timestamp in milliseconds."""
    return int((collection.sched.day_cutoff - 86400) * 1000)


def anki_day_datestr(collection, timezone_name: str | None = None) -> str:
    """Return the collection's current Anki day as ``YYYY-MM-DD``."""
    if collection is None:
        return datetime.date.today().isoformat()

    day_start_ts = collection.sched.day_cutoff - 86400
    if timezone_name:
        timezone = ZoneInfo(timezone_name)
        return datetime.datetime.fromtimestamp(
            day_start_ts, tz=timezone
        ).date().isoformat()
    return datetime.datetime.fromtimestamp(day_start_ts).strftime("%Y-%m-%d")


def get_deck_id(collection, deck_name: str | None):
    """Return a deck ID, or ``None`` when the name is empty or unknown."""
    if not deck_name:
        return None
    deck = collection.decks.by_name(deck_name)
    return deck["id"] if deck else None


def get_reviews_today(collection, deck_filter: str | None = None) -> int:
    """Count review answers recorded during the collection's current Anki day."""
    start_ms = day_start_ms(collection)
    if deck_filter:
        deck_id = get_deck_id(collection, deck_filter)
        if deck_id is None:
            return 0
        return int(
            collection.db.scalar(
                "SELECT count() FROM revlog r JOIN cards c ON r.cid = c.id "
                "WHERE r.id > ? AND c.did = ?",
                start_ms,
                deck_id,
            )
            or 0
        )
    return int(
        collection.db.scalar("SELECT count() FROM revlog WHERE id > ?", start_ms)
        or 0
    )


def get_new_cards_today(collection, deck_filter: str | None = None) -> int:
    """Count new-card review answers during the collection's current Anki day."""
    start_ms = day_start_ms(collection)
    if deck_filter:
        deck_id = get_deck_id(collection, deck_filter)
        if deck_id is None:
            return 0
        return int(
            collection.db.scalar(
                "SELECT count() FROM revlog r JOIN cards c ON r.cid = c.id "
                "WHERE r.id > ? AND r.type = 0 AND c.did = ?",
                start_ms,
                deck_id,
            )
            or 0
        )
    return int(
        collection.db.scalar(
            "SELECT count() FROM revlog WHERE id > ? AND type = 0", start_ms
        )
        or 0
    )


def get_backlog(collection, deck_filter: str | None = None) -> int:
    """Count cards currently due or learning, optionally restricted to a deck."""
    query = (
        f'"deck:{deck_filter}" (is:due or is:learn)'
        if deck_filter
        else "is:due or is:learn"
    )
    return len(collection.find_cards(query))


def get_minutes_today(collection, deck_filter: str | None = None) -> float:
    """Return review time in minutes during the collection's current Anki day."""
    start_ms = day_start_ms(collection)
    if deck_filter:
        deck_id = get_deck_id(collection, deck_filter)
        if deck_id is None:
            return 0
        total_ms = (
            collection.db.scalar(
                "SELECT sum(time) FROM revlog r JOIN cards c ON r.cid = c.id "
                "WHERE r.id > ? AND c.did = ?",
                start_ms,
                deck_id,
            )
            or 0
        )
    else:
        total_ms = (
            collection.db.scalar("SELECT sum(time) FROM revlog WHERE id > ?", start_ms)
            or 0
        )
    return round(total_ms / 1000 / 60, 1)
