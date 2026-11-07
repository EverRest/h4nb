// Input error tests (issue D2). load_input and make_simulation throw SettingsError. settings_main_error gives 2.
// No GPU needed: the config checks run before the first CUDA call.
#include <filesystem>
#include <fstream>
#include <stdexcept>
#include <string>
#include "check.hpp"
#include "h4nb/h4nb.hpp"
#include "input.hpp"
#include "settings.hpp"

namespace fs = std::filesystem;

static std::string tmp_path(const char* name) { return (fs::temp_directory_path() / name).string(); }

static void write_file(const std::string& path, const std::string& text) {
  std::ofstream f(path, std::ios::binary);
  f << text;
}

// Returns true when f throws a SettingsError.
template <class F>
static bool throws_settings(F f) {
  try {
    f();
  } catch (const SettingsError&) {
    return true;
  } catch (...) {
    return false;
  }
  return false;
}

static void test_load_input_errors() {
  const std::string dup = tmp_path("h4nb_test_dup.txt");
  write_file(dup, "0 1 0 0 0 0 0 0\n0 0.1 1 0 0 0 0 1\n");  // repeated ID 0
  CHECK(throws_settings([&] { load_input(dup); }));
  fs::remove(dup);

  const std::string ok = tmp_path("h4nb_test_ok.txt");
  write_file(ok, "0 1 0 0 0 0 0 0\n1 0.1 1 0 0 0 0 1\n");
  const h4nb::Particles p = h4nb::load_text(ok);
  fs::remove(ok);

  const std::string snap = tmp_path("h4nb_test_trunc.snap");
  h4nb::write_snapshot(snap, p, 0.0);
  fs::resize_file(snap, fs::file_size(snap) / 2);  // truncated snapshot
  CHECK(throws_settings([&] { load_input(snap); }));
  fs::remove(snap);

  CHECK(throws_settings([&] { load_input("/nonexistent_h4nb_dir/ic.txt"); }));  // missing file
}

static void test_make_simulation_config() {
  const std::string ok = tmp_path("h4nb_test_sim.txt");
  write_file(ok, "0 1 0 0 0 0 0 0\n1 0.1 1 0 0 0 0 1\n");
  const h4nb::Particles p = h4nb::load_text(ok);
  fs::remove(ok);

  h4nb::Config c;
  c.G = -1;  // invalid: validate() throws std::invalid_argument before any CUDA call
  CHECK(throws_settings([&] { make_simulation(p, c); }));
}

static void test_exit_code() {
  CHECK(settings_main_error("test", SettingsError("bad key")) == 2);
  CHECK(settings_main_error("test", std::runtime_error("no CUDA device")) == 1);
}

int main() {
  test_load_input_errors();
  test_make_simulation_config();
  test_exit_code();
  std::printf("test_input: all checks passed\n");
  return 0;
}
