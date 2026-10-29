# Research log: OpenCV threads, OpenMP waiting, and packaging

Recorded 29 October 2026. AI-assisted research summary of the questions,
evidence, experiments, corrections, and conclusions from this investigation.
This is a reviewable technical account, not a verbatim conversation transcript
or a statement from OpenCV, GCC, LLVM, RoboStack, or conda-forge maintainers.

## Reading map

- [Measured GNU/OpenCV results](RESULTS.md): controlled experiments, tables,
  hardware, and links to successful CI runs.
- [GNU and LLVM implementation analysis](RUNTIME_COMPARISON.md): source links,
  upstream reports, waiting defaults, local LLVM observations, and reproduction.
- [378 retained individual CI samples](measurements/2026-10-29.json).
- [Reported local runtime medians](measurements/runtime-local-reported-2026-10-29.json):
  a separate, less complete evidence record; original raw samples are unavailable.
- [How to run the investigation](README.md), [controlled source builds](../source-build/README.md),
  and [original packaged-stack validation](../validation/NOTES.md).

## 1. Initial question and competing explanations

The starting symptom was unexpectedly many native threads and high CPU usage
when using OpenCV from conda-forge, particularly in periodic camera pipelines.
The initial question was whether the cause was OpenCV itself, packaging, or a
runtime/dependency interaction.

Thread count and CPU consumption need separate measurements. A retained worker
can be blocked and consume essentially no CPU. Conversely, a small worker team
can consume considerable CPU without processing another image.

The investigation distinguished several possible sources:

| Source | Why it matters | Diagnostic implication |
| --- | --- | --- |
| OpenCV image-operation parallel framework | OpenMP, pthreads, TBB, etc. can create and retain workers | Record `cv2.getBuildInformation()` and test OpenCV's own thread limit |
| BLAS/runtime dependencies | Import or dependency initialization can introduce other pools | Limit BLAS to one thread and record loaded libraries/threadpool information |
| Video decoders such as FFmpeg | Capture/decoder threads are distinct from OpenCV's image-operation pool | Remove capture and codecs from the reproducer |
| Multiple application caller threads/processes | Nested/concurrent pools can amplify contention | Do not infer total process thread limits from an OpenCV team-size setting |
| Container CPU visibility/quota and affinity | Visible CPUs need not equal usable execution capacity | Save affinity and cgroup hints; avoid interpreting CPU count alone |

`cv2.setNumThreads(1)` is a control for OpenCV's parallel framework. It is not a
universal limit on every dependency's threads. [OpenCV issue #15277](https://github.com/opencv/opencv/issues/15277)
is a useful example: its reproducer opens a video capture, so decoder/dependency
threads must be distinguished from the image-processing backend.

## 2. Existing reports and packaging context

