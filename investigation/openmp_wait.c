#define _GNU_SOURCE
#include <omp.h>
#include <time.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <math.h>
#include <errno.h>
#include <string.h>

static double clock_s(clockid_t id) {
    struct timespec t;
    if (clock_gettime(id, &t)) { perror("clock_gettime"); exit(2); }
    return t.tv_sec + t.tv_nsec * 1e-9;
}
static void until(double deadline) {
    struct timespec t = {(time_t)deadline, (long)((deadline - (time_t)deadline) * 1e9)};
    int err;
    while ((err = clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &t, NULL)) == EINTR) {}
    if (err) { fprintf(stderr, "clock_nanosleep: %d\n", err); exit(2); }
}
static volatile unsigned long sink[256];
static int region(int threads) {
    int actual = 0;
    #pragma omp parallel num_threads(threads) shared(actual)
    {
        #pragma omp master
        actual = omp_get_num_threads();
        #pragma omp for schedule(dynamic)
        for (int i=0; i<256; ++i) {
            unsigned long v = i + 1;
            for (int j=0; j<32; ++j) v = v * 1664525UL + 1013904223UL;
            sink[i] = v;
        }
    }
    return actual;
}
static inline void relax_cpu(void) {
#if defined(__x86_64__) || defined(__i386__)
    __asm__ volatile("pause" ::: "memory");
#else
    __asm__ volatile("" ::: "memory");
#endif
}
int main(int argc, char **argv) {
    if (argc > 1 && (!strcmp(argv[1], "spin") || !strcmp(argv[1], "spin-nopause"))) {
        volatile int flag = 0;
        const long count = 30000000;
        double wall = clock_s(CLOCK_MONOTONIC), cpu = clock_s(CLOCK_THREAD_CPUTIME_ID);
        if (!strcmp(argv[1], "spin-nopause")) {
            for (long i=0; i<count; ++i) { if (flag) break; __asm__ volatile("" ::: "memory"); }
        } else {
            for (long i=0; i<count; ++i) { if (flag) break; relax_cpu(); }
        }
        cpu = clock_s(CLOCK_THREAD_CPUTIME_ID) - cpu;
        wall = clock_s(CLOCK_MONOTONIC) - wall;
        printf("{\"iterations\":%ld,\"cpu_s\":%.9f,\"wall_s\":%.9f,\"ns_per_spin\":%.3f}\n", count, cpu, wall, cpu*1e9/count);
        return 0;
    }
    if (argc != 5) { fprintf(stderr, "usage: %s threads duration warmup fps | spin\n", argv[0]); return 2; }
    int threads = atoi(argv[1]), frames = 0, actual = 0, misses = 0;
    double duration = atof(argv[2]), warmup = atof(argv[3]), fps = atof(argv[4]);
    if (threads < 1 || threads > 256 || duration <= 0 || warmup < 0 || fps <= 0) return 2;
    omp_set_dynamic(0);
    double start = clock_s(CLOCK_MONOTONIC);
    for (int n=1; clock_s(CLOCK_MONOTONIC) < start + warmup; ++n) {
        actual = region(threads);
        until(start + n / fps);
    }
    double sleep_cpu=0, sleep_caller=0, sleep_wall=0;
    start = clock_s(CLOCK_MONOTONIC);
    double p0=clock_s(CLOCK_PROCESS_CPUTIME_ID), t0=clock_s(CLOCK_THREAD_CPUTIME_ID);
    while (clock_s(CLOCK_MONOTONIC) < start + duration) {
        actual = region(threads);
        if (actual != threads) { fprintf(stderr, "team mismatch: %d != %d\n", actual, threads); return 3; }
        ++frames;
        double deadline = fmin(start + frames / fps, start + duration);
        double a=clock_s(CLOCK_MONOTONIC), pa=clock_s(CLOCK_PROCESS_CPUTIME_ID), ta=clock_s(CLOCK_THREAD_CPUTIME_ID);
        if (a > deadline) ++misses;
        until(deadline);
        sleep_caller += clock_s(CLOCK_THREAD_CPUTIME_ID) - ta;
        sleep_cpu += clock_s(CLOCK_PROCESS_CPUTIME_ID) - pa;
        sleep_wall += clock_s(CLOCK_MONOTONIC) - a;
    }
    double caller=clock_s(CLOCK_THREAD_CPUTIME_ID)-t0, cpu=clock_s(CLOCK_PROCESS_CPUTIME_ID)-p0, wall=clock_s(CLOCK_MONOTONIC)-start;
    printf("{\"actual_team\":%d,\"frames\":%d,\"deadline_misses\":%d,\"wall_s\":%.9f,\"cpu_s\":%.9f,\"caller_cpu_s\":%.9f,\"worker_cpu_s\":%.9f,\"sleep_cpu_s\":%.9f,\"sleep_worker_cpu_s\":%.9f,\"sleep_wall_s\":%.9f,\"actual_fps\":%.5f}\n", actual, frames, misses, wall, cpu, caller, fmax(0,cpu-caller), sleep_cpu, fmax(0,sleep_cpu-sleep_caller), sleep_wall, frames/wall);
}
