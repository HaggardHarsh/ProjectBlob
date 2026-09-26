#include "renderer.h"
#include <iostream>
#include <algorithm>
#include <cmath>

// ════════════════════════════════════════════════════════════════
//  Colour palette — Rimuru slime
// ════════════════════════════════════════════════════════════════
static const Color COL_OUTER     = {185, 215, 240, 160};   // translucent light blue
static const Color COL_OUTLINE   = { 95, 140, 190, 200};   // thin blue border
static const Color COL_INNER     = {130, 170, 215, 200};   // darker inner core
static const Color COL_INNER_LT  = {155, 195, 235, 180};   // lighter part of inner
static const Color COL_HIGHLIGHT = {255, 255, 255, 160};   // specular white
static const Color COL_EYE       = { 50,  60,  85, 255};   // dark eye dot
static const Color COL_MOUTH     = { 65,  85, 130, 180};   // whisker lines

// ════════════════════════════════════════════════════════════════
//  Construction / Destruction
// ════════════════════════════════════════════════════════════════

Renderer::Renderer(SDL_Window* window, int w, int h) : width_(w), height_(h) {
    sdlRenderer_ = SDL_CreateRenderer(
        window, -1, SDL_RENDERER_ACCELERATED | SDL_RENDERER_PRESENTVSYNC);
    if (!sdlRenderer_) {
        std::cerr << "HW renderer failed, trying SW\n";
        sdlRenderer_ = SDL_CreateRenderer(window, -1, SDL_RENDERER_SOFTWARE);
    }
    if (!sdlRenderer_)
        throw std::runtime_error("SDL_CreateRenderer failed");

    SDL_SetRenderDrawBlendMode(sdlRenderer_, SDL_BLENDMODE_BLEND);

    shapeSurface_ = SDL_CreateRGBSurface(
        0, width_, height_, 32,
        0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000);
}

Renderer::~Renderer() {
    if (shapeSurface_) SDL_FreeSurface(shapeSurface_);
    if (sdlRenderer_)  SDL_DestroyRenderer(sdlRenderer_);
}

// ════════════════════════════════════════════════════════════════
//  Frame management
// ════════════════════════════════════════════════════════════════

void Renderer::clear() {
    SDL_SetRenderDrawColor(sdlRenderer_, 0, 0, 0, 0);
    SDL_RenderClear(sdlRenderer_);
    if (shapeSurface_)
        SDL_FillRect(shapeSurface_, nullptr,
                     SDL_MapRGBA(shapeSurface_->format, 0, 0, 0, 0));
}

void Renderer::present() { SDL_RenderPresent(sdlRenderer_); }

// ════════════════════════════════════════════════════════════════
//  Outer body — filled triangle fan, translucent light blue
// ════════════════════════════════════════════════════════════════

void Renderer::drawOuterBody(const std::vector<Vec2>& verts) {
    if (verts.size() < 3) return;

    float cx = 0, cy = 0;
    for (auto& v : verts) { cx += v.x; cy += v.y; }
    cx /= (float)verts.size();
    cy /= (float)verts.size();

    // Slightly lighter centre for a 3-D gel look
    Color lighter = {
        (uint8_t)std::min(255, COL_OUTER.r + 30),
        (uint8_t)std::min(255, COL_OUTER.g + 25),
        (uint8_t)std::min(255, COL_OUTER.b + 15),
        COL_OUTER.a
    };

    auto toSDL = [](Color c) -> SDL_Color { return {c.r, c.g, c.b, c.a}; };

    for (size_t i = 0; i < verts.size(); ++i) {
        size_t next = (i + 1) % verts.size();
        SDL_Vertex v0, v1, v2;

        v0.position  = {cx, cy};
        v0.color     = toSDL(lighter);
        v0.tex_coord = {0, 0};

        v1.position  = {verts[i].x, verts[i].y};
        v1.color     = toSDL(COL_OUTER);
        v1.tex_coord = {0, 0};

        v2.position  = {verts[next].x, verts[next].y};
        v2.color     = toSDL(COL_OUTER);
        v2.tex_coord = {0, 0};

        SDL_Vertex tri[3] = {v0, v1, v2};
        SDL_RenderGeometry(sdlRenderer_, nullptr, tri, 3, nullptr, 0);
    }
}

// ════════════════════════════════════════════════════════════════
//  Outline — thin blue border connecting vertices
// ════════════════════════════════════════════════════════════════

