# times_tables_streamlit.py — 3 screens + keypad fallback + first-press + auto-submit fixes
# SAFE MODE defaults ON (minimal CSS). Toggle it off on the Settings screen when you're ready.
# Version: v1.10.9

import math
import os
import time
import random
from pathlib import Path
from datetime import datetime, timedelta
from uuid import uuid4

import streamlit as st
from streamlit.components.v1 import declare_component

APP_VERSION = "v1.10.9"

# ---------------- Local storage helpers ----------------
LS_COMPONENT_AVAILABLE = False
LS_LOAD_ERROR = ""
# When True, missing localStorage component falls back to in-memory store
LS_FALLBACK_ALLOWED = True

def _register_ls_component():
    """Register the localStorage component with a tiny retry and log errors."""
    global LS_COMPONENT_AVAILABLE, LS_LOAD_ERROR, ls_component
    comp_dir = Path(__file__).with_name("ls_component")
    for attempt in range(2):
        try:
            if comp_dir.exists() and (comp_dir / "index.html").exists():
                ls_component = declare_component("tt_ls", path=str(comp_dir))
                LS_COMPONENT_AVAILABLE = True
            else:
                LS_COMPONENT_AVAILABLE = False
                LS_LOAD_ERROR = f"LocalStorage component not found at: {comp_dir}/index.html"
                def ls_component(**kwargs):
                    return None
            break
        except Exception as e:
            LS_COMPONENT_AVAILABLE = False
            LS_LOAD_ERROR = f"{type(e).__name__}: {e}"
            def ls_component(**kwargs):
                return None
            time.sleep(0.1)

    if not LS_COMPONENT_AVAILABLE:
        msg = f"LS component unavailable; falling back to in-memory store. {LS_LOAD_ERROR}"
        try:
            st.warning(msg)
            st.write(
                f"<script>console.error('LS_LOAD_ERROR: {LS_LOAD_ERROR}')</script>",
                unsafe_allow_html=True,
            )
        except Exception:
            print(f"LS_LOAD_ERROR: {LS_LOAD_ERROR}")

_register_ls_component()

def _ls_store():
    if "_ls" not in st.session_state:
        st.session_state._ls = {}
    return st.session_state._ls


_ls_component_counter = 0


def _ls_component_key():
    global _ls_component_counter
    _ls_component_counter += 1
    return f"ls_{_ls_component_counter}"


def ls_get(key):
    if LS_COMPONENT_AVAILABLE:
        res = ls_component(action="get", ls_key=key, key=_ls_component_key(), default=None)
        if isinstance(res, dict):
            err = res.get("error") or res.get("ERROR")
            if err:
                if not LS_FALLBACK_ALLOWED:
                    raise RuntimeError(f"localStorage error: {err}")
                ls_remove(key)
                return None
        return res
    if not LS_FALLBACK_ALLOWED:
        raise RuntimeError(LS_LOAD_ERROR or "localStorage component unavailable")
    return _ls_store().get(key)


def ls_set(key, value, ttl_days=30):
    if LS_COMPONENT_AVAILABLE:
        res = ls_component(action="set", ls_key=key, value=value, ttl_days=ttl_days, key=_ls_component_key(), default=None)
        if isinstance(res, dict):
            err = res.get("error") or res.get("ERROR")
            if err and not LS_FALLBACK_ALLOWED:
                raise RuntimeError(f"localStorage error: {err}")
        return res
    if not LS_FALLBACK_ALLOWED:
        raise RuntimeError(LS_LOAD_ERROR or "localStorage component unavailable")
    _ls_store()[key] = value
    return True


def ls_remove(key):
    if LS_COMPONENT_AVAILABLE:
        res = ls_component(action="remove", ls_key=key, key=_ls_component_key(), default=None)
        if isinstance(res, dict):
            err = res.get("error") or res.get("ERROR")
            if err and not LS_FALLBACK_ALLOWED:
                raise RuntimeError(f"localStorage error: {err}")
        return res
    if not LS_FALLBACK_ALLOWED:
        raise RuntimeError(LS_LOAD_ERROR or "localStorage component unavailable")
    _ls_store().pop(key, None)
    return True


def iso_now_plus_days(days: int) -> str:
    return (datetime.utcnow() + timedelta(days=days)).isoformat()


