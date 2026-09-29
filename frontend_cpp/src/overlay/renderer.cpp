#include "renderer.h"

#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace {
constexpr Color TOP{198, 244, 251, 255};
constexpr Color BASE{75, 181, 216, 255};
constexpr Color OUTLINE{48, 139, 175, 180};
constexpr Color INK{28, 69, 98, 255};
float unit(float value) { return std::clamp(value, 0.0f, 1.0f); }
}

Renderer::Renderer(SDL_Window* window, int w, int h) : width_(w), height_(h) {
    sdlRenderer_ = SDL_CreateRenderer(window, -1, SDL_RENDERER_ACCELERATED | SDL_RENDERER_PRESENTVSYNC);
    if (!sdlRenderer_) sdlRenderer_ = SDL_CreateRenderer(window, -1, SDL_RENDERER_SOFTWARE);
    if (!sdlRenderer_) throw std::runtime_error("SDL_CreateRenderer failed");
    SDL_SetRenderDrawBlendMode(sdlRenderer_, SDL_BLENDMODE_BLEND);
    shapeSurface_ = SDL_CreateRGBSurface(0, width_, height_, 32,
                                        0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000);
    if (!shapeSurface_) throw std::runtime_error("SDL_CreateRGBSurface failed");
}

Renderer::~Renderer() {
    if (shapeSurface_) SDL_FreeSurface(shapeSurface_);
    if (sdlRenderer_) SDL_DestroyRenderer(sdlRenderer_);
}

void Renderer::clear() {
    SDL_SetRenderDrawColor(sdlRenderer_, 0, 0, 0, 0);
    SDL_RenderClear(sdlRenderer_);
    SDL_FillRect(shapeSurface_, nullptr, SDL_MapRGBA(shapeSurface_->format, 0, 0, 0, 0));
}

void Renderer::present() { SDL_RenderPresent(sdlRenderer_); }

void Renderer::drawOuterBody(const std::vector<Vec2>& verts) {
    if (verts.size() < 3) return;
    float minY = verts.front().y, maxY = minY;
    for (const auto& v : verts) {
        minY = std::min(minY, v.y);
        maxY = std::max(maxY, v.y);
    }
    std::vector<float> intersections;
    intersections.reserve(verts.size());
    for (int y = std::max(0, int(std::floor(minY)));
         y <= std::min(height_ - 1, int(std::ceil(maxY))); ++y) {
        intersections.clear();
        const float sampleY = y + 0.5f;
        for (size_t i = 0; i < verts.size(); ++i) {
            const auto& a = verts[i];
            const auto& b = verts[(i + 1) % verts.size()];
            if ((a.y <= sampleY && b.y > sampleY) || (b.y <= sampleY && a.y > sampleY)) {
                intersections.push_back(a.x + (sampleY - a.y) * (b.x - a.x) / (b.y - a.y));
            }
        }
        std::sort(intersections.begin(), intersections.end());
        const float t = unit((y - minY) / std::max(1.0f, maxY - minY));
        const float light = 0.04f * std::sin(t * 3.14159f);
        SDL_SetRenderDrawColor(sdlRenderer_,
                               Uint8(TOP.r + (BASE.r - TOP.r) * t + light * 255),
                               Uint8(TOP.g + (BASE.g - TOP.g) * t + light * 110),
                               Uint8(TOP.b + (BASE.b - TOP.b) * t), 246);
        for (size_t i = 0; i + 1 < intersections.size(); i += 2) {
            const int left = std::max(0, int(std::ceil(intersections[i])));
            const int right = std::min(width_ - 1, int(std::floor(intersections[i + 1])));
            if (right >= left) SDL_RenderDrawLine(sdlRenderer_, left, y, right, y);
        }
    }
}

void Renderer::drawOutline(const std::vector<Vec2>& verts) {
    if (verts.size() < 3) return;
    SDL_SetRenderDrawColor(sdlRenderer_, OUTLINE.r, OUTLINE.g, OUTLINE.b, OUTLINE.a);
    for (size_t i = 0; i < verts.size(); ++i) {
        const auto& a = verts[i];
        const auto& b = verts[(i + 1) % verts.size()];
        SDL_RenderDrawLineF(sdlRenderer_, a.x, a.y, b.x, b.y);
    }
}

void Renderer::drawHighlights(float cx, float cy, float rx, float ry) {
    fillEllipse(int(cx - rx * 0.48f), int(cy - ry * 0.52f),
                std::max(3, int(rx * 0.12f)), std::max(2, int(ry * 0.065f)),
                {255, 255, 255, 115});
    fillEllipse(int(cx + rx * 0.36f), int(cy - ry * 0.61f),
                std::max(2, int(rx * 0.055f)), std::max(2, int(ry * 0.042f)),
                {240, 255, 255, 70});
}

