/**
 * BSAI H3 Film Factory - Film Prompt Template Library
 * v2.40 (2026-09-20)
 *
 * Categories:
 * 1. Camera Movement
 * 2. Color Grading
 * 3. Aspect Ratio / Composition
 * 4. Cinematic Feel
 */

window.H3_FILM_TEMPLATES = {
  version: "1.0.0",
  categories: [
    {
      id: "camera",
      name: "Camera Movement",
      name_en: "Camera Movement",
      icon: "🎥",
      templates: [
        {
          id: "cam_push_in",
          name: "Slow Push-In",
          prompt: "[Cinematic Camera - Slow Push-In] The camera slowly pushes forward, moving from a wide shot to a close-up of the subject face, building tension and intimacy; focus tightens gradually and the background blurs.",
        },
        {
          id: "cam_pull_back",
          name: "Pull Back",
          prompt: "[Cinematic Camera - Pull Back] The camera slowly pulls back from a close-up to reveal the full environment, evoking loneliness and grand narrative scale as the frame fills with information.",
        },
        {
          id: "cam_pan_left",
          name: "Pan Left",
          prompt: "[Cinematic Camera - Pan Left] The camera pans horizontally from right to left, smoothly sweeping the scene and guiding the viewer eye after the subject, creating a sense of exploration.",
        },
        {
          id: "cam_pan_right",
          name: "Pan Right",
          prompt: "[Cinematic Camera - Pan Right] The camera pans horizontally from left to right, smoothly sweeping the scene and following the subject, creating a sense of pursuit.",
        },
        {
          id: "cam_tilt_up",
          name: "Tilt Up",
          prompt: "[Cinematic Camera - Tilt Up] The camera tilts vertically from bottom to top, moving from feet/ground up to the face/sky, evoking grandeur and the pressure of looking up.",
        },
        {
          id: "cam_tilt_down",
          name: "Tilt Down",
          prompt: "[Cinematic Camera - Tilt Down] The camera tilts vertically from top to bottom, moving from face/sky down to feet/ground, evoking scrutiny and fatefulness.",
        },
        {
          id: "cam_tracking",
          name: "Tracking Shot",
          prompt: "[Cinematic Camera - Tracking Shot] The camera smoothly follows the subject, keeping it centered; slight handheld shake adds realism and immersion, like a bystander viewpoint.",
        },
        {
          id: "cam_dolly",
          name: "Dolly In/Out",
          prompt: "[Cinematic Camera - Dolly] The camera moves smoothly along a track with parallax background scrolling, stable and fluid like professional cinematography.",
        },
        {
          id: "cam_crane",
          name: "Crane Shot",
          prompt: "[Cinematic Camera - Crane] The camera slowly rises or falls, shifting from eye level to high or low angle, evoking epic scale and choreographed staging.",
        },
        {
          id: "cam_orbit",
          name: "Orbit Shot",
          prompt: "[Cinematic Camera - Orbit] The camera circles the subject in a 360-degree or semicircular arc, revealing the subject-environment relationship from multiple angles in an immersive showcase.",
        },
        {
          id: "cam_handheld",
          name: "Handheld",
          prompt: "[Cinematic Camera - Handheld] The camera has natural handheld shake with tight pacing, creating documentary realism and tension like on-site footage.",
        },
        {
          id: "cam_stedicam",
          name: "Steadicam",
          prompt: "[Cinematic Camera - Steadicam] The camera is smooth and fluid like a Steadicam shot, moving through complex scenes without stutter, following the subject naturally with silk-smooth footage.",
        },
      ],
    },
    {
      id: "color",
      name: "Color Grading",
      name_en: "Color Grading",
      icon: "🎨",
      templates: [
        {
          id: "color_warm",
          name: "Warm Tone",
          prompt: "[Cinematic Color - Warm] Overall warm color grade dominated by gold and orange; skin tones warm and ruddy, shadows with brown hues, evoking warmth and nostalgia.",
        },
        {
          id: "color_cool",
          name: "Cool Tone",
          prompt: "[Cinematic Color - Cool] Overall cool color grade dominated by blue and cyan; pale skin tones, shadows with deep blue-gray hues, evoking cold isolation.",
        },
        {
          id: "color_teal_orange",
          name: "Teal & Orange",
          prompt: "[Cinematic Color - Teal and Orange] Classic Hollywood grade: teal-blue shadows and orange highlights, strong contrast, high visual impact, blockbuster quality.",
        },
        {
          id: "color_film_noir",
          name: "Film Noir B&W",
          prompt: "[Cinematic Color - B&W Film] Classic black-and-white film look with high contrast, rich deep-black and pure-white tones and natural gray transitions, like vintage cinema.",
        },
        {
          id: "color_pastel",
          name: "Pastel Macaron",
          prompt: "[Cinematic Color - Pastel] Low-saturation macaron palette, soft and delicate, fresh and elegant, creating a dreamy sweet mood in a Japanese clean style.",
        },
        {
          id: "color_high_contrast",
          name: "High Contrast",
          prompt: "[Cinematic Color - High Contrast] High-contrast grade with strong light/dark opposition, deep shadows and clear highlights, creating drama and tension.",
        },
        {
          id: "color_muted",
          name: "Low-Sat Morandi",
          prompt: "[Cinematic Color - Morandi] Low-saturation Morandi palette with soft gray tones and restrained colors, evoking refinement and an arthouse-film mood.",
        },
        {
          id: "color_neon",
          name: "Neon Cyberpunk",
          prompt: "[Cinematic Color - Neon Cyberpunk] Cyberpunk style with high-saturation neon, pink against cyan, strong night glow, deeply futuristic.",
        },
        {
          id: "color_sepia",
          name: "Vintage Sepia",
          prompt: "[Cinematic Color - Sepia] Vintage sepia grade like old photographs and films, yellowed and nostalgic, evoking history and bygone eras.",
        },
        {
          id: "color_natural",
          name: "Natural Realism",
          prompt: "[Cinematic Color - Natural] Natural true-to-life colors restoring original object hues; skin tones clear and natural, realistic lighting like a documentary.",
        },
      ],
    },
    {
      id: "composition",
      name: "Aspect / Composition",
      name_en: "Aspect / Composition",
      icon: "🎬",
      templates: [
        {
          id: "comp_widescreen",
          name: "Widescreen 2.39:1",
          prompt: "[Composition - Widescreen] 2.39:1 widescreen cinematic ratio with black bars top and bottom, classic film framing, epic and theatrical.",
        },
        {
          id: "comp_letterbox",
          name: "Letterbox",
          prompt: "[Composition - Letterbox] Moderate black bars top and bottom for a cinematic feel while keeping enough vertical space for the subject.",
        },
        {
          id: "comp_rule_thirds",
          name: "Rule of Thirds",
          prompt: "[Composition - Rule of Thirds] Classic rule-of-thirds composition with the subject at third-line intersections, visually balanced and stable, very cinematic.",
        },
        {
          id: "comp_center",
          name: "Centered Symmetry",
          prompt: "[Composition - Centered] Symmetrical centered composition, solemn and ceremonial, ideal for close-ups and formal scenes.",
        },
        {
          id: "comp_leading",
          name: "Leading Lines",
          prompt: "[Composition - Leading Lines] Environmental elements form leading lines that draw the eye naturally to the subject, adding depth and dimensionality.",
        },
        {
          id: "comp_frame_in_frame",
          name: "Frame in Frame",
          prompt: "[Composition - Frame in Frame] Use doors, windows, mirrors, etc. to create a frame-within-frame composition, adding layers and visual interest.",
        },
      ],
    },
    {
      id: "cinematic",
      name: "Cinematic Feel",
      name_en: "Cinematic Feel",
      icon: "✨",
      templates: [
        {
          id: "feel_cinematic",
          name: "Cinematic Quality",
          prompt: "[Cinematic Feel - Quality] Cinematic 8K ultra-HD quality with rich detail, fine light-and-shadow layering, natural depth of field, and moderate film grain.",
        },
        {
          id: "feel_dramatic_light",
          name: "Dramatic Lighting",
          prompt: "[Cinematic Feel - Dramatic Lighting] Dramatic lighting with Rembrandt effects, strong contrast and rich light/shadow layering, full of theatrical tension.",
        },
        {
          id: "feel_soft_light",
          name: "Soft Diffused Light",
          prompt: "[Cinematic Feel - Soft Light] Soft diffused light with blurred shadow edges, fine translucent skin tones, gentle and healing.",
        },
        {
          id: "feel_backlight",
          name: "Backlit Silhouette",
          prompt: "[Cinematic Feel - Backlight] Backlit shot with a golden rim light on the subject edges and a blown-out halo in the background, ethereal and dreamlike.",
        },
        {
          id: "feel_rainy",
          name: "Rainy Night",
          prompt: "[Cinematic Feel - Rainy Night] Rainy night scene with light reflecting on wet ground, visible raindrops and drifting mist, melancholic and romantic.",
        },
        {
          id: "feel_sunset",
          name: "Golden Hour",
          prompt: "[Cinematic Feel - Golden Hour] Sunset golden-hour light with warm golden side light, long shadows and gradient sky colors, warm and nostalgic.",
        },
        {
          id: "feel_night_neon",
          name: "Night Neon",
          prompt: "[Cinematic Feel - Night Neon] Night urban scene with flickering neon, bokeh light effects and reflections on wet streets, cyberpunk mood.",
        },
        {
          id: "feel_misty",
          name: "Misty Atmosphere",
          prompt: "[Cinematic Feel - Mist] Mist-filled scene with hazy distant background and strong aerial perspective, mysterious and poetic.",
        },
        {
          id: "feel_tense",
          name: "Tense Suspense",
          prompt: "[Cinematic Feel - Tense] Low-light suspense atmosphere with strong contrast, heavy shadows and oppressive framing, tense and suspenseful.",
        },
        {
          id: "feel_epic",
          name: "Epic Scale",
          prompt: "[Cinematic Feel - Epic] Epic grand scenes with wide-angle lenses, vast open spaces and tiny figures, evoking history and destiny.",
        },
      ],
    },
  ],
};
