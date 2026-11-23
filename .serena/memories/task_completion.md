# Completion checks

- Run `python -m py_compile __init__.py ui.py`.
- Run `git diff --check`.
- Review `git status --short` and `git diff --stat`; do not stage unrelated files.
- No automated tests currently exist; Anki-hosted/manual validation is required for hook/UI behavior and real Beeminder requests.
