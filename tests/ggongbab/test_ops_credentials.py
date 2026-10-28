# -*- coding: utf-8 -*-
"""This PC's secret store on Linux: one 0600 file per target outside the checkout (2026-10-29).
Synthetic values in a temporary directory only."""
from __future__ import annotations

import os
import stat

import pytest

from ggongbab import ops_credentials as oc

SECRET = "123456789:SYNTHETIC_TOKEN_NOT_REAL_abcdefghijklmnop"
pytestmark = pytest.mark.skipif(os.name == "nt", reason="the file store is the Linux path")


def test_a_written_secret_reads_back_and_only_this_user_can_read_it(tmp_path):
    root = tmp_path / "credentials"
    assert oc.write_credential(SECRET, "babdoduk/alert-telegram", root=root)
    assert oc.read_credential("babdoduk/alert-telegram", root=root) == SECRET
    (path,) = list(root.iterdir())
    assert path.name == "babdoduk_alert-telegram"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and stat.S_IMODE(root.stat().st_mode) == 0o700


def test_a_secret_others_could_read_is_refused(tmp_path):
    root = tmp_path / "credentials"
    oc.write_credential(SECRET, "t", root=root)
    os.chmod(root / "t", 0o644)
    assert oc.read_credential("t", root=root) is None


def test_missing_or_empty_is_nothing_and_delete_forgets(tmp_path):
    root = tmp_path / "credentials"
    assert oc.read_credential("t", root=root) is None
    oc.write_credential("  ", "t", root=root)
    assert oc.read_credential("t", root=root) is None
    oc.write_credential(SECRET, "t", root=root)
    assert oc.delete_credential("t", root=root) and oc.read_credential("t", root=root) is None
    assert not oc.delete_credential("t", root=root)


def test_the_store_is_outside_the_checkout_and_follows_xdg(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert oc.store_dir() == tmp_path / "babdoduk" / "credentials"
    assert oc.where() == str(tmp_path / "babdoduk" / "credentials")
    monkeypatch.delenv("XDG_CONFIG_HOME")
    assert oc.store_dir().is_relative_to(os.path.expanduser("~/.config"))


def test_the_alert_commands_store_and_read_through_it(tmp_path, monkeypatch, capsys):
    import alert_push
    from ggongbab import notify
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(alert_push, "CONFIG", tmp_path / "alert-push.json")
    monkeypatch.setattr(alert_push.getpass, "getpass", lambda prompt: SECRET)
    assert alert_push.main(["--store-telegram-token"]) == 0
    assert oc.read_credential(notify.TOKEN_TARGET) == SECRET
    assert alert_push.main(["--status"]) == 0
    printed = capsys.readouterr().out
    assert "telegram token   : stored" in printed and SECRET not in printed
    assert alert_push.main(["--remove"]) == 0 and oc.read_credential(notify.TOKEN_TARGET) is None
