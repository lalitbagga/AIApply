# AIApply — Architecture Diagrams

---

## Diagram 1: High-Level Architecture

```mermaid
graph TB
    User["👤 User / Browser"]

    subgraph Edge["AWS Edge / Auth"]
        CF["CloudFront CDN\n+ S3 (static site)"]
        Cognito["Cognito\nUser Pool (JWT auth)"]
    end

    subgraph Compute["AWS Compute"]
        APIGW["API Gateway\nHTTP API"]
        subgraph Lambdas["Lambda Functions (Python 3.12)"]
            API_L["api\n(REST handler)"]
            CV_L["cv_analyst\n(CV parser)"]
            JS_L["job_scout\n(job finder + scorer)"]
            CT_L["cv_tailor\n(CV rewriter)"]
        end
    end

    subgraph Storage["AWS Storage"]
        S3_CV["S3\nCV + tailored doc storage"]
        DDB["DynamoDB\n4 tables"]
        SSM["SSM Parameter Store\nAnthropic API key"]
    end

    subgraph Messaging["AWS Messaging"]
        SQS_JS["SQS\njob-scout queue"]
        SQS_CT["SQS\ncv-tailor queue"]
    end

    subgraph External["External"]
        Claude["Anthropic Claude API\nSonnet (CV work)\nHaiku (scoring)"]
        JobSpy["JobSpy\nLinkedIn + Indeed scraper"]
    end

    User -- "HTTPS (SPA)" --> CF
    User -- "Sign in / Sign up" --> Cognito
    Cognito -- "JWT token" --> User
    User -- "Bearer JWT" --> APIGW

    APIGW --> API_L
    S3_CV -- "ObjectCreated event" --> CV_L
    SQS_JS -- "trigger" --> JS_L
    SQS_CT -- "trigger" --> CT_L

    API_L <--> DDB
    API_L <--> S3_CV
    API_L --> SQS_JS

    CV_L --> SSM
    CV_L --> Claude
    CV_L <--> DDB

    JS_L --> SSM
    JS_L --> Claude
    JS_L --> JobSpy
    JS_L <--> DDB
    JS_L --> SQS_CT

    CT_L --> SSM
    CT_L --> Claude
    CT_L <--> DDB
    CT_L --> S3_CV
```

---

## Diagram 2: Detailed Service-Call Flow

