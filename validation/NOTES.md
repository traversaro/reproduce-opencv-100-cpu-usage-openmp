# Validation on 28 October 2026

The included `resize/` comparison was actually run in the authoring environment
using Pixi 0.83.0, Linux x86_64, nine CPUs in the affinity mask, Python 3.11,
OpenCV 4.13.0 and NumPy 2.2.6. Both environments were installed successfully;
the lockfile covers linux-64 and linux-aarch64. Only linux-64 was executed.

Command (with the locally installed Pixi executable supplied via `--pixi`):

```bash
python compare.py --pixi /path/to/pixi --duration 5 --warmup 1 --output-dir validation/resize
```

All cases processed synthetic 1920x1080 images, resized to 960x540, targeting
30 FPS. They ran sequentially. Each measurement followed one second of warmup
and lasted five seconds. No ACTIVE wait setting was injected.

| Case | conda-forge CPU % | PyPI CPU % |
| --- | ---: | ---: |
| Default | 189.6 | 15.0 |
| OpenCV one thread | 3.5 | 4.7 |
| OpenMP PASSIVE | 5.9 | 24.8 |
| OpenMP one thread | 3.3 | 19.5 |

100% means one CPU, not the entire machine. These are short observations on a
shared execution host, not stable comparative performance benchmarks. The PyPI
build uses pthreads, so the differences among its default/PASSIVE/OMP-one-thread
rows should not be interpreted as effects of OpenMP settings.

In conda-forge's default case, CPU accrued during Python's sleeps was 179.3%
of the sleep wall time. PASSIVE reduced that to 0.2%, while keeping nine OS
threads. This reproduces excess CPU use consistent with OpenMP busy-waiting;
it does not reproduce literal 100% utilization of every available CPU, and it
is not a native stack-profile attribution of the spinning instructions.

The saved build information identifies OpenMP for conda-forge and pthreads for
PyPI. JSON provenance confirms that OpenCV/NumPy are conda packages in the first
environment and PyPI distributions in the second. BLAS was limited to one
thread in both. An earlier three-second conda-only run showed the same pattern
(189.9% default, 3.7% OpenCV single thread, 8.9% PASSIVE).

The executable `pixi run compare` task was also smoke-tested through both
environments at 320x240, as were remap and color conversion. Small-image smoke
runs do not necessarily trigger parallelism and are not reproductions.

Absolute module paths in the raw files refer to the authoring environment;
they are diagnostic output, not paths required to run this project.
