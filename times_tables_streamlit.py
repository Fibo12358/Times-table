# times_tables_streamlit.py — mobile-first, 3 screens (Start → Practice → Results)
# Numeric keypad (custom or fallback), auto-submit, first-press fix, spaced repetition
# Discord webhook notifications with diagnostics (debug mode, test button, response logging)
# Version: v1.11.8

import os
import math
import time
import json
import random
import logging
from datetime import datetime, timezone
from pathlib import Path

import requests  # <-- uses certifi bundle, avoids local macOS cert issues
import streamlit as st
from streamlit.components.v1 import declare_component

APP_VERSION = "v1.11.8"

# ---------------- Logging ----------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("ttt")

# ---------------- Discord webhook defaults ----------------
DISCORD_WEBHOOK_DEFAULT = "https://discord.com/api/webhooks/1404817423475150899/coc3BZJlGyGArEEvTAk5YqK5ev_sSQnsBMczPIu0ikhWX9IZhhLe5Fh6lT6_9eq9ibR3"

def _mask_webhook(url: str) -> str:
    try:
        parts = url.strip().split("/")
        if len(parts) >= 2:
            token = parts[-1]
            if len(token) > 12:
                token = token[:6] + "…" + token[-6:]
            parts[-1] = token
        return "/".join(parts)
    except Exception:
        return "<invalid url>"

def _secret_webhook() -> str | None:
    """Safely read st.secrets['discord']['webhook'] without crashing if secrets.toml is missing."""
    try:
        return st.secrets["discord"]["webhook"]
    except Exception:
        return None

# ---------------- Page config ----------------
st.set_page_config(page_title="Times Tables Trainer", page_icon="✳️",
                   layout="centered", initial_sidebar_state="collapsed")

# ---------------- Query params ----------------
def _get_qp():
    try:
        return dict(st.query_params)  # Streamlit ≥1.30
    except Exception:
        return {k: v for k, v in st.experimental_get_query_params().items()}

_qp = _get_qp()
_qp_safe = _qp.get("safe", "1")
if isinstance(_qp_safe, list):
    _qp_safe = _qp_safe[0]
QP_SAFE = str(_qp_safe).lower() in ("1", "true")

# ---------------- State ----------------
def _init_state():
    ss = st.session_state

    # Routing: "start" | "practice" | "results"
    ss.setdefault("screen", "start")

    # Safe mode flag (ON by default; minimal CSS)
    ss.setdefault("safe_mode", True if QP_SAFE else False)

    # Run flags
    ss.setdefault("running", False)
    ss.setdefault("finished", False)

    # Start screen settings
    ss.setdefault("user", "")
    ss.setdefault("min_table", 2)
    ss.setdefault("max_table", 12)
    ss.setdefault("total_seconds", 180)     # session length (seconds); UI shows minutes only
    ss.setdefault("per_q", 10)              # per-question seconds

    # Timers
    ss.setdefault("session_start", 0.0)
    ss.setdefault("deadline", 0.0)
    ss.setdefault("q_start", 0.0)
    ss.setdefault("q_deadline", 0.0)

    # Current question
    ss.setdefault("awaiting_answer", False)
    ss.setdefault("a", None)
    ss.setdefault("b", None)

    # Counters
    ss.setdefault("total_questions", 0)
    ss.setdefault("correct_questions", 0)
    ss.setdefault("total_time_spent", 0.0)

    # Tracking for spaced repetition
    ss.setdefault("wrong_attempt_items", [])
    ss.setdefault("missed_items", [])
    ss.setdefault("wrong_twice", [])
    ss.setdefault("attempts_wrong", {})
    ss.setdefault("scheduled_repeats", [])

    # Input / FX
    ss.setdefault("entry", "")
    ss.setdefault("needs_rerun", False)
    ss.setdefault("shake_until", 0.0)
    ss.setdefault("ok_until", 0.0)
    ss.setdefault("pending_correct", False)
    ss.setdefault("last_kp_seq", -1)

    # Diagnostics / webhook config (precedence: UI > env > secrets > default)
    env_hook = os.getenv("DISCORD_WEBHOOK")
    sec_hook = _secret_webhook()
    default_hook = DISCORD_WEBHOOK_DEFAULT
    ss.setdefault("webhook_url", env_hook or sec_hook or default_hook)
    ss.setdefault("debug_mode", False)
    ss.setdefault("last_webhook", {})  # dict with last attempt details
    ss.setdefault("webhook_sources", {
        "ui": None, "env": _mask_webhook(env_hook or ""),
        "secrets": _mask_webhook(sec_hook or ""),
        "default": _mask_webhook(default_hook)
    })

