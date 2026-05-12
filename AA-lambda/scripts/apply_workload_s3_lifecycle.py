"""
Idempotently add a 1-day lifecycle rule for the `workload-uploads/` prefix on
the project's shared bucket WITHOUT disturbing rules already configured for
gmail-attachments/, drive-downloads/, temp-uploads/, etc.

CloudFormation can't merge into an existing bucket's lifecycle config (the
`AWS::S3::Bucket` resource owns ALL the rules), so we do a safe read-merge-
write through the S3 API instead.

Run once after a deploy:
    python AA-lambda/scripts/apply_workload_s3_lifecycle.py
    python AA-lambda/scripts/apply_workload_s3_lifecycle.py --bucket frontend-safexpress
    python AA-lambda/scripts/apply_workload_s3_lifecycle.py --remove   # take the rule back out

The rule:
    ID     : workload-uploads-1day-expire
    Filter : Prefix=workload-uploads/
    Action : Expiration after 1 day
    Status : Enabled

Rerunning the script is safe: it replaces only the rule with the matching
ID, leaving everything else untouched.
"""
from __future__ import annotations

import argparse
import json
import sys

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    print("boto3 is required: pip install boto3", file=sys.stderr)
    sys.exit(1)


RULE_ID    = "workload-uploads-1day-expire"
PREFIX     = "workload-uploads/"
TTL_DAYS   = 1
DEFAULT_BUCKET = "frontend-safexpress"


def _fetch_existing_rules(s3, bucket: str):
    try:
        resp = s3.get_bucket_lifecycle_configuration(Bucket=bucket)
        return resp.get("Rules", [])
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code in ("NoSuchLifecycleConfiguration", "NoSuchConfiguration"):
            return []  # bucket has no lifecycle yet
        raise


def _build_rule():
    return {
        "ID":     RULE_ID,
        "Status": "Enabled",
        # `Filter` (not `Prefix`) is the modern shape required when other
        # rules in the bucket already use Filter — mixing them is a hard
        # InvalidArgument from S3.
        "Filter": {"Prefix": PREFIX},
        "Expiration": {"Days": TTL_DAYS},
        # Belt-and-suspenders for incomplete multipart uploads under this
        # prefix (cheap, prevents stuck-upload storage charges).
        "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 1},
    }


def apply(bucket: str, remove: bool = False, dry_run: bool = False) -> None:
    s3 = boto3.client("s3")
    existing = _fetch_existing_rules(s3, bucket)
    other_rules = [r for r in existing if r.get("ID") != RULE_ID]

    if remove:
        new_rules = other_rules
        action = f"removing rule {RULE_ID!r}"
    else:
        new_rules = other_rules + [_build_rule()]
        action = f"adding/updating rule {RULE_ID!r}"

    print(f"Bucket            : {bucket}")
    print(f"Existing rule IDs : {[r.get('ID') for r in existing]}")
    print(f"Action            : {action}")
    print(f"Resulting rule IDs: {[r.get('ID') for r in new_rules]}")

    if dry_run:
        print("\n[dry-run] PutBucketLifecycleConfiguration payload:")
        print(json.dumps({"Rules": new_rules}, indent=2, default=str))
        return

    if not new_rules:
        # S3 doesn't accept an empty Rules list; remove the lifecycle config.
        s3.delete_bucket_lifecycle(Bucket=bucket)
        print("Deleted lifecycle configuration (was empty after removal).")
        return

    s3.put_bucket_lifecycle_configuration(
        Bucket=bucket,
        LifecycleConfiguration={"Rules": new_rules},
    )
    print("OK.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", default=DEFAULT_BUCKET,
                        help=f"Bucket name (default: {DEFAULT_BUCKET})")
    parser.add_argument("--remove", action="store_true",
                        help="Remove the rule instead of adding/updating it.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be written without calling S3.")
    args = parser.parse_args()
    apply(args.bucket, remove=args.remove, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
