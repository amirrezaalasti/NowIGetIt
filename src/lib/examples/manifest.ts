/**
 * Public showcase items for /examples.
 *
 * Every entry was produced through the Now I Get It MCP connector by a chat
 * model (Claude) in one session: it wrote the storyboard JSON, chose the
 * production options, wrote the Manim for each scene, and rendered. Quiz and
 * lab payloads are the connector's JSON, stored verbatim except where `note`
 * says otherwise. Media files live under public/samples (see
 * scripts/copy-sample-media.sh) or at NEXT_PUBLIC_SAMPLES_BASE_URL.
 */

import type { InteractiveLesson, PodcastScript, QuizPaper } from "@/lib/api";
import bayesPodcast from "./data/bayes-podcast.json";
import projectileLab from "./data/projectile-lab.json";
import unitCircleQuiz from "./data/unit-circle-quiz.json";

export type ExampleAudience = "hs" | "undergrad" | "general";

export type ExampleScene = { id: string; title: string; narration: string };

type ExampleBase = {
  slug: string;
  title: string;
  tagline: string;
  /** The request the chat model was given. */
  prompt: string;
  audience: ExampleAudience;
  /** Connector tools that produced this item, in call order. */
  tools: string[];
  /** Any hand correction applied after generation, stated plainly. */
  note?: string;
};

export type VideoExample = ExampleBase & {
  kind: "video" | "clip";
  lengthPreset: "clip" | "short" | "standard" | "deep";
  durationSeconds: number;
  narrated: boolean;
  subtitles: boolean;
  video: string;
  poster: string;
  gif?: string;
  /** Scene the GIF was cut from, when it covers one scene rather than the whole video. */
  gifScene?: string;
  scenes: ExampleScene[];
};

export type QuizExample = ExampleBase & { kind: "quiz"; paper: QuizPaper };

export type LabExample = ExampleBase & { kind: "interactive"; lesson: InteractiveLesson };

export type PodcastExample = ExampleBase & {
  kind: "podcast";
  audio: string | null;
  durationSeconds: number;
  script: PodcastScript;
  takeaways: string[];
};

export type Example = VideoExample | QuizExample | LabExample | PodcastExample;

export const AUDIENCE_LABEL: Record<ExampleAudience, string> = {
  hs: "High school",
  undergrad: "Undergrad",
  general: "General audience",
};

/** Resolve a sample file to a URL: same-origin /samples by default, CDN when configured. */
export function sampleUrl(file: string): string {
  const base = (process.env.NEXT_PUBLIC_SAMPLES_BASE_URL || "").trim().replace(/\/+$/, "");
  return base ? `${base}/${file}` : `/samples/${file}`;
}

const VIDEO_TOOLS = [
  "video_planning_spec",
  "create_video",
  "update_video_options",
  "video_codegen_spec",
  "submit_scene_code",
  "render_video",
];