void Renderer::drawDetails(float cx, float cy, float rx, float ry, float time,
                           const BlobPose& pose) {
    if (pose.bubbles > 0.05f) {
        for (int i = 0; i < 3; ++i) {
            const float phase = std::fmod(time * (0.28f + i * 0.06f) + i * 0.35f, 1.0f);
            const int x = pose.workFlow > 0.5f
                ? int(cx + rx * (-0.52f + phase * 1.0f))
                : int(cx + (i - 1) * rx * 0.30f + std::sin(time + i) * 2.0f);
            const int y = pose.workFlow > 0.5f
                ? int(cy + ry * (-0.38f + i * 0.24f))
                : int(cy + ry * (0.36f - phase * 1.05f));
            const int r = i == 1 ? 4 : 3;
            fillCircle(x, y, r, {221, 255, 255, Uint8(105 * pose.bubbles)});
            fillCircle(x - 1, y - 1, 1, {255, 255, 255, Uint8(155 * pose.bubbles)});
        }
    }
    if (pose.arms < -0.1f) {
        drawCurve(cx + rx * 0.82f, cy + ry * 0.26f,
                  cx + rx * 0.39f, cy + ry * 0.33f, -3.0f,
                  {58, 157, 194, Uint8(150 * -pose.arms)}, 2);
        fillCircle(int(cx + rx * 0.39f), int(cy + ry * 0.33f), 3,
                   {159, 229, 242, Uint8(180 * -pose.arms)});
    }
    if (pose.sparkles > 0.05f) {
        for (int side : {-1, 1}) {
            const float x = cx + side * rx * 0.69f;
            const float y = cy - ry * (side < 0 ? 0.29f : 0.57f);
            SDL_SetRenderDrawColor(sdlRenderer_, 245, 255, 255, Uint8(180 * pose.sparkles));
            SDL_RenderDrawLineF(sdlRenderer_, x - 3, y, x + 3, y);
            SDL_RenderDrawLineF(sdlRenderer_, x, y - 3, x, y + 3);
        }
    }
    if (pose.glitch > 0.05f) {
        SDL_SetRenderDrawColor(sdlRenderer_, 232, 255, 255, Uint8(150 * pose.glitch));
        SDL_RenderDrawLineF(sdlRenderer_, cx - rx * 0.65f, cy - ry * 0.2f,
                           cx + rx * 0.58f, cy - ry * 0.2f);
    }
}

void Renderer::drawCurve(float x0, float y0, float x1, float y1,
                         float bend, Color color, int thickness) {
    SDL_SetRenderDrawColor(sdlRenderer_, color.r, color.g, color.b, color.a);
    for (int stroke = 0; stroke < thickness; ++stroke) {
        float px = x0, py = y0 + stroke;
        for (int i = 1; i <= 20; ++i) {
            const float t = i / 20.0f;
            const float x = x0 + (x1 - x0) * t;
            const float y = y0 + (y1 - y0) * t + bend * 4.0f * t * (1.0f - t) + stroke;
            SDL_RenderDrawLineF(sdlRenderer_, px, py, x, y);
            px = x; py = y;
        }
    }
}