The clearest matching application report is [RoboStack/ros-jazzy#210](https://github.com/RoboStack/ros-jazzy/issues/210).
It reports all-core CPU use for a simple image topic with the conda OpenCV build,
and about 0.2% CPU on one core after adding `cv::setNumThreads(1)`, without dropped
frames. These are the reporter's observations, not measurements made by this
repository. The issue is closed, but its original subject is package availability;
closure should not be treated as evidence that the CPU behavior was fixed.

Related packaging reports include:

- [conda-forge/opencv-feedstock#455](https://github.com/conda-forge/opencv-feedstock/issues/455),
  open when checked: importing OpenCV interacts badly with parallel CPU PyTorch
  workloads. It establishes a related interaction report, not the same root cause.
- [conda-forge/opencv-feedstock PR #289](https://github.com/conda-forge/opencv-feedstock/pull/289),
  a closed proposal for an OpenCV variant without OpenMP.
- [STITCH camera setup notes](https://github.com/kushtimusPrime/stitch2#allied-vision-camera-setup),
  an application-level reference for limiting OpenCV threads in a camera pipeline.

The Linux conda-forge package tested here reports OpenMP; the tested PyPI
`opencv-python-headless` wheel reports pthreads. This is an observation about the
specific pinned packages, not a claim that every OpenCV distribution, platform,
or release has those defaults.

OpenCV 4.13.0 was deliberately selected in light of [OpenCV#25717](https://github.com/opencv/opencv/issues/25717)
and [PR #28122](https://github.com/opencv/opencv/pull/28122), concerning built-in
OpenMP initialization and dynamic team sizing. That history can affect how many
threads become visible. It does not establish that the OpenCV change caused
all reported waiting overhead.

## 3. First reproducible packaged-stack comparison

The Python reproducer removes ROS, cameras, displays, external images, and
video codecs. It preallocates deterministic 1920x1080 BGR images and outputs,
performs one operation at a target 30 FPS, and sleeps until the next frame.

The original Pixi environments isolate conda-forge OpenCV from the PyPI wheel,
with Python 3.11 and NumPy 2.2.6. Each case starts a fresh interpreter so environment
variables take effect before the runtime loads. Ambient threading overrides are
cleared; BLAS is restricted to one thread in every case.

The controls were import/idle, defaults, OpenCV one thread, OpenMP PASSIVE, and
`OMP_NUM_THREADS=1`. An optional explicit ACTIVE case is a positive control,
not evidence that the default package behaves identically.

The [original five-second resize measurements](../validation/NOTES.md) showed:

| Case | conda-forge CPU % | PyPI CPU % |
| --- | ---: | ---: |
| Default | 189.6 | 15.0 |
| OpenCV one thread | 3.5 | 4.7 |
| OpenMP PASSIVE | 5.9 | 24.8 |
| OpenMP one thread | 3.3 | 19.5 |

100% means one logical CPU. These are brief observations on a shared host with
nine CPUs in its affinity mask. Differences among PyPI rows are not effects of
OpenMP controls: that wheel used pthreads. Full provenance and limits are in
`validation/`. The conda case's high CPU during caller sleeps, and the large drop
with PASSIVE while workers remained alive, pointed toward runtime waiting.

This packaged comparison could not isolate a single build choice: wheels and
conda packages have other differences. It motivated controlled source builds.

## 4. Controlled OpenCV source builds

Pixi Build with `pixi-build-rattler-build` builds OpenCV 4.13.0 in four variants:
pthreads, OpenMP, TBB, and serial. They share the source archive/hash, build script,
compiler family, dependency specifications and solve group. All three backend
switches start disabled; only the selected framework is enabled.

These are minimal `core`/`imgproc`/Python builds, not full replicas of the
conda-forge recipe. IPP, BLAS/LAPACK acceleration, OpenCL, CUDA, and other alternate
acceleration paths are disabled. CMake configuration and actual runtime framework
are validated and saved.

The [initial source-build CI](https://github.com/traversaro/reproduce-opencv-100-cpu-usage-openmp/actions/runs/40780277944)
passed all eight native source-build jobs. On its x86 runners, default resize
CPU was 48.8% for OpenMP, 8.0% for pthreads, 15.7% for TBB, and 3.3% for serial.
These jobs used separate VMs, so those numbers are not a precise hardware-matched
throughput ranking. The framework/wait-policy effects motivated the stronger
within-job experiments below.

Resize and grayscale made waiting overhead particularly visible. Remap has a
larger useful computation cost, reducing the proportion of time spent waiting.
A correction made during discussion: **remap here runs on the CPU, not the GPU**.
The source build disables OpenCL and the inputs are CPU arrays.

## 5. Identify architecture and team-size effects

The next questions were whether the x86/ARM gap arose from different CPU counts,
team sizes, instructions, or OpenCV kernels.

The [fixed-team sweep](https://github.com/traversaro/reproduce-opencv-100-cpu-usage-openmp/actions/runs/40845594807)
used four threads, four allowed logical CPUs, dynamic teams disabled, and fresh
processes for each setting. It varied explicit spin counts from zero through one
million, plus unset-policy and PASSIVE cases, with one-/two-thread controls.
Three repetitions used shuffled order, one second warmup and four measured seconds.

A standalone C program performs tiny integer work in an OpenMP region and sleeps
to an absolute frame deadline. It links no OpenCV and loads the same GNU runtime
file as OpenCV within each job. It reproduced the large architecture difference:
77.43% total CPU on x86 versus 1.76% on ARM, falling to 0.45% and 0.36% with zero
spins. Increasing the spin count increased the excess CPU.

A necessary correction to the initial hardware interpretation: both GitHub runner
labels expose four vCPUs, but their topology differs. The first x86 job exposed
two SMT cores (EPYC 7763), while ARM exposed four non-SMT cores (Neoverse N2).
Four vCPUs are not equivalent to four physical cores.

The [physical-core follow-up](https://github.com/traversaro/reproduce-opencv-100-cpu-usage-openmp/actions/runs/40847250989)
selected two distinct VM-reported cores and bound two threads, one per core, on
both architectures. Runtime affinity output verified placement and the effective
default count of 300000. The standalone result remained 22.51% CPU on x86 versus
0.54% on ARM; zero spins reduced both to about 0.2%. Thus SMT sibling placement
and different active team sizes are not required for the effect. The VM topology
cannot prove exclusive use of the underlying host cores.

## 6. Trace and intervene on the waiting implementation

GNU's Linux waiting code counts iterations, executing `cpu_relax()` on each
unsatisfied check. Its x86 implementation emits PAUSE; the generic Linux path
selected for AArch64 emits a compiler barrier without a matching CPU instruction.
See the pinned source references in [the runtime comparison](RUNTIME_COMPARISON.md).

A separate microbenchmark of the loop shape measured approximately 25 ns per
iteration on the tested x86 CPU and 0.30 ns on ARM. Removing PAUSE from that
microbenchmark on the same x86 machine reduced its cost to approximately 0.275 ns.
This is a loop-shape calibration, not execution of libgomp's internal wait function.

The decisive intervention created a private copy of the actual GNU runtime and
replaced its 13 decoded x86 PAUSE instructions with NOP NOP. Only those bytes
could change; paths and hashes were checked, and the installed library stayed
untouched. ARM received an unchanged-copy control.

An initial x86 patcher run stopped before modifying bytes because debug sections
with overlapping virtual addresses were treated as candidate code sections.
The parser was corrected to select allocated executable sections. The fix was
verified against the exact packaged x86 library before rerunning CI.

The [corrected intervention](https://github.com/traversaro/reproduce-opencv-100-cpu-usage-openmp/actions/runs/40848501660)
passed on both architectures. Within the same x86 job:

| Workload | Original default CPU % | Zero-spin CPU % | Private PAUSE-removed default CPU % |
| --- | ---: | ---: | ---: |
| Standalone C | 70.84 | 0.32 | 1.66 |
| Resize | 74.36 | 3.72 | 5.01 |
| Grayscale | 75.40 | 3.46 | 4.98 |

The ARM unchanged-copy results remained similar. This is strong evidence that
instruction-dependent spin duration explains most of the gap on these machines.
Replacing PAUSE is an experimental intervention, not a production fix: that
instruction also serves power, contention, and synchronization-performance goals.

## 7. Measurement definitions and the 100% question

A reporting correction matters when comparing tables: the original
`repro.py` field `sleep_cpu_percent` divides CPU accrued during sleep by **sleep
wall time**. The later sweep tables divide every CPU component by the **full
measurement wall time**. The sweep derives its figures from raw CPU seconds.
Do not substitute one percentage directly for the other.

Process CPU clocks include all native threads even when Python's caller sleeps.
Caller-thread clocks let the isolated C program separate worker CPU from caller
CPU. These counters establish waiting cost but are not native stack-profile
attribution. Clock-read boundaries can cause small component-sum differences.

With `GOMP_SPINCOUNT` unset and no oversubscription, GNU uses 300000 iterations
when OMP_WAIT_POLICY is unset, 30 billion for explicit ACTIVE, and zero for
explicit PASSIVE. Those are different policies; unset is not equivalent to ACTIVE.

Using the measured loop costs gives approximate uninterrupted budgets:

| GNU policy | x86 budget | ARM budget |
| --- | ---: | ---: |
| Unset | 7.5 ms | 89 microseconds |
| ACTIVE | 750 s (12.5 minutes) | 8.9 s |
| PASSIVE | No initial spinning | No initial spinning |

These are estimates, not fixed delays imposed on image processing. Work arriving
earlier ends the wait. Oversubscription, detected hybrid x86 CPUs, explicit
spin-count overrides, and processor differences can change the applicable values.

At 30 FPS, frames arrive about every 33.3 ms. Both explicit ACTIVE budgets exceed
that interval, so workers can remain continuously active. Three waiting workers
can consume approximately 300% process CPU, even if the caller mostly sleeps.
For the unset x86 policy, the simple estimate `3 * 30 * 0.0075 = 0.675` CPU predicts
67.5%, close to the measured standalone 70.84% on the focused runner.

The experiments reproduce substantial waiting overhead. They do not establish
that the unset default saturates every core continuously for every workload.
CPU saturation percentages must state whether 100% means one CPU or the machine.

## 8. Other runtimes and what was not measured

The [runtime comparison](RUNTIME_COMPARISON.md) traces LLVM's time-based
`KMP_BLOCKTIME` threshold and its separate yielding policy. A short local x86
check of LLVM libomp 23.1.4 found approximately 300% CPU by default and 0.6% with
zero blocktime. Thus LLVM avoids GNU's iteration-to-duration portability problem
in its main sleep threshold, but changing runtime alone does not remove waiting
CPU usage. LLVM-on-ARM was not measured in this investigation.

The local LLVM observation is distinct from the retained CI data. Its original
per-repetition raw file was not available when these notes were written. The
reported medians are preserved with that limitation rather than reconstructed
as individual samples or presented as a new CI run.

## 9. Conclusions, scope, and remaining questions

Established for these experiments:

1. Python can reproduce the symptom without ROS, cameras, codecs, or GPU work.
2. GNU OpenMP waiting reproduces it without OpenCV at all.
3. The spin-count response, zero-spin/PASSIVE controls, physical-core controls,
   and private runtime intervention identify a runtime waiting mechanism.
4. Thread count alone does not establish CPU consumption; PASSIVE can preserve
   the workers while eliminating most of their waiting CPU.
5. OpenCV packaging selects which framework exposes users to this behavior.
   The evidence does not establish a conda-forge-specific GNU runtime defect.
6. Pthreads reduced waiting overhead in the sampled periodic workloads, but
   there is no universal throughput ranking for all applications or machines.
7. LLVM can also have high waiting CPU, despite using a time-based main threshold.

Remaining limits and questions:

- PAUSE latency and scheduling behavior vary across processors and VMs. The
  measured ratio is not an architectural constant or evidence that ARM runs
  ordinary computation 80 times faster.
- The full application may also have decoder/BLAS pools, multiple callers,
  nested parallelism, or external contention absent from the minimal reproducer.
- Zero spinning can lose throughput when parallel regions arrive very frequently;
  a periodic 30-FPS camera result does not justify changing every runtime's default.
- LLVM ARM64 and other runtime/compiler combinations require their own measurements.
- A backend/package change should also be tested on the actual application,
  including latency and dropped frames, not only average CPU.
- No issue was found specifically tracking this measured GNU x86/ARM ratio.
  Related upstream issues and the exact source locations are catalogued separately.

All final GNU experimental jobs passed. CI checks validate execution, provenance,
framework selection, teams, and measurement structure; performance outcomes are
not pass/fail thresholds. The documentation does not claim a feedstock or upstream
fix was submitted. The modified runtime is diagnostic only.
