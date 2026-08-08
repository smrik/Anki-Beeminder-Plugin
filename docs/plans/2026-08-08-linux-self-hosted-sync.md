# Linux Self-Hosted Anki Sync and Beeminder Worker Implementation Plan

> When execution is requested in a separate session, use the `executing-plans` skill to implement this plan task-by-task.

**Goal:** Replace the unsupported AnkiWeb-from-GitHub workflow with an official Linux self-hosted Anki sync server and a local daily Beeminder worker, so AnkiMobile, desktop Anki, and the worker all use the same Linux-hosted collection.

**Architecture:** Run the official `anki` standalone package on Linux as `python -m anki.syncserver` under systemd. AnkiMobile and desktop Anki point at the Linux server's custom sync URL; AnkiWeb credentials are no longer used by automation. A systemd timer runs the existing `reviews_today` metric locally against a safe SQLite snapshot of the server collection and upserts the daily Beeminder datapoint with the existing idempotent request ID.

**Tech Stack:** Python 3.10+, pinned `anki==26.5`, SQLite online backup, systemd, Bash, pytest/unittest, Beeminder REST API.

---

## Decisions and safety boundaries

- Use Anki's official self-hosted sync server documented in the Anki Manual, not an unmaintained third-party Docker image.
- Keep the server's raw HTTP endpoint private to the LAN or a VPN such as Tailscale; do not expose port 8080 directly to the public internet.
- Store sync and Beeminder credentials in `/etc/anki-beeminder/*.env` with mode `0600`; never commit them or copy them into GitHub Actions secrets.
- Snapshot the server collection before opening it in the metric worker so the worker does not share the live SQLite database with the sync server.
- Require a human-controlled migration checkpoint: back up the current Anki collection, sync the desktop copy from AnkiWeb, then point the desktop client at the Linux server and explicitly choose the initial upload. The installer must not silently overwrite a collection.
- Remove the scheduled AnkiWeb GitHub Action once the local timer is available, so failed remote runs cannot continue and no AnkiWeb password is needed by CI.

## Test seams

The implementation tests these public seams, as required by `@mattpocock-skills:tdd`:

1. `scripts.daily_beeminder_sync.load_config()` validates local-worker environment variables.
2. `scripts.daily_beeminder_sync.snapshot_collection()` creates a consistent temporary SQLite copy without changing the source.
3. `scripts.daily_beeminder_sync.run()` opens the configured local collection, calculates the existing metric, skips HTTP in dry-run mode, and posts exactly one idempotent Beeminder datapoint in normal mode.
4. The Bash setup wizard passes `bash -n`; systemd unit files are checked for the expected paths and dependencies by a static test.

## Implementation tasks

### Task 1: Start from the merged repository state

**Files:**
- No repository files changed.

**Steps:**

1. Fetch `origin/main` and verify the merged GitHub Actions commit is present.
2. Create branch `codex/linux-self-hosted-sync` from `origin/main`.
3. Confirm the only pre-existing untracked item, `.serena/`, remains untouched.

### Task 2: Add the local collection worker seam

**Files:**
- Modify: `scripts/daily_beeminder_sync.py`
- Modify: `requirements-worker.txt`
- Test: `tests/test_daily_beeminder_sync.py`

**Steps:**

1. Write a failing test for local-only configuration: Beeminder credentials, optional deck filter, timezone, and a required collection path; AnkiWeb credentials must no longer be required.
2. Write a failing test for a read-only SQLite snapshot and a missing-source error.
3. Write a failing test that `--dry-run` calculates `reviews_today` from the local collection and makes no Beeminder request.
4. Write a failing test that normal mode posts one datapoint with the existing day-based `requestid` and closes the opened snapshot collection.
5. Implement the smallest local worker: snapshot the configured `collection.anki2` with SQLite's online backup API, open the snapshot through the pinned Anki library, reuse `metrics.py`, and reuse the existing Beeminder POST helper.
6. Remove the AnkiWeb login/full-download path and its credential requirements from the daily worker; retain explicit, actionable errors for missing paths and invalid timezones.
7. Run the focused unit tests and then the complete test suite.

