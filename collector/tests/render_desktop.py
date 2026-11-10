"""Synthetic-only UI evidence harness; never included as an application mode."""

import argparse
import tkinter as tk
from pathlib import Path

from PIL import ImageGrab
from tanren_collector.desktop import Window


class FixtureSupervisor:
    def bindings(self):
        return ["synthetic-a", "synthetic-b"]

    def tick(self):
        return {
            "synthetic-a": {
                "state": "queued",
                "account_id": "11111111-1111-4111-8111-111111111111",
                "account_name": "Swing trading · Synthetic",
                "queue": {"pending": 2, "received": 1},
                "identity": {
                    "login": "12345",
                    "broker": "Synthetic Broker",
                    "server": "QA-Demo",
                    "currency": "USD",
                    "mode": "hedging",
                },
                "last_success": "2026-10-24T09:00:00+00:00",
            },
            "synthetic-b": {
                "state": "waiting_for_terminal",
                "account_id": "22222222-2222-4222-8222-222222222222",
                "account_name": "Intraday · Synthetic",
                "queue": {"pending": 0},
                "identity": {
                    "login": "67890",
                    "broker": "Synthetic Broker",
                    "server": "QA-Demo",
                    "currency": "EUR",
                    "mode": "netting",
                },
            },
        }

    def close(self):
        return None


def render(output):
    Path(output).mkdir(parents=True, exist_ok=True)
    for language, palette in (("en", "graphite"), ("uk", "ivory")):
        root = tk.Tk()
        window = Window(
            root, FixtureSupervisor(), {"locale": language, "palette": palette}, lambda _: None
        )
        root.title("Tanren Collector · SYNTHETIC QA")
        root.geometry("1100x860+0+0")
        window.tick()
        root.update()
        ImageGrab.grab(
            bbox=(
                root.winfo_rootx(),
                root.winfo_rooty(),
                root.winfo_rootx() + 1100,
                root.winfo_rooty() + 860,
            )
        ).save(Path(output) / f"desktop-{language}-{palette}.png")
        window.quit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    render(parser.parse_args().output)
