"""Prova el bucle de l'agent amb el servidor MCP real i un Ollama simulat.

El model fals respon de manera fixa (primer demana una eina, després respon),
de manera que es comprova la fontaneria agent ↔ MCP ↔ Ollama sense cap model.
"""
import json

import httpx

from agent import agent_ollama


def ollama_fals(guio):
    """Retorna un transport que respon /api/chat seguint un guió i desa les peticions."""
    peticions = []

    def gestor(request: httpx.Request) -> httpx.Response:
        cos = json.loads(request.content)
        peticions.append(cos)
        return httpx.Response(200, json={"message": guio[len(peticions) - 1](cos)})

    return httpx.MockTransport(gestor), peticions


def crida(nom, **args):
    return lambda _cos: {"role": "assistant", "content": "",
                         "tool_calls": [{"function": {"name": nom, "arguments": args}}]}


def text(t):
    return lambda _cos: {"role": "assistant", "content": t}


async def executar(monkeypatch, tmp_path, guio, peticio, capsys):
    monkeypatch.setenv("TASQUES_DB", str(tmp_path / "agent.db"))
    transport, peticions = ollama_fals(guio)
    http = httpx.AsyncClient(transport=transport, base_url="http://ollama")
    await agent_ollama.main([peticio], http=http)
    return peticions, capsys.readouterr().out


async def test_bucle_amb_eines(monkeypatch, tmp_path, capsys):
    guio = [
        crida("crear_tasca", titol="Revisar ruscs", data_limit="2026-11-20"),
        crida("llistar_tasques"),
        text("Fet! Tens 1 tasca pendent."),
    ]
    peticions, sortida = await executar(monkeypatch, tmp_path, guio,
                                        "Afegeix una tasca i digue'm quantes en tinc", capsys)

    assert sortida.strip() == "Fet! Tens 1 tasca pendent."
    # Les eines MCP arriben a Ollama en el format correcte
    noms = {t["function"]["name"] for t in peticions[0]["tools"]}
    assert "crear_tasca" in noms and peticions[0]["tools"][0]["type"] == "function"
    # El resultat de cada eina torna al model com a missatge 'tool'
    ultim = peticions[2]["messages"][-1]
    assert ultim["role"] == "tool" and "Revisar ruscs" in ultim["content"]


async def test_error_de_leina_arriba_al_model(monkeypatch, tmp_path, capsys):
    guio = [crida("eliminar_tasca", id=99), text("No existeix aquesta tasca.")]
    peticions, _ = await executar(monkeypatch, tmp_path, guio, "Elimina la tasca 99", capsys)
    missatge = peticions[1]["messages"][-1]
    assert missatge["content"].startswith("ERROR")
    assert "No existeix cap tasca amb id 99" in missatge["content"]


async def test_limit_iteracions(monkeypatch, tmp_path, capsys):
    guio = [crida("llistar_tasques")] * agent_ollama.MAX_ITERACIONS
    _, sortida = await executar(monkeypatch, tmp_path, guio, "Bucle", capsys)
    assert "límit" in sortida