def ensure_device_id() -> str:
    ss = st.session_state
    if ss.get("device_id"):
        return ss.device_id
    val = ls_get("tt.device_id.v1")
    if isinstance(val, dict):
        dev = val.get("id")
    elif isinstance(val, str):
        dev = val
    else:
        dev = None
    if not dev:
        dev = uuid4().hex
        ls_set("tt.device_id.v1", {"id": dev}, ttl_days=3650)
    ss.device_id = dev
    return dev


def persist_settings():
    ss = st.session_state
    obj = {
        "user": ss.user,
        "min": int(ss.min_table),
        "max": int(ss.max_table),
        "secs_per_q": float(ss.per_q),
        "session_secs": int(ss.total_seconds),
        "device_id": ensure_device_id(),
        "expires_at": iso_now_plus_days(30),
    }
    ls_set("tt.settings.v1", obj, ttl_days=30)


def load_settings_on_boot():
    ss = st.session_state
    obj = ls_get("tt.settings.v1")
    if isinstance(obj, dict):
        if isinstance(obj.get("user"), str):
            ss.user = obj["user"]
        if isinstance(obj.get("min"), int):
            ss.min_table = max(1, min(12, int(obj["min"])))
        if isinstance(obj.get("max"), int):
            ss.max_table = max(1, min(12, int(obj["max"])))
        if isinstance(obj.get("secs_per_q"), (int, float)):
            ss.per_q = float(obj["secs_per_q"])
        if isinstance(obj.get("session_secs"), int):
            ss.total_seconds = max(0, int(obj["session_secs"]))
    ss.session_mins = ss.total_seconds // 60
    ss.session_secs = ss.total_seconds % 60
    ss.did_boot_load = True


def _update_session_duration():
    ss = st.session_state
    ss.total_seconds = int(ss.session_mins) * 60 + int(ss.session_secs)
    persist_settings()


def render_debug_panel():
    info = ls_component(action="info", ls_key="tt.settings.v1", key=_ls_component_key(), default={}) if LS_COMPONENT_AVAILABLE else {}
    st.write("#### Storage debug")
    if info.get("origin"):
        st.text(f"Origin: {info.get('origin')}")
    if info.get("port"):
        st.text(f"Port: {info.get('port')}")
    st.text(
        "localStorage available: "
        + str(info.get("ls_ok"))
        + (f" ({info.get('ls_error')})" if info.get("ls_error") else "")
    )
    st.text(f"Now (UTC): {info.get('now')}")
    st.write("Stored tt.settings.v1:")
    st.json(info.get("stored"))
    cols = st.columns(2)
    with cols[0]:
        if st.button("Self-test"):
            nonce = uuid4().hex
            ls_set("tt.test.v1", {"nonce": nonce}, ttl_days=1)
            st.session_state._debug_nonce = nonce
            st.rerun()
    with cols[1]:
        if st.button("Clear settings"):
            ls_remove("tt.settings.v1")
            st.rerun()
    if "_debug_nonce" in st.session_state:
        test = ls_get("tt.test.v1")
        if test and test.get("nonce") == st.session_state._debug_nonce:
            st.success("Self-test passed")
        else:
            st.error("Self-test failed")
    st.caption("localStorage is per origin (host + port). On port change, storage appears empty.")
    st.write("Python view:")
    st.json(ls_get("tt.settings.v1"))

# ---------------- Page config ----------------
st.set_page_config(page_title="Times Tables Trainer", page_icon="✳️",
                   layout="wide", initial_sidebar_state="collapsed")

# ---------------- Query params ----------------
def _get_qp():
    try:
        return dict(st.query_params)  # Streamlit >=1.30
    except Exception:
        return {k: v for k, v in st.experimental_get_query_params().items()}

_qp = _get_qp()
_qp_safe = _qp.get("safe", "1")
if isinstance(_qp_safe, list):  # older APIs may return list
    _qp_safe = _qp_safe[0]
QP_SAFE = str(_qp_safe).lower() in ("1", "true")

# Allow disabling of in-memory localStorage fallback via env var or query param
_qp_ls_fb = _qp.get("ls_fallback", "1")
if isinstance(_qp_ls_fb, list):
    _qp_ls_fb = _qp_ls_fb[0]
LS_FALLBACK_ALLOWED = not (
    str(os.getenv("TT_DISABLE_LS_FALLBACK", "")).lower() in ("1", "true", "yes")
    or str(_qp_ls_fb).lower() in ("0", "false", "no")
)

