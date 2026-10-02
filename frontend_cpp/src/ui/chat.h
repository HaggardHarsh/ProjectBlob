#pragma once
#include <SDL2/SDL.h>
#include <filesystem>
#include <memory>
#include <string>
#include <vector>
#include "text.h"

class GrpcClient;

class ChatPanel {
public:
    explicit ChatPanel(GrpcClient& client);
    ~ChatPanel();
    void show();
    void hide();
    void toggle();
    void close();
    bool processEvent(const SDL_Event& event);
    void addAttachment(const std::string& path);
    void receiveReply(const std::string& id, const std::string& text);
    void addNotice(const std::string& text);
    void render();
    bool isVisible() const { return visible_; }
    Uint32 windowId() const { return window_ ? SDL_GetWindowID(window_) : 0; }
    const std::vector<std::string>& attachments() const { return attachments_; }
    bool isPending() const { return !pending_id_.empty(); }
private:
    struct Message { std::string role, text; std::vector<std::string> lines; };
    void send();
    void browse(const std::filesystem::path& path);
    void layout();
    void fill(SDL_Rect rect, SDL_Color color);
    void button(SDL_Rect rect, const std::string& label, bool enabled = true);
    void append(const std::string& role, const std::string& text);
    SDL_Rect transcriptRect() const;
    SDL_Rect inputRect() const;

    GrpcClient& client_;
    SDL_Window* window_ = nullptr;
    SDL_Renderer* renderer_ = nullptr;
    std::unique_ptr<TextRenderer> body_, small_;
    bool visible_ = false, selecting_ = false, browser_ = false;
    int width_ = 560, height_ = 680, wrap_width_ = 0, scroll_ = 0, browser_scroll_ = 0;
    std::string input_, status_, pending_id_;
    size_t cursor_ = 0;
    unsigned request_counter_ = 0;
    std::vector<std::string> attachments_;
    std::vector<Message> messages_;
    std::filesystem::path directory_;
    std::vector<std::filesystem::directory_entry> entries_;
};
