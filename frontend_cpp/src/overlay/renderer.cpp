#include "renderer.h"
#include <iostream>
#include <algorithm>
#include <cmath>

// ──────────────────────────────────────────────────────────────
// Construction / Destruction
// ──────────────────────────────────────────────────────────────

Renderer::Renderer(SDL_Window* window, int w, int h) : width_(w), height_(h) {
    sdlRenderer_ = SDL_CreateRenderer(
        window, -1, SDL_RENDERER_ACCELERATED | SDL_RENDERER_PRESENTVSYNC);
    if (!sdlRenderer_) {
        std::cerr << "HW renderer failed (" << SDL_GetError() << "), trying SW\n";
        sdlRenderer_ = SDL_CreateRenderer(window, -1, SDL_RENDERER_SOFTWARE);
    }
    if (!sdlRenderer_) {
        throw std::runtime_error("SDL_CreateRenderer failed: " +
                                 std::string(SDL_GetError()));
    }
    SDL_SetRenderDrawBlendMode(sdlRenderer_, SDL_BLENDMODE_BLEND);

    // Shape surface: 32-bit ARGB used by SDL_SetWindowShape
    shapeSurface_ = SDL_CreateRGBSurface(
        0, width_, height_, 32,
        0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000);
}

Renderer::~Renderer() {
    if (shapeSurface_) SDL_FreeSurface(shapeSurface_);
    if (sdlRenderer_)  SDL_DestroyRenderer(sdlRenderer_);
}

// ──────────────────────────────────────────────────────────────
// Frame management
// ──────────────────────────────────────────────────────────────

void Renderer::clear() {
    // Clear renderer to transparent black
    SDL_SetRenderDrawColor(sdlRenderer_, 0, 0, 0, 0);
    SDL_RenderClear(sdlRenderer_);
    // Clear shape surface to fully transparent
    if (shapeSurface_) {
        SDL_FillRect(shapeSurface_, nullptr,
                     SDL_MapRGBA(shapeSurface_->format, 0, 0, 0, 0));
    }
}

void Renderer::present() {
    SDL_RenderPresent(sdlRenderer_);
}

// ──────────────────────────────────────────────────────────────
// Blob body — filled polygon via triangle fan
// ──────────────────────────────────────────────────────────────

void Renderer::drawBlobMesh(const std::vector<Vec2>& vertices, Color color) {
    if (vertices.size() < 3) return;

    // Compute centroid
    float cx = 0.0f, cy = 0.0f;
    for (const auto& v : vertices) { cx += v.x; cy += v.y; }
    cx /= (float)vertices.size();
    cy /= (float)vertices.size();

    // Draw filled triangle fan on the renderer
    SDL_SetRenderDrawColor(sdlRenderer_, color.r, color.g, color.b, color.a);
    for (size_t i = 0; i < vertices.size(); ++i) {
        size_t next = (i + 1) % vertices.size();
        SDL_Vertex v0, v1, v2;

        auto toSDLColor = [&](Color c) -> SDL_Color {
            return {c.r, c.g, c.b, c.a};
        };

        // Slightly lighter centre for a cute 3D bulge look
        Color lighter = {
            (unsigned char)std::min(255, color.r + 40),
            (unsigned char)std::min(255, color.g + 40),
            (unsigned char)std::min(255, color.b + 40),
            color.a
        };

        v0.position = {cx, cy};
        v0.color    = toSDLColor(lighter);
        v0.tex_coord = {0, 0};

        v1.position = {vertices[i].x, vertices[i].y};
        v1.color    = toSDLColor(color);
        v1.tex_coord = {0, 0};

        v2.position = {vertices[next].x, vertices[next].y};
        v2.color    = toSDLColor(color);
        v2.tex_coord = {0, 0};

        SDL_Vertex tri[3] = {v0, v1, v2};
        SDL_RenderGeometry(sdlRenderer_, nullptr, tri, 3, nullptr, 0);
    }

    // Also stamp the shape onto the alpha-mask surface
    if (shapeSurface_) {
        // Compute approximate radius for a circle mask
        float maxR = 0;
        for (const auto& v : vertices) {
            float dx = v.x - cx, dy = v.y - cy;
            float r = std::sqrt(dx * dx + dy * dy);
            if (r > maxR) maxR = r;
        }
        Uint32 opaque = SDL_MapRGBA(shapeSurface_->format, 255, 255, 255, 255);
        fillCircleOnSurface(shapeSurface_, (int)cx, (int)cy, (int)(maxR + 6), opaque);
    }
}

// ──────────────────────────────────────────────────────────────
// Eyes
// ──────────────────────────────────────────────────────────────

