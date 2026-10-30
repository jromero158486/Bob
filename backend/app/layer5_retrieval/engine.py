"""Layer 5: execute a TaskPlan against the store (structured-first, exhaustive), add lexical
retrieval with reciprocal rank fusion, and synthesise evidence-linked claims.

No free-text generation here: every claim is rendered from typed facts and carries citations.
"""
from __future__ import annotations

import hashlib
import re
from collections import OrderedDict
from datetime import date

from backend.app.api.schemas import Citation, Claim, MissingItem, Section, TimelineEvent
from backend.app.layer2_extraction.contracts import ClinicalFact
from backend.app.layer3_store.repository import ClinicalStore
from backend.app.layer4_planner.contracts import PlanStep, TaskPlan

OBS_DISPLAY = {"body_height": "Height", "body_weight": "Weight", "bmi": "BMI", "body_temperature": "Temperature",
               "heart_rate": "Heart rate", "blood_pressure": "Blood pressure", "lvef": "LV ejection fraction",
               "hba1c": "HbA1c", "ki67": "Ki-67", "estrogen_receptor": "Oestrogen receptor",
               "progesterone_receptor": "Progesterone receptor", "hormone_receptor": "Hormone receptor",
               "her2": "HER2", "allred_score": "Allred score", "tnm_classification": "TNM", "birads": "BI-RADS",
               "stenosis_degree": "Stenosis", "lesion_size": "Lesion size", "mmse": "MMSE", "tapse": "TAPSE",
               "creatinine": "Creatinine", "egfr": "eGFR"}
VALUE_DE = {"positiv": "positive", "negativ": "negative"}
SIDE = {"left": "left", "right": "right", "bilateral": "both sides"}


def _cid(*parts) -> str:
    return "claim:" + hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:16]


def _fmt_num(x: float | None) -> str:
    if x is None:
        return "?"
    return {0.5: "½", 0.25: "¼"}.get(x, f"{x:g}")


def _schedule(s) -> str | None:
    if s is None:
        return None
    vals = [s.morning, s.noon, s.evening]
    if s.night:
        vals.append(s.night)
    return "-".join(_fmt_num(v or 0) for v in vals)


def _fdate(f: ClinicalFact) -> str | None:
    return f.event_date.value if f.event_date else f.document_date


