"""L'installation de ffmpeg depuis la fenêtre d'export, de bout en bout.

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

La fenêtre elle-même est parcourue au passage : le bouton n'apparaît que quand
c'est ffmpeg qui manque, et jamais quand la vidéo échoue pour une autre raison.
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

    print("Fenêtre d'export")
    ok &= _check_dialog()
    ok &= _check_dialog_progress()

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


def _check_dialog() -> bool:
    """Le bouton suit ce qui manque, pas le simple fait que la vidéo soit hors service."""
    import tkinter as tk

    from concertcutter.ui import export_dialog, theme

    root = tk.Tk()
    root.withdraw()
    theme.apply(root)
    ok = True
    try:
        video.forget_probe()
        present = video.find_ffmpeg() is not None

        dialog = export_dialog.ExportDialog(root)
        offered = dialog._install_row.winfo_manager() != ""
        ok &= check("bouton d'installation proposé si et seulement si ffmpeg manque",
                    offered == (not present and ffmpeg_install.supported()))
        if not present:
            ok &= check("la raison affichée dit quoi faire, pas seulement ce qui manque",
                        dialog._video_desc.cget("text") == export_dialog.FFMPEG_ABSENT)
        dialog.cancel()

        # Un ffmpeg présent mais sans drawtext bloque la vidéo sans que le
        # téléchargement y change rien : le bouton doit se taire.
        video.forget_probe()
        video._probe_cache["ffmpeg"] = "C:/faux/ffmpeg.exe"
        video._probe_cache["filters"] = ""
        dialog = export_dialog.ExportDialog(root)
        ok &= check("pas de bouton quand ffmpeg est là mais incapable",
                    dialog._install_row.winfo_manager() == "")
        dialog.cancel()
    finally:
        video.forget_probe()
        root.destroy()
    return ok


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


def _check_dialog_progress() -> bool:
    """L'avancement s'affiche, et la fenêtre ne bouge pas pendant ce temps.

    Le téléchargement est simulé : ce qui est éprouvé ici est la fenêtre, pas
    le réseau, et cent mégaoctets par exécution en feraient un contrôle qu'on
    n'exécuterait plus.
    """
    import time
    import tkinter as tk

    from concertcutter.ui import export_dialog, theme

    root = tk.Tk()
    root.withdraw()
    theme.apply(root)
    vrai_install = ffmpeg_install.install
    ok = True
    try:
        for issue in ("echec", "succes"):
            ffmpeg_install.install = _fake_install(issue)
            video.forget_probe()
            video._probe_cache["ffmpeg"] = None

            dialog = export_dialog.ExportDialog(root)
            dialog.update()
            avant = (dialog.winfo_width(), dialog.winfo_height())

            dialog.install_ffmpeg()
            seen = ""
            pendant = avant
            deadline = time.monotonic() + 10
            while dialog._installing and time.monotonic() < deadline:
                dialog.update()
                if "%" in dialog._install_state.cget("text") and not seen:
                    seen = dialog._install_state.cget("text")
                    pendant = (dialog.winfo_width(), dialog.winfo_height())
                time.sleep(0.02)
            dialog.update()
            apres = (dialog.winfo_width(), dialog.winfo_height())

            print(f"  {issue} : {avant} -> {pendant} -> {apres}, vu « {seen} »")
            ok &= check(f"[{issue}] avancement chiffré affiché", "%" in seen)
            # Le défaut corrigé : la barre et son compte rendu élargissaient la
            # fenêtre au clic, puis la rétrécissaient à la fin.
            ok &= check(f"[{issue}] rien ne bouge pendant le téléchargement",
                        avant == pendant)
            ok &= check(f"[{issue}] la fenêtre ne s'élargit jamais",
                        avant[0] == apres[0])
            if issue == "echec":
                ok &= check("[echec] la fenêtre garde sa taille", avant == apres)
                ok &= check("[echec] le bouton redevient cliquable",
                            str(dialog._install_button.cget("state")) == "normal")
                ok &= check("[echec] la raison est écrite",
                            "reseau" in dialog._install_state.cget("text"))
            else:
                # Seul mouvement admis, et il se justifie : le bouton n'a plus
                # de raison d'être, la section reprend la taille qu'elle aurait
                # toujours eue sur une machine équipée.
                ok &= check("[succes] la fenêtre se referme sur la place rendue",
                            apres[1] < avant[1])
                ok &= check("[succes] le bouton disparaît",
                            dialog._install_row.winfo_manager() == "")
                ok &= check("[succes] les cases vidéo s'activent",
                            str(dialog._video_full_check.cget("state")) == "normal")
            dialog.cancel()
    finally:
        ffmpeg_install.install = vrai_install
        video.forget_probe()
        root.destroy()
    return ok


def _fake_install(issue: str):
    """Un téléchargement simulé, qui rapporte son avancement puis conclut."""
    import time

    def fake(progress=None, cancelled=None):
        total = 106 * 1024 * 1024
        for done in range(0, total + 1, total // 8):
            if cancelled is not None and cancelled():
                raise ffmpeg_install.Cancelled()
            if progress:
                progress("download", done, total)
            time.sleep(0.05)
        if issue == "echec":
            raise RuntimeError("Le telechargement a echoue : reseau injoignable")
        # Le succès se constate par la disponibilité de la vidéo : on met donc
        # la sonde dans l'état qu'une vraie installation lui laisserait.
        video._probe_cache.update({"ffmpeg": "C:/faux/ffmpeg.exe",
                                   "filters": "drawtext", "encoders": "libx264"})
        return video.install_dir() / "ffmpeg.exe"

    return fake


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
