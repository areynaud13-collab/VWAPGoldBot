# ═══════════════════════════════════════════════════════
# CONFIG — Volume Profile Scalper · XAU/USDT · BITGET
# 3 Setups Long: VAL->POC · POC->VAH · HVN->POC
# ═══════════════════════════════════════════════════════

import os

# ── Clés API Bitget ─────────────────────────────────────
# Renseigne tes clés via les variables d'environnement Railway
# (ou directement ici pour un test local)

API_KEY    = os.environ.get("API_KEY",    "")
API_SECRET = os.environ.get("API_SECRET", "")
PASSPHRASE = os.environ.get("PASSPHRASE", "")

# ── Telegram ────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN",   "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# ── Futures ─────────────────────────────────────────────
SYMBOL    = "XAUUSDT"   # Symbole Bitget (sans tiret ni underscore)
LEVERAGE  = 20
OPEN_TYPE = 1           # 1 = Isolated (recommandé) · 2 = Cross

# ── Timeframes MTF ──────────────────────────────────────
INTERVAL_SIGNAL  = "15m"  # Analyse VP + EMA + ATR (structure institutionnelle)
INTERVAL_CONFIRM = "1m"   # Confirmation entrée chirurgicale (bougie de rejet)
CANDLES_CONFIRM  = 20     # Bougies 1m pour confirmation (20 dernières minutes)

# ── Capital & Risk ──────────────────────────────────────
CAPITAL        = 500
RISK_PER_TRADE = 0.02   # 2% par trade = $10 sur $500
MIN_RISK_PCT   = 0.005  # Risque minimum réel = 0.5% — en dessous : position annulée (inutile)
MAX_POSITIONS  = 2      # 2 positions simultanées max
MAX_MARGIN_PCT = 0.40   # Marge max utilisée par position = 40% du capital

# ── Volume Profile ──────────────────────────────────────
VP_LOOKBACK = 60        # Fenêtre glissante (bougies)
VP_BINS     = 48        # Bins de prix (résolution doublée → HVN plus précis ~$4/bin)
VALUE_PCT   = 0.70      # Value Area = 70% du volume

# ── Entrée ──────────────────────────────────────────────
TOL_MULT    = 0.8       # Tolérance autour VAL/POC (x ATR)
MIN_SCORE   = 5.0       # Score minimum /8 (relevé 4→5 pour plus de sélectivité)
MIN_RR      = 1.0       # RR minimum
MIN_RANGE   = 0.5       # Distance min POC-VAL (x ATR)
VOL_MULT    = 1.2       # Volume spike

# ── CDV (Cumulative Delta Volume) ───────────────────────
CDV_PERIOD  = 30

# ── SL / TP ─────────────────────────────────────────────
ATR_PERIOD  = 14
ATR_SL      = 1.2       # SL = 1.2x ATR
ATR_TP1     = 1.8       # TP1 = 1.8x ATR → RR 1:1.5 → WR min 40%
MIN_SL_DIST = 0.30      # Distance SL minimale absolue ($) — garde-fou secondaire
MIN_ATR     = 0.40      # ATR minimum ($) — filtre session morte (asiatique 01h-06h UTC)
                         # En dessous : TP potentiel < frais → on ne trade pas

# ── Runner — stratégie 3 phases ─────────────────────────
# Phase 1 : SL initial, les 2 lots exposés, cible TP1
# Phase 2 : Lot 1 fermé au TP1, Lot 2 continue avec SL = TP1 (profit garanti)
# Phase 3 : TP2 (POC) atteint → runner activé, SL plancher = TP2
#           Chandelier Exit : trail depuis highest close - 1.5× ATR
#           (close et non high pour filtrer les mèches de l'or 1m)
#           Time exit : si 15 bougies sans nouveau plus haut close → fermeture marché
RUNNER_PCT        = 0.50   # 50% des contrats gardés comme runner (Lot 2)
RUNNER_TRAIL_ATR  = 1.5    # Chandelier Exit : highest_close - 1.5× ATR
RUNNER_MAX_STALL  = 15     # Bougies max sans nouveau plus haut avant time exit

# ── Sécurité ────────────────────────────────────────────
COOLDOWN_AFTER_SL = 5 * 60   # 5 min pause après SL

# ── Drawdown protection ──────────────────────────────────
DD_LEVEL1       = 0.05   # 5%  → score min monte à 5.0 (plus sélectif)
DD_LEVEL2       = 0.10   # 10% → VAL->POC risque 1% au lieu de 2%
DD_LEVEL3       = 0.15   # 15% → pause complète 1h
DD_PAUSE        = 3600   # Durée pause niveau 3 (secondes)

# ── Heures à risque réduit (UTC) ────────────────────────
REDUCED_RISK_HOURS = [6, 13, 15, 17]
REDUCED_RISK_PCT   = 0.005   # 0.5% au lieu de 2%

# ── Loop ─────────────────────────────────────────────────
LOOP_SECONDS   = 60
CANDLES_NEEDED = 200    # 15m candles — VP 60 + EMA50 + ATR + marge (~50h)
CONFIRM_LOOKBACK = 3    # Bougies 1m analysées pour confirmation entrée

# ── Mode ─────────────────────────────────────────────────
# Mettre à False uniquement quand vous êtes prêt à trader en réel
PAPER_MODE = True

# ── Journal de Trading N8N (optionnel) ───────────────────
# Renseigne l'URL de ton webhook N8N pour activer le journal automatique
# Laisser vide ("") pour désactiver
N8N_WEBHOOK_URL = os.environ.get("N8N_WEBHOOK_URL", "")
