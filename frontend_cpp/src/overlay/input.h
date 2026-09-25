#pragma once
#include <SDL2/SDL.h>
#include <string>

struct InputEvent {
    enum Type { NONE, CLICK, DOUBLE_CLICK, PET, POKE, RIGHT_CLICK, DRAG_DROP } type;
    int x, y;
    float velocity;
    std::string filepath;
};

class InputHandler {
public:
    InputHandler();
    InputEvent processEvent(const SDL_Event& event);

private:
    Uint32 lastClickTime = 0;
    bool isDragging = false;
    int dragStartX, dragStartY;
};
