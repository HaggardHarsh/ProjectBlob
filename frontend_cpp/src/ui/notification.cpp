#include "notification.h"
#include "text.h"

#include <algorithm>
#include <iostream>

NotificationManager::NotificationManager() {
    window_ = SDL_CreateWindow("Blob notification", SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED,
                               480, 110, SDL_WINDOW_HIDDEN | SDL_WINDOW_BORDERLESS |
                               SDL_WINDOW_ALWAYS_ON_TOP | SDL_WINDOW_SKIP_TASKBAR);
    if (!window_) {
        std::cerr << "Could not create notification window: " << SDL_GetError() << '\n';
        return;
    }
    renderer_ = SDL_CreateRenderer(window_, -1, SDL_RENDERER_ACCELERATED);
    if (!renderer_) renderer_ = SDL_CreateRenderer(window_, -1, SDL_RENDERER_SOFTWARE);
}

NotificationManager::~NotificationManager() {
    if (renderer_) SDL_DestroyRenderer(renderer_);
    if (window_) SDL_DestroyWindow(window_);
}

void NotificationManager::show(const std::string& text, unsigned int displayMs) {
    text_ = text;
    remainingSeconds_ = static_cast<float>(displayMs ? displayMs : 6000) / 1000.0f;
    dirty_ = true;
    if (!window_) return;
    if (anchor_) {
        int x = 0, y = 0;
        SDL_GetWindowPosition(anchor_, &x, &y);
        SDL_SetWindowPosition(window_, std::max(0, x - 100), std::max(0, y - 120));
    }
    SDL_ShowWindow(window_);
}

void NotificationManager::update(float dt) {
    if (remainingSeconds_ <= 0.0f) return;
    remainingSeconds_ -= dt;
    if (remainingSeconds_ <= 0.0f && window_) SDL_HideWindow(window_);
}

void NotificationManager::render() {
    if (!renderer_ || !dirty_ || remainingSeconds_ <= 0.0f) return;
    SDL_SetRenderDrawColor(renderer_, 23, 42, 60, 255);
    SDL_RenderClear(renderer_);
    SDL_SetRenderDrawColor(renderer_, 91, 190, 232, 255);
    SDL_Rect border{0, 0, 479, 109};
    SDL_RenderDrawRect(renderer_, &border);
    const auto lines = ui::wrapText(text_, 44);
    for (std::size_t i = 0; i < lines.size() && i < 5; ++i) {
        ui::drawText(renderer_, 18, 15 + static_cast<int>(i) * 18, lines[i], SDL_Color{232, 248, 255, 255});
    }
    SDL_RenderPresent(renderer_);
    dirty_ = false;
}
