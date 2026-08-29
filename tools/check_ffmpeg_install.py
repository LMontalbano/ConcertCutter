"""L'installation de ffmpeg, de bout en bout.

Ce chemin est le seul de l'application qui aille sur le réseau, et le seul
qu'un utilisateur non technique emprunte sans savoir ce qu'il fait : il vaut
d'être vérifié en vrai, et pas seulement à la lecture.

Trois épreuves, de la moins coûteuse à la plus :

1. le chemin d'installation, et le fait que `find_ffmpeg` regarde bien là où
   `install` dépose — un ffmpeg posé à un endroit que personne ne consulte
   laisserait la vidéo grisée après une installation réussie ;
2. les sources, interrogées en HEAD : joignables, et de la taille attendue ;
3. avec `--vraiment`, l'installation complète, contrôlée par l'exécution du
   binaire obtenu, puis remise en état.
"""

from __future__ import annotations

import argparse
import os
import sys
import urllib.request

from concertcutter import ffmpeg_install, video


def check(label: str, condition: bool) -> bool:
    print(f"  [{'OK ' if condition else 'ECHEC'}] {label}")
    return bool(condition)


def main(really: bool) -> int:
    ok = True

    print("Emplacement")
    target = video.install_dir()
    print(f"  installation dans {target}")
    ok &= check("le dossier d'installation est absolu", target.is_absolute())
    # Le contrat entre les deux modules : l'un écrit, l'autre cherche. Il tient
    # par ce seul chemin, et rien ne le rappellerait s'il divergeait — d'où un
    # faux ffmpeg posé là, qui doit être vu.
    ok &= check("find_ffmpeg consulte le dossier d'installation", _lookup_reaches())

    print("Sources")
    for name, url in ffmpeg_install.SOURCES:
        size = _head(url)
        print(f"  {name} : {ffmpeg_install.human(size) if size else 'injoignable'}")
        ok &= check(f"{name} répond et annonce une archive plausible",
                    size > 20 * 1024 * 1024)

    print("Ménage")
    ok &= _check_sweep()

    if really:
        print("Installation réelle")
        ok &= _check_install()
    else:
        print("Installation réelle : ignorée (--vraiment pour la lancer)")

    print("TOUT PASSE" if ok else "DES TESTS ECHOUENT")
    return 0 if ok else 1


def _lookup_reaches() -> bool:
    """Un ffmpeg déposé à l'emplacement d'installation est-il retrouvé ?

    Vérifié par un fichier témoin plutôt qu'en comparant deux listes de chemins
    écrites chacune de son côté : la copie passerait encore le jour où la
    recherche oublie ce dossier.
    """
    target = video.install_dir()
    exe = target / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
    if exe.exists():
        # Déjà installé : la question est réglée, sans rien écrire.
        video.forget_probe()
        return video.find_ffmpeg() == str(exe)

    os.environ.pop("CONCERTCUTTER_FFMPEG", None)
    target.mkdir(parents=True, exist_ok=True)
    exe.write_bytes(b"")
    try:
        video.forget_probe()
        return video.find_ffmpeg() == str(exe)
    finally:
        exe.unlink()
        video.forget_probe()


def _head(url: str) -> int:
    request = urllib.request.Request(url, method="HEAD",
                                     headers={"User-Agent": "ConcertCutter"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return int(response.headers.get("Content-Length") or 0)
    except Exception as error:
        print(f"    {error}")
        return 0


def _check_sweep() -> bool:
    """Une archive laissée par un téléchargement tué doit disparaître ensuite.

    Le cas se produit quand on ferme l'application pendant le téléchargement :
    le fil meurt au milieu d'une écriture, et cinquante mégaoctets restent dans
    un dossier que l'utilisateur ne relierait à rien.
    """
    target = video.install_dir()
    target.mkdir(parents=True, exist_ok=True)
    stale = target / "cc-ffmpeg-abandonne"
    stale.mkdir(exist_ok=True)
    (stale / "ffmpeg.zip").write_bytes(b"moitie de telechargement")
    temoin = target / "un-fichier-a-moi.txt"
    temoin.write_text("ne pas toucher", encoding="utf-8")
    try:
        ffmpeg_install._sweep(target)
        ok = check("l'archive abandonnée est effacée", not stale.exists())
        ok &= check("rien d'autre n'est touché", temoin.exists())
    finally:
        temoin.unlink(missing_ok=True)
        if stale.exists():
            import shutil
            shutil.rmtree(stale, ignore_errors=True)
    return ok


def _check_install() -> bool:
    """Télécharge pour de bon, puis remet la machine dans l'état trouvé."""
    existed = (video.install_dir() / "ffmpeg.exe").exists()
    seen: list[tuple[str, int, int]] = []
    try:
        path = ffmpeg_install.install(
            progress=lambda step, done, total: seen.append((step, done, total)))
    except Exception as error:
        print(f"    {error}")
        return check("installation aboutie", False)

    ok = check("ffmpeg.exe écrit à l'emplacement attendu",
               path.exists() and path == video.install_dir() / "ffmpeg.exe")
    print(f"  {path} — {ffmpeg_install.human(path.stat().st_size)}")
    ok &= check("avancement rapporté pendant le téléchargement",
                any(step == "download" and done > 0 for step, done, _ in seen))
    ok &= check("l'extraction est rapportée aussi",
                any(step == "extract" for step, _, _ in seen))

    video.forget_probe()
    ok &= check("find_ffmpeg le retrouve", video.find_ffmpeg() == str(path))
    reason = video.unavailable_reason()
    if reason:
        print(f"    {reason}")
    ok &= check("l'export vidéo n'est plus bloqué", reason is None)

    if not existed:
        ok &= check("désinstallation propre", ffmpeg_install.uninstall())
    return ok


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vraiment", action="store_true",
                        help="télécharge réellement l'archive (une centaine de Mo)")
    args = parser.parse_args()
    raise SystemExit(main(args.vraiment))
