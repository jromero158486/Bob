// Stable API types generated from the FastAPI OpenAPI schema (docs/openapi.json).
// Regenerate: python -m backend.app.tools.gen_ts_types
export type {
  TaskResponse, TaskPlan, Section, Claim, Citation, ConflictOut, MissingItem, TimelineEvent, PatientSummary,
  DocumentOut, PassageOut, TaskRequest, ReviewUpdate,
} from './schema'
import type { ReviewUpdate } from './schema'
export type ReviewStatus = ReviewUpdate['status']
