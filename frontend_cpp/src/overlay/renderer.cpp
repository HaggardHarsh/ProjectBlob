#include "renderer.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <stdexcept>

namespace {
constexpr Color TOP{207, 239, 248, 255};
constexpr Color BASE{178, 222, 240, 255};
constexpr Color OUTLINE{195, 232, 244, 255};
constexpr Color INK{8, 28, 39, 255};
float unit(float value) { return std::clamp(value, 0.0f, 1.0f); }
}

Renderer::Renderer(SDL_Window* window, int w, int h) : width_(w), height_(h) {
    SDL_SetHint(SDL_HINT_RENDER_SCALE_QUALITY, "linear");
    sdlRenderer_ = SDL_CreateRenderer(window, -1, SDL_RENDERER_ACCELERATED | SDL_RENDERER_TARGETTEXTURE);
    if (!sdlRenderer_) sdlRenderer_ = SDL_CreateRenderer(window, -1, SDL_RENDERER_SOFTWARE);
    if (!sdlRenderer_) throw std::runtime_error("SDL_CreateRenderer failed");
    SDL_SetRenderDrawBlendMode(sdlRenderer_, SDL_BLENDMODE_BLEND);
    shapeSurface_ = SDL_CreateRGBSurface(0, width_, height_, 32,
                                        0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000);
    if (!shapeSurface_) {
        SDL_DestroyRenderer(sdlRenderer_);
        throw std::runtime_error("SDL_CreateRGBSurface failed");
    }
    // Draw at double resolution and downsample, including software/headless mode.
    scene_ = SDL_CreateTexture(sdlRenderer_, SDL_PIXELFORMAT_RGBA8888,
                              SDL_TEXTUREACCESS_TARGET, w * 2, h * 2);
    if (scene_) SDL_SetTextureBlendMode(scene_, SDL_BLENDMODE_NONE);
}

Renderer::~Renderer() {
    if (scene_) SDL_DestroyTexture(scene_);
    if (shapeSurface_) SDL_FreeSurface(shapeSurface_);
    if (sdlRenderer_) SDL_DestroyRenderer(sdlRenderer_);
}

void Renderer::clear() {
    SDL_SetRenderTarget(sdlRenderer_, scene_);
    SDL_RenderSetScale(sdlRenderer_, scene_ ? 2.0f : 1.0f, scene_ ? 2.0f : 1.0f);
    SDL_SetRenderDrawColor(sdlRenderer_, 0, 0, 0, 0);
    SDL_RenderClear(sdlRenderer_);
    SDL_FillRect(shapeSurface_, nullptr, SDL_MapRGBA(shapeSurface_->format, 0, 0, 0, 0));
}

void Renderer::present() {
    if (scene_) {
        SDL_SetRenderTarget(sdlRenderer_, nullptr);
        SDL_RenderSetScale(sdlRenderer_, 1.0f, 1.0f);
        SDL_RenderCopy(sdlRenderer_, scene_, nullptr, nullptr);
    }
    SDL_RenderPresent(sdlRenderer_);
}

int Renderer::readPixels(void* pixels, int pitch) {
    if (!pixels || pitch < width_ * 4 || !scene_) return -1;
    SDL_Texture* output = SDL_CreateTexture(sdlRenderer_, SDL_PIXELFORMAT_RGBA8888,
                                            SDL_TEXTUREACCESS_TARGET, width_, height_);
    if (!output) return -1;
    SDL_Texture* previous = SDL_GetRenderTarget(sdlRenderer_);
    int result = SDL_SetRenderTarget(sdlRenderer_, output);
    if (!result) {
        SDL_RenderSetScale(sdlRenderer_, 1, 1);
        result = SDL_RenderCopy(sdlRenderer_, scene_, nullptr, nullptr);
        if (!result) result = SDL_RenderReadPixels(sdlRenderer_, nullptr, SDL_PIXELFORMAT_RGBA8888, pixels, pitch);
    }
    SDL_SetRenderTarget(sdlRenderer_, previous);
    SDL_DestroyTexture(output);
    if (result) return result;
    // Filtering the transparent render target produces premultiplied edge colors.
    // Export straight alpha so previews composite cleanly on light and dark surfaces.
    for (int y = 0; y < height_; ++y) for (int x = 0; x < width_; ++x) {
        auto* address = static_cast<unsigned char*>(pixels) + y * pitch + x * 4;
        Uint32 pixel; std::memcpy(&pixel, address, 4);
        const unsigned alpha = pixel & 255;
        if (alpha > 0 && alpha < 255) {
            const unsigned r = std::min(255u, (pixel >> 24) * 255 / alpha);
            const unsigned g = std::min(255u, ((pixel >> 16) & 255) * 255 / alpha);
            const unsigned b = std::min(255u, ((pixel >> 8) & 255) * 255 / alpha);
            pixel = (r << 24) | (g << 16) | (b << 8) | alpha;
            std::memcpy(address, &pixel, 4);
        }
    }
    return 0;
}

