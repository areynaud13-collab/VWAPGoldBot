# ═══════════════════════════════════════════════════════
# BOT 2 — VWAP SD SCALPER · XAU/USDT · BITGET · MTF
# Stratégie mean-reversion institutionnelle
# ─────────────────────────────────────────────────────
# 4 Setups : SHORT +2SD / +3SD · LONG -2SD / -3SD
# Multi-TimeFrame :
#   15m → VWAP + SD + Sweep liquidité + CDV (détection)
#   1m  → Bougie de rejet (confirmation entrée chirurgicale)
# Gestion : 3 phases · Lot 1 → TP1(VWAP) · Runner → ±1SD
# ═══════════════════════════════════════════════════════

import time
import logging
import threading
import requests as req
from datetime import datetime, date, timezone
from zoneinfo import ZoneInfo
from config import *

# Fuseau horaire Suisse (UTC+1 hiver / UTC+2 été — DST automatique)
TZ_SWISS = ZoneInfo("Europe/Zurich")
from strategy import calc_signal
import bitget as exchange
import dashboard


# ── N8N Journal ────────────────────────────────────────
def _sheet_safe(value):
    """
    Anti-formule Google Sheets — Ajout 2026-07-29.
    En mode USER_ENTERED, une cellule commençant par '=', '+', '-' ou '@'
    est interprétée comme une formule → #ERROR!. C'est exactement ce qui
    corrompait le champ Setup des shorts ('+2SD→+1SD'). On préfixe d'une
    apostrophe : Sheets stocke alors le texte tel quel.
    """
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@"):
        return "'" + value
    return value


def notify_n8n(pos, event_type, pnl_lot1, pnl_lot2, total_pnl, phase_atteinte, resultat, exit_price=None):
    """Envoie les données du trade au webhook N8N Bot 2 → Google Sheets."""
    if not N8N_WEBHOOK_URL:
        return
    try:
        # FIX 2026-07-29 : la colonne s'appelle Heure_UTC mais recevait l'heure
        # SUISSE (UTC+2 en été) → toutes les analyses par session étaient
        # décalées de 2h. On journalise désormais en vrai UTC.
        now        = datetime.now(timezone.utc)
        entry_time = pos.get("entry_time", now)
        if entry_time.tzinfo is not None:
            entry_time = entry_time.astimezone(timezone.utc)
        duree      = int((now - entry_time).total_seconds() / 60)
        tp2        = pos.get("tp_poc", pos["tp"])
        data = {
            "Date":                now.strftime("%Y-%m-%d"),
            "Heure_UTC":           entry_time.strftime("%H:%M"),
            "Bot":                 "BOT2_VWAP",
            "Type":                event_type,
            "Setup":               _sheet_safe(pos.get("setup", "VWAP")),
            "Score":               pos.get("score", 0),
            "Entree":              pos["entry"],
            "SL":                  pos["sl"],
            "TP1":                 pos["tp"],
            "TP2":                 tp2,
            "VWAP":                pos.get("vwap", ""),
            "SD":                  pos.get("sd", ""),
            "ATR":                 pos.get("atr", 0),
            "RR_Cible":            pos.get("rr", 0),
            "Phase_Atteinte":      phase_atteinte,
            "Resultat":            resultat,
            "PnL_Lot1":            round(pnl_lot1, 2),
            "PnL_Lot2":            round(pnl_lot2, 2),
            "PnL_Total":           round(total_pnl, 2),
            "Capital_Avant":       round(pos.get("capital_at_entry", 0), 2),
            "Capital_Apres":       round(state.paper_balance, 2),
            # Point 6 : risque effectif tracé → chaque trade lisible en R
            "Risque_USD":          round(pos.get("risk_usd", 0), 2),
            "Risque_Pct":          round(pos.get("risk_usd", 0)
                                          / pos["capital_at_entry"] * 100, 2)
                                    if pos.get("capital_at_entry") else 0,
            "Duree_min":           duree,
            "Prix_Sortie_Runner":  round(exit_price, 2) if event_type == "CLOSE_RUNNER" and exit_price is not None else "",
            "Runner_Bonus_vs_TP2": round(exit_price - tp2, 2) if event_type == "CLOSE_RUNNER" and exit_price is not None else "",
        }
        req.post(N8N_WEBHOOK_URL, json=data, timeout=5)
    except Exception as e:
        log.warning(f"N8N webhook erreur: {e}")


# ── Journal des signaux bloqués (Point 2b — shadow log) ──
# Objectif : mesurer ce que les filtres coûtent en fréquence au lieu de le
# deviner. Chaque setup détecté mais refusé écrit une ligne SIGNAL_BLOQUE
# dans le Google Sheet (throttle : 1 ligne max par motif / 15 min).
BLOCK_PATTERNS = ("Expansion volatilité", "installé", "confirmation 1m absente",
                  "Lockout", "DD N", "Anti-cluster", "KILL SWITCH", "RR insuffisant")


def block_category(reason):
    """Retourne la catégorie de blocage si le motif en est un, sinon None."""
    for p in BLOCK_PATTERNS:
        if p in reason:
            return p
    return None


def notify_n8n_blocked(reason, price=0.0):
    """Ligne SIGNAL_BLOQUE dans le journal — mêmes colonnes, valeurs neutres."""
    if not N8N_WEBHOOK_URL:
        return
    try:
        now = datetime.now(timezone.utc)
        data = {
            "Date":                now.strftime("%Y-%m-%d"),
            "Heure_UTC":           now.strftime("%H:%M"),
            "Bot":                 "BOT2_VWAP",
            "Type":                "SIGNAL_BLOQUE",
            "Setup":               _sheet_safe(str(reason)[:120]),
            "Score":               0,
            "Entree":              price,
            "SL":                  0, "TP1": 0, "TP2": 0,
            "VWAP":                "", "SD": "",
            "ATR":                 0, "RR_Cible": 0,
            "Phase_Atteinte":      0,
            "Resultat":            "BLOQUE",
            "PnL_Lot1":            0, "PnL_Lot2": 0, "PnL_Total": 0,
            "Capital_Avant":       round(state.paper_balance, 2),
            "Capital_Apres":       round(state.paper_balance, 2),
            "Risque_USD":          0,
            "Risque_Pct":          0,
            "Duree_min":           0,
            "Prix_Sortie_Runner":  "",
            "Runner_Bonus_vs_TP2": "",
        }
        req.post(N8N_WEBHOOK_URL, json=data, timeout=5)
    except Exception as e:
        log.warning(f"N8N shadow log erreur: {e}")