void Renderer::drawEyes(float cx, float cy, float blobRadius, float time) {
    float eyeSpacing = blobRadius * 0.35f;
    float eyeY = cy - blobRadius * 0.15f;
    float eyeR = blobRadius * 0.18f;
    float pupilR = eyeR * 0.55f;

    // Subtle pupil tracking animation
    float pupilOffX = std::sin(time * 0.7f) * 2.0f;
    float pupilOffY = std::cos(time * 1.1f) * 1.5f;

    // Left eye
    fillCircle((int)(cx - eyeSpacing), (int)eyeY, (int)eyeR, {255, 255, 255, 255});
    fillCircle((int)(cx - eyeSpacing + pupilOffX), (int)(eyeY + pupilOffY),
               (int)pupilR, {30, 30, 30, 255});

    // Right eye
    fillCircle((int)(cx + eyeSpacing), (int)eyeY, (int)eyeR, {255, 255, 255, 255});
    fillCircle((int)(cx + eyeSpacing + pupilOffX), (int)(eyeY + pupilOffY),
               (int)pupilR, {30, 30, 30, 255});

    // Tiny white highlight on each pupil
    float hlR = pupilR * 0.35f;
    fillCircle((int)(cx - eyeSpacing + pupilOffX - 1), (int)(eyeY + pupilOffY - 2),
               (int)hlR, {255, 255, 255, 200});
    fillCircle((int)(cx + eyeSpacing + pupilOffX - 1), (int)(eyeY + pupilOffY - 2),
               (int)hlR, {255, 255, 255, 200});

    // Mark eye region on shape surface
    if (shapeSurface_) {
        Uint32 opaque = SDL_MapRGBA(shapeSurface_->format, 255, 255, 255, 255);
        fillCircleOnSurface(shapeSurface_, (int)(cx - eyeSpacing), (int)eyeY,
                            (int)eyeR + 2, opaque);
        fillCircleOnSurface(shapeSurface_, (int)(cx + eyeSpacing), (int)eyeY,
                            (int)eyeR + 2, opaque);
    }
}

// ──────────────────────────────────────────────────────────────
// Mouth
// ──────────────────────────────────────────────────────────────

void Renderer::drawMouth(float cx, float cy, float blobRadius, float time) {
    // A cute curved smile drawn as a series of small line segments
    float mouthY = cy + blobRadius * 0.15f;
    float mouthW = blobRadius * 0.35f;
    // Slight bounce to the smile
    float smileCurve = 3.0f + std::sin(time * 2.0f) * 1.5f;

    SDL_SetRenderDrawColor(sdlRenderer_, 40, 40, 40, 220);
    const int segments = 12;
    for (int i = 0; i < segments; ++i) {
        float t0 = (float)i / segments;
        float t1 = (float)(i + 1) / segments;
        float x0 = cx - mouthW + t0 * mouthW * 2.0f;
        float x1 = cx - mouthW + t1 * mouthW * 2.0f;
        // Parabolic curve for the smile
        float y0 = mouthY + smileCurve * (4.0f * t0 * (t0 - 1.0f) + 1.0f);
        float y1 = mouthY + smileCurve * (4.0f * t1 * (t1 - 1.0f) + 1.0f);
        SDL_RenderDrawLineF(sdlRenderer_, x0, y0, x1, y1);
        // Thicker line by drawing offset line
        SDL_RenderDrawLineF(sdlRenderer_, x0, y0 + 1, x1, y1 + 1);
    }
}

// ──────────────────────────────────────────────────────────────
// Helpers — filled circles on renderer and on surface
// ──────────────────────────────────────────────────────────────

void Renderer::fillCircle(int cx, int cy, int radius, Color color) {
    SDL_SetRenderDrawColor(sdlRenderer_, color.r, color.g, color.b, color.a);
    for (int dy = -radius; dy <= radius; ++dy) {
        int dx = (int)std::sqrt((float)(radius * radius - dy * dy));
        SDL_RenderDrawLine(sdlRenderer_, cx - dx, cy + dy, cx + dx, cy + dy);
    }
}

void Renderer::fillCircleOnSurface(SDL_Surface* surf, int cx, int cy,
                                   int radius, Uint32 color) {
    SDL_LockSurface(surf);
    Uint32* pixels = (Uint32*)surf->pixels;
    int pitch = surf->pitch / 4;
    for (int dy = -radius; dy <= radius; ++dy) {
        int dx = (int)std::sqrt((float)(radius * radius - dy * dy));
        int py = cy + dy;
        if (py < 0 || py >= surf->h) continue;
        int x0 = std::max(0, cx - dx);
        int x1 = std::min(surf->w - 1, cx + dx);
        for (int px = x0; px <= x1; ++px) {
            pixels[py * pitch + px] = color;
        }
    }
    SDL_UnlockSurface(surf);
}
