#pragma once
#include <vector>
#include <string>
#include <SDL2/SDL.h>
#include "common/types.h"

/**
 * Renderer — draws the Blob using SDL2's hardware-accelerated 2D renderer.
 * Also generates an alpha-mask surface used by the shaped window.
 */
class Renderer {
public:
    Renderer(SDL_Window* window, int w, int h);
    ~Renderer();

    void clear();
    void present();

    /// Draw the blob body (filled polygon from spring-mass vertices).
    void drawBlobMesh(const std::vector<Vec2>& vertices, Color color);

    /// Draw blob eyes (white sclera + black pupil).
    void drawEyes(float cx, float cy, float blobRadius, float time);

    /// Draw blob mouth (a cute smile).
    void drawMouth(float cx, float cy, float blobRadius, float time);

    /// Return the shape-mask surface for the current frame (caller must NOT free it).
    SDL_Surface* getShapeSurface() const { return shapeSurface_; }

private:
    void fillCircle(int cx, int cy, int radius, Color color);
    void fillCircleOnSurface(SDL_Surface* surf, int cx, int cy, int radius, Uint32 color);

    SDL_Renderer* sdlRenderer_ = nullptr;
    SDL_Surface*  shapeSurface_ = nullptr;
    int width_, height_;
};
