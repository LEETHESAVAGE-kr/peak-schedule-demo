# Streamlit Community Cloud entry point. Runs p6/viewer_mobile.py (phone view) or, with ?v=full, p6/viewer_ops_j9.py (SHOW_MODE_B=False).
# The access code is read from st.secrets["demo_key"] (Cloud app settings -> Secrets). It is never stored in this repository.
import os
import pathlib
import runpy
import sys
import tempfile

import streamlit as st

P6 = pathlib.Path(__file__).resolve().parent / "p6"
sys.path.insert(0, str(P6))


def _secret():
    try:
        return str(st.secrets["demo_key"]).strip()
    except Exception:
        return ""


KEY_FILE = pathlib.Path(tempfile.gettempdir()) / "peak_demo_access.txt"
_k = _secret()
try:
    if _k:
        if not KEY_FILE.exists() or KEY_FILE.read_text(encoding="utf-8") != _k:
            KEY_FILE.write_text(_k, encoding="utf-8")
    else:
        KEY_FILE.unlink(missing_ok=True)
except OSError:
    pass
os.environ["KAMP_DEMO_KEY_FILE"] = str(KEY_FILE)   # no secret or unreadable file -> the app stays locked


def _no_crash(mod, name):
    """Cloud disk can be read-only or reset: a failed state write must not take the screen down. Numbers are unaffected."""
    f = getattr(mod, name)
    if getattr(f, "_guarded", False):
        return

    def g(*a, **k):
        try:
            return f(*a, **k)
        except OSError:
            return 0
    g._guarded = True
    setattr(mod, name, g)


import ops_autoscore as _A   # noqa: E402
import ops_service as _O     # noqa: E402
_no_crash(_O, "save_last_gen")
_no_crash(_A, "append_log")


@st.cache_resource(show_spinner=False)
def _prep_demo_log():
    """Once per process: demo log scored up to the day before the demo day (same as run_local_j9.ps1)."""
    try:
        import ops_autoscore as A
        A.prep_demo_log()
        return True
    except Exception:
        return False


_prep_demo_log()
# Phone-first operator view by default (QR); ?v=full opens the full presentation screen.
VIEW = "viewer_ops_j9.py" if st.query_params.get("v") == "full" else "viewer_mobile.py"
runpy.run_path(str(P6 / VIEW), run_name="__main__")
