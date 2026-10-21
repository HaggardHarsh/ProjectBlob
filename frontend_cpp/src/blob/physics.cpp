#include "blob/physics.h"

#include <algorithm>
#include <cmath>

namespace {
constexpr float PI = 3.14159265358979323846f;
}

BlobPhysics::BlobPhysics(int windowWidth, int windowHeight)
    : radiusX_(windowWidth * 0.37f),
      topRadiusY_(windowHeight * 0.36f),
      bottomRadiusY_(windowHeight * 0.29f),
      centerX_(windowWidth * 0.5f),
      centerY_(windowHeight * 0.61f), windowHeight_(float(windowHeight)) {}

float BlobPhysics::poseCenterY() const {
    const float desired = centerY_ + bottomRadiusY_ * (1.0f - pose_.height) - pose_.lift;
    const float top = 2.0f + topRadiusY_ * pose_.height;
    const float bottom = windowHeight_ - 2.0f - bottomRadiusY_ * pose_.height;
    return std::clamp(desired, top, std::max(top, bottom));
}

void BlobPhysics::update(float dt) {
    if (!std::isfinite(dt) || dt <= 0.0f) return;
    dt = std::clamp(dt, 0.0f, 0.05f);
    if (!reducedMotion_) time_ += dt;
    // Substeps keep the damped spring stable when a desktop frame is delayed.
    const int steps = std::max(1, int(std::ceil(dt / 0.008f)));
    const float step = dt / steps;
    for (int i = 0; i < steps; ++i) {
        wobbleVelocity_ += (-140.0f * wobble_ - 14.0f * wobbleVelocity_) * step;
        wobble_ += wobbleVelocity_ * step;
    }
    drag_ += (dragTarget_ - drag_) * (1.0f - std::exp(-9.0f * dt));
    if (reducedMotion_) wobble_ = wobbleVelocity_ = drag_ = 0.0f;
    squash_ *= std::exp(-5.0f * dt);
}

std::vector<Vec2> BlobPhysics::getVertices() const {
    std::vector<Vec2> vertices;
    vertices.reserve(128);
    const float pulse = reducedMotion_ ? 0.0f : std::sin(time_ * 1.4f) * 0.35f;
    const float settle = wobble_;
    const float rx = getRadiusX();
    const float centerY = poseCenterY();
    auto arm = [&](float angle, float at) {
        float d = std::remainder(angle - at, 2.0f * PI) / 0.19f;
        return std::exp(-d * d);
    };
    for (int i = 0; i < 128; ++i) {
        const float angle = 2.0f * PI * i / 128.0f;
        const float sine = std::sin(angle);
        const float cosine = std::cos(angle);
        const float lower = std::pow(std::max(0.0f, sine), 0.58f - 0.25f * pose_.melt);
        const float vertical = sine < 0.0f ? sine * topRadiusY_ : lower * bottomRadiusY_;
        const float rightArm = std::abs(pose_.arms) * 12.0f *
                               arm(angle, pose_.arms < 0.0f ? 0.35f : 5.72f);
        const float leftArm = std::max(0.0f, pose_.arms) * 10.0f * arm(angle, 3.72f);
        const float outward = rightArm + leftArm;
        const float x = centerX_ + pose_.shake + cosine * (rx + pulse + squash_ * 1.5f + outward)
                        - (pose_.lean + drag_ * 0.10f) * radiusX_ * sine + std::sin(angle * 2.0f) * settle
                        + 0.8f * std::sin(angle * 3.0f) * (1.0f - pose_.melt);
        const float y = centerY + vertical * pose_.height * (1.0f - squash_ * 0.035f)
                        + sine * outward * 0.25f + std::cos(angle * 2.0f) * settle * 0.35f;
        vertices.push_back({x, y});
    }
    return vertices;
}

Vec2 BlobPhysics::getCenter() const {
    return {centerX_ + pose_.shake + pose_.lean * radiusX_ * 0.25f,
            poseCenterY()};
}

void BlobPhysics::applyForce(Vec2 force) {
    wobble_ = std::clamp(wobble_ + force.length() * 0.01f, 0.0f, 2.0f);
}

void BlobPhysics::jiggle() {
    if (reducedMotion_) return;
    wobble_ = 2.0f;
    wobbleVelocity_ = 18.0f;
    squash_ = 1.0f;
}

void BlobPhysics::squash(float amount) {
    squash_ = std::clamp(amount, -1.0f, 1.0f);
}
