"""Help dialog: guida rapida + FAQ + manuale completo (tema premium).

Aperto dal pulsante ? nell'header o da scorciatoia F1.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .theme import (
    COLORS,
    FONTS,
    FONT_FAMILY,
    GradientCanvas,
    apply_theme,
    center_window,
)


_HELP_QUICK = r"""\
COSA FARE IN 5 PASSAGGI SEMPLICI:

1️⃣ · SELEZIONA UN MODULO
   Nella barra laterale sinistra scegli il tipo di rapporto
   (es. "Rapporto Manutenzione Citterio").
   Oppure creane uno nuovo con Ctrl+N da un tuo template DOCX/XLSX
   (deve contenere placeholder {{nome_campo}}).

2️⃣ · SCRIVI LA DESCRIZIONE (Tab 📝 RAPPORTO, colonna sinistra)
   Descrivi l'intervento in linguaggio libero. Includi: data, impianto,
   componenti toccati, attività eseguite, esiti, misure, note.
   Più dettagli = più campi compilati bene.
   Verdi: qualità BUONA, Gialla: MEDIA, Rossa: BASSA.

3️⃣ · AVVIA L'ESTRAZIONE AI (Ctrl+E o pulsante 🚀)
   L'AI locale (Qwen3, totalmente offline) trasforma la tua
   descrizione in campi strutturati JSON secondo lo schema del modulo.
   Aspetta il messaggio "Elaborazione…" → NON chiudere l'app.
   Temperatura ≤ 0.2 = più preciso, 0.5 = più creativo (sconsigliato).

4️⃣ · REVISIONA SEMPRE TUTTI I CAMPI (GATE OBBLIGATORIO)
   Si apre automaticamente la finestra "Revisione bozza".
   · Controlla 1 campo alla volta, correggi errori, completa manualmente.
   · I campi in giallo/arancione NON_SPECIFICATO o vuoti vanno controllati.
   · Il badge LIVE in alto a destra conta quanti campi mancano.
   · Quando finisci → clicca  ✓ Approva e genera report.

5️⃣ · RITIRA I FILE ESPORTATI
   Viene creata una cartella in  %LOCALAPPDATA%\\MaintenanceAI\\exports\\
   Ogni rapporto produce:
   · JSON → dati ufficiali / canonici (la sorgente della verità)
   · DOCX o XLSX → il tuo template compilato
   · PDF → layout standard MaintenanceAI (generato direttamente)
   Inoltre una copia JSON va in 03_storico\\ del modulo per i prossimi.

SCORCIATOIE UTILI:
  Ctrl+N  = nuovo modulo          Ctrl+E  = avvia estrazione AI
  Ctrl+S  = apri ultimo export    Ctrl+F  = cerca moduli
  F1      = questa guida          F5      = ricarica moduli
  Ctrl+Tab = passa tra i tab      Esc     = chiudi finestre modali

RICORDATI SEMPRE:
  · L'AI NON decide nulla — la bozza è SUGGERIMENTO, non verità.
  · Il controllo umano è OBBLIGATORIO prima di ogni esportazione.
  · Tutto funziona OFFLINE — nessun dato lascia il tuo PC.
