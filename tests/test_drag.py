"""Phase 8a drag-out MIDI tests — the MidiDragButton renders a real .mid and
carries its file URL; gating + temp cleanup (pytest-qt offscreen)."""
import mido
from PySide6.QtCore import QMimeData, QUrl

from app.controller import Controller
from app.ui import drag
from app.ui.drag import MidiDragButton, temp_dir, cleanup_temp_dir


def test_start_drag_writes_mid_and_sets_url(qtbot, monkeypatch):
    # Stub QDrag so exec() doesn't block on a real drag loop; capture the mime.
    captured = {}

    class _FakeDrag:
        def __init__(self, _src):
            pass

        def setMimeData(self, mime):
            captured["mime"] = mime

        def exec(self, _action):
            return 0

    monkeypatch.setattr(drag, "QDrag", _FakeDrag)

    c = Controller(seed=1)
    c.song_from_profile("pop_punk")
    btn = MidiDragButton("Drag", export_fn=lambda p: c.export(p),
                         enabled_fn=lambda: c.spec is not None)
    qtbot.addWidget(btn)

    result = btn.start_drag()
    assert result is not None
    mime = captured["mime"]
    assert isinstance(mime, QMimeData) and mime.hasUrls()
    url = mime.urls()[0]
    assert isinstance(url, QUrl) and url.toLocalFile().endswith(".mid")
    mido.MidiFile(url.toLocalFile())               # a real, re-readable .mid


def test_drag_gated_when_no_spec(qtbot):
    c = Controller()
    btn = MidiDragButton("Drag", export_fn=lambda p: c.export(p),
                         enabled_fn=lambda: c.spec is not None)
    qtbot.addWidget(btn)
    assert btn.start_drag() is None                # no spec -> no drag, no crash


def test_failed_export_no_crash_and_not_down(qtbot):
    def _boom(_path):
        raise RuntimeError("render failed")
    status = []
    btn = MidiDragButton("Drag", export_fn=_boom, enabled_fn=lambda: True,
                         on_status=status.append)
    qtbot.addWidget(btn)
    assert btn.start_drag() is None
    assert not btn.isDown()                        # visual state reset on failure
    assert status and "failed" in status[-1].lower()


def test_click_without_drag_resets_pressed_state(qtbot):
    from PySide6.QtCore import Qt as _Qt
    btn = MidiDragButton("Drag", export_fn=lambda p: p, enabled_fn=lambda: True)
    qtbot.addWidget(btn)
    qtbot.mouseClick(btn, _Qt.LeftButton)          # press+release, no drag
    assert not btn.isDown() and btn._press is None


def test_cleanup_removes_temp_mids():
    d = temp_dir()
    f = d / "kickflip-drums.mid"
    f.write_bytes(b"\x00")
    assert f.exists()
    cleanup_temp_dir()
    assert not f.exists()
