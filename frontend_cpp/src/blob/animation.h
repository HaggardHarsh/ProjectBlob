#pragma once
#include "blob/visual_state.h"

class AnimationController {
public:
    AnimationController() = default;
    void setExpression(BlobExpression expression, float intensity = 0.5f);
    void setBlend(BlobExpression secondary, float amount);
    void update(float dt);
    void setReducedMotion(bool value) { reducedMotion_ = value; }
    void setAttention(float x, float y, bool hovered);
    const BlobPose& pose() const { return pose_; }
    BlobExpression expression() const { return expression_; }

private:
    BlobExpression expression_ = BlobExpression::IDLE;
    BlobExpression secondary_ = BlobExpression::IDLE;
    BlobPose pose_{};
    float intensity_ = 0.5f;
    float blend_ = 0.0f;
    float time_ = 0.0f;
    float expressionTime_ = 0.0f;
    bool reducedMotion_ = false;
    bool hovered_ = false;
    float attentionX_ = 0.0f, attentionY_ = 0.0f;
};
