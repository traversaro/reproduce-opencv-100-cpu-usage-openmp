#!/usr/bin/env bash
set -euo pipefail

parallel_args=(-DWITH_OPENMP=OFF -DWITH_TBB=OFF -DWITH_PTHREADS_PF=OFF)
case "$OPENCV_PARALLEL" in
  pthreads) parallel_args+=(-DWITH_PTHREADS_PF=ON) ;;
  openmp) parallel_args+=(-DWITH_OPENMP=ON) ;;
  tbb) parallel_args+=(-DWITH_TBB=ON) ;;
  serial) ;;
  *) echo "Unknown OPENCV_PARALLEL: $OPENCV_PARALLEL" >&2; exit 1 ;;
esac

cmake -S . -B build -G Ninja \
  ${CMAKE_ARGS:-} \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="$PREFIX" \
  -DCMAKE_INSTALL_LIBDIR=lib \
  -DCMAKE_EXPORT_COMPILE_COMMANDS=ON \
  -DBUILD_LIST=core,imgproc,python3 \
  -DBUILD_SHARED_LIBS=ON \
  -DBUILD_TESTS=OFF -DBUILD_PERF_TESTS=OFF -DBUILD_EXAMPLES=OFF \
  -DBUILD_DOCS=OFF -DBUILD_JAVA=OFF -DBUILD_opencv_apps=OFF \
  -DBUILD_opencv_python2=OFF -DBUILD_opencv_python3=ON \
  -DPYTHON3_EXECUTABLE="$PYTHON" \
  -DPYTHON3_INCLUDE_DIR="$("$PYTHON" -c 'import sysconfig; print(sysconfig.get_path("include"))')" \
  -DPYTHON3_NUMPY_INCLUDE_DIRS="$("$PYTHON" -c 'import numpy; print(numpy.get_include())')" \
  -DPYTHON3_PACKAGES_PATH="$SP_DIR" \
  -DPYTHON3_LIBRARY="$PREFIX/lib/libpython3.11.so" \
  -DOPENCV_PYTHON3_INSTALL_PATH="$SP_DIR" \
  -DWITH_IPP=OFF -DWITH_ITT=OFF -DWITH_LAPACK=OFF -DWITH_EIGEN=OFF \
  -DWITH_OPENCL=OFF -DWITH_OPENVINO=OFF -DWITH_CUDA=OFF \
  -DWITH_PROTOBUF=OFF -DWITH_ADE=OFF -DWITH_FFMPEG=OFF \
  -DWITH_GSTREAMER=OFF -DWITH_GTK=OFF -DWITH_QT=OFF \
  -DWITH_KLEIDICV=OFF -DWITH_CAROTENE=OFF \
  -DOPENCV_ENABLE_NONFREE=OFF -DOPENCV_DOWNLOAD_DISABLED=ON \
  "${parallel_args[@]}"

# Bound compiler memory usage on both local machines and hosted runners.
build_jobs="${CPU_COUNT:-2}"
if (( build_jobs > 4 )); then build_jobs=4; fi
cmake --build build --parallel "$build_jobs"
cmake --install build

# Make configuration evidence part of the package and CI output.
evidence="$PREFIX/share/opencv-source-build"
mkdir -p "$evidence"
cp build/CMakeCache.txt "$evidence/CMakeCache.txt"
"$PYTHON" - "$OPENCV_PARALLEL" "$evidence/build.json" <<'PY'
import hashlib, json, pathlib, subprocess, sys
backend, output = sys.argv[1:]
cache = {}
for line in pathlib.Path('build/CMakeCache.txt').read_text().splitlines():
    if line and not line.startswith(('#', '//')) and ':' in line and '=' in line:
        key, value = line.split('=', 1)
        cache[key.split(':', 1)[0]] = value
keys = ('BUILD_LIST', 'CMAKE_BUILD_TYPE', 'WITH_IPP', 'WITH_ITT', 'WITH_LAPACK',
        'WITH_EIGEN', 'WITH_OPENCL', 'WITH_OPENVINO', 'WITH_CUDA', 'WITH_PROTOBUF',
        'WITH_ADE', 'WITH_FFMPEG', 'WITH_GSTREAMER', 'WITH_GTK', 'WITH_QT',
        'WITH_KLEIDICV', 'WITH_CAROTENE', 'WITH_OPENMP', 'WITH_TBB', 'WITH_PTHREADS_PF')
data = {'backend': backend, 'opencv_version': '4.13.0',
        'source_sha256': '1d40ca017ea51c533cf9fd5cbde5b5fe7ae248291ddf2af99d4c17cf8e13017d',
        'cmake': {k: cache.get(k) for k in keys},
        'compiler': subprocess.check_output([cache['CMAKE_CXX_COMPILER'], '--version'], text=True)}
pathlib.Path(output).write_text(json.dumps(data, indent=2) + '\n')
PY
