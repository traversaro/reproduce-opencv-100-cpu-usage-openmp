# OpenCV periodic workload comparison

CPU percentages use 100% = one logical CPU; values may exceed 100%. Sleep CPU is process CPU accrued while the calling Python thread sleeps.

| Environment | Case | Backend | CPU % | Sleep CPU % | Peak threads | FPS |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| conda | idle | OpenMP | 0.4 | 0.1 | 1 | 30.0 |
| conda | default | OpenMP | 189.6 | 179.3 | 9 | 30.0 |
| conda | single | OpenMP | 3.5 | 0.1 | 1 | 30.0 |
| conda | passive | OpenMP | 5.9 | 0.2 | 9 | 30.0 |
| conda | omp1 | OpenMP | 3.3 | 0.1 | 1 | 30.0 |
| pypi | idle | pthreads | 0.3 | 0.1 | 1 | 30.0 |
| pypi | default | pthreads | 15.0 | 5.8 | 8 | 30.0 |
| pypi | single | pthreads | 4.7 | 0.1 | 1 | 30.0 |
| pypi | passive | pthreads | 24.8 | 8.2 | 8 | 29.6 |
| pypi | omp1 | pthreads | 19.5 | 6.4 | 8 | 30.0 |

High sleep CPU that falls with PASSIVE is evidence of waiting overhead. Many sleeping OS threads alone do not prove CPU contention. A saturated image operation or missed target FPS requires a smaller image/lower FPS. This compares packaged stacks; it does not isolate every build/dependency difference.
