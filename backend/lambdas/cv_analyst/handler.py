"""
CV Analyst Lambda — Triggered by S3 upload.
Parses uploaded CV (PDF/DOCX), extracts structured data using Claude,
and stores the result in DynamoDB.
"""

import io
import json
import os
from datetime import datetime, timezone

import anthropic
import boto3
from botocore.exceptions import BotoCoreError, ClientError

# Initialize AWS clients
s3 = boto3.client("s3")
sqs = boto3.client("sqs")
dynamodb = boto3.resource("dynamodb")
ssm = boto3.client("ssm")

# Environment
CV_BUCKET = os.environ.get("CV_BUCKET", "aiapply-dev-cv-storage")
ANTHROPIC_PARAM_NAME = os.environ.get("ANTHROPIC_PARAM_NAME", "")
ENVIRONMENT = os.environ.get("ENVIRONMENT", "dev")
SQS_JOB_SCOUT_URL = os.environ.get("SQS_JOB_SCOUT_URL", "")

# Table names
CVS_TABLE = f"aiapply-{ENVIRONMENT}-cvs"
USERS_TABLE = f"aiapply-{ENVIRONMENT}-users"

# Cache the API key across invocations
_anthropic_client = None


def get_anthropic_client():
    """Get or create Anthropic client with cached API key."""
    global _anthropic_client
    if _anthropic_client is None:
        if ANTHROPIC_PARAM_NAME:
            param = ssm.get_parameter(Name=ANTHROPIC_PARAM_NAME, WithDecryption=True)
            api_key = param["Parameter"]["Value"]
        else:
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        _anthropic_client = anthropic.Anthropic(api_key=api_key)
    return _anthropic_client


def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extract text from a PDF file."""
    from PyPDF2 import PdfReader

    reader = PdfReader(io.BytesIO(file_bytes))
    text = ""
    for page in reader.pages:
        text += page.extract_text() or ""
    return text


def extract_text_from_docx(file_bytes: bytes) -> str:
    """Extract visible text and hyperlink targets from a DOCX file."""
    from docx import Document
    from docx.oxml.ns import qn

    doc = Document(io.BytesIO(file_bytes))
    lines = []
    for para in doc.paragraphs:
        line = para.text
        links = []
        for hyperlink in para._p.xpath(".//w:hyperlink"):
            relationship_id = hyperlink.get(qn("r:id"))
            if relationship_id and relationship_id in doc.part.rels:
                target = doc.part.rels[relationship_id].target_ref
                if target not in links:
                    links.append(target)
        if links:
            line = f"{line} [Links: {', '.join(links)}]"
        lines.append(line)
    return "\n".join(lines)


def parse_cv_with_claude(cv_text: str) -> dict:
    """Use Claude to extract structured data from CV text."""
    client = get_anthropic_client()

    message = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=8192,
        messages=[
            {
                "role": "user",
                "content": f"""Extract this CV into structured data without summarizing, improving, or inferring anything.

FACTUAL FIDELITY RULES:
- Treat the CV text as the only source of truth.
- Preserve every role, project, bullet, certification, degree, date, metric, and contact detail.
- Copy job titles, employer names, dates, metrics, and claims exactly as written.
- If a date or value is absent, use null. Never infer it from role ordering or adjacent entries.
- Do not upgrade seniority, scope, ownership, leadership, scale, or business impact.
- Do not turn contributing to, deploying onto, or operating a system into architecting or owning it.
- Preserve project content in the projects array; never fold projects into employment or drop them.
- Hyperlink labels such as Email, GitHub, LinkedIn, or Blogsite may lack their underlying URL in extracted text. Use null rather than phrases such as "Not provided in CV".

Return ONLY valid JSON with this exact structure:

{{
  "name": "Full Name",
  "email": "email@example.com or null",
  "phone": "phone number or null",
  "location": "city, country or null",
  "links": [{{"label": "GitHub", "url": null}}],
  "summary": "2-3 sentence professional summary",
  "skills": ["skill1", "skill2", ...],
  "experience": [
    {{
      "title": "Job Title",
      "company": "Company Name",
      "startDate": "exact source value or null",
      "endDate": "exact source value or null",
      "description": "role description from the source, or null",
      "highlights": ["every source bullet, faithfully preserved"]
    }}
  ],
  "projects": [
    {{
      "name": "Project name",
      "description": "project description from the source",
      "highlights": ["every source bullet, faithfully preserved"]
    }}
  ],
  "education": [
    {{
      "degree": "Degree Name",
      "institution": "University/School",
      "year": "Graduation year",
      "field": "Field of study"
    }}
  ],
  "certifications": ["cert1", "cert2"],
  "languages": ["language1", "language2"],
  "totalYearsExperience": 5,
  "seniorityLevel": "junior|mid|senior|lead|executive"
}}

