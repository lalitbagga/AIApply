"""
CV Tailor Lambda — triggered by SQS.
Takes the user's original CV and a specific job listing,
generates a company-tailored CV with a tracked diff, and stores the result.
"""

import json
import os
from datetime import datetime, timezone
from decimal import Decimal

import anthropic
import boto3
from botocore.exceptions import BotoCoreError, ClientError

dynamodb = boto3.resource("dynamodb")
ssm = boto3.client("ssm")
s3_client = boto3.client("s3")

ENVIRONMENT = os.environ.get("ENVIRONMENT", "dev")
ANTHROPIC_PARAM_NAME = os.environ.get("ANTHROPIC_PARAM_NAME", "")
CV_BUCKET = os.environ.get("CV_BUCKET", "")

CVS_TABLE = f"aiapply-{ENVIRONMENT}-cvs"
JOBS_TABLE = f"aiapply-{ENVIRONMENT}-job-listings"
APPLICATIONS_TABLE = f"aiapply-{ENVIRONMENT}-applications"
USERS_TABLE = f"aiapply-{ENVIRONMENT}-users"

# Claude Sonnet 4.5 pricing ($/million tokens)
SONNET_INPUT_COST_PER_M  = Decimal("3.00")
SONNET_OUTPUT_COST_PER_M = Decimal("15.00")


def track_sonnet_usage(user_id: str, usage) -> None:
    """Atomically record Sonnet token usage on the user record (non-fatal)."""
    try:
        dynamodb.Table(USERS_TABLE).update_item(
            Key={"userId": user_id},
            UpdateExpression=(
                "ADD usageSonnetInputTokens :it, "
                "usageSonnetOutputTokens :ot, "
                "usageSonnetCalls :one"
            ),
            ExpressionAttributeValues={
                ":it":  Decimal(str(usage.input_tokens)),
                ":ot":  Decimal(str(usage.output_tokens)),
                ":one": Decimal(1),
            },
        )
    except (BotoCoreError, ClientError) as e:
        print(f"Usage tracking failed (non-fatal): {e}")

_anthropic_client = None


def get_client():
    global _anthropic_client
    if _anthropic_client is None:
        if ANTHROPIC_PARAM_NAME:
            param = ssm.get_parameter(Name=ANTHROPIC_PARAM_NAME, WithDecryption=True)
            api_key = param["Parameter"]["Value"]
        else:
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        _anthropic_client = anthropic.Anthropic(api_key=api_key)
    return _anthropic_client


def tailor_cv(cv_data: dict, job: dict) -> dict:
    """Use Claude to tailor the CV for a specific job and company."""
    client = get_client()

    cv_json = json.dumps(cv_data, indent=2)
    job_desc = f"{job.get('title')} at {job.get('company')}\n\n{job.get('description', '')}"

    message = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=8192,
        system="""You are a conservative CV editor. Your highest priority is factual
fidelity and completeness, not making the candidate sound more impressive.

NON-NEGOTIABLE RULES:
1. The ORIGINAL CV JSON is the only source of truth. The job description is only
   a relevance guide and must never become evidence about the candidate.
2. Preserve every employment entry, project, education entry, certification,
   contact field, and hyperlink. Preserve the original section order. Never
   remove an entire role, project, credential, or contact item.
3. Copy names, contact details, job titles, employers, dates, degrees,
   certifications, technologies, numbers, percentages, team sizes, customer
   counts, geography, and metrics exactly. If a value is null or absent, keep it
   null or absent; never infer it.
4. Never invent metrics or vague scale claims such as "thousands", "enterprise
   grade", "high availability", "eliminated configuration drift", or percentage
   improvements unless those exact facts exist in the original.
5. Never upgrade responsibility. In particular, do not change "deployed an
   application onto an existing cluster" into "architected the cluster"; do not
   change contributor work into ownership, leadership, strategy, or operations.
6. Never change the candidate's current title or professional identity to match
   the target job. A target role can influence emphasis, not historical facts.
7. You may reorder skills and bullets within the same role or project. You may
   make small wording edits to improve clarity or foreground relevant facts, but
   each rewritten sentence must be directly entailed by a specific original
   sentence and retain the same actor, scope, action, and outcome.
8. The tailored CV must contain the same number of experience, project,
   education, and certification entries as the original.
9. Aim for a concise 2-3 page CV. You may combine overlapping source bullets or
   shorten wording, but the combined bullet must preserve every material fact it
   retains and must not broaden the candidate's responsibility. Use at most 5
   bullets for the current role, 4 for the previous role, 2 for each older role,
   and 3 for each project. Prefer the facts most relevant to the target job.
10. Never move content between sections or roles. Keep the logical structure:
   contact details and links, summary, skills, experience, projects, education,
   certifications, and languages when those sections exist in the original.
11. Before returning JSON, perform a factual audit against the original. Revert
   any statement that is not directly supported. When uncertain, copy the
   original wording unchanged.
12. Return valid JSON only, without Markdown or comments.""",
        messages=[{
            "role": "user",
            "content": f"""Conservatively tailor this CV for the following job.

ORIGINAL CV:
{cv_json}

JOB TO APPLY FOR:
{job_desc}

Return this exact JSON structure:
{{
  "tailoredCV": {{
    "name": "...",
    "email": "... or null",
    "phone": "... or null",
    "location": "... or null",
    "links": [],
    "summary": "A factual 2-3 sentence summary emphasizing relevant existing experience",
    "skills": ["most relevant first", ...],
    "experience": [...],
    "projects": [...],
    "education": [...],
    "certifications": [...],
    "languages": [...]
  }},
  "changes": [
    {{
      "type": "modified|reordered",
      "section": "summary|skills|experience|projects",
      "description": "Specific wording/order change and the original fact supporting it"
    }}
  ],
  "atsScore": 85,
  "coverLetter": "3-4 paragraph cover letter for this specific role and company"
}}""",
        }],
    )

    response_text = message.content[0].text
    if "```json" in response_text:
        response_text = response_text.split("```json")[1].split("```")[0]
    elif "```" in response_text:
        response_text = response_text.split("```")[1].split("```")[0]

    return json.loads(response_text.strip()), message.usage


