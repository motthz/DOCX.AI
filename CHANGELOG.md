# Changelog di DOCX.AI (già MaintenanceAI)

Formato basato su [Keep a Changelog](https://keepachangelog.com/it/1.1.0/),
versionamento [SemVer](https://semver.org/lang/it/). La versione ha un'unica
fonte: `src/docx_ai/__init__.py`.

## [Non rilasciato]

## [0.9.0] - 2026-10-07

### Migliorato
- **Compilazione molto più precisa con il modello intermedio (Qwen3 1.7B).**
  - Per ogni campo l'AI deve citare la frase del testo da cui prende il valore, poi scrivere il valore:
    cerca l'informazione nel testo prima di rispondere (meno campi saltati) e il programma verifica che la
    frase esista davvero. Sì/No e scelte da elenco senza una frase che li confermi vengono tolti (erano
    deduzioni inventate), così come un Sì quando la frase lo esclude ("nessun fermo macchina" per il campo
    "fermo impianto") e le caselle Sì e No spuntate insieme.
  - Il significato dei campi viene ricavato dal nome anche senza descrizione: `data` e `data_intervento`
    sono date, `firma_operatore` è un nome, `numero_rapporto` un codice. Prima i campi data senza formato
    non venivano riconosciuti né verificati.
  - Con i modelli piccoli i campi vengono compilati a gruppi di 5 (prima 8) e l'elenco dei campi, con il
    loro significato, è ripetuto subito prima della risposta. Il prompt contiene un esempio di compilazione.
  - Tutti i campi sono obbligatori nella risposta: prima il modello poteva chiudere il JSON saltando i
    campi facoltativi.
- **Date riconosciute in molte più forme** e calcolate dal programma: "lunedì scorso", "venerdì
  prossimo", "il 15" (mese della data citata prima), "dal 3 al 5 ottobre", "primo ottobre", "entro il
  30/11", "tra due settimane", "3 giorni fa". Ogni data viene assegnata al campo giusto guardando le
  parole vicine ("riunione del 2 ottobre", "prossimo incontro il 15"): i campi data rimasti vuoti vengono
  completati, una data messa nel campo sbagliato viene spostata, una data scritta a parole viene
  convertita. Nei documenti esportati le date sono scritte come 05/10/2026.
- **Migliora testo**: la risposta è solo il testo (niente "Ecco il testo riscritto:"), viene controllata
  (codici, numeri, date o nomi aggiunti o persi vengono segnalati e provocano un secondo tentativo), il
  pulsante mostra l'avanzamento e, se il campo è vuoto, l'AI lo scrive dalle informazioni fornite.
- **Revisione**: cliccando un campo viene evidenziata nelle fonti la frase da cui l'AI ha preso il valore.

### Corretto
- La barra dei moduli a sinistra spariva: chiudendo l'app ridotta a icona (o durante un aggiornamento
  automatico) veniva salvata una larghezza di 1 pixel, ripresa a ogni avvio. Ora la larghezza è sempre
  tra 220 e 520 pixel.
- La scheda *Modulo* poteva mostrare il modulo selezionato in precedenza.

## [0.8.0] - 2026-10-06

### Migliorato
- **Moduli lunghi compilati a gruppi di campi.** Invece di chiedere tutti i campi in una sola risposta
  (un modello piccolo ne saltava molti e, sui PC lenti, la richiesta poteva scadere senza risultato),
  l'AI compila circa 8 campi alla volta. Il testo dell'utente viene letto una sola volta e riusato dalla
  cache per i gruppi successivi; se un gruppo non riesce gli altri campi restano compilati e quelli
  mancanti sono segnalati in revisione.
- **Date corrette anche con il modello piccolo.** Le date del testo ("1 ottobre 2026", "ieri",
  `05/10/2026`) vengono convertite dal programma e passate all'AI già pronte: prima il modello piccolo
  scriveva spesso la data di oggi in ogni campo data e il controllo dei fatti la toglieva.
- **AI più veloce sulla CPU**: un thread per core fisico (prima al massimo 6), tutti i core per leggere
  il testo, un solo slot del server, così la cache del prompt resta valida anche tra una bozza e l'altra.
  Il "ragionamento" del modello è bloccato anche lato server (a volte esauriva i token e la risposta
  arrivava vuota dopo minuti).
- **Modelli consigliati in base al PC**: *Qwen3 4B Instruct* (il più preciso) con una scheda video
  dedicata o una CPU recente; *Qwen3 1.7B a 4 bit* (circa 30% più veloce del precedente, stessa
  precisione nelle prove) per i PC datati; lo 0.6B solo sotto i 4 GB di RAM. L'app propone una volta il
  modello più adatto se quello installato è superato. I profili *compatibility* e *fastest* usano il
  modello veloce invece dello 0.6B con 2 thread.
- **GPU solo se conviene**: in automatico l'accelerazione si usa con una scheda video dedicata (almeno
  4 GB); sulla grafica integrata poteva essere più lenta della CPU. Se la scheda c'è ma manca il
  componente GPU, l'app lo suggerisce.
