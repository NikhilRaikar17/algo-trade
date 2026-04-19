# Admin Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only admin page visible only to user `nikhil` that shows all users' login times and minutes spent in the app today.

**Architecture:** Add a `UserActivityLog` DB table that is written to on login/logout. An admin NiceGUI page queries this table and renders a terminal-styled table. The sidebar conditionally shows the admin nav entry based on username.

**Tech Stack:** Python, SQLAlchemy (SQLite), NiceGUI, `datetime` (no numpy/pandas)

---

## Files

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `nicegui_app/models.py` | Add `UserActivityLog` ORM model |
| Modify | `nicegui_app/auth.py` | Write activity log on login/logout |
| Create | `nicegui_app/pages/admin.py` | Admin page render function |
| Modify | `nicegui_app/pages/__init__.py` | Export `render_admin_tab` |
| Modify | `nicegui_app/sidebar.py` | Conditional admin nav section |
| Modify | `nicegui_app/main.py` | Wire admin page and pass username to sidebar |

---

## Task 1: Add `UserActivityLog` model

**Files:**
- Modify: `nicegui_app/models.py`

- [ ] **Step 1: Add the model** — open `nicegui_app/models.py` and insert after the `UserSession` class (around line 43):

```python
class UserActivityLog(Base):
    """One row per login session — records login and logout time."""
    __tablename__ = "user_activity_log"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    username    = Column(String, ForeignKey("users.username"), nullable=False)
    session_key = Column(String, nullable=False)
    login_at    = Column(DateTime, nullable=False)
    logout_at   = Column(DateTime, nullable=True)
```

- [ ] **Step 2: Verify the import** — `models.py` already imports `Column, DateTime, ForeignKey, Integer, String` from `sqlalchemy`. No new imports needed.

- [ ] **Step 3: Commit**

```bash
git add nicegui_app/models.py
git commit -m "feat: add UserActivityLog model"
```

---

## Task 2: Wire activity logging into auth.py

**Files:**
- Modify: `nicegui_app/auth.py`

- [ ] **Step 1: Import `UserActivityLog`** — in `auth.py` line 22, change:

```python
from models import User, UserSession, Strategy, TopStock  # noqa: F401 — ensures TopStock table is created
```
to:
```python
from models import User, UserSession, Strategy, TopStock, UserActivityLog  # noqa: F401
```

- [ ] **Step 2: Create activity log on login** — in `create_session()`, after `s.commit()` (around line 136) and before `return key`, add:

```python
    with SessionLocal() as s2:
        s2.add(UserActivityLog(
            username=username,
            session_key=key,
            login_at=now,
            logout_at=None,
        ))
        s2.commit()
```

- [ ] **Step 3: Set logout_at on invalidation** — in `invalidate_session()`, after `s.delete(row)` and before `s.commit()` (around line 165), add:

```python
        log_row = s.query(UserActivityLog).filter(
            UserActivityLog.session_key == session_key
        ).first()
        if log_row and log_row.logout_at is None:
            log_row.logout_at = datetime.utcnow()
```

- [ ] **Step 4: Ensure table is created** — `auth.py` already calls `Base.metadata.create_all(bind=engine)` which will pick up the new table automatically since `UserActivityLog` is imported.

- [ ] **Step 5: Commit**

```bash
git add nicegui_app/auth.py
git commit -m "feat: log user activity on login/logout"
```

---

## Task 3: Create the admin page

**Files:**
- Create: `nicegui_app/pages/admin.py`

- [ ] **Step 1: Create `nicegui_app/pages/admin.py`** with this content:

