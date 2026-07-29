[AUDIT_CHANGELOG.md](https://github.com/user-attachments/files/30524511/AUDIT_CHANGELOG.md)
# AUDIT BOT 2 — VWAP SD Scalper · Changelog du 2026-07-29

Référence pour le prochain audit. Version déployée après correction complète
des points 1–8 (audit initial sur 43 trades, 27–29/07/2026).

---

## Bugs corrigés (Point 1)

1. **#ERROR! dans le journal** — les labels de setup short commençaient par `+`,
   interprété comme formule par Google Sheets (mode USER_ENTERED via N8N).
   → Labels renommés : `SHORT +3SD→+2SD`, `SHORT +2SD→+1SD`, `LONG -3SD→-2SD`,
   `LONG -2SD→-1SD`. Fonction `_sheet_safe()` en ceinture de sécurité.
   ⚠️ Correspondance ancien journal : `-2SD→-1SD` = `LONG -2SD→-1SD`, etc.
2. **VWAP jamais ancré à la session** — double division du timestamp par 1000
   dans `calc_vwap_session()` : le filtre de session était toujours vide, le bot
   tradait un VWAP glissant ~12h30 avec des bandes SD fausses. Corrigé : ancrage
   réel 07:00 (Londres) / 13:00 (NY) / 00:00 UTC.
   ⚠️ Invalide partiellement l'historique pré-correction.
3. **Colonne Heure_UTC en heure suisse** — décalage +2h sur toutes les analyses
   par session. Journal désormais en vrai UTC.
4. **Kill switch** — `validate_signal()` : aucun ordre si signal incomplet,
   NaN, label invalide ou géométrie incohérente (long : SL < entrée < TP1).

## Filtres de régime (Point 2) — shorts conservés et encadrés

- `VOLATILITY_SPIKE_MAX = 1.6` : ATR > 1.6× moyenne 30 bougies → aucun trade
  (news/parabole). Filtre DUR, deux sens.
- `TREND_PERSIST_N/K = 4/3` : 3 closes 15m sur 4 au-delà de ±2SD → tendance
  installée → côté contre-tendance interdit.
- `MIN_SCORE_SHORT = 5.0` (vs 4.0 long) : biais haussier structurel de l'or.
- Confirmation 1m renforcée : bougie directionnelle doit casser l'extrême de la
  bougie précédente (`1m_Bear+Break` / `1m_Bull+Break`) ; pin bar exige une
  mèche ≥ 50% de l'amplitude.
- Lockout directionnel : 2 SL consécutifs même direction → direction interdite
  2h (`CONSEC_SL_LOCKOUT_N = 2`, `DIRECTION_LOCKOUT_SEC = 7200`).

## Shadow log (Point 2b)

Chaque setup détecté mais refusé écrit une ligne `SIGNAL_BLOQUE` dans le sheet
avec le motif (throttle : 1/motif/15 min). Motifs : Expansion volatilité,
tendance installée, confirmation 1m absente, Lockout, DD, Anti-cluster,
KILL SWITCH, RR insuffisant. → Mesure le coût réel des filtres en fréquence.

## Stops (Point 4)

- SL recalculé depuis l'ENTRÉE RÉELLE (close 1m), plancher `SL_ATR_MIN = 1.0`
  (médiane historique : 0.56×ATR ; 20/24 pertes mortes en <60s).
- Taille de position auto-ajustée (risque $ constant via `calc_qty_risk`).
- Double contrôle géométrique final : `MIN_RR_TP1 = 0.9` ET `MIN_RR_TP2 = 1.5`,
  sinon refus tracé. Calibré : conserve ~72% du flux historique.

## Anti sur-trading corrélé (Point 5)

- `MAX_POSITIONS_PER_SIDE = 1` : jamais 2 positions simultanées même direction.
- `ENTRY_COOLDOWN_SEC = 180` : 3 min entre 2 entrées de même direction.
- Note d'audit : le "cluster ×13" du 28/07 était séquentiel (exposition max
  réelle = 2 via MAX_POSITIONS) ; le cooldown 15 min initialement envisagé
  détruisait l'edge (simulation : +11$ vs +244$) → protection ciblée retenue.

## Risque (Point 6)

- `RISK_PER_TRADE = 0.01` (1%) en phase de validation — le capital paper
  achète des données. Chaque perte = 1R = ~5$ sur 500$.
- `REDUCED_RISK_HOURS` SUPPRIMÉ (redondant avec le filtre volatilité, brouillait
  la lecture en R : pertes -2$ vs -15$).
- Paliers drawdown CONSERVÉS (DD ≥ 10% → risque ÷2).
- Nouvelles colonnes journal : `Risque_USD`, `Risque_Pct`.
  ⚠️ ACTION MANUELLE : ajouter ces 2 colonnes au Google Sheet + mapper dans N8N.

## Runner (Point 7) — spec Anna

- Phase 1 : 2 lots, SL initial. TP1 → Lot 1 fermé, SL Lot 2 = TP1.
- Phase 2 : TP2 → 50% du Lot 2 fermé (`RUNNER_TP2_KEEP = 0.50`), 50% court.
- Phase 3 : plancher runner = TP1 (jamais en dessous). Sorties : objectif TP3
  (bande suivante : ±2SD→VWAP opposé selon setup, champ `tp_runner`), OU
  trailing Chandelier 1.5×ATR, OU stall 20 boucles.
- Mystère des colonnes runner vides élucidé : TP2 jamais atteint sur les 43
  trades historiques (bandes fausses + stops trop serrés), pas un bug Phase 3.

## Supprimé (Point 8)

- `SESSION_HOURS_UTC` : code mort jamais branché, purgé.

---

## Prochain audit — checklist

Après 5–7 jours de paper SANS modification :
1. Exporter le sheet complet (trades + lignes SIGNAL_BLOQUE) en CSV.
2. Mesures clés :
   - Expectancy en R (possible grâce à Risque_USD/Pct) et win rate.
   - Fréquence : trades/jour vs signaux bloqués/jour, par motif → ajuster
     les seuils des filtres si étranglement (tout est dans config.py).
   - **P(TP2 | TP1)** : % des trades ayant atteint TP1 qui touchent TP2.
     ≥ ~25-30% → structure runner conservée ; < ~20% → simplifier
     (tout au TP1 ou 75/25). Phase_Atteinte + Prix_Sortie_Runner suffisent.
   - Distribution des durées de trades (les pertes <60s doivent avoir disparu).
   - Comportement du VWAP session : mutisme normal ~30-45 min en début de
     session (garde sd < 0.50 — ce n'est PAS une panne).
3. Point 9 restant (frais/slippage) : à traiter au passage en réel uniquement.

## Rappels méthodologiques

- Ne pas modifier les paramètres pendant la collecte (chaque changement remet
  les statistiques à zéro).
- Les simulations de cet audit sont in-sample (filtres conçus sur les mêmes
  43 trades) : les chiffres (+244$ etc.) sont des plafonds indicatifs, pas des
  promesses. Seul le paper hors-échantillon fait foi.
- Objectif réaliste : expectancy positive après frais et drawdown maîtrisé sur
  un échantillon significatif (200+ trades) — pas de "surperformance
  quotidienne", qui n'existe pour personne.
