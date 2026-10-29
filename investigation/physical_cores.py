#!/usr/bin/env python3
"""Compare two pinned OpenMP threads on two distinct physical cores."""
import argparse
import json
import os
from pathlib import Path
import platform
import random
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--native", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--duration", type=float, default=4)
    p.add_argument("--repeats", type=int, default=3)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    topology = []
    selected, seen = [], set()
    for cpu in sorted(os.sched_getaffinity(0)):
        base = Path(f"/sys/devices/system/cpu/cpu{cpu}/topology")
        record = {"cpu": cpu, **{key: (base / key).read_text().strip()
                  for key in ("physical_package_id", "core_id", "thread_siblings_list")}}
        topology.append(record)
        key = (record["physical_package_id"], record["core_id"])
        if key not in seen:
            selected.append(cpu)
            seen.add(key)
    if len(selected) < 2:
        raise RuntimeError("Need two distinct physical cores exposed by the VM")
    selected = selected[:2]
    os.sched_setaffinity(0, selected)
    env_base = {k: v for k, v in os.environ.items()
                if not k.startswith(("OMP_", "GOMP_", "KMP_", "OPENCV_", "MKL_", "OPENBLAS_"))
                and k not in ("PYTHONPATH", "PYTHONHOME")}
    env_base.update(OMP_NUM_THREADS="2", OMP_DYNAMIC="FALSE", OMP_THREAD_LIMIT="2",
                    OMP_PROC_BIND="TRUE", OMP_PLACES=",".join("{" + str(c) + "}" for c in selected),
                    OMP_DISPLAY_ENV="VERBOSE", OMP_DISPLAY_AFFINITY="TRUE",
                    OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    native = args.native.resolve()
    expected = (Path(sys.prefix) / "lib/libgomp.so.1").resolve()
    linked = subprocess.check_output(["ldd", str(native)], text=True, env=env_base)
    actual = next(Path(l.split("=>")[-1].strip().split()[0]).resolve()
                  for l in linked.splitlines() if "libgomp.so" in l)
    assert actual == expected
    metadata = {"machine": platform.machine(), "selected_cpus": selected, "topology": topology,
                "lscpu": subprocess.check_output(["lscpu"], text=True), "native_ldd": linked,
                "environment": {k: v for k, v in env_base.items() if k.startswith(("OMP_", "GOMP_"))}}
    (args.output / "machine.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print("PHYSICAL_CORE_CONTROL", json.dumps(metadata), flush=True)
    cases = [(op, spin, rep) for op in ("native", "resize", "cvtcolor")
             for spin in ("default", "300000", "0") for rep in range(args.repeats)]
    random.Random(20261029).shuffle(cases)
    results = []
    for op, spin, rep in cases:
        name = f"physical-{op}-{spin}-r{rep}"
        env = dict(env_base)
        if spin != "default":
            env["GOMP_SPINCOUNT"] = spin
        if op == "native":
            cmd = [str(native), "2", str(args.duration), "1", "30"]
        else:
            cmd = [sys.executable, str(ROOT / "repro.py"), "--worker", "--inherit-thread-env",
                   "--threads", "2", "--operation", op, "--label", name,
                   "--duration", str(args.duration), "--warmup", "1", "--output-dir", str(args.output / "raw")]
        child = subprocess.run(cmd, env=env, text=True, capture_output=True, check=True)
        (args.output / f"{name}-runtime.txt").write_text(child.stderr)
        if op == "native":
            details = {"summary": json.loads(child.stdout)}
            assert details["summary"]["actual_team"] == 2
        else:
            details = json.loads((args.output / "raw" / f"{name}-{op}-default.json").read_text())
            assert details["runtime"]["opencv_num_threads"] == 2
            assert details["summary"]["peak_os_threads"] == 2
            assert {expected} == {Path(x).resolve() for x in details["runtime"]["native_libraries"] if "libgomp.so" in x}
        s = details["summary"]
        row = {"operation": op, "spin": spin, "repeat": rep, "details": details,
               "cpu_percent": 100*s["cpu_s"]/s["wall_s"],
               "worker_percent": 100*s["worker_cpu_s"]/s["wall_s"],
               "sleep_worker_percent": 100*s["sleep_worker_cpu_s"]/s["wall_s"], "fps": s["actual_fps"]}
        results.append(row)
        (args.output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
        print(f"PHYSICAL_SAMPLE {name} CPU={row['cpu_percent']:.2f} worker={row['worker_percent']:.2f} sleep-worker={row['sleep_worker_percent']:.2f}", flush=True)
    lines = [f"# Two physical cores, two pinned threads: {platform.machine()}", "",
             "All percentages use full measured wall time. Medians across fresh processes.", "",
             "| Operation | Spin | CPU % | Worker CPU % | Sleeping-caller worker CPU % | FPS |",
             "| --- | --- | ---: | ---: | ---: | ---: |"]
    for op in ("native", "resize", "cvtcolor"):
        for spin in ("default", "300000", "0"):
            group = [r for r in results if (r["operation"], r["spin"]) == (op, spin)]
            med = lambda key: statistics.median(r[key] for r in group)
            lines.append(f"| {op} | {spin} | {med('cpu_percent'):.2f} | {med('worker_percent'):.2f} | {med('sleep_worker_percent'):.2f} | {med('fps'):.2f} |")
    report = "\n".join(lines) + "\n"
    (args.output / "comparison.md").write_text(report)
    print(report, flush=True)


if __name__ == "__main__":
    main()
