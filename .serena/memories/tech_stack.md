# Runtime stack

- Python Anki add-on; standard library networking via `urllib`; no third-party Python dependencies.
- Anki 2.1.50+ manifest target; Qt UI through Anki's `aqt.qt` compatibility layer.
- Background network work uses `mw.taskman.run_in_background`; UI callbacks return through `mw.taskman.run_on_main`.
- Beeminder integration is an HTTP POST to the v1 datapoints endpoint with `auth_token`, numeric `value`, comment, and sanitized daily `requestid`.
- Static package metadata in `manifest.json`; example/default configuration in `config.example.json`.
