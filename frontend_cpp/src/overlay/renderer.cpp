#include "renderer.h"

#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace {
constexpr Color SKY_TOP{192, 241, 250, 255};
constexpr Color SKY_LOWER{91, 192, 221, 255};
constexpr Color OUTLINE{51, 145, 177, 170};
constexpr Color INK{36, 75, 101, 255};
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
    for (int y = int(std::floor(minY)); y <= int(std::ceil(maxY)); ++y) {
        intersections.clear();
        const float sampleY = y + 0.5f;
        for (size_t i = 0; i < verts.size(); ++i) {
            const auto& a = verts[i];
            const auto& b = verts[(i + 1) % verts.size()];
            if ((a.y <= sampleY && b.y > sampleY) || (b.y <= sampleY && a.y > sampleY)) {
                const float ratio = (sampleY - a.y) / (b.y - a.y);
                intersections.push_back(a.x + ratio * (b.x - a.x));
            }
        }
        std::sort(intersections.begin(), intersections.end());
        const float t = std::clamp((y - minY) / std::max(1.0f, maxY - minY), 0.0f, 1.0f);
        SDL_SetRenderDrawColor(sdlRenderer_,
                               Uint8(SKY_TOP.r + (SKY_LOWER.r - SKY_TOP.r) * t),
                               Uint8(SKY_TOP.g + (SKY_LOWER.g - SKY_TOP.g) * t),
                               Uint8(SKY_TOP.b + (SKY_LOWER.b - SKY_TOP.b) * t), 255);
        for (size_t i = 0; i + 1 < intersections.size(); i += 2) {
            SDL_RenderDrawLine(sdlRenderer_, int(std::ceil(intersections[i])), y,
                               int(std::floor(intersections[i + 1])), y);
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
    fillEllipse(int(cx - rx * 0.42f), int(cy - ry * 0.55f),
                std::max(3, int(rx * 0.12f)), std::max(2, int(ry * 0.055f)),
                {255, 255, 255, 125});
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

void Renderer::drawFace(float cx, float cy, float rx, float ry, float time,
                        BlobState state, BlobExpression expression) {
    const float left = cx - rx * 0.26f;
    const float right = cx + rx * 0.26f;
    const float eyeY = cy - ry * 0.08f;
    const int eyeRX = std::max(2, int(rx * 0.055f));
    const int eyeRY = std::max(3, int(ry * 0.078f));
    const bool blink = expression == BlobExpression::IDLE && std::fmod(time, 5.8f) < 0.10f;

    auto dot = [&](float x, float y, int width = 0, int height = 0) {
        const int dotRX = width ? width : eyeRX;
        const int dotRY = height ? height : eyeRY;
        fillEllipse(int(x), int(y), dotRX, dotRY, INK);
        if (dotRX >= 2 && dotRY >= 3) {
            fillCircle(int(x - 1), int(y - 1), 1, {235, 252, 255, 215});
        }
    };
    auto lid = [&](float x, float y, float bend, int thickness = 1) {
        drawCurve(x - eyeRX - 2, y, x + eyeRX + 2, y, bend, INK, thickness);
    };

    if (state == BlobState::BLINDFOLDED || expression == BlobExpression::SLEEPING || blink) {
        lid(left, eyeY, 0.5f);
        lid(right, eyeY, 0.5f);
        return;
    }

    switch (expression) {
        case BlobExpression::HAPPY:
        case BlobExpression::EATING:
            lid(left, eyeY + 1, -2.7f, 2);
            lid(right, eyeY + 1, -2.7f, 2);
            break;
        case BlobExpression::EXCITED:
        case BlobExpression::CELEBRATE:
            lid(left, eyeY + 2, -3.8f, 2);
            lid(right, eyeY + 2, -3.8f, 2);
            break;
        case BlobExpression::PLAYFUL:
            lid(left, eyeY + 1, -2.5f, 2);
            dot(right, eyeY);
            break;
        case BlobExpression::TIRED:
            lid(left, eyeY + 1, 1.0f, 2);
            lid(right, eyeY + 1, 1.0f, 2);
            break;
        case BlobExpression::SAD:
            lid(left, eyeY + 1, 2.7f, 2);
            lid(right, eyeY + 1, 2.7f, 2);
            break;
        case BlobExpression::WORRIED:
            dot(left, eyeY + 1, eyeRX, eyeRY + 1);
            dot(right, eyeY + 1, eyeRX, eyeRY + 1);
            drawCurve(left - 4, eyeY - eyeRY - 4, left + 3, eyeY - eyeRY - 5,
                      -1.0f, INK, 1);
            drawCurve(right - 3, eyeY - eyeRY - 5, right + 4, eyeY - eyeRY - 4,
                      -1.0f, INK, 1);
            break;
        case BlobExpression::ANGRY:
            dot(left, eyeY + 1, eyeRX, eyeRY - 1);
            dot(right, eyeY + 1, eyeRX, eyeRY - 1);
            drawCurve(left - 5, eyeY - eyeRY - 5, left + 4, eyeY - eyeRY - 2,
                      0.0f, INK, 2);
            drawCurve(right - 4, eyeY - eyeRY - 2, right + 5, eyeY - eyeRY - 5,
                      0.0f, INK, 2);
            break;
        case BlobExpression::CONFUSED:
            dot(left, eyeY);
            lid(right, eyeY + 1, 0.5f);
            drawCurve(right - 4, eyeY - eyeRY - 6, right + 4, eyeY - eyeRY - 7,
                      -1.0f, INK, 1);
            break;
        case BlobExpression::THINKING:
            dot(left + 1, eyeY - 1);
            dot(right + 1, eyeY - 1);
            break;
        case BlobExpression::SHY:
            dot(left, eyeY + 2, eyeRX, eyeRY - 1);
            dot(right, eyeY + 2, eyeRX, eyeRY - 1);
            break;
        case BlobExpression::PROUD:
            dot(left, eyeY + 1, eyeRX + 1, eyeRY - 1);
            dot(right, eyeY + 1, eyeRX + 1, eyeRY - 1);
            lid(left, eyeY - 2, 0.2f);
            lid(right, eyeY - 2, 0.2f);
            break;
        default:
            dot(left, eyeY);
            dot(right, eyeY);
            break;
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
                const float t = (sampleY - a.y) / (b.y - a.y);
                intersections.push_back(a.x + t * (b.x - a.x));
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
