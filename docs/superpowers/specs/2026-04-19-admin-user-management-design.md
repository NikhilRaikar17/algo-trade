# Admin User Management — Design Spec

**Date:** 2026-04-19  
**Status:** Approved

---

## Overview

Add user management capabilities to the existing Admin Settings page (`nicegui_app/pages/admin.py`). The admin (`nikhil`) can add new users with a password and delete existing users directly from the page.

---

## UI Layout

An "Add User" form is placed **above** the existing user activity table. It contains:

- `ui.input` — Username (text)
- `ui.input` — Password (password-masked)
- "Add User" button

Below the form, the existing activity table gains a **Delete** column on the right. Each row shows a red trash icon button. Clicking it deletes that user. The `nikhil` row has the trash icon disabled (admin cannot delete themselves).

---

## Data Flow

**Add User:**
1. Validate username and password are non-empty (client-side, show `ui.notify` on error).
2. Check username does not already exist in DB — if it does, show error notification.
3. Hash password with `pwd_ctx.hash()` (imported from `auth.py`).
4. Insert new `User` row via `SessionLocal`.
5. Show success notification, clear inputs, refresh the page.

**Delete User:**
1. Guard: do not allow deleting `nikhil`.
2. Delete the `User` row by username via `SessionLocal`.
3. Associated `UserSession` and `UserActivityLog` rows are left in place (username FK — no cascade needed, data is historical).
4. Show success notification, refresh the page.

---

## Implementation Scope

All changes are confined to `nicegui_app/pages/admin.py`:

- `_add_user(username: str, password: str) -> str | None` — inserts user, returns error message or `None` on success.
- `_delete_user(username: str) -> None` — deletes user row.
- `render_admin_tab` updated to render the form and add the delete column to the table.

`auth.py` is imported for `pwd_ctx` (already available). No changes to `models.py`, `auth.py`, or `db.py`.

---

## Constraints

- `nikhil` cannot be deleted (hardcoded guard).
- Usernames are stored lowercase (consistent with existing `verify_user` logic).
- No password editing — out of scope.
- No role/permission system — all users are equivalent non-admin users; only `nikhil` sees the admin tab.
