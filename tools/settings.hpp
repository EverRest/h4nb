#pragma once
// Run settings of the h4nb tools (contracts/run-config.md, data-model.md section 5).
// A tool declares its keys with add(). Then it calls parse(). Then it reads the values with the typed getters.
// The sources apply in this order: default, preset, config file, environment, command line.
// A later source replaces the value of an earlier source.
// Each error is a SettingsError. Its message names the key, the value and the source.
// The tool catches it and returns settings_main_error(), which gives the exit code 2.
//
// Usage:
//   Settings s;
//   s.add_preset();
//   s.add("eta", Setting::Real, "0.01", "Aarseth accuracy parameter.", Range::gt(0));
//   s.add("ic", Setting::String, "", "Initial conditions.").required = true;
//   s.parse(argc, argv);
//   if (s.help()) { s.print_help(stdout, "h4nb_run"); return 0; }
//   const double eta = s.real("eta");
#include <cerrno>
#include <climits>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <ctime>
#include <deque>
#include <fstream>
#include <initializer_list>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

// A bad key, value or file in the run settings. The tool exits with code 2.
struct SettingsError : std::runtime_error {
  using std::runtime_error::runtime_error;
};

// The allowed values of a key. For a list, the range applies to each element.
struct Range {
  double lo = -HUGE_VAL, hi = HUGE_VAL;
  bool lo_open = false, hi_open = false;
  std::vector<std::string> allowed;  // Enum values, or the only allowed numbers (example: tile).
  std::vector<double> also;          // Numbers that are valid outside [lo, hi] (example: r_close=-1).
  bool pow2 = false;                 // The number must be a power of two.
  size_t count = 0;                  // A list must have this number of elements. 0: any number.

  static Range ge(double x) { Range r; r.lo = x; return r; }
  static Range gt(double x) { Range r; r.lo = x; r.lo_open = true; return r; }
  static Range between(double a, double b) { Range r; r.lo = a; r.hi = b; return r; }
  static Range one_of(std::initializer_list<const char*> v) { Range r; r.allowed.assign(v.begin(), v.end()); return r; }
  Range& or_value(double x) { also.push_back(x); return *this; }
  Range& power_of_two() { pow2 = true; return *this; }
  Range& size(size_t n) { count = n; return *this; }
};

// One key: its declaration, its final value and the source of that value.
struct Setting {
  enum Type { Real, Int, Bool, String, IntList, RealList, Enum };
  std::string name;
  Type type = String;
  std::string def;     // Default text. Empty: the key has no value until a source sets it.
  std::string help;    // One line of help text.
  Range range;
  bool required = false;  // parse() fails when no source sets the key.
  std::string value;   // Final value text.
  std::string source;  // "default", "preset:<name>", "file:<path>:<line>", "env" or "cli".
};

// True when v is an integer multiple of step. The tolerance is the same as in Simulation::advance_to.
inline bool is_multiple(double v, double step) {
  const double q = v / step, r = std::nearbyint(q);
  return std::fabs(q - r) <= 1e-9 * std::fmax(1.0, std::fabs(q));
}

// Prints the error of a tool. Returns 2 for a SettingsError and 1 for all other errors.
inline int settings_main_error(const char* tool, const std::exception& e) {
  std::fprintf(stderr, "%s: error: %s\n", tool, e.what());
  return dynamic_cast<const SettingsError*>(&e) ? 2 : 1;
}

class Settings {
 public:
  // The presets (contracts/run-config.md section 4). A preset sets only the keys that the tool declares.
  static const std::vector<std::pair<std::string, std::vector<std::pair<std::string, std::string>>>>& presets() {
    static const std::vector<std::pair<std::string, std::vector<std::pair<std::string, std::string>>>> p = {
        {"none", {{"eps", "0"}}}, {"agn", {{"eps", "0.01"}}}, {"stellar", {{"eps", "0.0001"}}}};
    return p;
  }

