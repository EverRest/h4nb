#pragma once
#include <map>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

// Parses key=value command-line arguments.
struct Args {
  std::map<std::string, std::string> kv;
  Args(int argc, char** argv) {
    for (int i = 1; i < argc; ++i) {
      const std::string s = argv[i];
      const size_t e = s.find('=');
      if (e == std::string::npos) throw std::invalid_argument("Expected key=value, got '" + s + "'");
      kv[s.substr(0, e)] = s.substr(e + 1);
    }
  }
  bool has(const std::string& k) const { return kv.count(k) != 0; }
  std::string str(const std::string& k, const std::string& def = "") const { return has(k) ? kv.at(k) : def; }
  double num(const std::string& k, double def) const { return has(k) ? std::stod(kv.at(k)) : def; }
  std::vector<int> ints(const std::string& k, const std::string& def) const {
    std::vector<int> out;
    std::stringstream ss(str(k, def));
    for (std::string t; std::getline(ss, t, ',');) out.push_back(std::stoi(t));
    return out;
  }
};
