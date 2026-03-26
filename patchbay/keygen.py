"""Generate API keys and append them to api_keys.yml."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import yaml

from patchbay.auth import generate_api_key
from patchbay.config import _load_yaml


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="patchbay-keygen",
        description="Generate an API key and add it to api_keys.yml",
    )
    parser.add_argument("--label", required=True, help="Human-readable key label")
    parser.add_argument("--roles", required=True, help="Comma-separated role names")
    parser.add_argument(
        "--config-dir",
        default=os.environ.get("CONFIG_DIR", "config"),
        help="Config directory (default: CONFIG_DIR env or ./config/)",
    )
    args = parser.parse_args(argv)

    config_dir = Path(args.config_dir)
    api_keys_path = config_dir / "api_keys.yml"
    roles = [r.strip() for r in args.roles.split(",") if r.strip()]

    # Load existing keys
    data = _load_yaml(api_keys_path)
    keys = data.get("api_keys", [])

    # Check for duplicate label
    existing_labels = {k["label"] for k in keys}
    if args.label in existing_labels:
        print(f"Error: label {args.label!r} already exists in {api_keys_path}", file=sys.stderr)
        sys.exit(1)

    # Generate and append
    plaintext, key_hash = generate_api_key(args.label)
    keys.append({"label": args.label, "key_hash": key_hash, "roles": roles})

    config_dir.mkdir(parents=True, exist_ok=True)
    with open(api_keys_path, "w") as f:
        yaml.safe_dump({"api_keys": keys}, f, default_flow_style=False, sort_keys=False)

    print(f"API key created for {args.label!r}")
    print(f"Key: {plaintext}")
    print("Save this key now -- it cannot be recovered.")


if __name__ == "__main__":
    main()
