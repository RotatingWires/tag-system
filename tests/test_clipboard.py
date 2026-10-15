import io
import os
from pathlib import Path
import runpy
import subprocess
import struct
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
import zlib
from unittest.mock import Mock, patch


client = runpy.run_path(str(Path(__file__).parents[1] / "client" / "tag"))
get = client["get"]
copy_to_clipboard = client["copy_to_clipboard"]
serve_clipboard_image = client["serve_clipboard_image"]
start_image_clipboard = client["start_image_clipboard"]


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
                    patch("shutil.which") as which, \
                    patch.dict(copy_to_clipboard.__globals__, start_image_clipboard=Mock()) as globals_:
                copy_to_clipboard(PNG, "image/png", "screenshot.png")
                start = globals_["start_image_clipboard"]
                command, payload = start.call_args.args
                self.assertEqual(command[:2], [sys.executable, "-c"])
                self.assertIn("serve_clipboard_image", command[2])
                self.assertEqual(command[-2:], ["image/png", "screenshot.png"])
                self.assertEqual(payload, PNG)
                which.assert_not_called()

    def test_image_copy_returns_after_ready_while_provider_stays_alive(self):
        command = [sys.executable, "-c",
                   "import sys,time; data=sys.stdin.buffer.read(); "
                   "assert data; print('ready',flush=True); time.sleep(10)"]
        popen = subprocess.Popen
        providers = []

        def launch(*args, **kwargs):
            process = popen(*args, **kwargs)
            providers.append(process)
            return process

        try:
            with patch("subprocess.Popen", side_effect=launch) as create:
                start = time.monotonic()
                start_image_clipboard(command, PNG)
                self.assertLess(time.monotonic() - start, 2)
            create.assert_called_once()
            self.assertTrue(create.call_args.kwargs["start_new_session"])
            self.assertIsNone(providers[0].poll())
            self.assertTrue(providers[0].stdin.closed)
            self.assertTrue(providers[0].stdout.closed)
        finally:
            for process in providers:
                process.terminate()
                process.wait(timeout=2)

    def test_provider_failure_reports_original_error_and_reaps_process(self):
        command = [sys.executable, "-c",
                   "import sys; sys.stdin.buffer.read(); sys.exit('image could not be decoded')"]
        popen = subprocess.Popen
        with patch("subprocess.Popen", side_effect=popen) as create:
            with self.assertRaisesRegex(OSError, "image could not be decoded"):
                start_image_clipboard(command, PNG)

    def test_unresponsive_provider_is_stopped_instead_of_reporting_success(self):
        command = [sys.executable, "-c", "import sys,time; sys.stdin.buffer.read(); time.sleep(10)"]
        popen = subprocess.Popen
        providers = []

        def launch(*args, **kwargs):
            process = popen(*args, **kwargs)
            providers.append(process)
            return process

        with patch("subprocess.Popen", side_effect=launch), \
                patch.dict(start_image_clipboard.__globals__, IMAGE_CLIPBOARD_START_TIMEOUT_SECONDS=0.1):
            with self.assertRaisesRegex(OSError, "did not become ready"):
                start_image_clipboard(command, PNG)
        self.assertIsNotNone(providers[0].returncode)

    def test_version_does_not_contact_server_or_keyring(self):
        with patch("requests.get") as request, patch("keyring.get_password") as key, \
                patch("sys.stdout", new_callable=io.StringIO) as output:
            with self.assertRaises(SystemExit) as exit_:
                client["parser"].parse_args(["--version"])
        self.assertEqual(exit_.exception.code, 0)
        self.assertEqual(output.getvalue(), f"Tag System {client['VERSION']}\n")
        request.assert_not_called()
        key.assert_not_called()

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
        self.assertEqual(timer.call_count, 2)
        self.assertEqual(timer.call_args_list[0].args[0], 0)
        with patch("builtins.print") as output:
            timer.call_args_list[0].args[1]()
        output.assert_called_once_with("ready", flush=True)
        timer.assert_any_call(client["IMAGE_CLIPBOARD_HOLD_MS"], app.quit)
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

    def test_get_combines_saved_text_and_urls_but_keeps_files_separate(self):
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
            expected = ["  first\nhttps://example.com\n雪\nlast  ".encode(), b"file text\n",
                        (Path(folder, "image.bin").as_uri() + "\r\n").encode()]
            self.assertEqual([c.kwargs["input"] for c in run.call_args_list], expected)
            self.assertEqual(run.call_args_list[2].args[0][-1], "text/uri-list")
            self.assertEqual(sleep.call_count, len(expected) - 1)
            for call in sleep.call_args_list:
                self.assertEqual(call.args, (client["CLIPBOARD_SETTLE_SECONDS"],))
            self.assertEqual(open_file.call_count, 2)
            self.assertEqual(request.call_count, 3)
            for call in request.call_args_list:
                self.assertEqual(call.kwargs["headers"], {"x-api-key": "test-key"})
            output.assert_any_call("Copied 3 items to clipboard")
            output.assert_any_call("Use clipboard history to select earlier items")

    def test_two_urls_and_screenshot_create_one_text_and_one_image_entry(self):
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
                patch.dict(get.__globals__, copy_to_clipboard=Mock(side_effect=lambda data, mime, filename:
                    events.append((mime, data, filename)))) as globals_, \
                patch("time.sleep", side_effect=lambda _: events.append("settle")), \
                patch("subprocess.Popen") as open_file, patch("builtins.print") as output:
            get(SimpleNamespace(name="he-on-dnd-screenshot", open_files=False))
            self.assertEqual(events, [
                ("text/plain;charset=utf-8", "https://example.com/one\nhttps://example.com/two", ""), "settle",
                ("image/png", image, "screenshot #1.png"),
            ])
            self.assertEqual(globals_["copy_to_clipboard"].call_count, 2)
            self.assertTrue(request.call_args.args[0].endswith("/he-on-dnd-screenshot/screenshot%20%231.png"))
            self.assertEqual(Path(folder, "screenshot #1.png").read_bytes(), image)
            open_file.assert_not_called()
            output.assert_any_call("Copied 2 items to clipboard")

    def test_text_only_tag_is_one_clipboard_item_without_waiting(self):
        tag = Mock(status_code=200)
        tag.json.return_value = {"items": [
            {"type": "text", "content": "  first"}, {"type": "url", "content": "https://example.com"},
            {"type": "text", "content": "last  "},
        ]}
        with patch("keyring.get_password", return_value="test-key"), patch("requests.get", return_value=tag), \
                patch("shutil.which", return_value="/usr/bin/xclip"), \
                patch("subprocess.run") as run, patch("time.sleep") as sleep, patch("builtins.print") as output:
            get(SimpleNamespace(name="text-only", open_files=False))
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.kwargs["input"], b"  first\nhttps://example.com\nlast  ")
            sleep.assert_not_called()
            output.assert_called_once_with("Copied 1 item to clipboard")

    def test_images_only_are_individual_items_without_an_empty_text_copy(self):
        tag = Mock(status_code=200)
        tag.json.return_value = {"items": [
            {"type": "file", "filename": "first.png"}, {"type": "file", "filename": "second.png"},
        ]}
        with tempfile.TemporaryDirectory() as folder, patch("tempfile.mkdtemp", return_value=folder), \
                patch("keyring.get_password", return_value="test-key"), \
                patch("requests.get", side_effect=[tag, Mock(raw=io.BytesIO(PNG)), Mock(raw=io.BytesIO(PNG))]), \
                patch.dict(get.__globals__, copy_to_clipboard=Mock()) as globals_, \
                patch("time.sleep") as sleep, patch("builtins.print"):
            get(SimpleNamespace(name="images-only", open_files=False))
            copies = globals_["copy_to_clipboard"].call_args_list
            self.assertEqual(len(copies), 2)
            self.assertEqual([c.args[2] for c in copies], ["first.png", "second.png"])
            self.assertTrue(all(c.args[0] == PNG for c in copies))
            sleep.assert_called_once_with(client["CLIPBOARD_SETTLE_SECONDS"])

    def test_clipboard_failure_stops_without_reporting_all_entries_copied(self):
        tag = Mock(status_code=200)
        tag.json.return_value = {"items": [
            {"type": "text", "content": "one"}, {"type": "file", "filename": "image.png"},
            {"type": "url", "content": "https://example.com"},
        ]}
        download = Mock(raw=io.BytesIO(PNG))
        with tempfile.TemporaryDirectory() as folder, patch("tempfile.mkdtemp", return_value=folder), \
                patch("keyring.get_password", return_value="test-key"), \
                patch("requests.get", side_effect=[tag, download]), \
                patch("time.sleep"), \
                patch.dict(get.__globals__, copy_to_clipboard=Mock(side_effect=[None, SystemExit("Could not copy image")])) as globals_, \
                patch("builtins.print") as output:
            with self.assertRaisesRegex(SystemExit, "Could not copy"):
                get(SimpleNamespace(name="test", open_files=False))
            self.assertEqual(globals_["copy_to_clipboard"].call_count, 2)
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