```python
"""
Admin Settings page — visible to nikhil only.
Shows all users' last login, sessions today, and minutes spent today.
"""

from datetime import datetime, timezone, timedelta

from nicegui import ui

from db import SessionLocal
from models import User, UserActivityLog

# IST = UTC+5:30
_IST = timezone(timedelta(hours=5, minutes=30))


def _get_admin_stats() -> list[dict]:
    """
    Return one dict per user with keys:
      username, last_login (str, IST), sessions_today (int), minutes_today (float)
    """
    now_utc = datetime.utcnow()
    today_ist = datetime.now(_IST).date()

    with SessionLocal() as s:
        users = s.query(User).order_by(User.username).all()
        rows = []
        for user in users:
            # Last login — convert UTC → IST string
            if user.last_login:
                ll_ist = user.last_login.replace(tzinfo=timezone.utc).astimezone(_IST)
                last_login_str = ll_ist.strftime("%d %b %Y  %H:%M IST")
            else:
                last_login_str = "—"

            # Activity logs where login_at date == today IST
            logs = (
                s.query(UserActivityLog)
                .filter(UserActivityLog.username == user.username)
                .all()
            )
            today_logs = [
                lg for lg in logs
                if lg.login_at.replace(tzinfo=timezone.utc).astimezone(_IST).date() == today_ist
            ]

            sessions_today = len(today_logs)

            total_seconds = 0.0
            for lg in today_logs:
                end = lg.logout_at if lg.logout_at else now_utc
                delta = (end - lg.login_at).total_seconds()
                if delta > 0:
                    total_seconds += delta

            minutes_today = round(total_seconds / 60, 1)

            rows.append({
                "username": user.username,
                "last_login": last_login_str,
                "sessions_today": sessions_today,
                "minutes_today": minutes_today,
            })

    return rows


def render_admin_tab(container):
    """Render the admin settings page. Returns an async refresh() closure."""

    def _build():
        container.clear()
        with container:
            ui.html("""
            <div style="
                font-family: 'Outfit', sans-serif;
                font-size: 11px; font-weight: 700;
                letter-spacing: 0.14em; text-transform: uppercase;
                color: var(--at-fg-faint); margin-bottom: 12px;
            ">ADMIN · USER ACTIVITY</div>
            """)

            stats = _get_admin_stats()

            # Table wrapper
            with ui.element("div").style(
                "width: 100%; overflow-x: auto;"
            ):
                ui.html(_build_table_html(stats))

    def _build_table_html(stats: list[dict]) -> str:
        header_style = (
            "font-family:'JetBrains Mono',monospace; font-size:10px; font-weight:700;"
            "letter-spacing:0.1em; text-transform:uppercase; color:var(--at-fg-faint);"
            "padding:8px 16px; border-bottom:1px solid var(--at-line); text-align:left;"
        )
        cell_style = (
            "font-family:'JetBrains Mono',monospace; font-size:12px;"
            "color:var(--at-fg); padding:10px 16px; border-bottom:1px solid var(--at-line2);"
        )
        name_style = (
            "font-family:'Outfit',sans-serif; font-size:13px; font-weight:600;"
            "color:var(--at-accent); padding:10px 16px; border-bottom:1px solid var(--at-line2);"
        )

        rows_html = ""
        for row in stats:
            rows_html += (
                f'<tr>'
                f'<td style="{name_style}">{row["username"].upper()}</td>'
                f'<td style="{cell_style}">{row["last_login"]}</td>'
                f'<td style="{cell_style}; text-align:center;">{row["sessions_today"]}</td>'
                f'<td style="{cell_style}; text-align:center;">{row["minutes_today"]} min</td>'
                f'</tr>'
            )

        return (
            f'<table style="width:100%; border-collapse:collapse; background:var(--at-bg2);">'
            f'<thead><tr>'
            f'<th style="{header_style}">Username</th>'
            f'<th style="{header_style}">Last Login</th>'
            f'<th style="{header_style}; text-align:center;">Sessions Today</th>'
            f'<th style="{header_style}; text-align:center;">Minutes Today</th>'
            f'</tr></thead>'
            f'<tbody>{rows_html}</tbody>'
            f'</table>'
        )

    _build()

    async def refresh():
        _build()

    return refresh
```

- [ ] **Step 2: Commit**

```bash
git add nicegui_app/pages/admin.py
git commit -m "feat: add admin settings page"
```

---

## Task 4: Export from pages/__init__.py

**Files:**
- Modify: `nicegui_app/pages/__init__.py`

- [ ] **Step 1: Add export** — append to `nicegui_app/pages/__init__.py`:

