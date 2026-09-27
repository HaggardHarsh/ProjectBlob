#include "renderer.h"

#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace {
constexpr Color SKY_TOP{177, 237, 253, 255};
constexpr Color SKY_LOWER{76, 178, 226, 255};
constexpr Color OUTLINE{36, 127, 185, 230};
constexpr Color INK{35, 65, 96, 255};
constexpr Color BLUSH{255, 124, 160, 105};
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
    Vec2 center{0, 0};
    float minY = verts.front().y, maxY = minY;
    for (const auto& v : verts) {
        center.x += v.x;
        center.y += v.y;
        minY = std::min(minY, v.y);
        maxY = std::max(maxY, v.y);
    }
    center.x /= verts.size();
    center.y /= verts.size();
    const SDL_Color middle{139, 223, 251, 255};
    for (size_t i = 0; i < verts.size(); ++i) {
        const auto& a = verts[i];
        const auto& b = verts[(i + 1) % verts.size()];
        auto edgeColor = [&](float y) {
            const float t = std::clamp((y - minY) / std::max(1.0f, maxY - minY), 0.0f, 1.0f);
            return SDL_Color{
                Uint8(SKY_TOP.r + (SKY_LOWER.r - SKY_TOP.r) * t),
                Uint8(SKY_TOP.g + (SKY_LOWER.g - SKY_TOP.g) * t),
                Uint8(SKY_TOP.b + (SKY_LOWER.b - SKY_TOP.b) * t),
                255,
            };
        };
        SDL_Vertex triangle[3]{
            {{center.x, center.y}, middle, {0, 0}},
            {{a.x, a.y}, edgeColor(a.y), {0, 0}},
            {{b.x, b.y}, edgeColor(b.y), {0, 0}},
        };
        SDL_RenderGeometry(sdlRenderer_, nullptr, triangle, 3, nullptr, 0);
    }
}

void Renderer::drawOutline(const std::vector<Vec2>& verts) {
    if (verts.size() < 3) return;
    SDL_SetRenderDrawColor(sdlRenderer_, OUTLINE.r, OUTLINE.g, OUTLINE.b, OUTLINE.a);
    for (size_t i = 0; i < verts.size(); ++i) {
        const auto& a = verts[i];
        const auto& b = verts[(i + 1) % verts.size()];
        SDL_RenderDrawLineF(sdlRenderer_, a.x, a.y, b.x, b.y);
        SDL_RenderDrawLineF(sdlRenderer_, a.x, a.y + 1.0f, b.x, b.y + 1.0f);
    }
}

void Renderer::drawInnerBody(float cx, float cy, float rx, float ry, float time) {
    const float breathe = std::sin(time * 1.8f) * 1.3f;
    fillEllipse(int(cx), int(cy + ry * 0.33f), int(rx * 0.74f),
                int(ry * 0.48f + breathe), {70, 175, 227, 35});
    fillEllipse(int(cx - rx * 0.10f), int(cy - ry * 0.31f),
                int(rx * 0.67f), int(ry * 0.34f), {225, 251, 255, 42});
}

