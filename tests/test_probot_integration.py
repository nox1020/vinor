# -*- coding: utf-8 -*-
"""1probot integration: config from env, /probot panel behind its own auth, no side effects."""
from __future__ import annotations

import json
import os
import re

import pytest

_PROBOT_ENV = (
    "PROBOT_BALE_TOKEN",
    "PROBOT_ADMIN_ID",
    "PROBOT_WEB_PASSWORD",
    "PROBOT_DIVAR_RELAY_URL",
    "PROBOT_DIVAR_RELAY_SECRET",
    "PROBOT_DATABASE",
    "PROBOT_ENABLED",
)


@pytest.fixture
def probot_env(tmp_path, monkeypatch):
    for name in _PROBOT_ENV:
        monkeypatch.delenv(name, raising=False)
    data = tmp_path / "probot_data"
    monkeypatch.setenv("PROBOT_DATA_DIR", str(data))
    monkeypatch.setenv("PROBOT_AUTOSTART", "0")
    return data

def _write_unconfigured(probot_env):
    """Placeholder data-dir config so packaged default is not used."""
    probot_env.mkdir(parents=True, exist_ok=True)
    (probot_env / "configs.json").write_text(
        json.dumps({"token": "YOUR_BALE_BOT_TOKEN", "admin": 0}), encoding="utf-8"
    )


def _make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("INSTANCE_PATH", str(tmp_path / "instance"))
    monkeypatch.setenv("SECRET_KEY", "unit-probot")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "0")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'vinor.db'}")
    monkeypatch.setenv("VINOR_DISABLE_SALES_COACH_NUDGE", "1")
    monkeypatch.setenv("VINOR_DISABLE_REACH", "1")
    monkeypatch.setenv("VINOR_DISABLE_CELEBRATION_SMS", "1")
    monkeypatch.setenv("VINOR_DISABLE_SMS_SCHEDULER", "1")
    monkeypatch.setenv("VINOR_OPTIMIZATION_SCHEDULER", "0")
    import probot.web_app as web_app

    monkeypatch.setattr(web_app, "_INIT_DONE", False)
    from app import create_app

    app = create_app()
    app.config.update(TESTING=True)
    return app, app.test_client()


def test_package_import_has_no_side_effects(probot_env):
    import probot
    import probot.paths as paths
    import probot.runner as runner  # noqa: F401
    import probot.web_app as web_app

    assert hasattr(probot, "register_probot")
    assert web_app.bp.url_prefix == "/probot"
    assert web_app.scheduler is None
    # import alone must not create the DB or start anything
    assert not (probot_env / "bot.db").exists()
    assert paths.data_dir() == str(probot_env)


def test_config_env_overrides_file(probot_env, monkeypatch):
    from probot import paths
    from probot.loadConfig import configBot

    # Packaged default is used when the data-dir file is absent.
    assert not (probot_env / "configs.json").exists()
    assert paths.is_configured()
    packed = paths.load_file_config()
    assert packed.get("token")
    assert not str(packed.get("token")).upper().startswith("YOUR_")
    # Env still overrides the packaged default (no data-dir file yet).
    monkeypatch.setenv("PROBOT_BALE_TOKEN", "111:env-token")
    monkeypatch.setenv("PROBOT_ADMIN_ID", "777")
    env_over_packed = paths.load_config()
    assert env_over_packed["token"] == "111:env-token"
    assert paths.load_file_config().get("token") != "111:env-token"
    monkeypatch.delenv("PROBOT_BALE_TOKEN", raising=False)
    monkeypatch.delenv("PROBOT_ADMIN_ID", raising=False)

    # A data-dir file, if present, wins over the packaged default.
    probot_env.mkdir(parents=True, exist_ok=True)
    (probot_env / "configs.json").write_text(
        json.dumps({"token": "YOUR_BALE_BOT_TOKEN", "admin": 0, "start_hour": 9}), encoding="utf-8"
    )
    assert not paths.is_configured()

    monkeypatch.setenv("PROBOT_BALE_TOKEN", "111:env-token")
    monkeypatch.setenv("PROBOT_ADMIN_ID", "777")
    cfg = paths.load_config()
    assert cfg["token"] == "111:env-token"
    assert cfg["start_hour"] == 9
    assert cfg["times"] == [8, 22]
    assert paths.is_configured()
    # raw file view never contains env secrets (it is written back to disk)
    assert paths.load_file_config()["token"] == "YOUR_BALE_BOT_TOKEN"

    datas = configBot()
    assert datas.token == "111:env-token"
    assert datas.admin == 777
    assert datas.database == str(probot_env / "bot.db")

    monkeypatch.setenv("PROBOT_ENABLED", "0")
    assert not paths.is_configured()


