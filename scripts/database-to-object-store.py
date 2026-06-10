#!/usr/bin/env python
import os
import sys
import argparse
import subprocess
import tempfile
from datetime import datetime, UTC
from pathlib import PosixPath
import openstack

SEGMENT_SIZE = 512 * 1024 * 1024
DELETE_AFTER = 3 * 24 * 60 * 60


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


def upload_file(
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

    segments = []
    with source_path.open("rb") as fh:
        i = 0
        while chunk := fh.read(SEGMENT_SIZE):
            print(f"  Uploading segment {i} ({len(chunk) / 1024 / 1024:.0f} MiB)")
            segment_name = f"{target_name}/{i:06d}"
            obj = conn.object_store.upload_object(
                container=container_name,
                name=segment_name,
                data=chunk,
                delete_after=DELETE_AFTER,
            )
            segments.append(
                {
                    "path": f"/{container_name}/{segment_name}",
                    "etag": obj.etag,
                    "size_bytes": len(chunk),
                }
            )
            i += 1

    conn.object_store.put(
        f"/{container_name}/{target_name}",
        params={"multipart-manifest": "put"},
        json=segments,
        headers={"X-Delete-After": str(DELETE_AFTER)},
    )


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

    target_name = f'{datetime.now(UTC).strftime("%Y%m%dT%H%M%S")}.sql.gz'
    with tempfile.NamedTemporaryFile(suffix=".sql.gz") as tmp:
        export_database(
            args.mysql_host,
            args.mysql_user,
            args.mysql_password,
            args.mysql_schema,
            PosixPath(tmp.name),
        )

        print(f"Uploading {target_name} to {args.openstack_bucket}")
        upload_file(
            PosixPath(tmp.name),
            args.openstack_bucket,
            target_name,
            args.openstack_application_credential,
            args.openstack_application_secret,
        )


if __name__ == "__main__":
    main()
