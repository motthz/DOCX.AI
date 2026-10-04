# Contribuire a DOCX.AI

## Ambiente

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_dev.ps1
.venv\Scripts\pre-commit install --hook-type pre-commit --hook-type commit-msg
```

Il progetto va tenuto **fuori da cartelle sincronizzate** (OneDrive, Dropbox):
la sincronizzazione blocca e ripristina file durante build e git.

## Messaggi di commit

[Conventional Commits](https://www.conventionalcommits.org/it/), controllati dall'hook `commit-msg`:

```
tipo(ambito): descrizione all'imperativo
```

| Tipo | Uso |
|---|---|
| `feat` | nuova funzione |
| `fix` | correzione di un bug |
| `perf` | miglioramento prestazioni |
| `refactor` | ristrutturazione senza cambi di comportamento |
| `docs`, `test`, `build`, `ci`, `chore` | documentazione, test, build, CI, manutenzione |

Esempi: `feat(storico): filtri per data e tecnico`, `fix(ocr): chiamata WinRT corretta`.

## Prima di aprire una PR

```powershell
.venv\Scripts\ruff check src tests scripts packaging
.venv\Scripts\mypy
powershell -ExecutionPolicy Bypass -File scripts\test.ps1
.venv\Scripts\python scripts\smoke_gui.py
```

Aggiorna `CHANGELOG.md` nella sezione **Non rilasciato**.

## Rilascio

1. Aggiorna `__version__` in `src/docx_ai/__init__.py` e sposta le voci del
   CHANGELOG in una nuova sezione `## [x.y.z] - data`.
2. `git tag vX.Y.Z && git push --tags`: la GitHub Action *Release* compila exe,
   installer e ZIP e li pubblica con le note prese dal CHANGELOG.

In locale: `scripts\release.ps1` produce gli stessi file in `release\`.
