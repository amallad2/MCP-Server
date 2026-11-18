"""Servidor MCP d'exemple: gestor de tasques amb SQLite.

Adaptat a l'SDK oficial `mcp` 2.x (on `FastMCP` es diu `MCPServer`).

Execució:
    python servidor_tasques.py            # transport stdio (Claude Code / Desktop)
    python servidor_tasques.py --http     # transport HTTP (ampliació)
"""
from __future__ import annotations

import functools
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

if __package__ in (None, ""):
    # Permet executar-lo com a script: python servidor/servidor_tasques.py
    sys.path.insert(0, str(Path(__file__).parent))
    import dades
else:
    from . import dades

# IMPORTANT amb stdio: stdout és el canal del protocol. Res de print()!
# El registre de crides (ampliació) va a stderr i a un fitxer.
log = logging.getLogger("tasques")
log.setLevel(logging.INFO)
_fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
for _h in (logging.StreamHandler(sys.stderr),
           logging.FileHandler(Path(__file__).with_name("crides.log"), encoding="utf-8")):
    _h.setFormatter(_fmt)
    log.addHandler(_h)

mcp = MCPServer(
    "tasques",
    instructions=(
        "Gestor de tasques personals i de classe. Les dates van en format "
        f"AAAA-MM-DD. Avui és {datetime.now().date().isoformat()}."
    ),
)


def eina(func):
    """Registra la crida al log i converteix els errors previstos en ToolError.

    A l'SDK 2.x, una excepció qualsevol (p. ex. ValueError) es tracta com una
    fallada inesperada i el model només veu «Error executing tool ...». Amb
    ToolError, el model rep el missatge i normalment es corregeix sol.
    """
    @functools.wraps(func)
    def embolcall(*args, **kwargs):
        log.info("crida %s %s", func.__name__, json.dumps(kwargs, ensure_ascii=False))
        try:
            return func(*args, **kwargs)
        except dades.ErrorDades as e:
            log.info("error previst a %s: %s", func.__name__, e)
            raise ToolError(str(e)) from e

    return mcp.tool()(embolcall)


def format_tasques(tasques: list[dict]) -> str:
    if not tasques:
        return "No s'ha trobat cap tasca."
    return "\n".join(
        f"[{t['id']}] {'✔' if t['feta'] else '·'} {t['titol']}"
        f" ({t['categoria']}{', fins al ' + t['data_limit'] if t['data_limit'] else ''})"
        for t in tasques
    )


# --- Eines MCP: la docstring i els tipus són el que llegeix el model ---------

@eina
def llistar_tasques(nomes_pendents: bool = True, categoria: str | None = None) -> str:
    """Llista les tasques, ordenades per data límit (les que no en tenen, al final).

    Args:
        nomes_pendents: Si és cert, només mostra les tasques que no estan fetes
        categoria: Filtra per categoria (per exemple 'classe' o 'personal')
    """
    return format_tasques(dades.llistar(nomes_pendents, categoria))


@eina
def cercar_tasques(text: str) -> str:
    """Cerca tasques (fetes o pendents) que continguin un text al títol.

    Args:
        text: Paraula o fragment a buscar
    """
    return format_tasques(dades.cercar(text))


@eina
def crear_tasca(titol: str, data_limit: str | None = None, categoria: str = "personal") -> str:
    """Crea una tasca nova.

    Args:
        titol: Descripció curta de la tasca (1-100 caràcters)
        data_limit: Data límit en format AAAA-MM-DD (opcional)
        categoria: Categoria de la tasca ('classe' o 'personal')
    """
    t = dades.crear(titol, data_limit, categoria)
    return f"Tasca creada amb id {t['id']}: {format_tasques([t])}"


@eina
def modificar_tasca(
    id: int,
    titol: str | None = None,
    data_limit: str | None = None,
    feta: bool | None = None,
    categoria: str | None = None,
    treure_data: bool = False,
) -> str:
    """Modifica una tasca existent. Només canvia els camps que s'indiquen.

    Fes servir aquesta eina també per marcar una tasca com a feta (feta=true).
    Si no saps l'id, busca'l abans amb cercar_tasques o llistar_tasques.

    Args:
        id: Identificador de la tasca
        titol: Títol nou (opcional)
        data_limit: Data límit nova en format AAAA-MM-DD (opcional)
        feta: Cert per marcar-la com a feta, fals per tornar-la a pendent (opcional)
        categoria: Categoria nova (opcional)
        treure_data: Cert per esborrar la data límit
    """
    t = dades.modificar(id, titol, data_limit, feta, categoria, treure_data)
    return f"Tasca {id} actualitzada: {format_tasques([t])}"


@eina
def eliminar_tasca(id: int) -> str:
    """Elimina una tasca de manera definitiva. Confirma-ho amb l'usuari si hi ha dubtes.

    Args:
        id: Identificador de la tasca
    """
    t = dades.eliminar(id)
    return f"Tasca {id} eliminada: {t['titol']}"


@eina
def estadistiques_tasques() -> str:
    """Retorna un resum numèric: total, fetes, pendents, vençudes i recompte per categoria."""
    return json.dumps(dades.estadistiques(), ensure_ascii=False, indent=2)


# --- Recurs (ampliació): context que el client pot llegir sense cridar eines --

@mcp.resource("tasques://resum", name="resum", mime_type="application/json")
def resum() -> str:
    """Resum de l'estat de la base de dades i categories disponibles."""
    return json.dumps(
        {"categories": dades.categories(), **dades.estadistiques()},
        ensure_ascii=False,
        indent=2,
    )


def main() -> None:
    dades.inicialitzar()
    if "--http" in sys.argv:
        mcp.run("streamable-http")
    else:
        mcp.run()  # stdio per defecte


if __name__ == "__main__":
    main()
