"""
Job Scout Lambda — triggered by SQS.
Scrapes job listings via JobSpy, scores them against the user's career goals
using Claude, and saves matches to DynamoDB.
"""

import json
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import anthropic
import boto3
from botocore.exceptions import BotoCoreError, ClientError


class DecimalEncoder(json.JSONEncoder):
    """DynamoDB returns numbers as Decimal — convert to float for JSON serialization."""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)

s3_client = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")
ssm = boto3.client("ssm")
sqs = boto3.client("sqs")

ENVIRONMENT = os.environ.get("ENVIRONMENT", "dev")
ANTHROPIC_PARAM_NAME = os.environ.get("ANTHROPIC_PARAM_NAME", "")
CV_BUCKET = os.environ.get("CV_BUCKET", "")

JOBS_TABLE = f"aiapply-{ENVIRONMENT}-job-listings"
APPLICATIONS_TABLE = f"aiapply-{ENVIRONMENT}-applications"
USERS_TABLE = f"aiapply-{ENVIRONMENT}-users"
CV_TAILOR_QUEUE_URL = os.environ.get("CV_TAILOR_QUEUE_URL", "")

# Claude Haiku 4.5 pricing ($/million tokens)
HAIKU_INPUT_COST_PER_M  = Decimal("0.80")
HAIKU_OUTPUT_COST_PER_M = Decimal("4.00")