# ── Telegram ────────────────────────────────────────────
def tg(msg):
    try:
        req.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=5
        )
    except Exception as e:
        log.warning(f"Telegram erreur: {e}")


# ── Logging ────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)s │ %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot2.log", encoding="utf-8"),
    ]
)
log = logging.getLogger("bot2")


# ── État partagé ───────────────────────────────────────
class State:
    def __init__(self):
        self.positions      = []
        self.last_price     = 0.0
        self.paper_balance  = float(CAPITAL)
        self.paper_pnl      = 0.0
        self.paper_mode     = PAPER_MODE
        self.total_trades   = 0
        self.wins           = 0
        self.losses         = 0
        self.breakevens     = 0
        self.daily_pnl      = 0.0
        self.daily_trades   = 0
        self.start_date     = date.today()
        self.contract_size  = 0.01
        self.last_sl_time   = 0
        self.peak_capital   = float(CAPITAL)
        self.dd_level       = 0
        self.dd_pause_until = 0
        # Point 2 (2026-07-29) : lockout directionnel — N SL consécutifs
        # dans une direction = cette direction se trompe de régime → on la
        # coupe temporairement au lieu de re-perdre au même endroit.
        self.consec_sl         = {"long": 0, "short": 0}
        self.side_lockout_until = {"long": 0.0, "short": 0.0}
        self.last_block_log     = {"motif": "", "ts": 0.0}   # throttle shadow log
        self.last_entry_time    = {"long": 0.0, "short": 0.0}  # anti-cluster (Pt5)

    def reset_daily(self):
        if date.today() != self.start_date:
            log.info(f"Nouveau jour · P&L hier: {self.daily_pnl:+.2f}$")
            self.daily_pnl    = 0.0
            self.daily_trades = 0
            self.start_date   = date.today()

    @property
    def wr(self):
        t = self.wins + self.losses
        return self.wins / t * 100 if t > 0 else 0.0

    @property
    def capital(self):
        if PAPER_MODE:
            return self.paper_balance
        try:
            return exchange.get_balance()
        except:
            return self.paper_balance


state  = State()
trades = []


def calc_qty_risk(price, sl_price, risk_pct):
    cap      = state.capital
    risk_usd = cap * risk_pct
    sl_dist  = abs(price - sl_price)
    if sl_dist <= 0:
        return 1
    contracts_by_risk   = risk_usd / (sl_dist * state.contract_size * LEVERAGE)
    margin_per_contract = (price * state.contract_size) / LEVERAGE
    max_margin          = cap * MAX_MARGIN_PCT
    contracts_by_margin = max_margin / margin_per_contract if margin_per_contract > 0 else contracts_by_risk
    return max(1, int(min(contracts_by_risk, contracts_by_margin)))


def validate_signal(sig):
    """
    KILL SWITCH — Ajout 2026-07-29.
    Aucun ordre ne part si le signal est incomplet ou incohérent.
    Retourne (ok: bool, motif: str).
    """
    required = ("signal", "price", "sl_price", "tp_price", "atr", "setup", "score")
    for k in required:
        v = sig.get(k)
        if v is None or (isinstance(v, str) and not v.strip()):
            return False, f"champ manquant/vide: {k}"

    setup = str(sig.get("setup", ""))
    if "ERROR" in setup.upper() or setup.startswith(("=", "+")):
        return False, f"label setup invalide: {setup!r}"

    side  = sig["signal"]
    price = sig["price"]
    sl    = sig["sl_price"]
    tp1   = sig["tp_price"]
    tp2   = sig.get("tp_poc", tp1)

    for name, v in (("price", price), ("sl", sl), ("tp1", tp1), ("tp2", tp2)):
        if not isinstance(v, (int, float)) or v != v or v <= 0:  # v != v → NaN
            return False, f"prix invalide: {name}={v!r}"

    # Cohérence géométrique stricte selon la direction
    if side == "long":
        if not (sl < price < tp1):
            return False, f"géométrie LONG incohérente: SL {sl} < entrée {price} < TP1 {tp1} non respecté"
    elif side == "short":
        if not (tp1 < price < sl):
            return False, f"géométrie SHORT incohérente: TP1 {tp1} < entrée {price} < SL {sl} non respecté"
    else:
        return False, f"direction inconnue: {side!r}"

    return True, ""


