#!/usr/bin/env python
import os
import sys
import argparse
import hashlib
import subprocess
import tempfile
from datetime import datetime, UTC
from pathlib import PosixPath
import openstack

SEGMENT_SIZE = 100 * 1024 * 1024
DELETE_BACKUP_AFTER = 3 * 24 * 60 * 60


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mysql-host", default=os.environ.get("TOOL_DB_HOST"))
    parser.add_argument("--mysql-user", default=os.environ.get("TOOL_DB_USER"))
    parser.add_argument("--mysql-password", default=os.environ.get("TOOL_DB_PASSWORD"))
    parser.add_argument("--mysql-schema", default=os.environ.get("TOOL_DB_SCHEMA"))
    parser.add_argument(
        "--openstack-application-credential",
        default=os.environ.get("TOOL_BACKUP_OS_CREDENTIAL"),
    )
    parser.add_argument(
        "--openstack-application-secret",
        default=os.environ.get("TOOL_BACKUP_OS_SECRET"),
    )
    parser.add_argument("--openstack-bucket", default=os.environ.get("TOOL_BACKUP_OS_BUCKET"))
    parser.add_argument("--dump-per-table", default=True, action="store")
    return parser.parse_args()


def _get_database_tables(
    mysql_host: str,
    mysql_user: str,
    mysql_password: str,
    mysql_schema: str,
) -> list[str]:
    p = subprocess.Popen(
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
    )
    return [line.strip() for line in p.stdout.read().decode("utf-8").splitlines()]


def _export_database_tables(
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


def _upload_file(
    source_path: PosixPath,
    container_name: str,
    target_name: str,
    openstack_application_credential: str,
    openstack_application_secret: str,
):
    conn = openstack.connect(
        auth_url="https://openstack.eqiad1.wikimediacloud.org:25000/v3",
        auth_type="v3applicationcredential",
        application_credential_id=openstack_application_credential,
        application_credential_secret=openstack_application_secret,
    )

    segment_prefix = f"segments/{target_name}"
    if "/" in target_name:
        parts = target_name.split("/", 2)
        segment_prefix = f"{parts[0]}/segments/{parts[1]}"

    segments = []
    with source_path.open("rb") as fh:
        while chunk := fh.read(SEGMENT_SIZE):
            obj = conn.object_store.upload_object(
                container=container_name,
                name=f"{segment_prefix}/{hashlib.sha256(chunk).hexdigest()}",
                data=chunk,
                headers={"X-Delete-After": f"{DELETE_BACKUP_AFTER}"},
            )
            segments.append({"path": f"/{container_name}/{obj.name}", "etag": obj.etag, "size_bytes": len(chunk)})

    r = conn.object_store.put(
        f"/{container_name}/{target_name}",
        params={"multipart-manifest": "put"},
        json=segments,
        headers={"X-Delete-After": f"{DELETE_BACKUP_AFTER}"},
    )
    if r.status_code != 201:
        print(f"Failed to create object for {target_name}: [{r.status_code}] {r.text}")


def main():
    args = get_args()
    if not all(
        (
            args.mysql_host,
            args.mysql_user,
            args.mysql_password,
            args.mysql_schema,
            args.openstack_bucket,
            args.openstack_application_credential,
            args.openstack_application_secret,
        )
    ):
        print("Missing required arguments")
        sys.exit(1)

    export_name = f'{datetime.now(UTC).strftime("%Y%m%dT%H%M%S")}'
    target_tables = (
        _get_database_tables(args.mysql_host, args.mysql_user, args.mysql_password, args.mysql_schema)
        if args.dump_per_table
        else [None]
    )

    for table in target_tables:
        target_name = f"{export_name}/{table}.sql.gz" if table else f"{export_name}.sql.gz"
        with tempfile.NamedTemporaryFile(suffix=".sql.gz") as tmp:
            if table:
                print(f"Exporting database table {table} to {tmp.name}")
            else:
                print(f"Exporting database schema {args.mysql_schema} to {tmp.name}")

            _export_database_tables(
                args.mysql_host,
                args.mysql_user,
                args.mysql_password,
                args.mysql_schema,
                table,
                PosixPath(tmp.name),
            )

            print(f"Uploading {target_name} to {args.openstack_bucket}")
            _upload_file(
                PosixPath(tmp.name),
                args.openstack_bucket,
                target_name,
                args.openstack_application_credential,
                args.openstack_application_secret,
            )


if __name__ == "__main__":
    main()
