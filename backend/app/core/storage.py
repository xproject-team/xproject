"""S3-compatible object storage client (MinIO in dev, S3 in prod).

Wraps boto3 with project-specific defaults:
- Bucket name from settings (default: xproject-attachments)
- Endpoint URL (MinIO local OR AWS in prod)
- Tenant-scoped object key prefixing
- Presigned URL generation for direct browser uploads/downloads

Note: we use boto3 (sync) rather than aioboto3 because:
1. Presigned URL generation is local string-signing — no I/O
2. The browser does the actual upload directly to MinIO (no backend I/O)
3. Adding aioboto3 doubles the dependency surface for ~zero benefit
"""
import os
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import boto3
from botocore.client import Config


# ─── Configuration ─────────────────────────────────────────────────────

# Endpoints differ between local Docker (where api talks to minio:9000)
# and the host browser (which talks to localhost:9000). We keep both.
# Load .env explicitly so this module sees overrides regardless of
# whether the parent process exported them.
try:
    from dotenv import load_dotenv as _ld
    from pathlib import Path as _P
    _ld(_P(__file__).resolve().parent.parent.parent.parent / ".env", override=False)
except Exception:  # noqa: BLE001
    pass

S3_ENDPOINT_INTERNAL = os.getenv("S3_ENDPOINT_INTERNAL", "http://minio:9000")
S3_ENDPOINT_PUBLIC   = os.getenv("S3_ENDPOINT_PUBLIC",   "http://localhost:9000")

S3_REGION       = os.getenv("S3_REGION", "us-east-1")
S3_ACCESS_KEY   = os.getenv("S3_ACCESS_KEY",  "xproject")
S3_SECRET_KEY   = os.getenv("S3_SECRET_KEY",  "xproject-dev-secret")
S3_BUCKET       = os.getenv("S3_BUCKET",      "xproject-attachments")

# Presigned URL TTLs
PRESIGN_UPLOAD_EXPIRY_SEC   = 600        # 10 min — upload window
PRESIGN_DOWNLOAD_EXPIRY_SEC = 3600 * 24  # 1 day — download links


def _make_client(endpoint: str):
    """Build a boto3 S3 client for a given endpoint. Internal vs public matters
    because the URLs in presigned-PUTs/GETs need to be reachable by the caller.
    """
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
        region_name=S3_REGION,
        # Path-style is required for MinIO (vs subdomain-style for AWS S3).
        # AWS S3 also accepts path-style, so this works for both.
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


# ─── Singletons ────────────────────────────────────────────────────────

# Two clients: one for backend↔storage talking (internal endpoint),
# another for generating URLs the browser will use (public endpoint).
_internal_client = _make_client(S3_ENDPOINT_INTERNAL)
_public_client   = _make_client(S3_ENDPOINT_PUBLIC)


# ─── Public API ────────────────────────────────────────────────────────

def make_object_key(tenant_id: UUID, channel_id: UUID, original_filename: str) -> str:
    """Build a tenant- and channel-scoped object key.

    Format: <tenant_id>/<channel_id>/<random-uuid>.<ext>
    The random UUID prevents filename collisions and obscures original names.
    """
    ext = ""
    if "." in original_filename:
        # Take the last extension only, lowercased
        ext = "." + original_filename.rsplit(".", 1)[-1].lower()
        # Sanity: cap extension length to avoid abuse
        if len(ext) > 16:
            ext = ""
    return f"{tenant_id}/{channel_id}/{uuid4()}{ext}"


def presigned_upload_url(
    object_key:  str,
    content_type: str,
) -> str:
    """Generate a presigned PUT URL the browser uses to upload directly to MinIO.

    Returns a URL valid for PRESIGN_UPLOAD_EXPIRY_SEC seconds.
    The URL embeds permission for exactly one PUT operation on this key with
    the specified content type. Browser does:
        PUT <url> with body=<file bytes>, Content-Type: <content_type>
    """
    return _public_client.generate_presigned_url(
        ClientMethod="put_object",
        Params={
            "Bucket":      S3_BUCKET,
            "Key":         object_key,
            "ContentType": content_type,
        },
        ExpiresIn=PRESIGN_UPLOAD_EXPIRY_SEC,
        HttpMethod="PUT",
    )


def public_download_url(object_key: str) -> str:
    """Build the direct-download URL for an object.

    Since our bucket is set to allow anonymous downloads, this is just the
    plain HTTP URL (no signing required). For private buckets we'd switch
    to presigned GET URLs.
    """
    return f"{S3_ENDPOINT_PUBLIC}/{S3_BUCKET}/{object_key}"


def head_object(object_key: str) -> dict[str, Any] | None:
    """Verify an object exists in the bucket. Returns None if not found.

    Used after the browser claims to have uploaded — we confirm with MinIO
    before persisting metadata, preventing fake-upload abuse.
    """
    try:
        return _internal_client.head_object(Bucket=S3_BUCKET, Key=object_key)
    except _internal_client.exceptions.ClientError:
        return None


def delete_object(object_key: str) -> None:
    """Delete an object. Used when a message with attachments is deleted."""
    _internal_client.delete_object(Bucket=S3_BUCKET, Key=object_key)
