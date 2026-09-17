# Frontend

Vite + React + TypeScript SPA, served from S3 + CloudFront (not Vercel —
this project's frontend is AWS-hosted end to end, unlike the PlayIt
Next.js site).

Views: alert list (`/`), alert detail (`/alerts/:alertId`) with a live
observe/plan/act trace, confirm/reject controls, and the full audit log.
No free-text input anywhere (see
`docs/decisions/ADR-0003-preseeded-demo-no-freetext.md`) -- every action
is a button click against a fixed set of pre-seeded alerts.

## Local development

```bash
npm install
cp .env.example .env.local   # then fill in the real API Gateway URL
npm run dev
```

`VITE_API_BASE_URL` is baked in at build time (like PlayIT-nextjs's Vercel
env vars) -- changing it means rebuilding, not just redeploying static
files.

## Build

```bash
npm run build   # tsc -b && vite build -> dist/
```

`dist/` is what gets uploaded to the S3 bucket behind CloudFront (not yet
provisioned in Terraform -- infra/README.md's "Modules (planned)" list
still has `frontend/` as a TODO).
