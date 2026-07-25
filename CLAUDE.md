# CLAUDE.md — Contexte Trading Bots Anna

Ce fichier me donne le contexte complet des deux bots de trading gold d'Anna.
Lis-le intégralement avant toute intervention sur le code.

---

## Profil utilisateur

- **Prénom** : Anna
- **Profil** : non-technique, basée en Suisse
- **Broker** : Bitget (futures XAU/USDT perpetual)
- **Infrastructure** : Railway (déploiement auto depuis GitHub) + N8N (journal) + Telegram (alertes)
- **Capital** : $500 par bot · Levier 20x · PAPER_MODE = True (simulation)
- **Langue** : français

---

## BOT 1 — Volume Profile Scalper

### Localisation des fichiers
```
gold-bot-share/
├── bot.py          ← logique principale + gestion positions
├── strategy.py     ← 6 setups Volume Profile + filtre EMA
├── config.py       ← tous les paramètres
├── bitget.py       ← client API Bitget v2
└── dashboard.py    ← dashboard web
```

### Stratégie
- **Timeframe** : 1 minute
- **Cœur** : Volume Profile (POC, VAH, VAL, HVN)
- **Filtre directionnel** : EMA 20/50 — EMA20>EMA50 = LONG only / EMA20<EMA50 = SHORT only
- **6 setups** :
  - LONG  : L1 VAL→POC · L2 POC→VAH · L3 HVN support→POC
  - SHORT : S1 VAH→POC · S2 POC→VAL · S3 HVN résistance→POC
- **Filtres** : CDV (Cumulative Delta Volume) + Pin Bar + Score minimum + RR minimum

### Gestion de position (4 phases)
```
Phase 1 : Entrée 2 lots (Lot1 + Lot2) · SL initial
Phase 2 : TP1 atteint → Lot1 fermé · Lot2 SL = TP1 (profit garanti)
Phase 3 : TP2/POC atteint → 70% Lot2 fermé · 30% runner actif · SL plancher = TP2
Runner  : Chandelier Exit 1.5×ATR depuis highest close · Time exit 15 bougies
```

### Paramètres clés (config.py)
```python
CAPITAL        = 500
RISK_PER_TRADE = 0.02      # 2%
LEVERAGE       = 20
VP_LOOKBACK    = 60        # bougies
ATR_SL         = 1.2
ATR_TP1        = 1.8
RUNNER_PCT     = 0.50      # 50% des contrats en Lot2
RUNNER_TP2_KEEP = 0.30     # 30% du Lot2 continue en runner au TP2
RUNNER_TRAIL_ATR = 1.5     # Chandelier Exit
RUNNER_MAX_STALL = 15      # bougies sans nouveau plus haut
MIN_SCORE      = 4.0       # /8
MIN_RR         = 1.0
LOOP_SECONDS   = 60
PAPER_MODE     = True
```

### Protections
- Drawdown 3 niveaux : 5% (score↑) / 10% (risque↓) / 15% (pause 1h)
- Cooldown 5min après SL
- Heures risque réduit (UTC) : 6h, 13h, 15h, 17h → 0.5% au lieu de 2%
- Filtre volatilité : ATR > 2.5× moyenne → pas de trade (news)
- Guard TP2 : si TP2 invalide vs TP1 → runner désactivé

### Journal N8N — Google Sheets
- Webhook séparé (URL dans variable Railway N8N_WEBHOOK_URL)
- Champs : Date, Heure_UTC, Type, Setup, Score, Entree, SL, TP1, TP2_POC, ATR, RR_Cible,
  Phase_Atteinte, Resultat, PnL_Lot1, PnL_Lot2, PnL_Total, Capital_Avant, Capital_Apres,
  Duree_min, Prix_Sortie_Runner, Runner_Bonus_vs_TP2

### Telegram Bot 1
- Bot dédié (@GoldAnna369Bot)
- Variables Railway : TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

---

## BOT 2 — VWAP SD Scalper

