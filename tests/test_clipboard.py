import io
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


client = runpy.run_path(str(Path(__file__).parents[1] / "client" / "tag"))
get = client["get"]
copy_to_clipboard = client["copy_to_clipboard"]


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
        run.assert_called_once_with(["xclip", "-selection", "clipboard"], input=b"one\ntwo", check=True)

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

    def test_get_copies_every_mixed_entry_once_in_stored_order(self):
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
                patch("tempfile.gettempdir", return_value=folder), \
                patch("keyring.get_password", return_value="test-key"), \
                patch("requests.get", side_effect=[tag, text_file, binary_file]) as request, \
                patch("shutil.which", return_value="/usr/bin/xclip"), \
                patch("subprocess.run") as run, patch("subprocess.Popen") as open_file, \
                patch("builtins.print") as output:
            get(SimpleNamespace(name="mixed", open_files=True))
            expected = (f"  first\nhttps://example.com\n[file: {folder}/notes.txt]\n"
                        f"file text\n\n雪\n[file: {folder}/image.bin]\n"
                        "[binary file contents not displayed]\nlast  ")
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.kwargs["input"], expected.encode())
            self.assertEqual(open_file.call_count, 2)
            self.assertEqual(request.call_count, 3)
            for call in request.call_args_list:
                self.assertEqual(call.kwargs["headers"], {"x-api-key": "test-key"})
            output.assert_called_once_with("Copied to clipboard")

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
