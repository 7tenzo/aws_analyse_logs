# aws-log-analyzer

Unified CLI to retrieve and analyze logs from AWS services.

## TL;DR

```bash
# Setup
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Or with uv
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt

# Run
awsume my-profile
./main.py cloudfront E1A2B3C4D5 --range 1h --dry-run
```

## Supported services

| Service | Subcommand | Alias | Log source |
|---------|-----------|-------|------------|
| CloudFront | `cloudfront` | `cf` | S3 legacy (W3C) |

More services coming (ALB, WAF, API Gateway...).

## Prerequisites

- Python 3.10+
- AWS credentials (awsume, profile, env vars, or instance role)

### IAM permissions (CloudFront)

```
cloudfront:GetDistributionConfig
s3:ListBucket   (on the logging bucket)
s3:GetObject    (on the logging bucket)
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
chmod +x main.py
```

## AWS authentication

The tool uses the standard boto3 credential chain:

```bash
# awsume (recommended)
awsume my-profile
./main.py cloudfront E1A2B3C4D5 --range 1h

# --profile flag
./main.py cloudfront E1A2B3C4D5 --range 1h --profile my-profile

# AWS_PROFILE env var
export AWS_PROFILE=my-profile
./main.py cloudfront E1A2B3C4D5 --range 1h

# EC2/ECS instance role — works automatically
```

## Usage

```
./main.py [global flags] <service> [service args]
```

### Global flags

| Flag | Description |
|------|-------------|
| `--range` / `-r` | Relative time range: `30m`, `1h`, `7d`, `2w` |
| `--start` / `-s` | Start datetime (ISO 8601) |
| `--end` / `-e` | End datetime (default: now) |
| `--pattern` / `-p` | Regex pattern to search in logs |
| `--count` | Show match count only |
| `--dry-run` | Preview files without downloading |
| `--verbose` / `-v` | Verbose output |
| `--workers` / `-w` | Parallel download threads (default: 10) |
| `--profile` | AWS profile name |
| `--region` | AWS region override |

### Examples

```bash
# Dry-run: list log files for the last hour
./main.py cloudfront E1A2B3C4D5 --range 1h --dry-run

# Fetch all logs from the last 30 minutes
./main.py cf E1A2B3C4D5 --range 30m

# Count 5xx errors in the last 7 days
./main.py cloudfront E1A2B3C4D5 --range 7d -p '\t5[0-9]{2}\t' --count

# Custom time range with pattern
./main.py cloudfront E1A2B3C4D5 \
  --start 2026-03-10T00:00:00 \
  --end 2026-03-10T12:00:00 \
  -p 'POST' -v

# Pipe results
./main.py cf E1A2B3C4D5 --range 1h -p '/api/error' > errors.txt
```

## Architecture

```
main.py                    # Entry point — routes to service analyzers
analyzers/
├── __init__.py
├── common.py              # Shared: time parsing, S3 download, log processing
└── cloudfront.py          # CloudFront-specific logic
```

To add a new service analyzer:
1. Create `analyzers/<service>.py` with `register_subparser()` and `run()` functions
2. Import and register in `main.py`'s `build_parser()`
