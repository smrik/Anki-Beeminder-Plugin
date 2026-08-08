import io
import unittest
from contextlib import redirect_stdout

from scripts.daily_beeminder_sync import (
    WorkerConfig,
    WorkerError,
    build_datapoint_payload,
    load_config,
    post_beeminder,
    run,
    sync_collection,
)


class FakeDatabase:
    def scalar(self, sql, *params):
        return 4


class FakeDecks:
    def by_name(self, name):
        return None


class FakeScheduler:
    day_cutoff = 1_800_086_400


class FakeSyncResult:
    required = None


class FakeEnumValue:
    def __init__(self, number):
        self.number = number


class FakeEnumType:
    values_by_name = {
        "FULL_SYNC": FakeEnumValue(2),
        "FULL_DOWNLOAD": FakeEnumValue(3),
        "FULL_UPLOAD": FakeEnumValue(4),
    }


class FakeRequiredField:
    enum_type = FakeEnumType()


class FakeSyncDescriptor:
    fields_by_name = {"required": FakeRequiredField()}


class FullDownloadSyncResult:
    # Anki 26.5's ChangesRequired enum assigns FULL_DOWNLOAD = 3.
    DESCRIPTOR = FakeSyncDescriptor()
    required = 3


class FullUploadSyncResult:
    # Anki 26.5's ChangesRequired enum assigns FULL_UPLOAD = 4.
    DESCRIPTOR = FakeSyncDescriptor()
    required = 4


class FullSyncConflictResult:
    # Anki 26.5's ChangesRequired enum assigns FULL_SYNC = 2.
    DESCRIPTOR = FakeSyncDescriptor()
    required = 2


class FakeCollection:
    def __init__(self, path, events):
        self.path = path
        self.events = events
        self.sched = FakeScheduler()
        self.db = FakeDatabase()
        self.decks = FakeDecks()

    def sync_login(self, username, password, endpoint=None):
        self.events.append(("login", username, password, endpoint))
        return "auth"

    def sync_collection(self, auth, sync_media=False):
        self.events.append(("sync", auth, sync_media))
        return FakeSyncResult()

    def close(self):
        self.events.append(("close",))


class FullDownloadCollection(FakeCollection):
    def sync_collection(self, auth, sync_media=False):
        self.events.append(("sync", auth, sync_media))
        return FullDownloadSyncResult()

    def close_for_full_sync(self):
        self.events.append(("close_for_full_sync",))

    def full_upload_or_download(self, **kwargs):
        self.events.append(("full_upload_or_download", kwargs))

    def reopen(self, **kwargs):
        self.events.append(("reopen", kwargs))


class FullUploadCollection(FakeCollection):
    def sync_collection(self, auth, sync_media=False):
        self.events.append(("sync", auth, sync_media))
        return FullUploadSyncResult()


class FullSyncConflictCollection(FakeCollection):
    def sync_collection(self, auth, sync_media=False):
        self.events.append(("sync", auth, sync_media))
        return FullSyncConflictResult()


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


def complete_environment():
    return {
        "ANKIWEB_USERNAME": "anki@example.com",
        "ANKIWEB_PASSWORD": "password",
        "BEEMINDER_USER": "beeminder-user",
        "BEEMINDER_TOKEN": "token",
        "BEEMINDER_GOAL": "anki-reviews",
        "ANKI_TIMEZONE": "Europe/Ljubljana",
    }


class WorkerTests(unittest.TestCase):
    def test_load_config_requires_every_credential(self):
        with self.assertRaisesRegex(WorkerError, "ANKIWEB_USERNAME"):
            load_config({})

    def test_load_config_defaults_to_all_decks_and_ljubljana(self):
        config = load_config(complete_environment())

        self.assertIsNone(config.deck_filter)
        self.assertEqual(config.timezone, "Europe/Ljubljana")

    def test_payload_uses_one_request_id_per_anki_day(self):
        config = WorkerConfig(
            ankiweb_username="anki@example.com",
            ankiweb_password="password",
            beeminder_user="beeminder-user",
            beeminder_token="token",
            beeminder_goal="anki-reviews",
            deck_filter=None,
            timezone="Europe/Ljubljana",
        )

        payload = build_datapoint_payload(config, 4, "2026-08-08")

        self.assertEqual(payload["value"], 4.0)
        self.assertEqual(payload["requestid"], "anki-anki-reviews-2026-08-08")
        self.assertNotIn("password", payload["comment"].lower())

    def test_post_beeminder_rejects_non_success_response(self):
        config = WorkerConfig(
            ankiweb_username="anki@example.com",
            ankiweb_password="password",
            beeminder_user="beeminder-user",
            beeminder_token="token",
            beeminder_goal="anki-reviews",
            deck_filter=None,
            timezone="Europe/Ljubljana",
        )

        with self.assertRaisesRegex(WorkerError, "HTTP 500"):
            post_beeminder(
                config,
                4,
                "2026-08-08",
                urlopen=lambda request, timeout: FakeResponse(500, b"failure"),
            )

    def test_sync_collection_disables_media_and_closes_on_full_run(self):
        events = []

        collection = sync_collection(
            WorkerConfig(
                ankiweb_username="anki@example.com",
                ankiweb_password="password",
                beeminder_user="beeminder-user",
                beeminder_token="token",
                beeminder_goal="anki-reviews",
                deck_filter=None,
                timezone="Europe/Ljubljana",
            ),
            "/tmp/collection.anki2",
            collection_factory=lambda path: FakeCollection(path, events),
        )

        self.assertEqual(events[:2], [
            ("login", "anki@example.com", "password", None),
            ("sync", "auth", False),
        ])
        collection.close()
        self.assertEqual(events[-1], ("close",))

    def test_sync_collection_completes_an_required_full_download(self):
        events = []

        collection = sync_collection(
            load_config(complete_environment()),
            "/tmp/collection.anki2",
            collection_factory=lambda path: FullDownloadCollection(path, events),
        )

        self.assertEqual(events[2][0], "close_for_full_sync")
        self.assertEqual(events[3][0], "full_upload_or_download")
        self.assertEqual(events[3][1]["upload"], False)
        self.assertEqual(events[4], ("reopen", {"after_full_sync": True}))
        collection.close()

    def test_sync_collection_refuses_an_required_full_upload(self):
        events = []

        with self.assertRaisesRegex(WorkerError, "refusing to upload"):
            sync_collection(
                load_config(complete_environment()),
                "/tmp/collection.anki2",
                collection_factory=lambda path: FullUploadCollection(path, events),
            )

        self.assertIn(("close",), events)

    def test_sync_collection_refuses_an_unresolved_full_sync_conflict(self):
        events = []

        with self.assertRaisesRegex(WorkerError, "full-sync conflict"):
            sync_collection(
                load_config(complete_environment()),
                "/tmp/collection.anki2",
                collection_factory=lambda path: FullSyncConflictCollection(path, events),
            )

        self.assertIn(("close",), events)

    def test_dry_run_syncs_and_reports_without_posting_to_beeminder(self):
        events = []
        output = io.StringIO()

        value = run(
            load_config(complete_environment()),
            dry_run=True,
            collection_factory=lambda path: FakeCollection(path, events),
            urlopen=lambda request, timeout: self.fail("dry-run made an HTTP request"),
            output=lambda message: print(message, file=output),
        )

        self.assertEqual(value, 4)
        self.assertIn("dry-run", output.getvalue())
        self.assertIn(("close",), events)


if __name__ == "__main__":
    unittest.main()
