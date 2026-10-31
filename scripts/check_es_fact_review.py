"""One-off live probe of the independent ES fact gate (no publishing)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fact_review import verify_es_script


cases = [
    ({"title": "El tornado de 1925 encendió madera por fricción del aire",
      "script": "El Tri-State Tornado de 1925 creó tanto calor que encendió madera sin tocarla y vaporizó ropa de personas vivas."},
     False),
    ({"title": "El terremoto de Cascadia de 1700 provocó un tsunami en Japón",
      "script": "El 26 de enero de 1700 un gran terremoto en Cascadia generó un tsunami que llegó a Japón."},
     True),
]

for case, expected in cases:
    approved, reason = verify_es_script(case)
    print(f"expected={expected} actual={approved} reason={reason}")
    if approved != expected:
        raise SystemExit(1)