def open_position(sig, dd_level=0):
    if len(state.positions) >= MAX_POSITIONS:
        return

    # ── KILL SWITCH : signal invalide = zéro ordre, alerte immédiate ──
    ok, motif = validate_signal(sig)
    if not ok:
        log.error(f"[KILL SWITCH] Signal rejeté — {motif} | sig={sig}")
        tg(f"🛑 <b>BOT 2 — KILL SWITCH</b>\nSignal rejeté avant ordre :\n{motif}")
        return f"KILL SWITCH: {motif}"

    side_str = sig["signal"]

    # ── Anti sur-trading corrélé (Point 5) ──
    if sum(1 for p in state.positions if p["side"] == side_str) >= MAX_POSITIONS_PER_SIDE:
        return (f"Anti-cluster: déjà {MAX_POSITIONS_PER_SIDE} position {side_str.upper()} "
                f"ouverte — pas de doublement du risque sur la même idée")
    _since = time.time() - state.last_entry_time.get(side_str, 0.0)
    if _since < ENTRY_COOLDOWN_SEC:
        return (f"Anti-cluster: cooldown entrée {side_str.upper()} — "
                f"encore {int(ENTRY_COOLDOWN_SEC - _since)}s")

    price    = sig["price"]
    atr      = sig["atr"]
    sl       = sig["sl_price"]
    tp       = sig["tp_price"]     # TP1 = VWAP
    tp_poc   = sig.get("tp_poc", tp)   # TP2 = ±1SD opposé
    score    = sig["score"]
    reason   = sig["reason"]
    rr       = sig.get("rr", round(abs(tp - price) / max(abs(price - sl), 0.01), 1))
    setup    = sig.get("setup", "VWAP")
    vwap     = sig.get("vwap", 0)
    sd       = sig.get("sd", 0)
    sd2_h    = sig.get("sd2_h", 0)
    sd3_h    = sig.get("sd3_h", 0)
    sd2_l    = sig.get("sd2_l", 0)
    sd3_l    = sig.get("sd3_l", 0)

    # ── Point 6 (2026-07-29) : risque de base UNIQUE ──
    # REDUCED_RISK_HOURS supprimé : réduire la mise sur un soupçon horaire
    # brouillait la lecture en R du journal (pertes -2$ vs -15$). Le filtre
    # d'expansion de volatilité (Pt2) fait ce travail en mieux : il coupe
    # quand le marché est RÉELLEMENT agité — mesure, pas horloge.
    # Seuls les paliers de drawdown modulent encore le risque (design assumé,
    # désormais tracé dans le journal via Risque_Pct / Risque_USD).
    if dd_level >= 2:
        effective_risk = RISK_PER_TRADE / 2
        log.info(f"DD N{dd_level} — risque réduit à {RISK_PER_TRADE / 2 * 100:.2f}%")
    else:
        effective_risk = RISK_PER_TRADE

    total_contracts = calc_qty_risk(price, sl, effective_risk)
    if total_contracts >= 2:
        runner_contracts = max(1, int(total_contracts * RUNNER_PCT))
        lot1_contracts   = total_contracts - runner_contracts
    else:
        runner_contracts = 0
        lot1_contracts   = total_contracts

    # ── Garde : TP2 doit être au-delà de TP1 dans le bon sens ──
    if (side_str == "long"  and tp_poc <= tp) or \
       (side_str == "short" and tp_poc >= tp):
        log.warning(f"[Guard] TP2 {tp_poc} invalide vs TP1 {tp} ({setup}) — runner désactivé")
        runner_contracts = 0
        lot1_contracts   = total_contracts

    cap_now   = state.capital
    risk_real = abs(price - sl) * total_contracts * state.contract_size * LEVERAGE
    risk_pct  = risk_real / cap_now * 100

    log.info("")
    log.info("=" * 60)
    log.info(f"SIGNAL {side_str.upper()} {setup} · Score {score} · Slot {len(state.positions)+1}/{MAX_POSITIONS}")
    log.info(f"   Prix : ${price:.2f} · SL: ${sl:.2f} · TP1(VWAP): ${tp:.2f} · TP2: ${tp_poc:.2f}")
    log.info(f"   VWAP : {vwap:.2f} · SD : {sd:.2f}")
    log.info(f"   Bandes : +2SD={sd2_h:.2f} +3SD={sd3_h:.2f} -2SD={sd2_l:.2f} -3SD={sd3_l:.2f}")
    log.info(f"   RR   : 1:{rr} · Total: {total_contracts}c (Lot1: {lot1_contracts} + Runner: {runner_contracts})")
    log.info(f"   Risque: {risk_pct:.1f}% = ${risk_real:.2f} · Mode: {'PAPER' if PAPER_MODE else 'LIVE'}")
    log.info("=" * 60)

    tg(
        f"{'🔴' if side_str == 'short' else '🟢'} <b>BOT 2 — SIGNAL {side_str.upper()} XAU/USDT — {setup}</b>\n"
        f"\n"
        f"📍 Entrée        : <b>${price:.2f}</b>\n"
        f"🛑 SL            : ${sl:.2f}\n"
        f"🎯 TP1 (±1SD)   : ${tp:.2f}  ← objectif scalping\n"
        f"🏃 TP2 (runner s'active ici) : ${tp_poc:.2f}\n"
        f"\n"
        f"📐 <b>Contexte VWAP</b>\n"
        f"   VWAP  : {vwap:.2f}   SD : {sd:.2f}\n"
        f"   +2SD  : {sd2_h:.2f}   +3SD : {sd3_h:.2f}\n"
        f"   -2SD  : {sd2_l:.2f}   -3SD : {sd3_l:.2f}\n"
        f"\n"
        f"📊 RR 1:{rr}  · Score {score}/9\n"
        f"💼 Lot 1 : {lot1_contracts} contrats → ferme au TP1\n"
        f"🏃 Lot 2 : {runner_contracts} contrats → runner s'active AU TP2\n"
        f"⚠️  Risque : {risk_pct:.1f}% = ${risk_real:.2f}\n"
        f"💰 Capital : ${cap_now:.2f}\n"
        f"{'📄 PAPER MODE' if PAPER_MODE else '💰 LIVE BITGET'}"
    )

    position_id = None
    if not PAPER_MODE:
        try:
            bg_side = 1 if side_str == "long" else 3
            order = exchange.place_order(bg_side, total_contracts)
            log.info(f"Ordre Bitget: {order}")
            time.sleep(1)
            open_pos = exchange.get_open_positions(SYMBOL)
            if open_pos:
                position_id = open_pos[-1].get("positionId")
                if position_id:
                    exchange.set_stop_loss_take_profit(position_id, sl, tp)
        except Exception as e:
            log.error(f"Erreur ordre: {e}")
            return

    state.positions.append({
        "side":             side_str,
        "entry":            price,
        "sl":               sl,
        "tp":               tp,
        "tp_poc":           tp_poc,
        "tp_runner":        sig.get("tp_runner", tp_poc),   # objectif runner (Pt7)
        "atr":              atr,
        "vwap":             vwap,
        "sd":               sd,
        "contracts":        total_contracts,
        "lot1_contracts":   lot1_contracts,
        "runner_contracts": runner_contracts,
        "phase":            1,
        "runner_active":    False,
        "runner_sl":        None,
        "highest_close":    0.0,
        "runner_stall":     0,
        "tp1_pnl":          0.0,
        "capital_at_entry": cap_now,
        "risk_usd":         risk_real,
        "position_id":      position_id,
        "setup":            setup,
        "score":            score,
        "entry_time":       datetime.now(TZ_SWISS),
        "rr":               rr,
    })
    state.daily_trades += 1
    state.total_trades += 1
    state.last_entry_time[side_str] = time.time()   # anti-cluster (Pt5)


