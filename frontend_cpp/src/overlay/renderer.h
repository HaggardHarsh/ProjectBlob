#pragma once
#include <vector>
#include <string>
#include "common/types.h"

class Renderer {
public:
    Renderer();
    ~Renderer();

    void clear();
    void present();

    void drawQuad(float x, float y, float w, float h, Color color);
    void drawCircle(float x, float y, float radius, Color color, int segments);
    void drawBlobMesh(const std::vector<Vec2>& vertices, Color color);
    void drawText(float x, float y, const std::string& text, Color color);
};