_init_state()

# ---------------- Keypad component (with fallback) ----------------
KP_COMPONENT_AVAILABLE = False
KP_LOAD_ERROR = ""
def _register_keypad_component():
    global KP_COMPONENT_AVAILABLE, KP_LOAD_ERROR, keypad
    try:
        comp_dir = Path(__file__).with_name("keypad_component")
        if comp_dir.exists() and (comp_dir / "index.html").exists():
            keypad = declare_component("tt_keypad", path=str(comp_dir))  # returns "CODE|SEQ" or None
            KP_COMPONENT_AVAILABLE = True
        else:
            KP_COMPONENT_AVAILABLE = False
            KP_LOAD_ERROR = f"Keypad component not found at: {comp_dir}/index.html"
            def keypad(default=None, key=None):  # fallback signature
                return None
    except Exception as e:
        KP_COMPONENT_AVAILABLE = False
        KP_LOAD_ERROR = f"{type(e).__name__}: {e}"
        def keypad(default=None, key=None):
            return None

_register_keypad_component()

# ---------------- Styles (mobile-first) ----------------
if not st.session_state.safe_mode:
    st.markdown("""
    <style>
      div[data-testid="stToolbar"], div[data-testid="stDecoration"], header, footer, #MainMenu { display: none !important; }
      .block-container{ max-width: 440px !important; padding: 8px 12px !important; }
      html, body { background:#0b1220; color:#f8fafc; }
      :root{ --muted:#94a3b8; --blue:#60a5fa; --ok-bg:#ecfdf5; --ok-bd:#16a34a; --ok-fg:#065f46; --bad-bg:#fef2f2; --bad-bd:#dc2626; --bad-fg:#7f1d1d; }
      .tt-prompt h1 { font-size: clamp(48px, 15vw, 88px); line-height: 1; margin: 4px 0 0; text-align:center; }
      .answer-display{ font-size:2rem; font-weight:700; text-align:center; padding:.32rem .6rem; border:2px solid #334155; border-radius:.6rem; background:#0f172a; color:#f8fafc; }
      .answer-display.ok{ background:var(--ok-bg); border:3px dashed var(--ok-bd); color:var(--ok-fg); }
      .answer-display.bad{ background:var(--bad-bg); border:3px solid var(--bad-bd); color:var(--bad-fg); }
      .stButton>button[kind="primary"]{ background:var(--blue) !important; color:#0b1220 !important; border:none !important; font-weight:700; width:100%; min-height:48px; }
      .stButton>button{ min-height:44px; width:100%; }
      .tt-metrics { display:grid; grid-template-columns:repeat(2,1fr); gap:8px; }
      .tt-footer { color:var(--muted); font-size:.75rem; text-align:center; margin-top:2px; }
      @keyframes shake{10%,90%{transform:translateX(-1px);}20%,80%{transform:translateX(2px);}30%,50%,70%{transform:translateX(-4px);}40%,60%{transform:translateX(4px);} }
      .shake{ animation:shake .4s linear both; }
      .barwrap{ background:#0f172a; border:1px solid #334155; border-radius:10px; height:10px; overflow:hidden; }
      .barfill{ background:linear-gradient(90deg, #60a5fa, #93c5fd); height:100%; width:0%; transition:width .12s linear; }
      .barlabel{ display:flex; justify-content:space-between; font-size:.8rem; color:#94a3b8; margin:2px 2px 6px; }
    </style>
    """, unsafe_allow_html=True)
else:
    st.markdown("""
    <style>
      .block-container{ max_width: 460px; }
      .tt-prompt h1 { font-size: 56px; line-height:1; margin: .25rem 0 0; text-align:center; }
      .answer-display{ font-size:1.6rem; font-weight:700; text-align:center; padding:.25rem .5rem; border:1px solid #999; border-radius:.5rem; background:#111; color:#eee; }
      .stButton>button{ min-height:42px; width:100%; }
      .tt-metrics { display:grid; grid-template-columns:repeat(2,1fr); gap:6px; }
      .tt-footer { color:#888; font-size:.8rem; text-align:center; margin-top:4px; }
      .barwrap{ background:#111; border:1px solid #999; border-radius:10px; height:10px; overflow:hidden; }
      .barfill{ background:#6aa0ff; height:100%; width:0%; transition:width .12s linear; }
      .barlabel{ display:flex; justify-content:space-between; font-size:.8rem; color:#aaa; margin:2px 2px 6px; }
    </style>
    """, unsafe_allow_html=True)

