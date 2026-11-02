import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import tagsystem.client as client


class ConfigureTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        environ = patch.dict(os.environ, {"XDG_CONFIG_HOME": self.directory.name}, clear=True)
        environ.start()
        self.addCleanup(environ.stop)
        self.keys = {}
        for name, fake in [("keyring.get_password", lambda service, account: self.keys.get((service, account))),
                           ("keyring.set_password", lambda service, account, value: self.keys.__setitem__((service, account), value))]:
            patcher = patch(name, side_effect=fake)
            patcher.start()
            self.addCleanup(patcher.stop)

    def configure(self, url, key):
        with patch("builtins.input", return_value=url), patch("getpass.getpass", return_value=key), \
                patch("builtins.print"):
            client.configure(SimpleNamespace())

    def test_saves_normalized_url_and_key_keyed_by_server(self):
        self.configure(" http://192.168.1.50:8710/ ", "secret")
        saved = json.loads(Path(self.directory.name, "tag-system", "config.json").read_text())
        self.assertEqual(saved, {"server_url": "http://192.168.1.50:8710"})
        self.assertEqual(client.server_url(), "http://192.168.1.50:8710")
        self.assertEqual(client.headers(client.server_url()), {"x-api-key": "secret"})

    def test_existing_keyring_entry_is_kept_when_key_is_left_empty(self):
        # Keys saved by earlier clients use the same service/account pair.
        self.keys[("tag-system", "http://tag.test:8710")] = "older-key"
        self.configure("http://tag.test:8710", "")
        self.assertEqual(client.get_api_key(client.server_url()), "older-key")
        self.configure("", "newer-key")
        self.assertEqual(client.get_api_key("http://tag.test:8710"), "newer-key")

    def test_empty_key_without_a_saved_key_is_rejected_and_not_saved(self):
        with self.assertRaisesRegex(SystemExit, "No API key is saved"):
            self.configure("http://tag.test:8710", "")
        self.assertFalse(client.config_path().exists())

    def test_invalid_urls_are_rejected(self):
        for url in ["", "tag.test:8710", "ftp://tag.test", "http://tag.test/?key=1"]:
            with self.subTest(url=url), self.assertRaisesRegex(SystemExit, "http://HOST:PORT"):
                self.configure(url, "secret")

    def test_commands_require_a_configured_server(self):
        with self.assertRaisesRegex(SystemExit, "Run: tag configure"):
            client.server_url()
        client.config_path().parent.mkdir(parents=True)
        client.config_path().write_text("not json")
        with self.assertRaisesRegex(SystemExit, "Could not read"):
            client.server_url()


if __name__ == "__main__":
    unittest.main()
