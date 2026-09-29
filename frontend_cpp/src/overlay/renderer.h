#pragma once
#include <vector>
#include <string>
#include <SDL2/SDL.h>
#include "common/types.h"
#include "blob/state_machine.h"
#include "blob/visual_state.h"

/** Draws the compact blue slime and its facial expressions. */
class Renderer {
public:
    Renderer(SDL_Window* window, int w, int h);
    ~Renderer();

    void clear();
    void present();

    /// Draw the translucent body.
    void drawOuterBody(const std::vector<Vec2>& vertices);

    /// Draw the outline around the body.
    void drawOutline(const std::vector<Vec2>& vertices);

    /// Draw one small surface highlight.
    void drawHighlights(float cx, float cy, float rx, float ry);

    /// Draw the current expression.
    void drawFace(float cx, float cy, float rx, float ry, float time,
                  BlobState state, const BlobPose& pose);
    void drawDetails(float cx, float cy, float rx, float ry, float time,
                     const BlobPose& pose);

    /// Build shape mask for the current frame.
    void stampShape(const std::vector<Vec2>& vertices, float cx, float cy);

    SDL_Surface* getShapeSurface() const { return shapeSurface_; }

private:
    void fillCircle(int cx, int cy, int r, Color color);
    void fillEllipse(int cx, int cy, int rx, int ry, Color color);
    void drawCurve(float x0, float y0, float x1, float y1,
                   float bend, Color color, int thickness);

    SDL_Renderer* sdlRenderer_ = nullptr;
    SDL_Surface*  shapeSurface_ = nullptr;
    int width_, height_;
};
