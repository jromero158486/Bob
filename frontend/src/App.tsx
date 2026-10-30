import { useEffect, useMemo, useState } from 'react'
import { api } from './api/client'
import type { Citation, Claim, ConflictOut, DocumentOut, PatientSummary, ReviewStatus, TaskResponse } from './api/types'

const EXAMPLES = [
  "I'm an anesthesiologist preparing this patient for surgery.",
  "I'm a pharmacist. Compare medications across admissions.",
  "I'm an oncologist. Summarize treatment history.",
  'Welche Allergien sind dokumentiert?',
  'Show the evolution of cardiac function.',
]
const STATUS_LABEL: Record<string, string> = {
  supported: 'Supported', contradicted: 'Conflict', not_addressed: 'Unverified', verification_incomplete: 'Needs review',
}

function CitationChip({ c, onOpen }: { c: Citation; onOpen: (c: Citation) => void }) {
  return (
    <button className={`cite ${c.verified ? '' : 'cite-bad'}`} title={c.passage_text} onClick={() => onOpen(c)}>
      {c.document_title} · {c.document_date ?? '?'}
    </button>
  )
}

function ClaimRow({ claim, onOpen, onReview }: { claim: Claim; onOpen: (c: Citation) => void; onReview: (k: string, s: ReviewStatus, t: string) => void }) {
  return (
    <li className={`claim claim-${claim.status} kind-${claim.kind}`}>
      <div className="claim-main">
        <span className={`badge badge-${claim.status}`}>{STATUS_LABEL[claim.status ?? 'verification_incomplete']}</span>
        {claim.kind === 'computed' && <span className="badge badge-info">calculated</span>}
        {claim.kind === 'documented_negative' && <span className="badge badge-neg">documented absent</span>}
        {claim.kind === 'not_documented' && <span className="badge badge-missing">not documented</span>}
        {claim.kind === 'change' && <span className="badge badge-info">change</span>}
        {(claim.flags ?? []).filter((f) => !['medication_list'].includes(f)).map((f) => <span key={f} className="flag">{f}</span>)}
        <span className="claim-text">{claim.text}</span>
      </div>
      {(claim.notes ?? []).length > 0 && <div className="claim-notes">{claim.notes!.join(' · ')}</div>}
      <div className="claim-cites">
        {(claim.citations ?? []).map((c) => <CitationChip key={c.passage_id + c.original_start} c={c} onOpen={onOpen} />)}
        <span className="review">
          {claim.review_status && <em>review: {claim.review_status}</em>}
          <button onClick={() => onReview(claim.claim_id, 'accepted', claim.text)}>✓</button>
          <button onClick={() => onReview(claim.claim_id, 'rejected', claim.text)}>✗</button>
          <button onClick={() => onReview(claim.claim_id, 'needs_more_info', claim.text)}>?</button>
        </span>
      </div>
    </li>
  )
}

function ConflictCard({ c, onOpen, onReview }: { c: ConflictOut; onOpen: (c: Citation) => void; onReview: (k: string, s: ReviewStatus, t: string) => void }) {
  return (
    <div className={`conflict sev-${c.severity} ${c.relevant_to_task ? '' : 'conflict-other'}`}>
      <div><span className={`badge sev-${c.severity}`}>{c.severity}</span> <strong>{c.title}</strong></div>
      <div className="claim-notes">{c.explanation}</div>
      <div className="claim-cites">
        {c.citations.map((x) => <CitationChip key={x.passage_id + x.original_start} c={x} onOpen={onOpen} />)}
        <span className="review">
          {c.review_status && <em>review: {c.review_status}</em>}
          <button onClick={() => onReview(c.conflict_id, 'accepted', c.title)}>confirm</button>
          <button onClick={() => onReview(c.conflict_id, 'rejected', c.title)}>dismiss</button>
        </span>
      </div>
    </div>
  )
}

function DocumentPanel({ doc, cite, onClose }: { doc: DocumentOut; cite: Citation; onClose: () => void }) {
  useEffect(() => { document.getElementById('hl')?.scrollIntoView({ block: 'center' }) }, [doc, cite])
  const passages = doc.passages ?? []
  return (
    <aside className="docpanel">
      <div className="docpanel-head">
        <div><strong>{doc.title}</strong> · {doc.document_date} · {doc.document_type}<br />
          <small>Original German source · document {doc.document_id} · sha256 {doc.source_sha256.slice(0, 12)}…</small></div>
        <button onClick={onClose}>Close</button>
      </div>
      <div className="quote">Cited: “{cite.quote}”</div>
      <div className="doctext">
        {passages.map((p) => (
          <p key={p.passage_id} id={p.passage_id === cite.passage_id ? 'hl' : undefined}
             className={`${p.passage_id === cite.passage_id ? 'hl' : ''} ptype-${p.passage_type}`}>{p.display_text}</p>
        ))}
      </div>
    </aside>
  )
}

