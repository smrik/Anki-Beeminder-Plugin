# Windows commands

- Syntax smoke test: `python -m py_compile __init__.py ui.py` (does not import Anki).
- File map/search: `rg --files`; `rg -n "pattern" --glob "*.py"`.
- Inspect repo state: `git status --short`; recent history: `git log -8 --oneline --decorate`.
- This package has no declared test runner, lockfile, or build system; run checks from the add-on directory.