def enforce_factual_invariants(original: dict, tailored: dict) -> dict:
    """Restore fields the model is never allowed to invent, alter, or omit."""
    safe = dict(tailored) if isinstance(tailored, dict) else {}

    # These fields are factual records, not tailoring opportunities.
    for field in (
        "name",
        "email",
        "phone",
        "location",
        "links",
        "education",
        "certifications",
        "languages",
    ):
        if field in original:
            safe[field] = original[field]

    original_experience = original.get("experience", [])
    tailored_experience = safe.get("experience", [])
    if (
        not isinstance(tailored_experience, list)
        or len(tailored_experience) != len(original_experience)
    ):
        safe["experience"] = original_experience
    else:
        protected_fields = ("title", "company", "startDate", "endDate")
        for source, edited in zip(original_experience, tailored_experience):
            if not isinstance(source, dict) or not isinstance(edited, dict):
                safe["experience"] = original_experience
                break
            for field in protected_fields:
                if field in source:
                    edited[field] = source[field]

    # Projects must never disappear. Their factual names are immutable.
    original_projects = original.get("projects", [])
    tailored_projects = safe.get("projects", [])
    if not isinstance(tailored_projects, list) or len(tailored_projects) != len(original_projects):
        safe["projects"] = original_projects
    else:
        for source, edited in zip(original_projects, tailored_projects):
            if not isinstance(source, dict) or not isinstance(edited, dict):
                safe["projects"] = original_projects
                break
            if "name" in source:
                edited["name"] = source["name"]

    # Skills may be reordered, but no unsupported skill may be introduced and
    # no source skill may be removed.
    original_skills = original.get("skills", [])
    tailored_skills = safe.get("skills", [])
    if isinstance(original_skills, list):
        source_by_key = {str(skill).casefold(): skill for skill in original_skills}
        reordered = []
        seen = set()
        if isinstance(tailored_skills, list):
            for skill in tailored_skills:
                key = str(skill).casefold()
                if key in source_by_key and key not in seen:
                    reordered.append(source_by_key[key])
                    seen.add(key)
        reordered.extend(
            skill for skill in original_skills if str(skill).casefold() not in seen
        )
        safe["skills"] = reordered

    return safe


def lambda_handler(event, context):
    """Triggered by SQS. Tailors CV for each queued application."""
    for record in event.get("Records", []):
        try:
            body = json.loads(record["body"])
            user_id = body["userId"]
            cv_id = body["cvId"]
            app_id = body["applicationId"]
            job_id = body["jobId"]

            print(f"Tailoring CV for user={user_id} app={app_id} job={job_id}")

            # Load CV
            cvs_table = dynamodb.Table(CVS_TABLE)
            cv_item = cvs_table.get_item(Key={"userId": user_id, "cvId": cv_id}).get("Item", {})
            cv_data = json.loads(cv_item.get("structuredData", "{}"))

            # Load job
            jobs_table = dynamodb.Table(JOBS_TABLE)
            job = jobs_table.get_item(Key={"jobId": job_id}).get("Item", {})

            if not cv_data or not job:
                print(f"Missing CV or job data: cv={bool(cv_data)} job={bool(job)}")
                continue

            # Tailor the CV
            result, sonnet_usage = tailor_cv(cv_data, job)
            track_sonnet_usage(user_id, sonnet_usage)
            tailored_cv = enforce_factual_invariants(
                cv_data, result.get("tailoredCV", {})
            )
            changes = result.get("changes", [])
            ats_score = result.get("atsScore", 0)
            cover_letter = result.get("coverLetter", "")

            # Save tailored CV to S3
            s3_key = f"tailored/{user_id}/{app_id}/cv.json"
            s3_client.put_object(
                Bucket=CV_BUCKET,
                Key=s3_key,
                Body=json.dumps(tailored_cv),
                ContentType="application/json",
            )

            # Update application record
            apps_table = dynamodb.Table(APPLICATIONS_TABLE)
            apps_table.update_item(
                Key={"userId": user_id, "applicationId": app_id},
                UpdateExpression="""
                    SET #status = :status,
                        tailoredCvKey = :cvKey,
                        cvChanges = :changes,
                        atsScore = :ats,
                        coverLetter = :cl,
                        tailoredAt = :ts
                """,
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":status": "review",       # ready for human review
                    ":cvKey": s3_key,
                    ":changes": json.dumps(changes),
                    ":ats": str(ats_score),
                    ":cl": cover_letter,
                    ":ts": datetime.now(timezone.utc).isoformat(),
                },
            )

            print(f"Tailored CV saved — {len(changes)} changes, ATS={ats_score}")

        except (BotoCoreError, ClientError, KeyError, TypeError, ValueError, json.JSONDecodeError, anthropic.APIError) as e:
            print(f"Error tailoring CV: {e}")
            import traceback
            traceback.print_exc()

    return {"statusCode": 200, "body": "Done"}
