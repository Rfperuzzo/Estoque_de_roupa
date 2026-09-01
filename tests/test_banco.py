import sqlite3
from pathlib import Path

import pytest

from banco import (
    BackupInvalidoError,
    BancoDeDados,
    DadosInvalidosError,
    EstoqueInsuficienteError,
    MigracaoError,
    PREFIXO_HASH,
    VERSAO_SCHEMA,
)


def criar_base_legada(caminho: Path, preco=19.99, com_tipo=True) -> None:
    conn = sqlite3.connect(caminho)
    try:
        conn.execute(
            """
            CREATE TABLE estoque (
                id INTEGER PRIMARY KEY AUTOINCREMENT, sku TEXT, nome TEXT NOT NULL,
                categoria TEXT, tamanho TEXT, cor TEXT,
                quantidade INTEGER NOT NULL, preco REAL NOT NULL
            )
            """
        )
        tipo = ", tipo TEXT DEFAULT 'Saída'" if com_tipo else ""
        conn.execute(
            f"""
            CREATE TABLE historico (
                id INTEGER PRIMARY KEY AUTOINCREMENT, produto_nome TEXT,
                cliente TEXT, quantidade INTEGER, data_hora TEXT{tipo}
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT, usuario TEXT UNIQUE, senha TEXT,
                perfil TEXT, p_ver_financeiro INTEGER, p_cadastrar_produto INTEGER,
                p_fazer_entrada INTEGER, p_ver_historico INTEGER
            )
            """
        )
        conn.execute(
            """
            INSERT INTO estoque
                (id, sku, nome, categoria, tamanho, cor, quantidade, preco)
            VALUES (7, 'SKU-7', 'Camiseta', 'Camiseta', 'M', 'Azul', 5, ?)
            """,
            (preco,),
        )
        if com_tipo:
            conn.execute(
                """
                INSERT INTO historico
                    (id, produto_nome, cliente, quantidade, data_hora, tipo)
                VALUES (9, 'Camiseta', 'Cliente', 1, '01/01/2026 10:00', 'Saída')
                """
            )
        else:
            conn.execute(
                """
                INSERT INTO historico
                    (id, produto_nome, cliente, quantidade, data_hora)
                VALUES (9, 'Camiseta', 'Cliente', 1, '01/01/2026 10:00')
                """
            )
        conn.execute(
            """
            INSERT INTO usuarios (
                id, usuario, senha, perfil, p_ver_financeiro,
                p_cadastrar_produto, p_fazer_entrada, p_ver_historico
            ) VALUES (3, 'dono', 'segredo', 'proprietario', 1, 1, 1, 1)
            """
        )
        conn.execute(
            """
            INSERT INTO usuarios (
                id, usuario, senha, perfil, p_ver_financeiro,
                p_cadastrar_produto, p_fazer_entrada, p_ver_historico
            ) VALUES (4, 'caixa', '123', 'funcionario', 0, 0, 0, 1)
            """
        )
        conn.commit()
    finally:
        conn.close()


def ler_senha(caminho: Path, usuario: str) -> str:
    conn = sqlite3.connect(caminho)
    try:
        return conn.execute(
            "SELECT senha FROM usuarios WHERE usuario=?", (usuario,)
        ).fetchone()[0]
    finally:
        conn.close()


def test_base_nova_protege_senhas_e_mantem_retorno_do_login(tmp_path):
    caminho = tmp_path / "nova.db"
    banco = BancoDeDados(caminho)

    assert banco.fazer_login("dono", "senha-errada") is None
    assert banco.fazer_login("dono", "123") == ("proprietario", 1, 1, 1, 1)
    assert ler_senha(caminho, "dono").startswith(f"{PREFIXO_HASH}$")

    conn = sqlite3.connect(caminho)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == VERSAO_SCHEMA
    finally:
        conn.close()


def test_crud_armazena_centavos_e_valida_dados(tmp_path):
    caminho = tmp_path / "crud.db"
    banco = BancoDeDados(caminho)

    banco.adicionar_produto("SKU", "Calça", "Calça", "G", "Preta", 3, "19.99")
    produto = banco.buscar_produtos("SKU")[0]
    assert produto[1:] == ("SKU", "Calça", "Calça", "G", "Preta", 3, 19.99)

    conn = sqlite3.connect(caminho)
    try:
        assert conn.execute("SELECT preco_centavos FROM estoque").fetchone()[0] == 1999
    finally:
        conn.close()

    banco.atualizar_produto(produto[0], "SKU", "Calça", "Calça", "G", "Preta", 4, 0.105)
    assert banco.buscar_produtos()[0][7] == 0.11

    with pytest.raises(DadosInvalidosError):
        banco.adicionar_produto("", "", "", "", "", 1, 10)
    with pytest.raises(DadosInvalidosError):
        banco.adicionar_produto("", "Produto", "", "", "", -1, 10)
    with pytest.raises(DadosInvalidosError):
        banco.adicionar_produto("", "Produto", "", "", "", 1, -0.01)


def test_movimentacao_e_historico_sao_atomicos(tmp_path):
    banco = BancoDeDados(tmp_path / "movimento.db")
    banco.adicionar_produto("SKU", "Casaco", "Casaco", "M", "Cinza", 5, 100)
    id_prod = banco.buscar_produtos()[0][0]

    assert banco.movimentar_estoque(id_prod, "Saída", "Cliente", 3) == 2
    assert banco.buscar_produto_por_id(id_prod) == ("Casaco", 2)
    assert len(banco.buscar_historico()) == 1

    with pytest.raises(EstoqueInsuficienteError):
        banco.movimentar_estoque(id_prod, "Saída", "Cliente", 3)
    assert banco.buscar_produto_por_id(id_prod) == ("Casaco", 2)
    assert len(banco.buscar_historico()) == 1

    # A assinatura antiga continua funcionando, sem confiar no saldo calculado pela UI.
    assert banco.registrar_movimentacao(
        id_prod, "Entrada", "Fornecedor", 2, 999, "Nome incorreto"
    ) == 4
    assert banco.buscar_produto_por_id(id_prod) == ("Casaco", 4)
    assert len(banco.buscar_historico()) == 2


