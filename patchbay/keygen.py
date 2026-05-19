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
    parser.add_argument(
        "--roles",
        help="Comma-separated role names (required for new keys; kept on overwrite if omitted)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing key without prompting",
    )
    parser.add_argument(
        "--config-dir",
        default=os.environ.get("CONFIG_DIR", "config"),
        help="Config directory (default: CONFIG_DIR env or ./config/)",
    )
    args = parser.parse_args(argv)

    config_dir = Path(args.config_dir)
    api_keys_path = config_dir / "api_keys.yml"
    roles = [r.strip() for r in args.roles.split(",") if r.strip()] if args.roles else None

    data = _load_yaml(api_keys_path)
    keys = data.get("api_keys", [])

    existing_idx = next((i for i, k in enumerate(keys) if k["label"] == args.label), None)

    if existing_idx is None:
        if roles is None:
            print("Error: --roles is required for new keys", file=sys.stderr)
            sys.exit(1)
    else:
        existing_roles = keys[existing_idx]["roles"]
        if not args.force:
            if not sys.stdin.isatty():
                print(
                    f"Error: label {args.label!r} already exists in {api_keys_path}. "
                    "Use --force to overwrite.",
                    file=sys.stderr,
                )
                sys.exit(1)
            prompt = (
                f"Key {args.label!r} already exists with roles {existing_roles}. Overwrite? [y/N] "
            )
            if input(prompt).strip().lower() not in ("y", "yes"):
                print("Aborted.", file=sys.stderr)
                sys.exit(1)
        if roles is None:
            roles = existing_roles

    plaintext, key_hash = generate_api_key(args.label)
    entry = {"label": args.label, "key_hash": key_hash, "roles": roles}
    if existing_idx is None:
        keys.append(entry)
    else:
        keys[existing_idx] = entry

    config_dir.mkdir(parents=True, exist_ok=True)
    with open(api_keys_path, "w") as f:
        yaml.safe_dump({"api_keys": keys}, f, default_flow_style=False, sort_keys=False)

    action = "rotated" if existing_idx is not None else "created"
    print(f"API key {action} for {args.label!r}")
    print(f"Key: {plaintext}")
    print("Save this key now -- it cannot be recovered.")
    print("Restart Patchbay or POST /api/config/reload for the key to take effect.")


if __name__ == "__main__":
    main()
