// Atomic publish test: a failed snapshot write must not touch the file that is already at the path.
// It needs /dev/full (Linux). On other systems the test is skipped. No GPU needed.
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <stdexcept>
#include <string>
#include "check.hpp"
#include "h4nb/h4nb.hpp"

namespace fs = std::filesystem;

static std::string read_bytes(const std::string& path) {
  std::ifstream f(path, std::ios::binary);
  return std::string(std::istreambuf_iterator<char>(f), std::istreambuf_iterator<char>());
}

static void test_failed_write_keeps_old_snapshot() {
  const fs::path dir = fs::temp_directory_path() / "h4nb_test_atomic";
  fs::remove_all(dir);
  fs::create_directories(dir);
  const std::string path = (dir / "out.snap").string();

  // An old snapshot is at the path.
  h4nb::Particles old;
  old.resize(2);
  old.id[0] = 0; old.id[1] = 1;
  h4nb::write_snapshot(path, old, 1.0);
  const std::string before = read_bytes(path);
  CHECK(!before.empty());

  // The temporary name is a link to a device that is always full. The write must fail.
  fs::create_symlink("/dev/full", dir / "out.snap.tmp");

  h4nb::Particles fresh;
  fresh.resize(3);
  fresh.id[0] = 7; fresh.id[1] = 8; fresh.id[2] = 9;
  bool threw = false;
  try {
    h4nb::write_snapshot(path, fresh, 2.0);
  } catch (const std::runtime_error&) {
    threw = true;
  }
  CHECK(threw);
  CHECK(read_bytes(path) == before);  // The old file is unchanged.

  fs::remove_all(dir);
}

int main() {
  // Exit code 77 tells CTest that the test is skipped. It needs SKIP_RETURN_CODE 77 (see CMakeLists.txt).
  if (!fs::exists("/dev/full")) {
    std::puts("test_io_atomic: /dev/full not found, skipped");
    return 77;
  }
  test_failed_write_keeps_old_snapshot();
  std::puts("test_io_atomic: OK");
  return 0;
}