  // Declares a key. The tool calls it for each key that it uses, before parse().
  // An invalid declaration is a bug in the tool: it throws std::logic_error.
  Setting& add(const std::string& name, Setting::Type type, const std::string& def, const std::string& help,
               const Range& range = Range()) {
    if (name.empty() || name == "config" || name == "help" || find(name))
      throw std::logic_error("settings: bad or repeated key '" + name + "'");
    Setting s;
    s.name = name, s.type = type, s.def = def, s.help = help, s.range = range;
    s.value = def, s.source = "default";
    if (!def.empty()) s.value = check(s, def, "default");
    keys_.push_back(s);
    return keys_.back();
  }

  // Declares the key "preset" with the names of the built-in presets.
  Setting& add_preset() {
    Range r;
    for (const auto& p : presets()) r.allowed.push_back(p.first);
    return add("preset", Setting::Enum, "none", "Preset of defaults (none: eps=0, agn: eps=0.01, stellar: eps=0.0001).", r);
  }

  // Reads all sources and sets the final values. The built-in keys are config=<file> and help=1.
  // The environment gives env_prefix + the key in upper case, for example H4NB_ETA.
  // The tool ignores an environment variable for a key that it does not declare, because one
  // environment serves several tools. An unknown key on the command line or in a file is an error.
  void parse(int argc, char** argv, const std::string& env_prefix = "H4NB_") {
    std::vector<Item> cli, env, file;
    for (int i = 1; i < argc; ++i) {
      const std::string a = argv[i];
      const size_t e = a.find('=');
      if (e == std::string::npos || e == 0) throw SettingsError(a + " (cli): expected key=value");
      cli.push_back({a.substr(0, e), a.substr(e + 1), "cli"});
    }
    std::vector<std::string> env_keys = {"config"};
    for (const Setting& s : keys_) env_keys.push_back(s.name);
    for (const std::string& k : env_keys) {
      std::string var = env_prefix;
      for (char c : k) var += char(c >= 'a' && c <= 'z' ? c - 'a' + 'A' : c);
      if (const char* v = std::getenv(var.c_str())) env.push_back({k, v, "env"});
    }
    const Item* cfg = nullptr;
    for (const Item& it : env) if (it.key == "config") cfg = &it;
    for (const Item& it : cli) if (it.key == "config") cfg = &it;
    if (cfg) {
      if (cfg->value.empty()) throw SettingsError("config= (" + cfg->source + "): empty file name");
      config_ = cfg->value;
      file = read_file(*cfg);
    }
    help_ = false;
    for (Item& it : cli) {
      if (it.key == "help") help_ = to_bool(it, it.value);
      else if (it.key != "config" && !find(it.key)) fail(it, "unknown key");
    }
    for (const Item& it : file)
      if (!find(it.key)) fail(it, "unknown key");
    for (Setting& s : keys_) s.value = s.def, s.source = "default";
    // The preset applies first. Its name comes from the source with the highest priority.
    if (Setting* p = find("preset")) {
      std::string name = p->def;
      for (const std::vector<Item>* layer : {&file, &env, &cli})
        for (const Item& it : *layer)
          if (it.key == "preset") name = check(*p, it.value, it.source);
      for (const auto& pr : presets())
        if (pr.first == name)
          for (const auto& kv : pr.second)
            if (Setting* s = find(kv.first)) set(*s, kv.second, "preset:" + name);
    }
    for (const std::vector<Item>* layer : {&file, &env, &cli})
      for (const Item& it : *layer)
        if (Setting* s = find(it.key)) set(*s, it.value, it.source);
    if (!help_)
      for (const Setting& s : keys_)
        if (s.required && s.value.empty()) throw SettingsError(s.name + " (" + s.source + "): required key has no value");
  }

  bool help() const { return help_; }
  const std::string& config_path() const { return config_; }  // Empty when no config file was read.

