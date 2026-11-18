"""Tests de la capa de dades, de les eines MCP i de l'API REST."""
import json

import pytest
from fastapi.testclient import TestClient
from mcp.server.mcpserver.exceptions import ToolError

from servidor import api_rest, dades
from servidor import servidor_tasques as srv


@pytest.fixture(autouse=True)
def bd_temporal(tmp_path, monkeypatch):
    monkeypatch.setenv("TASQUES_DB", str(tmp_path / "test.db"))
    dades.inicialitzar()


def text_resultat(resultat) -> str:
    return "\n".join(c.text for c in resultat.content)


async def cridar(nom: str, **args) -> str:
    return text_resultat(await srv.mcp.call_tool(nom, args))


# --- Capa de dades ----------------------------------------------------------

def test_crear_i_llistar():
    dades.crear("Estudiar MCP", "2026-12-01", "classe")
    dades.crear("Revisar ruscs", None, "personal")
    tasques = dades.llistar()
    assert [t["titol"] for t in tasques] == ["Estudiar MCP", "Revisar ruscs"]
    assert dades.llistar(categoria="classe")[0]["categoria"] == "classe"


@pytest.mark.parametrize("titol", ["", "   ", "x" * 101])
def test_titol_invalid(titol):
    with pytest.raises(dades.ErrorDades, match="títol"):
        dades.crear(titol)


def test_data_invalida():
    with pytest.raises(dades.ErrorDades, match="AAAA-MM-DD"):
        dades.crear("Tasca", "01/12/2026")


def test_categoria_inexistent_llista_les_valides():
    with pytest.raises(dades.ErrorDades, match="Categories: classe, personal"):
        dades.crear("Tasca", categoria="feina")


def test_modificar_i_eliminar_inexistent():
    with pytest.raises(dades.NoTrobat):
        dades.modificar(999, feta=True)
    with pytest.raises(dades.NoTrobat):
        dades.eliminar(999)


def test_modificar_sense_canvis():
    t = dades.crear("Tasca")
    with pytest.raises(dades.ErrorDades, match="cap canvi"):
        dades.modificar(t["id"])


def test_treure_data():
    t = dades.crear("Tasca", "2026-12-01")
    assert dades.modificar(t["id"], treure_data=True)["data_limit"] is None


def test_injeccio_sql_no_te_efecte():
    dades.crear("normal")
    assert dades.cercar("' OR 1=1; DROP TABLE tasques; --") == []
    assert len(dades.llistar()) == 1


def test_estadistiques():
    a = dades.crear("A", "2000-01-01", "classe")  # vençuda
    dades.crear("B", None, "personal")
    dades.modificar(dades.crear("C")["id"], feta=True)
    e = dades.estadistiques()
    assert (e["total"], e["fetes"], e["pendents"], e["vencudes"]) == (3, 1, 2, 1)
    assert e["per_categoria"]["classe"] == {"total": 1, "pendents": 1}
    assert a["id"] == 1


# --- Servidor MCP -----------------------------------------------------------

async def test_eines_publicades():
    noms = {t.name for t in await srv.mcp.list_tools()}
    assert {"llistar_tasques", "cercar_tasques", "crear_tasca",
            "modificar_tasca", "eliminar_tasca", "estadistiques_tasques"} <= noms


async def test_esquema_te_descripcions():
    eina = next(t for t in await srv.mcp.list_tools() if t.name == "crear_tasca")
    assert "Crea una tasca nova" in eina.description
    assert eina.input_schema["required"] == ["titol"]


async def test_flux_complet_mcp():
    assert "id 1" in await cridar("crear_tasca", titol="Fer la memòria", data_limit="2026-12-05",
                                  categoria="classe")
    assert "Fer la memòria" in await cridar("llistar_tasques")
    assert "✔" in await cridar("modificar_tasca", id=1, feta=True)
    assert "No s'ha trobat" in await cridar("llistar_tasques", nomes_pendents=True)
    assert "eliminada" in await cridar("eliminar_tasca", id=1)


async def test_error_arriba_al_model_amb_missatge():
    # A l'SDK 2.x, sense ToolError el model només veuria «Error executing tool».
    with pytest.raises(ToolError, match="No existeix cap tasca amb id 42"):
        await srv.mcp.call_tool("eliminar_tasca", {"id": 42})


async def test_estadistiques_mcp_es_json():
    await cridar("crear_tasca", titol="X")
    assert json.loads(await cridar("estadistiques_tasques"))["total"] == 1


# --- API REST i dades compartides ---------------------------------------------

@pytest.fixture
def client():
    with TestClient(api_rest.app) as c:
        yield c


def test_api_crud(client):
    r = client.post("/tasques", json={"titol": "Des de l'app", "categoria": "classe"})
    assert r.status_code == 201
    id = r.json()["id"]
    assert client.patch(f"/tasques/{id}", json={"feta": True}).json()["feta"] is True
    assert client.delete(f"/tasques/{id}").status_code == 204
    assert client.get(f"/tasques/{id}").status_code == 404


def test_api_errors(client):
    assert client.post("/tasques", json={"titol": "x", "data_limit": "demà"}).status_code == 400
    assert client.patch("/tasques/99", json={"feta": True}).status_code == 404


async def test_el_que_fa_la_ia_ho_veu_lapp(client):
    await cridar("crear_tasca", titol="Creada per la IA")
    assert client.get("/tasques").json()[0]["titol"] == "Creada per la IA"

    client.post("/tasques", json={"titol": "Creada per l'app"})
    assert "Creada per l'app" in await cridar("llistar_tasques")