- **Interfaccia più reattiva**: le Impostazioni si aprono in 1,5 s invece di 5 (la scheda video viene
  rilevata dal registro di Windows invece che con PowerShell), la pagina del modulo non viene più
  ricostruita a ogni apertura.

### Corretto
- Editor visuale: un errore compariva se l'impaginazione del modulo terminava dopo la chiusura
  dell'editor (o il passaggio alla vista semplificata).

## [0.7.0] - 2026-10-06

### Aggiunto
- **Controllo automatico dei fatti, anche con il modello piccolo.** Dopo ogni compilazione l'app, senza
  usare l'AI, confronta con il testo dell'utente (e i documenti di riferimento):
  - **date**, in qualsiasi formato (`05/10/2026`, `5 ottobre`, `2026-10-05`) o a parole ("oggi",
    "ieri", "lunedì scorso", "tra due settimane"): giorno/mese scambiati e anno sbagliato vengono
    corretti, una data senza riscontro viene tolta;
  - **numeri** dei campi numerici (anche `1.250,50` o "due ore");
  - **codici** e matricole nei campi brevi e **nomi** di persone/aziende.
  Un valore senza riscontro non arriva nel documento: il campo resta da compilare e un avviso indica
  quali campi sono stati corretti. Vale anche per la compilazione da documenti.
- **Editor visuale fedele al modulo.** Il documento Word si vede con le sue pagine vere (caratteri,
  tabelle, immagini, intestazioni, margini), impaginato da Microsoft Word o LibreOffice se presenti; i
  campi si trascinano direttamente sulla pagina e si può selezionare col mouse un testo d'esempio da
  sostituire. Senza Word/LibreOffice resta la vista semplificata, con un collegamento per scaricare
  LibreOffice (gratuito).
- **Editor Excel fedele**: larghezze e altezze reali, righe/colonne nascoste, celle unite, colori (anche
  del tema), bordi, caratteri, allineamenti, testo a capo, formati numerici e immagini.
- **PDF esportato identico al modulo**: con Word o LibreOffice il PDF è il modulo compilato impaginato
  (note di revisione e foto in coda); senza, resta il PDF riassuntivo.

### Corretto
- Editor (vista semplificata): le celle unite in verticale venivano ripetute in ogni riga e il testo
  perdeva grassetto, corsivo, sottolineato e allineamento.
- Il controllo delle fonti in revisione segnava in rosso date corrette scritte a parole ("ieri") o senza
  anno ("5 ottobre").

## [0.6.0] - 2026-10-06

