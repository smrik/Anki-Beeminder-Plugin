import time
import urllib.request
import urllib.parse
import urllib.error
import json
import logging
import os

from aqt import mw
from aqt import gui_hooks
from aqt.utils import showWarning, tooltip
from aqt.qt import QAction

from . import ui
from .metrics import (
    anki_day_datestr,
    day_start_ms,
    get_backlog as metrics_get_backlog,
    get_deck_id,
    get_minutes_today as metrics_get_minutes_today,
    get_new_cards_today as metrics_get_new_cards_today,
    get_reviews_today as metrics_get_reviews_today,
)

PLUGIN_NAME = "Anki-Beeminder Sync"
VERSION = "1.1.0"

# ---------------------------------------------------------------------------
# Logging — writes to beeminder_sync.log in the addon folder
# ---------------------------------------------------------------------------


def _setup_logger():
    log_path = os.path.join(os.path.dirname(__file__), "beeminder_sync.log")
    logger = logging.getLogger("anki_beeminder")
    logger.setLevel(logging.DEBUG)

    if not logger.handlers:
        handler = logging.handlers.RotatingFileHandler(
            log_path, maxBytes=512 * 1024, backupCount=2, encoding="utf-8"
        )
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s  %(levelname)-7s  %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(handler)
    return logger


import logging.handlers

log = _setup_logger()
log.info("=" * 60)
log.info(f"{PLUGIN_NAME} v{VERSION} loaded")

METRIC_LABELS = {
    "reviews_today": "Total Reviews Today",
    "new_cards_today": "New Cards Today",
    "backlog": "Current Backlog",
    "minutes_today": "Study Time (min)",
}

# ---------------------------------------------------------------------------
# Anki data helpers
# ---------------------------------------------------------------------------


def _day_start_ms():
    """Unix timestamp in milliseconds for the start of the current Anki day."""
    return day_start_ms(mw.col)


def _anki_today_datestr():
    """Return the current Anki day as a YYYY-MM-DD string."""
    return anki_day_datestr(mw.col)


def _deck_id(deck_name):
    """Return the deck ID for *deck_name*, or None if not found / empty."""
    return get_deck_id(mw.col, deck_name)


def get_reviews_today(deck_filter=None):
    if not mw.col:
        return 0
    return metrics_get_reviews_today(mw.col, deck_filter)


def get_new_cards_today(deck_filter=None):
    if not mw.col:
        return 0
    return metrics_get_new_cards_today(mw.col, deck_filter)


def get_backlog(deck_filter=None):
    if not mw.col:
        return 0
    return metrics_get_backlog(mw.col, deck_filter)


def get_minutes_today(deck_filter=None):
    if not mw.col:
        return 0
    return metrics_get_minutes_today(mw.col, deck_filter)


_METRIC_FUNCS = {
    "reviews_today": get_reviews_today,
    "new_cards_today": get_new_cards_today,
    "backlog": get_backlog,
    "minutes_today": get_minutes_today,
}


def get_sync_value(config=None):
    if config is None:
        config = mw.addonManager.getConfig(__name__)
    if not config:
        return 0
    metric = config.get("sync_metric", "reviews_today")
    deck_filter = config.get("deck_filter", "").strip() or None
    func = _METRIC_FUNCS.get(metric, get_reviews_today)
    val = func(deck_filter)
    log.debug(f"get_sync_value: metric={metric} deck={deck_filter!r} -> {val}")
    return val


def get_all_deck_names():
    """Return a sorted list of all deck names in the current collection."""
    if not mw.col:
        return []
    try:
        return sorted(d.name for d in mw.col.decks.all_names_and_ids())
    except Exception:
        try:
            return sorted(d["name"] for d in mw.col.decks.all())
        except Exception:
            return []


# ---------------------------------------------------------------------------
# Beeminder API
# ---------------------------------------------------------------------------

_last_sync_time: float = 0.0
_last_sent_value: float | None = None
_last_sent_date: str = ""
_SYNC_DEBOUNCE_SECONDS = 60  # minimum gap between automatic syncs