def check_exits(current_price, last_candle=None):
    if not state.positions:
        return

    candle_high  = last_candle["high"]  if last_candle else current_price
    candle_low   = last_candle["low"]   if last_candle else current_price
    candle_close = last_candle["close"] if last_candle else current_price

    still_open = []
    for pos in state.positions:
        ep        = pos["entry"]
        atr       = pos["atr"]
        setup     = pos["setup"]
        cap_entry = pos.get("capital_at_entry", state.paper_balance)
        phase     = pos.get("phase", 1)

        # ══════════════════════════════════════════════════
        # PHASE 2 — Lot 2 seul, SL = TP1, cible TP2
        # ══════════════════════════════════════════════════
        if phase == 2:
            sl_lot2          = pos["tp"]
            tp2_price        = pos["tp_poc"]
            runner_contracts = pos["runner_contracts"]
            tp1_pnl          = pos.get("tp1_pnl", 0.0)

            if pos["side"] == "long":
                hit_sl  = candle_low  <= sl_lot2
                hit_tp2 = candle_high >= tp2_price
            else:
                hit_sl  = candle_high >= sl_lot2
                hit_tp2 = candle_low  <= tp2_price

            if hit_sl and hit_tp2:
                hit_tp2 = True   # TP2 prioritaire

            if hit_tp2:
                actual_runner = max(1, int(runner_contracts * RUNNER_TP2_KEEP))
                close_at_tp2  = runner_contracts - actual_runner

                pnl_tp2_close = 0.0
                if close_at_tp2 > 0:
                    raw_tp2 = (tp2_price - ep) / ep if pos["side"] == "long" else (ep - tp2_price) / ep
                    pnl_tp2_close = raw_tp2 * close_at_tp2 * state.contract_size * ep * LEVERAGE
                    if not PAPER_MODE:
                        try:
                            close_side = 2 if pos["side"] == "long" else 4
                            exchange.place_order(close_side, close_at_tp2)
                        except Exception as e:
                            log.error(f"Fermeture partielle TP2 error: {e}")
                    state.paper_balance += pnl_tp2_close
                    state.paper_pnl     += pnl_tp2_close
                    state.daily_pnl     += pnl_tp2_close
                    pos["tp1_pnl"]      += pnl_tp2_close

                pos["runner_contracts"] = actual_runner
                pos["phase"]            = 3
                pos["runner_active"]    = True
                # Point 7 (spec Anna) : plancher du runner = TP1, jamais en
                # dessous. Le runner respire entre TP1 et son objectif ;
                # retour sur TP1 → fermeture (profit TP1 toujours préservé).
                pos["runner_sl"]        = pos["tp"]
                pos["highest_close"]    = candle_close
                pos["runner_stall"]     = 0

                log.info(f"[Ph2→3] TP2 ${tp2_price:.2f} atteint · "
                         f"{close_at_tp2}c fermés +${pnl_tp2_close:.2f}$ · Runner: {actual_runner}c")
                tg(
                    f"🚀 <b>BOT 2 — TP2 ATTEINT — {setup}</b>\n"
                    f"\n"
                    f"📍 Entrée         : ${ep:.2f}\n"
                    f"✅ TP1 (±1SD)    : ${pos['tp']:.2f}   P&L: +${tp1_pnl:.2f}$\n"
                    f"✅ TP2 (70% Lot2) : ${tp2_price:.2f}  P&L: +${pnl_tp2_close:.2f}$\n"
                    f"\n"
                    f"🏃 <b>Runner actif</b> : {actual_runner} contrats (30% Lot 2)\n"
                    f"🛡️ SL plancher    : ${pos['tp']:.2f} (TP1 — jamais en dessous)\n"
                    f"🎯 Objectif runner : ${pos.get('tp_runner', tp2_price):.2f}\n"
                    f"📏 Chandelier     : {RUNNER_TRAIL_ATR}× ATR\n"
                    f"⏱️ Time exit      : {RUNNER_MAX_STALL} bougies 15m sans nouveau haut\n"
                    f"📈 Capital        : ${state.paper_balance:.2f}\n"
                    f"{'📄 PAPER MODE' if PAPER_MODE else '💰 LIVE BITGET'}"
                )
                still_open.append(pos)
                continue

            if hit_sl:
                exit_price = sl_lot2
                raw_pnl    = (exit_price - ep) / ep if pos["side"] == "long" else (ep - exit_price) / ep
                pnl_lot2   = raw_pnl * runner_contracts * state.contract_size * ep * LEVERAGE
                total_pnl  = tp1_pnl + pnl_lot2
                acct_pct   = total_pnl / cap_entry * 100 if cap_entry else 0

                if not PAPER_MODE:
                    try:
                        close_side = 2 if pos["side"] == "long" else 4
                        exchange.place_order(close_side, runner_contracts)
                    except Exception as e:
                        log.error(f"Fermeture Lot 2 error: {e}")
                        still_open.append(pos)
                        continue

                state.paper_balance += pnl_lot2
                state.paper_pnl     += pnl_lot2
                state.daily_pnl     += pnl_lot2
                state.wins          += 1
                state.consec_sl[pos["side"]] = 0

                trades.append({"e": ep, "x": exit_price, "side": pos["side"],
                               "pnl": round(total_pnl, 2), "res": "TP1×2 (retour SL Lot 2)",
                               "setup": setup, "date": datetime.now().strftime("%m/%d %H:%M")})
                notify_n8n(pos, "CLOSE_LOT2_TP1", tp1_pnl, pnl_lot2, total_pnl, 2, "WIN")

                tg(
                    f"✅ <b>BOT 2 — LOT 2 FERMÉ au retour TP1 — {setup}</b>\n"
                    f"\n"
                    f"📍 Entrée      : ${ep:.2f}\n"
                    f"✅ TP1 (Lot 1) : ${pos['tp']:.2f}   P&L: +${tp1_pnl:.2f}$\n"
                    f"🛑 SL Lot 2    : ${exit_price:.2f}  P&L: +${pnl_lot2:.2f}$\n"
                    f"💰 P&L total   : <b>+{total_pnl:.2f}$</b>  ({acct_pct:+.2f}%)\n"
                    f"📈 Capital     : ${state.paper_balance:.2f}\n"
                    f"🎯 Win Rate    : {state.wr:.0f}%  ({state.wins}W / {state.losses}L)\n"
                    f"{'📄 PAPER MODE' if PAPER_MODE else '💰 LIVE BITGET'}"
                )
                continue

            still_open.append(pos)
            continue

        # ══════════════════════════════════════════════════
        # PHASE 3 — Runner seul · Trailing stop ATR · Stall timer
        # ══════════════════════════════════════════════════
        elif phase == 3:
            runner_sl    = pos["runner_sl"]
            act_runner   = pos["runner_contracts"]
            tp1_pnl      = pos.get("tp1_pnl", 0.0)
            hc           = pos.get("highest_close", candle_close)
            stall        = pos.get("runner_stall", 0)
            atr          = pos["atr"]

            tp_runner = pos.get("tp_runner", pos["tp_poc"])
            if pos["side"] == "long":
                hit_runner_sl = candle_low  <= runner_sl
                hit_tp3       = candle_high >= tp_runner
                new_progress  = candle_close > hc
            else:
                hit_runner_sl = candle_high >= runner_sl
                hit_tp3       = candle_low  <= tp_runner
                new_progress  = candle_close < hc

            # ── Point 7 : objectif runner atteint → clôture au TP3 ──
            if hit_tp3:
                exit_price  = tp_runner
                raw_pnl     = (exit_price - ep) / ep if pos["side"] == "long" else (ep - exit_price) / ep
                pnl_runner  = raw_pnl * act_runner * state.contract_size * ep * LEVERAGE
                total_pnl   = tp1_pnl + pnl_runner
                acct_pct    = total_pnl / cap_entry * 100 if cap_entry else 0

                if not PAPER_MODE:
                    try:
                        close_side = 2 if pos["side"] == "long" else 4
                        exchange.place_order(close_side, act_runner)
                    except Exception as e:
                        log.error(f"Fermeture Runner TP3 error: {e}")
                        still_open.append(pos)
                        continue

                state.paper_balance += pnl_runner
                state.paper_pnl     += pnl_runner
                state.daily_pnl     += pnl_runner
                state.wins          += 1
                state.consec_sl[pos["side"]] = 0

                trades.append({"e": ep, "x": exit_price, "side": pos["side"],
                               "pnl": round(total_pnl, 2), "res": "Runner (Objectif TP3)",
                               "setup": setup, "date": datetime.now().strftime("%m/%d %H:%M")})
                notify_n8n(pos, "CLOSE_RUNNER", tp1_pnl, pnl_runner, total_pnl, 3, "WIN", exit_price)

                log.info(f"[Ph3→FIN] Runner OBJECTIF TP3 ${exit_price:.2f} · "
                         f"P&L runner: {pnl_runner:+.2f}$ · P&L total: {total_pnl:+.2f}$")
                tg(
                    f"🏆 <b>BOT 2 — RUNNER : OBJECTIF ATTEINT — {setup}</b>\n"
                    f"\n"
                    f"📍 Entrée      : ${ep:.2f}\n"
                    f"🎯 TP3 (bande) : ${exit_price:.2f}\n"
                    f"💰 P&L runner  : <b>{pnl_runner:+.2f}$</b>\n"
                    f"💰 P&L total   : <b>{total_pnl:+.2f}$</b>  ({acct_pct:+.2f}%)\n"
                    f"📈 Capital     : ${state.paper_balance:.2f}\n"
                    f"{'📄 PAPER MODE' if PAPER_MODE else '💰 LIVE BITGET'}"
                )
                continue

            # ── Trailing stop ──────────────────────────────
            if new_progress:
                pos["highest_close"] = candle_close
                pos["runner_stall"]  = 0
                if pos["side"] == "long":
                    new_trail = round(candle_close - atr * RUNNER_TRAIL_ATR, 2)
                    pos["runner_sl"] = max(runner_sl, new_trail)
                else:
                    new_trail = round(candle_close + atr * RUNNER_TRAIL_ATR, 2)
                    pos["runner_sl"] = min(runner_sl, new_trail)
                runner_sl = pos["runner_sl"]
                log.info(f"[Ph3] Nouveau haut ${candle_close:.2f} · Trailing SL → ${runner_sl:.2f}")
            else:
                pos["runner_stall"] = stall + 1

            # ── Sortie : SL touché OU stall max ───────────
            time_exit = pos["runner_stall"] >= RUNNER_MAX_STALL
            if hit_runner_sl or time_exit:
                exit_price  = runner_sl if hit_runner_sl else candle_close
                raw_pnl     = (exit_price - ep) / ep if pos["side"] == "long" else (ep - exit_price) / ep
                pnl_runner  = raw_pnl * act_runner * state.contract_size * ep * LEVERAGE
                total_pnl   = tp1_pnl + pnl_runner
                acct_pct    = total_pnl / cap_entry * 100 if cap_entry else 0
                exit_reason = "SL Runner" if hit_runner_sl else f"Stall {RUNNER_MAX_STALL}×15m"

                if not PAPER_MODE:
                    try:
                        close_side = 2 if pos["side"] == "long" else 4
                        exchange.place_order(close_side, act_runner)
                    except Exception as e:
                        log.error(f"Fermeture Runner error: {e}")
                        still_open.append(pos)
                        continue

                state.paper_balance += pnl_runner
                state.paper_pnl     += pnl_runner
                state.daily_pnl     += pnl_runner
                state.wins          += 1
                state.consec_sl[pos["side"]] = 0

                trades.append({"e": ep, "x": exit_price, "side": pos["side"],
                               "pnl": round(total_pnl, 2), "res": f"Runner ({exit_reason})",
                               "setup": setup, "date": datetime.now().strftime("%m/%d %H:%M")})
                notify_n8n(pos, "CLOSE_RUNNER", tp1_pnl, pnl_runner, total_pnl, 3, "WIN", exit_price)

                log.info(f"[Ph3→FIN] Runner fermé {exit_reason} · ${ep:.2f}→${exit_price:.2f} · "
                         f"P&L runner: {pnl_runner:+.2f}$ · P&L total: {total_pnl:+.2f}$")
                tg(
                    f"🏃 <b>BOT 2 — RUNNER FERMÉ — {setup}</b>\n"
                    f"\n"
                    f"📍 Entrée      : ${ep:.2f}\n"
                    f"🏁 Sortie      : ${exit_price:.2f}  ({exit_reason})\n"
                    f"💰 P&L runner  : <b>{pnl_runner:+.2f}$</b>\n"
                    f"💰 P&L total   : <b>{total_pnl:+.2f}$</b>  ({acct_pct:+.2f}%)\n"
                    f"📈 Capital     : ${state.paper_balance:.2f}\n"
                    f"🎯 Win Rate    : {state.wr:.0f}%  ({state.wins}W / {state.losses}L)\n"
                    f"{'📄 PAPER MODE' if PAPER_MODE else '💰 LIVE BITGET'}"
                )
                continue

            still_open.append(pos)
            continue

        # ══════════════════════════════════════════════════
        # PHASE 1 — Les 2 lots, SL initial, cible TP1
        # ══════════════════════════════════════════════════
        else:
            sl = pos["sl"]
            tp = pos["tp"]

            if pos["side"] == "long":
                hit_tp = candle_high >= tp
                hit_sl = candle_low  <= sl
            else:
                hit_tp = candle_low  <= tp
                hit_sl = candle_high >= sl

            if hit_sl and hit_tp:
                hit_sl = True   # SL prioritaire en phase 1

            if not hit_sl and not hit_tp:
                still_open.append(pos)
                continue

            lot1_contracts   = pos["lot1_contracts"]
            runner_contracts = pos["runner_contracts"]
            total_contracts  = pos["contracts"]

            # ── TP1 atteint → fermer Lot 1, passer Phase 2 ──
            if hit_tp and runner_contracts > 0:
                exit_price_lot1 = tp
                raw_pnl_lot1    = (exit_price_lot1 - ep) / ep if pos["side"] == "long" else (ep - exit_price_lot1) / ep
                pnl_lot1        = raw_pnl_lot1 * lot1_contracts * state.contract_size * ep * LEVERAGE

                if not PAPER_MODE:
                    try:
                        close_side = 2 if pos["side"] == "long" else 4
                        exchange.place_order(close_side, lot1_contracts)
                    except Exception as e:
                        log.error(f"Fermeture Lot 1 error: {e}")
                        still_open.append(pos)
                        continue

                state.paper_balance += pnl_lot1
                state.paper_pnl     += pnl_lot1
                state.daily_pnl     += pnl_lot1

                pos["phase"]   = 2
                pos["tp1_pnl"] = pnl_lot1
                acct_pct_lot1  = pnl_lot1 / cap_entry * 100 if cap_entry else 0

                log.info(f"[Ph1→2] TP1/VWAP ${tp:.2f} atteint · Lot 1 ({lot1_contracts}c) +${pnl_lot1:.2f} · "
                         f"Lot 2 ({runner_contracts}c) SL → VWAP ${tp:.2f} · Cible TP2 ${pos['tp_poc']:.2f}")
                tg(
                    f"✅ <b>BOT 2 — TP1 ATTEINT — Lot 1 fermé — {setup}</b>\n"
                    f"\n"
                    f"📍 Entrée     : ${ep:.2f}\n"
                    f"🎯 TP1 (±1SD) : ${tp:.2f}\n"
                    f"💰 Lot 1 P&L  : <b>+${pnl_lot1:.2f}$</b>  ({acct_pct_lot1:+.2f}%)\n"
                    f"\n"
                    f"📊 <b>Phase 2 — Lot 2 continue</b> : {runner_contracts} contrats\n"
                    f"🛑 SL Lot 2   : ${tp:.2f}  (= TP1 — profit garanti)\n"
                    f"🏁 TP2 (runner s'active ici) : ${pos['tp_poc']:.2f}\n"
                    f"📈 Capital    : ${state.paper_balance:.2f}\n"
                    f"{'📄 PAPER MODE' if PAPER_MODE else '💰 LIVE BITGET'}"
                )
                still_open.append(pos)
                continue

            # ── TP1 atteint, 1 seul contrat → fermer tout ──
            if hit_tp and runner_contracts == 0:
                exit_price = tp
                raw_pnl    = (exit_price - ep) / ep if pos["side"] == "long" else (ep - exit_price) / ep
                pnl_usd    = raw_pnl * total_contracts * state.contract_size * ep * LEVERAGE
                acct_pct   = pnl_usd / cap_entry * 100 if cap_entry else 0

                if not PAPER_MODE:
                    try:
                        close_side = 2 if pos["side"] == "long" else 4
                        exchange.place_order(close_side, total_contracts)
                    except Exception as e:
                        log.error(f"Fermeture TP1 error: {e}")
                        still_open.append(pos)
                        continue

                state.paper_balance += pnl_usd
                state.paper_pnl     += pnl_usd
                state.daily_pnl     += pnl_usd
                state.wins          += 1
                state.consec_sl[pos["side"]] = 0

                trades.append({"e": ep, "x": exit_price, "side": pos["side"],
                               "pnl": round(pnl_usd, 2), "res": "TP1 (1 contrat)",
                               "setup": setup, "date": datetime.now().strftime("%m/%d %H:%M")})
                notify_n8n(pos, "CLOSE_TP1", pnl_usd, 0, pnl_usd, 1, "WIN")

                tg(
                    f"🎯 <b>BOT 2 — TP1 ATTEINT — {setup}</b> (1 contrat)\n"
                    f"📍 Entrée  : ${ep:.2f}   🎯 TP1 : ${exit_price:.2f}\n"
                    f"💰 P&L : <b>{pnl_usd:+.2f}$</b>  ({acct_pct:+.2f}%)\n"
                    f"📈 Capital : ${state.paper_balance:.2f}  · WR: {state.wr:.0f}%\n"
                    f"{'📄 PAPER MODE' if PAPER_MODE else '💰 LIVE BITGET'}"
                )
                continue

            # ── SL touché → fermer les 2 lots ───────────
            exit_price = sl
            raw_pnl    = (exit_price - ep) / ep if pos["side"] == "long" else (ep - exit_price) / ep
            pnl_usd    = raw_pnl * total_contracts * state.contract_size * ep * LEVERAGE
            acct_pct   = pnl_usd / cap_entry * 100 if cap_entry else 0

            if not PAPER_MODE:
                try:
                    close_side = 2 if pos["side"] == "long" else 4
                    exchange.place_order(close_side, total_contracts)
                except Exception as e:
                    log.error(f"Fermeture SL error: {e}")
                    still_open.append(pos)
                    continue

            state.paper_balance += pnl_usd
            state.paper_pnl     += pnl_usd
            state.daily_pnl     += pnl_usd
            state.losses        += 1
            state.last_sl_time   = time.time()

            # ── Lockout directionnel (Point 2) ──────────
            side_hit = pos["side"]
            state.consec_sl[side_hit] += 1
            if state.consec_sl[side_hit] >= CONSEC_SL_LOCKOUT_N:
                state.side_lockout_until[side_hit] = time.time() + DIRECTION_LOCKOUT_SEC
                state.consec_sl[side_hit] = 0
                log.warning(f"[Lockout] {CONSEC_SL_LOCKOUT_N} SL consécutifs "
                            f"{side_hit.upper()} — direction coupée "
                            f"{DIRECTION_LOCKOUT_SEC//3600}h")
                tg(f"🔒 <b>BOT 2 — LOCKOUT {side_hit.upper()}</b>\n"
                   f"{CONSEC_SL_LOCKOUT_N} SL consécutifs dans cette direction.\n"
                   f"Plus aucun {side_hit} pendant {DIRECTION_LOCKOUT_SEC//3600}h "
                   f"— le régime lui donne tort.")

            trades.append({"e": ep, "x": exit_price, "side": pos["side"],
                           "pnl": round(pnl_usd, 2), "res": "SL",
                           "setup": setup, "date": datetime.now().strftime("%m/%d %H:%M")})
            notify_n8n(pos, "CLOSE_SL", pnl_usd, 0, pnl_usd, 1, "LOSS")

            log.info(f"SL {pos['side'].upper()} [{setup}] ${ep:.2f}→${exit_price:.2f} · "
                     f"{pnl_usd:+.2f}$ · Capital: ${state.paper_balance:.2f}")
            tg(
                f"❌ <b>BOT 2 — SL TOUCHÉ — {setup}</b>\n"
                f"\n"
                f"📍 Entrée  : ${ep:.2f}   🛑 SL : ${exit_price:.2f}\n"
                f"💰 P&L : <b>{pnl_usd:+.2f}$</b>  ({acct_pct:+.2f}%)\n"
                f"📈 Capital : ${state.paper_balance:.2f}  · WR: {state.wr:.0f}%\n"
                f"📊 P&L jour: {state.daily_pnl:+.2f}$\n"
                f"⏸️ Cooldown: {COOLDOWN_AFTER_SL//60} min\n"
                f"{'📄 PAPER MODE' if PAPER_MODE else '💰 LIVE BITGET'}"
            )

    state.positions = still_open


