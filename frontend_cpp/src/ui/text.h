#pragma once

#include <SDL2/SDL.h>
#include <string>
#include <vector>

namespace ui {
constexpr int glyphWidth = 10;
constexpr int glyphHeight = 12;

void drawText(SDL_Renderer* renderer, int x, int y, const std::string& value,
              SDL_Color color, int scale = 1);
std::vector<std::string> wrapText(const std::string& value, std::size_t columns);
}