@pytest.mark.parametrize("com_tipo", [True, False])
def test_migracao_preserva_dados_ids_e_credenciais_legadas(tmp_path, com_tipo):
    caminho = tmp_path / "legada.db"
    criar_base_legada(caminho, com_tipo=com_tipo)

    banco = BancoDeDados(caminho)

    assert banco.ultimo_backup_migracao is not None
    assert Path(banco.ultimo_backup_migracao).is_file()
    assert banco.buscar_produtos()[0] == (
        7,
        "SKU-7",
        "Camiseta",
        "Camiseta",
        "M",
        "Azul",
        5,
        19.99,
    )
    assert banco.buscar_historico()[0][:5] == (9, "Saída", "Camiseta", "Cliente", 1)
    assert ler_senha(caminho, "dono") == "segredo"

    assert banco.fazer_login("dono", "segredo") == ("proprietario", 1, 1, 1, 1)
    assert ler_senha(caminho, "dono").startswith(f"{PREFIXO_HASH}$")

    conn = sqlite3.connect(caminho)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == VERSAO_SCHEMA
        assert conn.execute("SELECT preco_centavos FROM estoque WHERE id=7").fetchone()[0] == 1999
    finally:
        conn.close()


def test_migracao_invalida_nao_altera_base_original(tmp_path):
    caminho = tmp_path / "invalida.db"
    criar_base_legada(caminho, preco=1.999)

    with pytest.raises(MigracaoError, match="mais de duas casas"):
        BancoDeDados(caminho)

    conn = sqlite3.connect(caminho)
    try:
        colunas = {
            linha[1] for linha in conn.execute("PRAGMA table_info(estoque)").fetchall()
        }
        assert "preco" in colunas
        assert "preco_centavos" not in colunas
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
        assert conn.execute("SELECT preco FROM estoque WHERE id=7").fetchone()[0] == 1.999
    finally:
        conn.close()


def test_backup_e_restauracao_sao_validados(tmp_path):
    caminho = tmp_path / "ativa.db"
    backup = tmp_path / "backup.db"
    banco = BancoDeDados(caminho)
    banco.adicionar_produto("A", "Produto A", "", "", "", 1, 10)
    assert banco.criar_backup(backup) == str(backup)
    assert banco.validar_backup(backup) is True

    banco.adicionar_produto("B", "Produto B", "", "", "", 2, 20)
    seguranca = Path(banco.restaurar_backup(backup))
    assert seguranca.is_file()
    assert [produto[1] for produto in banco.buscar_produtos()] == ["A"]

    arquivo_invalido = tmp_path / "texto.db"
    arquivo_invalido.write_text("não é sqlite", encoding="utf-8")
    with pytest.raises(BackupInvalidoError):
        banco.validar_backup(arquivo_invalido)


def test_conexoes_internas_nao_mantem_o_arquivo_bloqueado(tmp_path):
    caminho = tmp_path / "bloqueio.db"
    movido = tmp_path / "movido.db"
    banco = BancoDeDados(caminho)
    banco.buscar_produtos()
    banco.buscar_historico()
    banco.buscar_permissoes_caixa()

    caminho.rename(movido)
    movido.rename(caminho)
    assert caminho.is_file()


def test_resumos_dashboard_relatorio_e_detalhes(tmp_path):
    banco = BancoDeDados(tmp_path / "indicadores.db")
    banco.adicionar_produto("A", "Produto A", "Categoria A", "M", "Azul", 2, 10)
    banco.adicionar_produto("B", "Produto B", "Categoria B", "G", "Preto", 8, 20)
    produtos = banco.buscar_produtos()
    banco.movimentar_estoque(produtos[0][0], "Entrada", "Fornecedor", 3)
    banco.movimentar_estoque(produtos[1][0], "Saída", "Cliente", 2)

    assert banco.obter_resumo_estoque() == {
        "produtos": 2,
        "unidades": 11,
        "estoque_baixo": 1,
        "valor_total": 170.0,
    }
    assert [produto[2] for produto in banco.buscar_estoque_baixo()] == ["Produto A"]
    assert banco.obter_resumo_movimentacoes() == {
        "entradas": 3,
        "saidas": 2,
        "produtos_movimentados": 2,
        "movimentacoes": 2,
    }
    assert len(banco.buscar_historico_produto("Produto A")) == 1


def test_gestao_de_usuarios_nao_expoe_hash_e_respeita_permissoes(tmp_path):
    caminho = tmp_path / "usuarios.db"
    banco = BancoDeDados(caminho)
    banco.adicionar_usuario("operador", "senha-segura", p_fin=1, p_cad=1, p_ent=0, p_his=1)

    operador = next(usuario for usuario in banco.listar_usuarios() if usuario[1] == "operador")
    assert operador[2:] == ("funcionario", 1, 1, 0, 1)
    assert "senha-segura" not in repr(banco.listar_usuarios())
    assert banco.fazer_login("operador", "senha-segura") == ("funcionario", 1, 1, 0, 1)

    banco.atualizar_permissoes_usuario("operador", 0, 0, 1, 0)
    assert banco.fazer_login("operador", "senha-segura") == ("funcionario", 0, 0, 1, 0)
    with pytest.raises(DadosInvalidosError, match="já existe"):
        banco.adicionar_usuario("operador", "outra-senha")