def check_drawdown():
    cap = state.capital
    if cap > state.peak_capital:
        state.peak_capital = cap
        if state.dd_level > 0:
            state.dd_level = 0
            tg(f"✅ <b>BOT 2 — Nouveau pic : ${cap:.2f}</b>\nDrawdown remis à zéro")

    dd = (state.peak_capital - cap) / state.peak_capital if state.peak_capital > 0 else 0

    if state.dd_pause_until > time.time():
        remaining = int((state.dd_pause_until - time.time()) / 60)
        log.info(f"DD pause niveau 3 — {remaining}min restantes")
        return False

    old_level = state.dd_level
    if dd >= DD_LEVEL3:        state.dd_level = 3
    elif dd >= DD_LEVEL2:      state.dd_level = 2
    elif dd >= DD_LEVEL1:      state.dd_level = 1
    else:                      state.dd_level = 0

    if state.dd_level != old_level:
        dd_pct = round(dd * 100, 1)
        if state.dd_level == 3:
            state.dd_pause_until = time.time() + DD_PAUSE
            tg(f"🔴 <b>BOT 2 — DD Niveau 3 — {dd_pct}%</b>\nPAUSE COMPLÈTE 1 heure")
            return False
        elif state.dd_level == 2:
            tg(f"🟠 <b>BOT 2 — DD Niveau 2 — {dd_pct}%</b>\nRisque réduit à 1%")
        elif state.dd_level == 1:
            tg(f"⚠️ <b>BOT 2 — DD Niveau 1 — {dd_pct}%</b>\nSurveillance renforcée — stratégie inchangée")

    return True


