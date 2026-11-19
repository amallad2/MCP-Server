"""Agent que connecta un model d'Ollama amb el servidor MCP de tasques.

Ollama no parla MCP: aquest programa fa de pont (el «host» en termes de MCP).

    Usuari ──▶ agent ──HTTP /api/chat──▶ Ollama
                 │ ▲
           stdio │ │ resultat
                 ▼ │
          servidor_tasques.py ──▶ SQLite

Ús:
    ollama pull qwen3                       # un model que suporti eines (tools)
    python agent/agent_ollama.py            # mode conversa
    python agent/agent_ollama.py "Quines tasques de classe tinc pendents?"

Variables d'entorn opcionals:
    OLLAMA_HOST   (per defecte http://localhost:11434)
    OLLAMA_MODEL  (per defecte qwen3)
    TASQUES_DB    (la passa al servidor MCP, igual que l'API REST)
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import date
from pathlib import Path

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVIDOR = Path(__file__).resolve().parent.parent / "servidor" / "servidor_tasques.py"
MAX_ITERACIONS = 10  # evita bucles infinits si el model no para de cridar eines

SISTEMA = (
    "Ets un assistent que gestiona les tasques de l'usuari amb les eines disponibles. "
    "Fes servir sempre les eines per consultar o canviar dades; no te les inventis. "
    "Si no saps l'id d'una tasca, busca-la abans. Respon en català i de manera breu. "
    f"Avui és {date.today().isoformat()}."
)


def eines_per_ollama(eines_mcp) -> list[dict]:
    """Converteix les eines MCP al format de 'tools' de l'API d'Ollama."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description or "",
                "parameters": t.input_schema,
            },
        }
        for t in eines_mcp
    ]


def text_resultat(resultat) -> str:
    """Extreu el text d'un CallToolResult de MCP."""
    parts = [c.text for c in resultat.content if getattr(c, "text", None)]
    text = "\n".join(parts) or "(sense contingut)"
    return f"ERROR: {text}" if resultat.is_error else text


class Agent:
    def __init__(self, mcp: ClientSession, http: httpx.AsyncClient, model: str, eines: list[dict]):
        self.mcp, self.http, self.model, self.eines = mcp, http, model, eines
        self.missatges: list[dict] = [{"role": "system", "content": SISTEMA}]

    async def xat(self) -> dict:
        r = await self.http.post(
            "/api/chat",
            json={"model": self.model, "messages": self.missatges,
                  "tools": self.eines, "stream": False},
        )
        r.raise_for_status()
        return r.json()["message"]

    async def cridar_eina(self, nom: str, arguments) -> str:
        if isinstance(arguments, str):  # alguns models envien els arguments com a text JSON
            try:
                arguments = json.loads(arguments or "{}")
            except json.JSONDecodeError:
                return "ERROR: els arguments no són JSON vàlid"
        print(f"  ⚙ {nom}({json.dumps(arguments, ensure_ascii=False)})", file=sys.stderr)
        try:
            resultat = await self.mcp.call_tool(nom, arguments or {})
        except Exception as e:  # eina inexistent, servidor caigut...
            return f"ERROR: {e}"
        return text_resultat(resultat)

    async def preguntar(self, peticio: str) -> str:
        """El bucle de l'agent: petició → crida a eina → resultat → ... → resposta."""
        self.missatges.append({"role": "user", "content": peticio})
        for _ in range(MAX_ITERACIONS):
            resposta = await self.xat()
            self.missatges.append(resposta)
            crides = resposta.get("tool_calls") or []
            if not crides:
                return resposta.get("content", "")
            for crida in crides:
                f = crida["function"]
                resultat = await self.cridar_eina(f["name"], f.get("arguments"))
                # Els errors també es retornen al model: així es pot corregir sol.
                self.missatges.append(
                    {"role": "tool", "tool_name": f["name"], "content": resultat}
                )
        return "He arribat al límit de crides a eines sense una resposta final."


async def main(peticions: list[str], http: httpx.AsyncClient | None = None) -> None:
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    model = os.environ.get("OLLAMA_MODEL", "qwen3")
    params = StdioServerParameters(
        command=sys.executable, args=[str(SERVIDOR)], env=dict(os.environ)
    )
    http = http or httpx.AsyncClient(base_url=host, timeout=300)

    async with http, stdio_client(params) as (r, w), ClientSession(r, w) as mcp:
        await mcp.initialize()
        eines = eines_per_ollama((await mcp.list_tools()).tools)
        print(f"Connectat: {len(eines)} eines, model {model}", file=sys.stderr)
        agent = Agent(mcp, http, model, eines)

        if peticions:
            for p in peticions:
                print(await agent.preguntar(p))
            return

        print("Escriu una petició (o «sortir»).", file=sys.stderr)
        while True:
            try:
                peticio = (await asyncio.to_thread(input, "> ")).strip()
            except (EOFError, KeyboardInterrupt):
                break
            if peticio.lower() in {"sortir", "exit", "quit"}:
                break
            if peticio:
                try:
                    print(await agent.preguntar(peticio))
                except httpx.HTTPError as e:
                    print(f"No puc parlar amb Ollama a {host}: {e}", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
