#include <SDL2/SDL.h>
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <utility>
#include <vector>

#include "blob/animation.h"
#include "blob/physics.h"
#include "overlay/renderer.h"

namespace {
constexpr int width = 132, height = 116;
using Reference = std::pair<const char*, BlobExpression>;
constexpr std::array references{
    Reference{"neutral", BlobExpression::IDLE},
    Reference{"cute_smile", BlobExpression::CUTE_SMILE},
    Reference{"happy", BlobExpression::HAPPY},
    Reference{"very_happy", BlobExpression::VERY_HAPPY},
    Reference{"excited", BlobExpression::EXCITED},
    Reference{"laughing", BlobExpression::LAUGHING},
    Reference{"shocked", BlobExpression::SHOCKED},
    Reference{"extremely_shocked", BlobExpression::EXTREME_SHOCK},
    Reference{"confused", BlobExpression::CONFUSED},
    Reference{"thinking", BlobExpression::THINKING},
    Reference{"deep_thinking", BlobExpression::DEEP_THINKING},
    Reference{"focused", BlobExpression::FOCUSED},
    Reference{"working", BlobExpression::WORKING},
    Reference{"listening", BlobExpression::LISTENING},
    Reference{"speaking", BlobExpression::SPEAKING},
    Reference{"angry", BlobExpression::ANGRY},
    Reference{"playfully_angry", BlobExpression::PLAYFUL_ANGRY},
    Reference{"frustrated", BlobExpression::FRUSTRATED},
    Reference{"sad", BlobExpression::SAD},
    Reference{"crying", BlobExpression::CRYING},
    Reference{"embarrassed", BlobExpression::EMBARRASSED},
    Reference{"nervous", BlobExpression::NERVOUS},
    Reference{"sleepy", BlobExpression::SLEEPY},
    Reference{"tired", BlobExpression::TIRED},
    Reference{"melting", BlobExpression::MELTING},
    Reference{"completely_melted", BlobExpression::MELTED},
    Reference{"recovering", BlobExpression::RECOVERING},
    Reference{"error", BlobExpression::ERROR},
    Reference{"glitch", BlobExpression::GLITCH},
    Reference{"success", BlobExpression::SUCCESS},
    Reference{"celebration", BlobExpression::CELEBRATE},
    Reference{"curious", BlobExpression::CURIOUS},
    Reference{"suspicious", BlobExpression::SUSPICIOUS},
    Reference{"proud", BlobExpression::PROUD},
    Reference{"surprised_realization", BlobExpression::REALIZATION},
    Reference{"idea", BlobExpression::IDEA},
    Reference{"waiting", BlobExpression::WAITING},
    Reference{"bored", BlobExpression::BORED},
};

int draw(SDL_Window* window, Renderer& renderer, BlobPhysics& physics,
         const BlobPose& pose, float time, std::vector<unsigned char>& pixels,
         bool face = true) {
    physics.setPose(pose);
    const auto vertices = physics.getVertices();
    const auto center = physics.getCenter();
    renderer.clear();
    renderer.drawOuterBody(vertices);
    renderer.drawOutline(vertices);
    renderer.drawHighlights(center.x, center.y, physics.getRadiusX(), physics.getRadiusY());
    renderer.drawDetails(center.x, center.y, physics.getRadiusX(), physics.getRadiusY(), time, pose);
    if (face) renderer.drawFace(center.x, center.y, physics.getRadiusX(), physics.getRadiusY(),
                                time, BlobState::IDLE, pose);
    renderer.present();
    return SDL_RenderReadPixels(SDL_GetRenderer(window), nullptr,
                                SDL_PIXELFORMAT_RGBA8888, pixels.data(), width * 4);
}

void save(const char* directory, const char* name, std::vector<unsigned char>& pixels) {
    if (!directory) return;
    const std::string path = std::string(directory) + "/" + name + ".bmp";
    SDL_Surface* surface = SDL_CreateRGBSurfaceWithFormatFrom(
        pixels.data(), width, height, 32, width * 4, SDL_PIXELFORMAT_RGBA8888);
    if (surface) {
        SDL_SaveBMP(surface, path.c_str());
        SDL_FreeSurface(surface);
    }
}
}

