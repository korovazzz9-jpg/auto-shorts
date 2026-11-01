"""Sourced and data-driven ES infographic scenes, rendered without an image API."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from infographic_data import normalize_card


SIZE = (1080, 1920)
ROOT = Path(__file__).resolve().parents[1]
FONT_BOLD = ROOT / "assets" / "fonts" / "ArchivoBlack.ttf"
FONT_CONDENSED = ROOT / "assets" / "fonts" / "Anton.ttf"
INK = "#101925"
WHITE = "#F7F5EC"
MUTED = "#A9B7C4"
ORANGE = "#FFB14A"
CYAN = "#64D5DF"


def _font(size: int, condensed: bool = False):
    return ImageFont.truetype(str(FONT_CONDENSED if condensed else FONT_BOLD), size)


def _center(draw, xy, text, font, fill=WHITE):
    draw.text(xy, text, font=font, fill=fill, anchor="mm", stroke_width=0)


def _base(label: str, title: tuple[str, ...], eyebrow: str):
    image = Image.new("RGB", SIZE, INK)
    draw = ImageDraw.Draw(image)
    # Quiet background and generous margins keep the diagram clear under Shorts UI.
    for y in range(0, SIZE[1], 5):
        shade = int(28 + 17 * y / SIZE[1])
        draw.line((0, y, SIZE[0], y), fill=(13, shade, 43), width=5)
    draw.rounded_rectangle((70, 150, 1010, 228), radius=35, outline=ORANGE, width=3)
    _center(draw, (540, 188), label, _font(36, True), ORANGE)
    draw.text((84, 294), eyebrow, font=_font(38, True), fill=CYAN)
    for i, line in enumerate(title):
        draw.text((82, 354 + i * 111), line, font=_font(87, True), fill=WHITE)
    draw.line((82, 610, 998, 610), fill="#34546A", width=3)
    draw.text((84, 1164), "ESQUEMA VISUAL", font=_font(29, True), fill=MUTED)
    return image, draw


def _ocean(draw):
    # Sea route: lost cargo, current, finds on different coasts.
    draw.rounded_rectangle((82, 665, 998, 1080), radius=34, fill="#123451", outline="#29718A", width=3)
    for y in (950, 994, 1038):
        draw.arc((115, y - 22, 960, y + 32), 185, 355, fill="#286781", width=5)
    draw.rounded_rectangle((155, 735, 360, 838), radius=12, fill="#A86437")
    draw.line((155, 800, 360, 800), fill="#F3B77A", width=6)
    draw.rectangle((207, 700, 309, 735), fill="#DB8950")
    draw.line((260, 672, 260, 700), fill=ORANGE, width=5)
    for x, y in ((472, 854), (640, 795), (826, 863)):
        draw.ellipse((x - 18, y - 18, x + 18, y + 18), fill=ORANGE)
    draw.line((365, 819, 456, 847, 620, 790, 806, 856), fill=CYAN, width=8, joint="curve")
    draw.polygon(((811, 855), (779, 832), (783, 869)), fill=CYAN)
    draw.text((136, 868), "CARGA PERDIDA", font=_font(35, True), fill=WHITE)
    draw.text((530, 933), "CORRIENTES", font=_font(44, True), fill=WHITE, anchor="mm")
    draw.text((84, 1105), "1992 · PACÍFICO NORTE", font=_font(40, True), fill=ORANGE)


def _island(draw):
    draw.rounded_rectangle((82, 665, 998, 1080), radius=34, fill="#123451", outline="#29718A", width=3)
    draw.line((120, 907, 960, 907), fill=CYAN, width=8)
    draw.polygon(((188, 907), (258, 785), (333, 740), (407, 830), (490, 907)), fill="#A75B40")
    draw.polygon(((206, 878), (270, 773), (333, 740), (400, 839)), fill="#E9914B")
    draw.polygon(((564, 907), (649, 823), (718, 805), (786, 857), (855, 907)), fill="#A75B40")
    draw.polygon(((583, 891), (658, 822), (718, 805), (773, 853)), fill="#E9914B")
    for x in (126, 520, 873):
        draw.arc((x, 915, x + 120, 960), 185, 350, fill=CYAN, width=5)
    _center(draw, (330, 1018), "NACE", _font(41, True), WHITE)
    _center(draw, (722, 1018), "CAMBIA", _font(41, True), WHITE)
    draw.line((493, 768, 548, 768), fill=ORANGE, width=7)
    draw.polygon(((557, 768), (530, 748), (530, 788)), fill=ORANGE)
    draw.text((84, 1105), "SURTSEY · DESDE 1963", font=_font(40, True), fill=ORANGE)


def _volcano(draw):
    draw.rounded_rectangle((82, 665, 998, 1080), radius=34, fill="#192D3A", outline="#59646A", width=3)
    draw.line((110, 951, 970, 951), fill="#768890", width=5)
    draw.polygon(((132, 951), (312, 720), (495, 951)), fill="#9A7564")
    draw.polygon(((163, 917), (312, 720), (453, 917)), fill="#C39372")
    draw.polygon(((567, 951), (674, 841), (714, 869), (753, 843), (930, 951)), fill="#9A7564")
    draw.polygon(((606, 922), (674, 841), (714, 869), (753, 843), (878, 922)), fill="#C39372")
    draw.line((312, 720, 730, 720), fill=ORANGE, width=4)
    draw.line((730, 723, 730, 845), fill=ORANGE, width=5)
    draw.polygon(((730, 846), (714, 817), (746, 817)), fill=ORANGE)
    draw.text((758, 756), "≈400 m", font=_font(46, True), fill=ORANGE)
    _center(draw, (318, 1018), "ANTES", _font(41, True), WHITE)
    _center(draw, (740, 1018), "DESPUÉS", _font(41, True), WHITE)
    draw.text((84, 1105), "MONTE SANTA HELENA · 1980", font=_font(38, True), fill=ORANGE)


TEMPLATES = {
    "ocean-toys-1992": ("OCÉANO · 1992", ("UN CARGAMENTO", "SIGUIÓ LAS CORRIENTES"), "DEL BARCO A DISTINTAS COSTAS", _ocean),
    "surtsey-1963": ("ISLANDIA · 1963", ("UNA ISLA NACIÓ", "DEL MAR"), "VOLCÁN, OLAS Y EROSIÓN", _island),
    "st-helens-1980": ("WASHINGTON · 1980", ("EL VOLCÁN PERDIÓ", "SU CIMA"), "ANTES Y DESPUÉS", _volcano),
}


def render_infographic(template_id: str, output_path: str) -> str:
    """Render a factual schematic at the Shorts frame size; unknown IDs are rejected."""
    label, title, eyebrow, paint = TEMPLATES[template_id]
    image, draw = _base(label, title, eyebrow)
    paint(draw)
    image.save(output_path, format="PNG")
    return output_path


_CARD_LABELS = {
    "route": "RUTA DEL HECHO", "before_after": "ANTES / DESPUÉS",
    "timeline": "CRONOLOGÍA", "comparison": "COMPARACIÓN",
}


def _fit_center(draw, x: int, y: int, text: str, width: int, size: int,
                fill=WHITE, minimum: int = 28):
    font = _font(size, True)
    while draw.textbbox((0, 0), text, font=font)[2] > width and size > minimum:
        size -= 2
        font = _font(size, True)
    _center(draw, (x, y), text, font, fill)


def render_card(card: dict, script: str, video_queries: list, output_path: str) -> str:
    """Render one checked card. Invalid or unsupported claims never become a frame."""
    card = normalize_card(card, script, video_queries)
    if card is None:
        raise ValueError("invalid infographic card")
    kind, items = card["type"], card["items"]
    image, draw = _base("DATOS EN 30S", (), _CARD_LABELS[kind])
    _fit_center(draw, 540, 455, card["subject"].upper(), 900, 87)
    draw.rounded_rectangle((82, 665, 998, 1105), radius=34, fill="#123451",
                           outline="#29718A", width=3)

    if kind == "route":
        for x, label, value in ((302, "ORIGEN", items[0]), (778, "DESTINO", items[1])):
            draw.ellipse((x - 64, 724, x + 64, 852), outline=ORANGE, width=7)
            draw.ellipse((x - 17, 771, x + 17, 805), fill=ORANGE)
            _fit_center(draw, x, 918, label, 370, 41, CYAN)
            _fit_center(draw, x, 993, value.upper(), 405, 62)
        draw.line((382, 789, 689, 789), fill=CYAN, width=8)
        draw.polygon(((700, 789), (671, 767), (671, 811)), fill=CYAN)
    elif kind == "before_after":
        for x, label, value in ((295, "ANTES", items[0]), (785, "DESPUÉS", items[1])):
            draw.rounded_rectangle((x - 205, 727, x + 205, 1038), radius=25,
                                   outline="#3F7C8A", width=3)
            _fit_center(draw, x, 811, label, 385, 47, ORANGE)
            draw.line((x - 155, 850, x + 155, 850), fill="#3F7C8A", width=3)
            _fit_center(draw, x, 943, value.upper(), 375, 61)
        draw.polygon(((553, 882), (525, 860), (525, 904)), fill=CYAN)
    elif kind == "timeline":
        for i, value in enumerate(items):
            y = 747 + i * 140
            draw.ellipse((150, y, 220, y + 70), fill=ORANGE)
            _fit_center(draw, 180, y + 35, str(i + 1), 48, 43, INK)
            _fit_center(draw, 600, y + 35, value.upper(), 700, 64)
            if i < 2:
                draw.line((185, y + 72, 185, y + 139), fill=CYAN, width=6)
    else:  # comparison: equal panels avoid implying an unsupported numeric ratio.
        for x, value in ((295, items[0]), (785, items[1])):
            draw.rounded_rectangle((x - 205, 745, x + 205, 1040), radius=25,
                                   outline="#3F7C8A", width=3)
            draw.rectangle((x - 145, 951, x + 145, 982), fill=ORANGE)
            _fit_center(draw, x, 854, value.upper(), 370, 63)
        _fit_center(draw, 540, 1070, "FRENTE A FRENTE", 700, 32, CYAN)

    image.save(output_path, format="PNG")
    return output_path


if __name__ == "__main__":
    directory = ROOT / "assets" / "infographics"
    directory.mkdir(parents=True, exist_ok=True)
    for template_id in TEMPLATES:
        print(render_infographic(template_id, str(directory / f"{template_id}.png")))
