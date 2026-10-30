import type { DocumentOut, PatientSummary, ReviewStatus, TaskResponse } from './types'

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? '/api'

async function j<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${BASE}${path}`, { headers: { 'Content-Type': 'application/json' }, ...init })
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`)
  return r.json() as Promise<T>
}

export const api = {
  health: () => j<{ status: string; llm_configured: boolean; database: string }>('/health'),
  patients: () => j<PatientSummary[]>('/patients'),
  document: (pid: string, docId: string) => j<DocumentOut>(`/patients/${encodeURIComponent(pid)}/documents/${encodeURIComponent(docId)}`),
  task: (patient_id: string, request: string) =>
    j<TaskResponse>('/tasks', { method: 'POST', body: JSON.stringify({ patient_id, request }) }),
  review: (pid: string, item_key: string, item_type: 'claim' | 'conflict', status: ReviewStatus, summary: string) =>
    j<{ status: string }>(`/patients/${encodeURIComponent(pid)}/review`, {
      method: 'POST', body: JSON.stringify({ item_key, item_type, status, summary, reviewer: 'demo-clinician' }),
    }),
}