void Renderer::drawOutline(const std::vector<Vec2>& verts) {
    if (verts.size() < 3) return;
    SDL_SetRenderDrawColor(sdlRenderer_, COL_OUTLINE.r, COL_OUTLINE.g,
                           COL_OUTLINE.b, COL_OUTLINE.a);
    for (size_t i = 0; i < verts.size(); ++i) {
        size_t next = (i + 1) % verts.size();
        SDL_RenderDrawLineF(sdlRenderer_,
                            verts[i].x, verts[i].y,
                            verts[next].x, verts[next].y);
        // Double-up for a slightly thicker line
        SDL_RenderDrawLineF(sdlRenderer_,
                            verts[i].x, verts[i].y + 1,
                            verts[next].x, verts[next].y + 1);
    }
}

// ════════════════════════════════════════════════════════════════
//  Inner "core" body — darker blue blob inside the dome
//  This mimics the Rimuru inner body silhouette.
// ════════════════════════════════════════════════════════════════

void Renderer::drawInnerBody(float cx, float cy, float rx, float ry,
                             float time) {
    // The inner core is a small blob shape sitting in the lower portion.
    // It has a "head" on the left and a "body" extending right, like
    // the reference image.

    float bodyX  = cx + rx * 0.02f;        // slightly right of centre
    float bodyY  = cy + ry * 0.25f;        // lower portion
    float bodyRX = rx * 0.38f;
    float bodyRY = ry * 0.28f;

    float headX  = cx - rx * 0.18f;        // head to the left
    float headY  = cy + ry * 0.02f;
    float headR  = rx * 0.22f;

    // Subtle breathing animation
    float breathe = std::sin(time * 1.5f) * 1.5f;
    bodyRY += breathe * 0.3f;
    headR  += breathe * 0.15f;

    // Draw body ellipse
    fillEllipse((int)bodyX, (int)bodyY, (int)bodyRX, (int)bodyRY, COL_INNER);

    // Draw head circle (overlapping body to form connected shape)
    fillCircle((int)headX, (int)headY, (int)headR, COL_INNER);

    // Lighter highlight stripe on the inner body for depth
    fillEllipse((int)(bodyX - bodyRX * 0.15f), (int)(bodyY - bodyRY * 0.3f),
                (int)(bodyRX * 0.5f), (int)(bodyRY * 0.35f), COL_INNER_LT);
}

// ════════════════════════════════════════════════════════════════
//  Specular highlights — white ovals on upper-left
// ════════════════════════════════════════════════════════════════

void Renderer::drawHighlights(float cx, float cy, float rx, float ry) {
    // Large highlight — upper-left of dome
    float h1x = cx - rx * 0.30f;
    float h1y = cy - ry * 0.55f;
    fillEllipse((int)h1x, (int)h1y, (int)(rx * 0.18f), (int)(ry * 0.14f),
                COL_HIGHLIGHT);

    // Small highlight — just below and left of the large one
    float h2x = cx - rx * 0.48f;
    float h2y = cy - ry * 0.35f;
    fillCircle((int)h2x, (int)h2y, (int)(rx * 0.06f), COL_HIGHLIGHT);

    // Tiny dot highlight
    float h3x = cx - rx * 0.42f;
    float h3y = cy - ry * 0.22f;
    fillCircle((int)h3x, (int)h3y, (int)(rx * 0.03f),
               {255, 255, 255, 120});
}

// ════════════════════════════════════════════════════════════════
//  Face — single dot eye + whisker mouth lines
// ════════════════════════════════════════════════════════════════

void Renderer::drawFace(float cx, float cy, float rx, float ry, float time) {
    // Eye position — on the inner body's "head" area
    float eyeX = cx - rx * 0.12f;
    float eyeY = cy + ry * 0.0f;
    float eyeR = rx * 0.04f;

    // Subtle look-around animation
    float lookX = std::sin(time * 0.6f) * 1.0f;
    float lookY = std::cos(time * 0.9f) * 0.8f;

    fillCircle((int)(eyeX + lookX), (int)(eyeY + lookY), (int)eyeR, COL_EYE);

    // Whisker/mouth lines — three small horizontal lines extending right
    SDL_SetRenderDrawColor(sdlRenderer_, COL_MOUTH.r, COL_MOUTH.g,
                           COL_MOUTH.b, COL_MOUTH.a);
    float mouthStartX = cx + rx * 0.0f;
    float mouthY      = cy + ry * 0.20f;
    float lineLen      = rx * 0.18f;
    float spacing      = ry * 0.06f;

    for (int i = -1; i <= 1; ++i) {
        float y = mouthY + (float)i * spacing;
        float angle = (float)i * 0.12f;  // slight splay
        SDL_RenderDrawLineF(sdlRenderer_,
                            mouthStartX, y,
                            mouthStartX + lineLen, y + angle * lineLen);
        // Thicken
        SDL_RenderDrawLineF(sdlRenderer_,
                            mouthStartX, y + 0.5f,
                            mouthStartX + lineLen, y + angle * lineLen + 0.5f);
    }
}

