"""
⚡ Thunder Detector Pro — Ultimate Streamlit Edition
=====================================================
Real-time storm monitor with advanced analytics, AI analysis,
auto-calibration, sound alerts, heatmap, PDF export, and more.

Install:
    pip install streamlit sounddevice numpy scipy plotly pandas
                reportlab pygame

Run:
    streamlit run app.py
"""

import time
import queue
import math
import random
import io
import json
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from collections import deque

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

# ── Optional imports ──────────────────────────────────────────────────────────
try:
    import sounddevice as sd
    from scipy.signal import butter, lfilter, welch
    AUDIO_AVAILABLE = True
except ImportError:
    AUDIO_AVAILABLE = False

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors as rl_colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

# ─────────────────────────────────────────────────────────────────────────────
# Module-level audio queue (NEVER put in session_state — background C thread!)
# ─────────────────────────────────────────────────────────────────────────────
_AUDIO_QUEUE: queue.Queue = queue.Queue()

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────
SAMPLE_RATE       = 44100
BLOCK_SIZE        = 2048
CHANNELS          = 1
THUNDER_LOW_HZ    = 20
THUNDER_HIGH_HZ   = 120
SPEED_SOUND_KMS   = 0.343
FLASH_WINDOW_SEC  = 30
RMS_HISTORY_LEN   = 400
CALIBRATION_SECS  = 5
NOISE_SMOOTHING   = 0.92        # EMA alpha for noise floor
STORM_APPROACHING_THRESHOLD = 2 # consecutive events getting closer

# ─────────────────────────────────────────────────────────────────────────────
# Page config
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="⚡ Thunder Detector Pro",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# CSS — industrial-military aesthetic with amber/storm palette
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;900&family=Share+Tech+Mono&family=Exo+2:wght@300;400;600&display=swap');

html, body, [class*="css"] { font-family: 'Exo 2', sans-serif !important; }

