// The four clips either side of the home form: the same home through a wildfire, a flood,
// a heatwave and an avalanche, playing together in a loop. They should read as living
// photographs: no sound, no controls. Each clip fades in over its last frame (the still
// under it) as it starts, and at its end waits on that frame for the others, so the four
// always start again together. They are fetched only when on screen (they are hidden on
// narrow screens) and pause when they leave it.

import { REDUCED_MOTION } from "./util.js";

export function initClips(root) {
  const clips = [...root.querySelectorAll(".home-clip video[data-src]")];
  // With reduced motion the stills stay and nothing is fetched.
  if (REDUCED_MOTION || !clips.length) return;

  let onScreen = false;
  const play = (v) => {
    if (!v.hasAttribute("src")) v.src = v.dataset.src;
    // Refused (autoplay blocked) or cut short by pause(): the still or the frame stays.
    v.play().catch(() => {});
  };
  // Play the clips still on their way. Once all four are at their end they give way at
  // once to their stills, the very frames they stopped on, and start again together.
  const run = () => {
    if (!onScreen) return;
    const going = clips.filter((v) => !v.ended);
    if (going.length) { going.forEach(play); return; }
    clips.forEach((v) => v.classList.remove("on"));
    void root.offsetHeight;   // settle the hidden state, so each fades in when it plays
    clips.forEach(play);
  };

  clips.forEach((v) => {
    v.addEventListener("playing", () => v.classList.add("on"));
    v.addEventListener("ended", run);
  });

  const seen = new Set();
  const io = new IntersectionObserver((entries) => {
    entries.forEach((e) => (e.isIntersecting ? seen.add(e.target) : seen.delete(e.target)));
    onScreen = seen.size > 0;
    if (onScreen) run();
    else clips.forEach((v) => v.pause());
  });
  root.querySelectorAll(".home-side").forEach((side) => io.observe(side));
}
