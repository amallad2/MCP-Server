"""Capa de dades compartida: la fan servir el servidor MCP i l'API REST.

Tota la lògica (SQL, validació, regles) viu aquí. Així la IA (via MCP) i l'app
Android (via REST) treballen exactament amb les mateixes dades i les mateixes
regles, i només cal provar-les una vegada.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Iterator

# La ruta es pot canviar amb una variable d'entorn (útil per als tests i per
# fer que MCP i API apuntin explícitament al mateix fitxer).
DB_PER_DEFECTE = Path(__file__).with_name("tasques.db")


def ruta_bd() -> Path:
    return Path(os.environ.get("TASQUES_DB", DB_PER_DEFECTE))


class ErrorDades(ValueError):
    """Error previst (entrada no vàlida). El missatge el llegeix el model o l'usuari."""


class NoTrobat(ErrorDades):
    """El registre demanat no existeix."""


# --- Connexió ---------------------------------------------------------------

@contextmanager
def connexio() -> Iterator[sqlite3.Connection]:
    """Obre una connexió, fa commit si tot va bé (rollback si no) i la tanca.

    Nota: `with sqlite3.connect(...) as con` només gestiona la transacció, NO
    tanca la connexió. Per això fem servir aquest context propi.
    """
    con = sqlite3.connect(ruta_bd())
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    try:
        with con:
            yield con
    finally:
        con.close()


ESQUEMA = """
CREATE TABLE IF NOT EXISTS categories (
    id  INTEGER PRIMARY KEY,
    nom TEXT UNIQUE NOT NULL
);
CREATE TABLE IF NOT EXISTS tasques (
    id           INTEGER PRIMARY KEY,
    titol        TEXT NOT NULL,
    data_limit   TEXT,
    feta         INTEGER NOT NULL DEFAULT 0 CHECK (feta IN (0, 1)),
    categoria_id INTEGER NOT NULL REFERENCES categories(id)
);
INSERT OR IGNORE INTO categories (nom) VALUES ('classe'), ('personal');
"""


def inicialitzar() -> None:
    """Crea les taules i les categories inicials si no existeixen."""
    with connexio() as con:
        con.executescript(ESQUEMA)


# --- Validació --------------------------------------------------------------

def validar_titol(titol: str) -> str:
    titol = (titol or "").strip()
    if not 1 <= len(titol) <= 100:
        raise ErrorDades("El títol ha de tenir entre 1 i 100 caràcters")
    return titol


def validar_data(data_limit: str | None) -> str | None:
    if data_limit is None or data_limit == "":
        return None
    try:
        return date.fromisoformat(data_limit).isoformat()
    except ValueError:
        raise ErrorDades(
            "La data ha de tenir el format AAAA-MM-DD, per exemple 2026-12-01"
        ) from None


def validar_id(id: int) -> int:
    if isinstance(id, bool) or not isinstance(id, int) or id < 1:
        raise ErrorDades("L'id ha de ser un enter positiu")
    return id


def id_categoria(con: sqlite3.Connection, nom: str) -> int:
    fila = con.execute(
        "SELECT id FROM categories WHERE nom = ?", ((nom or "").strip().lower(),)
    ).fetchone()
    if fila is None:
        noms = [f["nom"] for f in con.execute("SELECT nom FROM categories ORDER BY nom")]
        raise ErrorDades(f"La categoria '{nom}' no existeix. Categories: {', '.join(noms)}")
    return fila["id"]


# --- Operacions (CRUD) ------------------------------------------------------

CONSULTA = """
    SELECT t.id, t.titol, t.data_limit, t.feta, c.nom AS categoria
    FROM tasques t JOIN categories c ON c.id = t.categoria_id
"""


def a_dict(fila: sqlite3.Row) -> dict:
    return {
        "id": fila["id"],
        "titol": fila["titol"],
        "data_limit": fila["data_limit"],
        "feta": bool(fila["feta"]),
        "categoria": fila["categoria"],
    }


