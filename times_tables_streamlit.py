import streamlit as st
import time, random

MULTIPLIERS = list(range(1, 13))  # 1..12

st.set_page_config(page_title="Times Tables Trainer", page_icon="✳️", layout="centered")

# --- Calm palette + layout + effects (no jumping toasts) ---
st.markdown(
    """
    <style>
      :root{
        --bg:#f8fafc; --text:#0f172a; --muted:#64748b;
        --blue:#60a5fa; --teal:#34d399;
        --ok-bg:#ecfdf5; --ok-bd:#16a34a; --ok-fg:#065f46;
        --bad-bg:#fef2f2; --bad-bd:#dc2626; --bad-fg:#7f1d1d;
      }
      .block-container {max-width: 50% !important;}

      .answer-display {
        font-size: 2.2rem; font-weight: 700; text-align:center;
        padding:.35rem .6rem; border:2px solid #e5e7eb; border-radius:.6rem;
        background:#f9fafb; letter-spacing:.02em;
      }
      .answer-display.ok {
        background: var(--ok-bg);
        border: 3px dashed var(--ok-bd);
        color: var(--ok-fg);
      }
      .answer-display.bad {
        background: var(--bad-bg);
        border: 3px solid var(--bad-bd);
        color: var(--bad-fg);
      }
      .subtle { color:var(--muted); font-size:0.9rem; text-align:center; }

      .barwrap { margin: 0.2rem 0 0.6rem 0; }
      .barlabel { font-size: 0.9rem; color:var(--text); margin-bottom: 0.25rem; }
      .barbg { background:#e5e7eb; border-radius: 8px; height: 12px; overflow:hidden; }
      .barfg { height: 100%; border-radius: 8px; }

      .stButton>button[kind="primary"]{
        background: var(--blue) !important; color:white !important; border:none !important;
        box-shadow: 0 1px 2px rgba(0,0,0,.05);
      }
      .stButton>button[kind="secondary"]{
        background: #e2e8f0 !important; color:#0f172a !important; border:none !important;
      }
      .stButton>button:hover{ filter: brightness(0.97); }

      @keyframes shake {
        10%, 90% { transform: translateX(-1px); }
        20%, 80% { transform: translateX(2px);  }
        30%, 50%, 70% { transform: translateX(-4px); }
        40%, 60% { transform: translateX(4px); }
      }
      .shake { animation: shake .4s linear both; }
    </style>
    """,
    unsafe_allow_html=True
)

# ---------- State ----------
def _init_state():
    ss = st.session_state
    ss.setdefault("running", False)
    ss.setdefault("finished", False)
    ss.setdefault("min_table", 2)
    ss.setdefault("max_table", 12)
    ss.setdefault("total_seconds", 180)
    ss.setdefault("per_q", 10)  # default per-question time 10s
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

    # spaced repetition & outcomes
    ss.setdefault("wrong_attempt_items", set())
    ss.setdefault("missed_items", set())
    ss.setdefault("wrong_twice", set())
    ss.setdefault("attempts_wrong", {})          # (a,b) -> wrong count across questions
    ss.setdefault("scheduled_repeats", [])       # [{'item':(a,b), 'remaining':n}]

    # UI/visual state
    ss.setdefault("entry", "")
    ss.setdefault("needs_rerun", False)
    ss.setdefault("shake_until", 0.0)            # show red/ shake until time
    ss.setdefault("ok_until", 0.0)               # show green dashed until time
    ss.setdefault("pending_correct", False)      # waiting to commit correct result

def _now() -> float:
    return time.monotonic()

def _fmt_mmss(seconds: float) -> str:
    if seconds < 0: seconds = 0
    m, s = divmod(int(round(seconds)), 60)
    return f"{m:02d}:{s:02d}"

def _required_digits() -> int:
    return len(str(abs(st.session_state.a * st.session_state.b)))

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
    banned = {t["item"] for t in ss.scheduled_repeats}
    banned |= {k for k, v in ss.attempts_wrong.items() if v >= 2}
    for _ in range(200):
        a = random.randint(ss.min_table, ss.max_table)
        b = random.choice(MULTIPLIERS)
        if (a, b) not in banned:
            return (a, b)
    candidates = [(a, b) for a in range(ss.min_table, ss.max_table + 1) for b in MULTIPLIERS if (a, b) not in banned]
    return random.choice(candidates) if candidates else (random.randint(ss.min_table, ss.max_table), random.choice(MULTIPLIERS))

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
    ss.wrong_attempt_items = set()
    ss.missed_items = set()
    ss.wrong_twice = set()
    ss.attempts_wrong = {}
    ss.scheduled_repeats = []
    _new_question()

