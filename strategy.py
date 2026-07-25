# ═══════════════════════════════════════════════════════
# STRATEGY — VWAP SD Scalper · XAU/USDT · MTF 15m/1m
# ─────────────────────────────────────────────────────
# Multi-TimeFrame :
#   15m : VWAP journalier + bandes SD · sweep liquidité · CDV
#   1m  : confirmation entrée chirurgicale (bougie de rejet)
# ─────────────────────────────────────────────────────
# Avantage MTF : structure institutionnelle sur 15m →
#   niveaux SD plus robustes · SL serré 1m · RR amélioré
# ─────────────────────────────────────────────────────
# SHORT : rejet +2SD ou +3SD → TP1 VWAP · TP2 -1SD
# LONG  : rejet -2SD ou -3SD → TP1 VWAP · TP2 +1SD
# ═══════════════════════════════════════════════════════

import numpy as np
from datetime import datetime, timezone
from config import *


def calc_atr(highs, lows, closes, period=14):
    trs = [max(highs[i] - lows[i],
               abs(highs[i] - closes[i-1]),
               abs(lows[i]  - closes[i-1]))
           for i in range(1, len(closes))]
    if len(trs) < period:
        return [None] * (len(closes) + 1)
    atr_vals = [None] * period
    atr_vals.append(np.mean(trs[:period]))
    for i in range(period, len(trs)):
        atr_vals.append((atr_vals[-1] * (period - 1) + trs[i]) / period)
    return atr_vals + [None]


def calc_cdv(closes, opens, volumes, period=20):
    """Cumulative Delta Volume sur les bougies 15m."""
    deltas = [v if c > o else -v if c < o else 0
              for c, o, v in zip(closes, opens, volumes)]
    cdv = [None] * (period - 1)
    for i in range(period - 1, len(closes)):
        cdv.append(sum(deltas[i - period + 1:i + 1]))
    return cdv


def calc_vwap_session(candles_5m):
    """
    VWAP journalier (reset 00:00 UTC) calculé sur les bougies 15m.
    Retourne vwap, sd et les 6 bandes ±1SD/±2SD/±3SD.
    """
    now           = datetime.now(timezone.utc)
    session_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    session_ts    = session_start.timestamp()

    session = [c for c in candles_5m if c.get("timestamp", 0) / 1000 >= session_ts]
    if len(session) < 5:
        session = candles_5m[-50:]

    cum_tpv  = 0.0
    cum_vol  = 0.0
    cum_tpv2 = 0.0

    for c in session:
        tp  = (c["high"] + c["low"] + c["close"]) / 3
        vol = max(c["volume"], 1e-9)
        cum_tpv  += tp * vol
        cum_vol  += vol
        cum_tpv2 += (tp ** 2) * vol

    if cum_vol <= 0:
        return None

    vwap     = cum_tpv / cum_vol
    variance = max(0.0, cum_tpv2 / cum_vol - vwap ** 2)
    sd       = variance ** 0.5

    if sd < 0.50:
        return None

    return {
        "vwap":  round(vwap,           2),
        "sd":    round(sd,             2),
        "sd1_h": round(vwap + 1 * sd,  2),
        "sd1_l": round(vwap - 1 * sd,  2),
        "sd2_h": round(vwap + 2 * sd,  2),
        "sd2_l": round(vwap - 2 * sd,  2),
        "sd3_h": round(vwap + 3 * sd,  2),
        "sd3_l": round(vwap - 3 * sd,  2),
    }


def detect_liquidity_sweep(candles_5m, idx, side, lookback=4):
    """
    Sweep de liquidité sur les bougies 15m.
    SHORT : wick au-dessus des plus hauts récents puis clôture en dessous
    LONG  : wick en dessous des plus bas récents puis clôture au-dessus
    """
    if idx < lookback + 1:
        return False

    current   = candles_5m[idx]
    reference = candles_5m[idx - lookback: idx]

    if side == "short":
        recent_high = max(c["high"] for c in reference)
        return current["high"] > recent_high and current["close"] < recent_high
    else:
        recent_low = min(c["low"] for c in reference)
        return current["low"] < recent_low and current["close"] > recent_low


