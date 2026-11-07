// I/O tests: text IC loader and binary snapshots (layout documented in src/io.cpp). No GPU needed.
#include <cmath>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <stdexcept>
#include <string>
#include "check.hpp"
#include "h4nb/h4nb.hpp"

namespace fs = std::filesystem;

static std::string tmp_path(const char* name) { return (fs::temp_directory_path() / name).string(); }

static void write_file(const std::string& path, const std::string& text) {
  std::ofstream f(path, std::ios::binary);
  f << text;
}

static void test_text_loader() {
  const std::string path = tmp_path("h4nb_test_ic.txt");
  write_file(path,
             "# comment line\n"
             "\n"
             "   # indented comment\n"
             "0 1.0 0 0 0 0 0 0\r\n"
             "  1 0.1 2.5 -1.25 0.5 0.1 0.2 0.3\n");
  const h4nb::Particles p = h4nb::load_text(path);
  CHECK(p.size() == 2);
  CHECK(p.id[0] == 0 && p.id[1] == 1);
  CHECK(p.m[1] == 0.1 && p.x[1] == 2.5 && p.y[1] == -1.25 && p.z[1] == 0.5);
  CHECK(p.vx[1] == 0.1 && p.vy[1] == 0.2 && p.vz[1] == 0.3);
  fs::remove(path);
}

static void test_text_loader_bad_line() {
  const std::string path = tmp_path("h4nb_test_bad.txt");
  write_file(path, "0 1 0 0 0 0 0 0\n1 0.1 2 3\n");  // line 2 has too few fields
  bool threw = false;
  try {
    h4nb::load_text(path);
  } catch (const std::runtime_error& e) {
    threw = std::string(e.what()).find(":2:") != std::string::npos;
  }
  CHECK(threw);
  fs::remove(path);
}

static void test_snapshot_roundtrip() {
  const std::string path = tmp_path("h4nb_test_snap.bin");
  h4nb::Particles p;
  const size_t n = 5;
  p.resize(n);
  for (size_t i = 0; i < n; ++i) {
    p.id[i] = int64_t(i) * 7 - 3;
    p.m[i] = 1.0 / double(i + 3);
    p.x[i] = std::sqrt(2.0) * double(i);
    p.y[i] = -4.9e-324 * double(i + 1);  // denormal: must survive bit for bit
    p.z[i] = 1e300 * double(i);
    p.vx[i] = 1.0 / 3.0;
    p.vy[i] = -0.0;
    p.vz[i] = 0.1 + double(i);
  }
  const double t = 0.123456789012345678;
  h4nb::write_snapshot(path, p, t);

  // Layout: 32-byte header, then 8 arrays of n 8-byte values; file size must match exactly.
  CHECK(fs::file_size(path) == 32 + 8 * n * 8);
  std::ifstream f(path, std::ios::binary);
  char magic[8];
  f.read(magic, 8);
  CHECK(std::memcmp(magic, "H4NBSNAP", 8) == 0);
  uint32_t version = 0;
  f.read(reinterpret_cast<char*>(&version), 4);
  CHECK(version == 1);
  f.seekg(32 + 2 * 8 * n, std::ios::beg);  // array 2 is x: it can be read on its own
  double x1 = 0;
  f.read(reinterpret_cast<char*>(&x1), 8);
  CHECK(x1 == p.x[0]);
  f.close();

  double t_back = 0;
  const h4nb::Particles q = h4nb::read_snapshot(path, &t_back);
  CHECK(t_back == t);
  CHECK(q.size() == n);
  CHECK(q.id == p.id && q.m == p.m && q.x == p.x && q.y == p.y && q.z == p.z);
  CHECK(q.vx == p.vx && q.vz == p.vz);
  CHECK(std::signbit(q.vy[0]));  // -0.0 keeps its sign
  fs::remove(path);
}

static void test_snapshot_rejects_bad_files() {
  const std::string path = tmp_path("h4nb_test_bad.bin");
  write_file(path, std::string(40, 'x'));
  bool threw = false;
  try {
    h4nb::read_snapshot(path);
  } catch (const std::runtime_error&) {
    threw = true;
  }
  CHECK(threw);

  // Valid file, cut short: must be reported as truncated.
  h4nb::Particles p;
  p.resize(3);
  h4nb::write_snapshot(path, p, 0.0);
  fs::resize_file(path, fs::file_size(path) - 8);
  threw = false;
  try {
    h4nb::read_snapshot(path);
  } catch (const std::runtime_error&) {
    threw = true;
  }
  CHECK(threw);
  fs::remove(path);
}

// True when read_snapshot throws std::runtime_error. Any other exception counts as a failure.
static bool read_snapshot_throws(const std::string& path) {
  try {
    h4nb::read_snapshot(path);
  } catch (const std::runtime_error&) {
    return true;
  } catch (...) {
    return false;
  }
  return false;
}

// Write a 32-byte v1 header with the given n, then "body_bytes" zero bytes.
static void write_raw_snapshot(const std::string& path, uint64_t n, size_t body_bytes) {
  std::ofstream f(path, std::ios::binary);
  f.write("H4NBSNAP", 8);
  const uint32_t version = 1, reserved = 0;
  const double time = 0.0;
  f.write(reinterpret_cast<const char*>(&version), 4);
  f.write(reinterpret_cast<const char*>(&reserved), 4);
  f.write(reinterpret_cast<const char*>(&n), 8);
  f.write(reinterpret_cast<const char*>(&time), 8);
  const std::string zeros(body_bytes, '\0');
  f.write(zeros.data(), std::streamsize(zeros.size()));
}

static void test_snapshot_header_n_larger_than_file() {
  const std::string path = tmp_path("h4nb_test_bign.bin");
  write_raw_snapshot(path, 10, 3 * 64);  // header says 10, the body has room for 3
  CHECK(read_snapshot_throws(path));
  fs::remove(path);
}

static void test_snapshot_trailing_bytes() {
  const std::string path = tmp_path("h4nb_test_trail.bin");
  h4nb::Particles p;
  p.resize(3);
  for (size_t i = 0; i < 3; ++i) { p.id[i] = int64_t(i); p.m[i] = 1.0; }
  h4nb::write_snapshot(path, p, 0.0);
  {
    std::ofstream f(path, std::ios::binary | std::ios::app);
    f.write("tail", 4);
  }
  CHECK(read_snapshot_throws(path));
  fs::remove(path);
}

static void test_snapshot_huge_n() {
  const std::string path = tmp_path("h4nb_test_hugen.bin");
  write_raw_snapshot(path, uint64_t(1) << 61, 0);
  CHECK(read_snapshot_throws(path));
  fs::remove(path);
}

static void test_text_loader_fractional_id() {
  const std::string path = tmp_path("h4nb_test_frac.txt");
  write_file(path, "0 1 0 0 0 0 0 0\n1.5 1 0 0 1 0 0\n");  // the ID "1.5" must not shift the fields
  bool threw = false;
  try {
    h4nb::load_text(path);
  } catch (const std::runtime_error&) {
    threw = true;
  }
  CHECK(threw);
  fs::remove(path);
}

int main() {
  test_text_loader();
  test_text_loader_bad_line();
  test_snapshot_roundtrip();
  test_snapshot_rejects_bad_files();
  test_snapshot_header_n_larger_than_file();
  test_snapshot_trailing_bytes();
  test_snapshot_huge_n();
  test_text_loader_fractional_id();
  std::puts("test_io: OK");
  return 0;
}
