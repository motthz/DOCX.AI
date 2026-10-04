# Distribuzione aziendale (Intune, GPO, SCCM)

L'installer `MaintenanceAI-Setup-<ver>.exe` (Inno Setup) supporta l'installazione
silenziosa e non richiede interazione.

## Parametri della riga di comando

| Scenario | Comando |
|---|---|
| Utente corrente, silenzioso | `MaintenanceAI-Setup-0.3.0.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER` |
| Tutti gli utenti (richiede admin) | `MaintenanceAI-Setup-0.3.0.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /ALLUSERS` |
| Senza collegamento sul Desktop | aggiungere `/TASKS=""` |
| Cartella personalizzata | aggiungere `/DIR="C:\Programmi\MaintenanceAI"` |
| Log dell'installazione | aggiungere `/LOG="C:\Temp\mai-setup.log"` |
| Modello AI preselezionato | aggiungere `/AIMODEL=1.7b` (oppure `0.6b`, `none`) |

Disinstallazione silenziosa:

```bat
"%LOCALAPPDATA%\Programs\MaintenanceAI\unins000.exe" /VERYSILENT /SUPPRESSMSGBOXES
```

(per l'installazione "tutti gli utenti" il percorso è `C:\Program Files\MaintenanceAI\unins000.exe`).

Codici di uscita: `0` = OK; gli altri codici sono documentati da Inno Setup
(<https://jrsoftware.org/ishelp/topic_setupexitcodes.htm>).

## Microsoft Intune (Win32 app)

1. Scarica lo strumento [Microsoft Win32 Content Prep Tool](https://github.com/microsoft/Microsoft-Win32-Content-Prep-Tool).
2. Metti l'installer in una cartella e crea il pacchetto:
   ```bat
   IntuneWinAppUtil.exe -c .\setup -s MaintenanceAI-Setup-0.3.0.exe -o .\out
   ```
3. In Intune → *App → Windows → Aggiungi → App Windows (Win32)*:
   - **Comando di installazione**: `MaintenanceAI-Setup-0.3.0.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /ALLUSERS`
   - **Comando di disinstallazione**: `"C:\Program Files\MaintenanceAI\unins000.exe" /VERYSILENT /SUPPRESSMSGBOXES`
   - **Comportamento installazione**: Sistema
   - **Regola di rilevamento**: file `C:\Program Files\MaintenanceAI\MaintenanceAI.exe`, versione ≥ 0.3.0

## Modelli AI centralizzati

Per evitare che ogni PC scarichi ~2 GB:

1. Su un PC scarica i componenti dalla finestra *Componenti AI*.
2. Copia `%LOCALAPPDATA%\MaintenanceAI\runtime` e `%LOCALAPPDATA%\MaintenanceAI\models`
   nella cartella di installazione (`C:\Program Files\MaintenanceAI\runtime`, `...\models`)
   tramite il pacchetto di distribuzione: l'app li cerca anche lì.

## Cartella dati condivisa

In *Impostazioni → Cartella dati* è possibile puntare a una cartella di rete
(`\server\manutenzione\MaintenanceAI`). Il database viene aperto in modalità
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