def confirm_entry_1m(candles_1m, side, sd_band_price, lookback=3):
    """
    Confirmation chirurgicale sur les bougies 1m.

    Après détection du setup sur 5m, on vérifie que les dernières
    bougies 1m confirment le rejet de la bande SD.

    SHORT : bougie 1m baissière dont le close est sous la bande SD
            OU pin bar 1m avec mèche haute + close sous la bande
    LONG  : bougie 1m haussière dont le close est au-dessus de la bande SD
            OU pin bar 1m avec mèche basse + close au-dessus de la bande

    Retourne (confirmed: bool, entry_price: float, confirmation_tag: str)
    """
    if len(candles_1m) < 2:
        return False, None, ""

    # On analyse les dernières bougies 1m
    recent = candles_1m[-lookback:]

    if side == "short":
        for c in reversed(recent):
            body      = abs(c["close"] - c["open"])
            wick_up   = c["high"] - max(c["close"], c["open"])
            wick_down = min(c["close"], c["open"]) - c["low"]

            bear_candle = c["close"] < c["open"] and c["close"] < sd_band_price
            pin_bar_sh  = (wick_up > body * 1.2
                           and c["close"] < sd_band_price
                           and c["close"] < c["open"])
            engulf_sh   = (c["close"] < c["open"]
                           and body > wick_down * 1.5
                           and c["close"] < sd_band_price)

            if bear_candle:
                return True, c["close"], "1m_Bear"
            if pin_bar_sh:
                return True, c["close"], "1m_PinBar"
            if engulf_sh:
                return True, c["close"], "1m_Engulf"

    else:  # long
        for c in reversed(recent):
            body      = abs(c["close"] - c["open"])
            wick_up   = c["high"] - max(c["close"], c["open"])
            wick_down = min(c["close"], c["open"]) - c["low"]

            bull_candle = c["close"] > c["open"] and c["close"] > sd_band_price
            pin_bar_lg  = (wick_down > body * 1.2
                           and c["close"] > sd_band_price
                           and c["close"] > c["open"])
            engulf_lg   = (c["close"] > c["open"]
                           and body > wick_up * 1.5
                           and c["close"] > sd_band_price)

            if bull_candle:
                return True, c["close"], "1m_Bull"
            if pin_bar_lg:
                return True, c["close"], "1m_PinBar"
            if engulf_lg:
                return True, c["close"], "1m_Engulf"

    return False, None, ""


# ── Signal principal MTF ──────────────────────────────────

