#include "input.h"

InputHandler::InputHandler() {}

InputEvent InputHandler::processEvent(const SDL_Event& event) {
    InputEvent result = {InputEvent::NONE, 0, 0, 0.0f, ""};
    if (event.type == SDL_MOUSEBUTTONDOWN) {
        result.type = InputEvent::CLICK;
        result.x = event.button.x;
        result.y = event.button.y;
    } else if (event.type == SDL_DROPFILE) {
        result.type = InputEvent::DRAG_DROP;
        result.filepath = event.drop.file;
        SDL_free(event.drop.file);
    }
    return result;
}
