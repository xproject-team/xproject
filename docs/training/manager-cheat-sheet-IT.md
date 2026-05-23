# XProject — Guida Rapida Manager

**Sei il collegamento tra i bartender e il proprietario. Leggi questa pagina una volta prima dell'evento.**

---

## 1. Accesso

1. Apri XProject sul tablet o laptop
2. Tocca la card **Manager**
3. Inserisci email + password (te le fornisce il proprietario)
4. Atterrerai sulla dashboard del **tuo bar soltanto**

Se gestisci più bar, hai account separati — accedi con quello del bar in cui sei adesso.

---

## 2. Cosa vedi tu vs cosa vedono i bartender

| Cosa | Tu | Bartender |
|---|---|---|
| Livelli di stock | ✅ | ✅ |
| Ricavi | ✅ | ✅ |
| Alert depletion critici | ✅ | ✅ |
| **Alert di warning** | ✅ | ✅ |
| **Alert di anomalia (recipe deviation, demand spike)** | ❌ | ❌ |
| Chat dal proprietario | ✅ | ✅ |
| Altri bar | ❌ | ❌ |

**Gli alert di anomalia sono solo per il proprietario, by design.** Se il proprietario ti chiede di fare un "conteggio di routine" di un prodotto specifico, fallo senza domande — è così che funziona la silent investigation. Non chiedere perché. Conta e rispondi via chat.

---

## 3. Scanner — le tue 2 azioni

| Azione | Quando usarla |
|---|---|
| **DISPATCH** | "Sto inviando questa cassa dal magazzino al mio bar" — aumenta lo stock del bar, scala il magazzino |
| **RETURN** | "La rimando al magazzino" — scala lo stock del bar, aumenta il magazzino |

Scansiona sempre **prima** di muovere il prodotto, non dopo. Il sistema ha bisogno del timestamp coerente con la realtà.

---

## 4. Acknowledgment degli alert

Quando scatta un alert di depletion, hai 3 scelte:

1. **Acknowledge** — "Lo vedo, me ne occupo" → l'alert passa da attivo ad acknowledged
2. **Agire** — DISPATCH altro prodotto al bar, poi acknowledge
3. **Ignorare** — l'alert si auto-risolve quando lo stock torna sopra la soglia

Acknowledge il prima possibile anche se non puoi sistemarlo subito. Il proprietario vede gli alert non-acked accumularsi — è un segnale brutto.

---

## 5. Chat — la tua comunicazione bidirezionale

- **Da un bartender:** "Bacardi 1L è a 2 bottiglie" → rispondi con azione: "Dispatch in arrivo" o "Tira fino alle 23, poi rifornisco"
- **Dal proprietario:** considera che ogni messaggio del proprietario richieda risposta entro 5 minuti — sta gestendo l'evento dall'alto

Brevità > completezza. Il proprietario ha 5 bar; i messaggi lunghi lo rallentano.

---

## 6. Se qualcosa è rotto

| Sintomo | Prima azione |
|---|---|
| La dashboard non carica | Ricarica (Cmd+R o pull-down sul tablet) |
| Lo scanner non apre la fotocamera | Chiudi l'app, riapri, accetta i permessi della fotocamera |
| I numeri di stock sembrano sbagliati | Non correggerli — avvisa il proprietario. Numeri sbagliati potrebbero essere un bug da loggare |
| Un bartender non riesce a fare login | Conferma con il proprietario che l'account del bartender esista |
| L'intero sistema sembra giù | Problema del proprietario; tu continui a operare manualmente con la carta |

Il bar continua a funzionare anche se XProject è giù. Le vendite passano dal POS Slesh come al solito. XProject è il **livello di osservabilità**, non il livello cassa.

---

## 7. Fine evento

- Fai un giro finale sullo stock del tuo bar — INSPECT su qualsiasi cosa non sia stata tracciata stasera
- Conferma via chat al proprietario che il tuo bar è "chiuso"
- Logout

---

**Contatti d'emergenza durante l'evento:**
- **Proprietario (Omar):** _[compilato dal proprietario]_
- **XProject tecnico (Hesam):** _[compilato dal proprietario]_
- **Supporto POS Slesh:** _[compilato dal proprietario]_
