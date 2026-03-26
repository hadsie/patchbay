from __future__ import annotations

from pathlib import Path

import bcrypt
import yaml

from patchbay.keygen import main


class TestKeygen:
    def test_creates_api_keys_file(self, tmp_path: Path):
        main(["--label", "test-key", "--roles", "admin", "--config-dir", str(tmp_path)])
        api_keys_path = tmp_path / "api_keys.yml"
        assert api_keys_path.exists()
        data = yaml.safe_load(api_keys_path.read_text())
        assert len(data["api_keys"]) == 1
        entry = data["api_keys"][0]
        assert entry["label"] == "test-key"
        assert entry["roles"] == ["admin"]
        assert entry["key_hash"].startswith("$2b$")

    def test_appends_to_existing_file(self, tmp_path: Path):
        main(["--label", "first", "--roles", "admin", "--config-dir", str(tmp_path)])
        main(["--label", "second", "--roles", "viewer", "--config-dir", str(tmp_path)])
        data = yaml.safe_load((tmp_path / "api_keys.yml").read_text())
        assert len(data["api_keys"]) == 2
        labels = [k["label"] for k in data["api_keys"]]
        assert labels == ["first", "second"]

    def test_rejects_duplicate_label(self, tmp_path: Path):
        main(["--label", "dupe", "--roles", "admin", "--config-dir", str(tmp_path)])
        try:
            main(["--label", "dupe", "--roles", "viewer", "--config-dir", str(tmp_path)])
            assert False, "should have exited"
        except SystemExit as e:
            assert e.code == 1
        data = yaml.safe_load((tmp_path / "api_keys.yml").read_text())
        assert len(data["api_keys"]) == 1

    def test_multiple_roles(self, tmp_path: Path):
        main(["--label", "multi", "--roles", "admin,viewer", "--config-dir", str(tmp_path)])
        data = yaml.safe_load((tmp_path / "api_keys.yml").read_text())
        assert data["api_keys"][0]["roles"] == ["admin", "viewer"]

    def test_plaintext_key_in_stdout(self, tmp_path: Path, capsys):
        main(["--label", "out", "--roles", "admin", "--config-dir", str(tmp_path)])
        captured = capsys.readouterr()
        assert "pb_" in captured.out
        assert "cannot be recovered" in captured.out

    def test_generated_hash_verifies(self, tmp_path: Path, capsys):
        main(["--label", "verify", "--roles", "admin", "--config-dir", str(tmp_path)])
        captured = capsys.readouterr()
        key_line = [line for line in captured.out.splitlines() if line.startswith("Key:")][0]
        plaintext = key_line.split("Key: ")[1]
        data = yaml.safe_load((tmp_path / "api_keys.yml").read_text())
        stored_hash = data["api_keys"][0]["key_hash"]
        assert bcrypt.checkpw(plaintext.encode(), stored_hash.encode())