def calc_signal(candles_5m, candles_1m):
    """
    Stratégie VWAP SD MTF :
    - Analyse sur 15m : VWAP SD + sweep liquidité + CDV (structure institutionnelle)
    - Confirmation sur 1m : bougie de rejet chirurgicale
    - Entrée au close de la bougie 1m de confirmation
    """
    if len(candles_5m) < CANDLES_NEEDED:
        return {"signal": None, "reason": "Pas assez de bougies 15m"}

    if len(candles_1m) < 5:
        return {"signal": None, "reason": "Pas assez de bougies 1m"}

    # ── Filtre session active (London 7h-12h UTC / NY 13h-17h UTC) ──
    current_hour = datetime.now(timezone.utc).hour
    if current_hour not in SESSION_HOURS_UTC:
        return {"signal": None, "reason": f"Hors session active (heure UTC={current_hour}h) — London 7h-12h · NY 13h-17h"}

    # ── Données 5m ───────────────────────────────────────
    closes_5m  = [c["close"]  for c in candles_5m]
    highs_5m   = [c["high"]   for c in candles_5m]
    lows_5m    = [c["low"]    for c in candles_5m]
    opens_5m   = [c["open"]   for c in candles_5m]
    volumes_5m = [c["volume"] for c in candles_5m]

    i       = len(candles_5m) - 1
    d_close = closes_5m[i]
    d_high  = highs_5m[i]
    d_low   = lows_5m[i]
    d_open  = opens_5m[i]

    # ── ATR 5m ───────────────────────────────────────────
    atr_arr = calc_atr(highs_5m, lows_5m, closes_5m, ATR_PERIOD)
    at = atr_arr[i]
    if at is None:
        return {"signal": None, "reason": "ATR 15m insuffisant"}

    recent_atrs = [x for x in atr_arr[max(0, i - 30):i] if x is not None]
    avg_at      = np.mean(recent_atrs) if recent_atrs else at

    if at / avg_at > 3.0:
        return {"signal": None, "reason": "Volatilité excessive (news)"}

    if at < MIN_ATR:
        return {"signal": None, "reason": f"ATR trop faible ({at:.2f}$) — session morte, on ne trade pas"}

    # ── VWAP + SD (calculé sur 5m) ───────────────────────
    vp = calc_vwap_session(candles_5m)
    if vp is None:
        return {"signal": None, "reason": "VWAP insuffisant"}

    vwap  = vp["vwap"]
    sd    = vp["sd"]
    sd1_h = vp["sd1_h"]
    sd1_l = vp["sd1_l"]
    sd2_h = vp["sd2_h"]
    sd2_l = vp["sd2_l"]
    sd3_h = vp["sd3_h"]
    sd3_l = vp["sd3_l"]

    tol = sd * TOL_SD_MULT

    # ── CDV 5m ───────────────────────────────────────────
    cdv_arr = calc_cdv(closes_5m, opens_5m, volumes_5m, CDV_PERIOD)
    cdv  = cdv_arr[i]
    pcdv = cdv_arr[i - 1] if i > 0 else None

    cdv_turning_bear = cdv is not None and pcdv is not None and cdv < pcdv
    cdv_turning_bull = cdv is not None and pcdv is not None and cdv > pcdv

    # ══════════════════════════════════════════════════════
    #  SETUP SHORT +3SD (priorité)
    # ══════════════════════════════════════════════════════
    if d_high >= sd3_h - tol and d_close < sd3_h + tol:
        sl_price = round(sd3_h + at * 0.5, 2)
        tp1      = round(vwap, 2)
        tp2      = round(sd1_l, 2)

        dist_sl  = abs(sl_price - d_close)
        dist_tp1 = abs(d_close - tp1)
        est_rr   = dist_tp1 / dist_sl if dist_sl > 0 else 0

        if tp1 < d_close and tp2 < tp1 and est_rr >= MIN_RR:
            sweep   = detect_liquidity_sweep(candles_5m, i, "short", SWEEP_LOOKBACK)
            pin_bar = (d_high > sd3_h and d_close < d_open
                       and (d_high - max(d_close, d_open)) > (min(d_close, d_open) - d_low) * 1.2)

            score = 0.0
            tags  = []

            if d_high > sd3_h and d_close < sd3_h:  score += 3.0; tags.append("wick>+3SD")
            elif d_close >= sd3_h - tol:             score += 2.0; tags.append("@+3SD")
            if pin_bar:                              score += 1.5; tags.append("PinBar5m")
            elif d_close < d_open:                   score += 0.5; tags.append("Bear5m")
            if sweep:                                score += 1.5; tags.append("LiqSweep")
            if cdv_turning_bear:                     score += 1.5; tags.append("CDV↓")
            if at / avg_at < 1.8:                    score += 0.5; tags.append("ATRok")

            if score >= MIN_SCORE:
                # ── Confirmation 1m ──────────────────────
                confirmed, entry_1m, conf_tag = confirm_entry_1m(
                    candles_1m, "short", sd3_h, CONFIRM_LOOKBACK)

                if confirmed and entry_1m is not None:
                    score += 1.5
                    tags.append(conf_tag)
                    entry_price = entry_1m
                else:
                    # Pas de confirmation 1m → signal ignoré
                    return {"signal": None,
                            "reason": f"+3SD SHORT détecté (score {score:.1f}) mais confirmation 1m absente"}

                return {
                    "signal":   "short",
                    "setup":    "+3SD→VWAP",
                    "score":    round(score, 1),
                    "price":    entry_price,
                    "atr":      round(at, 2),
                    "sl_price": sl_price,
                    "tp_price": tp1,
                    "tp_poc":   tp2,
                    "rr":       round(abs(entry_price - tp1) / abs(sl_price - entry_price), 1)
                                if abs(sl_price - entry_price) > 0 else round(est_rr, 1),
                    "vwap":     vwap,
                    "sd":       round(sd, 2),
                    "sd2_h":    sd2_h, "sd3_h": sd3_h,
                    "sd2_l":    sd2_l, "sd3_l": sd3_l,
                    "reason":   f"+3SD SHORT MTF | " + "+".join(tags)
                                + f" | VWAP={vwap:.2f} SD={sd:.2f}",
                }

    # ══════════════════════════════════════════════════════
    #  SETUP SHORT +2SD
    # ══════════════════════════════════════════════════════
    if (d_high >= sd2_h - tol and d_close < sd2_h + tol
            and d_high < sd3_h - tol * 0.5):
        sl_price = round(sd2_h + at * 1.0, 2)  # SL : +2SD + 1×ATR — assez de marge pour le bruit
        tp1      = round(vwap, 2)
        tp2      = round(sd1_l, 2)

        dist_sl  = abs(sl_price - d_close)
        dist_tp1 = abs(d_close - tp1)
        est_rr   = dist_tp1 / dist_sl if dist_sl > 0 else 0

        if tp1 < d_close and tp2 < tp1 and est_rr >= MIN_RR:
            sweep   = detect_liquidity_sweep(candles_5m, i, "short", SWEEP_LOOKBACK)
            pin_bar = (d_high > sd2_h and d_close < d_open
                       and (d_high - max(d_close, d_open)) > (min(d_close, d_open) - d_low) * 1.2)

            score = 0.0
            tags  = []

            if d_high > sd2_h and d_close < sd2_h:  score += 2.5; tags.append("wick>+2SD")
            elif d_close >= sd2_h - tol:             score += 1.5; tags.append("@+2SD")
            if pin_bar:                              score += 1.5; tags.append("PinBar5m")
            elif d_close < d_open:                   score += 0.5; tags.append("Bear5m")
            if sweep:                                score += 1.5; tags.append("LiqSweep")
            if cdv_turning_bear:                     score += 1.5; tags.append("CDV↓")
            if at / avg_at < 1.5:                    score += 0.5; tags.append("ATRok")

            if score >= MIN_SCORE:
                confirmed, entry_1m, conf_tag = confirm_entry_1m(
                    candles_1m, "short", sd2_h, CONFIRM_LOOKBACK)

                if confirmed and entry_1m is not None:
                    score += 1.5
                    tags.append(conf_tag)
                    entry_price = entry_1m
                else:
                    return {"signal": None,
                            "reason": f"+2SD SHORT détecté (score {score:.1f}) mais confirmation 1m absente"}

                return {
                    "signal":   "short",
                    "setup":    "+2SD→VWAP",
                    "score":    round(score, 1),
                    "price":    entry_price,
                    "atr":      round(at, 2),
                    "sl_price": sl_price,
                    "tp_price": tp1,
                    "tp_poc":   tp2,
                    "rr":       round(abs(entry_price - tp1) / abs(sl_price - entry_price), 1)
                                if abs(sl_price - entry_price) > 0 else round(est_rr, 1),
                    "vwap":     vwap,
                    "sd":       round(sd, 2),
                    "sd2_h":    sd2_h, "sd3_h": sd3_h,
                    "sd2_l":    sd2_l, "sd3_l": sd3_l,
                    "reason":   f"+2SD SHORT MTF | " + "+".join(tags)
                                + f" | VWAP={vwap:.2f} SD={sd:.2f}",
                }

    # ══════════════════════════════════════════════════════
    #  SETUP LONG -3SD (priorité)
    # ══════════════════════════════════════════════════════
    if d_low <= sd3_l + tol and d_close > sd3_l - tol:
        sl_price = round(sd3_l - at * 0.5, 2)
        tp1      = round(vwap, 2)
        tp2      = round(sd1_h, 2)

        dist_sl  = abs(d_close - sl_price)
        dist_tp1 = abs(tp1 - d_close)
        est_rr   = dist_tp1 / dist_sl if dist_sl > 0 else 0

        if tp1 > d_close and tp2 > tp1 and est_rr >= MIN_RR:
            sweep   = detect_liquidity_sweep(candles_5m, i, "long", SWEEP_LOOKBACK)
            pin_bar = (d_low < sd3_l and d_close > d_open
                       and (min(d_close, d_open) - d_low) > (d_high - max(d_close, d_open)) * 1.2)

            score = 0.0
            tags  = []

            if d_low < sd3_l and d_close > sd3_l:   score += 3.0; tags.append("wick<-3SD")
            elif d_close <= sd3_l + tol:             score += 2.0; tags.append("@-3SD")
            if pin_bar:                              score += 1.5; tags.append("PinBar5m")
            elif d_close > d_open:                   score += 0.5; tags.append("Bull5m")
            if sweep:                                score += 1.5; tags.append("LiqSweep")
            if cdv_turning_bull:                     score += 1.5; tags.append("CDV↑")
            if at / avg_at < 1.8:                    score += 0.5; tags.append("ATRok")

            if score >= MIN_SCORE:
                confirmed, entry_1m, conf_tag = confirm_entry_1m(
                    candles_1m, "long", sd3_l, CONFIRM_LOOKBACK)

                if confirmed and entry_1m is not None:
                    score += 1.5
                    tags.append(conf_tag)
                    entry_price = entry_1m
                else:
                    return {"signal": None,
                            "reason": f"-3SD LONG détecté (score {score:.1f}) mais confirmation 1m absente"}

                return {
                    "signal":   "long",
                    "setup":    "-3SD→VWAP",
                    "score":    round(score, 1),
                    "price":    entry_price,
                    "atr":      round(at, 2),
                    "sl_price": sl_price,
                    "tp_price": tp1,
                    "tp_poc":   tp2,
                    "rr":       round(abs(tp1 - entry_price) / abs(entry_price - sl_price), 1)
                                if abs(entry_price - sl_price) > 0 else round(est_rr, 1),
                    "vwap":     vwap,
                    "sd":       round(sd, 2),
                    "sd2_h":    sd2_h, "sd3_h": sd3_h,
                    "sd2_l":    sd2_l, "sd3_l": sd3_l,
                    "reason":   f"-3SD LONG MTF | " + "+".join(tags)
                                + f" | VWAP={vwap:.2f} SD={sd:.2f}",
                }

    # ══════════════════════════════════════════════════════
    #  SETUP LONG -2SD
    # ══════════════════════════════════════════════════════
    if (d_low <= sd2_l + tol and d_close > sd2_l - tol
            and d_low > sd3_l + tol * 0.5):
        sl_price = round(sd3_l - at * 0.3, 2)
        tp1      = round(vwap, 2)
        tp2      = round(sd1_h, 2)

        dist_sl  = abs(d_close - sl_price)
        dist_tp1 = abs(tp1 - d_close)
        est_rr   = dist_tp1 / dist_sl if dist_sl > 0 else 0

        if tp1 > d_close and tp2 > tp1 and est_rr >= MIN_RR:
            sweep   = detect_liquidity_sweep(candles_5m, i, "long", SWEEP_LOOKBACK)
            pin_bar = (d_low < sd2_l and d_close > d_open
                       and (min(d_close, d_open) - d_low) > (d_high - max(d_close, d_open)) * 1.2)

            score = 0.0
            tags  = []

            if d_low < sd2_l and d_close > sd2_l:   score += 2.5; tags.append("wick<-2SD")
            elif d_close <= sd2_l + tol:             score += 1.5; tags.append("@-2SD")
            if pin_bar:                              score += 1.5; tags.append("PinBar5m")
            elif d_close > d_open:                   score += 0.5; tags.append("Bull5m")
            if sweep:                                score += 1.5; tags.append("LiqSweep")
            if cdv_turning_bull:                     score += 1.5; tags.append("CDV↑")
            if at / avg_at < 1.5:                    score += 0.5; tags.append("ATRok")

            if score >= MIN_SCORE:
                confirmed, entry_1m, conf_tag = confirm_entry_1m(
                    candles_1m, "long", sd2_l, CONFIRM_LOOKBACK)

                if confirmed and entry_1m is not None:
                    score += 1.5
                    tags.append(conf_tag)
                    entry_price = entry_1m
                else:
                    return {"signal": None,
                            "reason": f"-2SD LONG détecté (score {score:.1f}) mais confirmation 1m absente"}

                return {
                    "signal":   "long",
                    "setup":    "-2SD→VWAP",
                    "score":    round(score, 1),
                    "price":    entry_price,
                    "atr":      round(at, 2),
                    "sl_price": sl_price,
                    "tp_price": tp1,
                    "tp_poc":   tp2,
                    "rr":       round(abs(tp1 - entry_price) / abs(entry_price - sl_price), 1)
                                if abs(entry_price - sl_price) > 0 else round(est_rr, 1),
                    "vwap":     vwap,
                    "sd":       round(sd, 2),
                    "sd2_h":    sd2_h, "sd3_h": sd3_h,
                    "sd2_l":    sd2_l, "sd3_l": sd3_l,
                    "reason":   f"-2SD LONG MTF | " + "+".join(tags)
                                + f" | VWAP={vwap:.2f} SD={sd:.2f}",
                }

    return {
        "signal": None,
        "reason": (f"Pas de setup | Prix:{d_close:.2f} VWAP:{vwap:.2f} SD:{sd:.2f} "
                   f"+2SD:{sd2_h:.2f} +3SD:{sd3_h:.2f} "
                   f"-2SD:{sd2_l:.2f} -3SD:{sd3_l:.2f}"),
    }
