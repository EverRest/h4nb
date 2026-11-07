#pragma once
// run_info.txt of the h4nb tools (task T028, data-model.md section 8, docs/cuda-best-practices.md section 6).
// write_run_info() writes "key: value" lines. It does not throw for a CUDA error. It writes the error text instead.
// Thus a tool can call it before the Simulation constructor, also on a machine without a GPU.
// It throws std::runtime_error only when it cannot write the file.
// Several ranks (MPI): the tool calls h4nb::rank_table() on all ranks, and only rank 0 calls write_run_info() with
// its result in rank_lines. The device_<k> lines are then not written, because a rank ignores the devices key.
#include <cuda_runtime.h>
#include <unistd.h>
#include <cstdio>
#include <ctime>
#include <stdexcept>
#include <string>
#include <vector>
#include "h4nb/h4nb.hpp"

inline void write_run_info(const std::string& path, const std::string& tool, const std::vector<int>& devices, int argc,
                           char** argv, const std::string& rank_lines = "") {
  std::string s = "tool: " + tool + "\n" + h4nb::build_info();
  const int nranks = h4nb::ranks();
  for (size_t k = 0; nranks == 1 && k < devices.size(); ++k) {
    const std::string key = "device_" + std::to_string(k) + ": ";
    cudaDeviceProp prop{};
    const cudaError_t e = cudaGetDeviceProperties(&prop, devices[k]);
    if (e == cudaSuccess)
      s += key + "id=" + std::to_string(devices[k]) + " name=" + prop.name + " cc=" + std::to_string(prop.major) + "." +
           std::to_string(prop.minor) + "\n";
    else
      s += key + "id=" + std::to_string(devices[k]) + " error=" + cudaGetErrorString(e) + "\n";
  }
  cudaGetLastError();  // Clear the error. The Simulation constructor must not see it.
  s += "ranks: " + std::to_string(nranks) + "\n";
  s += rank_lines;  // Several ranks: "mpi_library: ..." and one "rank_<r>: host=... device=..." line for each rank.
  char host[256] = "unknown";
  if (gethostname(host, sizeof host) != 0) std::snprintf(host, sizeof host, "unknown");
  host[sizeof host - 1] = '\0';
  s += std::string("host: ") + host + "\n";
  char when[32] = "unknown";
  const std::time_t now = std::time(nullptr);
  std::tm utc{};
  if (gmtime_r(&now, &utc)) std::strftime(when, sizeof when, "%Y-%m-%dT%H:%M:%SZ", &utc);
  s += std::string("start_utc: ") + when + "\n";
  s += "command:";
  for (int i = 0; i < argc; ++i) s += std::string(" ") + argv[i];
  s += "\n";
  FILE* f = std::fopen(path.c_str(), "w");
  if (!f) throw std::runtime_error("cannot write " + path);
  const bool ok = std::fputs(s.c_str(), f) >= 0;
  if (std::fclose(f) != 0 || !ok) throw std::runtime_error("cannot write " + path);
}
