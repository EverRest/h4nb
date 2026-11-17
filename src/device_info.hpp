#pragma once
// Shared GPU identity fields for run_info.txt (issue O9) and MPI rank_table (MPI-M4 item 4).
// Format helpers only. Callers own cudaGetDeviceProperties and error clearing.
#include <cuda_runtime.h>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>

namespace h4nb {
namespace device_info {

inline std::string env_or_empty(const char* key) {
  const char* v = std::getenv(key);
  return v ? v : "";
}

// 32 lowercase hex digits (no dashes). Enough to tell two physical GPUs apart.
inline std::string uuid_hex(const cudaUUID_t& u) {
  char buf[33];
  // bytes is char[16]; cast via unsigned char so values >= 0x80 do not sign-extend.
  for (int i = 0; i < 16; ++i)
    std::snprintf(buf + 2 * i, 3, "%02x", static_cast<unsigned>(static_cast<unsigned char>(u.bytes[i])));
  return std::string(buf, 32);
}

// Domain:bus:device.function, same shape as nvidia-smi PCI strings.
inline std::string pci_id(const cudaDeviceProp& prop) {
  char buf[32];
  std::snprintf(buf, sizeof buf, "%04x:%02x:%02x.0", prop.pciDomainID, prop.pciBusID, prop.pciDeviceID);
  return buf;
}

// Fields after "name=...": cc, sm_count, uuid, pci, mem_bytes, clock_khz. Leading space included.
inline std::string prop_fields(const cudaDeviceProp& prop) {
  return std::string(" name=") + prop.name + " cc=" + std::to_string(prop.major) + "." + std::to_string(prop.minor) +
         " sm_count=" + std::to_string(prop.multiProcessorCount) + " uuid=" + uuid_hex(prop.uuid) +
         " pci=" + pci_id(prop) + " mem_bytes=" + std::to_string(static_cast<unsigned long long>(prop.totalGlobalMem)) +
         " clock_khz=" + std::to_string(prop.clockRate);
}

// One "p2p_i_j: 0|1" line per ordered pair of listed device IDs. Empty when fewer than two devices.
inline std::string p2p_block(const std::vector<int>& devices) {
  if (devices.size() < 2) return "";
  std::string s;
  for (size_t i = 0; i < devices.size(); ++i) {
    for (size_t j = 0; j < devices.size(); ++j) {
      if (i == j) continue;
      int can = 0;
      const cudaError_t e = cudaDeviceCanAccessPeer(&can, devices[i], devices[j]);
      s += "p2p_" + std::to_string(i) + "_" + std::to_string(j) + ": ";
      if (e == cudaSuccess)
        s += can ? "1\n" : "0\n";
      else
        s += std::string("error=") + cudaGetErrorString(e) + "\n";
    }
  }
  return s;
}

}  // namespace device_info
}  // namespace h4nb
