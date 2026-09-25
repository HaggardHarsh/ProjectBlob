#include "renderer.h"

Renderer::Renderer() {
    // Initialize GL
}

Renderer::~Renderer() {}

void Renderer::clear() {
    // glClear(GL_COLOR_BUFFER_BIT);
}

void Renderer::present() {
    // SDL_GL_SwapWindow
}

void Renderer::drawQuad(float x, float y, float w, float h, Color color) {}
void Renderer::drawCircle(float x, float y, float radius, Color color, int segments) {}
void Renderer::drawBlobMesh(const std::vector<Vec2>& vertices, Color color) {}
void Renderer::drawText(float x, float y, const std::string& text, Color color) {}
