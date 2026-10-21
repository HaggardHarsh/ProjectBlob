#include "blob/animation.h"

#include <algorithm>
#include <cmath>

namespace {
float unit(float x) { return std::clamp(x, 0.0f, 1.0f); }
float smooth(float x) { x = unit(x); return x * x * (3.0f - 2.0f * x); }
float pulse(float t, float center, float width) {
    const float d = (t - center) / width;
    return std::exp(-d * d);
}

BlobPose targetPose(BlobExpression expression, float intensity, float t, float age) {
    BlobPose p;
    constexpr float weight = 1.0f;
    const float breath = 0.018f * std::sin(t * 2.1f);
    p.height += breath;
    switch (expression) {
        case BlobExpression::IDLE:
        case BlobExpression::WAITING:
        case BlobExpression::CURIOUS:
            p.gazeX = 0.55f * std::sin(t * 0.53f) * std::sin(t * 0.19f);
            p.gazeY = 0.15f * std::sin(t * 0.41f);
            if (expression == BlobExpression::CURIOUS) {
                p.lean = 0.08f * weight; p.eyeSize = 1.18f; p.eyeAsymmetry = 0.18f; p.mouthSmile = 0.9f;
            }
            if (expression == BlobExpression::WAITING) p.eyeOpen = 0.85f;
            break;
        case BlobExpression::CUTE_SMILE:
        case BlobExpression::HAPPY:
        case BlobExpression::SUCCESS:
        case BlobExpression::EATING:
            p.height += 0.07f * weight;
            p.eyeOpen = expression == BlobExpression::CUTE_SMILE ? 0.85f : 0.12f;
            p.eyeSmile = expression == BlobExpression::CUTE_SMILE ? 0.0f : 1.0f;
            p.mouthSmile = 1.4f;
            p.mouthOpen = expression == BlobExpression::CUTE_SMILE ? 0.0f : 0.55f;
            p.blush = 0.3f;
            p.lift = 3.0f * pulse(age, 0.22f, 0.18f) * weight;
            p.sparkles = expression == BlobExpression::SUCCESS ? 0.45f : 0.0f;
            break;
        case BlobExpression::VERY_HAPPY:
        case BlobExpression::EXCITED:
        case BlobExpression::CELEBRATE:
        case BlobExpression::LAUGHING:
            p.height += (0.18f + 0.10f * pulse(age, 0.28f, 0.16f)) * weight;
            p.eyeOpen = expression == BlobExpression::EXCITED ? 1.3f : 0.08f;
            p.eyeSmile = expression == BlobExpression::EXCITED ? 0.0f : 1.0f;
            p.eyeSize = 1.2f; p.mouthSmile = 1.8f; p.mouthOpen = 1.1f; p.blush = 0.45f;
            p.lift = (expression == BlobExpression::CELEBRATE ? 12.0f : 7.0f)
                     * pulse(age, 0.32f, 0.20f) * weight;
            p.arms = expression == BlobExpression::CELEBRATE ? 0.7f * weight : 0.2f * weight;
            if (expression == BlobExpression::CELEBRATE)
                p.lift += 5.0f * std::pow(std::max(0.0f, std::sin(t * 6.0f)), 2);
            if (expression == BlobExpression::LAUGHING) {
                p.height = 0.87f + 0.045f * std::sin(t * 10.0f);
                p.lean = 0.06f * std::sin(t * 5.0f);
            }
            p.sparkles = expression == BlobExpression::CELEBRATE ? 0.8f : 0.25f;
            break;
        case BlobExpression::SHOCKED:
        case BlobExpression::EXTREME_SHOCK:
            p.height += (expression == BlobExpression::EXTREME_SHOCK ? 0.40f : 0.28f) * weight;
            p.eyeSize = expression == BlobExpression::EXTREME_SHOCK ? 1.65f : 1.4f;
            p.eyeOpen = 1.2f; p.mouthSmile = 0.0f; p.mouthRound = 1.0f; p.mouthOpen = 0.8f;
            p.shake = age > 0.18f && age < 0.52f ? 1.2f * std::sin(age * 92.0f) : 0.0f;
            break;
        case BlobExpression::CONFUSED:
        case BlobExpression::WORRIED:
            p.lean = 0.12f * std::cos(t * 1.7f) * weight;
            p.eyeAsymmetry = expression == BlobExpression::CONFUSED ? 0.58f : 0.25f;
            p.eyeSize = 1.1f; p.mouthSmile = -0.35f; p.mouthSkew = 0.35f;
            p.eyeTilt = expression == BlobExpression::WORRIED ? -0.7f : -0.25f;
            p.mouthWidth = 0.65f;
            p.sweat = expression == BlobExpression::WORRIED ? 0.7f : 0.0f;
            break;
        case BlobExpression::THINKING:
        case BlobExpression::DEEP_THINKING:
            p.lean = (expression == BlobExpression::DEEP_THINKING ? 0.06f : 0.12f)
                     * (0.7f + 0.3f * std::sin(t * 1.35f)) * weight;
            p.gazeX = 1.0f; p.gazeY = -1.1f;
            p.eyeAsymmetry = 0.48f;
            p.eyeOpen = expression == BlobExpression::DEEP_THINKING ? 0.62f : 0.86f;
            p.mouthSmile = 0.12f; p.mouthSkew = 1.0f; p.mouthWidth = 0.55f;
            p.bubbles = expression == BlobExpression::DEEP_THINKING ? 0.85f : 0.9f;
            p.arms = expression == BlobExpression::THINKING ? -0.65f : 0.0f;
            break;
        case BlobExpression::FOCUSED:
        case BlobExpression::WORKING:
            p.lean = 0.09f * weight; p.eyeOpen = 0.55f; p.eyeTilt = 0.35f; p.mouthSmile = 0.1f;
            p.bubbles = expression == BlobExpression::WORKING ? 0.75f : 0.2f;
            p.workFlow = expression == BlobExpression::WORKING ? 1.0f : 0.0f;
            p.arms = expression == BlobExpression::WORKING ? 0.35f : 0.0f;
            break;
        case BlobExpression::LISTENING:
            p.height += 0.045f * weight; p.eyeSize = 1.18f; p.mouthSmile = 0.45f;
            break;
        case BlobExpression::SPEAKING:
            p.mouthSmile = 0.9f;
            p.mouthOpen = 0.28f + 0.48f * (0.5f + 0.5f * std::sin(t * 14.0f));
            p.lift = 1.1f * std::sin(t * 6.0f);
            break;
        case BlobExpression::ANGRY:
        case BlobExpression::PLAYFUL_ANGRY:
        case BlobExpression::FRUSTRATED:
            p.height -= 0.22f * weight; p.eyeOpen = 0.12f; p.eyeTilt = 0.8f;
            p.eyeSqueeze = 1.0f;
            p.mouthSmile = -1.1f;
            p.mouthWidth = 0.65f;
            p.shake = (expression == BlobExpression::FRUSTRATED ? 2.5f : 1.0f)
                      * std::sin(t * 28.0f) * weight;
            if (expression == BlobExpression::PLAYFUL_ANGRY) {
                p.blush = 0.6f; p.mouthSmile = -0.5f;
            }
            break;
        case BlobExpression::SAD:
        case BlobExpression::CRYING:
            p.height -= 0.18f * weight; p.eyeOpen = 0.65f; p.lean = -0.07f;
            p.eyeTilt = -0.9f; p.mouthSmile = -1.3f; p.mouthWidth = 0.75f;
            p.tears = expression == BlobExpression::CRYING ? 1.0f : 0.0f;
            break;
        case BlobExpression::EMBARRASSED:
        case BlobExpression::SHY:
        case BlobExpression::NERVOUS:
            p.height -= 0.10f * weight; p.gazeX = 1.2f; p.gazeY = 0.45f; p.eyeOpen = 0.6f;
            p.mouthSmile = 0.45f; p.mouthSkew = 0.55f; p.mouthWidth = 0.6f;
            p.blush = expression == BlobExpression::NERVOUS ? 0.45f : 1.0f;
            p.shake = expression == BlobExpression::NERVOUS ? 0.6f * std::sin(t * 17.0f) : 0.0f;
            break;
        case BlobExpression::SLEEPY:
        case BlobExpression::SLEEPING:
        case BlobExpression::TIRED:
        case BlobExpression::BORED:
            p.height -= expression == BlobExpression::TIRED ? 0.21f : 0.12f;
            p.eyeOpen = expression == BlobExpression::SLEEPING ? 0.05f : 0.35f;
            p.mouthSmile = expression == BlobExpression::BORED ? -0.15f : 0.0f;
            p.lean = 0.025f * std::sin(t * 0.8f);
            break;
        case BlobExpression::MELTING:
        case BlobExpression::MELTED:
            p.melt = expression == BlobExpression::MELTED ? 1.0f : smooth(age / 1.15f);
            p.height = 1.0f - 0.72f * p.melt;
            p.eyeOpen = 1.0f - 0.72f * p.melt;
            p.mouthSmile = 0.0f; p.mouthWidth = 0.65f;
            p.bubbles = 0.2f * p.melt;
            break;
        case BlobExpression::RECOVERING:
            p.height = 1.0f + 0.10f * pulse(age, 0.55f, 0.25f);
            p.eyeOpen = 0.8f; p.mouthSmile = 0.5f;
            break;
        case BlobExpression::ERROR:
        case BlobExpression::GLITCH:
            p.eyeSize = age < 0.22f ? 1.4f : 1.1f;
            p.eyeAsymmetry = age < 0.22f ? 0.0f : 0.22f;
            p.mouthRound = age < 0.22f ? 1.0f : 0.0f;
            p.mouthSmile = age < 0.22f ? 0.0f : -0.3f;
            p.mouthSkew = 0.35f;
            p.blush = age < 0.22f ? 0.0f : 0.3f;
            p.shake = age < 0.5f ? 1.1f * std::sin(age * 70.0f) : 0.0f;
            p.glitch = expression == BlobExpression::GLITCH && age < 0.16f ? 0.65f : 0.0f;
            break;
        case BlobExpression::SUSPICIOUS:
            p.eyeOpen = 0.52f; p.eyeAsymmetry = 0.16f;
            p.mouthSmile = -0.15f; p.gazeX = -0.5f;
            break;
        case BlobExpression::PROUD:
            p.height += 0.06f; p.eyeOpen = 0.58f; p.mouthSmile = 1.1f;
            break;
        case BlobExpression::REALIZATION:
        case BlobExpression::IDEA:
            p.height += 0.12f * pulse(age, 0.35f, 0.25f);
            p.eyeSize = 1.3f; p.mouthSmile = 1.25f; p.mouthOpen = 0.3f;
            p.sparkles = expression == BlobExpression::IDEA ? 0.8f : 0.4f;
            break;
        case BlobExpression::PLAYFUL:
            p.eyeAsymmetry = 0.9f; p.eyeSmile = 0.0f; p.mouthSmile = 1.3f;
            p.mouthSkew = 0.55f; p.blush = 0.4f;
            p.lean = 0.09f * std::sin(t * 2.8f);
            break;
    }
    // Every facial and body parameter fades toward neutral at intensity zero.
    BlobPose neutral;
    neutral.height += breath;
    const float influence = std::sqrt(unit(intensity));
#define FADE(field) p.field = neutral.field + (p.field - neutral.field) * influence
    FADE(height); FADE(lift); FADE(lean); FADE(shake); FADE(arms); FADE(melt);
    FADE(eyeOpen); FADE(eyeSize); FADE(eyeTilt); FADE(eyeAsymmetry); FADE(gazeX); FADE(gazeY);
    FADE(eyeSqueeze); FADE(eyeSmile); FADE(tears);
    FADE(mouthSmile); FADE(mouthOpen); FADE(mouthRound); FADE(mouthWidth); FADE(mouthSkew);
    FADE(blush); FADE(sweat); FADE(bubbles); FADE(workFlow); FADE(sparkles); FADE(glitch);
#undef FADE
    // The visible side widens as it compresses; depth accounts for the rest.
    p.width = std::min(1.38f, 1.0f / std::sqrt(std::max(0.28f, p.height)));
    return p;
}

void approach(float& current, float target, float blend) {
    current += (target - current) * blend;
}
}

