#!/usr/bin/env python3
"""Fresh-process OpenCV/OpenMP sweep; all percentages use full measured wall time."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import random
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PREFIXES = ("OMP_", "GOMP_", "KMP_", "OPENBLAS_", "MKL_", "OPENCV_")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--native", type=Path, required=True)
    p.add_argument("--output", type=Path, default=ROOT / "results/spin-sweep")
    p.add_argument("--duration", type=float, default=4)
    p.add_argument("--warmup", type=float, default=1)
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--quick", action="store_true", help="Small smoke sweep")
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.duration <= 0 or args.warmup < 0 or args.repeats < 1:
        p.error("invalid duration/warmup/repeats")
    affinity = sorted(os.sched_getaffinity(0))
    if len(affinity) < 4 and not args.quick:
        raise RuntimeError("Need at least four allowed CPUs")
    # Same number of logical CPUs on both architectures; inherited by children.
    os.sched_setaffinity(0, affinity[:4])
    env_base = {k: v for k, v in os.environ.items() if not k.startswith(PREFIXES)}
    for k in ("PYTHONPATH", "PYTHONHOME"):
        env_base.pop(k, None)
    env_base.update(OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1", OMP_DYNAMIC="FALSE", OMP_THREAD_LIMIT="4")
    native = args.native.resolve()
    linked = subprocess.check_output(["ldd", str(native)], text=True)
    expected = (Path(sys.prefix) / "lib/libgomp.so.1").resolve()
    actual = next(Path(l.split("=>")[1].strip().split()[0]).resolve()
                  for l in linked.splitlines() if "libgomp.so" in l)
    if actual != expected:
        raise RuntimeError(f"Native libgomp {actual} != selected environment {expected}")
    metadata = {"machine": platform.machine(), "platform": platform.platform(),
                "affinity_before": affinity, "affinity_measured": sorted(os.sched_getaffinity(0)),
                "lscpu": subprocess.check_output(["lscpu"], text=True), "native_ldd": linked,
                "libgomp_path": str(actual), "libgomp_sha256": hashlib.sha256(actual.read_bytes()).hexdigest(),
                "spin_microbench": [json.loads(subprocess.check_output([str(native), "spin"], text=True)) for _ in range(3)],
                "duration": args.duration, "warmup": args.warmup, "repeats": args.repeats,
                "percent_denominator": "full measured wall time; 100% = one logical CPU"}
    (args.output / "machine.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print("MACHINE", metadata["machine"], "CPUS", metadata["affinity_measured"], flush=True)
    print("SPIN_NS", [x["ns_per_spin"] for x in metadata["spin_microbench"]], flush=True)
    settings = [(4, str(n)) for n in ("default", 0, 1000, 10000, 100000, 300000, 1000000, "passive")]
    settings += [(n, spin) for n in (1, 2) for spin in ("default", "0")]
    if args.quick:
        settings = [(1, "0"), (4, "0"), (4, "default")]
    cases = [(op, team, spin, rep) for op in ("native", "resize", "cvtcolor")
             for team, spin in settings for rep in range(args.repeats)]
    random.Random(20261029).shuffle(cases)
    results = []
    for op, team, spin, rep in cases:
        name = f"{op}-t{team}-s{spin}-r{rep}"
        env = dict(env_base, OMP_NUM_THREADS=str(team))
        if spin == "passive":
            env["OMP_WAIT_POLICY"] = "PASSIVE"
        elif spin != "default":
            env["GOMP_SPINCOUNT"] = spin
        if op == "native":
            summary = json.loads(subprocess.check_output(
                [str(native), str(team), str(args.duration), str(args.warmup), "30"], env=env, text=True))
            assert summary["actual_team"] == team
            details = {"summary": summary, "runtime_environment": {k: v for k, v in env.items() if k.startswith(PREFIXES)}}
        else:
            subprocess.run([sys.executable, str(ROOT / "repro.py"), "--worker", "--inherit-thread-env",
                            "--threads", str(team), "--operation", op, "--case", "default", "--label", name,
                            "--duration", str(args.duration), "--warmup", str(args.warmup),
                            "--output-dir", str(args.output / "raw")], env=env, check=True, stdout=subprocess.DEVNULL)
            details = json.loads((args.output / "raw" / f"{name}-{op}-default.json").read_text())
            summary = details["summary"]
            assert details["runtime"]["opencv_num_threads"] == team
            assert "OpenMP" in (args.output / "raw" / f"{name}-{op}-default-build.txt").read_text()
            assert expected in [Path(x).resolve() for x in details["runtime"]["native_libraries"] if "libgomp.so" in x]
            assert summary["peak_os_threads"] == team, (name, summary["peak_os_threads"])
        for k in ("wall_s", "cpu_s", "worker_cpu_s", "sleep_worker_cpu_s"):
            assert math.isfinite(summary[k]) and summary[k] >= 0, (name, k)
        assert summary["frames"] > 0
        row = {"operation": op, "team": team, "spin": spin, "repeat": rep, "details": details}
        for key, value in (("cpu_percent", "cpu_s"), ("worker_percent", "worker_cpu_s"),
                           ("sleep_worker_percent", "sleep_worker_cpu_s")):
            row[key] = 100 * summary[value] / summary["wall_s"]
        row["fps"] = summary["actual_fps"]
        results.append(row)
        (args.output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
        print(f"SAMPLE {name} CPU={row['cpu_percent']:.2f} worker={row['worker_percent']:.2f} sleep-worker={row['sleep_worker_percent']:.2f} FPS={row['fps']:.2f}", flush=True)
    lines = [f"# Fixed-team OpenMP sweep: {metadata['machine']}", "",
             "All percentages use full measured wall time; 100% = one logical CPU. Values are medians across fresh processes.", "",
             "| Operation | Team | Spin count / policy | CPU % | Worker CPU % | Sleeping-caller worker CPU % | FPS | CPU min–max % |",
             "| --- | ---: | --- | ---: | ---: | ---: | ---: | --- |"]
    for op in ("native", "resize", "cvtcolor"):
        for team, spin in settings:
            group = [r for r in results if (r["operation"], r["team"], r["spin"]) == (op, team, spin)]
            med = lambda key: statistics.median(r[key] for r in group)
            lines.append(f"| {op} | {team} | {spin} | {med('cpu_percent'):.2f} | {med('worker_percent'):.2f} | {med('sleep_worker_percent'):.2f} | {med('fps'):.2f} | {min(r['cpu_percent'] for r in group):.2f}–{max(r['cpu_percent'] for r in group):.2f} |")
    report = "\n".join(lines) + "\n"
    (args.output / "comparison.md").write_text(report)
    print(report, flush=True)


if __name__ == "__main__":
    main()
