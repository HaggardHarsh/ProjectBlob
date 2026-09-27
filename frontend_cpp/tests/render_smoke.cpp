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
    SDL_Window* window = SDL_CreateWindow("Blob render test", 0, 0, 180, 150, SDL_WINDOW_HIDDEN);
    if (!window) return 2;
    std::vector<unsigned char> idle(180 * 150 * 4), happy(idle.size());
    {
        Renderer renderer(window, 180, 150);
        BlobPhysics physics(180, 150);
        const auto vertices = physics.getVertices();
        const auto center = physics.getCenter();
        const auto draw = [&](BlobExpression expression, std::vector<unsigned char>& pixels) {
            renderer.clear();
            renderer.drawOuterBody(vertices);
            renderer.drawOutline(vertices);
            renderer.drawInnerBody(center.x, center.y, physics.getRadiusX(), physics.getRadiusY(), 1.0f);
            renderer.drawHighlights(center.x, center.y, physics.getRadiusX(), physics.getRadiusY());
            renderer.drawFace(center.x, center.y, physics.getRadiusX(), physics.getRadiusY(),
                              1.0f, BlobState::IDLE, expression);
            renderer.present();
            return SDL_RenderReadPixels(SDL_GetRenderer(window), nullptr,
                                        SDL_PIXELFORMAT_RGBA8888, pixels.data(), 180 * 4);
        };
        if (draw(BlobExpression::IDLE, idle) != 0 || draw(BlobExpression::HAPPY, happy) != 0)
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
            if (const char* directory = std::getenv("BLOB_PREVIEW_DIR")) {
                const std::string path = std::string(directory) + "/" + name + ".bmp";
                SDL_Surface* surface = SDL_CreateRGBSurfaceWithFormatFrom(
                    pixels.data(), 180, 150, 32, 180 * 4, SDL_PIXELFORMAT_RGBA8888);
                if (!surface || SDL_SaveBMP(surface, path.c_str()) != 0) return 7;
                SDL_FreeSurface(surface);
            }
        }
    }
    SDL_DestroyWindow(window);
    SDL_Quit();
    return 0;
}
