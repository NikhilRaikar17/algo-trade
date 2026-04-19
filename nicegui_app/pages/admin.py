"""
Admin Settings page — visible to nikhil only.
Shows all users' last login, sessions today, and minutes spent today.
"""

import re
from datetime import datetime, timezone, timedelta

from nicegui import ui

from db import SessionLocal
from models import User, UserActivityLog
from auth import pwd_ctx

# IST = UTC+5:30
_IST = timezone(timedelta(hours=5, minutes=30))


def _get_admin_stats() -> list[dict]:
    """
    Return one dict per user with keys:
      username, last_login (str, IST), sessions_today (int), minutes_today (float)
    """
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC for DB arithmetic
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
                # login_at / logout_at are stored as naive UTC by auth.py — arithmetic is safe
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


def _add_user(username: str, password: str) -> str | None:
    """
    Insert a new user. Returns an error string on failure, None on success.
    """
    username = username.strip().lower()
    if not username:
        return "Username must not be empty."
    if not re.fullmatch(r"[a-z0-9_]{1,32}", username):
        return "Username must be 1–32 characters: letters, digits, or underscores only."
    if not password:
        return "Password must not be empty."
    if len(password) < 8:
        return "Password must be at least 8 characters."

    with SessionLocal() as s:
        exists = s.query(User).filter(User.username == username).first()
        if exists is not None:
            return f"User '{username}' already exists."
        s.add(User(username=username, hashed_password=pwd_ctx.hash(password)))
        s.commit()
    return None


def _delete_user(username: str) -> None:
    """Delete a user row by username. Does nothing if the user does not exist."""
    if username == "nikhil":
        return
    with SessionLocal() as s:
        s.query(UserActivityLog).filter(UserActivityLog.username == username).delete()
        user = s.query(User).filter(User.username == username).first()
        if user:
            s.delete(user)
        s.commit()


def render_admin_tab(container):
    """Render the admin settings page. Returns an async refresh() closure."""

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

    _build()

    async def refresh():
        _build()

    return refresh
