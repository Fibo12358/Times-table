# times_tables_streamlit.py — 3-across HTML keypad; gap-aware; version badge
import streamlit as st
import time, random

APP_VERSION = "v1.3.0"  # increment each revision
MULTIPLIERS = list(range(1, 13))  # 1..12

st.set_page_config(page_title="Times Tables Trainer", page_icon="✳️", layout="centered")

# ---------- Styles ----------
st.markdown("""
<style>
:root{
  /* calm dark palette */
  --bg:#0b1220; --text:#f8fafc; --muted:#94a3b8;
  --blue:#60a5fa; --teal:#34d399;
  --ok-bg:#ecfdf5; --ok-bd:#16a34a; --ok-fg:#065f46;
  --bad-bg:#fef2f2; --bad-bd:#dc2626; --bad-fg:#7f1d1d;

  /* keypad spacing variable (shrinks on narrow screens) */
  --kp-gap: 8px;
  --btn-h: 64px;
}
@media (max-width: 680px){ :root{ --kp-gap: 6px; --btn-h: 64px; } }
@media (max-width: 420px){ :root{ --kp-gap: 4px; --btn-h: 56px; } }

html, body { background: var(--bg); color: var(--text); }

.block-container{max-width:50% !important;}
@media (max-width: 768px){
  .block-container{max-width:100% !important; padding-left:1rem; padding-right:1rem;}
}

/* Answer pill */
.answer-display{
  font-size:2.2rem; font-weight:700; text-align:center;
  padding:.35rem .6rem; border:2px solid #334155; border-radius:.6rem;
  background:#0f172a; color:var(--text); letter-spacing:.02em;
}
.answer-display.ok{ background:var(--ok-bg); border:3px dashed var(--ok-bd); color:var(--ok-fg);}
.answer-display.bad{ background:var(--bad-bg); border:3px solid var(--bad-bd); color:var(--bad-fg);}
.subtle{ color:var(--muted); font-size:.95rem; text-align:center; }

/* Bars */
.barwrap{ margin:.2rem 0 .6rem 0;}
.barlabel{ font-size:.95rem; color:var(--text); margin-bottom:.25rem;}
.barbg{ background:#334155; border-radius:8px; height:12px; overflow:hidden;}
.barfg{ height:100%; border-radius:8px; }

/* HTML keypad (no Streamlit columns) */
.kp-grid{
  width:100%;
  display:grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--kp-gap);
}
.kp-btn{
  display:flex; align-items:center; justify-content:center;
  height: var(--btn-h);
  font-size: 1.25rem; font-weight: 800; text-decoration:none;
  border-radius: .6rem; border: 0; box-sizing: border-box;
  user-select: none;
}
.kp-btn.primary{ background: var(--blue); color: #0b1220; }
.kp-btn.secondary{ background:#1f2937; color:#e5e7eb; border:1px solid #334155; }
.kp-btn:active{ filter: brightness(0.95); }

/* Shake effect */
@keyframes shake{10%,90%{transform:translateX(-1px);}20%,80%{transform:translateX(2px);}30%,50%,70%{transform:translateX(-4px);}40%,60%{transform:translateX(4px);} }
.shake{ animation:shake .4s linear both; }

/* Version badge */
.version-badge{
  position:fixed; bottom:6px; left:50%; transform:translateX(-50%);
  font-size:.75rem; color:#94a3b8; opacity:.85; pointer-events:none;
}
</style>
""", unsafe_allow_html=True)

# ---------- State ----------
def _init_state():
    ss = st.session_state
    ss.setdefault("running", False)
    ss.setdefault("finished", False)
    ss.setdefault("min_table", 2)
    ss.setdefault("max_table", 12)
    ss.setdefault("total_seconds", 180)
    ss.setdefault("per_q", 10)  # 10s default
    ss.setdefault("session_start", 0.0)
    ss.setdefault("deadline", 0.0)
    ss.setdefault("q_start", 0.0)
    ss.setdefault("q_deadline", 0.0)
    ss.setdefault("awaiting_answer", False)
    ss.setdefault("a", None); ss.setdefault("b", None)
    ss.setdefault("total_questions", 0)
    ss.setdefault("correct_questions", 0)
    ss.setdefault("total_time_spent", 0.0)
    # spaced repetition
    ss.setdefault("wrong_attempt_items", set())
    ss.setdefault("missed_items", set())
    ss.setdefault("wrong_twice", set())
    ss.setdefault("attempts_wrong", {})
    ss.setdefault("scheduled_repeats", [])
    # UI
    ss.setdefault("entry", "")
    ss.setdefault("needs_rerun", False)
    ss.setdefault("shake_until", 0.0)
    ss.setdefault("ok_until", 0.0)
    ss.setdefault("pending_correct", False)
    ss.setdefault("last_kp_tok", "")

def _now(): return time.monotonic()
def _fmt_mmss(s):
    if s < 0: s = 0
    m, s = divmod(int(round(s)), 60); return f"{m:02d}:{s:02d}"
def _required_digits(): return len(str(abs(st.session_state.a * st.session_state.b)))

