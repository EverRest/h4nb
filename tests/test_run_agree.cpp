// Checks of the input fingerprint of h4nb_run (MPI-H1). The test includes the tool's source with its main renamed.
// Build with -I tools -I include. Run without MPI: the agreement is then the identity.
#define main h4nb_run_main
#include "h4nb_run.cpp"
#undef main

#include <cstdio>
#include <cstdlib>

static int failures = 0;
#define CHECK(c)                                                       \
  do {                                                                 \
    if (!(c)) {                                                        \
      std::fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); \
      ++failures;                                                      \
    }                                                                  \
  } while (0)

// Parses the arguments as h4nb_run does, and returns the fingerprint entries.
static std::vector<InputEntry> entries_of(std::vector<std::string> args) {
  args.insert(args.begin(), "h4nb_run");
  std::vector<char*> argv;
  for (std::string& a : args) argv.push_back(&a[0]);
  argv.push_back(nullptr);
  Settings s;
  declare(s);
  s.parse(int(args.size()), argv.data());
  return input_entries(s, s.help());
}

static uint64_t digest_of(const std::vector<std::string>& args) { return entries_digest(entries_of(args)); }

// True when the settings parser accepts the arguments.
static bool accepts(const std::vector<std::string>& args) {
  try {
    entries_of(args);
    return true;
  } catch (const SettingsError&) {
    return false;
  }
}

static void write_file(const char* path, const char* text) {
  FILE* f = std::fopen(path, "wb");
  std::fputs(text, f);
  std::fclose(f);
}

int main() {
  // FNV-1a 64-bit test vectors.
  CHECK(fnv1a("", 0) == 0xcbf29ce484222325ULL);
  CHECK(fnv1a("a", 1) == 0xaf63dc4c8601ec8cULL);

  const char* ic = "test_run_agree.ic";
  write_file(ic, "0 1 0 0 0 0 0 0\n1 1e-3 1 0 0 0 1 0\n");
  const std::string icarg = std::string("ic=") + ic;

  // The order of the arguments does not change the digest.
  CHECK(digest_of({icarg, "out=o", "t_end=1"}) == digest_of({"out=o", "t_end=1", icarg}));

  // A value from the environment and the same value from the command line give the same digest.
  setenv("H4NB_ETA", "0.02", 1);
  const uint64_t env_digest = digest_of({icarg, "out=o", "t_end=1"});
  unsetenv("H4NB_ETA");
  CHECK(env_digest == digest_of({icarg, "out=o", "t_end=1", "eta=0.02"}));

  // Real values are compared as numbers, not as text.
  CHECK(digest_of({icarg, "out=o", "t_end=1", "dt_max=0.015625"}) ==
        digest_of({icarg, "out=o", "t_end=1", "dt_max=1.5625e-2"}));

  // A different setting or a different input byte changes the digest.
  CHECK(digest_of({icarg, "out=o", "t_end=1", "eta=0.01"}) != digest_of({icarg, "out=o", "t_end=1", "eta=0.02"}));
  write_file(ic, "0 1 0 0 0 0 0 0\n1 1e-3 1 0 0 0 1 1\n");
  CHECK(digest_of({icarg, "out=o", "t_end=1"}) != env_digest);

  // help=1 needs no input file. Its entry for the input is "-", and the help flag is in the digest.
  const std::vector<InputEntry> h = entries_of({"help=1"});
  bool has_help = false, has_ic_dash = false;
  for (const InputEntry& e : h) {
    if (e.name == "help" && e.text == "1") has_help = true;
    if (e.name == "ic bytes" && e.text == "-") has_ic_dash = true;
  }
  CHECK(has_help);
  CHECK(has_ic_dash);
  CHECK(digest_of({"help=1"}) != digest_of({"help=0", icarg, "out=o", "t_end=1"}));

  // An input file that cannot be read gives a fixed text. The error comes later from load_input().
  CHECK(digest_of({"ic=/nonexistent/h4nb.txt", "out=o", "t_end=1"}) != digest_of({icarg, "out=o", "t_end=1"}));

  // The generic error of a rank without its own error is recognized (MPI-H2). Other errors are local.
  CHECK(remote_setup_error(
      std::runtime_error("Simulation: the setup failed on another rank. See the message of that rank.")));
  CHECK(!remote_setup_error(SettingsError("devices must not be empty")));

  // With one rank, the agreement is the identity.
  CHECK(same_on_all(12345));

  // The rank's out directory is not in the fingerprint (MPI-L: only rank 0 writes files).
  CHECK(digest_of({icarg, "out=a", "t_end=1"}) == digest_of({icarg, "out=b", "t_end=1"}));

  // eta_init = 0 is valid: it means "use eta" (library review item 1). Negative values are not.
  CHECK(accepts({icarg, "out=o", "t_end=1", "eta_init=0"}));
  CHECK(!accepts({icarg, "out=o", "t_end=1", "eta_init=-1"}));

  // A NaN relative error fails the energy verdict. std::max would drop it (review D8).
  PeriodTracker tracker(1.0);
  tracker.add(0.25, 1e-12);
  tracker.add(0.75, NAN);
  tracker.finish(1.0);
  const std::string verdict = tracker.verdict(1e-8, "test", 0, 1.0);
  CHECK(verdict.rfind("energy verdict: FAIL", 0) == 0);

  std::remove(ic);
  if (failures) {
    std::fprintf(stderr, "test_run_agree: %d failure(s)\n", failures);
    return 1;
  }
  std::printf("test_run_agree: all checks passed\n");
  return 0;
}
