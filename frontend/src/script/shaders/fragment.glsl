precision highp float;

uniform vec3  uColor; // Viewport resolution (pixels)
uniform vec2  uResolution;
uniform vec4  uMouse;
uniform float uTime;
uniform float uPixelSize;


uniform int   uShapeType;         // 0=square 1=circle 2=tri 3=diamond
const int SHAPE_SQUARE   = 0;
const int SHAPE_CIRCLE   = 1;
const int SHAPE_TRIANGLE = 2;
const int SHAPE_DIAMOND  = 3;
/* ----------------------------------------------------------- */

const int   MAX_CLICKS = 10;

uniform vec2  uClickPos  [MAX_CLICKS];
uniform float uClickTimes[MAX_CLICKS];

out vec4 fragColor;


// ─────────────────────────────────────────────────────────────
// Bayer matrix helpers (ordered dithering thresholds)
// ─────────────────────────────────────────────────────────────
float Bayer2(vec2 a) {
    a = floor(a);
    return fract(a.x / 2. + a.y * a.y * .75);
}

#define Bayer4(a) (Bayer2(.5*(a))*0.25 + Bayer2(a))
#define Bayer8(a) (Bayer4(.5*(a))*0.25 + Bayer2(a))


#define FBM_OCTAVES     5
#define FBM_LACUNARITY  1.25
#define FBM_GAIN        1.
#define FBM_SCALE       4.0          // master scale for uv

/*-------------------------------------------------------------
  1-D hash and 3-D value-noise helpers
-------------------------------------------------------------*/
float hash11(float n) { return fract(sin(n)*43758.5453); }

float vnoise(vec3 p)
{
    vec3 ip = floor(p);
    vec3 fp = fract(p);

    float n000 = hash11(dot(ip + vec3(0.0,0.0,0.0), vec3(1.0,57.0,113.0)));
    float n100 = hash11(dot(ip + vec3(1.0,0.0,0.0), vec3(1.0,57.0,113.0)));
    float n010 = hash11(dot(ip + vec3(0.0,1.0,0.0), vec3(1.0,57.0,113.0)));
    float n110 = hash11(dot(ip + vec3(1.0,1.0,0.0), vec3(1.0,57.0,113.0)));
    float n001 = hash11(dot(ip + vec3(0.0,0.0,1.0), vec3(1.0,57.0,113.0)));
    float n101 = hash11(dot(ip + vec3(1.0,0.0,1.0), vec3(1.0,57.0,113.0)));
    float n011 = hash11(dot(ip + vec3(0.0,1.0,1.0), vec3(1.0,57.0,113.0)));
    float n111 = hash11(dot(ip + vec3(1.0,1.0,1.0), vec3(1.0,57.0,113.0)));

    vec3 w = fp*fp*fp*(fp*(fp*6.0-15.0)+10.0);   // smootherstep

    float x00 = mix(n000, n100, w.x);
    float x10 = mix(n010, n110, w.x);
    float x01 = mix(n001, n101, w.x);
    float x11 = mix(n011, n111, w.x);

    float y0  = mix(x00, x10, w.y);
    float y1  = mix(x01, x11, w.y);

    return mix(y0, y1, w.z) * 2.0 - 1.0;         // [-1,1]
}

/*-------------------------------------------------------------
  Stable fBm – no default args, loop fully static
-------------------------------------------------------------*/
float fbm2(vec2 uv, float t)
{
    vec3 p   = vec3(uv * FBM_SCALE, t);
    float amp  = 1.;
    float freq = 1.;
    float sum  = 1.;

    for (int i = 0; i < FBM_OCTAVES; ++i)
    {
        sum  += amp * vnoise(p * freq);
        freq *= FBM_LACUNARITY;
        amp  *= FBM_GAIN;
    }
    
    return sum * 0.5 + 0.5;   // [0,1]
}


float maskCircle(vec2 p, float cov) {

    float r = sqrt(cov) * .25;
    float d = length(p - 0.5) - r;
    // cheap analytic AA
    float aa = 0.5 * fwidth(d);
    return cov * (1.0 - smoothstep(-aa, aa, d * 2.));
    
}


float maskTriangle(vec2 p, vec2 id, float cov) {
    bool flip = mod(id.x + id.y, 2.0) > 0.5;
    if (flip) p.x = 1.0 - p.x;
    float r = sqrt(cov);
    float d  = p.y - r*(1.0 - p.x);   // signed distance to the edge
    float aa = fwidth(d);             // analytic pixel width
    return cov * clamp(0.5 - d/aa, 0.0, 1.0);
}
float maskDiamond(vec2 p, float cov) {
    float r = sqrt(cov) * 0.564;
    return step(abs(p.x - 0.49) + abs(p.y - 0.49), r);
}

/* ----------------------------------------------------------- */
void main() {

    float pixelSize = uPixelSize; // Size of each pixel in the Bayer matri
    vec2 fragCoord = gl_FragCoord.xy - uResolution * .5;

    // Calculate the UV coordinates for the grid
    float aspectRatio = uResolution.x / uResolution.y;

    vec2 pixelId = floor(fragCoord / pixelSize); // integer Bayer cell
    vec2 pixelUV = fract(fragCoord / pixelSize); 

    float cellPixelSize =  8. * pixelSize; // 8x8 Bayer matrix
    vec2 cellId = floor(fragCoord / cellPixelSize); // integer Bayer cell
    
    vec2 cellCoord = cellId * cellPixelSize;
    
    
    vec2 uv = cellCoord / uResolution * vec2(aspectRatio, 1.0);

    /* Animated fbm feed ------------------------------------ */
    float feed = fbm2(uv, uTime * 0.05);
    feed = feed * 0.5 - 0.65;                // contrast / brightness

    /* Ripple clicks ---------------------------------------- */
    const float speed     = 0.30;
    const float thickness = 0.10;
    const float dampT     = 1.0;
    const float dampR     = 10.0;

    float ov = 0.0;                           // number of overlapping ripples
    for (int i = 0; i < MAX_CLICKS; ++i) {
        vec2 pos = uClickPos[i];
        if (pos.x < 0.0) continue;           // “empty” slot

        vec2 cuv = (((pos - uResolution * .5 - cellPixelSize * .5) / (uResolution) )) * vec2(aspectRatio, 1.0);

        float t = max(uTime - uClickTimes[i], 0.0);
        float r = distance(uv, cuv);

        float waveR = speed * t;
        float ring  = exp(-pow((r - waveR) / thickness, 2.0));
        float atten = exp(-dampT * t) * exp(-dampR * r);
        float v = ring * atten;
        feed = max(feed, v);
        if (v > 0.5) ov += 1.0;
    }

    float bayer = Bayer8(fragCoord / uPixelSize) - 0.5;
    float bw    = step(0.5, feed + bayer);     // ordered-dither output

    /* ===== mask selection ================================= */
    float coverage = bw;
    float M;
    if      (uShapeType == SHAPE_CIRCLE)   M = maskCircle (pixelUV, coverage);
    else if (uShapeType == SHAPE_TRIANGLE) M = maskTriangle(pixelUV, pixelId, coverage);
    else if (uShapeType == SHAPE_DIAMOND)  M = maskDiamond(pixelUV, coverage);
    else                                   M = coverage;   // default = square
    /* ====================================================== */

    vec3 color = uColor;
    if (uShapeType == SHAPE_SQUARE) {
        // two or more overlapping ripples -> yellow, otherwise blue ink
        color = (ov >= 2.0) ? vec3(1.0, 0.9, 0.0) : uColor;
    }
    fragColor = vec4(color, M);
}
