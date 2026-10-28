#!/usr/bin/env python3
"""Check suite completeness and provenance, without performance thresholds."""
import argparse
import csv
import json
import math
from pathlib import Path


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate(directory, operation, machine=None):
    for env in ("conda", "pypi"):
        for case in ("idle", "default", "single", "passive", "omp1"):
            stem = directory / f"{env}-{operation}-{case}"
            data = json.loads(stem.with_suffix(".json").read_text())
            runtime, summary = data["runtime"], data["summary"]
            require(data["case"] == case and data["label"] == env, f"{stem}: wrong case/environment")
            require(data["settings"]["operation"] == operation, f"{stem}: wrong operation")
            require(runtime["opencv_version"] == "4.13.0", f"{stem}: wrong OpenCV version")
            require(runtime["numpy_version"] == "2.2.6", f"{stem}: wrong NumPy version")
            if machine:
                require(runtime["machine"] == machine, f"{stem}: wrong machine architecture")
            for key in ("wall_s", "cpu_s", "cpu_percent", "actual_fps", "operation_cpu_s", "sleep_cpu_s"):
                require(math.isfinite(summary[key]) and summary[key] >= 0, f"{stem}: invalid {key}")
            require(summary["wall_s"] > 0 and summary["frames"] > 0, f"{stem}: no measured work")
            require(summary["peak_os_threads"] >= 1, f"{stem}: missing native threads")
            if case == "single":
                require(runtime["opencv_num_threads"] == 1, f"{stem}: OpenCV thread limit failed")
            envvars = runtime["thread_environment"]
            require(envvars["OPENBLAS_NUM_THREADS"] == "1" and envvars["MKL_NUM_THREADS"] == "1",
                    f"{stem}: BLAS not isolated")
            if case == "passive":
                require(envvars.get("OMP_WAIT_POLICY") == "PASSIVE", f"{stem}: missing PASSIVE")
            if case == "omp1":
                require(envvars.get("OMP_NUM_THREADS") == "1", f"{stem}: missing OMP limit")
            names = {p["name"] for p in runtime["conda_packages"]}
            if env == "conda":
                require({"opencv", "libopencv", "py-opencv", "numpy"} <= names,
                        f"{stem}: conda package provenance missing")
            else:
                require(not names.intersection({"opencv", "libopencv", "py-opencv", "numpy"}),
                        f"{stem}: conda packages contaminated PyPI environment")
                require(runtime["python_distributions"].get("opencv-python-headless") == "4.13.0.92",
                        f"{stem}: wrong PyPI wheel")
            build = Path(str(stem) + "-build.txt").read_text()
            require("Parallel framework:" in build, f"{stem}: missing build configuration")
            with Path(str(stem) + "-timeline.csv").open(newline="") as f:
                reader = csv.DictReader(f)
                require(reader.fieldnames == ["elapsed_s", "cpu_percent", "os_threads", "frames"],
                        f"{stem}: invalid CSV header")
                samples = list(reader)
                # Very short smoke runs need not produce a one-second sample.
                if data["settings"]["duration"] >= 2:
                    require(bool(samples), f"{stem}: missing timeline samples")
            print(f"Validated {env}/{operation}/{case}")
    require((directory / "comparison.md").is_file(), "Missing comparison report")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--operation", choices=("resize", "remap", "cvtcolor"), default="resize")
    parser.add_argument("--machine")
    args = parser.parse_args()
    validate(args.directory, args.operation, args.machine)