export const EXAMPLES: Example[] = [
  {
    kind: "video",
    slug: "gradient-descent",
    title: "Gradient Descent: Walking Downhill",
    tagline:
      "One rule, x minus learning rate times slope, walks to the bottom of a curve, slows down by itself, and generalizes to any number of dimensions.",
    prompt:
      "Explain gradient descent on a parabola for undergrads: slope gives direction, the update rule, why steps shrink, learning rate too big and too small, and the same idea in two dimensions.",
    audience: "undergrad",
    lengthPreset: "standard",
    durationSeconds: 102,
    narrated: true,
    subtitles: true,
    video: "gradient-descent.mp4",
    poster: "gradient-descent.jpg",
    gif: "gradient-descent.gif",
    gifScene: "scene_3",
    tools: VIDEO_TOOLS,
    scenes: [
      {
        id: "scene_1",
        title: "Where is the bottom?",
        narration:
          "Here is a curve, and here is where we happen to be standing on it. We want the lowest point. The catch: we cannot see the whole curve. We only know the height and the steepness right where we stand.",
      },
      {
        id: "scene_2",
        title: "Slope points uphill",
        narration:
          "The steepness at a point is the slope of the tangent line. For x squared, the slope at x is two x, so here it is negative four. A negative slope means the curve falls as we move right. So downhill is to the right, opposite the sign of the slope.",
      },
      {
        id: "scene_3",
        title: "One step",
        narration:
          "Gradient descent is one rule: move x against the slope, scaled by a learning rate. With a learning rate of 0.3, we jump from negative two to negative zero point eight. Lower already.",
      },
      {
        id: "scene_4",
        title: "Steps shrink on their own",
        narration:
          "Repeat. Every step the slope is smaller, so the same rule produces a smaller move. We never told it to slow down. Near the bottom the ground is nearly flat, and the steps shrink by themselves.",
      },
      {
        id: "scene_5",
        title: "Too big a step",
        narration:
          "Now crank the learning rate up. The step is bigger than the distance to the bottom, so we overshoot to the other side. And each overshoot is worse than the last. Too large a learning rate does not converge. It explodes.",
      },
      {
        id: "scene_6",
        title: "Too small a step",
        narration:
          "Go too small and every step is safe but tiny. After a hundred steps we are still not there. The learning rate is a dial: small enough to be stable, large enough to actually get somewhere.",
      },
      {
        id: "scene_7",
        title: "The same idea in two dimensions",
        narration:
          "With two inputs, the slope becomes a gradient: a vector pointing straight uphill, perpendicular to the contour lines. Step against it, again and again, and you walk down into the bowl. Same rule, more dimensions. That is gradient descent.",
      },
    ],
  },
  {
    kind: "video",
    slug: "pythagorean-theorem",
    title: "Why a² + b² = c² Is True",
    tagline:
      "Four copies of one right triangle, two ways of packing them into the same square, and the leftover area proves the theorem without algebra.",
    prompt:
      "A 60-second visual proof of the Pythagorean theorem for high schoolers using the four-triangles rearrangement inside a square of side a + b, ending with the 3-4-5 check.",
    audience: "hs",
    lengthPreset: "short",
    durationSeconds: 68,
    narrated: true,
    subtitles: true,
    video: "pythagorean-theorem.mp4",
    poster: "pythagorean-theorem.jpg",
    gif: "pythagorean-theorem.gif",
    gifScene: "scene_3",
    tools: VIDEO_TOOLS,
    scenes: [
      {
        id: "scene_1",
        title: "The claim",
        narration:
          "Take any right triangle. Call the two short sides a and b, and the long side c. The claim is about area: the two small squares together fill exactly as much as the big one. Why should that be true?",
      },
      {
        id: "scene_2",
        title: "Four copies in a big square",
        narration:
          "Draw a square whose side is a plus b. Four copies of our triangle fit snugly into the corners. The hole they leave in the middle is a tilted square, and every side of it is c. So the hole has area c squared.",
      },
      {
        id: "scene_3",
        title: "Rearrange the same four triangles",
        narration:
          "Now slide those same four triangles around inside the same square. Pair them up into two rectangles. The leftover space has changed shape. It is now two squares: one a by a, one b by b.",
      },
      {
        id: "scene_4",
        title: "Same square, same pieces, same leftover",
        narration:
          "Same big square. Same four triangles. So whatever is left over must have the same area in both pictures. On the left that leftover is c squared. On the right it is a squared plus b squared. They are equal. That is the whole proof.",
      },
      {
        id: "scene_5",
        title: "Check with 3, 4, 5",
        narration:
          "Check it with numbers. Legs three and four, hypotenuse five. Nine tiles plus sixteen tiles is twenty-five tiles. The picture and the numbers agree.",
      },
    ],
  },
  {
    kind: "video",
    slug: "binary-search",
    title: "Binary Search: Halving the Haystack",
    tagline:
      "Sixteen sorted numbers, one target, and why checking the middle finds it in four steps instead of nine. A million items take about twenty.",
    prompt:
      "A 60-second explainer of binary search for a general audience: compare with linear scan, halve the sorted list each step, count the steps as log2 n, and end with the catch that the data must be sorted.",
    audience: "general",
    lengthPreset: "short",
    durationSeconds: 67,
    narrated: true,
    subtitles: true,
    video: "binary-search.mp4",
    poster: "binary-search.jpg",
    gif: "binary-search.gif",
    gifScene: "scene_3",
    tools: VIDEO_TOOLS,
    scenes: [
      {
        id: "scene_1",
        title: "The slow way",
        narration:
          "Here are sixteen numbers in order, and we want to find 37. The obvious way is to check them one at a time. Nine checks here, and on a bad day it could be all sixteen.",
      },
      {
        id: "scene_2",
        title: "Look in the middle",
        narration:
          "Instead, jump straight to the middle. Thirty-three. It is smaller than 37. Because the list is sorted, everything to the left is even smaller. One check just ruled out half the list.",
      },
      {
        id: "scene_3",
        title: "Halve again",
        narration:
          "Repeat on what is left. The middle is now 52, too big, so the right part goes. Forty-one. Still too big. Thirty-seven. Found it, in four checks instead of nine.",
      },
      {
        id: "scene_4",
        title: "Why halving wins",
        narration:
          "Every check cuts the pile in half. Sixteen becomes eight, four, two, one. Four halvings. Double the list and you pay just one more check. A million items? About twenty checks. That is the power of halving.",
      },
      {
        id: "scene_5",
        title: "The catch: sorted only",
        narration:
          "One catch. If the list is not sorted, the middle tells you nothing. Thirty-seven could be anywhere. So the recipe is: sort first, then search. Halve the haystack until the needle is the only thing left.",
      },
    ],
  },
  {
    kind: "clip",
    slug: "sine-is-a-height",
    title: "Sine Is a Height",
    tagline:
      "A point goes once around the unit circle while its height traces one period of the sine wave. The clip loops seamlessly and ships as a GIF.",
    prompt:
      "A looping GIF clip: a point travels once around the unit circle while its height traces out one period of the sine wave to the right.",
    audience: "general",
    lengthPreset: "clip",
    durationSeconds: 12,
    narrated: false,
    subtitles: false,
    video: "sine-is-a-height.mp4",
    poster: "sine-is-a-height.jpg",
    gif: "sine-is-a-height.gif",
    tools: VIDEO_TOOLS,
    scenes: [
      {
        id: "scene_1",
        title: "Unwrapping the circle",
        narration:
          "Silent clip. The gold dot moves counterclockwise once around the circle; a dashed line carries its height to a tracing point that draws the green sine curve, then everything resets to the opening pose.",
      },
    ],
  },
  {
    kind: "clip",
    slug: "knowledge-graph",
    title: "A Knowledge Graph Answers a Question",
    tagline:
      "Seven entities, seven labeled relations, one question. The answer is a path: born in to London, located in to England. Loops seamlessly and ships as a GIF.",
    prompt:
      "A looping silent GIF clip: a small knowledge graph of entities and labeled relations, where a question is answered by walking one path through the graph.",
    audience: "general",
    lengthPreset: "clip",
    durationSeconds: 12,
    narrated: false,
    subtitles: false,
    video: "knowledge-graph.mp4",
    poster: "knowledge-graph.jpg",
    gif: "knowledge-graph.gif",
    tools: VIDEO_TOOLS,
    scenes: [
      {
        id: "scene_1",
        title: "Walking the edges to the answer",
        narration:
          "Silent clip. The graph is already drawn. A question chip appears, Ada Lovelace lights up, a dot walks the born in edge to London and the located in edge to England, the answer chip reads London, England, then everything fades back to the neutral graph.",
      },
    ],
  },
  {
    kind: "clip",
    slug: "embedding-neighbours",
    title: "Embeddings: Meaning Becomes a Place",
    tagline:
      "Twelve words as points in three loose clusters. Grow a radius around queen and it catches king, monarch and prince: nearest neighbours are just distance. Loops seamlessly and ships as a GIF.",
    prompt:
      "A looping silent GIF clip: words as points in an embedding space, where similar meanings sit close together and a query finds its nearest neighbours by distance.",
    audience: "general",
    lengthPreset: "clip",
    durationSeconds: 12,
    narrated: false,
    subtitles: false,
    video: "embedding-neighbours.mp4",
    poster: "embedding-neighbours.jpg",
    gif: "embedding-neighbours.gif",
    tools: VIDEO_TOOLS,
    scenes: [
      {
        id: "scene_1",
        title: "Nearest neighbours are just distance",
        narration:
          "Silent clip. The point cloud is already drawn. queen turns green, a gold ring grows out of it, king, monarch and prince light up with dashed spokes, a chip lists the three neighbours, then everything fades back to the neutral cloud.",
      },
    ],
  },
  {
    kind: "clip",
    slug: "attention-fan",
    title: "Attention: Each Token Looks at the Others",
    tagline:
      "Eight tokens in a row. chased, was and fast each fan weighted arcs to the rest, and the heaviest arc from was skips mouse and lands on cat. Loops seamlessly and ships as a GIF.",
    prompt:
      "A looping silent GIF clip: a row of tokens where each highlighted token fans weighted attention arcs to the others, thickest to the one it depends on.",
    audience: "general",
    lengthPreset: "clip",
    durationSeconds: 12,
    narrated: false,
    subtitles: false,
    video: "attention-fan.mp4",
    poster: "attention-fan.jpg",
    gif: "attention-fan.gif",
    tools: VIDEO_TOOLS,
    note: "The attention weights are illustrative, chosen by hand to show the pattern; they were not computed by a model.",
    scenes: [
      {
        id: "scene_1",
        title: "The heaviest arc is the dependency",
        narration:
          "Silent clip. The token row is already drawn. chased, then was, then fast get a green ring and fan gold arcs above the row, stroke width proportional to attention weight; the top-weighted token lights green. Each fan clears before the next, and the row ends in its opening state.",
      },
    ],
  },
  {
    kind: "interactive",
    slug: "projectile-angle-explorer",
    title: "Projectile Angle Explorer",
    tagline:
      "Drive launch angle and speed with sliders, predict the best angle, test it, then hit a target 40 m away. Seven learning phases from orient to reflect.",
    prompt:
      "Let me play with projectile motion until I discover for myself why a 45 degree launch angle gives the longest range on flat ground. Sliders for launch angle and launch speed. Show the range and the maximum height as readouts. Guide me through predicting, testing, and a challenge where I have to hit a target.",
    audience: "hs",
    tools: ["create_interactive"],
    note:
      "One value was corrected by hand after generation: the challenge phase's target distance came back as 0 m and was set to 40 m to match the target drawn in the lab.",
    lesson: projectileLab as unknown as InteractiveLesson,
  },
  {
    kind: "quiz",
    slug: "unit-circle-quiz",
    title: "Unit Circle Basics Quiz",
    tagline:
      "Eight questions on sine and cosine as coordinates, radians as arc length, the special angles, and why sin² + cos² = 1. Scored instantly with explanations.",
    prompt:
      "The unit circle: how sine and cosine are the y and x coordinates of a point on the circle, radians as arc length, the special angles 30, 45, 60, 90 degrees and their exact values, and why sine squared plus cosine squared equals one. Mix multiple choice, true/false, and numeric questions.",
    audience: "hs",
    tools: ["create_quiz", "grade_quiz"],
    paper: unitCircleQuiz as unknown as QuizPaper,
  },
  {
    kind: "podcast",
    slug: "bayes-base-rates",
    title: bayesPodcast.title,
    tagline:
      "A host and a guide walk 100,000 people through a rare-disease test and discover why most positive results are false alarms. Chapters and a transcript are included.",
    prompt:
      "Bayes' theorem through a medical test: why a positive result for a rare disease is usually a false alarm. Use a concrete running example: a disease that 1 in 1000 people have, a test that is 99% sensitive and 95% specific, and walk through 100,000 people as a population table so the listener can hear the numbers. End with what base rates mean for everyday decisions.",
    audience: "general",
    tools: ["create_podcast"],
    note:
      "The connector's podcast call failed on the production server (its text-to-speech returns MP3 while the stitcher expected WAV). This episode was produced with the same pipeline code after fixing that step; the fix ships in this repo.",
    audio: "bayes-base-rates.mp3",
    durationSeconds: bayesPodcast.duration_seconds,
    script: bayesPodcast as unknown as PodcastScript,
    takeaways: bayesPodcast.takeaways,
  },
];

export function findExample(slug: string): Example | undefined {
  return EXAMPLES.find((item) => item.slug === slug);
}
