#pragma once
#include <vector>
#include <string>
#include <SDL2/SDL.h>
#include "common/types.h"
#include "blob/state_machine.h"

/**
 * Renderer — draws a Rimuru-style translucent blue slime with:
 *   • Translucent light-blue dome body
 *   • Thin blue outline
 *   • Darker-blue inner "core" shape
 *   • White specular highlights
 *   • Single dot eye & whisker mouth on the core
 */
class Renderer {
public:
    Renderer(SDL_Window* window, int w, int h);
    ~Renderer();

    void clear();
    void present();

    /// Draw the translucent outer dome body.
    void drawOuterBody(const std::vector<Vec2>& vertices);

    /// Draw the thin outline around the dome.
    void drawOutline(const std::vector<Vec2>& vertices);

    /// Draw the darker inner "core" body.
    void drawInnerBody(float cx, float cy, float rx, float ry, float time);

    /// Draw white specular highlight spots.
    void drawHighlights(float cx, float cy, float rx, float ry);

    /// Draw eye + whisker-mouth on the inner core.
    void drawFace(float cx, float cy, float rx, float ry, float time, BlobState state);

    /// Build shape mask for the current frame.
    void stampShape(const std::vector<Vec2>& vertices, float cx, float cy);

    SDL_Surface* getShapeSurface() const { return shapeSurface_; }

private:
    void fillCircle(int cx, int cy, int r, Color color);
    void fillEllipse(int cx, int cy, int rx, int ry, Color color);
    void fillCircleOnSurface(SDL_Surface* s, int cx, int cy, int r, Uint32 c);
    void fillEllipseOnSurface(SDL_Surface* s, int cx, int cy, int rx, int ry, Uint32 c);

    SDL_Renderer* sdlRenderer_ = nullptr;
    SDL_Surface*  shapeSurface_ = nullptr;
    int width_, height_;
};