### Corretto
- **Risposte dell'AI sbagliate o vuote.** Il prompt (fino a 14.000 caratteri) più la risposta superavano
  il contesto del modello (4096 token): llama-server rifiutava la richiesta o ne perdeva una parte, e il
  modulo restava pieno di "NON_SPECIFICATO" o di valori casuali. Ora il contesto è di 8192 token e il
  prompt viene dimensionato sul modello in uso.
- Quando il prompt era troppo lungo veniva tagliato **proprio il testo scritto dall'utente** (che era in
  fondo): ora si accorciano prima documenti di riferimento ed esempi dello storico, mai la richiesta.
- I campi a scelta senza informazione ricevevano **sempre la prima opzione** e i campi numerici **0**:
  valori inventati presentati come certi. Ora l'AI può rispondere "non specificato" e il campo resta da
  compilare in revisione. Accettati anche numeri all'italiana (`1.250,50`).
- L'AI non conosceva la data di oggi: "ieri", "lunedì scorso", "oggi" diventavano date inventate.
- Il ragionamento ("thinking") di Qwen3 restava attivo e consumava la risposta: ora è disattivato tramite
  il template di chat del modello.
- Al terzo tentativo i campi facoltativi venivano tolti dallo schema e andavano persi.
- Se l'AI falliva tutti i tentativi, la bozza vuota sembrava una risposta dell'AI: ora c'è un avviso.
- Documenti AI (compilazione smart, audit): stesse correzioni (contesto, data, "non specificato");
  il testo generato non contiene più blocchi `<think>`.

### Aggiunto
- **Modello Qwen3 4B** (~2,5 GB) per risposte molto più precise, consigliato dai 10 GB di RAM.
  L'app usa automaticamente il **modello più preciso installato** che entra nella RAM libera; a chi
  ha già l'AI installata e un PC adatto viene proposto una volta.
- Installer: scelta "Automatico" del modello in base alla RAM (`/AIMODEL=auto|4b|1.7b|0.6b|none`).
- Il prompt descrive meglio i campi (titolo, formato data, sotto-campi degli elenchi) e dà istruzioni
  precise su date, elenchi, Sì/No e campi descrittivi.
- Con Ollama viene scelto il modello Qwen più capace installato (fino a 14B).

## [0.5.0] - 2026-10-05

### Aggiunto
- **Editor visuale "trascina e rilascia"** per Word ed Excel: si trascinano le tessere dei campi (Testo,
  Numero, Data, Sì/No, Scelta, Elenco) direttamente nel documento. Rilasciandole su una riga da
  compilare (`______`, `.....`), su una cella vuota, su un testo selezionato o in fondo al documento il
  campo prende quel posto; il nome viene suggerito dall'etichetta vicina (es. "Cliente:"). I campi si
  spostano trascinandoli, si tolgono nel cestino, si modificano con un clic; c'è "Annulla modifica"
  (Ctrl+Z). Per chi non trascina: clic sulla tessera e poi clic nel documento.
- Nuovo modulo: si può trascinare il file Word/Excel nella finestra (anche sulla finestra principale;
  un `.zip` viene importato come modulo). Non servono più i segnaposto `{{...}}`: un modulo senza campi
  apre subito l'editor visuale.

## [0.4.2] - 2026-10-05

### Corretto
- **Documenti AI** (crea, modifica, audit, compila da documenti): l'AI riceveva una richiesta vuota e
  restituiva solo "NON_SPECIFICATO"; ora riceve davvero la richiesta, le regole e i brani dei documenti.
- Template DOCX: i campi `{{...}}` in **intestazioni/piè di pagina**, tabelle annidate e caselle di testo
  e quelli con **lettere accentate** (es. `{{città}}`) venivano ignorati e restavano nel documento finale.
  I campi seguono ora l'ordine del modulo; i segnaposto scritti male vengono segnalati.
- Editor dei campi (schema): salvare, anche senza modifiche, cancellava i **valori degli elenchi** e i
  formati data; il pulsante Annulla era fuori dalla finestra.
