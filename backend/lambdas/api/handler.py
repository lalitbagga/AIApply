"""
API Handler Lambda — Serves REST API requests via API Gateway.
Routes requests to appropriate handlers for CRUD operations.
"""

import base64
import binascii
import json
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from botocore.exceptions import BotoCoreError, ClientError

dynamodb = boto3.resource("dynamodb")
s3 = boto3.client("s3")
sqs = boto3.client("sqs")
ssm = boto3.client("ssm")

ENVIRONMENT = os.environ.get("ENVIRONMENT", "dev")
CV_BUCKET = os.environ.get("CV_BUCKET", "aiapply-dev-cv-storage")
SQS_JOB_SCOUT_URL = os.environ.get("SQS_JOB_SCOUT_URL", "")
SQS_CV_TAILOR_URL = os.environ.get("SQS_CV_TAILOR_URL", "")
STRIPE_SECRET_PARAM_NAME = os.environ.get("STRIPE_SECRET_PARAM_NAME", "")
STRIPE_WEBHOOK_PARAM_NAME = os.environ.get("STRIPE_WEBHOOK_PARAM_NAME", "")
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3000")

# Module-level cache — SSM called once per Lambda cold start
_stripe_secret_key = None
_stripe_webhook_secret = None


def get_stripe_secret_key() -> str:
    global _stripe_secret_key
    if _stripe_secret_key is None:
        if STRIPE_SECRET_PARAM_NAME:
            param = ssm.get_parameter(Name=STRIPE_SECRET_PARAM_NAME, WithDecryption=True)
            _stripe_secret_key = param["Parameter"]["Value"]
        else:
            _stripe_secret_key = os.environ.get("STRIPE_SECRET_KEY", "")
    return _stripe_secret_key


def get_stripe_webhook_secret() -> str:
    global _stripe_webhook_secret
    if _stripe_webhook_secret is None:
        if STRIPE_WEBHOOK_PARAM_NAME:
            param = ssm.get_parameter(Name=STRIPE_WEBHOOK_PARAM_NAME, WithDecryption=True)
            _stripe_webhook_secret = param["Parameter"]["Value"]
        else:
            _stripe_webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    return _stripe_webhook_secret

# Table references
USERS_TABLE = f"aiapply-{ENVIRONMENT}-users"
CVS_TABLE = f"aiapply-{ENVIRONMENT}-cvs"
APPLICATIONS_TABLE = f"aiapply-{ENVIRONMENT}-applications"
JOBS_TABLE = f"aiapply-{ENVIRONMENT}-job-listings"


class DecimalEncoder(json.JSONEncoder):
    """Handle DynamoDB Decimal types in JSON serialization."""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