  // Typed getters. A key without a value or a key of another type is a bug in the tool (std::logic_error).
  double real(const std::string& k) const { return to_real(need(k, Setting::Real)); }
  int integer(const std::string& k) const { return to_int(need(k, Setting::Int)); }
  bool boolean(const std::string& k) const { return need(k, Setting::Bool) == "1"; }
  const std::string& str(const std::string& k) const {
    const Setting& s = get(k);
    if (s.type != Setting::String && s.type != Setting::Enum) throw std::logic_error("settings: " + k + " is not a string");
    return s.value;
  }
  std::vector<int> ints(const std::string& k) const {
    std::vector<int> v;
    for (const std::string& t : split(list(k, Setting::IntList))) v.push_back(to_int(t));
    return v;
  }
  std::vector<double> reals(const std::string& k) const {
    std::vector<double> v;
    for (const std::string& t : split(list(k, Setting::RealList))) v.push_back(to_real(t));
    return v;
  }

  bool has_value(const std::string& k) const { return !get(k).value.empty(); }
  const std::string& source(const std::string& k) const { return get(k).source; }
  // True when a source other than the default sets the key. A preset counts as a source.
  bool is_set(const std::string& k) const { return get(k).source != "default"; }
  // True when a file, the environment or the command line sets the key. A preset does not count.
  bool user_set(const std::string& k) const {
    const std::string& s = get(k).source;
    return s != "default" && s.compare(0, 7, "preset:") != 0;
  }
  const std::deque<Setting>& keys() const { return keys_; }

  // Throws a SettingsError for key k with its value and source. Use it for checks across keys.
  [[noreturn]] void fail(const std::string& k, const std::string& why) const {
    const Setting& s = get(k);
    throw SettingsError(s.name + "=" + s.value + " (" + s.source + "): " + why);
  }

  // Writes config.used. The file is valid input for config=. A key without a value is a comment line.
  // ponytail: a value that contains '#' or a line break does not survive a read back. Add quotes when a tool needs it.
  void write_used(const std::string& path, const std::string& tool) const {
    FILE* f = std::fopen(path.c_str(), "w");
    if (!f) throw std::runtime_error("cannot write " + path);
    char when[32];
    const std::time_t now = std::time(nullptr);
    std::strftime(when, sizeof when, "%Y-%m-%dT%H:%M:%SZ", std::gmtime(&now));
    std::fprintf(f, "# %s config.used  %s\n", tool.c_str(), when);
    for (const Setting& s : keys_) {
      const std::string kv = (s.value.empty() ? "# " : "") + s.name + "=" + s.value;
      std::fprintf(f, "%-22s # %s%s\n", kv.c_str(), s.source.c_str(), s.value.empty() ? ", no value" : "");
    }
    const bool ok = std::ferror(f) == 0;
    if (std::fclose(f) != 0 || !ok) throw std::runtime_error("cannot write " + path);
  }

  // Prints the key table: name, type, default, range and help.
  void print_help(FILE* f, const std::string& tool) const {
    static const char* const type_names[] = {"real", "int", "bool", "string", "int list", "real list", "enum"};
    std::fprintf(f, "usage: %s [config=<file>] [key=value ...]\n", tool.c_str());
    std::fprintf(f, "Sources: default, preset, config file, environment H4NB_<KEY>, command line.\n\n");
    std::fprintf(f, "%-16s %-9s %-22s %s\n", "key", "type", "default", "range");
    for (const Setting& s : keys_) {
      const std::string d = s.required ? "(required)" : s.def.empty() ? "-" : s.def;
      std::fprintf(f, "%-16s %-9s %-22s %s\n", s.name.c_str(), type_names[s.type], d.c_str(), range_text(s).c_str());
      std::fprintf(f, "%18s%s\n", "", s.help.c_str());
    }
  }

