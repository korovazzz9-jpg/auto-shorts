"""One bounded, nonpublishing generation → fact review → PNG → video probe."""

import json
import os
import sys
from pathlib import Path

os.environ["CHANNEL"] = "es"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from anthropic import Anthropic
from PIL import Image
from moviepy.editor import ColorClip

from build_video import _build_background
from fact_review import verify_es_script
from generate_script import (_build_user_content, _parse_response, LENGTH_INSTRUCTION,
                             LOOP_INSTRUCTION, build_system_prompt)
from infographic import render_card
from infographic_data import normalize_card


def main():
    output = ROOT / "artifacts" / "es-infographic-probe"
    output.mkdir(parents=True, exist_ok=True)
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], max_retries=0)
    prompt = _build_user_content("volcanoes and earthquakes", "", structure="historical-story")
    prompt += (
        "\nCONTROL CASE, not for publication: use only the documented 1980 Mount St. Helens "
        "event from https://www.usgs.gov/volcanoes/mount-st.-helens . The eruption removed "
        "about 400 m of the summit in a debris avalanche and left a horseshoe-shaped crater. "
        "Do not add casualties, motives or extra numbers. If the spoken script supports it, "
        "supply a before_after visual_card using its own exact short phrases."
    )
    response = client.messages.create(
        model="claude-sonnet-4-6", max_tokens=1800,
        system=build_system_prompt("historical-story") + "\n\n" + LOOP_INSTRUCTION + "\n\n" + LENGTH_INSTRUCTION,
        messages=[{"role": "user", "content": prompt}],
    )
    data = _parse_response(response)
    card = normalize_card(data.get("visual_card"), data.get("script", ""),
                          data.get("video_queries", []))
    print(f"title={data.get('title')} card_generated={bool(card)} card={json.dumps(card, ensure_ascii=False)}")
    if card is None:
        raise RuntimeError("generator did not produce a valid card")
    data["visual_card"] = card
    approved, reason = verify_es_script(data, client=client)
    print(f"script_approved={approved} card_approved={data.get('visual_card') is not None} reason={reason}")
    if not approved or data.get("visual_card") is None:
        raise RuntimeError("independent fact review rejected the script or infographic")

    png = render_card(card, data["script"], data["video_queries"], str(output / "card.png"))
    with Image.open(png) as image:
        assert image.size == (1080, 1920)

    clips = []
    for index, color in enumerate(((25, 46, 64), (37, 58, 70), (51, 68, 76))):
        path = output / f"stock-placeholder-{index}.mp4"
        ColorClip((540, 960), color=color).set_duration(1).write_videofile(
            str(path), fps=8, codec="libx264", audio=False, logger=None)
        clips.append(str(path))
    clips.insert(3, png)
    background = _build_background(clips, 5, visual_loop=True)
    try:
        assert background.get_frame(3.5).shape == (1920, 1080, 3)
        background.write_videofile(str(output / "preview.mp4"), fps=8,
                                   codec="libx264", audio=False, logger=None)
    finally:
        background.close()
    print(f"preview={output / 'preview.mp4'}")


if __name__ == "__main__":
    main()