def response(status_code: int, body: dict) -> dict:
    """Create API Gateway response."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
        },
        "body": json.dumps(body, cls=DecimalEncoder),
    }


def get_user_id(event: dict) -> str:
    """Extract user ID (Cognito sub) from the JWT.

    Tries two sources in order:
    1. requestContext.authorizer.jwt.claims — populated when API Gateway has a
       JWT authorizer configured (preferred, validated by APIGW).
    2. Authorization header — decode the JWT payload directly (base64url).
       No signature verification here; we trust APIGW already accepted the
       request over HTTPS from our own frontend.
    """
    # Path 1: API Gateway JWT authorizer (if configured)
    claims = (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("jwt", {})
        .get("claims", {})
    )
    if claims.get("sub"):
        return claims["sub"]

    # Path 2: Decode JWT payload from Authorization header
    auth_header = (event.get("headers") or {}).get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        try:
            token = auth_header.split(" ", 1)[1]
            # JWT = header.payload.signature — we only need the payload
            payload_b64 = token.split(".")[1]
            # Base64url → base64 (add padding)
            payload_b64 += "=" * (4 - len(payload_b64) % 4)
            payload = json.loads(base64.b64decode(payload_b64).decode("utf-8"))
            sub = payload.get("sub", "")
            if sub:
                return sub
        except (AttributeError, IndexError, TypeError, ValueError, binascii.Error) as e:
            print(f"JWT decode error: {e}")

    return "anonymous"


def handle_get_profile(event: dict) -> dict:
    """GET /api/profile — Get user profile and CV data."""
    user_id = get_user_id(event)
    table = dynamodb.Table(CVS_TABLE)

    result = table.query(
        KeyConditionExpression="userId = :uid",
        ExpressionAttributeValues={":uid": user_id},
    )

    cvs = result.get("Items", [])
    # Parse structured data JSON strings back to dicts
    for cv in cvs:
        if "structuredData" in cv and isinstance(cv["structuredData"], str):
            cv["structuredData"] = json.loads(cv["structuredData"])

    return response(200, {"userId": user_id, "cvs": cvs})


def handle_get_applications(event: dict) -> dict:
    """GET /api/applications — Get applications for the user (paginated)."""
    user_id = get_user_id(event)
    params = event.get("queryStringParameters") or {}

    # Pagination: limit (default 100, max 200) + cursor
    try:
        limit = min(int(params.get("limit", 100)), 200)
    except (ValueError, TypeError):
        limit = 100

    last_key_raw = params.get("lastKey")
    exclusive_start = (
        {"userId": user_id, "applicationId": last_key_raw} if last_key_raw else None
    )

    table = dynamodb.Table(APPLICATIONS_TABLE)
    query_kwargs: dict = {
        "KeyConditionExpression": "userId = :uid",
        "ExpressionAttributeValues": {":uid": user_id},
        "ScanIndexForward": False,  # newest first
        "Limit": limit,
    }
    if exclusive_start:
        query_kwargs["ExclusiveStartKey"] = exclusive_start

    result = table.query(**query_kwargs)
    applications = result.get("Items", [])

    # Next-page cursor returned to the client (applicationId of the last record)
    next_key = None
    if "LastEvaluatedKey" in result:
        next_key = result["LastEvaluatedKey"].get("applicationId")

    # Enrich missing jobUrls with a single batch_get_item call (replaces N+1 loop).
    # Chunks of 25 to respect the DynamoDB batch limit.
    needs_url = [a for a in applications if a.get("jobId") and not a.get("jobUrl")]
    if needs_url:
        job_ids = list({a["jobId"] for a in needs_url})
        job_urls: dict = {}
        chunk_size = 25
        for i in range(0, len(job_ids), chunk_size):
            chunk = job_ids[i : i + chunk_size]
            try:
                resp = dynamodb.batch_get_item(
                    RequestItems={
                        JOBS_TABLE: {
                            "Keys": [{"jobId": jid} for jid in chunk],
                            "ProjectionExpression": "jobId, #u",
                            "ExpressionAttributeNames": {"#u": "url"},
                        }
                    }
                )
                for item in resp.get("Responses", {}).get(JOBS_TABLE, []):
                    job_urls[item["jobId"]] = item.get("url", "")
            except (BotoCoreError, ClientError) as e:
                print(f"batch_get_item failed (non-fatal): {e}")

        for app in applications:
            jid = app.get("jobId")
            if jid and jid in job_urls:
                app["jobUrl"] = job_urls[jid]

    payload: dict = {"applications": applications}
    if next_key:
        payload["nextKey"] = next_key
    return response(200, payload)


def handle_get_upload_url(event: dict) -> dict:
    """POST /api/upload-url — Generate presigned S3 URL for CV upload."""
    user_id = get_user_id(event)
    body = json.loads(event.get("body", "{}"))
    file_name = body.get("fileName", "cv.pdf")
    file_type = body.get("fileType", "application/pdf")

    # Sanitize filename
    safe_name = file_name.replace(" ", "_").replace("/", "_")
    cv_id = safe_name.rsplit(".", 1)[0]
    s3_key = f"uploads/{user_id}/{safe_name}"

    presigned_url = s3.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": CV_BUCKET,
            "Key": s3_key,
            "ContentType": file_type,
        },
        ExpiresIn=300,  # 5 minutes
    )

    return response(200, {
        "uploadUrl": presigned_url,
        "s3Key": s3_key,
        "cvId": cv_id,
    })


def get_job_scout_queue_url() -> str:
    """Get job scout SQS queue URL from env var, or derive it via STS (no extra perms needed)."""
    if SQS_JOB_SCOUT_URL:
        return SQS_JOB_SCOUT_URL
    # Fallback: derive from account ID — works without GetQueueUrl permission
    account_id = boto3.client("sts").get_caller_identity()["Account"]
    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    return f"https://sqs.{region}.amazonaws.com/{account_id}/aiapply-{ENVIRONMENT}-job-scout"


def get_cv_tailor_queue_url() -> str:
    """Get cv-tailor SQS queue URL from env var, or derive it via STS."""
    if SQS_CV_TAILOR_URL:
        return SQS_CV_TAILOR_URL
    account_id = boto3.client("sts").get_caller_identity()["Account"]
    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    return f"https://sqs.{region}.amazonaws.com/{account_id}/aiapply-{ENVIRONMENT}-cv-tailor"


def handle_save_career_goals(event: dict) -> dict:
    """POST /api/career-goals — Save user's career goals and trigger job scout."""
    user_id = get_user_id(event)
    body = json.loads(event.get("body", "{}"))

    table = dynamodb.Table(USERS_TABLE)
    # Use update_item (not put_item) so existing fields like creditsBalance
    # and usage stats are preserved when the user updates their career goals.
    goals = {
        "targetRoles": body.get("targetRoles", []),
        "targetIndustries": body.get("targetIndustries", []),
        "locations": body.get("locations", []),
        "workArrangement": body.get("workArrangement", ["remote"]),
        "dealbreakers": body.get("dealbreakers", []),
        "minMatchScore": body.get("minMatchScore", 70),
        "minAlignmentScore": body.get("minAlignmentScore", 70),
        "jobWindowHours": body.get("jobWindowHours", 72),
    }
    if body.get("minSalary") is not None:
        goals["minSalary"] = body["minSalary"]
    if body.get("maxSalary") is not None:
        goals["maxSalary"] = body["maxSalary"]
    table.update_item(
        Key={"userId": user_id},
        UpdateExpression="SET careerGoals = :goals",
        ExpressionAttributeValues={":goals": goals},
    )

    # Trigger job scout for the user's primary CV
    cvs_table = dynamodb.Table(CVS_TABLE)
    result = cvs_table.query(
        KeyConditionExpression="userId = :uid",
        ExpressionAttributeValues={":uid": user_id},
        Limit=1,
    )
    items = result.get("Items", [])
    if items:
        cv_id = items[0]["cvId"]
        queue_url = get_job_scout_queue_url()
        sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps({"userId": user_id, "cvId": cv_id}),
        )
        print(f"Triggered job scout for user {user_id}, cv {cv_id}")
    else:
        print(f"No CV found for user {user_id} — job scout not triggered")

    return response(200, {"message": "Career goals saved"})


