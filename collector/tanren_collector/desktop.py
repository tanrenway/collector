"""Desktop presentation shell. MT5/network operations stay in the existing spawned Supervisor."""

import locale
import re
import sys
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, ttk
from tkinter import font as tkfont

from .application_runtime import ApplicationRuntime
from .build_profile import current
from .desktop_copy import COPY
from .desktop_model import display_time, effective_state, error_hint, masked_login
from .diagnostics import export
from .engine import safe_error
from .palette_tokens import PALETTES
from .protocol import ORIGIN, VERSION
from .runtime_ui import RuntimePanel
from .storage import DPAPI, load_config, save_config
from .tray import Tray
from .windows import (
    AppMutex,
    FileLock,
    autostart,
    autostart_enabled,
    data_directory,
    icon_path,
    show_existing,
)


class Window:
    def __init__(self, root, supervisor, settings, persist):
        self.root, self.supervisor, self.settings, self.persist = (
            root,
            supervisor,
            settings,
            persist,
        )
        self.closed, self.tray = False, None
        self.rows, self.jobs, self.metrics = {}, [], {}
        self.switch_images = {}
        self.page, self.epoch, self.modal = "home", 0, None
        self.task_number, self.timer = 0, None
        self.expanded, self.card_widgets = set(), {}
        self.root.title(current().display_name)
        self.root.geometry("1080x780")
        self.root.minsize(620, 440)
        self.configure_style()
        self.build()
        self.root.protocol("WM_DELETE_WINDOW", self.close_window)
        self.timer = self.root.after(100, self.tick)

    def t(self, key):
        return COPY.get(key, COPY["not_ready"])[self.settings.get("locale") == "uk"]

    def configure_style(self):
        bg, panel, text, muted, accent, ink = PALETTES.get(
            self.settings.get("palette"), PALETTES["graphite"]
        )
        self.colors = bg, panel, text, muted, accent
        self.root.configure(bg=bg)
        style = ttk.Style(self.root)
        style.theme_use("clam")
        family = "Segoe UI" if "Segoe UI" in tkfont.families(self.root) else "DejaVu Sans"
        style.configure(".", font=(family, 10), background=bg, foreground=text)
        for kind in ("TFrame", "TLabel"):
            style.configure(kind, background=bg)
        style.configure("Card.TFrame", background=panel, borderwidth=0, relief="flat")
        style.configure("Card.TLabel", background=panel)
        style.configure("CardHeading.TLabel", background=panel, font=(family, 14, "bold"))
        style.configure("Muted.TLabel", foreground=muted)
        style.configure("Title.TLabel", font=(family, 23, "bold"))
        style.configure("Heading.TLabel", font=(family, 14, "bold"))
        style.configure(
            "Hero.TLabel", foreground=accent, font=(family, 17, "bold"), background=panel
        )
        style.configure(
            "TButton",
            background=panel,
            foreground=text,
            padding=(14, 10),
            borderwidth=1,
            bordercolor=panel,
            lightcolor=panel,
            darkcolor=panel,
            focuscolor=accent,
            relief="flat",
        )
        style.map(
            "TButton",
            background=[("active", accent)],
            foreground=[("active", ink), ("disabled", muted)],
            bordercolor=[("focus", accent)],
        )
        style.configure(
            "Accent.TButton",
            background=accent,
            foreground=ink,
            bordercolor=accent,
            lightcolor=accent,
            darkcolor=accent,
            focuscolor=ink,
        )
        style.map("Accent.TButton", foreground=[("disabled", muted), ("active", ink)])
        style.configure("TEntry", fieldbackground=panel, foreground=text, padding=10)
        style.configure("TCombobox", fieldbackground=panel, foreground=text, padding=8)
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", panel)],
            foreground=[("readonly", text)],
            selectbackground=[("readonly", panel)],
            selectforeground=[("readonly", text)],
        )
        style.configure("TCombobox", background=panel, arrowcolor=muted, bordercolor=panel)
        for option, value in [
            ("background", panel),
            ("foreground", text),
            ("selectBackground", accent),
            ("selectForeground", ink),
        ]:
            self.root.option_add("*TCombobox*Listbox." + option, value)
        palette = self.settings.get("palette", "graphite")
        scale = max(1, self.root.winfo_fpixels("1i") / 96)
        indicator = "Tanren_" + palette + "_" + str(round(scale * 100)) + ".indicator"
        if indicator not in style.element_names():
            images = []
            for enabled in (False, True):
                image = tk.PhotoImage(
                    master=self.root, width=round(56 * scale), height=round(26 * scale)
                )
                image.put(panel, to=(0, 0, round(56 * scale), round(26 * scale)))
                for y in range(round(26 * scale)):
                    for x in range(round(44 * scale)):
                        px, py = x / scale, y / scale
                        cx = min(31, max(13, px))
                        if (px - cx) ** 2 + (py - 13) ** 2 <= 121:
                            image.put(accent if enabled else muted, to=(x, y))
                        if (px - (31 if enabled else 13)) ** 2 + (py - 13) ** 2 <= 64:
                            image.put(ink if enabled else panel, to=(x, y))
                images.append(image)
            self.switch_images[indicator] = images
            style.element_create(indicator, "image", images[0], ("selected", images[1]))
        style.layout(
            "Switch.TCheckbutton",
            [
                (
                    "Checkbutton.padding",
                    {
                        "sticky": "nswe",
                        "children": [
                            (indicator, {"side": "left"}),
                            (
                                "Checkbutton.focus",
                                {
                                    "side": "left",
                                    "sticky": "nswe",
                                    "children": [("Checkbutton.label", {"sticky": "nswe"})],
                                },
                            ),
                        ],
                    },
                )
            ],
        )
        style.configure(
            "Switch.TCheckbutton", background=panel, foreground=text, padding=8, focuscolor=accent
        )
        style.map(
            "Switch.TCheckbutton",
            foreground=[("disabled", muted)],
            background=[("disabled", panel), ("active", bg)],
        )

        style.configure("Vertical.TScrollbar", background=panel, troughcolor=bg, arrowcolor=muted)

    def label(self, parent, text, style="TLabel"):
        if getattr(parent, "is_card", False) and style == "Heading.TLabel":
            style = "CardHeading.TLabel"
        widget = ttk.Label(parent, text=text, style=style, wraplength=600, justify="left")
        widget.pack(anchor="w", fill="x", pady=(0, 10))
        self.wraps.append(widget)
        return widget

    def button(self, parent, key, command, accent=False, enabled=True):
        widget = ttk.Button(
            parent,
            text=self.t(key),
            command=lambda: self.act(command),
            style="Accent.TButton" if accent else "TButton",
            state="normal" if enabled else "disabled",
            takefocus=enabled,
        )
        widget.full_text = self.t(key)
        self.buttons.append(widget)
        widget.pack(anchor="w", pady=4)
        if getattr(parent, "binding_key", None):
            self.focusables[(parent.binding_key, key)] = widget
        return widget

    def card(self, parent):
        frame = ttk.Frame(parent, style="Card.TFrame", padding=20)
        frame.is_card = True
        frame.pack(fill="x", pady=(0, 14))
        return frame

    def build(self):
        self.epoch += 1
        self.wraps, self.buttons = [], []
        for child in self.root.winfo_children():
            if not isinstance(child, tk.Toplevel):
                child.destroy()
        bar = ttk.Frame(self.root, padding=(20, 14))
        bar.pack(fill="x")
        ttk.Label(bar, text="↗  Tanren", style="Heading.TLabel").pack(side="left")
        ttk.Label(bar, text="COLLECTOR", style="Muted.TLabel").pack(side="left", padx=16)
        body = ttk.Frame(self.root)
        body.pack(fill="both", expand=True)
        nav = ttk.Frame(body, padding=(16, 16))
        nav.pack(side="top", fill="x")
        ttk.Label(nav, text=VERSION, style="Muted.TLabel").pack(side="right", padx=8)
        tabs = ttk.Frame(nav)
        tabs.pack(side="left", fill="x", expand=True)
        buttons = [
            self.button(tabs, "home", lambda: self.navigate("home"), self.page == "home"),
            self.button(
                tabs, "settings", lambda: self.navigate("settings"), self.page == "settings"
            ),
        ]
        if hasattr(self.supervisor, "pair_device"):
            buttons.append(
                self.button(
                    tabs, "device_runtime", lambda: self.navigate("device"), self.page == "device"
                )
            )
        for button in buttons:
            button.pack_forget()

        def arrange_tabs(event):
            row = col = used = 0
            for button in buttons:
                width = button.winfo_reqwidth() + 8
                if used and used + width > event.width:
                    row += 1
                    col = used = 0
                button.grid(row=row, column=col, sticky="w", padx=(0, 8), pady=4)
                used += width
                col += 1

        tabs.bind("<Configure>", arrange_tabs)
        canvas = tk.Canvas(body, bg=self.colors[0], highlightthickness=0)
        scroll = ttk.Scrollbar(body, command=canvas.yview)
        scroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        canvas.configure(yscrollcommand=scroll.set)
        self.content = ttk.Frame(canvas, padding=(16, 16, 24, 24))
        self.canvas = canvas
        token = canvas.create_window((0, 0), window=self.content, anchor="nw")
        self.content.bind(
            "<Configure>", lambda _: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        def resize(event):
            canvas.itemconfigure(token, width=event.width)
            for label in self.wraps:
                if label.winfo_exists():
                    label.configure(wraplength=max(120, event.width - 90))
            font = tkfont.Font(self.root, font=ttk.Style(self.root).lookup(".", "font"))
            for button in self.buttons:
                if button.winfo_exists():
                    lines = []
                    line = ""
                    for word in button.full_text.split():
                        if line and font.measure(line + " " + word) > max(120, event.width - 200):
                            lines.append(line)
                            line = word
                        else:
                            line = (line + " " + word).strip()
                    lines.append(line)
                    button.configure(text="\n".join(lines))

        canvas.bind("<Configure>", resize)

        def reveal(event):
            widget = event.widget
            # Tcl-owned combobox popdowns are not Python widgets; modal/nav focus must not scroll
            # the underlying page. Only reveal actual controls belonging to this page container.
            if (
                not isinstance(widget, tk.Misc)
                or self.modal is not None
                or not str(widget).startswith(str(self.content) + ".")
            ):
                return
            try:
                y = widget.winfo_rooty() - self.content.winfo_rooty()
                viewport = canvas.canvasy(0)
                if y < viewport or y + widget.winfo_height() > viewport + canvas.winfo_height():
                    canvas.yview_moveto(max(0, y - 30) / max(1, self.content.winfo_height()))
            except tk.TclError:
                pass

        self.content.bind_all("<FocusIn>", reveal)

        def wheel(event):
            if self.modal is None:
                canvas.yview_scroll(-1 if event.delta > 0 or event.num == 4 else 1, "units")

        canvas.bind_all("<MouseWheel>", wheel)
        canvas.bind_all("<Button-4>", wheel)
        canvas.bind_all("<Button-5>", wheel)
        self.notice = self.label(self.content, "", "Muted.TLabel")
        if self.page == "home":
            self.home()
        elif self.page == "settings":
            self.preferences()
        elif self.page == "device":
            self.runtime_panel = RuntimePanel(self)
        elif self.page == "wizard":
            self.wizard()
        self.root.update_idletasks()

    def navigate(self, page):
        if hasattr(self, "runtime_panel"):
            self.runtime_panel.code.set("")
        if hasattr(self, "token"):
            self.token.set("")
        self.page = page
        self.build()

    def inform(self, key):
        self.notice.configure(text=self.t(key))

    def failure(self, exc):
        code = "BINDING_BUSY" if str(exc) == "BINDING_BUSY" else safe_error(exc)
        hint = "busy" if code == "BINDING_BUSY" else error_hint(code)
        diagnostic = getattr(exc, "collector_diagnostic", None)
        reference = (
            (" · " + diagnostic["stage"] + " · " + diagnostic["id"][:8]) if diagnostic else ""
        )
        self.notice.configure(
            text=(
                f"{self.t('failure')}\n{self.t('diagnostic_code')}: {code}{reference}"
                f"\n{self.t(hint)}"
            )
        )

    def act(self, action):
        try:
            return action()
        except Exception as exc:
            self.failure(exc)
        return None

    def task(self, future, callback, failed=None):
        self.task_number += 1
        self.jobs.append((future, callback, self.epoch, self.task_number, failed))

    def home(self):
        self.label(self.content, self.t("title"), "Title.TLabel")
        self.label(self.content, self.t("subtitle"), "Muted.TLabel")
        if hasattr(self.supervisor, "pair_device"):
            self.button(self.content, "device_runtime", lambda: self.navigate("device"), True)
            self.label(
                self.content,
                "Рахунки пристрою — у вкладці Пристрій / MT5. Нижче показано старі підключення."
                if self.settings.get("locale") == "uk"
                else "Device accounts are in Device / MT5. The connections below are legacy.",
                "Muted.TLabel",
            )
        self.hero = self.card(self.content)
        self.hero_text = self.label(self.hero, self.t("empty"), "Hero.TLabel")
        self.label(self.hero, self.t("status_hint"), "Card.TLabel")
        self.button(self.hero, "add", self.enrollment, True)
        self.account_area = ttk.Frame(self.content)
        self.account_area.pack(fill="x")
        self.card_widgets = {}
        # Counters retained for automation, but do not duplicate dashboard navigation/actions.
        self.metrics = {
            key: ttk.Label(self.content, text="0") for key in ("accounts", "queue", "attention")
        }
        self.update_accounts(force=True)

    def update_accounts(self, force=False):
        if self.page != "home":
            return
        keys = self.supervisor.bindings()
        states = [effective_state(self.rows.get(k, {})) for k in keys]
        state = (
            "empty"
            if not keys
            else "needs_attention"
            if any(s in ("error", "needs_attention", "authentication_expired") for s in states)
            else states[0]
            if len(set(states)) == 1
            else "processing"
        )
        self.hero_text.configure(text=self.t(state))
        signature = repr(([(k, self.rows.get(k, {})) for k in keys], sorted(self.expanded)))
        if not force and signature == getattr(self, "signature", None):
            return
        self.signature = signature
        focused = self.root.focus_get()
        restore = next(
            (key for key, widget in getattr(self, "focusables", {}).items() if widget == focused),
            None,
        )
        for child in self.account_area.winfo_children():
            child.destroy()
        self.card_widgets, self.focusables = {}, {}
        if not keys:
            self.label(self.account_area, self.t("empty_body"), "Muted.TLabel")
        for key in keys:
            item = self.rows.get(key, {})
            identity = item.get("identity") or {}
            card = self.card(self.account_area)
            self.card_widgets[key] = card
            card.binding_key = key
            actions = ttk.Frame(card, style="Card.TFrame")
            actions.binding_key = key
            self.label(
                card,
                item.get("account_name") or identity.get("broker") or self.t("not_ready"),
                "CardHeading.TLabel",
            )
            self.label(
                card,
                (
                    f"{masked_login(identity.get('login'))}  ·  {identity.get('server', '—')}"
                    f"  ·  {identity.get('currency', '—')}"
                ),
                "Card.TLabel",
            )
            self.label(card, self.t(effective_state(item)), "Card.TLabel")
            self.label(
                card,
                f"{self.t('last')}: {display_time(item.get('last_success')) or self.t('none')}",
                "Card.TLabel",
            )
            counts = item.get("queue", {})
            pending = counts.get("pending", 0) if "queue" in item else "—"
            processing = counts.get("received", 0) if "queue" in item else "—"
            self.label(
                card,
                (f"{self.t('queue')}: {pending}  ·  {self.t('processing')}: {processing}"),
                "Card.TLabel",
            )
            ready = (
                bool(item.get("account_id"))
                and item.get("pairing") != "awaiting_browser_confirmation"
            )
            primary = [
                self.button(
                    actions,
                    "sync",
                    lambda k=key: self.sync_selected(k),
                    enabled=ready and item.get("state") != "paused",
                )
            ]
            paused = item.get("state") == "paused"
            primary.append(
                self.button(
                    actions,
                    "resume" if paused else "pause",
                    lambda k=key, p=not paused: self.change_pause(k, p),
                    enabled=ready,
                )
            )
            primary.append(self.button(actions, "details", lambda k=key: self.toggle_detail(k)))
            actions.pack(fill="x", pady=8)
            for button in primary:
                button.pack_forget()

            def arrange(event, buttons=primary):
                col = row = used = 0
                for button in buttons:
                    width = button.winfo_reqwidth() + 8
                    if used and used + width > event.width:
                        row += 1
                        col = used = 0
                    button.grid(row=row, column=col, sticky="w", padx=(0, 8), pady=4)
                    used += width
                    col += 1

            actions.bind("<Configure>", arrange)
            if key in self.expanded:
                if item.get("error"):
                    code = safe_error(RuntimeError(item["error"]))
                    diagnostic = item.get("diagnostic")
                    reference = (
                        (" · " + diagnostic["stage"] + " · " + diagnostic["id"][:8])
                        if diagnostic
                        else ""
                    )
                    self.label(
                        card,
                        (
                            f"{self.t('diagnostic_code')}: {code}{reference}"
                            f"\n{self.t(error_hint(code))}"
                        ),
                        "Card.TLabel",
                    )
                if not item.get("account_name"):
                    self.label(card, self.t("name_pending"), "Card.TLabel")
                for status in item.get("force_jobs", {}).values():
                    self.label(card, self.t(status), "Card.TLabel")
                self.button(card, "retry", lambda k=key: self.retry_binding(k))
                self.button(card, "reconnect", lambda k=key: self.enrollment(k))
                self.button(card, "full", lambda k=key: self.full_sync(k), enabled=ready)
                self.button(card, "manage", lambda k=key: self.open_site(k))
                self.label(card, self.t("lifecycle"), "Card.TLabel")
        self.wraps = [widget for widget in self.wraps if widget.winfo_exists()]
        self.buttons = [widget for widget in self.buttons if widget.winfo_exists()]
        if restore and restore not in self.focusables and restore[1] in ("pause", "resume"):
            restore = (restore[0], "resume" if restore[1] == "pause" else "pause")
        if restore in self.focusables and self.focusables[restore].instate(["!disabled"]):
            self.focusables[restore].focus_set()
        for key, value in {
            "accounts": len(keys),
            "queue": sum(r.get("queue", {}).get("pending", 0) for r in self.rows.values()),
            "attention": sum(
                s in ("error", "needs_attention", "authentication_expired") for s in states
            ),
        }.items():
            self.metrics[key].configure(text=str(value))

    def toggle_detail(self, key):
        self.expanded.symmetric_difference_update({key})
        self.update_accounts(force=True)

    def retry_binding(self, key):
        self.supervisor.next[key] = 0
        self.inform("reading")

    def tick(self):
        if self.closed:
            return
        if self.timer:
            self.root.after_cancel(self.timer)
        statuses = self.supervisor.tick() or {}
        for future, callback, epoch, serial, failed in list(self.jobs):
            if future.done():
                self.jobs.remove((future, callback, epoch, serial, failed))
                if epoch == self.epoch and serial == self.task_number:
                    try:
                        callback(future.result())
                    except Exception as exc:
                        self.failure(exc)
                        if failed:
                            failed()
        for key, status in statuses.items():
            previous = self.rows.get(key, {})
            self.rows[key] = {**previous, **status}
            if "pairing" not in status:
                self.rows[key].pop("pairing", None)
            if (
                self.tray
                and self.settings.get("notifications")
                and status.get("state") != previous.get("state")
                and status.get("state") in ("needs_attention", "authentication_expired")
            ):
                self.act(
                    lambda value=status["state"]: self.tray.notify(
                        current().display_name, self.t(value)
                    )
                )
        if self.page == "device":
            self.runtime_panel.refresh()
        if self.page == "home":
            self.update_accounts()
        if self.page == "wizard" and self.wiz_step == 4:
            item = self.rows.get(self.wiz_key, {})
            failed = item.get("state") in (
                "authentication_expired",
                "needs_attention",
                "error",
                "paused",
                "disconnected",
            )
            paired = (
                bool(item.get("account_id"))
                and not failed
                and item.get("pairing") != "awaiting_browser_confirmation"
            )
            message = "paired" if paired else effective_state(item) if failed else "pending_pair"
            self.pair_result.configure(text=self.t(message))
            self.finish.configure(state="normal" if paired else "disabled")
            if item.get("error"):
                self.failure(RuntimeError(item["error"]))
        if self.tray and hasattr(self.tray, "set_status"):
            states = {effective_state(row) for row in self.rows.values()}
            if hasattr(self.supervisor, "diagnostic_statuses"):
                states.update(effective_state(row) for row in self.supervisor.diagnostic_statuses())
            summary = (
                next(iter(states)) if len(states) == 1 else "processing" if states else "empty"
            )
            if getattr(self, "tray_summary", None) != summary:
                self.act(lambda: self.tray.set_status(self.t(summary)))
                self.tray_summary = summary
        if self.tray and getattr(self.tray, "callback_failed", False):
            self.tray.close()
            self.tray = None
            self.show()
            self.inform("tray_missing")
        self.timer = self.root.after(250, self.tick)

    def sync_selected(self, key):
        def request():
            self.supervisor.request_sync(key)
            self.inform("check_requested")

        self.act(request)

    def sync_all(self):
        if hasattr(self.supervisor, "request_device_sync"):
            self.supervisor.request_device_sync()
        for key in self.supervisor.bindings():
            if self.rows.get(key, {}).get("state") != "paused":
                self.sync_selected(key)

    def change_pause(self, key, paused):
        def request():
            self.supervisor.pause(key, paused)
            self.inform("local_saved")

        self.act(request)

    def pause_all(self):
        states = [self.rows.get(k, {}).get("state") for k in self.supervisor.bindings()]
        if hasattr(self.supervisor, "set_device_pause"):
            states += [
                a.stage
                for a in self.supervisor.state.accounts
                if a.stage not in {"awaiting_handover", "continuity_review"}
            ]
        paused = not all(state == "paused" for state in states)
        if hasattr(self.supervisor, "set_device_pause"):
            self.supervisor.set_device_pause(paused)
        for key in self.supervisor.bindings():
            self.change_pause(key, paused)

    def open_site(self, key=None):
        import uuid

        account = self.rows.get(key, {}).get("account_id")
        try:
            account = str(uuid.UUID(account)) if account else None
        except (ValueError, TypeError):
            account = None

        def open_browser():
            if not webbrowser.open(
                ORIGIN + ("/accounts/" + account if account else "/accounts/mt5")
            ):
                raise RuntimeError("BROWSER_UNAVAILABLE")

        self.act(open_browser)

    def dialog(self, title, body, action):
        if self.modal:
            self.modal.lift()
            return
        previous = self.root.focus_get()
        window = tk.Toplevel(self.root)
        self.modal = window
        window.title(self.t(title))
        window.transient(self.root)
        window.configure(bg=self.colors[0])
        frame = ttk.Frame(window, padding=24)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=self.t(title), style="Heading.TLabel", wraplength=430).pack(
            anchor="w", pady=(0, 16)
        )
        ttk.Label(frame, text=self.t(body), wraplength=430, justify="left").pack(
            fill="x", pady=(0, 16)
        )

        def close():
            self.modal = None
            window.grab_release()
            window.destroy()
            if previous and previous.winfo_exists():
                previous.focus_set()

        self.button(frame, "cancel", close)

        def confirm():
            close()
            self.act(action)

        button = self.button(frame, "quit" if title == "quit" else "manage", confirm, True)
        window.protocol("WM_DELETE_WINDOW", close)
        window.bind("<Escape>", lambda _: close())
        window.bind("<Tab>", lambda e: self.dialog_tab(window, e))
        window.grab_set()
        button.focus_set()

    @staticmethod
    def dialog_tab(window, event):
        widget = event.widget.tk_focusPrev() if event.state & 1 else event.widget.tk_focusNext()
        if widget and str(widget).startswith(str(window)):
            widget.focus_set()
        else:
            children = []

            def walk(parent):
                for child in parent.winfo_children():
                    if isinstance(child, ttk.Button):
                        children.append(child)
                    walk(child)

            walk(window)
            if children:
                children[-1 if event.state & 1 else 0].focus_set()
        return "break"

    def full_sync(self, key):
        self.dialog("full", "full_body", lambda: self.open_site(key))

    def enrollment(self, key=None):
        self.wiz_key = key
        self.wiz_step = 1
        self.paths = []
        self.wiz_path = None
        self.identity = None
        self.navigate("wizard")

    def advance_wizard(self, number):
        self.wiz_step = number
        self.build()

    def wizard(self):
        self.label(self.content, self.t("add"), "Title.TLabel")
        self.label(
            self.content,
            f"{self.wiz_step} / 4   ·   {self.t('step' + str(self.wiz_step))}",
            "Heading.TLabel",
        )
        card = self.card(self.content)
        if self.wiz_step == 1:
            self.label(card, self.t("found"), "Card.TLabel")
            self.choice = ttk.Combobox(card, state="readonly", takefocus=True)
            self.choice.pack(fill="x", pady=12)
            self.scan_button = self.button(card, "scan", self.discover)
            self.button(card, "browse", self.browse)
            self.next_button = self.button(card, "next", self.read_choice, True, False)
            self.discover()
        elif self.wiz_step == 2:
            if self.identity:
                self.label(
                    card,
                    " · ".join(str(self.identity[k]) for k in ("broker", "server", "currency"))
                    + " · "
                    + self.t("mode_" + self.identity["mode"]),
                    "Card.TLabel",
                )
                self.label(card, masked_login(self.identity.get("login")), "Hero.TLabel")
                self.button(card, "next", lambda: self.advance_wizard(3), True)
            else:
                self.read_state = self.label(card, self.t("reading"), "Card.TLabel")
                self.read_button = self.button(card, "retry", self.read_active)
                self.read_active()
            self.button(card, "back", lambda: self.advance_wizard(1))
        elif self.wiz_step == 3:
            self.label(card, self.t("token_help"), "Card.TLabel")
            self.button(card, "site", self.open_site)
            self.label(card, self.t("token"), "Card.TLabel")
            self.token = tk.StringVar()
            entry = ttk.Entry(card, textvariable=self.token, show="•", takefocus=True)
            entry.pack(fill="x", pady=12)
            self.button(card, "connect", self.connect, True)
            self.button(card, "back", lambda: self.advance_wizard(2))
            entry.focus_set()
        else:
            self.pair_result = self.label(card, self.t("pending_pair"), "Card.TLabel")
            self.button(card, "site", lambda: self.open_site(self.wiz_key))
            self.finish = self.button(card, "done", lambda: self.navigate("home"), True, False)
        self.button(self.content, "cancel", lambda: self.navigate("home"))

    def discover(self):
        self.inform("scan")
        self.scan_button.configure(state="disabled")
        self.next_button.configure(state="disabled")

        def result(items):
            self.scan_button.configure(state="normal")
            self.notice.configure(text="")
            self.paths = [item["path"] for item in items]
            self.choice.configure(
                values=[
                    (
                        f"{Path(i['path']).parent.name} · "
                        f"{self.t('running' if i['running'] else 'installed')}"
                    )
                    for i in items
                ]
            )
            if items:
                self.choice.current(0)
                self.next_button.configure(state="normal")
            else:
                self.inform("not_found")
                self.next_button.configure(state="disabled")

        self.task(
            self.supervisor.discover(), result, lambda: self.scan_button.configure(state="normal")
        )

    def browse(self):
        path = filedialog.askopenfilename(
            parent=self.root, title=self.t("browse"), filetypes=[("MT5", "terminal64.exe")]
        )
        if path and Path(path).name.lower() == "terminal64.exe":
            self.task_number += 1  # Late discovery cannot override a selected fallback.
            self.scan_button.configure(state="normal")
            self.notice.configure(text="")
            self.paths = [path]
            self.choice.configure(values=[Path(path).parent.name])
            self.choice.current(0)
            self.next_button.configure(state="normal")

    def read_choice(self):
        if self.choice.current() < 0:
            return
        self.wiz_path = self.paths[self.choice.current()]
        self.identity = None
        self.advance_wizard(2)

    def read_active(self):
        self.read_state.configure(text=self.t("reading"))
        self.read_button.configure(state="disabled")

        def failed():
            self.read_state.configure(text=self.t("not_ready"))
            self.read_button.configure(state="normal")

        def result(identity):
            self.identity = identity
            self.advance_wizard(2)

        self.task(self.supervisor.probe(self.wiz_path), result, failed)

    def connect(self):
        token = self.token.get().strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{40,128}", token) or not self.identity:
            self.inform("invalid_token")
            return

        def action():
            key = self.supervisor.add(token, self.wiz_path, dict(self.identity), self.wiz_key)
            self.token.set("")
            self.wiz_key = key
            self.advance_wizard(4)

        self.act(action)

    def preferences(self):
        self.label(self.content, self.t("settings"), "Title.TLabel")
        card = self.card(self.content)
        self.label(card, self.t("appearance"), "Heading.TLabel")
        self.pref_controls = {}
        for key, values, labels in [
            ("palette", list(PALETTES), [self.t("palette_" + k) for k in PALETTES]),
            ("locale", ["en", "uk"], ["English", "Українська"]),
        ]:
            self.label(card, self.t("language" if key == "locale" else "palette"), "Card.TLabel")
            field = ttk.Combobox(card, state="readonly", values=labels, takefocus=True)
            self.pref_controls[key] = field
            field.current(values.index(self.settings.get(key, values[0])))
            field.pack(fill="x", pady=(0, 16))
            field.bind(
                "<<ComboboxSelected>>",
                lambda _, k=key, v=values, f=field: self.save_preference(k, v[f.current()]),
            )
        card = self.card(self.content)
        self.label(card, self.t("behavior"), "Heading.TLabel")
        if not getattr(sys, "frozen", False):
            self.label(card, self.t("installed_only"), "Card.TLabel")
        for key, label in [
            ("autostart", "autostart"),
            ("background", "background"),
            ("close_to_tray", "close_tray"),
            ("notifications", "notify"),
        ]:
            enabled = self.settings.get(key, key == "close_to_tray")
            text = f"{self.t(label)}  ·  {self.t('on' if enabled else 'off')}"
            variable = tk.BooleanVar(value=enabled)

            def toggle(k=key, var=variable):
                self.save_preference(k, var.get())
                var.set(self.settings.get(k, k == "close_to_tray"))

            button = ttk.Checkbutton(
                card,
                text=text,
                style="Switch.TCheckbutton",
                variable=variable,
                state="disabled"
                if key == "autostart" and not getattr(sys, "frozen", False)
                else "normal",
                command=toggle,
                takefocus=True,
            )
            button.full_text = text
            self.buttons.append(button)
            self.pref_controls[key] = button
            button.pack(anchor="w", fill="x", pady=5)
        card = self.card(self.content)
        self.label(card, self.t("automatic"), "Heading.TLabel")
        self.label(card, self.t("automatic_body"), "Card.TLabel")
        self.label(card, self.t("limits"), "Card.TLabel")
        card = self.card(self.content)
        self.label(card, self.t("support"), "Heading.TLabel")
        self.label(card, self.t("support_body"), "Card.TLabel")
        self.button(card, "export", self.diagnostics)
        card = self.card(self.content)
        self.label(card, self.t("updates"), "Heading.TLabel")
        self.label(card, current().display_name + " " + VERSION, "Card.TLabel")
        self.label(card, self.t("updates_body"), "Card.TLabel")
        self.button(card, "quit", lambda: self.dialog("quit", "quit_body", self.quit))

    def save_preference(self, key, value):
        def action():
            if key == "autostart":
                autostart(value)
            settings = {**self.settings, key: value}
            self.persist(settings)
            self.settings.update(settings)
            self.configure_style()
            self.build()
            self.inform("saved")
            if key in self.pref_controls:
                self.pref_controls[key].focus_set()
            if self.tray:
                self.tray_summary = None
                self.tray.labels = (
                    self.t("open"),
                    self.t("sync"),
                    self.t("quit"),
                    self.t("pause") + " / " + self.t("resume"),
                )

        self.act(action)

    def diagnostics(self):
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title=self.t("export"),
            defaultextension=".zip",
            filetypes=[("ZIP", "*.zip")],
        )
        if path:

            def action():
                export(
                    path,
                    self.supervisor.diagnostic_statuses()
                    if hasattr(self.supervisor, "diagnostic_statuses")
                    else list(self.rows.values()),
                )
                self.inform("exported")

            self.act(action)

    def close_window(self):
        if self.settings.get("close_to_tray", True) and self.tray:
            self.hide()
        else:
            self.dialog("quit", "quit_body", self.quit)

    def hide(self):
        if self.tray:
            self.root.withdraw()
        else:
            self.root.iconify()

    def show(self):
        self.root.deiconify()
        self.root.lift()

    def quit(self):
        if hasattr(self, "runtime_panel"):
            self.runtime_panel.code.set("")
        self.closed = True
        if self.timer:
            self.root.after_cancel(self.timer)
        if hasattr(self, "token"):
            self.token.set("")
        if self.tray:
            self.tray.close()
        self.supervisor.close()
        self.root.destroy()