def main():
    log.info("=" * 60)
    log.info("  BOT 2 — VWAP SD SCALPER [BITGET] — MTF 15m/1m")
    log.info(f"  {SYMBOL} · Capital: ${CAPITAL} · Levier: {LEVERAGE}x")
    log.info(f"  Setups : SHORT +2SD/+3SD · LONG -2SD/-3SD → VWAP")
    log.info(f"  Mode: {'PAPER' if PAPER_MODE else 'LIVE FUTURES BITGET'}")
    log.info("=" * 60)

    try:
        info = exchange.get_contract_info(SYMBOL)
        state.contract_size = info["contractSize"]
        log.info(f"1 contrat = {state.contract_size} oz XAU (Bitget)")
        tg(
            f"🤖 <b>BOT 2 VWAP démarré sur Bitget</b>\n"
            f"📊 {SYMBOL} · Levier {LEVERAGE}x · 1 contrat = {state.contract_size} oz\n"
            f"🎯 Stratégie : VWAP SD · Mean Reversion · MTF 15m/1m\n"
            f"📐 Setups : SHORT +2/+3SD · LONG -2/-3SD → VWAP\n"
            f"💰 Capital : ${state.capital:.2f}\n"
            f"{'📄 PAPER MODE — aucun ordre réel' if PAPER_MODE else '💰 LIVE — ordres réels actifs'}"
        )
    except Exception as e:
        log.warning(f"contract_size=0.01 par défaut ({e})")
        tg(f"⚠️ BOT 2 démarré (contract_size par défaut)\n{e}")

    if not PAPER_MODE:
        try:
            exchange.set_leverage(SYMBOL, LEVERAGE)
        except Exception as e:
            log.warning(f"Levier: {e}")

    while True:
        try:
            state.reset_daily()

            if not check_drawdown():
                time.sleep(LOOP_SECONDS)
                continue

            # ── Fetch MTF : 15m (signal) + 1m (confirmation) ──
            candles_5m = exchange.get_candles(SYMBOL, INTERVAL_SIGNAL, CANDLES_NEEDED + 10)
            if not candles_5m:
                time.sleep(60)
                continue

            candles_1m = exchange.get_candles(SYMBOL, INTERVAL_CONFIRM, CANDLES_CONFIRM + 5)
            if not candles_1m:
                candles_1m = []

            current_price    = candles_5m[-1]["close"]
            state.last_price = current_price

            if state.positions:
                # Bougie EN COURS (candles_5m[-1]) : high/low/close live → détection
                # immédiate SL/TP sans délai (idem Bot VP).
                check_exits(current_price, candles_5m[-1])

            signal = {"signal": None}
            if len(state.positions) < MAX_POSITIONS:
                cooldown_remaining = COOLDOWN_AFTER_SL - (time.time() - state.last_sl_time)
                if cooldown_remaining > 0:
                    signal = {"signal": None, "reason": f"Cooldown SL: {int(cooldown_remaining//60)}min"}
                else:
                    signal = calc_signal(candles_5m, candles_1m)
                    # ── Lockout directionnel (Point 2) ──
                    sig_side = signal.get("signal")
                    if sig_side and time.time() < state.side_lockout_until.get(sig_side, 0):
                        mins = int((state.side_lockout_until[sig_side] - time.time()) // 60)
                        signal = {"signal": None,
                                  "reason": f"Lockout {sig_side.upper()} — encore {mins}min"}
                    if signal.get("signal"):
                        # DD Niveau 1 : score minimum relevé à MIN_SCORE+1 (idem Bot VP)
                        min_score_eff = MIN_SCORE + (1.0 if state.dd_level >= 1 else 0.0)
                        if signal.get("score", 0) >= min_score_eff:
                            refus = open_position(signal, state.dd_level)
                            if refus:
                                signal = {"signal": None, "reason": refus}
                        else:
                            signal = {"signal": None,
                                      "reason": (f"DD N{state.dd_level} — score "
                                                 f"{signal.get('score', 0):.1f} "
                                                 f"< min {min_score_eff:.0f}")}

            # ── Shadow log : setup détecté mais bloqué par un filtre ──
            if not signal.get("signal"):
                cat = block_category(signal.get("reason", ""))
                if cat:
                    _now = time.time()
                    if (cat != state.last_block_log["motif"]
                            or _now - state.last_block_log["ts"] > 900):
                        notify_n8n_blocked(signal["reason"], current_price)
                        state.last_block_log = {"motif": cat, "ts": _now}

            pos_desc = " | ".join(
                f"{p['side'].upper()}[{p['setup']}]@${p['entry']:.1f}"
                + (" [Ph3]" if p.get("phase") == 3 else " [Ph2]" if p.get("phase") == 2 else "")
                for p in state.positions
            ) if state.positions else "FLAT"

            dd_pct = (state.peak_capital - state.capital) / state.peak_capital * 100 if state.peak_capital > 0 else 0
            log.info(
                f"${current_price:.2f} | {pos_desc} | "
                f"Capital: ${state.paper_balance:.2f} | "
                f"P&L: {state.paper_pnl:+.2f}$ | "
                f"WR: {state.wr:.0f}% | DD: {dd_pct:.1f}% | "
                f"{signal.get('reason', '-')}"
            )

        except KeyboardInterrupt:
            log.info("Bot 2 arrêté")
            break
        except Exception as e:
            log.error(f"Erreur: {e}")
            time.sleep(60)
            continue

        time.sleep(LOOP_SECONDS)


if __name__ == "__main__":
    dashboard.init(state, trades)
    t = threading.Thread(target=dashboard.run, daemon=True)
    t.start()
    log.info("Dashboard démarré")
    main()