def handle_get_career_goals(event: dict) -> dict:
    """GET /api/career-goals — Get user's career goals."""
    user_id = get_user_id(event)
    table = dynamodb.Table(USERS_TABLE)

    result = table.get_item(Key={"userId": user_id})
    item = result.get("Item", {})

    usage = {
        "haikuInputTokens":  int(item.get("usageHaikuInputTokens",  0)),
        "haikuOutputTokens": int(item.get("usageHaikuOutputTokens", 0)),
        "haikuCalls":        int(item.get("usageHaikuCalls",        0)),
        "sonnetInputTokens":  int(item.get("usageSonnetInputTokens",  0)),
        "sonnetOutputTokens": int(item.get("usageSonnetOutputTokens", 0)),
        "sonnetCalls":        int(item.get("usageSonnetCalls",        0)),
    }

    return response(200, {
        "careerGoals": item.get("careerGoals", {}),
        "lastScannedAt": item.get("lastScannedAt"),
        "usage": usage,
        "creditsBalance": int(item.get("creditsBalance", 0)),
    })


def handle_scan_jobs(event: dict) -> dict:
    """POST /api/jobs/scan — Trigger job scout for the current user."""
    user_id = get_user_id(event)

    # Verify career goals exist
    users_table = dynamodb.Table(USERS_TABLE)
    user = users_table.get_item(Key={"userId": user_id}).get("Item", {})
    if not user.get("careerGoals"):
        return response(400, {"error": "Please set career goals first"})

    # Get primary CV
    cvs_table = dynamodb.Table(CVS_TABLE)
    result = cvs_table.query(
        KeyConditionExpression="userId = :uid",
        ExpressionAttributeValues={":uid": user_id},
        Limit=1,
    )
    items = result.get("Items", [])
    if not items:
        return response(400, {"error": "Please upload a CV first"})

    cv_id = items[0]["cvId"]

    # Record scan time
    users_table.update_item(
        Key={"userId": user_id},
        UpdateExpression="SET lastScannedAt = :t",
        ExpressionAttributeValues={":t": datetime.now(timezone.utc).isoformat()},
    )

    # Trigger job scout
    sqs.send_message(
        QueueUrl=get_job_scout_queue_url(),
        MessageBody=json.dumps({"userId": user_id, "cvId": cv_id}),
    )
    return response(200, {"message": "Job scan started"})


