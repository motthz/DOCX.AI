"""Pulizia del testo scritto di fretta prima della compilazione AI (senza AI).

Il modello piccolo perdeva molti campi con i testi "sporchi" (67% contro 85% degli
stessi contenuti scritti bene):

- abbreviazioni da chat o da appunti ("rapp", "manut", "matr", "gg", "xke", "uff"):
  sciolte, cosi' il modello riconosce a quale campo si riferiscono;
- autocorrezioni ("costo 500 euro, anzi no 680", "reparto produzione no scusate reparto
  qualità"): resta solo il valore detto dopo. Prima il modello prendeva il primo e il
  controllo dei fatti lo accettava, perche' compariva davvero nel testo.

Si interviene solo su forme sicure: abbreviazioni come parola isolata e in minuscolo,
autocorrezioni introdotte da formule esplicite.
"""

from __future__ import annotations

import re
from typing import List, Tuple

_ABBREVIATIONS = {
    "rapp": "rapporto", "manut": "manutenzione", "rep": "reparto", "uff": "ufficio", "matr": "matricola",
    "gg": "giorni", "xke": "perché", "xké": "perché", "xche": "perché", "xché": "perché", "resp": "responsabile",
    "cauz": "cauzione", "restituz": "restituzione", "sanific": "sanificazione", "magaz": "magazzino",
    "qta": "quantità", "q.tà": "quantità", "nr": "numero", "amm": "amministrazione", "forn": "fornitore", "tecn": "tecnico", "interv": "intervento",
    "cmq": "comunque", "nn": "non", "qlc": "qualche", "dx": "destra", "sx": "sinistra",
}
_ABBR_RE = re.compile(r"(?<![\w.])(" + "|".join(sorted((re.escape(k) for k in _ABBREVIATIONS), key=len, reverse=True))
                      + r")(?![\w])")
# "x" = "per" solo tra parole ("chiedo x oggi"), mai nelle misure ("3 x 4", "2x")
_X_RE = re.compile(r"(?<=[a-zà-ù] )x(?= [a-zà-ù])")

_CUE = re.compile(r"\s*[,;]?\s*\b(?:anzi\s+no|anzi\s+scusa(?:te)?|no\s+scusa(?:te)?|no\s+aspetta|volevo\s+dire|"
                  r"cio[eè]\s+no)\b(?:[\s,]+(?:scusa(?:te)?|aspetta|no)\b)*[\s,:.]*", re.I)
# fine del valore corretto: punteggiatura o congiunzione che apre un'altra frase
_STOP_WORDS = {"perché", "perche", "che", "ma", "quindi", "poi", "siccome", "visto", "dato", "mentre", "però"}
_NUM = re.compile(r"\d[\d.,]*")


def _expand(text: str) -> str:
    def repl(m: re.Match) -> str:
        word = m.group(1)
        if word != word.lower():
            return m.group(0)  # "Rep" maiuscolo: nome proprio o sigla, non toccare
        return _ABBREVIATIONS[word]
    text = _ABBR_RE.sub(repl, text)
    return _X_RE.sub("per", text)


def _apply_correction(text: str) -> Tuple[str, bool]:
    m = _CUE.search(text)
    if not m:
        return text, False
    before, after = text[:m.start()], text[m.end():]
    # valore corretto: parole dopo la formula fino a punteggiatura/congiunzione (max 5)
    words: List[str] = []
    rest_start = 0
    for wm in re.finditer(r"\S+", after):
        w = wm.group(0)
        bare = w.rstrip(",.;:!?").lower()
        if words and bare in _STOP_WORDS:
            rest_start = wm.start()
            break
        words.append(w.rstrip(",.;:!?"))
        rest_start = wm.end() - (len(w) - len(w.rstrip(",.;:!?")))
        if w != w.rstrip(",.;:!?") or len(words) >= 5:
            break
    else:
        rest_start = len(after)
    if not words:
        return text, False
    replacement = " ".join(words)
    rest = after[rest_start:]
    # segmento sbagliato: le ultime parole prima della formula, nella stessa frase
    seg_start = max(before.rfind(c) for c in ".;:\n") + 1
    segment = before[seg_start:]
    seg_words = list(re.finditer(r"\S+", segment))
    if not seg_words:
        return text, False
    nums = list(_NUM.finditer(segment))
    if _NUM.fullmatch(words[0]) and nums:
        # "500 euro, anzi no 680": si sostituisce solo il numero, l'unita' resta
        n = nums[-1]
        if len(words) > 1:  # "3 bar, anzi no 3,5 bar": il valore nuovo ha gia' l'unita'
            new_segment = segment[:n.start()] + replacement
        else:
            new_segment = segment[:n.start()] + words[0] + segment[n.end():].rstrip(" ,")
    else:
        k = min(len(words), len(seg_words))
        cut = seg_words[-k].start()
        new_segment = segment[:cut] + replacement
    return before[:seg_start] + new_segment + rest, True


def clean_user_text(text: str) -> Tuple[str, List[str]]:
    """(testo pulito, note sulle modifiche). Il testo originale resta nello storico."""
    if not text or not text.strip():
        return text, []
    notes: List[str] = []
    out = _expand(text)
    if out != text:
        notes.append("abbreviazioni sciolte")
    for _ in range(5):  # piu' autocorrezioni nello stesso testo
        out, changed = _apply_correction(out)
        if not changed:
            break
        if "autocorrezioni applicate" not in notes:
            notes.append("autocorrezioni applicate")
    return out, notes