// ════════════════════════════════════════════════════════════════
//  Shape mask — stamp opaque region for SDL_SetWindowShape
// ════════════════════════════════════════════════════════════════

void Renderer::stampShape(const std::vector<Vec2>& verts, float cx, float cy) {
    if (!shapeSurface_ || verts.empty()) return;

    float maxR = 0;
    for (auto& v : verts) {
        float dx = v.x - cx, dy = v.y - cy;
        float r = std::sqrt(dx * dx + dy * dy);
        if (r > maxR) maxR = r;
    }

    Uint32 opaque = SDL_MapRGBA(shapeSurface_->format, 255, 255, 255, 255);
    // Use an ellipse that covers the full dome
    fillEllipseOnSurface(shapeSurface_, (int)cx, (int)cy,
                         (int)(maxR + 8), (int)(maxR * 0.7f + 8), opaque);
}

// ════════════════════════════════════════════════════════════════
//  Primitive helpers
// ════════════════════════════════════════════════════════════════

void Renderer::fillCircle(int cx, int cy, int r, Color c) {
    SDL_SetRenderDrawColor(sdlRenderer_, c.r, c.g, c.b, c.a);
    for (int dy = -r; dy <= r; ++dy) {
        int dx = (int)std::sqrt((float)(r * r - dy * dy));
        SDL_RenderDrawLine(sdlRenderer_, cx - dx, cy + dy, cx + dx, cy + dy);
    }
}

void Renderer::fillEllipse(int cx, int cy, int rx, int ry, Color c) {
    if (rx <= 0 || ry <= 0) return;
    SDL_SetRenderDrawColor(sdlRenderer_, c.r, c.g, c.b, c.a);
    for (int dy = -ry; dy <= ry; ++dy) {
        float t = (float)dy / (float)ry;
        int dx = (int)(std::sqrt(1.0f - t * t) * (float)rx);
        SDL_RenderDrawLine(sdlRenderer_, cx - dx, cy + dy, cx + dx, cy + dy);
    }
}

void Renderer::fillCircleOnSurface(SDL_Surface* surf, int cx, int cy,
                                   int r, Uint32 color) {
    SDL_LockSurface(surf);
    Uint32* px = (Uint32*)surf->pixels;
    int pitch = surf->pitch / 4;
    for (int dy = -r; dy <= r; ++dy) {
        int dx = (int)std::sqrt((float)(r * r - dy * dy));
        int py = cy + dy;
        if (py < 0 || py >= surf->h) continue;
        int x0 = std::max(0, cx - dx);
        int x1 = std::min(surf->w - 1, cx + dx);
        for (int px_ = x0; px_ <= x1; ++px_)
            px[py * pitch + px_] = color;
    }
    SDL_UnlockSurface(surf);
}

void Renderer::fillEllipseOnSurface(SDL_Surface* surf, int cx, int cy,
                                    int rx, int ry, Uint32 color) {
    if (rx <= 0 || ry <= 0) return;
    SDL_LockSurface(surf);
    Uint32* px = (Uint32*)surf->pixels;
    int pitch = surf->pitch / 4;
    for (int dy = -ry; dy <= ry; ++dy) {
        float t = (float)dy / (float)ry;
        int dx = (int)(std::sqrt(1.0f - t * t) * (float)rx);
        int py = cy + dy;
        if (py < 0 || py >= surf->h) continue;
        int x0 = std::max(0, cx - dx);
        int x1 = std::min(surf->w - 1, cx + dx);
        for (int px_ = x0; px_ <= x1; ++px_)
            px[py * pitch + px_] = color;
    }
    SDL_UnlockSurface(surf);
}
