#include "renderer.h"
#include <iostream>
#include <algorithm>
#include <cmath>

// ════════════════════════════════════════════════════════════════
//  Colour palette — Rimuru Tempest slime
// ════════════════════════════════════════════════════════════════
static const Color COL_OUTER     = {175, 210, 240, 165};   // translucent light blue body
static const Color COL_OUTLINE   = { 80, 130, 185, 210};   // blue outline
static const Color COL_INNER     = {115, 155, 200, 210};   // dark inner core
static const Color COL_INNER_LT  = {145, 190, 230, 170};   // lighter inner highlight
static const Color COL_HIGHLIGHT = {245, 250, 255, 175};   // specular white
static const Color COL_EYE       = { 40,  50,  75, 255};   // dark eye
static const Color COL_MOUTH     = { 55,  75, 120, 210};   // whisker lines

// ════════════════════════════════════════════════════════════════
//  Construction / Destruction
// ════════════════════════════════════════════════════════════════

Renderer::Renderer(SDL_Window* window, int w, int h) : width_(w), height_(h) {
    sdlRenderer_ = SDL_CreateRenderer(
        window, -1, SDL_RENDERER_ACCELERATED | SDL_RENDERER_PRESENTVSYNC);
    if (!sdlRenderer_)
        sdlRenderer_ = SDL_CreateRenderer(window, -1, SDL_RENDERER_SOFTWARE);
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

void Renderer::clear() {
    SDL_SetRenderDrawColor(sdlRenderer_, 0, 0, 0, 0);
    SDL_RenderClear(sdlRenderer_);
    if (shapeSurface_)
        SDL_FillRect(shapeSurface_, nullptr,
                     SDL_MapRGBA(shapeSurface_->format, 0, 0, 0, 0));
}

void Renderer::present() { SDL_RenderPresent(sdlRenderer_); }

// ════════════════════════════════════════════════════════════════
//  Outer body — translucent dome, gradient from lighter centre
// ════════════════════════════════════════════════════════════════

void Renderer::drawOuterBody(const std::vector<Vec2>& verts) {
    if (verts.size() < 3) return;

    float cx = 0, cy = 0;
    for (auto& v : verts) { cx += v.x; cy += v.y; }
    cx /= (float)verts.size();
    cy /= (float)verts.size();

    Color lighter = {
        (uint8_t)std::min(255, COL_OUTER.r + 35),
        (uint8_t)std::min(255, COL_OUTER.g + 30),
        (uint8_t)std::min(255, COL_OUTER.b + 15),
        (uint8_t)std::min(255, COL_OUTER.a + 20)
    };

    auto toSDL = [](Color c) -> SDL_Color { return {c.r, c.g, c.b, c.a}; };

    for (size_t i = 0; i < verts.size(); ++i) {
        size_t next = (i + 1) % verts.size();
        SDL_Vertex v0, v1, v2;
        v0.position  = {cx, cy};        v0.color = toSDL(lighter); v0.tex_coord = {0,0};
        v1.position  = {verts[i].x, verts[i].y};   v1.color = toSDL(COL_OUTER);  v1.tex_coord = {0,0};
        v2.position  = {verts[next].x, verts[next].y}; v2.color = toSDL(COL_OUTER);  v2.tex_coord = {0,0};
        SDL_Vertex tri[3] = {v0, v1, v2};
        SDL_RenderGeometry(sdlRenderer_, nullptr, tri, 3, nullptr, 0);
    }
}

// ════════════════════════════════════════════════════════════════
//  Outline — blue border, 2px thick
// ════════════════════════════════════════════════════════════════

void Renderer::drawOutline(const std::vector<Vec2>& verts) {
    if (verts.size() < 3) return;
    SDL_SetRenderDrawColor(sdlRenderer_, COL_OUTLINE.r, COL_OUTLINE.g,
                           COL_OUTLINE.b, COL_OUTLINE.a);
    for (size_t i = 0; i < verts.size(); ++i) {
        size_t next = (i + 1) % verts.size();
        for (int off = -1; off <= 1; ++off) {
            SDL_RenderDrawLineF(sdlRenderer_,
                                verts[i].x, verts[i].y + off,
                                verts[next].x, verts[next].y + off);
        }
    }
}

// ════════════════════════════════════════════════════════════════
//  Inner "core" body — the darker blob visible inside Rimuru
//  Much larger and more prominent than before
// ════════════════════════════════════════════════════════════════

void Renderer::drawInnerBody(float cx, float cy, float rx, float ry,
                             float time) {
    // The inner body is a blob shape sitting inside the dome.
    // Head on the left, body extending right — matching reference.
    float breathe = std::sin(time * 1.3f) * 2.0f;

    // === Main body oval (centre-right of dome) ===
    float bodyX  = cx + rx * 0.05f;
    float bodyY  = cy + ry * 0.15f;
    float bodyRX = rx * 0.42f;
    float bodyRY = ry * 0.28f + breathe * 0.4f;
    fillEllipse((int)bodyX, (int)bodyY, (int)bodyRX, (int)bodyRY, COL_INNER);

    // === Head circle (left side, overlapping body) ===
    float headX  = cx - rx * 0.20f;
    float headY  = cy - ry * 0.05f;
    float headR  = rx * 0.28f + breathe * 0.2f;
    fillCircle((int)headX, (int)headY, (int)headR, COL_INNER);

    // === Lighter highlight on the inner body for depth ===
    fillEllipse((int)(headX + headR * 0.1f), (int)(headY - headR * 0.25f),
                (int)(headR * 0.55f), (int)(headR * 0.4f), COL_INNER_LT);
}

// ════════════════════════════════════════════════════════════════
//  Specular highlights — white glossy spots, upper-left
// ════════════════════════════════════════════════════════════════

void Renderer::drawHighlights(float cx, float cy, float rx, float ry) {
    // Large oval highlight — upper left of dome
    float h1x = cx - rx * 0.32f;
    float h1y = cy - ry * 0.55f;
    fillEllipse((int)h1x, (int)h1y,
                (int)(rx * 0.20f), (int)(ry * 0.13f), COL_HIGHLIGHT);

    // Medium circle highlight — below and left
    float h2x = cx - rx * 0.50f;
    float h2y = cy - ry * 0.32f;
    fillCircle((int)h2x, (int)h2y, (int)(rx * 0.08f), COL_HIGHLIGHT);

    // Small dot highlight
    float h3x = cx - rx * 0.43f;
    float h3y = cy - ry * 0.18f;
    fillCircle((int)h3x, (int)h3y, (int)(rx * 0.04f),
               {255, 255, 255, 130});
}

// ════════════════════════════════════════════════════════════════
//  Face — BIG eye + prominent whisker-mouth
// ════════════════════════════════════════════════════════════════

void Renderer::drawFace(float cx, float cy, float rx, float ry, float time, BlobState state) {
    if (state == BlobState::BLINDFOLDED) {
        fillEllipse((int)cx, (int)(cy + ry * 0.02f), (int)(rx * 0.37f),
                    (int)(ry * 0.15f), COL_EYE);
        fillCircle((int)(cx - rx * 0.2f), (int)(cy - ry * 0.02f), 3,
                   {173, 224, 249, 220});
        return;
    }
    // ─── EYE ───
    // Large dark oval on the inner body's "head"
    float eyeX = cx - rx * 0.14f;
    float eyeY = cy - ry * 0.02f;
    float eyeRX = rx * 0.065f;
    float eyeRY = ry * 0.07f;

    // Subtle look-around
    float lookX = std::sin(time * 0.5f) * 2.0f;
    float lookY = state == BlobState::THINKING ? -3.0f : std::cos(time * 0.8f) * 1.5f;

    fillEllipse((int)(eyeX + lookX), (int)(eyeY + lookY),
                (int)eyeRX, (int)eyeRY, COL_EYE);

    // Tiny white eye highlight
    fillCircle((int)(eyeX + lookX - 1), (int)(eyeY + lookY - 2),
               (int)(eyeRX * 0.4f), {255, 255, 255, 200});

    // ─── WHISKER MOUTH ───
    // Three prominent lines extending from the face to the right
    SDL_SetRenderDrawColor(sdlRenderer_, COL_MOUTH.r, COL_MOUTH.g,
                           COL_MOUTH.b, COL_MOUTH.a);

    float mouthX = cx + rx * 0.02f;
    float mouthY = cy + ry * 0.15f;
    float lineLen = rx * 0.22f;
    float spacing = ry * 0.07f;

    for (int i = -1; i <= 1; ++i) {
        float y = mouthY + (float)i * spacing;
        float splay = (float)i * 0.15f;   // slight fan-out angle

        // Draw 3 parallel lines for thickness
        for (int t = -1; t <= 1; ++t) {
            SDL_RenderDrawLineF(sdlRenderer_,
                                mouthX, y + (float)t * 0.7f,
                                mouthX + lineLen,
                                y + splay * lineLen + (float)t * 0.7f);
        }
    }
}

// ════════════════════════════════════════════════════════════════
//  Shape mask
// ════════════════════════════════════════════════════════════════

void Renderer::stampShape(const std::vector<Vec2>& verts, float cx, float cy) {
    if (!shapeSurface_ || verts.empty()) return;

    // Find bounding ellipse
    float maxRX = 0, maxRYup = 0, maxRYdn = 0;
    for (auto& v : verts) {
        float dx = std::abs(v.x - cx);
        if (dx > maxRX) maxRX = dx;
        float dy = v.y - cy;
        if (dy < 0 && std::abs(dy) > maxRYup) maxRYup = std::abs(dy);
        if (dy > 0 && dy > maxRYdn) maxRYdn = dy;
    }
    float maxRY = std::max(maxRYup, maxRYdn);

    Uint32 opaque = SDL_MapRGBA(shapeSurface_->format, 255, 255, 255, 255);
    fillEllipseOnSurface(shapeSurface_, (int)cx, (int)cy,
                         (int)(maxRX + 10), (int)(maxRY + 10), opaque);
}

// ════════════════════════════════════════════════════════════════
//  Primitive helpers
// ════════════════════════════════════════════════════════════════

void Renderer::fillCircle(int cx, int cy, int r, Color c) {
    if (r <= 0) return;
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
    if (r <= 0) return;
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
