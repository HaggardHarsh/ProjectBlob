#pragma once
#include <string>

struct DesktopSettings {
    float scale = 1.25f;
    bool reducedMotion = false;
    bool positioned = false;
    int x = 0, y = 0;
    static DesktopSettings load(const std::string& path);
    bool save(const std::string& path) const;
    static std::string defaultPath();
};
