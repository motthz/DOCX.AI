============================================================
  MaintenanceAI  -  Istruzioni per l'utente
============================================================
Versione: 0.1.0   |   Sorgente: https://github.com/motthz/DOCK.IA

Questa e' la cartella SORGENTE di MaintenanceAI clonata da GitHub.

------------------------------------------------------------
PRIMO AVVIO (tutto automatico, richiede solo un doppio click)
------------------------------------------------------------
  (solo 1 volta, poi si puo' usare AVVIA_APP.bat per sempre)

1. Fare DOPPIO CLICK sul file:

        INSTALLA_E_AVVIA.bat

   Attendere che finisca TUTTO (5 passaggi):
     - Controlla / installa Python 3.12
     - Crea l'ambiente virtuale .venv e scarica le librerie
     - Scarica il runtime llama-server.exe (llama.cpp Windows CPU x64)
     - Scarica il modello Qwen3-1.7B-Q8_0.gguf (~1.8 GB, verificato SHA-256)
     - Esegue i controlli di salute e infine AVVIA L'APP

   Il primo avvio puo' durare da 5 a 30 minuti
   a seconda della velocita' della connessione a Internet.

------------------------------------------------------------
AVVII SUCCESSIVI (piu' veloce, NESSUN download)
------------------------------------------------------------
   Fare DOPPIO CLICK su:

        AVVIA_APP.bat

------------------------------------------------------------
PER CREARE IL VERO .exe PORTATILE (MaintenanceAI.exe)
------------------------------------------------------------
Se invece dell'app da sorgente vuoi la VERSIONE FINALE
con l'.exe dentro una cartella standalone (come quella
che andrebbe data a un cliente NON sviluppatore):

   Apri PowerShell e scrivi:

      powershell -ExecutionPolicy Bypass -File scripts\build.ps1

   Questo produce la cartella:
        dist\MaintenanceAI\
   con    MaintenanceAI.exe   dentro.

   Poi per fare il pacchetto ZIP portatile completo
   (inclusi runtime e modello):

      powershell -ExecutionPolicy Bypass -File scripts\package.ps1

   Il risultato e' in:
        release\MaintenanceAI-portable.zip

------------------------------------------------------------
COSA CONTIENE IL PACCHETTO FINALE "MaintenanceAI-portable"
------------------------------------------------------------
MaintenanceAI\
├── MaintenanceAI.exe          <--- l'exe da doppio-click
├── _internal\                  (librerie Python PyInstaller)
├── runtime\llama\              (llama-server.exe + DLLs)
├── models\                     (Qwen3-1.7B-Q8_0.gguf)
├── config\default.json
├── LICENSES\
└── VERSION.txt

------------------------------------------------------------
REQUISITI SISTEMA
------------------------------------------------------------
  - Windows 10 / 11 a 64 bit
  - RAM libera minima consigliata: 6 GB
  - Spazio su disco per installazione completa: ~ 5 GB
  - Connessione a Internet SOLO per il PRIMO avvio
    (per scaricare modello e runtime)
  - TUTTO il resto funziona OFFLINE.
