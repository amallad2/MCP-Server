"""API REST per a l'app Android. Comparteix la base de dades amb el servidor MCP.

Execució:
    uvicorn api_rest:app --host 0.0.0.0 --port 8000
    (des de l'emulador d'Android, l'ordinador és http://10.0.2.2:8000)

Documentació interactiva: http://localhost:8000/docs
"""
from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).parent))
    import dades
else:
    from . import dades


@asynccontextmanager
async def cicle_de_vida(_app: FastAPI):
    dades.inicialitzar()
    yield


app = FastAPI(title="API de tasques", lifespan=cicle_de_vida)


@app.exception_handler(dades.ErrorDades)
async def error_dades(_req: Request, exc: dades.ErrorDades):
    estat = 404 if isinstance(exc, dades.NoTrobat) else 400
    return JSONResponse(status_code=estat, content={"detail": str(exc)})


class TascaNova(BaseModel):
    titol: str = Field(min_length=1, max_length=100)
    data_limit: str | None = Field(None, examples=["2026-12-01"])
    categoria: str = "personal"


class CanvisTasca(BaseModel):
    titol: str | None = None
    data_limit: str | None = None
    feta: bool | None = None
    categoria: str | None = None
    treure_data: bool = False


class Tasca(BaseModel):
    id: int
    titol: str
    data_limit: str | None
    feta: bool
    categoria: str


@app.get("/tasques", response_model=list[Tasca])
def llistar(nomes_pendents: bool = False, categoria: str | None = None, q: str | None = None):
    if q:
        return dades.cercar(q)
    return dades.llistar(nomes_pendents, categoria)


@app.get("/tasques/{id}", response_model=Tasca)
def obtenir(id: int):
    return dades.obtenir(id)


@app.post("/tasques", response_model=Tasca, status_code=201)
def crear(t: TascaNova):
    return dades.crear(t.titol, t.data_limit, t.categoria)


@app.patch("/tasques/{id}", response_model=Tasca)
def modificar(id: int, c: CanvisTasca):
    return dades.modificar(id, c.titol, c.data_limit, c.feta, c.categoria, c.treure_data)


@app.delete("/tasques/{id}", status_code=204)
def eliminar(id: int):
    dades.eliminar(id)


@app.get("/categories", response_model=list[str])
def categories():
    return dades.categories()


@app.get("/estadistiques")
def estadistiques():
    return dades.estadistiques()


@app.get("/salut")
def salut():
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
