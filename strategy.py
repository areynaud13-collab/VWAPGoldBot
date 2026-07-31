# ═══════════════════════════════════════════════════════
# STRATEGY — VWAP ±1SD Scalper · XAU/USDT · MTF 5m/1m
# ─────────────────────────────────────────────────────
# Version haute fréquence — Audit 2 (2026-07-31)
#
# Logique institutionnelle mean-reversion :
#   Signal sur ±1SD du VWAP session (touche 15-25x/jour)
#   Confirmation 1m : bougie de rejet / engulf / break
#   Target : retour au VWAP central (8-15 pips)
#
# Setups :
#   SHORT : rejet +1SD → TP VWAP
#   LONG  : rejet -1SD → TP VWAP
#
# Filtres Audit 2 :
#   · Session uniquement 07h-17h UTC (London + NY)
#   · Détecteur de régime tendanciel (suspend mean-reversion)
#   · SL minimum absolu 5$ (évite stops dans le bruit)
#   · ATR minimum (session active)
#   · Expansion volatilité (news/parabole)
#   · CDV : confirmation delta volume
#   · Tendance installée (prix reste au-delà ±1SD → skip)
# ═══════════════════════════════════════════════════════

import numpy as np
from datetime import datetime, timezone
from config import *


def is_trading_session() -> bool:
    """
    Filtre session institutionnel — Audit 2.
    On ne trade qu'en London (07h-12h UTC) et New York (13h-17h UTC).
    La session asiatique (17h-07h UTC) est exclue : liquidité faible,
    moves erratiques, mean-reversion peu fiable sur XAU.
    """
    hour = datetime.now(timezone.utc).hour
    return (7 <= hour < 12) or (13 <= hour < 17)


def detect_trend_regime(closes, highs, lows, atr, n=3, multiplier=1.5) -> str:
    """
    Détecteur de régime tendanciel — Audit 2.
    Concept institutionnel : un algo mean-reversion doit savoir
    quand le marché n'est PAS en mean-reversion.

    Analyse les N dernières bougies 5m :
    - Si N bougies consécutives baissières ET move total > multiplier×ATR
      → régime BEAR (tendance baissière) → suspendre les LONG
    - Si N bougies consécutives haussières ET move total > multiplier×ATR
      → régime BULL (tendance haussière) → suspendre les SHORT
    - Sinon → régime RANGE → mean-reversion autorisé

    Retourne : "BEAR", "BULL", ou "RANGE"
    """
    if len(closes) < n + 1 or atr is None or atr <= 0:
        return "RANGE"

    recent = closes[-(n + 1):]
    move_total = abs(recent[-1] - recent[0])

    # Toutes les bougies dans le même sens ?
    all_bear = all(recent[i] < recent[i-1] for i in range(1, len(recent)))
    all_bull = all(recent[i] > recent[i-1] for i in range(1, len(recent)))

    if all_bear and move_total > multiplier * atr:
        return "BEAR"
    if all_bull and move_total > multiplier * atr:
        return "BULL"
    return "RANGE"


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
    """Cumulative Delta Volume — proxy order flow institutionnel."""
    deltas = [v if c > o else -v if c < o else 0
              for c, o, v in zip(closes, opens, volumes)]
    cdv = [None] * (period - 1)
    for i in range(period - 1, len(closes)):
        cdv.append(sum(deltas[i - period + 1:i + 1]))
    return cdv


def calc_vwap_session(candles):
    """
    VWAP ancré à l'ouverture de la session active (reset institutionnel) :
      · London  : 07:00 UTC
      · New York: 13:00 UTC
      · Nuit    : 00:00 UTC (fallback)

    Retourne vwap, sd et les bandes ±1SD / ±2SD.
    ±1SD = zone de trading haute fréquence (touche 15-25x/jour).
    ±2SD = zone de confirmation de retournement fort (rare).
    """
    now  = datetime.now(timezone.utc)
    hour = now.hour

    if hour >= 13:
        session_open = now.replace(hour=13, minute=0, second=0, microsecond=0)
    elif hour >= 7:
        session_open = now.replace(hour=7,  minute=0, second=0, microsecond=0)
    else:
        session_open = now.replace(hour=0,  minute=0, second=0, microsecond=0)

    session_ts = session_open.timestamp()
    session    = [c for c in candles if c.get("timestamp", 0) >= session_ts]
    if len(session) < 5:
        session = candles[-50:]

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

    # SD trop faible = marché mort ou début de session (< 5 bougies utiles)
    if sd < 0.30:
        return None

    return {
        "vwap":  round(vwap,           2),
        "sd":    round(sd,             2),
        "sd1_h": round(vwap + 1 * sd,  2),
        "sd1_l": round(vwap - 1 * sd,  2),
        "sd2_h": round(vwap + 2 * sd,  2),
        "sd2_l": round(vwap - 2 * sd,  2),
    }