 private:
  struct Item {
    std::string key, value, source;
  };
  std::deque<Setting> keys_;  // A deque keeps the references from add() valid.
  std::string config_;
  bool help_ = false;

  Setting* find(const std::string& k) {
    for (Setting& s : keys_) if (s.name == k) return &s;
    return nullptr;
  }
  const Setting& get(const std::string& k) const {
    for (const Setting& s : keys_) if (s.name == k) return s;
    throw std::logic_error("settings: key '" + k + "' is not declared");
  }
  const std::string& need(const std::string& k, Setting::Type t) const {
    const Setting& s = get(k);
    if (s.type != t) throw std::logic_error("settings: wrong getter for " + k);
    if (s.value.empty()) throw std::logic_error("settings: " + k + " has no value");
    return s.value;
  }
  const std::string& list(const std::string& k, Setting::Type t) const {
    const Setting& s = get(k);
    if (s.type != t) throw std::logic_error("settings: wrong getter for " + k);
    return s.value;
  }

  [[noreturn]] static void fail(const Item& it, const std::string& why) {
    throw SettingsError(it.key + "=" + it.value + " (" + it.source + "): " + why);
  }
  static std::string trim(const std::string& s) {
    const size_t a = s.find_first_not_of(" \t\r"), b = s.find_last_not_of(" \t\r");
    return a == std::string::npos ? std::string() : s.substr(a, b - a + 1);
  }
  static std::vector<std::string> split(const std::string& s) {
    std::vector<std::string> v;
    if (s.empty()) return v;
    size_t a = 0;
    for (size_t e; (e = s.find(',', a)) != std::string::npos; a = e + 1) v.push_back(trim(s.substr(a, e - a)));
    v.push_back(trim(s.substr(a)));
    return v;
  }
  // The parsers return false when the whole text is not one valid number.
  static bool parse_real(const std::string& t, double& v) {
    if (t.empty() || t[0] == ' ' || t[0] == '\t') return false;
    char* end = nullptr;
    errno = 0;
    v = std::strtod(t.c_str(), &end);
    return *end == '\0' && errno != ERANGE && std::isfinite(v);
  }
  static bool parse_int(const std::string& t, long long& v) {
    if (t.empty() || t[0] == ' ' || t[0] == '\t') return false;
    char* end = nullptr;
    errno = 0;
    v = std::strtoll(t.c_str(), &end, 10);
    return *end == '\0' && errno != ERANGE && v >= INT_MIN && v <= INT_MAX;
  }
  static double to_real(const std::string& t) { double v = 0; parse_real(t, v); return v; }
  static int to_int(const std::string& t) { long long v = 0; parse_int(t, v); return int(v); }
  static bool to_bool(const Item& it, const std::string& t) {
    if (t == "1" || t == "true") return true;
    if (t == "0" || t == "false") return false;
    fail(it, "not a bool (use 0 or 1)");
  }

  static std::string num_text(double x) {
    char b[32];
    std::snprintf(b, sizeof b, "%g", x);
    return b;
  }
  static std::string join(const std::vector<std::string>& v) {
    std::string r;
    for (const std::string& s : v) r += (r.empty() ? "" : ", ") + s;
    return r;
  }
  static std::string range_text(const Setting& s) {
    const Range& r = s.range;
    std::string t;
    if (s.type == Setting::Bool) t = "0, 1";
    if (!r.allowed.empty()) t = join(r.allowed);
    else if (r.lo > -HUGE_VAL && r.hi < HUGE_VAL && !r.lo_open && !r.hi_open) t = num_text(r.lo) + " to " + num_text(r.hi);
    else if (r.lo > -HUGE_VAL && r.hi < HUGE_VAL)
      t = (r.lo_open ? "> " : ">= ") + num_text(r.lo) + " and " + (r.hi_open ? "< " : "<= ") + num_text(r.hi);
    else if (r.lo > -HUGE_VAL) t = (r.lo_open ? "> " : ">= ") + num_text(r.lo);
    else if (r.hi < HUGE_VAL) t = (r.hi_open ? "< " : "<= ") + num_text(r.hi);
    for (double x : r.also) t = num_text(x) + " or " + t;
    if (r.pow2) t += (t.empty() ? "" : ", ") + std::string("power of two");
    if (r.count) t += (t.empty() ? "" : ", ") + std::to_string(r.count) + " values";
    return t.empty() ? "-" : t;
  }

