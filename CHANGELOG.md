# Changelog di DOCX.AI (già MaintenanceAI)

Formato basato su [Keep a Changelog](https://keepachangelog.com/it/1.1.0/),
versionamento [SemVer](https://semver.org/lang/it/). La versione ha un'unica
fonte: `src/docx_ai/__init__.py`.

## [Non rilasciato]

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
