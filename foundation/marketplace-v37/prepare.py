#!/usr/bin/env python3
"""Reconstruct this exact candidate from the owner's authorized private base.

The public overlay and minimal core delta do not include the upstream private
core. A fresh destination is mandatory. The original source is read-only.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    package = Path(__file__).resolve().parent
    base = args.source.resolve()
    destination = args.destination.resolve()
    if not base.is_dir() or destination.exists() or base in destination.parents:
        parser.error("Use an existing private source and a fresh destination outside it")
    frozen = json.loads((package / "source-sha256.json").read_text())
    hooks = json.loads((package / "core-hooks-manifest.json").read_text())
    if frozen["candidate_sha"] != hooks["candidate_sha"]:
        raise RuntimeError("Candidate metadata disagrees")
    if (base / "RELEASE_COMMIT").read_text().strip() != hooks["production_sha"]:
        raise RuntimeError("Production release marker changed; rebuild/retest the integration")
    patch = package / "core-hooks.patch"
    if digest(patch) != hooks["patch_sha256"]:
        raise RuntimeError("Core delta checksum mismatch")
    # Validate every input before creating the output tree.
    selected = {}
    for name, expected in frozen["files"].items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError("Invalid source manifest path")
        authored = package / "overlay" / relative
        path = authored if authored.exists() else base / relative
        if not path.is_file() or path.is_symlink():
            raise RuntimeError("Missing or symbolic-link source: " + name)
        check = hooks["base_core_sha256"].get(name, expected)
        if digest(path) != check:
            raise RuntimeError("Input fingerprint changed: " + name)
        selected[name] = path
    destination.mkdir(parents=True)
    for name, path in selected.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        target.chmod(int(frozen.get("file_modes", {}).get(name, "100644"), 8) & 0o777)
    subprocess.run(["git", "apply", "--check", "--unidiff-zero", str(patch)],
                   cwd=destination, check=True)
    subprocess.run(["git", "apply", "--unidiff-zero", str(patch)],
                   cwd=destination, check=True)
    mismatches = [name for name, expected in frozen["files"].items()
                  if digest(destination / name) != expected]
    if mismatches:
        raise RuntimeError("Rebuilt tree differs: " + ", ".join(mismatches))
    print(json.dumps({"candidate_sha": frozen["candidate_sha"],
                      "production_sha": hooks["production_sha"],
                      "verified_files": len(frozen["files"]),
                      "source_modified": False,
                      "destination": str(destination),
                      "mismatches": []}, sort_keys=True))


if __name__ == "__main__":
    main()
