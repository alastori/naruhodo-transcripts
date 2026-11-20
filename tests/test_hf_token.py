"""HuggingFace token order: environment, Keychain copy, then 1Password. Offline only."""

import subprocess

import pytest

from src import diarization

TOKEN = "hf_synthetic_value"


class FakeRun:
    def __init__(self, keychain=(0, TOKEN + "\n"), op=(0, "hf_from_op\n"), raise_on=None):
        self.keychain, self.op, self.raise_on = keychain, op, raise_on
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        if self.raise_on and args[0] == self.raise_on[0]:
            raise self.raise_on[1]
        code, out = self.keychain if args[0] == diarization.SECURITY else self.op
        return subprocess.CompletedProcess(args, code, out, "")


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)

    def install(**kwargs):
        run = FakeRun(**kwargs)
        monkeypatch.setattr(diarization.subprocess, "run", run)
        return run

    return install


def test_environment_wins_without_any_lookup(fake, monkeypatch):
    run = fake()
    monkeypatch.setenv("HF_TOKEN", "hf_env")
    assert diarization.get_hf_token() == "hf_env"
    assert run.calls == []


def test_keychain_copy_is_used_before_1password(fake):
    run = fake()
    assert diarization.get_hf_token() == TOKEN
    assert run.calls == [["/usr/bin/security", "find-generic-password", "-s", "naruhodo-transcripts",
                          "-a", "HF_TOKEN", "-w"]]


@pytest.mark.parametrize("keychain", [(44, ""), (0, ""), (0, " padded\n"), (0, "two\nlines\n")])
def test_missing_or_unusable_copy_falls_back_to_1password(fake, keychain, caplog):
    run = fake(keychain=keychain)
    with caplog.at_level("INFO", logger="naruhodo"):
        assert diarization.get_hf_token() == "hf_from_op"
    assert [call[0] for call in run.calls] == ["/usr/bin/security", "op"]
    assert "Keychain copy of the HuggingFace token missing or unusable" in caplog.text
    assert TOKEN not in caplog.text and "hf_from_op" not in caplog.text


def test_keychain_timeout_falls_back(fake):
    run = fake(raise_on=("/usr/bin/security", subprocess.TimeoutExpired("security", 10)))
    assert diarization.get_hf_token() == "hf_from_op"
    assert [call[0] for call in run.calls] == ["/usr/bin/security", "op"]


def test_nothing_available_returns_none(fake):
    fake(keychain=(44, ""), op=(1, ""))
    assert diarization.get_hf_token() is None


def test_no_security_binary_falls_back(fake):
    run = fake(raise_on=("/usr/bin/security", FileNotFoundError("/usr/bin/security")))
    assert diarization.get_hf_token() == "hf_from_op"
    assert [call[0] for call in run.calls] == ["/usr/bin/security", "op"]


def test_op_permission_error_returns_none(fake):
    fake(keychain=(44, ""), raise_on=("op", PermissionError("op")))
    assert diarization.get_hf_token() is None
