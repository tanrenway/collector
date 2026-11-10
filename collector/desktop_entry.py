"""Frozen bootstrap precedes GUI imports; failure reports never include native messages/paths."""

import multiprocessing
import sys

if __name__ == "__main__":
    # PyInstaller intercepts spawned children here, before Qt/Tk, MT5 or DPAPI initialization.
    multiprocessing.freeze_support()
    from tanren_collector.build_profile import configure_engineering_log

    configure_engineering_log()
    from tanren_collector.observability import capture, stage

    capture("bootstrap")
    if "--bridge-probe" in sys.argv:
        from tanren_collector.bridge_probe import main

        sys.exit(main())
    if "--self-test" in sys.argv:
        try:
            with stage("self_test"):
                from tanren_collector.selftest import run

                run()
        except Exception:
            from tanren_collector.diagnostics import write_bootstrap_report

            write_bootstrap_report()
            sys.exit(2)
        sys.exit(0)
    try:
        with stage("gui_start"):
            if "--tk-fallback" in sys.argv:
                from tanren_collector.desktop import main
            else:
                from tanren_collector.qt.main import main
            status = main(background="--background" in sys.argv)
            if isinstance(status, int):
                sys.exit(status)
    except Exception:
        from tanren_collector.diagnostics import write_bootstrap_report

        write_bootstrap_report()
        sys.exit(2)
