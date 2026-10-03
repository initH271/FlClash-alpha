#include <flutter/runtime_effect.glsl>

// Impeller supplies the filter texture dimensions and sampler. Independent
// rounded-capsule refraction, informed by the source cited in the UI research.
uniform vec2 uSize;
uniform vec2 uSurfaceSize;
uniform vec4 uRadii;
uniform sampler2D uBackdrop;
out vec4 fragColor;

float capsuleDistance(vec2 point, vec2 halfSize) {
  float radius = point.y < 0.0
      ? (point.x < 0.0 ? uRadii.x : uRadii.y)
      : (point.x < 0.0 ? uRadii.w : uRadii.z);
  vec2 q = abs(point) - halfSize + radius;
  return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - radius;
}

void main() {
  vec2 pixel = FlutterFragCoord().xy;
  vec2 halfSize = uSurfaceSize * 0.5;
  vec2 point = pixel - uSize * 0.5;
  float distance = capsuleDistance(point, halfSize);
  // Thickness scales with the short side, so logical/DPR units cannot mix.
  float thickness = max(1.0, min(
      min(uSurfaceSize.x, uSurfaceSize.y) * 0.1964,
      max(max(uRadii.x, uRadii.y), max(uRadii.z, uRadii.w)) * 0.7));
  vec2 displaced = pixel;
  if (distance < 0.0 && distance > -thickness) {
    float edge = clamp(1.0 + distance / thickness, 0.0, 1.0);
    vec2 gradient = vec2(
      capsuleDistance(point + vec2(1.0, 0.0), halfSize) - distance,
      capsuleDistance(point + vec2(0.0, 1.0), halfSize) - distance
    );
    vec3 normal = normalize(vec3(gradient * edge,
      sqrt(max(0.0, 1.0 - edge * edge))));
    vec3 ray = refract(vec3(0.0, 0.0, -1.0), normal, 1.0 / 1.5);
    float depth = sqrt(max(0.0, distance * (-2.0 * thickness - distance)));
    displaced += ray.xy * ((depth + 8.0 * thickness) / max(.01, -ray.z)) * .75;
  }
  vec2 uv = clamp(displaced, vec2(.5), uSize - vec2(.5)) / uSize;
#ifdef IMPELLER_TARGET_OPENGLES
  uv.y = 1.0 - uv.y;
#endif
  fragColor = texture(uBackdrop, uv);
}
