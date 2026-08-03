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
        max_tokens=4096,
        system="""You are an expert CV writer. Your job is to tailor a candidate's CV
for a specific role without fabricating experience. You reorder, reframe, and
emphasize existing experience to match what the employer wants.
Always be honest — only use information from the original CV.""",
        messages=[{
            "role": "user",
            "content": f"""Tailor this CV for the following job. Return JSON only.

ORIGINAL CV:
{cv_json}

JOB TO APPLY FOR:
{job_desc}

Return this exact JSON structure:
{{
  "tailoredCV": {{
    // Same structure as input CV, but tailored:
    // - Summary rewritten to speak directly to this role
    // - Skills reordered: most relevant to this job first
    // - Experience bullets rewritten to emphasise relevant achievements
    // - Remove or de-emphasise unrelated work
    "name": "...",
    "email": "...",
    "summary": "Tailored 2-3 sentence summary for this specific role",
    "skills": ["most relevant first", ...],
    "experience": [...],
    "education": [...],
    "certifications": [...]
  }},
  "changes": [
    {{
      "type": "added|modified|removed",
      "section": "summary|skills|experience|education",
      "description": "What changed and why"
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
            tailored_cv = result.get("tailoredCV", {})
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
