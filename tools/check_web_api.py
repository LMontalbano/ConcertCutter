"""Contrôle du serveur local : les routes, le jeton, et les tranches audio.

Ce que le lot 2 doit garantir, et qu'aucun clic ne vérifie :

- une requête sans jeton n'obtient rien, y compris sur `/api/audio` — c'est la
  seule barrière entre une page ouverte dans un autre onglet et le disque de
  l'utilisateur ;
- l'édition passée par HTTP donne exactement le même résultat que l'appel
  direct à `edits` : mêmes frontières, même numérotation, même annulation ;
- `/api/audio` répond aux requêtes `Range`, sans quoi la balise `<audio>`
  téléchargerait deux gigaoctets avant d'émettre un son ;
- l'enveloppe et les pics arrivent en Float32 de la longueur demandée.

```bash
PYTHONPATH=. python tools/check_web_api.py test/faux_concert.wav
```
"""

from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

from concertcutter.web import server

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def check(label: str, condition: bool) -> bool:
    print(f"  [{'OK ' if condition else 'ECHEC'}] {label}")
    return condition


class Client:
    def __init__(self, address: str, token: str) -> None:
        self.address = address.rstrip("/")
        self.token = token

    def _open(self, route: str, body=None, headers=None, token=True):
        request = urllib.request.Request(
            f"{self.address}{route}",
            data=json.dumps(body).encode("utf-8") if body is not None else None,
            headers={"Content-Type": "application/json",
                     **({"X-ConcertCutter-Token": self.token} if token else {}),
                     **(headers or {})},
            method="POST" if body is not None else "GET")
        return urllib.request.urlopen(request, timeout=120)

    def get(self, route: str, **kwargs) -> dict:
        with self._open(route, **kwargs) as answer:
            return json.loads(answer.read())

    def post(self, route: str, body: dict | None = None, **kwargs) -> dict:
        with self._open(route, body or {}, **kwargs) as answer:
            return json.loads(answer.read())

    def raw(self, route: str, headers=None):
        with self._open(route, headers=headers) as answer:
            return answer.status, dict(answer.headers), answer.read()

    def status(self, route: str, body=None, token=True) -> int:
        try:
            with self._open(route, body, token=token) as answer:
                return answer.status
        except urllib.error.HTTPError as refused:
            return refused.code

    def wait(self, job: dict) -> dict:
        """Attend la fin d'un travail, et rend sa charge utile."""
        while job.get("state") == "running":
            job = self.get(f"/api/job?id={job['id']}")
        return job