"""


_HELP_FAQ = [
    ("L'app non si avvia / si chiude subito?",
     "Controlla che esistano:\n"
     "  • runtime/llama/llama-server.exe (e DLL vicine)\n"
     "  • models/<modello>.gguf (indicato in config/default.json)\n"
     "  • RAM libera ≥ 4 GB per profilo balanced. Leggi i log in\n"
     "    %LOCALAPPDATA%/MaintenanceAI/logs/crash.log"),
    ("Stato AI sempre ROSSO Errore?",
     "• Porte 39280–39299 occupate da altro processo\n"
     "• Modello GGUF corrotto o incompleto\n"
     "• RAM insufficiente → prova profilo 'compatibility'\n"
     "  dal menù a tendina in alto a destra. Riavvia l'app."),
    ("Estrazione AI fallisce sempre?",
     "• Scrivi ALMENO 10–20 caratteri nella descrizione\n"
     "• Verifica che lo Stato AI sia 'Inattivo' (non 'Errore')\n"
     "• Se usi un modulo vuoto → ricontrolla che schema.json sia valido."),
    ("L'AI ha INVENTATO dati (date, codici, nomi)?",
     "È FISIOLOGICO: per questo esiste LA REVISIONE UMANA.\n"
     "L'AI usa 'NON_SPECIFICATO' quando non sa, ma a volte sbaglia.\n"
     "RILEGGI SEMPRE TUTTO nella finestra Revisione, correggi a mano.\n"
     "Più dettagli scrivi nella descrizione e meno inventa."),
    ("Tanti campi sono NON_SPECIFICATO. Perché?",
     "Perché L'AI NON trova l'informazione nella tua descrizione\n"
     "e PER POLITICA NON inventa. Completa manualmente in Revisione\n"
     "o scrivi una descrizione più ricca di dettagli la prossima volta."),
    ("In approvazione: 'Validazione fallita'?",
     "Il popup dice QUALE campo e PERCHÉ. Esempi:\n"
     "  • campo numerico che contiene lettere\n"
     "  • enum non tra i valori ammessi → scegli dal Combobox\n"
     "  • array scritto male → 1 elemento PER RIGA; oggetti = 'k=v ; k=v'\n"
     "  • oggetto JSON scritto con sintassi sbagliata → controlla parentesi."),
    ("Doc 'Da template' → 'Nessun placeholder rilevato'",
     "Nel tuo DOCX o XLSX NON ci sono i segnaposto {{nome_campo}}.\n"
     "Aprili in Word/Excel e inserisci: {{data}} {{operatore}} {{esito}}\n"
     "ecc. Le doppie graffe sono OBBLIGATORIE. Gli spazi dentro {{ nome }}\n"
     "sono accettati."),
    ("Il PDF NON assomiglia al DOCX. È un bug?",
     "È VOLUTO: il PDF è un layout STANDARD di MaintenanceAI\n"
     "(generato direttamente da ReportLab, NON da rendering Office).\n"
     "Per il formato esatto del tuo documento → usa il file DOCX/XLSX\n"
     "esportato e stampalo come PDF da Word o LibreOffice."),
    ("Ho cancellato la cartella export / l'ho spostata.",
     "Nel DB è rimasto il percorso originale → doppio clic nello Storico\n"
     "ti avvisa con 'Cartella inesistente o spostata'. Non è un errore.\n"
     "Ripristina la cartella o ricrea il rapporto."),
    ("Come sposto TUTTO su un altro PC?",
     "Copia l'intera cartella  %LOCALAPPDATA%/MaintenanceAI/\n"
     "(DB, workspace moduli, storico, export) nella stessa posizione\n"
     "del nuovo PC. Copia poi anche la cartella MaintenanceAI.exe\n"
     "(installazione portatile). Fatto."),
    ("Posso modificare schema.json / template / mapping.json a mano?",
     "SÌ, sono file nel workspace/modules/<slug>/  — chiudi prima l'app\n"
     "o premi F5 dopo la modifica per ricaricare. Non c'è bisogno di\n"
     "ricompilare niente: l'app li legge direttamente dal disco."),
]


_HELP_FULL = r"""\
==== INDICE MANUALE COMPLETO ====

1. Panoramica generale
   MaintenanceAI è un'app desktop Windows 100% OFFLINE e LOCALE per la
   generazione assistita di rapporti di manutenzione. Usa il modello Qwen3
   (GGUF) eseguito localmente con llama.cpp. Nessun dato lascia il PC.

   FLUSSO OBBLIGATORIO NON SALTABILE:
   Modulo → Descrizione → Estrazione AI → REVISIONE UMANA → Esportazione.

