import time
import urllib.request
import urllib.error

from aqt import mw
from aqt.qt import (
    QWidget,
    QDialog,
    QTabWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QGridLayout,
    QScrollArea,
    QFrame,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QCheckBox,
    QComboBox,
    QAction,
    QWidgetAction,
    QToolBar,
    QPixmap,
    QTimer,
    QSizePolicy,
    Qt,
)
from aqt.utils import tooltip, showWarning

# ---------------------------------------------------------------------------
# Colour / style constants
# ---------------------------------------------------------------------------

_ACCENT = "#4A90D9"
_BG = "#F5F5F5"
_CARD_BG = "#FFFFFF"
_BORDER = "#DCDCDC"
_TEXT = "#1A1A1A"
_MUTED = "#6B6B6B"

_BTN_PRIMARY = f"""
    QPushButton {{
        background-color: {_ACCENT}; color: white;
        border: none; border-radius: 5px;
        padding: 7px 18px; font-weight: 600; font-size: 13px;
    }}
    QPushButton:hover  {{ background-color: #3a7ec8; }}
    QPushButton:pressed {{ background-color: #2d6bb0; }}
    QPushButton:disabled {{ background-color: #aaa; }}
"""

_BTN_SUCCESS = """
    QPushButton {
        background-color: #3a9e5f; color: white;
        border: none; border-radius: 5px;
        padding: 7px 18px; font-weight: 600; font-size: 13px;
    }
    QPushButton:hover  { background-color: #2e8050; }
    QPushButton:pressed { background-color: #226040; }
"""

_CARD_STYLE = f"""
    QFrame {{
        background-color: {_CARD_BG};
        border: 1px solid {_BORDER};
        border-radius: 8px;
    }}
"""

_GROUP_STYLE = f"""
    QGroupBox {{
        font-weight: 600;
        font-size: 12px;
        color: {_MUTED};
        border: 1px solid {_BORDER};
        border-radius: 6px;
        margin-top: 10px;
        padding: 6px 4px 4px 4px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 4px;
    }}
"""

