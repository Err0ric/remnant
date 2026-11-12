"""What the test host's operating system or file system cannot do, so a test skips there
with the reason instead of failing. Linux (the server and CI) runs every test."""

import errno
import os
from typing import TextIO

import pytest


def open_bytes_name(path: bytes) -> TextIO:
    """Open a file whose name is not valid UTF-8. APFS (macOS) refuses such names with
    EILSEQ, so the test is skipped there; Linux file systems accept them."""
    try:
        return open(path, "w")  # the caller closes it
    except OSError as exc:
        if exc.errno == errno.EILSEQ:
            pytest.skip("this file system refuses names that are not UTF-8 (APFS)")
        raise


def mkdir_bytes_name(path: bytes) -> None:
    try:
        os.mkdir(path)
    except OSError as exc:
        if exc.errno == errno.EILSEQ:
            pytest.skip("this file system refuses names that are not UTF-8 (APFS)")
        raise