def _end_session():
    ss = st.session_state
    ss.running = False
    ss.finished = True
    ss.awaiting_answer = False

def _record_question(correct: bool, timed_out: bool):
    ss = st.session_state
    duration = _now() - ss.q_start
    ss.total_questions += 1
    ss.total_time_spent += duration
    item = (ss.a, ss.b)
    if correct:
        ss.correct_questions += 1
        # drop any pending repeats of this item
        ss.scheduled_repeats = [s for s in ss.scheduled_repeats if s["item"] != item]
    else:
        cnt = ss.attempts_wrong.get(item, 0) + 1
        ss.attempts_wrong[item] = cnt
        ss.wrong_attempt_items.add(item)
        if timed_out:
            ss.missed_items.add(item)
        if cnt == 1:
            # schedule one repeat 2–4 questions later
            if item not in (s["item"] for s in ss.scheduled_repeats):
                ss.scheduled_repeats.append({"item": item, "remaining": random.randint(2, 4)})
        else:
            # second wrong — don’t reschedule; mark for highlighting
            ss.wrong_twice.add(item)
            ss.scheduled_repeats = [s for s in ss.scheduled_repeats if s["item"] != item]
    ss.awaiting_answer = False
    _new_question()
    ss.needs_rerun = True

def _tick(now_ts: float):
    ss = st.session_state
    if not ss.running:
        return
    # While showing green dashed confirmation, don't time out the question
    if ss.pending_correct and now_ts < ss.ok_until:
        return
    if now_ts >= ss.deadline:
        _end_session()
        ss.needs_rerun = True
        return
    if ss.awaiting_answer and now_ts >= ss.q_deadline:
        _record_question(correct=False, timed_out=True)

# ---------- Keypad callbacks (no reruns in callbacks) ----------
def _kp_append(d: str):
    if not st.session_state.awaiting_answer:
        return
    st.session_state.entry += d

def _kp_backspace():
    if not st.session_state.awaiting_answer:
        return
    st.session_state.entry = st.session_state.entry[:-1]

def _kp_clear():
    if not st.session_state.awaiting_answer:
        return
    st.session_state.entry = ""

# ---------- Small UI helpers ----------
def _bar(label: str, percent: int, colour_hex: str, caption: str = ""):
    percent = max(0, min(100, int(percent)))
    st.markdown(
        f"""
        <div class="barwrap">
          <div class="barlabel">{label}</div>
          <div class="barbg"><div class="barfg" style="width:{percent}%; background:{colour_hex};"></div></div>
          {f'<div class="subtle">{caption}</div>' if caption else ''}
        </div>
        """,
        unsafe_allow_html=True,
    )

# ---------- UI ----------
_init_state()
st.title("Times Tables Trainer")

# Placeholders to guarantee a single render of each bar
qbar_ph = st.empty()   # top question timer
sbar_ph = None         # bottom session timer

