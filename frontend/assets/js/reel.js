// The home screen's right-hand picture: the same home through a wildfire, a flood, a
// heatwave and an avalanche, four short clips played one after the other in a loop. It
// should read as a living photograph: no sound, no controls, no gap between clips.
// A clip is fetched only when the reel is on screen (it is hidden on narrow screens), the
// next one once the clip playing can play to its end, and the reel pauses off screen.

import { REDUCED_MOTION } from "./util.js";

export function initReel(root) {
  const clips = [...root.querySelectorAll("video[data-src]")];
  // With reduced motion the CSS shows a still instead and nothing is fetched.
  if (REDUCED_MOTION || !clips.length) return;

  let at = 0;              // the clip whose turn it is
  let front = clips[0];    // the clip on top
  let z = 0;
  let onScreen = false;

  const load = (v) => { if (!v.hasAttribute("src")) v.src = v.dataset.src; };
  const play = (v) => {
    load(v);
    // Refused (autoplay blocked) or cut short by pause(): the frame on screen stays.
    v.play().catch(() => {});
  };

  clips.forEach((v, i) => {
    const next = clips[(i + 1) % clips.length];
    v.addEventListener("playing", () => {
      if (v !== front) {
        // Its turn: it fades in on top of the last frame of the clip before, which stays
        // under it until the next turn. Older clips go back to their first frame.
        for (const c of clips) {
          if (c !== v && c !== front && c.classList.contains("on")) {
            c.classList.remove("on");
            c.currentTime = 0;
          }
        }
        v.style.zIndex = String(++z);
        v.classList.add("on");
        front = v;
      }
      // Fetch the next clip once this one has all it needs, so they never share the line.
      if (v.readyState >= HTMLMediaElement.HAVE_ENOUGH_DATA) load(next);
      else v.addEventListener("canplaythrough", () => load(next), { once: true });
    });
    v.addEventListener("ended", () => {
      at = (i + 1) % clips.length;
      if (onScreen) play(next);
    });
  });

  new IntersectionObserver((entries) => {
    onScreen = entries[entries.length - 1].isIntersecting;
    if (onScreen) play(clips[at]);
    else clips[at].pause();
  }).observe(root);
}
