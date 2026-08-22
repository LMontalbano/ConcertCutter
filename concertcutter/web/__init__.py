"""Interface web de ConcertCutter, servie par un serveur local.

Rien ne quitte la machine : le serveur écoute sur `127.0.0.1`, l'analyse et le
rendu tournent dans le même processus qu'avant, et le navigateur ne sert que de
surface d'affichage. Le portage change l'interface, pas l'architecture — voir
`docs/portage-web.md` pour ce qui a été écarté, et pourquoi.
"""

from __future__ import annotations
