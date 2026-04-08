from nicegui import ui


def render_homepage():
    """Standalone homepage — not embedded in the main app shell."""

    ui.page_title("AlgoTrade — Intelligent Options Trading")

    # Override NiceGUI/Quasar container styles that break full-width layout
    ui.add_head_html("""
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        /* ── Hard-reset NiceGUI / Quasar layout wrappers ── */
        html, body {
            margin: 0 !important;
            padding: 0 !important;
            width: 100% !important;
            max-width: 100% !important;
            overflow-x: hidden;
        }
        body {
            background: #f8fafc !important;
            font-family: 'Inter', system-ui, -apple-system, sans-serif;
        }

        /* Quasar layout tree: #q-app > .q-layout > .q-page-container > .q-page */
        #q-app,
        .q-layout,
        .q-layout__shadow,
        .q-page-container,
        .q-page {
            padding: 0 !important;
            margin: 0 !important;
            max-width: 100% !important;
            width: 100% !important;
            background: #f8fafc !important;
            min-height: unset !important;
        }

        /* NiceGUI wraps every ui.html() in an extra <div> — strip it too */
        .q-page > div,
        .q-page > div > div {
            padding: 0 !important;
            margin: 0 !important;
            max-width: 100% !important;
            width: 100% !important;
        }

        *, *::before, *::after { box-sizing: border-box; }

        /* ── Page wrapper ─────────────────────────────── */
        .hp-root {
            background: #f8fafc;
            min-height: 100vh;
            width: 100vw;
            max-width: 100vw;
            margin-left: calc(-50vw + 50%);
            color: #1e293b;
            overflow-x: hidden;
        }

        /* ── Navbar ───────────────────────────────────── */
        .hp-nav {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0 48px;
            height: 64px;
            border-bottom: 1px solid #e2e8f0;
            background: rgba(255,255,255,0.95);
            backdrop-filter: blur(12px);
            position: sticky;
            top: 0;
            z-index: 100;
            width: 100%;
            box-shadow: 0 1px 3px rgba(0,0,0,0.06);
        }
        .hp-logo {
            display: flex;
            align-items: center;
            gap: 10px;
            text-decoration: none;
        }
        .hp-logo-text {
            font-size: 1.25rem;
            font-weight: 800;
            color: #0f172a;
            letter-spacing: -0.02em;
        }
        .hp-logo-text span { color: #2563eb; }

        .hp-nav-btn {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            background: linear-gradient(135deg, #2563eb, #4f46e5);
            color: #fff;
            font-weight: 700;
            font-size: 0.875rem;
            padding: 10px 22px;
            border-radius: 10px;
            text-decoration: none;
            box-shadow: 0 2px 8px rgba(37,99,235,0.3);
            transition: transform 0.15s, box-shadow 0.15s;
            white-space: nowrap;
        }
        .hp-nav-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 18px rgba(37,99,235,0.4);
            color: #fff;
        }

        /* ── Hero ─────────────────────────────────────── */
        .hp-hero {
            display: flex;
            flex-direction: column;
            align-items: center;
            text-align: center;
            padding: 88px 24px 72px;
            position: relative;
            overflow: hidden;
            background: linear-gradient(160deg, #eff6ff 0%, #f8fafc 55%, #f0fdf4 100%);
        }
        .hp-hero::before {
            content: '';
            position: absolute;
            width: 700px; height: 700px;
            border-radius: 50%;
            background: radial-gradient(circle, rgba(37,99,235,0.07) 0%, transparent 65%);
            top: -200px; right: -150px;
            pointer-events: none;
        }
        .hp-hero::after {
            content: '';
            position: absolute;
            width: 500px; height: 500px;
            border-radius: 50%;
            background: radial-gradient(circle, rgba(79,70,229,0.06) 0%, transparent 65%);
            bottom: -100px; left: -120px;
            pointer-events: none;
        }

        .hp-badge {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background: #dbeafe;
            border: 1px solid #bfdbfe;
            border-radius: 99px;
            padding: 6px 18px;
            font-size: 0.775rem;
            font-weight: 600;
            color: #1d4ed8;
            margin-bottom: 28px;
            letter-spacing: 0.05em;
            position: relative;
            z-index: 1;
        }

        .hp-title {
            font-size: clamp(2rem, 5.5vw, 4rem);
            font-weight: 900;
            color: #0f172a;
            line-height: 1.12;
            letter-spacing: -0.03em;
            max-width: 800px;
            margin: 0 auto 22px;
            position: relative;
            z-index: 1;
        }
        .hp-title .accent { color: #2563eb; }

        .hp-subtitle {
            font-size: 1.05rem;
            color: #64748b;
            max-width: 560px;
            line-height: 1.75;
            margin: 0 auto 44px;
            position: relative;
            z-index: 1;
        }

        .hp-cta-row {
            display: flex;
            align-items: center;
            gap: 14px;
            flex-wrap: wrap;
            justify-content: center;
            position: relative;
            z-index: 1;
        }

        .hp-btn-primary {
            display: inline-flex;
            align-items: center;
            gap: 10px;
            background: linear-gradient(135deg, #2563eb, #4f46e5);
            color: #fff;
            font-weight: 700;
            font-size: 1rem;
            padding: 14px 34px;
            border-radius: 12px;
            text-decoration: none;
            box-shadow: 0 4px 16px rgba(37,99,235,0.35);
            transition: transform 0.15s, box-shadow 0.15s;
        }
        .hp-btn-primary:hover {
            transform: translateY(-3px);
            box-shadow: 0 10px 28px rgba(37,99,235,0.45);
            color: #fff;
        }

        .hp-btn-ghost {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            color: #475569;
            font-size: 0.95rem;
            text-decoration: none;
            padding: 14px 22px;
            border-radius: 12px;
            border: 1px solid #cbd5e1;
            background: #fff;
            transition: color 0.15s, border-color 0.15s, background 0.15s;
        }
        .hp-btn-ghost:hover {
            color: #1e293b;
            border-color: #94a3b8;
            background: #f1f5f9;
        }

        /* ── Stats bar ────────────────────────────────── */
        .hp-stats {
            display: flex;
            margin: 64px auto 0;
            max-width: 680px;
            width: calc(100% - 48px);
            border: 1px solid #e2e8f0;
            border-radius: 16px;
            overflow: hidden;
            background: #fff;
            box-shadow: 0 2px 12px rgba(0,0,0,0.06);
            position: relative;
            z-index: 1;
        }
        .hp-stat {
            flex: 1;
            padding: 22px 16px;
            text-align: center;
            border-right: 1px solid #e2e8f0;
        }
        .hp-stat:last-child { border-right: none; }
        .hp-stat-val {
            font-size: 1.7rem;
            font-weight: 800;
            color: #0f172a;
            line-height: 1;
        }
        .hp-stat-lbl {
            font-size: 0.7rem;
            color: #94a3b8;
            margin-top: 5px;
            letter-spacing: 0.06em;
            text-transform: uppercase;
        }

        /* ── Features ─────────────────────────────────── */
        .hp-features-wrap {
            background: #fff;
            border-top: 1px solid #e2e8f0;
            border-bottom: 1px solid #e2e8f0;
        }
        .hp-features {
            max-width: 1100px;
            margin: 0 auto;
            padding: 80px 24px;
        }
        .hp-section-title {
            text-align: center;
            font-size: clamp(1.4rem, 3vw, 1.9rem);
            font-weight: 800;
            color: #0f172a;
            margin-bottom: 10px;
            letter-spacing: -0.02em;
        }
        .hp-section-sub {
            text-align: center;
            color: #64748b;
            font-size: 0.92rem;
            margin-bottom: 52px;
        }

        .hp-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 20px;
        }

        .hp-card {
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 16px;
            padding: 28px 24px;
            transition: border-color 0.2s, transform 0.2s, background 0.2s, box-shadow 0.2s;
        }
        .hp-card:hover {
            border-color: #93c5fd;
            background: #eff6ff;
            transform: translateY(-4px);
            box-shadow: 0 8px 24px rgba(37,99,235,0.1);
        }
        .hp-card-icon {
            font-size: 1.6rem;
            width: 50px; height: 50px;
            background: #dbeafe;
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            margin-bottom: 16px;
        }
        .hp-card-title {
            font-size: 0.95rem;
            font-weight: 700;
            color: #0f172a;
            margin-bottom: 8px;
        }
        .hp-card-desc {
            font-size: 0.85rem;
            color: #64748b;
            line-height: 1.65;
        }

        /* ── Bottom CTA ───────────────────────────────── */
        .hp-cta-bottom {
            text-align: center;
            padding: 72px 24px 80px;
            background: linear-gradient(160deg, #eff6ff 0%, #f8fafc 100%);
        }
        .hp-cta-bottom h2 {
            font-size: clamp(1.4rem, 3vw, 2.1rem);
            font-weight: 800;
            color: #0f172a;
            margin-bottom: 14px;
        }
        .hp-cta-bottom p {
            color: #64748b;
            font-size: 1rem;
            margin-bottom: 36px;
        }

        /* ── Footer ───────────────────────────────────── */
        .hp-footer {
            text-align: center;
            padding: 20px 24px;
            border-top: 1px solid #e2e8f0;
            color: #94a3b8;
            font-size: 0.78rem;
            background: #fff;
        }

        /* ── Responsive ───────────────────────────────── */
        @media (max-width: 1024px) {
            .hp-nav { padding: 0 28px; }
        }
        @media (max-width: 768px) {
            .hp-grid { grid-template-columns: repeat(2, 1fr); }
            .hp-hero { padding: 64px 20px 52px; }
            .hp-stats { flex-wrap: wrap; }
            .hp-stat { min-width: 50%; border-bottom: 1px solid #e2e8f0; }
            .hp-stat:nth-child(odd) { border-right: 1px solid #e2e8f0; }
            .hp-stat:nth-child(even) { border-right: none; }
            .hp-stat:last-child { border-bottom: none; }
            .hp-stat:nth-last-child(2) { border-bottom: none; }
        }
        @media (max-width: 540px) {
            .hp-nav { padding: 0 16px; height: 56px; }
            .hp-logo-text { font-size: 1.1rem; }
            .hp-nav-btn { padding: 8px 16px; font-size: 0.82rem; }
            .hp-grid { grid-template-columns: 1fr; }
            .hp-stat { min-width: 50%; }
            .hp-features { padding: 52px 16px; }
            .hp-cta-bottom { padding: 52px 16px 60px; }
            .hp-btn-primary { padding: 13px 24px; font-size: 0.95rem; }
        }
    </style>
    """)

    # Single html block — avoids NiceGUI injecting gap-creating wrapper divs between sections
    ui.html("""
    <div class="hp-root">

      <!-- Navbar -->
      <nav class="hp-nav">
        <a href="/" class="hp-logo">
          <span style="font-size:1.5rem;">📈</span>
          <span class="hp-logo-text">Algo<span>Trade</span></span>
        </a>
        <a href="/login" class="hp-nav-btn">⚡ Launch App</a>
      </nav>

      <!-- Hero -->
      <section class="hp-hero">
        <div class="hp-badge">⚡ NIFTY &amp; BANKNIFTY &nbsp;·&nbsp; Live Options Trading</div>
        <h1 class="hp-title">
          Algorithmic Trading<br>
          for <span class="accent">Indian Options</span> Markets
        </h1>
        <p class="hp-subtitle">
          Real-time ABCD harmonic patterns, RSI+SMA crossover signals,
          live option chains with Greeks — all in one intelligent dashboard.
        </p>
        <div class="hp-cta-row">
          <a href="/login" class="hp-btn-primary">🚀 Open Dashboard</a>
          <a href="#features" class="hp-btn-ghost">Learn more &nbsp;↓</a>
        </div>
        <div class="hp-stats">
          <div class="hp-stat">
            <div class="hp-stat-val">15s</div>
            <div class="hp-stat-lbl">Candle Interval</div>
          </div>
          <div class="hp-stat">
            <div class="hp-stat-val">3</div>
            <div class="hp-stat-lbl">Algo Strategies</div>
          </div>
          <div class="hp-stat">
            <div class="hp-stat-val">120s</div>
            <div class="hp-stat-lbl">Auto Refresh</div>
          </div>
          <div class="hp-stat">
            <div class="hp-stat-val">Live</div>
            <div class="hp-stat-lbl">P&amp;L Tracking</div>
          </div>
        </div>
      </section>

      <!-- Features -->
      <div id="features" class="hp-features-wrap">
        <div class="hp-features">
          <h2 class="hp-section-title">Everything you need to trade smarter</h2>
          <p class="hp-section-sub">Powered by Dhan API &nbsp;·&nbsp; NSE market hours &nbsp;·&nbsp; Telegram alerts included</p>
          <div class="hp-grid">
            <div class="hp-card">
              <div class="hp-card-icon">📊</div>
              <div class="hp-card-title">Live Option Chain</div>
              <div class="hp-card-desc">ATM strikes with real-time LTP, IV, Delta, Theta, Gamma and OI trend (UP / DOWN / FLAT).</div>
            </div>
            <div class="hp-card">
              <div class="hp-card-icon">🔺</div>
              <div class="hp-card-title">ABCD Harmonic Patterns</div>
              <div class="hp-card-desc">Auto-detects 4-swing harmonic sequences with 61.8–78.6% BC retracement and 100–161.8% CD extension.</div>
            </div>
            <div class="hp-card">
              <div class="hp-card-icon">📉</div>
              <div class="hp-card-title">RSI + SMA Crossover</div>
              <div class="hp-card-desc">Fast SMA(9) / Slow SMA(21) crossovers filtered by RSI(14) for high-confidence BUY/SELL signals.</div>
            </div>
            <div class="hp-card">
              <div class="hp-card-icon">🕯️</div>
              <div class="hp-card-title">Candlestick Charts</div>
              <div class="hp-card-desc">Interactive Plotly charts for NIFTY and BANKNIFTY across multiple timeframes with pattern overlays.</div>
            </div>
            <div class="hp-card">
              <div class="hp-card-icon">💰</div>
              <div class="hp-card-title">P&amp;L Dashboard</div>
              <div class="hp-card-desc">Realized &amp; unrealized P&amp;L with win-rate stats. Daily summaries sent to Telegram at 9 AM and 3:30 PM IST.</div>
            </div>
            <div class="hp-card">
              <div class="hp-card-icon">🌐</div>
              <div class="hp-card-title">Market Overview</div>
              <div class="hp-card-desc">Global indices, currency rates, and live market news — all in one place to keep context around your trades.</div>
            </div>
          </div>
        </div>
      </div>

      <!-- Bottom CTA -->
      <div class="hp-cta-bottom">
        <h2>Ready to trade algorithmically?</h2>
        <p>The market opens at 9:15 AM IST. Be ready with live signals.</p>
        <a href="/login" class="hp-btn-primary" style="font-size:1.05rem; padding:16px 40px;">
          🚀 &nbsp;Open Trading Dashboard
        </a>
      </div>

      <!-- Footer -->
      <div class="hp-footer">
        &copy; 2025 AlgoTrade &nbsp;·&nbsp; NIFTY &amp; BANKNIFTY Options &nbsp;·&nbsp; Powered by Dhan API
      </div>

    </div>
    """)