_INPUT_STYLE = f"""
    QLineEdit, QComboBox {{
        border: 1px solid {_BORDER};
        border-radius: 4px;
        padding: 5px 8px;
        font-size: 13px;
        background: white;
        color: {_TEXT};
    }}
    QLineEdit:focus, QComboBox:focus {{
        border-color: {_ACCENT};
    }}
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_METRICS = [
    ("reviews_today", "Total reviews today"),
    ("new_cards_today", "New cards learned today"),
    ("backlog", "Current backlog (due + in learning)"),
    ("minutes_today", "Study time today (minutes)"),
]


def _fetch_goal_json(user, token, slug):
    url = (
        f"https://www.beeminder.com/api/v1/users/{user}/goals/{slug}.json"
        f"?auth_token={token}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "AnkiBeeminderSync/1.1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                import json

                return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise PermissionError("Invalid API token")
        if e.code == 404:
            raise LookupError(f"Goal '{slug}' not found")
    except Exception as e:
        raise ConnectionError(str(e))
    return None


def _load_pixmap(url, width=320):
    req = urllib.request.Request(url, headers={"User-Agent": "AnkiBeeminderSync/1.1.0"})
    data = urllib.request.urlopen(req, timeout=8).read()
    px = QPixmap()
    px.loadFromData(data)
    if px.width() > 0:
        return px.scaledToWidth(width, Qt.TransformationMode.SmoothTransformation)
    return None


def _color_for_safebuf(safebuf):
    if safebuf < 1:
        return "#D93025"  # red
    if safebuf < 2:
        return "#E8710A"  # orange
    if safebuf < 3:
        return "#3F3FFF"  # blue
    if safebuf < 7:
        return "#2E8B57"  # green
    return "#1A6B35"  # dark green


# ---------------------------------------------------------------------------
# Settings tab
# ---------------------------------------------------------------------------


class SettingsTab(QWidget):
    def __init__(self, parent, config, config_name, get_deck_names_fn, save_callback):
        super().__init__(parent)
        self._config = config
        self._config_name = config_name
        self._get_deck_names = get_deck_names_fn
        self._save_callback = save_callback
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(10)

        self.setStyleSheet(_GROUP_STYLE + _INPUT_STYLE)

        # ── Account ──────────────────────────────────────────────────
        acct_group = QGroupBox("Beeminder Account")
        acct_form = QFormLayout(acct_group)
        acct_form.setSpacing(8)

        self._user_input = QLineEdit(self._config.get("beeminder_user", ""))
        self._user_input.setPlaceholderText("your-username")

        self._token_input = QLineEdit(self._config.get("beeminder_token", ""))
        self._token_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._token_input.setPlaceholderText("Paste your API token here")

        token_hint = QLabel(
            '<a href="https://www.beeminder.com/api/v1/auth_token.json">'
            "Get your token</a>"
        )
        token_hint.setOpenExternalLinks(True)
        token_hint.setStyleSheet(f"color: {_MUTED}; font-size: 11px; border: none;")

        acct_form.addRow("Username:", self._user_input)
        acct_form.addRow("API Token:", self._token_input)
        acct_form.addRow("", token_hint)
        outer.addWidget(acct_group)

        # ── Goal & Metric ─────────────────────────────────────────────
        goal_group = QGroupBox("Goal and Metric")
        goal_form = QFormLayout(goal_group)
        goal_form.setSpacing(8)

        self._goal_input = QLineEdit(self._config.get("beeminder_goal", ""))
        self._goal_input.setPlaceholderText("e.g. anki-reviews")
        self._goal_input.setToolTip(
            "The slug from your Beeminder goal URL: beeminder.com/you/THIS-PART"
        )

        self._metric_combo = QComboBox()
        current_metric = self._config.get("sync_metric", "reviews_today")
        for val, label in _METRICS:
            self._metric_combo.addItem(label, val)
            if val == current_metric:
                self._metric_combo.setCurrentIndex(self._metric_combo.count() - 1)

        self._deck_combo = QComboBox()
        self._deck_combo.addItem("All decks", "")
        current_deck = self._config.get("deck_filter", "")
        for name in self._get_deck_names():
            self._deck_combo.addItem(name, name)
            if name == current_deck:
                self._deck_combo.setCurrentIndex(self._deck_combo.count() - 1)

        goal_form.addRow("Goal Slug:", self._goal_input)
        goal_form.addRow("Metric:", self._metric_combo)
        goal_form.addRow("Deck Filter:", self._deck_combo)
        outer.addWidget(goal_group)

        # ── Other Goals (dashboard) ───────────────────────────────────
        dash_group = QGroupBox("Dashboard — Extra Goals")
        dash_form = QFormLayout(dash_group)
        dash_form.setSpacing(8)

        self._other_goals_input = QLineEdit(self._config.get("other_goals", ""))
        self._other_goals_input.setPlaceholderText("slug1, slug2  (comma-separated)")
        self._other_goals_input.setToolTip(
            "Additional Beeminder goal slugs to show on the dashboard."
        )
        dash_form.addRow("Other Goals:", self._other_goals_input)
        outer.addWidget(dash_group)

        # ── Sync Triggers ─────────────────────────────────────────────
        sync_group = QGroupBox("Auto-Sync Triggers")
        sync_vbox = QVBoxLayout(sync_group)
        sync_vbox.setSpacing(4)

        self._chk_anki_sync = QCheckBox("After Anki syncs with AnkiWeb")
        self._chk_review_end = QCheckBox("After a review session ends")
        self._chk_anki_sync.setChecked(self._config.get("sync_on_anki_sync", True))
        self._chk_review_end.setChecked(self._config.get("sync_on_review_end", True))
        sync_vbox.addWidget(self._chk_anki_sync)
        sync_vbox.addWidget(self._chk_review_end)
        outer.addWidget(sync_group)

        # ── Save button ───────────────────────────────────────────────
        outer.addStretch()
        save_btn = QPushButton("Save Settings")
        save_btn.setStyleSheet(_BTN_PRIMARY)
        save_btn.clicked.connect(self._save)
        outer.addWidget(save_btn)

    def _save(self):
        user = self._user_input.text().strip()
        token = self._token_input.text().strip()
        goal = self._goal_input.text().strip()

        if not user or not token or not goal:
            showWarning(
                "Username, API Token, and Goal Slug are all required before saving.",
                title="Beeminder Sync",
            )
            return

        self._config["beeminder_user"] = user
        self._config["beeminder_token"] = token
        self._config["beeminder_goal"] = goal
        self._config["sync_metric"] = self._metric_combo.currentData()
        self._config["deck_filter"] = self._deck_combo.currentData()
        self._config["other_goals"] = self._other_goals_input.text().strip()
        self._config["sync_on_anki_sync"] = self._chk_anki_sync.isChecked()
        self._config["sync_on_review_end"] = self._chk_review_end.isChecked()

        mw.addonManager.writeConfig(self._config_name, self._config)
        tooltip("Settings saved.", period=1500)
        if self._save_callback:
            self._save_callback()


# ---------------------------------------------------------------------------
# Dashboard tab
# ---------------------------------------------------------------------------


class DashboardTab(QWidget):
    def __init__(self, parent, config, sync_callback):
        super().__init__(parent)
        self.config = config
        self.sync_callback = sync_callback
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._outer.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet(
            f"QScrollArea {{ border: none; background-color: {_BG}; }}"
        )
        self._outer.addWidget(self._scroll)

        self._content = QWidget()
        self._content.setStyleSheet(f"background-color: {_BG};")
        self._scroll.setWidget(self._content)

        self._grid = QGridLayout(self._content)
        self._grid.setSpacing(14)
        self._grid.setContentsMargins(14, 14, 14, 14)

    def refresh(self):
        # Clear existing widgets
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        user = self.config.get("beeminder_user", "").strip()
        token = self.config.get("beeminder_token", "").strip()
        goal = self.config.get("beeminder_goal", "").strip()

        if not user or not token or not goal:
            msg = QLabel(
                "No credentials configured.\nOpen the Settings tab to get started."
            )
            msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
            msg.setStyleSheet(f"color: {_MUTED}; font-size: 14px;")
            self._grid.addWidget(msg, 0, 0)
            return

        # Top bar: sync button + refresh button
        bar = QWidget()
        bar.setStyleSheet(f"background: {_BG};")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(0, 0, 0, 4)

        sync_btn = QPushButton("Sync Now")
        sync_btn.setStyleSheet(_BTN_SUCCESS)
        sync_btn.setFixedWidth(120)
        sync_btn.clicked.connect(self._on_sync_click)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setStyleSheet(_BTN_PRIMARY)
        refresh_btn.setFixedWidth(100)
        refresh_btn.clicked.connect(self.refresh)

        bar_layout.addWidget(sync_btn)
        bar_layout.addWidget(refresh_btn)
        bar_layout.addStretch()
        self._grid.addWidget(bar, 0, 0, 1, 2)

        # Collect slugs
        slugs = [goal]
        for s in self.config.get("other_goals", "").split(","):
            s = s.strip()
            if s and s not in slugs:
                slugs.append(s)

        row, col = 1, 0
        for slug in slugs:
            card = self._make_card(user, token, slug, primary=(slug == goal))
            self._grid.addWidget(card, row, col)
            col += 1
            if col >= 2:
                col = 0
                row += 1

        # Push cards to top
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._grid.addWidget(spacer, row + 1, 0, 1, 2)

    def _make_card(self, user, token, slug, primary=False):
        frame = QFrame()
        extra_border = (
            f"border: 2px solid {_ACCENT};"
            if primary
            else f"border: 1px solid {_BORDER};"
        )
        frame.setStyleSheet(
            f"QFrame {{ background: {_CARD_BG}; border-radius: 8px; {extra_border} }}"
        )
        frame.setMinimumWidth(300)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        try:
            data = _fetch_goal_json(user, token, slug)
        except PermissionError as e:
            layout.addWidget(self._error_label(str(e)))
            return frame
        except LookupError as e:
            layout.addWidget(self._error_label(str(e)))
            return frame
        except Exception as e:
            layout.addWidget(self._error_label(f"Could not load '{slug}': {e}"))
            return frame

        if not data:
            layout.addWidget(self._error_label(f"No data returned for '{slug}'"))
            return frame

        # Status colour bar
        safebuf = data.get("safebuf", 0)
        bar_color = _color_for_safebuf(safebuf)
        color_bar = QFrame()
        color_bar.setFixedHeight(4)
        color_bar.setStyleSheet(
            f"QFrame {{ background-color: {bar_color}; border-radius: 2px; border: none; }}"
        )
        layout.addWidget(color_bar)

        # Header row: title + pledge
        title = data.get("title") or slug
        pledge = data.get("pledge", 0)
        h_row = QHBoxLayout()
        t_lbl = QLabel(f"<b>{title}</b>")
        t_lbl.setStyleSheet(f"font-size: 15px; color: {_TEXT}; border: none;")
        p_lbl = QLabel(f"${pledge}")
        p_lbl.setStyleSheet(
            f"color: {_MUTED}; font-size: 13px; font-weight: 600; border: none;"
        )
        p_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        h_row.addWidget(t_lbl)
        h_row.addStretch()
        h_row.addWidget(p_lbl)
        layout.addLayout(h_row)

        # Graph image
        graph_url = data.get("graph_url")
        if graph_url:
            img_lbl = QLabel("Loading graph...")
            img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            img_lbl.setMinimumHeight(180)
            img_lbl.setStyleSheet(f"color: {_MUTED}; border: none;")
            layout.addWidget(img_lbl)
            self._load_image_async(img_lbl, graph_url)

        # Time remaining
        losedate = data.get("losedate", 0)
        seconds_rem = max(0, losedate - time.time())
        days = int(seconds_rem // 86400)
        hours = int((seconds_rem % 86400) // 3600)
        time_lbl = QLabel(f"{days}d {hours}h remaining")
        time_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        time_lbl.setStyleSheet(
            f"color: {bar_color}; font-weight: 700; font-size: 13px;"
            f" font-family: monospace; border: none;"
        )
        layout.addWidget(time_lbl)

        # Limsum
        limsum = data.get("limsum", "")
        if limsum:
            lim_lbl = QLabel(limsum)
            lim_lbl.setWordWrap(True)
            lim_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lim_lbl.setStyleSheet(f"color: {_MUTED}; font-size: 11px; border: none;")
            layout.addWidget(lim_lbl)

        return frame

    @staticmethod
    def _error_label(msg):
        lbl = QLabel(msg)
        lbl.setWordWrap(True)
        lbl.setStyleSheet("color: #D93025; font-size: 12px; border: none;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return lbl

    def _load_image_async(self, label, url):
        def task():
            try:
                return _load_pixmap(url)
            except Exception:
                return None

        def on_done(future):
            try:
                px = future.result()
            except Exception:
                px = None

            def update():
                if px:
                    label.setPixmap(px)
                    label.setText("")
                else:
                    label.setText("Graph unavailable")

            mw.taskman.run_on_main(update)

        mw.taskman.run_in_background(task, on_done)

    def _on_sync_click(self):
        if self.sync_callback:
            self.sync_callback()
        QTimer.singleShot(1500, self.refresh)


# ---------------------------------------------------------------------------
# Main dialog
# ---------------------------------------------------------------------------


class BeeminderDialog(QDialog):
    def __init__(self, parent, config, config_name, get_deck_names_fn, sync_callback):
        super().__init__(parent)
        self.setWindowTitle("Beeminder Sync")
        self.setMinimumWidth(720)
        self.setMinimumHeight(620)
        self.setStyleSheet(f"background-color: {_BG}; color: {_TEXT};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: none;
                background: {_BG};
            }}
            QTabBar::tab {{
                padding: 9px 18px;
                font-size: 13px;
                font-weight: 500;
                color: {_MUTED};
                background: {_BG};
                border: none;
                border-bottom: 2px solid transparent;
            }}
            QTabBar::tab:selected {{
                color: {_ACCENT};
                border-bottom: 2px solid {_ACCENT};
            }}
            QTabBar::tab:hover {{
                color: {_TEXT};
            }}
        """)

        self._dash_tab = DashboardTab(self, config, sync_callback)
        self._settings_tab = SettingsTab(
            self, config, config_name, get_deck_names_fn, self._on_settings_saved
        )

        self._tabs.addTab(self._dash_tab, "Dashboard")
        self._tabs.addTab(self._settings_tab, "Settings")
        layout.addWidget(self._tabs)

        # Open to Settings if not yet configured
        if not config.get("beeminder_token") or not config.get("beeminder_user"):
            self._tabs.setCurrentIndex(1)

    def _on_settings_saved(self):
        self._dash_tab.config = self._settings_tab._config
        self._dash_tab.refresh()
        self._tabs.setCurrentIndex(0)


