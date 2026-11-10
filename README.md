# Tanren Collector

Tanren Collector is a small Windows app that reads your trades from a MetaTrader 5 terminal on
your computer and sends them to your [Tanren](https://tanrenway.com) trading journal.

- **Read-only.** It reads account and deal history through the official MetaTrader 5 Python
  package. It never opens, changes or closes positions.
- **Your MT5 password stays on your computer.** Collector talks to a terminal you are already
  signed in to. It connects to Tanren with its own device credential, stored with Windows DPAPI.
- **Open and verifiable.** The installer is built from this repository by GitHub Actions and
  published with a signed build attestation.

Download it from **https://tanrenway.com/collector/download**. The site serves exactly the files
published in this repository's releases.

## Verify an installer

The installer is not code-signed yet, so Windows SmartScreen warns before it runs. You can check
that a file is the one built here:

```powershell
Get-FileHash .\TanrenCollectorSetup-<version>.exe -Algorithm SHA256   # compare with the release page
gh attestation verify .\TanrenCollectorSetup-<version>.exe --repo <owner>/<repo>
gh release verify-asset v<version> .\TanrenCollectorSetup-<version>.exe --repo <owner>/<repo>
```

A matching checksum and attestation show that the file was built by this repository's release
workflow from the tagged commit. They do not prove the code is free of mistakes.

## Build it yourself

Windows 10/11 x64, Python 3.12.10, Inno Setup 6.7.1:

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
./collector/build/build.ps1 -ExpectedSourceSha (git rev-parse HEAD) -ApiOrigin https://tanrenway.com
```

`build.ps1` refuses a dirty checkout, installs only hash-pinned wheels and checks the toolchain
versions. Tests run on Linux or Windows:

```bash
pip install --require-hashes --only-binary=:all: -r collector/qt/requirements.lock
pip install --require-hashes -r collector/public/test-requirements.lock
QT_QPA_PLATFORM=offscreen PYTHONPATH=collector pytest collector/tests
```

## Releases

A release is made only by pushing a `vX.Y.Z` tag that equals `collector/tanren_collector/__init__.py`
`__version__`. The workflow builds, tests, attests and publishes an immutable GitHub Release after a
maintainer approves it. Tanren's server then fetches that release, verifies the attestation and the
checksum, and only then offers it on the website and to the in-app updater.

## Security

Please report vulnerabilities privately; see [SECURITY.md](SECURITY.md).

## License

Apache License 2.0, see [LICENSE](LICENSE) and [NOTICE](NOTICE). Third-party components are listed
in [collector/build/THIRD_PARTY.md](collector/build/THIRD_PARTY.md). The Tanren name and logo are
not covered by the license; see [TRADEMARKS.md](TRADEMARKS.md).

MetaTrader is a registered trademark of MetaQuotes Ltd. This project is not affiliated with or
endorsed by MetaQuotes.