def _decrement_scheduled():
    for s in st.session_state.scheduled_repeats: s["remaining"] -= 1
def _pop_due_repeat():
    for i, s in enumerate(st.session_state.scheduled_repeats):
        if s["remaining"] <= 0: return st.session_state.scheduled_repeats.pop(i)["item"]
    return None
def _random_item():
    ss = st.session_state
    banned = {t["item"] for t in ss.scheduled_repeats} | {k for k,v in ss.attempts_wrong.items() if v>=2}
    for _ in range(200):
        a = random.randint(ss.min_table, ss.max_table); b = random.choice(MULTIPLIERS)
        if (a,b) not in banned: return (a,b)
    cands = [(a,b) for a in range(ss.min_table, ss.max_table+1) for b in MULTIPLIERS if (a,b) not in banned]
    return random.choice(cands) if cands else (random.randint(ss.min_table, ss.max_table), random.choice(MULTIPLIERS))
def _select_next_item():
    _decrement_scheduled(); due = _pop_due_repeat()
    return due if due else _random_item()

def _new_question():
    ss = st.session_state
    ss.a, ss.b = _select_next_item()
    ss.q_start = _now(); ss.q_deadline = ss.q_start + float(ss.per_q)
    ss.awaiting_answer = True
    ss.entry = ""; ss.pending_correct = False; ss.ok_until = 0.0; ss.shake_until = 0.0

def _start_session():
    ss = st.session_state
    ss.running = True; ss.finished = False
    ss.session_start = _now(); ss.deadline = ss.session_start + float(ss.total_seconds)
    ss.total_questions = 0; ss.correct_questions = 0; ss.total_time_spent = 0.0
    ss.wrong_attempt_items = set(); ss.missed_items = set(); ss.wrong_twice = set()
    ss.attempts_wrong = {}; ss.scheduled_repeats = []
    _new_question()
def _end_session():
    ss = st.session_state
    ss.running = False; ss.finished = True; ss.awaiting_answer = False

def _record_question(correct: bool, timed_out: bool):
    ss = st.session_state
    duration = _now() - ss.q_start
    ss.total_questions += 1; ss.total_time_spent += duration
    item = (ss.a, ss.b)
    if correct:
        ss.correct_questions += 1
        ss.scheduled_repeats = [s for s in ss.scheduled_repeats if s["item"] != item]
    else:
        cnt = ss.attempts_wrong.get(item, 0) + 1
        ss.attempts_wrong[item] = cnt; ss.wrong_attempt_items.add(item)
        if timed_out: ss.missed_items.add(item)
        if cnt == 1:
            if item not in (s["item"] for s in ss.scheduled_repeats):
                ss.scheduled_repeats.append({"item": item, "remaining": random.randint(2,4)})
        else:
            ss.wrong_twice.add(item)
            ss.scheduled_repeats = [s for s in ss.scheduled_repeats if s["item"] != item]
    ss.awaiting_answer = False; _new_question(); ss.needs_rerun = True

def _tick(now_ts: float):
    ss = st.session_state
    if not ss.running: return
    if ss.pending_correct and now_ts < ss.ok_until: return
    if now_ts >= ss.deadline: _end_session(); ss.needs_rerun = True; return
    if ss.awaiting_answer and now_ts >= ss.q_deadline: _record_question(False, True)

# keypad actions (used by URL-param based keypad)
def _kp_apply(code: str):
    if not st.session_state.awaiting_answer: return
    if code == "C":
        st.session_state.entry = ""
    elif code == "B":
        st.session_state.entry = st.session_state.entry[:-1]
    elif code.isdigit():
        st.session_state.entry += code

# ---------- UI ----------
_init_state()
st.title("Times Tables Trainer")

