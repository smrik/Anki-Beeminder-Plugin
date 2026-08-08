import io
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from scripts.daily_beeminder_sync import (
    WorkerConfig,
    WorkerError,
    build_datapoint_payload,
    load_config,
    post_beeminder,
    run,
    snapshot_collection,
)


class FakeDatabase:
    def scalar(self, sql, *params):
        return 4


class FakeDecks:
    def by_name(self, name):
        return None


class FakeScheduler:
    day_cutoff = 1_800_086_400


class FakeCollection:
    def __init__(self, path, events):
        self.path = path
        self.events = events
        self.sched = FakeScheduler()
        self.db = FakeDatabase()
        self.decks = FakeDecks()

    def close(self):
        self.events.append(("close",))


class FakeResponse:
    def __init__(self, status, body=b"{}"):
        self.status = status
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return self.body


def complete_environment(
    collection_path="/var/lib/anki-beeminder/sync/collection.anki2",
):
    return {
        "ANKI_COLLECTION_PATH": collection_path,
        "BEEMINDER_USER": "beeminder-user",
        "BEEMINDER_TOKEN": "token",
        "BEEMINDER_GOAL": "anki-reviews",
        "ANKI_TIMEZONE": "Europe/Ljubljana",
    }


def make_sqlite_collection() -> tuple[tempfile.TemporaryDirectory, Path]:
    temporary_directory = tempfile.TemporaryDirectory()
    collection_path = Path(temporary_directory.name) / "collection.anki2"
    with closing(sqlite3.connect(collection_path)) as database:
        database.execute("CREATE TABLE marker (value TEXT NOT NULL)")
        database.execute("INSERT INTO marker VALUES ('source')")
        database.commit()
    return temporary_directory, collection_path


class WorkerTests(unittest.TestCase):
    def test_load_config_requires_beeminder_credentials_and_collection(self):
        with self.assertRaisesRegex(WorkerError, "ANKI_COLLECTION_PATH"):
            load_config({})

    def test_load_config_defaults_to_all_decks_and_ljubljana(self):
        config = load_config(complete_environment())

        self.assertEqual(
            config.collection_path,
            Path("/var/lib/anki-beeminder/sync/collection.anki2"),
        )
        self.assertIsNone(config.deck_filter)
        self.assertEqual(config.timezone, "Europe/Ljubljana")

    def test_payload_uses_one_request_id_per_anki_day(self):
        config = WorkerConfig(
            collection_path=Path("/tmp/collection.anki2"),
            beeminder_user="beeminder-user",
            beeminder_token="token",
            beeminder_goal="anki-reviews",
            deck_filter=None,
            timezone="Europe/Ljubljana",
        )

        payload = build_datapoint_payload(config, 4, "2026-08-08")

        self.assertEqual(payload["value"], 4.0)
        self.assertEqual(payload["requestid"], "anki-anki-reviews-2026-08-08")
        self.assertIn("Linux", payload["comment"])

    def test_snapshot_collection_copies_source_without_modifying_it(self):
        temporary_directory, source_path = make_sqlite_collection()
        self.addCleanup(temporary_directory.cleanup)
        snapshot_path = Path(temporary_directory.name) / "snapshot.anki2"

        snapshot_collection(source_path, snapshot_path)

        with closing(sqlite3.connect(snapshot_path)) as database:
            value = database.execute("SELECT value FROM marker").fetchone()[0]
        self.assertEqual(value, "source")
        self.assertTrue(source_path.exists())

    def test_snapshot_collection_rejects_missing_source(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            missing_path = Path(temporary_directory) / "missing.anki2"
            snapshot_path = Path(temporary_directory) / "snapshot.anki2"

            with self.assertRaisesRegex(WorkerError, "collection not found"):
                snapshot_collection(missing_path, snapshot_path)

    def test_post_beeminder_rejects_non_success_response(self):
        config = load_config(complete_environment())

        with self.assertRaisesRegex(WorkerError, "HTTP 500"):
            post_beeminder(
                config,
                4,
                "2026-08-08",
                urlopen=lambda request, timeout: FakeResponse(500, b"failure"),
            )

    def test_dry_run_reads_local_snapshot_without_posting(self):
        temporary_directory, collection_path = make_sqlite_collection()
        self.addCleanup(temporary_directory.cleanup)
        events = []
        output = io.StringIO()

        value = run(
            load_config(complete_environment(str(collection_path))),
            dry_run=True,
            collection_factory=lambda path: FakeCollection(path, events),
            urlopen=lambda request, timeout: self.fail("dry-run made an HTTP request"),
            output=lambda message: print(message, file=output),
        )

        self.assertEqual(value, 4)
        self.assertIn("dry-run", output.getvalue())
        self.assertIn("reviews_today=4", output.getvalue())
        self.assertIn(("close",), events)

    def test_normal_run_posts_one_datapoint_from_local_snapshot(self):
        temporary_directory, collection_path = make_sqlite_collection()
        self.addCleanup(temporary_directory.cleanup)
        events = []
        requests = []

        def urlopen(request, timeout):
            requests.append((request, timeout))
            return FakeResponse(201)

        value = run(
            load_config(complete_environment(str(collection_path))),
            collection_factory=lambda path: FakeCollection(path, events),
            urlopen=urlopen,
        )

        self.assertEqual(value, 4)
        self.assertEqual(len(requests), 1)
        self.assertIn(b"requestid=anki-anki-reviews-", requests[0][0].data)
        self.assertIn(("close",), events)


if __name__ == "__main__":
    unittest.main()
