// h4nb::build_info() (task T027, data-model.md section 8, docs/cuda-best-practices.md section 6).
// CMake gives H4NB_GIT_COMMIT, H4NB_BUILD_TYPE and H4NB_CUDA_ARCHITECTURES to this file only.
// The commit is the commit at configure time. A later commit without a new configure step does not change it.
#include <cuda_runtime.h>
#include <string>
#include "h4nb/h4nb.hpp"

#ifndef H4NB_GIT_COMMIT
#define H4NB_GIT_COMMIT "unknown"
#endif
#ifndef H4NB_BUILD_TYPE
#define H4NB_BUILD_TYPE "unknown"
#endif
#ifndef H4NB_CUDA_ARCHITECTURES
#define H4NB_CUDA_ARCHITECTURES "unknown"
#endif

namespace h4nb {
namespace {
// CUDA encodes a version as 1000 * major + 10 * minor.
std::string version_text(int v) { return std::to_string(v / 1000) + "." + std::to_string((v % 1000) / 10); }
}  // namespace

std::string build_info() {
  std::string s;
  s += "h4nb_commit: " H4NB_GIT_COMMIT "\n";
  s += "build_type: " H4NB_BUILD_TYPE "\n";
  s += "cuda_architectures: " H4NB_CUDA_ARCHITECTURES "\n";
  s += "nvcc_version: " + std::to_string(__CUDACC_VER_MAJOR__) + "." + std::to_string(__CUDACC_VER_MINOR__) + "." +
       std::to_string(__CUDACC_VER_BUILD__) + "\n";
  // These calls do not throw. With no driver, the call fails or gives 0. Then the line is "none".
  int v = 0;
  s += "cuda_runtime_version: " + (cudaRuntimeGetVersion(&v) == cudaSuccess && v > 0 ? version_text(v) : "none") + "\n";
  v = 0;
  s += "cuda_driver_version: " + (cudaDriverGetVersion(&v) == cudaSuccess && v > 0 ? version_text(v) : "none") + "\n";
  cudaGetLastError();  // Clear an error of the calls above. The next CUDA call must not see it.
#if defined(__clang__)
  s += "host_compiler: clang " __VERSION__ "\n";
#elif defined(__GNUC__)
  s += "host_compiler: gcc " __VERSION__ "\n";
#else
  s += "host_compiler: " __VERSION__ "\n";
#endif
  return s;
}

}  // namespace h4nb