```mermaid
sequenceDiagram
    actor User
    participant CF as CloudFront / S3
    participant Cognito
    participant APIGW as API Gateway
    participant API as api Lambda
    participant S3 as S3 (CVs)
    participant CV as cv_analyst Lambda
    participant SQS1 as SQS job-scout
    participant JS as job_scout Lambda
    participant SQS2 as SQS cv-tailor
    participant CT as cv_tailor Lambda
    participant DDB as DynamoDB
    participant Claude as Claude API
    participant JobSpy as JobSpy

    %% ── 1. AUTH ─────────────────────────────────────────────
    Note over User,JobSpy: Step 1 — Authentication
    User->>CF: GET / (load SPA)
    CF->>User: Next.js HTML + JS
    User->>Cognito: signUp / signIn
    Cognito-->>User: JWT (idToken + accessToken)

    %% ── 2. CV UPLOAD ────────────────────────────────────────
    Note over User,JobSpy: Step 2 — CV Upload
    User->>APIGW: POST /api/upload-url  [JWT]
    APIGW->>API: invoke (get presigned URL)
    API->>S3: generate_presigned_url()
    API-->>User: { uploadUrl, s3Key, cvId }
    User->>S3: PUT file (direct upload — no Lambda)
    S3-->>CV: ObjectCreated event (s3Key)
    CV->>DDB: GetItem users (get career goals if any)
    CV->>Claude: extract structured data  [Sonnet]
    Claude-->>CV: { skills[], experience[], education, seniorityLevel, … }
    CV->>DDB: PutItem cvs (structuredData, skills, s3Key)

    %% ── 3. CAREER GOALS ─────────────────────────────────────
    Note over User,JobSpy: Step 3 — Career Goals
    User->>APIGW: POST /api/career-goals  [JWT]
    APIGW->>API: invoke
    API->>DDB: PutItem users (careerGoals)
    API->>DDB: Query cvs (get primary CV)
    API->>SQS1: SendMessage { userId, cvId }
    API-->>User: { message: "Career goals saved" }

    %% ── 4. JOB SCOUTING ─────────────────────────────────────
    Note over User,JobSpy: Step 4 — Job Scouting (async)
    SQS1-->>JS: trigger { userId, cvId }
    JS->>DDB: GetItem users (careerGoals)
    JS->>DDB: GetItem cvs (structuredData)
    JS->>JobSpy: scrape_jobs(roles, location, n=30)
    JobSpy-->>JS: raw job listings (title, company, desc, url)
    JS->>Claude: score all 30 jobs vs goals  [Haiku]
    Claude-->>JS: [{ index, matchScore, careerAlignmentScore, include }]
    loop top 10 matched jobs
        JS->>DDB: PutItem job-listings (jobId, title, company, url, …)
        JS->>DDB: PutItem applications (status: "tailoring", jobUrl, matchScore, …)
        JS->>SQS2: SendMessage { userId, cvId, applicationId, jobId }
    end

    %% ── 5. CV TAILORING ─────────────────────────────────────
    Note over User,JobSpy: Step 5 — CV Tailoring (async, once per job)
    SQS2-->>CT: trigger { userId, cvId, applicationId, jobId }
    CT->>DDB: GetItem users (careerGoals)
    CT->>DDB: GetItem cvs (structuredData, s3Key)
    CT->>DDB: GetItem job-listings (description, company, title)
    CT->>Claude: rewrite CV for this company + role  [Sonnet]
    Claude-->>CT: { tailoredCV, changes[], atsScore, coverLetter }
    CT->>S3: PutObject tailored/{userId}/{appId}/cv.json
    CT->>DDB: UpdateItem applications (status: "review", tailoredCvKey, cvChanges, atsScore, coverLetter)

    %% ── 6. USER REVIEW ──────────────────────────────────────
    Note over User,JobSpy: Step 6 — User Reviews on Dashboard
    User->>APIGW: GET /api/applications  [JWT]
    APIGW->>API: invoke
    API->>DDB: Query applications (userId, newest first)
    loop apps without jobUrl
        API->>DDB: GetItem job-listings (get URL)
    end
    API-->>User: applications[] with jobUrl

    User->>APIGW: GET /api/applications/tailored-cv?applicationId=xxx  [JWT]
    APIGW->>API: invoke
    API->>DDB: GetItem applications (verify ownership, get tailoredCvKey)
    API->>S3: GetObject (tailored CV JSON)
    API-->>User: { tailoredCV: { name, skills[], experience[], … } }

    %% ── 7. APPROVE ──────────────────────────────────────────
    Note over User,JobSpy: Step 7 — Approve & Manually Apply
    User->>APIGW: POST /api/applications/approve  [JWT]
    APIGW->>API: invoke
    API->>DDB: UpdateItem applications (status → "submitted", submittedAt)
    API-->>User: { message: "Application approved and marked as submitted" }
    Note right of User: User manually applies at jobUrl link
```

---

## Data Flow Summary

| Step | Trigger | Lambda | Reads from | Writes to |
|------|---------|--------|-----------|-----------|
| CV Upload | S3 ObjectCreated | `cv_analyst` | SSM (API key) | DynamoDB cvs |
| Career Goals | API call (user) | `api` | DynamoDB cvs | DynamoDB users + SQS job-scout |
| Job Scouting | SQS job-scout | `job_scout` | DynamoDB users+cvs, JobSpy, SSM | DynamoDB job-listings+applications, SQS cv-tailor |
| CV Tailoring | SQS cv-tailor | `cv_tailor` | DynamoDB users+cvs+jobs, SSM | S3 (tailored CV), DynamoDB applications |
| Get Applications | API call (user) | `api` | DynamoDB applications+jobs | — |
| Get Tailored CV | API call (user) | `api` | DynamoDB applications, S3 | — |
| Approve | API call (user) | `api` | — | DynamoDB applications |
