#pragma once

#include <SDL2/SDL.h>
#include <deque>
#include <functional>
#include <string>

class ChatWindow {
public:
    ChatWindow();
    ~ChatWindow();

    void render();
    void handleEvent(const SDL_Event& event);
    void toggle();
    void show();
    void hide();
    void addAssistantMessage(const std::string& text);
    void setConnected(bool connected);
    void setSendHandler(std::function<void(const std::string&)> handler);
    bool isVisible() const { return visible_; }
    Uint32 windowId() const { return windowId_; }

private:
    struct Entry { bool fromUser; std::string text; };
    SDL_Window* window_ = nullptr;
    SDL_Renderer* renderer_ = nullptr;
    Uint32 windowId_ = 0;
    bool visible_ = false;
    bool dirty_ = true;
    bool connected_ = false;
    std::string input_;
    std::deque<Entry> history_;
    int scrollLines_ = 0;
    std::function<void(const std::string&)> onSend_;
};
