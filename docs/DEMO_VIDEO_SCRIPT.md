# Two-minute demo video script (what works and what does not)

Recorded on the published app (https://screenshot-stitchery-studio.lovable.app, backend `b814c70`). Keep to 2:00.

| Time | Screen | Voice-over |
|---|---|---|
| 0:00–0:12 | Live app, **Live backend** badge, patient overview | "A patient's history is spread across German letters, reports and medication lists. Lumen Clinical shows each clinician what their task needs, linked to the exact source passage." |
| 0:12–0:35 | S1: role *Anaesthetist*, paste the pre-op situation; result in about 2 s | "Any role, any task, in English or German. For the anaesthetist: Thrombo ASS 100 mg in the morning, the contrast allergy with its reactions, and the 2015 echo, with no clicking." |
| 0:35–0:47 | Click a citation → German letter with the highlighted span | "Every fact links to the original document. The highlight uses exact character offsets." |
| 0:47–1:05 | S3: *General practitioner*, diabetes review; weight 78 → 67 → 66 kg; **Medications** candesartan 2015 vs 2016; **Timeline** | "Same patient, different task: diabetes drugs with doses, the latest HbA1c and its date, and the weight loss over a year. Changes over time are shown as changes, not as errors." |
| 1:05–1:20 | S4: **Not documented: Kidney function**; **Potential conflicts** (BMI vs height/weight, two admission dates) | "Lumen separates 'not documented' from 'documented absent', and flags passages that cannot all be true, with links to each passage." |
| 1:20–1:45 | **Review**: open *Left and right both documented for the same finding* (60% carotid stenosis), click both source passages (one sentence says right, the overall assessment and the radiology report say left), Approve with the comment "Confirmed documentation error: stenosis is left-sided per radiology report", refresh → "Human reviewed · approved" | "The AI flags a real inconsistency: one letter puts the carotid stenosis on the right, everything else on the left. The clinician checks both passages and records the decision. It is stored separately; the original documents are never changed." |
| 1:45–2:00 | README metrics table | "Limits: 12 of 15 official answers are complete and 3 are partial. One false finding, atrial fibrillation, comes from a question line in a report. Results on new questions are preliminary. Synthetic data only; Lumen supports clinicians, it doesn't replace them." |

Use the carotid left/right item (still pending on the live app). Backup if it was already reviewed: *Inconsistent admission date in one document* (10/04/2016 vs 12.04.2016). Do not use the 140/90 vs 145/90 mmHg item: it is a small measurement difference, which the IBM README counts as a false alarm. Do not demonstrate Escalate or Correct live: in the deployed version they show as unreviewed after a refresh (fix
prepared in Bob PR #4 / screenshot-match PR #3, not deployed). 