def handle_tailor_application(event: dict) -> dict:
    """POST /api/applications/tailor — Queue a matched application for CV tailoring."""
    user_id = get_user_id(event)
    body = json.loads(event.get("body", "{}"))
    application_id = body.get("applicationId")

    if not application_id:
        return response(400, {"error": "applicationId required"})

    # Atomically check and deduct one credit — fails if balance is 0 or missing
    users_table = dynamodb.Table(USERS_TABLE)
    try:
        users_table.update_item(
            Key={"userId": user_id},
            UpdateExpression="ADD creditsBalance :neg",
            ConditionExpression="creditsBalance >= :one",
            ExpressionAttributeValues={":neg": Decimal(-1), ":one": Decimal(1)},
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return response(402, {"error": "No credits remaining. Purchase credits to tailor more CVs."})
        raise

    # Fetch the application to get cvId and jobId for the SQS message
    table = dynamodb.Table(APPLICATIONS_TABLE)
    item = table.get_item(
        Key={"userId": user_id, "applicationId": application_id}
    ).get("Item", {})

    if not item:
        return response(404, {"error": "Application not found"})

    # Update status to tailoring
    table.update_item(
        Key={"userId": user_id, "applicationId": application_id},
        UpdateExpression="SET #status = :s",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={":s": "tailoring"},
    )

    # Send to cv-tailor queue
    sqs.send_message(
        QueueUrl=get_cv_tailor_queue_url(),
        MessageBody=json.dumps({
            "userId": user_id,
            "cvId": item["cvId"],
            "applicationId": application_id,
            "jobId": item["jobId"],
        }),
    )
    return response(200, {"message": "CV tailoring queued"})


def handle_delete_application(event: dict) -> dict:
    """DELETE /api/applications — Permanently delete an application record."""
    user_id = get_user_id(event)
    params = event.get("queryStringParameters") or {}
    application_id = params.get("applicationId")

    if not application_id:
        return response(400, {"error": "applicationId required"})

    table = dynamodb.Table(APPLICATIONS_TABLE)
    table.delete_item(Key={"userId": user_id, "applicationId": application_id})
    return response(200, {"message": "Application deleted"})


def handle_approve_application(event: dict) -> dict:
    """POST /api/applications/approve — Mark a reviewed application as submitted."""
    user_id = get_user_id(event)
    body = json.loads(event.get("body", "{}"))
    application_id = body.get("applicationId")

    if not application_id:
        return response(400, {"error": "applicationId required"})

    table = dynamodb.Table(APPLICATIONS_TABLE)
    table.update_item(
        Key={"userId": user_id, "applicationId": application_id},
        UpdateExpression="SET #status = :s, submittedAt = :t",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={
            ":s": "submitted",
            ":t": datetime.now(timezone.utc).isoformat(),
        },
    )

    return response(200, {"message": "Application approved and marked as submitted"})


def handle_update_application_status(event: dict) -> dict:
    """PUT /api/applications/status — Update an application's pipeline status."""
    user_id = get_user_id(event)
    body = json.loads(event.get("body", "{}"))
    application_id = body.get("applicationId")
    new_status = body.get("status")

    if not application_id:
        return response(400, {"error": "applicationId required"})
    if not new_status:
        return response(400, {"error": "status required"})

    allowed_statuses = {
        "pending",
        "matched",
        "matching",
        "tailoring",
        "review",
        "submitted",
        "interview",
        "offer",
        "rejected",
    }
    if new_status not in allowed_statuses:
        return response(400, {"error": f"Invalid status: {new_status}"})

    now = datetime.now(timezone.utc).isoformat()

    # Always record the last time status was changed.
    update_expr = "SET #status = :s, updatedAt = :t"
    expr_attr_names = {"#status": "status"}
    expr_attr_values = {":s": new_status, ":t": now}

    # Convenience timestamps for later analytics.
    if new_status == "submitted":
        update_expr += ", submittedAt = :t"
    elif new_status == "interview":
        update_expr += ", interviewAt = :t"
    elif new_status == "offer":
        update_expr += ", offerAt = :t"
    elif new_status == "rejected":
        update_expr += ", rejectedAt = :t"

    table = dynamodb.Table(APPLICATIONS_TABLE)

    # Verify ownership and existence.
    existing = table.get_item(Key={"userId": user_id, "applicationId": application_id}).get("Item")
    if not existing:
        return response(404, {"error": "Application not found"})

    table.update_item(
        Key={"userId": user_id, "applicationId": application_id},
        UpdateExpression=update_expr,
        ExpressionAttributeNames=expr_attr_names,
        ExpressionAttributeValues=expr_attr_values,
    )

    return response(200, {"message": "Status updated", "status": new_status, "updatedAt": now})


def handle_save_application_notes(event: dict) -> dict:
    """POST /api/applications/notes — Save personal notes for an application."""
    user_id = get_user_id(event)
    body = json.loads(event.get("body", "{}"))
    application_id = body.get("applicationId")
    raw_notes = body.get("notes", "")

    if not application_id:
        return response(400, {"error": "applicationId required"})

    # Normalise notes to a bounded-length string (defensive; frontend already keeps it reasonable)
    notes = (raw_notes or "").strip()
    if len(notes) > 5000:
        notes = notes[:5000]

    table = dynamodb.Table(APPLICATIONS_TABLE)

    # Verify ownership and existence
    existing = table.get_item(
        Key={"userId": user_id, "applicationId": application_id}
    ).get("Item")
    if not existing:
        return response(404, {"error": "Application not found"})

    now = datetime.now(timezone.utc).isoformat()
    update_expr = "SET notes = :n, updatedAt = :t"
    expr_values = {
        ":n": notes,
        ":t": now,
    }

    table.update_item(
        Key={"userId": user_id, "applicationId": application_id},
        UpdateExpression=update_expr,
        ExpressionAttributeValues=expr_values,
    )

    return response(200, {"message": "Notes saved", "notes": notes, "updatedAt": now})

def handle_create_manual_application(event: dict) -> dict:
    """POST /api/applications/manual — Create an application the user found/applied to manually."""
    user_id = get_user_id(event)
    body = json.loads(event.get("body", "{}"))

    company_name = (body.get("companyName") or "").strip()
    job_title = (body.get("jobTitle") or "").strip()
    job_url = (body.get("jobUrl") or "").strip()
    job_description = (body.get("jobDescription") or "").strip()
    status = body.get("status") or "submitted"

    if not company_name and not job_title:
        return response(400, {"error": "companyName or jobTitle required"})
    if not job_url:
        return response(400, {"error": "jobUrl required"})

    allowed_statuses = {"matched", "review", "submitted", "interview", "offer", "rejected"}
    if status not in allowed_statuses:
        return response(400, {"error": f"Invalid status: {status}"})

    now = datetime.now(timezone.utc).isoformat()
    application_id = str(uuid.uuid4())

    # Attach user's primary CV so tailoring works for manual entries.
    cvs_table = dynamodb.Table(CVS_TABLE)
    cv_result = cvs_table.query(
        KeyConditionExpression="userId = :uid",
        ExpressionAttributeValues={":uid": user_id},
        Limit=1,
    )
    cv_items = cv_result.get("Items", [])
    if not cv_items:
        return response(400, {"error": "Please upload a CV first"})
    cv_id = cv_items[0]["cvId"]

    # Create a minimal job record so cv_tailor can load it by jobId.
    job_id = str(uuid.uuid4())
    jobs_table = dynamodb.Table(JOBS_TABLE)
    jobs_table.put_item(
        Item={
            "jobId": job_id,
            "title": job_title or "",
            "company": company_name or "",
            "url": job_url,
            "description": job_description,
            "source": "manual",
            "createdAt": now,
        }
    )

    item = {
        "userId": user_id,
        "applicationId": application_id,
        "status": status,
        "jobId": job_id,
        "cvId": cv_id,
        "companyName": company_name or None,
        "jobTitle": job_title or None,
        "jobUrl": job_url,
        "jobDescription": job_description or None,
        "source": "manual",
        "createdAt": now,
        "updatedAt": now,
    }

    # Remove None values (keeps DynamoDB item clean)
    item = {k: v for k, v in item.items() if v is not None}

    table = dynamodb.Table(APPLICATIONS_TABLE)
    table.put_item(Item=item)

    return response(200, {"message": "Manual application created", "application": item})


def handle_delete_account(event: dict) -> dict:
    """DELETE /api/account — Permanently erase every record and file for this user."""
    user_id = get_user_id(event)
    if user_id == "anonymous":
        return response(401, {"error": "Unauthorized"})

    errors = []

    # 1. Delete all application records
    try:
        apps_table = dynamodb.Table(APPLICATIONS_TABLE)
        result = apps_table.query(
            KeyConditionExpression="userId = :uid",
            ExpressionAttributeValues={":uid": user_id},
            ProjectionExpression="applicationId",
        )
        for item in result.get("Items", []):
            apps_table.delete_item(Key={"userId": user_id, "applicationId": item["applicationId"]})
    except (BotoCoreError, ClientError) as e:
        errors.append(f"applications: {e}")

    # 2. Delete all CV records
    try:
        cvs_table = dynamodb.Table(CVS_TABLE)
        result = cvs_table.query(
            KeyConditionExpression="userId = :uid",
            ExpressionAttributeValues={":uid": user_id},
            ProjectionExpression="cvId",
        )
        for item in result.get("Items", []):
            cvs_table.delete_item(Key={"userId": user_id, "cvId": item["cvId"]})
    except (BotoCoreError, ClientError) as e:
        errors.append(f"cvs: {e}")

    # 3. Delete all S3 objects under uploads/{userId}/ and tailored/{userId}/
    for prefix in [f"uploads/{user_id}/", f"tailored/{user_id}/"]:
        try:
            paginator = s3.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=CV_BUCKET, Prefix=prefix):
                for obj in page.get("Contents", []):
                    s3.delete_object(Bucket=CV_BUCKET, Key=obj["Key"])
        except (BotoCoreError, ClientError) as e:
            errors.append(f"s3 {prefix}: {e}")

    # 4. Delete user record (last — keeps auth working until everything else is gone)
    try:
        dynamodb.Table(USERS_TABLE).delete_item(Key={"userId": user_id})
    except (BotoCoreError, ClientError) as e:
        errors.append(f"user record: {e}")

    if errors:
        print(f"Delete account partial errors for {user_id}: {errors}")
        return response(207, {"message": "Account deleted with some errors", "errors": errors})

    print(f"Account fully deleted: {user_id}")
    return response(200, {"message": "Account deleted"})