  // Checks one number against the range. Returns an empty text when the number is valid.
  static std::string check_number(const Setting& s, double x) {
    const Range& r = s.range;
    int exp = 0;
    for (double a : r.also) if (x == a) return "";
    if (!r.allowed.empty()) {
      for (const std::string& a : r.allowed) if (to_real(a) == x) return "";
      return "not one of " + join(r.allowed);
    }
    if (x < r.lo || (r.lo_open && x == r.lo) || x > r.hi || (r.hi_open && x == r.hi)) return "out of range (" + range_text(s) + ")";
    if (r.pow2 && !(x > 0 && std::frexp(x, &exp) == 0.5)) return "not a power of two";
    return "";
  }

  // Validates a value text for key s. Returns the normalized text, or throws a SettingsError.
  static std::string check(const Setting& s, const std::string& raw, const std::string& source) {
    const Item it{s.name, raw, source};
    const std::string v = trim(raw);
    const Range& r = s.range;
    switch (s.type) {
      case Setting::String: return v;
      case Setting::Bool: return to_bool(it, v) ? "1" : "0";
      case Setting::Enum:
        for (const std::string& a : r.allowed) if (v == a) return v;
        fail(it, "not one of " + join(r.allowed));
      case Setting::Real:
      case Setting::Int:
      case Setting::RealList:
      case Setting::IntList: {
        const bool is_list = s.type == Setting::RealList || s.type == Setting::IntList;
        const bool is_int = s.type == Setting::Int || s.type == Setting::IntList;
        const std::vector<std::string> parts = is_list ? split(v) : std::vector<std::string>{v};
        if (r.count && parts.size() != r.count) fail(it, "expected " + std::to_string(r.count) + " values");
        std::string out;
        for (const std::string& p : parts) {
          double x = 0;
          long long n = 0;
          if (is_int ? !parse_int(p, n) : !parse_real(p, x)) fail(it, is_int ? "not an integer" : "not a number");
          if (is_int) x = double(n);
          const std::string why = check_number(s, x);
          if (!why.empty()) fail(it, why);
          out += (out.empty() ? "" : ",") + p;
        }
        return out;
      }
    }
    return v;
  }
  static void set(Setting& s, const std::string& value, const std::string& source) {
    s.value = check(s, value, source);
    s.source = source;
  }

  // Reads a config file. Rejects a repeated key and a nested config=.
  static std::vector<Item> read_file(const Item& cfg) {
    std::ifstream in(cfg.value);
    if (!in) fail(cfg, "cannot open the file");
    std::vector<Item> items;
    std::vector<int> lines;
    std::string line;
    for (int no = 1; std::getline(in, line); ++no) {
      const std::string where = "file:" + cfg.value + ":" + std::to_string(no);
      const std::string t = trim(line.substr(0, line.find('#')));
      if (t.empty()) continue;
      const size_t e = t.find('=');
      if (e == std::string::npos || trim(t.substr(0, e)).empty()) throw SettingsError(t + " (" + where + "): expected key=value");
      const Item it{trim(t.substr(0, e)), trim(t.substr(e + 1)), where};
      if (it.key == "config") fail(it, "config= is not allowed in a config file");
      for (size_t i = 0; i < items.size(); ++i)
        if (items[i].key == it.key) fail(it, "key repeated in the file, first at line " + std::to_string(lines[i]));
      items.push_back(it);
      lines.push_back(no);
    }
    return items;
  }
};
