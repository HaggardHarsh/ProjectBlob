#include "ui/conversation_bubble.h"
#include <SDL2/SDL.h>
#include <fstream>
#include <iterator>

int main(int argc, char** argv) {
    if (ConversationBubble::fresh(0, 1000) || ConversationBubble::fresh(1000, 22000) ||
        ConversationBubble::fresh(2000, 1000) || !ConversationBubble::fresh(1000, 1001)) return 12;
    if (SDL_Init(SDL_INIT_VIDEO)) return 1;
    SDL_Window* anchor = SDL_CreateWindow("Bubble anchor", 200, 300, 132, 116, SDL_WINDOW_HIDDEN);
    if (!anchor) return 2;
    int result = 0;
    {
        ConversationBubble bubble;
        blob::NotificationBubble event;
        event.set_proactive(true); event.set_approach_id("synthetic-invitation");
        event.set_text("How did your day turn out?"); event.set_display_ms(20000);
        std::string data(54 + 340 * 180 * 3, '\0');
        auto put = [&](int offset, unsigned value) { for (int i = 0; i < 4; ++i) data[offset + i] = char((value >> (i * 8)) & 255); };
        data[0] = 'B'; data[1] = 'M'; put(2, data.size()); put(10, 54); put(14, 40);
        put(18, 340); put(22, 180); data[26] = 1; data[28] = 24;
        if (argc == 2) { std::ifstream file(argv[1], std::ios::binary); data.assign(std::istreambuf_iterator<char>(file), {}); }
        event.set_image_bmp(data);
        const bool opened = bubble.show(event, anchor, 100);
        if (!opened || !bubble.visible()) {
            SDL_Log("Bubble did not open (%d, %d): %s", opened, bubble.visible(), SDL_GetError());
            return 3;
        }
        if (std::string(SDL_GetCurrentVideoDriver()) != "dummy") {
            SDL_Delay(200); SDL_PumpEvents();
            if (SDL_GetWindowFlags(SDL_GetWindowFromID(bubble.windowId())) & SDL_WINDOW_INPUT_FOCUS) return 11;
        }
        SDL_Event click{}; click.type = SDL_MOUSEBUTTONDOWN; click.button.button = SDL_BUTTON_LEFT;
        unsigned imageHeight = 0;
        for (int i = 0; i < 4; ++i) imageHeight |= unsigned(static_cast<unsigned char>(data[22 + i])) << (8 * i);
        click.button.windowID = bubble.windowId(); click.button.y = int(imageHeight) - 40;
        click.button.x = 35;
        if (bubble.handle(click) != blob::ProactiveFeedback::REPLY) result = 4;
        click.button.x = 150;
        if (bubble.handle(click) != blob::ProactiveFeedback::QUIET_TODAY) result = 5;
        click.button.x = 260;
        if (bubble.handle(click) != blob::ProactiveFeedback::MUTE) result = 6;
        click.button.y = 35;
        if (bubble.handle(click) != blob::ProactiveFeedback::DISMISSED) result = 7;
        bubble.update(anchor, 20101);
        if (bubble.visible() || bubble.handle(click)) result = 8;
        event.set_image_bmp("BM");
        if (bubble.show(event, anchor, 30000)) result = 9;
        event.set_image_bmp(data); event.set_approach_id("");
        if (bubble.show(event, anchor, 30000)) result = 10;
    }
    SDL_DestroyWindow(anchor); SDL_Quit();
    return result;
}
