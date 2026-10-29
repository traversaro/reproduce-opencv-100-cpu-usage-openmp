#!/usr/bin/env python3
"""Retain compact CI measurements beyond GitHub artifact expiration."""
import argparse
import json
import re
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", action="append", required=True, help="LABEL=artifact_directory")
    p.add_argument("--run", action="append", default=[], help="LABEL=workflow_run_URL")
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    links = dict(x.split("=", 1) for x in args.run)
    output = {"schema": 1, "percent_denominator": "entire measured wall interval; 100% = one logical CPU", "experiments": {}}
    for item in args.input:
        label, folder = item.split("=", 1)
        folder = Path(folder)
        metadata = json.loads((folder / "machine.json").read_text())
        samples = []
        for r in json.loads((folder / "results.json").read_text()):
            s = r["details"]["summary"]
            samples.append({"operation": r["operation"], "team": r.get("team", 2),
                            "spin": r["spin"], "repeat": r["repeat"],
                            **{k: r[k] for k in ("cpu_percent", "worker_percent", "sleep_worker_percent", "fps")},
                            "wall_s": s["wall_s"], "cpu_s": s["cpu_s"],
                            "worker_cpu_s": s["worker_cpu_s"], "sleep_worker_cpu_s": s["sleep_worker_cpu_s"],
                            "frames": s["frames"], "deadline_misses": s["deadline_misses"],
                            "observed_team": s.get("actual_team", r["details"].get("runtime", {}).get("opencv_num_threads")),
                            "peak_os_threads": s.get("peak_os_threads")})
            runtime_file = folder / f"physical-{r['operation']}-{r['spin']}-r{r['repeat']}-runtime.txt"
            if runtime_file.is_file():
                text = runtime_file.read_text()
                count = re.search(r"GOMP_SPINCOUNT = '(\d+)'", text)
                samples[-1]["reported_spin_count"] = int(count[1]) if count else None
                samples[-1]["reported_thread_affinities"] = sorted(set(re.findall(r" affinity ([0-9,-]+)", text)))
        experiment = {"run_url": links.get(label), "machine": metadata, "samples": samples}
        packages = next((r["details"].get("runtime", {}).get("conda_packages")
                         for r in json.loads((folder / "results.json").read_text())
                         if r["operation"] != "native"), None)
        experiment["conda_packages"] = packages
        patch_root = folder.parent if folder.name == "nopause" else folder
        patch_files = list((patch_root / "nopause-lib").glob("*.patch.json"))
        if patch_files:
            experiment["private_runtime_patch"] = json.loads(patch_files[0].read_text())
        output["experiments"][label] = experiment
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n")
    print(f"Saved {sum(len(x['samples']) for x in output['experiments'].values())} individual samples to {args.output}")


if __name__ == "__main__":
    main()
