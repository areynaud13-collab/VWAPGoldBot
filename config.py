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
RISK_PER_TRADE = 0.01   # Point 6 : 1% en phase de validation = $5 sur $500.
                        # Le capital paper achète des DONNÉES, pas des profits :
                        # 1% double le nombre de trades encaissables avant que
                        # les pauses drawdown n'interrompent la collecte.
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
MIN_SCORE = 4.0         # 4.0 : 2 confirmations convergentes suffisent — données en priorité

# ── RR minimum ──────────────────────────────────────────
MIN_RR = 1.2            # Pré-filtre grossier (géométrie 15m, avant confirmation)

# ── SL & RR finaux (Point 4 — 2026-07-29) ───────────────
# Le SL est recalculé depuis l'ENTRÉE RÉELLE (close 1m de confirmation) avec
# un plancher en ATR, puis la géométrie est re-contrôlée sur TP1 ET TP2.
# Calibré sur le journal : floor 1.0 garde 72% du flux et donne +66% de marge
# au stop (médiane 0.56×ATR → 1.0×ATR). La taille de position s'ajuste
# automatiquement (risque $ constant via calc_qty_risk).
SL_ATR_MIN  = 1.0       # distance SL minimale depuis l'entrée, en ATR
MIN_RR_TP1  = 0.9       # RR minimal vers TP1 avec le SL final
MIN_RR_TP2  = 1.5       # RR minimal vers TP2 — le runner doit justifier le trade

# ── ATR ─────────────────────────────────────────────────
ATR_PERIOD = 14
MIN_ATR    = 0.40       # ATR minimum ($) — filtre session morte (asiatique 01h-06h UTC)

# ── Runner — même logique 3 phases que Bot 1 ────────────
RUNNER_PCT       = 0.50
RUNNER_TP2_KEEP  = 0.50   # Point 7 : au TP2, 50% fermé / 50% continue (spec Anna)
RUNNER_TRAIL_ATR = 1.5   # Trail = 1.5×ATR depuis highest close (plus large que VP car moves VWAP = 2×SD)
RUNNER_MAX_STALL = 20    # 20 boucles 1m = 20 min sans nouveau high close → exit runner

# ── Sécurité ────────────────────────────────────────────
COOLDOWN_AFTER_SL = 5 * 60

# ── Drawdown protection ──────────────────────────────────
DD_LEVEL1 = 0.05
DD_LEVEL2 = 0.10
DD_LEVEL3 = 0.15
DD_PAUSE  = 3600

# ── Heures à risque réduit — SUPPRIMÉ (Point 6, 2026-07-29) ──
# Remplacé par le filtre d'expansion de volatilité (VOLATILITY_SPIKE_MAX) qui
# coupe le trading quand le marché est réellement agité, au lieu de demi-trader
# sur un a priori d'horloge. Deux règles pour le même risque brouillaient la
# lecture en R du journal (pertes -2$ vs -15$ pour la même stratégie).

# ── Loop ─────────────────────────────────────────────────
LOOP_SECONDS = 60       # 1 minute — réactif pour capter la confirmation 1m

# ── Filtres de régime (Point 2 — 2026-07-29) ───────────
VOLATILITY_SPIKE_MAX  = 1.6    # ATR courant / ATR moyen max — au-delà : marché en
                               # expansion (news/parabole), mean-reversion suspendue
TREND_PERSIST_N       = 4      # fenêtre (bougies 15m) du test de tendance installée
TREND_PERSIST_K       = 3      # K closes au-delà de ±2SD sur N → trend, setup interdit
MIN_SCORE_SHORT       = 5.0    # score requis côté SHORT (vs 4.0 long) — biais haussier
                               # structurel de l'or : vendre exige plus de confluence
CONSEC_SL_LOCKOUT_N   = 2      # nb de SL consécutifs dans UNE direction → lockout
DIRECTION_LOCKOUT_SEC = 7200   # durée du lockout directionnel (2h)

# ── Anti sur-trading corrélé (Point 5 — 2026-07-29) ────
MAX_POSITIONS_PER_SIDE = 1     # jamais 2 positions simultanées dans le même sens
                               # (levier caché ×2 sur la même idée — cf. 16:09/16:10)
ENTRY_COOLDOWN_SEC     = 180   # 3 min mini entre 2 entrées de même direction :
                               # tue le mitraillage 1/min, laisse recharger un
                               # niveau qui fonctionne (le lockout borne l'échec)

# ── Mode ─────────────────────────────────────────────────
PAPER_MODE = True

# ── Journal N8N (BOT 2 — webhook séparé) ────────────────
N8N_WEBHOOK_URL = os.environ.get("N8N_WEBHOOK_URL", "")