def handle_get_tailored_cv(event: dict) -> dict:
    """GET /api/applications/tailored-cv?applicationId=xxx — Fetch the tailored CV JSON from S3."""
    user_id = get_user_id(event)
    params = event.get("queryStringParameters") or {}
    application_id = params.get("applicationId")

    if not application_id:
        return response(400, {"error": "applicationId required"})

    # Look up application to get the S3 key (also verifies ownership via userId PK)
    apps_table = dynamodb.Table(APPLICATIONS_TABLE)
    item = apps_table.get_item(
        Key={"userId": user_id, "applicationId": application_id}
    ).get("Item", {})

    tailored_cv_key = item.get("tailoredCvKey")
    if not tailored_cv_key:
        return response(404, {"error": "Tailored CV not ready yet"})

    obj = s3.get_object(Bucket=CV_BUCKET, Key=tailored_cv_key)
    cv_data = json.loads(obj["Body"].read().decode("utf-8"))

    return response(200, {"tailoredCV": cv_data})


def handle_create_checkout(event: dict) -> dict:
    """POST /api/payments/create-checkout — Create a Stripe Checkout session."""
    import stripe  # lazy import — only loaded for payment requests

    user_id = get_user_id(event)
    if user_id == "anonymous":
        return response(401, {"error": "Unauthorized"})

    stripe.api_key = get_stripe_secret_key()
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": "CV Tailoring Credits (3 tailors)"},
                    "unit_amount": 100,  # $1.00 in cents
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=f"{FRONTEND_URL}/payment/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{FRONTEND_URL}/payment/cancel",
            client_reference_id=user_id,
            metadata={"user_id": user_id, "credits": "3"},
        )
        return response(200, {"checkoutUrl": session.url})
    except stripe.error.StripeError as e:
        print(f"Stripe checkout error: {e}")
        return response(500, {"error": "Failed to create checkout session"})


