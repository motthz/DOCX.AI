import multiprocessing

# Necessario per i processi figli (export PDF) nell'exe PyInstaller.
multiprocessing.freeze_support()

from maintenance_ai.main import main  # noqa: E402

raise SystemExit(main())