def send_to_beeminder(val=None, on_done=None, force=False):
    """
    Submit *val* to Beeminder asynchronously.

    Uses a fixed daily requestid (``anki-{goal}-{YYYY-MM-DD}``) so that
    multiple syncs on the same day update the existing datapoint rather than
    stacking new ones.  This is a native Beeminder upsert — the same
    requestid with a different value simply overwrites the stored value.

    Automatic calls are debounced: if a sync was sent less than
    ``_SYNC_DEBOUNCE_SECONDS`` ago the call is silently dropped.
    Pass ``force=True`` (used by manual sync) to bypass the debounce.
    """
    global _last_sync_time, _last_sent_value, _last_sent_date

    import time as _time

    now = _time.time()
    if not force and (now - _last_sync_time) < _SYNC_DEBOUNCE_SECONDS:
        log.debug(
            f"send_to_beeminder: debounced (last sync {now - _last_sync_time:.1f}s ago)"
        )
        return  # too soon — drop this duplicate trigger

    config = mw.addonManager.getConfig(__name__)
    if not config:
        log.warning("send_to_beeminder: no config found")
        return

    token = config.get("beeminder_token", "").strip()
    user = config.get("beeminder_user", "").strip()
    goal = config.get("beeminder_goal", "").strip()

    if not token or not user or not goal:
        log.debug("send_to_beeminder: skipped — credentials not configured")
        return  # silently skip — not yet configured

    _last_sync_time = (
        now  # stamp before the async call so parallel triggers are also blocked
    )

    if val is None:
        val = get_sync_value(config)

    date_str = _anki_today_datestr()

    # Skip if value hasn't changed since the last successful send today
    if not force and date_str == _last_sent_date and float(val) == _last_sent_value:
        log.debug(
            f"send_to_beeminder: skipped — value unchanged ({val}) since last send"
        )
        return
    requestid = f"anki-{goal}-{date_str}"
    metric_lbl = METRIC_LABELS.get(config.get("sync_metric", "reviews_today"), "")

    # Sanitise requestid — only alphanumeric, hyphens, underscores allowed
    import re as _re

    requestid = _re.sub(r"[^a-zA-Z0-9_\-]", "-", requestid)

    log.info(
        f"send_to_beeminder: user={user} goal={goal} value={val} requestid={requestid} force={force}"
    )

    url = f"https://www.beeminder.com/api/v1/users/{user}/goals/{goal}/datapoints.json"
    post_data = urllib.parse.urlencode(
        {
            "auth_token": token,
            "value": float(val),  # ensure numeric, never a bare Python int/str
            "comment": f"Auto-sync from Anki ({metric_lbl}) v{VERSION}",
            "requestid": requestid,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=post_data,
        method="POST",
        headers={"User-Agent": f"AnkiBeeminderSync/{VERSION}"},
    )

    def task():
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = resp.read().decode()
                log.debug(f"API response: HTTP {resp.status}  body={body[:200]}")
                return resp.status, body
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            log.warning(f"API HTTP error: HTTP {e.code}  body={body}")
            return e.code, body
        except Exception as e:
            log.error(f"API request exception: {e}")
            return None, str(e)

    def on_result(future):
        try:
            status, body = future.result()
        except Exception as exc:
            log.error(f"on_result exception: {exc}")
            mw.taskman.run_on_main(
                lambda: tooltip(f"Beeminder sync error: {exc}", period=4000)
            )
            return

        def update_ui():
            if status in (200, 201):
                log.info(f"Sync OK (HTTP {status}): value={val} requestid={requestid}")
                _last_sent_value = float(val)
                _last_sent_date = date_str
                tooltip(f"Beeminder synced: {val} ({metric_lbl})", period=2500)
                if widget_instance:
                    widget_instance.update_count()
                if on_done:
                    on_done(True, val)
            elif status == 401:
                log.error("Sync FAILED: 401 Unauthorized — bad token")
                showWarning(
                    "Beeminder authentication failed.\n\n"
                    "Your API token appears to be invalid. Please update it in "
                    "Tools > Beeminder Sync > Settings.",
                    title=PLUGIN_NAME,
                )
                if on_done:
                    on_done(False, None)
            elif status == 404:
                log.error(f"Sync FAILED: 404 — goal '{goal}' not found")
                showWarning(
                    f'Beeminder goal "{goal}" was not found.\n\n'
                    "Please check the goal slug in Tools > Beeminder Sync > Settings.",
                    title=PLUGIN_NAME,
                )
                if on_done:
                    on_done(False, None)
            elif status == 422:
                if "duplicate" in body.lower():
                    log.info(
                        f"Sync OK (duplicate, already up to date): value={val} requestid={requestid}"
                    )
                    tooltip(
                        f"Beeminder already up to date: {val} ({metric_lbl})",
                        period=2000,
                    )
                    if widget_instance:
                        widget_instance.update_count()
                    if on_done:
                        on_done(True, val)
                else:
                    log.error(f"Sync FAILED: 422 — body={body}")
                    showWarning(
                        f"Beeminder rejected the data (HTTP 422).\n\n"
                        f"Beeminder says: {body}\n\n"
                        f"Sent value: {val}  requestid: {requestid}",
                        title=PLUGIN_NAME,
                    )
                    if on_done:
                        on_done(False, None)
            elif status is None:
                log.error(f"Sync FAILED: network error — {body}")
                tooltip(f"Beeminder sync failed (network error): {body}", period=4000)
                if on_done:
                    on_done(False, None)
            else:
                log.error(f"Sync FAILED: HTTP {status} — {body}")
                tooltip(
                    f"Beeminder sync failed (HTTP {status}): {body[:120]}", period=4000
                )
                if on_done:
                    on_done(False, None)

        mw.taskman.run_on_main(update_ui)

    mw.taskman.run_in_background(task, on_result)


# ---------------------------------------------------------------------------
# Hooks & UI
# ---------------------------------------------------------------------------

widget_instance = None


def on_profile_did_open():
    global widget_instance
    widget_instance = ui.AnkiBeeminderWidget(
        mw, get_sync_value, manual_sync, get_all_deck_names, __name__
    )


def on_sync_did_finish():
    config = mw.addonManager.getConfig(__name__)
    if config and config.get("sync_on_anki_sync", True):
        send_to_beeminder()


def on_state_did_change(new_state: str, old_state: str) -> None:
    """Fire after leaving the reviewer — works on all modern Anki versions."""
    if old_state == "review":
        config = mw.addonManager.getConfig(__name__)
        if config and config.get("sync_on_review_end", True):
            send_to_beeminder()


def manual_sync():
    send_to_beeminder(force=True)
    if widget_instance:
        widget_instance.update_count()


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

action = QAction("Beeminder Force Sync", mw)
action.triggered.connect(manual_sync)
mw.form.menuTools.addAction(action)

gui_hooks.profile_did_open.append(on_profile_did_open)
gui_hooks.sync_did_finish.append(on_sync_did_finish)
gui_hooks.state_did_change.append(on_state_did_change)