def handle_stripe_webhook(event: dict) -> dict:
    """POST /api/payments/webhook — Process Stripe payment webhook.

    No JWT auth — Stripe signature is the authentication mechanism.
    """
    import stripe  # lazy import

    payload = event.get("body", "") or ""
    if event.get("isBase64Encoded"):
        payload = base64.b64decode(payload).decode("utf-8")

    sig_header = (event.get("headers") or {}).get("stripe-signature", "")
    webhook_secret = get_stripe_webhook_secret()

    try:
        stripe_event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except (ValueError, stripe.error.SignatureVerificationError) as e:
        print(f"Stripe webhook signature invalid: {e}")
        return response(400, {"error": "Invalid webhook signature"})

    if stripe_event["type"] == "checkout.session.completed":
        session = stripe_event["data"]["object"]
        user_id = session.get("client_reference_id") or session.get("metadata", {}).get("user_id", "")
        credits_to_add = int(session.get("metadata", {}).get("credits", "3"))

        if user_id:
            try:
                dynamodb.Table(USERS_TABLE).update_item(
                    Key={"userId": user_id},
                    UpdateExpression="ADD creditsBalance :n",
                    ExpressionAttributeValues={":n": Decimal(str(credits_to_add))},
                )
                print(f"Added {credits_to_add} credits to user {user_id}")
            except (BotoCoreError, ClientError) as e:
                print(f"Failed to credit user {user_id}: {e}")
                return response(500, {"error": "Failed to update credit balance"})

    return response(200, {"received": True})


