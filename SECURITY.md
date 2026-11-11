# Security policy

VOC is currently a local-only prototype. Bind it to `127.0.0.1`; do not expose its port to the internet or a shared network. There is no account authentication or production tenant isolation. Collection tokens do not protect the management API.

## Protect secrets and customer data

- Model keys are stored on the backend. UI-saved keys are plaintext in the runtime data directory, not encrypted at rest by this application.
- The model settings endpoints require a loopback client, a loopback Host, same-origin browser access, and a custom header for writes. These are local safeguards, not a replacement for authentication.
- Other management endpoints are not designed to withstand hostile websites or untrusted network users. Do not browse untrusted content in the same environment while using sensitive data; public deployment requires authentication and a complete API security review.
- Keep runtime files, `.env`, credentials, private keys, backups, and customer content outside Git. Review staged files before every commit.
- Analyzing content transmits it to the model provider you configure. Verify consent, service terms, retention, and data residency.
- Reports preserve their creation-time evidence text. Deleting a recording does not necessarily remove quoted text from old reports, logs, or backups.
- Do not include actual keys, recordings, names, or contact details in issue reports.

## Reporting a vulnerability

Use the repository's **Security → Report a vulnerability** feature if available. If private reporting is unavailable, open an issue requesting a private contact without including exploit instructions, credentials, customer data, or sensitive details. Wait for a private channel before sending them.

No response-time guarantee is currently provided. Production deployments require independent review, access control, encryption, backup/retention policies, and monitoring appropriate to their environment.
