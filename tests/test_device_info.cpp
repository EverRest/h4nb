// CPU checks for device_info formatters (issue O9). No GPU call.
#include <cstdio>
#include <cstring>
#include <string>
#include "device_info.hpp"

#define CHECK(c)                                                                                             \
  do {                                                                                                       \
    if (!(c)) {                                                                                              \
      std::fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #c);                                      \
      return 1;                                                                                              \
    }                                                                                                        \
  } while (0)

int main() {
  cudaUUID_t u{};
  for (int i = 0; i < 16; ++i) u.bytes[i] = static_cast<char>(i);
  CHECK(h4nb::device_info::uuid_hex(u) == "000102030405060708090a0b0c0d0e0f");
  // High-bit bytes must not sign-extend through char (e.g. 0xab -> "ab", not "ff").
  cudaUUID_t hi = u;
  hi.bytes[0] = static_cast<char>(0xab);
  hi.bytes[15] = static_cast<char>(0xff);
  CHECK(h4nb::device_info::uuid_hex(hi) == "ab0102030405060708090a0b0c0d0eff");

  cudaDeviceProp prop{};
  std::memset(&prop, 0, sizeof prop);
  std::snprintf(prop.name, sizeof prop.name, "FakeGPU");
  prop.major = 8;
  prop.minor = 9;
  prop.multiProcessorCount = 60;
  prop.pciDomainID = 0;
  prop.pciBusID = 1;
  prop.pciDeviceID = 0;
  prop.totalGlobalMem = 12ull << 30;
  prop.clockRate = 2100000;
  prop.uuid = u;

  CHECK(h4nb::device_info::pci_id(prop) == "0000:01:00.0");
  const std::string f = h4nb::device_info::prop_fields(prop);
  CHECK(f.find(" name=FakeGPU") != std::string::npos);
  CHECK(f.find(" cc=8.9") != std::string::npos);
  CHECK(f.find(" sm_count=60") != std::string::npos);
  CHECK(f.find(" uuid=000102030405060708090a0b0c0d0e0f") != std::string::npos);
  CHECK(f.find(" pci=0000:01:00.0") != std::string::npos);
  CHECK(f.find(" mem_bytes=") != std::string::npos);
  CHECK(f.find(" clock_khz=2100000") != std::string::npos);

  CHECK(h4nb::device_info::p2p_block({}).empty());
  CHECK(h4nb::device_info::p2p_block({0}).empty());
  return 0;
}
