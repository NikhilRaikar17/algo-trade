from nicegui import ui, app


VALID_CREDENTIALS = {"admin": "admin"}


def render_login_page():
    """Standalone login page."""

    ui.page_title("AlgoTrade — Login")

    ui.add_head_html("""
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
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
            background: #f1f5f9 !important;
            min-height: unset !important;
        }
        *, *::before, *::after { box-sizing: border-box; }

        .login-root {
            min-height: 100vh;
            width: 100vw;
            background: linear-gradient(160deg, #eff6ff 0%, #f1f5f9 55%, #f0fdf4 100%);
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 24px;
            position: relative;
            overflow: hidden;
        }
        .login-root::before {
            content: '';
            position: absolute;
            width: 700px; height: 700px;
            border-radius: 50%;
            background: radial-gradient(circle, rgba(37,99,235,0.07) 0%, transparent 65%);
            top: -200px; right: -150px;
            pointer-events: none;
        }
        .login-root::after {
            content: '';
            position: absolute;
            width: 500px; height: 500px;
            border-radius: 50%;
            background: radial-gradient(circle, rgba(79,70,229,0.06) 0%, transparent 65%);
            bottom: -100px; left: -120px;
            pointer-events: none;
        }

        .login-card {
            background: #fff;
            border: 1px solid #e2e8f0;
            border-radius: 20px;
            padding: 44px 40px 36px;
            width: 100%;
            max-width: 420px;
            position: relative;
            z-index: 1;
            box-shadow: 0 8px 32px rgba(0,0,0,0.08);
        }

        .login-logo {
            display: flex;
            align-items: center;
            gap: 10px;
            justify-content: center;
            margin-bottom: 8px;
            text-decoration: none;
        }
        .login-logo-text {
            font-size: 1.5rem;
            font-weight: 800;
            color: #0f172a;
            letter-spacing: -0.02em;
        }
        .login-logo-text span { color: #2563eb; }

        .login-tagline {
            text-align: center;
            color: #64748b;
            font-size: 0.85rem;
            margin-bottom: 36px;
        }

        .login-label {
            display: block;
            font-size: 0.78rem;
            font-weight: 600;
            color: #64748b;
            letter-spacing: 0.05em;
            text-transform: uppercase;
            margin-bottom: 6px;
        }

        .login-error {
            background: #fef2f2;
            border: 1px solid #fecaca;
            border-radius: 8px;
            color: #dc2626;
            font-size: 0.82rem;
            padding: 10px 14px;
            margin-top: 16px;
            display: none;
        }
        .login-error.visible { display: block; }

        .login-footer {
            text-align: center;
            margin-top: 28px;
            color: #94a3b8;
            font-size: 0.75rem;
        }
        .login-footer a {
            color: #2563eb;
            text-decoration: none;
        }
        .login-footer a:hover { text-decoration: underline; }

        /* Quasar input overrides */
        .login-card .q-field__control {
            background: #f8fafc !important;
            border-radius: 10px !important;
        }
        .login-card .q-field__native,
        .login-card .q-field__input {
            color: #0f172a !important;
        }
        .login-card .q-field--outlined .q-field__control:before {
            border-color: #cbd5e1 !important;
        }
        .login-card .q-field--outlined:hover .q-field__control:before {
            border-color: #93c5fd !important;
        }
        .login-card .q-field--focused .q-field__control:before,
        .login-card .q-field--outlined.q-field--focused .q-field__control:after {
            border-color: #2563eb !important;
        }
        .login-card .q-field__label { color: #94a3b8 !important; }
        .login-card .q-icon { color: #94a3b8 !important; }
    </style>
    """)

    with ui.element("div").classes("login-root"):
        with ui.element("div").classes("login-card"):
            # Logo
            ui.html("""
            <a href="/" class="login-logo">
              <span style="font-size:1.8rem;">📈</span>
              <span class="login-logo-text">Algo<span>Trade</span></span>
            </a>
            <p class="login-tagline">NIFTY &amp; BANKNIFTY · Intelligent Options Trading</p>
            """)

            username = ui.input(
                label="Username",
                placeholder="Enter username",
            ).props('outlined dense').classes("w-full mb-4")

            password = ui.input(
                label="Password",
                placeholder="Enter password",
                password=True,
                password_toggle_button=True,
            ).props('outlined dense').classes("w-full mb-2")

            error_box = ui.html('<div class="login-error" id="login-error">Invalid username or password.</div>')

            def do_login():
                u = username.value.strip()
                p = password.value
                if VALID_CREDENTIALS.get(u) == p:
                    app.storage.user["authenticated"] = True
                    ui.navigate.to("/app")
                else:
                    ui.run_javascript(
                        'document.getElementById("login-error").classList.add("visible")'
                    )

            password.on("keydown.enter", do_login)

            ui.button(
                "Sign In",
                on_click=do_login,
            ).props("unelevated").classes(
                "w-full mt-4"
            ).style(
                "background: linear-gradient(135deg, #2563eb, #4f46e5) !important;"
                "color: #fff !important;"
                "font-weight: 700 !important;"
                "font-size: 0.95rem !important;"
                "border-radius: 10px !important;"
                "height: 44px !important;"
                "box-shadow: 0 4px 14px rgba(59,130,246,0.4) !important;"
            )

        ui.html("""
        <div class="login-footer" style="position:relative;z-index:1;margin-top:24px;">
          <a href="/">← Back to Home</a>
        </div>
        """)
