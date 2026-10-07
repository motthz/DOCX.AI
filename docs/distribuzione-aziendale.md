# Distribuzione aziendale (Intune, GPO, SCCM)

L'installer `DOCX.AI-Setup-<ver>.exe` (Inno Setup) supporta l'installazione
silenziosa e non richiede interazione.

## Parametri della riga di comando

| Scenario | Comando |
|---|---|
| Utente corrente, silenzioso | `DOCX.AI-Setup-0.3.0.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER` |
| Tutti gli utenti (richiede admin) | `DOCX.AI-Setup-0.3.0.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /ALLUSERS` |
| Senza collegamento sul Desktop | aggiungere `/TASKS=""` |
| Cartella personalizzata | aggiungere `/DIR="C:\Programmi\DOCX.AI"` |
| Log dell'installazione | aggiungere `/LOG="C:\Temp\mai-setup.log"` |
| Modello AI preselezionato | aggiungere `/AIMODEL=4b` (oppure `1.7b`, `0.6b`, `none`; predefinito `auto`: in base alla RAM) |

Disinstallazione silenziosa:

```bat
"%LOCALAPPDATA%\Programs\DOCX.AI\unins000.exe" /VERYSILENT /SUPPRESSMSGBOXES
```

(per l'installazione "tutti gli utenti" il percorso è `C:\Program Files\DOCX.AI\unins000.exe`).

Codici di uscita: `0` = OK; gli altri codici sono documentati da Inno Setup
(<https://jrsoftware.org/ishelp/topic_setupexitcodes.htm>).

## Aggiornamenti automatici

L'app installata controlla le release su GitHub all'avvio, scarica il nuovo installer in
`%LOCALAPPDATA%\DOCX.AI\updates` (verificato con SHA-256) e lo esegue in modalità
silenziosa alla chiusura. Se gli aggiornamenti vengono distribuiti centralmente,
disattivarli impostando la variabile d'ambiente `DOCX_AI_NO_UPDATE=1` (ad esempio via GPO)
oppure da *Impostazioni → Informazioni*.

## Microsoft Intune (Win32 app)

1. Scarica lo strumento [Microsoft Win32 Content Prep Tool](https://github.com/microsoft/Microsoft-Win32-Content-Prep-Tool).
2. Metti l'installer in una cartella e crea il pacchetto:
   ```bat
   IntuneWinAppUtil.exe -c .\setup -s DOCX.AI-Setup-0.3.0.exe -o .\out
   ```
3. In Intune → *App → Windows → Aggiungi → App Windows (Win32)*:
   - **Comando di installazione**: `DOCX.AI-Setup-0.3.0.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /ALLUSERS`
   - **Comando di disinstallazione**: `"C:\Program Files\DOCX.AI\unins000.exe" /VERYSILENT /SUPPRESSMSGBOXES`
   - **Comportamento installazione**: Sistema
   - **Regola di rilevamento**: file `C:\Program Files\DOCX.AI\DOCX.AI.exe`, versione ≥ 0.3.0

## Modelli AI centralizzati

Per evitare che ogni PC scarichi ~2 GB:

1. Su un PC scarica i componenti dalla finestra *Componenti AI*.
2. Copia `%LOCALAPPDATA%\DOCX.AI\runtime` e `%LOCALAPPDATA%\DOCX.AI\models`
   nella cartella di installazione (`C:\Program Files\DOCX.AI\runtime`, `...\models`)
   tramite il pacchetto di distribuzione: l'app li cerca anche lì.

## Cartella dati condivisa

In *Impostazioni → Cartella dati* è possibile puntare a una cartella di rete
(`\server\manutenzione\DOCX.AI`). Il database viene aperto in modalità
compatibile con SMB e un file di lock impedisce l'uso contemporaneo da due PC.
Per l'uso simultaneo da più postazioni usare cartelle dati separate.

## Pacchetto MSI

Non viene prodotto un MSI nativo: Intune, SCCM e GPO (tramite script di avvio)
gestiscono direttamente l'installer `.exe` con i parametri sopra. Se un MSI è
obbligatorio, l'installer può essere incapsulato con strumenti come
*MSI Wrapper* o *Advanced Installer*.

## winget

`scripts\winget_manifest.py` genera i manifest per il catalogo winget a partire
dall'installer della release; la pubblicazione richiede l'invio di una pull
request a `microsoft/winget-pkgs` dall'account del titolare.

## Antivirus e SmartScreen

DOCX.AI è un'applicazione Python impacchettata con PyInstaller ed esegue un motore AI
locale (`llama-server.exe`): alcuni antivirus possono segnalarla per errore. Cosa fa l'app
per evitarlo:

- il *bootloader* di PyInstaller viene compilato da sorgente a ogni release (quello
  precompilato è condiviso da migliaia di programmi, anche malevoli, ed è spesso segnalato);
- niente UPX né file compressi/offuscati; l'eseguibile ha icona, manifest (`asInvoker`, nessun
  diritto di amministratore) e informazioni di versione complete;
- PowerShell (usato solo per impaginare con Word e per l'OCR di Windows) viene avviato dal
  percorso di sistema con lo script in chiaro: niente `-EncodedCommand` né
  `-ExecutionPolicy Bypass`, i due segnali più usati dagli antivirus per riconoscere i malware;
- il runtime llama.cpp e i modelli scaricati vengono verificati con SHA-256.

**Firma digitale.** Il rimedio definitivo è firmare exe e installer con un certificato di
firma del codice (OV/EV, oppure Azure Trusted Signing). La release lo fa da sola se nel
repository sono presenti i secret `WINDOWS_SIGN_PFX_BASE64` (file `.pfx` in base64) e
`WINDOWS_SIGN_PFX_PASSWORD`; in locale basta impostare `SIGN_PFX_PATH` e
`SIGN_PFX_PASSWORD` prima di `scripts\release.ps1`.

**Se l'antivirus blocca comunque l'app:**

1. invia l'installer come *falso positivo* al produttore (Microsoft Defender:
   <https://www.microsoft.com/wdsi/filesubmission>, scegli "Software developer" o
   "Home customer"); di solito la segnalazione viene rimossa in 1-3 giorni per tutti;
2. in azienda aggiungi un'esclusione per la cartella di installazione
   (`%LOCALAPPDATA%\Programs\DOCX.AI`) e per la cartella dati (`%LOCALAPPDATA%\DOCX.AI`,
   che contiene `runtime\llama\llama-server.exe`), oppure consenti l'hash dei file;
3. SmartScreen ("PC protetto da Windows") sparisce con la firma digitale o dopo che
   l'installer è stato scaricato da abbastanza utenti: *Ulteriori informazioni → Esegui comunque*.
