============================================================
  MaintenanceAI  -  Istruzioni per l'utente (SETTEMBRE 2026)
============================================================
Versione: 0.1.0   |   Sorgente: https://github.com/motthz/DOCK.IA

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
   AVVIO RACCOMANDATO  --  NIENTE INSTALLAZIONI, NIENTE .BAT
   BASTA UN DOPPIO CLICK, ANCHE SUI PC AZIENDALI BLOCCATI
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

               MaintenanceAI.exe     <-- DOPPIO CLICK QUI

      Si trova direttamente nella cartella principale del progetto.

      COSA FA ESATTAMENTE questo MaintenanceAI.exe:
      - E' un VERO EXE Windows compilato (non un .bat camuffato).
      - NON richiede Python installato sul PC.
      - NON richiama nessun file .bat / .cmd / PowerShell internamente.
      - NON ha bisogno di amministratori.
      - Prova ad avviare, in ordine:
          1) dist\MaintenanceAI\MaintenanceAI.exe
                  (versione PyInstaller portatile, Python embedded,
                   GIA' PRONTA se hai scaricato la repo per intero)
          2) .venv\Scripts\python.exe  (se sei uno sviluppatore)
          3) python nel PATH  (se hai Python nel sistema)
      - Se nessuno di questi funziona, mostra un messaggio chiaro
        invece di chiudersi silenziosamente.

      NOTA SUI PC DI LAVORO AZIENDALI:
      Le policy che bloccano i file .bat NON influenzano questo
      MaintenanceAI.exe perche' NON usa nessuno script batch.
      Questo exe e' un launcher standalone che usa la sola API Win32
      per creare il processo dell'app vera.

------------------------------------------------------------
COSA OTTIENI CON IL SOLA SCARICAMENTO DELLA REPO (senza installare):
------------------------------------------------------------

Scarica la ZIP da GitHub (Code -> Download ZIP), estraila,
poi doppio click su MaintenanceAI.exe.

L'app si avvia immediatamente.

Primo avvio: l'app mostrera' la GUI. Se non trovi runtime/llama
e models/ in locale, verra' usato un backend MOCK per permetterti
di provare l'interfaccia e l'export DOCX/XLSX/PDF senza AI.

Per la FUNZIONE AI COMPLETA servono:
  - runtime/llama/     (llama-server.exe + DLLs)
  - models/*.gguf      (Qwen3 GGUF locale)
Questi file sono grandi (~2.2 GB totali). Puoi ottenerli in 2 modi:

  METODO A) Scarica la RELEASE completa GitHub (MaintenanceAI-portable.zip)
            include TUTTO: launcher, app compilata, runtime e modello.
            Estrazione e doppio click: funziona subito offline al 100%.

  METODO B) Sul tuo PC di sviluppo, lancia una sola volta:
               INSTALLA_E_AVVIA.bat
            (o in PowerShell:
               powershell -ExecutionPolicy Bypass -File scripts\download_runtime.ps1)
            Questo scarica runtime/ e models/.

------------------------------------------------------------
AVVII SUCCESSIVI
------------------------------------------------------------

Sempre lo stesso comando, sempre lo stesso file:

        MaintenanceAI.exe    (doppio click)

Nessun passaggio aggiuntivo. Nessun file .bat.

------------------------------------------------------------
PER SVILUPPATORI E MANUTENTORI
------------------------------------------------------------

File ancora disponibili nella root per sviluppatori:

  AVVIA_APP.bat           Avvia l'app dal .venv gia' creato
  INSTALLA_E_AVVIA.bat    Installa tutto (Python + venv + runtime + modello)
                          ed e' utile per chi clona la repo e vuole
                          sviluppare / ricreare l'ambiente dev.

Istruzioni build della distribuzione finale:
  1.  powershell -ExecutionPolicy Bypass -File scripts\build.ps1
        Produce:  dist\MaintenanceAI\MaintenanceAI.exe
  2.  powershell -ExecutionPolicy Bypass -File scripts\package.ps1
        Produce:  release\MaintenanceAI-portable.zip
        (include anche runtime/ e models/ se presenti)

------------------------------------------------------------
REQUISITI SISTEMA MINIMI
------------------------------------------------------------
  - Windows 10 / 11 a 64 bit
  - RAM libera: 6 GB consigliati per AI locale
                 (4 GB bastano per GUI + export senza AI)
  - Spazio su disco:
       ~  500 MB : repo sorgente + build PyInstaller (senza AI)
       ~  5 GB   : pacchetto completo con runtime e modello Qwen3 1.7B
  - Connessione Internet: SOLO per il primo download di runtime/modello.
    TUTTO IL RESTO funziona OFFLINE.