def confirm_entry_1m(candles_1m, side, sd_band_price, lookback=3):
    """
    Confirmation chirurgicale sur bougie 1m.

    SHORT : bougie baissière sous la bande + micro-cassure structure
            OU pin bar avec mèche haute dominante
            OU engulf baissier
    LONG  : bougie haussière au-dessus de la bande + micro-cassure structure
            OU pin bar avec mèche basse dominante
            OU engulf haussier

    Retourne (confirmed, entry_price, tag)
    """
    if len(candles_1m) < 2:
        return False, None, ""

    data = candles_1m[-(lookback + 1):]

    if side == "short":
        for k in range(len(data) - 1, 0, -1):
            c, prev   = data[k], data[k - 1]
            body      = abs(c["close"] - c["open"])
            wick_up   = c["high"] - max(c["close"], c["open"])
            wick_down = min(c["close"], c["open"]) - c["low"]
            rng_c     = max(c["high"] - c["low"], 1e-9)

            bear_candle = (c["close"] < c["open"]
                           and c["close"] < sd_band_price
                           and c["close"] < prev["low"])
            pin_bar_sh  = (wick_up > body * 1.2
                           and wick_up >= rng_c * 0.45
                           and c["close"] < sd_band_price
                           and c["close"] < c["open"])
            engulf_sh   = (c["close"] < c["open"]
                           and body > wick_down * 1.5
                           and c["close"] < sd_band_price
                           and c["close"] < prev["low"])

            if bear_candle: return True, c["close"], "1m_Bear+Break"
            if pin_bar_sh:  return True, c["close"], "1m_PinBar"
            if engulf_sh:   return True, c["close"], "1m_Engulf"

    else:
        for k in range(len(data) - 1, 0, -1):
            c, prev   = data[k], data[k - 1]
            body      = abs(c["close"] - c["open"])
            wick_up   = c["high"] - max(c["close"], c["open"])
            wick_down = min(c["close"], c["open"]) - c["low"]
            rng_c     = max(c["high"] - c["low"], 1e-9)

            bull_candle = (c["close"] > c["open"]
                           and c["close"] > sd_band_price
                           and c["close"] > prev["high"])
            pin_bar_lg  = (wick_down > body * 1.2
                           and wick_down >= rng_c * 0.45
                           and c["close"] > sd_band_price
                           and c["close"] > c["open"])
            engulf_lg   = (c["close"] > c["open"]
                           and body > wick_up * 1.5
                           and c["close"] > sd_band_price
                           and c["close"] > prev["high"])

            if bull_candle: return True, c["close"], "1m_Bull+Break"
            if pin_bar_lg:  return True, c["close"], "1m_PinBar"
            if engulf_lg:   return True, c["close"], "1m_Engulf"

    return False, None, ""


# ── Signal principal ──────────────────────────────────────

