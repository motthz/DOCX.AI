# Changelog

Formato basato su [Keep a Changelog](https://keepachangelog.com/it/1.1.0/),
versionamento [SemVer](https://semver.org/lang/it/). La versione ha un'unica
fonte: `src/maintenance_ai/__init__.py`.

## [Non rilasciato]

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

[Non rilasciato]: https://github.com/motthz/MaintenanceAI/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/motthz/MaintenanceAI/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/motthz/MaintenanceAI/releases/tag/v0.1.0
