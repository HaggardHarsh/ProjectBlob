#include "app/settings.h"
#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <sstream>

std::string DesktopSettings::defaultPath() {
    const char* xdg = std::getenv("XDG_CONFIG_HOME");
    const char* home = std::getenv("HOME");
    if (xdg && std::filesystem::path(xdg).is_absolute()) return std::string(xdg) + "/projectblob/frontend.conf";
    return home ? std::string(home) + "/.config/projectblob/frontend.conf" : "";
}

DesktopSettings DesktopSettings::load(const std::string& path) {
    DesktopSettings settings;
    std::error_code error;
    if (std::filesystem::file_size(path, error) > 4096 || error) return settings;
    std::ifstream file(path);
    std::string line, key;
    bool hasX = false, hasY = false;
    for (int count = 0; count < 16 && std::getline(file, line); ++count) {
        if (line.size() > 256) break;
        std::istringstream row(line);
        if (!(row >> key)) continue;
        if (key == "scale") { float value; if (row >> value && std::isfinite(value)) settings.scale = std::clamp(value, 0.75f, 2.0f); }
        else if (key == "reduced_motion") { int value; if (row >> value) settings.reducedMotion = value == 1; }
        else if (key == "x") hasX = bool(row >> settings.x);
        else if (key == "y") hasY = bool(row >> settings.y);
    }
    settings.positioned = hasX && hasY;
    return settings;
}

bool DesktopSettings::save(const std::string& path) const {
    if (path.empty()) return false;
    try {
        const std::filesystem::path target(path);
        std::filesystem::create_directories(target.parent_path());
        const auto temporary = path + ".tmp";
        std::ofstream file(temporary, std::ios::trunc);
        file << "scale " << scale << "\nreduced_motion " << reducedMotion << '\n';
        if (positioned) file << "x " << x << "\ny " << y << '\n';
        file.close();
        if (!file) return false;
        std::filesystem::rename(temporary, target);
        return true;
    } catch (const std::filesystem::filesystem_error&) { return false; }
}
