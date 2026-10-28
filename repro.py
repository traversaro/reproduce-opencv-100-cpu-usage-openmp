#!/usr/bin/env python3
"""Periodic synthetic image processing; every case starts a fresh interpreter."""
import argparse
import csv
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

CASES = ("idle", "default", "single", "passive", "omp1")
THREAD_PREFIXES = ("OMP_", "GOMP_", "KMP_", "OPENBLAS_", "MKL_",
                   "OPENCV_FOR_", "OPENCV_THREAD_POOL_", "OPENCV_PARALLEL_")


def case_environment(case, inherit=False):
    env = os.environ.copy()
    if not inherit:
        env = {k: v for k, v in env.items() if not k.startswith(THREAD_PREFIXES)}
    # Avoid importing packages from outside the selected Pixi environment.
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    # Isolate OpenCV image parallelism from eager BLAS worker pools.
    env["OPENBLAS_NUM_THREADS"] = "1"
    env["MKL_NUM_THREADS"] = "1"
    if case == "passive":
        env["OMP_WAIT_POLICY"] = "PASSIVE"
    elif case == "omp1":
        env["OMP_NUM_THREADS"] = "1"
    elif case == "active":
        env["OMP_WAIT_POLICY"] = "ACTIVE"
    return env


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--suite", action="store_true", help="Run all five diagnostic cases")
    p.add_argument("--case", choices=(*CASES, "active"), default="default")
    p.add_argument("--include-active", action="store_true", help="Add forced ACTIVE wait positive control")
    p.add_argument("--operation", choices=("resize", "remap", "cvtcolor"), default="resize")
    p.add_argument("--duration", type=float, default=10.0, help="Measured seconds per case")
    p.add_argument("--warmup", type=float, default=2.0, help="Unmeasured periodic warmup seconds")
    p.add_argument("--fps", type=float, default=30.0)
    p.add_argument("--width", type=int, default=1920)
    p.add_argument("--height", type=int, default=1080)
    p.add_argument("--output-dir", type=Path, default=Path("results"))
    p.add_argument("--label", default=os.environ.get("PIXI_ENVIRONMENT_NAME", "manual"))
    p.add_argument("--inherit-thread-env", action="store_true", help="Preserve ambient runtime settings; BLAS still limited to one")
    p.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    return p


def runtime_metadata(proc, cv2, np):
    from threadpoolctl import threadpool_info
    packages = []
    for record in sorted((Path(sys.prefix) / "conda-meta").glob("*.json")):
        d = json.loads(record.read_text())
        if d.get("name") in {"python", "numpy", "opencv", "py-opencv", "libopencv",
                              "libgomp", "llvm-openmp", "libopenblas", "libblas", "mkl"}:
            packages.append({k: d.get(k) for k in ("name", "version", "build", "channel")})
    distributions = {}
    for name in ("numpy", "opencv-python", "opencv-python-headless", "opencv-contrib-python",
                 "opencv-contrib-python-headless", "psutil", "threadpoolctl"):
        try:
            distributions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            pass
    cgroups = {}
    for name in ("cpu.max", "cpuset.cpus.effective", "cpu.stat"):
        path = Path("/sys/fs/cgroup") / name
        if path.is_file():
            cgroups[name] = path.read_text().strip()
    native_libraries = []
    maps = Path("/proc/self/maps")
    if maps.is_file():
        native_libraries = sorted({line.split()[-1] for line in maps.read_text().splitlines()
                                  if any(s in line for s in ("libgomp", "libomp", "libiomp", "openblas", "libtbb", "libopencv"))})
    return {
        "python": sys.version, "executable": sys.executable,
        "platform": platform.platform(), "machine": platform.machine(),
        "logical_cpus": os.cpu_count(),
        "affinity": sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
        "cgroups": cgroups, "opencv_version": cv2.__version__, "opencv_file": cv2.__file__,
        "numpy_version": np.__version__, "numpy_file": np.__file__,
        "opencv_num_threads": cv2.getNumThreads(), "opencv_num_cpus": cv2.getNumberOfCPUs(),
        "threadpools": threadpool_info(), "conda_packages": packages,
        "python_distributions": distributions, "native_libraries": native_libraries,
        "thread_environment": {k: v for k, v in os.environ.items() if k.startswith(THREAD_PREFIXES)},
    }


