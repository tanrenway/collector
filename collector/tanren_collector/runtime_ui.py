"""Minimal Tk compatibility panel. Commands only; all network/MT5 work is spawned."""

import tkinter as tk
import webbrowser
from tkinter import ttk

from .protocol import ORIGIN


class RuntimePanel:
    def __init__(self, window):
        self.window, self.runtime = window, window.supervisor
        self.uk = window.settings.get("locale") == "uk"
        self.local_error = None
        self.message = window.label(window.content, "", "Muted.TLabel")
        self.device = window.label(window.content, "", "Heading.TLabel")
        self.device_var = tk.StringVar(value="My Collector")
        self.code = tk.StringVar()
        for label, variable, secret in [
            ("Назва пристрою" if self.uk else "Device name", self.device_var, False),
            ("Код підключення" if self.uk else "Pairing code", self.code, True),
        ]:
            window.label(window.content, label)
            ttk.Entry(window.content, textvariable=variable, show="•" if secret else "").pack(
                fill="x", pady=4
            )
        self.button("Підключити пристрій", "Pair device", self.pair)
        self.confirm = tk.BooleanVar()
        ttk.Checkbutton(
            window.content,
            variable=self.confirm,
            text=self.text("Підтверджую повторне підключення", "Confirm re-pair"),
        ).pack(anchor="w", pady=4)
        window.label(
            window.content,
            self.text(
                "Старі черги зберігаються; може знадобитися перевірка прив’язки.",
                "Old queues stay and may require continuity review.",
            ),
        )
        self.button("Повторно підключити", "Re-pair", lambda: self.pair(True))
        self.button(
            "Відключити локально",
            "Disconnect locally",
            lambda: self.perform(self.runtime.disconnect_device),
        )
        window.label(
            window.content,
            self.text(
                "Локальне відключення зупиняє v3. Старі підключення керуються окремо; "
                "серверний доступ відкликається у Tanren.",
                "Local disconnect stops v3. Legacy connections are separate; "
                "revoke server access in Tanren.",
            ),
        )
        self.button(
            "Відкрити Tanren",
            "Open Tanren",
            lambda: webbrowser.open(ORIGIN + "/settings/collector"),
        )
        self.button(
            "Знайти термінали",
            "Discover terminals",
            lambda: self.perform(self.runtime.discover_accounts),
        )
        self.terminal = ttk.Combobox(window.content, state="readonly")
        self.terminal.pack(fill="x", pady=8)
        self.button(
            "Прочитати вибраний рахунок",
            "Read selected account",
            lambda: self.perform(lambda: self.runtime.preview_account(self.selected_terminal())),
        )
        self.preview = window.label(window.content, "", "Card.TLabel")
        self.fields = {}
        for key, uk, en in [
            ("name", "Назва рахунку", "Account name"),
            ("firm", "Фірма (вказана вами)", "Firm (user supplied)"),
            ("category", "Категорія", "Category"),
            ("journal_mode", "Режим журналу", "Journal mode"),
            ("timezone", "Часовий пояс IANA", "IANA timezone"),
            ("initial_balance", "Початковий баланс, якщо відомий", "Initial balance, if known"),
        ]:
            window.label(window.content, self.text(uk, en))
            if key in {"category", "journal_mode"}:
                field = ttk.Combobox(
                    window.content,
                    state="readonly",
                    values=["personal", "prop_firm", "demo"]
                    if key == "category"
                    else ["automatic", "semi_automatic"],
                )
            else:
                field = ttk.Entry(window.content)
            field.pack(fill="x", pady=3)
            self.fields[key] = field
        self.button("Зареєструвати вибраний рахунок", "Register selected account", self.register)
        self.accounts = ttk.Combobox(window.content, state="readonly")
        self.accounts.pack(fill="x", pady=12)
        self.account_info = window.label(window.content, "", "Card.TLabel")
        self.button(
            "Перевірити старі черги",
            "Inspect legacy queues",
            lambda: self.perform(lambda: self.runtime.migrate(self.selected_account())),
        )
        self.migration_confirm = tk.BooleanVar()
        ttk.Checkbutton(
            window.content,
            variable=self.migration_confirm,
            text=self.text(
                "Підтверджую перехід цього рахунку", "Confirm transition of this account"
            ),
        ).pack(anchor="w", pady=4)
        window.label(
            window.content,
            self.text(
                "Старі черги доставляються без зміни прив’язок та нових сканувань.",
                "Legacy queues drain without relabelling or new scans.",
            ),
        )
        self.button(
            "Доставити старі пакети без нового збору",
            "Drain old packets without capture",
            self.drain,
        )
        window.label(
            window.content,
            self.text(
                "Після завершення черг підтвердіть v3 у браузері, потім увімкніть рахунок.",
                "After draining, approve v3 handover in the browser, then enable this account.",
            ),
        )
        self.button(
            "Увімкнути v3 після підтвердження",
            "Enable v3 after confirmation",
            lambda: self.perform(
                lambda: self.runtime.account_action(self.selected_account(), "activate")
            ),
        )
        self.button(
            "Відновити раніше увімкнений рахунок",
            "Resume previously enabled account",
            lambda: self.perform(
                lambda: self.runtime.account_action(self.selected_account(), "resume")
            ),
        )
        self.button(
            "Призупинити рахунок",
            "Pause account",
            lambda: self.perform(
                lambda: self.runtime.account_action(self.selected_account(), "pause")
            ),
        )
        self.button(
            "Оновити стан / синхронізацію",
            "Refresh status / synchronization",
            lambda: self.perform(
                lambda: self.runtime.account_action(self.selected_account(), "step")
            ),
        )
        self.terminal_keys = []
        self.account_keys = []
        self.refresh()

    def text(self, uk, en):
        return uk if self.uk else en

    def button(self, uk, en, action):
        button = ttk.Button(self.window.content, text=self.text(uk, en), command=action)
        button.pack(fill="x", pady=4)
        return button

    def perform(self, action):
        try:
            action()
            self.local_error = None
            self.message.configure(
                text=self.text(
                    "Запит передано фоновому процесу", "Request submitted to background worker"
                )
            )
        except Exception as exc:
            from .engine import safe_error

            self.local_error = safe_error(exc)
            self.message.configure(text=self.local_error)

    def selected_terminal(self):
        if self.terminal.current() < 0:
            raise ValueError("EXPLICIT_ACCOUNT_SELECTION_REQUIRED")
        return self.terminal_keys[self.terminal.current()]

    def selected_account(self):
        if self.accounts.current() < 0:
            raise ValueError("EXPLICIT_ACCOUNT_SELECTION_REQUIRED")
        return self.account_keys[self.accounts.current()]

    def pair(self, repair=False):
        def submit():
            self.runtime.pair_device(
                self.code.get(), self.device_var.get(), repair=repair, confirmed=self.confirm.get()
            )
            self.code.set("")

        self.perform(submit)

    def register(self):
        def submit():
            metadata = {key: field.get() for key, field in self.fields.items() if field.get()}
            if not all(
                metadata.get(key)
                for key in ("name", "firm", "category", "journal_mode", "timezone")
            ):
                # First request may intentionally return metadata_required; never fabricate fields.
                metadata = None
            view = self.runtime.state.registration
            resume = (
                view.request_id
                if view.state == "metadata_required"
                and view.terminal_key == self.selected_terminal()
                else None
            )
            self.runtime.register_account(self.selected_terminal(), metadata, resume)

        self.perform(submit)

    def drain(self):
        self.perform(
            lambda: self.runtime.migrate(
                self.selected_account(), drain=True, confirmed=self.migration_confirm.get()
            )
        )

    def refresh(self):
        state = self.runtime.state
        self.device.configure(
            text=self.text("Пристрій: ", "Device: ")
            + state.device.state
            + " "
            + (state.device.verification_phrase or "")
            + " "
            + (state.device.error or "")
        )
        keys = [t.key for t in state.terminals]
        if keys != self.terminal_keys:
            self.terminal_keys = keys
            self.terminal.configure(values=[t.label for t in state.terminals])
        selected = self.terminal.current()
        if selected >= 0 and selected < len(state.terminals):
            t = state.terminals[selected]
            self.preview.configure(
                text=f"{t.broker or '—'} · {t.server or '—'} · •••• {t.login_suffix or '—'}"
            )
        keys = [a.binding_id for a in state.accounts]
        if keys != self.account_keys:
            self.account_keys = keys
            self.accounts.configure(
                values=[f"{n + 1} · {a.binding_id[:8]}" for n, a in enumerate(state.accounts)]
            )
        selected = self.accounts.current()
        if selected >= 0 and selected < len(state.accounts):
            a = state.accounts[selected]
            self.account_info.configure(
                text=f"{a.stage} · {a.role}\n"
                + self.text(
                    f"Черга {a.pending} · Обробка {a.processing} · Перевірка {a.review}",
                    f"Pending {a.pending} · Processing {a.processing} · Review {a.review}",
                )
                + "\n"
                + ", ".join(f"{j.state}" for j in a.force)
                + "\n"
                + (a.error or "")
            )
        registration = state.registration
        migration = state.migration
        self.message.configure(
            text=(state.error or self.local_error or "")
            + " "
            + registration.state
            + " "
            + (registration.error or "")
            + (" · " + migration.stage + " " + (migration.error or "") if migration else "")
        )
