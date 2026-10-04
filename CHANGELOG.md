# Changelog

Formato basato su [Keep a Changelog](https://keepachangelog.com/it/1.1.0/),
versionamento [SemVer](https://semver.org/lang/it/). La versione ha un'unica
fonte: `src/maintenance_ai/__init__.py`.

## [Non rilasciato]

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

[Non rilasciato]: https://github.com/motthz/MaintenanceAI/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/motthz/MaintenanceAI/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/motthz/MaintenanceAI/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/motthz/MaintenanceAI/releases/tag/v0.1.0
