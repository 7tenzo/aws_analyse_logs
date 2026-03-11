"""CloudFront log analyzer — retrieves and analyzes CloudFront access logs from S3."""

import argparse
import re
import sys
from datetime import datetime, timedelta
from typing import NamedTuple

from analyzers.common import (
    AnalysisResult,
    list_s3_objects,
    parse_time_range,
    process_logs,
)


class LoggingConfig(NamedTuple):
    enabled: bool
    bucket: str
    prefix: str


def register_subparser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'cloudfront' subcommand."""
    parser = subparsers.add_parser(
        "cloudfront",
        aliases=["cf"],
        help="Analyze CloudFront access logs",
        description="Retrieve and analyze AWS CloudFront access logs from S3",
    )
    parser.add_argument("distribution_id", help="CloudFront distribution ID")
    parser.set_defaults(handler=run)


def get_logging_config(cf_client, distribution_id: str) -> LoggingConfig:
    resp = cf_client.get_distribution_config(Id=distribution_id)
    logging_cfg = resp["DistributionConfig"]["Logging"]

    enabled = logging_cfg.get("Enabled", False)
    # Bucket comes as "mybucket.s3.amazonaws.com"
    raw_bucket = logging_cfg.get("Bucket", "")
    bucket = re.sub(r"\.s3\.amazonaws\.com$", "", raw_bucket)
    prefix = logging_cfg.get("Prefix", "")

    return LoggingConfig(enabled=enabled, bucket=bucket, prefix=prefix)


def build_s3_prefixes(
    prefix: str,
    distribution_id: str,
    start: datetime,
    end: datetime,
) -> list[str]:
    """Build S3 key prefixes exploiting CloudFront naming: {prefix}{distid}.YYYY-MM-DD-HH."""
    hours = int((end - start).total_seconds() / 3600) + 1

    # For ranges > 48h, use daily prefixes to reduce list calls
    if hours > 48:
        prefixes = []
        current = start.replace(hour=0, minute=0, second=0, microsecond=0)
        while current <= end:
            prefixes.append(f"{prefix}{distribution_id}.{current:%Y-%m-%d-}")
            current += timedelta(days=1)
        return prefixes

    prefixes = []
    current = start.replace(minute=0, second=0, microsecond=0)
    while current <= end:
        prefixes.append(f"{prefix}{distribution_id}.{current:%Y-%m-%d-%H}.")
        current += timedelta(hours=1)
    return prefixes


def run(args: argparse.Namespace, session) -> None:
    """Execute the CloudFront log analysis pipeline."""
    from botocore.exceptions import ClientError

    start, end = parse_time_range(args.time_range, args.start, args.end)

    if args.verbose:
        print(
            f"Distribution: {args.distribution_id}\n"
            f"Time range: {start.isoformat()} -> {end.isoformat()}",
            file=sys.stderr,
        )

    cf_client = session.client("cloudfront")

    try:
        config = get_logging_config(cf_client, args.distribution_id)
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code == "NoSuchDistribution":
            print(f"Error: distribution {args.distribution_id} not found", file=sys.stderr)
        elif code in ("AccessDenied", "403"):
            print("Error: access denied. Check cloudfront:GetDistributionConfig permission", file=sys.stderr)
        else:
            print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if not config.enabled:
        print(f"Error: logging is not enabled for distribution {args.distribution_id}", file=sys.stderr)
        sys.exit(1)

    if args.verbose:
        print(f"Logging bucket: {config.bucket}\nLogging prefix: {config.prefix}", file=sys.stderr)

    prefixes = build_s3_prefixes(config.prefix, args.distribution_id, start, end)
    s3_client = session.client("s3")

    if args.verbose:
        print(f"Listing log files ({len(prefixes)} prefix queries)...", file=sys.stderr)

    keys = list_s3_objects(s3_client, config.bucket, prefixes, verbose=args.verbose)

    if not keys:
        print("No log files found for the specified time range", file=sys.stderr)
        sys.exit(0)

    if args.dry_run:
        print(f"Distribution: {args.distribution_id}")
        print(f"Logging bucket: {config.bucket}")
        print(f"Logging prefix: {config.prefix}")
        print(f"Time range: {start.isoformat()} -> {end.isoformat()}")
        print(f"\nWould download {len(keys)} log file(s):")
        for key in keys:
            print(f"  {key}")
        return

    if args.verbose:
        print(f"Downloading and analyzing {len(keys)} log file(s)...", file=sys.stderr)

    result = process_logs(
        s3_client,
        config.bucket,
        keys,
        pattern=args.pattern,
        count_only=args.count,
        verbose=args.verbose,
        workers=args.workers,
    )

    summary = (
        f"\nScanned {result.total_files} file(s), {result.total_lines} line(s)\n"
        f"Pattern: {args.pattern or '(all)'}\n"
        f"Matches: {result.matched_lines}"
    )
    print(summary, file=sys.stderr)

    if not args.count:
        for line in result.matches:
            print(line)
