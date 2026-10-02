#pragma once
#include <SDL2/SDL.h>
#include <string>
#include <vector>

struct InputEvent {
    enum Type { NONE, CLICK, DOUBLE_CLICK, PET, POKE, RIGHT_CLICK, DRAG_DROP, ATTACHMENT_DROP } type;
    int x, y;
    float velocity;
    std::string filepath;
    std::vector<std::string> attachments;
};

class InputHandler {
public:
    InputHandler();
    InputEvent processEvent(const SDL_Event& event);

private:
    bool dropInProgress = false;
    std::vector<std::string> droppedFiles;
    Uint32 lastClickTime = 0;
    bool isDragging = false;
    int dragStartX, dragStartY;
};
