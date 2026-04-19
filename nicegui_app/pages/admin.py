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
