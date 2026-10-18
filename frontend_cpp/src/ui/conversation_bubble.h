#pragma once

#include <SDL2/SDL.h>
#include <optional>
#include <string>
#include "blob_service.pb.h"

// An ephemeral tooltip beside the pet. No input box, focus grab, or history.
class ConversationBubble {
public:
    ~ConversationBubble();
    bool show(const blob::NotificationBubble& invitation, SDL_Window* anchor, Uint32 now);
    void hide();
    void update(SDL_Window* anchor, Uint32 now);
    std::optional<blob::ProactiveFeedback::Action> handle(const SDL_Event& event);
    const std::string& id() const { return id_; }
    bool visible() const { return visible_; }
    Uint32 windowId() const { return window_ ? SDL_GetWindowID(window_) : 0; }
    static bool fresh(uint64_t sent, uint64_t now) { return sent > 0 && sent <= now && now - sent <= 20000; }
private:
    SDL_Window* window_ = nullptr;
    SDL_Renderer* renderer_ = nullptr;
    SDL_Texture* texture_ = nullptr;
    std::string id_;
    Uint32 expires_ = 0;
    bool visible_ = false;
    int height_ = 180;
};
