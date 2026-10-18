#include "window.h"
#include <iostream>
#include <algorithm>

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

    resetPosition();
    SDL_EventState(SDL_DROPFILE, SDL_ENABLE);
}

OverlayWindow::~OverlayWindow() {
    if (scaledShape_) SDL_FreeSurface(scaledShape_);
    if (window_) SDL_DestroyWindow(window_);
}

void OverlayWindow::updateShape(SDL_Surface* shapeSurface) {
    if (!shapeSurface) return;
    if (SDL_IsShapedWindow(window_)) {
        SDL_Surface* mask = shapeSurface;
        if (shapeSurface->w != width_ || shapeSurface->h != height_) {
            if (!scaledShape_ || scaledShape_->w != width_ || scaledShape_->h != height_) {
                if (scaledShape_) SDL_FreeSurface(scaledShape_);
                scaledShape_ = SDL_CreateRGBSurfaceWithFormat(0, width_, height_, 32, SDL_PIXELFORMAT_RGBA32);
            }
            if (!scaledShape_) return;
            SDL_SetSurfaceBlendMode(shapeSurface, SDL_BLENDMODE_NONE);
            SDL_BlitScaled(shapeSurface, nullptr, scaledShape_, nullptr);
            mask = scaledShape_;
        }
        SDL_WindowShapeMode mode;
        mode.mode = ShapeModeBinarizeAlpha;
        mode.parameters.binarizationCutoff = 1;
        SDL_SetWindowShape(window_, mask, &mode);
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

void OverlayWindow::resetPosition() {
    SDL_Rect usable{};
    int display = SDL_GetWindowDisplayIndex(window_);
    if (SDL_GetDisplayUsableBounds(std::max(0, display), &usable) == 0)
        SDL_SetWindowPosition(window_, usable.x + std::max(0, usable.w - width_ - 24),
                             usable.y + std::max(0, usable.h - height_ - 24));
}

void OverlayWindow::restorePosition(int x, int y) {
    for (int display = 0; display < SDL_GetNumVideoDisplays(); ++display) {
        SDL_Rect area{};
        if (SDL_GetDisplayUsableBounds(display, &area)) continue;
        const long long right = static_cast<long long>(x) + width_;
        const long long bottom = static_cast<long long>(y) + height_;
        if (right > area.x && x < static_cast<long long>(area.x) + area.w &&
            bottom > area.y && y < static_cast<long long>(area.y) + area.h) {
            SDL_SetWindowPosition(window_, std::clamp(x, area.x, area.x + std::max(0, area.w - width_)),
                                 std::clamp(y, area.y, area.y + std::max(0, area.h - height_)));
            return;
        }
    }
    resetPosition();
}

void OverlayWindow::resize(int width, int height) {
    int x, y; SDL_GetWindowPosition(window_, &x, &y);
    const int previousW = width_, previousH = height_;
    width_ = width; height_ = height;
    SDL_SetWindowSize(window_, width, height);
    restorePosition(x + previousW - width, y + previousH - height);
}
