"""One-off live probe of the independent ES fact gate (no publishing)."""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fact_review import verify_es_script

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
]

for case, expected in cases:
    approved, reason = verify_es_script(case)
    print(f"expected={expected} actual={approved} reason={reason}")
    if approved != expected:
        raise SystemExit(1)
