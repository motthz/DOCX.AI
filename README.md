# MaintenanceAI

<img src="src/maintenance_ai/assets/logo.png" width="96" align="right" alt="logo">

Applicazione desktop per Windows 10/11 (x64) per redigere, revisionare ed esportare
rapporti di manutenzione. L'AI gira **in locale e offline** (llama.cpp + Qwen3):
i dati non lasciano mai il PC. Ogni bozza generata dall'AI va **sempre** revisionata
dall'operatore prima dell'esportazione.

---

## Installazione (utente finale)

1. Scarica **`MaintenanceAI-Setup-<versione>.exe`** dalla pagina
   [Releases](https://github.com/motthz/MaintenanceAI/releases/latest).
2. Avvialo e segui la procedura. Non servono diritti di amministratore:
   l'app viene installata in `%LOCALAPPDATA%\Programs\MaintenanceAI` e viene creato
   il collegamento **MaintenanceAI** sul Desktop e nel menu Start.
3. Al primo avvio clicca su **«AI non installata»** in alto a destra e poi su
   **Scarica e installa**: runtime llama.cpp e modello Qwen3 vengono scaricati una sola
   volta (~2 GB, serve Internet solo per questo passaggio).

> Windows SmartScreen può mostrare "PC protetto da Windows" perché l'installer non è
> firmato digitalmente: clic su **Ulteriori informazioni → Esegui comunque**.

Senza componenti AI l'app funziona comunque: i rapporti vanno compilati a mano
(i campi restano `NON_SPECIFICATO`). Se sul PC è già attivo **Ollama** con un modello
installato, viene usato automaticamente.

In alternativa all'installer è disponibile lo ZIP **portable** (estrai e avvia
`MaintenanceAI.exe`).

Disinstallazione: *Impostazioni → App → App installate → MaintenanceAI*. I dati utente
in `%LOCALAPPDATA%\MaintenanceAI` vengono conservati.

---

## Cosa fa l'app

1. **Moduli adattivi** — da un template DOCX/XLSX crea automaticamente schema JSON e
   mapping dei placeholder `{{campo}}`.
2. **Storico e documenti di riferimento** — usati come contesto per l'AI.
3. **AI anti-allucinazione** — la policy vieta di inventare dati; se un valore non è noto
   l'AI scrive `NON_SPECIFICATO`. Catena di backend: llama.cpp (Qwen3 1.7B → 0.6B) →
   Ollama locale → modalità manuale.
4. **Revisione obbligatoria** — scheda con quality score e evidenza dei campi mancanti.
5. **Export** JSON (fonte canonica) + DOCX/XLSX + PDF (ReportLab, Office non richiesto).
6. **Documenti AI** — creazione, modifica, audit e compilazione da documenti, con regole
   AI personalizzabili per funzione e per modulo.
7. **Sicurezza** — protezione path traversal, limiti ZIP, estensioni pericolose
   bloccate, nessuna connessione di rete fuori da 127.0.0.1 (salvo il download
   esplicito dei componenti AI).

Dati utente: `%LOCALAPPDATA%\MaintenanceAI\` (database, log, export, workspace moduli,
runtime e modelli AI). Log degli errori di avvio: `logs\crash.log`.

### Profili AI

| Profilo | Modello | Uso |
|---|---|---|
| `compatibility` | Qwen3 0.6B, contesto 2048 | PC lenti / poca RAM |
| `balanced` (default) | Qwen3 1.7B, contesto 4096 | consigliato |
| `fastest` | Qwen3 1.7B, 8 thread | CPU con molti core |

Requisiti: Windows 10 22H2+ x64, 4 GB RAM (6 GB consigliati con AI), ~2.5 GB di disco
con modello.

---

## Sviluppo

Prerequisito: Python 3.12 x64. Da PowerShell nella cartella del progetto:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_dev.ps1        # venv + dipendenze
powershell -ExecutionPolicy Bypass -File scripts\run_dev.ps1          # avvia la GUI
powershell -ExecutionPolicy Bypass -File scripts\test.ps1             # unit test + self-test
.venv\Scripts\python.exe scripts\smoke_gui.py                          # smoke test GUI
powershell -ExecutionPolicy Bypass -File scripts\release.ps1  # build + ZIP + installer
```

`release.ps1` richiede [Inno Setup 6](https://jrsoftware.org/isinfo.php)
(`winget install JRSoftware.InnoSetup`) e produce in `release\`:

- `MaintenanceAI-Setup-<ver>.exe` — installer
- `MaintenanceAI-<ver>-portable-win64.zip` — versione portable

Le build non sono versionate nel repository: vengono pubblicate come asset delle
GitHub Release.

```
src/maintenance_ai/      sorgente (ui/, llm/, docintelligence/, exporters/, parsers/, services/)
src/maintenance_ai/assets logo e icona (rigenerabili con packaging/make_icon.py)
tests/                   unit test
scripts/                 setup, test, build, smoke test
packaging/               spec PyInstaller, manifest, versione exe, installer Inno Setup
config/default.json      configurazione predefinita
examples/modules/        modulo di esempio
```

### Comandi CLI

```bat
MaintenanceAI.exe                       :: GUI
MaintenanceAI.exe --self-test --verbose :: smoke test, exit code 0 = OK
MaintenanceAI.exe --version
MaintenanceAI.exe --config PATH         :: configurazione alternativa
```

### Limitazioni note

- Il PDF è un layout MaintenanceAI (ReportLab), non una resa pixel-perfect del DOCX/XLSX.
- Il modello 0.6B è più veloce ma meno affidabile: verificare sempre i valori proposti.
- Solo Windows x64 è supportato ufficialmente.