def test_panel_disabled_without_token(probot_env, tmp_path, monkeypatch):
    # Explicit unconfigured data-dir file (not the packaged default).
    _write_unconfigured(probot_env)
    _app, client = _make_client(tmp_path, monkeypatch)
    resp = client.get("/probot/login")
    assert resp.status_code == 503
    assert "فعال نشده" in resp.get_data(as_text=True)
    assert not (probot_env / "bot.db").exists()
    # Vinor itself is unaffected
    assert client.get("/healthz").status_code == 204


def test_packaged_default_enables_panel_login(probot_env, tmp_path, monkeypatch):
    """Empty data dir + committed default => login page, not 503."""
    assert not (probot_env / "configs.json").exists()
    from probot import paths

    assert paths.is_configured()
    _app, client = _make_client(tmp_path, monkeypatch)
    home = client.get("/probot/")
    assert home.status_code == 303
    assert home.headers["Location"].endswith("/probot/login")
    page = client.get("/probot/login")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "فعال نشده" not in html
    assert 'name="csrf_token"' in html
    # Never leak the packaged token into the login page.
    packed_token = str(paths.load_file_config().get("token") or "")
    if packed_token:
        assert packed_token not in html


def test_panel_requires_login_and_has_csrf(probot_env, tmp_path, monkeypatch):
    monkeypatch.setenv("PROBOT_BALE_TOKEN", "111:env-token")
    monkeypatch.setenv("PROBOT_ADMIN_ID", "777")
    app, client = _make_client(tmp_path, monkeypatch)

    resp = client.get("/probot/")
    assert resp.status_code == 303
    assert resp.headers["Location"].endswith("/probot/login")

    page = client.get("/probot/login")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert 'name="csrf_token"' in html
    assert (probot_env / "bot.db").exists()

    # POST without CSRF token is rejected by Vinor's CSRFProtect (its handler answers 400 or redirects)
    no_csrf = client.post("/probot/login", data={"phone": "0", "password": "x"})
    assert no_csrf.status_code in (302, 400)
    assert not no_csrf.headers.get("Location", "").endswith("/probot/")

    token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
    bad = client.post(
        "/probot/login",
        data={"phone": "09000000000", "password": "wrong", "csrf_token": token},
    )
    assert bad.status_code == 200
    with client.session_transaction() as sess:
        assert not sess.get("probot_web_auth")

    # commands require the panel session
    cmd = client.post("/probot/api/command", data={"csrf_token": token, "command_type": "startJob"})
    assert cmd.status_code == 303
    assert cmd.headers["Location"].endswith("/probot/login")


def test_logout_keeps_vinor_session(probot_env, tmp_path, monkeypatch):
    monkeypatch.setenv("PROBOT_BALE_TOKEN", "111:env-token")
    monkeypatch.setenv("PROBOT_ADMIN_ID", "777")
    _app, client = _make_client(tmp_path, monkeypatch)
    with client.session_transaction() as sess:
        sess["user_phone"] = "09120000000"
        sess["probot_web_auth"] = True
        sess["probot_panel_chatid"] = 5
    client.get("/probot/logout")
    with client.session_transaction() as sess:
        assert sess.get("user_phone") == "09120000000"
        assert "probot_web_auth" not in sess


def test_divar_relay_disabled_without_secret(probot_env, tmp_path, monkeypatch):
    _app, client = _make_client(tmp_path, monkeypatch)
    resp = client.post("/probot/divar-relay", json={"url": "https://api.divar.ir/x"})
    assert resp.status_code == 503
    assert client.get("/probot/divar-relay/health").status_code == 503


