import unittest
from pathlib import Path


DEPLOY_DIR = Path(__file__).parents[1] / "deploy" / "linux"


class LinuxDeploymentTests(unittest.TestCase):
    def test_sync_server_service_runs_official_server_as_unprivileged_user(self):
        service = (DEPLOY_DIR / "anki-sync-server.service").read_text()

        self.assertIn("User=anki", service)
        self.assertIn(
            "EnvironmentFile=/etc/anki-beeminder/anki-sync-server.env",
            service,
        )
        self.assertIn(
            "ExecStart=/opt/anki-beeminder/venv/bin/python -m anki.syncserver",
            service,
        )
        self.assertIn("Restart=on-failure", service)
        self.assertIn("ReadWritePaths=/var/lib/anki-beeminder", service)

    def test_beeminder_service_reads_local_collection_after_sync_server(self):
        service = (DEPLOY_DIR / "anki-beeminder.service").read_text()

        self.assertIn("Requires=anki-sync-server.service", service)
        self.assertIn("After=anki-sync-server.service", service)
        self.assertIn(
            "EnvironmentFile=/etc/anki-beeminder/anki-beeminder.env",
            service,
        )
        self.assertIn(
            "ExecStart=/opt/anki-beeminder/venv/bin/python -m scripts.daily_beeminder_sync",
            service,
        )
        self.assertIn(
            "--collection-path /var/lib/anki-beeminder/sync/collection.anki2",
            service,
        )
        self.assertNotIn("ANKIWEB", service)

    def test_daily_timer_is_persistent_and_runs_at_anki_day_end(self):
        timer = (DEPLOY_DIR / "anki-beeminder.timer").read_text()

        self.assertIn("OnCalendar=*-*-* 21:05:00", timer)
        self.assertIn("Persistent=true", timer)
        self.assertIn("Unit=anki-beeminder.service", timer)

    def test_environment_examples_contain_no_real_credentials(self):
        sync_env = (DEPLOY_DIR / "anki-sync-server.env.example").read_text()
        beeminder_env = (DEPLOY_DIR / "anki-beeminder.env.example").read_text()

        self.assertIn("SYNC_USER1=", sync_env)
        self.assertIn("ANKI_COLLECTION_PATH=", beeminder_env)
        self.assertIn("BEEMINDER_TOKEN=", beeminder_env)
        self.assertNotIn("ANKIWEB_PASSWORD", sync_env + beeminder_env)
        self.assertNotIn("api_token", sync_env + beeminder_env)


if __name__ == "__main__":
    unittest.main()
