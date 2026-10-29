# GNU and LLVM OpenMP waiting: source and issue references

Research checked 29 October 2026. This note supplements [the research log](RESEARCH_LOG.md)
and [retained GNU/OpenCV experiments](RESULTS.md). Source links below are pinned
to upstream revisions inspected while documenting the investigation. They explain
the implementation; they are not a claim that the tested packaged binaries were
built from these exact upstream HEAD revisions.

## GNU implementation

| Source | Function / purpose |
| --- | --- |
| [Linux waiting](https://github.com/gcc-mirror/gcc/blob/82a9c3b4850be48ed1ed5cc471720a2445d50443/libgomp/config/linux/wait.h#L48-L68) | `do_spin()` counts iterations and checks the shared value; `do_wait()` subsequently calls `futex_wait()` |
| [x86 relax](https://github.com/gcc-mirror/gcc/blob/82a9c3b4850be48ed1ed5cc471720a2445d50443/libgomp/config/linux/x86/futex.h#L120-L124) | `cpu_relax()` emits `__builtin_ia32_pause()` |
| [Generic Linux relax](https://github.com/gcc-mirror/gcc/blob/82a9c3b4850be48ed1ed5cc471720a2445d50443/libgomp/config/linux/futex.h#L66-L70) | `cpu_relax()` is an empty assembly statement with a compiler memory barrier |
| [Architecture selection](https://github.com/gcc-mirror/gcc/blob/82a9c3b4850be48ed1ed5cc471720a2445d50443/libgomp/configure.tgt#L43-L45) | AArch64 selects the generic Linux path; x86 selects `linux/x86` later in this file |
| [Default counts](https://github.com/gcc-mirror/gcc/blob/82a9c3b4850be48ed1ed5cc471720a2445d50443/libgomp/env.c#L2494-L2517) | Initializes the spin count, with a rough historical time estimate and oversubscription limits |
| [Hybrid x86 adjustment](https://github.com/gcc-mirror/gcc/blob/82a9c3b4850be48ed1ed5cc471720a2445d50443/libgomp/config/linux/x86/spincount.h#L33-L43) | Changes the unset-policy default count to 1 when the relevant CPUID hybrid bit is set |
| [Barrier wait](https://github.com/gcc-mirror/gcc/blob/82a9c3b4850be48ed1ed5cc471720a2445d50443/libgomp/config/linux/bar.c#L35-L49) | Barrier waiting reaches the shared `do_wait()` mechanism |
| [Worker lifetime](https://github.com/gcc-mirror/gcc/blob/82a9c3b4850be48ed1ed5cc471720a2445d50443/libgomp/team.c#L70-L140) | Worker execution and reuse, including pool-docking synchronization |

The default initialization comment assumes roughly 100000 spins/ms, aiming for
about 3 ms when the policy is unset. That estimate is not a calibrated timer.
The measured x86 loop was approximately 25 ns per iteration and the ARM loop
approximately 0.30 ns. A fixed iteration count therefore represents very different
waiting durations. The private runtime intervention in RESULTS.md tests this
mechanism directly in the packaged library.

PAUSE is not an OS sleep. It is a processor hint whose implementation can slow
polling, reduce power, and improve resource sharing. Its latency is processor-specific.
Intel's [optimization manual, PAUSE latency section](https://cdrdv2-public.intel.com/821612/248966-Optimization-Reference-Manual-V1-050.pdf)
discusses substantial latency differences between microarchitectures and the risk
of fixed loops of PAUSE instructions. This is supporting architectural context;
the measured runners here were AMD EPYC, not Intel Skylake.

## Upstream issue search

No report was found specifically tracking the x86/AArch64 waiting-time ratio
measured here. This is a search result, not proof that no such discussion exists.
The following are related rather than interchangeable root-cause reports.

| Reference | Relevance and checked status |
| --- | --- |
| [GCC PR109812](https://gcc.gnu.org/bugzilla/show_bug.cgi?id=109812), [implemented commit](https://github.com/gcc-mirror/gcc/commit/e1e127de18dbee47b88fa0ce74a1c7f4d658dc68) | Architecture-sensitive defaults: benchmarks motivated reducing the unset-policy spin count to 1 on hybrid x86. The GCC Bugzilla page was access-blocked; the linked commit and source were readable. |
| [GCC PR109062 fix](https://gcc.gnu.org/pipermail/gcc-cvs/2023-March/379210.html) | Fixed default-policy initialization in 2023 so the count matched its documentation. A historical default-setting bug, not the demonstrated GCC 16.2 waiting mechanism. |
| [scikit-learn #34764](https://github.com/scikit-learn/scikit-learn/issues/34764) | Open when checked. Compares GNU and LLVM waiting, interference with BLAS pools, and workloads harmed by reducing spinning. |
| [LLVM #208405](https://github.com/llvm/llvm-project/issues/208405) | Open when checked. Default barrier waiting in imbalanced fork/join workloads issues many `sched_yield()` calls; zero blocktime trades those for blocking and can hurt elapsed time. |
| [LLVM #195239](https://github.com/llvm/llvm-project/issues/195239), [PR #195473](https://github.com/llvm/llvm-project/pull/195473) | Many-core barrier/wait-policy discussion. The issue closed after an application configuration change; the PR closed without merging. Closure is not evidence that LLVM changed its default. |
| [primecount application PR #117](https://github.com/kimwalisch/primecount/pull/117) | The application-level configuration referenced by that LLVM discussion. |

The LLVM discussion separates time before blocking from yielding during that
time. Maintainers describe these as configurable policies with workload-dependent
tradeoffs. It does not establish that a single global policy is best for both
short camera operations and highly parallel throughput-oriented computations.

## LLVM implementation

| Source | Function / purpose |
| --- | --- |
| [Default blocktime](https://github.com/llvm/llvm-project/blob/2f7a16ae3f634b1e889d13b01e6a65914a4d13c1/openmp/runtime/src/kmp.h#L1242-L1249) | Normally 200000 microseconds (200 ms), or zero for recognized hybrid CPUs |
| [Hybrid detection](https://github.com/llvm/llvm-project/blob/2f7a16ae3f634b1e889d13b01e6a65914a4d13c1/openmp/runtime/src/kmp.h#L3355-L3362) | x86 uses CPU flags; Darwin AArch64 is treated as hybrid; other platforms use the remaining branch |
| [Policy parsing](https://github.com/llvm/llvm-project/blob/2f7a16ae3f634b1e889d13b01e6a65914a4d13c1/openmp/runtime/src/kmp_settings.cpp#L817-L845) | Explicit ACTIVE chooses infinite blocktime and PASSIVE chooses zero, unless blocktime was specified |
| [Waiting deadline](https://github.com/llvm/llvm-project/blob/2f7a16ae3f634b1e889d13b01e6a65914a4d13c1/openmp/runtime/src/kmp_wait_release.h#L487-L524) | Establishes a time-based hibernation threshold |
| [Sleep decision](https://github.com/llvm/llvm-project/blob/2f7a16ae3f634b1e889d13b01e6a65914a4d13c1/openmp/runtime/src/kmp_wait_release.h#L611-L640) | Checks infinite waiting, tasks, deadlines, and whether the wait can suspend |
| [Clock checks](https://github.com/llvm/llvm-project/blob/2f7a16ae3f634b1e889d13b01e6a65914a4d13c1/openmp/runtime/src/kmp.h#L1274-L1292) | Timer/timestamp-based blocking checks rather than GNU's main fixed-iteration budget |
| [Pause/backoff/yield](https://github.com/llvm/llvm-project/blob/2f7a16ae3f634b1e889d13b01e6a65914a4d13c1/openmp/runtime/src/kmp.h#L1631-L1673) | Selects available pause instructions/backoff and scheduler yielding |

[LLVM's runtime documentation](https://openmp.llvm.org/design/Runtimes.html)
describes `KMP_BLOCKTIME` and `OMP_WAIT_POLICY`. The default policy is labelled
passive/throughput, but leaving OMP_WAIT_POLICY unset still permits active waiting
for the configured blocktime. Explicit PASSIVE is different from leaving it unset.

Usual defaults with runtime-specific overrides unset and without topology or
oversubscription adjustments:

| Policy | GNU libgomp | LLVM libomp |
| --- | --- | --- |
| Unset | 300000 spin iterations | Normally 200 ms blocktime |
| ACTIVE | 30 billion spin iterations | Infinite blocktime |
| PASSIVE | Zero spins | Zero blocktime |

These defaults are implementation details. Explicit `GOMP_SPINCOUNT` or
`KMP_BLOCKTIME`, topology detection, oversubscription and runtime versions can
change the effective behavior. LLVM also may yield within its blocktime window;
that window is not a guarantee of uninterrupted busy-spinning for an exact duration.
A scheduler yield is not equivalent to sleeping until new work arrives.

LLVM's elapsed-time threshold avoids the particular GNU iteration-count-to-time
portability problem. It does not ensure low waiting CPU. At 30 FPS the next region
arrives after about 33 ms, well before a 200 ms sleep threshold, so workers can
remain active across frames. Clock-check granularity and different wait paths
also mean this is not an exact portable timer guarantee for every barrier.

## Short local LLVM check

This was executed in the authoring environment on Linux x86-64, AMD EPYC 9V74,
restricted to CPUs 0-3, with an eight-CPU cgroup quota (four OpenMP threads were
requested). It was not a GitHub Actions LLVM run and did not test LLVM on ARM64.

The tested package was conda-forge `llvm-openmp` 23.1.4, build `h7148c6a_0`,
obtained through the package API. The GCC-generated OpenMP object for the
standalone C reproducer was linked explicitly against libomp, without adding
`-fopenmp` at the final link. This exercises LLVM's GNU ABI compatibility layer,
not Clang's native `__kmpc_*` frontend ABI. `ldd` showed libomp and no libgomp in
that executable. A settings check reported 200 ms blocktime, throughput mode,
yield mode 1, and the passive default-policy label.

Each setting used a fresh process, four threads, 30 FPS, 0.5 s warmup, 2 measured
seconds, and three repetitions. Ambient OMP/GOMP/KMP settings were cleared;
OMP_NUM_THREADS=4, OMP_DYNAMIC=FALSE and OMP_THREAD_LIMIT=4 were set. The following
are reported medians, with 100% meaning one logical CPU:

| LLVM setting | Total CPU % | Worker CPU during caller sleep, as % of full wall time |
| --- | ---: | ---: |
| Default | 300.18 | 299.48 |
| KMP_BLOCKTIME=0 | 0.60 | 0.01 |
| KMP_BLOCKTIME=1 | 9.74 | 9.02 |
| KMP_BLOCKTIME=10 | 90.64 | 89.87 |
| OMP_WAIT_POLICY=PASSIVE | 0.62 | 0.01 |
| OMP_WAIT_POLICY=ACTIVE | 300.34 | 298.94 |

A local GNU 16.2.0 check of the standalone workload reported 76.26% total CPU
(default) and 0.57% (zero spins). The local runs are quick diagnostics rather
than a formal cross-compiler performance ranking. The GNU/OpenCV CI evidence is
separately retained at much greater detail in RESULTS.md.

**Evidence limitation:** the original per-repetition local JSON and temporary
binaries were unavailable at documentation time. The table and the accompanying
JSON preserve medians transcribed from the prior execution output; they do not
fabricate raw samples. There was no rerun while preparing this documentation.

## Reproducing the LLVM linkage and settings

With a separately installed LLVM libomp available, the essential build steps
from the repository root are:

```sh
gcc -O2 -Wall -Wextra -Werror -fopenmp \
  -c investigation/openmp_wait.c -o /tmp/runtime-probe.o
# Replace the library directory below with the actual installation directory.
gcc /tmp/runtime-probe.o /path/to/llvm/lib/libomp.so \
  -Wl,-rpath,/path/to/llvm/lib -lm -o /tmp/runtime-probe-llvm
ldd /tmp/runtime-probe-llvm
```

Run cases in fresh, clean environments. For example, with ambient OMP/GOMP/KMP
settings cleared, compare `KMP_BLOCKTIME=0`, `1`, `10`, the unset default, PASSIVE,
and ACTIVE using:

```sh
OMP_NUM_THREADS=4 OMP_DYNAMIC=FALSE OMP_THREAD_LIMIT=4 \
  KMP_BLOCKTIME=0 /tmp/runtime-probe-llvm 4 2 0.5 30

OMP_NUM_THREADS=4 OMP_DYNAMIC=FALSE OMP_THREAD_LIMIT=4 \
  KMP_SETTINGS=1 /tmp/runtime-probe-llvm 4 2 0.5 30
```

Remove explicit KMP_BLOCKTIME before measuring the default or policy-only cases.
Select the same four allowed CPUs for every child. Record runtime package/version,
loaded-library paths, effective settings, actual teams and CPU topology. Repeating
this on ARM64 is still needed before claiming measured LLVM architecture parity.
