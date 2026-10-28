#!/usr/bin/env python3
"""Run the same suite in both isolated Pixi environments and summarize results."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pixi", default=shutil.which("pixi"))
    p.add_argument("--manifest-path", type=Path)
    p.add_argument("--environments", nargs="+", default=["conda", "pypi"])
    p.add_argument("--duration", type=float, default=10)
    p.add_argument("--warmup", type=float, default=2)
    p.add_argument("--fps", type=float, default=30)
    p.add_argument("--width", type=int, default=1920)
    p.add_argument("--height", type=int, default=1080)
    p.add_argument("--operation", choices=("resize", "remap", "cvtcolor"), default="resize")
    p.add_argument("--include-active", action="store_true")
    p.add_argument("--output-dir", type=Path)
    args = p.parse_args()
    if not args.pixi:
        p.error("pixi not on PATH; supply --pixi /absolute/path/to/pixi")
    root = Path(__file__).resolve().parent
    manifest = (args.manifest_path or root / "pixi.toml").resolve()
    out = (args.output_dir or root / "results" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")).resolve()
    out.mkdir(parents=True, exist_ok=True)
    for env in args.environments:
        cmd = [args.pixi, "run", "--locked", "--manifest-path", str(manifest), "-e", env,
               "python", str(root / "repro.py"), "--suite", "--label", env, "--output-dir", str(out)]
        for name in ("duration", "warmup", "fps", "width", "height", "operation"):
            cmd.extend(["--" + name.replace("_", "-"), str(getattr(args, name))])
        if args.include_active:
            cmd.append("--include-active")
        subprocess.run(cmd, cwd=root, check=True)
    rows = []
    for env in args.environments:
        for case in ("idle", "default", "single", "passive", "omp1", "active"):
            f = out / f"{env}-{args.operation}-{case}.json"
            if f.exists():
                d = json.loads(f.read_text())
                s = d["summary"]
                build = Path(str(f.with_suffix("")) + "-build.txt").read_text()
                backend = next((line.split(":", 1)[1].strip() for line in build.splitlines()
                                if "Parallel framework:" in line), "unknown")
                rows.append(f"| {env} | {case} | {backend} | {s['cpu_percent']:.1f} | "
                            f"{s['sleep_cpu_percent']:.1f} | {s['peak_os_threads']} | {s['actual_fps']:.1f} |")
    report = ("# OpenCV periodic workload comparison\n\n"
              "CPU percentages use 100% = one logical CPU; values may exceed 100%. "
              "Sleep CPU is process CPU accrued while the calling Python thread sleeps.\n\n"
              "| Environment | Case | Backend | CPU % | Sleep CPU % | Peak threads | FPS |\n"
              "| --- | --- | --- | ---: | ---: | ---: | ---: |\n" + "\n".join(rows) + "\n\n"
              "High sleep CPU that falls with PASSIVE is evidence of waiting overhead. "
              "Many sleeping OS threads alone do not prove CPU contention. A saturated "
              "image operation or missed target FPS requires a smaller image/lower FPS. "
              "This compares packaged stacks; it does not isolate every build/dependency difference.\n")
    (out / "comparison.md").write_text(report)
    print("\n" + report)
    print("Results:", out)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)