```python
from pages.admin import render_admin_tab
```

- [ ] **Step 2: Commit**

```bash
git add nicegui_app/pages/__init__.py
git commit -m "chore: export render_admin_tab"
```

---

## Task 5: Conditional admin section in sidebar

**Files:**
- Modify: `nicegui_app/sidebar.py`

- [ ] **Step 1: Update function signature** — change line 33 from:

```python
def build_sidebar(drawer, active_page, nav_btn_refs, page_containers, on_navigate=None):
```
to:
```python
def build_sidebar(drawer, active_page, nav_btn_refs, page_containers, on_navigate=None, username: str = ""):
```

- [ ] **Step 2: Add admin nav section** — in `sidebar.py`, after the `# LIVE TRADING` section (after the `_nav_button("pnl", ...)` line, around line 125) and before `ui.separator().style(_S["sep"])`, add:

```python
            # ADMIN (nikhil only)
            if username == "nikhil":
                ui.separator().style(_S["sep"])
                _section_label("ADMIN")
                _nav_button("admin", "Admin Settings", "admin_panel_settings", icon_color="icon-rose")
```

- [ ] **Step 3: Commit**

```bash
git add nicegui_app/sidebar.py
git commit -m "feat: show admin nav entry for nikhil"
```

---

## Task 6: Wire admin page in main.py

**Files:**
- Modify: `nicegui_app/main.py`

- [ ] **Step 1: Add "admin" to ALL_PAGE_IDS** — in `main.py`, find `ALL_PAGE_IDS` (around line 52) and add `"admin"` to the list:

```python
ALL_PAGE_IDS = [
    "dashboard",
    "markets",
    "market_news",
    "top_stocks",
    "swing_trades",
    "global_markets",
    "nifty",
    "banknifty",
    "algo",
    "abcd_only",
    "dt_only",
    "db_only",
    "sma50",
    "ema10",
    "backtest_pnl",
    "pnl",
    "admin",
]
```

- [ ] **Step 2: Import render_admin_tab** — in `main.py`, add to the imports from `pages` (around line 30):

```python
from pages import (
    render_dashboard,
    render_markets_tab,
    render_index_tab,
    render_algo_tab,
    render_abcd_only_tab,
    render_double_top_tab,
    render_double_bottom_tab,
    render_sma50_tab,
    render_ema10_tab,
    render_pnl_tab,
    render_backtest_pnl_tab,
    render_market_closed,
    render_market_news_tab,
    render_top_stocks_tab,
    render_swing_trades_tab,
    render_global_markets_tab,
    render_admin_tab,
)
```

- [ ] **Step 3: Register admin page in build_ui()** — in `build_ui()`, after `refresh_fns["backtest_pnl"] = ...` (around line 596), add:

```python
        refresh_fns["admin"] = render_admin_tab(page_containers["admin"])
```

- [ ] **Step 4: Pass username to build_sidebar()** — find the `build_sidebar(...)` call (around line 558) and add the `username` kwarg:

```python
    build_sidebar(
        drawer, active_page, nav_btn_refs, page_containers,
        on_navigate=_on_navigate,
        username=username_from_session,
    )
```

- [ ] **Step 5: Commit**

```bash
git add nicegui_app/main.py
git commit -m "feat: wire admin page into main app"
```

---

## Task 7: Manual smoke test

- [ ] **Step 1: Start the app**

```bash
cd nicegui_app
uv run python main.py
```

- [ ] **Step 2: Log in as `nikhil` / `nikhil`** — navigate to `http://localhost:8501/login`. Verify the sidebar shows "ADMIN" section with "Admin Settings" link.

- [ ] **Step 3: Open Admin Settings** — click "Admin Settings" in the sidebar. Verify the table loads with columns: Username | Last Login | Sessions Today | Minutes Today.

- [ ] **Step 4: Log in as `bharath`** — log out, then log in as `bharath`. Verify the "ADMIN" sidebar section is **not** visible.

- [ ] **Step 5: Log back in as `nikhil`** — verify bharath now shows at least 1 session today and minutes > 0 in the admin table.