- Nei documenti esportati (Word/Excel/PDF) compariva la scritta interna `NON_SPECIFICATO`.
- Importare un modulo ZIP già presente lo annidava dentro quello esistente: ora diventa una copia.
- Con un Ollama locale e modelli "thinking" (Qwen3) la compilazione falliva con un errore interno.
- La barra in alto restava su "AI al lavoro…" dopo ogni compilazione; ora rileva anche Ollama all'avvio.
- Punteggio di qualità: un modulo compilato per intero valeva 40/100.
- Dialoghi Documenti AI: pulsanti Salva/Chiudi fuori dalla finestra, intestazione con riquadri neri,
  salvataggio della compilazione smart sempre in errore, testo originale non mostrato in "Modifica",
  sottosezioni perse nel Word generato, contenuto duplicato con un template.
- Audit: le incoerenze tra documenti ora compaiono tra le criticità (prima solo in una scheda secondaria).
- Procedura guidata: scegliendo un'altra cartella dati si perdevano lingua e configurazione.
- Nuovo modulo: Invio nella descrizione creava il modulo; campo "Tipo di documento" tagliato.
- Storico: il pulsante Elimina sembrava attivo senza selezione; conteggi della barra laterale non aggiornati.
- Testo tagliato con la dimensione del testo ingrandita; varie etichette non tradotte o al plurale errato.
- OCR: "Usa come informazioni" sostituiva il testo già scritto invece di aggiungerlo.

