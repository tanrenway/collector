"""Names offered in the add-account form. Data only: no rules, limits or rankings of any firm.

The same set as the site's add-account list (``propFirms`` in frontend/lib/providers.ts); a test in
the monorepo keeps the two in step. Order here is alphabetical.
"""

import re

PROP_FIRMS = (
    "Alpha Capital Group",
    "Apex Trader Funding",
    "AquaFunded",
    "Audacity Capital",
    "Blue Guardian",
    "BrightFunded",
    "City Traders Imperium",
    "Crypto Fund Trader",
    "E8 Markets",
    "Fintokei",
    "For Traders",
    "FTMO",
    "Funded Trading Plus",
    "FundedNext",
    "Funding Pips",
    "FXIFY",
    "Goat Funded Trader",
    "Hola Prime",
    "Instant Funding",
    "Maven Trading",
    "The5ers",
    "Topstep",
)

# Compared with the MT5 company and server text, lower case, letters and digits only.
_HINTS = {
    "alphacapital": "Alpha Capital Group",
    "acgmarkets": "Alpha Capital Group",
    "apextrader": "Apex Trader Funding",
    "aquafunded": "AquaFunded",
    "audacitycapital": "Audacity Capital",
    "blueguardian": "Blue Guardian",
    "brightfunded": "BrightFunded",
    "citytraders": "City Traders Imperium",
    "cryptofundtrader": "Crypto Fund Trader",
    "rlcrates": "Crypto Fund Trader",
    "e8markets": "E8 Markets",
    "e8funding": "E8 Markets",
    "fintokei": "Fintokei",
    "fortraders": "For Traders",
    "ftmo": "FTMO",
    "fundedtradingplus": "Funded Trading Plus",
    "fundednext": "FundedNext",
    "fundingpips": "Funding Pips",
    "fxify": "FXIFY",
    "goatfunded": "Goat Funded Trader",
    "holaprime": "Hola Prime",
    "instantfunding": "Instant Funding",
    "maventrading": "Maven Trading",
    "the5ers": "The5ers",
    "fivepercentonline": "The5ers",
    "topstep": "Topstep",
}


def suggest_firm(broker, server):
    """A listed firm only when its name appears in the MT5 identity; otherwise an empty string."""
    text = re.sub(r"[^a-z0-9]", "", f"{broker} {server}".lower())
    return next((firm for hint, firm in _HINTS.items() if hint in text), "")
