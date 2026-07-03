"""Drag-out MIDI — a button you drag onto a DAW/EZD3 track to drop the generated
`.mid` directly, skipping the export→find→drag loop.

On drag-start the button renders the current spec to a `.mid` in a managed temp
dir (via the supplied `export_fn`) and hands the DAW a file URL. Temp files are
best-effort cleaned by `cleanup_temp_dir()` from `MainWindow.closeEvent`. This is
separate from the 6a "Export" (the user's chosen output folder).
"""
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt, QMimeData, QUrl
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QPushButton

_TEMP_DIR = Path(tempfile.gettempdir()) / "kickflip-shuffle"
_DRAG_THRESHOLD = 10          # px before a press becomes a drag


def temp_dir():
    _TEMP_DIR.mkdir(parents=True, exist_ok=True)
    return _TEMP_DIR


def cleanup_temp_dir():
    """Remove drag-export temp `.mid` files. Best-effort; called on app close."""
    if _TEMP_DIR.exists():
        for p in _TEMP_DIR.glob("*.mid"):
            try:
                p.unlink()
            except OSError:
                pass


class MidiDragButton(QPushButton):
    """Drag source. On a real drag it calls `export_fn(path) -> written_path` to
    render the `.mid`, then starts a QDrag carrying that file's URL. `enabled_fn`
    (if given) gates whether a drag may start (e.g. only when a spec exists)."""

    def __init__(self, text, export_fn, *, enabled_fn=None, on_status=None,
                 parent=None):
        super().__init__(text, parent)
        self._export_fn = export_fn
        self._enabled_fn = enabled_fn
        self._on_status = on_status
        self._press = None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press is None or not (event.buttons() & Qt.LeftButton):
            return
        if (event.position().toPoint() - self._press).manhattanLength() < _DRAG_THRESHOLD:
            return
        self._press = None
        self.start_drag()

    def mouseReleaseEvent(self, event):
        # A click (no drag) or a gated drag never reaches start_drag's exec(), so
        # reset the pressed state here. (For a started drag, exec() consumes the
        # release — start_drag clears setDown itself.)
        self._press = None
        self.setDown(False)
        super().mouseReleaseEvent(event)

    def start_drag(self):
        """Render the .mid and launch the drag. Returns the QDrag (or None if
        gated/failed) — split out so it is unit-testable without a mouse."""
        if self._enabled_fn is not None and not self._enabled_fn():
            return None
        path = str(temp_dir() / "kickflip-drums.mid")
        try:
            out = self._export_fn(path)
        except Exception as exc:                     # noqa: BLE001 - surface to UI
            if self._on_status is not None:
                self._on_status(f"Drag export failed: {exc}")
            return None
        drag = QDrag(self)
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(out))])
        drag.setMimeData(mime)
        if self._on_status is not None:
            self._on_status("Dragging drums .mid…")
        drag.exec(Qt.CopyAction)
        self.setDown(False)              # exec() consumed the release -> clear pressed
        return drag
