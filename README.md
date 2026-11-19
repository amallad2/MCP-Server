# Projecte 2n DAM: Servidor MCP propi — solució de referència

Codi de referència del projecte: un **gestor de tasques** amb una base de dades
SQLite compartida per dues portes d'entrada:

```
 App Android ──HTTP/JSON──▶ api_rest.py ─┐
                                         ├──▶ dades.py ──▶ tasques.db (SQLite)
 IA (Claude, Ollama...) ──MCP──▶ servidor_tasques.py ─┘
```

El que canvia la IA ho veu l'app, i al revés, perquè totes dues fan servir
`dades.py` (mateix SQL, mateixes validacions).

## Estructura

| Fitxer | Què hi ha |
|---|---|
| `servidor/dades.py` | Esquema SQLite (2 taules relacionades), validació i operacions CRUD + estadístiques |
| `servidor/servidor_tasques.py` | Servidor MCP: 6 eines, 1 recurs (`tasques://resum`), registre de crides |
| `servidor/api_rest.py` | API REST (FastAPI) per a l'app Android |
| `tests/test_tasques.py` | Tests amb `pytest` de dades, eines MCP, API i dades compartides |
| `agent/agent_ollama.py` | Agent que connecta un model d'Ollama amb el servidor MCP |
| `tests/test_agent.py` | Tests del bucle de l'agent amb un Ollama simulat |

## Posar-ho en marxa

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest            # 22 tests
```

La base de dades es crea sola a `servidor/tasques.db` en arrencar el servidor
o l'API. Per fer servir un altre fitxer: `export TASQUES_DB=/ruta/tasques.db`.

### Servidor MCP

```bash
# Provar les eines sense IA
npx @modelcontextprotocol/inspector python servidor/servidor_tasques.py

# Connectar-lo a Claude Code
claude mcp add tasques -- python /ruta/absoluta/servidor/servidor_tasques.py

# Transport HTTP (ampliació)
python servidor/servidor_tasques.py --http
```

Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "tasques": {
      "command": "python",
      "args": ["/ruta/absoluta/servidor/servidor_tasques.py"]
    }
  }
}
```

### API REST per a l'app

```bash
cd servidor && uvicorn api_rest:app --host 0.0.0.0 --port 8000
```

Documentació interactiva a <http://localhost:8000/docs>. Des de l'emulador
d'Android, l'ordinador és `http://10.0.2.2:8000`.

| Mètode | Ruta | Descripció |
|---|---|---|
| GET | `/tasques?nomes_pendents=&categoria=&q=` | Llistar o cercar |
| GET | `/tasques/{id}` | Una tasca |
| POST | `/tasques` | Crear (`titol`, `data_limit`, `categoria`) |
| PATCH | `/tasques/{id}` | Modificar només els camps enviats |
| DELETE | `/tasques/{id}` | Eliminar |
| GET | `/categories`, `/estadistiques` | Dades auxiliars |

Errors: `400` amb `{"detail": "..."}` si l'entrada no és vàlida, `404` si no existeix.

### Agent amb Ollama (sense pagar cap API)

Ollama no parla MCP: `agent/agent_ollama.py` fa de pont. Arrenca el servidor
MCP, li demana les eines, les passa a Ollama i reenvia cada crida del model
al servidor fins que el model dona la resposta final.

```bash
ollama pull qwen3                      # cal un model que suporti eines
python agent/agent_ollama.py           # mode conversa
python agent/agent_ollama.py "Afegeix una tasca per demà i digue'm quantes en tinc pendents"
```

Variables opcionals: `OLLAMA_HOST` (per defecte `http://localhost:11434`),
`OLLAMA_MODEL` (per defecte `qwen3`) i `TASQUES_DB`. Les crides a eines
es mostren per stderr amb `⚙`. Els tests (`tests/test_agent.py`) proven el
bucle amb el servidor MCP real i un Ollama simulat.

## Notes per a l'SDK `mcp` 2.x

El codi de l'enunciat estava escrit per a `mcp` 1.x. A la versió 2:

- `from mcp.server.fastmcp import FastMCP` → `from mcp.server.mcpserver import MCPServer`.
- Si una eina llança una excepció qualsevol (`ValueError`), el model només rep
  «Error executing tool ...» i perd el missatge. Els errors previstos s'han de
  llançar com a **`ToolError`**. Aquí ho fa el decorador `@eina`, que també
  registra cada crida (stderr + `servidor/crides.log`).

Altres millores respecte a l'exemple de l'enunciat: les connexions es tanquen
(`with sqlite3.connect()` no les tanca), es pot canviar la categoria i esborrar
la data límit, i hi ha `CHECK` a la columna `feta`.

## Recordatori

Amb stdio, **no feu servir `print()`** al servidor MCP: stdout és el canal del protocol.