def calc_signal(candles_5m, candles_1m):
    """
    Stratégie VWAP ±1SD haute fréquence :

    Détection sur 5m :
      · Prix touche ±1SD du VWAP session
      · CDV confirme retournement
      · Pas de tendance installée (prix ne reste pas au-delà de ±1SD)

    Confirmation sur 1m :
      · Bougie de rejet chirurgicale

    Target : retour au VWAP central
    Stop   : au-delà de ±1SD + ATR buffer
    """
    if len(candles_5m) < CANDLES_NEEDED:
        return {"signal": None, "reason": "Pas assez de bougies 5m"}

    if len(candles_1m) < 5:
        return {"signal": None, "reason": "Pas assez de bougies 1m"}

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

    # ── ATR ──────────────────────────────────────────────
    atr_arr = calc_atr(highs_5m, lows_5m, closes_5m, ATR_PERIOD)
    at = atr_arr[i]
    if at is None:
        return {"signal": None, "reason": "ATR insuffisant"}

    recent_atrs = [x for x in atr_arr[max(0, i - 30):i] if x is not None]
    avg_at      = np.mean(recent_atrs) if recent_atrs else at

    if at < MIN_ATR:
        return {"signal": None, "reason": f"ATR trop faible ({at:.2f}$) — session morte"}

    # ── Filtre session (Audit 2) ──────────────────────────
    # London 07h-12h UTC + New York 13h-17h UTC uniquement
    if not is_trading_session():
        return {"signal": None, "reason": "Hors session London/NY (07h-12h / 13h-17h UTC) — suspendu"}

    # ── Détecteur de régime (Audit 2) ────────────────────
    regime = detect_trend_regime(closes_5m, highs_5m, lows_5m, at,
                                 n=REGIME_CANDLES_N,
                                 multiplier=REGIME_ATR_MULT)

    # ── Filtre expansion volatilité ───────────────────────
    # Marché en mouvement parabolique → mean-reversion ne fonctionne pas
    if avg_at > 0 and at / avg_at > VOLATILITY_SPIKE_MAX:
        return {"signal": None,
                "reason": f"Expansion volatilité ATR {at:.2f}$ = {at/avg_at:.1f}× moyenne — suspendu"}

    # ── VWAP session + bandes SD ──────────────────────────
    vp = calc_vwap_session(candles_5m)
    if vp is None:
        return {"signal": None, "reason": "VWAP insuffisant (SD trop faible ou début session)"}

    vwap  = vp["vwap"]
    sd    = vp["sd"]
    sd1_h = vp["sd1_h"]
    sd1_l = vp["sd1_l"]
    sd2_h = vp["sd2_h"]
    sd2_l = vp["sd2_l"]

    # Tolérance de contact avec la bande (zone et non point exact)
    tol = sd * TOL_SD_MULT

    # ── CDV ───────────────────────────────────────────────
    cdv_arr = calc_cdv(closes_5m, opens_5m, volumes_5m, CDV_PERIOD)
    cdv  = cdv_arr[i]
    pcdv = cdv_arr[i - 1] if i > 0 else None

    cdv_turning_bear = cdv is not None and pcdv is not None and cdv < pcdv
    cdv_turning_bull = cdv is not None and pcdv is not None and cdv > pcdv

    # ══════════════════════════════════════════════════════
    #  SETUP SHORT — rejet +1SD → VWAP
    # ══════════════════════════════════════════════════════
    if d_high >= sd1_h - tol and d_close < sd1_h + tol:

        # Filtre régime (Audit 2) : tendance haussière → short interdit
        if regime == "BULL":
            return {"signal": None,
                    "reason": f"Régime BULL détecté ({REGIME_CANDLES_N} bougies haussières >{REGIME_ATR_MULT}×ATR) — short suspendu"}

        # Filtre tendance installée sur ±1SD
        recent_closes = closes_5m[max(0, i - (TREND_PERSIST_N - 1)): i + 1]
        if sum(1 for c in recent_closes if c > sd1_h) >= TREND_PERSIST_K:
            return {"signal": None,
                    "reason": f"{TREND_PERSIST_K}+/{TREND_PERSIST_N} closes au-dessus de +1SD — tendance haussière, short interdit"}

        # SL au-delà de +1SD + buffer ATR + plancher absolu (Audit 2)
        sl_price = round(max(sd1_h + at * SL_ATR_BUFFER, d_close + SL_MIN_ABS), 2)
        tp1      = round(vwap, 2)   # Target : VWAP central

        dist_sl  = abs(sl_price - d_close)
        dist_tp1 = abs(d_close - tp1)
        est_rr   = dist_tp1 / dist_sl if dist_sl > 0 else 0

        # Cohérence SL/TP (Audit 2) : si le VWAP est trop proche,
        # le TP ne couvre pas le SL minimum → trade non viable
        if dist_tp1 < SL_MIN_ABS * MIN_RR_TP1:
            return {"signal": None,
                    "reason": f"TP trop proche du VWAP ({dist_tp1:.1f}$) — distance minimum {SL_MIN_ABS * MIN_RR_TP1:.1f}$ requise"}

        if tp1 < d_close and est_rr >= MIN_RR:

            score = 0.0
            tags  = []

            # Contact avec ±1SD
            if d_high > sd1_h and d_close < sd1_h:
                score += 2.5; tags.append("wick>+1SD")
            elif d_close >= sd1_h - tol:
                score += 1.5; tags.append("@+1SD")

            # Bougie baissière sur 5m
            pin_bar = (d_high > sd1_h and d_close < d_open
                       and (d_high - max(d_close, d_open)) > (min(d_close, d_open) - d_low) * 1.2)
            if pin_bar:
                score += 1.5; tags.append("PinBar5m")
            elif d_close < d_open:
                score += 0.5; tags.append("Bear5m")

            # CDV confirme la pression vendeuse
            if cdv_turning_bear:
                score += 1.5; tags.append("CDV↓")

            # Prix proche du +2SD = zone de rejet forte supplémentaire
            if d_high >= sd2_h - tol:
                score += 1.0; tags.append("Proche+2SD")

            # ATR dans la normale
            if at / avg_at < 1.5:
                score += 0.5; tags.append("ATRok")

            if score >= MIN_SCORE_SHORT:
                confirmed, entry_1m, conf_tag = confirm_entry_1m(
                    candles_1m, "short", sd1_h, CONFIRM_LOOKBACK)

                if not confirmed or entry_1m is None:
                    return {"signal": None,
                            "reason": f"+1SD SHORT détecté (score {score:.1f}) — confirmation 1m absente"}

                score += 1.5
                tags.append(conf_tag)
                entry_price = entry_1m

                # Recalcul SL depuis entrée réelle avec plancher ATR
                sl_price  = round(max(sl_price, entry_price + SL_ATR_MIN * at), 2)
                _dist_sl  = abs(sl_price - entry_price)
                _rr1      = abs(entry_price - tp1) / _dist_sl if _dist_sl > 0 else 0

                if _rr1 < MIN_RR_TP1:
                    return {"signal": None,
                            "reason": f"RR insuffisant avec SL ATR: {_rr1:.2f} (min {MIN_RR_TP1})"}

                return {
                    "signal":    "short",
                    "setup":     "SHORT +1SD→VWAP",
                    "tp_runner": round(sd1_l, 2),   # runner vise -1SD
                    "score":     round(score, 1),
                    "price":     entry_price,
                    "atr":       round(at, 2),
                    "sl_price":  sl_price,
                    "tp_price":  tp1,
                    "tp_poc":    round(sd1_l, 2),
                    "rr":        round(abs(entry_price - tp1) / abs(sl_price - entry_price), 1)
                                 if abs(sl_price - entry_price) > 0 else round(est_rr, 1),
                    "vwap":      vwap,
                    "sd":        round(sd, 2),
                    "sd2_h":     sd2_h, "sd3_h": round(vwap + 3 * sd, 2),
                    "sd2_l":     sd2_l, "sd3_l": round(vwap - 3 * sd, 2),
                    "reason":    f"+1SD SHORT | " + "+".join(tags)
                                 + f" | VWAP={vwap:.2f} SD={sd:.2f}",
                }

    # ══════════════════════════════════════════════════════
    #  SETUP LONG — rejet -1SD → VWAP
    # ══════════════════════════════════════════════════════
    if d_low <= sd1_l + tol and d_close > sd1_l - tol:

        # Filtre régime (Audit 2) : tendance baissière → long interdit
        if regime == "BEAR":
            return {"signal": None,
                    "reason": f"Régime BEAR détecté ({REGIME_CANDLES_N} bougies baissières >{REGIME_ATR_MULT}×ATR) — long suspendu"}

        # Filtre tendance installée sur ±1SD
        recent_closes = closes_5m[max(0, i - (TREND_PERSIST_N - 1)): i + 1]
        if sum(1 for c in recent_closes if c < sd1_l) >= TREND_PERSIST_K:
            return {"signal": None,
                    "reason": f"{TREND_PERSIST_K}+/{TREND_PERSIST_N} closes sous -1SD — tendance baissière, long interdit"}

        # SL en dessous de -1SD + buffer ATR + plancher absolu (Audit 2)
        sl_price = round(min(sd1_l - at * SL_ATR_BUFFER, d_close - SL_MIN_ABS), 2)
        tp1      = round(vwap, 2)   # Target : VWAP central

        dist_sl  = abs(d_close - sl_price)
        dist_tp1 = abs(tp1 - d_close)
        est_rr   = dist_tp1 / dist_sl if dist_sl > 0 else 0

        # Cohérence SL/TP (Audit 2) : si le VWAP est trop proche,
        # le TP ne couvre pas le SL minimum → trade non viable
        if dist_tp1 < SL_MIN_ABS * MIN_RR_TP1:
            return {"signal": None,
                    "reason": f"TP trop proche du VWAP ({dist_tp1:.1f}$) — distance minimum {SL_MIN_ABS * MIN_RR_TP1:.1f}$ requise"}

        if tp1 > d_close and est_rr >= MIN_RR:

            score = 0.0
            tags  = []

            # Contact avec ±1SD
            if d_low < sd1_l and d_close > sd1_l:
                score += 2.5; tags.append("wick<-1SD")
            elif d_close <= sd1_l + tol:
                score += 1.5; tags.append("@-1SD")

            # Bougie haussière sur 5m
            pin_bar = (d_low < sd1_l and d_close > d_open
                       and (min(d_close, d_open) - d_low) > (d_high - max(d_close, d_open)) * 1.2)
            if pin_bar:
                score += 1.5; tags.append("PinBar5m")
            elif d_close > d_open:
                score += 0.5; tags.append("Bull5m")

            # CDV confirme pression acheteuse
            if cdv_turning_bull:
                score += 1.5; tags.append("CDV↑")

            # Prix proche du -2SD = zone de rejet forte supplémentaire
            if d_low <= sd2_l + tol:
                score += 1.0; tags.append("Proche-2SD")

            # ATR dans la normale
            if at / avg_at < 1.5:
                score += 0.5; tags.append("ATRok")

            if score >= MIN_SCORE:
                confirmed, entry_1m, conf_tag = confirm_entry_1m(
                    candles_1m, "long", sd1_l, CONFIRM_LOOKBACK)

                if not confirmed or entry_1m is None:
                    return {"signal": None,
                            "reason": f"-1SD LONG détecté (score {score:.1f}) — confirmation 1m absente"}

                score += 1.5
                tags.append(conf_tag)
                entry_price = entry_1m

                # Recalcul SL depuis entrée réelle avec plancher ATR
                sl_price  = round(min(sl_price, entry_price - SL_ATR_MIN * at), 2)
                _dist_sl  = abs(entry_price - sl_price)
                _rr1      = abs(tp1 - entry_price) / _dist_sl if _dist_sl > 0 else 0

                if _rr1 < MIN_RR_TP1:
                    return {"signal": None,
                            "reason": f"RR insuffisant avec SL ATR: {_rr1:.2f} (min {MIN_RR_TP1})"}

                return {
                    "signal":    "long",
                    "setup":     "LONG -1SD→VWAP",
                    "tp_runner": round(sd1_h, 2),   # runner vise +1SD
                    "score":     round(score, 1),
                    "price":     entry_price,
                    "atr":       round(at, 2),
                    "sl_price":  sl_price,
                    "tp_price":  tp1,
                    "tp_poc":    round(sd1_h, 2),
                    "rr":        round(abs(tp1 - entry_price) / abs(entry_price - sl_price), 1)
                                 if abs(entry_price - sl_price) > 0 else round(est_rr, 1),
                    "vwap":      vwap,
                    "sd":        round(sd, 2),
                    "sd2_h":     sd2_h, "sd3_h": round(vwap + 3 * sd, 2),
                    "sd2_l":     sd2_l, "sd3_l": round(vwap - 3 * sd, 2),
                    "reason":    f"-1SD LONG | " + "+".join(tags)
                                 + f" | VWAP={vwap:.2f} SD={sd:.2f}",
                }

    return {
        "signal": None,
        "reason": (f"Pas de setup | Prix:{d_close:.2f} VWAP:{vwap:.2f} SD:{sd:.2f} "
                   f"+1SD:{sd1_h:.2f} -1SD:{sd1_l:.2f}"),
    }
