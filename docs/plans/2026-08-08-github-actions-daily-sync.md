# GitHub Actions Daily Anki-to-Beeminder Sync Implementation Plan

> When execution is requested in a separate session, use the `executing-plans` skill to implement this plan task-by-task.

**Goal:** Run the existing `reviews_today` metric once per day from GitHub Actions by syncing a disposable headless Anki collection from AnkiWeb and upserting that day’s value to Beeminder.

**Architecture:** The add-on and the scheduled worker will share the same small metric module so `reviews_today` keeps exactly the current meaning: review answers recorded in Anki’s current day, optionally filtered by deck. The worker will authenticate to AnkiWeb, perform a no-media collection sync on an ephemeral runner, calculate the metric using Anki’s day cutoff, and send one idempotent Beeminder datapoint keyed by the Anki day. No Anki database, password, or API token will be committed or persisted by the workflow.

**Tech Stack:** Python 3.13, Anki headless library (`anki==26.5`, pinned), GitHub Actions, AnkiWeb sync API through the official `anki` package, Beeminder HTTP API, `unittest`.

---

## Implementation Tasks

### 1. Extract and test the shared Anki-day metric logic

**Files:**

- Create `metrics.py`.
- Modify `__init__.py` to delegate its existing metric helpers to `metrics.py` without changing the add-on’s public behavior.
- Create `tests/__init__.py` and `tests/test_metrics.py`.

**Work:**

1. Add collection-agnostic helpers for Anki day start, Anki-day date strings, deck lookup, and `reviews_today`.
2. Preserve the existing query semantics, including `revlog.id > day_start_ms`, optional deck filtering through the cards table, and a zero result for a missing deck.
3. Keep the existing add-on function names as compatibility wrappers, so the UI and config code continue to call `get_reviews_today()` and `get_sync_value()` as before.
4. Write tests first using a small fake collection/database/scheduler, covering all-deck counts, deck-filtered counts, missing decks, the day-cutoff boundary, and the generated Anki-day string.

**Verification:** `python -m unittest discover -s tests -v` passes before and after the extraction; the existing add-on module remains import-compatible in Anki’s environment.

### 2. Add a safe, headless daily worker

**Files:**

- Create `scripts/__init__.py`.
- Create `scripts/daily_beeminder_sync.py`.
- Create `tests/test_daily_beeminder_sync.py`.

**Work:**

1. Read required credentials only from environment variables:
   `ANKIWEB_USERNAME`, `ANKIWEB_PASSWORD`, `BEEMINDER_USER`, `BEEMINDER_TOKEN`, and `BEEMINDER_GOAL`.
2. Accept optional `ANKI_DECK_FILTER` and `ANKI_TIMEZONE` variables, defaulting to all decks and `Europe/Ljubljana` respectively.
3. Create a temporary collection path, log in to AnkiWeb with `Collection.sync_login(..., endpoint=None)`, and call `sync_collection(..., sync_media=False)`.
4. Handle the official sync result explicitly: complete a required full download into the disposable collection, refuse an unexpected full upload, and fail loudly on sync/authentication errors. Always close the collection and remove the temporary directory.
5. Calculate the shared `reviews_today` value after sync.
6. POST to Beeminder using the existing daily request-id shape `anki-{goal}-{YYYY-MM-DD}`. Re-running the workflow for the same Anki day must update the same datapoint rather than create another one.
7. Include a `--dry-run` mode that performs the Anki sync and prints only non-secret operational information without sending to Beeminder.
8. Use standard-library HTTP for the Beeminder call, redact credentials from errors, and return a non-zero exit code for missing configuration, failed sync, or non-success API responses.

**Tests:** Test environment validation, date/request-id generation, payload construction, dry-run behavior, and API error handling with fakes. Do not contact AnkiWeb or Beeminder from unit tests.

**Verification:** `python -m unittest discover -s tests -v` and `python -m py_compile __init__.py ui.py metrics.py scripts/*.py` pass.

### 3. Pin the worker dependency

**Files:**

- Create `requirements-worker.txt`.

**Work:**

1. Pin the tested stable headless Anki package as `anki==26.5`.
2. Keep this dependency separate from the Anki add-on bundle; the desktop add-on does not install or vendor it.

**Verification:** On a Linux environment, install the file and run a smoke import for `anki.collection.Collection`; if the installed Anki client uses a materially different sync protocol, update the pin and the documented compatibility note before enabling the scheduled job.

### 4. Add the GitHub Actions workflow

**Files:**

- Create `.github/workflows/beeminder-daily.yml`.

**Work:**

1. Run on `workflow_dispatch` and at `21:05` in `Europe/Ljubljana`, deliberately off the hour to reduce scheduled-run delays.
2. Use `ubuntu-24.04`, Python 3.13, a 15-minute timeout, and `permissions: contents: read`.
3. Prevent overlapping daily runs with a workflow concurrency group.
4. Install `requirements-worker.txt` and run `python -m scripts.daily_beeminder_sync` from the repository root.
5. Inject only the five required secrets plus optional repository variable values for deck and timezone. Do not echo the environment or write credentials to files.
6. Leave media disabled; the workflow needs review history, not card media.

**Verification:** Validate the YAML structure, run the worker in `--dry-run` mode locally with faked dependencies, and use the Actions UI’s manual trigger for the first real end-to-end run.

### 5. Document setup, limitations, and recovery

**Files:**

- Modify `README.md`.
- Optionally update `CHANGELOG.md` if the implementation is released as a new add-on version.

**Work:** Document:

1. The recommended private-repository setup.
2. The exact GitHub Actions secrets and optional variables.
3. That AnkiMobile must sync to AnkiWeb before the scheduled run; the workflow cannot read unsynced phone activity.
4. That the worker uses `reviews_today`, counts review answers rather than unique notes, and writes one daily idempotent Beeminder datapoint.
5. How to trigger a manual dry-run/real run, inspect logs, recover from AnkiWeb or Beeminder authentication failures, and change the timezone or schedule.
6. The ephemeral/no-media behavior and the fact that secrets must never be placed in `config.json`, repository files, or logs.

### 6. Final verification and handoff

**Work:**

1. Run the complete unit-test and syntax-check commands.
2. Run `git diff --check` and inspect the full diff for accidental credentials, Anki database files, generated artifacts, or changes to unrelated add-on behavior.
3. Confirm `.serena/` remains untracked local agent state and is not part of the feature diff.
4. Report the created workflow, required repository configuration, verification results, and any end-to-end check that still requires the user’s AnkiWeb/Beeminder credentials.

## Configuration Contract

Repository secrets:

- `ANKIWEB_USERNAME`
- `ANKIWEB_PASSWORD`
- `BEEMINDER_USER`
- `BEEMINDER_TOKEN`
- `BEEMINDER_GOAL`

Optional repository variables:

- `ANKI_DECK_FILTER` — empty means all decks.
- `ANKI_TIMEZONE` — defaults to `Europe/Ljubljana`.

The scheduled run itself should use `21:05` local time. GitHub Actions scheduling is best-effort, so the workflow must also expose `workflow_dispatch` for a manual retry or first-run validation.

## Out of Scope

- Replacing AnkiWeb with a self-hosted Linux sync server.
- Scraping the AnkiWeb website.
- Reading AnkiMobile’s local database directly.
- Uploading media or exporting the user’s collection to the repository.
- Adding an IFTTT/Zapier dependency when the required Anki review metric is not available as a native trigger.
