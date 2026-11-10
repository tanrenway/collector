"""Synthetic Tk layout/screenshots, NOT Windows DPI/MT5 E2E. Run only as explicit QA script."""

import json
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace

from PIL import ImageGrab
from render_desktop import FixtureSupervisor
from tanren_collector.desktop import Window
from tanren_collector.palette_tokens import PALETTES


class Supervisor(FixtureSupervisor):
    next = {}

    def discover(self):
        return SimpleNamespace(done=lambda: True, result=lambda: [])

    def probe(self, *_):
        return SimpleNamespace(
            done=lambda: True, result=lambda: self.tick()["synthetic-a"]["identity"]
        )


def run(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    results = []
    for language in ("en", "uk"):
        for palette in PALETTES:
            for scale in (1, 1.25, 1.5, 2):
                root = tk.Tk()
                root.tk.call("tk", "scaling", 96 / 72 * scale)
                errors = []
                root.report_callback_exception = lambda *e, bucket=errors: bucket.append(str(e[0]))
                window = Window(
                    root, Supervisor(), {"locale": language, "palette": palette}, lambda _: None
                )
                root.geometry("760x640+0+0")
                try:
                    window.tick()
                    root.update()
                    for page in ("home", "settings"):
                        window.navigate(page)
                        root.update()
                        for button in window.buttons:
                            if button.winfo_exists() and button.winfo_ismapped():
                                assert button.winfo_reqwidth() <= button.master.winfo_width() + 2, (
                                    language,
                                    palette,
                                    scale,
                                    page,
                                    button.cget("text"),
                                    button.winfo_reqwidth(),
                                    button.master.winfo_width(),
                                )
                        results.append(
                            {
                                "locale": language,
                                "palette": palette,
                                "tk_font_scale": scale,
                                "page": page,
                                "width": root.winfo_width(),
                                "height": root.winfo_height(),
                            }
                        )
                    assert not errors, errors
                    if scale == 1:

                        def capture(name, root=root):
                            root.geometry("1100x860+0+0")
                            root.update()
                            ImageGrab.grab(
                                bbox=(
                                    root.winfo_rootx(),
                                    root.winfo_rooty(),
                                    root.winfo_rootx() + 1100,
                                    root.winfo_rooty() + 860,
                                )
                            ).save(output / name)

                        window.navigate("home")
                        root.update()
                        capture(f"connections-{language}-{palette}.png")
                        if palette in ("graphite", "ivory"):
                            window.navigate("settings")
                            capture(f"settings-{language}-{palette}.png")
                            window.enrollment()
                            capture(f"wizard-find-{language}-{palette}.png")
                            window.wiz_path = "C:/synthetic/terminal64.exe"
                            window.identity = window.supervisor.tick()["synthetic-a"]["identity"]
                            window.advance_wizard(2)
                            capture(f"wizard-review-{language}-{palette}.png")
                            window.advance_wizard(3)
                            capture(f"wizard-token-{language}-{palette}.png")
                finally:
                    window.quit()
    (output / "layout-results.json").write_text(json.dumps(results, indent=2))
    print(json.dumps({"layout_cases": len(results), "real_windows_dpi": False, "errors": 0}))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    run(parser.parse_args().output)
