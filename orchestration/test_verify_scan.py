"""Tests for the 12-digit scan allowance (provider hashes in lock files only)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import verify_scan  # noqa: E402

LOCK = ".terraform.lock.hcl"
RUN12 = "2109" + "8765" + "4321"  # built at run time so the scan stays clean
ZH = '"zh:' + "0123456789ab" * 5 + '0123",'


def test_zh_line_allowed_in_lock_file():
    assert verify_scan.allowed("    " + ZH, "terraform/envs/x/" + LOCK)


def test_zh_line_flagged_in_other_file():
    assert not verify_scan.allowed("    " + ZH, "terraform/envs/x/main.tf")


def test_lock_line_with_added_account_number_flagged():
    line = "    " + ZH + " # " + RUN12
    assert not verify_scan.allowed(line, "terraform/envs/x/" + LOCK)
    assert not verify_scan.allowed(f'    "zh:{RUN12}",', "x/" + LOCK)


def test_default_path_does_not_allow_zh():
    assert not verify_scan.allowed(ZH)


def test_scan_is_digit_bounded():
    assert verify_scan.RUN.search(RUN12)
    assert verify_scan.RUN.search("id " + RUN12 + " end")
    assert verify_scan.RUN.search("acct" + RUN12 + "x")  # letters next to it still flag
    assert not verify_scan.RUN.search("1" + RUN12)  # 13 digits: an epoch in ms
    assert not verify_scan.RUN.search(RUN12 + "7")
    assert not verify_scan.RUN.search("17" + "9" * 11)  # 13 digits
    assert not verify_scan.RUN.search("1" * 11)  # 11 digits
