#include "chat.h"
#include "ipc/grpc_client.h"
#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <iostream>
#include <stdexcept>

namespace {
const SDL_Color ink{27, 42, 55, 255}, muted{88, 108, 120, 255}, blue{31, 116, 139, 255};
bool contains(SDL_Rect rect, int x, int y) { SDL_Point point{x, y}; return SDL_PointInRect(&point, &rect); }
bool supported(const std::filesystem::path& path) {
    std::string ext = path.extension().string();
    std::transform(ext.begin(), ext.end(), ext.begin(), [](unsigned char c) { return std::tolower(c); });
    return ext == ".pdf" || ext == ".png" || ext == ".jpg" || ext == ".jpeg" || ext == ".webp";
}
size_t previous(const std::string& text, size_t index) {
    if (!index) return 0;
    --index;
    while (index && (static_cast<unsigned char>(text[index]) & 192) == 128) --index;
    return index;
}
size_t next(const std::string& text, size_t index) {
    if (index >= text.size()) return text.size();
    ++index;
    while (index < text.size() && (static_cast<unsigned char>(text[index]) & 192) == 128) ++index;
    return index;
}
}

ChatPanel::ChatPanel(GrpcClient& client) : client_(client) {}
ChatPanel::~ChatPanel() { close(); }
void ChatPanel::close() {
    body_.reset(); small_.reset();
    if (renderer_) SDL_DestroyRenderer(renderer_);
    if (window_) SDL_DestroyWindow(window_);
    renderer_ = nullptr; window_ = nullptr; visible_ = false;
}
void ChatPanel::show() {
    if (!window_) {
        window_ = SDL_CreateWindow("Blob chat", SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED,
                                   width_, height_, SDL_WINDOW_RESIZABLE | SDL_WINDOW_HIDDEN);
        if (!window_) throw std::runtime_error(SDL_GetError());
        SDL_SetWindowMinimumSize(window_, 460, 600);
        renderer_ = SDL_CreateRenderer(window_, -1, SDL_RENDERER_ACCELERATED);
        if (!renderer_) renderer_ = SDL_CreateRenderer(window_, -1, SDL_RENDERER_SOFTWARE);
        if (!renderer_) throw std::runtime_error(SDL_GetError());
        char* base = SDL_GetBasePath();
        std::string font = std::string(base ? base : "") + "data/OpenSans-Regular.ttf";
        SDL_free(base);
        body_ = std::make_unique<TextRenderer>(renderer_, font, 19);
        small_ = std::make_unique<TextRenderer>(renderer_, font, 16);
        if (messages_.empty()) append("Blob", "Hi! Ask me something, or attach a PDF or image and tell me what you'd like to understand.");
    }
    visible_ = true;
    SDL_ShowWindow(window_); SDL_RaiseWindow(window_); SDL_StartTextInput();
}
void ChatPanel::hide() { visible_ = false; SDL_HideWindow(window_); SDL_StopTextInput(); }
void ChatPanel::toggle() { if (visible_) hide(); else show(); }
void ChatPanel::append(const std::string& role, const std::string& text) {
    messages_.push_back({role, text, {}});
    if (messages_.size() > 200) messages_.erase(messages_.begin());
    wrap_width_ = 0; scroll_ = 0;
}
void ChatPanel::addNotice(const std::string& text) { append("Notice", text); }
void ChatPanel::addAttachment(const std::string& path) {
    show();
    if (isPending()) { status_ = "Wait for this reply before changing attachments."; return; }
    if (!supported(path)) { status_ = "Choose a PDF, PNG, JPEG, or WebP file."; return; }
    if (std::find(attachments_.begin(), attachments_.end(), path) != attachments_.end()) return;
    if (attachments_.size() == 4) { status_ = "Attach up to four files. Remove one with its x button."; return; }
    std::error_code error;
    if (!std::filesystem::is_regular_file(path, error)) { status_ = "That file couldn't be opened. Select it again."; return; }
    if (std::filesystem::file_size(path, error) > 20 * 1024 * 1024 || error) {
        status_ = "Files must be at most 20 MB each."; return;
    }
    attachments_.push_back(path);
    status_ = "File attached. Ask a question below, then send.";
}
SDL_Rect ChatPanel::inputRect() const { return {20, height_ - 126, width_ - 40, 70}; }
SDL_Rect ChatPanel::transcriptRect() const {
    return {20, 72, width_ - 40, std::max(40, height_ - 280 - int(attachments_.size()) * 29)};
}
void ChatPanel::layout() {
    if (wrap_width_ == width_) return;
    for (auto& message : messages_) message.lines = body_->wrap(message.text, width_ - 76);
    wrap_width_ = width_;
}
void ChatPanel::send() {
    if (isPending()) return;
    if (!client_.isConnected()) { status_ = "Blob is connecting. Start the backend, then send."; return; }
    if (input_.find_first_not_of(" \t\r\n") == std::string::npos && attachments_.empty()) return;
    std::string question = input_.empty() ? "Explain these attached files." : input_;
    std::string id = "desktop-" + std::to_string(SDL_GetTicks64()) + "-" + std::to_string(++request_counter_);
    if (!client_.sendMessage(question, attachments_, id)) { status_ = "Couldn't send. Please try again."; return; }
    std::string display = question;
    for (const auto& file : attachments_) display += "\n[" + std::filesystem::path(file).filename().string() + "]";
    append("You", display);
    input_.clear(); cursor_ = 0; selecting_ = false; pending_id_ = id;
    status_ = "Blob is reading and thinking...";
}
void ChatPanel::receiveReply(const std::string& id, const std::string& text) {
    if (id != pending_id_) return;
    append("Blob", text);
    pending_id_.clear(); status_.clear();
}
void ChatPanel::browse(const std::filesystem::path& path) {
    std::error_code error;
    std::vector<std::filesystem::directory_entry> entries;
    std::filesystem::directory_iterator it(path, error);
    if (error) { status_ = "Couldn't open that folder."; return; }
    for (; it != std::filesystem::directory_iterator(); it.increment(error)) {
        if (error) break;
        auto name = it->path().filename().string();
        if (!name.empty() && name[0] == '.') continue;
        bool folder = it->is_directory(error);
        if (!error && (folder || (it->is_regular_file(error) && supported(it->path())))) entries.push_back(*it);
        if (entries.size() >= 5000) break;
    }
    std::sort(entries.begin(), entries.end(), [](const auto& a, const auto& b) {
        std::error_code ea, eb;
        bool ad = a.is_directory(ea), bd = b.is_directory(eb);
        return ad != bd ? ad : a.path().filename().string() < b.path().filename().string();
    });
    directory_ = path; entries_ = std::move(entries); browser_scroll_ = 0; browser_ = true;
}
bool ChatPanel::processEvent(const SDL_Event& event) {
    if (!window_) return false;
    Uint32 id = 0;
    switch (event.type) {
        case SDL_WINDOWEVENT: id = event.window.windowID; break;
        case SDL_TEXTINPUT: id = event.text.windowID; break;
        case SDL_KEYDOWN: id = event.key.windowID; break;
        case SDL_MOUSEBUTTONDOWN: id = event.button.windowID; break;
        case SDL_MOUSEWHEEL: id = event.wheel.windowID; break;
        default: return false;
    }
    if (id != windowId()) return false;
    if (event.type == SDL_WINDOWEVENT) {
        if (event.window.event == SDL_WINDOWEVENT_CLOSE) hide();
        if (event.window.event == SDL_WINDOWEVENT_SIZE_CHANGED) {
            width_ = event.window.data1; height_ = event.window.data2;
        }
        return true;
    }
    if (event.type == SDL_MOUSEWHEEL) {
        int amount = event.wheel.y * (event.wheel.direction == SDL_MOUSEWHEEL_FLIPPED ? -1 : 1);
        if (browser_) browser_scroll_ = std::clamp(browser_scroll_ - amount * 3, 0,
            std::max(0, int(entries_.size()) - (height_ - 180) / 32));
        else scroll_ = std::max(0, scroll_ + amount * 65);
        return true;
    }
    if (event.type == SDL_MOUSEBUTTONDOWN && event.button.button == SDL_BUTTON_LEFT) {
        int x = event.button.x, y = event.button.y;
        if (browser_) {
            if (contains({20, 64, 65, 32}, x, y)) browse(directory_.parent_path());
            else if (contains({95, 64, 75, 32}, x, y)) browse(std::getenv("HOME") ? std::getenv("HOME") : ".");
            else if (contains({width_ - 95, 64, 75, 32}, x, y)) browser_ = false;
            else if (y >= 144 && y < height_ - 36) {
                int index = browser_scroll_ + (y - 144) / 32;
                if (index < int(entries_.size())) {
                    auto entry = entries_[index];
                    std::error_code error;
                    if (entry.is_directory(error)) browse(entry.path());
                    else addAttachment(entry.path().string());
                }
            }
        } else {
            if (contains({20, height_ - 44, 106, 30}, x, y)) {
                if (!isPending()) browse(directory_.empty() ? (std::getenv("HOME") ? std::getenv("HOME") : ".") : directory_);
            } else if (contains({width_ - 110, height_ - 44, 90, 30}, x, y)) send();
            else if (contains(inputRect(), x, y)) { cursor_ = input_.size(); selecting_ = false; }
            else {
                int top = transcriptRect().y + transcriptRect().h + 12;
                for (size_t index = 0; index < attachments_.size(); ++index) {
                    if (contains({width_ - 53, top + int(index) * 29, 28, 25}, x, y)) {
                        if (!isPending()) attachments_.erase(attachments_.begin() + index);
                        break;
                    }
                }
            }
        }
        return true;
    }
    if (event.type == SDL_TEXTINPUT && !browser_) {
        if (selecting_) { input_.clear(); cursor_ = 0; selecting_ = false; }
        if (input_.size() + std::char_traits<char>::length(event.text.text) <= 32000) {
            input_.insert(cursor_, event.text.text); cursor_ += std::char_traits<char>::length(event.text.text);
        }
        return true;
    }
    if (event.type == SDL_KEYDOWN) {
        auto key = event.key.keysym.sym;
        bool control = event.key.keysym.mod & KMOD_CTRL, shift = event.key.keysym.mod & KMOD_SHIFT;
        if (key == SDLK_ESCAPE) { if (browser_) browser_ = false; else hide(); return true; }
        if (browser_) return true;
        if (control && key == SDLK_a) selecting_ = true;
        else if (control && key == SDLK_c) SDL_SetClipboardText(input_.c_str());
        else if (control && key == SDLK_v) {
            char* paste = SDL_GetClipboardText();
            if (paste) {
                if (selecting_) { input_.clear(); cursor_ = 0; selecting_ = false; }
                std::string value(paste); SDL_free(paste);
                if (input_.size() + value.size() <= 32000) { input_.insert(cursor_, value); cursor_ += value.size(); }
            }
        } else if (key == SDLK_BACKSPACE || key == SDLK_DELETE) {
            if (selecting_) { input_.clear(); cursor_ = 0; selecting_ = false; }
            else if (key == SDLK_BACKSPACE && cursor_) {
                size_t before = previous(input_, cursor_); input_.erase(before, cursor_ - before); cursor_ = before;
            } else if (key == SDLK_DELETE && cursor_ < input_.size()) input_.erase(cursor_, next(input_, cursor_) - cursor_);
        } else if (key == SDLK_LEFT) { cursor_ = previous(input_, cursor_); selecting_ = false; }
        else if (key == SDLK_RIGHT) { cursor_ = next(input_, cursor_); selecting_ = false; }
        else if (key == SDLK_HOME) { cursor_ = 0; selecting_ = false; }
        else if (key == SDLK_END) { cursor_ = input_.size(); selecting_ = false; }
        else if (key == SDLK_RETURN || key == SDLK_KP_ENTER) {
            if (shift) { input_.insert(cursor_, "\n"); ++cursor_; } else send();
        }
        return true;
    }
    return true;
}
void ChatPanel::fill(SDL_Rect rect, SDL_Color color) {
    SDL_SetRenderDrawColor(renderer_, color.r, color.g, color.b, color.a); SDL_RenderFillRect(renderer_, &rect);
}
void ChatPanel::button(SDL_Rect rect, const std::string& label, bool enabled) {
    fill(rect, enabled ? blue : SDL_Color{179, 191, 196, 255});
    small_->draw(label, rect.x + 12, rect.y + 6, {255, 255, 255, 255});
}
void ChatPanel::render() {
    if (!visible_) return;
    fill({0, 0, width_, height_}, {248, 250, 251, 255});
    fill({0, 0, width_, 58}, {228, 241, 244, 255});
    body_->draw(browser_ ? "Choose PDFs or images" : "Blob chat", 20, 17, ink);
    if (browser_) {
        button({20, 64, 65, 32}, "Up"); button({95, 64, 75, 32}, "Home");
        button({width_ - 95, 64, 75, 32}, "Done");
        SDL_Rect pathClip{20, 105, width_ - 40, 30}; SDL_RenderSetClipRect(renderer_, &pathClip);
        small_->draw(directory_.string(), 20, 112, muted); SDL_RenderSetClipRect(renderer_, nullptr);
        SDL_Rect listClip{20, 144, width_ - 40, height_ - 180}; SDL_RenderSetClipRect(renderer_, &listClip);
        if (entries_.empty()) body_->draw("No supported files in this folder.", 30, 157, muted);
        for (int row = 0, i = browser_scroll_; i < int(entries_.size()); ++i, ++row) {
            int y = 144 + row * 32;
            if (y >= height_ - 36) break;
            std::error_code error;
            const auto& entry = entries_[i];
            bool folder = entry.is_directory(error);
            bool attached = std::find(attachments_.begin(), attachments_.end(), entry.path().string()) != attachments_.end();
            fill({20, y, width_ - 40, 31}, attached ? SDL_Color{217, 239, 229, 255} : SDL_Color{239, 244, 247, 255});
            body_->draw((folder ? "/ " : attached ? "+ " : "  ") + entry.path().filename().string(), 28, y + 6, ink);
        }
        SDL_RenderSetClipRect(renderer_, nullptr);
        small_->draw("Click folders to open; click files to attach. Up to 4 files.", 20, height_ - 26, muted);
        SDL_RenderPresent(renderer_); return;
    }
    small_->draw(client_.isConnected() ? "Connected" : "Connecting...", width_ - 112, 20, muted);
    layout();
    auto area = transcriptRect();
    int total = 0;
    for (const auto& message : messages_) total += 43 + int(message.lines.size()) * 23;
    int maxScroll = std::max(0, total - area.h);
    scroll_ = std::clamp(scroll_, 0, maxScroll);
    int y = area.y - maxScroll + scroll_;
    SDL_RenderSetClipRect(renderer_, &area);
    for (const auto& message : messages_) {
        int h = 35 + int(message.lines.size()) * 23;
        if (y + h >= area.y && y <= area.y + area.h) {
            fill({area.x, y, area.w, h}, message.role == "You" ? SDL_Color{220, 239, 244, 255} : SDL_Color{237, 242, 245, 255});
            small_->draw(message.role, area.x + 12, y + 7, blue);
            for (size_t i = 0; i < message.lines.size(); ++i) {
                int rowY = y + 30 + int(i) * 23;
                if (rowY + 23 >= area.y && rowY < area.y + area.h) body_->draw(message.lines[i], area.x + 12, rowY, ink);
            }
        }
        y += h + 8;
    }
    SDL_RenderSetClipRect(renderer_, nullptr);
    int top = area.y + area.h + 12;
    for (size_t i = 0; i < attachments_.size(); ++i) {
        int row = top + int(i) * 29;
        fill({20, row, width_ - 40, 25}, {224, 237, 242, 255});
        SDL_Rect clip{28, row, width_ - 95, 25}; SDL_RenderSetClipRect(renderer_, &clip);
        small_->draw(std::filesystem::path(attachments_[i]).filename().string(), 28, row + 4, ink);
        SDL_RenderSetClipRect(renderer_, nullptr);
        small_->draw("x", width_ - 43, row + 4, blue);
    }
    auto notice = small_->wrap(status_, width_ - 40);
    if (!notice.empty()) small_->draw(notice[0], 20, height_ - 181, blue);
    small_->draw("Sending shares selected file content with your AI provider.", 20, height_ - 158, muted);
    auto input = inputRect();
    fill(input, selecting_ ? SDL_Color{223, 239, 249, 255} : SDL_Color{255, 255, 255, 255});
    SDL_SetRenderDrawColor(renderer_, 183, 203, 211, 255); SDL_RenderDrawRect(renderer_, &input);
    SDL_RenderSetClipRect(renderer_, &input);
    if (input_.empty()) body_->draw(isPending() ? "Write your next question..." : "Ask about your files...", input.x + 10, input.y + 10, muted);
    else {
        auto lines = body_->wrap(input_.substr(0, cursor_) + "|" + input_.substr(cursor_), input.w - 22);
        auto prefix = body_->wrap(input_.substr(0, cursor_), input.w - 22);
        int start = std::max(0, int(prefix.size()) - 3);
        for (int i = start; i < std::min(start + 3, int(lines.size())); ++i)
            body_->draw(lines[i], input.x + 10, input.y + 4 + (i - start) * 22, ink);
    }
    SDL_RenderSetClipRect(renderer_, nullptr);
    button({20, height_ - 44, 106, 30}, "Attach file", !isPending());
    small_->draw("Enter to send", 139, height_ - 36, muted);
    button({width_ - 110, height_ - 44, 90, 30}, isPending() ? "Reading" : "Send", !isPending() && client_.isConnected());
    SDL_RenderPresent(renderer_);
}