class Synthesizer:
    def __init__(self, store: ClinicalStore, patient_id: str):
        self.store, self.patient_id = store, patient_id
        self.docs = {d.source_id: d for d in store.documents(patient_id)}
        self._passages: dict[str, object] = {}

    def citations(self, facts: list[ClinicalFact]) -> list[Citation]:
        spans = []
        for f in facts:
            ev = next((e for e in f.evidence if e.role == "mention"), f.evidence[0])
            spans.append(ev)
        missing = {e.passage_id for e in spans} - set(self._passages)
        self._passages.update(self.store.passages(self.patient_id, missing))
        out, seen = [], set()
        for e in spans:
            if (e.passage_id, e.original_start) in seen:
                continue
            seen.add((e.passage_id, e.original_start))
            d, p = self.docs.get(e.source_id), self._passages.get(e.passage_id)
            out.append(Citation(document_id=e.document_id, document_title=d.title if d else "?",
                                document_date=d.document_date if d else None, passage_id=e.passage_id,
                                quote=e.display_text, passage_text=p.display_text if p else e.display_text,
                                original_start=e.original_start, original_end=e.original_end))
        return sorted(out, key=lambda c: (c.document_date or "", c.document_id), reverse=True)

    def passage_citation(self, p) -> Citation:
        d = self.docs.get(p.source_id)
        return Citation(document_id=d.document_id if d else "?", document_title=d.title if d else "?",
                        document_date=d.document_date if d else None, passage_id=p.passage_id, quote=p.display_text,
                        passage_text=p.display_text, original_start=p.original_start, original_end=p.original_end)

    # ----- rendering -----
    def med_claim(self, group: list[ClinicalFact], step: PlanStep) -> Claim:
        f = group[0]
        d = f.details
        parts = [d.drug_text + (f" ({d.ingredient})" if d.ingredient and d.ingredient.casefold() not in d.drug_text.casefold() else "")]
        if d.strength_value is not None:
            parts.append(f"{d.strength_value:g} {d.strength_unit}")
        if d.form and d.form.casefold() not in d.drug_text.casefold():
            parts.append(d.form)
        if d.route:
            parts.append({"s.c.": "subcutaneous", "oral": "oral", "i.v.": "intravenous"}.get(d.route, d.route))
        sched = _schedule(d.schedule)
        if sched:
            parts.append(sched + (" (morning-noon-evening)" if not d.schedule.night else " (morning-noon-evening-night)"))
        if d.frequency_text:
            parts.append(d.frequency_text)
        flags = [] if d.statement == "medication_list" else [d.statement]
        return Claim(claim_id=_cid(step.concept, *sorted(x.fact_id for x in group)), text=", ".join(parts),
                     original_text=f.label, kind="fact", date=max((_fdate(x) or "") for x in group) or None,
                     codes=sorted({c.code for x in group for c in x.codings}), flags=flags,
                     fact_ids=[x.fact_id for x in group], citations=self.citations(group))

    def obs_claim(self, group: list[ClinicalFact], step: PlanStep) -> Claim:
        f = group[0]
        d = f.details
        name = OBS_DISPLAY.get(d.name, d.name_text)
        value = " ".join(VALUE_DE.get(w, w) for w in d.value_text.split())
        if d.unit and d.unit not in value and d.unit not in ("/30",) and d.name not in ("blood_pressure",):
            value += f" {d.unit}" if d.unit not in ("%", "/min") else d.unit
        extra = [x for x in (d.qualifier, SIDE.get(d.laterality) if d.laterality else None) if x]
        dt = _fdate(f)
        text = f"{name}: {value}" + (f" ({', '.join(extra)})" if extra else "") + (f" — {dt}" if dt else "")
        return Claim(claim_id=_cid(step.concept, *sorted(x.fact_id for x in group)), text=text, original_text=f.label,
                     kind="fact", date=dt, codes=sorted({c.code for x in group for c in x.codings}),
                     fact_ids=[x.fact_id for x in group], citations=self.citations(group))

    def dx_claim(self, group: list[ClinicalFact], step: PlanStep) -> Claim:
        f = group[0]
        a = f.assertion
        flags = []
        if a.negated:
            flags.append("documented as absent")
        if a.certainty == "possible":
            flags.append("suspected")
        if a.temporality == "historical":
            flags.append("history of")
        if a.experiencer == "family":
            flags.append("family history")
        disp = f.codings[0].display if f.codings else None
        side = SIDE.get(f.details.laterality) if f.details.laterality else None
        text = (disp or f.details.text) + (f" ({side})" if side else "")
        if disp and disp.casefold() not in f.label.casefold():
            text += f" — “{f.label}”"
        dates = sorted({x.event_date.value for x in group if x.event_date})
        return Claim(claim_id=_cid(step.concept, *sorted(x.fact_id for x in group)), text=text, original_text=f.label,
                     kind="documented_negative" if a.negated else "fact", date=dates[-1] if dates else None,
                     codes=sorted({c.code for x in group for c in x.codings}), flags=flags,
                     fact_ids=[x.fact_id for x in group], citations=self.citations(group))

    def generic_claim(self, group: list[ClinicalFact], step: PlanStep, text: str, kind: str = "fact",
                      flags=None, dt=None) -> Claim:
        return Claim(claim_id=_cid(step.concept, *sorted(x.fact_id for x in group)), text=text, original_text=group[0].label,
                     kind=kind, date=dt, flags=flags or [], codes=sorted({c.code for x in group for c in x.codings}),
                     fact_ids=[x.fact_id for x in group], citations=self.citations(group))


def _group(facts: list[ClinicalFact], key) -> list[list[ClinicalFact]]:
    groups: OrderedDict = OrderedDict()
    for f in facts:
        groups.setdefault(key(f), []).append(f)
    return list(groups.values())


def _med_sig(f: ClinicalFact):
    d = f.details
    s = d.schedule
    sched = (s.morning or 0, s.noon or 0, s.evening or 0, s.night or 0) if s else None
    return ((d.ingredient or d.drug_text).casefold(), d.strength_value, sched, (d.frequency_text or "").split(" ")[0])


def _codes_ok(f: ClinicalFact, prefixes: list[str]) -> bool:
    return not prefixes or any(c.code.startswith(tuple(prefixes)) for c in f.codings)