int main() {
    if (SDL_Init(SDL_INIT_VIDEO) != 0) return 1;
    SDL_Window* window = SDL_CreateWindow("Blob render test", 0, 0, width, height, SDL_WINDOW_HIDDEN);
    if (!window) return 2;
    const char* directory = std::getenv("BLOB_PREVIEW_DIR");
    std::vector<unsigned char> idle(width * height * 4), bodyOnly(idle.size()), pixels(idle.size());
    {
        Renderer renderer(window, width, height);
        BlobPhysics physics(width, height);
        AnimationController idleAnimation;
        idleAnimation.update(1.0f / 60.0f);
        if (draw(window, renderer, physics, idleAnimation.pose(), 1.0f, idle) != 0 ||
            draw(window, renderer, physics, idleAnimation.pose(), 1.0f, bodyOnly, false) != 0) return 3;
        // The idle face has a readable mouth as well as eyes.
        bool mouthVisible = false;
        const int centerY = int(physics.getCenter().y + physics.getRadiusY() * 0.29f);
        for (int y = centerY - 2; y <= centerY + 5; ++y) {
            for (int x = width / 2 - 10; x <= width / 2 + 10; ++x) {
                const int offset = (y * width + x) * 4;
                if (!std::equal(idle.begin() + offset, idle.begin() + offset + 4,
                                bodyOnly.begin() + offset)) mouthVisible = true;
            }
        }
        if (!mouthVisible) return 4;
        for (const auto& [name, expression] : references) {
            AnimationController animation;
            animation.setExpression(expression, 0.85f);
            for (int frame = 0; frame < 75; ++frame) animation.update(1.0f / 60.0f);
            if (draw(window, renderer, physics, animation.pose(), 1.25f, pixels) != 0) return 5;
            if (expression != BlobExpression::IDLE && std::equal(idle.begin(), idle.end(), pixels.begin())) return 6;
            save(directory, name, pixels);
        }
        AnimationController mixed;
        mixed.setExpression(BlobExpression::HAPPY, 0.7f);
        mixed.setBlend(BlobExpression::CONFUSED, 0.3f);
        for (int frame = 0; frame < 75; ++frame) mixed.update(1.0f / 60.0f);
        if (mixed.pose().eyeAsymmetry < 0.05f || mixed.pose().mouthSmile < 0.3f) return 10;
        draw(window, renderer, physics, mixed.pose(), 1.25f, pixels);
        save(directory, "happy_confused", pixels);
        mixed.setExpression(BlobExpression::TIRED);
        mixed.setBlend(BlobExpression::THINKING, 0.4f);
        for (int frame = 0; frame < 75; ++frame) mixed.update(1.0f / 60.0f);
        draw(window, renderer, physics, mixed.pose(), 1.25f, pixels);
        save(directory, "tired_thinking", pixels);
        if (directory) {
            const auto motion = [&](const char* prefix, BlobExpression expression, int frames) {
                AnimationController animation;
                animation.setExpression(expression, 0.9f);
                for (int frame = 0; frame < frames; ++frame) {
                    for (int step = 0; step < 4; ++step) animation.update(1.0f / 60.0f);
                    draw(window, renderer, physics, animation.pose(), frame / 15.0f, pixels);
                    char name[80];
                    std::snprintf(name, sizeof(name), "%s_%03d", prefix, frame);
                    save(directory, name, pixels);
                }
            };
            motion("thinking_motion", BlobExpression::THINKING, 45);
            motion("celebration_motion", BlobExpression::CELEBRATE, 28);
            AnimationController meltMotion;
            meltMotion.setExpression(BlobExpression::MELTING, 0.9f);
            for (int frame = 0; frame < 50; ++frame) {
                if (frame == 30) meltMotion.setExpression(BlobExpression::RECOVERING, 0.65f);
                for (int step = 0; step < 4; ++step) meltMotion.update(1.0f / 60.0f);
                draw(window, renderer, physics, meltMotion.pose(), frame / 15.0f, pixels);
                char name[80];
                std::snprintf(name, sizeof(name), "melting_motion_%03d", frame);
                save(directory, name, pixels);
            }
        }
        AnimationController melt;
        melt.setExpression(BlobExpression::MELTING, 1.0f);
        for (int frame = 0; frame < 100; ++frame) melt.update(1.0f / 60.0f);
        if (melt.pose().height > 0.36f || melt.pose().width < 1.25f) return 7;
        melt.setExpression(BlobExpression::RECOVERING);
        for (int frame = 0; frame < 90; ++frame) melt.update(1.0f / 60.0f);
        if (melt.pose().height < 0.95f || melt.pose().height > 1.2f) return 8;
        AnimationController neutralIntensity, fullIntensity;
        neutralIntensity.setExpression(BlobExpression::SHOCKED, 0.0f);
        fullIntensity.setExpression(BlobExpression::SHOCKED, 1.0f);
        for (int frame = 0; frame < 75; ++frame) {
            neutralIntensity.update(1.0f / 60.0f);
            fullIntensity.update(1.0f / 60.0f);
        }
        if (std::abs(neutralIntensity.pose().height - 1.0f) > 0.03f ||
            neutralIntensity.pose().mouthRound > 0.01f ||
            fullIntensity.pose().height < neutralIntensity.pose().height + 0.16f) return 11;
        physics.jiggle();
        for (int frame = 0; frame < 120; ++frame) {
            physics.update(1.0f / 60.0f);
            for (const auto& point : physics.getVertices()) {
                if (!std::isfinite(point.x) || !std::isfinite(point.y)) return 9;
            }
        }
    }
    SDL_DestroyWindow(window);
    SDL_Quit();
    return 0;
}