# Controls
with st.container():
    c1, c2 = st.columns([1,1])
    with c1:
        if not st.session_state.running:
            st.button("Start session", type="primary", use_container_width=True, on_click=_start_session)
        else:
            st.button("Stop", type="secondary", use_container_width=True, on_click=_end_session)
    with c2:
        st.caption("You can adjust settings below at any time.")
    with st.expander("Session settings", expanded=not st.session_state.running):
        colA, colB, colC = st.columns([1,1,1])
        with colA:
            st.session_state.min_table = int(st.number_input("Min table", 1, 20, value=st.session_state.min_table, step=1))
        with colB:
            st.session_state.max_table = int(st.number_input("Max table", 1, 20, value=st.session_state.max_table, step=1))
        if st.session_state.min_table > st.session_state.max_table:
            st.session_state.min_table, st.session_state.max_table = st.session_state.max_table, st.session_state.min_table
        with colC:
            st.session_state.per_q = int(st.number_input("Per-question (s)", 3, 120, value=st.session_state.per_q, step=1))
        colD, colE = st.columns(2)
        with colD:
            mins = st.number_input("Session minutes", 0, 180, value=st.session_state.total_seconds // 60, step=1)
        with colE:
            secs = st.number_input("Session seconds", 0, 59, value=st.session_state.total_seconds % 60, step=1)
        st.session_state.total_seconds = int(mins)*60 + int(secs)

# Bars
qbar_ph = st.empty()
now_ts = _now()
if st.session_state.running:
    q_left_s = st.session_state.q_deadline - now_ts
    q_pct = round(100 * q_left_s / max(1, st.session_state.per_q))
    with qbar_ph:
        st.markdown(
            f"""<div class="barwrap"><div class="barlabel">Question time</div>
            <div class="barbg"><div class="barfg" style="width:{q_pct}%; background:var(--blue);"></div></div>
            <div class="subtle">Time left: {_fmt_mmss(q_left_s)}</div></div>""",
            unsafe_allow_html=True
        )
else:
    with qbar_ph:
        st.markdown(
            """<div class="barwrap"><div class="barlabel">Question time</div>
            <div class="barbg"><div class="barfg" style="width:0%; background:var(--blue);"></div></div>
            <div class="subtle">Time left: 00:00</div></div>""",
            unsafe_allow_html=True
        )

# Handle keypad URL params BEFORE main logic
# Supports both new and old Streamlit query param APIs
kp = None; tok = None
try:
    q = st.query_params
    kp = q.get("kp"); tok = q.get("tok")
except Exception:
    q = st.experimental_get_query_params()
    kp_list = q.get("kp", [None]); tok_list = q.get("tok", [None])
    kp = kp_list[0]; tok = tok_list[0]

if kp:
    if tok != st.session_state.last_kp_tok:
        _kp_apply(kp)
        st.session_state.last_kp_tok = tok or ""
        # clear params
        try:
            st.query_params.clear()
        except Exception:
            st.experimental_set_query_params()

# Main area
if st.session_state.running:
    _tick(now_ts)

    if st.session_state.pending_correct and now_ts >= st.session_state.ok_until:
        st.session_state.pending_correct = False
        _record_question(True, False)

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
                    st.session_state.awaiting_answer = False
                    st.session_state.pending_correct = True
                    st.session_state.ok_until = now_ts + 0.6
                else:
                    st.session_state.entry = ""
                    st.session_state.wrong_attempt_items.add((st.session_state.a, st.session_state.b))
                    st.session_state.shake_until = now_ts + 0.45

    st.subheader(f"{st.session_state.a} × {st.session_state.b} = ?")

    # Answer pill
    classes = ["answer-display"]
    if st.session_state.pending_correct and now_ts < st.session_state.ok_until:
        classes.append("ok")
    elif now_ts < st.session_state.shake_until:
        classes.append("bad"); classes.append("shake")
    st.markdown(f"<div class='{' '.join(classes)}'>{st.session_state.entry or '&nbsp;'}</div>", unsafe_allow_html=True)
    st.markdown(f"<div class='subtle'>Auto-submit after <b>{_required_digits()}</b> digit{'s' if _required_digits()>1 else ''}</div>", unsafe_allow_html=True)

    # HTML keypad (always 3 columns)
    nonce = str(int(time.time() * 1000))  # prevent duplicate handling
    def btn(label, code, kind="primary"):
        return f'<a class="kp-btn {kind}" href="?kp={code}&tok={nonce}">{label}</a>'

    grid = []
    grid += [btn("1","1"), btn("2","2"), btn("3","3")]
    grid += [btn("4","4"), btn("5","5"), btn("6","6")]
    grid += [btn("7","7"), btn("8","8"), btn("9","9")]
    grid += [btn("C","C","secondary"), btn("0","0"), btn("⌫","B","secondary")]
    html = '<div class="kp-grid">' + "".join(grid) + '</div>'
    st.markdown(html, unsafe_allow_html=True)

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
    if st.button("Start a new session", type="primary"):
        _start_session()

# Bottom session timer
sbar_ph = st.empty()
if st.session_state.running:
    sess_left_s = st.session_state.deadline - now_ts
    sess_pct = round(100 * sess_left_s / max(1, st.session_state.total_seconds))
    st.markdown("<hr style='border:none;height:1px;background:#334155;margin:.8rem 0'/>", unsafe_allow_html=True)
    with sbar_ph:
        st.markdown(
            f"""<div class="barwrap"><div class="barlabel">Session time</div>
            <div class="barbg"><div class="barfg" style="width:{sess_pct}%; background:var(--teal);"></div></div>
            <div class="subtle">Time left: {_fmt_mmss(sess_left_s)}</div></div>""",
            unsafe_allow_html=True
        )
else:
    with sbar_ph:
        st.markdown(
            """<div class="barwrap"><div class="barlabel">Session time</div>
            <div class="barbg"><div class="barfg" style="width:0%; background:var(--teal);"></div></div>
            <div class="subtle">Time left: 00:00</div></div>""",
            unsafe_allow_html=True
        )

# Version badge
st.markdown(f"<div class='version-badge'>Times Tables Trainer {APP_VERSION}</div>", unsafe_allow_html=True)

# Refresh loop
if st.session_state.needs_rerun:
    st.session_state.needs_rerun = False
    st.rerun()
elif st.session_state.running:
    time.sleep(1); st.rerun()
