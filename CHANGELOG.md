# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [1.1.0] - 2026-07-03

### Added
- Four selectable sync metrics: total reviews today, new cards learned today,
  current backlog, and study time in minutes.
- Per-deck filtering: restrict any metric to a single Anki deck.
- Auto-sync after review sessions end (`reviewer_did_end` hook).
- Settings toggles to independently enable or disable each auto-sync trigger.
- Dashboard now loads goal graphs asynchronously — Anki UI never blocks during
  network requests.
- Improved error reporting: authentication failures and missing goals show modal
  dialogs; network errors show non-intrusive tooltips.
- Toolbar badge updates after every successful sync.
- Multi-goal dashboard with configurable extra goal slugs.
- Settings tab validation: warns before saving incomplete configuration.

### Changed
- Sync `requestid` is now fixed per goal per calendar day
  (`anki-{slug}-{YYYY-MM-DD}`), making repeated syncs idempotent — the same
  datapoint is updated rather than duplicated.
- Network requests moved to Anki's background task manager.
- UI redesigned: cleaner card layout, section groupboxes, consistent colour
  scheme, per-goal status colour bars.
- `config.json` defaults updated: `sync_metric` now defaults to
  `reviews_today` instead of `backlog`.
- `manifest.json`: bumped to 1.1.0, added author and description, removed
  upper version cap.

### Fixed
- Old code used a timestamp-based `requestid`, causing one new datapoint per
  sync regardless of how many times Anki synced in a day.
- Dashboard images were loaded synchronously, freezing the UI when Beeminder
  was slow to respond.
- Settings dialog opened to an unconfigured state without guidance on what to
  do next.

## [1.0.0] - 2025-01-01

### Added
- Initial release.
- Sync backlog (due + learning card count) to a Beeminder goal after each
  AnkiWeb sync.
- Toolbar badge showing current metric value.
- Dashboard tab with goal graph, time to derailment, pledge, and limsum.
- Settings tab for credentials and metric selection.
