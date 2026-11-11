#!/usr/bin/env python3
import argparse
import os
import shutil
import sys
from datetime import UTC, datetime, timedelta
from pathlib import PosixPath


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--target-directory",
        default=(
            (PosixPath(os.environ.get("TOOL_DATA_DIR")) / "mysql_backups").as_posix()
            if os.environ.get("TOOL_DATA_DIR")
            else None
        ),
    )
    parser.add_argument("--days", default=7, type=int)
    return parser.parse_args()


def prune_backups(target_directory: PosixPath, days: int):
    cutoff = datetime.now(UTC) - timedelta(days=days)
    for path in target_directory.iterdir():
        if datetime.fromtimestamp(path.lstat().st_mtime, UTC) >= cutoff:
            continue

        print(f"Removing {path}")
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()


def main():
    args = get_args()

    if not args.target_directory:
        print("Missing required arguments")
        sys.exit(1)

    if args.days < 1:
        print("Days must be at least 1")
        sys.exit(1)

    target_directory = PosixPath(args.target_directory)
    if not target_directory.is_dir():
        print(f"Target directory {target_directory} does not exist")
        sys.exit(1)

    prune_backups(target_directory, args.days)


if __name__ == "__main__":
    main()
