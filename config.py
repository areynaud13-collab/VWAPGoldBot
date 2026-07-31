# ═══════════════════════════════════════════════════════
# CONFIG — VWAP ±1SD Scalper · XAU/USDT · BITGET
# Version haute fréquence — 15-25 signaux/jour
# ─────────────────────────────────────────────────────
# Setups : SHORT +1SD → VWAP · LONG -1SD → VWAP
# Multi-TimeFrame : 5m détection · 1m confirmation
# ═══════════════════════════════════════════════════════

import os

# ── Clés API Bitget ──────────────────────────────────────
API_KEY    = os.environ.get("API_KEY",    "")
API_SECRET = os.environ.get("API_SECRET", "")
PASSPHRASE = os.environ.get("PASSPHRASE", "")

# ── Telegram ─────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN",   "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# ── Futures ──────────────────────────────────────────────
SYMBOL    = "XAUUSDT"
LEVERAGE  = 20
OPEN_TYPE = 1   # 1 = Isolated

# ── Timeframes MTF ───────────────────────────────────────
INTERVAL_SIGNAL  = "5m"   # Détection zone ±1SD (plus réactif que 15m)
INTERVAL_CONFIRM = "1m"   # Confirmation bougie de rejet
CANDLES_NEEDED   = 100    # Bougies 5m (~8h — suffisant pour VWAP session)
CANDLES_CONFIRM  = 10     # Bougies 1m pour confirmation

# ── Capital & Risk ───────────────────────────────────────
CAPITAL        = 500
RISK_PER_TRADE = 0.01     # 1% par trade = 5$ sur 500$ — phase validation
MAX_POSITIONS  = 2        # Max 2 positions simultanées
MAX_MARGIN_PCT = 0.40

# ── VWAP & Bandes SD ─────────────────────────────────────
# ±1SD se touche 15-25x/jour → source principale de signaux
# ±2SD utilisé comme bonus de score uniquement
TOL_SD_MULT = 0.20        # Tolérance contact SD = 0.20 × SD (légèrement plus serré)

# ── Confirmation 1m ──────────────────────────────────────
CONFIRM_LOOKBACK = 3      # 3 dernières bougies 1m analysées

# ── CDV ──────────────────────────────────────────────────
CDV_PERIOD = 20

# ── Score minimum ────────────────────────────────────────
# Score max possible : ~8.5 pts (contact SD + pin bar + CDV + ATRok + bonus 2SD + conf 1m)
# Seuil abaissé vs bot ±2SD car ±1SD est intrinsèquement moins rare → on accepte
# moins de confluence pour plus de fréquence, mais la confirmation 1m reste obligatoire.
MIN_SCORE       = 3.5     # Seuil LONG (biais haussier structurel de l'or)
MIN_SCORE_SHORT = 4.0     # Seuil SHORT légèrement plus exigeant

# ── RR minimum ───────────────────────────────────────────
MIN_RR     = 0.8          # Pré-filtre géométrique (distance TP/SL estimée)
MIN_RR_TP1 = 0.7          # RR minimal après recalcul SL depuis entrée réelle
                          # Note : ±1SD → VWAP = distance plus courte que ±2SD → VWAP
                          # Le RR est plus faible mais la fréquence compense

# ── SL ───────────────────────────────────────────────────
SL_ATR_BUFFER = 0.25      # Buffer au-delà de la bande SD pour le SL structurel
SL_ATR_MIN    = 0.70      # Distance SL minimale depuis l'entrée, en ATR
                          # (plus serré que ±2SD car moves ±1SD sont plus courts)

# ── ATR ──────────────────────────────────────────────────
ATR_PERIOD = 14
MIN_ATR    = 0.30         # ATR minimum ($) — légèrement plus bas que v1
                          # pour capter les sessions London en début de journée

# ── Runner ───────────────────────────────────────────────
RUNNER_PCT       = 0.50   # 50% du lot total en runner
RUNNER_TP2_KEEP  = 0.50   # Au TP2 : 50% fermé, 50% continue
RUNNER_TRAIL_ATR = 1.2    # Trail plus serré (moves ±1SD → VWAP plus courts)
RUNNER_MAX_STALL = 15     # 15 bougies 1m sans nouveau high → exit runner

# ── Sécurité ─────────────────────────────────────────────
COOLDOWN_AFTER_SL = 3 * 60   # 3 min après un SL (vs 5 min v1 — plus réactif)

# ── Drawdown protection ───────────────────────────────────
DD_LEVEL1 = 0.05
DD_LEVEL2 = 0.10
DD_LEVEL3 = 0.15
DD_PAUSE  = 3600          # 1h de pause complète au niveau 3

# ── Loop ─────────────────────────────────────────────────
LOOP_SECONDS = 60         # Vérification toutes les 60 secondes

# ── Filtres de régime ─────────────────────────────────────
VOLATILITY_SPIKE_MAX = 1.8    # ATR courant / ATR moyen max avant suspension
TREND_PERSIST_N      = 3      # Fenêtre test tendance installée (bougies 5m)
TREND_PERSIST_K      = 2      # K closes au-delà de ±1SD sur N → tendance, skip

# ── Détecteur de régime tendanciel (Audit 2) ─────────────
# Si N bougies 5m consécutives dans le même sens ET move > mult×ATR
# → régime tendanciel → mean-reversion suspendue dans ce sens
# Evite les 8 pertes consécutives LONG dans une journée baissière
REGIME_CANDLES_N  = 3         # Nombre de bougies consécutives à analyser
REGIME_ATR_MULT   = 1.5       # Move total minimum en ATR pour confirmer la tendance

# ── Filtre session (Audit 2) ──────────────────────────────
# London 07h-12h UTC + New York 13h-17h UTC uniquement
# Session asiatique exclue : liquidité faible, stops dans le bruit
# Paramétré dans strategy.py / is_trading_session()

# ── SL minimum absolu (Audit 2) ──────────────────────────
# Sur XAU, le bruit normal = 2-4$ par minute.
# Un SL < 5$ se fait toucher par le bruit avant le vrai move.
SL_MIN_ABS = 5.0              # Distance SL minimale en $ absolu depuis l'entrée

# ── Anti-clustering ──────────────────────────────────────
MAX_POSITIONS_PER_SIDE = 1    # Jamais 2 positions dans le même sens simultanément
ENTRY_COOLDOWN_SEC     = 120  # 2 min entre 2 entrées de même direction

# ── Lockout directionnel ──────────────────────────────────
CONSEC_SL_LOCKOUT_N   = 3     # 3 SL consécutifs dans une direction → lockout
                               # (vs 2 en v1 — ±1SD plus fréquent donc tolérance plus haute)
DIRECTION_LOCKOUT_SEC = 3600  # 1h de lockout (vs 2h en v1)

# ── Mode ──────────────────────────────────────────────────
PAPER_MODE = True             # ← Toujours True pour le backtest paper

# ── Journal N8N ───────────────────────────────────────────
N8N_WEBHOOK_URL = os.environ.get("N8N_WEBHOOK_URL", "")
