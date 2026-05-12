"""Seed the three workload DynamoDB tables with defaults.

Idempotent: re-running won't duplicate UOMs or overwrite a config that was
already edited via the admin UI (only writes if `configKey="current"` is
missing). Run once after `cloudformation deploy` of `workload-dynamodb.yaml`.

Usage (with AWS credentials configured in the environment):

    python AA-lambda/scripts/seed_workload_tables.py
    python AA-lambda/scripts/seed_workload_tables.py --force-config   # overwrite rates
"""
from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path

# Reuse the canonical defaults from the Lambda module.
_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parent.parent / "functions" / "agent-workload"))

from handlers.calculate import DEFAULT_RATES  # noqa: E402
from handlers.storage   import DEFAULT_UOMS    # noqa: E402

import boto3  # noqa: E402


def _now_iso() -> str:
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def seed(force_config: bool = False) -> None:
    db = boto3.resource("dynamodb")
    config_table = db.Table("workload-config")
    uom_table    = db.Table("workload-uom")

    # --- config -------------------------------------------------------
    existing = config_table.get_item(Key={"configKey": "current"}).get("Item")
    if existing and not force_config:
        print("[config] already seeded; pass --force-config to overwrite")
    else:
        item = {
            "configKey": "current",
            **{k: Decimal(str(v)) for k, v in DEFAULT_RATES.items()},
            "updatedAt": _now_iso(),
            "updatedBy": "seed-script",
        }
        config_table.put_item(Item=item)
        print(f"[config] {'forced' if existing else 'seeded'} default rates ({len(DEFAULT_RATES)} keys)")

    # --- uom ---------------------------------------------------------
    inserted = 0
    for uom in DEFAULT_UOMS:
        # ConditionExpression avoids overwriting if user already added it.
        try:
            uom_table.put_item(
                Item={"uom": uom},
                ConditionExpression="attribute_not_exists(#u)",
                ExpressionAttributeNames={"#u": "uom"},
            )
            inserted += 1
        except db.meta.client.exceptions.ConditionalCheckFailedException:
            pass
    print(f"[uom]    inserted {inserted}/{len(DEFAULT_UOMS)} (skipped existing)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force-config", action="store_true",
                        help="Overwrite an existing 'current' config row.")
    args = parser.parse_args()
    seed(force_config=args.force_config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
