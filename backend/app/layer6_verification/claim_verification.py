"""VeriFact-inspired claim verification of free text against the patient's record (Phase 3).

Adapted from VeriFact (Chung et al., NEJM AI 2025; github.com/philipchung/verifact, MIT): text is decomposed into
atomic claims, evidence is retrieved from the patient's record per claim (VeriFact: hybrid retrieval + rerank,
top-k 5), and a judge labels each claim Supported / Not Supported / Not Addressed. Differences, by design:
  * the judge is a multilingual NLI cross-encoder (or an optional Groq structured judge using VeriFact's verdict
    prompt) instead of a local vLLM judge;
  * deterministic checks of numbers+units, dates and negation run on every claim and can veto "supported";
  * "Not Supported" is split into contradicted (record says otherwise) and needs-review;
  * strict citation integrity (`verify.ClaimVerifier.verify_citation`) runs as a separate stage on every evidence
    citation; evidence failing it is dropped before judging;
  * conservative abstention: anything not positively supported is routed to human review.
"supported" here means "supported by the cited record text", never "clinically verified".
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from backend.app.layer1_ingestion.processing.segmentation import _split_sentences
from backend.app.layer4_planner.contracts import PlanStep
from backend.app.layer4_planner.planner import _search_terms

ENTAIL_T, CONTRA_T = 0.80, 0.80  # thresholds fixed a priori (not tuned on the evaluation claims)

_UNIT = r"(mg/dl|mmol/l|mmhg|mg|µg|mcg|ug|g|ml|l|kg|cm|mm|%|/min|ie|i\.e\.|mm/s|m/s)"
_NUM_UNIT = re.compile(r"(?<![\w.,])(\d+(?:[.,]\d+)?)\s*" + _UNIT + r"(?![a-zäöü])", re.I)
_NUM = re.compile(r"(?<![\w.,])\d+(?:[.,]\d+)?(?![\w])")
_MONTHS = {m: i + 1 for i, ms in enumerate([
    ("januar", "jänner", "january", "jan"), ("februar", "feber", "february", "feb"), ("märz", "march", "mar"),
    ("april", "apr"), ("mai", "may"), ("juni", "june", "jun"), ("juli", "july", "jul"), ("august", "aug"),
    ("september", "sep", "sept"), ("oktober", "october", "okt", "oct"), ("november", "nov"),
    ("dezember", "december", "dez", "dec")]) for m in ms}
_DMY = re.compile(r"\b(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{4})\b")
_ISO = re.compile(r"\b(\d{4})-(\d{2})(?:-(\d{2}))?\b")
_MY = re.compile(r"\b(\d{1,2})/(\d{4})\b")
_DMONY = re.compile(r"\b(?:(\d{1,2})\.?\s+)?(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\.?\s+(\d{4})\b", re.I)
_NEG = re.compile(r"\b(kein|keine|keinen|keinem|keiner|keines|nicht|ohne|negativ|ausgeschlossen|verneint|"
                  r"no|not|without|negative|denies|denied|absent)\b", re.I)
_STOP = set("der die das ein eine einer eines einem den dem des und oder mit von vom zur zum im in am an auf bei "
            "für ist sind war wurde wurden hat haben sie er es patientin patient the a an of and or with in on at "
            "for is was were has have she he her his patient to by as "
            # polarity words are judged by the negation check, not used to match topics
            "positiv negativ positive negative kein keine keinen keinem keiner nicht ohne no not without "
            # generic clinical predicates: they must not make unrelated passages look topical
            "nimmt erhält erhielt zeigte zeigt zeigten zeigen besteht bestand betrug beträgt lag liegt wurde "
            "durchgeführt geplant empfohlen takes took received showed shows was were done planned".split())
_TOK = re.compile(r"[a-zäöüß0-9]+", re.I)


@dataclass
class AtomicClaim:
    text: str
    start: int | None = None
    end: int | None = None


@dataclass
class ClaimResult:
    claim: AtomicClaim
    verdict: str = "not_addressed"  # supported | contradicted | not_addressed
    needs_review: bool = True
    review_reason: str = ""
    deterministic: dict = field(default_factory=dict)
    semantic: dict = field(default_factory=dict)
    evidence: list = field(default_factory=list)  # [(Citation, p_entail, p_contra, det)]


def _num(s: str) -> str:
    return s.replace(",", ".").rstrip("0").rstrip(".") if "." in s.replace(",", ".") else s


def _unit(u: str) -> str:
    u = u.lower().replace("i.e.", "ie")
    return {"mcg": "µg", "ug": "µg"}.get(u, u)


def values(text: str) -> set[tuple[str, str]]:
    return {(_num(n), _unit(u)) for n, u in _NUM_UNIT.findall(text)}


def dates(text: str) -> set[tuple]:
    out = {(int(y), int(m), int(d)) for d, m, y in _DMY.findall(text)}
    out |= {(int(y), int(m), int(d) if d else None) for y, m, d in _ISO.findall(text)}
    out |= {(int(y), int(m), None) for m, y in _MY.findall(text) if 1 <= int(m) <= 12}
    out |= {(int(y), _MONTHS[mon.lower()], int(d) if d else None) for d, mon, y in _DMONY.findall(text)}
    return out


def negated(text: str) -> bool:
    return bool(_NEG.search(text))


def content_tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOK.findall(text) if t.lower() not in _STOP and not t.isdigit() and len(t) >= 2}


def _shared(ct: set[str], et: set[str]) -> int:
    """Claim tokens matched in the evidence, allowing German compounds/inflections by prefix ("her2" ~ "her2neu")."""
    return sum(any(e == t or (min(len(e), len(t)) >= 3 and (e.startswith(t) or t.startswith(e))) for e in et)
               for t in ct)


def atomize(text: str) -> list[AtomicClaim]:
    """Deterministic decomposition: sentences (German-abbreviation-aware Layer 1 splitter), then semicolon/bullet
    clauses, then comma-separated enumerations whose every part carries its own value ("A 5 mg, B 10 mg")."""
    out = []
    for s, e in _split_sentences(text, 0, len(text)):
        for m in re.finditer(r"[^;\n•]+", text[s:e]):
            cs, ce = s + m.start(), s + m.end()
            chunk = text[cs:ce]
            parts = [p for p in re.finditer(r"[^,]+", chunk)]
            if len(parts) > 1 and all(_NUM_UNIT.search(p.group()) for p in parts):
                spans = [(cs + p.start(), cs + p.end()) for p in parts]
            else:
                spans = [(cs, ce)]
            for a, b in spans:
                while a < b and text[a] in " \t-:": a += 1
                while b > a and text[b - 1] in " \t.": b -= 1
                if len(content_tokens(text[a:b])) >= 1 and b - a >= 6:
                    out.append(AtomicClaim(text[a:b], a, b))
    return out


def atomize_llm(text: str, llm) -> list[AtomicClaim]:
    """VeriFact's atomic-claim prompt (rag/node_parser/atomic_claims/prompts.py), structured output. Claims are not
    offset-grounded; each is still verified independently against retrieved evidence."""
    system = ("You are a physician tasked with extracting atomic claims from different text reference sources to "
              "represent the information in the text as a list of atomic claims.")
    user = ("Generate a list of unique atomic claims that can be inferred from the provided text. An atomic claim is "
            "a phrase or sentence that makes a single assertion, is indivisible, and has a subject, predicate and "
            "object. Keep the language of the text (German stays German), keep every number, unit, date and "
            "negation exactly as written, and do not add information.\n\nText:\n" + text)
    schema = {"type": "object", "properties": {"claims": {"type": "array", "items": {"type": "string"}}},
              "required": ["claims"]}
    res = llm.complete_json(system, user, schema, "atomic_claims")
    return [AtomicClaim(c.strip()) for c in res.data.get("claims", []) if isinstance(c, str) and c.strip()]


def deterministic_check(claim: str, evidence: str, document_date: str | None = None) -> dict:
    """Value/unit, date and negation agreement between a claim and one evidence text. Claim dates may also match the
    evidence document's date (VeriFact formats reference context with timestamps for the same reason)."""
    cv, ev = values(claim), values(evidence)
    cd, ed = dates(claim), dates(evidence) | dates(document_date or "")
    ct, et = content_tokens(claim), content_tokens(evidence)
    overlap = _shared(ct, et) / len(ct) if ct else 0.0
    # date match allows day-less claim dates to match any day of that month
    def date_found(d):
        return any(d[:2] == x[:2] and (d[2] is None or d[2] == x[2]) for x in ed)
    missing_v = sorted(f"{n} {u}" for n, u in cv - ev)
    conflicting_v = sorted(f"{n} {u}" for n, u in cv - ev if any(u == eu for _, eu in ev))
    missing_d = sorted(str(d) for d in cd if not date_found(d))
    # Negation is compared with the evidence clause that best matches the claim, not the whole passage
    # ("kein Anhalt für Perikarderguss, Normale LV-Funktion (EF 55%)" does not negate the EF).
    clauses = [c for c in re.split(r"[,;.](?!\d)|\s+und\s+|\s+and\s+", evidence) if c.strip()] or [evidence]
    best = max(clauses, key=lambda c: (_shared(ct, content_tokens(c)), len(cv & values(c))))
    neg_c, neg_e = negated(claim), negated(best)
    return {"overlap": round(overlap, 2), "values": "na" if not cv else ("pass" if not missing_v else "fail"),
            "missing_values": missing_v, "conflicting_values": conflicting_v,
            "dates": "na" if not cd else ("pass" if not missing_d else "fail"), "missing_dates": missing_d,
            "negation": "pass" if neg_c == neg_e else "fail"}


