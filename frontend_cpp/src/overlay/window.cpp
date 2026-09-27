#include "window.h"
#include <iostream>

OverlayWindow::OverlayWindow(int w, int h) : width_(w), height_(h) {
    // SDL_CreateShapedWindow creates a non-rectangular window whose visible
    // area is determined by an alpha-mask surface passed to SDL_SetWindowShape.
    window_ = SDL_CreateShapedWindow(
        "Blob",
        SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED,
        width_, height_,
        SDL_WINDOW_BORDERLESS | SDL_WINDOW_ALWAYS_ON_TOP | SDL_WINDOW_ALLOW_HIGHDPI);

    if (!window_) {
        // Fallback to a normal window if shaped windows aren't supported
        std::cerr << "Shaped window not available (" << SDL_GetError()
                  << "), falling back to normal window.\n";
        window_ = SDL_CreateWindow(
            "Blob",
            SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED,
            width_, height_,
            SDL_WINDOW_BORDERLESS | SDL_WINDOW_ALWAYS_ON_TOP);
        if (!window_) {
            throw std::runtime_error("Window creation failed: " + std::string(SDL_GetError()));
        }
    }

    SDL_Rect usable{};
    const int display = SDL_GetWindowDisplayIndex(window_);
    if (display >= 0 && SDL_GetDisplayUsableBounds(display, &usable) == 0) {
        SDL_SetWindowPosition(window_, usable.x + usable.w - width_ - 24,
                             usable.y + usable.h - height_ - 24);
    }
    SDL_EventState(SDL_DROPFILE, SDL_ENABLE);
}

OverlayWindow::~OverlayWindow() {
    if (window_) SDL_DestroyWindow(window_);
}

void OverlayWindow::updateShape(SDL_Surface* shapeSurface) {
    if (!shapeSurface) return;
    if (SDL_IsShapedWindow(window_)) {
        SDL_WindowShapeMode mode;
        mode.mode = ShapeModeBinarizeAlpha;
        mode.parameters.binarizationCutoff = 1;
        SDL_SetWindowShape(window_, shapeSurface, &mode);
        shapedOnce_ = true;
    }
}

void OverlayWindow::startDrag(int gx, int gy) {
    dragging_ = true;
    SDL_CaptureMouse(SDL_TRUE);
    int wx, wy;
    SDL_GetWindowPosition(window_, &wx, &wy);
    dragWinX_ = wx;
    dragWinY_ = wy;
    dragMouseX_ = gx;
    dragMouseY_ = gy;
}

void OverlayWindow::updateDrag(int gx, int gy) {
    if (!dragging_) return;
    int dx = gx - dragMouseX_;
    int dy = gy - dragMouseY_;
    SDL_SetWindowPosition(window_, dragWinX_ + dx, dragWinY_ + dy);
}

void OverlayWindow::updateDragRelative(int xrel, int yrel) {
    if (!dragging_) return;
    int wx, wy;
    SDL_GetWindowPosition(window_, &wx, &wy);
    SDL_SetWindowPosition(window_, wx + xrel, wy + yrel);
}

void OverlayWindow::stopDrag() {
    dragging_ = false;
    SDL_CaptureMouse(SDL_FALSE);
}