# Sidebar
with st.sidebar:
    st.header("Session settings")
    min_table = st.number_input("Min table", 1, 20, value=st.session_state.min_table, step=1)
    max_table = st.number_input("Max table", 1, 20, value=st.session_state.max_table, step=1)
    if min_table > max_table:
        min_table, max_table = max_table, min_table
    col_t = st.columns(2)
    mins = col_t[0].number_input("Minutes", 0, 180, value=st.session_state.total_seconds // 60, step=1)
    secs = col_t[1].number_input("Seconds", 0, 59, value=st.session_state.total_seconds % 60, step=1)
    per_q = col_t[0].number_input("Per-question (s)", 3, 120, value=st.session_state.per_q, step=1)

    st.session_state.min_table = int(min_table)
    st.session_state.max_table = int(max_table)
    st.session_state.total_seconds = int(mins) * 60 + int(secs)
    st.session_state.per_q = int(per_q)

    if not st.session_state.running:
        if st.button("Start session", type="primary"):
            _start_session()
    else:
        if st.button("Stop", type="secondary"):
            _end_session()

# Compute one timestamp per run
now_ts = _now()

# TOP: Question timer (single render via placeholder)
if st.session_state.running:
    q_left_s = st.session_state.q_deadline - now_ts
    q_pct = round(100 * q_left_s / max(1, st.session_state.per_q))
    with qbar_ph:
        _bar("Question time", q_pct, "var(--blue)", f"Time left: {_fmt_mmss(q_left_s)}")
else:
    with qbar_ph:
        _bar("Question time", 0, "var(--blue)", "Time left: 00:00")

# Question + entry display
if st.session_state.running:
    # Handle timeouts and auto-submit/confirmation in main thread
    _tick(now_ts)

    # If we're showing the green-dashed confirmation, commit after it expires
    if st.session_state.pending_correct and now_ts >= st.session_state.ok_until:
        st.session_state.pending_correct = False
        _record_question(correct=True, timed_out=False)

    if st.session_state.awaiting_answer:
        target = st.session_state.a * st.session_state.b
        need = _required_digits()
        if len(st.session_state.entry) == need:
            try:
                val = int(st.session_state.entry)
            except ValueError:
                st.session_state.entry = ""
                st.session_state.shake_until = now_ts + 0.45
            else:
                if val == target:
                    # Show green dashed confirmation briefly, then record and move on
                    st.session_state.awaiting_answer = False
                    st.session_state.pending_correct = True
                    st.session_state.ok_until = now_ts + 0.6
                else:
                    # Wrong attempt: red border + shake, then clear for retry (question stays active)
                    st.session_state.entry = ""
                    st.session_state.wrong_attempt_items.add((st.session_state.a, st.session_state.b))
                    st.session_state.shake_until = now_ts + 0.45

    st.subheader(f"{st.session_state.a} × {st.session_state.b} = ?")

    # Answer pill with state classes
    classes = ["answer-display"]
    if st.session_state.pending_correct and now_ts < st.session_state.ok_until:
        classes.append("ok")
    elif now_ts < st.session_state.shake_until:
        classes.append("bad"); classes.append("shake")

    st.markdown(f"<div class='{ ' '.join(classes) }'>{st.session_state.entry or '&nbsp;'}</div>", unsafe_allow_html=True)
    st.markdown(
        f"<div class='subtle'>Auto-submit after <b>{_required_digits()}</b> digit{'s' if _required_digits()>1 else ''}</div>",
        unsafe_allow_html=True
    )

    # Keypad (numbers = primary; C/⌫ = secondary)
    kp_cols = st.columns(3)
    keys = ["1","2","3","4","5","6","7","8","9","C","0","⌫"]
    for i, key in enumerate(keys):
        col = kp_cols[i % 3]
        if key.isdigit():
            col.button(
                key, use_container_width=True, type="primary",
                on_click=_kp_append, args=(key,)
            )
        elif key == "C":
            col.button("C", use_container_width=True, type="secondary", on_click=_kp_clear)
        elif key == "⌫":
            col.button("⌫", use_container_width=True, type="secondary", on_click=_kp_backspace)

    st.caption(f"Answered: {st.session_state.total_questions}  |  Correct: {st.session_state.correct_questions}")

# Report
if st.session_state.finished:
    total = st.session_state.total_questions
    correct = st.session_state.correct_questions
    avg = (st.session_state.total_time_spent / total) if total else 0.0
    pct = (100.0 * correct / total) if total else 0.0

    st.subheader("Session report")
    st.write(f"Questions answered: **{total}**")
    st.write(f"Correct: **{correct}** ({pct:0.1f}%)")
    st.write(f"Average time per question: **{avg:0.2f}s**")

    wrong_any = sorted(list(st.session_state.wrong_attempt_items), key=lambda t: (t[0], t[1]))
    if wrong_any:
        st.write("Items you got wrong at least once:")
        lines = []
        for a, b in wrong_any:
            prod = a * b
            if (a, b) in st.session_state.wrong_twice:
                lines.append(f"<div style='color:#b91c1c;font-weight:700'>✕ {a} × {b} = {prod} — wrong twice</div>")
            else:
                lines.append(f"<div>• {a} × {b} = {prod}</div>")
        st.markdown("\n".join(lines), unsafe_allow_html=True)

        csv = "a,b,answer,wrong_twice\n" + "\n".join(
            [f"{a},{b},{a*b},{1 if (a,b) in st.session_state.wrong_twice else 0}" for a,b in wrong_any]
        )
        st.download_button("Download list (CSV)", data=csv, file_name="wrong_items.csv", mime="text/csv")
    else:
        st.success("You didn’t get any items wrong.")

    if st.button("Start a new session"):
        _start_session()

# BOTTOM: Session timer (single render via placeholder)
sbar_ph = st.empty()
if st.session_state.running:
    sess_left_s = st.session_state.deadline - now_ts
    sess_pct = round(100 * sess_left_s / max(1, st.session_state.total_seconds))
    st.markdown("<hr style='border:none;height:1px;background:#e5e7eb;margin:0.8rem 0'/>", unsafe_allow_html=True)
    with sbar_ph:
        _bar("Session time", sess_pct, "var(--teal)", f"Time left: {_fmt_mmss(sess_left_s)}")
else:
    with sbar_ph:
        _bar("Session time", 0, "var(--teal)", "Time left: 00:00")

# ---------- Main-thread refresh loop ----------
if st.session_state.needs_rerun:
    st.session_state.needs_rerun = False
    st.rerun()
elif st.session_state.running:
    time.sleep(1)
    st.rerun()