.stApp {
    background:
        radial-gradient(ellipse 120% 40% at 50% -5%, #0e2030 0%, transparent 60%),
        linear-gradient(180deg, #020c14 0%, #040d12 100%);
    min-height: 100vh;
}

/* Scanline overlay */
.stApp::before {
    content: '';
    position: fixed; inset: 0; pointer-events: none; z-index: 0;
    background: repeating-linear-gradient(
        0deg, transparent, transparent 2px,
        rgba(0,0,0,0.03) 2px, rgba(0,0,0,0.03) 4px
    );
}

/* Title */
.pro-title {
    font-family: 'Orbitron', monospace;
    font-weight: 900;
    font-size: 2.6rem;
    letter-spacing: 8px;
    background: linear-gradient(135deg, #f5c518 0%, #ff8c00 50%, #ff4500 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    text-shadow: none;
    line-height: 1;
    filter: drop-shadow(0 0 20px rgba(245,197,24,0.25));
}
.pro-sub {
    font-family: 'Share Tech Mono', monospace;
    font-size: 0.62rem;
    letter-spacing: 4px;
    color: #2a5570;
    margin-top: 5px;
}

/* Metric cards */
[data-testid="metric-container"] {
    background: linear-gradient(135deg, #0a1825 0%, #0d1f2e 100%) !important;
    border: 1px solid #1e3a50 !important;
    border-top: 2px solid rgba(245,197,24,0.25) !important;
    border-radius: 4px !important;
    padding: 14px 18px !important;
    position: relative;
}
[data-testid="metric-container"] label {
    font-family: 'Share Tech Mono', monospace !important;
    font-size: 0.55rem !important;
    letter-spacing: 3px !important;
    color: #2a5570 !important;
}
[data-testid="metric-container"] [data-testid="stMetricValue"] {
    font-family: 'Orbitron', monospace !important;
    font-size: 1.9rem !important;
    font-weight: 700 !important;
    color: #f5c518 !important;
}
[data-testid="stMetricDelta"] { font-family: 'Share Tech Mono', monospace !important; font-size: 0.65rem !important; }

/* Alert styles */
.alert-box {
    border-radius: 3px;
    padding: 12px 18px;
    font-family: 'Share Tech Mono', monospace;
    font-size: 0.78rem;
    letter-spacing: 1px;
    display: flex; align-items: center; gap: 12px;
    margin-bottom: 10px;
}
.alert-danger  { background:#200010; border:1px solid #ff2d55; border-left:4px solid #ff2d55; color:#ff2d55; }
.alert-warning { background:#1e1000; border:1px solid #ff8c00; border-left:4px solid #ff8c00; color:#ff8c00; }
.alert-watch   { background:#1a1800; border:1px solid #f5c518; border-left:4px solid #f5c518; color:#f5c518; }
.alert-clear   { background:#001810; border:1px solid #00e676; border-left:4px solid #00e676; color:#00e676; }

/* Approaching storm pulse */
.approaching { animation: pulse-border 1s ease-in-out infinite alternate; }
@keyframes pulse-border { from { border-left-color: #ff2d55; } to { border-left-color: rgba(255,0,0,0.25); } }

/* Sidebar */
[data-testid="stSidebar"] {
    background: #050e17 !important;
    border-right: 1px solid #1e3a50 !important;
}
[data-testid="stSidebar"] * { color: #7aabb8 !important; }
[data-testid="stSidebar"] .stSlider [data-testid="stMarkdownContainer"] p { font-size: 0.7rem !important; }

/* Section headers */
.sec-hdr {
    font-family: 'Share Tech Mono', monospace;
    font-size: 0.55rem;
    letter-spacing: 4px;
    color: #1e4060;
    text-transform: uppercase;
    padding-bottom: 6px;
    border-bottom: 1px solid #1e3a50;
    margin-bottom: 10px;
    display: flex; align-items: center; gap: 8px;
}
.sec-hdr-dot { width:6px; height:6px; border-radius:50%; background:#f5c518; display:inline-block; }

/* Tab styling */
[data-testid="stTabs"] [data-baseweb="tab-list"] {
    background: #050e17;
    border-bottom: 1px solid #1e3a50;
    gap: 2px;
}
[data-testid="stTabs"] [data-baseweb="tab"] {
    font-family: 'Share Tech Mono', monospace !important;
    font-size: 0.62rem !important;
    letter-spacing: 2px !important;
    color: #2a5570 !important;
    background: transparent !important;
    border: none !important;
    padding: 8px 16px !important;
}
[data-testid="stTabs"] [aria-selected="true"] {
    color: #f5c518 !important;
    border-bottom: 2px solid #f5c518 !important;
}

/* Buttons */
.stButton > button {
    font-family: 'Share Tech Mono', monospace !important;
    letter-spacing: 2px !important;
    font-size: 0.65rem !important;
    border-radius: 3px !important;
    transition: all 0.15s !important;
}
.stButton > button:hover { transform: translateY(-1px); }

/* Status badge */
.status-live {
    display: inline-flex; align-items: center; gap: 6px;
    background: #001a0a; border: 1px solid #00e676;
    border-radius: 2px; padding: 4px 12px;
    font-family: 'Share Tech Mono', monospace;
    font-size: 0.6rem; letter-spacing: 2px; color: #00e676;
}
.status-dot { width: 7px; height: 7px; border-radius: 50%; background: #00e676; animation: blink 1s infinite; }
@keyframes blink { 0%,100%{opacity:1} 50%{opacity:0.2} }

.status-idle {
    display: inline-flex; align-items: center; gap: 6px;
    background: #100a00; border: 1px solid rgba(245,197,24,0.38);
    border-radius: 2px; padding: 4px 12px;
    font-family: 'Share Tech Mono', monospace;
    font-size: 0.6rem; letter-spacing: 2px; color: rgba(245,197,24,0.63);
}

/* Calibration bar */
.cal-bar-wrap { background:#0a1825; border:1px solid #1e3a50; border-radius:3px; height:8px; overflow:hidden; margin:6px 0; }
.cal-bar-fill { height:100%; background: linear-gradient(90deg,#f5c518,#ff8c00); transition: width 0.3s; }

/* Info card */
.info-card {
    background: #0a1825;
    border: 1px solid #1e3a50;
    border-radius: 4px;
    padding: 14px 16px;
    font-family: 'Share Tech Mono', monospace;
    font-size: 0.65rem;
    color: #3a6070;
    line-height: 2;
}
.info-card b { color: #7aabb8; }
.info-card span.val { color: #f5c518; }

/* Storm trend badge */
.trend-approaching { color: #ff2d55; font-weight: bold; }
.trend-moving-away { color: #00e676; font-weight: bold; }
.trend-stationary  { color: #f5c518; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# Session state
# ─────────────────────────────────────────────────────────────────────────────
def init_state():
    defaults = {
        "events":             [],
        "rms_history":        deque([0.0] * RMS_HISTORY_LEN, maxlen=RMS_HISTORY_LEN),
        "freq_history":       deque([{}] * 50, maxlen=50),
        "flash_time":         None,
        "listening":          False,
        "last_detect_time":   0.0,
        "stream":             None,
        "peak_rms":           0.0,
        "noise_floor":        0.02,
        "calibrating":        False,
        "cal_samples":        [],
        "cal_start":          None,
        "session_start":      datetime.now(),
        "storm_trend":        "UNKNOWN",   # APPROACHING / MOVING_AWAY / STATIONARY
        "last_km":            None,
        "heatmap_data":       [],          # list of (minute_str, km)
        "auto_threshold":     0.25,
        "ai_summary":         "",
        "sound_alerts":       True,
        "rolling_rms":        deque([0.0] * 20, maxlen=20),  # smoothed
        # ── New features ─────────────────────────────────────────────────────
        "severity_score":     0,        # 0-100 composite
        "severity_history":   [],       # list of (ts, score)
        "decay_info":         None,     # storm decay prediction dict
        "session_saved":      False,    # flag for save confirmation
        "radar_frame":        0,        # polar radar animation frame counter
        "all_clear_start":    None,      # epoch when last strike occurred
        "tts_queue":          [],        # pending TTS messages
        "weather_data":       None,      # cached OpenWeatherMap response
        "weather_ts":         0.0,       # fetch timestamp
        "storm_vector":       None,      # {"bearing_deg": x, "speed_kmh": y}
        "arrival_eta":        None,      # minutes until storm reaches 3 km
        # ── Auto simulation ──────────────────────────────────────────────────
        "auto_sim":           False,
        "sim_phase":          "idle",
        "sim_step":           0,
        "sim_next_tick":      0.0,
        "sim_scenario":       "random",
        "sim_speed":          1.0,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_state()

# ─────────────────────────────────────────────────────────────────────────────
# Audio DSP helpers
# ─────────────────────────────────────────────────────────────────────────────
def butter_bandpass(low, high, fs, order=5):
    nyq = 0.5 * fs
    return butter(order, [low / nyq, high / nyq], btype="band")

def bandpass_filter(data, low, high, fs):
    b, a = butter_bandpass(low, high, fs)
    return lfilter(b, a, data)

def compute_spectral_centroid(samples, fs):
    """Rough spectral centroid of thunder band — gives texture info."""
    try:
        freqs, psd = welch(samples, fs=fs, nperseg=512)
        mask = (freqs >= THUNDER_LOW_HZ) & (freqs <= THUNDER_HIGH_HZ)
        psd_band = psd[mask]; freqs_band = freqs[mask]
        if psd_band.sum() == 0:
            return 0.0
        return float(np.sum(freqs_band * psd_band) / np.sum(psd_band))
    except Exception:
        return 0.0

def compute_distance(flash_time):
    if flash_time is None: return None
    dt = time.time() - flash_time
    if dt > FLASH_WINDOW_SEC: return None
    return round(dt * SPEED_SOUND_KMS, 2)

def classify(dist_km):
    if dist_km is None:   return "UNKNOWN"
    if dist_km <= 3:      return "DANGER"
    if dist_km <= 8:      return "WARNING"
    if dist_km <= 20:     return "WATCH"
    return "CLEAR"

def level_color(level):
    return {"DANGER":"#ff2d55","WARNING":"#ff8c00","WATCH":"#f5c518",
            "CLEAR":"#00e676","UNKNOWN":"#3a6070"}.get(level,"#fff")

def detect_storm_trend():
    evs = st.session_state.events
    if len(evs) < 2: return "UNKNOWN"
    recent = [e["_dist_km"] for e in evs[:4] if e.get("_dist_km")]
    if len(recent) < 2: return "UNKNOWN"
    diffs = [recent[i] - recent[i+1] for i in range(len(recent)-1)]
    avg_diff = sum(diffs) / len(diffs)
    if avg_diff > 0.5:   return "APPROACHING"
    if avg_diff < -0.5:  return "MOVING_AWAY"
    return "STATIONARY"

def generate_ai_summary():
    """Rule-based storm intelligence summary."""
    evs = st.session_state.events
    if not evs:
        return "No storm activity detected. System is monitoring."
    
    dists   = [e["_dist_km"] for e in evs if e.get("_dist_km")]
    amps    = [e["_amp"] for e in evs]
    danger  = sum(1 for e in evs if e["Level"] == "DANGER")
    trend   = st.session_state.storm_trend
    total   = len(evs)
    
    lines = []
    
    # Opening assessment
    if dists:
        min_d = min(dists)
        if min_d <= 3:
            lines.append(f"⚠ CRITICAL: Storm passed within {min_d} km. Extreme danger zone breached.")
        elif min_d <= 8:
            lines.append(f"⚡ HIGH RISK: Closest strike at {min_d} km. Immediate shelter recommended.")
        else:
            lines.append(f"🌩 MONITORING: Storm activity detected. Closest strike {min_d} km away.")
    
    # Trend analysis
    if trend == "APPROACHING":
        lines.append("📉 TREND: Storm is approaching your position. Seek shelter immediately.")
    elif trend == "MOVING_AWAY":
        lines.append("📈 TREND: Storm appears to be moving away. Continue monitoring.")
    elif trend == "STATIONARY":
        lines.append("📊 TREND: Storm is stationary or circling. Remain sheltered.")
    
    # Intensity
    if amps:
        avg_amp = sum(amps) / len(amps)
        if avg_amp > 0.7:
            lines.append(f"🔊 INTENSITY: Very high — avg amplitude {avg_amp:.2f}. Severe storm.")
        elif avg_amp > 0.4:
            lines.append(f"🔊 INTENSITY: Moderate — avg amplitude {avg_amp:.2f}. Active storm.")
        else:
            lines.append(f"🔊 INTENSITY: Low — avg amplitude {avg_amp:.2f}. Mild activity.")
    
    # Frequency
    rate = total / max(1, (datetime.now() - st.session_state.session_start).seconds / 60)
    if rate > 3:
        lines.append(f"⚡ FREQUENCY: {rate:.1f} strikes/min — extremely active storm cell.")
    elif rate > 1:
        lines.append(f"⚡ FREQUENCY: {rate:.1f} strikes/min — active conditions.")
    else:
        lines.append(f"⚡ FREQUENCY: {rate:.1f} strikes/min — intermittent activity.")
    
    if danger > 0:
        lines.append(f"🚨 {danger} DANGER-level event(s) recorded this session.")
    
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Storm Severity Score  (0-100 composite)
# ─────────────────────────────────────────────────────────────────────────────
def compute_severity(events: list, noise_floor: float) -> int:
    """
    0-100 score combining:
      - Proximity sub-score   (40 pts)  — based on closest strike
      - Intensity sub-score   (30 pts)  — peak amplitude normalised
      - Frequency sub-score   (20 pts)  — strikes/min
      - Trend sub-score       (10 pts)  — approaching adds, receding subtracts
    """
    if not events:
        return 0
    dists = [e["_dist_km"] for e in events if e.get("_dist_km")]
    amps  = [e["_amp"]     for e in events]
    # proximity (40)
    prox = 0
    if dists:
        d = min(dists)
        prox = 40 if d <= 1 else 35 if d <= 3 else 28 if d <= 8 else 18 if d <= 20 else 8
    # intensity (30)
    peak_amp = max(amps) if amps else 0
    inten = int(min(30, peak_amp * 32))
    # frequency (20)
    sess_s = max(1, (datetime.now() - st.session_state.session_start).seconds)
    rate   = len(events) / (sess_s / 60)
    freq   = int(min(20, rate * 5))
    # trend (10)
    trend = st.session_state.storm_trend
    tbonus = 10 if trend == "APPROACHING" else -5 if trend == "MOVING_AWAY" else 0
    score = max(0, min(100, prox + inten + freq + tbonus))
    return score

def severity_label(score: int) -> tuple:
    """Returns (label, color, emoji)."""
    if score >= 80: return "EXTREME",    "#ff2d55", "🔴"
    if score >= 60: return "SEVERE",     "#ff5500", "🟠"
    if score >= 40: return "MODERATE",   "#ff8c00", "🟡"
    if score >= 20: return "LOW",        "#f5c518", "🟡"
    return             "MINIMAL",    "#00e676", "🟢"


# ─────────────────────────────────────────────────────────────────────────────
# Arrival Time Predictor
# ─────────────────────────────────────────────────────────────────────────────
def predict_arrival(events: list) -> dict:
    """
    Fits a linear regression over the last N distance readings vs time.
    Projects when the storm will reach DANGER_KM (3 km).
    Returns dict with keys: eta_min, speed_kmh, r2, reliable
    """
    DANGER_KM = 3.0
    MIN_POINTS = 3
    timed = [(e["_ts"].timestamp(), e["_dist_km"])
             for e in events if e.get("_dist_km") and e.get("_ts")]
    timed = sorted(timed, key=lambda x: x[0])[-12:]   # last 12 readings
    if len(timed) < MIN_POINTS:
        return {"eta_min": None, "speed_kmh": None, "r2": None, "reliable": False}

    xs = np.array([t for t, _ in timed])
    ys = np.array([d for _, d in timed])
    xs_norm = xs - xs[0]                              # seconds from first reading

    # Weighted least-squares (recent points weighted higher)
    weights = np.linspace(0.4, 1.0, len(xs))
    x_mean = np.average(xs_norm, weights=weights)
    y_mean = np.average(ys,      weights=weights)
    ss_xy  = np.sum(weights * (xs_norm - x_mean) * (ys - y_mean))
    ss_xx  = np.sum(weights * (xs_norm - x_mean) ** 2)

    if abs(ss_xx) < 1e-9:
        return {"eta_min": None, "speed_kmh": None, "r2": None, "reliable": False}

    slope     = ss_xy / ss_xx                         # km/s (negative = approaching)
    intercept = y_mean - slope * x_mean
    y_pred    = slope * xs_norm + intercept
    ss_res    = np.sum((ys - y_pred) ** 2)
    ss_tot    = np.sum((ys - y_mean) ** 2)
    r2        = 1 - ss_res / ss_tot if ss_tot > 0 else 0

    speed_kmh = abs(slope) * 3600                     # km/h

    # ETA: solve intercept + slope * t_future = DANGER_KM
    if abs(slope) < 1e-9 or slope >= 0:               # not approaching
        return {"eta_min": None, "speed_kmh": round(speed_kmh, 1),
                "r2": round(r2, 2), "reliable": r2 > 0.6, "approaching": False}

    t_future   = (DANGER_KM - intercept) / slope      # seconds from xs[0]
    t_now      = time.time() - xs[0]
    secs_left  = t_future - t_now
    eta_min    = secs_left / 60

    return {
        "eta_min":    round(eta_min, 1) if eta_min > 0 else 0,
        "speed_kmh":  round(speed_kmh, 1),
        "r2":         round(r2, 2),
        "reliable":   r2 > 0.55 and eta_min > 0,
        "approaching": True,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Storm Vector (bearing + speed)
# ─────────────────────────────────────────────────────────────────────────────
def compute_storm_vector(events: list) -> dict | None:
    """
    Estimates storm speed from distance-over-time slope and assigns a
    pseudo-bearing from the azimuth pattern of recent amplitude changes.
    (True bearing needs multi-mic array; here we use a heuristic.)
    """
    timed = [(e["_ts"].timestamp(), e["_dist_km"], e["_amp"])
             for e in events if e.get("_dist_km") and e.get("_ts")]
    timed = sorted(timed)[-8:]
    if len(timed) < 3:
        return None

    xs = np.array([t for t, _, _ in timed])
    ds = np.array([d for _, d, _ in timed])
    # speed estimate via slope
    slope = np.polyfit(xs - xs[0], ds, 1)[0]
    speed_kmh = abs(slope) * 3600

    # pseudo-bearing: map amplitude-distance ratio to compass quadrant
    # (placeholder — real bearing needs directional microphones)
    avg_amp = np.mean([a for _,_,a in timed])
    bearing = (hash(f"{avg_amp:.2f}{round(speed_kmh)}") % 360)

    return {
        "bearing_deg": bearing,
        "speed_kmh":   round(speed_kmh, 1),
        "moving_away": slope > 0,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 30-Minute All-Clear Timer
# ─────────────────────────────────────────────────────────────────────────────
ALL_CLEAR_MINUTES = 30

def all_clear_status() -> dict:
    """
    Returns dict: safe (bool), minutes_remaining (float), pct_complete (float).
    Safe when 30 min have elapsed since the last strike event.
    """
    if not st.session_state.events:
        return {"safe": True, "minutes_remaining": 0, "pct": 100}
    last_ts = st.session_state.events[0]["_ts"]
    elapsed_s  = (datetime.now() - last_ts).total_seconds()
    remaining  = max(0, ALL_CLEAR_MINUTES * 60 - elapsed_s)
    pct        = min(100, elapsed_s / (ALL_CLEAR_MINUTES * 60) * 100)
    return {
        "safe":              remaining == 0,
        "minutes_remaining": round(remaining / 60, 1),
        "pct":               round(pct, 1),
        "elapsed_min":       round(elapsed_s / 60, 1),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Weather API (OpenWeatherMap — free tier, no key for basic calls)
# Falls back to a graceful "unavailable" state.
# ─────────────────────────────────────────────────────────────────────────────
OWM_CACHE_SECS = 300   # refresh every 5 min

@st.cache_data(ttl=OWM_CACHE_SECS, show_spinner=False)
def fetch_weather(lat: float, lon: float, api_key: str = "") -> dict | None:
    """
    Fetches current conditions from OpenWeatherMap.
    With no API key, tries the free endpoint (limited calls).
    Returns simplified dict or None on failure.
    """
    if not api_key:
        # OpenWeatherMap requires a key — return a placeholder
        return None
    try:
        url = (f"https://api.openweathermap.org/data/2.5/weather"
               f"?lat={lat}&lon={lon}&appid={api_key}&units=metric")
        req = urllib.request.Request(url, headers={"User-Agent": "ThunderDetectorPro/1.0"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            raw = json.loads(resp.read().decode())
        return {
            "temp_c":      round(raw["main"]["temp"], 1),
            "humidity":    raw["main"]["humidity"],
            "pressure":    raw["main"]["pressure"],
            "wind_speed":  round(raw["wind"]["speed"] * 3.6, 1),  # m/s → km/h
            "wind_deg":    raw["wind"].get("deg", 0),
            "description": raw["weather"][0]["description"].title(),
            "icon":        raw["weather"][0]["main"],
            "visibility":  raw.get("visibility", 0) // 1000,
            "clouds":      raw["clouds"]["all"],
        }
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Text-to-Speech — browser-side via JS speechSynthesis
# ─────────────────────────────────────────────────────────────────────────────
def tts_speak(text: str):
    """Inject JS to speak text via browser's Web Speech API."""
    safe = text.replace("'", "\'").replace('"', '\"').replace("\n", " ")
    js = f"""
    <script>
    (function() {{
        if (!window._ttsReady) {{
            window._ttsReady = true;
            window.speechSynthesis.cancel();
        }}
        var u = new SpeechSynthesisUtterance('{safe}');
        u.rate = 0.92;
        u.pitch = 0.85;
        u.volume = 1.0;
        window.speechSynthesis.speak(u);
    }})();
    </script>
    """
    st.components.v1.html(js, height=0)

def maybe_speak(level: str, dist_km, eta: dict):
    """Speak an alert only when level is significant and it changed."""
    if not st.session_state.get("tts_enabled", False):
        return
    last = st.session_state.get("last_tts_level", "")
    if level == last:
        return
    st.session_state["last_tts_level"] = level
    dist_str = f"{dist_km:.1f} kilometres" if dist_km else "unknown distance"
    if level == "DANGER":
        msg = f"DANGER! Storm is only {dist_str} away. Seek shelter immediately!"
    elif level == "WARNING":
        msg = f"Warning. Storm detected at {dist_str}. Move indoors now."
    elif level == "WATCH":
        msg = f"Storm watch. Activity at {dist_str}. Monitor the situation."
    elif level == "CLEAR":
        msg = "Storm is clearing. Conditions improving."
    else:
        return
    if eta.get("reliable") and eta.get("approaching") and level in ("DANGER","WARNING"):
        msg += f" Estimated arrival in {eta['eta_min']} minutes."
    tts_speak(msg)


# ─────────────────────────────────────────────────────────────────────────────
# Storm Decay Predictor
# ─────────────────────────────────────────────────────────────────────────────
def predict_decay(events: list) -> dict:
    """
    Fits exponential decay model to strike-rate-over-time.
    Estimates when strikes/min will drop below QUIET_THRESHOLD.
    Returns dict: eta_min, half_life_min, current_rate, reliable
    """
    QUIET_THRESHOLD = 0.3   # strikes/min considered "over"
    MIN_EVENTS = 5

    if len(events) < MIN_EVENTS:
        return {"reliable": False, "eta_min": None,
                "half_life_min": None, "current_rate": 0}

    # Build 1-min buckets
    now = datetime.now()
    bucket_rates = []
    for minutes_ago in range(10, 0, -1):
        t_start = now - timedelta(minutes=minutes_ago)
        t_end   = now - timedelta(minutes=minutes_ago - 1)
        count   = sum(1 for e in events
                      if e.get("_ts") and t_start <= e["_ts"] < t_end)
        bucket_rates.append(float(count))

    current_rate = bucket_rates[-1]
    nonzero = [(i, r) for i, r in enumerate(bucket_rates) if r > 0]
    if len(nonzero) < 3:
        return {"reliable": False, "eta_min": None,
                "half_life_min": None, "current_rate": current_rate}

    xs = np.array([i for i, _ in nonzero], dtype=float)
    ys = np.array([r for _, r in nonzero], dtype=float)

    # Fit log-linear (exponential decay): log(y) = a + b*x
    try:
        log_ys = np.log(ys + 1e-9)
        coeffs = np.polyfit(xs, log_ys, 1)
        b, a = coeffs
        if b >= 0:  # not decaying
            return {"reliable": False, "eta_min": None,
                    "half_life_min": None, "current_rate": current_rate,
                    "growing": True}
        half_life_min = abs(math.log(2) / b)
        # Solve for when rate drops to QUIET_THRESHOLD
        t_quiet = (math.log(QUIET_THRESHOLD) - a) / b
        eta_min = max(0, t_quiet - len(bucket_rates))
        return {
            "reliable":      True,
            "eta_min":       round(eta_min, 1),
            "half_life_min": round(half_life_min, 1),
            "current_rate":  round(current_rate, 2),
            "growing":       False,
        }
    except Exception:
        return {"reliable": False, "eta_min": None,
                "half_life_min": None, "current_rate": current_rate}


# ─────────────────────────────────────────────────────────────────────────────
# Session Save / Load helpers
# ─────────────────────────────────────────────────────────────────────────────
def session_to_json() -> str:
    """Serialise current session to a JSON string."""
    payload = {
        "version":      "1.0",
        "exported_at":  datetime.now().isoformat(),
        "session_start": st.session_state.session_start.isoformat(),
        "events": [
            {k: (v.isoformat() if isinstance(v, datetime) else v)
             for k, v in e.items()}
            for e in st.session_state.events
        ],
        "heatmap_data": st.session_state.heatmap_data,
        "peak_rms":     st.session_state.peak_rms,
    }
    return json.dumps(payload, indent=2)

def session_from_json(raw: str) -> tuple:
    """Load a session from JSON string. Returns (ok: bool, message: str)."""
    try:
        data = json.loads(raw)
        if data.get("version") != "1.0":
            return False, "Incompatible version"
        events = []
        for e in data.get("events", []):
            if "_ts" in e and isinstance(e["_ts"], str):
                e["_ts"] = datetime.fromisoformat(e["_ts"])
            events.append(e)
        st.session_state.events       = events
        st.session_state.heatmap_data = data.get("heatmap_data", [])
        st.session_state.peak_rms     = data.get("peak_rms", 0.0)
        st.session_state.session_start = datetime.fromisoformat(
            data.get("session_start", datetime.now().isoformat()))
        st.session_state.storm_trend   = detect_storm_trend()
        st.session_state.severity_score = compute_severity(
            st.session_state.events, st.session_state.noise_floor)
        st.session_state.ai_summary    = generate_ai_summary()
        return True, f"Loaded {len(events)} events"
    except Exception as ex:
        return False, str(ex)


# ─────────────────────────────────────────────────────────────────────────────
# Siren — Web Audio API via JS
# ─────────────────────────────────────────────────────────────────────────────
def play_siren(level: str):
    """Play a short tone pattern matching the alert level via Web Audio API."""
    if not st.session_state.get("siren_enabled", False):
        return
    last_siren = st.session_state.get("last_siren_level", "")
    if level == last_siren:
        return
    st.session_state["last_siren_level"] = level

    patterns = {
        "DANGER":  [(880,0.15),(0,0.05),(880,0.15),(0,0.05),(880,0.3)],
        "WARNING": [(660,0.2),(0,0.1),(660,0.2)],
        "WATCH":   [(440,0.25)],
        "CLEAR":   [(330,0.1),(440,0.2)],
    }
    tones = patterns.get(level, [])
    if not tones:
        return

    js_parts = []
    t_offset = 0.0
    for freq, dur in tones:
        if freq == 0:
            t_offset += dur
            continue
        js_parts.append(f"""
        (function(){{
            var o = ctx.createOscillator();
            var g = ctx.createGain();
            o.connect(g); g.connect(ctx.destination);
            o.type = 'sine';
            o.frequency.value = {freq};
            g.gain.setValueAtTime(0.35, ctx.currentTime + {t_offset:.2f});
            g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + {t_offset+dur:.2f});
            o.start(ctx.currentTime + {t_offset:.2f});
            o.stop(ctx.currentTime + {t_offset+dur+0.05:.2f});
        }})();""")
        t_offset += dur + 0.02

    js = f"""<script>
    (function(){{
        try {{
            var ctx = new (window.AudioContext || window.webkitAudioContext)();
            {''.join(js_parts)}
        }} catch(e) {{ console.warn('Audio unavailable:', e); }}
    }})();
    </script>"""
    st.components.v1.html(js, height=0)


# ─────────────────────────────────────────────────────────────────────────────
# Rain Radar — RainViewer API (free, no key needed)
# ─────────────────────────────────────────────────────────────────────────────
RAINVIEWER_API = "https://api.rainviewer.com/public/weather-maps.json"

@st.cache_data(ttl=120, show_spinner=False)
def fetch_rainviewer_frames() -> list:
    """
    Fetches the latest radar frame URLs from RainViewer.
    Returns list of dicts: {time, path, tile_url_template}
    """
    try:
        req = urllib.request.Request(RAINVIEWER_API,
                                     headers={"User-Agent": "ThunderDetectorPro/1.0"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode())
        frames = data.get("radar", {}).get("past", [])
        host   = data.get("host", "https://tilecache.rainviewer.com")
        result = []
        for f in frames[-6:]:           # last 6 frames (~30 min)
            path = f.get("path", "")
            result.append({
                "time":  f.get("time", 0),
                "path":  path,
                "tile_url": f"{host}{path}/256/{{z}}/{{x}}/{{y}}/2/1_1.png",
            })
        return result
    except Exception:
        return []

# ─────────────────────────────────────────────────────────────────────────────
# Audio pipeline
# ─────────────────────────────────────────────────────────────────────────────
def audio_callback(indata, frames, time_info, status):
    # RUNS IN C THREAD — never touch st.session_state here!
    _AUDIO_QUEUE.put(indata.copy())

def process_audio_block(threshold):
    processed = 0
    while not _AUDIO_QUEUE.empty() and processed < 8:
        data = _AUDIO_QUEUE.get_nowait()
        samples = data[:, 0] if data.ndim > 1 else data.flatten()
        samples_f32 = samples.astype(np.float32)

        # Bandpass filter
        filtered = bandpass_filter(samples_f32, THUNDER_LOW_HZ, THUNDER_HIGH_HZ, SAMPLE_RATE)
        raw_rms   = float(np.sqrt(np.mean(filtered ** 2)))

        # Update noise floor (EMA)
        st.session_state.noise_floor = (
            NOISE_SMOOTHING * st.session_state.noise_floor +
            (1 - NOISE_SMOOTHING) * raw_rms
        )

        # Noise-suppressed RMS
        rms = max(0.0, raw_rms - st.session_state.noise_floor * 0.5)

        # Rolling average smoothing
        st.session_state.rolling_rms.append(rms)
        smoothed = float(np.mean(list(st.session_state.rolling_rms)))

        st.session_state.rms_history.append(smoothed)
        if smoothed > st.session_state.peak_rms:
            st.session_state.peak_rms = smoothed

        # Calibration mode
        if st.session_state.calibrating:
            st.session_state.cal_samples.append(raw_rms)
            elapsed = time.time() - (st.session_state.cal_start or time.time())
            if elapsed >= CALIBRATION_SECS:
                if st.session_state.cal_samples:
                    noise = float(np.percentile(st.session_state.cal_samples, 90))
                    st.session_state.auto_threshold = round(noise * 3.5, 3)
                    st.session_state.noise_floor = noise
                st.session_state.calibrating = False
                st.session_state.cal_samples = []
            processed += 1
            continue

        # Spectral centroid
        centroid = compute_spectral_centroid(samples_f32, SAMPLE_RATE)
        st.session_state.freq_history.append({"centroid": centroid, "rms": smoothed})

        # Thunder detection
        now = time.time()
        if smoothed >= threshold and (now - st.session_state.last_detect_time) > float(st.session_state.get("cooldown", 3.0)):
            st.session_state.last_detect_time = now
            dist = compute_distance(st.session_state.flash_time)
            st.session_state.flash_time = None
            add_event(smoothed, dist, centroid)

        processed += 1

def add_event(amp, dist_km, centroid=0.0):
    level = classify(dist_km)
    ts    = datetime.now()
    ev = {
        "Time":      ts.strftime("%H:%M:%S"),
        "Amplitude": round(amp, 4),
        "Distance":  f"{dist_km} km" if dist_km else "—",
        "Level":     level,
        "Centroid":  round(centroid, 1),
        "_dist_km":  dist_km,
        "_amp":      amp,
        "_ts":       ts,
    }
    st.session_state.events.insert(0, ev)

    # Heatmap data
    minute_str = ts.strftime("%H:%M")
    st.session_state.heatmap_data.append((minute_str, dist_km or 0, amp))

    # Storm trend
    st.session_state.storm_trend = detect_storm_trend()
    st.session_state.last_km = dist_km

    # Severity score + history
    score = compute_severity(st.session_state.events, st.session_state.noise_floor)
    st.session_state.severity_score = score
    st.session_state.severity_history.append((datetime.now(), score))
    # Keep last 200 data points
    if len(st.session_state.severity_history) > 200:
        st.session_state.severity_history = st.session_state.severity_history[-200:]
    # Storm decay
    st.session_state.decay_info = predict_decay(st.session_state.events)

    # Storm vector
    st.session_state.storm_vector = compute_storm_vector(st.session_state.events)

    # AI summary (regenerate)
    st.session_state.ai_summary = generate_ai_summary()

    # TTS + siren alerts
    eta = predict_arrival(st.session_state.events)
    maybe_speak(classify(dist_km), dist_km, eta)
    play_siren(classify(dist_km))

# ─────────────────────────────────────────────────────────────────────────────
# PDF Report generator
# ─────────────────────────────────────────────────────────────────────────────
def generate_pdf_report():
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    title_style  = ParagraphStyle("t", parent=styles["Heading1"], fontSize=18,
                                  textColor=rl_colors.HexColor("#f5c518"), spaceAfter=6)
    sub_style    = ParagraphStyle("s", parent=styles["Normal"], fontSize=9,
                                  textColor=rl_colors.HexColor("#888888"), spaceAfter=12)
    body_style   = ParagraphStyle("b", parent=styles["Normal"], fontSize=10,
                                  textColor=rl_colors.HexColor("#cccccc"), spaceAfter=6)
    section_style = ParagraphStyle("sec", parent=styles["Heading2"], fontSize=12,
                                   textColor=rl_colors.HexColor("#f5c518"), spaceBefore=12, spaceAfter=6)

    evs   = st.session_state.events
    dists = [e["_dist_km"] for e in evs if e.get("_dist_km")]

    story = [
        Paragraph("⚡ THUNDER DETECTOR PRO", title_style),
        Paragraph(f"Storm Report — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", sub_style),
        Spacer(1, 0.4*cm),
        Paragraph("EXECUTIVE SUMMARY", section_style),
        Paragraph(f"Total strikes detected: <b>{len(evs)}</b>", body_style),
        Paragraph(f"Session started: <b>{st.session_state.session_start.strftime('%H:%M:%S')}</b>", body_style),
        Paragraph(f"Closest strike: <b>{min(dists):.1f} km</b>" if dists else "Closest strike: —", body_style),
        Paragraph(f"Peak amplitude: <b>{st.session_state.peak_rms:.4f}</b>", body_style),
        Paragraph(f"Storm trend: <b>{st.session_state.storm_trend}</b>", body_style),
        Spacer(1, 0.3*cm),
        Paragraph("AI ANALYSIS", section_style),
    ]

    for line in st.session_state.ai_summary.split("\n"):
        story.append(Paragraph(line, body_style))

    if evs:
        story += [Spacer(1, 0.4*cm), Paragraph("STRIKE LOG", section_style)]
        table_data = [["Time", "Level", "Distance", "Amplitude"]]
        for e in evs[:50]:
            table_data.append([e["Time"], e["Level"], e["Distance"], str(e["Amplitude"])])

        tbl = Table(table_data, colWidths=[3*cm, 3*cm, 4*cm, 4*cm])
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), rl_colors.HexColor("#1a2e40")),
            ("TEXTCOLOR",  (0,0), (-1,0), rl_colors.HexColor("#f5c518")),
            ("FONTNAME",   (0,0), (-1,-1), "Helvetica"),
            ("FONTSIZE",   (0,0), (-1,-1), 8),
            ("TEXTCOLOR",  (0,1), (-1,-1), rl_colors.HexColor("#cccccc")),
            ("ROWBACKGROUNDS", (0,1), (-1,-1),
             [rl_colors.HexColor("#0a1825"), rl_colors.HexColor("#0d1f2e")]),
            ("GRID", (0,0), (-1,-1), 0.5, rl_colors.HexColor("#1e3a50")),
            ("TOPPADDING",    (0,0), (-1,-1), 4),
            ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ]))
        story.append(tbl)

    doc.build(story)
    buf.seek(0)
    return buf.read()

# ─────────────────────────────────────────────────────────────────────────────
# Live Storm Map — Blitzortung API + simulated fallback
# ─────────────────────────────────────────────────────────────────────────────

BLITZORTUNG_URLS = [
    "https://data.blitzortung.org/Data/Protected/Strokes/latest.json",
    "https://map.blitzortung.org/GEO/strikes/latest.json",
]

@st.cache_data(ttl=30, show_spinner=False)
def fetch_blitzortung() -> tuple:
    """Try Blitzortung public feeds. Returns (strikes_list, source_label)."""
    for url in BLITZORTUNG_URLS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ThunderDetectorPro/1.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                raw = json.loads(resp.read().decode())
            if isinstance(raw, list):
                strikes = raw
            elif isinstance(raw, dict):
                strikes = raw.get("r", raw.get("strokes", []))
            else:
                continue
            normalised = []
            for s in strikes:
                lat = s.get("lat", s.get("y"))
                lon = s.get("lon", s.get("x"))
                ts  = s.get("time", s.get("t", 0))
                if lat is not None and lon is not None:
                    normalised.append({"lat": float(lat), "lon": float(lon), "time": ts})
            if normalised:
                return normalised, "LIVE — blitzortung.org"
        except Exception:
            continue
    return [], "OFFLINE"


def generate_simulated_strikes(center_lat: float, center_lon: float, n: int = 80) -> list:
    """Generate n simulated lightning strikes around center_lat/lon."""
    now_ms = int(time.time() * 1000)
    strikes = []
    for _ in range(n):
        angle     = random.uniform(0, 2 * math.pi)
        radius_km = random.expovariate(1 / 30)
        lat = center_lat + (radius_km / 111.0) * math.cos(angle)
        lon = center_lon + (radius_km / (111.0 * math.cos(math.radians(center_lat)))) * math.sin(angle)
        age_ms    = random.randint(0, 120_000)
        intensity = max(0.1, 1.0 - radius_km / 80)
        strikes.append({
            "lat": round(lat, 5), "lon": round(lon, 5),
            "time": now_ms - age_ms,
            "intensity": round(intensity, 2), "simulated": True,
        })
    return strikes


def build_storm_map(strikes: list, center_lat: float, center_lon: float,
                    user_events: list, source_label: str) -> go.Figure:
    """Build Plotly geo map: live/simulated strikes + user detections + range rings."""
    now_ms = int(time.time() * 1000)
    fig = go.Figure()

    # Strike cloud
    if strikes:
        lats   = [s["lat"] for s in strikes]
        lons   = [s["lon"] for s in strikes]
        ages   = [(now_ms - s.get("time", now_ms)) / 1000 for s in strikes]
        colors = [f"rgba({max(0,int(245-a*1.8))},{max(0,int(197-a*1.5))},24,{max(0.12,1-a/120)})"
                  for a in ages]
        sizes  = [max(3, 11 - a / 14) for a in ages]
        texts  = [f"{int(a)}s ago{'  [sim]' if s.get('simulated') else ''}"
                  for a, s in zip(ages, strikes)]
        fig.add_trace(go.Scattergeo(
            lat=lats, lon=lons, mode="markers",
            marker=dict(color=colors, size=sizes, opacity=0.9, symbol="circle"),
            text=texts,
            hovertemplate="<b>Strike</b><br>%{text}<br>%{lat:.3f}°N %{lon:.3f}°E<extra></extra>",
            name=f"Lightning ({source_label})",
        ))

    # Range rings
    ring_specs = [(3,"#ff2d55"),(8,"#ff8c00"),(20,"#f5c518"),(40,"#2a5570")]
    for km, color in ring_specs:
        rlats, rlons = [], []
        for deg in range(0, 361, 4):
            rad  = math.radians(deg)
            rlats.append(center_lat + (km/111.0)*math.cos(rad))
            rlons.append(center_lon + (km/(111.0*math.cos(math.radians(center_lat))))*math.sin(rad))
        fig.add_trace(go.Scattergeo(
            lat=rlats, lon=rlons, mode="lines",
            line=dict(color=color, width=0.9, dash="dot"),
            hoverinfo="skip", showlegend=False,
        ))
        fig.add_trace(go.Scattergeo(
            lat=[center_lat + km/111.0], lon=[center_lon],
            mode="text", text=[f"{km}km"],
            textfont=dict(color=color, size=8, family="Share Tech Mono"),
            hoverinfo="skip", showlegend=False,
        ))

    # User-detected events (starred, direction randomised since bearing unknown)
    for ev in user_events:
        if not ev.get("_dist_km"):
            continue
        angle  = random.uniform(0, 2*math.pi)
        km     = ev["_dist_km"]
        ev_lat = center_lat + (km/111.0)*math.cos(angle)
        ev_lon = center_lon + (km/(111.0*math.cos(math.radians(center_lat))))*math.sin(angle)
        clr    = {"DANGER":"#ff2d55","WARNING":"#ff8c00",
                  "WATCH":"#f5c518","CLEAR":"#00e676"}.get(ev["Level"],"#fff")
        fig.add_trace(go.Scattergeo(
            lat=[ev_lat], lon=[ev_lon],
            mode="markers+text",
            marker=dict(color=clr, size=15, symbol="star",
                        line=dict(color="#040d12", width=1)),
            text=[ev["Level"]],
            textposition="top center",
            textfont=dict(color=clr, size=8, family="Share Tech Mono"),
            hovertemplate=(f"<b>⚡ Detected</b><br>Level: {ev['Level']}<br>"
                           f"Dist: {ev['Distance']}<br>Amp: {ev['Amplitude']}<extra></extra>"),
            showlegend=False,
        ))

    # User location
    fig.add_trace(go.Scattergeo(
        lat=[center_lat], lon=[center_lon],
        mode="markers+text",
        marker=dict(color="#00e5ff", size=18, symbol="diamond",
                    line=dict(color="#fff", width=2)),
        text=["YOU"],
        textposition="top right",
        textfont=dict(color="#00e5ff", size=10, family="Orbitron"),
        hovertemplate="<b>Your Location</b><extra></extra>",
        name="Your position",
    ))

    fig.update_layout(
        height=520, margin=dict(l=0,r=0,t=0,b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        showlegend=True,
        legend=dict(
            font=dict(color="#7aabb8", size=9, family="Share Tech Mono"),
            bgcolor="rgba(5,14,23,0.88)", bordercolor="#1e3a50", borderwidth=1,
            x=0.01, y=0.99,
        ),
        geo=dict(
            projection_type="natural earth",
            showland=True,      landcolor="#0a1520",
            showocean=True,     oceancolor="#040d12",
            showlakes=True,     lakecolor="#071020",
            showcountries=True, countrycolor="#1e3a50",
            showcoastlines=True,coastlinecolor="#1e3a50", coastlinewidth=0.7,
            bgcolor="rgba(0,0,0,0)",
            center=dict(lat=center_lat, lon=center_lon),
            projection_scale=8,
        ),
        annotations=[dict(
            text=(f"SOURCE: {source_label}  ·  {len(strikes)} strikes  ·  "
                  "rings: 3 / 8 / 20 / 40 km  ·  ⭐ = your detections"),
            xref="paper", yref="paper", x=0.5, y=0.005,
            xanchor="center", yanchor="bottom", showarrow=False,
            font=dict(color="#2a5570", size=8, family="Share Tech Mono"),
        )],
    )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div style='font-family:"Orbitron",monospace;font-weight:900;font-size:1.3rem;
                letter-spacing:3px;background:linear-gradient(135deg,#f5c518,#ff8c00);
                -webkit-background-clip:text;-webkit-text-fill-color:transparent;
                margin-bottom:2px'>⚡ CONTROL PANEL</div>
    """, unsafe_allow_html=True)
    st.divider()

    st.markdown("**DETECTION**")
    use_auto = st.checkbox("Use auto-calibrated threshold", value=False)
    if use_auto:
        threshold = st.session_state.auto_threshold
        st.markdown(f"<span style='color:#f5c518;font-size:0.7rem'>Auto: {threshold}</span>",
                    unsafe_allow_html=True)
    else:
        threshold = st.slider("Threshold (RMS)", 0.01, 1.0, 0.25, 0.01)

    cooldown = st.slider("Cooldown (s)", 0.5, 15.0, 3.0, 0.5)
    st.session_state["cooldown"] = cooldown

    st.divider()
    st.markdown("**AUTO-CALIBRATE**")
    st.caption("Records ambient noise for 5s and sets threshold automatically.")
    if not st.session_state.calibrating:
        if st.button("🎛 START CALIBRATION", use_container_width=True):
            if not st.session_state.listening:
                st.warning("Start mic first!")
            else:
                st.session_state.calibrating = True
                st.session_state.cal_start   = time.time()
                st.session_state.cal_samples = []
                st.rerun()
    else:
        elapsed = time.time() - (st.session_state.cal_start or time.time())
        pct = min(100, int(elapsed / CALIBRATION_SECS * 100))
        st.markdown(f"""
        <div style='font-family:"Share Tech Mono",monospace;font-size:0.65rem;color:#f5c518;margin-bottom:4px'>
            CALIBRATING... {pct}%</div>
        <div class='cal-bar-wrap'><div class='cal-bar-fill' style='width:{pct}%'></div></div>
        """, unsafe_allow_html=True)

    st.divider()
    st.markdown("**AUTO SIMULATION**")
    st.caption("Runs a realistic storm scenario automatically — no input needed.")

    sim_scenario = st.selectbox("Storm scenario", [
        "random",
        "approaching storm",
        "passing storm",
        "distant rumble",
        "severe outbreak",
    ], index=0)
    st.session_state.sim_scenario = sim_scenario

    sim_speed = st.select_slider("Speed", options=[0.5, 1.0, 2.0, 4.0],
                                  value=st.session_state.sim_speed,
                                  format_func=lambda x: f"{x}x")
    st.session_state.sim_speed = sim_speed

    if not st.session_state.auto_sim:
        if st.button("▶ START AUTO SIM", use_container_width=True):
            st.session_state.auto_sim      = True
            st.session_state.sim_phase     = "running"
            st.session_state.sim_step      = 0
            st.session_state.sim_next_tick = time.time()
            st.rerun()
    else:
        st.markdown("""<div class='status-live' style='margin-bottom:6px'>
            <div class='status-dot'></div>AUTO SIM RUNNING</div>""",
            unsafe_allow_html=True)
        if st.button("⏹ STOP AUTO SIM", use_container_width=True):
            st.session_state.auto_sim  = False
            st.session_state.sim_phase = "idle"
            st.rerun()

    st.divider()
    st.markdown("**ALERTS & TTS**")
    tts_on = st.checkbox("🔊 Text-to-Speech announcer", value=st.session_state.get("tts_enabled", False))
    st.session_state["tts_enabled"] = tts_on
    if tts_on:
        st.caption("Browser will speak alerts aloud (uses Web Speech API)")
    siren_on = st.checkbox("🚨 Siren sound on DANGER/WARNING",
                            value=st.session_state.get("siren_enabled", False))
    st.session_state["siren_enabled"] = siren_on
    if siren_on:
        st.caption("Uses Web Audio API — no install needed")
    st.session_state.sound_alerts = st.checkbox("Visual alert banners", value=st.session_state.sound_alerts)

    st.divider()
    st.markdown("**WEATHER API**")
    st.caption("OpenWeatherMap key for live conditions (free at openweathermap.org)")
    owm_key = st.text_input("OWM API Key", value=st.session_state.get("owm_key",""),
                             type="password", placeholder="paste key here…")
    st.session_state["owm_key"] = owm_key
    if owm_key:
        st.success("Key saved — weather will load on Storm Map tab")
    else:
        st.caption("Leave blank to skip weather overlay")

    st.divider()
    if st.button("🗑 CLEAR ALL DATA", use_container_width=True):
        st.session_state.events       = []
        st.session_state.heatmap_data = []
        st.session_state.peak_rms     = 0.0
        st.session_state.storm_trend  = "UNKNOWN"
        st.session_state.ai_summary   = ""
        st.session_state.session_start = datetime.now()
        st.rerun()

    st.divider()
    # Noise floor display
    st.markdown(f"""
    <div class='info-card'>
    <b>NOISE FLOOR</b><br>
    <span class='val'>{st.session_state.noise_floor:.4f} RMS</span><br>
    <b>AUTO THRESHOLD</b><br>
    <span class='val'>{st.session_state.auto_threshold}</span><br>
    <b>SESSION</b><br>
    <span class='val'>{str(datetime.now() - st.session_state.session_start).split('.')[0]}</span>
    </div>
    """, unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# Process live audio
# ─────────────────────────────────────────────────────────────────────────────
if st.session_state.listening and AUDIO_AVAILABLE:
    process_audio_block(threshold)

# ─────────────────────────────────────────────────────────────────────────────
# Header
# ─────────────────────────────────────────────────────────────────────────────
hcol1, hcol2, hcol3 = st.columns([4, 1.5, 1.5])

with hcol1:
    st.markdown("""
    <p class='pro-title'>⚡ THUNDER DETECTOR PRO</p>
    <p class='pro-sub'>REAL-TIME STORM INTELLIGENCE SYSTEM — STREAMLIT EDITION</p>
    """, unsafe_allow_html=True)

with hcol2:
    st.markdown("<br>", unsafe_allow_html=True)
    trend = st.session_state.storm_trend
    trend_html = {
        "APPROACHING":  "<span class='trend-approaching'>▼ APPROACHING</span>",
        "MOVING_AWAY":  "<span class='trend-moving-away'>▲ MOVING AWAY</span>",
        "STATIONARY":   "<span class='trend-stationary'>● STATIONARY</span>",
        "UNKNOWN":      "<span style='color:#2a5570'>— UNKNOWN</span>",
    }.get(trend, "")
    st.markdown(f"""
    <div class='info-card' style='text-align:center'>
        <div style='font-size:0.5rem;letter-spacing:3px;color:#1e4060;margin-bottom:4px'>STORM TREND</div>
        <div style='font-size:0.85rem'>{trend_html}</div>
    </div>
    """, unsafe_allow_html=True)

with hcol3:
    st.markdown("<br>", unsafe_allow_html=True)
    if AUDIO_AVAILABLE:
        if not st.session_state.listening:
            if st.button("🎙 START MIC", use_container_width=True):
                try:
                    stream = sd.InputStream(
                        samplerate=SAMPLE_RATE, blocksize=BLOCK_SIZE,
                        channels=CHANNELS, callback=audio_callback,
                    )
                    stream.start()
                    st.session_state.stream   = stream
                    st.session_state.listening = True
                    st.rerun()
                except Exception as e:
                    st.error(f"Mic error: {e}")
        else:
            st.markdown("<div class='status-live'><div class='status-dot'></div>MIC LIVE</div>",
                        unsafe_allow_html=True)
            if st.button("⏹ STOP MIC", use_container_width=True):
                if st.session_state.stream:
                    st.session_state.stream.stop()
                    st.session_state.stream.close()
                    st.session_state.stream = None
                st.session_state.listening = False
                st.rerun()
    else:
        st.markdown("<div class='status-idle'>SIM MODE</div>", unsafe_allow_html=True)

st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# Alert banner
# ─────────────────────────────────────────────────────────────────────────────
evs = st.session_state.events
if evs:
    latest = evs[0]
    level  = latest["Level"]
    dist   = latest["Distance"]
    approaching = st.session_state.storm_trend == "APPROACHING"
    cls_extra   = " approaching" if approaching and level in ("DANGER","WARNING") else ""
    messages = {
        "DANGER":  f"⚠ DANGER — Storm {dist} away! SEEK SHELTER IMMEDIATELY.",
        "WARNING": f"⚡ WARNING — Storm {dist} away. Move indoors now.",
        "WATCH":   f"🌩 WATCH — Storm {dist} away. Monitor conditions closely.",
        "CLEAR":   f"✓ CLEAR — Storm has moved to {dist}. Conditions improving.",
    }
    msg = messages.get(level, "")
    if msg:
        cls = {"DANGER":"alert-danger","WARNING":"alert-warning",
               "WATCH":"alert-watch","CLEAR":"alert-clear"}.get(level,"")
        st.markdown(f'<div class="alert-box {cls}{cls_extra}">🔊 {msg}</div>',
                    unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# Stat cards row
# ─────────────────────────────────────────────────────────────────────────────
dists = [e["_dist_km"] for e in evs if e.get("_dist_km")]
amps  = [e["_amp"] for e in evs]
sess_secs = max(1, (datetime.now() - st.session_state.session_start).seconds)

# Derived values needed for new widgets
_severity  = st.session_state.severity_score
_sev_label, _sev_color, _sev_emoji = severity_label(_severity)
_eta       = predict_arrival(evs)
_ac        = all_clear_status()
_vector    = st.session_state.storm_vector

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("⚡ STRIKES",      len(evs))
c2.metric("📏 CLOSEST",      f"{min(dists):.1f} km" if dists else "—")
c3.metric("📊 PEAK AMP",     f"{st.session_state.peak_rms:.3f}")
c4.metric("🔴 DANGER",       sum(1 for e in evs if e["Level"] == "DANGER"))
c5.metric("⏱ RATE",          f"{len(evs)/(sess_secs/60):.1f}/min")
c6.metric("🔇 NOISE FLOOR",  f"{st.session_state.noise_floor:.4f}")

# ── NEW: Severity + ETA + All-Clear row ──────────────────────────────────────
sc1, sc2, sc3, sc4 = st.columns([1, 1.4, 1.4, 1.2])

with sc1:
    st.markdown(f"""
    <div style='background:#0a1825;border:1px solid #1e3a50;border-top:2px solid {_sev_color};
                border-radius:4px;padding:12px 16px;text-align:center'>
      <div style='font-family:"Share Tech Mono",monospace;font-size:0.5rem;
                  letter-spacing:3px;color:#2a5570'>SEVERITY SCORE</div>
      <div style='font-family:"Orbitron",monospace;font-size:2rem;font-weight:700;
                  color:{_sev_color};line-height:1.1'>{_severity}</div>
      <div style='font-family:"Share Tech Mono",monospace;font-size:0.6rem;
                  color:{_sev_color}'>{_sev_emoji} {_sev_label}</div>
    </div>
    """, unsafe_allow_html=True)

with sc2:
    if _eta.get("reliable") and _eta.get("approaching"):
        eta_color = "#ff2d55" if _eta["eta_min"] < 5 else "#ff8c00" if _eta["eta_min"] < 15 else "#f5c518"
        eta_text  = f"{_eta['eta_min']} min"
        eta_sub   = f"at {_eta['speed_kmh']} km/h  ·  R²={_eta['r2']}"
    elif _eta.get("speed_kmh") and not _eta.get("approaching"):
        eta_color, eta_text, eta_sub = "#00e676", "RECEDING", f"{_eta['speed_kmh']} km/h away"
    else:
        eta_color, eta_text, eta_sub = "#2a5570", "—", "need ≥3 events"
    st.markdown(f"""
    <div style='background:#0a1825;border:1px solid #1e3a50;border-top:2px solid {eta_color};
                border-radius:4px;padding:12px 16px;text-align:center'>
      <div style='font-family:"Share Tech Mono",monospace;font-size:0.5rem;
                  letter-spacing:3px;color:#2a5570'>ETA TO DANGER (3km)</div>
      <div style='font-family:"Orbitron",monospace;font-size:1.6rem;font-weight:700;
                  color:{eta_color};line-height:1.2'>{eta_text}</div>
      <div style='font-family:"Share Tech Mono",monospace;font-size:0.55rem;
                  color:#2a5570'>{eta_sub}</div>
    </div>
    """, unsafe_allow_html=True)

with sc3:
    ac_color = "#00e676" if _ac["safe"] else "#ff8c00"
    ac_text  = "ALL CLEAR ✓" if _ac["safe"] else f"{_ac['minutes_remaining']} min left"
    ac_sub   = "safe to go outside" if _ac["safe"] else f"{_ac['elapsed_min']} min since last strike"
    ac_pct   = _ac["pct"]
    st.markdown(f"""
    <div style='background:#0a1825;border:1px solid #1e3a50;border-top:2px solid {ac_color};
                border-radius:4px;padding:12px 16px'>
      <div style='font-family:"Share Tech Mono",monospace;font-size:0.5rem;
                  letter-spacing:3px;color:#2a5570;margin-bottom:4px'>30-MIN ALL-CLEAR</div>
      <div style='font-family:"Orbitron",monospace;font-size:1.1rem;font-weight:700;
                  color:{ac_color}'>{ac_text}</div>
      <div style='background:#070e16;border-radius:3px;height:6px;margin:6px 0;overflow:hidden'>
        <div style='height:100%;width:{ac_pct}%;background:{ac_color};
                    transition:width 1s;border-radius:3px'></div>
      </div>
      <div style='font-family:"Share Tech Mono",monospace;font-size:0.55rem;
                  color:#2a5570'>{ac_sub}</div>
    </div>
    """, unsafe_allow_html=True)

with sc4:
    if _vector:
        v_color = "#ff2d55" if not _vector["moving_away"] else "#00e676"
        bearing = _vector["bearing_deg"]
        spd     = _vector["speed_kmh"]
        # Cardinal direction
        dirs = ["N","NE","E","SE","S","SW","W","NW"]
        card = dirs[int((bearing + 22.5) / 45) % 8]
        arrow = "↓↗↑↙←↘→↖"[int(bearing/45)%8]  # approximate compass arrow
        dir_label = "APPROACHING" if not _vector["moving_away"] else "RECEDING"
        st.markdown(f"""
        <div style='background:#0a1825;border:1px solid #1e3a50;border-top:2px solid {v_color};
                    border-radius:4px;padding:12px 16px;text-align:center'>
          <div style='font-family:"Share Tech Mono",monospace;font-size:0.5rem;
                      letter-spacing:3px;color:#2a5570'>STORM VECTOR</div>
          <div style='font-size:1.8rem;line-height:1.1;color:{v_color}'>{arrow}</div>
          <div style='font-family:"Orbitron",monospace;font-size:0.85rem;
                      font-weight:700;color:{v_color}'>{spd} km/h {card}</div>
          <div style='font-family:"Share Tech Mono",monospace;font-size:0.55rem;
                      color:#2a5570'>{dir_label}</div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown("""
        <div style='background:#0a1825;border:1px solid #1e3a50;border-top:2px solid #1e3a50;
                    border-radius:4px;padding:12px 16px;text-align:center'>
          <div style='font-family:"Share Tech Mono",monospace;font-size:0.5rem;
                      letter-spacing:3px;color:#2a5570'>STORM VECTOR</div>
          <div style='font-family:"Orbitron",monospace;font-size:1.4rem;color:#1e3a50'>—</div>
          <div style='font-family:"Share Tech Mono",monospace;font-size:0.55rem;
                      color:#1e3a50'>need ≥3 events</div>
        </div>
        """, unsafe_allow_html=True)

st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# Flash timing controls (always visible)
# ─────────────────────────────────────────────────────────────────────────────
fl1, fl2, fl3 = st.columns([2, 2, 3])
with fl1:
    if st.button("🌩 LOG LIGHTNING FLASH", use_container_width=True):
        st.session_state.flash_time = time.time()
        st.success("Flash logged — waiting for thunder…")
with fl2:
    if st.session_state.flash_time:
        elapsed = time.time() - st.session_state.flash_time
        est_km  = round(elapsed * SPEED_SOUND_KMS, 1)
        st.markdown(f"""
        <div class='info-card' style='text-align:center;padding:8px'>
          <span style='font-size:0.55rem;color:#2a5570'>ELAPSED / EST DIST</span><br>
          <span style='color:#00e5ff;font-family:Orbitron,monospace;font-size:1.1rem'>{elapsed:.1f}s</span>
          <span style='color:#3a6070'> / </span>
          <span style='color:#f5c518;font-family:Orbitron,monospace;font-size:1.1rem'>~{est_km}km</span>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown("<div class='info-card' style='text-align:center;padding:8px;color:#1e3a50'>No flash logged</div>",
                    unsafe_allow_html=True)
with fl3:
    st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
    st.caption("Flash-to-Thunder method: press LOG FLASH when you see lightning → "
               "the next thunder detection auto-calculates distance using Δt × 343 m/s")

st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# TABS
# ─────────────────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
    "📡  LIVE MONITOR",
    "📊  ANALYTICS",
    "🗺  HEATMAP",
    "🤖  AI ANALYSIS",
    "📋  EVENT LOG",
    "🌍  STORM MAP",
    "🌀  RADAR & 3D",
    "💾  SESSION",
])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — LIVE MONITOR
# ══════════════════════════════════════════════════════════════════════════════
with tab1:
    # Waveform
    st.markdown('<div class="sec-hdr"><span class="sec-hdr-dot"></span>AUDIO WAVEFORM — BANDPASS RMS (20–120 Hz)</div>',
                unsafe_allow_html=True)
    rms_data = list(st.session_state.rms_history)
    peak_val = max(rms_data) if rms_data else 1.0

    fig_wave = go.Figure()
    # Danger zone fill
    fig_wave.add_hrect(y0=0, y1=threshold, fillcolor="rgba(245,197,24,0.04)",
                       line_width=0, annotation_text="")
    # Waveform fill
    fig_wave.add_trace(go.Scatter(
        y=rms_data, mode="lines",
        fill="tozeroy", fillcolor="rgba(0,229,255,0.04)",
        line=dict(color="#00e5ff", width=1.8), name="RMS",
    ))
    # Smoothed overlay
    smooth = pd.Series(rms_data).rolling(10, min_periods=1).mean().tolist()
    fig_wave.add_trace(go.Scatter(
        y=smooth, mode="lines",
        line=dict(color="#f5c518", width=1, dash="dot"), name="Smoothed",
        opacity=0.7,
    ))
    fig_wave.add_hline(y=threshold, line=dict(color="#ff8c00", width=1, dash="dash"),
                       annotation_text=f"threshold {threshold:.2f}",
                       annotation_font=dict(color="#ff8c00", size=9))
    fig_wave.update_layout(
        height=160, margin=dict(l=0,r=0,t=0,b=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#040d12",
        showlegend=False,
        xaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
        yaxis=dict(showgrid=True, gridcolor="#0d1e2d",
                   range=[0, max(1.0, peak_val*1.15)],
                   tickfont=dict(color="#2a5570", size=8), zeroline=False),
    )
    st.plotly_chart(fig_wave, use_container_width=True, config={"displayModeBar": False})

    # Distance gauge + Spectral centroid
    g1, g2 = st.columns(2)

    with g1:
        st.markdown('<div class="sec-hdr"><span class="sec-hdr-dot"></span>DISTANCE GAUGE</div>',
                    unsafe_allow_html=True)
        gauge_val = dists[0] if dists else 40
        fig_gauge = go.Figure(go.Indicator(
            mode="gauge+number+delta",
            value=gauge_val,
            delta={"reference": dists[1] if len(dists) > 1 else gauge_val,
                   "valueformat": ".1f",
                   "suffix": " km",
                   "font": {"size": 13}},
            number={"suffix": " km", "font": {"family": "Orbitron", "size": 32, "color": "#f5c518"}},
            gauge=dict(
                axis=dict(range=[0, 40], tickfont=dict(color="#2a5570", size=9),
                          tickcolor="#1e3a50"),
                bar=dict(color="#f5c518", thickness=0.22),
                bgcolor="#0a1825", borderwidth=1, bordercolor="#1e3a50",
                steps=[
                    dict(range=[0, 3],   color="#2d0015"),
                    dict(range=[3, 8],   color="#2d1200"),
                    dict(range=[8, 20],  color="#1a1a00"),
                    dict(range=[20, 40], color="#0a1020"),
                ],
                threshold=dict(line=dict(color="#ff2d55", width=3),
                               thickness=0.8, value=3),
            ),
            title=dict(text="Distance to Storm",
                       font=dict(family="Share Tech Mono", size=11, color="#2a5570")),
        ))
        fig_gauge.update_layout(
            height=230, margin=dict(l=20,r=20,t=30,b=10),
            paper_bgcolor="rgba(0,0,0,0)", font=dict(color="#7aabb8"),
        )
        st.plotly_chart(fig_gauge, use_container_width=True, config={"displayModeBar": False})

    with g2:
        st.markdown('<div class="sec-hdr"><span class="sec-hdr-dot"></span>SPECTRAL CENTROID — THUNDER TEXTURE</div>',
                    unsafe_allow_html=True)
        freq_data = list(st.session_state.freq_history)
        centroids = [f.get("centroid", 0) for f in freq_data]
        rms_vals  = [f.get("rms", 0) for f in freq_data]

        fig_freq = make_subplots(specs=[[{"secondary_y": True}]])
        fig_freq.add_trace(go.Scatter(
            y=centroids, mode="lines",
            line=dict(color="#a855f7", width=1.5), name="Centroid (Hz)",
            fill="tozeroy", fillcolor="rgba(168,85,247,0.05)",
        ), secondary_y=False)
        fig_freq.add_trace(go.Scatter(
            y=rms_vals, mode="lines",
            line=dict(color="#00e5ff", width=1, dash="dot"), name="RMS",
            opacity=0.6,
        ), secondary_y=True)
        fig_freq.update_layout(
            height=230, margin=dict(l=0,r=0,t=0,b=0),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#040d12",
            legend=dict(font=dict(color="#7aabb8", size=9), bgcolor="rgba(0,0,0,0)",
                        orientation="h", y=1.1),
            xaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
            yaxis=dict(showgrid=True, gridcolor="#0d1e2d",
                       range=[0, 130], tickfont=dict(color="#2a5570", size=8),
                       title=dict(text="Hz", font=dict(color="#2a5570", size=9))),
        )
        fig_freq.update_yaxes(
            showgrid=False, tickfont=dict(color="#2a5570", size=8),
            title=dict(text="RMS", font=dict(color="#2a5570", size=9)),
            secondary_y=True,
        )
        st.plotly_chart(fig_freq, use_container_width=True, config={"displayModeBar": False})

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — ANALYTICS
# ══════════════════════════════════════════════════════════════════════════════
with tab2:
    if len(evs) < 2:
        st.markdown("""
        <div class='info-card' style='text-align:center;padding:40px'>
            Simulate at least 2 strikes to see analytics
        </div>
        """, unsafe_allow_html=True)
    else:
        df_ev = pd.DataFrame([{
            "Time":      e["Time"],
            "Distance":  e["_dist_km"] or 0,
            "Amplitude": e["_amp"],
            "Level":     e["Level"],
            "Centroid":  e.get("Centroid", 0),
        } for e in reversed(evs)])

        color_map = {"DANGER":"#ff2d55","WARNING":"#ff8c00",
                     "WATCH":"#f5c518","CLEAR":"#00e676","UNKNOWN":"#3a6070"}

        a1, a2 = st.columns(2)

        with a1:
            st.markdown('<div class="sec-hdr"><span class="sec-hdr-dot"></span>STRIKE TIMELINE</div>',
                        unsafe_allow_html=True)
            fig_tl = px.scatter(df_ev, x="Time", y="Distance",
                                size="Amplitude", color="Level",
                                color_discrete_map=color_map, size_max=35)
            # Trend line
            if len(df_ev) >= 3:
                fig_tl.add_trace(go.Scatter(
                    x=df_ev["Time"], y=df_ev["Distance"].rolling(3, min_periods=1).mean(),
                    mode="lines", line=dict(color="rgba(255,255,255,0.19)", width=1, dash="dot"),
                    name="Trend", showlegend=False,
                ))
            fig_tl.update_layout(
                height=280, margin=dict(l=0,r=0,t=0,b=0),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#040d12",
                legend=dict(font=dict(color="#7aabb8",size=9), bgcolor="rgba(0,0,0,0)"),
                xaxis=dict(showgrid=False, tickfont=dict(color="#2a5570",size=9)),
                yaxis=dict(showgrid=True, gridcolor="#0d1e2d",
                           tickfont=dict(color="#2a5570",size=9),
                           title=dict(text="km",font=dict(color="#2a5570",size=9))),
            )
            st.plotly_chart(fig_tl, use_container_width=True, config={"displayModeBar":False})

        with a2:
            st.markdown('<div class="sec-hdr"><span class="sec-hdr-dot"></span>AMPLITUDE DISTRIBUTION</div>',
                        unsafe_allow_html=True)
            fig_hist = px.histogram(df_ev, x="Amplitude", nbins=20,
                                    color="Level", color_discrete_map=color_map,
                                    barmode="overlay")
            fig_hist.update_layout(
                height=280, margin=dict(l=0,r=0,t=0,b=0),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#040d12",
                legend=dict(font=dict(color="#7aabb8",size=9), bgcolor="rgba(0,0,0,0)"),
                xaxis=dict(showgrid=False, tickfont=dict(color="#2a5570",size=9),
                           title=dict(text="Amplitude",font=dict(color="#2a5570",size=9))),
                yaxis=dict(showgrid=True, gridcolor="#0d1e2d",
                           tickfont=dict(color="#2a5570",size=9)),
                bargap=0.05,
            )
            fig_hist.update_traces(opacity=0.75)
            st.plotly_chart(fig_hist, use_container_width=True, config={"displayModeBar":False})

        a3, a4 = st.columns(2)

        with a3:
            st.markdown('<div class="sec-hdr"><span class="sec-hdr-dot"></span>DISTANCE vs AMPLITUDE</div>',
                        unsafe_allow_html=True)
            fig_da = px.scatter(df_ev, x="Distance", y="Amplitude",
                                color="Level", color_discrete_map=color_map,
                                trendline="ols" if len(df_ev) >= 3 else None,
                                size_max=20)
            fig_da.update_layout(
                height=260, margin=dict(l=0,r=0,t=0,b=0),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#040d12",
                legend=dict(font=dict(color="#7aabb8",size=9), bgcolor="rgba(0,0,0,0)"),
                xaxis=dict(showgrid=True,gridcolor="#0d1e2d",tickfont=dict(color="#2a5570",size=9),
                           title=dict(text="Distance (km)",font=dict(color="#2a5570",size=9))),
                yaxis=dict(showgrid=True,gridcolor="#0d1e2d",tickfont=dict(color="#2a5570",size=9),
                           title=dict(text="Amplitude",font=dict(color="#2a5570",size=9))),
            )
            st.plotly_chart(fig_da, use_container_width=True, config={"displayModeBar":False})

        with a4:
            st.markdown('<div class="sec-hdr"><span class="sec-hdr-dot"></span>LEVEL BREAKDOWN</div>',
                        unsafe_allow_html=True)
            level_counts = df_ev["Level"].value_counts().reset_index()
            level_counts.columns = ["Level","Count"]
            fig_pie = px.pie(level_counts, values="Count", names="Level",
                             color="Level", color_discrete_map=color_map,
                             hole=0.55)
            fig_pie.update_traces(textfont=dict(family="Share Tech Mono", size=10),
                                  textinfo="label+percent")
            fig_pie.update_layout(
                height=260, margin=dict(l=0,r=0,t=0,b=0),
                paper_bgcolor="rgba(0,0,0,0)",
                legend=dict(font=dict(color="#7aabb8",size=9), bgcolor="rgba(0,0,0,0)"),
                showlegend=False,
            )
            st.plotly_chart(fig_pie, use_container_width=True, config={"displayModeBar":False})

        # Stats summary row
        st.markdown('<div class="sec-hdr"><span class="sec-hdr-dot"></span>STATISTICS SUMMARY</div>',
                    unsafe_allow_html=True)
        s1,s2,s3,s4 = st.columns(4)
        s1.metric("Mean Distance", f"{df_ev['Distance'].mean():.1f} km" if dists else "—")
        s2.metric("Std Deviation", f"{df_ev['Distance'].std():.1f} km" if len(dists)>1 else "—")
        s3.metric("Mean Amplitude", f"{df_ev['Amplitude'].mean():.3f}")
        s4.metric("Spectral Avg", f"{df_ev['Centroid'].mean():.1f} Hz")

        # ── Danger score history ──────────────────────────────────────────────
        sev_hist = st.session_state.severity_history
        if len(sev_hist) >= 2:
            st.markdown('<div class="sec-hdr" style="margin-top:12px"><span class="sec-hdr-dot"></span>SEVERITY SCORE HISTORY</div>',
                        unsafe_allow_html=True)
            sh_times  = [t.strftime("%H:%M:%S") for t, _ in sev_hist]
            sh_scores = [s for _, s in sev_hist]
            fig_sev_h = go.Figure()
            # Coloured background zones
            for y0, y1, clr in [(0,20,"rgba(0,230,118,0.04)"),(20,40,"rgba(245,197,24,0.04)"),
                                (40,60,"rgba(255,140,0,0.05)"),(60,80,"rgba(255,85,0,0.06)"),
                                (80,100,"rgba(255,45,85,0.07)")]:
                fig_sev_h.add_hrect(y0=y0, y1=y1, fillcolor=clr, line_width=0)
            fig_sev_h.add_trace(go.Scatter(
                x=sh_times, y=sh_scores, mode="lines+markers",
                line=dict(color="#f5c518", width=2),
                marker=dict(color=[level_color(severity_label(s)[0]) for s in sh_scores],
                            size=6, line=dict(color="#040d12", width=1)),
                fill="tozeroy", fillcolor="rgba(245,197,24,0.06)",
                name="Severity",
            ))
            # Storm decay overlay
            decay = st.session_state.decay_info
            if decay and decay.get("reliable") and decay.get("eta_min") is not None:
                fig_sev_h.add_annotation(
                    text=f"📉 Storm ends in ~{decay['eta_min']} min  "
                         f"(½-life {decay['half_life_min']} min)",
                    xref="paper", yref="paper", x=0.01, y=0.96,
                    xanchor="left", showarrow=False,
                    font=dict(color="#00e676", size=9, family="Share Tech Mono"))
            fig_sev_h.update_layout(
                height=200, margin=dict(l=0,r=0,t=0,b=0),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#040d12",
                showlegend=False,
                xaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
                yaxis=dict(range=[0,105], showgrid=True, gridcolor="#0d1e2d",
                           tickfont=dict(color="#2a5570",size=8),
                           title=dict(text="Score",font=dict(color="#2a5570",size=9))),
            )
            st.plotly_chart(fig_sev_h, use_container_width=True, config={"displayModeBar":False})

            # Decay info card
            if decay and decay.get("reliable"):
                dc = "#00e676" if not decay.get("growing") else "#ff8c00"
                msg = (f"Storm decaying — estimated end in <b>{decay['eta_min']} min</b>. "
                       f"Half-life: {decay['half_life_min']} min. "
                       f"Current rate: {decay['current_rate']} strikes/min.")
                if decay.get("growing"):
                    msg = f"⚠ Storm INTENSIFYING. Rate: {decay['current_rate']} strikes/min."
                st.markdown(f"<div class='info-card' style='border-left:3px solid {dc};"
                            f"font-size:0.65rem'>{msg}</div>", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — HEATMAP
# ══════════════════════════════════════════════════════════════════════════════
with tab3:
    st.markdown('<div class="sec-hdr"><span class="sec-hdr-dot"></span>STORM INTENSITY HEATMAP — TIME × DISTANCE</div>',
                unsafe_allow_html=True)

    hd = st.session_state.heatmap_data
    if len(hd) < 2:
        st.markdown("<div class='info-card' style='text-align:center;padding:40px'>Simulate strikes to build heatmap</div>",
                    unsafe_allow_html=True)
    else:
        hdf = pd.DataFrame(hd, columns=["Minute","Distance","Amplitude"])
        # Pivot: rows=distance bucket, cols=time
        hdf["DistBucket"] = pd.cut(hdf["Distance"], bins=[0,3,8,15,25,40],
                                    labels=["0-3km","3-8km","8-15km","15-25km","25-40km"])
        pivot = hdf.groupby(["Minute","DistBucket"])["Amplitude"].mean().unstack(fill_value=0)
        pivot = pivot.reindex(columns=["0-3km","3-8km","8-15km","15-25km","25-40km"],
                               fill_value=0)

        fig_hm = go.Figure(go.Heatmap(
            z=pivot.values.T,
            x=pivot.index.tolist(),
            y=pivot.columns.tolist(),
            colorscale=[
                [0.0,  "#040d12"],
                [0.2,  "#0a2040"],
                [0.4,  "#1a4060"],
                [0.6,  "#f5c518"],
                [0.8,  "#ff8c00"],
                [1.0,  "#ff2d55"],
            ],
            colorbar=dict(
                tickfont=dict(color="#7aabb8", size=9),
                title=dict(text="Amplitude", font=dict(color="#7aabb8", size=10)),
                thickness=12,
            ),
            hovertemplate="Time: %{x}<br>Distance: %{y}<br>Amplitude: %{z:.3f}<extra></extra>",
        ))
        fig_hm.update_layout(
            height=320, margin=dict(l=0,r=0,t=0,b=0),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#040d12",
            xaxis=dict(tickfont=dict(color="#2a5570",size=9), gridcolor="#0d1e2d",
                       title=dict(text="Time",font=dict(color="#2a5570",size=9))),
            yaxis=dict(tickfont=dict(color="#2a5570",size=9), autorange="reversed",
                       title=dict(text="Distance Zone",font=dict(color="#2a5570",size=9))),
        )
        st.plotly_chart(fig_hm, use_container_width=True, config={"displayModeBar":False})

    # Distance over time line chart
    if evs:
        st.markdown('<div class="sec-hdr" style="margin-top:16px"><span class="sec-hdr-dot"></span>DISTANCE OVER TIME — STORM PATH</div>',
                    unsafe_allow_html=True)
        path_df = pd.DataFrame([{
            "Time":     e["Time"],
            "Distance": e["_dist_km"] or 0,
            "Level":    e["Level"],
        } for e in reversed(evs) if e.get("_dist_km")])

        if not path_df.empty:
            fig_path = go.Figure()
            # Danger zone
            fig_path.add_hrect(y0=0, y1=3, fillcolor="rgba(255,45,85,0.08)", line_width=0,
                                annotation_text="DANGER", annotation_font_color="#ff2d55",
                                annotation_font_size=9)
            fig_path.add_hrect(y0=3, y1=8, fillcolor="rgba(255,140,0,0.05)", line_width=0,
                                annotation_text="WARNING", annotation_font_color="#ff8c00",
                                annotation_font_size=9)
            fig_path.add_trace(go.Scatter(
                x=path_df["Time"], y=path_df["Distance"],
                mode="lines+markers",
                line=dict(color="#00e5ff", width=2),
                marker=dict(color=[level_color(l) for l in path_df["Level"]],
                            size=10, line=dict(color="#040d12", width=1)),
                name="Distance",
            ))
            fig_path.update_layout(
                height=240, margin=dict(l=0,r=0,t=0,b=0),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#040d12",
                showlegend=False,
                xaxis=dict(showgrid=False, tickfont=dict(color="#2a5570",size=9)),
                yaxis=dict(showgrid=True, gridcolor="#0d1e2d",
                           tickfont=dict(color="#2a5570",size=9),
                           title=dict(text="km",font=dict(color="#2a5570",size=9))),
            )
            st.plotly_chart(fig_path, use_container_width=True, config={"displayModeBar":False})

# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — AI ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════
with tab4:
    st.markdown('<div class="sec-hdr"><span class="sec-hdr-dot"></span>STORM INTELLIGENCE ANALYSIS</div>',
                unsafe_allow_html=True)

    if st.button("🔄 REGENERATE ANALYSIS", use_container_width=False):
        st.session_state.ai_summary = generate_ai_summary()

    summary = st.session_state.ai_summary or generate_ai_summary()

    for line in summary.split("\n"):
        if not line.strip(): continue
        icon = line[:2] if line[0] in "⚠⚡🌩✓📉📈📊🔊" else "ℹ"
        rest = line[2:].strip() if line[0] in "⚠⚡🌩✓📉📈📊🔊" else line
        level_color_map = {
            "⚠": "#ff2d55", "⚡": "#ff8c00", "🌩": "#f5c518",
            "✓": "#00e676", "📉": "#ff2d55", "📈": "#00e676",
            "📊": "#7aabb8", "🔊": "#a855f7", "🚨": "#ff2d55",
        }
        clr = level_color_map.get(icon, "#7aabb8")
        st.markdown(f"""
        <div style='background:#0a1825;border:1px solid #1e3a50;border-left:3px solid {clr};
                    border-radius:3px;padding:10px 16px;margin-bottom:8px;
                    font-family:"Share Tech Mono",monospace;font-size:0.75rem;color:{clr}'>
            {icon} {rest}
        </div>
        """, unsafe_allow_html=True)

    # ── Severity gauge + All-Clear side by side ──────────────────────────────
    sev_c1, sev_c2 = st.columns(2)
    with sev_c1:
        st.markdown('<div class="sec-hdr"><span class="sec-hdr-dot"></span>SEVERITY GAUGE</div>',
                    unsafe_allow_html=True)
        fig_sev = go.Figure(go.Indicator(
            mode="gauge+number",
            value=_severity,
            number={"font": {"family":"Orbitron","size":32,"color":_sev_color}},
            gauge=dict(
                axis=dict(range=[0,100], tickfont=dict(color="#2a5570",size=9)),
                bar=dict(color=_sev_color, thickness=0.25),
                bgcolor="#0a1825", borderwidth=1, bordercolor="#1e3a50",
                steps=[
                    dict(range=[0,20],  color="#001508"),
                    dict(range=[20,40], color="#1a1800"),
                    dict(range=[40,60], color="#1e1000"),
                    dict(range=[60,80], color="#200800"),
                    dict(range=[80,100],color="#200010"),
                ],
                threshold=dict(line=dict(color="#ff2d55",width=3),thickness=0.8,value=80),
            ),
            title=dict(text=f"{_sev_emoji} {_sev_label}",
                       font=dict(family="Share Tech Mono",size=12,color=_sev_color)),
        ))
        fig_sev.update_layout(height=220, margin=dict(l=20,r=20,t=30,b=10),
                              paper_bgcolor="rgba(0,0,0,0)",font=dict(color="#7aabb8"))
        st.plotly_chart(fig_sev, use_container_width=True, config={"displayModeBar":False})

    with sev_c2:
        st.markdown('<div class="sec-hdr"><span class="sec-hdr-dot"></span>30-MINUTE ALL-CLEAR TIMER</div>',
                    unsafe_allow_html=True)
        _ac2 = all_clear_status()
        ac2_color = "#00e676" if _ac2["safe"] else "#ff8c00"
        fig_ac = go.Figure(go.Indicator(
            mode="gauge+number",
            value=_ac2["pct"],
            number={"suffix":"%","font":{"family":"Orbitron","size":32,"color":ac2_color}},
            gauge=dict(
                axis=dict(range=[0,100], tickfont=dict(color="#2a5570",size=9)),
                bar=dict(color=ac2_color, thickness=0.25),
                bgcolor="#0a1825", borderwidth=1, bordercolor="#1e3a50",
                steps=[dict(range=[0,100],color="#0a1020")],
                threshold=dict(line=dict(color="#00e676",width=3),thickness=0.8,value=100),
            ),
            title=dict(
                text="ALL CLEAR ✓" if _ac2["safe"] else f"{_ac2['minutes_remaining']} min remaining",
                font=dict(family="Share Tech Mono",size=12,color=ac2_color)),
        ))
        fig_ac.update_layout(height=220, margin=dict(l=20,r=20,t=30,b=10),
                             paper_bgcolor="rgba(0,0,0,0)",font=dict(color="#7aabb8"))
        st.plotly_chart(fig_ac, use_container_width=True, config={"displayModeBar":False})
        st.markdown(f"""
        <div class='info-card' style='font-size:0.65rem;padding:8px 14px'>
          {"✅ Safe to resume outdoor activity." if _ac2["safe"]
           else f"⏳ Wait {_ac2['minutes_remaining']} more min. ({_ac2['elapsed_min']} min elapsed since last strike)"}
        </div>""", unsafe_allow_html=True)

    if not evs:
        st.markdown("""
        <div class='info-card' style='text-align:center;padding:30px'>
            No storm data yet. Simulate strikes to see AI analysis.
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
    st.markdown('<div class="sec-hdr"><span class="sec-hdr-dot"></span>SAFETY RECOMMENDATIONS</div>',
                unsafe_allow_html=True)

    recs = [
        ("🏠", "Seek a sturdy building or hard-top vehicle if storm is within 10 km."),
        ("📱", "Avoid using wired electronics or plumbing during an active storm."),
        ("🌲", "Stay away from isolated trees, hilltops, and open fields."),
        ("⏱", "Wait 30 minutes after the last thunder before resuming outdoor activity."),
        ("🔋", "Keep emergency kit ready: torch, first aid, battery-powered radio."),
        ("📡", "Monitor official weather services (IMD / local authorities) for updates."),
    ]
    r1, r2 = st.columns(2)
    for i, (icon, text) in enumerate(recs):
        col = r1 if i % 2 == 0 else r2
        col.markdown(f"""
        <div style='background:#0a1825;border:1px solid #1e3a50;border-radius:3px;
                    padding:10px 14px;margin-bottom:8px;
                    font-family:"Share Tech Mono",monospace;font-size:0.7rem;color:#7aabb8'>
            {icon} {text}
        </div>
        """, unsafe_allow_html=True)

    # PDF export
    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
    st.markdown('<div class="sec-hdr"><span class="sec-hdr-dot"></span>EXPORT REPORT</div>',
                unsafe_allow_html=True)
    if PDF_AVAILABLE:
        if st.button("📄 GENERATE PDF REPORT", use_container_width=False):
            pdf_bytes = generate_pdf_report()
            st.download_button(
                label="⬇ DOWNLOAD PDF",
                data=pdf_bytes,
                file_name=f"thunder_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                mime="application/pdf",
            )
    else:
        st.info("Install `reportlab` for PDF export: `pip install reportlab`")

    csv_data = pd.DataFrame([{
        "Time": e["Time"], "Amplitude": e["Amplitude"],
        "Distance": e["Distance"], "Level": e["Level"], "Centroid_Hz": e.get("Centroid", ""),
    } for e in evs]).to_csv(index=False) if evs else "No data"
    st.download_button("⬇ DOWNLOAD CSV", data=csv_data,
                       file_name=f"thunder_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                       mime="text/csv")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 5 — EVENT LOG
# ══════════════════════════════════════════════════════════════════════════════
with tab5:
    st.markdown('<div class="sec-hdr"><span class="sec-hdr-dot"></span>COMPLETE STRIKE LOG</div>',
                unsafe_allow_html=True)

    if evs:
        # Search/filter
        f1, f2 = st.columns([2, 1])
        with f1:
            filter_level = st.multiselect("Filter by level",
                options=["DANGER","WARNING","WATCH","CLEAR","UNKNOWN"],
                default=["DANGER","WARNING","WATCH","CLEAR","UNKNOWN"])
        with f2:
            sort_col = st.selectbox("Sort by", ["Time","Amplitude","Distance"])

        df_log = pd.DataFrame([{
            "Time":      e["Time"],
            "Level":     e["Level"],
            "Distance":  e["Distance"],
            "Amplitude": e["Amplitude"],
            "Centroid":  f"{e.get('Centroid', 0):.1f} Hz",
        } for e in evs if e["Level"] in filter_level])

        if not df_log.empty:
            if sort_col == "Amplitude":
                df_log = df_log.sort_values("Amplitude", ascending=False)
            elif sort_col == "Distance":
                df_log["_dist_sort"] = df_log["Distance"].str.replace(" km","").replace("—","999").astype(float, errors="ignore")
                df_log = df_log.sort_values("_dist_sort").drop(columns=["_dist_sort"], errors="ignore")

            def style_level(val):
                c = {"DANGER":"#ff2d55","WARNING":"#ff8c00","WATCH":"#f5c518",
                     "CLEAR":"#00e676","UNKNOWN":"#3a6070"}.get(val,"#fff")
                return f"color:{c};font-weight:bold"

            styled = (df_log.style
                      .map(style_level, subset=["Level"])
                      .set_properties(**{
                          "background-color": "#0a1825",
                          "color": "#c8d8e8",
                          "font-family": "Share Tech Mono, monospace",
                          "font-size": "0.72rem",
                      }))
            st.dataframe(styled, use_container_width=True, hide_index=True)
            st.caption(f"Showing {len(df_log)} of {len(evs)} events")
        else:
            st.info("No events match the selected filters.")
    else:
        st.markdown("<div class='info-card' style='text-align:center;padding:40px'>No events recorded yet.</div>",
                    unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# TAB 6 — LIVE STORM MAP
# ══════════════════════════════════════════════════════════════════════════════
with tab6:
    st.markdown('<div class="sec-hdr"><span class="sec-hdr-dot"></span>LIVE STORM MAP — REAL DATA + SIMULATED FALLBACK</div>',
                unsafe_allow_html=True)

    # ── Browser Geolocation ──────────────────────────────────────────────────
    # Inject a JS component that reads navigator.geolocation and writes
    # the result back into Streamlit via st.query_params.
    geo_html = """
    <div id="geo-wrap" style="font-family:'Share Tech Mono',monospace;
         font-size:0.65rem;color:#7aabb8;padding:4px 0;">
      <span id="geo-status">Requesting location…</span>
    </div>
    <script>
    (function() {
        // Read current query params
        function getParam(key) {
            return new URLSearchParams(window.location.search).get(key);
        }
        var existingLat = getParam('geo_lat');
        var existingLon = getParam('geo_lon');

        if (existingLat && existingLon) {
            document.getElementById('geo-status').innerHTML =
                '📍 Location set: ' + parseFloat(existingLat).toFixed(4) + '°N, '
                + parseFloat(existingLon).toFixed(4) + '°E';
            return;
        }

        if (!navigator.geolocation) {
            document.getElementById('geo-status').textContent =
                '⚠ Geolocation not supported — enter manually below.';
            return;
        }

        document.getElementById('geo-status').textContent = '🔄 Detecting your location…';

        navigator.geolocation.getCurrentPosition(
            function(pos) {
                var lat = pos.coords.latitude.toFixed(6);
                var lon = pos.coords.longitude.toFixed(6);
                document.getElementById('geo-status').innerHTML =
                    '✅ Located: ' + parseFloat(lat).toFixed(4) + '°N, '
                    + parseFloat(lon).toFixed(4) + '°E  (±'
                    + Math.round(pos.coords.accuracy) + 'm)';
                // Write coords into URL query params → Streamlit reads them
                var url = new URL(window.location.href);
                url.searchParams.set('geo_lat', lat);
                url.searchParams.set('geo_lon', lon);
                window.history.replaceState({}, '', url.toString());
                // Trigger Streamlit rerun by posting to the parent
                window.parent.postMessage({type: 'streamlit:setComponentValue',
                    value: lat + ',' + lon}, '*');
            },
            function(err) {
                var msgs = {1:'Permission denied', 2:'Position unavailable', 3:'Timeout'};
                document.getElementById('geo-status').innerHTML =
                    '⚠ ' + (msgs[err.code] || 'Error') + ' — enter coordinates manually below.';
            },
            {enableHighAccuracy: true, timeout: 8000, maximumAge: 60000}
        );
    })();
    </script>
    """
    st.components.v1.html(geo_html, height=36)

    # Read coords from URL query params (set by JS above)
    qp = st.query_params
    try:
        geo_lat = float(qp.get("geo_lat", 22.5726))   # Kolkata fallback
        geo_lon = float(qp.get("geo_lon", 88.3639))
    except (TypeError, ValueError):
        geo_lat, geo_lon = 22.5726, 88.3639            # Kolkata default

    # Persist to session_state so other tabs can use it
    st.session_state["user_lat"] = geo_lat
    st.session_state["user_lon"] = geo_lon

    # Manual override (pre-filled with auto-detected or last known)
    lc1, lc2, lc3, lc4 = st.columns([1.6, 1.6, 1.2, 1])
    with lc1:
        center_lat = st.number_input("Latitude (auto-detected)",
                                     value=round(geo_lat, 6),
                                     min_value=-90.0, max_value=90.0,
                                     step=0.0001, format="%.4f")
    with lc2:
        center_lon = st.number_input("Longitude (auto-detected)",
                                     value=round(geo_lon, 6),
                                     min_value=-180.0, max_value=180.0,
                                     step=0.0001, format="%.4f")
    with lc3:
        if st.button("🔄 Re-detect Location", use_container_width=True):
            # Clear stored params so JS fires again
            qp_clear = dict(st.query_params)
            qp_clear.pop("geo_lat", None)
            qp_clear.pop("geo_lon", None)
            st.query_params.clear()
            st.rerun()
    with lc4:
        force_sim = st.checkbox("Force simulate", value=False,
                                help="Skip Blitzortung and use simulated data")

    # Location info card
    st.markdown(f"""
    <div class='info-card' style='font-size:0.62rem;padding:8px 14px;margin-bottom:8px'>
      📍 <b>Active coordinates:</b>
      <span class='val'>{center_lat:.4f}°N, {center_lon:.4f}°E</span>
      &nbsp;·&nbsp; Override by editing the fields above.
      &nbsp;·&nbsp; Accuracy improves with GPS/Wi-Fi enabled.
    </div>
    """, unsafe_allow_html=True)

    # ── Fetch or simulate ─────────────────────────────────────────────────────
    map_status = st.empty()
    strikes, source_label = [], "OFFLINE"

    if not force_sim:
        with st.spinner("Fetching live lightning data from Blitzortung…"):
            strikes, source_label = fetch_blitzortung()

    if not strikes:
        source_label = "SIMULATED — no live feed available"
        strikes = generate_simulated_strikes(center_lat, center_lon, n=90)

    # ── Source badge ──────────────────────────────────────────────────────────
    is_live = "LIVE" in source_label
    badge_color = "#00e676" if is_live else "#f5c518"
    badge_icon  = "🟢 LIVE DATA" if is_live else "🟡 SIMULATED"
    st.markdown(f"""
    <div style='display:inline-flex;align-items:center;gap:8px;
                background:#0a1825;border:1px solid {badge_color};border-radius:3px;
                padding:5px 14px;margin-bottom:10px;
                font-family:"Share Tech Mono",monospace;font-size:0.65rem;color:{badge_color}'>
        {badge_icon} &nbsp;·&nbsp; {source_label} &nbsp;·&nbsp; {len(strikes)} strikes loaded
    </div>
    """, unsafe_allow_html=True)

    # ── Render map ────────────────────────────────────────────────────────────
    fig_map = build_storm_map(
        strikes=strikes,
        center_lat=center_lat,
        center_lon=center_lon,
        user_events=evs,
        source_label=source_label,
    )
    st.plotly_chart(fig_map, use_container_width=True, config={
        "displayModeBar": True,
        "modeBarButtonsToRemove": ["select2d", "lasso2d"],
        "toImageButtonOptions": {"format": "png", "filename": "storm_map"},
    })

    # ── Weather overlay ───────────────────────────────────────────────────────
    owm_key = st.session_state.get("owm_key", "")
    wx = fetch_weather(center_lat, center_lon, owm_key) if owm_key else None
    if wx:
        st.markdown('<div class="sec-hdr" style="margin-top:10px"><span class="sec-hdr-dot"></span>CURRENT WEATHER CONDITIONS</div>',
                    unsafe_allow_html=True)
        icon_map = {
            "Thunderstorm": "⛈", "Drizzle": "🌦", "Rain": "🌧",
            "Snow": "❄️", "Clear": "☀️", "Clouds": "☁️",
            "Mist": "🌫", "Fog": "🌫", "Haze": "🌫",
        }
        wx_icon = icon_map.get(wx["icon"], "🌡")
        w1,w2,w3,w4,w5,w6 = st.columns(6)
        w1.metric(f"{wx_icon} Weather",  wx["description"])
        w2.metric("🌡 Temp",             f"{wx['temp_c']}°C")
        w3.metric("💧 Humidity",         f"{wx['humidity']}%")
        w4.metric("🌬 Wind",             f"{wx['wind_speed']} km/h")
        w5.metric("📊 Pressure",         f"{wx['pressure']} hPa")
        w6.metric("👁 Visibility",       f"{wx['visibility']} km")
    elif owm_key:
        st.warning("Weather fetch failed — check API key or network.")
    else:
        st.markdown("""<div class='info-card' style='font-size:0.62rem'>
            ℹ Enter your <b>OpenWeatherMap API key</b> in the sidebar to see live
            weather conditions overlaid here (temp, humidity, wind, pressure).
            Free keys at <b>openweathermap.org</b>.
        </div>""", unsafe_allow_html=True)

    # ── Storm vector chart ─────────────────────────────────────────────────────
    if _vector:
        st.markdown('<div class="sec-hdr" style="margin-top:10px"><span class="sec-hdr-dot"></span>STORM VECTOR COMPASS</div>',
                    unsafe_allow_html=True)
        bearing = _vector["bearing_deg"]
        spd     = _vector["speed_kmh"]
        v_col   = "#ff2d55" if not _vector["moving_away"] else "#00e676"

        theta   = math.radians(bearing)
        arr_x   = [0, math.sin(theta) * 0.85]
        arr_y   = [0, math.cos(theta) * 0.85]

        fig_compass = go.Figure()
        # Compass rings
        for r, lbl in [(1.0,""), (0.5,"")]:
            angles = list(range(0, 361, 5))
            fig_compass.add_trace(go.Scatterpolar(
                r=[r]*len(angles), theta=angles, mode="lines",
                line=dict(color="#1e3a50", width=0.8), showlegend=False))
        # Cardinal labels
        for ang, lbl in [(0,"N"),(90,"E"),(180,"S"),(270,"W")]:
            fig_compass.add_trace(go.Scatterpolar(
                r=[1.15], theta=[ang], mode="text", text=[lbl],
                textfont=dict(color="#7aabb8", size=11, family="Share Tech Mono"),
                showlegend=False))
        # Arrow
        fig_compass.add_trace(go.Scatterpolar(
            r=[0, 0.85], theta=[bearing, bearing], mode="lines+markers",
            line=dict(color=v_col, width=4),
            marker=dict(color=v_col, size=[4,14], symbol=["circle","arrow"],
                        angleref="previous"),
            showlegend=False))
        # Speed annotation
        fig_compass.add_annotation(
            text=f"{spd} km/h<br>{'▼ TOWARD YOU' if not _vector['moving_away'] else '▲ AWAY'}",
            x=0.5, y=0.08, xref="paper", yref="paper",
            showarrow=False, font=dict(color=v_col, size=10, family="Share Tech Mono"),
            align="center")
        fig_compass.update_layout(
            height=280, margin=dict(l=10,r=10,t=10,b=30),
            paper_bgcolor="rgba(0,0,0,0)",
            polar=dict(
                bgcolor="#040d12",
                radialaxis=dict(visible=False, range=[0,1.2]),
                angularaxis=dict(
                    tickmode="array",
                    tickvals=[0,45,90,135,180,225,270,315],
                    ticktext=["N","NE","E","SE","S","SW","W","NW"],
                    tickfont=dict(color="#2a5570", size=8, family="Share Tech Mono"),
                    linecolor="#1e3a50", gridcolor="#0d1e2d",
                    direction="clockwise", rotation=90,
                ),
            ),
        )
        _vcol1, _vcol2 = st.columns([1, 2])
        with _vcol1:
            st.plotly_chart(fig_compass, use_container_width=True,
                            config={"displayModeBar": False})
        with _vcol2:
            st.markdown(f"""
            <div class='info-card' style='margin-top:10px'>
              <b>BEARING</b> <span class='val'>{bearing:.0f}°</span><br>
              <b>SPEED</b>   <span class='val'>{spd} km/h</span><br>
              <b>DIRECTION</b> <span class='val'>{'Toward you' if not _vector['moving_away'] else 'Away from you'}</span><br>
              <b>NOTE</b> Bearing is estimated from amplitude envelope.
              Multi-microphone array required for true bearing.
            </div>
            """, unsafe_allow_html=True)

    # ── Strike proximity table ────────────────────────────────────────────────
    if strikes:
        st.markdown('<div class="sec-hdr" style="margin-top:8px"><span class="sec-hdr-dot"></span>NEAREST STRIKES TO YOUR LOCATION</div>',
                    unsafe_allow_html=True)

        now_ms = int(time.time() * 1000)
        proximity = []
        for s in strikes:
            dlat = s["lat"] - center_lat
            dlon = s["lon"] - center_lon
            km   = math.sqrt((dlat * 111) ** 2 +
                             (dlon * 111 * math.cos(math.radians(center_lat))) ** 2)
            age_s = (now_ms - s.get("time", now_ms)) / 1000
            proximity.append({
                "Distance (km)": round(km, 1),
                "Age (s)":       round(age_s, 0),
                "Lat":           round(s["lat"], 3),
                "Lon":           round(s["lon"], 3),
                "Source":        "Simulated" if s.get("simulated") else "Live",
            })

        proximity.sort(key=lambda x: x["Distance (km)"])
        prox_df = pd.DataFrame(proximity[:15])

        def color_dist(val):
            if val <= 3:   return "color:#ff2d55;font-weight:bold"
            if val <= 8:   return "color:#ff8c00;font-weight:bold"
            if val <= 20:  return "color:#f5c518"
            return "color:#7aabb8"

        styled_prox = (prox_df.style
                       .map(color_dist, subset=["Distance (km)"])
                       .set_properties(**{
                           "background-color": "#0a1825",
                           "color": "#c8d8e8",
                           "font-family": "Share Tech Mono, monospace",
                           "font-size": "0.72rem",
                       }))
        st.dataframe(styled_prox, use_container_width=True, hide_index=True)

    # ── Refresh hint ──────────────────────────────────────────────────────────
    st.markdown("""
    <div class='info-card' style='margin-top:10px;font-size:0.6rem'>
        <b>ℹ MAP NOTES</b><br>
        • Live data from <b>blitzortung.org</b> (public feed, updates every ~30s)<br>
        • ⭐ Stars = your mic-detected strikes (bearing unknown → randomly scattered in radius)<br>
        • Simulated strikes use exponential radial distribution (more near, fewer far)<br>
        • Range rings: <span style='color:#ff2d55'>3km DANGER</span> /
          <span style='color:#ff8c00'>8km WARNING</span> /
          <span style='color:#f5c518'>20km WATCH</span> /
          <span style='color:#2a5570'>40km CLEAR</span>
    </div>
    """, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 7 — RADAR & 3D
# ══════════════════════════════════════════════════════════════════════════════
with tab7:
    t7a, t7b = st.columns(2)

    # ── Polar Storm Radar ─────────────────────────────────────────────────────
    with t7a:
        st.markdown('<div class="sec-hdr"><span class="sec-hdr-dot"></span>POLAR STORM RADAR</div>',
                    unsafe_allow_html=True)
        fig_radar = go.Figure()
        # Range rings
        for r_km, clr, lbl in [(3,"#ff2d55","DANGER"),(8,"#ff8c00","WARNING"),
                                (20,"#f5c518","WATCH"),(40,"#1e3a50","")]:
            angs = list(range(0, 361, 3))
            fig_radar.add_trace(go.Scatterpolar(
                r=[r_km]*len(angs), theta=angs, mode="lines",
                line=dict(color=clr, width=1 if r_km < 40 else 0.5, dash="dot"),
                hoverinfo="skip", showlegend=False))
            if lbl:
                fig_radar.add_trace(go.Scatterpolar(
                    r=[r_km], theta=[5], mode="text", text=[lbl],
                    textfont=dict(color=clr, size=8, family="Share Tech Mono"),
                    showlegend=False, hoverinfo="skip"))
        # Sweep line (animated via frame counter)
        sweep_angle = (st.session_state.radar_frame * 6) % 360
        fig_radar.add_trace(go.Scatterpolar(
            r=[0, 42], theta=[sweep_angle, sweep_angle],
            mode="lines",
            line=dict(color="rgba(0,229,255,0.6)", width=2),
            showlegend=False, hoverinfo="skip"))
        # Sweep afterglow (fading trail)
        for i in range(1, 8):
            a = (sweep_angle - i * 4) % 360
            alpha = max(0.05, 0.5 - i * 0.07)
            fig_radar.add_trace(go.Scatterpolar(
                r=[0, 42], theta=[a, a], mode="lines",
                line=dict(color=f"rgba(0,229,255,{alpha:.2f})", width=1),
                showlegend=False, hoverinfo="skip"))
        # Strike dots
        if evs:
            for ev in evs[:30]:
                if not ev.get("_dist_km"): continue
                angle = hash(ev["Time"] + str(ev["_amp"])) % 360
                km    = ev["_dist_km"]
                clr   = level_color(ev["Level"])
                # Fade older events
                age_s = (datetime.now() - ev["_ts"]).total_seconds() if ev.get("_ts") else 999
                alpha = max(0.2, 1.0 - age_s / 300)
                fig_radar.add_trace(go.Scatterpolar(
                    r=[km], theta=[angle], mode="markers",
                    marker=dict(color=clr, size=10, opacity=alpha,
                                line=dict(color="#040d12", width=1)),
                    hovertemplate=f"<b>{ev['Level']}</b><br>{km} km<br>{ev['Time']}<extra></extra>",
                    showlegend=False))
        # YOU marker at centre
        fig_radar.add_trace(go.Scatterpolar(
            r=[0.5], theta=[0], mode="markers+text",
            marker=dict(color="#00e5ff", size=14, symbol="diamond"),
            text=["YOU"], textposition="top right",
            textfont=dict(color="#00e5ff", size=9, family="Orbitron"),
            showlegend=False))
        fig_radar.update_layout(
            height=400, margin=dict(l=10, r=10, t=10, b=10),
            paper_bgcolor="rgba(0,0,0,0)",
            polar=dict(
                bgcolor="#020c14",
                radialaxis=dict(range=[0,42], visible=True,
                                tickvals=[3,8,20,40],
                                tickfont=dict(color="#2a5570",size=7,family="Share Tech Mono"),
                                gridcolor="#0d1e2d", linecolor="#0d1e2d"),
                angularaxis=dict(
                    tickmode="array",
                    tickvals=list(range(0,360,45)),
                    ticktext=["N","NE","E","SE","S","SW","W","NW"],
                    tickfont=dict(color="#2a5570",size=8,family="Share Tech Mono"),
                    direction="clockwise", rotation=90,
                    linecolor="#0d1e2d", gridcolor="#0d1e2d"),
            ),
        )
        st.session_state.radar_frame += 1
        st.plotly_chart(fig_radar, use_container_width=True, config={"displayModeBar":False})
        st.caption("Sweep animates on each page refresh. Dots = your detected strikes (bearing estimated).")

    # ── 3D Storm Trajectory ───────────────────────────────────────────────────
    with t7b:
        st.markdown('<div class="sec-hdr"><span class="sec-hdr-dot"></span>3D STORM TRAJECTORY</div>',
                    unsafe_allow_html=True)
        if len(evs) < 3:
            st.markdown("<div class='info-card' style='text-align:center;padding:60px'>"
                        "Need ≥3 strikes for 3D plot</div>", unsafe_allow_html=True)
        else:
            traj = [e for e in reversed(evs) if e.get("_dist_km") and e.get("_ts")]
            xs   = [(e["_ts"] - traj[0]["_ts"]).total_seconds() for e in traj]
            ys   = [e["_dist_km"] for e in traj]
            zs   = [e["_amp"] for e in traj]
            lvls = [e["Level"] for e in traj]
            clrs = [level_color(l) for l in lvls]

            fig3d = go.Figure()
            # Trajectory tube
            fig3d.add_trace(go.Scatter3d(
                x=xs, y=ys, z=zs, mode="lines+markers",
                line=dict(color="#00e5ff", width=3),
                marker=dict(color=clrs, size=7,
                            line=dict(color="#040d12", width=0.5)),
                hovertemplate="<b>%{customdata}</b><br>t+%{x:.0f}s<br>%{y} km<br>amp %{z:.3f}<extra></extra>",
                customdata=lvls,
                name="Strike path",
            ))
            # Danger plane
            fig3d.add_trace(go.Surface(
                x=[[min(xs), max(xs)],[min(xs),max(xs)]],
                y=[[3, 3],[3, 3]],
                z=[[0, 0],[max(zs)*1.1, max(zs)*1.1]],
                colorscale=[[0,"rgba(255,45,85,0.08)"],[1,"rgba(255,45,85,0.08)"]],
                showscale=False, hoverinfo="skip", name="Danger (3km)",
            ))
            # Projection on floor
            fig3d.add_trace(go.Scatter3d(
                x=xs, y=ys, z=[0]*len(zs), mode="lines",
                line=dict(color="rgba(0,229,255,0.2)", width=1, dash="dash"),
                showlegend=False, hoverinfo="skip",
            ))
            fig3d.update_layout(
                height=400, margin=dict(l=0,r=0,t=0,b=0),
                paper_bgcolor="rgba(0,0,0,0)",
                scene=dict(
                    bgcolor="#020c14",
                    xaxis=dict(title="Time (s)", color="#2a5570",
                               gridcolor="#0d1e2d", backgroundcolor="#020c14"),
                    yaxis=dict(title="Distance (km)", color="#2a5570",
                               gridcolor="#0d1e2d", backgroundcolor="#020c14"),
                    zaxis=dict(title="Amplitude", color="#2a5570",
                               gridcolor="#0d1e2d", backgroundcolor="#020c14"),
                    camera=dict(eye=dict(x=1.4, y=-1.6, z=0.9)),
                ),
                legend=dict(font=dict(color="#7aabb8",size=9), bgcolor="rgba(0,0,0,0)"),
            )
            st.plotly_chart(fig3d, use_container_width=True, config={"displayModeBar":True})
            st.caption("X=time since session start · Y=distance km · Z=amplitude · "
                       "Red plane=3km danger zone · Drag to rotate.")

    # ── Rain Radar overlay info ───────────────────────────────────────────────
    st.markdown('<div class="sec-hdr" style="margin-top:4px"><span class="sec-hdr-dot"></span>RAIN RADAR — RAINVIEWER LIVE TILES</div>',
                unsafe_allow_html=True)
    radar_frames = fetch_rainviewer_frames()
    if radar_frames:
        st.success(f"✅ RainViewer: {len(radar_frames)} radar frames available (last 30 min)")
        center_lat_rv = st.session_state.get("user_lat", 22.5726)
        center_lon_rv = st.session_state.get("user_lon", 88.3639)
        frame_idx = st.slider("Radar frame (oldest → newest)",
                               0, max(0, len(radar_frames)-1),
                               len(radar_frames)-1, 1,
                               format="Frame %d")
        frame      = radar_frames[frame_idx]
        frame_time = datetime.fromtimestamp(frame["time"]).strftime("%H:%M:%S")
        tile_url   = frame["tile_url"]

        # Render radar using Plotly mapbox (tile overlay)
        fig_rv = go.Figure(go.Scattermapbox(
            lat=[center_lat_rv], lon=[center_lon_rv],
            mode="markers",
            marker=dict(size=16, color="#00e5ff", symbol="marker"),
            text=["YOU"], hoverinfo="text",
        ))
        fig_rv.update_layout(
            height=380, margin=dict(l=0,r=0,t=0,b=0),
            mapbox=dict(
                style="carto-darkmatter",
                center=dict(lat=center_lat_rv, lon=center_lon_rv),
                zoom=7,
                layers=[dict(
                    sourcetype="raster",
                    source=[tile_url],
                    type="raster",
                    opacity=0.65,
                )],
            ),
            paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_rv, use_container_width=True, config={"displayModeBar":False})
        st.caption(f"Radar frame timestamp: {frame_time}  ·  "
                   "Precipitation data © RainViewer  ·  "
                   "Blue/green=light rain · Yellow/red=heavy rain")
    else:
        st.markdown("""<div class='info-card' style='font-size:0.65rem'>
            ℹ RainViewer frames unavailable (offline or rate-limited).
            Radar tiles will appear here when connected to the internet.
        </div>""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 8 — SESSION SAVE / LOAD
# ══════════════════════════════════════════════════════════════════════════════
with tab8:
    st.markdown('<div class="sec-hdr"><span class="sec-hdr-dot"></span>SESSION SAVE / LOAD</div>',
                unsafe_allow_html=True)

    ss1, ss2 = st.columns(2)

    # ── Save ──────────────────────────────────────────────────────────────────
    with ss1:
        st.markdown("**💾 SAVE CURRENT SESSION**")
        st.caption(f"{len(evs)} events in current session")
        if evs:
            json_str  = session_to_json()
            fname     = f"storm_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            st.download_button(
                label="⬇ DOWNLOAD SESSION JSON",
                data=json_str,
                file_name=fname,
                mime="application/json",
                use_container_width=True,
            )
            # Preview
            with st.expander("Preview JSON", expanded=False):
                st.code(json_str[:800] + ("\n…" if len(json_str) > 800 else ""),
                        language="json")
        else:
            st.markdown("<div class='info-card' style='text-align:center;padding:30px'>"
                        "No events to save yet</div>", unsafe_allow_html=True)

    # ── Load ──────────────────────────────────────────────────────────────────
    with ss2:
        st.markdown("**📂 LOAD SAVED SESSION**")
        st.caption("Upload a previously saved .json file to replay it")
        uploaded = st.file_uploader("Choose session file",
                                     type=["json"], label_visibility="collapsed")
        if uploaded:
            raw = uploaded.read().decode("utf-8")
            ok, msg = session_from_json(raw)
            if ok:
                st.success(f"✅ {msg}")
            else:
                st.error(f"❌ Load failed: {msg}")

    # ── Session summary ───────────────────────────────────────────────────────
    st.markdown('<div class="sec-hdr" style="margin-top:16px"><span class="sec-hdr-dot"></span>CURRENT SESSION SUMMARY</div>',
                unsafe_allow_html=True)
    if evs:
        _dists_s = [e["_dist_km"] for e in evs if e.get("_dist_km")]
        _amps_s  = [e["_amp"] for e in evs]
        duration = str(datetime.now() - st.session_state.session_start).split(".")[0]
        sm1,sm2,sm3,sm4,sm5 = st.columns(5)
        sm1.metric("Duration",     duration)
        sm2.metric("Total Events", len(evs))
        sm3.metric("Closest",      f"{min(_dists_s):.1f} km" if _dists_s else "—")
        sm4.metric("Peak Amp",     f"{max(_amps_s):.3f}" if _amps_s else "—")
        sm5.metric("Severity",     f"{st.session_state.severity_score}/100")

        # Timeline mini-chart
        st.markdown('<div class="sec-hdr" style="margin-top:8px"><span class="sec-hdr-dot"></span>SESSION TIMELINE</div>',
                    unsafe_allow_html=True)
        tl_df = pd.DataFrame([{
            "Time":     e["Time"],
            "Distance": e["_dist_km"] or 0,
            "Amp":      e["_amp"],
            "Level":    e["Level"],
        } for e in reversed(evs)])
        fig_tl2 = make_subplots(rows=2, cols=1, shared_xaxes=True,
                                 row_heights=[0.6,0.4], vertical_spacing=0.05)
        fig_tl2.add_trace(go.Scatter(
            x=tl_df["Time"], y=tl_df["Distance"],
            mode="lines+markers",
            line=dict(color="#00e5ff", width=2),
            marker=dict(color=[level_color(l) for l in tl_df["Level"]],
                        size=8, line=dict(color="#040d12",width=1)),
            name="Distance (km)"), row=1, col=1)
        fig_tl2.add_trace(go.Bar(
            x=tl_df["Time"], y=tl_df["Amp"],
            marker_color=[level_color(l) for l in tl_df["Level"]],
            name="Amplitude", opacity=0.8), row=2, col=1)
        fig_tl2.update_layout(
            height=280, margin=dict(l=0,r=0,t=0,b=0),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#040d12",
            showlegend=False,
            xaxis2=dict(showgrid=False, tickfont=dict(color="#2a5570",size=8)),
            yaxis=dict(showgrid=True, gridcolor="#0d1e2d",
                       tickfont=dict(color="#2a5570",size=8),
                       title=dict(text="km",font=dict(color="#2a5570",size=8))),
            yaxis2=dict(showgrid=True, gridcolor="#0d1e2d",
                        tickfont=dict(color="#2a5570",size=8),
                        title=dict(text="Amp",font=dict(color="#2a5570",size=8))),
        )
        st.plotly_chart(fig_tl2, use_container_width=True, config={"displayModeBar":False})
    else:
        st.markdown("<div class='info-card' style='text-align:center;padding:30px'>"
                    "No session data yet.</div>", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# Auto-simulation engine
# Scenarios produce a scripted sequence of (delay_s, km, amp) steps.
# The engine fires one step per rerun and schedules the next via sim_next_tick.
# ─────────────────────────────────────────────────────────────────────────────

def build_scenario(name: str, speed: float) -> list:
    """
    Returns list of (delay_seconds, dist_km, amplitude) tuples.
    delay_seconds = pause after *previous* event before firing this one.
    speed multiplier shrinks delays.
    """
    def s(d, km, amp): return (d / speed, km, amp)

    if name == "approaching storm":
        return [
            s(2,  38, 0.18), s(4,  32, 0.22), s(3,  27, 0.27),
            s(5,  22, 0.31), s(3,  17, 0.38), s(4,  13, 0.44),
            s(3,   9, 0.52), s(2,   6, 0.63), s(3,   4, 0.74),
            s(2, 2.5, 0.88), s(4, 1.8, 0.95), s(5,   3, 0.82),
            s(4,   7, 0.61), s(5,  14, 0.44), s(6,  22, 0.29),
            s(8,  35, 0.18),
        ]
    elif name == "passing storm":
        return [
            s(1,  12, 0.45), s(2,   9, 0.55), s(2,   6, 0.68),
            s(2,   4, 0.79), s(3,   3, 0.91), s(2, 2.2, 0.97),
            s(3, 2.8, 0.93), s(2,   4, 0.80), s(3,   7, 0.65),
            s(3,  11, 0.50), s(4,  16, 0.37), s(5,  23, 0.24),
        ]
    elif name == "distant rumble":
        return [
            s(5,  35, 0.15), s(8,  38, 0.12), s(6,  33, 0.17),
            s(9,  40, 0.11), s(7,  36, 0.14), s(10, 39, 0.13),
            s(8,  34, 0.16), s(6,  37, 0.12),
        ]
    elif name == "severe outbreak":
        steps = []
        # Three cells — each approaches, peaks, recedes
        for cell_start_km, base_amp in [(40, 0.5), (35, 0.6), (30, 0.7)]:
            for i, (km_off, amp_boost) in enumerate([
                (0, 0.0), (-6, 0.08), (-10, 0.15), (-14, 0.22),
                (-18, 0.3), (-22, 0.35), (-25, 0.38),
                (-22, 0.3), (-16, 0.2), (-10, 0.1), (-4, 0.05)
            ]):
                steps.append(s(2 if i > 0 else 5,
                               max(1.0, cell_start_km + km_off),
                               min(1.0, base_amp + amp_boost)))
        return steps
    else:  # "random"
        # Organic random storm — starts far, wanders, then clears
        steps = []
        km = random.uniform(30, 40)
        for _ in range(20):
            delay = random.uniform(2, 7) / speed
            km   += random.uniform(-8, 4)          # biased inward early
            km    = max(1.0, min(42.0, km))
            amp   = max(0.1, min(0.98, 1.1 - km / 45 + random.uniform(-0.1, 0.1)))
            steps.append((delay, round(km, 1), round(amp, 2)))
        return steps

def build_waveform_spike(amp: float):
    """Push a thunder spike into the RMS history."""
    envelope = [0.01,0.05,0.15,0.35,0.65,0.88,0.98,0.92,0.78,
                0.60,0.44,0.30,0.18,0.10,0.05,0.02]
    for v in envelope:
        noisy = v * amp + random.uniform(0, 0.015)
        st.session_state.rms_history.append(noisy)

# ── Idle ambient noise ────────────────────────────────────────────────────────
def push_ambient_noise():
    noise = st.session_state.noise_floor * random.uniform(0.5, 1.8)
    st.session_state.rms_history.append(noise)

# ── Scenario cache (built once per run, stored in session_state) ──────────────
if "sim_steps" not in st.session_state:
    st.session_state.sim_steps = []

# ── Auto-simulation tick ──────────────────────────────────────────────────────
REFRESH_INTERVAL = 0.28   # seconds between reruns

if st.session_state.auto_sim:
    now = time.time()

    # Build scenario steps if not yet built for this run
    if not st.session_state.sim_steps:
        st.session_state.sim_steps    = build_scenario(
            st.session_state.sim_scenario,
            st.session_state.sim_speed,
        )
        st.session_state.sim_step     = 0
        st.session_state.sim_next_tick = now + st.session_state.sim_steps[0][0]

    # Always push ambient noise each tick
    push_ambient_noise()

    step_idx = st.session_state.sim_step
    steps    = st.session_state.sim_steps

    if step_idx < len(steps):
        if now >= st.session_state.sim_next_tick:
            delay, km, amp = steps[step_idx]
            add_event(amp=amp, dist_km=km,
                      centroid=random.uniform(25 + km * 0.5, 90))
            build_waveform_spike(amp)
            st.session_state.sim_step += 1
            next_idx = st.session_state.sim_step
            if next_idx < len(steps):
                st.session_state.sim_next_tick = now + steps[next_idx][0]
    else:
        # Scenario finished — stop or loop depending on scenario
        if st.session_state.sim_scenario == "random":
            # Regenerate for continuous random operation
            st.session_state.sim_steps = []
        else:
            st.session_state.auto_sim  = False
            st.session_state.sim_phase = "idle"
            st.session_state.sim_steps = []

    time.sleep(REFRESH_INTERVAL)
    st.rerun()

elif st.session_state.listening:
    # Real mic mode — still needs refresh loop
    time.sleep(REFRESH_INTERVAL)
    st.rerun()
