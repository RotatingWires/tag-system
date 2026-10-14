import io
import os
from pathlib import Path
import runpy
import subprocess
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
import zlib
from unittest.mock import Mock, patch


client = runpy.run_path(str(Path(__file__).parents[1] / "client" / "tag"))
get = client["get"]
copy_to_clipboard = client["copy_to_clipboard"]
serve_clipboard_image = client["serve_clipboard_image"]


def png_chunk(kind, data):
    body = kind + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xffffffff)


PNG = (b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
       + png_chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00\xff")) + png_chunk(b"IEND", b""))


class ClipboardTests(unittest.TestCase):
    def setUp(self):
        self.environ = patch.dict(os.environ, {}, clear=True)
        self.environ.start()
        self.addCleanup(self.environ.stop)

    def test_wayland_prefers_native_clipboard_even_with_xwayland(self):
        with patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0"}), \
                patch("shutil.which", return_value="/usr/bin/wl-copy"), \
                patch("subprocess.run") as run:
            copy_to_clipboard("  first\nsecond\n雪\n ")
        run.assert_called_once_with(
            ["wl-copy", "--type", "text/plain;charset=utf-8"],
            input="  first\nsecond\n雪\n ".encode("utf-8"), check=True,
        )

    def test_x11_uses_clipboard_selection(self):
        with patch("shutil.which", return_value="/usr/bin/xclip"), patch("subprocess.run") as run:
            copy_to_clipboard("one\ntwo")
        run.assert_called_once_with(
            ["xclip", "-selection", "clipboard", "-target", "UTF8_STRING"], input=b"one\ntwo", check=True,
        )

    def test_images_use_qt_worker_on_wayland_and_x11(self):
        for environment in [{"WAYLAND_DISPLAY": "wayland-0"}, {}]:
            with self.subTest(environment=environment), patch.dict(os.environ, environment, clear=True), \
                    patch("shutil.which") as which, patch("subprocess.run") as run:
                copy_to_clipboard(PNG, "image/png", "screenshot.png")
                command = run.call_args.args[0]
                self.assertEqual(command[:2], [sys.executable, "-c"])
                self.assertIn("serve_clipboard_image", command[2])
                self.assertEqual(command[-2:], ["image/png", "screenshot.png"])
                self.assertEqual(run.call_args.kwargs, {"input": PNG, "check": True})
                which.assert_not_called()

    def test_qt_image_offer_matches_spectacle_image_and_kde_metadata(self):
        app = Mock()
        with patch.dict(os.environ, {"DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-0"}), \
                patch("PySide6.QtGui.QGuiApplication", return_value=app) as create_app, \
                patch("PySide6.QtCore.QTimer.singleShot") as timer:
            serve_clipboard_image(PNG, "image/png", "screenshot-雪.png")
        mime, mode = app.clipboard.return_value.setMimeData.call_args.args
        self.assertTrue(mime.hasImage())
        self.assertEqual((mime.imageData().width(), mime.imageData().height()), (1, 1))
        self.assertEqual(bytes(mime.data("image/png")), PNG)
        self.assertTrue(mime.hasFormat("application/x-qt-image"))
        self.assertTrue(mime.hasFormat("x-kde-force-image-copy"))
        self.assertEqual(bytes(mime.data("application/x-kde-suggestedfilename")), "screenshot-雪.png".encode())
        create_app.assert_called_once_with(["tag", "-platform", "xcb"])
        timer.assert_called_once_with(client["IMAGE_CLIPBOARD_HOLD_MS"], app.quit)
        app.exec.assert_called_once()

    def test_invalid_image_is_rejected_before_opening_a_clipboard_connection(self):
        with patch("PySide6.QtGui.QGuiApplication") as create_app:
            with self.assertRaisesRegex(SystemExit, "could not be decoded"):
                serve_clipboard_image(b"not an image", "image/png", "broken.png")
            create_app.assert_not_called()

    def test_missing_xwayland_session_is_reported(self):
        with patch("PySide6.QtGui.QGuiApplication") as create_app:
            with self.assertRaisesRegex(SystemExit, "X11 or XWayland"):
                serve_clipboard_image(PNG, "image/png", "screenshot.png")
            create_app.assert_not_called()

    def test_missing_wayland_helper_reports_install_instruction(self):
        with patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-0"}), \
                patch("shutil.which", return_value=None), patch("subprocess.run") as run:
            with self.assertRaisesRegex(SystemExit, "Install wl-clipboard"):
                copy_to_clipboard("one\ntwo")
        run.assert_not_called()

    def test_clipboard_failure_is_not_success(self):
        with patch("shutil.which", return_value="/usr/bin/xclip"), \
                patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "xclip")):
            with self.assertRaisesRegex(SystemExit, "Could not copy tag contents"):
                copy_to_clipboard("one\ntwo")

    def test_get_copies_every_mixed_entry_separately_in_stored_order(self):
        items = [
            {"type": "text", "content": "  first"},
            {"type": "url", "content": "https://example.com"},
            {"type": "file", "filename": "notes.txt"},
            {"type": "text", "content": "雪"},
            {"type": "file", "filename": "image.bin"},
            {"type": "text", "content": "last  "},
        ]
        tag = Mock(status_code=200)
        tag.json.return_value = {"items": items}
        text_file = Mock(raw=io.BytesIO("file text\n".encode()))
        binary_file = Mock(raw=io.BytesIO(b"\xff\x00"))
        with tempfile.TemporaryDirectory() as folder, \
                patch("tempfile.mkdtemp", return_value=folder), \
                patch("keyring.get_password", return_value="test-key"), \
                patch("requests.get", side_effect=[tag, text_file, binary_file]) as request, \
                patch("shutil.which", return_value="/usr/bin/xclip"), \
                patch("subprocess.run") as run, patch("time.sleep") as sleep, \
                patch("subprocess.Popen") as open_file, \
                patch("builtins.print") as output:
            get(SimpleNamespace(name="mixed", open_files=True))
            expected = [b"  first", b"https://example.com", b"file text\n", "雪".encode(),
                        (Path(folder, "image.bin").as_uri() + "\r\n").encode(), b"last  "]
            self.assertEqual([c.kwargs["input"] for c in run.call_args_list], expected)
            self.assertEqual(run.call_args_list[4].args[0][-1], "text/uri-list")
            self.assertEqual(sleep.call_count, len(items) - 1)
            for call in sleep.call_args_list:
                self.assertEqual(call.args, (client["CLIPBOARD_SETTLE_SECONDS"],))
            self.assertEqual(open_file.call_count, 2)
            self.assertEqual(request.call_count, 3)
            for call in request.call_args_list:
                self.assertEqual(call.kwargs["headers"], {"x-api-key": "test-key"})
            output.assert_any_call("Copied 6 items to clipboard")
            output.assert_any_call("Use clipboard history to select earlier items")

    def test_two_urls_and_screenshot_create_three_typed_clipboard_entries(self):
        tag = Mock(status_code=200)
        tag.json.return_value = {"items": [
            {"type": "url", "content": "https://example.com/one"},
            {"type": "url", "content": "https://example.com/two"},
            {"type": "file", "filename": "screenshot #1.png"},
        ]}
        image = PNG
        download = Mock(raw=io.BytesIO(image))
        events = []
        with tempfile.TemporaryDirectory() as folder, \
                patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-0"}), \
                patch("tempfile.mkdtemp", return_value=folder), \
                patch("keyring.get_password", return_value="test-key"), \
                patch("requests.get", side_effect=[tag, download]) as request, \
                patch("shutil.which", return_value="/usr/bin/wl-copy"), \
                patch("subprocess.run", side_effect=lambda *a, **kw: events.append(
                    (a[0][-2] if a[0][0] == sys.executable else a[0][-1], kw["input"]))) as run, \
                patch("time.sleep", side_effect=lambda _: events.append("settle")), \
                patch("subprocess.Popen") as open_file, patch("builtins.print") as output:
            get(SimpleNamespace(name="he-on-dnd-screenshot", open_files=False))
            self.assertEqual(events, [
                ("text/plain;charset=utf-8", b"https://example.com/one"), "settle",
                ("text/plain;charset=utf-8", b"https://example.com/two"), "settle",
                ("image/png", image),
            ])
            self.assertEqual(run.call_count, 3)
            self.assertTrue(request.call_args.args[0].endswith("/he-on-dnd-screenshot/screenshot%20%231.png"))
            self.assertEqual(Path(folder, "screenshot #1.png").read_bytes(), image)
            open_file.assert_not_called()
            output.assert_any_call("Copied 3 items to clipboard")

    def test_clipboard_failure_stops_without_reporting_all_entries_copied(self):
        tag = Mock(status_code=200)
        tag.json.return_value = {"items": [
            {"type": "text", "content": "one"}, {"type": "text", "content": "two"},
            {"type": "text", "content": "three"},
        ]}
        with patch("keyring.get_password", return_value="test-key"), patch("requests.get", return_value=tag), \
                patch("shutil.which", return_value="/usr/bin/xclip"), patch("time.sleep"), \
                patch("subprocess.run", side_effect=[None, subprocess.CalledProcessError(1, "xclip")]) as run, \
                patch("builtins.print") as output:
            with self.assertRaisesRegex(SystemExit, "Could not copy"):
                get(SimpleNamespace(name="test", open_files=False))
            self.assertEqual(run.call_count, 2)
            output.assert_not_called()

    def test_empty_and_missing_tags_leave_clipboard_unchanged(self):
        for status, data in [(200, {"items": []}), (404, {"detail": "Tag not found"})]:
            with self.subTest(status=status), \
                    patch("keyring.get_password", return_value="test-key"), \
                    patch("requests.get", return_value=SimpleNamespace(status_code=status, json=lambda: data)), \
                    patch("subprocess.run") as run, patch("builtins.print"):
                get(SimpleNamespace(name="missing", open_files=False))
                run.assert_not_called()

    def test_download_failure_does_not_copy_partial_tag(self):
        tag = Mock(status_code=200)
        tag.json.return_value = {"items": [
            {"type": "text", "content": "first"}, {"type": "file", "filename": "missing.txt"},
        ]}
        download = Mock()
        download.raise_for_status.side_effect = RuntimeError("Download failed")
        with patch("keyring.get_password", return_value="test-key"), \
                patch("requests.get", side_effect=[tag, download]), patch("subprocess.run") as run:
            with self.assertRaisesRegex(RuntimeError, "Download failed"):
                get(SimpleNamespace(name="mixed", open_files=False))
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