def lambda_handler(event, context):
    """Main Lambda handler — routes requests based on path and method."""
    raw_path = event.get("rawPath", "")
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")

    print(f"Request: {method} {raw_path}")

    # Route mapping
    if method == "OPTIONS":
        return response(200, {})
    elif raw_path == "/api/profile" and method == "GET":
        return handle_get_profile(event)
    elif raw_path == "/api/applications" and method == "GET":
        return handle_get_applications(event)
    elif raw_path == "/api/applications" and method == "DELETE":
        return handle_delete_application(event)
    elif raw_path == "/api/account" and method == "DELETE":
        return handle_delete_account(event)
    elif raw_path == "/api/applications/tailor" and method == "POST":
        return handle_tailor_application(event)
    elif raw_path == "/api/applications/approve" and method == "POST":
        return handle_approve_application(event)
    elif raw_path == "/api/applications/status" and method == "PUT":
        return handle_update_application_status(event)
    elif raw_path == "/api/applications/notes" and method == "POST":
        return handle_save_application_notes(event)
    elif raw_path == "/api/applications/manual" and method == "POST":
        return handle_create_manual_application(event)
    elif raw_path == "/api/applications/tailored-cv" and method == "GET":
        return handle_get_tailored_cv(event)
    elif raw_path == "/api/upload-url" and method == "POST":
        return handle_get_upload_url(event)
    elif raw_path == "/api/career-goals" and method == "POST":
        return handle_save_career_goals(event)
    elif raw_path == "/api/career-goals" and method == "GET":
        return handle_get_career_goals(event)
    elif raw_path == "/api/jobs/scan" and method == "POST":
        return handle_scan_jobs(event)
    elif raw_path == "/api/payments/create-checkout" and method == "POST":
        return handle_create_checkout(event)
    elif raw_path == "/api/payments/webhook" and method == "POST":
        return handle_stripe_webhook(event)
    elif raw_path == "/api/health":
        return response(200, {"status": "healthy", "environment": ENVIRONMENT})
    else:
        return response(404, {"error": f"Not found: {method} {raw_path}"})