def main(wav: Path) -> int:
    ok = True
    httpd, app = server.serve(0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    client = Client(server.url_for(httpd), app.token)

    try:
        print("Le jeton garde la porte")
        ok &= check("sans jeton, l'état est refusé",
                    client.status("/api/state", token=False) == 403)
        ok &= check("sans jeton, l'audio est refusé",
                    client.status("/api/audio", token=False) == 403)
        ok &= check("un jeton faux ne passe pas non plus",
                    Client(client.address, "x" * 40).status("/api/state") == 403)
        ok &= check("avec le jeton, l'état répond",
                    client.status("/api/state") == 200)

        print("\nOuverture d'un enregistrement")
        job = client.wait(client.post("/api/open", {"path": str(wav)}))
        ok &= check("le travail d'ouverture aboutit", job["state"] == "done")
        state = client.get("/api/state")
        ok &= check(f"durée relevée ({state['duration']:.0f} s)",
                    state["duration"] > 1.0)
        ok &= check("enveloppe lue", state["hasLevels"])
        ok &= check("rien n'est encore découpé", not state["segments"])

        print("\nTracé : l'enveloppe entière, puis une fenêtre")
        status, headers, raw = client.raw("/api/envelope")
        heights = np.frombuffer(raw, dtype="<f4")
        ok &= check(f"enveloppe en Float32 ({len(heights)} points)",
                    len(heights) > 10)
        ok &= check("hauteurs entre 0 et 1",
                    bool(heights.min() >= 0.0 and heights.max() <= 1.0))
        ok &= check("les images par seconde accompagnent l'enveloppe",
                    float(headers["X-Fps"]) > 0)
        _, _, raw = client.raw("/api/peaks?start=0&duration=20&width=300")
        window = np.frombuffer(raw, dtype="<f4")
        ok &= check(f"une colonne par pixel demandé ({len(window)})",
                    len(window) == 300)

        print("\nLe WAV se sert par tranches")
        status, headers, raw = client.raw("/api/audio",
                                          headers={"Range": "bytes=0-1023"})
        ok &= check("réponse partielle (206)", status == 206)
        ok &= check(f"mille vingt-quatre octets rendus ({len(raw)})",
                    len(raw) == 1024)
        ok &= check("l'étendue est annoncée",
                    headers.get("Content-Range", "").startswith("bytes 0-1023/"))
        ok &= check("le type dit que c'est du WAV",
                    headers.get("Content-Type") == "audio/wav")

        print("\nAnalyse")
        job = client.wait(client.post("/api/analyze"))
        ok &= check("l'analyse aboutit", job["state"] == "done")
        state = job["result"] or client.get("/api/state")
        tracks = len(state["tracks"])
        ok &= check(f"des morceaux sont trouvés ({tracks})", tracks > 0)
        ok &= check("les descripteurs sont gardés pour le recalage",
                    state["hasFeatures"])

        print("\nÉdition : les mêmes règles qu'en local, à travers HTTP")
        first = state["segments"][0]
        middle = (first["start"] + first["end"]) / 2
        after = client.post("/api/edit", {"op": "split_here", "moment": middle})
        ok &= check("une frontière de plus",
                    len(after["segments"]) == len(state["segments"]) + 1)
        ok &= check("l'annulation est offerte", after["canUndo"])
        back = client.post("/api/undo")
        ok &= check("annuler rend la segmentation d'avant",
                    len(back["segments"]) == len(state["segments"]))
        again = client.post("/api/redo")
        ok &= check("rétablir la remet",
                    len(again["segments"]) == len(state["segments"]) + 1)
        client.post("/api/undo")

        print("\nCe qu'un geste impossible répond")
        ok &= check("couper hors du concert est refusé, sans casser la séance",
                    client.status("/api/edit",
                                  {"op": "split_here", "moment": 1e9}) == 400)
        ok &= check("un geste inconnu aussi",
                    client.status("/api/edit", {"op": "détruire"}) == 400)
        ok &= check("la segmentation n'a pas bougé",
                    len(client.get("/api/state")["segments"])
                    == len(state["segments"]))

        print("\nRecalage sur l'attaque")
        edges = client.get("/api/state")["segments"]
        if len(edges) > 2:
            index = 0
            moved = client.post("/api/edit", {
                "op": "move_boundary", "index": index,
                "moment": edges[index]["end"] + 0.4})
            shifted = moved["segments"][index]["end"]
            snapped = client.post("/api/edit",
                                  {"op": "refine_boundary", "index": index})
            landed = snapped["segments"][index]["end"]
            ok &= check(f"la coupe revient sur l'attaque ({landed:.2f} s)",
                        abs(landed - edges[index]["end"]) <= abs(
                            shifted - edges[index]["end"]))
            client.post("/api/undo")
            client.post("/api/undo")

        # Une coupe qu'on n'a pas touchée est déjà là où le détecteur l'a
        # recalée. Le bouton le disait autrefois par un silence, et empilait
        # dans l'historique une annulation qui ne défaisait rien.
        ok &= check("une coupe déjà calée le dit, au lieu de faire semblant",
                    client.status("/api/edit",
                                  {"op": "refine_boundary", "index": 1}) == 400)

        print("\nTitres et sort des segments")
        named = client.post("/api/edit",
                            {"op": "set_title", "index": 0, "title": "Ouverture"})
        ok &= check("le titre suit son morceau",
                    named["segments"][0]["trackTitle"] == "Ouverture")
        dropped = client.post("/api/edit", {"op": "toggle_kind", "index": 0})
        ok &= check("décocher change le sort du segment",
                    dropped["segments"][0]["kind"] != named["segments"][0]["kind"])
        ok &= check("et le titre reste au chaud sur le segment",
                    dropped["segments"][0]["title"] == "Ouverture")
        client.post("/api/undo")

        # Un morceau peut compter plusieurs segments — c'est ce que « couper
        # ici » produit. Le titre s'écrit alors en tête de la suite, quel que
        # soit le segment depuis lequel on l'a saisi : ailleurs, `track_at` ne
        # l'aurait jamais lu, la tête ayant la priorité.
        head = next(index for index, segment in enumerate(
            client.get("/api/state")["segments"]) if segment["kind"] == "music")
        piece = client.get("/api/state")["segments"][head]
        cut = client.post("/api/edit", {
            "op": "split_here", "moment": (piece["start"] + piece["end"]) / 2})
        if cut["segments"][head + 1]["kind"] == "music":
            from_tail = client.post("/api/edit", {
                "op": "set_title", "index": head + 1, "title": "Depuis la queue"})
            ok &= check("nommer depuis la seconde moitié écrit en tête du morceau",
                        from_tail["segments"][head]["title"] == "Depuis la queue")
            client.post("/api/undo")
        client.post("/api/undo")

        print("\nTravail en cours")
        saved = client.post("/api/save")
        ok &= check("un point de reprise est écrit",
                    bool(saved["saved"]) and Path(saved["saved"]).exists())
        listed = client.get("/api/recent")["projects"]
        ok &= check("il figure dans les travaux récents",
                    any(entry["path"] == saved["saved"] for entry in listed))

        print("\nUn travail repris cale ses coupes sans réanalyser")
        # Le recalage ne lit que le niveau, et l'enveloppe calculée à
        # l'ouverture *est* ce niveau — `audio.envelope` et
        # `spectral.extract().rms_db` s'accordent au millionième de décibel.
        # Rouvrir un travail le lendemain est le cas courant : y trouver le
        # bouton « Caler » grisé pour toujours ne l'était pas moins.
        client.wait(client.post("/api/open", {"path": saved["saved"]}))
        resumed = client.get("/api/state")
        ok &= check("les descripteurs ne sont pas rechargés",
                    not resumed["hasFeatures"])
        ok &= check("mais l'enveloppe est là", resumed["hasLevels"])
        ok &= check(f"le découpage est retrouvé ({len(resumed['tracks'])} morceaux)",
                    len(resumed["tracks"]) > 0)
        edge = next(index for index, segment in enumerate(resumed["segments"])
                    if segment["kind"] == "music")
        nudged = client.post("/api/edit", {
            "op": "move_boundary", "index": edge,
            "moment": resumed["segments"][edge]["end"] + 0.4})
        back = client.post("/api/edit", {"op": "refine_boundary", "index": edge})
        ok &= check("« Caler » marche sans analyse",
                    abs(back["segments"][edge]["end"]
                        - resumed["segments"][edge]["end"])
                    < abs(nudged["segments"][edge]["end"]
                          - resumed["segments"][edge]["end"]))
    finally:
        httpd.shutdown()

    print("\n" + ("TOUT PASSE" if ok else "DES TESTS ECHOUENT"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))
