#include "ui/chat_window.h"

#include <SDL2/SDL.h>
#include <cstring>
#include <string>

int main() {
    if (SDL_Init(SDL_INIT_VIDEO | SDL_INIT_EVENTS) != 0) return 1;
    std::string sent;
    {
        ChatWindow chat;
        if (!chat.windowId()) return 2;
        chat.setSendHandler([&](const std::string& text) { sent = text; });
        chat.show();
        SDL_Event input{};
        input.type = SDL_TEXTINPUT;
        input.text.windowID = chat.windowId();
        std::strcpy(input.text.text, "/camera list");
        chat.handleEvent(input);
        SDL_Event enter{};
        enter.type = SDL_KEYDOWN;
        enter.key.windowID = chat.windowId();
        enter.key.keysym.sym = SDLK_RETURN;
        chat.handleEvent(enter);
        chat.addAssistantMessage("No people enrolled.");
        chat.render();
        if (sent != "/camera list") return 3;
    }
    SDL_Quit();
    return 0;
}
