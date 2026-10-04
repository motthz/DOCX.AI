# Guida all'uso di DOCX.AI

DOCX.AI compila **qualsiasi modulo Word o Excel** (rapporti, verbali, richieste, schede,
checklist, offerte, moduli amministrativi…) partendo da informazioni scritte a parole
tue. L'intelligenza artificiale gira **sul tuo PC**: nessun dato viene inviato in
Internet. Ogni documento viene sempre **controllato e approvato da te** prima di
essere esportato.

![Home](img/home.png)

## 1. Primi passi

1. **Installa** l'app con `DOCX.AI-Setup.exe`: non servono diritti di amministratore.
   Sul Desktop compare il collegamento *DOCX.AI*.
2. Al primo avvio una breve procedura guidata chiede lingua e cartella dei dati.
3. **Installa il motore AI** (una volta sola, 0,7–2 GB): clicca su *AI non installata*
   in alto a destra, oppure lascia che lo faccia l'app se l'hai scelto nell'installer.
   Da quel momento l'AI funziona anche senza Internet.
4. Segui il **tour guidato** delle funzioni principali (lo rivedi da
   *Impostazioni → Aiuto e supporto*).

> Senza AI installata l'app funziona lo stesso: la bozza ha i campi vuoti da compilare
> a mano nella revisione.

> Aggiornamento da MaintenanceAI: i tuoi moduli, documenti e impostazioni vengono
> spostati automaticamente in DOCX.AI al primo avvio.

## 2. Moduli

Un **modulo** è il modello del documento: un tuo file Word (DOCX) o Excel (XLSX) in cui
i punti da compilare sono scritti come `{{nome_campo}}`, per esempio
`Cliente: {{cliente}}` oppure `Data della riunione: {{data_riunione}}`.

- **Nuovo modulo** (barra laterale o `Ctrl+N`): scegli *Da un mio file* e seleziona il
  DOCX/XLSX. Campi e mappatura vengono creati da soli. Indica il **tipo di documento**
  (es. "verbale di riunione", "richiesta d'acquisto"): l'AI lo usa per capire il contesto.
- **Editor template** (scheda *Modulo*): seleziona un testo nell'anteprima del
  documento e trasformalo in un campo, senza aprire Word né scrivere JSON.

  ![Editor del template](img/editor-template.png)

- **Documenti di riferimento**: listini, procedure, contratti, manuali (anche PDF e
  scansioni) nella cartella *Documenti di riferimento* del modulo. L'AI li usa come
  istruzioni e contesto, mai come prova dei fatti del documento corrente.
