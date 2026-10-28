#!/usr/bin/env python3
"""Ensure backend recipes differ only in package identity/backend selection."""
from pathlib import Path
import tomllib

root = Path(__file__).resolve().parent
recipes = []
manifests = []
for backend in ("pthreads", "openmp", "tbb", "serial"):
    recipe = (root / backend / "recipe.yaml").read_text()
    recipes.append(recipe.replace("opencv-source-" + backend, "opencv-source-BACKEND")
                   .replace("OPENCV_PARALLEL: " + backend, "OPENCV_PARALLEL: BACKEND"))
    manifest = tomllib.loads((root / backend / "pixi.toml").read_text())
    manifest["package"]["name"] = "opencv-source-BACKEND"
    manifests.append(manifest)
if len(set(recipes)) != 1 or any(m != manifests[0] for m in manifests):
    raise SystemExit("Backend package definitions have differences beyond backend selection")
workspace = tomllib.loads((root / "pixi.toml").read_text())
groups = {workspace["environments"][b]["solve-group"] for b in ("pthreads", "openmp", "tbb", "serial")}
if len(groups) != 1:
    raise SystemExit("Source environments must share a solve group")
print("Four source recipes have identical dependency/build specifications")
