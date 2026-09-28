#include "blob/physics.h"

#include <algorithm>
#include <cmath>

namespace {
constexpr float PI = 3.14159265358979323846f;
}

BlobPhysics::BlobPhysics(int windowWidth, int windowHeight)
    : radiusX_(windowWidth * 0.38f),
      topRadiusY_(windowHeight * 0.37f),
      bottomRadiusY_(windowHeight * 0.28f),
      centerX_(windowWidth * 0.5f),
      centerY_(windowHeight * 0.55f) {}

void BlobPhysics::update(float dt) {
    dt = std::clamp(dt, 0.0f, 0.05f);
    time_ += dt;
    wobble_ *= std::exp(-6.0f * dt);
    squash_ *= std::exp(-5.0f * dt);
}

std::vector<Vec2> BlobPhysics::getVertices() const {
    std::vector<Vec2> vertices;
    vertices.reserve(64);
    const float pulse = std::sin(time_ * 1.4f) * 0.35f;
    const float settle = wobble_ * std::sin(time_ * 10.0f);
    for (int i = 0; i < 64; ++i) {
        const float angle = 2.0f * PI * i / 64.0f;
        const float sine = std::sin(angle);
        const float cosine = std::cos(angle);
        // A rounded dome with a gently flattened base reads as a resting slime.
        const float lower = std::pow(std::max(0.0f, sine), 0.45f);
        const float vertical = sine < 0.0f ? sine * topRadiusY_ : lower * bottomRadiusY_;
        const float x = centerX_ + cosine * (radiusX_ + pulse + squash_ * 1.5f)
                        + std::sin(angle * 2.0f) * settle;
        const float y = centerY_ + vertical * (1.0f - squash_ * 0.035f)
                        + std::cos(angle * 2.0f) * settle * 0.35f;
        vertices.push_back({x, y});
    }
    return vertices;
}

Vec2 BlobPhysics::getCenter() const { return {centerX_, centerY_}; }

void BlobPhysics::applyForce(Vec2 force) {
    wobble_ = std::clamp(wobble_ + force.length() * 0.01f, 0.0f, 2.0f);
}

void BlobPhysics::jiggle() {
    wobble_ = 2.0f;
    squash_ = 1.0f;
}

void BlobPhysics::squash(float amount) {
    squash_ = std::clamp(amount, -1.0f, 1.0f);
}