void AnimationController::setExpression(BlobExpression expression, float intensity) {
    if (expression != expression_) expressionTime_ = 0.0f;
    expression_ = expression;
    intensity_ = unit(intensity);
}

void AnimationController::setBlend(BlobExpression secondary, float amount) {
    secondary_ = secondary;
    blend_ = unit(amount);
}

void AnimationController::setAttention(float x, float y, bool hovered) {
    if (!std::isfinite(x) || !std::isfinite(y)) return;
    x = std::clamp(x, -1.0f, 1.0f);
    y = std::clamp(y, -1.0f, 1.0f);
    if (hovered && hovered_) {
        const float delta = x - teaseX_;
        if (std::abs(delta) > 0.12f) {
            const int direction = delta > 0.0f ? 1 : -1;
            if (time_ - lastMoveTime_ > 0.55f) teaseTurns_ = 0;
            else if (lastDirection_ && direction != lastDirection_) ++teaseTurns_;
            if (teaseTurns_ >= 3) teaseRemaining_ = 1.2f;
            lastDirection_ = direction;
            lastMoveTime_ = time_;
            teaseX_ = x;
        }
    } else if (hovered) {
        teaseX_ = x;
    }
    if (hovered) {
        attentionX_ = x;
        attentionY_ = y;
        awakeRemaining_ = 0.85f;
    } else if (hovered_) {
        teaseTurns_ = lastDirection_ = 0;
    }
    hovered_ = hovered;
}

