# OpenMP waiting investigation: CI results, 29 October 2026

The excessive CPU use is reproducible without OpenCV. On the tested x86-64
runners, GNU OpenMP's default waiting policy burns substantial CPU between tiny
periodic operations. The cost rises with the spin count and falls close to the
zero-spin baseline when PAUSE instructions are removed from a private runtime
copy. The architecture gap persists with exactly two threads pinned to two
distinct physical cores, so it does not require SMT siblings or a different
number of active workers.

This identifies a runtime waiting mechanism that OpenCV's OpenMP backend exposes.
It does not establish a conda-forge-specific runtime code defect. Conda-forge's
backend choice remains relevant to which users encounter it.

## Method

OpenCV 4.13.0 is built from source with the OpenMP backend; BLAS is limited to one
thread and OpenCL is disabled. The standalone C program links no OpenCV. Both
programs must load the exact same selected libgomp 16.2.0 file within each job.
The system C compiler is GCC 13.3.0 on both architectures. The source-built OpenCV
compiler is independently recorded in its build evidence.

Each setting starts a fresh process: one second warmup, four seconds measurement,
30 FPS target, three repetitions in deterministic shuffled order. Tables report
medians. CPU percentages divide CPU seconds by the entire measured wall interval:
100% is one logical CPU. Worker CPU is process CPU minus caller-thread CPU;
sleeping-caller worker CPU applies that subtraction only around the caller's sleep.
Clock-reading boundaries can produce small differences between component sums.

The retained JSON contains individual repetitions, raw clock deltas, FPS,
deadline misses, observed teams, hardware, library hashes and package versions.
These are periodic-workload diagnostics, not peak-throughput benchmarks.

## Hardware

GitHub's four-vCPU labels do not imply identical physical topology. The first
x86 VM exposed two physical cores with SMT, while ARM64 exposed four cores
without SMT. The pinned-core follow-up explicitly compensates for this. Different
jobs can land on different AMD EPYC models; comparisons of original/private
runtimes below are performed within the same job.

| Experiment | Architecture | Reported processor | vCPUs | Threads/core |
| --- | --- | --- | ---: | ---: |
| first | x86-64 | AMD EPYC 7763 64-Core Processor | 4 | 2 |
| first | arm64 | Neoverse-N2 | 4 | 1 |
| focused | x86-64 | AMD EPYC 9V74 80-Core Processor | 4 | 2 |
| focused | arm64 | Neoverse-N2 | 4 | 1 |
| physical | x86-64 | AMD EPYC 9V74 80-Core Processor | 4 | 2 |
| physical | arm64 | Neoverse-N2 | 4 | 1 |

## Four-thread runtime intervention

The private x86 library differs only at the 13 decoded PAUSE instructions:
`f3 90` becomes `90 90` (NOP NOP). Executable ELF sections and instruction bytes
are validated; the installed library is never changed. ARM64 is an unchanged
copy control. Runtime paths and hashes verify which copy each child loads.
The columns below compare the same machine, workload, team size and cadence.

| Architecture | Operation | Original default CPU % | Original zero-spin CPU % | Private copy default CPU % | Private copy 300000 CPU % | Private copy zero CPU % |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| x86-64 | native | 70.84 | 0.32 | 1.66 | 1.63 | 0.32 |
| x86-64 | resize | 74.36 | 3.72 | 5.01 | 5.22 | 3.56 |
| x86-64 | cvtcolor | 75.40 | 3.46 | 4.98 | 5.02 | 3.50 |
| arm64 | native | 1.63 | 0.36 | 1.69 | 1.68 | 0.34 |
| arm64 | resize | 5.97 | 4.42 | 5.98 | 5.95 | 4.48 |
| arm64 | cvtcolor | 7.16 | 5.59 | 7.04 | 6.82 | 5.68 |

Removing PAUSE is a diagnostic intervention, not a proposed production runtime.
It changes spin duration and can change contention, latency and power behavior
in other workloads. The independent zero-spin control gives the practical
reference without modifying runtime instructions.

## Match two physical cores and pin two threads

For each VM, sysfs identifies two distinct `(physical_package_id, core_id)`
pairs. The process is restricted to one logical CPU per chosen core;
`OMP_PLACES` and `OMP_PROC_BIND=TRUE` bind the two threads to those CPUs.
Saved verbose libgomp output confirms their affinities and the default spin count
of 300000. VM topology does not guarantee exclusive use of the host cores.

