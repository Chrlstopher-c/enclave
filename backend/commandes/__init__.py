"""Domaine `commandes` — `/compact` et `/clear` du chat, exécutées comme des tâches serveur.

Une commande occupe sa conversation comme une génération (`chat.annulation`), tourne dans sa propre tâche
asyncio, et publie sa progression dans la `Diffusion` de la conversation : fermer l'onglet ne l'arrête pas.

Ce paquet n'exporte rien à l'import : `chat` l'appelle depuis ses propres modules, un import ici
créerait un cycle. Les routes sont montées par `main.py`.
"""
