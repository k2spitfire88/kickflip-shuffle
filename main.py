"""Kickflip Shuffle — application entry point.

Run: `python main.py`. Importing this module is side-effect free (no QApplication
is created and no event loop runs at import) — construction lives in `main()` under
the `__main__` guard, so tests can import it without clashing with pytest-qt's
QApplication.
"""
import sys


def main():
    from app._bootstrap import bootstrap
    bootstrap()                                   # frozen dylib fixups — must be first
    from PySide6.QtWidgets import QApplication
    from app.ui import theme
    from app.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    app.setOrganizationName("Kickflip Shuffle")
    app.setApplicationName("Kickflip Shuffle")
    from app.ui.settings import Prefs
    prefs = Prefs()
    theme.apply(app, mode=prefs.theme())
    window = MainWindow(prefs=prefs)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
