# CLAUDE.md — AIApply Project Memory

This file is read by Claude at the start of every conversation to restore full context.

---

## What This Project Is

**AIApply** — an AI-powered job application platform built for personal use first (spouse's job search), with a plan to turn it into a SaaS product later.

**Core flow**: Upload CV → Set career goals → AI finds matching jobs → AI tailors CV per company → User reviews → Applies

**Key differentiator vs aiapply.co**: Quality over quantity. 20 targeted applications with company-specific CVs, not 200 generic blasts. Career goal alignment built in.

---

## Owner Context

- **Who uses it**: Spouse is the primary user right now (job searching)
- **Developer**: AWS Solutions Architect certified. Comfortable with frontend (React/Next.js). Python/AI agents are newer territory.
- **Budget**: As cheap as possible. Currently ~$5–7/month (just Claude API — everything else is AWS free tier)
- **Goal**: Personal tool now → SaaS later
- **Auto-apply mode**: Review-first by default (user approves each tailored CV before submission). Toggle to full auto in settings.
- **Claude API keys**: Already set up and working

---

## What Has Been Built (Phase 1 + Phase 2 — Complete)

### Frontend — Next.js 15 + TypeScript + shadcn/ui + Tailwind
Located at: `/Users/l.bagga/Documents/AIApply/frontend/`

| Page | File | Status |
|------|------|--------|
| Landing page | `app/page.tsx` | ✅ Done |
| Sign up | `app/signup/page.tsx` | ✅ Done |
| Log in | `app/login/page.tsx` | ✅ Done |
| Onboarding (CV upload + career goals) | `app/onboarding/page.tsx` | ✅ Done |
| Dashboard (Kanban board) | `app/dashboard/page.tsx` | ✅ Done |
| Application detail + CV diff | `app/applications/[id]/page.tsx` | ✅ Done |
| Settings (goals, scanning, costs, danger zone) | `app/settings/page.tsx` | ✅ Done |

Key support files:
- `lib/auth.ts` — Amplify/Cognito helpers (signIn, signUp, getAuthToken)
- `lib/api.ts` — API client (full suite of functions, see API section)
- `components/amplify-provider.tsx` — client-side Cognito config wrapper
- `components/ui/` — shadcn/ui components (button, card, badge, dialog, tabs, dropdown-menu, etc.)
- `app/applications/application-detail-client.tsx` — full application detail client component

### Dashboard Features (all built)
- **Kanban board** with columns: 🎯 Matched → ✏️ Tailoring → 👁 Review → ✅ Submitted → 💼 Interview → 🎉 Offer → ❌ Rejected
- **"Matched" column** — human checkpoint: user explicitly clicks "Tailor CV" for jobs they want to pursue (prevents wasting Claude Sonnet tokens)
- **Source badge** — shows LinkedIn/Indeed on each card
- **Last scanned time** — inline badge shows "Last scanned X ago"
- **Scan for New Jobs** button — triggers job scout on demand
- **Manual application creation** — add jobs manually with URL, title, company, status
- **Status update dropdown** — move any application between stages from detail page
- **Application deletion** — "Not Interested" button removes from pipeline
- **Dark mode** — full dark/light toggle with persisted theme preference

### Application Detail Features (all built)
- CV diff view — changes highlighted (green=added, yellow=modified, red=removed)
- Job description tab (for matched jobs)
- "Why You" tab (match reasoning from Claude)
- Cover letter tab with **Copy** button
- Tailored CV tab with **Copy** button (converts JSON to formatted plain text)
- ATS score before/after
- Personal notes — free-text notes per application, saved to DynamoDB
- Status update dropdown in header
- "Approve CV" → status becomes "submitted"
- "Tailor CV" button for matched applications

### Settings Features (all built)
- Career goals editor (roles, industries, location, salary, experience level)
- Job Scout card — Scan for New Jobs button + last scanned time
- Job window hours — configurable how many hours back to scan
- User-defined scoring thresholds — custom match/alignment score cutoffs
- Application mode toggle (review-first vs auto)
- **Usage & Costs** — per-model breakdown (Haiku for scanning, Sonnet for tailoring), token counts, USD cost
- **Danger Zone** — Delete Account with full data wipe (2-step confirmation: must type "DELETE")

### Backend — Python 3.12 Lambda functions
Located at: `/Users/l.bagga/Documents/AIApply/backend/lambdas/`

| Lambda | Trigger | What it does |
|--------|---------|-------------|
| `cv_analyst` | S3 ObjectCreated | Parses PDF/DOCX → extracts structured data via Claude Sonnet |
| `api` | API Gateway HTTP | Routes all `/api/*` REST requests |
| `job_scout` | SQS | Scrapes LinkedIn/Indeed (JobSpy) → scores matches via Claude Haiku → saves as "matched" status |
| `cv_tailor` | SQS | Rewrites CV per company → diff + cover letter via Claude Sonnet |

**API routes in `api/handler.py`:**

| Method | Path | What it does |
|--------|------|-------------|
| POST | `/api/upload-url` | Presigned S3 URL for CV upload |
| GET | `/api/profile` | Get user's CVs |
| GET/POST | `/api/career-goals` | Get/save career goals + last scanned time + usage stats |
| GET | `/api/applications?limit=N` | List applications (paginated, default limit=100, BatchGetItem for job URLs) |
| POST | `/api/applications/approve` | Approve CV → status "submitted" |
| DELETE | `/api/applications?applicationId=X` | Delete an application |
| GET | `/api/applications/tailored-cv` | Fetch tailored CV JSON from S3 |
| POST | `/api/applications/tailor` | Queue a matched application for CV tailoring |
| PUT | `/api/applications/status` | Update application status |
| POST | `/api/applications/notes` | Save personal notes on an application |
| POST | `/api/applications/manual` | Create a manual application entry |
| POST | `/api/jobs/scan` | Trigger job scout for current user |
| DELETE | `/api/account` | Full account wipe (DynamoDB + S3 objects) |

### Infrastructure — Terraform
Located at: `/Users/l.bagga/Documents/AIApply/infrastructure/terraform/`

| Module | What it creates |
|--------|----------------|
| `modules/storage` | S3 (CV bucket) + 4 DynamoDB tables |
| `modules/cdn` | S3 (frontend) + CloudFront distribution |
| `modules/auth` | Cognito User Pool + App Client |
| `modules/queue` | SQS job-scout + cv-tailor queues (with DLQs) |
| `modules/api` | Lambda functions + API Gateway HTTP API + IAM roles (incl. BatchGetItem) + SSM Parameter |
| `modules/monitoring` | CloudWatch log groups |
| `modules/cicd` | GitHub OIDC identity provider + IAM role for GitHub Actions |

Environment: `infrastructure/terraform/environments/dev/`

**Terraform has been applied against real AWS** — all resources exist and are live.

### CI/CD — GitHub Actions
Located at: `/Users/l.bagga/Documents/AIApply/.github/workflows/`

| Workflow | Trigger | Does |
|----------|---------|------|
| `ci.yml` | Every PR | Lint frontend (ESLint) + lint backend (Ruff) + build check |
| `deploy.yml` | Push to main | Deploy Lambda zips + S3 sync (excl. lambda-deploy/) + extensionless routes + CloudFront invalidation |
| `terraform.yml` | Changes to `infrastructure/` | Plan on PR, apply on merge (passes `TF_VAR_anthropic_api_key`) |

**GitHub configuration (already done):**
- **Repository Variables** (Settings → Secrets and variables → Actions → Variables tab):
  - `AWS_DEPLOY_ROLE_ARN` — IAM role ARN for OIDC
  - `API_GATEWAY_URL` — API Gateway URL
  - `COGNITO_USER_POOL_ID` — Cognito pool ID
  - `COGNITO_CLIENT_ID` — Cognito app client ID
  - `FRONTEND_BUCKET` — S3 bucket name for website
  - `CLOUDFRONT_DIST_ID` — CloudFront distribution ID
- **Repository Secret** (Settings → Secrets and variables → Actions → Secrets tab):
  - `ANTHROPIC_API_KEY` — Claude API key (used by terraform.yml via `TF_VAR_anthropic_api_key`)
- **Environments**: `production` (deploy.yml) and `infrastructure` (terraform.yml) — both empty, no protection rules

**Key deploy.yml fixes applied:**
- `--exclude "lambda-deploy/*"` on S3 sync (prevents deleting Lambda zips)
- `deploy-backend` has `needs: [deploy-frontend]` (eliminates race condition)
- Uploads extensionless route files (e.g., `/dashboard`) for CloudFront SPA routing

### Local Dev
- `docker-compose.yml` — LocalStack (emulates S3, DynamoDB, SQS, Lambda, SSM)
- `scripts/localstack-init.sh` — creates all local AWS resources on startup
- `scripts/terraform-bootstrap.sh` — one-time script to create S3 state bucket + DynamoDB lock table before first `terraform init`
- `frontend/.env.local.example` — template for environment variables

---

## Tech Stack Summary

| Layer | Technology | Monthly Cost |
|-------|-----------|-------------|
| Frontend | Next.js 15, TypeScript, shadcn/ui, Tailwind | $0 (CloudFront free tier) |
| Backend | Python 3.12, AWS Lambda | $0 (1M req/mo free) |
| Database | DynamoDB (4 tables, PAY_PER_REQUEST) | ~$0 (<$0.01/mo at personal scale) |
| Queue | SQS | $0 (1M msgs/mo free) |
| Auth | AWS Cognito | $0 (50K MAU free) |
| File Storage | S3 | $0 (5 GB free tier) |
| AI | Claude API — Sonnet (`claude-sonnet-4-5-20250929`) for CV work, Haiku (`claude-haiku-4-5-20251001`) for scoring | ~$5–7/mo |
| IaC | Terraform | $0 |
| CI/CD | GitHub Actions | $0 |
| Monitoring | CloudWatch Log Groups only | $0 |
| **Total** | | **~$5–7/mo** |

---

## DynamoDB Schema

| Table | PK | SK | Key Fields |
|-------|----|----|-----------|
| `aiapply-dev-users` | `userId` | — | careerGoals (object), lastScannedAt, usageHaikuInputTokens, usageHaikuOutputTokens, usageHaikuCalls, usageSonnetInputTokens, usageSonnetOutputTokens, usageSonnetCalls |
| `aiapply-dev-cvs` | `userId` | `cvId` | s3Key, structuredData (JSON string), skills (list), isPrimary |
| `aiapply-dev-job-listings` | `jobId` | — | title, company, description, url, source, matchScore |
| `aiapply-dev-applications` | `userId` | `applicationId` | jobId, cvId, status, companyName, jobTitle, jobUrl, jobDescription, jobLocation, matchScore, careerAlignmentScore, matchReason, tailoredCvKey, cvChanges, coverLetter, atsScore, notes, source, createdAt |

**Application statuses:** `pending` → `matched` → `tailoring` → `review` → `submitted` → `interview` → `offer` / `rejected`

Note: `matched` is the human checkpoint — job scout saves here, user must explicitly click "Tailor CV" to proceed.

---

## Agent Pipeline (How It Works End-to-End)

```
1. User uploads CV to S3 (presigned URL from /api/upload-url)
        ↓ S3 ObjectCreated event
2. cv_analyst Lambda — Claude Sonnet extracts structured JSON → DynamoDB

3. User sets career goals on /onboarding → saved to DynamoDB

4. User clicks "Scan for New Jobs" in dashboard or settings
        ↓ POST /api/jobs/scan → SQS message to job-scout queue
5. job_scout Lambda
   - JobSpy scrapes LinkedIn + Indeed
   - Claude Haiku scores each job: matchScore + careerAlignmentScore
   - Filters: both scores >= user-defined threshold (default 70), no dealbreakers
   - Saves top 10 to DynamoDB as Application records (status: "matched")
   - Updates lastScannedAt + tracks Haiku token usage
   - Does NOT auto-queue for tailoring (user decides)

6. User sees applications in "🎯 Matched" column on dashboard
   - Clicks a card → views job description + match reasoning
   - Clicks "✨ Tailor CV for this Job" → POST /api/applications/tailor → SQS
        ↓ SQS trigger
7. cv_tailor Lambda
   - Claude Sonnet rewrites CV specifically for that company/role
   - Returns: tailored CV JSON + changes list + ATS score + cover letter
   - Saves tailored CV to S3 (tailored/{userId}/{appId}/cv.json)
   - Updates Application status → "review"
   - Tracks Sonnet token usage

8. User sees application move to "👁 Review" column
   - Reviews CV diff (green=added, yellow=modified, red=removed)
   - Copies tailored CV or cover letter via Copy buttons
   - Clicks "✓ Approve CV" → status → "submitted"
   - Goes to company site manually and applies
```

---

## `lib/api.ts` — Full API Client Functions

```typescript
getUploadUrl(fileName, fileType)        // presigned S3 URL
uploadFileToS3(uploadUrl, file)         // direct S3 upload
getProfile()                            // user's CVs
saveCareerGoals(goals)                  // save career goals
getCareerGoals()                        // get goals + lastScannedAt + usage stats
getApplications(limit = 100)            // list applications (paginated)
approveApplication(applicationId)       // approve CV → submitted
getTailoredCV(applicationId)            // fetch tailored CV JSON
deleteApplication(applicationId)        // remove application
tailorApplication(applicationId)        // queue for tailoring
updateApplicationStatus(id, status)     // move between statuses
saveApplicationNotes(id, notes)         // save personal notes
createManualApplication(input)          // add manual job entry
scanJobs()                              // trigger job scout
deleteAccount()                         // full data wipe
```

---

## What Is NOT Done Yet (Phase 2 — Remaining)

- [ ] **Submit Agent** — Playwright Lambda that auto-fills and submits job application forms
- [ ] **Email notifications via SES** — "Your CV has been tailored for Stripe"
- [ ] **CloudFront custom domain** — currently uses default CloudFront URL
- [ ] **Mobile responsive polish** — works but not optimised for mobile

---

## What Is NOT Done Yet (Phase 3 — SaaS)

- [ ] Stripe payments (Free / Pro $29 / Premium $59)
- [ ] Multi-user support (currently designed for 1–2 users)
- [ ] Migrate DynamoDB → RDS PostgreSQL + pgvector (for vector similarity search)
- [ ] Scale Lambda → ECS Fargate (for long-running Playwright sessions)
- [ ] Admin panel (user management, AI cost tracking, pipeline monitoring)
- [ ] Analytics dashboard (interview rates, skill demand, salary insights)
- [ ] API rate limiting per user (100 req/s)
- [ ] Pagination UI on dashboard (currently limit=100, sufficient for personal scale)
- [ ] BatchWriteItem for delete operations (currently sequential, fine at personal scale)

---

## Key File Paths

```
/Users/l.bagga/Documents/AIApply/
├── CLAUDE.md                                                  ← this file
├── README.md                                                  ← project overview
├── docker-compose.yml                                         ← LocalStack local dev
├── scripts/
│   ├── localstack-init.sh                                     ← creates local AWS resources
│   └── terraform-bootstrap.sh                                 ← one-time: creates S3+DynamoDB for TF state
├── frontend/
│   ├── .env.local.example                                     ← copy to .env.local
│   ├── app/page.tsx                                           ← landing page
│   ├── app/onboarding/page.tsx                                ← CV upload + career goals
│   ├── app/dashboard/page.tsx                                 ← kanban board
│   ├── app/applications/[id]/page.tsx                         ← route wrapper (static export)
│   ├── app/applications/application-detail-client.tsx         ← full detail page logic
│   ├── app/settings/page.tsx                                  ← settings + costs + danger zone
│   ├── lib/auth.ts                                            ← Cognito helpers
│   └── lib/api.ts                                             ← API client (all functions)
├── backend/
│   ├── requirements.txt                                       ← pip freeze (full deps)
│   └── lambdas/
│       ├── cv_analyst/handler.py                              ← parse CV with Claude
│       ├── api/handler.py                                     ← REST API routes (all endpoints)
│       ├── job_scout/handler.py                               ← scrape + score jobs + track usage
│       └── cv_tailor/handler.py                               ← tailor CV per company + track usage
└── infrastructure/terraform/
    ├── modules/{storage,cdn,auth,queue,api,monitoring,cicd}/main.tf
    └── environments/dev/{main,variables,outputs,backend}.tf
```

---

## How to Resume Development

### Run the app locally
```bash
cd /Users/l.bagga/Documents/AIApply
docker-compose up -d          # start LocalStack
npm run dev --prefix frontend  # start frontend on :3000
```

### Re-run Terraform (if infrastructure changes needed)
```bash
cd infrastructure/terraform/environments/dev
terraform init   # only needed first time or after provider changes
terraform apply -var="anthropic_api_key=sk-ant-YOUR_KEY"
# github_repo variable has default "lbagga2x/AIApply" — no need to pass it
```

### Deploy
Push to `main` — GitHub Actions handles everything automatically.

---

## Decisions Already Made (Don't Re-discuss)

- **AWS serverless** (Lambda + DynamoDB) not ECS/RDS — keeps cost near $0 at personal scale
- **Review-first mode** is default — user approves each tailored CV before submission
- **Claude API** (not OpenAI) — better quality/cost, prompt caching saves ~40%
- **JobSpy** (open source) for job scraping — free, covers LinkedIn + Indeed
- **Cognito** for auth — free up to 50K MAU, cert-aligned
- **No admin panel yet** — monitor via CloudWatch + Anthropic dashboard
- **DynamoDB** (not PostgreSQL) for now — free tier, no vector search needed at personal scale
- **GitHub Actions OIDC** for CI/CD — no long-lived AWS credentials
- **SSM Parameter Store** (not Secrets Manager) for Anthropic API key in Lambda env — SSM standard params are free; Secrets Manager costs $0.40/secret/month
- **DynamoDB PAY_PER_REQUEST** — the 25 RCU/WCU free tier only applies to PROVISIONED mode; PAY_PER_REQUEST has no free tier but costs <$0.01/month at personal scale
- **S3 versioning** with a 30-day lifecycle rule on non-current versions — prevents old CV versions accumulating cost
- **"Matched" status as human gate** — job scout saves as "matched", user manually triggers tailoring — prevents wasting Sonnet tokens on jobs user doesn't want
- **Usage tracking via DynamoDB ADD** — atomic increments, no schema migration needed, non-fatal if tracking fails
- **BatchGetItem for job URL enrichment** — replaced N+1 GetItem loop; `dynamodb:BatchGetItem` added to Lambda IAM policy
- **Pagination default=100** — sufficient for personal scale; cursor-based pagination backend is ready if needed
- **GitHub variables at repository level** (not environment level) — so all workflow jobs (deploy + terraform plan/apply) can access them regardless of which GitHub environment they reference
- **`TF_VAR_anthropic_api_key`** in terraform.yml env — avoids interactive stdin prompt hanging the CI job; value sourced from `ANTHROPIC_API_KEY` GitHub Secret