void Renderer::drawFace(float cx, float cy, float rx, float ry, float,
                        BlobState state, const BlobPose& pose) {
    const float eyeY = cy - ry * (pose.melt > 0.5f ? 0.04f : 0.16f) + pose.gazeY * 2.0f;
    const float eyeOffset = rx * 0.28f;
    const int eyeRX = std::max(2, int(rx * 0.10f * pose.eyeSize));
    const int eyeRY = std::max(1, int(ry * 0.19f * pose.eyeSize * pose.eyeOpen));
    const bool hidden = state == BlobState::BLINDFOLDED;
    for (int side : {-1, 1}) {
        const float x = cx + side * eyeOffset + pose.gazeX * 2.0f;
        const float y = eyeY + (side > 0 ? pose.eyeAsymmetry * 3.0f : 0.0f);
        const int thisRY = std::max(1, int(eyeRY * (side > 0 ? 1.0f - pose.eyeAsymmetry * 0.45f : 1.0f)));
        if (hidden || thisRY <= 2) {
            drawCurve(x - eyeRX, y, x + eyeRX, y,
                      pose.mouthSmile > 1.0f ? -2.1f : 0.8f, INK, 2);
        } else {
            fillEllipse(int(x), int(y), eyeRX, thisRY, INK);
            fillCircle(int(x - eyeRX * 0.3f), int(y - thisRY * 0.36f),
                       std::max(1, eyeRX / 3), {239, 253, 255, 235});
        }
        if (!hidden && std::abs(pose.eyeTilt) > 0.12f) {
            const float tilt = pose.eyeTilt * (side < 0 ? 1.0f : -1.0f);
            SDL_SetRenderDrawColor(sdlRenderer_, INK.r, INK.g, INK.b, 230);
            SDL_RenderDrawLineF(sdlRenderer_, x - eyeRX - 1, y - thisRY - tilt * 3,
                               x + eyeRX + 1, y - thisRY + tilt * 3);
        }
    }
    const float mouthY = cy + ry * (pose.melt > 0.5f ? 0.49f : 0.29f);
    const float mouthHalf = std::max(3.0f, rx * 0.17f * pose.mouthWidth);
    if (pose.mouthRound > 0.55f) {
        fillEllipse(int(cx), int(mouthY), std::max(3, int(mouthHalf * 0.58f)),
                    std::max(3, int(ry * 0.13f * pose.mouthOpen)), INK);
    } else if (pose.mouthOpen > 0.16f) {
        fillEllipse(int(cx), int(mouthY + 1), std::max(4, int(mouthHalf * 0.85f)),
                    std::max(2, int(ry * 0.12f * pose.mouthOpen)), INK);
        drawCurve(cx - mouthHalf, mouthY - 1, cx + mouthHalf, mouthY - 1,
                  pose.mouthSmile * 2.0f, INK, 1);
    } else {
        drawCurve(cx - mouthHalf, mouthY, cx + mouthHalf,
                  mouthY + pose.mouthSkew * 2.0f, pose.mouthSmile * 2.6f, INK, 2);
    }
    if (pose.blush > 0.05f) {
        const Color blush{236, 135, 173, Uint8(110 * pose.blush)};
        fillEllipse(int(cx - rx * 0.53f), int(cy + ry * 0.12f),
                    std::max(2, int(rx * 0.11f)), std::max(1, int(ry * 0.06f)), blush);
        fillEllipse(int(cx + rx * 0.53f), int(cy + ry * 0.12f),
                    std::max(2, int(rx * 0.11f)), std::max(1, int(ry * 0.06f)), blush);
    }
    if (pose.sweat > 0.05f) {
        fillEllipse(int(cx + rx * 0.55f), int(eyeY + ry * 0.22f), 2,
                    std::max(2, int(ry * 0.08f)), {237, 255, 255, Uint8(180 * pose.sweat)});
    }
}

void Renderer::stampShape(const std::vector<Vec2>& verts, float, float) {
    if (!shapeSurface_ || verts.size() < 3) return;
    SDL_LockSurface(shapeSurface_);
    auto* pixels = static_cast<Uint32*>(shapeSurface_->pixels);
    const int pitch = shapeSurface_->pitch / 4;
    const Uint32 opaque = SDL_MapRGBA(shapeSurface_->format, 255, 255, 255, 255);
    std::vector<float> intersections;
    intersections.reserve(verts.size());
    for (int y = 0; y < height_; ++y) {
        intersections.clear();
        const float sampleY = y + 0.5f;
        for (size_t i = 0; i < verts.size(); ++i) {
            const Vec2& a = verts[i];
            const Vec2& b = verts[(i + 1) % verts.size()];
            if ((a.y <= sampleY && b.y > sampleY) || (b.y <= sampleY && a.y > sampleY)) {
                intersections.push_back(a.x + (sampleY - a.y) * (b.x - a.x) / (b.y - a.y));
            }
        }
        std::sort(intersections.begin(), intersections.end());
        for (size_t i = 0; i + 1 < intersections.size(); i += 2) {
            const int start = std::max(0, int(std::ceil(intersections[i])));
            const int end = std::min(width_ - 1, int(std::floor(intersections[i + 1])));
            for (int x = start; x <= end; ++x) pixels[y * pitch + x] = opaque;
        }
    }
    SDL_UnlockSurface(shapeSurface_);
}

void Renderer::fillCircle(int cx, int cy, int r, Color color) {
    fillEllipse(cx, cy, r, r, color);
}

void Renderer::fillEllipse(int cx, int cy, int rx, int ry, Color color) {
    if (rx <= 0 || ry <= 0) return;
    SDL_SetRenderDrawColor(sdlRenderer_, color.r, color.g, color.b, color.a);
    for (int y = -ry; y <= ry; ++y) {
        const float t = float(y) / float(ry);
        const int dx = int(std::sqrt(std::max(0.0f, 1.0f - t * t)) * rx);
        SDL_RenderDrawLine(sdlRenderer_, cx - dx, cy + y, cx + dx, cy + y);
    }
}