# ---------------------------------------------------------------------------
# Toolbar badge widget
# ---------------------------------------------------------------------------

_METRIC_SHORT = {
    "reviews_today": "reviews",
    "new_cards_today": "new",
    "backlog": "due",
    "minutes_today": "min",
}

_BADGE_NORMAL = f"""
    QFrame#BeeBadge {{
        background-color: #E8F0FA;
        border: 1px solid {_ACCENT};
        border-radius: 6px;
    }}
    QFrame#BeeBadge:hover {{
        background-color: #D0E4F7;
    }}
"""

_BADGE_UNCONFIGURED = f"""
    QFrame#BeeBadge {{
        background-color: #F0F0F0;
        border: 1px solid {_BORDER};
        border-radius: 6px;
    }}
"""


class _BadgeWidget(QFrame):
    """Single-line clickable toolbar badge: '● 42 reviews  ·  7 left'"""

    def __init__(self, parent, on_click_fn):
        super().__init__(parent)
        self.setObjectName("BeeBadge")
        self._on_click_fn = on_click_fn
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Beeminder Sync — click to open dashboard")

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 4, 10, 4)
        row.setSpacing(4)

        self._dot = QLabel("●")
        self._dot.setStyleSheet(f"color: {_ACCENT}; font-size: 9px; border: none;")

        self._main_lbl = QLabel("--")
        self._main_lbl.setStyleSheet(
            f"font-size: 13px; font-weight: 600; color: {_TEXT}; border: none;"
        )

        self._sep_lbl = QLabel("·")
        self._sep_lbl.setStyleSheet(
            f"font-size: 13px; color: {_BORDER}; border: none; padding: 0 2px;"
        )

        self._left_lbl = QLabel("")
        self._left_lbl.setStyleSheet(f"font-size: 13px; color: {_MUTED}; border: none;")

        row.addWidget(self._dot)
        row.addWidget(self._main_lbl)
        row.addWidget(self._sep_lbl)
        row.addWidget(self._left_lbl)

        self.setStyleSheet(_BADGE_NORMAL)

    def set_value(self, val, metric_key, backlog, unconfigured=False):
        short = _METRIC_SHORT.get(metric_key, "")
        self._main_lbl.setText(f"{val} {short}")

        if unconfigured:
            self._dot.setStyleSheet(f"color: {_MUTED}; font-size: 9px; border: none;")
            self._main_lbl.setStyleSheet(
                f"font-size: 13px; font-weight: 600; color: {_MUTED}; border: none;"
            )
            self._sep_lbl.hide()
            self._left_lbl.hide()
            self.setStyleSheet(_BADGE_UNCONFIGURED)
            return

        self._dot.setStyleSheet(f"color: {_ACCENT}; font-size: 9px; border: none;")
        self._main_lbl.setStyleSheet(
            f"font-size: 13px; font-weight: 600; color: {_TEXT}; border: none;"
        )

        # Only show the "X left" separator when the primary metric is NOT backlog
        if metric_key != "backlog":
            self._sep_lbl.show()
            self._left_lbl.show()
            self._left_lbl.setText(f"{backlog} left")
        else:
            self._sep_lbl.hide()
            self._left_lbl.hide()

        self.setStyleSheet(_BADGE_NORMAL)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_click_fn()
        super().mousePressEvent(event)


