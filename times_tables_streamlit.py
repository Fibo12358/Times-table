# times_tables_streamlit.py — mobile-first, 3 screens (Start → Practice → Results) + Assign helper
# Features: Numeric keypad (custom or fallback), auto-submit, spaced repetition,
# Discord webhook, cookies (settings, history, streak, revisit), adaptive timing,
# URL-parameter bootstrap for initial settings, Assign page with sharable link + QR.
# Version: v1.31.0
#
# v1.31.0:
# - Dark-mode contrast fix for Results KPI tiles (value/label/border/background) using theme-aware CSS vars.

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
import altair as alt
from streamlit.components.v1 import declare_component, html as st_html
from streamlit_cookies_manager import EncryptedCookieManager  # robust cookies

APP_VERSION = "v1.31.0"
DEFAULT_BASE_URL = "https://times-tables-from-chalkface.streamlit.app/"

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

def _public_base_url() -> str | None:
    try:
        v = st.secrets.get("public_base_url")
        if v: return str(v)
    except Exception:
        pass
    try:
        v = st.secrets["general"]["public_base_url"]
        if v: return str(v)
    except Exception:
        pass
    return None

# ---------------- Page config + compact CSS ----------------
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

# ---- GLOBAL STYLES (light/dark aware) ----
st.markdown("""
<style>
  /* Layout tightening + bottom padding to clear fixed session bar */
  .block-container{ max-width: 480px !important; padding: 4px 8px 72px !important; }
  [data-testid="stVerticalBlock"]{ gap: 6px !important; }
  .element-container{ padding-top: 0.1rem !important; padding-bottom: 0.1rem !important; }

  /* Base tokens (light theme defaults) */
  :root{
    --bg:#ffffff;
    --fg:#0f172a;         /* slate-900 */
    --muted:#64748b;      /* slate-500 */
    --blue:#2563eb; --blue2:#60a5fa;
    --ok-bg:#ecfdf5; --ok-bd:#16a34a; --ok-fg:#065f46;
    --bad-bg:#fef2f2; --bad-bd:#dc2626; --bad-fg:#7f1d1d;
    --slate-bd:#cbd5e1;   /* light border */

    --amber:#f59e0b; --amber2:#fbbf24;

    /* KPI variables (Results tiles) — LIGHT */
    --kpi-bg:#ffffff;
    --kpi-bd:#cbd5e1;
    --kpi-v:#0f172a;      /* value text */
    --kpi-l:#64748b;      /* label text */

    /* Caption */
    --mini:#64748b;
  }

  /* Dark theme overrides for good contrast */
  @media (prefers-color-scheme: dark){
    :root{
      --bg:#0b1220;
      --fg:#e5e7eb;       /* slate-200 */
      --muted:#94a3b8;    /* slate-400 */
      --slate-bd:#334155; /* darker border */

      /* KPI variables — DARK (higher contrast on dark bg) */
      --kpi-bg:#0f172a;   /* panel bg */
      --kpi-bd:#334155;   /* border */
      --kpi-v:#e5e7eb;    /* value */
      --kpi-l:#a8b1bb;    /* label */

      --mini:#94a3b8;     /* captions */
    }
  }

  /* Tiny titlebar (minimise top whitespace) */
  .tt-title{ font-weight:700; font-size:1rem; margin:2px 0 2px; color: var(--fg); }

  /* Practice prompt + answer */
  .tt-prompt h1 { font-size: clamp(40px, 15vw, 80px); line-height: 1; margin: 0px 0 2px; text-align:center; color: var(--fg); }
  @media (max-width: 420px){ .tt-prompt h1{ font-size: clamp(36px, 14vw, 64px); } }
  .answer-display{ font-size:1.6rem; font-weight:700; text-align:center; padding:.24rem .5rem; border:2px solid var(--slate-bd); border-radius:.6rem; background:#ffffff; margin:2px 0 2px; color:#111827; }
  .answer-display.ok{ background:var(--ok-bg); border:3px dashed var(--ok-bd); color:var(--ok-fg); }
  .answer-display.bad{ background:var(--bad-bg); border:3px solid var(--bad-bd); color:var(--bad-fg); }

  /* Buttons */
  .stButton>button[kind="primary"]{ background:var(--blue) !important; color:#ffffff !important; border:none !important; font-weight:700; width:100%; min-height:44px; }
  .stButton>button{ min-height:40px; width:100%; }

  /* Bars */
  .barwrap{ background:#e5e7eb; border:1px solid var(--slate-bd); border-radius:10px; height:6px; overflow:hidden; }
  .barlabel{ display:flex; justify-content:space-between; font-size:.78rem; color:var(--muted); margin:0 2px 2px; }
  .barfill-q{ background:linear-gradient(90deg, var(--amber), var(--amber2)); height:100%; width:0%; transition:width .12s linear; }
  .barfill-s{ background:linear-gradient(90deg, var(--blue), var(--blue2)); height:100%; width:0%; transition:width .12s linear; }

  /* Fixed session bar (centred to content width) */
  .fixed-bottom{ position: fixed; left: 0; right: 0; bottom: 0; background: var(--bg); z-index: 1000; border-top:1px solid var(--slate-bd); }
  .fixed-bottom .inner{ max-width: 480px; margin: 0 auto; padding: 4px 8px 6px; }

  /* Results — KPI tiles use theme variables for contrast */
  .kpi-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:6px;margin:4px 0;}
  .kpi{border:1px solid var(--kpi-bd);border-radius:8px;padding:6px 8px;background:var(--kpi-bg)}
  .kpi .v{font-weight:700;font-size:1.05rem;line-height:1;color:var(--kpi-v)}
  .kpi .l{font-size:.78rem;color:var(--kpi-l);margin-top:2px}
  @media (max-width:360px){.kpi .v{font-size:1rem}}

  .mini-caption{ font-size: 0.78rem; color: var(--mini); margin-top: 6px; } /* captions/legends */
</style>
""", unsafe_allow_html=True)

# ---------------- Cookies ----------------
COOKIE_PREFIX = "ttt/"
COOKIE_SETTINGS_KEY = "settings"
COOKIE_HISTORY_KEY = "history"
COOKIE_STREAK_KEY = "streak"
COOKIE_REVISIT_KEY = "revisit"   # {"v":1,"min":int