def _veto(d: dict) -> bool:
    return d["values"] == "fail" or d["dates"] == "fail" or d["negation"] == "fail"


def _evidence_rank(verdict: str, cit, ent, con, det: dict) -> tuple:
    """Order evidence so the passages that decided the verdict come first (UIs show only the top few)."""
    topical = det["overlap"] >= 0.5
    if verdict == "supported":
        decisive = not _veto(det) and (ent >= ENTAIL_T if ent is not None else topical)
        return (not decisive, -(ent or 0), -det["overlap"])
    if verdict == "contradicted":
        decisive = topical and (det["conflicting_values"] or det["negation"] == "fail" or (con or 0) >= CONTRA_T)
        return (not decisive, -(con or 0), -det["overlap"])
    return (0,)


def _claim_terms(claim: str) -> list[str]:
    """Search terms for one claim: the planner's lexicon terms plus the claim's own content words (VeriFact
    queries with the claim text itself; the dense/hybrid modes embed title + terms)."""
    terms = _search_terms(claim)
    return terms + sorted(t for t in content_tokens(claim) if len(t) >= 3 and t not in {x.lower() for x in terms})


class ClaimVerificationPipeline:
    """Atomize → retrieve evidence per claim → citation integrity → deterministic checks → semantic judge →
    conservative verdict. `judge` is "nli", "groq" (needs an LLM provider) or "none" (deterministic baseline)."""

    def __init__(self, executor, citation_verifier, judge: str = "nli", llm=None, k: int = 5):
        self.ex, self.cv, self.judge, self.llm, self.k = executor, citation_verifier, judge, llm, k
        self.ex.short_rows = True  # value rows (observations, medications) are evidence for claims
        self.warnings: list[str] = []
        self.judge_used = judge
        self.judge_model = None
        self._nli = None
        if judge == "nli":
            from backend.app.layer6_verification.nli import NLIUnavailable, shared_nli
            try:
                self._nli = shared_nli()
                self.judge_model = f"{self._nli.name}@{self._nli.revision}"
            except NLIUnavailable as exc:
                self.judge_used = "none"
                self.warnings.append(f"NLI judge unavailable, deterministic verification only: {exc}")
        elif judge == "groq":
            if llm is None:
                self.judge_used = "none"
                self.warnings.append("LLM judge requested but no LLM provider configured; deterministic only")
            else:
                self.judge_model = getattr(llm, "model", None)

    def evidence(self, claim: str) -> list:
        step = PlanStep.model_validate({"step_id": "verify", "title": claim, "concept": "verification",
                                        "operation": "search_text", "filters": {"search_terms": _claim_terms(claim)}})
        top, passages, _ = self.ex.search_passages(step, self.k)
        top = top + self._exact_term_passages(claim, top, passages)
        out = []
        for pid in top:
            cit = self.ex.syn.passage_citation(passages[pid])
            if self.cv.verify_citation(cit):
                out.append(cit)
            else:
                self.warnings.append(f"evidence {pid} dropped: citation integrity failed")
        return out

    def _exact_term_passages(self, claim: str, top: list[str], passages: dict, limit: int = 2) -> list[str]:
        """Lexical hits containing a claim word verbatim, appended to dense evidence: a short claim ("Patient nimmt
        ASS") embeds close to generic passages, while the medication row naming "ASS" is found lexically."""
        words = [w for w in content_tokens(claim) if len(w) >= 3]
        if not words:
            return []
        pat = re.compile(r"\b(?:" + "|".join(map(re.escape, words)) + r")\b", re.I)
        extra = [pid for pid in self.ex.last_rankings.get("lexical", [])
                 if pid not in top and pat.search(passages[pid].display_text)]
        return extra[:limit]

    def _groq(self, claim: str, cits) -> tuple[float, float]:
        ref = "\n".join(f"[{c.document_date or '?'}] {c.passage_text}" for c in cits)
        system = "You are judging whether text written about a patient is supported by information from the patient's electronic health record."
        user = ("Using the provided reference from the patient's record, determine whether the text is supported, "
                "not supported, or not addressed by the reference context. 'Supported' only if fully supported; "
                "'Not Supported' if the reference contradicts it or supports it only partially; 'Not Addressed' if "
                "the reference does not address it. The reference is the source of truth.\n"
                f'{{"text": {claim!r}, "reference": {ref!r}}}')
        schema = {"type": "object", "properties": {"verdict": {"type": "string", "enum": ["Supported", "Not Supported", "Not Addressed"]},
                                                   "reason": {"type": "string"}}, "required": ["verdict", "reason"]}
        v = self.llm.complete_json(system, user, schema, "verdict").data.get("verdict")
        return (1.0, 0.0) if v == "Supported" else (0.0, 1.0) if v == "Not Supported" else (0.0, 0.0)

    def verify_claim(self, claim: AtomicClaim) -> ClaimResult:
        r = ClaimResult(claim)
        cits = self.evidence(claim.text)
        dets = [deterministic_check(claim.text, c.passage_text, c.document_date) for c in cits]
        if self.judge_used == "nli" and cits:
            probs = self._nli.score([(c.passage_text, claim.text) for c in cits])
        else:
            probs = [(None, None, None)] * len(cits)
        r.evidence = [(c, p[0], p[2], d) for c, p, d in zip(cits, probs, dets)]
        if self.judge_used == "groq" and cits:
            try:
                ent, con = self._groq(claim.text, cits)
                r.semantic = {"judge": "groq", "model": self.judge_model, "entail": ent, "contradiction": con}
            except Exception as exc:  # noqa: BLE001 - provider errors are reported, never treated as support
                self.warnings.append(f"LLM judge failed ({type(exc).__name__}); claim left for review")
                r.semantic = {"judge": "groq", "error": type(exc).__name__}
        elif self.judge_used == "nli" and cits:
            r.semantic = {"judge": "nli", "model": self.judge_model,
                          "entail": max(p[0] for p in probs), "contradiction": max(p[2] for p in probs)}
        # Topical evidence: passages sharing at least half of the claim's content words.
        topical = [(c, e, x, d) for c, e, x, d in r.evidence if d["overlap"] >= 0.5]
        det_ok = [(c, e, x, d) for c, e, x, d in topical
                  if d["values"] != "fail" and d["dates"] != "fail" and d["negation"] == "pass"]
        det_conflict = [d for _, _, _, d in topical if d["conflicting_values"] or d["negation"] == "fail"]
        r.deterministic = {"evidence_passages": len(cits), "topical": len(topical), "consistent": len(det_ok),
                           "conflicts": det_conflict[:3]}
        sem = r.semantic
        if self.judge_used == "none" or not sem or "error" in sem:
            if det_ok and not det_conflict:
                return self._done(r, "supported", False, "deterministic: values/dates/negation found in topical evidence")
            if det_conflict and not det_ok:
                return self._done(r, "contradicted", True, "deterministic: value or negation differs from topical evidence")
            return self._done(r, "not_addressed", True, "insufficient evidence" if not det_conflict else "mixed evidence")
        if self.judge_used == "nli":
            # Deterministic checks veto (a value, date or negation mismatch in the entailing passage itself); they
            # do not require word overlap, so paraphrases ("Ejektionsfraktion" ~ "EF") can be supported.
            ent_ok = [e for c, e, x, d in r.evidence if e >= ENTAIL_T and not _veto(d)]
            contra = [x for c, e, x, d in r.evidence if x >= CONTRA_T and d["overlap"] >= 0.5]
            against = contra or det_conflict
            if ent_ok and not against:
                return self._done(r, "supported", False, "entailed by cited evidence; no value/date/negation mismatch")
            if against and not ent_ok:
                return self._done(r, "contradicted", True, "evidence contradicts the claim"
                                  + (" (NLI)" if contra else " (deterministic)"))
            if ent_ok and against:
                return self._done(r, "not_addressed", True, "conflicting evidence")
            if sem["entail"] >= ENTAIL_T:
                return self._done(r, "not_addressed", True, "model entailment vetoed by value/date/negation check")
            return self._done(r, "not_addressed", True, "insufficient evidence")
        # groq
        if sem["entail"] == 1.0 and det_ok and not det_conflict:
            return self._done(r, "supported", False, "LLM judge Supported and deterministic checks pass")
        if sem["contradiction"] == 1.0:
            return self._done(r, "contradicted", True, "LLM judge: Not Supported")
        return self._done(r, "not_addressed", True, "insufficient evidence or judge/deterministic disagreement")

    @staticmethod
    def _done(r: ClaimResult, verdict: str, review: bool, reason: str) -> ClaimResult:
        r.verdict, r.needs_review, r.review_reason = verdict, review, reason
        r.evidence.sort(key=lambda ev: _evidence_rank(verdict, *ev))
        return r

    def run(self, text: str, atomizer: str = "rules") -> tuple[list[ClaimResult], dict]:
        t0 = time.perf_counter()
        claims = atomize(text)
        if atomizer == "llm":
            if self.llm is None:
                self.warnings.append("LLM atomizer requested but no LLM configured; rule atomizer used")
            else:
                try:
                    claims = atomize_llm(text, self.llm) or claims
                except Exception as exc:  # noqa: BLE001
                    self.warnings.append(f"LLM atomizer failed ({type(exc).__name__}); rule atomizer used")
        t1 = time.perf_counter()
        results = [self.verify_claim(c) for c in claims]
        return results, {"atomize": round((t1 - t0) * 1000, 1), "verify": round((time.perf_counter() - t1) * 1000, 1)}
