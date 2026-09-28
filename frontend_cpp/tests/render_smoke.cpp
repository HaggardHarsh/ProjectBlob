#include <SDL2/SDL.h>
#include <algorithm>
#include <array>
#include <cstdlib>
#include <string>
#include <vector>

#include "blob/physics.h"
#include "overlay/renderer.h"

int main() {
    if (SDL_Init(SDL_INIT_VIDEO) != 0) return 1;
    constexpr int width = 132, height = 116;
    SDL_Window* window = SDL_CreateWindow("Blob render test", 0, 0, width, height, SDL_WINDOW_HIDDEN);
    if (!window) return 2;
    std::vector<unsigned char> idle(width * height * 4), happy(idle.size()), bodyOnly(idle.size());
    {
        Renderer renderer(window, width, height);
        BlobPhysics physics(width, height);
        const auto vertices = physics.getVertices();
        const auto center = physics.getCenter();
        const auto draw = [&](BlobExpression expression, std::vector<unsigned char>& pixels, bool face = true) {
            renderer.clear();
            renderer.drawOuterBody(vertices);
            renderer.drawOutline(vertices);
            renderer.drawHighlights(center.x, center.y, physics.getRadiusX(), physics.getRadiusY());
            if (face) {
                renderer.drawFace(center.x, center.y, physics.getRadiusX(), physics.getRadiusY(),
                                  1.0f, BlobState::IDLE, expression);
            }
            renderer.present();
            return SDL_RenderReadPixels(SDL_GetRenderer(window), nullptr,
                                        SDL_PIXELFORMAT_RGBA8888, pixels.data(), width * 4);
        };
        if (draw(BlobExpression::IDLE, idle) != 0 || draw(BlobExpression::HAPPY, happy) != 0 ||
            draw(BlobExpression::IDLE, bodyOnly, false) != 0)
            return 3;
        if (std::equal(idle.begin(), idle.end(), happy.begin())) return 4;
        constexpr std::array expressions{
            std::pair{"idle", BlobExpression::IDLE},
            std::pair{"happy", BlobExpression::HAPPY},
            std::pair{"excited", BlobExpression::EXCITED},
            std::pair{"thinking", BlobExpression::THINKING},
            std::pair{"worried", BlobExpression::WORRIED},
            std::pair{"sad", BlobExpression::SAD},
            std::pair{"angry", BlobExpression::ANGRY},
            std::pair{"confused", BlobExpression::CONFUSED},
            std::pair{"shy", BlobExpression::SHY},
            std::pair{"sleeping", BlobExpression::SLEEPING},
            std::pair{"eating", BlobExpression::EATING},
            std::pair{"proud", BlobExpression::PROUD},
            std::pair{"playful", BlobExpression::PLAYFUL},
        };
        for (const auto& [name, expression] : expressions) {
            std::vector<unsigned char> pixels(idle.size());
            if (draw(expression, pixels) != 0) return 5;
            if (expression != BlobExpression::IDLE &&
                std::equal(idle.begin(), idle.end(), pixels.begin())) return 6;
            // Expressions must not draw a mouth below the eyes.
            for (int y = int(center.y + 8); y < int(center.y + 21); ++y) {
                const int first = (y * width + int(center.x - 14)) * 4;
                const int last = (y * width + int(center.x + 14)) * 4;
                if (!std::equal(pixels.begin() + first, pixels.begin() + last,
                                bodyOnly.begin() + first)) return 8;
            }
            if (const char* directory = std::getenv("BLOB_PREVIEW_DIR")) {
                const std::string path = std::string(directory) + "/" + name + ".bmp";
                SDL_Surface* surface = SDL_CreateRGBSurfaceWithFormatFrom(
                    pixels.data(), width, height, 32, width * 4, SDL_PIXELFORMAT_RGBA8888);
                if (!surface || SDL_SaveBMP(surface, path.c_str()) != 0) return 7;
                SDL_FreeSurface(surface);
            }
        }
        physics.jiggle();
        for (int frame = 0; frame < 120; ++frame) {
            physics.update(1.0f / 60.0f);
            const auto moved = physics.getVertices();
            for (size_t i = 0; i < vertices.size(); ++i) {
                const float dx = moved[i].x - vertices[i].x;
                const float dy = moved[i].y - vertices[i].y;
                if (dx * dx + dy * dy > 25.0f) return 9;
            }
        }
    }
    SDL_DestroyWindow(window);
    SDL_Quit();
    return 0;
}
