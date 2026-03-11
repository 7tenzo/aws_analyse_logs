#!/usr/bin/env python3
"""AWS Log Analyzer — unified CLI for analyzing logs across AWS services."""

import argparse
import re
import sys

from analyzers import cloudfront


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyze logs from various AWS services",
        epilog=(
            "Supported services:\n"
            "  cloudfront (cf)   CloudFront access logs (S3 legacy)\n"
            "\n"
            "AWS authentication:\n"
            "  awsume my-profile && %(prog)s cloudfront E1A2B3C4D5 --range 1h\n"
            "  %(prog)s cloudfront E1A2B3C4D5 --range 1h --profile my-profile\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Global flags (shared across all subcommands)
    parser.add_argument("--profile", dest="aws_profile", help="AWS profile name (compatible with awsume)")
    parser.add_argument("--region", dest="aws_region", help="AWS region override")
    parser.add_argument("--dry-run", action="store_true", help="Preview actions without executing")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--workers", "-w", type=int, default=10, help="Parallel download workers (default: 10)")

    # Time range (shared across all subcommands)
    time_group = parser.add_mutually_exclusive_group(required=True)
    time_group.add_argument("--range", "-r", dest="time_range", help="Relative time range: 30m, 1h, 7d, 2w")
    time_group.add_argument("--start", "-s", help="Start datetime (ISO 8601, UTC if no tz)")
    parser.add_argument("--end", "-e", help="End datetime (default: now). Used with --start")

    # Pattern (shared across all subcommands)
    parser.add_argument("--pattern", "-p", help="Regex pattern to search for in logs")
    parser.add_argument("--count", action="store_true", help="Show match count only")

    # Subcommands — one per AWS service
    subparsers = parser.add_subparsers(dest="service", help="AWS service to analyze")
    cloudfront.register_subparser(subparsers)
    # Future: alb.register_subparser(subparsers)
    # Future: waf.register_subparser(subparsers)
    # Future: apigateway.register_subparser(subparsers)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if not args.service:
        parser.print_help()
        sys.exit(1)

    if args.end and not args.start:
        parser.error("--end requires --start")

    if args.pattern:
        try:
            re.compile(args.pattern)
        except re.error as exc:
            parser.error(f"invalid regex pattern: {exc}")

    # Lazy import so --help works without boto3
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

    args.handler(args, session)


if __name__ == "__main__":
    main()
