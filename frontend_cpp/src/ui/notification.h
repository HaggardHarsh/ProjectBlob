#pragma once

#include <SDL2/SDL.h>
#include <string>

class NotificationManager {
public:
    NotificationManager();
    ~NotificationManager();
    void setAnchor(SDL_Window* anchor) { anchor_ = anchor; }
    void show(const std::string& text, unsigned int displayMs = 6000);
    void update(float dt);
    void render();

private:
    SDL_Window* window_ = nullptr;
    SDL_Renderer* renderer_ = nullptr;
    SDL_Window* anchor_ = nullptr;
    std::string text_;
    float remainingSeconds_ = 0.0f;
    bool dirty_ = false;
};