def make_operation(args, np, cv2):
    # No BLAS operations, codecs, or file I/O in the timed loop.
    image = np.random.default_rng(42).integers(0, 256, (args.height, args.width, 3), dtype=np.uint8)
    if args.operation == "resize":
        dst = np.empty((args.height // 2, args.width // 2, 3), dtype=np.uint8)
        return lambda: cv2.resize(image, (args.width // 2, args.height // 2), dst=dst,
                                  interpolation=cv2.INTER_LINEAR)
    if args.operation == "cvtcolor":
        dst = np.empty((args.height, args.width), dtype=np.uint8)
        return lambda: cv2.cvtColor(image, cv2.COLOR_BGR2GRAY, dst=dst)
    # Fractional translation makes remap do actual bilinear interpolation.
    map_x = np.broadcast_to(np.arange(args.width, dtype=np.float32)[None, :] + 0.37,
                            (args.height, args.width)).copy()
    map_y = np.broadcast_to(np.arange(args.height, dtype=np.float32)[:, None] + 0.23,
                            (args.height, args.width)).copy()
    dst = np.empty_like(image)
    return lambda: cv2.remap(image, map_x, map_y, cv2.INTER_LINEAR, dst=dst)


def run_periodic(operation, duration, fps, proc, measure):
    period = 1.0 / fps
    start = last_wall = time.perf_counter()
    start_cpu = last_cpu = time.process_time()
    next_frame = start
    frames = misses = 0
    operation_wall = operation_cpu = wait_wall = wait_cpu = 0.0
    peak_threads = proc.num_threads()
    timeline = []
    while time.perf_counter() < start + duration:
        a, ca = time.perf_counter(), time.process_time()
        operation()
        b, cb = time.perf_counter(), time.process_time()
        operation_wall += b - a
        operation_cpu += cb - ca
        frames += 1
        next_frame += period
        misses += b > next_frame
        if measure:
            peak_threads = max(peak_threads, proc.num_threads())
        # process_time counts *all* native threads, even while this Python thread sleeps.
        a, ca = time.perf_counter(), time.process_time()
        time.sleep(max(0.0, min(next_frame, start + duration) - a))
        b, cb = time.perf_counter(), time.process_time()
        wait_wall += b - a
        wait_cpu += cb - ca
        if measure and b - last_wall >= 1.0:
            timeline.append({"elapsed_s": b - start, "cpu_percent": 100 * (cb - last_cpu) / (b - last_wall),
                             "os_threads": proc.num_threads(), "frames": frames})
            last_wall, last_cpu = b, cb
    wall = time.perf_counter() - start
    cpu = time.process_time() - start_cpu
    return {
        "wall_s": wall, "cpu_s": cpu, "cpu_percent": 100 * cpu / wall,
        "cpu_cores_equivalent": cpu / wall, "frames": frames, "actual_fps": frames / wall,
        "deadline_misses": misses, "operation_wall_s": operation_wall,
        "operation_cpu_s": operation_cpu, "sleep_wall_s": wait_wall,
        "sleep_cpu_s": wait_cpu,
        "sleep_cpu_percent": 100 * wait_cpu / wait_wall if wait_wall else None,
        "peak_os_threads": peak_threads, "final_os_threads": proc.num_threads(),
        "timeline": timeline,
    }


def worker(args):
    import psutil
    # /proc can expose host PIDs when running in a nested PID namespace.
    # Resolve self through procfs so psutil reads the matching procfs directory.
    proc = psutil.Process(int(os.readlink("/proc/self")) if sys.platform == "linux" else os.getpid())
    stages = {"before_numpy": proc.num_threads()}
    import numpy as np
    stages["after_numpy"] = proc.num_threads()
    import cv2
    stages["after_cv2"] = proc.num_threads()
    if args.case == "single":
        cv2.setNumThreads(1)
    operation = make_operation(args, np, cv2)
    if args.case == "idle":
        operation = lambda: None
    run_periodic(operation, args.warmup, args.fps, proc, False)
    stages["after_warmup"] = proc.num_threads()
    metadata = runtime_metadata(proc, cv2, np)
    before_threads = {t.id: t.user_time + t.system_time for t in proc.threads()}
    summary = run_periodic(operation, args.duration, args.fps, proc, True)
    top_threads = sorted(({"tid": t.id, "cpu_s": t.user_time + t.system_time - before_threads.get(t.id, 0)}
                          for t in proc.threads()), key=lambda t: t["cpu_s"], reverse=True)
    result = {"case": args.case, "label": args.label,
              "settings": {k: getattr(args, k) for k in ("operation", "fps", "width", "height", "duration", "warmup", "inherit_thread_env")},
              "thread_stages": stages, "runtime": metadata,
              "summary": summary, "top_threads": top_threads[:32]}
    cpu_stat = Path("/sys/fs/cgroup/cpu.stat")
    if cpu_stat.is_file():
        result["cgroup_cpu_stat_after"] = cpu_stat.read_text().strip()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stem = args.output_dir / f"{args.label}-{args.operation}-{args.case}"
    stem.with_suffix(".json").write_text(json.dumps(result, indent=2) + "\n")
    Path(str(stem) + "-build.txt").write_text(cv2.getBuildInformation())
    with Path(str(stem) + "-timeline.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=("elapsed_s", "cpu_percent", "os_threads", "frames"))
        w.writeheader()
        w.writerows(summary["timeline"])
    print(f"{args.label:8} {args.case:8} CPU={summary['cpu_percent']:7.1f}%  "
          f"sleep CPU={summary['sleep_cpu_percent']:7.1f}%  "
          f"threads={summary['peak_os_threads']:4}  fps={summary['actual_fps']:5.1f}  "
          f"cv threads={metadata['opencv_num_threads']}", flush=True)


def main():
    p = parser()
    args = p.parse_args()
    if args.duration <= 0 or args.warmup < 0 or args.fps <= 0 or min(args.width, args.height) < 2:
        p.error("duration/fps must be positive, warmup nonnegative, and dimensions >= 2")
    if not args.label or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in args.label):
        p.error("label must contain only letters, numbers, underscores and hyphens")
    if args.worker:
        worker(args)
        return
    cases = list(CASES) if args.suite else [args.case]
    if args.suite and args.include_active:
        cases.append("active")
    for case in cases:
        cmd = [sys.executable, str(Path(__file__).resolve()), "--worker", "--case", case,
               "--label", args.label, "--operation", args.operation, "--duration", str(args.duration),
               "--warmup", str(args.warmup), "--fps", str(args.fps), "--width", str(args.width),
               "--height", str(args.height), "--output-dir", str(args.output_dir)]
        if args.inherit_thread_env:
            cmd.append("--inherit-thread-env")
        subprocess.run(cmd, env=case_environment(case, args.inherit_thread_env), check=True)


if __name__ == "__main__":
    main()
