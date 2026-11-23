# Anki Worker Service Coordination Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Coordinate the daily Beeminder worker with the Anki sync server so SQLite snapshotting completes reliably without changing collection data.

**Architecture:** `anki-beeminder.service` becomes a root-owned systemd coordinator. It stops `anki-sync-server.service`, invokes the existing Python worker through `runuser` as the existing `anki` system user, and starts the sync server in `ExecStopPost` so cleanup runs after success or failure. The existing timer and per-user collection path remain unchanged.

**Tech Stack:** systemd unit files, Bash deployment fixtures, Python `unittest` static deployment tests, Markdown documentation.

## Global Constraints

- Keep the worker process unprivileged as the existing `anki` user.
- Stop the sync server only for the short snapshot and metric-read window.
- Restart the sync server even when the worker exits non-zero.
- Do not move, delete, or rewrite the live Anki collection.
- Keep the timer at `21:05`.
- Keep the collection path user-scoped as `/var/lib/anki-beeminder/sync/<sync-username>/collection.anki2`.

---

### Task 1: Specify the coordinator contract with regression tests

**Files:**
- Modify: `tests/test_linux_deployment.py:25-45`
- Test: `deploy/linux/anki-beeminder.service`

**Interfaces:**
- Consumes: the current service fixture and its `EnvironmentFile`.
- Produces: assertions that lock in the stop → unprivileged worker → restart sequence.

- [ ] **Step 1: Write the failing assertions**

Update `test_beeminder_service_reads_local_collection_after_sync_server` to require:

```python
self.assertIn("User=root", service)
self.assertNotIn("Requires=anki-sync-server.service", service)
self.assertIn(
    "ExecStartPre=/usr/bin/systemctl stop anki-sync-server.service",
    service,
)
self.assertIn(
    "ExecStart=/usr/bin/runuser --user anki --group anki -- "
    "/opt/anki-beeminder/venv/bin/python -m scripts.daily_beeminder_sync",
    service,
)
self.assertIn(
    "ExecStopPost=/usr/bin/systemctl start anki-sync-server.service",
    service,
)
```

Also remove the old assertions for `Requires=anki-sync-server.service` and
`After=anki-sync-server.service`.

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
python3 -m unittest tests.test_linux_deployment.LinuxDeploymentTests.test_beeminder_service_reads_local_collection_after_sync_server
```

Expected: FAIL because the current unit still runs as `anki` and has no stop/restart coordinator actions.

### Task 2: Implement safe service coordination

**Files:**
- Modify: `deploy/linux/anki-beeminder.service:1-20`

**Interfaces:**
- Consumes: `/etc/anki-beeminder/anki-beeminder.env` and the installed worker module.
- Produces: a systemd oneshot service whose privileged lifecycle actions surround an unprivileged worker process.

- [ ] **Step 1: Replace the dependency and service identity**

Use this unit structure:

```ini
[Unit]
Description=Send local Anki reviews_today to Beeminder
After=network-online.target

[Service]
Type=oneshot
User=root
WorkingDirectory=/opt/anki-beeminder
EnvironmentFile=/etc/anki-beeminder/anki-beeminder.env
ExecStartPre=/usr/bin/systemctl stop anki-sync-server.service
ExecStart=/usr/bin/runuser --user anki --group anki -- /opt/anki-beeminder/venv/bin/python -m scripts.daily_beeminder_sync
ExecStopPost=/usr/bin/systemctl start anki-sync-server.service
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/anki-beeminder
```

Do not retain `Requires=anki-sync-server.service`, because stopping a required
unit would stop the worker before it can take its snapshot. Do not add a
collection-path argument; the environment file already supplies the
user-scoped `ANKI_COLLECTION_PATH`.

- [ ] **Step 2: Run the focused deployment test**

Run:

```bash
python3 -m unittest tests.test_linux_deployment.LinuxDeploymentTests.test_beeminder_service_reads_local_collection_after_sync_server
```

Expected: PASS.

### Task 3: Document the brief scheduled outage and verify the deployment

**Files:**
- Modify: `README.md:200-230`
- Test: `tests/test_linux_deployment.py`, `tests/test_setup_linux_sync.sh`

**Interfaces:**
- Consumes: the coordinated service behavior from Task 2.
- Produces: operator instructions that explain service availability during the worker run and a clean full test result.

- [ ] **Step 1: Update the operations documentation**

Add a short note explaining that `anki-beeminder.service` temporarily stops
the sync server at 21:05, reads a SQLite snapshot, and restarts the server even
if the worker fails. State that mobile/desktop sync should not be attempted
during that brief window.

- [ ] **Step 2: Run all repository verification**

Run:

```bash
python3 -m unittest discover -s tests
bash tests/test_setup_linux_sync.sh
bash -n scripts/setup_linux_sync.sh
git diff --check
```

Expected: 19 Python tests pass, Bash validation passes, shell syntax passes,
and `git diff --check` produces no output.

- [ ] **Step 3: Install the updated unit on Linux**

From the repository on the Linux host, rerun:

```bash
bash scripts/setup_linux_sync.sh
```

Keep the saved values, do not repeat desktop/mobile upload, confirm the
existing collection at Stage 6, and run the Stage 7 dry-run. The next scheduled
run will use the same stop → worker → restart sequence automatically.