void Renderer::drawHighlights(float cx, float cy, float rx, float ry) {
    fillEllipse(int(cx - rx * 0.48f), int(cy - ry * 0.61f),
                int(rx * 0.23f), int(ry * 0.105f), {255, 255, 255, 175});
    fillEllipse(int(cx - rx * 0.65f), int(cy - ry * 0.42f),
                int(rx * 0.065f), int(ry * 0.12f), {255, 255, 255, 105});
    fillCircle(int(cx + rx * 0.58f), int(cy + ry * 0.34f),
               std::max(2, int(rx * 0.035f)), {225, 250, 255, 100});
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
    const float left = cx - rx * 0.29f;
    const float right = cx + rx * 0.29f;
    const float eyeY = cy - ry * 0.10f;
    const float eyeRX = std::max(4.0f, rx * 0.085f);
    const float eyeRY = std::max(5.0f, ry * 0.14f);
    const float mouthY = cy + ry * 0.36f;

    if (state == BlobState::BLINDFOLDED) {
        fillEllipse(int(cx), int(eyeY), int(rx * 0.58f), int(ry * 0.25f),
                    {39, 105, 153, 220});
        fillEllipse(int(cx), int(eyeY - 2), int(rx * 0.51f), int(ry * 0.20f),
                    {80, 156, 195, 245});
        fillEllipse(int(cx - rx * 0.20f), int(eyeY - ry * 0.08f),
                    int(rx * 0.11f), std::max(2, int(ry * 0.035f)), {219, 242, 248, 135});
        drawCurve(cx - rx * 0.13f, mouthY, cx + rx * 0.13f, mouthY, 3, INK, 2);
        return;
    }

    const bool blink = expression == BlobExpression::IDLE && std::fmod(time, 4.8f) < 0.12f;
    const bool closed = expression == BlobExpression::HAPPY ||
                        expression == BlobExpression::EXCITED ||
                        expression == BlobExpression::CELEBRATE ||
                        expression == BlobExpression::PLAYFUL ||
                        expression == BlobExpression::SLEEPING ||
                        expression == BlobExpression::TIRED || blink;
    if (closed) {
        const bool sleepy = expression == BlobExpression::SLEEPING ||
                            expression == BlobExpression::TIRED || blink;
        const float bend = sleepy ? 1.0f : -eyeRY * 0.75f;
        drawCurve(left - eyeRX, eyeY, left + eyeRX, eyeY, bend, INK, 2);
        drawCurve(right - eyeRX, eyeY, right + eyeRX, eyeY, bend, INK, 2);
    } else {
        float lookX = 0.0f, lookY = 0.0f;
        if (expression == BlobExpression::THINKING) { lookX = eyeRX * 0.30f; lookY = -eyeRY * 0.24f; }
        if (expression == BlobExpression::SHY) lookY = eyeRY * 0.30f;
        fillEllipse(int(left + lookX), int(eyeY + lookY), int(eyeRX), int(eyeRY), INK);
        fillEllipse(int(right + lookX), int(eyeY + lookY), int(eyeRX), int(eyeRY), INK);
        fillCircle(int(left + lookX - eyeRX * 0.28f), int(eyeY + lookY - eyeRY * 0.30f),
                   std::max(2, int(eyeRX * 0.29f)), {255, 255, 255, 225});
        fillCircle(int(right + lookX - eyeRX * 0.28f), int(eyeY + lookY - eyeRY * 0.30f),
                   std::max(2, int(eyeRX * 0.29f)), {255, 255, 255, 225});
    }

    if (expression == BlobExpression::WORRIED || expression == BlobExpression::SAD) {
        drawCurve(left - eyeRX, eyeY - eyeRY * 1.55f, left + eyeRX, eyeY - eyeRY * 1.1f, -2, INK, 2);
        drawCurve(right - eyeRX, eyeY - eyeRY * 1.1f, right + eyeRX, eyeY - eyeRY * 1.55f, -2, INK, 2);
        drawCurve(cx - rx * 0.15f, mouthY + 3, cx + rx * 0.15f, mouthY + 3, -5, INK, 2);
        if (expression == BlobExpression::SAD)
            fillEllipse(int(left - eyeRX * 1.3f), int(eyeY + eyeRY * 1.5f), 3, 5, {225, 249, 255, 220});
    } else if (expression == BlobExpression::ANGRY) {
        drawCurve(left - eyeRX * 1.4f, eyeY - eyeRY * 1.5f,
                  left + eyeRX, eyeY - eyeRY * 0.85f, 1, INK, 2);
        drawCurve(right - eyeRX, eyeY - eyeRY * 0.85f,
                  right + eyeRX * 1.4f, eyeY - eyeRY * 1.5f, 1, INK, 2);
        drawCurve(cx - rx * 0.14f, mouthY + 1, cx + rx * 0.14f, mouthY + 1, -3, INK, 2);
    } else if (expression == BlobExpression::CONFUSED) {
        drawCurve(right - eyeRX, eyeY - eyeRY * 1.7f,
                  right + eyeRX, eyeY - eyeRY * 1.95f, -2, INK, 2);
        drawCurve(cx - rx * 0.13f, mouthY, cx + rx * 0.13f, mouthY - 2, 1, INK, 2);
    } else if (expression == BlobExpression::THINKING) {
        fillEllipse(int(cx), int(mouthY), std::max(3, int(rx * 0.045f)),
                    std::max(3, int(ry * 0.065f)), INK);
    } else if (expression == BlobExpression::EXCITED ||
               expression == BlobExpression::CELEBRATE ||
               expression == BlobExpression::EATING) {
        fillEllipse(int(cx), int(mouthY), int(rx * 0.16f), int(ry * 0.14f), INK);
        fillEllipse(int(cx), int(mouthY + ry * 0.06f), int(rx * 0.10f),
                    int(ry * 0.045f), {249, 136, 162, 220});
    } else if (expression == BlobExpression::SLEEPING || expression == BlobExpression::TIRED) {
        drawCurve(cx - rx * 0.08f, mouthY, cx + rx * 0.08f, mouthY, 2, INK, 2);
    } else if (expression == BlobExpression::PROUD) {
        drawCurve(cx - rx * 0.12f, mouthY + 1, cx + rx * 0.16f, mouthY - 2, 4, INK, 2);
    } else {
        drawCurve(cx - rx * 0.19f, mouthY - 2, cx + rx * 0.19f, mouthY - 2,
                  expression == BlobExpression::HAPPY || expression == BlobExpression::PLAYFUL ? 7 : 5,
                  INK, 2);
    }

    if (expression == BlobExpression::HAPPY || expression == BlobExpression::EXCITED ||
        expression == BlobExpression::SHY || expression == BlobExpression::PLAYFUL ||
        expression == BlobExpression::CELEBRATE) {
        fillEllipse(int(cx - rx * 0.57f), int(cy + ry * 0.22f),
                    int(rx * 0.13f), int(ry * 0.09f), BLUSH);
        fillEllipse(int(cx + rx * 0.57f), int(cy + ry * 0.22f),
                    int(rx * 0.13f), int(ry * 0.09f), BLUSH);
    }
    if (expression == BlobExpression::EXCITED || expression == BlobExpression::CELEBRATE) {
        fillCircle(int(cx - rx * 0.74f), int(cy - ry * 0.43f), 2, {255, 255, 255, 215});
        fillCircle(int(cx + rx * 0.72f), int(cy - ry * 0.35f), 2, {255, 255, 255, 215});
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
