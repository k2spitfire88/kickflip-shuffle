"""Kickflip Shuffle — application entry point.

Run: `python main.py`. Importing this module is side-effect free (no QApplication
is created and no event loop runs at import) — construction lives in `main()` under
the `__main__` guard, so tests can import it without clashing with pytest-qt's
QApplication.
"""
import sys


def main():
    from PySide6.QtWidgets import QApplication
    from app.ui import theme
    from app.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    theme.apply(app, mode="dark")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
