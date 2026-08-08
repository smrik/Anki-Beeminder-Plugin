import datetime
import unittest

from metrics import (
    anki_day_datestr,
    day_start_ms,
    get_deck_id,
    get_backlog,
    get_minutes_today,
    get_new_cards_today,
    get_reviews_today,
)


class FakeDatabase:
    def __init__(self, values):
        self.values = list(values)
        self.calls = []

    def scalar(self, sql, *params):
        self.calls.append((sql, params))
        return self.values.pop(0)


class FakeDecks:
    def __init__(self, decks):
        self.decks = decks

    def by_name(self, name):
        return self.decks.get(name)


class FakeScheduler:
    def __init__(self, day_cutoff):
        self.day_cutoff = day_cutoff


class FakeCollection:
    def __init__(self, *, day_cutoff, values=(), decks=None, due_cards=()):
        self.sched = FakeScheduler(day_cutoff)
        self.db = FakeDatabase(values)
        self.decks = FakeDecks(decks or {})
        self.due_cards = list(due_cards)

    def find_cards(self, query):
        self.last_find_query = query
        return self.due_cards


class MetricsTests(unittest.TestCase):
    def test_reviews_today_uses_anki_day_cutoff(self):
        cutoff = 1_800_000_000
        collection = FakeCollection(day_cutoff=cutoff, values=[3])

        self.assertEqual(get_reviews_today(collection), 3)
        self.assertEqual(
            collection.db.calls[0][1], ((cutoff - 86400) * 1000,)
        )
        self.assertIn("FROM revlog", collection.db.calls[0][0])

    def test_reviews_today_filters_cards_by_deck(self):
        cutoff = 1_800_000_000
        collection = FakeCollection(
            day_cutoff=cutoff,
            values=[2],
            decks={"German": {"id": 17}},
        )

        self.assertEqual(get_reviews_today(collection, "German"), 2)
        sql, params = collection.db.calls[0]
        self.assertIn("JOIN cards", sql)
        self.assertEqual(params, ((cutoff - 86400) * 1000, 17))

    def test_missing_deck_returns_zero_without_querying_database(self):
        collection = FakeCollection(day_cutoff=1_800_000_000, decks={})

        self.assertEqual(get_reviews_today(collection, "Missing"), 0)
        self.assertEqual(collection.db.calls, [])

    def test_other_existing_metrics_keep_their_collection_semantics(self):
        cutoff = 1_800_000_000
        new_cards = FakeCollection(day_cutoff=cutoff, values=[4])
        study_time = FakeCollection(day_cutoff=cutoff, values=[125000])
        backlog = FakeCollection(day_cutoff=cutoff, due_cards=[1, 2, 3])

        self.assertEqual(get_new_cards_today(new_cards), 4)
        self.assertEqual(get_minutes_today(study_time), 2.1)
        self.assertEqual(get_backlog(backlog), 3)
        self.assertEqual(backlog.last_find_query, "is:due or is:learn")

    def test_day_string_uses_the_collection_cutoff_and_requested_timezone(self):
        day_start = datetime.datetime(
            2026, 8, 8, 1, 0, tzinfo=datetime.timezone.utc
        ).timestamp()
        collection = FakeCollection(day_cutoff=day_start + 86400)

        self.assertEqual(
            anki_day_datestr(collection, "Europe/Ljubljana"), "2026-08-08"
        )

    def test_deck_lookup_returns_id_or_none(self):
        collection = FakeCollection(
            day_cutoff=1_800_000_000,
            decks={"German": {"id": 17}},
        )

        self.assertEqual(get_deck_id(collection, "German"), 17)
        self.assertIsNone(get_deck_id(collection, ""))
        self.assertIsNone(get_deck_id(collection, "Missing"))

    def test_day_start_is_in_milliseconds(self):
        cutoff = 1_800_000_000

        self.assertEqual(day_start_ms(FakeCollection(day_cutoff=cutoff)), (cutoff - 86400) * 1000)


if __name__ == "__main__":
    unittest.main()