def track_haiku_usage(user_id: str, usage) -> None:
    """Atomically record Haiku token usage on the user record (non-fatal)."""
    try:
        dynamodb.Table(USERS_TABLE).update_item(
            Key={"userId": user_id},
            UpdateExpression=(
                "ADD usageHaikuInputTokens :it, "
                "usageHaikuOutputTokens :ot, "
                "usageHaikuCalls :one"
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


def scrape_jobs(search_terms: list[str], location: str, num_results: int = 20, hours_old: int = 72) -> list[dict]:
    """Use JobSpy to scrape job listings."""
    try:
        from jobspy import scrape_jobs as jobspy_scrape
        jobs_df = jobspy_scrape(
            site_name=["linkedin", "indeed"],
            search_term=" OR ".join(search_terms[:3]),
            location=location or "Remote",
            results_wanted=num_results,
            hours_old=hours_old,  # configurable "recent jobs" window
            country_indeed="UK",
        )
        if jobs_df is None or jobs_df.empty:
            return []

        jobs = []
        for _, row in jobs_df.iterrows():
            jobs.append({
                "jobId": str(uuid.uuid4()),
                "title": str(row.get("title", "")),
                "company": str(row.get("company", "")),
                "location": str(row.get("location", "")),
                "description": str(row.get("description", ""))[:3000],  # truncate
                "url": str(row.get("job_url", "")),
                "source": str(row.get("site", "")),
                "salary_min": str(row.get("min_amount", "")),
                "salary_max": str(row.get("max_amount", "")),
                "postedAt": datetime.now(timezone.utc).isoformat(),
            })
        return jobs
    except (ImportError, TypeError, ValueError, RuntimeError) as e:
        print(f"JobSpy error: {e}")
        return []


def score_jobs_with_claude(jobs: list[dict], career_goals: dict, cv_summary: str) -> list[dict]:
    """Use Claude to score each job against career goals and CV.

    Respects optional user thresholds from career_goals:
    - minMatchScore (default 70)
    - minAlignmentScore (default 70)
    - maxMatches (default 10)
    """
    if not jobs:
        return [], None

    client = get_client()

    # User-tunable thresholds with sensible defaults
    min_match = int(career_goals.get("minMatchScore", 70) or 70)
    min_align = int(career_goals.get("minAlignmentScore", 70) or 70)
    max_matches = int(career_goals.get("maxMatches", 10) or 10)
    max_matches = max(1, min(max_matches, 50))

    # Build a compact job list for scoring
    job_list = "\n".join([
        f"{i+1}. [{j['title']} at {j['company']}] {j['description'][:300]}"
        for i, j in enumerate(jobs)
    ])

    career_summary = json.dumps({
        "targetRoles": career_goals.get("targetRoles", []),
        "targetIndustries": career_goals.get("targetIndustries", []),
        "workArrangement": career_goals.get("workArrangement", ["Remote"]),
        "dealbreakers": career_goals.get("dealbreakers", []),
        "minSalary": career_goals.get("minSalary"),
        "minMatchScore": min_match,
        "minAlignmentScore": min_align,
    }, cls=DecimalEncoder)

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": f"""Score these job listings for a candidate.

CANDIDATE PROFILE:
{cv_summary}

CAREER GOALS:
{career_summary}

JOB LISTINGS:
{job_list}

Return ONLY a JSON array (one object per job, same order):
[
  {{
    "index": 1,
    "matchScore": 85,
    "careerAlignmentScore": 78,
    "matchReason": "One sentence why this matches",
    "include": true
  }}
]

Rules:
- matchScore: how well skills/experience match the role (0-100)
- careerAlignmentScore: how well this advances stated career goals (0-100)
- include: true if both scores >= 70 AND no dealbreakers apply
Only return jobs with a realistic chance of success.""",
        }],
    )

    response_text = message.content[0].text
    if "```json" in response_text:
        response_text = response_text.split("```json")[1].split("```")[0]
    elif "```" in response_text:
        response_text = response_text.split("```")[1].split("```")[0]

    scores = json.loads(response_text.strip())
    score_map = {s["index"]: s for s in scores}

    scored_jobs = []
    for i, job in enumerate(jobs):
        score_data = score_map.get(i + 1, {})
        match_score = score_data.get("matchScore", 0)
        align_score = score_data.get("careerAlignmentScore", 0)
        include_flag = score_data.get("include", False)

        # Safety net: enforce user thresholds even if Claude forgot to
        if include_flag and (match_score < min_match or align_score < min_align):
            include_flag = False

        if include_flag:
            scored_jobs.append({
                **job,
                "matchScore": match_score,
                "careerAlignmentScore": align_score,
                "matchReason": score_data.get("matchReason", ""),
            })

    # Sort by combined score and cap by user preference
    scored_jobs.sort(key=lambda j: j["matchScore"] + j["careerAlignmentScore"], reverse=True)
    return scored_jobs[:max_matches], message.usage  # top N + usage stats


def lambda_handler(event, context):
    """Triggered by SQS message containing userId and cvId."""
    for record in event.get("Records", []):
        try:
            body = json.loads(record["body"])
            user_id = body["userId"]
            cv_id = body["cvId"]

            print(f"Scout for user {user_id}, cv {cv_id}")

            # Load career goals
            users_table = dynamodb.Table(USERS_TABLE)
            user = users_table.get_item(Key={"userId": user_id}).get("Item", {})
            career_goals = user.get("careerGoals", {})

            # Load CV structured data
            cvs_table = dynamodb.Table(f"aiapply-{ENVIRONMENT}-cvs")
            cv_item = cvs_table.get_item(
                Key={"userId": user_id, "cvId": cv_id}
            ).get("Item", {})
            cv_data = json.loads(cv_item.get("structuredData", "{}"))
            cv_summary = f"Skills: {', '.join(cv_data.get('skills', [])[:15])}. " \
                        f"Experience: {cv_data.get('totalYearsExperience', 0)} years. " \
                        f"Level: {cv_data.get('seniorityLevel', 'mid')}."

            # Scrape jobs — prefer user's stated location, fall back to CV location,
            # then "worldwide" (JobSpy accepts this; "Remote" causes geocoding errors)
            target_roles = career_goals.get("targetRoles", ["Software Engineer"])
            stated_locations = career_goals.get("locations") or []
            if stated_locations:
                location = stated_locations[0]
            elif cv_data.get("location"):
                # Extract just the country part (e.g. "Porto, Portugal" → "Portugal")
                loc_parts = cv_data["location"].rsplit(",", 1)
                location = loc_parts[-1].strip() if len(loc_parts) > 1 else cv_data["location"]
            else:
                location = "worldwide"

            # User-tunable recency window (in hours), with safe defaults/bounds
            window_hours = int(career_goals.get("jobWindowHours", 72) or 72)
            window_hours = max(24, min(window_hours, 336))  # 1–14 days

            raw_jobs = scrape_jobs(target_roles, location, num_results=30, hours_old=window_hours)

            if not raw_jobs:
                print("No jobs found from scrapers")
                return {"statusCode": 200, "body": "No jobs found"}

            # Score jobs
            matched_jobs, haiku_usage = score_jobs_with_claude(raw_jobs, career_goals, cv_summary)
            if haiku_usage:
                track_haiku_usage(user_id, haiku_usage)

            # Save matched jobs to DynamoDB and queue CV tailoring
            jobs_table = dynamodb.Table(JOBS_TABLE)
            apps_table = dynamodb.Table(APPLICATIONS_TABLE)

            # Load existing job URLs for this user to avoid duplicates across scans
            existing = apps_table.query(
                KeyConditionExpression="userId = :uid",
                ExpressionAttributeValues={":uid": user_id},
                ProjectionExpression="jobUrl",
            )
            existing_urls = {
                item["jobUrl"]
                for item in existing.get("Items", [])
                if item.get("jobUrl")
            }

            for job in matched_jobs:
                job_url = job.get("url", "")
                if job_url and job_url in existing_urls:
                    # Skip if we've already created an application for this posting
                    continue

                # Save job listing
                jobs_table.put_item(Item=job)

                # Create application record
                app_id = str(uuid.uuid4())
                apps_table.put_item(Item={
                    "userId": user_id,
                    "applicationId": app_id,
                    "jobId": job["jobId"],
                    "cvId": cv_id,
                    "status": "matched",           # human checkpoint — user triggers tailoring manually
                    "companyName": job["company"],
                    "jobTitle": job["title"],
                    "jobLocation": job.get("location", ""),
                    "jobDescription": job.get("description", ""),  # stored so user can read before tailoring
                    "matchScore": str(job["matchScore"]),
                    "careerAlignmentScore": str(job["careerAlignmentScore"]),
                    "matchReason": job["matchReason"],
                    "jobUrl": job_url,
                    "createdAt": datetime.now(timezone.utc).isoformat(),
                })
                if job_url:
                    existing_urls.add(job_url)
                # CV tailoring is now triggered manually by the user via POST /api/applications/tailor
                # (no automatic SQS send here — saves tokens on jobs the user doesn't want)

            print(f"Found {len(matched_jobs)} matches, queued for tailoring")
            return {"statusCode": 200, "body": f"Found {len(matched_jobs)} matches"}

        except (BotoCoreError, ClientError, KeyError, TypeError, ValueError, json.JSONDecodeError, anthropic.APIError) as e:
            print(f"Error in job scout: {e}")
            import traceback
            traceback.print_exc()

    return {"statusCode": 200, "body": "Done"}
