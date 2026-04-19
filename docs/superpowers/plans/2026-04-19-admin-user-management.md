# Admin User Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add "Add User" form and per-row delete buttons to the Admin Settings page so nikhil can manage users without touching the database directly.

**Architecture:** All changes are confined to `nicegui_app/pages/admin.py`. Two new helper functions (`_add_user`, `_delete_user`) handle DB writes. The existing `render_admin_tab` is extended to render the form above the table and add a delete column to each row.

**Tech Stack:** NiceGUI, SQLAlchemy (SQLite), passlib sha256_crypt (via `auth.py`'s `pwd_ctx`)

---

### Task 1: Add `_add_user` and `_delete_user` helpers

**Files:**
- Modify: `nicegui_app/pages/admin.py`

- [ ] **Step 1: Open `nicegui_app/pages/admin.py` and add imports**

At the top of the file, the existing imports are:
```python
from datetime import datetime, timezone, timedelta
from nicegui import ui
from db import SessionLocal
from models import User, UserActivityLog
```

Add the `pwd_ctx` import from `auth`:
```python
from datetime import datetime, timezone, timedelta
from nicegui import ui
from db import SessionLocal
from models import User, UserActivityLog
from auth import pwd_ctx
```

- [ ] **Step 2: Add `_add_user` helper after `_get_admin_stats`**

Insert this function after the `_get_admin_stats` function (after line 66):

```python
def _add_user(username: str, password: str) -> str | None:
    """
    Insert a new user. Returns an error string on failure, None on success.
    """
    username = username.strip().lower()
    if not username:
        return "Username must not be empty."
    if not password:
        return "Password must not be empty."

    with SessionLocal() as s:
        exists = s.query(User).filter(User.username == username).first()
        if exists is not None:
            return f"User '{username}' already exists."
        s.add(User(username=username, hashed_password=pwd_ctx.hash(password)))
        s.commit()
    return None


def _delete_user(username: str) -> None:
    """Delete a user row by username. Does nothing if the user does not exist."""
    with SessionLocal() as s:
        user = s.query(User).filter(User.username == username).first()
        if user:
            s.delete(user)
            s.commit()
```

- [ ] **Step 3: Commit**

```bash
git add nicegui_app/pages/admin.py
git commit -m "feat: add _add_user and _delete_user helpers to admin page"
```

---

### Task 2: Add "Add User" form to `render_admin_tab`

**Files:**
- Modify: `nicegui_app/pages/admin.py`

- [ ] **Step 1: Replace `_build` inside `render_admin_tab` with the version below**

The current `_build` function (starting at line 110) looks like:

```python
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
```

Replace it with:

```python
def _build():
    container.clear()
    with container:
        # ── Section label ──────────────────────────────────────────────
        ui.html("""
        <div style="
            font-family: 'Outfit', sans-serif;
            font-size: 11px; font-weight: 700;
            letter-spacing: 0.14em; text-transform: uppercase;
            color: var(--at-fg-faint); margin-bottom: 12px;
        ">ADMIN · USER MANAGEMENT</div>
        """)

        # ── Add User form ──────────────────────────────────────────────
        with ui.row().style("align-items: flex-end; gap: 8px; margin-bottom: 20px;"):
            username_input = ui.input(
                label="Username",
                placeholder="new_user",
            ).style(
                "font-family:'JetBrains Mono',monospace; font-size:12px; width:160px;"
            )
            password_input = ui.input(
                label="Password",
                placeholder="••••••••",
                password=True,
                password_toggle_button=True,
            ).style(
                "font-family:'JetBrains Mono',monospace; font-size:12px; width:160px;"
            )

            def on_add_user():
                err = _add_user(username_input.value, password_input.value)
                if err:
                    ui.notify(err, type="negative")
                else:
                    ui.notify(
                        f"User '{username_input.value.strip().lower()}' added.",
                        type="positive",
                    )
                    username_input.value = ""
                    password_input.value = ""
                    _build()

            ui.button("Add User", on_click=on_add_user).style(
                "font-family:'Outfit',sans-serif; font-size:12px; font-weight:600;"
                "background:var(--at-accent); color:#fff; border-radius:6px;"
                "padding:6px 14px;"
            )

        # ── User activity table ────────────────────────────────────────
        ui.html("""
        <div style="
            font-family: 'Outfit', sans-serif;
            font-size: 11px; font-weight: 700;
            letter-spacing: 0.14em; text-transform: uppercase;
            color: var(--at-fg-faint); margin-bottom: 12px;
        ">ADMIN · USER ACTIVITY</div>
        """)

        stats = _get_admin_stats()

        with ui.element("div").style("width: 100%; overflow-x: auto;"):
            ui.html(_build_table_html(stats))
```

- [ ] **Step 2: Commit**

```bash
git add nicegui_app/pages/admin.py
git commit -m "feat: add Add User form to admin page"
```

---

### Task 3: Add Delete column to the activity table

**Files:**
- Modify: `nicegui_app/pages/admin.py`

The activity table is built as raw HTML in `_build_table_html`. Because delete buttons need Python callbacks, we cannot use raw HTML for them. We'll replace the HTML table with a NiceGUI element-based table that supports per-row buttons.

- [ ] **Step 1: Replace `_build_table_html` and its call-site inside `_build`**

Remove `_build_table_html` entirely and replace the table rendering inside `_build` (the section labelled `# ── User activity table ────`) with:

```python
        # ── User activity table ────────────────────────────────────────
        ui.html("""
        <div style="
            font-family: 'Outfit', sans-serif;
            font-size: 11px; font-weight: 700;
            letter-spacing: 0.14em; text-transform: uppercase;
            color: var(--at-fg-faint); margin-bottom: 12px;
        ">ADMIN · USER ACTIVITY</div>
        """)

        stats = _get_admin_stats()

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

        with ui.element("div").style("width:100%; overflow-x:auto;"):
            with ui.element("table").style(
                "width:100%; border-collapse:collapse; background:var(--at-bg2);"
            ):
                # Header row
                with ui.element("thead"):
                    with ui.element("tr"):
                        for label, extra in [
                            ("Username", ""),
                            ("Last Login", ""),
                            ("Sessions Today", " text-align:center;"),
                            ("Minutes Today", " text-align:center;"),
                            ("", ""),  # delete column — no label
                        ]:
                            with ui.element("th").style(header_style + extra):
                                ui.label(label)

                # Body rows
                with ui.element("tbody"):
                    for row in stats:
                        uname = row["username"]
                        with ui.element("tr"):
                            with ui.element("td").style(name_style):
                                ui.label(uname.upper())
                            with ui.element("td").style(cell_style):
                                ui.label(row["last_login"])
                            with ui.element("td").style(cell_style + " text-align:center;"):
                                ui.label(str(row["sessions_today"]))
                            with ui.element("td").style(cell_style + " text-align:center;"):
                                ui.label(f"{row['minutes_today']} min")
                            with ui.element("td").style(
                                cell_style + " text-align:center; width:48px;"
                            ):
                                if uname == "nikhil":
                                    # Admin row — no delete button
                                    ui.label("—").style("color:var(--at-fg-faint);")
                                else:
                                    def make_delete(u: str):
                                        def on_delete():
                                            _delete_user(u)
                                            ui.notify(
                                                f"User '{u}' deleted.",
                                                type="warning",
                                            )
                                            _build()
                                        return on_delete

                                    ui.button(
                                        icon="delete",
                                        on_click=make_delete(uname),
                                    ).props("flat dense color=negative size=sm")
```

- [ ] **Step 2: Remove the now-unused `_build_table_html` function**

Delete the entire `_build_table_html` method (lines 72–108 in the original file). It is no longer called.

- [ ] **Step 3: Verify the app starts without errors**

```bash
cd nicegui_app
uv run python main.py
```

Expected: server starts at `http://0.0.0.0:8501` with no import errors or tracebacks.

- [ ] **Step 4: Manual smoke test**

1. Open `http://localhost:8501`, log in as `nikhil`.
2. Navigate to Admin Settings.
3. Add a new user (e.g., `testuser` / `testpass`) — confirm success notification appears and the user appears in the table.
4. Delete `testuser` — confirm warning notification and row disappears.
5. Try to add a duplicate username — confirm error notification.
6. Confirm `nikhil` row shows `—` instead of a delete button.

- [ ] **Step 5: Commit**

```bash
git add nicegui_app/pages/admin.py
git commit -m "feat: add delete button per user row in admin page, remove HTML table builder"
```
