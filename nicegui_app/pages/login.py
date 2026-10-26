from datetime import datetime

from nicegui import ui, app

from auth import verify_user, create_session
from config import IST
from state import is_market_open


def render_login_page():
    """Standalone login page — served at / and /login."""

    ui.page_title("AlgoTrade — Sign in")

    ui.add_head_html(
        '<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
        '<link href="https://fonts.googleapis.com/css2?'
        'family=Outfit:wght@500;600;700'
        '&family=DM+Sans:wght@400;500;600'
        '&family=JetBrains+Mono:wght@400;500'
        '&display=swap" rel="stylesheet">'
    )
    ui.add_head_html("""
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        :root {
            --lg-bg:    #0a0d10;
            --lg-panel: #0f1317;
            --lg-field: #141a1f;
            --lg-line:  #1f2830;
            --lg-line2: #2a353f;
            --lg-fg:    #e6edf3;
            --lg-dim:   #8a97a3;
            --lg-faint: #5a6672;
            --lg-accent:#00d084;
            --lg-down:  #ff4d5e;
            --lg-mono:  'JetBrains Mono', ui-monospace, Menlo, monospace;
            --lg-sans:  'DM Sans', -apple-system, system-ui, sans-serif;
            --lg-disp:  'Outfit', var(--lg-sans);
        }
        html, body {
            margin: 0 !important;
            padding: 0 !important;
            background: var(--lg-bg) !important;
            color: var(--lg-fg);
            font-family: var(--lg-sans);
            -webkit-font-smoothing: antialiased;
        }
        #q-app, .q-layout, .q-page-container, .q-page, .nicegui-content {
            padding: 0 !important;
            margin: 0 !important;
            background: transparent !important;
            min-height: unset !important;
        }
        *, *::before, *::after { box-sizing: border-box; }

        .lg-root {
            min-height: 100vh;
            width: 100%;
            display: flex;
            flex-direction: column;
            background:
                linear-gradient(var(--lg-line) 1px, transparent 1px) 0 0 / 100% 64px,
                var(--lg-bg);
        }
        .lg-root::before {
            /* fade the grid lines out toward the centre */
            content: '';
            position: fixed;
            inset: 0;
            background: radial-gradient(ellipse at center, var(--lg-bg) 35%, rgba(10,13,16,0.6) 100%);
            pointer-events: none;
        }

        .lg-top, .lg-bottom {
            position: relative;
            z-index: 1;
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 20px 32px;
            font-family: var(--lg-mono);
            font-size: 0.72rem;
            color: var(--lg-faint);
            letter-spacing: 0.04em;
        }

        .lg-brand {
            display: flex;
            align-items: center;
            gap: 10px;
            font-family: var(--lg-disp);
            font-size: 1.05rem;
            font-weight: 600;
            color: var(--lg-fg);
            letter-spacing: -0.01em;
        }

        .lg-status {
            display: inline-flex;
            align-items: center;
            gap: 8px;
        }
        .lg-dot {
            width: 6px; height: 6px;
            border-radius: 50%;
            background: var(--lg-faint);
        }
        .lg-dot.open { background: var(--lg-accent); }

        .lg-main {
            position: relative;
            z-index: 1;
            flex: 1;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 24px 16px;
        }

        .lg-card {
            width: 100%;
            max-width: 380px;
            background: var(--lg-panel);
            border: 1px solid var(--lg-line);
            border-radius: 8px;
            padding: 36px 32px 28px;
        }

        .lg-title {
            font-family: var(--lg-disp);
            font-size: 1.35rem;
            font-weight: 600;
            line-height: 1.3;
            color: var(--lg-fg);
            letter-spacing: -0.01em;
            margin: 0 0 6px;
        }
        .lg-sub {
            font-size: 0.85rem;
            color: var(--lg-dim);
            margin: 0 0 28px;
        }

        .lg-label {
            display: block;
            font-family: var(--lg-mono);
            font-size: 0.68rem;
            font-weight: 500;
            color: var(--lg-dim);
            letter-spacing: 0.08em;
            text-transform: uppercase;
            margin-bottom: 6px;
        }

        /* Quasar input overrides */
        .lg-card .q-field__control {
            background: var(--lg-field) !important;
            border-radius: 6px !important;
            height: 42px !important;
            min-height: 42px !important;
        }
        .lg-card .q-field__native,
        .lg-card .q-field__input {
            color: var(--lg-fg) !important;
            font-family: var(--lg-sans) !important;
            font-size: 0.9rem !important;
        }
        .lg-card .q-field__native::placeholder { color: var(--lg-faint) !important; }
        .lg-card .q-field--outlined .q-field__control:before {
            border-color: var(--lg-line2) !important;
        }
        .lg-card .q-field--outlined:hover .q-field__control:before {
            border-color: var(--lg-faint) !important;
        }
        .lg-card .q-field--outlined.q-field--focused .q-field__control:after {
            border-color: var(--lg-accent) !important;
            border-width: 1px !important;
        }
        .lg-card .q-icon { color: var(--lg-faint) !important; }

        .lg-error {
            display: none;
            align-items: center;
            gap: 8px;
            font-size: 0.8rem;
            color: var(--lg-down);
            background: rgba(255,77,94,0.08);
            border: 1px solid rgba(255,77,94,0.25);
            border-radius: 6px;
            padding: 9px 12px;
            margin-top: 4px;
        }
        .lg-error.visible { display: flex; }

        .lg-btn {
            width: 100%;
            height: 42px !important;
            margin-top: 20px;
            border-radius: 6px !important;
            background: var(--lg-accent) !important;
            color: #04110b !important;
            font-family: var(--lg-sans) !important;
            font-weight: 600 !important;
            font-size: 0.9rem !important;
            text-transform: none !important;
            letter-spacing: 0 !important;
        }
        .lg-btn:hover { filter: brightness(1.08); }

        .lg-note {
            margin-top: 22px;
            padding-top: 18px;
            border-top: 1px solid var(--lg-line);
            font-size: 0.75rem;
            color: var(--lg-faint);
            line-height: 1.6;
        }

        @media (max-width: 540px) {
            .lg-top, .lg-bottom { padding: 16px; }
            .lg-bottom { flex-direction: column; gap: 6px; }
            .lg-card { padding: 28px 20px 22px; border-radius: 6px; }
        }
    </style>
    """)

    market_open = is_market_open()
    now_ist = datetime.now(IST).strftime("%d %b %Y · %H:%M IST")

    with ui.element("div").classes("lg-root"):
        ui.html(f"""
        <div class="lg-top">
          <div class="lg-brand">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none"
                 stroke="#00d084" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="3 17 9 11 13 15 21 7"/>
              <polyline points="15 7 21 7 21 13"/>
            </svg>
            AlgoTrade
          </div>
          <div class="lg-status">
            <span class="lg-dot{' open' if market_open else ''}"></span>
            NSE {'OPEN' if market_open else 'CLOSED'}
          </div>
        </div>
        """)

        with ui.element("div").classes("lg-main"):
            with ui.element("div").classes("lg-card"):
                ui.html("""
                <div class="lg-title">Sign in</div>
                <div class="lg-sub">Access the NIFTY &amp; BANKNIFTY trading console.</div>
                """)

                ui.html('<span class="lg-label">Username</span>')
                username = ui.input(
                    placeholder="Username",
                ).props('outlined dense autocomplete="username"').classes("w-full mb-4")

                ui.html('<span class="lg-label">Password</span>')
                password = ui.input(
                    placeholder="Password",
                    password=True,
                    password_toggle_button=True,
                ).props('outlined dense autocomplete="current-password"').classes("w-full mb-2")

                ui.html(
                    '<div class="lg-error" id="login-error">'
                    '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
                    '<circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/>'
                    '<line x1="12" y1="16" x2="12.01" y2="16"/></svg>'
                    'Incorrect username or password.'
                    '</div>'
                )

                def do_login():
                    u = username.value.strip().lower()
                    p = password.value
                    if verify_user(u, p):
                        session_key = create_session(u)
                        app.storage.user["authenticated"] = True
                        app.storage.user["username"] = u
                        app.storage.user["session_key"] = session_key
                        ui.navigate.to("/app")
                    else:
                        ui.run_javascript(
                            'document.getElementById("login-error").classList.add("visible")'
                        )

                username.on("keydown.enter", do_login)
                password.on("keydown.enter", do_login)

                ui.button("Sign in", on_click=do_login, color=None).props("unelevated no-caps").classes("lg-btn")

                ui.html(
                    '<div class="lg-note">Authorised users only. '
                    'Contact the administrator if you need access.</div>'
                )

        ui.html(f"""
        <div class="lg-bottom">
          <span>{now_ist}</span>
          <span>Market hours 09:15 – 15:30 IST</span>
        </div>
        """)
