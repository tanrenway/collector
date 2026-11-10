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