CV Text:
{cv_text}""",
            }
        ],
    )

    # Extract JSON from response
    response_text = message.content[0].text
    # Handle case where Claude wraps JSON in markdown code blocks
    if "```json" in response_text:
        response_text = response_text.split("```json")[1].split("```")[0]
    elif "```" in response_text:
        response_text = response_text.split("```")[1].split("```")[0]

    return json.loads(response_text.strip())


def lambda_handler(event, context):
    """
    Triggered by S3 ObjectCreated event when a CV is uploaded.
    Expected S3 key format: uploads/{userId}/{cvId}.pdf
    """
    try:
        # Get S3 event details
        record = event["Records"][0]
        bucket = record["s3"]["bucket"]["name"]
        key = record["s3"]["object"]["key"]

        print(f"Processing CV upload: s3://{bucket}/{key}")

        # Parse user ID and CV ID from key
        # Expected format: uploads/{userId}/{filename}
        parts = key.split("/")
        if len(parts) < 3:
            print(f"Unexpected key format: {key}")
            return {"statusCode": 400, "body": "Invalid key format"}

        user_id = parts[1]
        file_name = parts[2]
        cv_id = file_name.rsplit(".", 1)[0]  # Remove extension

        # Download file from S3
        response = s3.get_object(Bucket=bucket, Key=key)
        file_bytes = response["Body"].read()
        file_type = key.rsplit(".", 1)[-1].lower()

        # Extract text based on file type
        if file_type == "pdf":
            cv_text = extract_text_from_pdf(file_bytes)
        elif file_type == "docx":
            cv_text = extract_text_from_docx(file_bytes)
        else:
            return {"statusCode": 400, "body": f"Unsupported file type: {file_type}"}

        if not cv_text.strip():
            return {"statusCode": 400, "body": "Could not extract text from CV"}

        print(f"Extracted {len(cv_text)} chars from {file_type}")

        # Parse CV with Claude
        structured_data = parse_cv_with_claude(cv_text)
        print(f"Extracted structured data: {json.dumps(structured_data)[:200]}...")

        # Store in DynamoDB
        table = dynamodb.Table(CVS_TABLE)

        # Only the most recently uploaded CV is primary. Keep older records so
        # submitted applications retain their history, but stop selecting them
        # for new tailoring work.
        existing_cvs = table.query(
            KeyConditionExpression="userId = :uid",
            ExpressionAttributeValues={":uid": user_id},
            ProjectionExpression="userId, cvId",
        ).get("Items", [])
        for existing_cv in existing_cvs:
            if existing_cv.get("cvId") != cv_id:
                table.update_item(
                    Key={"userId": user_id, "cvId": existing_cv["cvId"]},
                    UpdateExpression="SET isPrimary = :false",
                    ExpressionAttributeValues={":false": False},
                )

        table.put_item(
            Item={
                "userId": user_id,
                "cvId": cv_id,
                "fileName": file_name,
                "fileType": file_type,
                "s3Key": key,
                "structuredData": json.dumps(structured_data),
                "skills": structured_data.get("skills", []),
                "name": structured_data.get("name", ""),
                "experienceYears": str(structured_data.get("totalYearsExperience", 0)),
                "seniorityLevel": structured_data.get("seniorityLevel", ""),
                "isPrimary": True,
                "uploadedAt": datetime.now(timezone.utc).isoformat(),
            }
        )

        print(f"Saved CV data for user {user_id}, cv {cv_id}")

        # Race-condition guard: if the user already saved career goals before
        # cv_analyst finished, the career-goals handler would have found no CV
        # and skipped triggering job_scout. Check now and fire it ourselves.
        users_table = dynamodb.Table(USERS_TABLE)
        user_item = users_table.get_item(Key={"userId": user_id}).get("Item", {})
        if user_item.get("careerGoals"):
            try:
                if SQS_JOB_SCOUT_URL:
                    queue_url = SQS_JOB_SCOUT_URL
                else:
                    account_id = boto3.client("sts").get_caller_identity()["Account"]
                    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
                    queue_url = f"https://sqs.{region}.amazonaws.com/{account_id}/aiapply-{ENVIRONMENT}-job-scout"
                sqs.send_message(
                    QueueUrl=queue_url,
                    MessageBody=json.dumps({"userId": user_id, "cvId": cv_id}),
                )
                print(f"Career goals already exist — triggered job scout for user {user_id}, cv {cv_id}")
            except (BotoCoreError, ClientError) as sqs_err:
                print(f"Warning: could not trigger job scout: {sqs_err}")
        else:
            print(f"No career goals yet for user {user_id} — job scout will trigger when goals are saved")

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "message": "CV processed successfully",
                    "userId": user_id,
                    "cvId": cv_id,
                    "skills": structured_data.get("skills", []),
                    "name": structured_data.get("name", ""),
                }
            ),
        }

    except (BotoCoreError, ClientError, KeyError, TypeError, ValueError, json.JSONDecodeError, anthropic.APIError) as e:
        print(f"Error processing CV: {e!s}")
        import traceback
        traceback.print_exc()
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}
