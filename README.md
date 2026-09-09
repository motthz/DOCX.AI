# MaintenanceAI 0.1.0

Applicazione desktop Windows 10/11 x64 **100% offline e portable** per la redazione, approvazione ed esportazione di rapporti di manutenzione. Draft generati con AI locale (Qwen3 GGUF tramite llama.cpp CPU, runtime incluso separatamente o distribuibile) e SEMPRE revisionati dall'operatore prima della finalizzazione.

---

## Cosa fa l'app

1. **Moduli adattivi** — carica un file DOCX/XLSX template e l'app crea automaticamente schema JSON + mapping dei placeholder `{{campo}}` / mapping.json celle.
2. **Storico + documenti di riferimento** — ogni modulo mantiene 03_storico/ (JSON rapporti finalizzati) e 02_documenti_riferimento/ (caricabili come contesto per l'AI).
3. **AI anti-allucinazione locale** — la `SYSTEM_POLICY` blocca l'invenzione dati; quando l'AI non sa scrive `NON_SPECIFICATO`. Fallback Ollama → llama.cpp Primary 1.7B → llama.cpp 0.6B → Mock.
4. **Review Dialog obbligatorio** — l'output AI è sempre un *draft* e l'utente vede una scheda verde/giallo/rosso con quality score 0-100, correggibile campo-per-campo, highlight dei `NON_SPECIFICATO`.
5. **Export 3 formati canonici** per ogni rapporto approvato:
   - `Rapporto_xxx.json` — fonte canonica dei dati (validato jsonschema)
   - `Rapporto_xxx.docx` o `.xlsx` — copia deterministica del template riempito
   - `Rapporto_xxx.pdf` — layout MaintenanceAI con ReportLab (NON richiede Office installato)
6. **Persistenza robusta** — tutti i dati utente in `%LOCALAPPDATA%\MaintenanceAI\` (db sqlite, logs, exports, workspace/modules); cartella d'installazione è a sola lettura per l'EXE.
7. **Sicurezza** — `safe_resolve_name` blocca path traversal; limiti ZIP (entries/size/estensioni); blacklist estensioni pericolose `.docm/.xlsm/.exe/.bat/.ps1/.js/.lnk/.vbs`; mask API key nei log; nessuna chiamata di rete fuori da 127.0.0.1.

---

## Come avviare l'EXE (portable, nessuna installazione)

**Cartella distribuita** (onedir PyInstaller, ~60 MB):
```
MaintenanceAI\
├── MaintenanceAI.exe      ← doppio click = avvio GUI
├── _internal\             (DLL Python, librerie packate)
├── config\default.json
├── LICENSES\
└── VERSION.txt
```

- **NON** serve Python / Node / npm / pip / Java / IDE / Office / Ollama / Docker.
- Doppio click su `MaintenanceAI.exe`.
- Dati e workspace scritti in `%LOCALAPPDATA%\MaintenanceAI\` (dove l'utente standard ha permessi scrittura).
- Per vedere se tutto funziona senza aprire la GUI:
  ```bat
  MaintenanceAI.exe --self-test --verbose
  ```
  Exit code `0` = ambiente e build sono OK.

---

## Come eseguire da sorgente (Windows, PowerShell)

Prerequisito singolo: **Python 3.12 x64** installato con Tcl/Tk (default). Poi da PowerShell esegui **in ordine**:

```powershell
# 1. Crea venv e installa dipendenze, scarica test fixtures
powershell -ExecutionPolicy Bypass -File scripts\setup_dev.ps1

# 2. Opzionale: scarica runtime llama.cpp CPU e modelli Qwen3 GGUF in runtime/models
powershell -ExecutionPolicy Bypass -File scripts\download_runtime.ps1

# 3. Run unit test + self-test
powershell -ExecutionPolicy Bypass -File scripts\test.ps1

# 4. Avvia GUI da sorgente
powershell -ExecutionPolicy Bypass -File scripts\run_dev.ps1

# 5. Build EXE onedir (copiare dist\MaintenanceAI\ all'utente finale)
powershell -ExecutionPolicy Bypass -File scripts\build.ps1
```

Sviluppo manuale (se vuoi evitare gli script wrapper):
```powershell
$env:PYTHONPATH = "src;."
.\.venv\Scripts\python.exe -m maintenance_ai.main --self-test --verbose
.\.venv\Scripts\python.exe -m maintenance_ai.main
```

---

## Requisiti sistema finale

| Requisito | Versione | Note |
|-----------|----------|------|
| OS | Windows 10 22H2+ o Windows 11 x64 | Il mutex single-instance usa Win32 API; DPI-aware chain PMv2/Shcore; **solo x64** (no arm, no 32bit) |
| RAM | ≥ 4 GB consigliato | Per 1.7B Q8_0 sono ~1.9GB + ~600MB Python EXE + ~1GB di headroom Tkinter/ReportLab |
| CPU | Qualsiasi x64 moderno | AI runtime è CPU-only llama.cpp; per template/docx grandi o report batch è meglio 4+ core |
| Spazio disco | ~250 MB | EXE portable 60 MB + runtime llama.cpp 40 MB + modello 1.7B Q8_0 1.9 GB opzionale (se usi AI reale) |
| Rete | **Non richiesta** | Zero telemetria, zero auto-update, zero API remote. llama-server.exe gira su 127.0.0.1 con API-key casuale per avvio. |
| Office | **Non richiesto** | DOCX/XLSX editati con python-docx/openpyxl; PDF render con ReportLab (nessun Office render) |

---

## Struttura essenziale cartelle

```
Progetto DOCK.IA\
├── src\maintenance_ai\       # sorgente produzione (tkinter, sqlite, export, llm pipeline, docintelligence)
├── tests\                    # unittest 28+ casi + golden_cases.json anti-regressioni modello
├── scripts\                  # PowerShell setup, dev run, test, build, download runtime, smoke e2e
├── packaging\MaintenanceAI.spec  # onedir PyInstaller spec
├── config\default.json       # profilo default (max file size, paths, LLM configs)
├── dist\MaintenanceAI\       # BUILD FINALE onedir (MaintenanceAI.exe + _internal + config)
├── .gitignore
├── README.md
└── AUDIT_REPORT.md           # report completo audit 40+ test
```

A runtime sul PC utente i DATI sono SEMPRE separati dalla cartella d'installazione:
```
%LOCALAPPDATA%\MaintenanceAI\
├── maintenance.db            # SQLite + migrazioni FTS5
├── logs\crash.log            # stderr/stdout persistenti post-crash
├── exports\<timestamp>\      # 3 file finalizzati (JSON + DOCX/XLSX + PDF)
└── workspace\modules\<slug>\
    ├── module.json           # metadati + version SemVer
    ├── schema.json           # JSON schema, edibile manualmente
    ├── mapping.json          # mapping placeholder → celle DOCX/XLSX
    ├── 01_modulo_vuoto\      # originale template vergine
    ├── 02_documenti_riferimento\  # contesto opzionale per l'AI
    ├── 03_storico\           # JSON rapporti già finalizzati → contesto
    └── _versions\            # ultime 10 modifiche schemi/mappature
```

---

## Limitazioni reali conosciute

- **AI reale richiede runtime + modello**: il pacchetto EXE portable include il codice per pilotare llama-server.exe; il runtime ufficiale `runtime/llama/` e i file `.gguf` possono essere copiati a parte o scaricati con `scripts/download_runtime.ps1`. Senza di essi l'AI usa il `MockLlamaServer` (genera valori `NON_SPECIFICATO` e placeholder deterministici) — export/import/moduli funzionano comunque.
- **PDF fidelity DOCX**: ReportLab produce un PDF "standard MaintenanceAI" con il proprio font e layout; non è un rendering pixel-perfect del DOCX/XLSX (come sarebbe se avessi Word installato). Il DOCX/XLSX originale è sempre incluso come output.
- **MacOS/Linux**: **Non supportati** ufficialmente; il codice è portatile ma la build è target Windows 10/11 x64.
- **Modelli grandi (>10B)**: non testati e potrebbero saturare la RAM. Il pin ufficiale per v0.1.0 è Qwen3-1.7B-Instruct Q8_0 e Qwen3-0.6B come fallback.
- **OCR/Scanner**: placeholder vuoti vengono popolati con NON_SPECIFICATO, non c'è OCR integrato in questa release.
- **Excel formule/macro**: `openpyxl` ha `defusedxml` attivo; macro `.xlsm` e formule sono bloccati dal security filter come previsto.

---

## Comandi CLI utili

```bat
MaintenanceAI.exe                 :: Avvio GUI (default)
MaintenanceAI.exe --self-test     :: Smoke test 14 step, exit 0 se tutto OK
MaintenanceAI.exe --self-test --verbose :: dettagli ogni step
MaintenanceAI.exe --config PATH   :: usa file json alternativo invece di config/default.json
MaintenanceAI.exe --version       :: stampa versione da VERSION.txt / __init__.py
```

Per ulteriori dettagli di audit e copertura test vedi `AUDIT_REPORT.md`.
