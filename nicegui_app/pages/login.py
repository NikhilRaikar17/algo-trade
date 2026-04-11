from nicegui import ui, app

from auth import verify_user, create_session


def render_login_page():
    """Standalone login page."""

    ui.page_title("AlgoTrade — Login")

    ui.add_head_html("""
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        html, body {
            margin: 0 !important;
            padding: 0 !important;
            width: 100% !important;
            background: #f1f5f9 !important;
            font-family: 'Inter', system-ui, -apple-system, sans-serif;
        }
        #q-app, .q-layout, .q-page-container, .q-page {
            padding: 0 !important;
            margin: 0 !important;
            background: transparent !important;
            min-height: unset !important;
        }
        *, *::before, *::after { box-sizing: border-box; }

        /* ── Full-page centering wrapper ── */
        .login-root {
            min-height: 100vh;
            width: 100vw;
            background: #f1f5f9;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 32px 16px;
            position: relative;
            overflow: hidden;
        }

        /* ── Dot-grid background ── */
        .login-bg {
            position: absolute;
            inset: 0;
            background-image: radial-gradient(circle, #cbd5e1 1px, transparent 1px);
            background-size: 28px 28px;
            opacity: 0.55;
            pointer-events: none;
        }

        /* ── Colour blobs ── */
        .orb {
            position: absolute;
            border-radius: 50%;
            filter: blur(90px);
            pointer-events: none;
            animation: orbPulse 9s ease-in-out infinite alternate;
        }
        .orb-1 {
            width: 460px; height: 460px;
            background: radial-gradient(circle, rgba(16,185,129,0.2) 0%, transparent 65%);
            top: -140px; right: -100px;
        }
        .orb-2 {
            width: 360px; height: 360px;
            background: radial-gradient(circle, rgba(16,185,129,0.14) 0%, transparent 65%);
            bottom: -100px; left: -80px;
            animation-delay: -4s;
        }
        @keyframes orbPulse {
            0%   { opacity: 0.65; transform: scale(1); }
            100% { opacity: 1;    transform: scale(1.1); }
        }

        /* ── The card ── */
        .login-card {
            position: relative;
            z-index: 2;
            width: 100%;
            max-width: 1020px;
            min-height: 520px;
            background: #ffffff;
            border-radius: 24px;
            box-shadow: 0 8px 48px rgba(0,0,0,0.10), 0 1px 4px rgba(0,0,0,0.06);
            display: flex;
            align-items: stretch;
            overflow: hidden;
        }
        /* NiceGUI injects wrapper divs — make them stretch too */
        .login-card > div {
            display: flex;
            align-items: stretch;
            flex: 1;
            min-width: 0;
        }

        /* ── Left branding pane ── */
        .card-left {
            flex: 1;
            align-self: stretch;
            background: linear-gradient(150deg, #064e3b 0%, #065f46 45%, #047857 100%);
            padding: 48px 44px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            position: relative;
            overflow: hidden;
        }
        /* decorative circles inside left pane */
        .card-left::before {
            content: '';
            position: absolute;
            width: 340px; height: 340px;
            border-radius: 50%;
            border: 1px solid rgba(255,255,255,0.08);
            top: -80px; right: -80px;
        }
        .card-left::after {
            content: '';
            position: absolute;
            width: 220px; height: 220px;
            border-radius: 50%;
            border: 1px solid rgba(255,255,255,0.06);
            bottom: -60px; left: -40px;
        }

        .brand-logo {
            display: flex;
            align-items: center;
            gap: 10px;
            position: relative;
            z-index: 1;
        }
        .brand-icon {
            width: 40px; height: 40px;
            background: rgba(255,255,255,0.15);
            border: 1px solid rgba(255,255,255,0.2);
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.2rem;
        }
        .brand-name {
            font-size: 1.25rem;
            font-weight: 800;
            color: #ffffff;
            letter-spacing: -0.03em;
        }
        .brand-name span { color: #6ee7b7; }

        .card-left-body { position: relative; z-index: 1; }
        .hero-headline {
            font-size: clamp(1.6rem, 2.5vw, 2.4rem);
            font-weight: 800;
            color: #ffffff;
            line-height: 1.2;
            letter-spacing: -0.03em;
            margin: 0 0 16px;
        }
        .hero-headline .hl { color: #6ee7b7; }
        .hero-sub {
            font-size: 0.88rem;
            color: rgba(255,255,255,0.6);
            line-height: 1.7;
            margin-bottom: 36px;
        }

        .stats-row {
            display: flex;
            gap: 28px;
            flex-wrap: wrap;
        }
        .stat-value {
            font-size: 1.4rem;
            font-weight: 800;
            color: #ffffff;
            letter-spacing: -0.03em;
        }
        .stat-label {
            font-size: 0.68rem;
            color: rgba(255,255,255,0.45);
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            margin-top: 2px;
        }

        .card-left-footer {
            position: relative;
            z-index: 1;
            font-size: 0.72rem;
            color: rgba(255,255,255,0.3);
        }

        /* ── Right form pane ── */
        .card-right {
            width: 420px;
            flex-shrink: 0;
            padding: 48px 40px;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-self: stretch;
        }

        .form-title {
            font-size: 1.5rem;
            font-weight: 800;
            color: #0f172a;
            letter-spacing: -0.03em;
            margin-bottom: 4px;
        }
        .form-subtitle {
            font-size: 0.84rem;
            color: #64748b;
            margin-bottom: 32px;
        }

        .login-label {
            display: block;
            font-size: 0.71rem;
            font-weight: 700;
            color: #64748b;
            letter-spacing: 0.07em;
            text-transform: uppercase;
            margin-bottom: 6px;
        }

        .form-divider {
            width: 100%;
            height: 1px;
            background: #f1f5f9;
            margin: 20px 0;
        }

        /* ── Sign-in button ── */
        .signin-btn {
            width: 100%;
            height: 46px;
            border: none;
            border-radius: 12px;
            background: linear-gradient(135deg, #10b981 0%, #059669 100%);
            color: #fff;
            font-size: 0.93rem;
            font-weight: 700;
            cursor: pointer;
            position: relative;
            overflow: hidden;
            transition: transform 0.15s, box-shadow 0.15s;
            box-shadow: 0 4px 18px rgba(16,185,129,0.38);
            letter-spacing: 0.01em;
        }
        .signin-btn::after {
            content: '';
            position: absolute;
            inset: 0;
            background: linear-gradient(135deg, rgba(255,255,255,0.14), transparent);
        }
        .signin-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 26px rgba(16,185,129,0.48);
        }
        .signin-btn:active { transform: translateY(0); }

        /* ── Error box ── */
        .login-error {
            width: 100%;
            background: #fef2f2;
            border: 1px solid #fecaca;
            border-radius: 10px;
            color: #dc2626;
            font-size: 0.81rem;
            padding: 10px 13px;
            margin-top: 12px;
            display: none;
            align-items: center;
            gap: 8px;
        }
        .login-error.visible { display: flex; }

        .form-footer {
            text-align: center;
            margin-top: 24px;
            font-size: 0.73rem;
            color: #94a3b8;
        }

        /* ── Quasar input overrides (scoped to card-right) ── */
        .card-right .q-field__control {
            background: #f8fafc !important;
            border-radius: 10px !important;
        }
        .card-right .q-field__native,
        .card-right .q-field__input {
            color: #0f172a !important;
        }
        .card-right .q-field--outlined .q-field__control:before {
            border-color: #e2e8f0 !important;
        }
        .card-right .q-field--outlined:hover .q-field__control:before {
            border-color: #6ee7b7 !important;
        }
        .card-right .q-field--focused .q-field__control:before,
        .card-right .q-field--outlined.q-field--focused .q-field__control:after {
            border-color: #10b981 !important;
        }
        .card-right .q-field__label { color: #94a3b8 !important; }
        .card-right .q-icon { color: #94a3b8 !important; }

        /* ── Responsive ── */
        @media (max-width: 700px) {
            .login-card { flex-direction: column; max-width: 440px; min-height: unset; }
            .card-left { padding: 36px 32px 32px; }
            .hero-headline { font-size: 1.6rem; }
            .stats-row { gap: 20px; }
            .card-right { width: 100%; padding: 36px 32px 40px; }
        }

        @media (max-width: 440px) {
            .login-root { padding: 0; align-items: stretch; }
            .login-card { border-radius: 0; max-width: 100%; box-shadow: none; }
            .card-left { padding: 32px 24px 28px; }
            .card-right { padding: 32px 24px 36px; }
            .hero-headline { font-size: 1.45rem; }
        }
    </style>
    """)

    with ui.element("div").classes("login-root"):
        ui.html("""
        <div class="login-bg"></div>
        <div class="orb orb-1"></div>
        <div class="orb orb-2"></div>
        """)

        with ui.element("div").classes("login-card"):

            # ── Left branding pane ──
            ui.html("""
            <div class="card-left">
              <div class="brand-logo">
                <div class="brand-icon">📈</div>
                <span class="brand-name">Algo<span>Trade</span></span>
              </div>

              <div class="card-left-body">
                <h1 class="hero-headline">
                  Institutional-grade<br>
                  <span class="hl">options intelligence</span><br>
                  for Indian markets.
                </h1>
                <p class="hero-sub">
                  Real-time NIFTY &amp; BANKNIFTY signals powered by ABCD
                  harmonic patterns and RSI/SMA crossover strategies — built
                  for speed, precision, and consistent edge.
                </p>
                <div class="stats-row">
                  <div>
                    <div class="stat-value">15 min</div>
                    <div class="stat-label">Candle intervals</div>
                  </div>
                  <div>
                    <div class="stat-value">2</div>
                    <div class="stat-label">Live indices</div>
                  </div>
                  <div>
                    <div class="stat-value">3</div>
                    <div class="stat-label">Strategies</div>
                  </div>
                </div>
              </div>

              <div class="card-left-footer">Secure · Encrypted · Private</div>
            </div>
            """)

            # ── Right form pane ──
            with ui.element("div").classes("card-right"):
                ui.html("""
                <div class="form-title">Welcome back</div>
                <div class="form-subtitle">Sign in to your trading dashboard</div>
                """)

                ui.html('<span class="login-label">Username</span>')
                username = ui.input(
                    placeholder="Enter username",
                ).props('outlined dense').classes("w-full mb-4")

                ui.html('<span class="login-label">Password</span>')
                password = ui.input(
                    placeholder="Enter password",
                    password=True,
                    password_toggle_button=True,
                ).props('outlined dense').classes("w-full mb-1")

                ui.html(
                    '<div class="login-error" id="login-error">'
                    '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">'
                    '<circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/>'
                    '<line x1="12" y1="16" x2="12.01" y2="16"/></svg>'
                    'Invalid username or password.'
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

                password.on("keydown.enter", do_login)

                ui.html('<div class="form-divider"></div>')

                ui.button(
                    "Sign In →",
                    on_click=do_login,
                ).props("unelevated").classes("signin-btn w-full").style(
                    "background: linear-gradient(135deg, #10b981, #059669) !important;"
                    "color: #fff !important;"
                    "font-weight: 700 !important;"
                    "font-size: 0.93rem !important;"
                    "border-radius: 12px !important;"
                    "height: 46px !important;"
                    "box-shadow: 0 4px 18px rgba(16,185,129,0.38) !important;"
                )

                ui.html('<div class="form-footer">AlgoTrade &copy; 2025</div>')
