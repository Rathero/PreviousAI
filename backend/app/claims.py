"""Fact-checks a text about a place against its report.

Paste an estate agent's listing, a travel blog or what an AI chatbot said about the
place, and every sentence gets a verdict: supported, contradicted, not covered by the
data, or not a claim about hazards at all.

Two steps per sentence:
  A. Is this a claim about natural hazards, and which cards does it talk about? (one
     yes/no question per topic, so a sentence about "floods and fires" gets both);
  B. With ONLY those cards as evidence, does the evidence support it, contradict it or
     say nothing? (one choice; its confidence sets a review flag).
Step B never sees the whole report: unrelated evidence is a distractor.
"""

from __future__ import annotations

import asyncio
import re

from .providers import ai

MAX_SENTENCES = 12
MAX_TEXT = 3000
REVIEW_BELOW = 0.8  # the citation-check cookbook's starting threshold
MAX_TOPICS = 3

VERDICTS = {"supports": "supported", "contradicts": "contradicted", "says_nothing": "not covered"}


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text[:MAX_TEXT])
    return [p.strip() for p in parts if len(p.strip()) >= 12][:MAX_SENTENCES]


def _value(ind: dict) -> str:
    display = (ind.get("extras") or {}).get("display")
    if display:
        return str(display)
    if ind.get("value") is None:
        return "no value"
    return f"{ind['value']:g} {ind.get('unit') or ''}".strip()


# What a card covers, in the words a text would use, where its label falls short:
# "the valley gets plenty of snow" is about the avalanche card (it carries the
# snowfall record), "summer nights are cool" about the heat card (it carries the
# tropical nights), and "the town has never flooded" about the recorded floods.
TOPIC_ABOUT = {
    "avalanche": "avalanches, snow and snowfall",
    "heat": "extreme heat, hot days, and warm or cool nights",
    "flood_zone": "flooding from the river or the sea at this address",
    "flood_history": "floods and flooding problems in this town in the past",
    "rain": "heavy rain, downpours and storms",
    "fire_history": "wildfires and forest fires near this place",
    "wildfire": "wildfire danger and fire-prone weather",
}
# Plain phrases match far better than technical ones: "fires recorded near here in the
# past" is not matched to "wildfires are not a concern this close to the sea".


def topics(report: dict) -> dict[str, dict]:
    """The report cut into evidence topics: one per card, plus what was ruled out."""
    out = {}
    for h in report["hazards"]:
        score = f" ({h['score']:.0f}/100)" if h.get("score") is not None else ""
        facts = [f"{h['label']} at this place: {h['level']}{score}.", h["headline"] + "."]
        # All of them: the snowfall record is the avalanche card's 8th indicator.
        for ind in h["indicators"][:10]:
            p = ind.get("provenance") or {}
            facts.append(f"{ind['label']}: {_value(ind)} ({p.get('period')}; scale: {p.get('scale')}).")
        if h.get("limitation"):
            facts.append("Stated limitation: " + h["limitation"])
        out[h["key"]] = {"label": h["label"], "facts": facts, "card": True,
                         "about": TOPIC_ABOUT.get(h["key"], h["label"].lower())}
    cov = report.get("coverage") or {}
    # The shared-climate-record note is about method, not hazards: as evidence it
    # only distracts (it was picked to judge "wildfires are not a concern").
    ruled_out = [n for n in cov.get("notes") or [] if n != cov.get("shared_series")]
    ruled_out += [f"Not covered by this report: {n['hazard']} ({n['reason']})"
                  for n in cov.get("not_covered") or []]
    if ruled_out:
        out["ruled_out"] = {"label": "Hazards checked and ruled out, or not covered", "facts": ruled_out}
    out["overall"] = {"label": "Overall natural hazard risk",
                      "facts": [f"Overall score {report['overall']['score']}/100 "
                                f"({report['overall']['level']}).",
                                (report.get("narrative") or {}).get("headline") or ""]}
    ol = report.get("outlook") or {}
    if ol.get("events"):
        facts = [ol["headline"] + "."]
        for e in ol["events"]:
            c = e.get("climatology") or {}
            facts.append(f"{e['label']}: forecast {e['forecast']['expected_days']} days, "
                         f"{e['forecast']['prob_any'] * 100:.0f} % chance of at least one; "
                         f"usual {c.get('expected_days', '?')} days, "
                         f"{(c.get('prob_any') or 0) * 100:.0f} %.")
        out["forecast"] = {"label": "Weather forecast for the next 15 days", "facts": facts}
    return out


