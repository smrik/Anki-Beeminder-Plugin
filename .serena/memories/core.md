# Project map

- Anki add-on package is flat: `__init__.py` is the runtime entrypoint; `ui.py` contains Qt dialogs/widgets.
- `__init__.py`: reads Anki collection data, selects the configured metric, posts one daily idempotent datapoint to Beeminder, registers Anki hooks/actions.
- `ui.py`: Settings/Dashboard dialog and toolbar badge; settings are persisted through `mw.addonManager`.
- Runtime assumes Anki's `aqt.mw`, `aqt.gui_hooks`, Qt, and task manager; importing outside Anki is not a normal runtime path.
- Configuration contract is in `config.example.json`: Beeminder identity/token/goal, metric, deck filter, extra dashboard goals, and two automatic-trigger flags.
- Read implementation/toolchain details in `mem:tech_stack`, Windows commands in `mem:suggested_commands`, and completion checks in `mem:task_completion`.