# ---------------- Logic helpers ----------------
MULTIPLIERS = list(range(1, 13))  # 1..12
def _now() -> float: return time.monotonic()
def _required_digits() -> int: return len(str(abs(st.session_state.a * st.session_state.b)))

def _decrement_scheduled():
    for s in st.session_state.scheduled_repeats:
        s["remaining"] -= 1

def _pop_due_repeat():
    for i, s in enumerate(st.session_state.scheduled_repeats):
        if s["remaining"] <= 0:
            return st.session_state.scheduled_repeats.pop(i)["item"]
    return None

def _random_item():
    ss = st.session_state
    banned = {t["item"] for t in ss.scheduled_repeats} | {k for k, v in ss.attempts_wrong.items() if v >= 2}
    for _ in range(200):
        a = random.randint(ss.min_table, ss.max_table)
        b = random.choice(MULTIPLIERS)
        if (a, b) not in banned:
            return (a, b)
    cands = [(a, b) for a in range(ss.min_table, ss.max_table + 1) for b in MULTIPLIERS if (a, b) not in banned]
    return random.choice(cands) if cands else (random.randint(ss.min_table, ss.max_table), random.choice(MULTIPLIERS))

def _select_next_item():
    _decrement_scheduled()
    due = _pop_due_repeat()
    return due if due else _random_item()

def _new_question():
    ss = st.session_state
    ss.a, ss.b = _select_next_item()
    ss.q_start = _now()
    ss.q_deadline = ss.q_start + float(ss.per_q)
    ss.awaiting_answer = True
    ss.entry = ""
    ss.pending_correct = False
    ss.ok_until = 0.0
    ss.shake_until = 0.0

def _build_results_text():
    ss = st.session_state
    total = ss.total_questions or 1
    pct = round(100 * (ss.correct_questions / total))
    wrong = ", ".join(
        f"{a}×{b}" + (" (×2)" if (a, b) in ss.wrong_twice else "")
        for (a, b) in sorted(set(ss.wrong_attempt_items))
    ) or "None"
    lines = [
        "**Times Tables Results**",
        f"User: {ss.user or 'Anonymous'}",
        f"Score: {ss.correct_questions}/{ss.total_questions} ({pct}%)",
        f"Avg: {ss.total_time_spent/total:.2f}s  •  Time: {ss.total_time_spent:.0f}s",
        f"Revisit: {wrong}"
    ]
    return "\n".join(lines)

def _get_webhook_url() -> str:
    ss = st.session_state
    # precedence: UI > env > secrets > default
    ui = (ss.webhook_url or "").strip()
    env_ = (os.getenv("DISCORD_WEBHOOK") or "").strip()
    sec_ = (_secret_webhook() or "").strip()
    eff = ui or env_ or sec_ or DISCORD_WEBHOOK_DEFAULT
    ss.webhook_sources.update({
        "ui": _mask_webhook(ui),
        "env": _mask_webhook(env_),
        "secrets": _mask_webhook(sec_),
        "default": _mask_webhook(DISCORD_WEBHOOK_DEFAULT),
    })
    return eff

def _send_results_discord(text: str | None = None):
    """POST to Discord webhook with requests (uses certifi bundle)."""
    url = _get_webhook_url()
    ss = st.session_state

    content = (text or _build_results_text()).strip()
    if len(content) > 1900:
        content = content[:1900] + "…"

    payload = {"content": content}
    attempt_info = {
        "when": datetime.now(timezone.utc).isoformat(),
        "url": _mask_webhook(url),
        "bytes": len(json.dumps(payload)),
        "content_preview": content[:200] + ("…" if len(content) > 200 else ""),
        "sources": ss.webhook_sources.copy(),
    }

    try:
        r = requests.post(url, json=payload, timeout=10)
        attempt_info.update({"status": r.status_code, "ok": r.ok, "response": (r.text or "")[:500]})
        if r.ok:
            logger.info("Discord webhook success (status %s)", r.status_code)
        else:
            logger.error("Discord webhook non-2xx (status %s): %s", r.status_code, (r.text or "")[:200])
    except requests.exceptions.SSLError as e:
        attempt_info.update({"status": None, "ok": False, "error": f"SSLError: {e}"})
        logger.exception("Discord webhook SSL error")
    except requests.exceptions.RequestException as e:
        attempt_info.update({"status": None, "ok": False, "error": f"RequestException: {e}"})
        logger.exception("Discord webhook request error")
    except Exception as e:
        attempt_info.update({"status": None, "ok": False, "error": f"{type(e).__name__}: {e}"})
        logger.exception("Discord webhook unexpected error")

    ss.last_webhook = attempt_info

