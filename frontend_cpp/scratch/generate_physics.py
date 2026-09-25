import os

files = {
    "/home/cloud/ProjectBlob/frontend_cpp/src/overlay/window.h": """#pragma once
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
""",
    "/home/cloud/ProjectBlob/frontend_cpp/src/overlay/window.cpp": """#include "window.h"
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
""",
    "/home/cloud/ProjectBlob/frontend_cpp/src/blob/physics.h": """#pragma once
#include <vector>
#include <cmath>

struct Vec2 { 
    float x, y;
    Vec2 operator+(const Vec2& o) const { return {x + o.x, y + o.y}; }
    Vec2 operator-(const Vec2& o) const { return {x - o.x, y - o.y}; }
    Vec2 operator*(float s) const { return {x * s, y * s}; }
};

class BlobPhysics {
public:
    BlobPhysics();
    void update(float dt);
    std::vector<Vec2> getVertices() const;
    void applyForce(Vec2 force);
    void jiggle();
    void squash(float amount);

private:
    struct Point {
        Vec2 pos, oldPos, accel;
        float mass = 1.0f;
    };
    
    struct Spring {
        int p1, p2;
        float restLength, k, damp;
    };
    
    std::vector<Point> points;
    std::vector<Spring> springs;
    float gravity = 9.81f * 10.0f;
};
""",
    "/home/cloud/ProjectBlob/frontend_cpp/src/blob/physics.cpp": """#include "blob/physics.h"
#include <cstdlib>

BlobPhysics::BlobPhysics() {
    int numPoints = 16;
    float radius = 50.0f;
    
    // Center point
    points.push_back({{400, 300}, {400, 300}, {0, 0}, 2.0f});
    
    // Perimeter points
    for (int i = 0; i < numPoints; ++i) {
        float angle = i * 2.0f * M_PI / numPoints;
        Vec2 p = {400 + std::cos(angle) * radius, 300 + std::sin(angle) * radius};
        points.push_back({p, p, {0, 0}, 1.0f});
        
        // Connect to center
        springs.push_back({0, i + 1, radius, 10.0f, 1.0f});
        
        // Connect to previous perimeter point
        if (i > 0) {
            float dist = radius * 2.0f * std::sin(M_PI / numPoints);
            springs.push_back({i, i + 1, dist, 15.0f, 1.0f});
        }
    }
    
    // Close the loop
    float dist = radius * 2.0f * std::sin(M_PI / numPoints);
    springs.push_back({numPoints, 1, dist, 15.0f, 1.0f});
}

void BlobPhysics::update(float dt) {
    // Verlet integration
    for (auto& p : points) {
        Vec2 temp = p.pos;
        p.pos = p.pos + (p.pos - p.oldPos) * 0.99f + p.accel * (dt * dt);
        p.oldPos = temp;
        p.accel = {0, gravity}; // Reset accel to just gravity
    }
    
    // Spring forces
    for (const auto& s : springs) {
        Point& p1 = points[s.p1];
        Point& p2 = points[s.p2];
        
        Vec2 delta = p2.pos - p1.pos;
        float dist = std::sqrt(delta.x * delta.x + delta.y * delta.y);
        
        if (dist > 0.001f) {
            float diff = (dist - s.restLength) / dist;
            Vec2 force = delta * diff * s.k;
            p1.accel = p1.accel + force * (1.0f / p1.mass);
            p2.accel = p2.accel - force * (1.0f / p2.mass);
        }
    }
    
    // Floor collision
    float floorY = 550.0f;
    for (auto& p : points) {
        if (p.pos.y > floorY) {
            p.pos.y = floorY;
            // Add some friction
            p.pos.x = p.oldPos.x + (p.pos.x - p.oldPos.x) * 0.8f;
        }
    }
}

std::vector<Vec2> BlobPhysics::getVertices() const {
    std::vector<Vec2> v;
    for (size_t i = 1; i < points.size(); ++i) {
        v.push_back(points[i].pos);
    }
    return v;
}

void BlobPhysics::applyForce(Vec2 force) {
    for (auto& p : points) p.accel = p.accel + force;
}

void BlobPhysics::jiggle() {
    for (auto& p : points) {
        float jx = (std::rand() % 100 - 50) * 10.0f;
        float jy = (std::rand() % 100 - 50) * 10.0f;
        p.accel = p.accel + Vec2{jx, jy};
    }
}

void BlobPhysics::squash(float amount) {
    for (auto& p : points) {
        p.pos.y += (p.pos.y - points[0].pos.y) * amount;
        p.pos.x -= (p.pos.x - points[0].pos.x) * amount * 0.5f; // Maintain volume approx
    }
}
"""
}

for path, content in files.items():
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
