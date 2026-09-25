#include "window.h"
#include <iostream>

#ifdef _WIN32
#include <SDL2/SDL_syswm.h>
#include <windows.h>
#elif defined(__linux__)
#include <SDL2/SDL_syswm.h>
#include <X11/Xlib.h>
#include <X11/extensions/shape.h>
#endif

OverlayWindow::OverlayWindow(int w, int h) : width(w), height(h) {
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_MAJOR_VERSION, 3);
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_MINOR_VERSION, 3);
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_PROFILE_MASK, SDL_GL_CONTEXT_PROFILE_CORE);

    // Alpha blending and transparency
    SDL_GL_SetAttribute(SDL_GL_RED_SIZE, 8);
    SDL_GL_SetAttribute(SDL_GL_GREEN_SIZE, 8);
    SDL_GL_SetAttribute(SDL_GL_BLUE_SIZE, 8);
    SDL_GL_SetAttribute(SDL_GL_ALPHA_SIZE, 8);

    window = SDL_CreateWindow("Blob Overlay",
                              SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED,
                              width, height,
                              SDL_WINDOW_OPENGL | SDL_WINDOW_BORDERLESS | SDL_WINDOW_ALWAYS_ON_TOP | SDL_WINDOW_ALLOW_HIGHDPI);
    
    if (!window) {
        throw std::runtime_error("Window creation failed: " + std::string(SDL_GetError()));
    }

    glContext = SDL_GL_CreateContext(window);
    if (!glContext) {
        throw std::runtime_error("GL context creation failed: " + std::string(SDL_GetError()));
    }
    
    SDL_EventState(SDL_DROPFILE, SDL_ENABLE);
    makeClickThrough(true);
}

OverlayWindow::~OverlayWindow() {
    if (glContext) SDL_GL_DeleteContext(glContext);
    if (window) SDL_DestroyWindow(window);
}

void OverlayWindow::makeClickThrough(bool clickThrough) {
#ifdef _WIN32
    SDL_SysWMinfo wmInfo;
    SDL_VERSION(&wmInfo.version);
    if (SDL_GetWindowWMInfo(window, &wmInfo)) {
        HWND hwnd = wmInfo.info.win.window;
        LONG lExStyle = GetWindowLong(hwnd, GWL_EXSTYLE);
        if (clickThrough) {
            SetWindowLong(hwnd, GWL_EXSTYLE, lExStyle | WS_EX_TRANSPARENT | WS_EX_LAYERED);
        } else {
            SetWindowLong(hwnd, GWL_EXSTYLE, (lExStyle & ~WS_EX_TRANSPARENT) | WS_EX_LAYERED);
        }
    }
#elif defined(__linux__)
    // Simple clickthrough logic for X11 if needed.
#endif
}
