#pragma once
#include <SDL2/SDL.h>
#include <memory>
#include <string>
#include <vector>

class TextRenderer {
public:
    TextRenderer(SDL_Renderer* renderer, const std::string& fontPath, float size);
    ~TextRenderer();
    float width(const std::string& text);
    void draw(const std::string& text, int x, int y, SDL_Color color);
    std::vector<std::string> wrap(const std::string& text, int width);
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
