#pragma once
#include <SDL2/SDL.h>
#include <string>
#include <stdexcept>

/**
 * @class OverlayWindow
 * @brief Manages the transparent, borderless SDL2 window for the overlay.
 */
class OverlayWindow {
public:
    /**
     * @brief Constructs the overlay window.
     * @param width Width of the window.
     * @param height Height of the window.
     */
    OverlayWindow(int width, int height);
    ~OverlayWindow();

    /**
     * @brief Toggles click-through behavior.
     * @param clickThrough If true, mouse events pass through to desktop.
     */
    void makeClickThrough(bool clickThrough);

    SDL_Window* getSDLWindow() const { return window; }
    int getWidth() const { return width; }
    int getHeight() const { return height; }

private:
    SDL_Window* window = nullptr;
    SDL_GLContext glContext;
    int width, height;
};