def _start_session():
    ss = st.session_state
    ss.running = True
    ss.finished = False
    ss.session_start = _now()
    ss.deadline = ss.session_start + float(ss.total_seconds)
    ss.total_questions = 0
    ss.correct_questions = 0
    ss.total_time_spent = 0.0
    ss.wrong_attempt_items = []
    ss.missed_items = []
    ss.wrong_twice = []
    ss.attempts_wrong = {}
    ss.scheduled_repeats = []
    _new_question()
    ss.screen = "practice"
    ss.needs_rerun = True

def _end_session():
    ss = st.session_state
    ss.running = False
    ss.finished = True
    ss.awaiting_answer = False
    _send_results_discord()  # send automatically
    ss.screen = "results"
    ss.needs_rerun = True

def _record_question(correct: bool, timed_out: bool):
    ss = st.session_state
    duration = _now() - ss.q_start
    ss.total_questions += 1
    ss.total_time_spent += duration
    item = (ss.a, ss.b)

    if correct:
        ss.correct_questions += 1
        ss.scheduled_repeats = [s for s in ss.scheduled_repeats if s["item"] != item]
    else:
        cnt = ss.attempts_wrong.get(item, 0) + 1
        ss.attempts_wrong[item] = cnt
        if item not in ss.wrong_attempt_items:
            ss.wrong_attempt_items.append(item)
        if timed_out and item not in ss.missed_items:
            ss.missed_items.append(item)
        if cnt == 1:
            if item not in (s["item"] for s in ss.scheduled_repeats):
                ss.scheduled_repeats.append({"item": item, "remaining": random.randint(2, 4)})
        else:
            if item not in ss.wrong_twice:
                ss.wrong_twice.append(item)
            ss.scheduled_repeats = [s for s in ss.scheduled_repeats if s["item"] != item]

    ss.awaiting_answer = False
    _new_question()
    ss.needs_rerun = True

def _tick(now_ts: float):
    ss = st.session_state
    if not ss.running: return
    if ss.pending_correct and now_ts < ss.ok_until: return
    if now_ts >= ss.deadline:
        _end_session(); return
    if ss.awaiting_answer and now_ts >= ss.q_deadline:
        _record_question(False, True)

def _kp_apply(code: str):
    if not st.session_state.awaiting_answer: return
    if code == "C":
        st.session_state.entry = ""
    elif code == "B":
        st.session_state.entry = st.session_state.entry[:-1]
    elif code and code.isdigit():
        st.session_state.entry += code

# First-keypress fix
def _handle_keypad_payload(payload):
    if not payload:
        return
    text = str(payload)
    code, seq = None, None
    if "|" in text:
        code, seq_s = text.split("|", 1)
        try:
            seq = int(seq_s)
        except Exception:
            seq = None
    else:
        code = text

    last = st.session_state.get("last_kp_seq", -1)
    if (seq is None) or (last < 0) or (seq > last):
        st.session_state.last_kp_seq = (last + 1) if (seq is None) else seq
        _kp_apply(code)

# ---------- Timer bars (Practice only) ----------
def _timer_bars(now_ts: float):
    ss = st.session_state
    q_total = max(1e-6, float(ss.per_q))
    s_total = max(1e-6, float(ss.total_seconds))
    q_left = max(0.0, (ss.q_deadline - now_ts) if ss.running else 0.0)
    s_left = max(0.0, (ss.deadline - now_ts) if ss.running else 0.0)
    q_pct = max(0.0, min(100.0, 100.0 * q_left / q_total))
    s_pct = max(0.0, min(100.0, 100.0 * s_left / s_total))

    c1, c2 = st.columns(2, gap="small")
    with c1:
        st.markdown("<div class='barlabel'><span>Per-question</span></div>", unsafe_allow_html=True)
        st.markdown(f"<div class='barwrap'><div class='barfill' style='width:{q_pct:.0f}%'></div></div>", unsafe_allow_html=True)
    with c2:
        st.markdown("<div class='barlabel'><span>Session</span></div>", unsafe_allow_html=True)
        st.markdown(f"<div class='barwrap'><div class='barfill' style='width:{s_pct:.0f}%'></div></div>", unsafe_allow_html=True)

