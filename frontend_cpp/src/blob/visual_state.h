#pragma once

// One continuous body and face are reused for every expression.
enum class BlobExpression {
    IDLE, CUTE_SMILE, HAPPY, VERY_HAPPY, EXCITED, LAUGHING,
    SHOCKED, EXTREME_SHOCK, CONFUSED, THINKING, DEEP_THINKING,
    FOCUSED, WORKING, LISTENING, SPEAKING, ANGRY, PLAYFUL_ANGRY,
    FRUSTRATED, SAD, CRYING, EMBARRASSED, NERVOUS, SLEEPY, TIRED,
    MELTING, MELTED, RECOVERING, ERROR, GLITCH, SUCCESS, CELEBRATE,
    CURIOUS, SUSPICIOUS, PROUD, REALIZATION, IDEA, WAITING, BORED,
    WORRIED, SHY, SLEEPING, EATING, PLAYFUL
};

struct BlobPose {
    float height = 1.0f;
    float width = 1.0f;
    float lift = 0.0f;
    float lean = 0.0f;
    float shake = 0.0f;
    float arms = 0.0f;
    float melt = 0.0f;
    float eyeOpen = 1.0f;
    float eyeSize = 1.0f;
    float eyeTilt = 0.0f;
    float eyeAsymmetry = 0.0f;
    float gazeX = 0.0f;
    float gazeY = 0.0f;
    float mouthSmile = 0.6f;
    float mouthOpen = 0.0f;
    float mouthRound = 0.0f;
    float mouthWidth = 1.0f;
    float mouthSkew = 0.0f;
    float blush = 0.0f;
    float sweat = 0.0f;
    float bubbles = 0.0f;
    float workFlow = 0.0f;
    float sparkles = 0.0f;
    float glitch = 0.0f;
};
