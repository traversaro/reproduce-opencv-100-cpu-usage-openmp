# OpenCV periodic-frame CPU/thread reproducer

[![Linux x86-64 and ARM64](https://github.com/traversaro/reproduce-opencv-100-cpu-usage-openmp/actions/workflows/reproduce.yml/badge.svg)](https://github.com/traversaro/reproduce-opencv-100-cpu-usage-openmp/actions/workflows/reproduce.yml)

This project compares **OpenCV 4.13.0** from conda-forge and PyPI on Linux
(`linux-64` and `linux-aarch64`). It investigates the symptom reported in
[RoboStack/ros-jazzy#210](https://github.com/RoboStack/ros-jazzy/issues/210):
image processing at a modest frame rate consumes CPU on all cores, and
`cv::setNumThreads(1)` dramatically reduces CPU usage.

No ROS, camera, display, downloaded images, or video codecs are required. Each
case allocates a deterministic synthetic 1920x1080 BGR image and processes it at
30 FPS, sleeping between frames. Resize produces a 960x540 image; remap and
color conversion operate at the source resolution. Output arrays are reused.

For a controlled backend comparison, [source-build/](source-build/README.md)
uses Pixi Build to compile the same OpenCV release with pthreads, OpenMP, TBB,
or no parallel framework. All four use one shared build script and common
dependency specifications. This complements the packaged conda-forge/PyPI test.

## Quick start

Install [Pixi](https://pixi.prefix.dev/latest/installation/), clone this repository,
and run these commands from the folder containing `pixi.toml`:

```bash
# Installs the two isolated stacks, then measures both. About two minutes.
pixi run compare
```

This writes a timestamped directory under `results/`, containing `comparison.md`,
JSON metrics/provenance, full OpenCV build information, and one-second CSV
samples. The supplied `pixi.lock` fixes exact packages for both Linux platforms.
Packages are downloaded on first use; they are not bundled in the archive.

## GitHub Actions

The [workflow](.github/workflows/reproduce.yml) runs on pushes to `main`, pull
requests and manual dispatch. It uses native `ubuntu-24.04` (x86-64) and
`ubuntu-24.04-arm` (ARM64) hosted runners, with separate jobs for resize, remap
and color conversion. Each job runs both package environments sequentially and
all five cases at 1920x1080 and 30 FPS, with two seconds of warmup followed by
eight measured seconds per case. Pixi 0.83.0 and the committed lockfile are used.

CI fails on installation/runtime errors, missing or invalid measurements,
incorrect architecture/versions, or mixed conda/PyPI package provenance. It
**does not fail on CPU usage, frame rate or whether the symptom reproduces**:
these depend on the host and runtime. The comparison appears in the job summary;
JSON, CSV, build details and the Pixi manifest/lockfile are uploaded as artifacts
for 30 days, including partial results when a later step fails.

To validate an existing result directory locally:

```bash
pixi run python validate_results.py results/YOUR_RUN --operation resize
```

To run each environment separately:

```bash
pixi run -e conda suite
pixi run -e pypi suite
```

To try the operation mentioned in the STITCH camera report:

```bash
pixi run compare --operation remap
```

For a longer comparison or another frame size/rate:

```bash
pixi run compare --duration 20 --warmup 3 --fps 30 --width 1280 --height 720
pixi run compare --operation cvtcolor
```

## The cases

Each case runs in a **fresh Python process**, so runtime environment variables
are set before NumPy/OpenCV are loaded. Cases run sequentially, never in parallel.

| Case | Change from the common baseline | Purpose |
| --- | --- | --- |
| `idle` | Import and allocate, but do no OpenCV processing | Baseline import/measurement/sleep overhead |
| `default` | No OpenCV/OpenMP thread override | Attempt to reproduce natural package behavior |
| `single` | `cv2.setNumThreads(1)` before warmup | Disable OpenCV's internal image-operation parallelism |
| `passive` | `OMP_WAIT_POLICY=PASSIVE` before import | Test whether waiting behavior explains high CPU |
| `omp1` | `OMP_NUM_THREADS=1` before import | Test a startup OpenMP team-size limit |

Optional positive control:

```bash
pixi run compare --include-active
```

This adds `active`, with `OMP_WAIT_POLICY=ACTIVE`. It deliberately asks OpenMP
to wait actively and can use substantial CPU. A failure seen **only** with this
forced setting does not reproduce the default-packaging problem.

For just one case:

```bash
pixi run -e conda repro --case default --operation remap --duration 15
pixi run -e conda repro --case passive --operation remap --duration 15
pixi run -e pypi repro --case single --operation remap --duration 15
```

Direct single/suite runs use stable filenames and overwrite the corresponding
previous results. `compare` uses a new timestamped directory by default.

## What the numbers mean

- **CPU %:** process CPU time / wall time x 100. **100% is one logical CPU**;
  800% means eight logical CPUs' worth of CPU time, as in `top`'s usual display.
- **Sleep CPU %:** CPU time accrued by the **whole process** while the calling
  Python thread is in `time.sleep`, divided by that wall time. Substantial CPU
  here is evidence of background work/waiting; the image operation has returned.
- **Operation CPU:** CPU accrued while the OpenCV call is executing. Both CPU
  and wall durations are in the JSON. Background workers are included in both
  operation/sleep windows; these counters are not native profiler stack attribution.
- **Threads:** OS-native thread count, not `threading.active_count()`. A high
  count alone does not show CPU usage: retained workers may be asleep.
- **FPS and deadline misses:** distinguish excessive computation from waiting.
  If the target rate cannot be met, reduce image size/FPS. If operations occupy
  nearly the whole period, little idle time remains to expose busy-waiting.

The most convincing signature is high `default` CPU, substantial CPU during
sleep, and a large drop with `passive` and/or `single` at similar achieved FPS.
`passive` may leave the same number of OS threads alive. PyPI may still create
a pthread pool, so `OMP_NUM_THREADS`/`OMP_WAIT_POLICY` may have no effect there.
The saved build information records the actual selected parallel framework.

Not every machine/runtime will reproduce the symptom at these defaults. Try
`remap`, `cvtcolor`, 5/15/30/60 FPS, and image sizes 640x480 through 1920x1080.
Repeat comparisons on an otherwise idle host. An environment with many visible
CPUs but a small container CPU quota can distort the results; affinity, root
cgroup information and per-thread CPU deltas are recorded when available.
Cgroup paths are diagnostic hints, not a complete hierarchical quota detector.

## Isolation and scope

- `conda`: OpenCV and NumPy come from conda-forge; the OpenCV metapackage is
  constrained to its headless variant.
- `pypi`: `opencv-python-headless==4.13.0.92` and `numpy==2.2.6` come from PyPI.
  Python, psutil and threadpoolctl are common conda-forge infrastructure.
- Both use Python 3.11 and NumPy 2.2.6. The PyPI wheel suffix `.92` is a
  packaging version: its OpenCV runtime reports `4.13.0`.
- Inherited `OMP_*`, `GOMP_*`, `KMP_*`, `OPENBLAS_*`, `MKL_*` and OpenCV
  thread/backend overrides are cleared. `OPENBLAS_NUM_THREADS=1` and
  `MKL_NUM_THREADS=1` are then set in **all** cases. This deliberately removes
  eager BLAS workers as a competing explanation; the timed operations use no
  BLAS, decoder or video capture API.
- Use `--inherit-thread-env` with `repro`/`suite` to preserve your ambient runtime
  settings for a separate experiment; BLAS remains limited to one. Saved JSON
  records effective threading variables. Do not confuse this with the clean run.
- This is a comparison of packaged stacks, not a controlled rebuild changing
  only one CMake switch. Different BLAS/IPP/HAL/OpenMP/dependency builds can still
  affect timing. It cannot alone establish responsibility for a packaging bug.
- OpenCV 4.13 is deliberate: it follows removal of the built-in backend's
  `omp_set_dynamic(1)` initialization. See
  [OpenCV#25717](https://github.com/opencv/opencv/issues/25717) and
  [PR#28122](https://github.com/opencv/opencv/pull/28122).

## Verification and reporting

```bash
# Fast import/output smoke run; not a performance measurement.
pixi run -e conda smoke
pixi run -e pypi smoke

# Exact package inventories, in addition to the provenance in each JSON.
pixi list -e conda
pixi list -e pypi
```

For an upstream/feedstock report, attach `comparison.md`, both default-case
JSON files, their `*-build.txt` files, `pixi.toml`, and `pixi.lock`. Record any
custom dimensions/FPS and whether the process was CPU-throttled. A native
profiler/backtrace during a high-CPU sleep interval can confirm which runtime
is actually spinning.

The archive's `validation/` directory, if present, contains results measured in
the authoring environment and a note describing their limits. Your own output
always goes to `results/` unless explicitly overridden.
