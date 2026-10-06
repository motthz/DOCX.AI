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
