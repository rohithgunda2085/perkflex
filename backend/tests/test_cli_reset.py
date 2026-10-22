"""demo-reset deletes data, so its guards are tested. None of these reach a database."""

from types import SimpleNamespace

from app import cli


def run(monkeypatch, argv, *, demo=True, schema="pf_demo"):
    monkeypatch.setattr(cli, "get_settings", lambda: SimpleNamespace(demo_mode=demo, db_schema=schema))

    def no_database(*a, **k):
        raise AssertionError("a guard should have stopped this before connecting")

    monkeypatch.setattr(cli, "connect", no_database)
    return cli.main(["demo-reset", *argv])


def test_it_needs_an_explicit_yes(monkeypatch, capsys):
    assert run(monkeypatch, []) == 2
    assert "--yes" in capsys.readouterr().err


def test_it_refuses_outside_demo_mode(monkeypatch, capsys):
    assert run(monkeypatch, ["--yes"], demo=False) == 2
    assert "DEMO_MODE" in capsys.readouterr().err


def test_it_refuses_the_public_schema_unless_told_otherwise(monkeypatch, capsys):
    assert run(monkeypatch, ["--yes"], schema="") == 2
    assert "public" in capsys.readouterr().err


def test_it_refuses_a_schema_name_that_is_not_plain(monkeypatch, capsys):
    assert run(monkeypatch, ["--yes"], schema='x"; DROP SCHEMA public CASCADE; --') == 2
    assert "plain schema name" in capsys.readouterr().err
