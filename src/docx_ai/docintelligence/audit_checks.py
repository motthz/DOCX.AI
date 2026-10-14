"""Controlli deterministici dell'audit su cartella (senza AI).

Il modello piccolo non riesce a confrontare date, revisioni e codici sparsi in piu'
documenti: nell'audit di prova trovava 1 problema su 8 e segnalava problemi
inesistenti. Questi controlli leggono le righe "etichetta: valore" (e le righe di
tabella "a | b | c" di Excel/PDF) e verificano:

- cronologia: apertura <= chiusura, ordine di lavoro <= intervento <= collaudo,
  anche tra documenti collegati (stesso numero di rapporto o documento citato);
- documenti citati ("vedi", "rif.", "procedura", "rapporto"...) ma assenti dal pacchetto;
- revisione citata diversa da quella presente nel pacchetto;
- strumenti usati dopo la scadenza della taratura (tabelle con colonna "Scadenza");
- codice macchina diverso tra documenti collegati (AF-300 / AF-350);
- firme e responsabili lasciati vuoti ("Responsabile:", "firma: ____", "(manca)").
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode("ascii")
    return s.lower()


def _alnum(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", _norm(s))


_DATE_RE = re.compile(r"(?<![\d/.-])(\d{1,2})[/.-](\d{1,2})[/.-](\d{4}|\d{2})(?![\d/.-])|(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
_MONTHS = {"gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6, "luglio": 7,
           "agosto": 8, "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12}
_TEXT_DATE_RE = re.compile(r"\b(\d{1,2})\s+(" + "|".join(_MONTHS) + r")\s+(\d{4})\b", re.I)


def _dates_in(text: str) -> List[date]:
    out: List[date] = []
    for m in _DATE_RE.finditer(text or ""):
        try:
            if m.group(4):
                out.append(date(int(m.group(4)), int(m.group(5)), int(m.group(6))))
            else:
                y = int(m.group(3))
                y = y + 2000 if y < 100 else y
                out.append(date(y, int(m.group(2)), int(m.group(1))))
        except ValueError:
            pass
    for m in _TEXT_DATE_RE.finditer(text or ""):
        try:
            out.append(date(int(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1))))
        except ValueError:
            pass
    return out


def _fmt(d: date) -> str:
    return d.strftime("%d/%m/%Y")


# ---------------------------------------------------------------------------
# Lettura dei documenti
# ---------------------------------------------------------------------------
@dataclass
class Field:
    label: str
    value: str
    line: str
    next_line: str = ""


@dataclass
class DocInfo:
    name: str
    text: str
    title: str
    fields: List[Field] = field(default_factory=list)
    lines: List[str] = field(default_factory=list)

    @property
    def is_order(self) -> bool:
        k = re.sub(r"[^a-z0-9]+", " ", _norm(self.name + " " + self.title))
        return bool(re.search(r"\bodl\b|odl[-_ ]?\d|\boda\b|oda[-_ ]?\d|\bordine\b|work order|purchase order|"
                              r"richiesta (di )?intervento", k))


_SEP = re.compile(r"\s*(?::|\|)\s*")


def _doc_info(doc: Any) -> DocInfo:
    name = Path(getattr(doc, "path", "")).name
    text = getattr(doc, "full_text", "") or ""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("[Sheet:")]
    info = DocInfo(name=name, text=text, title=lines[0] if lines else "", lines=lines)
    for i, ln in enumerate(lines):
        m = _SEP.search(ln)
        if not m or m.start() == 0:
            continue
        label = ln[:m.start()].strip()
        if len(label) > 60 or len(label.split()) > 7:
            continue
        value = ln[m.end():].strip()
        # righe di tabella con piu' colonne: "Calibro | CAL-12 | 30/09/2025" non e' etichetta: valore
        if "|" in value:
            continue
        info.fields.append(Field(label, value, ln, lines[i + 1] if i + 1 < len(lines) else ""))
    return info


# ruolo di una data dall'etichetta
_ROLE_WORDS = [
    ("delivery", r"consegn|ricevimento|\barrivo\b|spedizion|\bddt\b"),
    ("close", r"chiusur|\bfine\b|completament|risoluzion|evas"),
    ("test", r"collaud|verific|\bprova\b|controllo finale|rimess[ao] in servizio|accettazion"),
    ("work", r"intervent|esecuzion|\blavori\b|riparazion|manutenzion|sostituzion|\bcorso\b|formazion"),
    ("open", r"apertur|emission|creazion|richiest|segnalazion|rilevazion|\binizio\b"),
]


def _role(label: str) -> Optional[str]:
    lab = _norm(label)
    if not re.search(r"\bdata\b|\bdel\b|\bil\b|date|giorno", lab) and not re.search(r"apertur|chiusur|collaud|consegn",
                                                                                   lab):
        return None
    for role, rx in _ROLE_WORDS:
        if re.search(rx, lab):
            return role
    return None


def _role_dates(info: DocInfo) -> Dict[str, Tuple[date, str]]:
    out: Dict[str, Tuple[date, str]] = {}
    for f in info.fields:
        role = _role(f.label)
        ds = _dates_in(f.value)
        if role and ds and role not in out:
            if role == "open" and info.is_order:
                role = "order"
            out[role] = (ds[0], f.line)
    return out


# riferimenti: numeri di rapporto (245/26) e codici documento (OdL-1182, PR-07, 8D-044)
_REPORT_NO = re.compile(r"(?<![\w/])(\d{1,6})\s*[/-]\s*(\d{2,4})(?![\w/])")
_CODE = re.compile(r"(?<![\w-])([A-Za-z][A-Za-z0-9]{0,5}[-_][A-Za-z0-9]*\d[A-Za-z0-9-]*|[A-Za-z]{1,6}\d{2,}[A-Za-z0-9-]*|\d{1,2}[A-Za-z]{1,3}[-_]\d{2,}[A-Za-z0-9-]*)(?![\w-])")
_CUE = re.compile(r"\b(?:vedi|v\.|rif\.?|riferimento|cfr\.?|secondo|allegat[oi]|procedura|istruzione|rapporto|"
                  r"verbale|modulo|ordine di lavoro|documento|doc\.|report|8d)\b", re.I)


def _keys(text: str) -> Set[str]:
    keys = {f"{int(a)}/{b[-2:]}" for a, b in _REPORT_NO.findall(text or "") if len(b) in (2, 4)}
    keys |= {_alnum(c) for c in _CODE.findall(text or "") if sum(ch.isdigit() for ch in c) >= 2}
    return keys


def _own_keys(info: "DocInfo") -> Set[str]:
    """Identificativi del documento stesso: dal nome del file ("Ordine_ODA-1120.xlsx") e dal titolo."""
    return _keys(Path(info.name).stem.replace("_", " ") + " " + info.title)


def _digits_ok(code: str) -> bool:
    return sum(ch.isdigit() for ch in code) >= 2


# ---------------------------------------------------------------------------
@dataclass
class Issue:
    title: str
    severity: str
    description: str
    files: List[str]
    evidence: str
    suggestion: str
    kind: str


class AuditChecks:
    def __init__(self, docs: Iterable[Any]):
        self.docs = [_doc_info(d) for d in docs]
        self.issues: List[Issue] = []
        names = " ".join(_alnum(d.name) for d in self.docs)
        titles = " ".join(_alnum(d.title) for d in self.docs)
        self._present = names + " " + titles

    # --------------------------------------------------------------
    def run(self) -> List[Issue]:
        groups = self._groups()
        for info in self.docs:
            self._chronology_inside(info)
            self._empty_signatures(info)
        self._chronology_across(groups)
        self._references()
        self._calibration()
        self._labelled_expiry()
        self._codes_across(groups)
        return self.issues

    def _add(self, kind: str, title: str, severity: str, description: str, files: List[str], evidence: str,
             suggestion: str) -> None:
        key = (kind, tuple(sorted(files)), title)
        if any((i.kind, tuple(sorted(i.files)), i.title) == key for i in self.issues):
            return
        self.issues.append(Issue(title, severity, description, files, evidence, suggestion, kind))

    # ---- documenti collegati (stesso rapporto o documento citato) ----
    def _groups(self) -> List[List[DocInfo]]:
        own = {d.name: _own_keys(d) for d in self.docs}
        mentions = {d.name: _keys(d.text) | own[d.name] for d in self.docs}
        parent = {d.name: d.name for d in self.docs}

        def find(x: str) -> str:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for a in self.docs:
            for b in self.docs:
                if a.name >= b.name:
                    continue
                # collegati se uno cita l'identificativo dell'altro, o se citano lo stesso rapporto
                shared_reports = {k for k in mentions[a.name] & mentions[b.name] if "/" in k}
                if (own[a.name] & mentions[b.name]) or (own[b.name] & mentions[a.name]) or shared_reports:
                    parent[find(a.name)] = find(b.name)
        by: Dict[str, List[DocInfo]] = {}
        for d in self.docs:
            by.setdefault(find(d.name), []).append(d)
        return [g for g in by.values() if len(g) > 1]

    # ---- cronologia ----
    def _chronology_inside(self, info: DocInfo) -> None:
        r = _role_dates(info)
        start = r.get("open") or r.get("order")
        if start and "close" in r and r["close"][0] < start[0]:
            self._add("cronologia", f"{info.name}: chiusura precedente all'apertura", "ALTO",
                      f"In {info.name} la data di chiusura ({_fmt(r['close'][0])}) è precedente a quella di "
                      f"apertura ({_fmt(start[0])}).", [info.name], f"{start[1]} / {r['close'][1]}",
                      "Verifica le date: una pratica non può essere chiusa prima di essere aperta.")
        if "work" in r and "test" in r and r["test"][0] < r["work"][0]:
            self._add("cronologia", f"{info.name}: verifica precedente all'attività", "ALTO",
                      f"In {info.name} la verifica/collaudo ({_fmt(r['test'][0])}) è precedente "
                      f"all'attività verificata ({_fmt(r['work'][0])}).", [info.name], f"{r['work'][1]} / {r['test'][1]}",
                      "Verifica le date di intervento e collaudo.")

    def _chronology_across(self, groups: List[List[DocInfo]]) -> None:
        for g in groups:
            roles = [(d, _role_dates(d)) for d in g]
            works = [(d, r["work"]) for d, r in roles if "work" in r]
            orders = [(d, r["order"]) for d, r in roles if "order" in r]
            for d, r in roles:
                for od, (odate, oline) in orders:
                    if od is not d and "delivery" in r and r["delivery"][0] < odate:
                        self._add("cronologia", f"Consegna precedente all'ordine ({d.name})", "ALTO",
                                  f"{d.name} riporta la consegna il {_fmt(r['delivery'][0])}, prima dell'ordine "
                                  f"{od.name} del {_fmt(odate)}.", [d.name, od.name], f"{r['delivery'][1]} / {oline}",
                                  "Verifica se la merce è stata consegnata senza ordine o se le date sono errate.")
                for wd, (wdate, wline) in works:
                    if wd is d:
                        continue
                    if "order" in r and r["order"][0] > wdate:
                        self._add("cronologia", f"Ordine di lavoro datato dopo l'intervento ({d.name})", "ALTO",
                                  f"L'ordine {d.name} è aperto il {_fmt(r['order'][0])}, ma l'intervento "
                                  f"documentato in {wd.name} è del {_fmt(wdate)}: l'ordine dovrebbe precedere "
                                  f"il lavoro.", [d.name, wd.name], f"{r['order'][1]} / {wline}",
                                  "Verifica le date o se l'ordine è stato aperto a posteriori.")
                    if "test" in r and r["test"][0] < wdate:
                        self._add("cronologia", f"Collaudo/verifica precedente all'intervento ({d.name})", "ALTO",
                                  f"{d.name} riporta il collaudo/verifica il {_fmt(r['test'][0])}, prima "
                                  f"dell'intervento del {_fmt(wdate)} documentato in {wd.name}.",
                                  [d.name, wd.name], f"{r['test'][1]} / {wline}",
                                  "Verifica le date: il collaudo deve seguire l'intervento.")

    # ---- documenti citati e revisioni ----
    def _present_rev(self, code: str) -> Optional[Tuple[str, str]]:
        """(revisione, file) del documento del pacchetto con questo codice."""
        ac = _alnum(code)
        for d in self.docs:
            if ac and (ac in _alnum(d.name) or ac in _alnum(d.title)):
                m = re.search(r"rev(?:isione)?[\s._-]*(?:n\.?\s*)?([0-9]{1,3}|[a-z])\b", _norm(d.name))
                if not m:
                    for ln in d.lines[:12]:
                        m = re.search(r"\brev(?:isione)?\.?\s*[:.]?\s*(?:rev\.?\s*)?(?:n\.?\s*)?([0-9]{1,3}|[a-z])\b",
                                      _norm(ln))
                        if m:
                            break
                return (m.group(1) if m else "", d.name)
        return None

    def _references(self) -> None:
        for d in self.docs:
            own = _own_keys(d)
            for cue in _CUE.finditer(d.text):
                window = d.text[cue.end(): cue.end() + 40].split("\n")[0]
                cands = [m for m in _CODE.finditer(window) if _digits_ok(m.group(1))]
                # "245/26" da solo, non la parte finale di un codice ("CT-2025-08")
                cands += [m for m in _REPORT_NO.finditer(window)
                          if not any(c.start() <= m.start() < c.end() for c in cands)]
                cands.sort(key=lambda m: m.start())
                for m in cands[:2]:
                    raw = m.group(0).strip()
                    key = _alnum(raw)
                    if not key or key in own or f"{raw}" in d.title:
                        continue
                    sentence = next((ln for ln in d.lines if raw in ln), raw)
                    if key not in self._present:
                        self._add("riferimento", f"Documento citato non presente: {raw}", "ALTO",
                                  f"{d.name} cita «{raw}», ma nel pacchetto non c'è un documento con questo "
                                  f"identificativo.", [d.name], sentence,
                                  f"Recupera {raw} e aggiungilo al pacchetto, o correggi il riferimento.")
                        continue
                    rev = re.match(r"\s*,?\s*(?:rev\.?|revisione)\s*(?:n\.?\s*)?([0-9]{1,3}|[A-Za-z])\b",
                                   window[m.end():], re.I)
                    present = self._present_rev(raw)
                    if rev and present and present[0] and present[0].lower() != rev.group(1).lower():
                        self._add("revisione", f"Revisione diversa per {raw}", "ALTO",
                                  f"{d.name} applica {raw} rev. {rev.group(1)}, ma nel pacchetto c'è la rev. "
                                  f"{present[0]} ({present[1]}).", [d.name, present[1]], sentence,
                                  "Verifica quale revisione era in vigore e allega quella corretta.")

    # ---- tarature / scadenze ----
    def _calibration(self) -> None:
        for reg in self.docs:
            rows = [ln for ln in reg.lines if "|" in ln]
            header = next((ln for ln in rows if re.search(r"scaden|scade|valid", _norm(ln))), None)
            if header is None:
                continue
            cols = [_norm(c) for c in header.split("|")]
            exp_i = next(i for i, c in enumerate(cols) if re.search(r"scaden|scade|valid", c))
            for ln in rows[rows.index(header) + 1:]:
                cells = [c.strip() for c in ln.split("|")]
                if len(cells) <= exp_i:
                    continue
                exp = _dates_in(cells[exp_i])
                code = next((c for i, c in enumerate(cells) if i != exp_i and _CODE.fullmatch(c) and _digits_ok(c)),
                            None)
                if not exp or not code:
                    continue
                for d in self.docs:
                    if d is reg or not re.search(r"(?<![\w-])" + re.escape(code) + r"(?![\w-])", d.text, re.I):
                        continue
                    r = _role_dates(d)
                    used = (r.get("work") or r.get("test") or r.get("open") or (None, ""))[0]
                    if used is None:
                        ds = _dates_in(d.text)
                        used = ds[0] if ds else None
                    if used and used > exp[0]:
                        sentence = next((x for x in d.lines if code.lower() in x.lower()), code)
                        self._add("taratura", f"{code} usato con taratura/validità scaduta", "ALTO",
                                  f"{d.name} usa {code} il {_fmt(used)}, ma secondo {reg.name} la scadenza era "
                                  f"il {_fmt(exp[0])}.", [d.name, reg.name], sentence,
                                  f"Verifica le misure eseguite con {code} e la sua taratura.")

    def _labelled_expiry(self) -> None:
        """"Scadenza offerta: 15/09/2026", "Valido fino al ..." in un documento, usato da un
        documento successivo che lo cita (ordine emesso dopo la scadenza dell'offerta)."""
        for src in self.docs:
            exp = None
            for f in src.fields:
                if re.search(r"scaden|scade|valid", _norm(f.label)):
                    ds = _dates_in(f.value)
                    if ds:
                        exp = (ds[0], f.line)
                        break
            own = _own_keys(src)
            if exp is None or not own:
                continue
            for d in self.docs:
                if d is src or not (_keys(d.text) & own):
                    continue
                r = _role_dates(d)
                used = r.get("order") or r.get("open") or r.get("work")
                if used and used[0] > exp[0]:
                    self._add("scadenza", f"{d.name} successivo alla scadenza di {src.name}", "ALTO",
                              f"{d.name} è del {_fmt(used[0])} e si basa su {src.name}, valido fino al "
                              f"{_fmt(exp[0])}.", [d.name, src.name], f"{used[1]} / {exp[1]}",
                              f"Verifica se {src.name} era ancora valido o se ne serviva uno aggiornato.")

    # ---- codici macchina incoerenti ----
    _ASSET = re.compile(r"macchin|impiant|apparecchiatur|attrezzatur|matricol|asset|\bn\.? ?serie|strumento|mezzo")

    def _codes_across(self, groups: List[List[DocInfo]]) -> None:
        for g in groups:
            seen: Dict[str, List[str]] = {}
            lines: Dict[str, str] = {}
            for d in g:
                for f in d.fields:
                    if not self._ASSET.search(_norm(f.label)):
                        continue
                    m = _CODE.search(f.value)
                    if m and _digits_ok(m.group(1)):
                        code = m.group(1).upper()
                        seen.setdefault(code, []).append(d.name)
                        lines.setdefault(code, f.line)
            codes = sorted(seen)
            for i, a in enumerate(codes):
                for b in codes[i + 1:]:
                    pa, pb = re.match(r"[A-Z]+", a), re.match(r"[A-Z]+", b)
                    if pa and pb and pa.group(0) == pb.group(0):
                        files = sorted(set(seen[a] + seen[b]))
                        self._add("codice", f"Codice diverso tra documenti collegati: {a} / {b}", "ALTO",
                                  f"{a} in {', '.join(seen[a])}, {b} in {', '.join(seen[b])}: i documenti "
                                  f"riguardano lo stesso lavoro ma riportano codici diversi.", files,
                                  f"{lines[a]} / {lines[b]}", "Verifica quale codice è corretto.")

    # ---- firme e responsabili vuoti ----
    _SIGN = re.compile(r"respons|firma|firmat|approvat|verificat|redatt|visto|autorizzat|controllat")
    _EMPTY = re.compile(r"^[\s_\-.()/*]*(?:\((?:manca|mancante|assente)\)|manca|mancante|assente|n\.?d\.?|"
                        r"da firmare|non firmat\w*)?[\s_\-.()/*]*$", re.I)

    def _empty_signatures(self, info: DocInfo) -> None:
        empty = []
        for f in info.fields:
            if not self._SIGN.search(_norm(f.label)):
                continue
            if f.value:
                blank = bool(self._EMPTY.match(f.value))  # "____", "(manca)"
            else:
                # valore a capo ("Firmato:" e sotto il nome) oppure davvero vuoto
                nxt = f.next_line
                blank = not nxt or bool(self._EMPTY.match(nxt)) or bool(_SEP.search(nxt))
            if blank:
                empty.append(f.line)
        if empty:
            self._add("firma", f"{info.name}: firma o responsabile mancante", "ALTO",
                      f"In {info.name} risultano vuoti: " + "; ".join(e.rstrip(":| ") for e in empty[:4]) + ".",
                      [info.name], " / ".join(empty[:3]),
                      "Fai completare e firmare il documento dal responsabile.")


def run_checks(docs: Iterable[Any]) -> List[Issue]:
    return AuditChecks(docs).run()