def main(background=False):
    directory = data_directory()
    try:
        mutex = AppMutex()
    except RuntimeError:
        if not background:
            show_existing()
        return
    try:
        lock = FileLock(directory / "instance.lock")
    except OSError:
        mutex.close()
        if not background:
            show_existing()
        return
    protector = DPAPI()
    settings_path = directory / "settings.dpapi"
    settings = (
        load_config(settings_path, protector)
        if settings_path.exists()
        else {
            "locale": "uk" if (locale.getlocale()[0] or "").lower().startswith("uk") else "en",
            "palette": "graphite",
            "background": False,
            "close_to_tray": True,
            "autostart": False,
        }
    )
    settings["autostart"] = autostart_enabled()
    root = tk.Tk()
    if icon_path():
        root.iconbitmap(default=str(icon_path()))
    supervisor = ApplicationRuntime(directory)
    window = Window(
        root, supervisor, settings, lambda value: save_config(settings_path, value, protector)
    )
    try:
        window.tray = Tray(
            root,
            window.show,
            window.sync_all,
            window.quit,
            supervisor.resume,
            window.pause_all,
        )
        window.tray.can_sync = lambda: (
            any(
                row.get("account_id") and row.get("state") != "paused"
                for row in window.rows.values()
            )
            or any(
                a.stage not in {"paused", "awaiting_handover", "continuity_review"}
                for a in supervisor.state.accounts
            )
        )
        window.tray.can_pause = lambda: (
            any(row.get("account_id") for row in window.rows.values())
            or bool(supervisor.state.accounts)
        )
        window.tray.labels = (
            window.t("open"),
            window.t("sync"),
            window.t("quit"),
            window.t("pause") + " / " + window.t("resume"),
        )
    except RuntimeError:
        window.inform("tray_missing")
    if (background or settings.get("background")) and window.tray:
        root.withdraw()
    try:
        root.mainloop()
    finally:
        if not window.closed:
            supervisor.close()
        lock.close()
        mutex.close()
