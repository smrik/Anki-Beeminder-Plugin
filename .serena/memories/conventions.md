# Code conventions

- Keep add-on code compatible with Anki's embedded Python and Qt runtime; avoid dependencies not shipped by Anki.
- Keep collection reads on the Anki/main side and network calls off the UI thread.
- Use `mw.addonManager.getConfig(__name__)` / `writeConfig` for settings; preserve existing config keys when adding options.
- Use fixed, sanitized daily request IDs for Beeminder writes so retries/upserts do not create duplicate datapoints.
- UI-facing errors use Anki `tooltip`/warning helpers; detailed diagnostics go to the rotating `beeminder_sync.log`.
- Public-ish functions are module-level hooks/helpers; UI classes are in `ui.py` and receive callbacks from `__init__.py` rather than importing runtime logic back into the entrypoint.
