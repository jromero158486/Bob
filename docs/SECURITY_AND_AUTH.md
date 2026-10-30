# Security boundary (demo only)

This deployment is for **synthetic data only**. It has no user authentication, no patient-level authorisation and no
verified reviewer identity. The API refuses to start unless `CLINICAL_DEMO_ONLY=1`, adds an
`X-Clinical-Demo` header to every response, and Docker Compose publishes ports on `127.0.0.1` only.

`DEMO_API_TOKEN` (optional) requires `Authorization: Bearer <token>` on `/api/*` (except `/api/health`). It is a
shared secret to prevent accidental exposure of a demo, not user authentication.

Review decisions store the `reviewer` string sent by the client. It is an unauthenticated label, not an identity.

## Required before any hospital integration
- Authentication through the hospital IdP (OIDC/SAML; e.g. Keycloak/Entra ID), short-lived tokens, MFA.
- Authorisation per patient: treatment relationship / care-team context (ELGA/e-card context in Austria), break-glass
  with justification, and enforcement in the repository layer (every `ClinicalStore` read is already patient-scoped).
- Reviewer identity from the token (not the request body); immutable, signed audit log of reads and review decisions.
- TLS everywhere, encrypted storage/backups, secrets in a vault, no public CORS, network isolation of the LLM provider
  (or an on-premise model) and a DPA/GDPR and MDR assessment before using real data.
