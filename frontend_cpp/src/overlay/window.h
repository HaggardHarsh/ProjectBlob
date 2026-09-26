#pragma once
#include <SDL2/SDL.h>
#include <SDL2/SDL_shape.h>
#include <string>
#include <stdexcept>
#include <vector>
#include "common/types.h"

/**
 * OverlayWindow — a small, non-rectangular, always-on-top shaped window
 * that renders only the Blob silhouette with no background.
 */
class OverlayWindow {
public:
    OverlayWindow(int width, int height);
    ~OverlayWindow();

    /// Update the window's visible shape mask from a rendered surface.
    void updateShape(SDL_Surface* shapeSurface);

    /// Dragging helpers — call from event loop.
    void startDrag(int globalMouseX, int globalMouseY);
    void updateDrag(int globalMouseX, int globalMouseY);
    void updateDragRelative(int xrel, int yrel);
    void stopDrag();
    bool isDragging() const { return dragging_; }

    SDL_Window* getSDLWindow() const { return window_; }
    int getWidth() const { return width_; }
    int getHeight() const { return height_; }

private:
    SDL_Window* window_ = nullptr;
    int width_, height_;
    bool dragging_ = false;
    int dragWinX_ = 0, dragWinY_ = 0;
    int dragMouseX_ = 0, dragMouseY_ = 0;
    bool shapedOnce_ = false;
};
