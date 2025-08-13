# times_tables_streamlit.py — mobile-first, 3 screens (Start → Practice → Results) + Assign helper
# Features: Numeric keypad (custom or fallback), auto-submit, spaced repetition,
# Discord webhook, cookies (settings, history, streak, revisit), adaptive timing,
# URL-parameter bootstrap for initial settings, Assign page with sharable link + QR.
# Version: v1.22.0

import os
import time
import json
import random
import logging
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
import warnings
from urllib.parse import urlencode

import requests
import streamlit as st
import pandas as pd
from streamlit.components.v1 import declare_component, html as st_html
from streamlit_cookies_manager import EncryptedCookieManager  # robust cookies

APP_VERSION = "v1.22.0"

# Note on st.cache deprecation: this script does NOT use st.cache.
warnings.filterwarnings("ignore", message=r"`st\.cache` is deprecated")

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

# ---------------- Page config + light CSS ----------------
st.set_page_config(page_title="Times Tables Trainer", page_icon="✳️",
                   layout="centered", initial_sidebar_state="collapsed")

def _get_qp():
    try:
        return dict(st.query_params)
    except Exception:
        return {k: v for k, v in st.experimental_get_query_params().items()}

_qp = _get_qp()
def _qp_scalar(name: str):
    v = _qp.get(name)
    if isinstance(v, (list, tuple)): return v[0]
    return v

DEBUG = str(_qp_scalar("debug") or "0").lower() in ("1", "true", "yes")

if not DEBUG:
    st.markdown("""
    <style>
      div[data-testid="stToolbar"], div[data-testid="stDecoration"], header, footer, #MainMenu { display: none !important; }
    </style>
    """, unsafe_allow_html=True)

st.markdown("""
<style>
  .block-container{ max-width: 480px !important; padding: 8px 12px !important; }
  :root{
    --muted:#64748b; --blue:#2563eb; --blue2:#60a5fa;
    --ok-bg:#ecfdf5; --ok-bd:#16a34a; --ok-fg:#065f46;
    --bad-bg:#fef2f2; --bad-bd:#dc2626; --bad-fg:#7f1d1d;
    --slate-bd:#cbd5e1;
    --amber:#f59e0b; --amber2:#fbbf24;
  }
  .tt-prompt h1 { font-size: clamp(48px, 15vw, 88px); line-height: 1; margin: 4px 0 6px; text-align:center; }
  .answer-display{ font-size:2rem; font-weight:700; text-align:center; padding:.36rem .6rem; border:2px solid var(--slate-bd); border-radius:.6rem; background:#ffffff; }
  .answer-display.ok{ background:var(--ok-bg); border:3px dashed var(--ok-bd); color:var(--ok-fg); }
  .answer-display.bad{ background:var(--bad-bg); border:3px solid var(--bad-bd); color:var(--bad-fg); }
  .stButton>button[kind="primary"]{ background:var(--blue) !important; color:#ffffff !important; border:none !important; font-weight:700; width:100%; min-height:48px; }
  .stButton>button{ min-height:44px; width:100%; }
  @keyframes shake{10%,90%{transform:translateX(-1px);}20%,80%{transform:translateX(2px);}30%,50%,70%{transform:translateX(-4px);}40%,60%{transform:translateX(4px);} }
  .shake{ animation:shake .4s linear both; }
  .barwrap{ background:#e5e7eb; border:1px solid #cbd5e1; border-radius:10px; height:12px; overflow:hidden; }
  .barlabel{ display:flex; justify-content:space-between; font-size:.86rem; color:var(--muted); margin:6px 2px 6px; }
  .barfill-q{ background:linear-gradient(90deg, var(--amber), var(--amber2)); height:100%; width:0%; transition:width .12s linear; }
  .barfill-s{ background:linear-gradient(90deg, var(--blue), var(--blue2)); height:100%; width:0%; transition:width .12s linear; }
</style>
""", unsafe_allow_html=True)

