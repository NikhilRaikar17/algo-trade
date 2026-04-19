# Admin Settings — Design Spec
**Date:** 2026-04-19
**Status:** Approved

## Overview

Add an admin-only page visible only to user `nikhil` that shows a table of all users, their last login time, number of sessions today, and total minutes spent in the app today (measured as session duration: login time to logout/now).

---

## Data Layer

### New model: `UserActivityLog` (in `models.py`)

| Column       | Type     | Notes                                      |
|--------------|----------|--------------------------------------------|
| id           | Integer  | Primary key, autoincrement                 |
| username     | String   | FK → users.username                        |
| session_key  | String   | Matches the session that was created       |
| login_at     | DateTime | Set when session is created (UTC)          |
| logout_at    | DateTime | Nullable; set when session is invalidated  |

### Changes to `auth.py`

- `create_session(username)`: after inserting `UserSession`, also insert a `UserActivityLog` row with `login_at = now`, `logout_at = None`.
- `invalidate_session(session_key)`: after deleting the `UserSession` row, find the matching `UserActivityLog` row by `session_key` and set `logout_at = now`.

### Query for admin page

For each user, compute today's stats (date in IST):
- **Last Login**: `User.last_login` (already stored)
- **Sessions Today**: count of `UserActivityLog` rows where `login_at` date == today IST
- **Minutes Today**: sum of `(logout_at or utcnow) - login_at` for rows where `login_at` date == today IST, converted to minutes (rounded to 1 decimal)

---

## UI Layer

### New file: `nicegui_app/pages/admin.py`

- Export `render_admin_tab(container)` following the existing page pattern
- Renders a styled table (matching terminal theme) with columns:
  - Username | Last Login (IST) | Sessions Today | Minutes Today
- One row per user (nikhil, bharath, indresh)
- Returns an async `refresh()` closure that clears and rebuilds the container

### Table styling

Use the existing terminal dark theme CSS variables (`--at-bg2`, `--at-line`, `--at-fg`, etc.) inline via NiceGUI `ui.html()` or `ui.aggrid()`. Match the style of existing data tables in the app.

---

## Sidebar

### Change to `build_sidebar()` signature

Add a `username: str = ""` parameter.

### Conditional admin section

After the LIVE TRADING section, conditionally render:

```
if username == "nikhil":
    ui.separator()
    _section_label("ADMIN")
    _nav_button("admin", "Admin Settings", "admin_panel_settings", icon_color="icon-rose")
```

---

## Wiring in `main.py`

1. Add `"admin"` to `ALL_PAGE_IDS`.
2. In `build_ui()`, add:
   ```python
   refresh_fns["admin"] = render_admin_tab(page_containers["admin"])
   ```
3. Pass `username_from_session` to `build_sidebar()`:
   ```python
   build_sidebar(drawer, active_page, nav_btn_refs, page_containers,
                 on_navigate=_on_navigate, username=username_from_session)
   ```

---

## Constraints

- The admin page is purely read-only; no editing of users.
- No new routes — follows the single-page container/visibility pattern.
- No numpy/pandas; all datetime math uses Python `datetime` only.
- All times displayed to the user are converted to IST.
