# Times Tables Trainer (Streamlit)

A calm, keypad-first trainer for multiplication tables:
- Randomised questions, with min/max tables.
- Per-question timer bar (top) and session timer bar (bottom).
- On-screen keypad; auto-submit when the answer reaches the right number of digits.
- Clear visual feedback (red solid on wrong; green dashed on correct).
- Spaced repetition: a missed item reappears after 2–4 other questions; if wrong twice, it won’t reappear this session and is highlighted in the report.
- Adaptive timing: per-question limit adjusts ±10% based on answer speed and accuracy (2–30 s, saved between sessions).

## Run locally
```bash
python3 -m pip install -r requirements.txt
python3 -m streamlit run times_tables_streamlit.py
```

## Mobile layout

The app uses dynamic viewport units (`100dvh` with a `100vh` fallback) and clamps the keypad area to `height: clamp(260px, 38dvh, 340px)` to keep all four rows visible on phones like the Pixel 7a/9a.
