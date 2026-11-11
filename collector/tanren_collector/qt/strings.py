"""Presentation strings only; no runtime state decisions."""

PAIRS = {
    "syntheticPreview": (
        "SYNTHETIC PREVIEW",
        "СИНТЕТИЧНИЙ ПЕРЕГЛЯД",
    ),
    "workspaceHint": (
        "Your trades, in your journal automatically",
        "Ваші угоди — автоматично в журналі",
    ),
    "running": (
        "Running",
        "Запущено",
    ),
    "stopped": (
        "Not observed running",
        "Запуск не підтверджено",
    ),
    "pathUnavailable": (
        "Local path unavailable",
        "Локальний шлях недоступний",
    ),
    "pairBeforeRegister": (
        "Connect this computer to Tanren first.",
        "Спершу підключіть цей комп’ютер до Tanren.",
    ),
    "registrationHint": (
        "Check the account details before adding it.",
        "Перевірте дані рахунку перед додаванням.",
    ),
    "shutdownHelp": (
        "Shutdown is delayed. Keep Collector open while active operations finish;"
        " do not reset local data.",
        "Завершення затримується. Залиште Collector відкритим до завершення "
        "операцій; не скидайте локальні дані.",
    ),
    "activity": (
        "Activity",
        "Активність",
    ),
    "connectApp": (
        "Connect application",
        "Підключити застосунок",
    ),
    "chooseStep": (
        "Choose accounts",
        "Вибрати рахунки",
    ),
    "readiness": (
        "Check synchronization",
        "Перевірити синхронізацію",
    ),
    "continue": (
        "Continue to accounts",
        "Перейти до рахунків",
    ),
    "advanced": (
        "Open help",
        "Відкрити допомогу",
    ),
    "activityHint": (
        "What has happened since Collector was opened.",
        "Що відбувалося відтоді, як ви відкрили Collector.",
    ),
    "noActivity": (
        "Nothing to show yet",
        "Поки що нічого не сталося",
    ),
    "search": (
        "Search…",
        "Пошук…",
    ),
    "noMatches": (
        "No matching accounts",
        "Збігів не знайдено",
    ),
    "retryAction": (
        "Retry connection check",
        "Перевірити підключення знову",
    ),
    "readyHint": (
        "Your MetaTrader 5 trades go to your Tanren journal automatically.",
        "Угоди з MetaTrader 5 автоматично потрапляють у ваш журнал Tanren.",
    ),
    "terminalHelp": (
        "Open MetaTrader 5 and sign in to this account. Collector never changes your login.",
        "Відкрийте MetaTrader 5 і увійдіть у цей рахунок. Collector не змінює ваш вхід.",
    ),
    "networkHelp": (
        "No connection to Tanren. Collector will retry on its own, and your data is safe.",
        "Немає зв’язку з Tanren. Collector спробує ще раз сам, ваші дані в безпеці.",
    ),
    "authHelp": (
        (
            "This computer no longer has access to your Tanren account: it was unlinked or its "
            "access was revoked on the website, or the sign-in expired. Your journal is safe. "
            "Create a new code on the Collector page of the Tanren site and pair again."
        ),
        (
            "Цей комп’ютер більше не має доступу до вашого акаунта Tanren: його відв’язали чи "
            "відкликали доступ на сайті, або вхід застарів. Ваш журнал у безпеці. Створіть "
            "новий код на сторінці Collector на сайті Tanren і підключіть комп’ютер знову."
        ),
    ),
    "conflictHelp": (
        (
            "This MetaTrader 5 account is already linked to another Tanren account or "
            "computer. Nothing was changed. Check that you are signed in to the right Tanren "
            "account, or unlink the account there first."
        ),
        (
            "Цей рахунок MetaTrader 5 уже прив’язано до іншого акаунта Tanren або комп’ютера. "
            "Нічого не змінено. Перевірте, що ви в правильному акаунті Tanren, або спершу "
            "відв’яжіть рахунок там."
        ),
    ),
    "scopeHelp": (
        (
            "This computer is not allowed to send this account. Check which accounts it may "
            "sync on the Collector page of the Tanren site."
        ),
        (
            "Цьому комп’ютеру не дозволено надсилати цей рахунок. Перевірте, які рахунки він "
            "може синхронізувати, на сторінці Collector на сайті Tanren."
        ),
    ),
    "statusDevicePaused": (
        "Paused — computer not connected",
        "Призупинено — комп’ютер не підключено",
    ),
    "disconnectAction": (
        "Disconnect computer",
        "Відключити комп’ютер",
    ),
    "repairAction": (
        "Pair again",
        "Підключити знову",
    ),
    "quitAction": (
        "Quit Collector",
        "Закрити Collector",
    ),
    "paletteSystem": (
        "Match Windows (light or dark)",
        "Як у Windows (світла чи темна)",
    ),
    "paletteSystemHint": (
        (
            "Horizon Graphite in dark mode, Horizon Paper in light mode. Choosing a palette "
            "below switches this off."
        ),
        (
            "Horizon Графіт у темному режимі, Horizon Папір у світлому. Вибір палітри нижче "
            "вимикає цей режим."
        ),
    ),
    "palette_obsidian": (
        "Horizon Night",
        "Horizon Ніч",
    ),
    "palette_midnight": (
        "Horizon Night Cyan",
        "Horizon Ніч Ціан",
    ),
    "palette_graphite": (
        "Horizon Graphite",
        "Horizon Графіт",
    ),
    "palette_carbon": (
        "Horizon Ember",
        "Horizon Жар",
    ),
    "palette_arctic": (
        "Horizon Day",
        "Horizon День",
    ),
    "palette_ivory": (
        "Horizon Paper",
        "Horizon Папір",
    ),
    "standbyHelp": (
        "This account is being synced from another computer.",
        "Цей рахунок синхронізується з іншого комп’ютера.",
    ),
    "continuityHelp": (
        "This computer was reconnected. Contact support so nothing is lost.",
        "Цей комп’ютер підключено заново. Зверніться до підтримки, щоб нічого не втратити.",
    ),
    "reviewAccess": (
        "Manage access in Tanren",
        "Керувати доступом у Tanren",
    ),
    "loading": (
        "Working…",
        "Виконується…",
    ),
    "stepLabel": (
        "Setup progress",
        "Кроки налаштування",
    ),
    "retry": (
        "Next attempt in (seconds)",
        "Наступна спроба за (секунд)",
    ),
    "expiresHint": (
        "Code expired? Create a new one on the Tanren site.",
        "Код уже не діє? Створіть новий на сайті Tanren.",
    ),
    "scheduled": (
        "Scheduled; waiting for updated status",
        "Заплановано; очікуємо оновлений стан",
    ),
    "welcome": (
        "Welcome",
        "Вітаємо",
    ),
    "dashboard": (
        "Overview",
        "Огляд",
    ),
    "accounts": (
        "Trading accounts",
        "Торгові рахунки",
    ),
    "add": (
        "Add account",
        "Додати рахунок",
    ),
    "details": (
        "Account details",
        "Деталі рахунку",
    ),
    "migration": (
        "Legacy migration",
        "Перехід зі старої версії",
    ),
    "settings": (
        "Settings",
        "Налаштування",
    ),
    "support": (
        "Help",
        "Допомога",
    ),
    "tagline": (
        "Your trading history. Always connected.",
        "Ваша торгова історія. Завжди на зв’язку.",
    ),
    "subtitle": (
        "One secure device. Every trading account.",
        "Один захищений пристрій. Усі торгові рахунки.",
    ),
    "pairTitle": (
        "Connect your Collector",
        "Підключіть Collector",
    ),
    "pairHint": (
        "Create a code in Tanren Web, then compare the verification phrase in your browser.",
        "Створіть код у Tanren Web, а потім звірте фразу підтвердження у браузері.",
    ),
    "deviceName": (
        "Device name",
        "Назва пристрою",
    ),
    "pairCode": (
        "Pairing code",
        "Код підключення",
    ),
    "pair": (
        "Pair device",
        "Підключити пристрій",
    ),
    "browser": (
        "Open Tanren",
        "Відкрити Tanren",
    ),
    "phrase": (
        "Verification phrase",
        "Фраза підтвердження",
    ),
    "repair": (
        "Connect again",
        "Підключити заново",
    ),
    "disconnect": (
        "Disconnect this computer",
        "Відключити цей комп’ютер",
    ),
    "repairWarning": (
        "Use this only if Collector stopped working. Your data stays on this "
        "computer, and support may need to help finish the reconnection.",
        "Робіть це, лише якщо Collector перестав працювати. Дані залишаться на "
        "цьому комп’ютері, а завершити підключення може допомогти підтримка.",
    ),
    "disconnectWarning": (
        "Collector will stop syncing accounts from this computer. Your journal "
        "stays as it is. To remove access completely, use Collector on the Tanren"
        " site.",
        "Collector перестане синхронізувати рахунки з цього комп’ютера. Журнал "
        "залишиться без змін. Щоб повністю закрити доступ, скористайтеся розділом"
        " Collector на сайті Tanren.",
    ),
    "registered": (
        "Accounts",
        "Рахунки",
    ),
    "active": (
        "Active",
        "Активний",
    ),
    "standby": (
        "On another computer",
        "На іншому комп’ютері",
    ),
    "unknown": (
        "Unknown",
        "Невідомо",
    ),
    "pending": (
        "Waiting to be sent",
        "Очікує надсилання",
    ),
    "processing": (
        "Updating journal",
        "Оновлюємо журнал",
    ),
    "lastProcessed": (
        "Journal last updated",
        "Журнал оновлено",
    ),
    "lastObserved": (
        "Last sync",
        "Остання синхронізація",
    ),
    "noAccounts": (
        "Your accounts will appear here",
        "Тут з’являться ваші рахунки",
    ),
    "noAccountsHint": (
        "Add a MetaTrader 5 account and your trades will start appearing in the "
        "journal. No trading password needed.",
        "Додайте рахунок MetaTrader 5, і угоди почнуть з’являтися в журналі. "
        "Торговий пароль не потрібен.",
    ),
    "notAvailable": (
        "Not available",
        "Недоступно",
    ),
    "device": (
        "This computer",
        "Цей комп’ютер",
    ),
    "paused": (
        "Paused",
        "Призупинено",
    ),
    "connected": (
        "Connected",
        "Підключено",
    ),
    "paired": (
        "Connected",
        "Підключено",
    ),
    "disconnected": (
        "Not connected",
        "Не підключено",
    ),
    "claiming": (
        "Contacting Tanren",
        "З’єднання з Tanren",
    ),
    "awaiting_browser_confirmation": (
        "Waiting for browser confirmation",
        "Очікуємо підтвердження у браузері",
    ),
    "authorization_required": (
        "Authorization required",
        "Потрібна авторизація",
    ),
    "locally_revoked": (
        "Disconnected locally",
        "Відключено локально",
    ),
    "awaiting_handover": (
        "Your action needed",
        "Потрібна ваша дія",
    ),
    "continuity_review": (
        "Contact support",
        "Зверніться до підтримки",
    ),
    "waiting": (
        "Retrying",
        "Повторюємо спробу",
    ),
    "syncing": (
        "Syncing",
        "Синхронізуємо",
    ),
    "access_denied": (
        "No access to this account",
        "Немає доступу до цього рахунку",
    ),
    "error": (
        "Needs attention",
        "Потребує уваги",
    ),
    "review": (
        "Needs review",
        "Потрібна перевірка",
    ),
    "needs_attention": (
        "Needs attention",
        "Потребує уваги",
    ),
    "needs_review": (
        "Some trades need checking on the Tanren site.",
        "Деякі угоди потрібно перевірити на сайті Tanren.",
    ),
    "partial": (
        "Partly updated",
        "Оновлено частково",
    ),
    "processed": (
        "Journal updated",
        "Журнал оновлено",
    ),
    "received": (
        "Updating journal",
        "Оновлюємо журнал",
    ),
    "complete": (
        "Complete",
        "Завершено",
    ),
    "cancelled": (
        "Cancelled",
        "Скасовано",
    ),
    "requested": (
        "Requested",
        "Запитано",
    ),
    "force": (
        "Full history update",
        "Оновлення всієї історії",
    ),
    "forceHint": (
        "Requested on the Tanren site. Collector is re-reading this account’s history.",
        "Запитано на сайті Tanren. Collector заново читає історію цього рахунку.",
    ),
    "pause": (
        "Pause",
        "Призупинити",
    ),
    "resume": (
        "Resume",
        "Відновити",
    ),
    "refresh": (
        "Sync now",
        "Синхронізувати",
    ),
    "discover": (
        "Find MT5 terminals",
        "Знайти термінали MT5",
    ),
    "chooseTerminal": (
        "Select a terminal",
        "Виберіть термінал",
    ),
    "preview": (
        "Read account",
        "Прочитати рахунок",
    ),
    "identityHint": (
        "Open MetaTrader 5, sign in to the account, then find it here. Collector "
        "only reads your history and never places trades.",
        "Відкрийте MetaTrader 5, увійдіть у потрібний рахунок і знайдіть його "
        "тут. Collector лише читає історію й ніколи не торгує.",
    ),
    "name": (
        "Account name",
        "Назва рахунку",
    ),
    "showAdvanced": (
        "More options",
        "Додаткові параметри",
    ),
    "hideAdvanced": (
        "Hide options",
        "Сховати параметри",
    ),
    "registrationDenied": (
        "This computer is not allowed to add accounts. In Tanren Web open "
        "Collector, choose this computer and select Allow account registration.",
        "Цьому комп’ютеру не дозволено додавати рахунки. На сайті відкрийте "
        "Collector, виберіть цей комп’ютер і натисніть «Дозволити реєстрацію "
        "рахунків».",
    ),
    "busyHelp": (
        "Collector is finishing another action. Try again in a few seconds.",
        "Collector завершує іншу дію. Спробуйте ще раз за кілька секунд.",
    ),
    "pickTerminal": (
        "Choose terminal manually",
        "Вказати термінал вручну",
    ),
    "noTerminalsHint": (
        "No terminals yet. Search again, or choose terminal64.exe manually.",
        "Терміналів ще немає. Запустіть пошук або вкажіть файл terminal64.exe вручну.",
    ),
    "deleteOnSite": (
        "Delete on the site",
        "Видалити на сайті",
    ),
    "firm": (
        "Prop firm or broker",
        "Пропфірма або брокер",
    ),
    "howAdd": (
        "You don’t need to create anything on the site: Collector adds the "
        "account for you. Choose any name you like.",
        "На сайті нічого створювати не потрібно: Collector додасть рахунок сам. "
        "Назву можна вказати будь-яку.",
    ),
    "chartsHint": (
        "Automatic charts are a separate option in the account settings on the site.",
        "Автоматичні графіки вмикаються окремо в налаштуваннях рахунку на сайті.",
    ),
    "category": (
        "Category",
        "Категорія",
    ),
    "categoryHint": (
        "Choose the account type: personal, prop firm or demo. We couldn’t tell it from MT5.",
        "Оберіть тип рахунку: особистий, пропфірма чи демо. "
        "За даними MT5 його не вдалося визначити.",
    ),
    "personal": (
        "Personal",
        "Особистий",
    ),
    "prop_firm": (
        "Prop firm",
        "Пропфірма",
    ),
    "demo": (
        "Demo",
        "Демо",
    ),
    "choose": (
        "Select…",
        "Виберіть…",
    ),
    "timezone": (
        "Time zone",
        "Часовий пояс",
    ),
    "baseline": (
        "Initial balance",
        "Початковий баланс",
    ),
    "baselineHint": (
        "We couldn’t find this in your MT5 history. Enter it if you know it, or leave it blank.",
        "В історії MT5 цього не знайшлося. Вкажіть суму, якщо знаєте, або залиште порожнім.",
    ),
    "baselineFound": (
        "Taken from your first deposits in MT5. Please check the amount.",
        "Узято з перших депозитів у MT5. Перевірте суму.",
    ),
    "register": (
        "Add account",
        "Додати рахунок",
    ),
    "metadata_required": (
        "Complete required metadata",
        "Заповніть обов’язкові відомості",
    ),
    "created": (
        "Account registered",
        "Рахунок зареєстровано",
    ),
    "linked": (
        "Account linked",
        "Рахунок прив’язано",
    ),
    "identity_conflict": (
        "Identity conflict: review before retry",
        "Конфлікт ідентичності: перевірте перед повтором",
    ),
    "account_policy_blocked": (
        "Account policy blocks registration",
        "Політика рахунку блокує реєстрацію",
    ),
    "idle": (
        "Ready",
        "Готово",
    ),
    "chooseAccount": (
        "Select an account",
        "Виберіть рахунок",
    ),
    "migrationHint": (
        "Keep existing local history. Finish pending delivery, then approve this "
        "account in the browser before starting capture.",
        "Збережіть локальну історію. Завершіть доставку даних та схваліть цей "
        "рахунок у браузері перед початком збору.",
    ),
    "inspect": (
        "Inspect local queues",
        "Перевірити локальні черги",
    ),
    "drain": (
        "Finish pending synchronization",
        "Завершити попередню синхронізацію",
    ),
    "confirmDrain": (
        "I confirm the transition of this account only.",
        "Підтверджую перехід лише цього рахунку.",
    ),
    "awaiting_confirmation": (
        "Review and confirm drain",
        "Перевірте та підтвердіть доставку",
    ),
    "draining": (
        "Draining legacy data",
        "Доставка старих даних",
    ),
    "waiting_for_legacy_turns": (
        "Waiting for legacy workers",
        "Очікування старих worker-процесів",
    ),
    "blocked": (
        "Review required; queues kept",
        "Потрібна перевірка; черги збережено",
    ),
    "enable": (
        "Start after browser approval",
        "Почати після схвалення у браузері",
    ),
    "updates": (
        "Updates",
        "Оновлення",
    ),
    "installedVersion": (
        "Installed version",
        "Встановлена версія",
    ),
    "checkUpdates": (
        "Check for updates",
        "Перевірити оновлення",
    ),
    "downloadUpdate": (
        "Download update",
        "Завантажити оновлення",
    ),
    "installUpdate": (
        "Install and restart",
        "Встановити й перезапустити",
    ),
    "updateAvailableShort": (
        "Update available",
        "Є оновлення",
    ),
    "update_idle": (
        "Check whether a newer version is available.",
        "Перевірте, чи вийшла нова версія.",
    ),
    "update_checking": (
        "Checking…",
        "Перевіряємо…",
    ),
    "update_current": (
        "You have the latest version.",
        "У вас остання версія.",
    ),
    "update_available": (
        "A new version is available:",
        "Доступна нова версія:",
    ),
    "update_downloading": (
        "Downloading the update…",
        "Завантажуємо оновлення…",
    ),
    "update_ready": (
        "Ready to install. Collector will close while the installer runs.",
        "Готово до встановлення. Collector закриється на час установки.",
    ),
    "update_error": (
        "The update could not be completed. Try again later.",
        "Не вдалося виконати оновлення. Спробуйте пізніше.",
    ),
    "updateUnsigned": (
        "The installer has no digital signature, so Windows may show a warning.",
        "Інсталятор не має цифрового підпису, тому Windows може показати попередження.",
    ),
    "appearance": (
        "Language & appearance",
        "Мова й оформлення",
    ),
    "appearanceHint": (
        "Language, colours and app behaviour.",
        "Мова, кольори й поведінка застосунку.",
    ),
    "palette": (
        "Color palette",
        "Кольорова палітра",
    ),
    "behaviour": (
        "Behaviour",
        "Поведінка",
    ),
    "dark": (
        "Dark",
        "Темна",
    ),
    "light": (
        "Light",
        "Світла",
    ),
    "selected": (
        "Selected",
        "Вибрано",
    ),
    "deviceHint": (
        "This computer sends your MetaTrader 5 trades to Tanren.",
        "Цей комп’ютер надсилає ваші угоди з MetaTrader 5 у Tanren.",
    ),
    "language": (
        "Language",
        "Мова",
    ),
    "motion": (
        "Reduce motion",
        "Зменшити анімацію",
    ),
    "closeTray": (
        "Close to system tray",
        "Закривати в системний трей",
    ),
    "autostart": (
        "Start when I sign in",
        "Запускати під час входу",
    ),
    "notifications": (
        "Desktop notifications",
        "Сповіщення на робочому столі",
    ),
    "installedOnly": (
        "Available in the installed version of Collector.",
        "Доступно у встановленій версії Collector.",
    ),
    "export": (
        "Save report for support",
        "Зберегти звіт для підтримки",
    ),
    "exportHint": (
        "If you contact support, attach this file. It contains no passwords, trades or file paths.",
        "Додайте цей файл, якщо звертаєтеся до підтримки. У ньому немає паролів, "
        "угод і шляхів до файлів.",
    ),
    "stage": (
        "Stage",
        "Етап",
    ),
    "correlation": (
        "Correlation ID",
        "Ідентифікатор звернення",
    ),
    "help": (
        "Please don’t delete Collector’s data to fix a problem. Your trades could be delayed.",
        "Не видаляйте дані Collector, щоб виправити проблему: синхронізація угод може затриматися.",
    ),
    "submitted": (
        "Request sent; waiting for confirmation",
        "Запит надіслано; очікуємо підтвердження",
    ),
    "confirmed": (
        "Action confirmed",
        "Дію підтверджено",
    ),
    "failed": (
        "Action failed",
        "Помилка дії",
    ),
    "noErrors": (
        "Everything is working",
        "Усе працює",
    ),
    "offlineHint": (
        "Your data is safe and will be sent when the connection returns.",
        "Ваші дані в безпеці й надійдуть, коли зв’язок відновиться.",
    ),
    "confirm": (
        "Confirm",
        "Підтвердити",
    ),
    "cancel": (
        "Cancel",
        "Скасувати",
    ),
    "quit": (
        "Quit Collector",
        "Завершити Collector",
    ),
    "quitHint": (
        "New trades won’t sync until you open Collector again. Your data is safe.",
        "Нові угоди не синхронізуватимуться, доки ви знову не відкриєте Collector. Дані в безпеці.",
    ),
    "suspended": (
        "Windows suspended — synchronization paused",
        "Windows призупинено — синхронізацію зупинено",
    ),
    "noActivityHint": (
        "Connections and journal updates will appear here.",
        "Тут з’являтимуться підключення й оновлення журналу.",
    ),
    "supportHint": (
        "What to do if something isn’t working.",
        "Що робити, якщо щось не працює.",
    ),
    "lastSync": (
        "Last sync",
        "Остання синхронізація",
    ),
    "mt5Account": (
        "MT5 account",
        "Рахунок MT5",
    ),
    "broker": (
        "Broker",
        "Брокер",
    ),
    "server": (
        "Server",
        "Сервер",
    ),
    "todayAt": (
        "Today at {time}",
        "Сьогодні о {time}",
    ),
    "yesterdayAt": (
        "Yesterday at {time}",
        "Вчора о {time}",
    ),
    "notYet": (
        "Not yet",
        "Ще не було",
    ),
    "statusSyncing": (
        "Syncing",
        "Синхронізується",
    ),
    "statusPaused": (
        "Paused",
        "Призупинено",
    ),
    "statusRetrying": (
        "Retrying",
        "Повторюємо спробу",
    ),
    "statusAction": (
        "Your action needed",
        "Потрібна ваша дія",
    ),
    "statusStandby": (
        "On another computer",
        "На іншому комп’ютері",
    ),
    "statusChecking": (
        "Checking",
        "Перевіряємо",
    ),
    "overviewOk": (
        "Everything is working",
        "Усе працює",
    ),
    "overviewOkHint": (
        "New trades will appear in your journal automatically.",
        "Нові угоди з’являтимуться в журналі автоматично.",
    ),
    "overviewAttention": (
        "One thing needs a look",
        "Дещо потребує уваги",
    ),
    "overviewAttentionHint": (
        "Check the accounts below. Your data is safe.",
        "Перегляньте рахунки нижче. Ваші дані в безпеці.",
    ),
    "overviewPaused": (
        "Sync is paused",
        "Синхронізацію призупинено",
    ),
    "overviewPausedHint": (
        "New trades won’t arrive until you resume.",
        "Нові угоди не надходитимуть, доки ви не відновите синхронізацію.",
    ),
    "overviewNoDevice": (
        "This computer isn’t connected",
        "Цей комп’ютер не підключено",
    ),
    "overviewNoDeviceHint": (
        "Connect it to Tanren to start syncing your trades.",
        "Підключіть його до Tanren, щоб почати синхронізацію угод.",
    ),
    "overviewEmpty": (
        "Add your first account",
        "Додайте перший рахунок",
    ),
    "overviewEmptyHint": (
        "It takes about a minute.",
        "Це займе близько хвилини.",
    ),
    "helpTitle": (
        "If your trades aren’t arriving",
        "Якщо угоди не надходять",
    ),
    "helpStepTerminal": (
        "Make sure MetaTrader 5 is open and signed in to this account.",
        "Переконайтеся, що MetaTrader 5 відкрито і ви увійшли в цей рахунок.",
    ),
    "helpStepNetwork": (
        "Check your internet connection.",
        "Перевірте підключення до інтернету.",
    ),
    "helpStepAccess": (
        "On the Tanren site, check that this computer still has access.",
        "На сайті Tanren перевірте, чи цей комп’ютер досі має доступ.",
    ),
    "exportTitle": (
        "Need more help?",
        "Потрібна додаткова допомога?",
    ),
    "technicalDetails": (
        "Details for support",
        "Дані для підтримки",
    ),
    "activity_device_paired": (
        "This computer connected to Tanren",
        "Комп’ютер підключено до Tanren",
    ),
    "activity_device_awaiting_browser_confirmation": (
        "Waiting for your confirmation in the browser",
        "Очікуємо підтвердження у браузері",
    ),
    "activity_device_disconnected": (
        "This computer disconnected",
        "Комп’ютер відключено",
    ),
    "activity_accounts_processed": (
        "Journal updated",
        "Журнал оновлено",
    ),
    "activity_accounts_processing": (
        "Trades sent to your journal",
        "Угоди надіслано в журнал",
    ),
    "activity_accounts_syncing": (
        "Sending new data",
        "Надсилаємо нові дані",
    ),
    "activity_accounts_active": (
        "Account is syncing",
        "Рахунок синхронізується",
    ),
    "activity_accounts_paused": (
        "Sync paused",
        "Синхронізацію призупинено",
    ),
    "activity_accounts_waiting": (
        "Connection problem, retrying",
        "Проблема зі зв’язком, повторюємо",
    ),
    "activity_accounts_standby": (
        "Account moved to another computer",
        "Рахунок перейшов на інший комп’ютер",
    ),
}


def words(language):
    return {key: value[language == "uk"] for key, value in PAIRS.items()}