2. Requisiti e installazione
   Nessun software richiesto sul PC utente:
   ❌ Python ❌ Ollama ❌ GPU ❌ Office ❌ Internet.
   Basta doppio clic su MaintenanceAI.exe

   Cartella portatile:
     MaintenanceAI\MaintenanceAI.exe
     MaintenanceAI\_internal\        (runtime Python)
     MaintenanceAI\runtime\llama\    (llama-server.exe + DLL)
     MaintenanceAI\models\           (file modello .gguf)
     MaintenanceAI\config\default.json
     MaintenanceAI\VERSION.txt

   DATI UTENTE →  %LOCALAPPDATA%\MaintenanceAI\
     logs\           maintenance_ai.log (rotanti 2MB × 3)
     maintenance_ai.db   (SQLite: metadati, record, hash, cache)
     exports\        (una sottocartella per ogni rapporto finale)
     workspace\modules\<slug>\ (moduli utente)
         01_modulo_vuoto/        (template DOCX/XLSX)
         02_documenti_riferimento/ (procedure, manuali, listini)
         03_storico/             (JSON copiati auto dopo ogni export)
         module.json  schema.json  mapping.json

3. Avvio
   - Doppio clic MaintenanceAI.exe
   - L'app:
     a) crea %LOCALAPPDATA%\MaintenanceAI\ (se non esiste)
     b) inizializza il DB SQLite
     c) avvia in background llama-server.exe su 127.0.0.1 porta casuale
        39280-39299, --no-webui, api-key FRESCA per ogni avvio
     d) attende /health
     e) apre la GUI.
   La console nera è VOLUTA: mostra immediatamente gli errori di runtime.

   Chiusura: clic X in alto destra → arresta llama-server, salva DB, chiude.

4. Interfaccia principale
   HEADER SUPERIORE gradient:
     · Logo + sottotitolo "AI locale · Offline"
     · PROFILO LLM (tendina):
         compatibility = 0.6B, 2048 ctx, 2 thread (PC lenti)
         balanced      = 1.7B, 4096 ctx         (default, CONSIGLIATO)
         fastest       = 1.7B, 8 thread forzati (CPU potenti)
     · STATO AI (pallino):
         grigio Inattivo | giallo Elaborazione… | verde OK | rosso Errore
     · (?) Pulsante aiuto = QUESTA finestra (o F1)

   SIDEBAR SINISTRA 310px:
     · 📦 Moduli  + casella ricerca LIVE 🔍 (digita e filtra, senza Invio)
     · Albero moduli → clic per selezionare, doppio clic → dettagli
     · Pulsanti:
         + Nuovo modulo (Ctrl+N)
         ↓ Importa modulo (ZIP)
         ↻ Ricarica (F5)

   4 TAB CENTRALI (Ctrl+Tab / Ctrl+Shift+Tab):
     🏠 HOME       → statistiche e azioni rapide
     📝 RAPPORTO   → descrizione + estrazione AI
     📚 STORICO    → tutti i rapporti creati (filtri + ricerca)
     ℹ️ DETTAGLI   → info e file del modulo selezionato

   BARRA STATO INFERIORE: messaggio + "Offline · Locale · Privacy first".
   SISTEMA TOAST in basso dx: messaggi colorati ℹ️ ✅ ⚠️ ❌.

5. Tab 🏠 HOME
   4 card statistiche: Moduli · Bozze/Rapporti · Esportati · Ultimo intervento
   3 card azione: Nuovo modulo · Importa ZIP · Apri cartella modelli.