# ---------------- Cookies ----------------
COOKIE_PREFIX = "ttt/"
COOKIE_SETTINGS_KEY = "settings"
COOKIE_HISTORY_KEY = "history"
COOKIE_STREAK_KEY = "streak"
COOKIE_REVISIT_KEY = "revisit"   # {"v":1,"min":int,"max":int,"items":[[a,b],...]}

cookies = EncryptedCookieManager(
    prefix=COOKIE_PREFIX,
    password=os.environ.get("COOKIES_PASSWORD", os.environ.get("COOKIE_PASSWORD", "insecure-dev-cookie-key")),
)
if not cookies.ready():
    st.stop()

def _cookies_set(key: str, value: str | None):
    if value is None:
        try: cookies.pop(key, None)
        except Exception: pass
    else:
        cookies[key] = value

def _cookies_flush():
    try: cookies.save()
    except Exception as e: logger.warning("Cookie flush failed: %s", e)

# ---------- History ----------
def _history_load() -> dict:
    raw = cookies.get(COOKIE_HISTORY_KEY)
    if not raw: return {"v": 1, "items": []}
    try:
        data = json.loads(raw); items = data.get("items") or []
        clean = []
        for it in items:
            try:
                clean.append({"t": str(it.get("t")), "pct": int(it.get("pct", 0)),
                              "avg": float(it.get("avg", 0.0)), "q": int(it.get("q", 0))})
            except Exception: continue
        return {"v": 1, "items": clean}
    except Exception:
        return {"v": 1, "items": []}

def _history_save(data: dict):
    _cookies_set(COOKIE_HISTORY_KEY, json.dumps(data, separators=(",", ":")))

def _history_append_session(pct: int, avg: float, q: int):
    data = _history_load()
    data["items"].append({"t": datetime.now(timezone.utc).isoformat(),
                          "pct": int(pct), "avg": float(avg), "q": int(q)})
    def _key(it):
        try: return datetime.fromisoformat(it["t"].replace("Z",""))
        except Exception: return datetime.min.replace(tzinfo=timezone.utc)
    data["items"] = sorted(data["items"], key=_key)[-10:]
    _history_save(data)

def _history_for_last_10_days() -> pd.DataFrame:
    data = _history_load(); items = data["items"]
    if not items: return pd.DataFrame(columns=["when","pct","avg"])
    now = datetime.now(timezone.utc); cutoff = now - timedelta(days=10)
    rows=[]
    for it in items:
        try:
            ts = datetime.fromisoformat(it["t"].replace("Z",""))
            if ts.tzinfo is None: ts = ts.replace(tzinfo=timezone.utc)
        except Exception: continue
        if ts >= cutoff: rows.append({"when": ts, "pct": int(it["pct"]), "avg": float(it["avg"])})
    rows = sorted(rows, key=lambda r: r["when"])[-10:]
    if not rows: return pd.DataFrame(columns=["when","pct","avg"])
    df = pd.DataFrame(rows)
    try: df["label"] = df["when"].dt.tz_convert("UTC").dt.strftime("%d %b")
    except Exception: df["label"] = df["when"].dt.strftime("%d %b")
    return df

# ---------- Streak ----------
def _streak_load() -> dict:
    raw = cookies.get(COOKIE_STREAK_KEY)
    if not raw: return {"last": None, "count": 0}
    try:
        data = json.loads(raw); return {"last": data.get("last"), "count": int(data.get("count", 0))}
    except Exception:
        return {"last": None, "count": 0}

def _streak_save(last_day: str, count: int):
    _cookies_set(COOKIE_STREAK_KEY, json.dumps({"last": last_day, "count": int(count)}, separators=(",", ":")))

def _streak_update_on_session_end() -> int:
    today = datetime.now(timezone.utc).date()
    data = _streak_load(); last_str, count = data.get("last"), int(data.get("count", 0))
    try: last_day = date.fromisoformat(last_str) if last_str else None
    except Exception: last_day = None
    if last_day is None: new_count = 1
    else:
        delta = (today - last_day).days
        if delta == 0: new_count = count
        elif delta == 1: new_count = count + 1
        else: new_count = 1
    _streak_save(today.isoformat(), new_count)
    return new_count

