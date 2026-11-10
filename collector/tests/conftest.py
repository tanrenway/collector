"""Run direct QML tests with the same controls style as the desktop entry point."""

import pytest


@pytest.fixture(scope="session", autouse=True)
def desktop_controls_style():
    # Tests also construct QApplication/engines directly, without qt.main.main().
    # Native Windows styles reject our custom content items; production uses Basic.
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("QT_QUICK_CONTROLS_STYLE", "Basic")
        yield


def monorepo_file(relative):
    """A Tanren website file for cross-checks that run only inside the private monorepo.

    The public Collector repository has no website sources, so these contract checks skip there
    and keep running in the monorepo, where the website and the app change together.
    """
    from pathlib import Path

    import pytest

    path = Path(__file__).resolve().parents[2] / relative
    if not path.is_file():
        pytest.skip("website contract check; runs in the Tanren monorepo")
    return path


@pytest.fixture(scope="session", autouse=True)
def tk_init_retry():
    """Retry Tk start-up when Tcl intermittently fails to read init.tcl on Windows.

    On hosted Windows runners (and occasionally on a desktop), creating many Tk interpreters in
    one test process sometimes fails with "Can't find a usable init.tcl ... couldn't read file
    ...: No error" although the file exists. Only that exact start-up error is retried, after
    freeing the previous interpreters; anything else still fails the test. Application code is
    not changed.
    """
    import os

    if os.name != "nt":
        yield
        return
    import gc
    import time
    import tkinter

    original = tkinter.Tk.__init__

    def init(self, *args, **kwargs):
        for attempt in range(3):
            try:
                return original(self, *args, **kwargs)
            except tkinter.TclError as exc:
                if "init.tcl" not in str(exc) or attempt == 2:
                    raise
                gc.collect()
                time.sleep(0.25)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(tkinter.Tk, "__init__", init)
        yield