# ---------- Fallback keypad ----------
def _kp_click(code: str): _kp_apply(code)
def render_fallback_keypad():
    for row in ("123","456","789"):
        cols = st.columns(3, gap="small")
        for i, ch in enumerate(row):
            with cols[i]:
                st.button(ch, use_container_width=True, on_click=_kp_click, args=(ch,))
    cols = st.columns(3, gap="small")
    with cols[0]: st.button("Clear", use_container_width=True, on_click=_kp_click, args=("C",))
    with cols[1]: st.button("0", use_container_width=True, on_click=_kp_click, args=("0",))
    with cols[2]: st.button("Back", use_container_width=True, on_click=_kp_click, args=("B",))

# ---------------- Screens ----------------
def screen_start():
    st.write("### Start")

    # Safe-mode toggle (off = fancy CSS; on = minimal CSS)
    st.session_state.safe_mode = st.toggle(
        "Safe mode (minimal CSS)",
        value=st.session_state.safe_mode,
        help="Turn off to enable the compact, mobile-first theme"
    )

    if KP_LOAD_ERROR:
        st.info(f"Keypad component: {KP_LOAD_ERROR}. Using fallback keypad.", icon="ℹ️")

    # Start controls live in a form. Use ONLY form submit buttons inside.
    with st.form("start_form", clear_on_submit=False):
        c1, c2 = st.columns([1, 1], gap="small")
        with c1:
            st.session_state.user = st.text_input("User", st.session_state.user, max_chars=32, placeholder="Name or ID")
            st.session_state.min_table = int(st.number_input("Min table", 1, 12, value=st.session_state.min_table, step=1))
        with c2:
            st.session_state.max_table = int(st.number_input("Max table", 1, 12, value=st.session_state.max_table, step=1))
            st.session_state.per_q = int(st.number_input("Seconds per question", 2, 30, value=st.session_state.per_q, step=1))

        mins = st.number_input("Session minutes", 0, 180, value=st.session_state.total_seconds // 60, step=1)
        st.session_state.total_seconds = int(mins) * 60

        if st.session_state.min_table > st.session_state.max_table:
            st.session_state.min_table, st.session_state.max_table = st.session_state.max_table, st.session_state.min_table

        with st.expander("Advanced"):
            st.session_state.webhook_url = st.text_input(
                "Discord webhook URL (effective)",
                value=st.session_state.webhook_url,
                help="Precedence: this field > DISCORD_WEBHOOK env var > secrets.toml > built-in default.",
            )
            st.caption(f"Sources — UI: {_mask_webhook(st.session_state.webhook_url or '')} | "
                       f"ENV: {st.session_state.webhook_sources.get('env','')} | "
                       f"SECRETS: {st.session_state.webhook_sources.get('secrets','')} | "
                       f"DEFAULT: {st.session_state.webhook_sources.get('default','')}")
            st.session_state.debug_mode = st.checkbox(
                "Debug mode (log webhook attempts and show diagnostics here)",
                value=st.session_state.debug_mode,
            )
            test_clicked = st.form_submit_button("Send test message to Discord", use_container_width=True)
            if test_clicked:
                _send_results_discord(text=f"**Test** — Times Tables Trainer {APP_VERSION} ping at {datetime.utcnow().isoformat()}Z")
            if st.session_state.debug_mode and st.session_state.last_webhook:
                st.markdown("**Last webhook attempt**")
                st.json(st.session_state.last_webhook)

        start_clicked = st.form_submit_button("Start", type="primary", use_container_width=True)
        if start_clicked:
            _start_session(); st.rerun()

def screen_practice():
    now_ts = _now()
    _tick(now_ts)

    # Timer bars only (no numeric countdowns; no stats)
    _timer_bars(now_ts)

    # Placeholders in UI order
    prompt_area = st.container()   # 1) multiplication prompt
    answer_area = st.container()   # 2) answer field + caption
    keypad_area = st.container()   # 3) keypad

    # Render keypad FIRST (for event capture), but INTO the third placeholder
    with keypad_area:
        if KP_COMPONENT_AVAILABLE:
            payload = keypad(default=None)  # "CODE|SEQ" or None
        else:
            payload = None
            render_fallback_keypad()

    # Apply keypad event
    _handle_keypad_payload(payload)

    # Auto-submit when the required digit count is reached
    if st.session_state.awaiting_answer:
        target = st.session_state.a * st.session_state.b
        need = _required_digits()
        if len(st.session_state.entry) == need:
            try:
                val = int(st.session_state.entry)
            except ValueError:
                st.session_state.entry = ""; st.session_state.shake_until = now_ts + 0.45
            else:
                if val == target:
                    st.session_state.awaiting_answer = False
                    st.session_state.pending_correct = True
                    st.session_state.ok_until = now_ts + 0.6
                    st.session_state.needs_rerun = True
                else:
                    st.session_state.entry = ""
                    if (st.session_state.a, st.session_state.b) not in st.session_state.wrong_attempt_items:
                        st.session_state.wrong_attempt_items.append((st.session_state.a, st.session_state.b))
                    st.session_state.shake_until = now_ts + 0.45

    # Finalise correct after the green flash
    if st.session_state.pending_correct and now_ts >= st.session_state.ok_until:
        st.session_state.pending_correct = False
        _record_question(True, False)

    # 1) Prompt
    with prompt_area:
        st.markdown(f"<div class='tt-prompt'><h1>{st.session_state.a} × {st.session_state.b}</h1></div>", unsafe_allow_html=True)

    # 2) Answer field
    with answer_area:
        classes = ["answer-display"]
        if st.session_state.pending_correct and now_ts < st.session_state.ok_until: classes.append("ok")
        elif now_ts < st.session_state.shake_until: classes += ["bad","shake"]
        st.markdown(f"<div class='{' '.join(classes)}'>{st.session_state.entry or '&nbsp;'}</div>", unsafe_allow_html=True)
        st.caption(f"Auto-submit after {_required_digits()} digit{'s' if _required_digits()>1 else ''}")

def screen_results():
    total = st.session_state.total_questions
    correct = st.session_state.correct_questions
    avg = (st.session_state.total_time_spent / total) if total else 0.0
    pct = (100.0 * correct / total) if total else 0.0

    st.write("### Results")

    # Results-only stats
    cols = st.columns(4, gap="small")
    data = [("Correct", f"{pct:0.0f}%"), ("Questions", str(total)),
            ("Avg time", f"{avg:0.2f} s"), ("Time spent", f"{st.session_state.total_time_spent:0.0f} s")]
    for c, (lab, val) in zip(cols, data):
        with c: st.metric(lab, val)

    st.markdown("##### Items to revisit")
    wrong_any = sorted(list(set(st.session_state.wrong_attempt_items)))
    if wrong_any:
        st.write("\n".join([f"{a} × {b}{' — wrong twice' if (a, b) in st.session_state.wrong_twice else ''}" for a, b in wrong_any]))
    else:
        st.write("None.")

    # Diagnostics panel also visible on Results
    if st.session_state.debug_mode and st.session_state.last_webhook:
        with st.expander("Debug — last webhook attempt"):
            st.json(st.session_state.last_webhook)

    c1, c2 = st.columns(2, gap="small")
    with c1:
        if st.button("Again", type="primary", use_container_width=True):
            _start_session(); st.rerun()
    with c2:
        if st.button("Back to Start", use_container_width=True):
            st.session_state.screen = "start"; st.rerun()

# ---------------- Router + heartbeat ----------------
def _render():
    try:
        screen = st.session_state.screen
        if screen == "start":
            screen_start()
        elif screen == "practice":
            screen_practice()
        else:
            screen_results()
    except Exception as e:
        st.error("Unhandled exception while rendering.")
        st.exception(e)

    st.caption(f"Times Tables Trainer {APP_VERSION} — Keypad={'custom' if KP_COMPONENT_AVAILABLE else 'fallback'} — SAFE_MODE={'on' if st.session_state.safe_mode else 'off'}")

    # Heartbeat (progress timers / flashes without user input)
    if st.session_state.needs_rerun:
        st.session_state.needs_rerun = False
        st.rerun()
    elif st.session_state.running:
        time.sleep(0.1)
        st.rerun()

_render()
