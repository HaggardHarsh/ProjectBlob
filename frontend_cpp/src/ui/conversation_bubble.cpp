#include "conversation_bubble.h"
#include <SDL2/SDL_shape.h>
#include <algorithm>
#include <cstdint>

namespace {
constexpr int width = 340;
struct ScopedHint {
    std::string name, previous;
    bool hadValue;
    ScopedHint(const char* key, const char* value) : name(key), hadValue(SDL_GetHint(key) != nullptr) {
        if (hadValue) previous = SDL_GetHint(key);
        SDL_SetHint(key, value);
    }
    ~ScopedHint() {
        if (hadValue) SDL_SetHint(name.c_str(), previous.c_str());
        else {
#if SDL_VERSION_ATLEAST(2, 24, 0)
            SDL_ResetHint(name.c_str());
#else
            SDL_SetHint(name.c_str(), "");
#endif
        }
    }
};
uint32_t le32(const std::string& data, size_t offset) {
    uint32_t value = 0;
    for (int i = 0; i < 4; ++i) value |= uint32_t(static_cast<unsigned char>(data[offset + i])) << (8 * i);
    return value;
}
}

ConversationBubble::~ConversationBubble() {
    if (texture_) SDL_DestroyTexture(texture_);
    if (renderer_) SDL_DestroyRenderer(renderer_);
    if (window_) SDL_DestroyWindow(window_);
}

bool ConversationBubble::show(const blob::NotificationBubble& invitation, SDL_Window* anchor, Uint32 now) {
    hide();
    const auto& data = invitation.image_bmp();
    const int height = data.size() >= 54 ? int(le32(data, 22)) : 0;
    // Check dimensions before the decoder can allocate from an untrusted header.
    if (!invitation.proactive() || invitation.approach_id().empty() || invitation.text().empty() ||
        height < 116 || height > 180 || data.size() != size_t(54 + width * height * 3) || data.substr(0, 2) != "BM" ||
        le32(data, 10) != 54 || le32(data, 14) != 40 || le32(data, 18) != width ||
        static_cast<unsigned char>(data[28]) != 24 || le32(data, 30) != 0) {
        SDL_SetError("Invalid conversation bubble image");
        return false;
    }
    SDL_RWops* input = SDL_RWFromConstMem(data.data(), int(data.size()));
    SDL_Surface* raw = input ? SDL_LoadBMP_RW(input, 1) : nullptr;
    if (!raw) { SDL_Log("Bubble bitmap could not be decoded"); return false; }
    SDL_SetColorKey(raw, SDL_TRUE, SDL_MapRGB(raw->format, 255, 0, 255));
    SDL_Surface* rgba = SDL_CreateRGBSurfaceWithFormat(0, width, height, 32, SDL_PIXELFORMAT_RGBA32);
    if (!rgba) { SDL_FreeSurface(raw); return false; }
    SDL_FillRect(rgba, nullptr, SDL_MapRGBA(rgba->format, 0, 0, 0, 0));
    SDL_BlitSurface(raw, nullptr, rgba, nullptr);
    SDL_FreeSurface(raw);
    if (!window_) {
        const Uint32 flags = SDL_WINDOW_HIDDEN | SDL_WINDOW_BORDERLESS | SDL_WINDOW_ALWAYS_ON_TOP |
                             SDL_WINDOW_SKIP_TASKBAR;
        // Also works with SDL2-compat, whose tooltip flag requires a popup parent.
        ScopedHint type("SDL_X11_WINDOW_TYPE", "_NET_WM_WINDOW_TYPE_NOTIFICATION");
        window_ = SDL_CreateShapedWindow("Blob conversation", 0, 0, width, height, flags);
        if (!window_) window_ = SDL_CreateWindow("Blob conversation", 0, 0, width, height, flags);
        if (window_) renderer_ = SDL_CreateRenderer(window_, -1, SDL_RENDERER_SOFTWARE);
    }
    if (!renderer_) { SDL_Log("Bubble renderer unavailable: %s", SDL_GetError()); SDL_FreeSurface(rgba); return false; }
    if (height_ != height) SDL_SetWindowSize(window_, width, height);
    height_ = height;
    if (texture_) SDL_DestroyTexture(texture_);
    texture_ = SDL_CreateTextureFromSurface(renderer_, rgba);
    if (SDL_IsShapedWindow(window_)) {
        SDL_WindowShapeMode mode{};
        mode.mode = ShapeModeBinarizeAlpha;
        mode.parameters.binarizationCutoff = 1;
        SDL_SetWindowShape(window_, rgba, &mode);
    }
    SDL_FreeSurface(rgba);
    if (!texture_) { SDL_Log("Bubble texture unavailable: %s", SDL_GetError()); return false; }
    SDL_SetRenderDrawColor(renderer_, 0, 0, 0, 0);
    SDL_RenderClear(renderer_);
    SDL_RenderCopy(renderer_, texture_, nullptr, nullptr);
    SDL_RenderPresent(renderer_);
    id_ = invitation.approach_id();
    expires_ = now + std::clamp(invitation.display_ms(), Uint32(5000), Uint32(30000));
    visible_ = true;
    update(anchor, now);
    ScopedHint activation("SDL_WINDOW_NO_ACTIVATION_WHEN_SHOWN", "1");
    SDL_ShowWindow(window_);
    return true;
}

void ConversationBubble::hide() {
    visible_ = false;
    if (window_) SDL_HideWindow(window_);
}

void ConversationBubble::update(SDL_Window* anchor, Uint32 now) {
    if (!visible_) return;
    if (SDL_TICKS_PASSED(now, expires_)) { hide(); return; }
    int x, y, w, h;
    SDL_GetWindowPosition(anchor, &x, &y);
    SDL_GetWindowSize(anchor, &w, &h);
    SDL_Rect area{};
    if (SDL_GetDisplayUsableBounds(std::max(0, SDL_GetWindowDisplayIndex(anchor)), &area)) return;
    const int left = std::clamp(x + w / 2 - 286, area.x, area.x + std::max(0, area.w - width));
    const int top = std::clamp(y - height_ - 6, area.y, area.y + std::max(0, area.h - height_));
    SDL_SetWindowPosition(window_, left, top);
}

std::optional<blob::ProactiveFeedback::Action> ConversationBubble::handle(const SDL_Event& event) {
    if (!visible_) return std::nullopt;
    if (event.type == SDL_WINDOWEVENT && event.window.windowID == windowId() && event.window.event == SDL_WINDOWEVENT_CLOSE)
        return blob::ProactiveFeedback::DISMISSED;
    if (event.type != SDL_MOUSEBUTTONDOWN || event.button.windowID != windowId()) return std::nullopt;
    if (event.button.button == SDL_BUTTON_LEFT && event.button.y >= height_ - 50 && event.button.y <= height_ - 22) {
        if (event.button.x >= 12 && event.button.x <= 115) return blob::ProactiveFeedback::REPLY;
        if (event.button.x >= 118 && event.button.x <= 221) return blob::ProactiveFeedback::QUIET_TODAY;
        if (event.button.x >= 224 && event.button.x <= 327) return blob::ProactiveFeedback::MUTE;
    }
    return blob::ProactiveFeedback::DISMISSED;
}