# ---------- Settings cookie ----------
def _cookies_read_apply_settings():
    raw = cookies.get(COOKIE_SETTINGS_KEY)
    if not raw: return False
    try:
        data = json.loads(raw); ss = st.session_state
        ss.user = str(data.get("user", ss.user))
        ss.min_table = int(data.get("min_table", ss.min_table))
        ss.max_table = int(data.get("max_table", ss.max_table))
        ss.per_q = int(data.get("per_q", ss.per_q))
        mins = int(data.get("minutes", (ss.total_seconds // 60))); ss.total_seconds = max(0, mins) * 60
        return True
    except Exception:
        return False

def _cookies_set_current_settings_no_flush():
    ss = st.session_state
    _cookies_set(COOKIE_SETTINGS_KEY, json.dumps({
        "user": ss.user, "min_table": ss.min_table, "max_table": ss.max_table,
        "per_q": ss.per_q, "minutes": ss.total_seconds // 60
    }, separators=(",", ":")))

def _cookies_save_current_settings():
    _cookies_set_current_settings_no_flush(); _cookies_flush()

# ---------- Revisit cookie ----------
def _revisit_load() -> dict:
    raw = cookies.get(COOKIE_REVISIT_KEY)
    if not raw: return {"v": 1, "min": None, "max": None, "items": []}
    try:
        data = json.loads(raw)
        items = data.get("items") or []
        norm = []
        for it in items:
            try:
                a, b = int(it[0]), int(it[1])
                norm.append([a, b])
            except Exception:
                continue
        return {"v": 1, "min": data.get("min"), "max": data.get("max"), "items": norm}
    except Exception:
        return {"v": 1, "min": None, "max": None, "items": []}

def _revisit_save(min_table: int, max_table: int, items: list[tuple[int,int]]):
    uniq = sorted({(int(a), int(b)) for (a, b) in items})
    payload = {"v": 1, "min": int(min_table), "max": int(max_table),
               "items": [[a, b] for (a, b) in uniq]}
    _cookies_set(COOKIE_REVISIT_KEY, json.dumps(payload, separators=(",", ":")))

def _revisit_prepare_for_session():
    ss = st.session_state
    data = _revisit_load()
    same_range = (data.get("min") == ss.min_table) and (data.get("max") == ss.max_table)
    if same_range and data.get("items"):
        items = [(int(a), int(b)) for (a, b) in data["items"]]
        ss.revisit_queue = items[:]
        ss.revisit_loaded = items[:]
    else:
        ss.revisit_queue = []
        ss.revisit_loaded = []

# ---------------- State ----------------
def _init_state():
    ss = st.session_state
    ss.setdefault("screen", "start")
    ss.setdefault("running", False)
    ss.setdefault("finished", False)

    ss.setdefault("user", "")
    ss.setdefault("min_table", 2)
    ss.setdefault("max_table", 12)  # default remains 12; no hard max in UI now
    ss.setdefault("total_seconds", 180)
    ss.setdefault("per_q", 10)

    ss.setdefault("session_start", 0.0)
    ss.setdefault("deadline", 0.0)
    ss.setdefault("q_start", 0.0)
    ss.setdefault("q_deadline", 0.0)

    ss.setdefault("awaiting_answer", False)
    ss.setdefault("a", None); ss.setdefault("b", None)

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

    ss.setdefault("settings_loaded", False)

    ss.setdefault("revisit_queue", [])
    ss.setdefault("revisit_loaded", [])

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

    ss.setdefault("streak_count", _streak_load().get("count", 0))

_init_state()

# ---------- Apply URL settings once (override cookie on first load) ----------
def _apply_url_settings_from_qp_once() -> bool:
    ss = st.session_state
    found = False
    def _as_int(name, default=None, minv=None, maxv=None):
        raw = _qp_scalar(name)
        if raw is None: return default, False
        try:
            v = int(str(raw).strip())
        except Exception:
            return default, False
        if minv is not None: v = max(minv, v)
        if maxv is not None: v = min(maxv, v)
        return v, True

    user_q = _qp_scalar("user")
    if user_q is not None:
        ss.user = str(user_q).strip()
        found = True

    min_v, ok = _as_int("min", default=ss.min_table, minv=1)
    if ok: ss.min_table = min_v; found = True
    max_v, ok = _as_int("max", default=ss.max_table, minv=1)
    if ok: ss.max_table = max_v; found = True

    perq_v, ok = _as_int("per_q", default=ss.per_q, minv=2, maxv=60)
    if ok: ss.per_q = perq_v; found = True

    mins_v, ok = _as_int("minutes", default=ss.total_seconds // 60, minv=0, maxv=180)
    if ok:
        ss.total_seconds = int(mins_v) * 60
        found = True

    if ss.min_table > ss.max_table:
        ss.min_table, ss.max_table = ss.max_table, ss.min_table

    screen_q = (_qp_scalar("screen") or "").strip().lower()
    if screen_q in ("start", "practice", "results", "assign"):
        ss.screen = screen_q

    return found

if not st.session_state.settings_loaded:
    if _apply_url_settings_from_qp_once():
        st.session_state.settings_loaded = True
    else:
        _cookies_read_apply_settings()
        st.session_state.settings_loaded = True

# ---------------- Keypad component ----------------
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
            def keypad(default=None, key=None): return None
    except Exception as e:
        KP_COMPONENT_AVAILABLE = False
        KP_LOAD_ERROR = f"{type(e).__name__}: {e}"
        def keypad(default=None, key=None): return None

_register_keypad_component()

# ---------------- Core logic ----------------
MULTIPLIERS = list(range(1, 13))  # keep 1..12 multipliers; "table" (a) can be >12
FAST_FRAC = 1.0/3.0
SLOW_FRAC = 2.0/3.0
MIN_PER_Q = 2
MAX_PER_Q = 60

def _now() -> float: return time.monotonic()
def _required_digits() -> int: return len(str(abs(st.session_state.a * st.session_state.b)))
def _clamp_per_q(x: float | int) -> int: return int(min(MAX_PER_Q, max(MIN_PER_Q, round(float(x)))))

def _decrement_scheduled():
    for s in st.session_state.scheduled_repeats: s["remaining"] -= 1

def _pop_due_repeat():
    for i, s in enumerate(st.session_state.scheduled_repeats):
        if s["remaining"] <= 0: return st.session_state.scheduled_repeats.pop(i)["item"]
    return None

def _random_item():
    ss = st.session_state
    banned = {t["item"] for t in ss.scheduled_repeats} | {k for k, v in ss.attempts_wrong.items() if v >= 2}
    for _ in range(200):
        a = random.randint(ss.min_table, ss.max_table); b = random.choice(MULTIPLIERS)
        if (a, b) not in banned: return (a, b)
    cands = [(a, b) for a in range(ss.min_table, ss.max_table + 1) for b in MULTIPLIERS if (a, b) not in banned]
    return random.choice(cands) if cands else (random.randint(ss.min_table, ss.max_table), random.choice(MULTIPLIERS))

def _select_next_item():
    if st.session_state.revisit_queue:
        return st.session_state.revisit_queue.pop(0)
    _decrement_scheduled()
    due = _pop_due_repeat()
    if due: return due
    return _random_item()

def _new_question():
    ss = st.session_state
    ss.a, ss.b = _select_next_item()
    ss.q_start = _now()
    ss.q_deadline = ss.q_start + float(ss.per_q)
    ss.awaiting_answer = True
    ss.entry = ""; ss.pending_correct = False; ss.ok_until = 0.0; ss.shake_until = 0.0

def _build_results_text():
    ss = st.session_state
    total = ss.total_questions or 1
    pct = round(100 * (ss.correct_questions / total))
    lines = [
        "**Times Tables Results**",
        f"User: {ss.user or 'Anonymous'}",
        f"Score: {ss.correct_questions}/{ss.total_questions} ({pct}%)",
        f"Avg: {ss.total_time_spent/total:.2f}s  •  Time: {ss.total_time_spent:.0f}s",
        f"Streak: {ss.streak_count} day(s)",
        f"Per Q now: {ss.per_q}s",
    ]
    wrong = ", ".join(
        f"{a}×{b}" + (" (×2)" if (a, b) in ss.wrong_twice else "")
        for (a, b) in sorted(set(ss.wrong_attempt_items))
    )
    if wrong: lines.append(f"Revisit: {wrong}")
    return "\n".join(lines)

def _get_webhook_url() -> str:
    ss = st.session_state
    ui = (ss.webhook_url or "").strip()
    env_ = (os.getenv("DISCORD_WEBHOOK") or "").strip()
    sec_ = (_secret_webhook() or "").strip()
    eff = ui or env_ or sec_ or DISCORD_WEBHOOK_DEFAULT
    ss.webhook_sources.update({
        "ui": _mask_webhook(ui), "env": _mask_webhook(env_),
        "secrets": _mask_webhook(sec_), "default": _mask_webhook(DISCORD_WEBHOOK_DEFAULT),
    })
    return eff

def _send_results_discord(text: str | None = None):
    url = _get_webhook_url(); ss = st.session_state
    content = (text or _build_results_text()).strip()
    if len(content) > 1900: content = content[:1900] + "…"
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
        if r.ok: logger.info("Discord webhook success (status %s)", r.status_code)
        else: logger.error("Discord webhook non-2xx (status %s): %s", r.status_code, (r.text or "")[:200])
    except requests.exceptions.RequestException as e:
        attempt_info.update({"status": None, "ok": False, "error": f"RequestException: {e}"})
        logger.exception("Discord webhook request error")
    except Exception as e:
        attempt_info.update({"status": None, "ok": False, "error": f"{type(e).__name__}: {e}"})
        logger.exception("Discord webhook unexpected error")
    ss.last_webhook = attempt_info

def _start_session():
    ss = st.session_state
    ss.running = True; ss.finished = False
    ss.session_start = _now(); ss.deadline = ss.session_start + float(ss.total_seconds)
    ss.total_questions = 0; ss.correct_questions = 0; ss.total_time_spent = 0.0
    ss.wrong_attempt_items = []; ss.missed_items = []; ss.wrong_twice = []; ss.attempts_wrong = {}; ss.scheduled_repeats = []
    ss.entry = ""
    ss.pending_correct = False
    ss.shake_until = 0.0
    ss.ok_until = 0.0
    ss.last_kp_seq = -1           # accept fresh keypad sequence after start
    _revisit_prepare_for_session()
    _new_question()
    ss.screen = "practice"; ss.needs_rerun = True

def _end_session():
    ss = st.session_state
    ss.running = False; ss.finished = True; ss.awaiting_answer = False

    total = max(1, ss.total_questions)
    pct = int(round(100.0 * ss.correct_questions / total))
    avg = float(ss.total_time_spent / total) if total else 0.0

    _history_append_session(pct=pct, avg=avg, q=ss.total_questions)
    ss.streak_count = _streak_update_on_session_end()

    wrong_any = sorted({(a, b) for (a, b) in ss.wrong_attempt_items})
    _revisit_save(ss.min_table, ss.max_table, wrong_any)

    _cookies_set_current_settings_no_flush()
    _cookies_flush()

    try: _send_results_discord()
    except Exception: logger.exception("Discord send failed")

    ss.screen = "results"; ss.needs_rerun = True

def _record_question(correct: bool, timed_out: bool):
    ss = st.session_state
    duration = _now() - ss.q_start
    ss.total_questions += 1
    ss.total_time_spent += duration
    item = (ss.a, ss.b)

    # Adaptive timing
    if correct and duration <= FAST_FRAC * float(ss.per_q):
        ss.per_q = _clamp_per_q(ss.per_q * 0.9)    # speed up
    elif duration >= SLOW_FRAC * float(ss.per_q):
        ss.per_q = _clamp_per_q(ss.per_q * 1.1)    # slow down (regardless of correctness)

    if correct:
        ss.correct_questions += 1
        ss.scheduled_repeats = [s for s in ss.scheduled_repeats if s["item"] != item]
    else:
        cnt = ss.attempts_wrong.get(item, 0) + 1
        ss.attempts_wrong[item] = cnt
        if item not in ss.wrong_attempt_items: ss.wrong_attempt_items.append(item)
        if timed_out and item not in ss.missed_items: ss.missed_items.append(item)
        if cnt == 1:
            if item not in (s["item"] for s in ss.scheduled_repeats):
                ss.scheduled_repeats.append({"item": item, "remaining": random.randint(2, 4)})
        else:
            if item not in ss.wrong_twice: ss.wrong_twice.append(item)
            ss.scheduled_repeats = [s for s in ss.scheduled_repeats if s["item"] != item]

    ss.awaiting_answer = False

    if _now() >= ss.deadline:
        _end_session()
    else:
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
    if code == "C": st.session_state.entry = ""
    elif code == "B": st.session_state.entry = st.session_state.entry[:-1]
    elif code and code.isdigit(): st.session_state.entry += code

def _handle_keypad_payload(payload):
    if not payload: return
    text = str(payload); code, seq = None, None
    if "|" in text:
        code, seq_s = text.split("|", 1)
        try: seq = int(seq_s)
        except Exception: seq = None
    else: code = text
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

# ---------- Debug expander ----------
def _debug_cookies_expander(title="Debug: cookies"):
    with st.expander(title, expanded=False):
        st.write("**settings_loaded flag:**", st.session_state.get("settings_loaded"))
        st.write("**Exists — settings/history/streak/revisit:**",
                 bool(cookies.get(COOKIE_SETTINGS_KEY)),
                 bool(cookies.get(COOKIE_HISTORY_KEY)),
                 bool(cookies.get(COOKIE_STREAK_KEY)),
                 bool(cookies.get(COOKIE_REVISIT_KEY)))
        raw_settings = cookies.get(COOKIE_SETTINGS_KEY) or ""
        raw_revisit  = cookies.get(COOKIE_REVISIT_KEY) or ""
        st.write("**settings (raw JSON) preview:**")
        st.code(raw_settings[:600] + ("…" if len(raw_settings) > 600 else ""), language="json")
        st.write("**revisit (raw JSON) preview:**")
        st.code(raw_revisit[:600] + ("…" if len(raw_revisit) > 600 else ""), language="json")
        try: parsed = json.loads(raw_settings) if raw_settings else {}
        except Exception as e: parsed = {"_error": f"JSON parse failed: {e}"}
        try: parsed_r = json.loads(raw_revisit) if raw_revisit else {}
        except Exception as e: parsed_r = {"_error": f"JSON parse failed: {e}"}
        st.write("**settings (parsed):**", parsed)
        st.write("**revisit (parsed):**", parsed_r)
        st.write("**session_state.per_q (live):**", st.session_state.get("per_q"))

# ---------------- Screens ----------------
def screen_start():
    st.write("### Start")
    if KP_LOAD_ERROR: st.info(f"Keypad component: {KP_LOAD_ERROR}. Using fallback keypad.", icon="ℹ️")
    if DEBUG: _debug_cookies_expander()

    # ——— Widgets live (no form) so Assign uses currently visible values
    st.session_state.user = st.text_input("User (required)", st.session_state.user,
                                          max_chars=32, placeholder="Name or ID",
                                          help="Saved on this device.")

    # Row: Min/Max side-by-side
    c_min, c_max = st.columns([1, 1], gap="small")
    with c_min:
        st.session_state.min_table = int(st.number_input("Min table", min_value=1,
                                                         value=st.session_state.min_table, step=1))
    with c_max:
        st.session_state.max_table = int(st.number_input("Max table", min_value=1,
                                                         value=st.session_state.max_table, step=1))

    # Row: per_q / minutes side-by-side (kept simple)
    c_pq, c_mins = st.columns([1, 1], gap="small")
    with c_pq:
        st.session_state.per_q = int(st.number_input("Seconds per question",
                                                     min_value=MIN_PER_Q, max_value=MAX_PER_Q,
                                                     value=int(st.session_state.per_q), step=1))
    with c_mins:
        mins = st.number_input("Session minutes", min_value=0, max_value=180,
                               value=st.session_state.total_seconds // 60, step=1)
        st.session_state.total_seconds = int(mins) * 60

    if st.session_state.min_table > st.session_state.max_table:
        st.session_state.min_table, st.session_state.max_table = st.session_state.max_table, st.session_state.min_table

    if st.button("Start", type="primary", use_container_width=True):
        if not st.session_state.user or not st.session_state.user.strip():
            st.error("Please enter a User name to continue.")
        else:
            _cookies_save_current_settings()
            _start_session(); st.rerun()

def render_fallback_keypad():
    rows = [["1","2","3"], ["4","5","6"], ["7","8","9"], ["C","0","B"]]
    for r, row in enumerate(rows):
        cols = st.columns(3, gap="small")
        for c, ch in enumerate(row):
            key = f"kp_{r}_{c}_{ch}"
            if ch.isdigit():
                cols[c].button(ch, key=key, use_container_width=True, on_click=_kp_apply, args=(ch,))
            elif ch == "C":
                cols[c].button("Clear", key=key, use_container_width=True, on_click=_kp_apply, args=("C",))
            else:
                cols[c].button("Back", key=key, use_container_width=True, on_click=_kp_apply, args=("B",))

def screen_practice():
    now_ts = _now()
    _tick(now_ts)  # may end the session

    if not st.session_state.running and st.session_state.finished and st.session_state.screen != "results":
        st.session_state.screen = "results"; st.rerun(); return

    _q_bar(now_ts)

    prompt_area = st.container(); answer_area = st.container(); keypad_area = st.container()

    with keypad_area:
        if KP_COMPONENT_AVAILABLE:
            payload = keypad(default=None, key="tt_keypad")
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

    if st.session_state.running and _now() >= st.session_state.deadline:
        _end_session()

def screen_results():
    ss = st.session_state
    total = ss.total_questions; correct = ss.correct_questions
    avg = (ss.total_time_spent / total) if total else 0.0
    pct = int(round((100.0 * correct / total), 0)) if total else 0
    time_spent = ss.total_time_spent; streak = ss.streak_count

    st.subheader("Results")

    c1, c2 = st.columns(2)
    with c1:
        st.metric("Correct", f"{correct}/{total}", f"{pct}%")
        st.metric("Avg time / Q", f"{avg:0.2f} s")
    with c2:
        st.metric("Time spent", f"{time_spent:0.0f} s")
        st.metric("Streak", f"{streak} day{'s' if streak != 1 else ''}")

    st.caption(f"Per-question time now: {ss.per_q}s")

    st.write("#### Carried over this session")
    carried = ss.revisit_loaded
    st.write(", ".join(f"{a}×{b}" for (a, b) in carried) if carried else "None.")

    st.write("#### Items to revisit")
    wrong_any = sorted(list(set(ss.wrong_attempt_items)))
    st.write(", ".join(
        f"{a}×{b}{' (wrong twice)' if (a, b) in ss.wrong_twice else ''}"
        for a, b in wrong_any
    ) or "None.")

    st.write("#### Progress (last 10 days)")
    df = _history_for_last_10_days()
    if df.empty:
        st.caption("No recent history yet — complete a few sessions to see your progress.")
    else:
        st.line_chart(df.set_index("label")[["pct"]].rename(columns={"pct": "% correct"}), height=120)
        st.line_chart(df.set_index("label")[["avg"]].rename(columns={"avg": "avg sec / Q"}), height=120)

    if DEBUG:
        _debug_cookies_expander("Debug: cookies (Results)")

    if st.button("Start Over", type="primary", use_container_width=True):
        ss = st.session_state
        ss.screen = "start"
        ss.running = False
        ss.finished = False
        ss.awaiting_answer = False
        ss.pending_correct = False
        ss.entry = ""
        ss.revisit_queue = []
        ss.revisit_loaded = []
        ss.last_kp_seq = -1
        st.rerun()

def _current_params_from_state() -> dict:
    ss = st.session_state
    params = {
        "min": int(ss.min_table),
        "max": int(ss.max_table),
        "per_q": int(_clamp_per_q(ss.per_q)),
        "minutes": int(ss.total_seconds // 60),
        "screen": "start",
    }
    if ss.user and ss.user.strip():
        params["user"] = ss.user.strip()
    if DEBUG:
        params["debug"] = "1"
    return params

def screen_assign():
    st.write("### Assign")
    ss = st.session_state

    params = _current_params_from_state()
    qs = urlencode(params)

    # Instruction text
    st.write("Copy this link and send it to the learner. They can also grab it from the QR code below.")

    # Absolute link + QR (computed from top window; fallback to PUBLIC_BASE_URL or default cloud URL)
    fallback_base = (
        os.getenv("PUBLIC_BASE_URL")
        or st.secrets.get("public_base_url", "")
        or "https://times-tables-from-chalkface.streamlit.app/"
    )

    st_html(f"""
      <div id="assign-wrap" style="margin-top:8px">
        <p><strong>Full URL:</strong> <span id="fullurl"></span></p>
        <div id="qrcode" style="margin-top:8px;"></div>
      </div>
      <script>
        (function() {{
          var qs = {json.dumps(qs)};
          var base = "";
          try {{
            // Prefer the top-level window (avoids 'about:srcdoc' / 'nullsrcdoc')
            var topLoc = window.top && window.top.location;
            if (topLoc) {{
              base = topLoc.origin + topLoc.pathname;
            }}
          }} catch (e) {{}}
          if (!base || base.startsWith("null") || base.includes("srcdoc")) {{
            base = {json.dumps(fallback_base)};
          }}
          if (base && base.slice(-1) === "/") {{
            // Streamlit app root normally ends with '/', keep it
          }}
          var abs = base + (qs ? ("?" + qs) : "");
          var a = document.createElement('a');
          a.href = abs; a.target = '_blank'; a.rel = 'noopener'; a.textContent = abs;
          var span = document.getElementById('fullurl'); span.innerHTML = '';
          span.appendChild(a);

          // QR
          var s = document.createElement('script');
          s.src = "https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js";
          s.onload = function(){{
            try {{
              new QRCode(document.getElementById('qrcode'), {{ text: abs, width: 180, height: 180 }});
            }} catch (e) {{
              document.getElementById('qrcode').innerHTML = '<em>Could not render QR.</em>';
            }}
          }};
          document.currentScript.parentNode.appendChild(s);
        }})();
      </script>
    """, height=280)

    if st.button("Back to Start", use_container_width=True):
        st.session_state.screen = "start"; st.rerun()

# ---------------- Router + heartbeat ----------------
def _render():
    try:
        screen = st.session_state.screen
        if screen == "start": screen_start()
        elif screen == "practice": screen_practice()
        elif screen == "assign": screen_assign()
        else: screen_results()
    except Exception as e:
        st.error("Unhandled exception while rendering."); st.exception(e)

    # Footer (page-specific)
    if st.session_state.screen == "practice":
        st.caption(f"Times Tables Trainer {APP_VERSION} — per-Q: {int(st.session_state.per_q)}s")
    elif st.session_state.screen == "start":
        st.caption(f"Times Tables Trainer {APP_VERSION} from The Chalkface Project. "
                   f"[Assign](?screen=assign)")
    elif st.session_state.screen == "assign":
        st.caption(f"Times Tables Trainer {APP_VERSION} from The Chalkface Project")
    else:
        st.caption(f"Times Tables Trainer {APP_VERSION} from The Chalkface Project")

    if st.session_state.needs_rerun:
        st.session_state.needs_rerun = False; st.rerun()
    elif st.session_state.running:
        time.sleep(0.1); st.rerun()

_render()
