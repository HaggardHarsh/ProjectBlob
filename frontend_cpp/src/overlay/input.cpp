#include "input.h"
#include <utility>

InputHandler::InputHandler() {}

InputEvent InputHandler::processEvent(const SDL_Event& event) {
    InputEvent result{};
    if (event.type == SDL_MOUSEBUTTONDOWN) {
        result.type = InputEvent::CLICK;
        result.x = event.button.x;
        result.y = event.button.y;
    } else if (event.type == SDL_DROPBEGIN) {
        dropInProgress = true;
        droppedFiles.clear();
    } else if (event.type == SDL_DROPFILE) {
        std::string path = event.drop.file ? event.drop.file : "";
        SDL_free(event.drop.file);
        if (path.size() >= 11 && path.substr(path.size() - 11) == ".skill.yaml") {
            result.type = InputEvent::DRAG_DROP;
            result.filepath = std::move(path);
        } else if (!path.empty()) {
            droppedFiles.push_back(std::move(path));
            if (!dropInProgress) {
                result.type = InputEvent::ATTACHMENT_DROP;
                result.attachments = std::move(droppedFiles);
                droppedFiles.clear();
            }
        }
    } else if (event.type == SDL_DROPCOMPLETE) {
        dropInProgress = false;
        if (!droppedFiles.empty()) {
            result.type = InputEvent::ATTACHMENT_DROP;
            result.attachments = std::move(droppedFiles);
            droppedFiles.clear();
        }
    }
    return result;
}
