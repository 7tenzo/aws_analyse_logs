#!/usr/bin/env python3
"""AWS Log Analyzer — unified CLI for analyzing logs across AWS services."""

import argparse
import re
import sys

from analyzers import cloudfront

# Registry: service name -> (aliases, handler, extra_args_fn, help)
SERVICES: dict[str, tuple] = {}


def _register(name: str, aliases: list[str], handler, extra_args_fn, help_text: str) -> None:
    entry = (name, handler, extra_args_fn, help_text)
    SERVICES[name] = entry
    for alias in aliases:
        SERVICES[alias] = entry


def _add_cloudfront_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("resource_id", help="CloudFront distribution ID")


_register("cloudfront", ["cf"], cloudfront.run, _add_cloudfront_args, "CloudFront access logs (S3 legacy)")
# Future: _register("alb", ["lb"], alb.run, _add_alb_args, "ALB access logs")


def build_parser(service_name: str | None = None) -> argparse.ArgumentParser:
    service_list = "\n".join(
        f"  {name:<16} {entry[3]}"
        for name, entry in SERVICES.items()
        if entry[0] == name  # skip aliases
    )

    parser = argparse.ArgumentParser(
        description="Analyze logs from various AWS services",
        epilog=(
            f"Supported services:\n{service_list}\n"
            "\n"
            "AWS authentication:\n"
            "  awsume my-profile && %(prog)s cloudfront E1A2B3C4D5 --range 1h\n"
            "  %(prog)s cloudfront E1A2B3C4D5 --range 1h --profile my-profile\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument("service", choices=list(SERVICES.keys()), help="AWS service to analyze")
    parser.add_argument("--profile", dest="aws_profile", help="AWS profile name (compatible with awsume)")
    parser.add_argument("--region", dest="aws_region", help="AWS region override")
    parser.add_argument("--dry-run", action="store_true", help="Preview actions without executing")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--workers", "-w", type=int, default=10, help="Parallel download workers (default: 10)")

    time_group = parser.add_mutually_exclusive_group(required=True)
    time_group.add_argument("--range", "-r", dest="time_range", help="Relative time range: 30m, 1h, 7d, 2w")
    time_group.add_argument("--start", "-s", help="Start datetime (ISO 8601, UTC if no tz)")
    parser.add_argument("--end", "-e", help="End datetime (default: now). Used with --start")

    parser.add_argument("--pattern", "-p", help="Regex pattern to search for in logs")
    parser.add_argument("--count", action="store_true", help="Show match count only")

    # Add service-specific args if we know the service
    if service_name and service_name in SERVICES:
        SERVICES[service_name][2](parser)

    return parser


def _detect_service() -> str | None:
    """Scan argv for a known service name (works regardless of flag positions)."""
    for arg in sys.argv[1:]:
        if arg in SERVICES:
            return arg
    return None


def main() -> None:
    parser = build_parser(_detect_service())
    args = parser.parse_args()

    if args.end and not args.start:
        parser.error("--end requires --start")

    if args.pattern:
        try:
            re.compile(args.pattern)
        except re.error as exc:
            parser.error(f"invalid regex pattern: {exc}")

    try:
        import boto3
    except ImportError:
        print("Error: boto3 is required. Install with: pip install -r requirements.txt", file=sys.stderr)
        sys.exit(1)

    session_kwargs = {}
    if args.aws_profile:
        session_kwargs["profile_name"] = args.aws_profile
    if args.aws_region:
        session_kwargs["region_name"] = args.aws_region
    session = boto3.Session(**session_kwargs)

    creds = session.get_credentials()
    frozen = creds.get_frozen_credentials() if creds else None

    # Resolve canonical service name from alias
    canonical_name = SERVICES[args.service][0]

    print(
        "\n"
        "=== AWS Log Analyzer ===\n"
        "\n"
        f"  AWS profile  : {session.profile_name or '(default/env)'}\n"
        f"  AWS region   : {session.region_name or '(not set)'}\n"
        f"  AWS identity : {'configured' if frozen and frozen.access_key else 'NOT FOUND'}\n"
        "\n"
        f"  Service      : {canonical_name}\n"
        f"  Resource ID  : {getattr(args, 'resource_id', 'N/A')}\n"
        f"  Time range   : {args.time_range or (args.start + ' -> ' + (args.end or 'now'))}\n"
        f"  Pattern      : {args.pattern or '(all lines)'}\n"
        f"  Count only   : {args.count}\n"
        f"  Dry run      : {args.dry_run}\n"
        f"  Workers      : {args.workers}\n",
        file=sys.stderr,
    )

    if not frozen or not frozen.access_key:
        print("Error: no AWS credentials found. Use awsume or --profile.", file=sys.stderr)
        sys.exit(1)

    _, handler, _, _ = SERVICES[args.service]
    handler(args, session)


if __name__ == "__main__":
    main()
