# ═══════════════════════════════════════════════════════
# CONFIG — VWAP SD Scalper · XAU/USDT · BITGET
# BOT 2 — Stratégie Mean-Reversion Institutionnelle MTF
# ─────────────────────────────────────────────────────
# 4 Setups : SHORT +2SD · SHORT +3SD
#            LONG  -2SD · LONG  -3SD
# Multi-TimeFrame :
#   15m → VWAP + SD + Sweep liquidité + CDV (détection zone)
#   1m  → Bougie de rejet (confirmation entrée chirurgicale)
# ═══════════════════════════════════════════════════════

import os

# ── Clés API Bitget ─────────────────────────────────────
API_KEY    = os.environ.get("API_KEY",    "")
API_SECRET = os.environ.get("API_SECRET", "")
PASSPHRASE = os.environ.get("PASSPHRASE", "")

# ── Telegram (BOT 2 — token séparé) ────────────────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN",   "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# ── Futures ─────────────────────────────────────────────
SYMBOL    = "XAUUSDT"
LEVERAGE  = 20
OPEN_TYPE = 1   # 1 = Isolated

# ── Timeframes MTF ──────────────────────────────────────
INTERVAL_SIGNAL  = "15m"  # Analyse VWAP + détection zone SD (structure institutionnelle)
INTERVAL_CONFIRM = "1m"   # Confirmation entrée chirurgicale
CANDLES_NEEDED   = 200    # Bougies 15m (~50h — VWAP session complet + historique)
CANDLES_CONFIRM  = 20     # Bougies 1m pour confirmation (20 dernières minutes)

# ── Capital & Risk ──────────────────────────────────────
CAPITAL        = 500
RISK_PER_TRADE = 0.02   # 2% par trade = $10 sur $500
MAX_POSITIONS  = 2
MAX_MARGIN_PCT = 0.40

# ── VWAP & Bandes SD ────────────────────────────────────
TOL_SD_MULT = 0.25      # Tolérance contact SD = 0.25 × SD

# ── Détection sweep de liquidité (15m) ──────────────────
SWEEP_LOOKBACK = 4      # Bougies 15m en arrière (= 60 minutes)

# ── Confirmation 1m ─────────────────────────────────────
CONFIRM_LOOKBACK = 3    # Nombre de bougies 1m à analyser pour confirmation
                         # (3 bougies 1m = 3 dernières minutes dans la 5m en cours)

# ── CDV ─────────────────────────────────────────────────
CDV_PERIOD = 20         # Sur les bougies 5m

# ── Score minimum ───────────────────────────────────────
# Score 5m max : 9 pts (zone SD + pin bar + sweep + CDV + ATR)
# Bonus confirmation 1m : +1.5 pts si bougie 1m confirme
MIN_SCORE = 4.0

# ── RR minimum ──────────────────────────────────────────
MIN_RR = 1.2

# ── ATR ─────────────────────────────────────────────────
ATR_PERIOD = 14

# ── Runner — même logique 3 phases que Bot 1 ────────────
RUNNER_PCT       = 0.50
RUNNER_TP2_KEEP  = 0.30
RUNNER_TRAIL_ATR = 1.5
RUNNER_MAX_STALL = 4    # 4 bougies 15m = 60 minutes

# ── Sécurité ────────────────────────────────────────────
COOLDOWN_AFTER_SL = 5 * 60

# ── Drawdown protection ──────────────────────────────────
DD_LEVEL1 = 0.05
DD_LEVEL2 = 0.10
DD_LEVEL3 = 0.15
DD_PAUSE  = 3600

# ── Heures à risque réduit (UTC) ────────────────────────
REDUCED_RISK_HOURS = [6, 13, 15, 17]
REDUCED_RISK_PCT   = 0.005

# ── Loop ─────────────────────────────────────────────────
LOOP_SECONDS = 60       # 1 minute — réactif pour capter la confirmation 1m

# ── Mode ─────────────────────────────────────────────────
PAPER_MODE = True

# ── Journal N8N (BOT 2 — webhook séparé) ────────────────
N8N_WEBHOOK_URL = os.environ.get("N8N_WEBHOOK_URL", "")
