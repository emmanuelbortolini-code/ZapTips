from decimal import Decimal

from starlette.testclient import TestClient

from app.console.deps import get_cursor
from app.console.main import create_app
from tests._fakes import FakeCursor

app = create_app()
client = TestClient(app, follow_redirects=False)


def _limpar_overrides():
    app.dependency_overrides.clear()


def test_relatorios_responde_200_sem_dado():
    _limpar_overrides()
    app.dependency_overrides[get_cursor] = lambda: FakeCursor(fetchall_results=[[], [], []])

    resposta = client.get("/relatorios")

    assert resposta.status_code == 200
    assert "Nenhum dado no período." in resposta.text
    _limpar_overrides()


def test_relatorios_mostra_fonte_com_metricas_e_status_quarentena():
    _limpar_overrides()
    picks = [("p1", "Fonte X", "Tipster A", "1x2", "green", Decimal("1.8"), None, None)]
    app.dependency_overrides[get_cursor] = lambda: FakeCursor(
        fetchall_results=[picks, [], [("Fonte X", True)]]
    )

    resposta = client.get("/relatorios")

    assert resposta.status_code == 200
    assert "Fonte X" in resposta.text
    assert "quarentena" in resposta.text
    _limpar_overrides()