### Aggiunto
- Pulsante **Aggiungi moduli di esempio** (i moduli di esempio ora sono inclusi nell'installer).
- **Ripristino dei moduli archiviati** da Impostazioni → Dati e backup.
- Compila → Da documenti: **Crea il documento con questi dati** porta i dati letti nel flusso normale
  (revisione, documento compilato, Storico) e la lettura parte subito.
- Editor template: **Aggiungi allo schema i campi mancanti** (campi aggiunti modificando il file in Word).

## [0.4.1] - 2026-10-05

### Aggiunto
- **Aggiornamenti automatici**: all'avvio l'app controlla le release su GitHub, scarica il nuovo
  installer in background (verificato con SHA-256) e lo installa in silenzio alla chiusura, oppure
  subito con "Riavvia e aggiorna". Interruttore e "Controlla ora" in *Impostazioni → Informazioni*;
  disattivabile in azienda con `DOCX_AI_NO_UPDATE=1`. Lo ZIP portable mostra solo un avviso.

### Corretto
- **Installazione dell'AI dall'app**: l'estrazione del runtime llama.cpp falliva sempre
  (`FileExistsError`) e impediva di scaricare i modelli.

## [0.4.0] - 2026-10-04

### Modificato
- **L'app si chiama ora DOCX.AI** (prima MaintenanceAI): nuovo nome, nuovo logo, nuovo repository
  `motthz/DOCX.AI`. Al primo avvio dati, moduli e impostazioni vengono spostati automaticamente da
  `%LOCALAPPDATA%\MaintenanceAI` a `%LOCALAPPDATA%\DOCX.AI`; l'installer rimuove la vecchia versione.
- **Compilazione di qualsiasi tipo di modulo**, non solo rapporti di manutenzione: istruzioni all'AI
  generiche, testi dell'interfaccia neutri ("Compila", "documento"), PDF ed Excel senza riferimenti alla
  manutenzione.

### Aggiunto
- **Tipo di documento** per ogni modulo (es. "verbale di riunione"), passato all'AI come contesto.
- Filtro dello storico su **qualsiasi campo** del modulo.
- Moduli di esempio **Verbale di riunione** (DOCX) e **Richiesta d'acquisto** (XLSX).
- I backup della v0.3 restano ripristinabili.

## [0.3.0] - 2026-10-04

### Aggiunto
- **Nuova interfaccia** (CustomTkinter): tema chiaro/scuro/come Windows, titlebar scura, icone vettoriali,
  barra laterale ridimensionabile e comprimibile, schede animate, toast con azioni, stati vuoti,
  splash animato, dimensione del testo regolabile, contrasti WCAG AA, scorciatoie `Ctrl+1…6`.
- **Revisione affiancata alle fonti** con controllo anti-allucinazione (valori non presenti nelle fonti
  evidenziati), "Migliora testo" e salvataggio automatico della bozza.
- **Storico**: ricerca globale, filtri per data/tecnico/impianto, paginazione, duplica, versioni con
  confronto e ripristino, export Excel riepilogativo, import interventi da CSV/Excel.
- **Foto** nel rapporto (anche dalla Fotocamera di Windows) incluse nel PDF; **anteprima PDF** integrata;
  invio per email.
- **Editor visuale del template** DOCX: seleziona il testo e trasformalo in campo.
- **Impostazioni** complete, **backup/ripristino** in ZIP con backup automatico, **cartella dati di rete**
  con blocco tra postazioni, **pacchetto diagnostico** e **segnalazione problemi**, **tour guidato**.
- **AI**: streaming dell'output, ricerca semantica (Qwen3-Embedding), accelerazione **GPU Vulkan**,
  controllo RAM, precaricamento e spegnimento per inattività, temperatura e contesto configurabili.
- **Lingua inglese** completa e **guida utente** IT/EN con screenshot dentro l'app.
- Installer con pagina di benvenuto e scelta del modello AI (`/AIMODEL=`); manifest winget; guida
  alla distribuzione aziendale (Intune/GPO).
- Progetto: CI GitHub Actions con build automatica delle release, ruff, mypy, pre-commit, Conventional
  Commits, Dependabot, dipendenze bloccate con hash, licenze complete, versione da fonte unica.

### Corretto
- OCR di Windows non funzionante.
- Crea/Modifica/Audit documento non funzionavano (errore interno sempre silenziato).
- I rapporti con campi sì/no non si potevano approvare (valori salvati come testo).
- Le opzioni "documenti di riferimento", "storico" e "temperatura" non venivano applicate.
- Filtri per data e contatore "Oggi" errati; errori di estrazione/export mai mostrati.
- Menu "Modulo" vuoto nelle finestre Documenti AI; metodi del database duplicati.
- `pypdf` e `pillow` mancanti dalle dipendenze.

### Modificato
- PDF generato in un processo separato (interfaccia sempre reattiva); cache dei documenti di
  riferimento estesa a PDF/TXT/scansioni; build ottimizzata (bytecode `-OO`, moduli inutili esclusi).
- Repository rinominato in `motthz/MaintenanceAI`.

## [0.2.0] - 2026-10-04

### Aggiunto
- Installer Windows (Inno Setup) senza diritti di amministratore, con collegamento su Desktop e menu Start.
- Logo e icona dell'applicazione.
- Finestra "Componenti AI": download di runtime llama.cpp e modelli Qwen3 con verifica SHA-256.
- Rilevamento automatico di Ollama locale.

### Corretto
- Build pubblicata incompleta (mancavano `.pyd` e `base_library.zip`): l'app non partiva su altri PC.
- La generazione rapporti falliva senza runtime AI: ora degrada a compilazione manuale.
- Menu "Modulo" sempre vuoto nelle finestre Documenti AI.
- Selettore profilo LLM non funzionante.

### Modificato
- Un solo llama-server condiviso; interfaccia rivista; exe senza console.

## [0.1.0] - 2026-09-10

- Prima versione pubblica (portable onedir).

[Non rilasciato]: https://github.com/motthz/DOCX.AI/compare/v0.4.2...HEAD
[0.4.2]: https://github.com/motthz/DOCX.AI/compare/v0.4.1...v0.4.2
[0.4.1]: https://github.com/motthz/DOCX.AI/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/motthz/DOCX.AI/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/motthz/DOCX.AI/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/motthz/DOCX.AI/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/motthz/DOCX.AI/releases/tag/v0.1.0
