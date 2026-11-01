"""One-off live probe of the independent ES fact gate (no publishing)."""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fact_review import repair_es_script, verify_es_script

if "--repair" in sys.argv:
    case = {
        "title": "¿La catarata más grande del mundo está bajo el océano?",
        "script": ("Hay una catarata que cae 3,500 metros — completamente invisible. "
                   "En el Estrecho de Dinamarca, entre Islandia y Groenlandia, agua fría "
                   "del Ártico choca con agua más cálida del Atlántico. La fría pesa más "
                   "y se hunde hacia el fondo. Eso triplica el Salto Ángel. "
                   "El agua fría que tomas hoy pasó por ahí. "
                   "¿Cuántas cosas más esconde el océano? Y así es como."),
        "video_queries": ["Denmark strait ocean", "underwater current"],
        "source_url": "https://oceanservice.noaa.gov/facts/largest-waterfall.html",
        "topic": "the ocean", "has_loop": True,
    }
    revised = repair_es_script(case, "NOAA does not support the claim that drinking water passed through this cataract.")
    approved, reason = verify_es_script(revised)
    print(f"repair_approved={approved} title={revised['title']} reason={reason}")
    if not approved:
        raise SystemExit(1)
    raise SystemExit(0)

if "--queue" in sys.argv:
    queue = json.loads((Path(__file__).resolve().parents[1] / "queue_es.json").read_text(encoding="utf-8"))
    for index, case in enumerate(queue):
        approved, reason = verify_es_script(case)
        print(f"queue_index={index} approved={approved} title={case['title']} reason={reason}")
    raise SystemExit(0)


cases = [
    ({"title": "El tornado de 1925 encendió madera por fricción del aire",
      "script": "El Tri-State Tornado de 1925 creó tanto calor que encendió madera sin tocarla y vaporizó ropa de personas vivas."},
     False),
    ({"title": "El terremoto de Cascadia de 1700 provocó un tsunami en Japón",
      "script": "El 26 de enero de 1700 un gran terremoto en Cascadia generó un tsunami que llegó a Japón."},
     True),
    ({"title": "El señor de El Caño fue enterrado con exactamente 31 sacrificados",
      "script": "En la tumba T9 hallada en 2024 había exactamente 31 sacrificados. Los huesos demuestran que todos estaban bien alimentados y nunca fueron cautivos."},
     False),
    ({"title": "La espada de 2.3 metros que nadie debería poder cargar",
      "script": "En Nara hallaron una espada de 2.37 metros. Nadie la pudo haber blandido: pesa demasiado. Fue creada únicamente para intimidar a los demonios."},
     False),
]

for case, expected in cases:
    approved, reason = verify_es_script(case)
    print(f"expected={expected} actual={approved} reason={reason}")
    if approved != expected:
        raise SystemExit(1)
