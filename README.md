# ExecWrite

Application web monopage qui transforme un brouillon professionnel en texte clair, concis et prêt à envoyer : l'essentiel en premier, voix active, sans jargon.

FastAPI sert la page et appelle l'API Claude côté serveur, de sorte que la clé API n'atteint jamais le navigateur. Le résultat s'affiche au fur et à mesure de sa génération.

## Démarrer en local

Prérequis : [uv](https://docs.astral.sh/uv/) et une clé API Anthropic.

```bash
cp .env.example .env
```

Renseignez `ANTHROPIC_API_KEY` dans `.env`, puis lancez le serveur :

```bash
uv run uvicorn execwrite.main:app --reload
```

L'application est disponible sur <http://localhost:8000>.

## Configuration

| Variable | Rôle | Défaut |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | Clé API (obligatoire) | aucun |
| `EXECWRITE_MODEL` | Modèle Claude utilisé | `claude-haiku-5-5` |

## Tests

```bash
uv run pytest
```

Les tests simulent l'API Claude : ils ne consomment aucun crédit et ne vérifient pas la qualité des reformulations.

## Déploiement

```bash
docker build -t execwrite .
docker run -p 8000:8000 --env-file .env execwrite
```

L'image respecte la variable `PORT` imposée par des hébergeurs comme Render ou Railway.

La route `/api/rewrite` n'a ni authentification ni limite de débit. Avant toute mise en ligne publique, protégez-la pour éviter que des tiers consomment votre crédit API.

## Structure

- `execwrite/rewriter.py` : prompt système, ajustements de ton, appel à Claude.
- `execwrite/main.py` : API, validation (2 000 mots maximum), diffusion du résultat.
- `execwrite/static/` : interface en HTML, CSS et JavaScript sans framework.