### Task 3: Add Linux service definitions

**Files:**
- Create: `deploy/linux/anki-sync-server.service`
- Create: `deploy/linux/anki-beeminder.service`
- Create: `deploy/linux/anki-beeminder.timer`
- Create: `deploy/linux/anki-sync-server.env.example`
- Create: `deploy/linux/anki-beeminder.env.example`
- Test: `tests/test_linux_deployment.py`

**Steps:**

1. Write a failing static test that the sync service loads its environment file, runs the pinned virtualenv's `anki.syncserver`, restarts on failure, and has a writable `SYNC_BASE`.
2. Write a failing static test that the Beeminder service depends on the sync server, runs the local worker against the configured collection path, and never references AnkiWeb credentials.
3. Write a failing static test that the timer runs at 21:05 local time, is persistent across downtime, and does not overlap the service through systemd ordering/concurrency.
4. Add restrictive example environment files containing placeholders only; document that `SYNC_USER1` is a new local sync-server credential, not the AnkiWeb password.
5. Add the systemd units with a dedicated unprivileged `anki` service user, `/var/lib/anki-beeminder` state, `/opt/anki-beeminder` application path, and `0600` environment files.
6. Run the static deployment tests and shell/unit validation.

### Task 4: Add the repeatable Linux setup wizard

**Files:**
- Create: `scripts/setup_linux_sync.sh`
- Test: `tests/test_setup_linux_sync.sh`

**Steps:**

1. Copy the wizard library from `@mattpocock-skills:wizard` without editing the library section.
2. Add stages that prompt for the Linux install path, sync-server username/password, bind host/port, Beeminder username/token/goal, optional deck filter, and timezone.
3. Make the wizard install Python/venv prerequisites, create the unprivileged service user and state directories, install `anki==26.5`, copy the worker and service files, write root-readable environment files, enable/start the sync server, and enable the daily timer.
4. Add an explicit backup-and-cutover checkpoint before any client is pointed at the new server. The wizard must stop and ask the user to confirm the current collection is backed up and the desktop collection is current.
5. End with exact AnkiMobile, desktop, LAN/VPN, first-upload, dry-run, status, and log commands.
6. Run `bash -n` and ShellCheck when available; do not execute the wizard end-to-end in this environment because it requires the user's Linux host and credentials.

### Task 5: Remove the misleading GitHub-hosted AnkiWeb path and document cutover

**Files:**
- Delete: `.github/workflows/beeminder-daily.yml`
- Modify: `README.md`
- Modify: `CHANGELOG.md`

**Steps:**

1. Remove the scheduled GitHub Actions job that attempts headless AnkiWeb full downloads.
2. Replace its documentation with the Linux architecture: server URL, local sync credentials, firewall/VPN guidance, collection location, timer behavior, and Beeminder environment files.
3. Document the safe migration sequence from AnkiWeb, including a backup, a current desktop sync, the initial upload decision, and a recovery path back to AnkiWeb if the first sync is wrong.
4. Document that the Linux host must be running and reachable for mobile sync, and that the 21:05 timer only sees reviews that have already reached the Linux server.
5. Add a changelog entry describing the removal of AnkiWeb credentials from automation.

### Task 6: Verify the complete handoff

**Files:**
- No additional files expected.

**Steps:**

1. Run the full Python test suite.
2. Run `bash -n scripts/setup_linux_sync.sh` and ShellCheck if installed.
3. Validate every service path and environment variable against the setup wizard and README.
4. Review `git diff` for secrets, AnkiWeb credentials, accidental `.serena/` changes, and unsafe public bind instructions.
5. Commit the focused change, push the branch, and open a draft pull request for review.