async def _classify(sentence: str, place: str, tp: dict, meter: ai.Meter) -> dict:
    questions = {"about": ai.noul(
        "The sentence makes a claim about natural hazards, climate, weather, flooding, fire, avalanches, snow, "
        "earthquakes, volcanoes, air quality or the physical safety of the place.",
        false="It is about something else: the property, prices, services, views, food or culture")}
    questions |= {f"t_{k}": ai.noul(f"The sentence talks about this topic: {t.get('about', t['label'].lower())}.")
                  for k, t in tp.items()}
    result = meter.add(await ai.ask({"sentence": sentence, "place": place}, questions))
    a = result["answers"]
    ranked = sorted(((k, a[f"t_{k}"]["noul"]) for k in tp), key=lambda kv: -kv[1])
    chosen = [k for k, p in ranked if p >= 0.5]
    # Hazard cards first: "the river has never caused problems" also matched "ruled
    # out" and "overall", and their facts came first as the evidence shown.
    chosen = [k for k in chosen if tp[k].get("card")] + [k for k in chosen if not tp[k].get("card")]
    return {"about": a["about"]["noul"], "topics": chosen[:MAX_TOPICS]}


async def _judge(sentence: str, place: str, tp: dict, keys: list[str], meter: ai.Meter) -> dict:
    evidence = {tp[k]["label"]: tp[k]["facts"] for k in keys}
    q = {"relation": ai.choice(
        "How does the evidence about this place relate to the claim?",
        {"supports": "The evidence states the claim or directly implies that it is true",
         "contradicts": "The evidence states the opposite of the claim or implies it is false",
         "says_nothing": "The evidence does not address what the claim asserts, either way"})}
    result = meter.add(await ai.ask({"claim": sentence, "place": place, "evidence": evidence}, q))
    return result["answers"]["relation"]


async def check(report: dict, text: str) -> dict:
    sentences = split_sentences(text)
    if not sentences:
        return {"sentences": [], "summary": {}, "error": "No sentences long enough to check."}
    if not ai.available():
        return {"sentences": [], "summary": {},
                "unavailable": "Claim checking needs an AI key on the server "
                               "(NEBIUS_API_KEY or TYPESAFE_API_KEY)."}
    tp = topics(report)
    place = report["location"]["label"]
    meter = ai.Meter()
    try:
        classes = await asyncio.gather(*(_classify(s, place, tp, meter) for s in sentences))
        to_judge = [i for i, c in enumerate(classes) if c["about"] >= 0.5 and c["topics"]]
        judged = await asyncio.gather(*(_judge(sentences[i], place, tp, classes[i]["topics"], meter)
                                        for i in to_judge))
    except ai.AIUnavailable as exc:
        return {"sentences": [], "summary": {}, "unavailable": str(exc)}
    verdicts = dict(zip(to_judge, judged))

    out = []
    for i, (sentence, c) in enumerate(zip(sentences, classes)):
        row = {"text": sentence, "about_hazards": round(c["about"], 3),
               "topics": [{"key": k, "label": tp[k]["label"]} for k in c["topics"]]}
        if i in verdicts:
            v = verdicts[i]
            row.update(verdict=VERDICTS[v["choice"]], confidence=round(v["confidence"], 3),
                       probabilities={VERDICTS[k]: round(p, 3) for k, p in v["probabilities"].items()},
                       review=v["confidence"] < REVIEW_BELOW,
                       evidence=[f for k in c["topics"] for f in tp[k]["facts"][:3]])
        elif c["about"] >= 0.5:
            row.update(verdict="not covered", confidence=None, review=True, evidence=[])
        else:
            row.update(verdict="not a hazard claim", confidence=None, review=False, evidence=[])
        out.append(row)

    summary = {}
    for row in out:
        summary[row["verdict"]] = summary.get(row["verdict"], 0) + 1
    return {
        "sentences": out, "summary": summary, "ai": meter.to_dict(),
        "limitation": ("Each sentence is judged only against this report, which is itself "
                       "limited (see each card). The AI compares meaning, not arithmetic: a claim "
                       "with a different number is usually caught, but check the card before "
                       "relying on a verdict, especially one flagged for review."),
    }
