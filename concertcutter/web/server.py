"""Le serveur local : six routes, la bibliothèque standard, rien de plus.

`http.server` plutôt qu'un cadriciel. Le `requirements.txt` de ConcertCutter
tient en deux lignes — numpy, soundfile — et FastAPI avec uvicorn ajouteraient
une quinzaine de mégaoctets à un exécutable qui en fait vingt-cinq, pour une
douzaine de routes qui ne servent qu'un seul client au bout d'une boucle
locale.

**Un serveur local qui ouvre un chemin arbitraire est une primitive de lecture
de fichiers.** N'importe quelle page ouverte dans le même navigateur peut
parler à `127.0.0.1`, et si elle le pouvait ici, elle lirait le disque de
l'utilisateur à travers `/api/audio`. Trois barrières, posées tout de suite :

- l'écoute est sur `127.0.0.1`, jamais sur `0.0.0.0` ;
- un jeton aléatoire est tiré à chaque lancement, glissé dans la page servie,
  et exigé sur chaque requête d'API ;
- l'en-tête `Origin` d'une requête venue d'ailleurs est refusé, ce qui coupe
  aussi le cas d'une page qui aurait deviné le jeton.

Les travaux longs ne tiennent pas dans une requête : `/api/analyze` et
`/api/export` rendent un identifiant, et `/api/job` dit où ils en sont.
"""

from __future__ import annotations

import json
import math
import mimetypes
import os
import secrets
import sys
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np

from .. import edits, ffmpeg_install, video
from . import dialogs
from .jobs import Jobs
from .session import MissingSource, Session, SessionError

STATIC = Path(__file__).parent / "static"
CHUNK = 512 * 1024

# Ce que le lecteur du navigateur réclame par tranches. Le WAV d'un concert de
# deux heures pèse deux gigaoctets : sans les requêtes `Range`, la balise
# `<audio>` téléchargerait tout avant d'émettre un son, là où l'ancien lecteur
# MCI ouvrait le même fichier en six centièmes de seconde.
RANGE_TYPES = {".wav": "audio/wav", ".flac": "audio/flac"}


class Application:
    """Ce que les routes partagent : une séance, des travaux, un jeton."""

    def __init__(self) -> None:
        self.session = Session()
        self.jobs = Jobs()
        self.token = secrets.token_urlsafe(32)
        self.quit = threading.Event()
        self.startup = None
        self.on_theme = None


