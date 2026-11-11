#!/usr/bin/env python3
import argparse
import os
import subprocess
import sys
from datetime import UTC, datetime
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
    parser.add_argument("--dump-per-table", default=False, action=argparse.BooleanOptionalAction)
    return parser.parse_args()


def get_database_tables(
    mysql_host: str,
    mysql_user: str,
    mysql_password: str,
    mysql_schema: str,
) -> list[str]:
    p = subprocess.run(
        [
            "mysql",
            f"--host={mysql_host}",
            f"--user={mysql_user}",
            "--disable-ssl",
            "-A",
            mysql_schema,
            "-e",
            "show tables",
            "-N",
        ],
        stdout=subprocess.PIPE,
        env={**os.environ, "MYSQL_PWD": mysql_password},
        check=True,
    )
    return [line.strip() for line in p.stdout.decode("utf-8").splitlines() if line.strip()]


def export_database(
    mysql_host: str,
    mysql_user: str,
    mysql_password: str,
    mysql_schema: str,
    mysql_table: str | None,
    target_path: PosixPath,
):
    mysqldump_args = [
        "mysqldump",
        f"--host={mysql_host}",
        f"--user={mysql_user}",
        "--disable-ssl",
        mysql_schema,
    ]
    if mysql_table:
        mysqldump_args.append(mysql_table)

    fd = os.open(target_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640)
    with open(fd, "wb") as fh:
        mysqldump = subprocess.Popen(
            mysqldump_args,
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

    export_name = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    if not args.dump_per_table:
        target_path = target_directory / f"{export_name}.sql.gz"
        print(f"Exporting database to {target_path}")
        export_database(
            args.mysql_host,
            args.mysql_user,
            args.mysql_password,
            args.mysql_schema,
            None,
            target_path,
        )
        return

    export_directory = target_directory / export_name
    export_directory.mkdir(exist_ok=True)
    export_directory.chmod(0o750)

    for table in get_database_tables(args.mysql_host, args.mysql_user, args.mysql_password, args.mysql_schema):
        target_path = export_directory / f"{table}.sql.gz"
        print(f"Exporting database table {table} to {target_path}")
        export_database(
            args.mysql_host,
            args.mysql_user,
            args.mysql_password,
            args.mysql_schema,
            table,
            target_path,
        )


if __name__ == "__main__":
    main()
