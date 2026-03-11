"""Shared utilities for all AWS log analyzers."""

import gzip
import io
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import NamedTuple


class AnalysisResult(NamedTuple):
    total_files: int
    total_lines: int
    matched_lines: int


def parse_time_range(
    relative: str | None,
    start: str | None,
    end: str | None,
) -> tuple[datetime, datetime]:
    """Parse relative ('1h','30m','7d','2w') or absolute start/end into UTC datetimes."""
    now = datetime.now(timezone.utc)

    if relative:
        match = re.fullmatch(r"(\d+)([mhdw])", relative)
        if not match:
            raise ValueError(f"Invalid relative range: {relative!r}. Use e.g. 30m, 1h, 7d, 2w")
        value, unit = int(match.group(1)), match.group(2)
        deltas = {"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}
        delta = timedelta(**{deltas[unit]: value})
        return now - delta, now

    dt_start = datetime.fromisoformat(start)
    if dt_start.tzinfo is None:
        dt_start = dt_start.replace(tzinfo=timezone.utc)

    if end:
        dt_end = datetime.fromisoformat(end)
        if dt_end.tzinfo is None:
            dt_end = dt_end.replace(tzinfo=timezone.utc)
    else:
        dt_end = now

    if dt_start >= dt_end:
        raise ValueError("Start must be before end")

    return dt_start, dt_end


def list_s3_objects(
    s3_client,
    bucket: str,
    prefixes: list[str],
    suffix: str = ".gz",
    verbose: bool = False,
) -> list[str]:
    """List S3 objects matching any of the given prefixes."""
    keys = set()
    paginator = s3_client.get_paginator("list_objects_v2")

    for pfx in prefixes:
        if verbose:
            print(f"  Listing s3://{bucket}/{pfx}*", file=sys.stderr)
        for page in paginator.paginate(Bucket=bucket, Prefix=pfx):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key.endswith(suffix):
                    keys.add(key)

    return sorted(keys)


def download_and_decompress(s3_client, bucket: str, key: str) -> str:
    """Download a .gz S3 object and decompress in memory."""
    body = s3_client.get_object(Bucket=bucket, Key=key)["Body"].read()
    with gzip.GzipFile(fileobj=io.BytesIO(body)) as gz:
        return gz.read().decode("utf-8")


def process_logs(
    s3_client,
    bucket: str,
    keys: list[str],
    pattern: str | None,
    count_only: bool,
    verbose: bool,
    workers: int,
    output_stream=None,
    skip_prefix: str = "#",
    batch_size: int = 50,
) -> AnalysisResult:
    """Download, decompress and analyze log files in parallel batches.

    Processes files in batches to bound memory usage. Matching lines are
    streamed immediately instead of accumulated in memory.
    When output_stream is a file (not stdout), lines are also echoed to stderr.
    """
    if output_stream is None:
        output_stream = sys.stdout
    # Tee to stderr when output goes to a file so user sees matches in terminal
    tee_to_stderr = output_stream is not sys.stdout

    regex = re.compile(pattern) if pattern else None
    total_lines = 0
    matched_lines = 0
    processed = 0

    def _download(key: str) -> tuple[str, str]:
        return key, download_and_decompress(s3_client, bucket, key)

    def _emit(line: str) -> None:
        print(line, file=output_stream, flush=True)
        if tee_to_stderr:
            print(line, file=sys.stderr)

    for batch_start in range(0, len(keys), batch_size):
        batch = keys[batch_start:batch_start + batch_size]

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_download, k): k for k in batch}

            for future in as_completed(futures):
                key = futures[future]
                try:
                    _, content = future.result()
                except Exception as exc:
                    print(f"  Warning: failed to process {key}: {exc}", file=sys.stderr)
                    continue

                processed += 1
                if verbose or processed % 100 == 0:
                    print(
                        f"  [{processed}/{len(keys)}] Processing {key}",
                        file=sys.stderr,
                    )

                for line in content.splitlines():
                    if skip_prefix and line.startswith(skip_prefix):
                        continue
                    total_lines += 1
                    if regex:
                        if regex.search(line):
                            matched_lines += 1
                            if not count_only:
                                _emit(line)
                    else:
                        matched_lines += 1
                        if not count_only:
                            _emit(line)

    return AnalysisResult(
        total_files=len(keys),
        total_lines=total_lines,
        matched_lines=matched_lines,
    )
