#include "app/settings.h"
#include "blob/animation.h"
#include "blob/physics.h"
#include <SDL2/SDL.h>
#include <cmath>
#include <filesystem>
#include <iostream>
#include <limits>
#include <stdexcept>

void require(bool value, const char* message) { if (!value) throw std::runtime_error(message); }

int main() {
    if (SDL_Init(SDL_INIT_TIMER)) return 1;
    int result = 0;
    try {
        AnimationController animation;
        DesktopSettings settings;
        animation.setReducedMotion(true); animation.setExpression(BlobExpression::CELEBRATE, 1);
        BlobPhysics physics;
        physics.setReducedMotion(true);
        for (int i = 0; i < 300; ++i) { animation.update(1.0f / 60); physics.setPose(animation.pose()); physics.update(1.0f / 60); }
        const auto before = physics.getVertices();
        physics.jiggle(); physics.setDrag(1);
        for (int i = 0; i < 60; ++i) { animation.update(1.0f / 60); physics.setPose(animation.pose()); physics.update(1.0f / 60); }
        const auto after = physics.getVertices();
        for (size_t i = 0; i < before.size(); ++i) require((before[i] - after[i]).length() < 0.001f, "Reduced motion still animated");
        animation.update(std::numeric_limits<float>::quiet_NaN()); physics.update(std::numeric_limits<float>::infinity());
        require(std::isfinite(animation.pose().height) && std::isfinite(physics.getCenter().x), "Invalid frame timing corrupted the pose");
        const auto path = std::filesystem::temp_directory_path() / ("blob-desktop-settings-" + std::to_string(SDL_GetPerformanceCounter()));
        settings.scale = 1.75f; settings.reducedMotion = true; settings.positioned = true; settings.x = -1000; settings.y = 50;
        require(settings.save((path / "frontend.conf").string()), "Desktop preferences could not save");
        const auto restored = DesktopSettings::load((path / "frontend.conf").string());
        require(restored.scale == settings.scale && restored.reducedMotion && restored.x == -1000, "Desktop preferences did not survive reload");
        std::filesystem::remove_all(path);
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; result = 1; }
    SDL_Quit();
    return result;
}
