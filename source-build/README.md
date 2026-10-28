# Controlled source builds

These environments use **Pixi Build** with the `pixi-build-rattler-build` backend
(0.4.7) to compile OpenCV 4.13.0 directly from its upstream archive. The archive
SHA-256 is fixed in each recipe. No prebuilt OpenCV package is installed.

| Environment | Parallel framework | Backend-specific CMake switch |
| --- | --- | --- |
| `pthreads` | OpenCV pthreads pool | `WITH_PTHREADS_PF=ON` |
| `openmp` | GNU OpenMP | `WITH_OPENMP=ON` |
| `tbb` | oneTBB | `WITH_TBB=ON` |
| `serial` | No parallel framework | All three switches OFF |

All three backend switches start OFF; only the requested one is enabled. All
other CMake arguments and the build script are shared. The serial variant still
has ordinary OS thread support; it disables OpenCV parallel frameworks.

From the repository root:

```bash
# Builds all four packages on first use, then measures all five cases in each.
pixi run --manifest-path source-build/pixi.toml compare

# Try the same controlled comparison with remap.
pixi run --manifest-path source-build/pixi.toml compare --operation remap

# Build/run just one backend and its five diagnostic cases.
pixi run --manifest-path source-build/pixi.toml -e openmp suite --operation resize
pixi run --manifest-path source-build/pixi.toml -e pthreads suite --operation resize
```

The first build can take several minutes per backend. Pixi caches built source
packages. Builds use at most four compiler jobs to bound memory use. Source
builds have their own manifest and lockfile, so they do not change the existing
prebuilt conda-forge/PyPI comparison. Both Linux x86-64 and ARM64 are locked.

## What is controlled

- All variants use the same OpenCV release/archive, GCC 14 compiler family,
  CMake 3.31.8, Python 3.11 and NumPy 2.2.6 specifications.
- Host/build/run specifications are identical in the four recipes, including
  TBB development files and the OpenMP runtime even for variants that do not
  link them. Runtime environments share a Pixi solve group so common packages
  resolve to the same versions/builds.
- Only `core`, `imgproc` and Python bindings are built. IPP, ITT, LAPACK, Eigen,
  OpenCL, OpenVINO, CUDA, KleidiCV and Carotene are OFF in every build. This avoids
  alternate acceleration paths obscuring the parallel-framework comparison.
- The same synthetic Python workload and fresh-process runtime cases are used.
  BLAS workers are limited to one, just as in the prebuilt comparison.

This is a controlled **minimal image-processing build**, not a full recreation
of conda-forge's feature-rich recipe. Comparing these four source builds isolates
the framework choice much better than comparing a source build directly to a
prebuilt wheel. Backend defaults (including default team/pool sizes) remain part
of the behavior being compared.

## Build evidence and CI

Each package installs `share/opencv-source-build/build.json` and `CMakeCache.txt`.
The reproducer embeds the build metadata in each result JSON and copies the
CMake cache alongside it. The validator checks the actual `Parallel framework`
in `cv2.getBuildInformation()`, so a silently missing TBB/OpenMP backend fails CI.
It also rejects environments containing prebuilt OpenCV packages.

The [source workflow](../.github/workflows/source-backends.yml) has eight native
jobs: four backends on each of x86-64 and ARM64. Each job builds one variant and
tests resize, remap and color conversion sequentially, then uploads measurements,
CMake evidence and recipes. As with prebuilt CI, no CPU/FPS threshold is enforced.

See the [main README](../README.md) for interpretation of CPU during sleep versus
CPU during OpenCV calls. `OMP_NUM_THREADS` and `OMP_WAIT_POLICY` are expected to
affect the OpenMP build; changes in those rows for other backends are not evidence
of an OpenMP effect.
