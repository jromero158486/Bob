# Limitations

- One synthetic patient (8 documents) from IBM; extra patients are author-written synthetic letters. No real data.
- Lexicons and rules were tuned while looking at the IBM questions; benchmark numbers are not held-out.
- Automatic benchmark checks are string matches, not independent clinical review.
- GERNERMED++ licence is unspecified; it runs only in a separate environment and is not shipped.
- No GPU on the development VM (8 CPU cores, 31 GB RAM); large models run on CPU or the event A5000.
- No authentication / authorisation; demo-only (docs/SECURITY_AND_AUTH.md).
- Restricted datasets (CARDIO:DE, FactEHR, ArchEHR-QA, MedAlign, MIMIC) were not used.