- **Regole AI del modulo**: istruzioni permanenti (es. "scrivi gli importi con due
  decimali"). L'AI le legge ma non può modificarle.

Esempi già pronti nella cartella `examples/modules`: *Verbale di riunione* (DOCX),
*Richiesta d'acquisto* (XLSX) e un rapporto di intervento tecnico.

## 3. Compilare un documento

![Compila](img/rapporto.png)

1. Seleziona il modulo nella barra laterale e apri la scheda **Compila**.
2. Scrivi le informazioni a parole tue, nell'ordine che preferisci: chi, cosa, quando,
   dove, importi, decisioni, esiti. Più dettagli dai, più campi vengono compilati. Puoi anche:
   - **aggiungere foto o immagini** (o aprire la *Fotocamera* di Windows): finiscono nel PDF;
   - passare a **Da documenti** per compilare leggendo altri file, tabelle o scansioni.
3. Premi **Compila con AI** (`Ctrl+E`). Le fasi (Contesto → AI → Verifica fonti →
   Revisione → Export) sono mostrate sotto il pulsante; con *Mostra l'output dell'AI in
   tempo reale* vedi il testo mentre viene generato.

### Opzioni

| Opzione | Effetto |
|---|---|
| Documenti di riferimento | Il materiale del modulo come istruzioni per l'AI |
| Storico del modulo | I documenti già approvati insegnano forma e terminologia (i dati non vengono copiati) |
| Controllo delle fonti | In revisione evidenzia i valori che non compaiono nelle informazioni fornite |
| Creatività dell'AI | Bassa = più fedele al testo (consigliato) |

## 4. Revisione e approvazione

![Revisione affiancata](img/revisione.png)

La revisione mostra **a sinistra le fonti** (il tuo testo e i documenti) e **a destra
i campi**. Cliccando un campo, il suo valore viene evidenziato nelle fonti.

- **Trovato nelle fonti**: il valore compare nel testo o nei documenti.
- **Da verificare** (rosso): numeri, codici, date, importi o nomi che **non** compaiono
  nelle fonti, cioè probabili invenzioni dell'AI. Controllali sempre.
- **Dedotto**: valore scelto da un elenco o sì/no, non verificabile parola per parola.
- **Mancante**: campo vuoto o `NON_SPECIFICATO`.

Sui testi lunghi **Migliora testo** riscrive la frase in forma chiara e professionale
senza aggiungere fatti (puoi annullare). La bozza viene **salvata automaticamente** ogni
20 secondi: se chiudi, la ritrovi in *Home → Bozze da completare*.

**Approva e genera il documento** produce nella cartella di esportazione:

- `*.pdf`: il documento impaginato, con le immagini;
- `*.docx` / `*.xlsx`: il tuo modello compilato;
- `*.json`: i dati approvati (fonte ufficiale).

Dalla finestra finale puoi aprire l'**anteprima PDF**, stampare o preparare un'**email**.

## 5. Storico

![Storico](img/storico.png)

- **Ricerca globale** (`Ctrl+F`) nel contenuto di tutti i documenti compilati.
- **Filtri** per stato, modulo, periodo (*gg/mm/aaaa*) e **per qualsiasi campo** del
  modulo (es. *Cliente = ACME*, *Urgenza = alta*).
- **Azioni** sui documenti selezionati (anche con il tasto destro): anteprima PDF,
  apri/modifica, **duplica**, **versioni**, cartella, elimina.
- **Esporta Excel**: riepilogo dei documenti filtrati, una riga per documento.
- **Importa da tabella**: ogni riga di un CSV/Excel diventa un documento, associando
  le colonne ai campi del modulo.

### Versioni

Ogni approvazione o modifica successiva salva una **versione**: la finestra *Versioni*
mostra cosa cambia rispetto alla versione attuale e permette di ripristinarla.

![Versioni](img/versioni.png)

## 6. Documenti AI

![Documenti AI](img/documenti-ai.png)

| Strumento | A cosa serve |
|---|---|
| Crea documento | Procedure, istruzioni, lettere o relazioni a partire dai documenti di riferimento |
| Modifica documento | Nuova versione di un DOCX/PDF/scansione secondo le tue richieste |
| Audit documenti | Contraddizioni, date incoerenti, dati mancanti, revisioni non allineate |
| Compila da documenti | Compila un modulo leggendo altri documenti, tabelle e scansioni |
| Testo da scansione (OCR) | Estrae il testo da foto e PDF scansionati con l'OCR di Windows |
| Regole AI | Istruzioni permanenti per funzione o per modulo |

Gli originali non vengono mai modificati: ogni risultato è una nuova versione.

## 7. Impostazioni

![Impostazioni](img/impostazioni.png)

- **Aspetto**: tema chiaro, scuro o *come Windows*; lingua (italiano/inglese);
  **dimensione del testo** (80–160%).

  ![Tema scuro](img/home-scuro.png)

- **Intelligenza artificiale**: profilo (*compatibility* per PC lenti, *balanced*
  consigliato, *fastest*), **accelerazione GPU** (schede con driver Vulkan),
  precaricamento, spegnimento dopo inattività, thread CPU, contesto, **ricerca semantica**
  nei documenti, controllo delle fonti.
- **Dati e backup**: cartella dati (anche **di rete**, con blocco contro l'uso
  contemporaneo da due PC), **backup** in un file ZIP, **ripristino**, backup automatico.
- **Aiuto e supporto**: questa guida, tour guidato, **pacchetto diagnostico** (log senza
  i tuoi documenti) e **segnalazione di un problema**.

![Componenti AI](img/componenti-ai.png)

## 8. Scorciatoie da tastiera

| Tasti | Azione |
|---|---|
| `Ctrl+1` … `Ctrl+6` | Home, Compila, Storico, Modulo, Documenti AI, Impostazioni |
| `Ctrl+Tab` / `Ctrl+Shift+Tab` | Scheda successiva / precedente |
| `Ctrl+N` | Nuovo modulo |
| `Ctrl+E` | Compila con AI |
| `Ctrl+F` | Cerca nello storico |
| `Ctrl+B` | Mostra/nascondi la barra laterale |
| `Ctrl+,` | Impostazioni |
| `F1` | Guida |
| `F5` | Ricarica i moduli |
| `Esc` | Chiude la finestra di dialogo |
| `Canc` | Elimina i documenti selezionati (Storico) |

## 9. Domande frequenti

**Funziona con i miei moduli?** Sì, con qualsiasi DOCX o XLSX: basta indicare i punti da
compilare con `{{nome_campo}}` (o usare l'editor template). Con descrizioni dei campi e
tipo di documento l'AI è più precisa.

**L'AI inventa dei dati?** Le regole interne le vietano di inventare date, nomi, codici,
importi e numeri, e il *controllo delle fonti* evidenzia in rosso i valori che non
compaiono nelle fonti. Il modello leggero (0.6B) sbaglia più spesso: con almeno 6 GB di
RAM usa l'1.7B.

**Serve Internet?** Solo per scaricare una volta i componenti AI.

**L'AI è lenta.** Usa il profilo *compatibility*, attiva la GPU se disponibile, chiudi i
programmi che occupano RAM.

**Dove sono i miei dati?** In `%LOCALAPPDATA%\DOCX.AI` (o nella cartella scelta in
*Impostazioni → Dati*). Fai un **backup** periodico; quello automatico è settimanale.

**Posso usare l'app da più PC?** Sì, con una cartella dati di rete, ma non dallo stesso
archivio contemporaneamente: l'app avvisa se succede.

**Windows mostra "PC protetto da Windows".** L'installer non è firmato digitalmente:
clicca *Ulteriori informazioni → Esegui comunque*.

**Qualcosa non funziona.** *Impostazioni → Aiuto e supporto → Segnala un problema*.
