# Two-minute demo video script (what works and what does not)

Recorded on the published app (https://screenshot-stitchery-studio.lovable.app, backend `b814c70`). Keep to 2:00.

| Time | Screen | Voice-over |
|---|---|---|
| 0:00–0:12 | Live app, **Live backend** badge, patient overview | "A patient's history is spread across German letters, reports and medication lists. Lumen Clinical shows each clinician what their task needs, linked to the exact source passage." |
| 0:12–0:35 | S1: role *Anaesthetist*, paste the pre-op situation; result in about 2 s | "Any role, any task, in English or German. For the anaesthetist: Thrombo ASS 100 mg in the morning, the contrast allergy with its reactions, and the 2015 echo, with no clicking." |
| 0:35–0:47 | Click a citation → German letter with the highlighted span | "Every fact links to the original document. The highlight uses exact character offsets." |
| 0:47–1:05 | S3: *General practitioner*, diabetes review; weight 78 → 67 → 66 kg; **Medications** candesartan 2015 vs 2016; **Timeline** | "Same patient, different task: diabetes drugs with doses, the latest HbA1c and its date, and the weight loss over a year. Changes over time are shown as changes, not as errors." |
| 1:05–1:20 | S4: **Not documented: Kidney function**; **Potential conflicts** (BMI vs height/weight, two admission dates) | "Lumen separates 'not documented' from 'documented absent', and flags passages that cannot all be true, with links to each passage." |
| 1:20–1:40 | **Review**: open the BP discrepancy, inspect both sources, Approve with a comment, refresh → "Human reviewed · approved" | "The AI flags; the clinician inspects the evidence and records the decision. It is stored separately and never changes the original documents." |
| 1:40–2:00 | README metrics table | "What does not work yet: on the official 15 questions we get 12 fully correct and 3 partial. A false 'atrial fibrillation' diagnosis is extracted from a question in a Holter request. On 20 new questions, 5 were fully correct and 11 partial: false premises are not corrected, and some missing items are not flagged. Escalated reviews are not yet shown after a refresh. Synthetic data only; it supports clinicians, it does not replace them." |

Do not demonstrate Escalate or Correct live: in the deployed version they show as unreviewed after a refresh (fix
prepared in Bob PR #4 / screenshot-match PR #3, not deployed). Recording of the review flow: in the team's
submission folder.
