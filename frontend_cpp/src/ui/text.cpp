#include "text.h"
#include <fstream>
#include <iterator>
#include <map>
#include <stdexcept>
#define STB_TRUETYPE_IMPLEMENTATION
#include "stb_truetype.h"

namespace {
int codepoint(const std::string& text, size_t& offset) {
    unsigned char c = text[offset++];
    if (c < 128) return c;
    int extra = c >= 240 ? 3 : c >= 224 ? 2 : c >= 192 ? 1 : 0;
    int value = c & (extra == 3 ? 7 : extra == 2 ? 15 : 31);
    for (int i = 0; i < extra; ++i) {
        if (offset == text.size() || (static_cast<unsigned char>(text[offset]) & 192) != 128) return '?';
        value = (value << 6) | (static_cast<unsigned char>(text[offset++]) & 63);
    }
    return extra ? value : '?';
}
}

struct TextRenderer::Impl {
    struct Glyph { SDL_Texture* texture; int w, h, x, y; float advance; };
    SDL_Renderer* renderer;
    std::vector<unsigned char> bytes;
    stbtt_fontinfo font{};
    float scale;
    int ascent;
    std::map<int, Glyph> glyphs;
    Glyph& glyph(int point) {
        if (!stbtt_FindGlyphIndex(&font, point)) point = '?';
        auto found = glyphs.find(point);
        if (found != glyphs.end()) return found->second;
        int advance, bearing, w, h, x, y;
        stbtt_GetCodepointHMetrics(&font, point, &advance, &bearing);
        unsigned char* bitmap = stbtt_GetCodepointBitmap(&font, 0, scale, point, &w, &h, &x, &y);
        SDL_Texture* texture = nullptr;
        if (bitmap && w && h) {
            SDL_Surface* surface = SDL_CreateRGBSurfaceWithFormat(0, w, h, 32, SDL_PIXELFORMAT_RGBA32);
            if (!surface) { stbtt_FreeBitmap(bitmap, nullptr); throw std::runtime_error(SDL_GetError()); }
            for (int row = 0; row < h; ++row) {
                auto* pixels = reinterpret_cast<Uint32*>(static_cast<char*>(surface->pixels) + row * surface->pitch);
                for (int col = 0; col < w; ++col) pixels[col] = SDL_MapRGBA(surface->format, 255, 255, 255, bitmap[row * w + col]);
            }
            texture = SDL_CreateTextureFromSurface(renderer, surface);
            SDL_FreeSurface(surface);
            SDL_SetTextureBlendMode(texture, SDL_BLENDMODE_BLEND);
        }
        stbtt_FreeBitmap(bitmap, nullptr);
        return glyphs.emplace(point, Glyph{texture, w, h, x, y, advance * scale}).first->second;
    }
    ~Impl() { for (auto& item : glyphs) if (item.second.texture) SDL_DestroyTexture(item.second.texture); }
};

TextRenderer::TextRenderer(SDL_Renderer* renderer, const std::string& fontPath, float size)
    : impl_(std::make_unique<Impl>()) {
    impl_->renderer = renderer;
    std::ifstream file(fontPath, std::ios::binary);
    impl_->bytes.assign(std::istreambuf_iterator<char>(file), {});
    if (impl_->bytes.empty() || !stbtt_InitFont(&impl_->font, impl_->bytes.data(), 0))
        throw std::runtime_error("Could not load Blob's bundled font: " + fontPath);
    impl_->scale = stbtt_ScaleForPixelHeight(&impl_->font, size);
    int ascent, descent, gap;
    stbtt_GetFontVMetrics(&impl_->font, &ascent, &descent, &gap);
    impl_->ascent = static_cast<int>(ascent * impl_->scale);
}
TextRenderer::~TextRenderer() = default;
float TextRenderer::width(const std::string& text) {
    float width = 0;
    for (size_t i = 0; i < text.size();) width += impl_->glyph(codepoint(text, i)).advance;
    return width;
}
void TextRenderer::draw(const std::string& text, int x, int y, SDL_Color color) {
    float cursor = x;
    for (size_t i = 0; i < text.size();) {
        auto& glyph = impl_->glyph(codepoint(text, i));
        if (glyph.texture) {
            SDL_SetTextureColorMod(glyph.texture, color.r, color.g, color.b);
            SDL_SetTextureAlphaMod(glyph.texture, color.a);
            SDL_Rect rect{int(cursor) + glyph.x, y + impl_->ascent + glyph.y, glyph.w, glyph.h};
            SDL_RenderCopy(impl_->renderer, glyph.texture, nullptr, &rect);
        }
        cursor += glyph.advance;
    }
}
std::vector<std::string> TextRenderer::wrap(const std::string& text, int maxWidth) {
    std::vector<std::string> lines;
    std::string line;
    float used = 0;
    // Preserve whitespace and explicit newlines; prefer wrapping at word boundaries.
    for (size_t i = 0; i < text.size();) {
        size_t start = i;
        int point = codepoint(text, i);
        if (point == '\r') continue;
        if (point == '\n') { lines.push_back(line); line.clear(); used = 0; continue; }
        float advance = impl_->glyph(point).advance;
        if (used + advance > maxWidth && !line.empty()) {
            size_t space = line.find_last_of(' ');
            if (space != std::string::npos && space > line.size() / 2) {
                lines.push_back(line.substr(0, space));
                line = line.substr(space + 1);
                used = width(line);
            } else { lines.push_back(line); line.clear(); used = 0; }
        }
        line.append(text, start, i - start);
        used += advance;
    }
    lines.push_back(line);
    return lines;
}