void Renderer::drawShadow(float cx, float baseline, float rx, float lift) {
    const float strength = std::clamp(1.0f - lift / 35.0f, 0.35f, 1.0f);
    for (int ring = 5; ring > 0; --ring)
        fillEllipse(int(cx), int(baseline), int(rx * (0.69f + ring * 0.035f)),
                    ring, {32, 90, 110, Uint8(5 * strength)});
}

void Renderer::drawOuterBody(const std::vector<Vec2>& verts) {
    if (verts.size() < 3) return;
    float minY = verts.front().y, maxY = minY;
    for (const auto& v : verts) {
        minY = std::min(minY, v.y);
        maxY = std::max(maxY, v.y);
    }
    std::vector<float> intersections;
    intersections.reserve(verts.size());
    for (float y = std::max(0.0f, std::floor(minY));
         y <= std::min(float(height_ - 1), std::ceil(maxY)); y += 0.5f) {
        intersections.clear();
        const float sampleY = y + 0.25f;
        for (size_t i = 0; i < verts.size(); ++i) {
            const auto& a = verts[i];
            const auto& b = verts[(i + 1) % verts.size()];
            if ((a.y <= sampleY && b.y > sampleY) || (b.y <= sampleY && a.y > sampleY)) {
                intersections.push_back(a.x + (sampleY - a.y) * (b.x - a.x) / (b.y - a.y));
            }
        }
        std::sort(intersections.begin(), intersections.end());
        const float t = unit((y - minY) / std::max(1.0f, maxY - minY));
        const float light = 0.015f * std::sin(t * 3.14159f);
        SDL_SetRenderDrawColor(sdlRenderer_,
                               Uint8(TOP.r + (BASE.r - TOP.r) * t + light * 255),
                               Uint8(TOP.g + (BASE.g - TOP.g) * t + light * 110),
                               Uint8(TOP.b + (BASE.b - TOP.b) * t), 255);
        for (size_t i = 0; i + 1 < intersections.size(); i += 2) {
            const float left = std::max(0.0f, intersections[i]);
            const float right = std::min(float(width_ - 1), intersections[i + 1]);
            if (right >= left) SDL_RenderDrawLineF(sdlRenderer_, left, y, right, y);
        }
        // A soft, asymmetric blue core sits inside the pale jelly shell.
        // Clip it to each body span so the shading follows squash and stretch.
        if (t > 0.18f && t < 0.97f) {
            const float u = (t - 0.18f) / 0.79f;
            const float pinch = 1.0f - 0.26f * std::exp(-std::pow((u - 0.53f) / 0.13f, 2));
            SDL_SetRenderDrawColor(sdlRenderer_, 137, 178, 222, 120);
            for (size_t i = 0; i + 1 < intersections.size(); i += 2) {
                const float span = intersections[i + 1] - intersections[i];
                const float center = (intersections[i] + intersections[i + 1]) * 0.5f +
                                     span * (0.08f * std::cos(u * 4.4f));
                const float half = span * 0.39f * std::sqrt(std::sin(u * 3.14159265f)) * pinch;
                SDL_RenderDrawLineF(sdlRenderer_, std::max(intersections[i] + 2, center - half), y,
                                    std::min(intersections[i + 1] - 2, center + half), y);
            }
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
    const float flatten = std::min(1.0f, ry / std::max(1.0f, rx * 0.7f));
    fillTiltedEllipse(cx - rx * 0.28f, cy - ry * 0.65f, rx * 0.42f, ry * 0.14f,
                      -0.43f * flatten, {251, 255, 255, 255});
    fillTiltedEllipse(cx - rx * 0.76f, cy - ry * 0.20f, rx * 0.09f, ry * 0.21f,
                      0.28f * flatten, {250, 255, 255, 235});
    fillTiltedEllipse(cx + rx * 0.38f, cy - ry * 0.43f, rx * 0.075f, ry * 0.06f,
                      0, {221, 247, 253, 210});
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
    stroke({x0, y0}, {(x0 + x1) * 0.5f, (y0 + y1) * 0.5f + bend * 2},
           {x1, y1}, color, float(thickness));
}

void Renderer::stroke(Vec2 start, Vec2 control, Vec2 end, Color color, float width, bool tapered) {
    constexpr int steps = 32;
    std::array<SDL_Vertex, (steps + 1) * 2> vertices{};
    std::array<int, steps * 6> indices{};
    const SDL_Color ink{color.r, color.g, color.b, color.a};
    for (int i = 0; i <= steps; ++i) {
        const float t = i / float(steps), a = 1.0f - t;
        const Vec2 p = start * (a * a) + control * (2 * a * t) + end * (t * t);
        const Vec2 d = ((control - start) * a + (end - control) * t).normalized();
        const float r = width * 0.5f * (tapered ? 0.18f + 0.82f * std::sqrt(std::sin(t * 3.1415926f)) : 1.0f);
        vertices[i * 2] = {{p.x - d.y * r, p.y + d.x * r}, ink, {0, 0}};
        vertices[i * 2 + 1] = {{p.x + d.y * r, p.y - d.x * r}, ink, {0, 0}};
        if (i < steps) {
            const int at = i * 2;
            indices[i * 6] = at; indices[i * 6 + 1] = at + 1; indices[i * 6 + 2] = at + 2;
            indices[i * 6 + 3] = at + 1; indices[i * 6 + 4] = at + 3; indices[i * 6 + 5] = at + 2;
        }
    }
    SDL_RenderGeometry(sdlRenderer_, nullptr, vertices.data(), int(vertices.size()), indices.data(), int(indices.size()));
}

void Renderer::drawFace(float cx, float cy, float rx, float ry, float,
                        BlobState state, const BlobPose& pose) {
    const float eyeY = cy - ry * (pose.melt > 0.5f ? 0.04f : 0.16f) + pose.gazeY * 2.0f;
    const float eyeOffset = rx * 0.34f;
    const int eyeRX = std::max(3, int(rx * 0.12f * pose.eyeSize));
    const int eyeRY = std::max(1, int(ry * 0.22f * pose.eyeSize * pose.eyeOpen));
    const bool protectedScreen = state == BlobState::BLINDFOLDED;
    const bool hidden = protectedScreen && pose.attention < 0.55f;
    if (protectedScreen) {
        // Keep protection visible while lifting the mask for local play.
        const float maskY = eyeY - ry * 0.65f * pose.attention;
        fillEllipse(int(cx), int(maskY), int(rx * 0.73f), std::max(4, int(ry * (0.27f - pose.attention * 0.06f))), {43, 84, 106, 245});
        drawCurve(cx - rx * 0.50f, maskY - ry * 0.14f, cx + rx * 0.50f, maskY - ry * 0.14f,
                  -1.2f, {94, 146, 166, 150}, 1);
    }
    for (int side : {-1, 1}) {
        const float x = cx + side * eyeOffset + pose.gazeX * 2.0f;
        const float y = eyeY + (side > 0 ? pose.eyeAsymmetry * 4.0f : 0.0f);
        const float asymmetry = side > 0 ? 1.0f - pose.eyeAsymmetry * 0.8f : 1.0f;
        const int thisRY = std::max(1, int(eyeRY * asymmetry));
        const float eyeStroke = std::max(2.0f, rx * 0.062f);
        if (!hidden && pose.eyeSqueeze > 0.3f) {
            // Broad, pinched eye strokes echo the reference's scrunched expression.
            const float outward = rx * (0.48f + 0.29f * pose.eyeSqueeze);
            const float inward = rx * 0.09f;
            stroke({cx + side * outward, y - ry * 0.10f},
                   {cx + side * rx * 0.42f, y - ry * 0.07f},
                   {cx + side * inward, y + ry * 0.17f}, INK, eyeStroke + 0.7f, true);
            stroke({cx + side * rx * 0.23f, y + ry * 0.04f},
                   {cx + side * rx * 0.18f, y + ry * 0.07f},
                   {cx + side * rx * 0.12f, y + ry * 0.11f}, INK, 1.3f, true);
        } else if (hidden || thisRY <= 2 || pose.eyeSmile > 0.45f || (side > 0 && pose.eyeAsymmetry > 0.65f)) {
            const float half = eyeRX * (hidden ? 1.1f : 1.2f + pose.eyeSmile * 0.7f);
            const float bend = hidden ? 1.0f : pose.eyeSmile > 0.2f ? -ry * 0.13f : 1.2f;
            stroke({x - half, y}, {x, y + bend * 2}, {x + half, y},
                   hidden ? Color{198, 229, 237, 255} : INK, eyeStroke, true);
        } else {
            fillEllipse(int(x), int(y), eyeRX, thisRY, INK);
            fillCircle(int(x - eyeRX * 0.3f), int(y - thisRY * 0.36f),
                       std::max(1, eyeRX / 3), {239, 253, 255, 235});
            fillCircle(int(x + eyeRX * 0.25f), int(y + thisRY * 0.35f), 1, {115, 184, 209, 130});
        }
        if (!hidden && pose.eyeSqueeze < 0.3f && std::abs(pose.eyeTilt) > 0.12f) {
            const float tilt = pose.eyeTilt * (side < 0 ? 1.0f : -1.0f);
            stroke({x - eyeRX - 2, y - thisRY - 3 - tilt * 5},
                   {x, y - thisRY - 5}, {x + eyeRX + 2, y - thisRY - 3 + tilt * 5}, INK, 2.2f, true);
        }
    }
    const float mouthY = cy + ry * (pose.melt > 0.5f ? 0.49f : 0.29f);
    const float mouthHalf = std::max(3.0f, rx * 0.20f * pose.mouthWidth);
    if (pose.mouthRound > 0.55f) {
        fillEllipse(int(cx), int(mouthY), std::max(3, int(mouthHalf * 0.58f)),
                    std::max(3, int(ry * 0.22f * pose.mouthOpen)), INK);
    } else if (pose.mouthOpen > 0.16f) {
        const int mouthHeight = std::max(2, int(ry * 0.22f * pose.mouthOpen));
        fillEllipse(int(cx), int(mouthY + 1), std::max(4, int(mouthHalf * 0.95f)), mouthHeight, INK);
        if (pose.mouthSmile > 0.8f && mouthHeight > 4)
            fillEllipse(int(cx), int(mouthY + mouthHeight * 0.55f), std::max(2, int(mouthHalf * 0.48f)),
                        std::max(1, mouthHeight / 3), {242, 151, 179, 255});
        drawCurve(cx - mouthHalf, mouthY - 1, cx + mouthHalf, mouthY - 1,
                  pose.mouthSmile * 2.0f, INK, 1);
    } else {
        drawCurve(cx - mouthHalf, mouthY, cx + mouthHalf,
                  mouthY + pose.mouthSkew * 3.0f, pose.mouthSmile * 3.8f, INK, 2);
    }
    if (pose.blush > 0.05f) {
        const Color blush{239, 130, 167, Uint8(160 * pose.blush)};
        fillEllipse(int(cx - rx * 0.53f), int(cy + ry * 0.12f),
                    std::max(3, int(rx * 0.15f)), std::max(2, int(ry * 0.085f)), blush);
        fillEllipse(int(cx + rx * 0.53f), int(cy + ry * 0.12f),
                    std::max(3, int(rx * 0.15f)), std::max(2, int(ry * 0.085f)), blush);
    }
    if (pose.tears > 0.05f && !hidden) {
        for (int side : {-1, 1}) {
            const float x = cx + side * rx * 0.43f;
            const float y = eyeY + ry * 0.37f;
            fillTiltedEllipse(x, y, rx * 0.055f, ry * 0.22f, -side * 0.12f,
                              {75, 161, 219, Uint8(220 * pose.tears)});
            stroke({x - 0.5f, y - ry * 0.13f}, {x - 1, y}, {x, y + ry * 0.10f},
                   {241, 254, 255, Uint8(230 * pose.tears)}, 1.2f);
        }
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
    fillTiltedEllipse(float(cx), float(cy), float(rx), float(ry), 0, color);
}

void Renderer::fillTiltedEllipse(float cx, float cy, float rx, float ry, float rotation, Color color) {
    if (rx <= 0 || ry <= 0) return;
    constexpr int segments = 48;
    std::array<SDL_Vertex, segments + 1> vertices{};
    std::array<int, segments * 3> indices{};
    const SDL_Color ink{color.r, color.g, color.b, color.a};
    vertices[0] = {{float(cx), float(cy)}, ink, {0, 0}};
    for (int i = 0; i < segments; ++i) {
        const float angle = i * 6.2831853f / segments;
        const float x = rx * std::cos(angle), y = ry * std::sin(angle);
        vertices[i + 1] = {{cx + x * std::cos(rotation) - y * std::sin(rotation),
                            cy + x * std::sin(rotation) + y * std::cos(rotation)}, ink, {0, 0}};
        indices[i * 3] = 0; indices[i * 3 + 1] = i + 1; indices[i * 3 + 2] = (i + 1) % segments + 1;
    }
    SDL_RenderGeometry(sdlRenderer_, nullptr, vertices.data(), int(vertices.size()), indices.data(), int(indices.size()));
}
