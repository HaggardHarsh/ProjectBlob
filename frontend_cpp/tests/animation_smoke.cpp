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
void advance(AnimationController& animation, int frames) {
    for (int i = 0; i < frames; ++i) animation.update(1.0f / 60);
}

int main() {
    if (SDL_Init(SDL_INIT_TIMER)) return 1;
    int result = 0;
    try {
        AnimationController companion;
        companion.setExpression(BlobExpression::SLEEPING, 1.0f);
        advance(companion, 90);
        require(companion.pose().eyeOpen < 0.1f, "Sleeping eyes did not close");
        companion.setAttention(0.8f, -0.6f, true);
        advance(companion, 30);
        require(companion.pose().eyeOpen > 1.0f && companion.pose().attention > 0.95f,
                "Hover did not wake sleeping Blob and lift the privacy mask");
        require(companion.pose().gazeX > 1.2f && companion.pose().gazeY < -0.8f,
                "Awake eyes did not follow the cursor");
        companion.setAttention(-0.8f, 0.7f, true);
        advance(companion, 30);
        require(companion.pose().gazeX < -1.2f && companion.pose().gazeY > 0.9f,
                "Eyes did not follow a change in cursor direction");
        advance(companion, 120);
        require(companion.pose().eyeOpen > 1.0f, "A stationary hover stopped keeping Blob awake");
        companion.setAttention(0, 0, false);
        advance(companion, 20);
        require(companion.pose().eyeOpen > 1.0f, "Blob fell asleep immediately on cursor exit");
        advance(companion, 150);
        require(companion.pose().eyeOpen < 0.1f && companion.pose().attention < 0.01f,
                "Blob did not settle back to sleep after interaction");
        companion.poke();
        advance(companion, 6);
        require(companion.pose().eyeSize > 1.2f, "A poke did not briefly surprise Blob");
        advance(companion, 24);
        require(companion.pose().mouthSmile > 0.9f && companion.pose().eyeAsymmetry > 0.3f,
                "A poke did not produce a playful face");
        companion.poke(); companion.poke();
        advance(companion, 30);
        require(companion.pose().eyeTilt > 0.6f && companion.pose().blush > 0.3f,
                "Repeated pokes did not produce a mock grumpy reaction");
        advance(companion, 180);
        require(companion.pose().eyeOpen < 0.1f, "A poke permanently replaced the backend expression");
        companion.setAttention(-0.8f, 0, true);
        for (int turn = 0; turn < 5; ++turn) {
            // Small mouse events must accumulate into a teasing reversal.
            for (int step = 0; step < 16; ++step) {
                const float x = turn % 2 == 0 ? -0.8f + step * 0.1f : 0.8f - step * 0.1f;
                companion.setAttention(x, 0, true);
                companion.update(1.0f / 120);
            }
        }
        advance(companion, 24);
        require(companion.pose().eyeAsymmetry > 0.3f && companion.pose().blush > 0.25f,
                "Wiggling the pointer did not trigger playful teasing");
        companion.setReducedMotion(true);
        companion.poke();
        advance(companion, 30);
        require(companion.pose().attention > 0.95f && companion.pose().eyeAsymmetry > 0.65f &&
                std::abs(companion.pose().lift) < 0.01f &&
                std::abs(companion.pose().lean) < 0.01f && std::abs(companion.pose().shake) < 0.01f,
                "Reduced motion lost facial interaction or retained body movement");

        AnimationController emotions;
        emotions.setExpression(BlobExpression::HAPPY, 0.6f);
        advance(emotions, 60);
        require(emotions.pose().eyeSmile > 0.7f && emotions.pose().attention > 0.95f,
                "A happy emote did not show smiling eyes above the privacy mask");
        emotions.setAttention(0.7f, 0.2f, true);
        advance(emotions, 30);
        require(emotions.pose().eyeSmile > 0.7f && emotions.pose().eyeOpen < 0.4f,
                "Hover erased the happy squint");
        emotions.setExpression(BlobExpression::ANGRY, 0.6f);
        advance(emotions, 60);
        require(emotions.pose().eyeSqueeze > 0.7f && emotions.pose().height < 0.85f,
                "Annoyance lost its broad squeezed eyes and compressed silhouette");
        emotions.setExpression(BlobExpression::CRYING, 0.6f);
        advance(emotions, 60);
        require(emotions.pose().tears > 0.7f && emotions.pose().eyeTilt < -0.6f,
                "Crying did not have its own tearful expression");
        emotions.setAttention(0, 0, false);
        emotions.setExpression(BlobExpression::SLEEPING, 1);
        advance(emotions, 180);
        require(emotions.pose().attention < 0.01f && emotions.pose().tears < 0.01f &&
                emotions.pose().eyeSqueeze < 0.01f && emotions.pose().eyeSmile < 0.01f,
                "Expression features or raised privacy mask persisted into sleep");

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
