============================================================
  MaintenanceAI  -  Istruzioni per l'utente
============================================================
Versione: 0.1.0   |   Sorgente: https://github.com/motthz/DOCK.IA

AVVIO RACCOMANDATO (tutto automatico, SOLO UN DOPPIO CLICK):

        MaintenanceAI.exe          <--- QUESTO E' IL FILE EXE CHE CERCHI

        Si trova direttamente nella root del progetto.
        E' un VERO file EXE Windows (PE 32/64 bit), non un .bat.
        Come funziona:
          - SE E' IL PRIMO AVVIO (mancano .venv / runtime / modello)
              -> avvia automaticamente INSTALLA_E_AVVIA.bat che
                 installa Python, venv, requirements, runtime e modello
                 e poi parte l'app.
          - SE E' GIA' STATO INSTALLATO TUTTO
              -> avvia AVVIA_APP.bat direttamente.

In entrambi i casi le finestre CMD / PowerShell restano aperte
cosi' puoi vedere scaricamenti progressivi ed eventuali errori.

------------------------------------------------------------
PRIMO AVVIO DETTAGLIATO
------------------------------------------------------------
Prima volta sempre il doppio click su MaintenanceAI.exe.
I passaggi automatici sono:
  1. Controlla / installa Python 3.12 (via winget, se manca)
  2. Crea l'ambiente virtuale .venv e installa le librerie
  3. Scarica il runtime llama-server.exe (llama.cpp Windows CPU x64)
  4. Scarica il modello Qwen3-1.7B-Q8_0.gguf (~1.8 GB, verificato SHA-256)
  5. Esegue i controlli di salute e infine AVVIA L'APP

Durata prevista primo avvio: 5-30 minuti
(dipende dalla velocita' della connessione a Internet).

------------------------------------------------------------
AVVII SUCCESSIVI (piu' veloce, NESSUN download)
------------------------------------------------------------
Sempre lo stesso file:

        MaintenanceAI.exe

  (in alternativa, direttamente AVVIA_APP.bat)

------------------------------------------------------------
ALTERNATIVA: IL VERO EXE PORTATILE "one-folder" PER CLIENTI
------------------------------------------------------------
Se vuoi invece dell'app da sorgente la VERSIONE FINALE
con un MaintenanceAI.exe standalone (cartella onedir PyInstaller)
da distribuire a un cliente SENZA INSTALLARE Python sul suo PC:

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