class AnkiBeeminderWidget:
    def __init__(self, mw, get_count_fn, sync_fn, get_deck_names_fn, config_name):
        self._mw = mw
        self._get_count = get_count_fn
        self._sync = sync_fn
        self._get_deck_names = get_deck_names_fn
        self._config_name = config_name

        self._badge = _BadgeWidget(mw, self._on_click)

        self._widget_action = QWidgetAction(mw)
        self._widget_action.setDefaultWidget(self._badge)

        try:
            if hasattr(mw.form, "mainToolBar"):
                mw.form.mainToolBar.addAction(self._widget_action)
            else:
                tb = mw.findChild(QToolBar, "AnkiBeeminderToolbar")
                if not tb:
                    tb = mw.addToolBar("Beeminder")
                    tb.setObjectName("AnkiBeeminderToolbar")
                tb.addAction(self._widget_action)
        except Exception:
            pass

        self.update_count()

    def update_count(self):
        try:
            config = self._mw.addonManager.getConfig(self._config_name) or {}
            token = config.get("beeminder_token", "").strip()
            metric = config.get("sync_metric", "reviews_today")
            unconfigured = not token
            val = self._get_count(config)
            # Always fetch backlog separately so we can show "X left"
            from . import get_backlog

            backlog = get_backlog(config.get("deck_filter", "").strip() or None)
            self._badge.set_value(val, metric, backlog, unconfigured=unconfigured)
        except Exception:
            self._badge.set_value("?", "reviews_today", 0)

    def _on_click(self):
        config = self._mw.addonManager.getConfig(self._config_name)
        if config is None:
            config = {}
        dialog = BeeminderDialog(
            self._mw,
            config,
            self._config_name,
            self._get_deck_names,
            self._sync,
        )
        dialog.exec()
