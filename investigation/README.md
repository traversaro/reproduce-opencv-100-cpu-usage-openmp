# OpenMP waiting investigation

`spin-sweep.yml` runs on native Linux x86-64 and ARM64. It reuses the locked
source-built OpenMP environment and checks that OpenCV and the standalone C
program load exactly the same libgomp file. No OpenCV is linked into the C program.

The primary sweep uses exactly four OpenMP threads, affinity restricted to four
allowed logical CPUs, `OMP_DYNAMIC=FALSE`, and `OMP_THREAD_LIMIT=4`. Each fresh
process tests the default, explicit spin counts 0/1000/10000/100000/300000/1000000,
or PASSIVE. One- and two-thread controls test default and zero spinning. All
settings run three times, in deterministic shuffled order, at 30 FPS, with one
second warmup and four seconds measurement. Only resize and BGR-to-gray are used.

The standalone program dispatches tiny integer work through an OpenMP parallel
region and dynamic loop, then sleeps to an absolute frame deadline. It checks
the actual team size. CPU clocks distinguish caller CPU from other-thread CPU,
including other-thread CPU accrued during the caller's sleep. In the isolated
C process these other threads are OpenMP workers. In OpenCV runs we also record
native libraries and thread counts to check isolation.

All sweep percentages use the **entire measured wall interval** as denominator.
The older `repro.py` field `sleep_cpu_percent` uses only `sleep_wall_s` as its
denominator; those numbers must not be directly substituted in this report.
The sweep derives its percentages from raw CPU seconds. Repeated samples and
ranges are retained; this is diagnostic evidence, not a stable throughput benchmark.

A separate 30-million-iteration microbenchmark measures the waiting-loop shape:
volatile flag load plus x86 PAUSE, or flag load plus compiler barrier on ARM64.
It is an approximation, not execution of libgomp's exact internal wait function.
Full native/libgomp disassemblies, CPU topology (`lscpu`), affinity, library hash,
compiler version, runtime environment and raw OpenCV reports are uploaded.

To reproduce locally after installing the source environment:

```sh
pixi install --locked --manifest-path source-build/pixi.toml -e openmp
mkdir -p results/spin-sweep
pixi run --locked --manifest-path source-build/pixi.toml -e openmp bash -c \
  'gcc -O2 -Wall -Wextra -Werror -fopenmp ../investigation/openmp_wait.c -L"$CONDA_PREFIX/lib" -Wl,-rpath,"$CONDA_PREFIX/lib" -lm -o ../results/spin-sweep/openmp_wait'
pixi run --locked --manifest-path source-build/pixi.toml -e openmp \
  python ../investigation/sweep.py --native ../results/spin-sweep/openmp_wait
```

A system C compiler and binutils are required. The compiler is recorded; the
runtime is explicitly linked from Pixi and verified by `ldd` before measurement.