def test_runner_not_configured_is_noop(probot_env, monkeypatch):
    from probot import runner

    _write_unconfigured(probot_env)
    spawned = []
    monkeypatch.setattr(runner, "spawn_detached", lambda: spawned.append(1))
    assert runner.ensure() == 0
    assert runner.foreground() == 0
    monkeypatch.setenv("PROBOT_AUTOSTART", "1")
    monkeypatch.setattr(runner, "_last_autostart_check", 0.0)
    runner.maybe_autostart()
    assert spawned == []
    assert runner.is_running() is False


def test_runner_lock_is_single_instance(probot_env):
    fcntl = pytest.importorskip("fcntl")
    from probot import paths, runner

    os.makedirs(paths.data_dir(), exist_ok=True)
    fd = os.open(paths.data_path(runner.LOCK_NAME), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        assert runner.is_running() is False
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert runner.is_running() is True
    finally:
        os.close(fd)
    assert runner.is_running() is False


def test_autostart_spawns_once_when_configured(probot_env, monkeypatch):
    from probot import runner

    monkeypatch.setenv("PROBOT_BALE_TOKEN", "111:env-token")
    monkeypatch.setenv("PROBOT_ADMIN_ID", "777")
    monkeypatch.setenv("PROBOT_AUTOSTART", "1")
    spawned = []
    monkeypatch.setattr(runner, "spawn_detached", lambda: spawned.append(1))
    monkeypatch.setattr(runner, "_last_autostart_check", 0.0)
    runner.maybe_autostart()
    runner.maybe_autostart()  # throttled
    assert spawned == [1]


def test_autostart_uses_packaged_default_when_data_dir_empty(probot_env, monkeypatch):
    from probot import paths, runner

    assert not (probot_env / "configs.json").exists()
    assert paths.is_configured()
    monkeypatch.setenv("PROBOT_AUTOSTART", "1")
    spawned = []
    monkeypatch.setattr(runner, "spawn_detached", lambda: spawned.append(1))
    monkeypatch.setattr(runner, "_last_autostart_check", 0.0)
    runner.maybe_autostart()
    assert spawned == [1]


def test_seed_data_config_copies_packaged_not_empty(probot_env):
    from probot import paths

    assert not (probot_env / "configs.json").exists()
    dest = paths.seed_data_config()
    assert dest == str(probot_env / "configs.json")
    assert (probot_env / "configs.json").is_file()
    data = json.loads((probot_env / "configs.json").read_text(encoding="utf-8"))
    assert data != {}
    assert data.get("token")
    assert not str(data.get("token")).upper().startswith("YOUR_")
    # Second call must not rewrite / clobber an existing data-dir file.
    data["start_hour"] = 3
    (probot_env / "configs.json").write_text(json.dumps(data), encoding="utf-8")
    paths.seed_data_config()
    again = json.loads((probot_env / "configs.json").read_text(encoding="utf-8"))
    assert again.get("start_hour") == 3


def test_bot_module_uses_data_dir(probot_env, monkeypatch):
    pytest.importorskip("telegram")
    import sys

    monkeypatch.setenv("PROBOT_BALE_TOKEN", "111:env-token")
    monkeypatch.setenv("PROBOT_ADMIN_ID", "777")
    cwd = os.getcwd()
    for mod in ("probot.bot", "probot.worker"):
        sys.modules.pop(mod, None)
    try:
        import probot.bot as bot
        import probot.worker as worker

        assert bot._PROJECT_ROOT == str(probot_env)
        assert bot.Datas.database == str(probot_env / "bot.db")
        assert worker.WORKER_LOCK_FILE == str(probot_env / ".worker.lock")
        assert callable(bot.serve)
    finally:
        os.chdir(cwd)
        for mod in ("probot.bot", "probot.worker"):
            sys.modules.pop(mod, None)


def test_logged_in_panel_renders_with_prefixed_forms(probot_env, tmp_path, monkeypatch):
    monkeypatch.setenv("PROBOT_BALE_TOKEN", "111:env-token")
    monkeypatch.setenv("PROBOT_ADMIN_ID", "777")
    _app, client = _make_client(tmp_path, monkeypatch)
    assert client.get("/probot/login").status_code == 200  # init DB
    with client.session_transaction() as sess:
        sess["probot_web_auth"] = True
        sess["probot_panel_chatid"] = 777
    resp = client.get("/probot/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'action="/probot/api/command"' in html
    assert 'action="/api/command"' not in html
    assert html.count('name="csrf_token"') >= 5
    assert "111:env-token" not in html