export default function App() {
  const [patients, setPatients] = useState<PatientSummary[]>([])
  const [pid, setPid] = useState('')
  const [request, setRequest] = useState(EXAMPLES[0])
  const [resp, setResp] = useState<TaskResponse | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [doc, setDoc] = useState<{ d: DocumentOut; c: Citation } | null>(null)
  const [tab, setTab] = useState<'summary' | 'medications' | 'diagnoses' | 'timeline' | 'plan'>('summary')

  useEffect(() => { api.patients().then((p) => { setPatients(p); if (p[0]) setPid(p[0].patient_id) }).catch((e) => setError(String(e))) }, [])

  const run = async () => {
    setBusy(true); setError(''); setDoc(null)
    try { setResp(await api.task(pid, request)) } catch (e) { setError(String(e)) } finally { setBusy(false) }
  }
  const open = async (c: Citation) => setDoc({ d: await api.document(pid, c.document_id), c })
  const review = async (key: string, status: ReviewStatus, summary: string) => {
    await api.review(pid, key, key.startsWith('conflict') ? 'conflict' : 'claim', status, summary)
    await run()
  }
  const sections = resp?.sections ?? []
  const shown = useMemo(() => {
    if (tab === 'medications') return sections.filter((s) => s.operation.includes('medication'))
    if (tab === 'diagnoses') return sections.filter((s) => s.operation === 'list_diagnoses')
    return sections
  }, [sections, tab])

  return (
    <div className={`app ${doc ? 'with-doc' : ''}`}>
      <header>
        <h1>Clinical evidence view</h1>
        <span className="disclaimer">Synthetic data · research prototype · not a medical device</span>
      </header>
      <section className="ask">
        <select value={pid} onChange={(e) => setPid(e.target.value)} aria-label="patient">
          {patients.map((p) => <option key={p.patient_id} value={p.patient_id}>{p.patient_id} ({p.document_count} docs, {p.first_document_date}–{p.last_document_date})</option>)}
        </select>
        <textarea value={request} onChange={(e) => setRequest(e.target.value)} rows={3}
                  placeholder="Your role and task, e.g. I'm an anesthesiologist preparing this patient for surgery." />
        <button disabled={busy || !pid} onClick={run}>{busy ? 'Working…' : 'Show relevant facts'}</button>
        <div className="examples">{EXAMPLES.map((x) => <button key={x} onClick={() => setRequest(x)}>{x}</button>)}</div>
      </section>
      {error && <div className="error">{error}</div>}
      {resp && (
        <main>
          <div className="meta">
            As of <strong>{resp.as_of}</strong> · audience: {resp.plan.presentation.audience} · planner: {resp.provenance.planner}
            {resp.provenance.planner_model ? ` (${resp.provenance.planner_model})` : ''} · {resp.timings_ms.total} ms ·
            verified {resp.verification.supported}, conflicts {resp.verification.contradicted}, needs review {resp.verification.verification_incomplete}, unverified {resp.verification.not_addressed}
          </div>
          {resp.missing.length > 0 && (
            <div className="missing"><strong>Not documented:</strong> {resp.missing.map((m) => m.title).join(' · ')}</div>
          )}
          {resp.conflicts.filter((c) => c.relevant_to_task).length > 0 && (
            <div className="conflicts"><h3>Documentation conflicts relevant to this task</h3>
              {resp.conflicts.filter((c) => c.relevant_to_task).map((c) => <ConflictCard key={c.conflict_id} c={c} onOpen={open} onReview={review} />)}</div>
          )}
          <nav className="tabs">{(['summary', 'medications', 'diagnoses', 'timeline', 'plan'] as const).map((t) =>
            <button key={t} className={tab === t ? 'active' : ''} onClick={() => setTab(t)}>{t}</button>)}</nav>
          {tab === 'timeline' && (
            <ol className="timeline">{resp.timeline.map((e, i) => (
              <li key={i}><span className="tdate">{e.date}</span> <span className="tkind">{e.kind}</span> {e.label}
                {(e.citations ?? []).slice(0, 2).map((c) => <CitationChip key={c.passage_id + c.original_start} c={c} onOpen={open} />)}</li>))}</ol>
          )}
          {tab === 'plan' && <pre className="plan">{JSON.stringify(resp.plan, null, 2)}</pre>}
          {!['timeline', 'plan'].includes(tab) && shown.map((s) => (
            <section key={s.section_id} className={`section outcome-${s.outcome}`}>
              <h2>{s.title} {s.outcome !== 'answered' && <span className="badge badge-missing">{s.outcome.replace('_', ' ')}</span>}</h2>
              {s.claims.length === 0 ? <p className="claim-notes">Not documented in the available documents.</p> :
                <ul>{s.claims.map((c) => <ClaimRow key={c.claim_id} claim={c} onOpen={open} onReview={review} />)}</ul>}
            </section>
          ))}
          {tab === 'summary' && resp.conflicts.some((c) => !c.relevant_to_task) && (
            <details className="conflicts"><summary>Other documentation conflicts in this record ({resp.conflicts.filter((c) => !c.relevant_to_task).length})</summary>
              {resp.conflicts.filter((c) => !c.relevant_to_task).map((c) => <ConflictCard key={c.conflict_id} c={c} onOpen={open} onReview={review} />)}</details>
          )}
          <p className="disclaimer">{resp.disclaimer}</p>
        </main>
      )}
      {doc && <DocumentPanel doc={doc.d} cite={doc.c} onClose={() => setDoc(null)} />}
    </div>
  )
}
