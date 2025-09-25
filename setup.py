#!/usr/bin/env python3
import shutil
import subprocess
from pathlib import PosixPath


def main():
    # Poetry expects a Python package from `setup.py install`, create a minimal one
    package_dir = PosixPath("/workspace/external_utilities")
    package_dir.mkdir(parents=True)
    (package_dir / "__init__.py").open("w").close()


if __name__ == "__main__":
    main()
