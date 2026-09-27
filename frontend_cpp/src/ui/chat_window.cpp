#include "chat_window.h"
#include "text.h"

#include <algorithm>
#include <cstring>
#include <iostream>
#include <utility>
#include <vector>

ChatWindow::ChatWindow() {
    window_ = SDL_CreateWindow("Blob Chat", SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED,
                               560, 480, SDL_WINDOW_HIDDEN | SDL_WINDOW_RESIZABLE);
    if (!window_) {
        std::cerr << "Could not create chat window: " << SDL_GetError() << '\n';
        return;
    }
    renderer_ = SDL_CreateRenderer(window_, -1, SDL_RENDERER_ACCELERATED);
    if (!renderer_) renderer_ = SDL_CreateRenderer(window_, -1, SDL_RENDERER_SOFTWARE);
    if (!renderer_) std::cerr << "Could not create chat renderer: " << SDL_GetError() << '\n';
    windowId_ = SDL_GetWindowID(window_);
}

ChatWindow::~ChatWindow() {
    if (renderer_) SDL_DestroyRenderer(renderer_);
    if (window_) SDL_DestroyWindow(window_);
}

void ChatWindow::setSendHandler(std::function<void(const std::string&)> handler) {
    onSend_ = std::move(handler);
}

void ChatWindow::setConnected(bool connected) {
    if (connected_ != connected) {
        connected_ = connected;
        dirty_ = true;
    }
}

void ChatWindow::show() {
    if (!window_) return;
    visible_ = true;
    dirty_ = true;
    SDL_ShowWindow(window_);
    SDL_RaiseWindow(window_);
    SDL_StartTextInput();
}

void ChatWindow::hide() {
    if (!window_) return;
    visible_ = false;
    SDL_HideWindow(window_);
    SDL_StopTextInput();
}

void ChatWindow::toggle() {
    if (visible_) hide();
    else show();
}

void ChatWindow::addAssistantMessage(const std::string& text) {
    if (text.empty()) return;
    history_.push_back({false, text});
    if (history_.size() > 100) history_.pop_front();
    scrollLines_ = 0;
    dirty_ = true;
}

void ChatWindow::handleEvent(const SDL_Event& event) {
    if (!window_ || !visible_) return;
    if (event.type == SDL_WINDOWEVENT && event.window.windowID == windowId_) {
        if (event.window.event == SDL_WINDOWEVENT_CLOSE) hide();
        if (event.window.event == SDL_WINDOWEVENT_SIZE_CHANGED ||
            event.window.event == SDL_WINDOWEVENT_EXPOSED) dirty_ = true;
        return;
    }
    if (event.type == SDL_MOUSEWHEEL && event.wheel.windowID == windowId_) {
        scrollLines_ = std::max(0, scrollLines_ + event.wheel.y * 3);
        dirty_ = true;
        return;
    }
    if (event.type == SDL_TEXTINPUT && event.text.windowID == windowId_) {
        if (input_.size() + std::strlen(event.text.text) <= 1000) input_ += event.text.text;
        dirty_ = true;
        return;
    }
    if (event.type != SDL_KEYDOWN || event.key.windowID != windowId_) return;
    if (event.key.keysym.sym == SDLK_ESCAPE) {
        hide();
    } else if (event.key.keysym.sym == SDLK_BACKSPACE && !input_.empty()) {
        do { input_.pop_back(); } while (!input_.empty() && (static_cast<unsigned char>(input_.back()) & 0xC0) == 0x80);
        dirty_ = true;
    } else if (event.key.keysym.sym == SDLK_RETURN || event.key.keysym.sym == SDLK_KP_ENTER) {
        if (!input_.empty()) {
            const std::string message = input_;
            history_.push_back({true, message});
            if (history_.size() > 100) history_.pop_front();
            input_.clear();
            scrollLines_ = 0;
            dirty_ = true;
            if (onSend_) onSend_(message);
        }
    }
}

void ChatWindow::render() {
    if (!visible_ || !renderer_ || !dirty_) return;
    int width = 0, height = 0;
    SDL_GetRendererOutputSize(renderer_, &width, &height);
    SDL_SetRenderDrawColor(renderer_, 19, 28, 43, 255);
    SDL_RenderClear(renderer_);

    SDL_Rect header{0, 0, width, 42};
    SDL_SetRenderDrawColor(renderer_, 28, 58, 82, 255);
    SDL_RenderFillRect(renderer_, &header);
    ui::drawText(renderer_, 14, 12, connected_ ? "BLOB CHAT  -  CONNECTED" : "BLOB CHAT  -  CONNECTING",
                 SDL_Color{193, 237, 255, 255});

    const int columns = std::max(12, (width - 32) / ui::glyphWidth);
    std::vector<std::pair<bool, std::string>> lines;
    for (const Entry& entry : history_) {
        const std::string prefix = entry.fromUser ? "YOU: " : "BLOB: ";
        for (const auto& line : ui::wrapText(prefix + entry.text, static_cast<std::size_t>(columns))) {
            lines.emplace_back(entry.fromUser, line);
        }
        lines.emplace_back(entry.fromUser, "");
    }
    const int lineHeight = ui::glyphHeight + 4;
    const int availableLines = std::max(1, (height - 115) / lineHeight);
    const int maxScroll = std::max(0, static_cast<int>(lines.size()) - availableLines);
    scrollLines_ = std::min(scrollLines_, maxScroll);
    const int end = std::max(0, static_cast<int>(lines.size()) - scrollLines_);
    const int start = std::max(0, end - availableLines);
    int y = 54;
    for (int i = start; i < end; ++i) {
        ui::drawText(renderer_, 14, y, lines[i].second,
                     lines[i].first ? SDL_Color{172, 216, 255, 255} : SDL_Color{232, 245, 248, 255});
        y += lineHeight;
    }

    SDL_Rect inputBox{10, height - 52, width - 20, 42};
    SDL_SetRenderDrawColor(renderer_, 36, 48, 65, 255);
    SDL_RenderFillRect(renderer_, &inputBox);
    SDL_SetRenderDrawColor(renderer_, 94, 183, 225, 255);
    SDL_RenderDrawRect(renderer_, &inputBox);
    const std::string prompt = "> " + input_;
    const std::size_t visibleColumns = static_cast<std::size_t>(std::max(1, (width - 45) / ui::glyphWidth));
    ui::drawText(renderer_, 20, height - 38,
                 prompt.size() > visibleColumns ? prompt.substr(prompt.size() - visibleColumns) : prompt,
                 SDL_Color{255, 255, 255, 255});
    SDL_RenderPresent(renderer_);
    dirty_ = false;
}
