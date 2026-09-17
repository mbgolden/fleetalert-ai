# Frontend

React app served from S3 + CloudFront (not Vercel — this project's frontend
is AWS-hosted end to end, unlike the PlayIt Next.js site).

Planned views: alert list, alert detail (live observe/plan/act trace),
confirm/reject controls, per-alert audit log viewer. No free-text input
anywhere (see `docs/decisions/ADR-0003-preseeded-demo-no-freetext.md`).

Scaffolding (Vite/React, package.json, etc.) not yet created.