class Executor:
    def __init__(self, store: ClinicalStore, patient_id: str, as_of: str):
        self.store, self.pid, self.as_of = store, patient_id, as_of
        self.syn = Synthesizer(store, patient_id)
        self.all_facts = store.facts(patient_id, as_of=as_of)

    def run(self, plan: TaskPlan) -> tuple[list[Section], list[MissingItem]]:
        sections, missing = [], []
        for step in plan.steps:
            claims = getattr(self, "op_" + step.operation)(step)
            if not claims:
                outcome = "not_documented"
                if step.required:
                    missing.append(MissingItem(step_id=step.step_id, title=step.title,
                                               message=f"Not documented in the {len(self.syn.docs)} available documents "
                                                       f"(as of {self.as_of})."))
                else:
                    continue
            elif all(c.kind == "documented_negative" for c in claims):
                outcome = "documented_negative"
            else:
                outcome = "answered"
            sections.append(Section(section_id=f"sec-{step.step_id}", step_id=step.step_id, title=step.title,
                                    concept=step.concept, operation=step.operation, outcome=outcome, claims=claims))
        return sections, missing

    def _facts(self, ftype: str) -> list[ClinicalFact]:
        return [f for f in self.all_facts if f.fact_type == ftype]

    # ----- operations -----
    def op_list_medications(self, step: PlanStep) -> list[Claim]:
        prefixes = step.filters.code_prefixes
        meds = [f for f in self._facts("medication") if _codes_ok(f, prefixes) and not f.assertion.negated]
        current = self.store.medication_list(self.pid, self.as_of)
        if step.temporal.mode in ("current", "latest") and current:
            doc, latest = current
            chosen = [f for f in latest if _codes_ok(f, prefixes)]
            if not chosen:
                return []
            # Merge identical statements (same drug, strength, schedule) from earlier documents as extra citations.
            sigs = {_med_sig(f): [f] for f in chosen}
            for f in meds:
                if f not in chosen and _med_sig(f) in sigs:
                    sigs[_med_sig(f)].append(f)
                elif f not in chosen and f.details.statement != "medication_list":
                    k = next((s for s in sigs if s[0] == _med_sig(f)[0] and _med_sig(f)[1] in (None, s[1])
                              and (_med_sig(f)[2] in (None, s[2]))), None)
                    if k is not None:
                        sigs[k].append(f)
            claims = [self.syn.med_claim(g, step) for g in sigs.values()]
            for c in claims:
                c.notes.append(f"Current per medication list of {doc.document_date} ({doc.title})")
            return claims
        groups = _group(sorted(meds, key=lambda f: f.document_date or "", reverse=True), _med_sig)
        return [self.syn.med_claim(g, step) for g in groups]

    def op_compare_medication_lists(self, step: PlanStep) -> list[Claim]:
        lists = self.store.medication_lists(self.pid, self.as_of)
        claims = []
        for (d1, a), (d2, b) in zip(lists, lists[1:]):
            for ch in ClinicalStore.compare_medication_lists(a, b):
                if ch["change"] == "unchanged":
                    continue
                facts = [x for x in (ch.get("before"), ch.get("after")) if x]
                desc = {"added": "added", "removed": "no longer listed", "changed": "changed"}[ch["change"]]
                before = self.syn.med_claim([ch["before"]], step).text if ch.get("before") else None
                after = self.syn.med_claim([ch["after"]], step).text if ch.get("after") else None
                text = f"{ch['drug']}: {desc} between {d1.document_date} and {d2.document_date}" + \
                       (f" — before: {before}" if before else "") + (f"; after: {after}" if after else "")
                claims.append(self.syn.generic_claim(facts, step, text, kind="change", dt=d2.document_date,
                                                     flags=["change over time (not a contradiction)"]))
            if not any(c.date == d2.document_date for c in claims):
                claims.append(self.syn.generic_claim(b, step, f"No changes between the medication lists of "
                                                              f"{d1.document_date} and {d2.document_date}", kind="change",
                                                     dt=d2.document_date))
        return claims

    def op_list_diagnoses(self, step: PlanStep) -> list[Claim]:
        prefixes = step.filters.code_prefixes
        dx = [f for f in self._facts("diagnosis") if not f.assertion.question and _codes_ok(f, prefixes)]
        if not prefixes:
            dx = [f for f in dx if f.details.listed_in_diagnosis_section or f.codings]
        key = lambda f: ((f.codings[0].code if f.codings else f.details.text.casefold()), f.assertion.negated,  # noqa: E731
                         f.assertion.certainty, f.assertion.temporality, f.assertion.experiencer, f.details.laterality)
        groups = _group(sorted(dx, key=lambda f: (not f.details.listed_in_diagnosis_section, f.document_date or "")), key)
        groups.sort(key=lambda g: (g[0].assertion.negated, -max(len(g), 1)))
        return [self.syn.dx_claim(g, step) for g in groups]

    def op_list_allergies(self, step: PlanStep) -> list[Claim]:
        al = self._facts("allergy")
        groups = _group(al, lambda f: ((f.details.substance or f.details.substance_text).casefold(), f.assertion.negated))
        claims = []
        for g in groups:
            f = max(g, key=lambda x: len(x.details.reactions))
            d = f.details
            if f.assertion.negated:
                claims.append(self.syn.generic_claim(g, step, "No known allergies documented (explicit statement)",
                                                     kind="documented_negative"))
                continue
            text = (d.substance or d.substance_text) + " allergy"
            reactions = sorted({r for x in g for r in x.details.reactions})
            if reactions:
                text += f" (reactions: {', '.join(reactions)})"
            claims.append(self.syn.generic_claim(g, step, text, dt=None))
        return claims

    def op_get_observations(self, step: PlanStep) -> list[Claim]:
        claims = []
        for name in step.filters.observation_names:
            series = self.store.observation_series(self.pid, name, self.as_of)
            if not series:
                continue
            key = lambda f: (f.details.value_text.replace(" ", "").replace(",", "."), f.details.qualifier,  # noqa: E731
                             f.details.laterality, (_fdate(f) or "")[:7])
            groups = _group(series, key)
            if step.temporal.mode == "latest":
                latest = groups[-1]
                claims.append(self.syn.obs_claim(latest, step))
                if len(groups) > 1:
                    claims[-1].notes.append("Latest documented value; earlier values: " +
                                            "; ".join(f"{g[0].details.value_text} ({_fdate(g[0])})" for g in groups[:-1]))
                else:
                    claims[-1].notes.append("Only documented value")
            else:
                claims += [self.syn.obs_claim(g, step) for g in groups]
            numeric = [g for g in groups if g[0].details.value_num is not None and not g[0].details.qualifier
                       and _fdate(g[0])]
            if step.temporal.mode == "series" and len(numeric) >= 2 and name in ("body_weight", "lvef", "hba1c", "bmi"):
                first, last = numeric[0], numeric[-1]
                delta = last[0].details.value_num - first[0].details.value_num
                unit = first[0].details.unit or ""
                text = (f"Change in {OBS_DISPLAY.get(name, name)}: {delta:+g} {unit} from {first[0].details.value_num:g} "
                        f"({_fdate(first[0])}) to {last[0].details.value_num:g} ({_fdate(last[0])}) — calculated")
                claims.append(self.syn.generic_claim(first + last, step, text, kind="computed", dt=_fdate(last[0])))
        return claims

    def op_list_procedures(self, step: PlanStep) -> list[Claim]:
        pr = [f for f in self._facts("procedure") if not f.assertion.question]
        if step.filters.procedure_names:
            pr = [f for f in pr if f.label in step.filters.procedure_names]
        if step.filters.statuses:
            pr = [f for f in pr if f.details.status in step.filters.statuses]
        groups = _group(pr, lambda f: (f.label, f.details.status, f.event_date.value if f.event_date else None,
                                       f.document_id if not f.event_date else ""))
        claims = []
        for g in groups:
            f = g[0]
            dt = f.event_date.value if f.event_date else None
            text = f"{f.label} — {f.details.status}" + (f" ({dt})" if dt else f" (documented {f.document_date})")
            claims.append(self.syn.generic_claim(g, step, text, dt=dt or f.document_date, flags=[f.details.status]))
        return sorted(claims, key=lambda c: c.date or "", reverse=True)

    def op_list_recommendations(self, step: PlanStep) -> list[Claim]:
        recs = self._facts("recommendation")
        claims = []
        for g in _group(recs, lambda f: re.sub(r"\W+", " ", f.label.casefold())):
            f = g[0]
            due = ""
            if f.event_date:
                due = f" — due {f.event_date.value}" + (" (calculated from the document date)"
                                                        if f.event_date.source == "relative_to_document" else "")
            action = f"{f.details.action}: " if f.details.action else ""
            claims.append(self.syn.generic_claim(g, step, f"{action}“{f.label}”{due}", dt=f.document_date,
                                                 flags=[f"recommended {f.document_date}"]))
        return sorted(claims, key=lambda c: c.date or "")

    def op_check_followups(self, step: PlanStep) -> list[Claim]:
        recs = [f for f in self._facts("recommendation") if f.details.action]
        procs = [f for f in self._facts("procedure") if f.details.status == "performed"]
        claims = []
        for r in recs:
            for action in [a.strip() for a in r.details.action.split(",")]:
                done = [p for p in procs if p.label == action and (p.document_date or "") > (r.document_date or "")
                        and p.document_id != r.document_id]
                if done:
                    claims.append(self.syn.generic_claim([r] + done, step,
                                                         f"{action} (recommended {r.document_date}): documented as performed "
                                                         f"{', '.join(sorted({_fdate(p) or '?' for p in done}))}"))
                else:
                    claims.append(self.syn.generic_claim([r], step,
                                                         f"{action} (recommended {r.document_date}): no later document "
                                                         f"records that it took place", kind="not_documented",
                                                         flags=["open / not documented"]))
        return claims

    def op_list_encounters(self, step: PlanStep) -> list[Claim]:
        ev = [f for f in self._facts("encounter_event") if f.details.event != "case_id"]
        claims = []
        for g in _group(ev, lambda f: (f.details.event, f.event_date.value if f.event_date else f.details.date_text)):
            f = g[0]
            flags = [] if f.details.date_valid else ["invalid date in source"]
            if f.assertion.temporality == "future":
                flags.append("planned")
            claims.append(self.syn.generic_claim(g, step, f"{f.details.event.replace('_', ' ').capitalize()}: "
                                                          f"{f.event_date.value if f.event_date else f.details.date_text}",
                                                 dt=f.event_date.value if f.event_date else None, flags=flags))
        return sorted(claims, key=lambda c: c.date or "")

    def op_demographics(self, step: PlanStep) -> list[Claim]:
        dem = self._facts("demographic")
        dob = [f for f in dem if f.details.attribute == "birth_date"]
        claims = []
        if dob:
            v = dob[0].details.value
            claims.append(self.syn.generic_claim(dob, step, f"Date of birth: {v}"))
            try:
                b, ref = date.fromisoformat(v), date.fromisoformat(self.as_of)
                age = ref.year - b.year - ((ref.month, ref.day) < (b.month, b.day))
                claims.append(self.syn.generic_claim(dob[:1], step, f"Age: {age} years on {self.as_of} — calculated",
                                                     kind="computed", dt=self.as_of))
            except (TypeError, ValueError):
                pass
        return claims

    def op_search_text(self, step: PlanStep, k: int = 6) -> list[Claim]:
        terms = step.filters.search_terms
        if not terms:
            return []
        scores: dict[str, float] = {}
        passages = {}
        for t in terms:  # reciprocal rank fusion over per-term rankings (Cormack et al., 2009)
            for rank, (p, _) in enumerate(self.store.search_passages(self.pid, t, limit=30)):
                if p.passage_type in ("section_heading", "table_header") or len(p.display_text) < 25:
                    continue
                d = self.syn.docs.get(p.source_id)
                if d is None or (d.document_date or "") > self.as_of:
                    continue
                passages[p.passage_id] = p
                scores[p.passage_id] = scores.get(p.passage_id, 0) + 1 / (60 + rank)
        top = sorted(scores, key=lambda i: -scores[i])[:k]
        claims = []
        for pid in top:
            p = passages[pid]
            cit = self.syn.passage_citation(p)
            claims.append(Claim(claim_id=_cid(step.concept, pid), text=p.display_text, original_text=p.display_text,
                                kind="passage", date=cit.document_date, citations=[cit],
                                notes=["Original passage retrieved by lexical search (not a structured fact)"]))
        return claims


def build_timeline(store: ClinicalStore, patient_id: str, as_of: str, syn: Synthesizer) -> list[TimelineEvent]:
    events = []
    for d in store.documents(patient_id):
        if d.document_date and d.document_date <= as_of:
            events.append(TimelineEvent(date=d.document_date, kind="document", label=d.title))
    for f in store.facts(patient_id, types=["encounter_event", "procedure"], as_of=as_of):
        if not f.event_date or f.assertion.question:
            continue
        if f.fact_type == "encounter_event" and f.details.event == "case_id":
            continue
        label = (f"{f.details.event.replace('_', ' ')}" if f.fact_type == "encounter_event"
                 else f"{f.label} ({f.details.status})")
        events.append(TimelineEvent(date=f.event_date.value, kind=f.fact_type, label=label, citations=syn.citations([f])))
    merged: OrderedDict = OrderedDict()
    for e in sorted(events, key=lambda e: e.date):
        k = (e.date, e.kind, e.label)
        if k in merged:
            merged[k].citations += [c for c in e.citations if c not in merged[k].citations]
        else:
            merged[k] = e
    return list(merged.values())
