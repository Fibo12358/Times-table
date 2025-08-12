# times_tables_streamlit.py — mobile-first, 3 screens (Start → Practice → Results)
# Numeric keypad (custom or fallback), auto-submit, spaced repetition
# Discord webhook notifications, streamlined UI
# Persist Start-screen settings per device using browser cookies (EncryptedCookieManager)
# Version: v1.13.2

import os
import time
import json
import random
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
import streamlit as st
from streamlit.components.v1 import declare_component
from streamlit_cookies_manager import EncryptedCookieManager  # ← new, robust cookies

APP_VERSION = "v1.13.2"

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
    try:
        return st.secrets["discord"]["webhook"]
    except Exception:
        return None

# ---------------- Page config + styles ----------------
st.set_page_config(page_title="Times Tables Trainer", page_icon="✳️",
                   layout="centered", initial_sidebar_state="collapsed")

# Query params helper (used for debug toggle)
def _get_qp():
    try:
        return dict(st.query_params)
    except Exception:
        return {k: v for k, v in st.experimental_get_query_params().items()}

_qp = _get_qp()
DEBUG = str(_qp.get("debug", "0")).lower() in ("1", "true", "yes")

# Hide Streamlit chrome unless DEBUG
if not DEBUG:
    st.markdown("""
    <style>
      div[data-testid="stToolbar"], div[data-testid="stDecoration"], header, footer, #MainMenu { display: none !important; }
    </style>
    """, unsafe_allow_html=True)

# Global theme/css
st.markdown("""
<style>
  .block-container{ max-width: 440px !important; padding: 8px 12px !important; }
  html, body { background:#0b1220; color:#f8fafc; }
  :root{
    --muted:#94a3b8; --blue:#60a5fa; --blue2:#93c5fd;
    --ok-bg:#ecfdf5; --ok-bd:#16a34a; --ok-fg:#065f46;
    --bad-bg:#fef2f2; --bad-bd:#dc2626; --bad-fg:#7f1d1d;
    --slate:#0f172a; --slate-bd:#334155; --chip:#1f2937;
    --amber:#fbbf24; --amber2:#f59e0b;
  }
  .tt-prompt h1 { font-size: clamp(48px, 15vw, 88px); line-height: 1; margin: 4px 0 0; text-align:center; }
  .answer-display{ font-size:2rem; font-weight:700; text-align:center; padding:.32rem .6rem; border:2px solid var(--slate-bd); border-radius:.6rem; background:var(--slate); color:#f8fafc; }
  .answer-display.ok{ background:var(--ok-bg); border:3px dashed var(--ok-bd); color:#065f46; }
  .answer-display.bad{ background:var(--bad-bg); border:3px solid var(--bad-bd); color:#7f1d1d; }
  .stButton>button[kind="primary"]{ background:var(--blue) !important; color:#0b1220 !important; border:none !important; font-weight:700; width:100%; min-height:48px; }
  .stButton>button{ min-height:44px; width:100%; }
  @keyframes shake{10%,90%{transform:translateX(-1px);}20%,80%{transform:translateX(2px);}30%,50%,70%{transform:translateX(-4px);}40%,60%{transform:translateX(4px);} }
  .shake{ animation:shake .4s linear both; }
  .barwrap{ background:#0f172a; border:1px solid var(--slate-bd); border-radius:10px; height:12px; overflow:hidden; }
  .barlabel{ display:flex; justify-content:space-between; font-size:.86rem; color:var(--muted); margin:4px 2px 6px; }
  .barfill-q{ background:linear-gradient(90deg, var(--amber), var(--amber2)); height:100%; width:0%; transition:width .12s linear; }
  .barfill-s{ background:linear-gradient(90deg, var(--blue), var(--blue2)); height:100%; width:0%; transition:width .12s linear; }
  .dash{ display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-top:6px; }
  .card{ background:#0f172a; border:1px solid var(--slate-bd); border-radius:12px; padding:10px 12px; }
  .card .lab{ color:var(--muted); font-size:.85rem; margin-bottom:4px; }
  .card .val{ font-weight:800; font-size:1.6rem; }
  .hero{ text-align:center; margin:2px 0 6px; }
  .hero .pct{ font-size:3rem; font-weight:900; letter-spacing:.5px; }
  .chips{ display:flex; flex-wrap:wrap; gap:6px; }
  .chip{ background:#111827; border:1px dashed #475569; color:#e5e7eb; font-size:.9rem; padding:.2rem .5rem; border-radius:.6rem; }
</style>
""", unsafe_allow_html=True)

