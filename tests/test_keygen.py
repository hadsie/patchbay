from __future__ import annotations

from pathlib import Path

import bcrypt
import pytest
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

    def test_rejects_duplicate_label_when_non_interactive(self, tmp_path: Path, capsys):
        main(["--label", "dupe", "--roles", "admin", "--config-dir", str(tmp_path)])
        with pytest.raises(SystemExit) as exc:
            main(["--label", "dupe", "--roles", "viewer", "--config-dir", str(tmp_path)])
        assert exc.value.code == 1
        assert "Use --force to overwrite" in capsys.readouterr().err
        data = yaml.safe_load((tmp_path / "api_keys.yml").read_text())
        assert len(data["api_keys"]) == 1
        assert data["api_keys"][0]["roles"] == ["admin"]

    def test_force_overwrites_existing_key(self, tmp_path: Path):
        main(["--label", "rot", "--roles", "admin", "--config-dir", str(tmp_path)])
        first_hash = yaml.safe_load((tmp_path / "api_keys.yml").read_text())["api_keys"][0][
            "key_hash"
        ]
        main(
            [
                "--label",
                "rot",
                "--roles",
                "viewer",
                "--force",
                "--config-dir",
                str(tmp_path),
            ]
        )
        data = yaml.safe_load((tmp_path / "api_keys.yml").read_text())
        assert len(data["api_keys"]) == 1
        assert data["api_keys"][0]["roles"] == ["viewer"]
        assert data["api_keys"][0]["key_hash"] != first_hash

    def test_force_preserves_roles_when_omitted(self, tmp_path: Path):
        main(
            [
                "--label",
                "rot",
                "--roles",
                "admin,viewer",
                "--config-dir",
                str(tmp_path),
            ]
        )
        main(["--label", "rot", "--force", "--config-dir", str(tmp_path)])
        data = yaml.safe_load((tmp_path / "api_keys.yml").read_text())
        assert data["api_keys"][0]["roles"] == ["admin", "viewer"]

    def test_overwrite_preserves_list_position(self, tmp_path: Path):
        main(["--label", "a", "--roles", "admin", "--config-dir", str(tmp_path)])
        main(["--label", "b", "--roles", "admin", "--config-dir", str(tmp_path)])
        main(["--label", "c", "--roles", "admin", "--config-dir", str(tmp_path)])
        main(
            [
                "--label",
                "b",
                "--roles",
                "viewer",
                "--force",
                "--config-dir",
                str(tmp_path),
            ]
        )
        data = yaml.safe_load((tmp_path / "api_keys.yml").read_text())
        assert [k["label"] for k in data["api_keys"]] == ["a", "b", "c"]
        assert data["api_keys"][1]["roles"] == ["viewer"]

    def test_prompt_yes_overwrites(self, tmp_path: Path, monkeypatch):
        main(["--label", "rot", "--roles", "admin", "--config-dir", str(tmp_path)])
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("builtins.input", lambda _: "y")
        main(["--label", "rot", "--roles", "viewer", "--config-dir", str(tmp_path)])
        data = yaml.safe_load((tmp_path / "api_keys.yml").read_text())
        assert data["api_keys"][0]["roles"] == ["viewer"]

    def test_prompt_no_aborts(self, tmp_path: Path, monkeypatch, capsys):
        main(["--label", "rot", "--roles", "admin", "--config-dir", str(tmp_path)])
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("builtins.input", lambda _: "n")
        with pytest.raises(SystemExit) as exc:
            main(["--label", "rot", "--roles", "viewer", "--config-dir", str(tmp_path)])
        assert exc.value.code == 1
        assert "Aborted" in capsys.readouterr().err
        data = yaml.safe_load((tmp_path / "api_keys.yml").read_text())
        assert data["api_keys"][0]["roles"] == ["admin"]

    def test_prompt_shows_existing_roles(self, tmp_path: Path, monkeypatch, capsys):
        main(
            [
                "--label",
                "rot",
                "--roles",
                "admin,viewer",
                "--config-dir",
                str(tmp_path),
            ]
        )
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        captured_prompt = {}

        def fake_input(prompt: str) -> str:
            captured_prompt["text"] = prompt
            return "n"

        monkeypatch.setattr("builtins.input", fake_input)
        with pytest.raises(SystemExit):
            main(["--label", "rot", "--config-dir", str(tmp_path)])
        assert "admin" in captured_prompt["text"]
        assert "viewer" in captured_prompt["text"]

    def test_new_key_without_roles_errors(self, tmp_path: Path, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["--label", "new", "--config-dir", str(tmp_path)])
        assert exc.value.code == 1
        assert "--roles is required" in capsys.readouterr().err

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
