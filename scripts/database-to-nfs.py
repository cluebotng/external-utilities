#!/usr/bin/env python3
import os
import sys
import argparse
import subprocess
from datetime import datetime, UTC
from pathlib import PosixPath


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mysql-host", default=os.environ.get("TOOL_DB_HOST"))
    parser.add_argument("--mysql-user", default=os.environ.get("TOOL_DB_USER"))
    parser.add_argument("--mysql-password", default=os.environ.get("TOOL_DB_PASSWORD"))
    parser.add_argument("--mysql-schema", default=os.environ.get("TOOL_DB_SCHEMA"))
    parser.add_argument(
        "--target-directory",
        default=(
            (PosixPath(os.environ.get("TOOL_DATA_DIR")) / "mysql_backups").as_posix()
            if os.environ.get("TOOL_DATA_DIR")
            else None
        ),
    )
    return parser.parse_args()


def export_database(
    mysql_host: str,
    mysql_user: str,
    mysql_password: str,
    mysql_schema: str,
    target_path: PosixPath,
):
    fd = os.open(target_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640)
    with open(fd, "wb") as fh:
        mysqldump = subprocess.Popen(
            [
                "mysqldump",
                f"--host={mysql_host}",
                f"--user={mysql_user}",
                "--disable-ssl",
                mysql_schema,
            ],
            stdout=subprocess.PIPE,
            env={**os.environ, "MYSQL_PWD": mysql_password},
        )
        gzip = subprocess.Popen(
            ["gzip", "-9"],
            stdin=mysqldump.stdout,
            stdout=fh,
        )
        mysqldump.stdout.close()
        gzip.wait()
        mysqldump.wait()

    if mysqldump.returncode != 0 or gzip.returncode != 0:
        print(f"Dump failed: mysqldump={mysqldump.returncode}, gzip={gzip.returncode}")
        sys.exit(1)


def main():
    args = get_args()

    if not all(
        (
            args.mysql_host,
            args.mysql_user,
            args.mysql_password,
            args.mysql_schema,
            args.target_directory,
        )
    ):
        print("Missing required arguments")
        sys.exit(1)

    target_directory = PosixPath(args.target_directory)
    target_directory.mkdir(parents=True, exist_ok=True)
    target_directory.chmod(0o750)

    target_path = (
        target_directory / f'{datetime.now(UTC).strftime("%Y%m%dT%H%M%S")}.sql.gz'
    )
    print(f"Exporting database to {target_path}")
    export_database(
        args.mysql_host,
        args.mysql_user,
        args.mysql_password,
        args.mysql_schema,
        target_path,
    )


if __name__ == "__main__":
    main()