def llistar(nomes_pendents: bool = True, categoria: str | None = None) -> list[dict]:
    sql, params = CONSULTA + " WHERE 1 = 1", []
    if nomes_pendents:
        sql += " AND t.feta = 0"
    with connexio() as con:
        if categoria:
            sql += " AND t.categoria_id = ?"
            params.append(id_categoria(con, categoria))
        sql += " ORDER BY t.data_limit IS NULL, t.data_limit, t.id"
        return [a_dict(f) for f in con.execute(sql, params)]


def cercar(text: str) -> list[dict]:
    text = (text or "").strip()
    if not text:
        raise ErrorDades("Cal indicar un text per cercar")
    with connexio() as con:
        files = con.execute(
            CONSULTA + " WHERE t.titol LIKE ? ORDER BY t.id", (f"%{text}%",)
        )
        return [a_dict(f) for f in files]


def obtenir(id: int) -> dict:
    validar_id(id)
    with connexio() as con:
        fila = con.execute(CONSULTA + " WHERE t.id = ?", (id,)).fetchone()
    if fila is None:
        raise NoTrobat(f"No existeix cap tasca amb id {id}")
    return a_dict(fila)


def crear(titol: str, data_limit: str | None = None, categoria: str = "personal") -> dict:
    titol, data_limit = validar_titol(titol), validar_data(data_limit)
    with connexio() as con:
        cur = con.execute(
            "INSERT INTO tasques (titol, data_limit, categoria_id) VALUES (?, ?, ?)",
            (titol, data_limit, id_categoria(con, categoria)),
        )
        nou_id = cur.lastrowid
    return obtenir(nou_id)


def modificar(
    id: int,
    titol: str | None = None,
    data_limit: str | None = None,
    feta: bool | None = None,
    categoria: str | None = None,
    treure_data: bool = False,
) -> dict:
    validar_id(id)
    canvis: dict[str, object] = {}
    if titol is not None:
        canvis["titol"] = validar_titol(titol)
    if treure_data:
        canvis["data_limit"] = None
    elif data_limit is not None:
        canvis["data_limit"] = validar_data(data_limit)
    if feta is not None:
        canvis["feta"] = int(feta)

    with connexio() as con:
        if categoria is not None:
            canvis["categoria_id"] = id_categoria(con, categoria)
        if not canvis:
            raise ErrorDades("No s'ha indicat cap canvi")
        # Els noms de camp són nostres (claus fixes), mai de l'usuari:
        # per això és segur construir el SET. Els valors van per paràmetres.
        sets = ", ".join(f"{camp} = ?" for camp in canvis)
        cur = con.execute(
            f"UPDATE tasques SET {sets} WHERE id = ?", (*canvis.values(), id)
        )
        if cur.rowcount == 0:
            raise NoTrobat(f"No existeix cap tasca amb id {id}")
    return obtenir(id)


def eliminar(id: int) -> dict:
    tasca = obtenir(id)  # llança NoTrobat si no existeix
    with connexio() as con:
        con.execute("DELETE FROM tasques WHERE id = ?", (id,))
    return tasca


def categories() -> list[str]:
    with connexio() as con:
        return [f["nom"] for f in con.execute("SELECT nom FROM categories ORDER BY nom")]


def estadistiques() -> dict:
    """Dades agregades: totals, pendents, vençudes i recompte per categoria."""
    avui = date.today().isoformat()
    with connexio() as con:
        total, fetes, vencudes = con.execute(
            """
            SELECT COUNT(*),
                   COALESCE(SUM(feta), 0),
                   COALESCE(SUM(feta = 0 AND data_limit IS NOT NULL AND data_limit < ?), 0)
            FROM tasques
            """,
            (avui,),
        ).fetchone()
        per_categoria = {
            f["nom"]: {"total": f["total"], "pendents": f["pendents"]}
            for f in con.execute(
                """
                SELECT c.nom, COUNT(t.id) AS total,
                       COALESCE(SUM(t.feta = 0), 0) AS pendents
                FROM categories c LEFT JOIN tasques t ON t.categoria_id = c.id
                GROUP BY c.id ORDER BY c.nom
                """
            )
        }
    return {
        "total": total,
        "fetes": fetes,
        "pendents": total - fetes,
        "vencudes": vencudes,
        "per_categoria": per_categoria,
    }