### Localisation des fichiers
```
gold-bot2-vwap/
├── bot.py          ← logique principale (loop 5min)
├── strategy.py     ← 4 setups VWAP SD + liquidités
├── config.py       ← paramètres bot 2
├── bitget.py       ← identique bot 1 (copie)
└── dashboard.py    ← identique bot 1 (copie)
```

### Stratégie
- **Timeframe** : 5 minutes
- **Cœur** : VWAP journalier (reset 00:00 UTC) + bandes ±1SD/±2SD/±3SD
- **Logique** : mean-reversion institutionnelle
- **4 setups** :
  - SHORT +2SD → TP1 VWAP · TP2 runner -1SD
  - SHORT +3SD → TP1 VWAP · TP2 runner -1SD (priorité, plus rare)
  - LONG  -2SD → TP1 VWAP · TP2 runner +1SD
  - LONG  -3SD → TP1 VWAP · TP2 runner +1SD (priorité)
- **Filtres** : Sweep de liquidité (stop hunt détecté) + Pin Bar + CDV retournement

### Gestion de position
Identique Bot 1 (3 phases + runner Chandelier) — cohérence totale entre les deux bots.

### Paramètres clés (config.py)
```python
CAPITAL        = 500
RISK_PER_TRADE = 0.02
LEVERAGE       = 20
INTERVAL       = "5m"
TOL_SD_MULT    = 0.25      # tolérance contact SD = 0.25 × SD
SWEEP_LOOKBACK = 10        # bougies pour détecter sweep liquidité
CDV_PERIOD     = 20
MIN_SCORE      = 4.0       # /9
MIN_RR         = 1.2
RUNNER_PCT     = 0.50
RUNNER_TP2_KEEP = 0.30
RUNNER_TRAIL_ATR = 1.5
RUNNER_MAX_STALL = 10      # bougies 5m (= 50 minutes)
LOOP_SECONDS   = 300       # 5 minutes
CANDLES_NEEDED = 400       # ~33h de bougies 5m
PAPER_MODE     = True
```

### Journal N8N — Google Sheets (séparé du bot 1)
- Webhook séparé
- Champs supplémentaires vs bot 1 : Bot (="BOT2_VWAP"), VWAP, SD
- Même structure sinon pour comparaison cohérente

### Telegram Bot 2
- Nouveau bot à créer via @BotFather
- Variables Railway séparées : TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

---

## Infrastructure Railway

- **Même abonnement Railway** — deux services distincts sous le même compte
- Bot 1 : repo GitHub `gold-bot-share` → service Railway actif
- Bot 2 : repo GitHub `gold-bot2-vwap` → nouveau service à créer (même projet)
- Variables d'environnement à définir par service :
  API_KEY, API_SECRET, PASSPHRASE, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, N8N_WEBHOOK_URL

---

## Décisions importantes prises

- **EMA 20/50** choisi (pas 9/21) : meilleur équilibre réactivité/stabilité pour 1m scalping
- **RUNNER_PCT 50%** : Lot2 = 50% des contrats totaux
- **RUNNER_TP2_KEEP 30%** : au TP2, 70% du Lot2 fermé, 30% continue en runner
- **Chandelier sur close** (pas high) : filtre les mèches de l'or sur 1m
- **SL runner = TP2** (jamais en dessous) : worst case Lot2 = toujours TP1
- **Guard TP2 < TP1** en strategy.py : pour VAL→POC, si POC<TP1 → tp_poc = VAH
- **PAPER_MODE = True** sur les deux bots jusqu'à validation des données (2 semaines)
- **Pas de VWAP dans bot 1** : intégration reportée après collecte de données
- **Rapport hebdo N8N** : prévu mais reporté (attente données 2 semaines)
- **Backtesting** : à construire après 2 semaines de journal (Google Sheet → Markdown → Claude)

---

## Prochaines étapes

1. Attendre 2 semaines de données bot 1 (sans modifier le code)
2. Déployer bot 2 sur Railway (nouveau repo GitHub + nouveau service)
3. Dans 2 semaines : analyse comparative bot 1 vs bot 2 via journal Google Sheets
4. Construire le workflow N8N de rapport hebdo (dimanche 20h → Markdown → Telegram)
5. Décider si passage en LIVE sur le meilleur des deux bots
