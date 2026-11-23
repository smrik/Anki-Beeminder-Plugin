# Anki worker service coordination design

## Problem

The official Anki sync server keeps the user collection open while it serves
clients. The Beeminder worker's SQLite online backup can wait indefinitely for
that live database. A manual test confirmed that the same dry-run completes as
soon as the sync server is stopped.

## Approved behavior

At the scheduled worker time, the service will:

1. Stop `anki-sync-server.service`.
2. Run the existing Beeminder worker as the restricted `anki` system user.
3. Start `anki-sync-server.service` again, including when the worker fails.

The sync server will therefore be unavailable only during the short snapshot
and metric-read window. No collection files are moved, deleted, or rewritten.

## Service design

`anki-beeminder.service` becomes a privileged coordinator because systemd
service stop/start operations require root. The Python worker remains an
unprivileged `anki` process. The direct `Requires=anki-sync-server.service`
dependency is removed so stopping the required service does not cancel the
worker. The coordinator uses a pre-start stop action, a worker command run as
`anki`, and a post-stop start action.

The existing timer remains unchanged at 21:05. Manual starts use the same
stop, run, and restart sequence.

## Failure handling and safety

- The sync server is restarted from the service cleanup action even if the
  worker exits non-zero.
- The worker keeps using the configured per-user collection path and its
  SQLite snapshot workflow.
- The worker remains unable to write the live collection and continues to use
  the existing systemd filesystem restrictions.
- Tests will verify the ordering, the unprivileged worker invocation, the
  cleanup restart action, and the absence of the old `Requires` dependency.
