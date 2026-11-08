// Run settings parser (tools/settings.hpp): sources, precedence, presets and the main errors. No GPU needed.
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <string>
#include <vector>
#include "check.hpp"
#include "settings.hpp"

namespace fs = std::filesystem;

// A unique env prefix, so the test does not read the H4NB_ variables of the shell.
static const char* const kPrefix = "H4NBTEST_";

static std::string tmp_path(const char* name) { return (fs::temp_directory_path() / name).string(); }

// Calls parse() with the "key=value" arguments.
static void parse_args(Settings& s, std::vector<std::string> args) {
  std::vector<char*> argv{const_cast<char*>("tool")};
  for (std::string& a : args) argv.push_back(a.data());
  s.parse(int(argv.size()), argv.data(), kPrefix);
}

// True when f throws a SettingsError.
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

// A tool with one key of each type.
static void declare_keys(Settings& s) {
  s.add("eta", Setting::Real, "0.01", "Accuracy.", Range::gt(0));
  s.add("n", Setting::Int, "4", "Count.", Range::between(1, 16));
  s.add("on", Setting::Bool, "0", "Flag.");
  s.add("devs", Setting::IntList, "0", "Devices.", Range::ge(0));
  s.add("name", Setting::String, "run", "Name.");
  s.add("mode", Setting::Enum, "block", "Mode.", Range::one_of({"block", "fixed"}));
  s.add("dt", Setting::Real, "0.5", "Power of two.", Range::gt(0).power_of_two());
}

static void test_defaults() {
  Settings s;
  declare_keys(s);
  parse_args(s, {});
  CHECK(s.real("eta") == 0.01);
  CHECK(s.integer("n") == 4);
  CHECK(!s.boolean("on"));
  CHECK(s.ints("devs") == std::vector<int>{0});
  CHECK(s.str("name") == "run" && s.str("mode") == "block");
  CHECK(s.source("eta") == "default" && !s.is_set("eta"));
}

// Command line values replace the defaults.
static void test_cli() {
  Settings s;
  declare_keys(s);
  parse_args(s, {"eta=0.02", "n=8", "on=1", "devs=0,1", "mode=fixed", "name=run one"});
  CHECK(s.real("eta") == 0.02);
  CHECK(s.integer("n") == 8);
  CHECK(s.boolean("on"));
  CHECK(s.ints("devs") == (std::vector<int>{0, 1}));
  CHECK(s.str("mode") == "fixed" && s.str("name") == "run one");
  CHECK(s.source("n") == "cli" && s.user_set("n"));
}

// The environment is read for declared keys. The command line replaces it.
static void test_env_and_precedence() {
  setenv("H4NBTEST_N", "3", 1);
  Settings s;
  declare_keys(s);
  parse_args(s, {});
  CHECK(s.integer("n") == 3 && s.source("n") == "env");
  parse_args(s, {"n=5"});
  CHECK(s.integer("n") == 5 && s.source("n") == "cli");
  unsetenv("H4NBTEST_N");
}

// The config file gives values. The command line replaces a value of the file.
static void test_config_file() {
  const std::string path = tmp_path("h4nb_test_settings.cfg");
  {
    std::ofstream f(path);
    f << "eta=0.5\n# a comment line\nn=2 # trailing comment\n";
  }
  Settings s;
  declare_keys(s);
  parse_args(s, {"config=" + path});
  CHECK(s.real("eta") == 0.5 && s.integer("n") == 2);
  CHECK(s.source("eta") == "file:" + path + ":1");
  CHECK(s.config_path() == path);
  parse_args(s, {"config=" + path, "eta=0.7"});
  CHECK(s.real("eta") == 0.7 && s.source("eta") == "cli");
  std::remove(path.c_str());
}

// Presets set the keys of the tool. A user value replaces the preset.
static void test_preset() {
  Settings s;
  s.add("eps", Setting::Real, "0", "Softening.", Range::ge(0));
  s.add_preset();
  parse_args(s, {"preset=stellar"});
  CHECK(s.real("eps") == 0.0001);
  CHECK(s.source("eps") == "preset:stellar" && s.is_set("eps") && !s.user_set("eps"));
  parse_args(s, {"preset=stellar", "eps=0.5"});
  CHECK(s.real("eps") == 0.5 && s.user_set("eps"));
}

// The main errors: each must throw SettingsError.
static void test_errors() {
  Settings s;
  declare_keys(s);
  CHECK(throws_settings([&] { parse_args(s, {"nosuch=1"}); }));  // unknown key on the command line
  CHECK(throws_settings([&] { parse_args(s, {"eta=-1"}); }));    // out of range
  CHECK(throws_settings([&] { parse_args(s, {"n=17"}); }));      // above the range
  CHECK(throws_settings([&] { parse_args(s, {"n=4x"}); }));      // not a whole number
  CHECK(throws_settings([&] { parse_args(s, {"eta=nan"}); }));   // not finite
  CHECK(throws_settings([&] { parse_args(s, {"on=yes"}); }));    // not a bool
  CHECK(throws_settings([&] { parse_args(s, {"mode=other"}); }));  // not an enum value
  CHECK(throws_settings([&] { parse_args(s, {"dt=0.3"}); }));      // not a power of two
  CHECK(throws_settings([&] { parse_args(s, {"noequals"}); }));     // no '='
  CHECK(throws_settings([&] { parse_args(s, {"=5"}); }));          // empty key

  // A key that is not in the file is an error. So is a repeated key in the file.
  const std::string path = tmp_path("h4nb_test_settings_bad.cfg");
  {
    std::ofstream f(path);
    f << "eta=0.5\nnosuch=1\n";
  }
  CHECK(throws_settings([&] { parse_args(s, {"config=" + path}); }));
  {
    std::ofstream f(path);
    f << "eta=0.5\neta=0.6\n";
  }
  CHECK(throws_settings([&] { parse_args(s, {"config=" + path}); }));
  std::remove(path.c_str());

  // A required key with no value is an error.
  Settings r;
  r.add("ic", Setting::String, "", "Input.").required = true;
  CHECK(throws_settings([&] { parse_args(r, {}); }));
  parse_args(r, {"ic=a.txt"});
  CHECK(r.str("ic") == "a.txt");
}

int main() {
  test_defaults();
  test_cli();
  test_env_and_precedence();
  test_config_file();
  test_preset();
  test_errors();
  std::puts("test_settings: OK");
  return 0;
}