# ---------------- State ----------------
def _init_state():
    ss = st.session_state

    # Safe mode flag (ON by default)
    ss.setdefault("safe_mode", True if QP_SAFE else False)

    # Router
    ss.setdefault("screen", "settings")     # "settings" | "practice" | "report"

    # Run flags
    ss.setdefault("running", False)
    ss.setdefault("finished", False)

    # Settings defaults
    ss.setdefault("user", "")
    ss.setdefault("min_table", 2)
    ss.setdefault("max_table", 12)
    ss.setdefault("total_seconds", 180)
    ss.setdefault("per_q", 10.0)  # per-question seconds
    ss.setdefault("session_mins", ss.total_seconds // 60)
    ss.setdefault("session_secs", ss.total_seconds % 60)
    ss.setdefault("did_boot_load", False)

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

    # Tracking (lists for safe serialisation)
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

_init_state()
if not st.session_state.did_boot_load:
    load_settings_on_boot()

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
            def keypad(default=None, key=None):
                return None
    except Exception as e:
        KP_COMPONENT_AVAILABLE = False
        KP_LOAD_ERROR = f"{type(e).__name__}: {e}"
        def keypad(default=None, key=None):
            return None

_register_keypad_component()

# ---------------- Styles ----------------
if not st.session_state.safe_mode:
    # Fancy CSS: no scroll, hidden chrome, compact layout
    st.markdown("""
    <style>
    div[data-testid="stToolbar"], div[data-testid="stDecoration"], header, footer, #MainMenu { display: none !important; }
    html, body, [data-testid="stAppViewContainer"] { height:100dvh; overflow:hidden; }
    .block-container{ max-width:460px !important; padding-top:0; padding-bottom:0; padding-left:12px; padding-right:12px; }
    .tt-screen{height:100dvh; box-sizing:border-box; display:flex; flex-direction:column;}
    @supports not (height:100dvh){.tt-screen{height:100vh;}}
    .tt-settings{padding:12px 14px 10px; gap:8px;}
    .tt-header{height:40px; min-height:40px; display:flex; align-items:center; gap:8px;}
    .tt-header *{margin:0;}
    .tt-prompt{flex:1 1 auto; display:flex; align-items:center; justify-content:center;}
    .tt-prompt h1{font-size:clamp(36px,10vw,64px); line-height:1; margin:0;}
    .tt-keypad{flex:0 0 auto; height:clamp(248px,40dvh,320px);}
    .tt-report{padding:10px 14px; display:flex; flex-direction:column; gap:10px; overflow:hidden;}
    .tt-metrics{display:grid; grid-template-columns:repeat(4,1fr); gap:8px;}
    .tt-list{flex:1 1 auto; overflow:auto; border-top:1px solid #334155; padding-top:8px;}
    .tt-spark{height:120px;}
    .tt-streak{text-align:center; font-weight:600;}
    :root{--bg:#0b1220;--text:#f8fafc;--muted:#94a3b8;--blue:#60a5fa;--ok-bg:#ecfdf5;--ok-bd:#16a34a;--ok-fg:#065f46;--bad-bg:#fef2f2;--bad-bd:#dc2626;--bad-fg:#7f1d1d;}
    html, body{background:var(--bg); color:var(--text);}
    .tt-timer{font-variant-numeric:tabular-nums; font-weight:700; font-size:16px; line-height:1;}
    .answer-display{font-size:2rem; font-weight:700; text-align:center; padding:.28rem .5rem; border:2px solid #334155; border-radius:.6rem; background:#0f172a; color:var(--text);}
    .answer-display.ok{background:var(--ok-bg); border:3px dashed var(--ok-bd); color:var(--ok-fg);}
    .answer-display.bad{background:var(--bad-bg); border:3px solid var(--bad-bd); color:var(--bad-fg);}
    .stButton>button[kind="primary"]{background:var(--blue) !important; color:#0b1220 !important; border:none !important; font-weight:700; width:100%;}
    .stButton>button{min-height:44px;}
    @keyframes shake{10%,90%{transform:translateX(-1px);}20%,80%{transform:translateX(2px);}30%,50%,70%{transform:translateX(-4px);}40%,60%{transform:translateX(4px);}}
    .shake{animation:shake .4s linear both;}
    .version-badge{position:fixed; bottom:6px; left:50%; transform:translateX(-50%); font-size:.75rem; color:#94a3b8; opacity:.85; pointer-events:none;}
    </style>
    """, unsafe_allow_html=True)
else:
    # Minimal CSS so errors and content are always visible
    st.markdown("""
    <style>
    html, body, [data-testid="stAppViewContainer"] { height:100dvh; }
    @supports not (height:100dvh){ html, body, [data-testid="stAppViewContainer"]{ height:100vh; } }
    .block-container{ max-width:640px; padding-top:0; padding-bottom:0; }
    .tt-screen{height:100dvh; display:flex; flex-direction:column;}
    @supports not (height:100dvh){.tt-screen{height:100vh;}}
    .tt-header{height:40px; min-height:40px; display:flex; align-items:center; gap:8px;}
    .tt-header *{margin:0;}
    .tt-timer{font-variant-numeric:tabular-nums; font-weight:700; font-size:16px; line-height:1;}
    .tt-prompt{flex:1 1 auto; display:flex; align-items:center; justify-content:center;}
    .tt-keypad{flex:0 0 auto; height:clamp(248px,40dvh,320px);}
    .answer-display{font-size:1.6rem; font-weight:700; text-align:center; padding:.25rem .5rem; border:1px solid #999; border-radius:.5rem; background:#111; color:#eee;}
    .tt-prompt h1{font-size:clamp(36px,10vw,64px); line-height:1; margin:0;}
    .stButton>button{min-height:42px;}
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

def _persist_settings():
    key = "tt.settings.v1"
    settings = ls_get(key) or {
        "user": st.session_state.user,
        "min": st.session_state.min_table,
        "max": st.session_state.max_table,
        "session_secs": st.session_state.total_seconds,
        "device_id": st.session_state.get("device_id", ""),
    }
    settings["secs_per_q"] = round(float(st.session_state.per_q), 1)
    settings["expires_at"] = (datetime.utcnow() + timedelta(days=30)).isoformat()
    ls_set(key, settings, ttl_days=30)

def _end_session():
    ss = st.session_state
    ss.running = False
    ss.finished = True
    ss.awaiting_answer = False
    ss.screen = "report"
    _persist_settings()
    ss.needs_rerun = True


def _update_baseline(correct: bool, timed_out: bool, duration: float):
    b = float(st.session_state.per_q)
    if (not correct) or timed_out:
        b = min(30.0, round(b * 1.10, 1))
    else:
        if duration <= 0.5 * b:
            b = max(2.0, round(b * 0.90, 1))
    st.session_state.per_q = float(b)

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

    _update_baseline(correct, timed_out, duration)
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
            seq = None   # treat as unsequenced
    else:
        code = text

    last = st.session_state.get("last_kp_seq", -1)
    if (seq is None) or (last < 0) or (seq > last):
        st.session_state.last_kp_seq = (last + 1) if (seq is None) else seq
        _kp_apply(code)

def _timers_compact_row(now_ts: float):
    q_left = st.session_state.q_deadline - now_ts if st.session_state.running else 0.0
    s_left = st.session_state.deadline - now_ts if st.session_state.running else 0.0
    st.markdown(
        f"<div class='tt-header'><div class='tt-timer'>{math.ceil(max(0, q_left))} s</div><div class='tt-timer'>{math.ceil(max(0, s_left))} s</div></div>",
        unsafe_allow_html=True,
    )

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
def screen_settings():
    st.write("### Times Tables — Settings")

    # Safe-mode toggle (for you): off = fancy CSS; on = minimal CSS
    st.session_state.safe_mode = st.toggle(
        "Safe mode (minimal CSS)",
        value=st.session_state.safe_mode,
        help="Turn off to enable the no-scroll/hidden-chrome layout"
    )

    if KP_LOAD_ERROR:
        st.info(f"Keypad component: {KP_LOAD_ERROR}. Using fallback keypad.", icon="ℹ️")

    c1, c2 = st.columns([1, 1], gap="small")
    with c1:
        st.text_input("User", max_chars=32, placeholder="Name or ID", key="user", on_change=persist_settings)
        st.number_input("Min table", 1, 12, step=1, key="min_table", on_change=persist_settings)
    with c2:
        st.number_input("Max table", 1, 12, step=1, key="max_table", on_change=persist_settings)
        st.number_input(
            "Seconds per question",
            2.0,
            30.0,
            step=0.5,
            key="per_q",
            on_change=persist_settings,
        )

    c3, c4 = st.columns([1, 1], gap="small")
    with c3:
        st.number_input("Session minutes", 0, 180, step=1, key="session_mins", on_change=_update_session_duration)
        st.number_input("Session seconds", 0, 59, step=1, key="session_secs", on_change=_update_session_duration)
    with c4:
        st.write("")
        if st.button("Start", type="primary", use_container_width=True):
            persist_settings(); _start_session(); st.rerun()

    if st.session_state.min_table > st.session_state.max_table:
        st.session_state.min_table, st.session_state.max_table = st.session_state.max_table, st.session_state.min_table

    st.session_state.show_debug = st.toggle("Debug storage", value=st.session_state.get("show_debug", False))
    if st.session_state.show_debug:
        render_debug_panel()

def screen_practice():
    now_ts = _now()
    _tick(now_ts)

    _timers_compact_row(now_ts)

    # Keep visual order: prompt above keypad; but render keypad first to read payload this run.
    top_area = st.container()

    # Reuse a stable container for the keypad and clear it each run so old
    # fallback keypads do not linger if the custom component loads later.
    if "_keypad_area" not in st.session_state:
        st.session_state._keypad_area = st.container()
    keypad_area = st.session_state._keypad_area
    keypad_area.empty()

    # --- Keypad (render first) ---
    with keypad_area:
        payload = None
        if KP_COMPONENT_AVAILABLE:
            payload = keypad(default=None)  # "CODE|SEQ" or None
            st.caption("Keypad: custom")
        else:
            render_fallback_keypad()
            st.caption("Keypad: fallback")

    # Process keypad event (first-press fix)
    _handle_keypad_payload(payload)

    # Auto-submit when required digits reached
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
                    st.session_state.needs_rerun = True  # trigger the green-flash cycle immediately
                else:
                    st.session_state.entry = ""
                    if (st.session_state.a, st.session_state.b) not in st.session_state.wrong_attempt_items:
                        st.session_state.wrong_attempt_items.append((st.session_state.a, st.session_state.b))
                    st.session_state.shake_until = now_ts + 0.45

    # Finalise correct after the green flash (no extra keypress needed)
    if st.session_state.pending_correct and now_ts >= st.session_state.ok_until:
        st.session_state.pending_correct = False
        _record_question(True, False)

    # --- Prompt + entry (draw after processing so it reflects the latest state) ---
    with top_area:
        st.markdown(f"<div class='tt-prompt'><h1>{st.session_state.a} × {st.session_state.b}</h1></div>", unsafe_allow_html=True)
        classes = ["answer-display"]
        if st.session_state.pending_correct and now_ts < st.session_state.ok_until: classes.append("ok")
        elif now_ts < st.session_state.shake_until: classes += ["bad","shake"]
        st.markdown(f"<div class='{' '.join(classes)}'>{st.session_state.entry or '&nbsp;'}</div>", unsafe_allow_html=True)

def screen_report():
    total = st.session_state.total_questions
    correct = st.session_state.correct_questions
    avg = (st.session_state.total_time_spent / total) if total else 0.0
    pct = (100.0 * correct / total) if total else 0.0

    st.write("### Session report")
    cols = st.columns(4, gap="small")
    data = [("Correct", f"{pct:0.0f}%"), ("Questions", str(total)),
            ("Avg time", f"{avg:0.2f} s"), ("Time spent", f"{st.session_state.total_time_spent:0.0f} s")]
    for c, (lab, val) in zip(cols, data):
        with c: st.metric(lab, val)

    st.markdown("##### Items to revisit")
    wrong_any = sorted(list(set(st.session_state.wrong_attempt_items)))
    if wrong_any:
        for a, b in wrong_any:
            extra = " — wrong twice" if (a, b) in st.session_state.wrong_twice else ""
            st.write(f"{a} × {b}{extra}")
    else:
        st.write("None.")

    c1, c2 = st.columns(2, gap="small")
    with c1:
        if st.button("Again", type="primary", use_container_width=True):
            _start_session(); st.rerun()
    with c2:
        if st.button("Settings", use_container_width=True):
            st.session_state.screen = "settings"; st.rerun()

# ---------------- Router + footer ----------------
def _render():
    try:
        if st.session_state.screen == "settings":
            screen_settings()
        elif st.session_state.screen == "practice":
            screen_practice()
        else:
            screen_report()
    except Exception as e:
        st.error("Unhandled exception while rendering.")
        st.exception(e)

    st.caption(f"Times Tables Trainer {APP_VERSION} — Keypad={'custom' if KP_COMPONENT_AVAILABLE else 'fallback'} — SAFE_MODE={'on' if st.session_state.safe_mode else 'off'}")

    # Heartbeat (always on so green flash and timers progress without extra keypress)
    if st.session_state.needs_rerun:
        st.session_state.needs_rerun = False
        st.rerun()
    elif st.session_state.running:
        time.sleep(0.1)
        st.rerun()

_render()