| Architecture | Operation | Default CPU % | Zero-spin CPU % | Default sleeping-caller worker CPU % | Zero-spin sleeping-caller worker CPU % |
| --- | --- | ---: | ---: | ---: | ---: |
| x86-64 | native | 22.51 | 0.18 | 22.34 | 0.01 |
| x86-64 | resize | 24.40 | 2.07 | 22.90 | 0.02 |
| x86-64 | cvtcolor | 24.34 | 2.02 | 22.96 | 0.02 |
| arm64 | native | 0.54 | 0.19 | 0.35 | 0.02 |
| arm64 | resize | 4.87 | 4.48 | 0.12 | 0.03 |
| arm64 | cvtcolor | 5.94 | 5.59 | 0.33 | 0.02 |

## Spin-count response, four threads

Independent first full sweep. Total process CPU %, with explicit spin counts:

| Architecture | Operation | 0 | 1000 | 10000 | 100000 | 300000 | 1000000 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| x86-64 | native | 0.45 | 0.84 | 3.61 | 26.98 | 77.31 | 254.94 |
| x86-64 | resize | 5.00 | 5.50 | 8.86 | 31.21 | 81.89 | 258.05 |
| x86-64 | cvtcolor | 5.43 | 5.46 | 8.60 | 31.57 | 82.29 | 258.26 |
| arm64 | native | 0.36 | 0.36 | 0.46 | 0.92 | 1.78 | 3.64 |
| arm64 | resize | 4.45 | 4.33 | 4.48 | 5.07 | 5.97 | 8.08 |
| arm64 | cvtcolor | 5.63 | 5.52 | 5.67 | 6.21 | 7.21 | 9.00 |

The complete one-/two-/four-thread results and all repeats are in the JSON and
CI job summaries. PASSIVE also approaches the explicit-zero baseline. All cases
ran near the target 30 FPS; small scheduling variations are retained in the data.

## Waiting-loop calibration

This separate microbenchmark times 30 million volatile-flag checks, with either
x86 PAUSE or a compiler barrier. The compiler-barrier version emits no matching
CPU pause instruction on ARM64. It approximates the runtime loop shape; it is not
a direct invocation of libgomp's internal wait function. The runtime-copy
intervention above supplies the direct library-level check.

| Architecture | PAUSE / native loop ns per iteration | Compiler-barrier-only ns per iteration | Approx. time for 300000 native-loop iterations |
| --- | ---: | ---: | ---: |
| x86-64 | 25.009 | 0.275 | 7.503 ms |
| arm64 | 0.298 | 0.297 | 0.089 ms |

GNU OpenMP bounds this waiting by loop iterations rather than a portable wall-time
budget. A slower iteration therefore keeps a worker runnable for longer before
it reaches the futex sleep. PAUSE is a processor hint, not an operating-system
sleep. Repeating this behavior every frame can cost much more CPU than resize
or grayscale itself.

The exact ratio is specific to these CPUs and VMs. It should not be generalized
to every x86/ARM processor. The evidence supports tuning the waiting policy or
benchmarking another OpenCV backend for this periodic workload; it does not show
that zero spinning is best for tightly repeated, throughput-oriented OpenMP work.

## Evidence and reproduction

- [Individual measurements and metadata](measurements/2026-10-29.json)
- [Full spin sweep](https://github.com/traversaro/reproduce-opencv-100-cpu-usage-openmp/actions/runs/40845594807)
- [Two pinned physical cores](https://github.com/traversaro/reproduce-opencv-100-cpu-usage-openmp/actions/runs/40847250989)
- [Corrected runtime intervention](https://github.com/traversaro/reproduce-opencv-100-cpu-usage-openmp/actions/runs/40848501660)
- [Commands and measurement details](README.md)
- [GNU libgomp spin-count documentation](https://gcc.gnu.org/onlinedocs/libgomp/GOMP_005fSPINCOUNT.html)
- [GCC Linux waiting loop](https://github.com/gcc-mirror/gcc/blob/master/libgomp/config/linux/wait.h)
- [GCC x86 relax instruction](https://github.com/gcc-mirror/gcc/blob/master/libgomp/config/linux/x86/futex.h)
- [GCC generic Linux relax implementation](https://github.com/gcc-mirror/gcc/blob/master/libgomp/config/linux/futex.h)
- [Related scikit-learn waiting-policy discussion](https://github.com/scikit-learn/scikit-learn/issues/34764)

CI artifacts also contain full build information, CMake configuration, raw
OpenCV reports, compiler version, disassembly, runtime patch manifest and hashes.
Artifacts expire after 30 days; the compact individual measurements are retained
in this repository. `collect_results.py` regenerates the compact snapshot from
extracted artifact directories using `--input LABEL=directory` and `--run LABEL=URL`.