# ---------------- Cookies (EncryptedCookieManager) ----------------
COOKIE_PREFIX = "ttt/"
COOKIE_SETTINGS_KEY = "settings"

cookies = EncryptedCookieManager(
    prefix=COOKIE_PREFIX,
    # For cloud, set a proper secret in the environment or secrets.
    password=os.environ.get("COOKIES_PASSWORD", os.environ.get("COOKIE_PASSWORD", "insecure-dev-cookie-key")),
)

# Block until the component is ready and current cookies are available
if not cookies.ready():
    st.stop()

def _cookies_read_apply():
    raw = cookies.get(COOKIE_SETTINGS_KEY)
    if not raw:
        return False
    try:
        data = json.loads(raw)
        ss = st.session_state
        ss.user = str(data.get("user", ss.user))
        ss.min_table = int(data.get("min_table", ss.min_table))
        ss.max_table = int(data.get("max_table", ss.max_table))
        ss.per_q = int(data.get("per_q", ss.per_q))
        mins = int(data.get("minutes", (ss.total_seconds // 60)))
        ss.total_seconds = max(0, mins) * 60
        return True
    except Exception:
        return False

def _cookies_save_current_settings():
    ss = st.session_state
    payload = json.dumps({
        "user": ss.user,
        "min_table": ss.min_table,
        "max_table": ss.max_table,
        "per_q": ss.per_q,
        "minutes": ss.total_seconds // 60,
    })
    cookies[COOKIE_SETTINGS_KEY] = payload
    cookies.save()  # flush immediately

# ---------------- State ----------------
def _init_state():
    ss = st.session_state
    ss.setdefault("screen", "start")
    ss.setdefault("running", False)
    ss.setdefault("finished", False)

    ss.setdefault("user", "")
    ss.setdefault("min_table", 2)
    ss.setdefault("max_table", 12)
    ss.setdefault("total_seconds", 180)
    ss.setdefault("per_q", 10)

    ss.setdefault("session_start", 0.0)
    ss.setdefault("deadline", 0.0)
    ss.setdefault("q_start", 0.0)
    ss.setdefault("q_deadline", 0.0)

    ss.setdefault("awaiting_answer", False)
    ss.setdefault("a", None)
    ss.setdefault("b", None)

    ss.setdefault("total_questions", 0)
    ss.setdefault("correct_questions", 0)
    ss.setdefault("total_time_spent", 0.0)

    ss.setdefault("wrong_attempt_items", [])
    ss.setdefault("missed_items", [])
    ss.setdefault("wrong_twice", [])
    ss.setdefault("attempts_wrong", {})
    ss.setdefault("scheduled_repeats", [])

    ss.setdefault("entry", "")
    ss.setdefault("needs_rerun", False)
    ss.setdefault("shake_until", 0.0)
    ss.setdefault("ok_until", 0.0)
    ss.setdefault("pending_correct", False)
    ss.setdefault("last_kp_seq", -1)

    env_hook = os.getenv("DISCORD_WEBHOOK")
    sec_hook = _secret_webhook()
    default_hook = DISCORD_WEBHOOK_DEFAULT
    ss.setdefault("webhook_url", env_hook or sec_hook or default_hook)
    ss.setdefault("last_webhook", {})
    ss.setdefault("webhook_sources", {
        "ui": None, "env": _mask_webhook(env_hook or ""),
        "secrets": _mask_webhook(sec_hook or ""),
        "default": _mask_webhook(default_hook)
    })

_init_state()

# Prefill once per run from cookie (safe; no retries needed here)
_cookies_read_apply()

# ---------------- Keypad component (with fallback) ----------------
KP_COMPONENT_AVAILABLE = False
KP_LOAD_ERROR = ""
def _register_keypad_component():
    global KP_COMPONENT_AVAILABLE, KP_LOAD_ERROR, keypad
    try:
        comp_dir = Path(__file__).with_name("keypad_component")
        if comp_dir.exists() and (comp_dir / "index.html").exists():
            keypad = declare_component("tt_keypad", path=str(comp_dir))
            KP_COMPONENT_AVAILABLE = True
        else:
            KP_COMPONENT_AVAILABLE = False
            KP_LOAD_ERROR = f"Keypad component not found at: {comp_dir}/index.html"
            def keypad(default=None, key=None):
                return None
    except Exception as e:
        KP_COMPONENT_AVAILABLE = False
        KP_LOAD_ERROR = f"{type(e).__name__}: {e}"
        def keypad(default=None, key=None):
            return None

_register_keypad_component()

# ---------------- Core logic ----------------
MULTIPLIERS = list(range(1, 13))
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
    _send_results_discord()
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

# ---------- Bars ----------
def _q_bar(now_ts: float):
    ss = st.session_state
    q_total = max(1e-6, float(ss.per_q))
    q_left = max(0.0, (ss.q_deadline - now_ts) if ss.running else 0.0)
    q_pct = max(0.0, min(100.0, 100.0 * q_left / q_total))
    st.markdown("<div class='barlabel'><span>Per-question</span></div>", unsafe_allow_html=True)
    st.markdown(f"<div class='barwrap'><div class='barfill-q' style='width:{q_pct:.0f}%'></div></div>", unsafe_allow_html=True)

def _s_bar(now_ts: float):
    ss = st.session_state
    s_total = max(1e-6, float(ss.total_seconds))
    s_left = max(0.0, (ss.deadline - now_ts) if ss.running else 0.0)
    s_pct = max(0.0, min(100.0, 100.0 * s_left / s_total))
    st.markdown("<div class='barlabel'><span>Session</span></div>", unsafe_allow_html=True)
    st.markdown(f"<div class='barwrap'><div class='barfill-s' style='width:{s_pct:.0f}%'></div></div>", unsafe_allow_html=True)

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

    if KP_LOAD_ERROR:
        st.info(f"Keypad component: {KP_LOAD_ERROR}. Using fallback keypad.", icon="ℹ️")

    # Debug panel
    if DEBUG:
        with st.expander("Debug: cookies", expanded=False):
            st.write("ready:", cookies.ready())
            st.write("cookie exists now:", bool(cookies.get(COOKIE_SETTINGS_KEY)))
            st.write("cookie value preview:", (cookies.get(COOKIE_SETTINGS_KEY) or "")[:160])
            if st.button("Delete settings cookie"):
                try:
                    # Clear cookie and flush
                    cookies.pop(COOKIE_SETTINGS_KEY, None)
                    cookies.save()
                except Exception:
                    pass
                st.rerun()

    # Start controls in a form
    with st.form("start_form", clear_on_submit=False):
        c1, c2 = st.columns([1, 1], gap="small")
        with c1:
            st.session_state.user = st.text_input(
                "User (required)",
                st.session_state.user,
                max_chars=32,
                placeholder="Name or ID",
                help="Saved on this device."
            )
            st.session_state.min_table = int(st.number_input("Min table", 1, 12, value=st.session_state.min_table, step=1))
        with c2:
            st.session_state.max_table = int(st.number_input("Max table", 1, 12, value=st.session_state.max_table, step=1))
            st.session_state.per_q = int(st.number_input("Seconds per question", 2, 30, value=st.session_state.per_q, step=1))

        mins = st.number_input("Session minutes", 0, 180, value=st.session_state.total_seconds // 60, step=1)
        st.session_state.total_seconds = int(mins) * 60

        if st.session_state.min_table > st.session_state.max_table:
            st.session_state.min_table, st.session_state.max_table = st.session_state.max_table, st.session_state.min_table

        start_clicked = st.form_submit_button("Start", type="primary", use_container_width=True)
        if start_clicked:
            if not st.session_state.user or not st.session_state.user.strip():
                st.error("Please enter a User name to continue.")
            else:
                _cookies_save_current_settings()
                _start_session(); st.rerun()

def screen_practice():
    now_ts = _now()
    _tick(now_ts)

    _q_bar(now_ts)

    prompt_area = st.container()
    answer_area = st.container()
    keypad_area = st.container()

    with keypad_area:
        if KP_COMPONENT_AVAILABLE:
            payload = keypad(default=None)
        else:
            payload = None
            render_fallback_keypad()

    _handle_keypad_payload(payload)

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

    if st.session_state.pending_correct and now_ts >= st.session_state.ok_until:
        st.session_state.pending_correct = False
        _record_question(True, False)

    with prompt_area:
        st.markdown(f"<div class='tt-prompt'><h1>{st.session_state.a} × {st.session_state.b}</h1></div>", unsafe_allow_html=True)

    with answer_area:
        classes = ["answer-display"]
        if st.session_state.pending_correct and now_ts < st.session_state.ok_until: classes.append("ok")
        elif now_ts < st.session_state.shake_until: classes += ["bad","shake"]
        st.markdown(f"<div class='{' '.join(classes)}'>{st.session_state.entry or '&nbsp;'}</div>", unsafe_allow_html=True)
        st.caption(f"Auto-submit after {_required_digits()} digit{'s' if _required_digits()>1 else ''}")

    _s_bar(now_ts)

def screen_results():
    total = st.session_state.total_questions
    correct = st.session_state.correct_questions
    avg = (st.session_state.total_time_spent / total) if total else 0.0
    pct = int(round((100.0 * correct / total), 0)) if total else 0
    time_spent = st.session_state.total_time_spent

    st.write("### Results")

    st.markdown(f"<div class='hero'><div class='pct'>{pct}%</div><div class='lab' style='color:var(--muted)'>Correct</div></div>", unsafe_allow_html=True)

    st.markdown("<div class='dash'>", unsafe_allow_html=True)
    st.markdown(f"<div class='card'><div class='lab'>Questions</div><div class='val'>{total}</div></div>", unsafe_allow_html=True)
    st.markdown(f"<div class='card'><div class='lab'>Avg time</div><div class='val'>{avg:0.2f} s</div></div>", unsafe_allow_html=True)
    st.markdown(f"<div class='card'><div class='lab'>Time spent</div><div class='val'>{time_spent:0.0f} s</div></div>", unsafe_allow_html=True)
    st.markdown(f"<div class='card'><div class='lab'>Correct</div><div class='val'>{correct}</div></div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    wrong_any = sorted(list(set(st.session_state.wrong_attempt_items)))
    st.markdown("#### Items to revisit")
    if wrong_any:
        chips_html = "".join(
            f"<span class='chip'>{a} × {b}{' — wrong twice' if (a, b) in st.session_state.wrong_twice else ''}</span>"
            for a, b in wrong_any
        )
        st.markdown(f"<div class='chips'>{chips_html}</div>", unsafe_allow_html=True)
    else:
        st.write("None.")

    if st.button("Start Over", type="primary", use_container_width=True):
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

    st.caption(f"Times Tables Trainer {APP_VERSION} — Keypad={'custom' if KP_COMPONENT_AVAILABLE else 'fallback'}")

    if st.session_state.needs_rerun:
        st.session_state.needs_rerun = False
        st.rerun()
    elif st.session_state.running:
        time.sleep(0.1)
        st.rerun()

_render()
