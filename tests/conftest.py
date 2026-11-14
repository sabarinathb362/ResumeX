"""
Test isolation. pytest imports this file before any test module, so the environment is set
before backend.config builds its settings.

Why this exists: tests/test_smoke.py creates and then DROPS every table on the app's engine, and
several tests upload files through the API. Without this, running the test suite wiped the real
resumeiq.db and wrote into the real uploads/ folder.
"""
import os
import shutil
import tempfile

_TMP = tempfile.mkdtemp(prefix="resumex-tests-")
os.environ["RESUMEIQ_DATABASE_URL"] = "sqlite:///" + os.path.join(_TMP, "test.db").replace("\\", "/")
os.environ["RESUMEIQ_UPLOAD_DIR"] = os.path.join(_TMP, "uploads")
os.makedirs(os.environ["RESUMEIQ_UPLOAD_DIR"], exist_ok=True)


def pytest_sessionstart(session):
    """Refuse to run if the app database is still the target (e.g. settings were imported too early)."""
    from backend.config import BASE_DIR, settings
    real = (BASE_DIR / "resumeiq.db").as_posix()
    assert real not in settings.database_url, "tests must not run against the real resumeiq.db"
    from backend.database import init_db
    init_db()


def pytest_sessionfinish(session, exitstatus):
    try:
        from backend.database import engine
        engine.dispose()
    except Exception:
        pass
    shutil.rmtree(_TMP, ignore_errors=True)
