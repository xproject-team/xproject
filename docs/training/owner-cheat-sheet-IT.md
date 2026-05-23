# XProject — Guida Rapida Proprietario

**Per Omar. La piattaforma lavora per te, non viceversa. Due pagine.**

---

## 1. La dashboard ti dice 4 cose a colpo d'occhio

1. **Ricavi totali stasera** — in alto, si aggiorna ogni pochi secondi
2. **Griglia dei bar** — una card per bar, con un bordo colorato che indica lo stato
   - Bordo verde = tutto bene
   - Bordo giallo = almeno un alert di warning
   - Bordo rosso = almeno un alert critico
3. **Colonna alert (a destra)** — tutti gli alert di tutti i bar, dai più recenti
4. **Chat** — la tua linea bidirezionale con ogni manager

Tocca una card per aprire la vista di dettaglio di quel bar.

---

## 2. Le 3 classi di alert che vedrai

| Classe | Significato | Audience |
|---|---|---|
| **Depletion** | Un prodotto specifico finirà entro 2 ore | Tu + il manager di quel bar |
| **Anomalia — Demand spike** | Un prodotto vende 2-3× più veloce del normale | Solo tu (silenzioso — il manager non lo vede) |
| **Anomalia — Recipe deviation** | Un bar usa più ingrediente di quanto la ricetta preveda | Solo tu (silenzioso — il manager non lo vede) |

Le classi di anomalia "silenziose" sono volute. Ti danno visibilità su possibili problemi di staff (over-pour, ammanchi, errori di conteggio) senza mettere il manager sulla difensiva o avvisare lo staff. **Quando fai acknowledge di un alert di anomalia** parte un messaggio neutro "per favore fate un conteggio di routine" alla chat del bar — il manager indaga senza sapere che tu sospetti qualcosa.

---

## 3. Acknowledgment degli alert

Tocca la card di un alert → **Acknowledge**

Cosa succede:
- L'alert esce dalla lista attiva
- Per le anomalie: un messaggio neutro viene postato automaticamente nella chat di quel bar
- L'acknowledgment è loggato per sempre (puoi consultarlo dopo)

Puoi anche **resolve** un alert manualmente se l'hai gestito. La resolution è permanente.

---

## 4. La chat — il tuo telecomando

- Scrivi direttamente a qualsiasi manager
- I messaggi arrivano in tempo reale
- Il manager vede il tuo nome e il timestamp
- Usa la chat per chiedere conteggi, dare istruzioni o semplicemente dire "grazie"

**Non** puoi scrivere direttamente a un bartender — by design. Tutta la comunicazione passa dal manager. Così il numero di canali resta gestibile con 5+ bar.

---

## 5. Quando NON fidarti della dashboard

XProject legge i dati di vendita da Slesh, che ha la sua latenza. Numeri realistici:

- Aggiornamento ricavi: **ogni 30 secondi** (cron interroga Slesh)
- Aggiornamento stock: **immediato** quando avviene una scansione, **30 sec di ritardo** quando le vendite riducono lo stock
- Valutazione alert: **ogni 5 minuti** (cron)

Se il cron si blocca, gli alert tacciono. Diagnostica:

```bash
./scripts/alert-pipeline-check.sh
curl -s http://localhost:8000/api/v1/health/deep | python3 -m json.tool
```

Il primo comando dimostra che gli alert scattano ancora. Il secondo ti dice quale sottosistema (Postgres, Redis, MinIO) è giù.

---

## 6. Se qualcosa va storto

| Sintomo | Prima azione |
|---|---|
| La dashboard non mostra nulla | Lancia il deep health check (sopra) — vedi quale componente fallisce |
| Il bar X sembra morto | Chiama il manager del bar. Magari sta solo attraversando un momento tranquillo |
| Un alert sembra sbagliato | Fidati. Manda un manager a verificare fisicamente. I falsi positivi sono rari e valgono un controllo di 30 sec |
| L'intero sito è irraggiungibile | Slesh continua a funzionare. Il bar continua a vendere. Hesam aggiusta la piattaforma dal suo laptop. Tu continui a lavorare di pancia |

La piattaforma è **assicurazione + leva**, non un singolo punto di rottura. I bar girano con o senza di lei.

---

## 7. Report di fine evento

Dopo la chiusura di Sundance:
- La pagina Reports genera automaticamente un PDF per evento (italiano + inglese)
- Include: ricavi totali, top product, top bar, anomalie rilevate, scostamenti di stock
- Mandalo al tuo commercialista la mattina dopo

Se vuoi una vista specifica dei dati (es. "ricavi per ora dei cocktail"), dillo a Hesam — la aggiunge al template del report per la prossima volta.

---

## 8. Linea diretta

- **XProject tecnico (Hesam):** _[tuo numero]_
- **Supporto POS Slesh:** _[contatto Slesh]_

Chiama, non scrivere. Durante l'evento il tuo schermo è pieno di dashboard.