void AnimationController::poke() {
    pokeCount_ = pokeRemaining_ > 0.0f ? std::min(pokeCount_ + 1, 3) : 1;
    pokeRemaining_ = 1.5f;
    pokeAge_ = 0.0f;
    awakeRemaining_ = 1.8f;
}

void AnimationController::update(float dt) {
    if (!std::isfinite(dt) || dt <= 0.0f) return;
    dt = std::clamp(dt, 0.0f, 0.05f);
    time_ += dt;
    expressionTime_ += dt;
    if (hovered_) awakeRemaining_ = std::max(awakeRemaining_, 0.85f);
    else awakeRemaining_ = std::max(0.0f, awakeRemaining_ - dt);
    pokeRemaining_ = std::max(0.0f, pokeRemaining_ - dt);
    teaseRemaining_ = std::max(0.0f, teaseRemaining_ - dt);
    pokeAge_ += dt;
    const float motionTime = reducedMotion_ ? 0.0f : time_;
    const float age = reducedMotion_ ? 2.0f : expressionTime_;
    BlobPose target = targetPose(expression_, intensity_, motionTime, age);
    if (blend_ > 0.0f) {
        const BlobPose second = targetPose(secondary_, intensity_, motionTime, age);
#define MIX(field) target.field += (second.field - target.field) * blend_
        MIX(height); MIX(width); MIX(lift); MIX(lean); MIX(shake); MIX(arms); MIX(melt);
        MIX(eyeOpen); MIX(eyeSize); MIX(eyeTilt); MIX(eyeAsymmetry); MIX(gazeX); MIX(gazeY);
        MIX(eyeSqueeze); MIX(eyeSmile); MIX(tears);
        MIX(mouthSmile); MIX(mouthOpen); MIX(mouthRound); MIX(mouthWidth); MIX(mouthSkew);
        MIX(blush); MIX(sweat); MIX(bubbles); MIX(workFlow); MIX(sparkles); MIX(glitch);
#undef MIX
    }
    const bool awake = hovered_ || awakeRemaining_ > 0.0f || pokeRemaining_ > 0.0f || teaseRemaining_ > 0.0f;
    const bool resting = expression_ == BlobExpression::IDLE || expression_ == BlobExpression::WAITING ||
        expression_ == BlobExpression::LISTENING || expression_ == BlobExpression::CURIOUS ||
        expression_ == BlobExpression::SLEEPING || expression_ == BlobExpression::SLEEPY ||
        expression_ == BlobExpression::TIRED || expression_ == BlobExpression::BORED;
    if (awake && resting) target = targetPose(BlobExpression::CURIOUS, 0.9f, motionTime, age);
    if (pokeRemaining_ > 0.0f) {
        const auto reaction = pokeAge_ < 0.16f ? BlobExpression::SHOCKED :
            pokeCount_ >= 3 ? BlobExpression::PLAYFUL_ANGRY : BlobExpression::PLAYFUL;
        target = targetPose(reaction, 0.9f, motionTime, reducedMotion_ ? 2.0f : pokeAge_);
    } else if (teaseRemaining_ > 0.0f) {
        target = targetPose(BlobExpression::PLAYFUL, 0.9f, motionTime, age);
        target.blush = 0.35f;
    }
    // Incoming emotions remain readable while the raised mask still signals protection.
    const bool showExpression = expression_ != BlobExpression::IDLE && expression_ != BlobExpression::SLEEPING &&
        expression_ != BlobExpression::SLEEPY && expression_ != BlobExpression::TIRED && expression_ != BlobExpression::BORED;
    target.attention = awake || showExpression ? 1.0f : 0.0f;
    if (awake) {
        // Follow deliberate local pointer input even while cloud or screen work is paused.
        target.gazeX = attentionX_ * 1.7f;
        target.gazeY = attentionY_ * 1.5f;
        if (resting && pokeRemaining_ == 0.0f && teaseRemaining_ == 0.0f) {
            target.eyeOpen = std::max(target.eyeOpen, 1.05f);
            target.eyeSize = std::max(target.eyeSize, 1.18f);
            target.mouthSmile = 0.95f;
            target.lean = attentionX_ * 0.055f;
            target.height = std::max(target.height, 1.035f);
        }
    }
    if (reducedMotion_) {
        target.shake = target.lift = target.lean = target.glitch = 0.0f;
    }
    const float speed = expression_ == BlobExpression::SHOCKED || expression_ == BlobExpression::EXTREME_SHOCK
                            ? 24.0f : expression_ == BlobExpression::MELTING ? 5.0f : 10.0f;
    const float blend = 1.0f - std::exp(-speed * dt);
#define BLEND(field) approach(pose_.field, target.field, blend)
    BLEND(height); BLEND(width); BLEND(lift); BLEND(lean); BLEND(shake); BLEND(arms); BLEND(melt);
    BLEND(eyeOpen); BLEND(eyeSize); BLEND(eyeTilt); BLEND(eyeAsymmetry); BLEND(gazeX); BLEND(gazeY);
    BLEND(eyeSqueeze); BLEND(eyeSmile); BLEND(tears);
    BLEND(attention);
    BLEND(mouthSmile); BLEND(mouthOpen); BLEND(mouthRound); BLEND(mouthWidth); BLEND(mouthSkew);
    BLEND(blush); BLEND(sweat); BLEND(bubbles); BLEND(workFlow); BLEND(sparkles); BLEND(glitch);
#undef BLEND
    if (!reducedMotion_ && (expression_ == BlobExpression::IDLE || expression_ == BlobExpression::WAITING ||
                           expression_ == BlobExpression::LISTENING)) {
        const float cycle = std::fmod(time_ + 0.12f * std::sin(time_ * 0.31f), 4.9f);
        // Close and reopen within one short blink, without accumulating closure.
        if (cycle > 3.7f && cycle < 3.9f) {
            const float closure = std::sin((cycle - 3.7f) / 0.2f * 3.14159265f);
            pose_.eyeOpen *= 1.0f - 0.95f * closure;
        }
    }
}