class Handler(BaseHTTPRequestHandler):
    app: Application
    server_version = "ConcertCutter"
    protocol_version = "HTTP/1.1"

    # -- plomberie ---------------------------------------------------------

    def log_message(self, fmt: str, *args) -> None:
        """Silence. Une ligne par requête noierait les vraies erreurs.

        Les échecs, eux, passent par `log_error`, qui reste bavard.
        """

    def _allowed(self) -> bool:
        """Le jeton, et la certitude que la requête ne vient pas d'ailleurs."""
        origin = self.headers.get("Origin")
        if origin and urlparse(origin).hostname not in ("127.0.0.1", "localhost"):
            return False
        sent = self.headers.get("X-ConcertCutter-Token") or self._query().get(
            "token", [""])[0]
        return secrets.compare_digest(sent, self.app.token)

    def _query(self) -> dict:
        return parse_qs(urlparse(self.path).query)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length < 0 or length > 1024 * 1024:
            raise SessionError("Corps de requête trop volumineux.")
        if not length:
            return {}
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise SessionError("Corps JSON illisible.")
        if not isinstance(payload, dict):
            raise SessionError("Le corps JSON doit être un objet.")
        return payload

    def _send(self, payload, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, raw: bytes, kind: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _fail(self, message: str, status: int = 400, **extra) -> None:
        self._send({"error": message, **extra}, status)

    # -- routes ------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 — nom imposé par http.server
        route = urlparse(self.path).path
        if not route.startswith("/api/"):
            self._serve_static(route)
            return
        if not self._allowed():
            self._fail("Jeton absent ou invalide.", HTTPStatus.FORBIDDEN)
            return
        try:
            self._get(route)
        except SessionError as refusal:
            self._fail(str(refusal))
        except (TypeError, ValueError, OverflowError):
            self._fail("Paramètres de requête illisibles.")

    def do_POST(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        if not self._allowed():
            self._fail("Jeton absent ou invalide.", HTTPStatus.FORBIDDEN)
            return
        try:
            self._post(route, self._body())
        except MissingSource as lost:
            self._fail(str(lost), HTTPStatus.CONFLICT, missing=str(lost.source))
        except SessionError as refusal:
            self._fail(str(refusal))
        except (TypeError, ValueError, OverflowError):
            self._fail("Paramètres de requête illisibles.")

    def _get(self, route: str) -> None:
        session, jobs = self.app.session, self.app.jobs
        query = self._query()

        if route == "/api/state":
            payload = session.state()
            startup = self.app.startup
            if startup is not None and startup.state != "done":
                payload["opening"] = startup.payload()
            self._send(payload)
        elif route == "/api/envelope":
            heights = session.envelope_heights()
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("X-Fps", f"{session.levels_fps:.6f}")
            self.send_header("X-Duration", f"{session.duration:.6f}")
            self.send_header("Content-Length", str(heights.nbytes))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(heights.astype("<f4").tobytes())
        elif route == "/api/peaks":
            start = self._float_query(query, "start", 0.0, 0.0, 24 * 3600.0)
            span = self._float_query(query, "duration", 60.0, 0.01, 24 * 3600.0)
            width = self._int_query(query, "width", 1000, 1, 4096)
            heights = session.window_heights(start, span, width)
            self._send_bytes(np.asarray(heights, dtype="<f4").tobytes(),
                             "application/octet-stream")
        elif route == "/api/job":
            job = jobs.get(query.get("id", [""])[0])
            if job is None:
                self._fail("Travail inconnu.", HTTPStatus.NOT_FOUND)
            else:
                self._send(job.payload())
        elif route == "/api/audio":
            self._serve_audio()
        elif route == "/api/recent":
            self._send({"projects": session.recent(),
                        "dialogs": dialogs.available()})
        elif route == "/api/segments":
            self._send(session.segments_payload())
        elif route == "/api/navigate":
            self._send({"moment": self._navigate(query)})
        elif route == "/api/image":
            raw, kind = session.image_bytes(query.get("path", [""])[0])
            self._send_bytes(raw, kind)
        else:
            self._fail("Route inconnue.", HTTPStatus.NOT_FOUND)

    def _post(self, route: str, body: dict) -> None:
        session, jobs = self.app.session, self.app.jobs

        if route == "/api/open":
            self._open(body)
        elif route == "/api/pick":
            self._pick(body)
        elif route == "/api/analyze":
            if jobs.running("analyze"):
                self._fail("Une analyse est déjà en cours.")
                return
            job = jobs.start("analyze", session.analyze, "Préparation…")
            self._send(job.payload())
        elif route == "/api/edit":
            self._send(self._edit(body))
        elif route == "/api/undo":
            self._send(session.undo())
        elif route == "/api/redo":
            self._send(session.redo())
        elif route == "/api/settings":
            session.update_settings(body.get("settings") or {})
            self._send(session.state())
        elif route == "/api/export/plan":
            self._send(session.plan_export(body))
        elif route == "/api/export":
            if jobs.running("export"):
                self._fail("Un export est déjà en cours.")
                return
            job = jobs.start("export", lambda work: session.render(body, work),
                             "Préparation…")
            self._send(job.payload())
        elif route == "/api/save":
            written = session.save()
            self._send({"saved": str(written) if written else "",
                        "when": session.saved})
        elif route == "/api/theme":
            theme = str(body.get("theme", "dark"))
            if self.app.on_theme:
                try:
                    self.app.on_theme(theme)
                except Exception:
                    pass
            self._send({"theme": theme})
        elif route == "/api/ffmpeg":
            self._install_ffmpeg()
        elif route == "/api/quit":
            self._send({"bye": True})
            self.app.quit.set()
        else:
            self._fail("Route inconnue.", HTTPStatus.NOT_FOUND)

    @staticmethod
    def _float_query(query: dict, name: str, fallback: float,
                     low: float, high: float) -> float:
        value = float(query.get(name, [str(fallback)])[0])
        if not math.isfinite(value) or not low <= value <= high:
            raise SessionError(f"Paramètre « {name} » hors limites.")
        return value

    @staticmethod
    def _int_query(query: dict, name: str, fallback: int,
                   low: int, high: int) -> int:
        raw = query.get(name, [str(fallback)])[0]
        value = int(raw)
        if str(value) != str(raw).strip() or not low <= value <= high:
            raise SessionError(f"Paramètre « {name} » hors limites.")
        return value

    # -- gestes ------------------------------------------------------------

    def _open(self, body: dict) -> None:
        """Ouvre un enregistrement ou reprend un travail.

        Sans chemin, c'est Python qui ouvre le dialogue : le navigateur n'en a
        pas à donner. Un dialogue refermé sans rien choisir n'est pas une
        erreur — on rend l'état inchangé.
        """
        path = body.get("path")
        if not path:
            path = (dialogs.ask_project() if body.get("kind") == "project"
                    else dialogs.ask_wav())
        if not path:
            self._send({"cancelled": True, **self.app.session.state()})
            return
        job = self.app.jobs.start(
            "open",
            lambda work: (self.app.session.open(path, work, body.get("source")),
                          self.app.session.state())[1],
            "Import en cours…")
        self._send(job.payload())

    def _pick(self, body: dict) -> None:
        kind = body.get("kind")
        if kind == "dir":
            self._send({"path": dialogs.ask_dir(body.get("start", "")) or ""})
        elif kind == "images":
            # Passées par la liste blanche au passage : ce sont les seules que
            # `/api/image` acceptera de servir en vignette.
            self._send({"paths": self.app.session.allow_image(
                dialogs.ask_images())})
        elif kind == "source":
            self._send({"path": dialogs.ask_source(body.get("name", "")) or ""})
        elif kind == "project":
            self._send({"path": dialogs.ask_project() or ""})
        else:
            self._send({"path": dialogs.ask_wav() or ""})

    def _edit(self, body: dict) -> dict:
        """Une opération d'édition, nommée par le front, exécutée par `edits`.

        Le navigateur ne connaît que des noms de gestes ; les règles restent
        où elles sont. Une opération inconnue est un refus, pas une exception :
        c'est la frontière entre deux programmes.
        """
        session = self.app.session
        operation = body.get("op")
        moment = float(body.get("moment", 0.0))
        index = int(body.get("index", -1))

        if operation == "split_here":
            return session.apply(lambda s: edits.split_here(s, moment))
        if operation == "split_track":
            return session.apply(lambda s: edits.split_track(s, moment))
        if operation == "delete_boundary":
            return session.apply(lambda s: edits.delete_boundary(s, index))
        if operation == "move_boundary":
            return session.apply(lambda s: edits.move_boundary(s, index, moment))
        if operation == "refine_boundary":
            return session.refine(index)
        if operation == "set_kind":
            return session.apply(
                lambda s: edits.set_kinds(s, {index: str(body.get("kind"))}))
        if operation == "set_kinds":
            wanted = {int(key): str(value)
                      for key, value in (body.get("kinds") or {}).items()}
            return session.apply(lambda s: edits.set_kinds(s, wanted))
        if operation == "toggle_kind":
            return session.apply(lambda s: edits.toggle_kind(s, index))
        if operation == "set_title":
            title = str(body.get("title", ""))
            return session.apply(lambda s: edits.set_title(s, index, title))
        raise SessionError(f"Geste inconnu : {operation}")

    def _navigate(self, query: dict) -> float:
        """Où portent les flèches et la touche Origine.

        Un aller-retour par touche, sur une boucle locale, plutôt qu'une copie
        de `edits.section_start` en JavaScript : le « deux fois de suite,
        remonte à la section précédente » tient à un seuil d'une seconde et
        demie, et deux implémentations d'un seuil finissent toujours par
        diverger.
        """
        session = self.app.session
        moment = float(query.get("from", ["0"])[0])
        where = query.get("to", ["next"])[0]
        segments = session.analysis.segments if session.analysis else []
        if where == "section":
            return edits.section_start(segments, session.duration, moment)
        return edits.next_boundary(segments, session.duration, moment,
                                   where == "next")

    def _install_ffmpeg(self) -> None:
        if not ffmpeg_install.supported():
            self._fail("L'installation automatique n'existe que sous Windows.")
            return
        if self.app.jobs.running("ffmpeg"):
            self._fail("L'installation est déjà en cours.")
            return

        def work(job):
            def tick(step: str, done: int, total: int) -> None:
                job.phase = step
                job.done, job.total = done, total

            path = ffmpeg_install.install(progress=tick)
            # `install` a déjà oublié la sonde : la raison est donc relue, pas
            # devinée — une installation qui aboutit sans police utilisable
            # laisse la vidéo indisponible, et il vaut mieux le dire.
            return {"path": str(path), "blocked": video.unavailable_reason()}

        self._send(self.app.jobs.start("ffmpeg", work, "Téléchargement…").payload())

    # -- fichiers ----------------------------------------------------------

    def _serve_audio(self) -> None:
        """Le WAV source, par tranches, tel que `<audio>` le réclame."""
        source = self.app.session.source
        if source is None or not source.exists():
            self._fail("Aucun enregistrement ouvert.", HTTPStatus.NOT_FOUND)
            return
        size = source.stat().st_size
        kind = RANGE_TYPES.get(source.suffix.lower(), "application/octet-stream")
        try:
            start, stop = self._range(size)
        except ValueError:
            self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
            self.send_header("Content-Range", f"bytes */{size}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        with source.open("rb") as handle:
            handle.seek(start)
            self.send_response(HTTPStatus.PARTIAL_CONTENT if stop is not None
                               else HTTPStatus.OK)
            last = (stop if stop is not None else size) - 1
            length = last - start + 1
            self.send_header("Content-Type", kind)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(length))
            if stop is not None:
                self.send_header("Content-Range", f"bytes {start}-{last}/{size}")
            self.end_headers()
            self._pour(handle, length)

    def _range(self, size: int) -> tuple[int, int | None]:
        header = self.headers.get("Range", "")
        if not header.startswith("bytes="):
            return 0, None
        wanted = header[len("bytes="):].strip()
        if "," in wanted or "-" not in wanted:
            raise ValueError("étendue multiple ou illisible")
        first, _, last = wanted.partition("-")
        try:
            if not first:
                suffix = int(last)
                if suffix <= 0:
                    raise ValueError("suffixe vide")
                return max(0, size - suffix), size
            start = int(first)
            if start < 0 or start >= size:
                raise ValueError("début hors fichier")
            stop = int(last) + 1 if last else size
            if stop <= start:
                raise ValueError("fin avant début")
        except ValueError:
            raise
        return start, min(stop, size)

    def _pour(self, handle, length: int) -> None:
        """Verse le fichier par blocs, en supportant l'arrêt du lecteur.

        Le navigateur coupe la connexion dès qu'il a de quoi jouer, ou quand on
        se déplace ailleurs dans le morceau : c'est le fonctionnement normal,
        pas une erreur à remonter.
        """
        while length > 0:
            block = handle.read(min(CHUNK, length))
            if not block:
                break
            try:
                self.wfile.write(block)
            except (BrokenPipeError, ConnectionResetError):
                return
            length -= len(block)

    def _serve_static(self, route: str) -> None:
        """La page et ses fichiers, avec le jeton glissé dans la page.

        Le jeton n'arrive donc jamais par une URL qu'on pourrait relire dans un
        historique : il est écrit dans le document que le navigateur vient de
        recevoir, et n'existe que le temps du lancement.
        """
        if route in ("/", ""):
            route = "/index.html"
        target = (STATIC / route.lstrip("/")).resolve()
        if not target.is_relative_to(STATIC.resolve()):
            self._fail("Chemin refusé.", HTTPStatus.FORBIDDEN)
            return
        if not target.is_file():
            # Une seule page : tout ce qui n'est pas un fichier retombe dessus.
            target = STATIC / "index.html"
        if not target.is_file():
            self._fail("L'interface n'est pas compilée. Voir web/README.md.",
                       HTTPStatus.NOT_FOUND)
            return

        raw = target.read_bytes()
        kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if target.name == "index.html":
            raw = raw.replace(b"__CC_TOKEN__", self.app.token.encode("utf-8"))
            kind = "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(raw)))
        # Rien n'est mis en cache, pas même les polices : tout vient du disque
        # local, l'économie serait nulle, et un fichier recompilé qui ne
        # remplace pas celui du navigateur coûte une heure à comprendre.
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address) -> None:
        """Une connexion coupée par le lecteur n'est pas une erreur.

        La balise `<audio>` demande une tranche, en prend ce qu'il lui faut, et
        raccroche — à chaque déplacement dans le morceau, donc dix fois par
        minute quand on cale une coupe. `socketserver` en imprimait une trace
        d'appels de vingt lignes, qui noyait les vraies.
        """
        if isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionAbortedError,
                                          ConnectionResetError)):
            return
        super().handle_error(request, client_address)

    # Windows laisse deux sockets prendre le même port quand `SO_REUSEADDR` est
    # posé — ce que `HTTPServer` fait par défaut. Deux ConcertCutter lancés
    # coup sur coup écoutaient alors tous les deux sur 8722, chacun avec son
    # jeton, et une requête sur deux tombait chez le mauvais : la fenêtre
    # affichait « jeton invalide » sur un jeton parfaitement valide. Un port
    # déjà pris doit refuser la liaison, pour qu'on puisse en essayer un autre.
    allow_reuse_address = False


def serve(port: int = 0) -> tuple[Server, Application]:
    """Ouvre le serveur sur la boucle locale. Port 0 : le système en choisit un.

    Un port imposé qui n'est pas libre ne fait pas échouer le lancement : on
    retombe sur le choix du système. Refuser de démarrer parce qu'un autre
    programme occupe un numéro serait incompréhensible pour qui double-clique
    un exécutable.
    """
    app = Application()
    handler = type("BoundHandler", (Handler,), {"app": app})
    try:
        return Server(("127.0.0.1", port), handler), app
    except OSError:
        if not port:
            raise
        print(f"Le port {port} est déjà pris : le système en choisit un autre.",
              flush=True)
        return Server(("127.0.0.1", 0), handler), app


def url_for(httpd: Server) -> str:
    host, port = httpd.socket.getsockname()[:2]
    return f"http://{host}:{port}/"


mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("font/woff2", ".woff2")
os.environ.setdefault("PYTHONUNBUFFERED", "1")
