"""The verbs that write a pack-shaped artifact refuse a pack nothing named.

`resolve_pack`'s last step — the bundled pack — is the only one no human asked
for. On a machine with no ESTIMATING_PROFILES, `scaffold` and `scaffold-save`
would take their recipe names, sheet prefixes and takeoff routing from the demo
pack and write a real file; nothing downstream would object until the spec
failed to build, days later. `apply-takeoff` would die instead, but as
"produced an invalid spec (bug)" — the tool blaming itself for the operator's
missing environment variable.

The gate is `require_chosen`, NOT a `supports:` entry: every valid pack carries
the `seed.scaffold` and `seed.takeoff_mapping` these verbs read, so a supports
entry would be one every pack always sets — including the bundled pack, which
would reopen the hazard. See `format_pack.require_chosen`.

`build` is deliberately ungated: its schema IS the pack's vocabulary, so a spec
of another shape is refused by name.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from estimating_tools.estimate_spec import format_pack as fp
from estimating_tools.estimate_spec.cli import main

DEMO_DIR = fp.ENGINE_DIR / "packs" / "demo"

#: Every gated verb, invoked with inputs that do not exist. The gate runs
#: before any input is read, so an ungated run of these exits 1 ("no such
#: file") and a gated one exits 2 — which is what distinguishes the two.
GATED = {
    "scaffold": lambda p: ["scaffold", "--manifest", str(p / "nope.json"),
                           "-o", str(p / "out.estimate.yaml")],
    "apply-takeoff": lambda p: ["apply-takeoff", str(p / "nope.estimate.yaml"),
                                "--takeoff", str(p / "nope.json")],
    "scaffold-save": lambda p: ["scaffold-save", "--spec",
                                str(p / "nope.estimate.yaml")],
}


@pytest.fixture(autouse=True)
def no_profile(monkeypatch):
    """No org profile configured — the case the gate exists for. Set on the
    developer's own machine, so a test that did not clear it would pass by
    resolving the real org pack and never exercise the gate at all."""
    monkeypatch.delenv("ESTIMATING_PROFILES", raising=False)


@pytest.mark.parametrize("verb", sorted(GATED))
def test_the_write_verbs_refuse_a_pack_nothing_named(verb, tmp_path, capsys):
    assert main(GATED[verb](tmp_path)) == 2
    err = capsys.readouterr().err
    assert f"{verb} would use the bundled 'demo' pack" in err
    assert "ESTIMATING_PROFILES" in err and "--format" in err


@pytest.mark.parametrize("verb", sorted(GATED))
def test_the_gate_runs_before_any_input_is_read(verb, tmp_path):
    """Named pack, same missing inputs: exit 1, the ordinary "no such file".
    The only thing the gate changed is refusing an unchosen pack — it did not
    start rejecting the inputs."""
    assert main(GATED[verb](tmp_path) + ["--format", str(DEMO_DIR)]) == 1


@pytest.mark.parametrize("verb", sorted(GATED))
def test_nothing_is_written_when_the_gate_refuses(verb, tmp_path):
    assert main(GATED[verb](tmp_path)) == 2
    assert list(tmp_path.iterdir()) == []


def test_naming_the_bundled_pack_is_a_choice_the_gate_honours(tmp_path):
    """The message offers `--format PATH` as the escape hatch and says the
    bundled pack's own path works. It has to."""
    assert fp.resolve_pack(str(DEMO_DIR), None).chosen is True
    fp.require_chosen(fp.resolve_pack(str(DEMO_DIR), None), "scaffold")


def test_build_is_not_gated(tmp_path, capsys):
    """build's protection is structural — the composed schema is the pack's own
    vocabulary — so it reaches the input and reports THAT, not the pack."""
    config = tmp_path / "nope.yaml"
    assert main(["build", str(config)]) == 1
    assert "no such file" in capsys.readouterr().err


def test_cip_buildup_resolves_no_pack_at_all():
    """Not an oversight of this gate: `cip-buildup` takes no --format and never
    calls resolve_pack, so there is no pack for it to have chosen wrongly. Its
    shapes are hardwired in cip.py.

    That is settled, not pending. Converting cip.py to a pack was considered and
    declined on 2026-09-30: it shares nothing with the format-pack mechanism, so
    a pack buys no consistency any other code path can observe, while adding one
    more pack to author and one more place an org's numbers can be wrong. So
    this test pins a deliberate asymmetry -- do not "fix" it by wiring
    `--format` into cmd_cip.
    """
    import inspect

    from estimating_tools.estimate_spec import cli

    assert "--format" not in inspect.getsource(cli.cmd_cip)
    assert "_resolve_pack_or_report" not in inspect.getsource(cli.cmd_cip)
    parser = cli._parser()
    cip = [a for a in parser._subparsers._group_actions[0].choices["cip-buildup"]._actions
           if a.option_strings]
    assert not any("--format" in a.option_strings for a in cip)
