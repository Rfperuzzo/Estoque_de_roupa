"""Persistência, segurança e regras de integridade do estoque."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import shutil
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Iterator


VERSAO_SCHEMA = 2
ITERACOES_PBKDF2 = 600_000
PREFIXO_HASH = "pbkdf2_sha256"
TIPOS_MOVIMENTACAO = ("Entrada", "Saída")


class ErroBanco(Exception):
    """Erro conhecido da camada de persistência."""


class DadosInvalidosError(ErroBanco, ValueError):
    """Dados de domínio inválidos."""


class EstoqueInsuficienteError(ErroBanco):
    """A saída solicitada é maior que o saldo disponível."""


class BackupInvalidoError(ErroBanco):
    """O arquivo informado não é um backup válido da aplicação."""


class MigracaoError(ErroBanco):
    """A base antiga não pôde ser migrada com segurança."""


class BancoDeDados:
    """Gerencia o SQLite e mantém compatibilidade com a interface atual."""

    def __init__(self, db_name="estoque.db"):
        self.db_name = str(db_name)
        self.ultimo_backup_migracao: str | None = None
        self._inicializar_banco()

    def conectar(self) -> sqlite3.Connection:
        """Abre uma conexão configurada; quem chamar diretamente deve fechá-la."""
        conn = sqlite3.connect(self.db_name, timeout=5)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    @contextmanager
    def _conexao(self) -> Iterator[sqlite3.Connection]:
        """Entrega uma transação e sempre fecha o arquivo, inclusive em falhas."""
        conn = self.conectar()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _inicializar_banco(self) -> None:
        try:
            with self._conexao() as conn:
                versao = conn.execute("PRAGMA user_version").fetchone()[0]
                tabelas = self._listar_tabelas(conn)
        except sqlite3.DatabaseError as exc:
            raise MigracaoError("O arquivo informado não é um banco SQLite válido.") from exc

        tabelas_aplicacao = {"estoque", "historico", "usuarios"}
        if not tabelas.intersection(tabelas_aplicacao):
            with self._conexao() as conn:
                self._criar_schema_atual(conn)
                self._inserir_usuarios_padrao(conn)
                conn.execute(f"PRAGMA user_version = {VERSAO_SCHEMA}")
            return

        if not tabelas_aplicacao.issubset(tabelas):
            ausentes = ", ".join(sorted(tabelas_aplicacao - tabelas))
            raise MigracaoError(f"Base incompleta; tabelas ausentes: {ausentes}.")

        if versao > VERSAO_SCHEMA:
            raise MigracaoError(
                f"A base usa o schema {versao}, mais recente que o suportado ({VERSAO_SCHEMA})."
            )

        if versao < VERSAO_SCHEMA:
            self._migrar_base_legada(versao)

    @staticmethod
    def _listar_tabelas(conn: sqlite3.Connection) -> set[str]:
        linhas = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        return {linha[0] for linha in linhas}

    @staticmethod
    def _criar_schema_atual(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS estoque (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sku TEXT NOT NULL DEFAULT '',
                nome TEXT NOT NULL CHECK (length(trim(nome)) > 0),
                categoria TEXT NOT NULL DEFAULT '',
                tamanho TEXT NOT NULL DEFAULT '',
                cor TEXT NOT NULL DEFAULT '',
                quantidade INTEGER NOT NULL CHECK (quantidade >= 0),
                preco_centavos INTEGER NOT NULL CHECK (preco_centavos >= 0)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS historico (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                produto_nome TEXT NOT NULL,
                cliente TEXT NOT NULL,
                quantidade INTEGER NOT NULL CHECK (quantidade > 0),
                data_hora TEXT NOT NULL,
                tipo TEXT NOT NULL CHECK (tipo IN ('Entrada', 'Saída'))
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario TEXT NOT NULL UNIQUE,
                senha TEXT NOT NULL,
                perfil TEXT NOT NULL,
                p_ver_financeiro INTEGER NOT NULL CHECK (p_ver_financeiro IN (0, 1)),
                p_cadastrar_produto INTEGER NOT NULL CHECK (p_cadastrar_produto IN (0, 1)),
                p_fazer_entrada INTEGER NOT NULL CHECK (p_fazer_entrada IN (0, 1)),
                p_ver_historico INTEGER NOT NULL CHECK (p_ver_historico IN (0, 1))
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_estoque_nome ON estoque(nome)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_estoque_sku ON estoque(sku)")

    def _inserir_usuarios_padrao(self, conn: sqlite3.Connection) -> None:
        usuarios = (
            ("dono", "123", "proprietario", 1, 1, 1, 1),
            ("caixa", "123", "funcionario", 0, 0, 0, 1),
        )
        for usuario, senha, perfil, p_fin, p_cad, p_ent, p_hist in usuarios:
            conn.execute(
                """
                INSERT INTO usuarios (
                    usuario, senha, perfil, p_ver_financeiro,
                    p_cadastrar_produto, p_fazer_entrada, p_ver_historico
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    usuario,
                    self._gerar_hash_senha(senha),
                    perfil,
                    p_fin,
                    p_cad,
                    p_ent,
                    p_hist,
                ),
            )

    def _migrar_base_legada(self, versao: int) -> None:
        if versao != 0:
            raise MigracaoError(f"Não existe migração disponível para o schema {versao}.")

        with self._conexao() as conn:
            dados = self._ler_e_validar_dados_legados(conn)

        self.ultimo_backup_migracao = self._caminho_backup_migracao()
        self.criar_backup(self.ultimo_backup_migracao)

        try:
            with self._conexao() as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("ALTER TABLE estoque RENAME TO estoque_legado")
                conn.execute("ALTER TABLE historico RENAME TO historico_legado")
                conn.execute("ALTER TABLE usuarios RENAME TO usuarios_legado")
                self._criar_schema_atual(conn)

                conn.executemany(
                    """
                    INSERT INTO estoque (
                        id, sku, nome, categoria, tamanho, cor,
                        quantidade, preco_centavos
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    dados["estoque"],
                )
                conn.executemany(
                    """
                    INSERT INTO historico (
                        id, produto_nome, cliente, quantidade, data_hora, tipo
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    dados["historico"],
                )
                conn.executemany(
                    """
                    INSERT INTO usuarios (
                        id, usuario, senha, perfil, p_ver_financeiro,
                        p_cadastrar_produto, p_fazer_entrada, p_ver_historico
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    dados["usuarios"],
                )

                conn.execute("DROP TABLE estoque_legado")
                conn.execute("DROP TABLE historico_legado")
                conn.execute("DROP TABLE usuarios_legado")
                conn.execute(f"PRAGMA user_version = {VERSAO_SCHEMA}")
        except (sqlite3.DatabaseError, DadosInvalidosError) as exc:
            raise MigracaoError(
                "A migração falhou. A base original foi mantida e o backup está em "
                f"{self.ultimo_backup_migracao}."
            ) from exc

    def _ler_e_validar_dados_legados(self, conn: sqlite3.Connection) -> dict[str, list[tuple]]:
        colunas_historico = {
            linha[1] for linha in conn.execute("PRAGMA table_info(historico)").fetchall()
        }
        possui_tipo = "tipo" in colunas_historico

        estoque_convertido = []
        erros = []
        for linha in conn.execute(
            "SELECT id, sku, nome, categoria, tamanho, cor, quantidade, preco FROM estoque"
        ).fetchall():
            id_prod, sku, nome, categoria, tamanho, cor, quantidade, preco = linha
            try:
                nome = self._texto_obrigatorio(nome, "nome")
                quantidade = self._quantidade_nao_negativa(quantidade)
                centavos = self._preco_para_centavos(preco, exigir_centavos_exatos=True)
            except DadosInvalidosError as exc:
                erros.append(f"produto {id_prod}: {exc}")
                continue
            estoque_convertido.append(
                (
                    id_prod,
                    self._texto_opcional(sku),
                    nome,
                    self._texto_opcional(categoria),
                    self._texto_opcional(tamanho),
                    self._texto_opcional(cor),
                    quantidade,
                    centavos,
                )
            )

        tipo_sql = "tipo" if possui_tipo else "'Saída' AS tipo"
        historico_convertido = []
        for linha in conn.execute(
            "SELECT id, produto_nome, cliente, quantidade, data_hora, "
            f"{tipo_sql} FROM historico"
        ).fetchall():
            id_hist, produto, cliente, quantidade, data_hora, tipo = linha
            try:
                produto = self._texto_obrigatorio(produto, "produto_nome")
                cliente = self._texto_obrigatorio(cliente, "cliente")
                quantidade = self._quantidade_positiva(quantidade)
                data_hora = self._texto_obrigatorio(data_hora, "data_hora")
                tipo = self._tipo_movimentacao(tipo)
            except DadosInvalidosError as exc:
                erros.append(f"histórico {id_hist}: {exc}")
                continue
            historico_convertido.append(
                (id_hist, produto, cliente, quantidade, data_hora, tipo)
            )

        usuarios_convertidos = []
        for linha in conn.execute(
            """
            SELECT id, usuario, senha, perfil, p_ver_financeiro,
                   p_cadastrar_produto, p_fazer_entrada, p_ver_historico
            FROM usuarios
            """
        ).fetchall():
            id_usuario, usuario, senha, perfil, *permissoes = linha
            try:
                usuario = self._texto_obrigatorio(usuario, "usuario")
                senha = self._texto_obrigatorio(senha, "senha")
                perfil = self._texto_obrigatorio(perfil, "perfil")
                permissoes = [self._permissao(valor) for valor in permissoes]
            except DadosInvalidosError as exc:
                erros.append(f"usuário {id_usuario}: {exc}")
                continue
            usuarios_convertidos.append(
                (id_usuario, usuario, senha, perfil, *permissoes)
            )

        if erros:
            detalhes = "; ".join(erros[:10])
            if len(erros) > 10:
                detalhes += f"; e mais {len(erros) - 10} erro(s)"
            raise MigracaoError(
                "A base contém dados que não podem ser migrados sem alteração: " + detalhes
            )

        return {
            "estoque": estoque_convertido,
            "historico": historico_convertido,
            "usuarios": usuarios_convertidos,
        }

    def _caminho_backup_migracao(self) -> str:
        caminho = Path(self.db_name)
        momento = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        return str(caminho.with_name(f"{caminho.stem}.pre_migracao_{momento}.db"))

    @staticmethod
    def _texto_opcional(valor) -> str:
        return "" if valor is None else str(valor).strip()

    @staticmethod
    def _texto_obrigatorio(valor, campo: str) -> str:
        texto = "" if valor is None else str(valor).strip()
        if not texto:
            raise DadosInvalidosError(f"{campo} é obrigatório")
        return texto

    @staticmethod
    def _inteiro(valor, campo: str) -> int:
        if isinstance(valor, bool):
            raise DadosInvalidosError(f"{campo} deve ser inteiro")
        try:
            inteiro = int(valor)
        except (TypeError, ValueError) as exc:
            raise DadosInvalidosError(f"{campo} deve ser inteiro") from exc
        if isinstance(valor, float) and not valor.is_integer():
            raise DadosInvalidosError(f"{campo} deve ser inteiro")
        return inteiro

    @classmethod
    def _quantidade_nao_negativa(cls, valor) -> int:
        quantidade = cls._inteiro(valor, "quantidade")
        if quantidade < 0:
            raise DadosInvalidosError("quantidade não pode ser negativa")
        return quantidade

    @classmethod
    def _quantidade_positiva(cls, valor) -> int:
        quantidade = cls._inteiro(valor, "quantidade")
        if quantidade <= 0:
            raise DadosInvalidosError("quantidade deve ser positiva")
        return quantidade

    @staticmethod
    def _permissao(valor) -> int:
        if valor not in (0, 1, False, True):
            raise DadosInvalidosError("permissão deve ser 0 ou 1")
        return int(valor)

    @staticmethod
    def _tipo_movimentacao(tipo) -> str:
        if tipo not in TIPOS_MOVIMENTACAO:
            raise DadosInvalidosError("tipo deve ser Entrada ou Saída")
        return str(tipo)

    @staticmethod
    def _preco_para_centavos(valor, exigir_centavos_exatos: bool = False) -> int:
        try:
            decimal = Decimal(str(valor))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise DadosInvalidosError("preço inválido") from exc
        if not decimal.is_finite() or decimal < 0:
            raise DadosInvalidosError("preço deve ser um número não negativo")
        arredondado = decimal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if exigir_centavos_exatos and decimal != arredondado:
            raise DadosInvalidosError("preço possui mais de duas casas decimais")
        return int(arredondado * 100)

    @staticmethod
    def _gerar_hash_senha(senha: str) -> str:
        salt = os.urandom(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256", senha.encode("utf-8"), salt, ITERACOES_PBKDF2
        )
        salt_b64 = base64.b64encode(salt).decode("ascii")
        digest_b64 = base64.b64encode(digest).decode("ascii")
        return f"{PREFIXO_HASH}${ITERACOES_PBKDF2}${salt_b64}${digest_b64}"

    @staticmethod
    def _senha_esta_protegida(valor: str) -> bool:
        return valor.startswith(f"{PREFIXO_HASH}$")

    @staticmethod
    def _verificar_hash_senha(senha: str, valor_armazenado: str) -> bool:
        try:
            prefixo, iteracoes, salt_b64, digest_b64 = valor_armazenado.split("$", 3)
            if prefixo != PREFIXO_HASH:
                return False
            salt = base64.b64decode(salt_b64, validate=True)
            esperado = base64.b64decode(digest_b64, validate=True)
            calculado = hashlib.pbkdf2_hmac(
                "sha256", senha.encode("utf-8"), salt, int(iteracoes)
            )
        except (ValueError, TypeError):
            return False
        return hmac.compare_digest(calculado, esperado)

    def fazer_login(self, usuario, senha):
        """Retorna perfil e permissões, migrando senhas legadas após login válido."""
        with self._conexao() as conn:
            linha = conn.execute(
                """
                SELECT senha, perfil, p_ver_financeiro, p_cadastrar_produto,
                       p_fazer_entrada, p_ver_historico
                FROM usuarios WHERE usuario=?
                """,
                (usuario,),
            ).fetchone()
            if not linha:
                return None

            senha_armazenada = linha[0]
            if self._senha_esta_protegida(senha_armazenada):
                senha_valida = self._verificar_hash_senha(senha, senha_armazenada)
            else:
                senha_valida = hmac.compare_digest(str(senha_armazenada), str(senha))

            if not senha_valida:
                return None
            if not self._senha_esta_protegida(senha_armazenada):
                conn.execute(
                    "UPDATE usuarios SET senha=? WHERE usuario=?",
                    (self._gerar_hash_senha(str(senha)), usuario),
                )
            return linha[1:]

    def buscar_produtos(self, termo=""):
        """Retorna produtos no formato legado, com o preço novamente em reais."""
        termo = self._texto_opcional(termo)
        with self._conexao() as conn:
            sql = (
                "SELECT id, sku, nome, categoria, tamanho, cor, quantidade, "
                "preco_centavos FROM estoque"
            )
            parametros = ()
            if termo:
                sql += " WHERE nome LIKE ? OR sku LIKE ?"
                busca = f"%{termo}%"
                parametros = (busca, busca)
            sql += " ORDER BY nome COLLATE NOCASE, id"
            linhas = conn.execute(sql, parametros).fetchall()
        return [(*linha[:7], linha[7] / 100.0) for linha in linhas]

    def adicionar_produto(self, sku, nome, categoria, tamanho, cor, qtd, preco):
        nome = self._texto_obrigatorio(nome, "nome")
        quantidade = self._quantidade_nao_negativa(qtd)
        centavos = self._preco_para_centavos(preco)
        with self._conexao() as conn:
            conn.execute(
                """
                INSERT INTO estoque (
                    sku, nome, categoria, tamanho, cor, quantidade, preco_centavos
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self._texto_opcional(sku),
                    nome,
                    self._texto_opcional(categoria),
                    self._texto_opcional(tamanho),
                    self._texto_opcional(cor),
                    quantidade,
                    centavos,
                ),
            )

    def atualizar_produto(self, id_prod, sku, nome, categoria, tamanho, cor, qtd, preco):
        nome = self._texto_obrigatorio(nome, "nome")
        quantidade = self._quantidade_nao_negativa(qtd)
        centavos = self._preco_para_centavos(preco)
        with self._conexao() as conn:
            cursor = conn.execute(
                """
                UPDATE estoque
                SET sku=?, nome=?, categoria=?, tamanho=?, cor=?,
                    quantidade=?, preco_centavos=?
                WHERE id=?
                """,
                (
                    self._texto_opcional(sku),
                    nome,
                    self._texto_opcional(categoria),
                    self._texto_opcional(tamanho),
                    self._texto_opcional(cor),
                    quantidade,
                    centavos,
                    id_prod,
                ),
            )
            if cursor.rowcount != 1:
                raise DadosInvalidosError("produto não encontrado")

    def excluir_produto(self, id_prod):
        with self._conexao() as conn:
            conn.execute("DELETE FROM estoque WHERE id=?", (id_prod,))
            if conn.execute("SELECT COUNT(*) FROM estoque").fetchone()[0] == 0:
                conn.execute("DELETE FROM sqlite_sequence WHERE name='estoque'")

    def buscar_produto_por_id(self, id_prod):
        with self._conexao() as conn:
            return conn.execute(
                "SELECT nome, quantidade FROM estoque WHERE id=?", (id_prod,)
            ).fetchone()

    def movimentar_estoque(self, id_prod, tipo_mov, envolvido, qtd_mov):
        """Altera saldo e histórico atomicamente e retorna o novo saldo."""
        tipo = self._tipo_movimentacao(tipo_mov)
        envolvido = self._texto_obrigatorio(envolvido, "envolvido")
        quantidade = self._quantidade_positiva(qtd_mov)

        with self._conexao() as conn:
            conn.execute("BEGIN IMMEDIATE")
            produto = conn.execute(
                "SELECT nome, quantidade FROM estoque WHERE id=?", (id_prod,)
            ).fetchone()
            if not produto:
                raise DadosInvalidosError("produto não encontrado")

            nome_produto, estoque_atual = produto
            if tipo == "Saída":
                if estoque_atual < quantidade:
                    raise EstoqueInsuficienteError(
                        f"Saldo atual: {estoque_atual}; saída solicitada: {quantidade}."
                    )
                novo_estoque = estoque_atual - quantidade
            else:
                novo_estoque = estoque_atual + quantidade

            conn.execute(
                "UPDATE estoque SET quantidade=? WHERE id=?",
                (novo_estoque, id_prod),
            )
            conn.execute(
                """
                INSERT INTO historico (
                    tipo, produto_nome, cliente, quantidade, data_hora
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    tipo,
                    nome_produto,
                    envolvido,
                    quantidade,
                    datetime.now().strftime("%d/%m/%Y %H:%M"),
                ),
            )
        return novo_estoque

    def registrar_movimentacao(
        self, id_prod, tipo_mov, envolvido, qtd_mov, novo_estoque, nome_produto
    ):
        """Compatibilidade: saldo e nome recebidos não são confiados pela transação."""
        del novo_estoque, nome_produto
        return self.movimentar_estoque(id_prod, tipo_mov, envolvido, qtd_mov)

    def buscar_historico(self):
        with self._conexao() as conn:
            return conn.execute(
                """
                SELECT id, tipo, produto_nome, cliente, quantidade, data_hora
                FROM historico ORDER BY id DESC
                """
            ).fetchall()

    def buscar_historico_produto(self, nome_produto):
        """Retorna o histórico associado ao nome preservado do produto."""
        nome = self._texto_obrigatorio(nome_produto, "nome_produto")
        with self._conexao() as conn:
            return conn.execute(
                """
                SELECT id, tipo, produto_nome, cliente, quantidade, data_hora
                FROM historico
                WHERE produto_nome=?
                ORDER BY id DESC
                """,
                (nome,),
            ).fetchall()

    def obter_resumo_estoque(self, limite_baixo=5):
        """Entrega os indicadores usados pelo dashboard sem expor detalhes SQL."""
        limite = self._quantidade_nao_negativa(limite_baixo)
        with self._conexao() as conn:
            linha = conn.execute(
                """
                SELECT COUNT(*), COALESCE(SUM(quantidade), 0),
                       COALESCE(SUM(CASE WHEN quantidade <= ? THEN 1 ELSE 0 END), 0),
                       COALESCE(SUM(quantidade * preco_centavos), 0)
                FROM estoque
                """,
                (limite,),
            ).fetchone()
        return {
            "produtos": linha[0],
            "unidades": linha[1],
            "estoque_baixo": linha[2],
            "valor_total": linha[3] / 100.0,
        }

    def buscar_estoque_baixo(self, limite=5):
        """Retorna produtos abaixo do limite no mesmo formato da listagem."""
        limite = self._quantidade_nao_negativa(limite)
        with self._conexao() as conn:
            linhas = conn.execute(
                """
                SELECT id, sku, nome, categoria, tamanho, cor,
                       quantidade, preco_centavos
                FROM estoque
                WHERE quantidade <= ?
                ORDER BY quantidade, nome COLLATE NOCASE
                """,
                (limite,),
            ).fetchall()
        return [(*linha[:7], linha[7] / 100.0) for linha in linhas]

    def obter_resumo_movimentacoes(self):
        """Agrega entradas, saídas e produtos movimentados para relatórios."""
        with self._conexao() as conn:
            linha = conn.execute(
                """
                SELECT
                    COALESCE(SUM(CASE WHEN tipo='Entrada' THEN quantidade ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN tipo='Saída' THEN quantidade ELSE 0 END), 0),
                    COUNT(DISTINCT produto_nome),
                    COUNT(*)
                FROM historico
                """
            ).fetchone()
        return {
            "entradas": linha[0],
            "saidas": linha[1],
            "produtos_movimentados": linha[2],
            "movimentacoes": linha[3],
        }

    def excluir_historico(self, id_hist):
        with self._conexao() as conn:
            conn.execute("DELETE FROM historico WHERE id=?", (id_hist,))

    def buscar_permissoes_caixa(self):
        with self._conexao() as conn:
            return conn.execute(
                """
                SELECT p_ver_financeiro, p_cadastrar_produto,
                       p_fazer_entrada, p_ver_historico
                FROM usuarios WHERE usuario='caixa'
                """
            ).fetchone()

    def listar_usuarios(self):
        """Lista usuários e permissões sem retornar hashes de senha."""
        with self._conexao() as conn:
            return conn.execute(
                """
                SELECT id, usuario, perfil, p_ver_financeiro,
                       p_cadastrar_produto, p_fazer_entrada, p_ver_historico
                FROM usuarios
                ORDER BY CASE WHEN perfil='proprietario' THEN 0 ELSE 1 END,
                         usuario COLLATE NOCASE
                """
            ).fetchall()

    def adicionar_usuario(
        self,
        usuario,
        senha,
        perfil="funcionario",
        p_fin=0,
        p_cad=0,
        p_ent=0,
        p_his=1,
    ):
        """Cria um usuário com senha protegida e permissões explícitas."""
        usuario = self._texto_obrigatorio(usuario, "usuario")
        senha = self._texto_obrigatorio(senha, "senha")
        perfil = self._texto_obrigatorio(perfil, "perfil")
        if perfil not in ("proprietario", "funcionario"):
            raise DadosInvalidosError("perfil deve ser proprietario ou funcionario")
        permissoes = tuple(
            self._permissao(valor) for valor in (p_fin, p_cad, p_ent, p_his)
        )
        if perfil == "proprietario":
            permissoes = (1, 1, 1, 1)
        try:
            with self._conexao() as conn:
                conn.execute(
                    """
                    INSERT INTO usuarios (
                        usuario, senha, perfil, p_ver_financeiro,
                        p_cadastrar_produto, p_fazer_entrada, p_ver_historico
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        usuario,
                        self._gerar_hash_senha(senha),
                        perfil,
                        *permissoes,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise DadosInvalidosError("já existe um usuário com esse nome") from exc

    def atualizar_permissoes_usuario(self, usuario, p_fin, p_cad, p_ent, p_his):
        """Atualiza a matriz de acesso de um usuário operacional."""
        usuario = self._texto_obrigatorio(usuario, "usuario")
        permissoes = tuple(
            self._permissao(valor) for valor in (p_fin, p_cad, p_ent, p_his)
        )
        with self._conexao() as conn:
            linha = conn.execute(
                "SELECT perfil FROM usuarios WHERE usuario=?", (usuario,)
            ).fetchone()
            if not linha:
                raise DadosInvalidosError("usuário não encontrado")
            if linha[0] == "proprietario":
                permissoes = (1, 1, 1, 1)
            conn.execute(
                """
                UPDATE usuarios
                SET p_ver_financeiro=?, p_cadastrar_produto=?,
                    p_fazer_entrada=?, p_ver_historico=?
                WHERE usuario=?
                """,
                (*permissoes, usuario),
            )

    def salvar_configuracoes(self, s_dono, s_caixa, p_fin, p_cad, p_ent, p_his):
        permissoes = tuple(
            self._permissao(valor) for valor in (p_fin, p_cad, p_ent, p_his)
        )
        with self._conexao() as conn:
            if s_dono:
                conn.execute(
                    "UPDATE usuarios SET senha=? WHERE usuario='dono'",
                    (self._gerar_hash_senha(str(s_dono)),),
                )
            if s_caixa:
                conn.execute(
                    "UPDATE usuarios SET senha=? WHERE usuario='caixa'",
                    (self._gerar_hash_senha(str(s_caixa)),),
                )
            conn.execute(
                """
                UPDATE usuarios
                SET p_ver_financeiro=?, p_cadastrar_produto=?,
                    p_fazer_entrada=?, p_ver_historico=?
                WHERE usuario='caixa'
                """,
                permissoes,
            )

    def validar_backup(self, caminho) -> bool:
        """Valida integridade SQLite e as tabelas mínimas da aplicação."""
        origem = Path(caminho)
        if not origem.is_file():
            raise BackupInvalidoError("Arquivo de backup não encontrado.")

        uri = origem.resolve().as_uri() + "?mode=ro"
        try:
            conn = sqlite3.connect(uri, uri=True, timeout=5)
            try:
                integridade = conn.execute("PRAGMA integrity_check").fetchone()[0]
                tabelas = self._listar_tabelas(conn)
            finally:
                conn.close()
        except sqlite3.DatabaseError as exc:
            raise BackupInvalidoError("O arquivo não é um SQLite íntegro.") from exc

        if integridade != "ok":
            raise BackupInvalidoError(f"Falha de integridade: {integridade}.")
        necessarias = {"estoque", "historico", "usuarios"}
        if not necessarias.issubset(tabelas):
            raise BackupInvalidoError("O arquivo não contém as tabelas da aplicação.")
        return True

    def criar_backup(self, destino) -> str:
        """Cria um snapshot consistente com a API nativa de backup do SQLite."""
        destino = Path(destino)
        origem = Path(self.db_name)
        if origem.resolve() == destino.resolve():
            raise DadosInvalidosError("O destino do backup deve ser diferente da base ativa.")
        destino.parent.mkdir(parents=True, exist_ok=True)

        fd, temporario_nome = tempfile.mkstemp(
            prefix=f".{destino.name}.", suffix=".tmp", dir=destino.parent
        )
        os.close(fd)
        temporario = Path(temporario_nome)
        try:
            origem_conn = self.conectar()
            try:
                destino_conn = sqlite3.connect(temporario)
                try:
                    origem_conn.backup(destino_conn)
                    destino_conn.commit()
                finally:
                    destino_conn.close()
            finally:
                origem_conn.close()
            self.validar_backup(temporario)
            os.replace(temporario, destino)
        except Exception:
            temporario.unlink(missing_ok=True)
            raise
        return str(destino)

    def restaurar_backup(self, origem) -> str:
        """Valida, cria cópia de segurança e substitui a base de forma atômica."""
        origem = Path(origem)
        destino = Path(self.db_name)
        if origem.resolve() == destino.resolve():
            raise DadosInvalidosError("O backup deve ser diferente da base ativa.")
        self.validar_backup(origem)

        momento = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        seguranca = destino.with_name(f"{destino.stem}.pre_restauracao_{momento}.db")
        self.criar_backup(seguranca)

        fd, temporario_nome = tempfile.mkstemp(
            prefix=f".{destino.name}.", suffix=".restore", dir=destino.parent
        )
        os.close(fd)
        temporario = Path(temporario_nome)
        try:
            shutil.copy2(origem, temporario)
            os.replace(temporario, destino)
            self._inicializar_banco()
        except Exception:
            temporario.unlink(missing_ok=True)
            shutil.copy2(seguranca, destino)
            raise
        return str(seguranca)
