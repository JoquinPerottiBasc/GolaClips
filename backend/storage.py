"""Cloudflare R2 storage operations for GolaClips (boto3/S3-compatible API)."""

import os

import boto3
from botocore.client import Config


def is_configured() -> bool:
    return bool(
        os.getenv("R2_ACCOUNT_ID")
        and os.getenv("R2_ACCESS_KEY_ID")
        and os.getenv("R2_SECRET_ACCESS_KEY")
    )


def _get_client():
    account_id = os.getenv("R2_ACCOUNT_ID")
    return boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=os.getenv("R2_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY"),
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def _bucket() -> str:
    return os.getenv("R2_BUCKET_NAME", "golaclips-clips")


def upload_clip(local_path: str, r2_key: str) -> str:
    """Upload a local clip file to R2. Returns the r2_key."""
    if not is_configured():
        return r2_key
    client = _get_client()
    with open(local_path, "rb") as f:
        client.put_object(
            Bucket=_bucket(),
            Key=r2_key,
            Body=f,
            ContentType="video/mp4",
        )
    return r2_key


def get_presigned_url(r2_key: str, expires_in: int = 3600) -> str:
    """Generate a presigned URL valid for expires_in seconds (default 1 hour)."""
    if not is_configured() or not r2_key:
        return ""
    client = _get_client()
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": _bucket(), "Key": r2_key},
        ExpiresIn=expires_in,
    )


def delete_objects(r2_keys: list):
    """Delete multiple objects from R2 in a single request."""
    if not r2_keys or not is_configured():
        return
    client = _get_client()
    client.delete_objects(
        Bucket=_bucket(),
        Delete={"Objects": [{"Key": k} for k in r2_keys]},
    )