6. Gestione moduli
   Ogni modulo = UN TIPO SPECIFICO DI RAPPORTO.
   STRUTTURA OBBLIGATORIA:
     <workspace>/modules/<slug>/
       module.json         ← nome, versione, template_type (docx|xlsx)
       schema.json         ← JSON Schema dei campi
       mapping.json        ← mapping celle XLSX ({} per DOCX)
       01_modulo_vuoto/template.(docx|xlsx)
       02_documenti_riferimento/*.docx, *.xlsx   (procedure, listini…)
       03_storico/*.json   (app ci scrive AUTOMATICAMENTE dopo export)

   CREA NUOVO MODULO (Ctrl+N):
     Passo 1: MODALITÀ
       📄 Da file template (DOCX/XLSX)  ← CONSIGLIATA, zero codice
          Carica il tuo file Word/Excel con placeholder {{nome_campo}}
          L'app AUTO: trova tutti i placeholder, genera schema.json,
          genera mapping.json (per XLSX: ricorda posizione cella).
       🧱 Modulo vuoto  → DOCX minimale, modifica poi schema/template a mano
     Passo 2:
       Nome modulo * (obbligatorio)
       Descrizione (opzionale)
       Slug (opzionale: auto dal nome, minuscolo, pulito, senza spazi)
       File template (solo modalità "Da file"): Scegli file…
     Clic "Crea modulo": cartella creata + DB aggiornato + selezionato auto.

   Regole per i placeholder nel template:
     {{nome_campo}}  → doppie graffe OBBLIGATORIE
     Lettere / numeri / _ / .  → niente spazi niente caratteri strani
     L'app gestisce anche placeholder spezzati in più "run" di Word.
     Esempi:  {{data_intervento}}  {{operatore}}  {{esito_finale}}
     Suffissi speciali (euristica schema zero-code):
       chk_xxx, xxx_si, xxx_no     → booleano
       xxx_list, xxx_items, xxx_s, xxx_i, xxx_pezzi   → array

   IMPORTA MODULO: pulsante ↓ oppure card HOME → file .zip → validato
     sicurezza (max 100 MB decompresso, ≤ 5000 entries) → estratto
     in workspace → modulo subito disponibile.

7. Tab 📝 RAPPORTO  (flusso operativo)
   PREREQUISITO: modulo selezionato nella sidebar (primo auto-selezionato).

   COLONNA SX (3/5):
     • Titolo 📝  Descrizione intervento
     • Contatore qualità in alto dx:
         <20 char  🔴 BASSA
         <60 char  🟡 MEDIA
         ≥60 char  🟢 BUONA
     • Area testo multilinea → scrivi QUI in italiano libero.
       CONSIGLIO (casella blu 💡):
         Includi data, impianto, componenti, attività, esiti, misure, note.
     • Pulsante HERO  🚀  Avvia estrazione AI  (Ctrl+E)
        Richiede MINIMO 10 caratteri.
     • Barra progresso sotto (indeterminata → determinata).

   COLONNA DX (2/5) · Opzioni estrazione:
     ✅ Usa documenti di riferimento   (02_…) → contesto/istruzioni
     ✅ Usa storico interventi (03_…)  → solo TERMINOLOGIA/FORMATO, NON fatti
     Temperatura AI: slider 0.0 – 0.5, default 0.2
         0 = ripetibile/deterministico
         0.5 = più creativo (PIÙ RISCHIO ALLUCI, NON usare)

   PIPELINE AI INTERNA (dopo 🚀):
     1) Stato AI → 🟡 Elaborazione…, pulsante disabilitato + spinner
     2) Legge 02_documenti_riferimento  → testo allegato come contesto
     3) Seleziona storico da 03_ rilevante per similarità con descrizione
     4) Assembla PROMPT:
        · Politica anti-allucinazione (NON inventare, NON_SPECIFICATO ecc.)
        · Semantica schema
        · Documenti riferimento
        · Storico (solo terminologia)
        · Descrizione operatore
        · Coda  /no_think  (Qwen3)
     5) POST locale /v1/chat/completions
        temperature ≤ 0.2, stream=false,
        response_format={type:json_object, schema:schema}
        E json_schema=<schema> (doppio vincolo)
     6) Pulizia output: strip fence markdown ```, primo {…} bilanciato,
        rimozione virgole finali.
     7) Defaulting: stringhe→NON_SPECIFICATO, enum→primo valore,
        array→[], oggetti→{}
     8) Valida jsonschema. Se non valido → 1 SOLO retry con errore
        in testa al prompt.
     9) Salva BOZZA in DB (status = draft) → APRE REVISIONE.

   L'OUTPUT AI È SEMPRE BOZZA, NON È MAI FINALE.

8. Schermata Revisione (GATE UMANO OBBLIGATORIO)
   Si apre in modale, NON puoi saltarla.

   Header:
     Icona ✓  + "REVISIONE DATI ESTRATTI"
     Badge LIVE dx (si aggiorna mentre scrivi):
        ⚠ N campi da controllare (arancione) + nomi dei primi 8
        ✓ Tutti i campi compilati (verde)
     Sottotitolo: "Conferma o correggi i campi prima di approvare."

   CORPO (scrollabile, rotella mouse funziona):
     UNA CARD PER CAMPO (ordine = ordine in schema.json).
     Card ha:
       • Etichetta nome umanizzato + asterisco se required
       • Descrizione opzionale (da schema.description)
       • Widget tipo-dipendente:
           enum     → Combobox READ-ONLY, scegli valore
           string corta → Entry riga singola
           string lunga (note/descrizione/diagnosi/…)  → Text 4 righe
           array    → Text N righe (1 elemento PER RIGA)
                        oggetti: k1=v1 ; k2=v2  per riga
           object   → Text N righe JSON VALIDO
           boolean  → Checkbox
       • Evidenziazione LIVE:
           se campo manca (null, "", NON_SPECIFICATO, [] o {}):
             card → striscia arancione + sfondo giallino
             bordo input → arancione
             messaggio sotto ⚠ NON_SPECIFICATO … compila se disponibile
           altrimenti:
             card → striscia azzurro chiaro + sfondo bianco
       • Messino ⚠ Mancante / NON_SPECIFICATO  se campo è da rivedere.

   3 BOTTONI IN BASSO (destra):
     ⬅ Annulla → chiude, ESPORTA NULLA. Bozza resta nel DB.
     💾 Salva modifiche (continua) → popup ok, NON chiude.
     ✓ Approva e genera report → FINALE:
        1) raccoglie tutti i dati da widget
        2) VALIDA jsonschema FORMALE → se fallisce → mostra errore
           CON nome campo + motivo → correggere
        3) se valido → chiude Revisione → LANCIA ESPORTAZIONI.

9. Dopo l'approvazione · esportazioni
   Torni nel tab Rapporto. Appare popup "✅ Rapporto esportato".
   Contenuto popup:
     • Nome modulo · nome cartella esportazione
     • Elenco file prodotti + PULSANTE "Apri" per ognuno
     • 3 bottoni finali:
         Nuovo rapporto (verde) → svuota descrizione e ricomincia
         Apri cartella  (accento) → Explorer sulla cartella export
         Chiudi

   CARTELLE ESPORTAZIONE:
     %LOCALAPPDATA%\MaintenanceAI\exports\<slug>_<id>_<YYYYMMDD_HHMMSS>\
       .\  <stesso_nome>.json     ← SORGENTE UFFICIALE (dati approvati)
       .\  <stesso_nome>.docx     o .xlsx   (template compilato)
       .\  <stesso_nome>.pdf      ← layout standard ReportLab
   Inoltre:
     copia  03_storico\<stesso_nome>.json   nel modulo (input + final_json)
     DB: status = exported, vengono salvati i 3 percorsi file.

10. Tab 📚 STORICO
    Filtro stato (tendina):
      Tutti | Bozze (draft) | Approvati (approved) | Esportati (exported) | Falliti (failed)
    Ricerca libera 🔍 (cerca in modulo / data / stato / cartella)
    Pulsante 🔄 Aggiorna

    Tabella colonne:  Modulo · Stato · Data creazione · Cartella
    Righe colorate per stato:
      Bozza arancio | Approvato grigio | Esportato verde | Fallito rosso

    DOPPIO CLICK su riga → apre in EXPLORER la cartella export (se esiste).

11. Tab ℹ️ DETTAGLI MODULO
    Card riepilogo: nome, descrizione, 🔖 slug, 📁 cartella,
                    📄 template, 🧱 schema
    Pulsanti:
      Apri cartella modulo  (root con i 3 JSON + 3 cartelle)
      01 · Vuoto            → 01_modulo_vuoto/
      02 · Riferimenti      → 02_documenti_riferimento/
      03 · Storico          → 03_storico/

    Albero file ricorsivo del modulo:
      icona tipo, dimensione KB, estensione. Root aperto di default.

12. Scorciatoie tastiera (riassunto)
    Ctrl+N     Nuovo modulo
    Ctrl+E     Avvia estrazione AI
    Ctrl+S     Apri ultima cartella export
    Ctrl+F     Focus casella ricerca moduli
    F1         GUIDA (questa finestra)
    F5         Ricarica moduli
    Ctrl+Tab   / Ctrl+PagGiu   → Tab successivo
    Ctrl+Shift+Tab / Ctrl+PagSu → Tab precedente
    Esc        Chiudi finestra modale in primo piano
    Invio      Nel wizard "Nuovo modulo" = crea

13. Modifiche manuali a moduli (avanzato)
    Puoi editare direttamente:
      workspace/modules/<slug>/schema.json
      workspace/modules/<slug>/mapping.json
      workspace/modules/<slug>/01_modulo_vuoto/template.docx
      workspace/modules/<slug>/02_documenti_riferimento/*.docx
    Poi nella GUI premi F5 per ricaricare. Non serve riavviare.

14. Percorsi diagnostici / debug
    %LOCALAPPDATA%\MaintenanceAI\logs\maintenance_ai.log
    %LOCALAPPDATA%\MaintenanceAI\logs\crash.log
    %LOCALAPPDATA%\MaintenanceAI\maintenance_ai.db   (SQLite, apribile con DB Browser)
    Cartella installazione\VERSION.txt  (versione MaintenanceAI + llama.cpp + modello SHA)

15. Politiche anti-allucinazione
    L'AI è istruita con regole severe (vedi prompt_builder SYSTEM_POLICY):
      "Il tuo compito NON è inventare un rapporto plausibile.
       Il tuo compito è trasformare ESCLUSIVAMENTE le informazioni
       fornite dall'operatore e dai documenti di contesto.
       NON inventare date, nomi, codici, quantità, misure, componenti,
       cause o risultati. Quando manca → NON_SPECIFICATO.
       Non trasformare una possibilità in un fatto.
       I documenti riferimento SONO ISTRUZIONI, non prove di esecuzione.
       Lo storico è per TERMINOLOGIA, non per copiare fatti.
       Restituisci ESCLUSIVAMENTE i campi richiesti.
       Non aggiungere campi non previsti."
    Inoltre la temperatura è BLOCCATA a ≤ 0.2.
    TUTTAVIA, il controllo umano RIMANE SEMPRE l'unica garanzia.
"""


class HelpDialog(tk.Toplevel):
    def __init__(self, master: tk.Misc):
        super().__init__(master)
        self.title("Manuale e FAQ · MaintenanceAI")
        self.configure(bg=COLORS["white"])
        try:
            apply_theme(self)
        except Exception:
            pass

        w = 1020
        h = 720
        self.geometry(f"{w}x{h}")
        self.minsize(860, 600)
        center_window(self, w, h)
        self.transient(master)
        self.grab_set()

        self._build()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.bind("<Escape>", lambda _e: self._close())

    # ------------------------------------------------------------------
    def _build(self) -> None:
        head = GradientCanvas(self, COLORS["primary_800"], COLORS["slate_900"],
                              direction="horizontal", height=104)
        head.pack(fill="x")

        inner = tk.Frame(self, bg=COLORS["primary_800"])
        head.create_window((24, 16), anchor="nw", window=inner, tags="hdr")

        def _hr(_e=None):
            try:
                ww = head.winfo_width() - 48
                if ww < 500:
                    ww = 500
                inner.configure(width=ww)
            except Exception:
                pass

        head.bind("<Configure>", _hr, add="+")

        left = tk.Frame(inner, bg=COLORS["primary_800"])
        left.pack(side="left", fill="y")
        icon_wrap = tk.Frame(left, bg=COLORS["white"], bd=0, highlightthickness=0)
        icon_wrap.pack(side="left")
        tk.Label(icon_wrap, text="?",
                 bg=COLORS["white"], fg=COLORS["primary_600"],
                 font=(FONT_FAMILY, 26, "bold"),
                 padx=16, pady=8).pack()

        titles = tk.Frame(left, bg=COLORS["primary_800"])
        titles.pack(side="left", padx=(16, 0), fill="both", expand=True)
        tk.Label(titles, text="GUIDA ALL'USO · FAQ · MANUALE",
                 bg=COLORS["primary_800"], fg=COLORS["white"],
                 font=FONTS["h2"]).pack(anchor="w")
        tk.Label(titles,
                 text="Scorciatoia rapida: F1 da qualsiasi punto dell'applicazione. "
                      "Il controllo umano è sempre obbligatorio prima dell'esportazione.",
                 bg=COLORS["primary_800"], fg=COLORS["slate_300"],
                 wraplength=640, justify="left",
                 font=FONTS["body_sm"]).pack(anchor="w", pady=(4, 0))

        close_wrap = tk.Frame(inner, bg=COLORS["primary_800"])
        close_wrap.pack(side="right")
        ttk.Button(close_wrap, text="Chiudi  (Esc)", style="Subtle.TButton",
                   command=self._close).pack()

        wrap = tk.Frame(self, bg=COLORS["white"])
        wrap.pack(fill="both", expand=True, padx=22, pady=20)

        nb = ttk.Notebook(wrap, style="Card.TNotebook")
        nb.pack(fill="both", expand=True)

        self._tab_quick = ttk.Frame(nb, style="TFrame")
        self._tab_faq = ttk.Frame(nb, style="TFrame")
        self._tab_full = ttk.Frame(nb, style="TFrame")

        nb.add(self._tab_quick, text="  🚀  Guida rapida  ")
        nb.add(self._tab_faq,   text="  ❓  FAQ  ")
        nb.add(self._tab_full,  text="  📖  Manuale completo  ")

        self._build_quick(self._tab_quick)
        self._build_faq(self._tab_faq)
        self._build_full(self._tab_full)

    # ------------------ Tab Guida rapida -------------------------------
    def _build_quick(self, parent: ttk.Frame) -> None:
        body = tk.Frame(parent, bg=COLORS["white"])
        body.pack(fill="both", expand=True, padx=10, pady=10)
        self._build_document_view(body, _HELP_QUICK, accent=COLORS["primary_600"])

    # ------------------ Tab FAQ ----------------------------------------
    def _build_faq(self, parent: ttk.Frame) -> None:
        body = tk.Frame(parent, bg=COLORS["white"])
        body.pack(fill="both", expand=True, padx=10, pady=10)

        lines = []
        lines.append("═" * 78)
        lines.append("  FAQ — DOMANDE FREQUENTI")
        lines.append("═" * 78)
        lines.append("")
        for i, (q, a) in enumerate(_HELP_FAQ, start=1):
            lines.append(f"[{i:02d}] ❓ {q}")
            lines.append("─" * 78)
            for raw in a.splitlines():
                lines.append(f"      {raw}")
            lines.append("")
        lines.append("═" * 78)
        self._build_document_view(body, "\n".join(lines), accent=COLORS["warning_600"])

    # ------------------ Tab Manuale completo ---------------------------
    def _build_full(self, parent: ttk.Frame) -> None:
        body = tk.Frame(parent, bg=COLORS["white"])
        body.pack(fill="both", expand=True, padx=10, pady=10)
        self._build_document_view(body, _HELP_FULL, accent=COLORS["primary_600"])

    # ------------------ Shared helpers ---------------------------------
    def _build_document_view(self, parent: tk.Misc, text: str,
                             accent: str) -> None:
        shell = tk.Frame(parent, bg=COLORS["white"],
                         highlightthickness=1,
                         highlightbackground=COLORS["slate_200"],
                         bd=0)
        shell.pack(fill="both", expand=True)
        strip = tk.Frame(shell, bg=accent, height=4)
        strip.pack(fill="x", side="top")

        inner = tk.Frame(shell, bg=COLORS["white"])
        inner.pack(fill="both", expand=True, padx=16, pady=16)

        vsb = ttk.Scrollbar(inner, orient="vertical")
        vsb.pack(side="right", fill="y")

        txt = tk.Text(inner, wrap="word",
                      font=(FONT_FAMILY, 10),
                      fg=COLORS["slate_900"],
                      bg=COLORS["white"],
                      selectbackground=accent,
                      selectforeground=COLORS["white"],
                      insertbackground=COLORS["slate_700"],
                      bd=0, relief="flat",
                      padx=14, pady=14,
                      spacing1=1, spacing3=2,
                      yscrollcommand=vsb.set)
        vsb.configure(command=txt.yview)
        txt.pack(side="left", fill="both", expand=True)
        txt.insert("1.0", text)
        txt.configure(state="disabled")

    def _close(self) -> None:
        try:
            self.destroy()
        except Exception:
            pass


def run_help(master: tk.Misc) -> None:
    try:
        dlg = HelpDialog(master)
        master.wait_window(dlg)
    except Exception:
        pass
