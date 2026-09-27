#include "text.h"
#include "bitmap_font.h"

#include <algorithm>
#include <sstream>

namespace ui {
void drawText(SDL_Renderer* renderer, int x, int y, const std::string& value,
              SDL_Color color, int scale) {
    if (!renderer || scale < 1) return;
    SDL_SetRenderDrawColor(renderer, color.r, color.g, color.b, color.a);
    int startX = x;
    for (unsigned char byte : value) {
        if (byte == '\n') {
            x = startX;
            y += BitmapFont::HEIGHT * scale + 2;
            continue;
        }
        if (byte >= 0x80 && byte <= 0xBF) continue; // Skip UTF-8 continuation bytes.
        char character = (byte >= 32 && byte <= 126) ? static_cast<char>(byte) : '?';
        const auto& rows = BitmapFont::GLYPHS[character - 32];
        for (int row = 0; row < BitmapFont::HEIGHT; ++row) {
            for (int col = 0; col < BitmapFont::WIDTH; ++col) {
                if (rows[row] & (1u << col)) {
                    SDL_Rect pixel{x + col * scale, y + row * scale, scale, scale};
                    SDL_RenderFillRect(renderer, &pixel);
                }
            }
        }
        x += BitmapFont::WIDTH * scale;
    }
}

std::vector<std::string> wrapText(const std::string& value, std::size_t columns) {
    columns = std::max<std::size_t>(columns, 1);
    std::vector<std::string> lines;
    std::istringstream input(value);
    std::string paragraph;
    while (std::getline(input, paragraph)) {
        std::istringstream words(paragraph);
        std::string word;
        std::string line;
        while (words >> word) {
            while (word.size() > columns) {
                if (!line.empty()) {
                    lines.push_back(line);
                    line.clear();
                }
                lines.push_back(word.substr(0, columns));
                word.erase(0, columns);
            }
            if (word.empty()) continue;
            if (!line.empty() && line.size() + 1 + word.size() > columns) {
                lines.push_back(line);
                line.clear();
            }
            if (!line.empty()) line += ' ';
            line += word;
        }
        lines.push_back(line);
    }
    if (lines.empty()) lines.emplace_back();
    return lines;
}
}
