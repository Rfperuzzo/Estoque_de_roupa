"""Interface desktop inspirada no projeto Stitch Modern Stock Manager."""

from __future__ import annotations

import csv
import os
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, filedialog, messagebox, ttk

import customtkinter as ctk

from banco import (
    BackupInvalidoError,
    BancoDeDados,
    DadosInvalidosError,
    EstoqueInsuficienteError,
    MigracaoError,
)


ARQUIVO_TEMA = "tema.txt"
MOV_SAIDA = "Saída"
MOV_ENTRADA = "Entrada"

# Tokens extraídos dos oito layouts do Stitch.
COR = {
    "nav": "#091426",
    "nav_hover": "#17243A",
    "nav_active": "#1E293B",
    "nav_text": "#B8C2D3",
    "bg": "#F8FAFC",
    "card": "#FFFFFF",
    "border": "#E2E8F0",
    "divider": "#F1F5F9",
    "text": "#1B1B1D",
    "muted": "#64748B",
    "subtle": "#94A3B8",
    "primary": "#091426",
    "primary_hover": "#1E293B",
    "warning": "#F59E0B",
    "warning_bg": "#FFF7E6",
    "danger": "#DC2626",
    "danger_bg": "#FEF2F2",
    "success": "#15803D",
    "success_bg": "#ECFDF3",
}

FONTE = "Segoe UI"
FONTE_DADOS = "Consolas"


class SistemaEstoqueApp:
    """Aplicação de estoque com navegação por módulos e componentes reutilizáveis."""

    def __init__(self, root):
        self.root = root
        self.root.title("Estoque · Gestão de Inventário")
        self.root.geometry("1280x800")
        self.root.minsize(1080, 680)
        self.root.configure(fg_color=COR["bg"])

        self.db = BancoDeDados()
        self.usuario_atual = ""
        self.perfil_usuario = ""
        self.permissoes = {}
        self.produto_id_selecionado = None
        self.usuario_selecionado = None
        self.tela_atual = ""
        self.nav_botoes = {}
        self._configurar_treeview()
        self.montar_tela_login()

    # ------------------------------------------------------------------
    # Componentes visuais compartilhados
    # ------------------------------------------------------------------
    def _configurar_treeview(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Modern.Treeview",
            background=COR["card"],
            fieldbackground=COR["card"],
            foreground=COR["text"],
            borderwidth=0,
            relief="flat",
            rowheight=36,
            font=(FONTE, 10),
        )
        style.map(
            "Modern.Treeview",
            background=[("selected", "#E8EEF7")],
            foreground=[("selected", COR["text"])],
        )
        style.configure(
            "Modern.Treeview.Heading",
            background="#F8FAFC",
            foreground=COR["muted"],
            borderwidth=0,
            relief="flat",
            font=(FONTE, 9, "bold"),
            padding=(8, 10),
        )
        style.map("Modern.Treeview.Heading", background=[("active", "#F1F5F9")])

    @staticmethod
    def _limpar(container):
        for widget in container.winfo_children():
            widget.destroy()

    @staticmethod
    def _formatar_moeda(valor):
        return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    def _card(self, parent, **kwargs):
        return ctk.CTkFrame(
            parent,
            fg_color=COR["card"],
            border_color=COR["border"],
            border_width=1,
            corner_radius=8,
            **kwargs,
        )

    def _botao_primario(self, parent, texto, comando, width=130):
        return ctk.CTkButton(
            parent,
            text=texto,
            command=comando,
            width=width,
            height=36,
            corner_radius=5,
            fg_color=COR["primary"],
            hover_color=COR["primary_hover"],
            font=(FONTE, 11, "bold"),
        )

    def _botao_secundario(self, parent, texto, comando, width=110):
        return ctk.CTkButton(
            parent,
            text=texto,
            command=comando,
            width=width,
            height=36,
            corner_radius=5,
            fg_color=COR["card"],
            hover_color="#F1F5F9",
            border_color="#CBD5E1",
            border_width=1,
            text_color=COR["text"],
            font=(FONTE, 11, "bold"),
        )

    def _entrada(self, parent, placeholder="", width=220, textvariable=None, show=None):
        return ctk.CTkEntry(
            parent,
            placeholder_text=placeholder,
            width=width,
            height=36,
            corner_radius=5,
            border_color="#CBD5E1",
            border_width=1,
            fg_color=COR["card"],
            text_color=COR["text"],
            placeholder_text_color=COR["subtle"],
            font=(FONTE, 11),
            textvariable=textvariable,
            show=show,
        )

    def _combo(self, parent, valores, width=200, command=None):
        return ctk.CTkComboBox(
            parent,
            values=valores,
            width=width,
            height=36,
            command=command,
            corner_radius=5,
            fg_color=COR["card"],
            border_color="#CBD5E1",
            button_color="#E2E8F0",
            button_hover_color="#CBD5E1",
            text_color=COR["text"],
            dropdown_fg_color=COR["card"],
            dropdown_hover_color="#F1F5F9",
            dropdown_text_color=COR["text"],
            font=(FONTE, 11),
        )

    def _cabecalho_pagina(self, titulo, subtitulo="", acao=None, texto_acao=None):
        frame = ctk.CTkFrame(self.view_container, fg_color="transparent")
        frame.pack(fill="x", pady=(0, 20))
        textos = ctk.CTkFrame(frame, fg_color="transparent")
        textos.pack(side=LEFT)
        ctk.CTkLabel(
            textos, text=titulo, text_color=COR["text"], font=(FONTE, 23, "bold")
        ).pack(anchor="w")
        if subtitulo:
            ctk.CTkLabel(
                textos, text=subtitulo, text_color=COR["muted"], font=(FONTE, 10)
            ).pack(anchor="w", pady=(2, 0))
        if acao and texto_acao:
            self._botao_primario(frame, texto_acao, acao, 145).pack(side=RIGHT, pady=2)
        return frame

    def _criar_tabela(self, parent, colunas, larguras, altura=8):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill=BOTH, expand=True)
        tree = ttk.Treeview(
            frame,
            columns=tuple(colunas),
            show="headings",
            style="Modern.Treeview",
            height=altura,
        )
        for coluna, largura in zip(colunas, larguras):
            tree.heading(coluna, text=coluna.upper())
            tree.column(coluna, width=largura, minwidth=45, anchor="w")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side=RIGHT, fill="y")
        tree.pack(fill=BOTH, expand=True)
        return tree

    def _rotulo_campo(self, parent, texto):
        return ctk.CTkLabel(
            parent, text=texto, text_color=COR["muted"], font=(FONTE, 9, "bold")
        )

    # ------------------------------------------------------------------
    # Login Stitch
    # ------------------------------------------------------------------
    def montar_tela_login(self):
        self._limpar(self.root)
        self.root.configure(fg_color=COR["bg"])
        self.root.unbind("<Return>")

        pagina = ctk.CTkFrame(self.root, fg_color=COR["bg"], corner_radius=0)
        pagina.pack(fill=BOTH, expand=True)

        painel = ctk.CTkFrame(pagina, fg_color="#1E293B", corner_radius=0, width=500)
        painel.pack(side=LEFT, fill="y")
        painel.pack_propagate(False)
        ctk.CTkLabel(
            painel,
            text="▣  ESTOQUE",
            text_color="white",
            font=(FONTE, 18, "bold"),
        ).pack(anchor="nw", padx=54, pady=(48, 0))

        mensagem = ctk.CTkFrame(painel, fg_color="transparent")
        mensagem.place(relx=0.5, rely=0.53, anchor="center")
        ctk.CTkLabel(
            mensagem,
            text="Gestão simples e segura\ndo seu estoque.",
            justify="left",
            text_color="white",
            font=(FONTE, 27, "bold"),
        ).pack(anchor="w")
        ctk.CTkLabel(
            mensagem,
            text="Controle de inventário projetado para eficiência\ne precisão nas operações diárias.",
            justify="left",
            text_color="#CBD5E1",
            font=(FONTE, 11),
        ).pack(anchor="w", pady=(14, 0))

        area = ctk.CTkFrame(pagina, fg_color=COR["bg"], corner_radius=0)
        area.pack(side=LEFT, fill=BOTH, expand=True)
        formulario = ctk.CTkFrame(area, fg_color="transparent", width=390)
        formulario.place(relx=0.5, rely=0.5, anchor="center")
        ctk.CTkLabel(
            formulario, text="Bem-vindo", text_color=COR["text"], font=(FONTE, 24, "bold")
        ).pack(anchor="w")
        ctk.CTkLabel(
            formulario,
            text="Insira suas credenciais para continuar.",
            text_color=COR["muted"],
            font=(FONTE, 10),
        ).pack(anchor="w", pady=(3, 20))

        card = self._card(formulario)
        card.pack(fill="x")
        self._rotulo_campo(card, "USUÁRIO").pack(anchor="w", padx=18, pady=(18, 5))
        self.entry_user = self._entrada(card, "Digite seu usuário", width=354)
        self.entry_user.pack(padx=18)
        self._rotulo_campo(card, "SENHA").pack(anchor="w", padx=18, pady=(14, 5))
        self.entry_senha = self._entrada(card, "Digite sua senha", width=354, show="•")
        self.entry_senha.pack(padx=18)
        self.lbl_login_erro = ctk.CTkLabel(
            card, text="", text_color=COR["danger"], font=(FONTE, 9)
        )
        self.lbl_login_erro.pack(anchor="w", padx=18, pady=(5, 0))
        self._botao_primario(card, "Entrar", self.fazer_login, 354).pack(
            padx=18, pady=(8, 18)
        )
        ctk.CTkLabel(
            formulario,
            text="Use suas credenciais para acessar o sistema.",
            text_color=COR["subtle"],
            font=(FONTE, 9),
        ).pack(pady=(18, 0))
        self.entry_user.focus_set()
        self.root.bind("<Return>", lambda _event: self.fazer_login())

    def fazer_login(self):
        usuario = self.entry_user.get().strip()
        senha = self.entry_senha.get()
        try:
            dados = self.db.fazer_login(usuario, senha)
        except (MigracaoError, OSError) as exc:
            self.lbl_login_erro.configure(text=str(exc))
            return
        if not dados:
            self.lbl_login_erro.configure(text="Usuário ou senha incorretos.")
            return
        self.usuario_atual = usuario
        self.perfil_usuario = dados[0]
        self.permissoes = {
            "ver_financeiro": bool(dados[1]),
            "cadastrar_produto": bool(dados[2]),
            "fazer_entrada": bool(dados[3]),
            "ver_historico": bool(dados[4]),
        }
        self.root.unbind("<Return>")
        self.montar_tela_principal()

    def fazer_logout(self):
        self.usuario_atual = ""
        self.perfil_usuario = ""
        self.permissoes = {}
        self.produto_id_selecionado = None
        self.montar_tela_login()

    # ------------------------------------------------------------------
    # Shell compartilhado: sidebar, topbar e roteamento
    # ------------------------------------------------------------------
    def montar_tela_principal(self):
        self._limpar(self.root)
        shell = ctk.CTkFrame(self.root, fg_color=COR["bg"], corner_radius=0)
        shell.pack(fill=BOTH, expand=True)

        sidebar = ctk.CTkFrame(shell, fg_color=COR["nav"], corner_radius=0, width=220)
        sidebar.pack(side=LEFT, fill="y")
        sidebar.pack_propagate(False)
        ctk.CTkLabel(
            sidebar,
            text="▣  ESTOQUE",
            text_color="white",
            font=(FONTE, 17, "bold"),
        ).pack(anchor="w", padx=22, pady=(26, 2))
        ctk.CTkLabel(
            sidebar,
            text="Gestão de Inventário",
            text_color="#8FA0B8",
            font=(FONTE, 9),
        ).pack(anchor="w", padx=22, pady=(0, 24))

        nav = ctk.CTkFrame(sidebar, fg_color="transparent")
        nav.pack(fill="x")
        itens = [
            ("dashboard", "▦", "Dashboard"),
            ("produtos", "▤", "Produtos"),
            ("movimentacao", "⇄", "Movimentações"),
        ]
        if self.permissoes.get("ver_historico"):
            itens.append(("historico", "◷", "Histórico"))
        if self.perfil_usuario == "proprietario":
            itens.append(("usuarios", "♙", "Usuários"))
        if self.permissoes.get("ver_financeiro"):
            itens.append(("relatorios", "▥", "Relatórios"))
        if self.perfil_usuario == "proprietario":
            itens.extend(
                [
                    ("backup", "◈", "Backup e Segurança"),
                    ("configuracoes", "⚙", "Configurações"),
                ]
            )

        self.nav_botoes = {}
        for chave, icone, titulo in itens:
            botao = ctk.CTkButton(
                nav,
                text=f"{icone}   {titulo}",
                command=lambda tela=chave: self.navegar(tela),
                height=42,
                corner_radius=0,
                anchor="w",
                fg_color="transparent",
                hover_color=COR["nav_hover"],
                text_color=COR["nav_text"],
                font=(FONTE, 11),
            )
            botao.pack(fill="x")
            self.nav_botoes[chave] = botao

        rodape = ctk.CTkFrame(sidebar, fg_color="transparent")
        rodape.pack(side="bottom", fill="x", pady=18)
        ctk.CTkLabel(
            rodape,
            text=f"○  {self.usuario_atual}\n    {self.perfil_usuario.title()}",
            justify="left",
            text_color=COR["nav_text"],
            font=(FONTE, 10),
        ).pack(anchor="w", padx=20, pady=(0, 8))
        ctk.CTkButton(
            rodape,
            text="↪   Sair",
            command=self.fazer_logout,
            anchor="w",
            height=34,
            corner_radius=0,
            fg_color="transparent",
            hover_color=COR["nav_hover"],
            text_color=COR["nav_text"],
            font=(FONTE, 10),
        ).pack(fill="x")

        principal = ctk.CTkFrame(shell, fg_color=COR["bg"], corner_radius=0)
        principal.pack(side=LEFT, fill=BOTH, expand=True)
        topbar = ctk.CTkFrame(
            principal,
            fg_color=COR["card"],
            corner_radius=0,
            height=62,
            border_width=1,
            border_color=COR["border"],
        )
        topbar.pack(fill="x")
        topbar.pack_propagate(False)
        self.entry_busca_global = self._entrada(topbar, "⌕  Buscar produtos...", 270)
        self.entry_busca_global.pack(side=LEFT, padx=24, pady=13)
        self.entry_busca_global.bind("<Return>", self._buscar_global)
        ctk.CTkLabel(
            topbar, text="◌   ⓘ", text_color=COR["muted"], font=(FONTE, 15)
        ).pack(side=RIGHT, padx=(8, 22))
        if self.permissoes.get("cadastrar_produto"):
            self._botao_primario(topbar, "+  Novo Produto", self.abrir_editor_produto, 145).pack(
                side=RIGHT, pady=13
            )

        self.view_container = ctk.CTkFrame(principal, fg_color=COR["bg"], corner_radius=0)
        self.view_container.pack(fill=BOTH, expand=True, padx=26, pady=22)
        self.navegar("dashboard")

    def _buscar_global(self, _event=None):
        termo = self.entry_busca_global.get().strip()
        self.navegar("produtos")
        if hasattr(self, "entry_busca_produtos"):
            self.entry_busca_produtos.delete(0, END)
            self.entry_busca_produtos.insert(0, termo)
            self.carregar_produtos_view()

    def navegar(self, tela):
        permitidas = {
            "dashboard": True,
            "produtos": True,
            "produto_detalhes": True,
            "movimentacao": True,
            "historico": self.permissoes.get("ver_historico"),
            "usuarios": self.perfil_usuario == "proprietario",
            "relatorios": self.permissoes.get("ver_financeiro"),
            "backup": self.perfil_usuario == "proprietario",
            "configuracoes": self.perfil_usuario == "proprietario",
        }
        if not permitidas.get(tela):
            messagebox.showwarning("Acesso restrito", "Seu perfil não possui acesso a este módulo.")
            return
        self.tela_atual = tela
        self._limpar(self.view_container)
        ativo = "produtos" if tela == "produto_detalhes" else tela
        for chave, botao in self.nav_botoes.items():
            selecionado = chave == ativo
            botao.configure(
                fg_color=COR["nav_active"] if selecionado else "transparent",
                text_color="white" if selecionado else COR["nav_text"],
                font=(FONTE, 11, "bold" if selecionado else "normal"),
            )
        rotas = {
            "dashboard": self.montar_dashboard,
            "produtos": self.montar_produtos,
            "produto_detalhes": self.montar_detalhes_produto,
            "movimentacao": self.montar_movimentacao,
            "historico": self.montar_historico,
            "usuarios": self.montar_usuarios,
            "relatorios": self.montar_relatorios,
            "backup": self.montar_backup,
            "configuracoes": self.montar_configuracoes,
        }
        rotas[tela]()

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------
    def montar_dashboard(self):
        topo = self._cabecalho_pagina(
            "Visão geral do estoque", "Acompanhamento atualizado do inventário"
        )
        ctk.CTkLabel(
            topo,
            text=f"DATA ATUAL\n{datetime.now().strftime('%d de %b. de %Y')}",
            justify="right",
            text_color=COR["muted"],
            font=(FONTE, 9, "bold"),
        ).pack(side=RIGHT, padx=18)

        resumo = self.db.obter_resumo_estoque()
        cards = ctk.CTkFrame(self.view_container, fg_color="transparent", height=122)
        cards.pack(fill="x", pady=(0, 20))
        cards.pack_propagate(False)
        cards.grid_propagate(False)
        cards.grid_rowconfigure(0, weight=1)
        for indice in range(4):
            cards.grid_columnconfigure(indice, weight=1)
        metricas = [
            ("PRODUTOS CADASTRADOS", resumo["produtos"], "▤", COR["text"]),
            ("UNIDADES EM ESTOQUE", resumo["unidades"], "□", COR["text"]),
            ("ESTOQUE BAIXO", resumo["estoque_baixo"], "△", COR["warning"]),
            (
                "VALOR DO ESTOQUE",
                self._formatar_moeda(resumo["valor_total"])
                if self.permissoes.get("ver_financeiro")
                else "Acesso restrito",
                "♙",
                COR["text"],
            ),
        ]
        for i, (rotulo, valor, icone, cor) in enumerate(metricas):
            card = self._card(cards)
            card.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 7, 0 if i == 3 else 7))
            card.grid_propagate(False)
            ctk.CTkLabel(card, text=icone, text_color=cor, font=(FONTE, 18)).pack(
                anchor="e", padx=16, pady=(12, 0)
            )
            ctk.CTkLabel(
                card, text=rotulo, text_color=cor, font=(FONTE, 8, "bold")
            ).place(x=15, y=16)
            ctk.CTkLabel(
                card, text=str(valor), text_color=cor, font=(FONTE, 23, "bold")
            ).place(x=15, y=48)

        grade = ctk.CTkFrame(self.view_container, fg_color="transparent")
        grade.pack(fill=BOTH, expand=True)
        grade.grid_columnconfigure(0, weight=3)
        grade.grid_columnconfigure(1, weight=2)
        grade.grid_rowconfigure(0, weight=1)

        alertas = self._card(grade)
        alertas.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        cab = ctk.CTkFrame(alertas, fg_color="transparent")
        cab.pack(fill="x", padx=16, pady=14)
        ctk.CTkLabel(
            cab, text="◉  Alertas de Estoque Baixo", text_color=COR["text"], font=(FONTE, 13, "bold")
        ).pack(side=LEFT)
        ctk.CTkButton(
            cab,
            text="Ver todos",
            command=lambda: self.navegar("produtos"),
            fg_color="transparent",
            hover_color="#F1F5F9",
            text_color=COR["text"],
            width=80,
            height=28,
        ).pack(side=RIGHT)
        tree = self._criar_tabela(alertas, ["Produto", "SKU", "Categoria", "Qtd", "Mínimo", "Status"], [180, 85, 110, 55, 55, 75], 8)
        tree.tag_configure("critico", foreground=COR["danger"])
        tree.tag_configure("baixo", foreground="#B45309")
        for produto in self.db.buscar_estoque_baixo():
            status = "CRÍTICO" if produto[6] <= 2 else "BAIXO"
            tree.insert(
                "", END, values=(produto[2], produto[1], produto[3], produto[6], 5, status),
                tags=("critico" if produto[6] <= 2 else "baixo",),
            )

        recentes = self._card(grade)
        recentes.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        ctk.CTkLabel(
            recentes,
            text="↕  Movimentações Recentes",
            text_color=COR["text"],
            font=(FONTE, 13, "bold"),
        ).pack(anchor="w", padx=16, pady=14)
        tree_r = self._criar_tabela(recentes, ["Movimento", "Produto", "Qtd", "Data"], [90, 160, 55, 105], 8)
        tree_r.tag_configure("entrada", foreground=COR["success"])
        tree_r.tag_configure("saida", foreground=COR["danger"])
        for linha in self.db.buscar_historico()[:10]:
            tree_r.insert(
                "", END,
                values=(linha[1].upper(), linha[2], f"{linha[4]:+}" if linha[1] == MOV_ENTRADA else f"-{linha[4]}", linha[5]),
                tags=("entrada" if linha[1] == MOV_ENTRADA else "saida",),
            )

    # ------------------------------------------------------------------
    # Produtos: listagem, edição e detalhes
    # ------------------------------------------------------------------
    def montar_produtos(self):
        self._cabecalho_pagina("Produtos", "Gerencie o catálogo e os níveis de estoque")
        filtros = self._card(self.view_container)
        filtros.pack(fill="x", pady=(0, 14))
        self.entry_busca_produtos = self._entrada(filtros, "⌕  Buscar por produto, SKU ou categoria...", 390)
        self.entry_busca_produtos.pack(side=LEFT, padx=14, pady=12)
        self.entry_busca_produtos.bind("<Return>", lambda _event: self.carregar_produtos_view())
        self._botao_secundario(filtros, "Buscar", self.carregar_produtos_view, 90).pack(side=LEFT)

        tabela_card = self._card(self.view_container)
        tabela_card.pack(fill=BOTH, expand=True)
        self.tree_produtos = self._criar_tabela(
            tabela_card,
            ["ID", "SKU", "Produto", "Categoria", "Tamanho", "Cor", "Estoque", "Preço"],
            [50, 95, 220, 120, 75, 95, 75, 100],
            12,
        )
        self.tree_produtos.tag_configure("baixo", foreground=COR["danger"])
        self.tree_produtos.bind("<Double-1>", lambda _event: self.mostrar_detalhes_selecionado())
        acoes = ctk.CTkFrame(tabela_card, fg_color="transparent")
        acoes.pack(fill="x", padx=14, pady=12)
        self.lbl_produtos_status = ctk.CTkLabel(
            acoes, text="", text_color=COR["muted"], font=(FONTE, 9)
        )
        self.lbl_produtos_status.pack(side=LEFT)
        self._botao_secundario(acoes, "Ver detalhes", self.mostrar_detalhes_selecionado, 110).pack(side=RIGHT, padx=4)
        if self.permissoes.get("cadastrar_produto"):
            self._botao_secundario(acoes, "Editar", self.editar_produto_selecionado, 85).pack(side=RIGHT, padx=4)
            ctk.CTkButton(
                acoes,
                text="Excluir",
                command=self.excluir_produto_selecionado,
                width=85,
                height=36,
                fg_color=COR["danger_bg"],
                hover_color="#FEE2E2",
                text_color=COR["danger"],
                border_color="#FECACA",
                border_width=1,
            ).pack(side=RIGHT, padx=4)
        self.carregar_produtos_view()

    def carregar_produtos_view(self):
        if not hasattr(self, "tree_produtos"):
            return
        for item in self.tree_produtos.get_children():
            self.tree_produtos.delete(item)
        termo = self.entry_busca_produtos.get().strip()
        produtos = self.db.buscar_produtos(termo)
        for produto in produtos:
            preco = self._formatar_moeda(produto[7]) if self.permissoes.get("ver_financeiro") else "Restrito"
            self.tree_produtos.insert(
                "", END,
                values=(*produto[:7], preco),
                tags=("baixo",) if produto[6] <= 5 else (),
            )
        self.lbl_produtos_status.configure(text=f"Mostrando {len(produtos)} produto(s)")

    def _id_produto_focado(self):
        if not hasattr(self, "tree_produtos"):
            return None
        selecionado = self.tree_produtos.focus()
        if not selecionado:
            messagebox.showwarning("Seleção necessária", "Selecione um produto na listagem.")
            return None
        return int(self.tree_produtos.item(selecionado, "values")[0])

    def mostrar_detalhes_selecionado(self):
        produto_id = self._id_produto_focado()
        if produto_id is not None:
            self.produto_id_selecionado = produto_id
            self.navegar("produto_detalhes")

    def editar_produto_selecionado(self):
        produto_id = self._id_produto_focado()
        if produto_id is not None:
            self.abrir_editor_produto(produto_id)

    def excluir_produto_selecionado(self):
        produto_id = self._id_produto_focado()
        if produto_id is None:
            return
        if messagebox.askyesno("Excluir produto", "Confirma a exclusão permanente deste produto?"):
            self.db.excluir_produto(produto_id)
            self.carregar_produtos_view()

    def abrir_editor_produto(self, produto_id=None):
        if not self.permissoes.get("cadastrar_produto"):
            messagebox.showwarning("Acesso restrito", "Seu perfil não pode alterar produtos.")
            return
        produto = None
        if produto_id:
            produto = next((p for p in self.db.buscar_produtos() if p[0] == int(produto_id)), None)
        janela = ctk.CTkToplevel(self.root)
        janela.title("Editar Produto" if produto else "Novo Produto")
        janela.geometry("610x575")
        janela.resizable(False, False)
        janela.configure(fg_color=COR["bg"])
        janela.transient(self.root)
        janela.grab_set()

        corpo = ctk.CTkFrame(janela, fg_color=COR["bg"], corner_radius=0)
        corpo.pack(fill=BOTH, expand=True, padx=28, pady=24)
        ctk.CTkLabel(
            corpo,
            text="Editar produto" if produto else "Cadastrar novo produto",
            text_color=COR["text"],
            font=(FONTE, 21, "bold"),
        ).pack(anchor="w")
        ctk.CTkLabel(
            corpo,
            text="Preencha os dados de identificação, variação e estoque.",
            text_color=COR["muted"],
            font=(FONTE, 10),
        ).pack(anchor="w", pady=(2, 16))
        card = self._card(corpo)
        card.pack(fill=BOTH, expand=True)
        card.grid_columnconfigure((0, 1), weight=1)

        campos = {}
        definicoes = [
            ("sku", "SKU", "Código do produto", 0, 0),
            ("nome", "NOME DO PRODUTO", "Nome obrigatório", 0, 1),
            ("categoria", "CATEGORIA", "Camiseta, Calça...", 1, 0),
            ("tamanho", "TAMANHO", "PP, P, M, G...", 1, 1),
            ("cor", "COR", "Cor ou variação", 2, 0),
            ("quantidade", "QUANTIDADE", "Saldo inicial", 2, 1),
            ("preco", "PREÇO (R$)", "0,00", 3, 0),
        ]
        for chave, rotulo, placeholder, linha, coluna in definicoes:
            grupo = ctk.CTkFrame(card, fg_color="transparent")
            grupo.grid(row=linha, column=coluna, sticky="ew", padx=14, pady=(14, 2))
            self._rotulo_campo(grupo, rotulo).pack(anchor="w", pady=(0, 5))
            entrada = self._entrada(grupo, placeholder, 240)
            entrada.pack(fill="x")
            campos[chave] = entrada
        if produto:
            valores = [produto[1], produto[2], produto[3], produto[4], produto[5], produto[6], f"{produto[7]:.2f}".replace(".", ",")]
            for chave, valor in zip(("sku", "nome", "categoria", "tamanho", "cor", "quantidade", "preco"), valores):
                campos[chave].insert(0, valor)

        def salvar():
            try:
                quantidade = int(campos["quantidade"].get())
                preco = float(campos["preco"].get().replace(",", "."))
                dados = (
                    campos["sku"].get(), campos["nome"].get(), campos["categoria"].get(),
                    campos["tamanho"].get(), campos["cor"].get(), quantidade, preco,
                )
                if produto:
                    self.db.atualizar_produto(produto[0], *dados)
                else:
                    self.db.adicionar_produto(*dados)
            except (ValueError, DadosInvalidosError) as exc:
                messagebox.showerror("Dados inválidos", str(exc), parent=janela)
                return
            janela.destroy()
            messagebox.showinfo("Produto salvo", "As informações foram salvas com sucesso.")
            self.navegar("produtos")

        botoes = ctk.CTkFrame(corpo, fg_color="transparent")
        botoes.pack(fill="x", pady=(16, 0))
        self._botao_primario(botoes, "Salvar Produto", salvar, 145).pack(side=RIGHT)
        self._botao_secundario(botoes, "Cancelar", janela.destroy, 100).pack(side=RIGHT, padx=8)

    def montar_detalhes_produto(self):
        produto = next(
            (p for p in self.db.buscar_produtos() if p[0] == self.produto_id_selecionado), None
        )
        if not produto:
            self.navegar("produtos")
            return
        topo = self._cabecalho_pagina(produto[2], "‹ Voltar para Produtos")
        ctk.CTkButton(
            topo,
            text="‹  Voltar",
            command=lambda: self.navegar("produtos"),
            width=80,
            height=30,
            fg_color="transparent",
            hover_color="#EEF2F7",
            text_color=COR["muted"],
        ).pack(side=RIGHT, padx=6)
        if self.permissoes.get("cadastrar_produto"):
            self._botao_primario(topo, "Editar", lambda: self.abrir_editor_produto(produto[0]), 90).pack(side=RIGHT)

        resumo = ctk.CTkFrame(self.view_container, fg_color="transparent")
        resumo.pack(fill="x", pady=(0, 18))
        resumo.grid_columnconfigure(0, weight=3)
        resumo.grid_columnconfigure(1, weight=1)
        dados = self._card(resumo, height=245)
        dados.grid(row=0, column=0, sticky="nsew", padx=(0, 9))
        dados.grid_propagate(False)
        imagem = ctk.CTkFrame(dados, fg_color="#E9ECEF", corner_radius=6, width=190, height=190)
        imagem.pack(side=LEFT, padx=18, pady=18)
        imagem.pack_propagate(False)
        ctk.CTkLabel(imagem, text="▤", text_color="#94A3B8", font=(FONTE, 52)).place(relx=0.5, rely=0.5, anchor="center")
        info = ctk.CTkFrame(dados, fg_color="transparent")
        info.pack(side=LEFT, fill=BOTH, expand=True, padx=(4, 18), pady=22)
        ctk.CTkLabel(info, text="Detalhes do item", text_color=COR["text"], font=(FONTE, 16, "bold")).pack(anchor="w", pady=(0, 14))
        pares = [
            ("SKU", produto[1] or "—"), ("Categoria", produto[3] or "—"),
            ("Tamanho", produto[4] or "—"), ("Cor", produto[5] or "—"),
            ("Preço", self._formatar_moeda(produto[7]) if self.permissoes.get("ver_financeiro") else "Acesso restrito"),
        ]
        for rotulo, valor in pares:
            linha = ctk.CTkFrame(info, fg_color="transparent")
            linha.pack(fill="x", pady=4)
            ctk.CTkLabel(linha, text=rotulo, width=90, anchor="w", text_color=COR["muted"], font=(FONTE, 9, "bold")).pack(side=LEFT)
            ctk.CTkLabel(linha, text=str(valor), anchor="w", text_color=COR["text"], font=(FONTE, 10)).pack(side=LEFT)

        status = self._card(resumo, height=245)
        status.grid(row=0, column=1, sticky="nsew", padx=(9, 0))
        status.grid_propagate(False)
        ctk.CTkLabel(status, text="Status do Estoque", text_color=COR["text"], font=(FONTE, 15, "bold")).pack(anchor="w", padx=18, pady=(20, 10))
        ctk.CTkLabel(status, text=str(produto[6]), text_color=COR["text"], font=(FONTE, 36, "bold")).pack()
        ctk.CTkLabel(status, text="Unidades disponíveis", text_color=COR["muted"], font=(FONTE, 9)).pack()
        estado = "Crítico" if produto[6] <= 2 else "Baixo" if produto[6] <= 5 else "Saudável"
        cor_estado = COR["danger"] if produto[6] <= 2 else COR["warning"] if produto[6] <= 5 else COR["success"]
        ctk.CTkLabel(status, text=f"●  {estado}", text_color=cor_estado, font=(FONTE, 11, "bold")).pack(pady=18)
        self._botao_primario(status, "+ Movimentar", lambda: self.navegar("movimentacao"), 135).pack()

        historico = self._card(self.view_container)
        historico.pack(fill=BOTH, expand=True)
        ctk.CTkLabel(historico, text="Histórico deste produto", text_color=COR["text"], font=(FONTE, 13, "bold")).pack(anchor="w", padx=16, pady=14)
        tree = self._criar_tabela(historico, ["Data/Hora", "Movimentação", "Quantidade", "Envolvido"], [145, 110, 90, 240], 6)
        for linha in self.db.buscar_historico_produto(produto[2]):
            tree.insert("", END, values=(linha[5], linha[1], linha[4], linha[3]))

    # ------------------------------------------------------------------
    # Movimentação
    # ------------------------------------------------------------------
    def montar_movimentacao(self):
        self._cabecalho_pagina("Movimentação de Estoque", "Registre entradas e saídas com validação de saldo")
        centro = ctk.CTkFrame(self.view_container, fg_color="transparent")
        centro.pack(fill=BOTH, expand=True)
        card = self._card(centro, width=760)
        card.pack(anchor="n", pady=4)
        card.pack_propagate(False)
        card.configure(height=450)

        self._rotulo_campo(card, "SELECIONAR PRODUTO").pack(anchor="w", padx=22, pady=(16, 5))
        produtos = self.db.buscar_produtos()
        self.mov_produtos = {
            f"{p[1] or 'SEM-SKU'} · {p[2]}": p for p in produtos
        }
        valores = list(self.mov_produtos) or ["Nenhum produto cadastrado"]
        self.combo_produto_mov = ctk.CTkComboBox(
            card,
            values=valores,
            width=716,
            height=38,
            command=lambda _valor: self.atualizar_previa_movimentacao(),
            fg_color=COR["card"],
            border_color="#CBD5E1",
            button_color="#E2E8F0",
            button_hover_color="#CBD5E1",
            text_color=COR["text"],
            font=(FONTE, 11),
        )
        self.combo_produto_mov.pack(padx=22)
        self.combo_produto_mov.set(valores[0])

        selecionado = ctk.CTkFrame(card, fg_color="#F8FAFC", corner_radius=5, height=52)
        selecionado.pack(fill="x", padx=22, pady=(6, 11))
        selecionado.pack_propagate(False)
        self.lbl_mov_produto = ctk.CTkLabel(selecionado, text="", text_color=COR["text"], font=(FONTE, 11, "bold"))
        self.lbl_mov_produto.pack(side=LEFT, padx=14)
        self.lbl_mov_saldo = ctk.CTkLabel(selecionado, text="", text_color=COR["text"], font=(FONTE, 19, "bold"))
        self.lbl_mov_saldo.pack(side=RIGHT, padx=18)

        self._rotulo_campo(card, "TIPO DE MOVIMENTAÇÃO").pack(anchor="w", padx=22, pady=(0, 6))
        tipos = [MOV_SAIDA, MOV_ENTRADA] if self.permissoes.get("fazer_entrada") else [MOV_SAIDA]
        self.segmento_mov = ctk.CTkSegmentedButton(
            card,
            values=tipos,
            width=716,
            height=42,
            command=lambda _valor: self.atualizar_previa_movimentacao(),
            selected_color="#FDECEC",
            selected_hover_color="#FEE2E2",
            unselected_color=COR["card"],
            unselected_hover_color="#F1F5F9",
            text_color=COR["text"],
        )
        self.segmento_mov.pack(padx=22)
        self.segmento_mov.set(MOV_SAIDA)

        campos = ctk.CTkFrame(card, fg_color="transparent")
        campos.pack(fill="x", padx=22, pady=11)
        self.var_qtd_mov = ctk.StringVar()
        self.var_qtd_mov.trace_add("write", lambda *_: self.atualizar_previa_movimentacao())
        qtd = ctk.CTkFrame(campos, fg_color="transparent")
        qtd.pack(side=LEFT)
        self._rotulo_campo(qtd, "QUANTIDADE").pack(anchor="w", pady=(0, 5))
        self.entry_qtd_mov = self._entrada(qtd, "0", 210, self.var_qtd_mov)
        self.entry_qtd_mov.pack()
        obs = ctk.CTkFrame(campos, fg_color="transparent")
        obs.pack(side=LEFT, fill="x", expand=True, padx=(14, 0))
        self._rotulo_campo(obs, "OBSERVAÇÃO / ENVOLVIDO").pack(anchor="w", pady=(0, 5))
        self.entry_envolvido = self._entrada(obs, "Ex.: Cliente ou fornecedor", 490)
        self.entry_envolvido.pack(fill="x")

        previa = ctk.CTkFrame(card, fg_color="#F8FAFC", corner_radius=5, height=50)
        previa.pack(fill="x", padx=22)
        previa.pack_propagate(False)
        self.lbl_mov_previa = ctk.CTkLabel(previa, text="", text_color=COR["muted"], font=(FONTE, 10))
        self.lbl_mov_previa.pack(anchor="w", padx=14, pady=8)
        acoes = ctk.CTkFrame(card, fg_color="transparent")
        acoes.pack(fill="x", padx=22, pady=11)
        self._botao_primario(acoes, "✓  Confirmar Movimentação", self.registrar_movimentacao, 210).pack(side=RIGHT)
        self.entry_qtd_mov.bind("<Return>", self.registrar_movimentacao)
        self.atualizar_previa_movimentacao()

    def atualizar_previa_movimentacao(self):
        if not hasattr(self, "combo_produto_mov"):
            return
        produto = self.mov_produtos.get(self.combo_produto_mov.get())
        if not produto:
            self.lbl_mov_produto.configure(text="Nenhum produto selecionado")
            self.lbl_mov_saldo.configure(text="0")
            self.lbl_mov_previa.configure(text="Cadastre um produto antes de movimentar o estoque.")
            return
        self.lbl_mov_produto.configure(text=f"{produto[2]}  ·  {produto[1] or 'SEM-SKU'}")
        self.lbl_mov_saldo.configure(text=f"{produto[6]} un")
        try:
            qtd = int(self.var_qtd_mov.get() or 0)
        except ValueError:
            qtd = 0
        novo = produto[6] + qtd if self.segmento_mov.get() == MOV_ENTRADA else produto[6] - qtd
        self.lbl_mov_previa.configure(
            text=f"Estoque atual: {produto[6]}     Quantidade: {qtd}     Saldo após operação: {novo}",
            text_color=COR["danger"] if novo < 0 else COR["muted"],
        )

    def registrar_movimentacao(self, _event=None):
        produto = self.mov_produtos.get(self.combo_produto_mov.get())
        if not produto:
            messagebox.showwarning("Produto necessário", "Selecione um produto válido.")
            return "break"
        try:
            novo = self.db.movimentar_estoque(
                produto[0],
                self.segmento_mov.get(),
                self.entry_envolvido.get(),
                self.var_qtd_mov.get(),
            )
        except (DadosInvalidosError, EstoqueInsuficienteError) as exc:
            messagebox.showerror("Movimentação não realizada", str(exc))
            return "break"
        messagebox.showinfo("Movimentação concluída", f"Novo saldo: {novo} unidade(s).")
        self.navegar("movimentacao")
        return "break"

    # ------------------------------------------------------------------
    # Histórico e relatórios
    # ------------------------------------------------------------------
    def montar_historico(self):
        self._cabecalho_pagina("Histórico", "Registro consolidado das movimentações de estoque")
        card = self._card(self.view_container)
        card.pack(fill=BOTH, expand=True)
        tree = self._criar_tabela(card, ["ID", "Tipo", "Produto", "Envolvido", "Qtd", "Data/Hora"], [55, 90, 230, 190, 65, 145], 13)
        tree.tag_configure("entrada", foreground=COR["success"])
        tree.tag_configure("saida", foreground=COR["danger"])
        for linha in self.db.buscar_historico():
            tree.insert("", END, values=linha, tags=("entrada" if linha[1] == MOV_ENTRADA else "saida",))
        if self.perfil_usuario == "proprietario":
            def excluir():
                selecionado = tree.focus()
                if selecionado and messagebox.askyesno("Excluir registro", "Confirma a exclusão deste registro?"):
                    self.db.excluir_historico(tree.item(selecionado, "values")[0])
                    tree.delete(selecionado)
            self._botao_secundario(card, "Excluir registro", excluir, 125).pack(anchor="e", padx=14, pady=12)

    def montar_relatorios(self):
        self._cabecalho_pagina("Relatórios", "Análise consolidada de movimentações e posição de estoque", self.exportar_relatorio, "⇩ Exportar relatório")
        filtros = self._card(self.view_container)
        filtros.pack(fill="x", pady=(0, 14))
        opcoes = ctk.CTkFrame(filtros, fg_color="transparent")
        opcoes.pack(fill="x", padx=14, pady=12)
        produtos = self.db.buscar_produtos()
        self.rel_categoria = self._combo(opcoes, ["Todas as categorias"] + sorted({p[3] for p in produtos if p[3]}), 190, lambda _v: self.atualizar_relatorio())
        self.rel_categoria.pack(side=LEFT, padx=(0, 8))
        self.rel_produto = self._combo(opcoes, ["Todos os produtos"] + [p[2] for p in produtos], 220, lambda _v: self.atualizar_relatorio())
        self.rel_produto.pack(side=LEFT, padx=8)
        self.rel_tipo = self._combo(opcoes, ["Todas as movimentações", MOV_ENTRADA, MOV_SAIDA], 190, lambda _v: self.atualizar_relatorio())
        self.rel_tipo.pack(side=LEFT, padx=8)
        self.rel_periodo = self._combo(opcoes, ["Todo o histórico", "Últimos 30 dias", "Últimos 7 dias"], 170, lambda _v: self.atualizar_relatorio())
        self.rel_periodo.pack(side=LEFT, padx=8)
        self.rel_categoria.set("Todas as categorias")
        self.rel_produto.set("Todos os produtos")
        self.rel_tipo.set("Todas as movimentações")
        self.rel_periodo.set("Todo o histórico")

        metricas = ctk.CTkFrame(self.view_container, fg_color="transparent")
        metricas.pack(fill="x", pady=(0, 14))
        for i in range(3):
            metricas.grid_columnconfigure(i, weight=1)
        self.rel_valores = []
        for i, titulo in enumerate(("ENTRADAS NO PERÍODO", "SAÍDAS NO PERÍODO", "PRODUTOS MOVIMENTADOS")):
            card = self._card(metricas, height=100)
            card.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 7, 0 if i == 2 else 7))
            card.grid_propagate(False)
            ctk.CTkLabel(card, text=titulo, text_color=COR["muted"], font=(FONTE, 8, "bold")).pack(anchor="w", padx=16, pady=(16, 2))
            valor = ctk.CTkLabel(card, text="0", text_color=COR["text"], font=(FONTE, 23, "bold"))
            valor.pack(anchor="w", padx=16)
            self.rel_valores.append(valor)

        card_tabela = self._card(self.view_container)
        card_tabela.pack(fill=BOTH, expand=True)
        self.tree_relatorio = self._criar_tabela(card_tabela, ["Data/Hora", "Tipo", "Produto", "Envolvido", "Qtd"], [150, 100, 240, 210, 70], 8)
        self.atualizar_relatorio()

    def _linhas_relatorio_filtradas(self):
        linhas = self.db.buscar_historico()
        produto_categoria = {p[2]: p[3] for p in self.db.buscar_produtos()}
        categoria = self.rel_categoria.get()
        produto = self.rel_produto.get()
        tipo = self.rel_tipo.get()
        periodo = self.rel_periodo.get()
        corte = None
        if periodo == "Últimos 30 dias":
            corte = datetime.now() - timedelta(days=30)
        elif periodo == "Últimos 7 dias":
            corte = datetime.now() - timedelta(days=7)
        filtradas = []
        for linha in linhas:
            if categoria != "Todas as categorias" and produto_categoria.get(linha[2]) != categoria:
                continue
            if produto != "Todos os produtos" and linha[2] != produto:
                continue
            if tipo != "Todas as movimentações" and linha[1] != tipo:
                continue
            if corte:
                try:
                    if datetime.strptime(linha[5], "%d/%m/%Y %H:%M") < corte:
                        continue
                except ValueError:
                    pass
            filtradas.append(linha)
        return filtradas

    def atualizar_relatorio(self):
        if not hasattr(self, "tree_relatorio"):
            return
        linhas = self._linhas_relatorio_filtradas()
        entradas = sum(l[4] for l in linhas if l[1] == MOV_ENTRADA)
        saidas = sum(l[4] for l in linhas if l[1] == MOV_SAIDA)
        distintos = len({l[2] for l in linhas})
        for label, valor in zip(self.rel_valores, (entradas, saidas, distintos)):
            label.configure(text=f"{valor:,}".replace(",", "."))
        for item in self.tree_relatorio.get_children():
            self.tree_relatorio.delete(item)
        for linha in linhas:
            self.tree_relatorio.insert("", END, values=(linha[5], linha[1], linha[2], linha[3], linha[4]))

    def exportar_relatorio(self):
        linhas = self._linhas_relatorio_filtradas() if hasattr(self, "tree_relatorio") else self.db.buscar_historico()
        if not linhas:
            messagebox.showwarning("Sem dados", "Não há movimentações para exportar.")
            return
        caminho = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")], initialfile=f"relatorio_movimentacoes_{datetime.now():%d_%m_%Y}.csv")
        if caminho:
            with open(caminho, "w", newline="", encoding="utf-8-sig") as arquivo:
                writer = csv.writer(arquivo, delimiter=";")
                writer.writerow(["ID", "Tipo", "Produto", "Envolvido", "Quantidade", "Data/Hora"])
                writer.writerows(linhas)
            messagebox.showinfo("Relatório exportado", "O arquivo foi salvo com sucesso.")

    # ------------------------------------------------------------------
    # Usuários
    # ------------------------------------------------------------------
    def montar_usuarios(self):
        self._cabecalho_pagina("Usuários", "Gerencie os acessos e permissões do sistema", self.abrir_novo_usuario, "+ Novo Usuário")
        grade = ctk.CTkFrame(self.view_container, fg_color="transparent")
        grade.pack(fill=BOTH, expand=True)
        grade.grid_columnconfigure(0, weight=3)
        grade.grid_columnconfigure(1, weight=2)
        grade.grid_rowconfigure(0, weight=1)
        lista = self._card(grade)
        lista.grid(row=0, column=0, sticky="nsew", padx=(0, 9))
        ctk.CTkLabel(lista, text="Listagem de Usuários", text_color=COR["text"], font=(FONTE, 13, "bold")).pack(anchor="w", padx=16, pady=14)
        self.tree_usuarios = self._criar_tabela(lista, ["ID", "Usuário", "Perfil", "Financeiro", "Status"], [50, 160, 120, 95, 80], 11)
        self.tree_usuarios.bind("<<TreeviewSelect>>", self.selecionar_usuario)
        for usuario in self.db.listar_usuarios():
            self.tree_usuarios.insert("", END, values=(usuario[0], usuario[1], usuario[2].title(), "Sim" if usuario[3] else "Não", "● Ativo"))

        painel = self._card(grade)
        painel.grid(row=0, column=1, sticky="nsew", padx=(9, 0))
        self.lbl_usuario_permissoes = ctk.CTkLabel(painel, text="Selecione um usuário", text_color=COR["text"], font=(FONTE, 15, "bold"))
        self.lbl_usuario_permissoes.pack(anchor="w", padx=18, pady=(20, 4))
        ctk.CTkLabel(painel, text="Permissões de acesso", text_color=COR["muted"], font=(FONTE, 10)).pack(anchor="w", padx=18, pady=(0, 18))
        self.vars_permissoes = [ctk.IntVar(value=0) for _ in range(4)]
        nomes = ("Visualizar informações financeiras", "Cadastrar e editar produtos", "Registrar entradas", "Consultar histórico")
        self.checks_permissoes = []
        for nome, var in zip(nomes, self.vars_permissoes):
            check = ctk.CTkCheckBox(painel, text=nome, variable=var, onvalue=1, offvalue=0, text_color=COR["text"], fg_color=COR["primary"], hover_color=COR["primary_hover"], font=(FONTE, 10))
            check.pack(anchor="w", padx=18, pady=9)
            self.checks_permissoes.append(check)
        botoes = ctk.CTkFrame(painel, fg_color="transparent")
        botoes.pack(side="bottom", fill="x", padx=18, pady=18)
        self._botao_primario(botoes, "Salvar Alterações", self.salvar_permissoes_usuario, 150).pack(side=RIGHT)
        self._botao_secundario(botoes, "Senhas padrão", self.abrir_alterar_senhas, 125).pack(side=RIGHT, padx=8)
        primeiros = self.tree_usuarios.get_children()
        if primeiros:
            self.tree_usuarios.focus(primeiros[0])
            self.tree_usuarios.selection_set(primeiros[0])
            self.selecionar_usuario()

    def selecionar_usuario(self, _event=None):
        selecionado = self.tree_usuarios.focus()
        if not selecionado:
            return
        usuario_nome = self.tree_usuarios.item(selecionado, "values")[1]
        dados = next((u for u in self.db.listar_usuarios() if u[1] == usuario_nome), None)
        if not dados:
            return
        self.usuario_selecionado = usuario_nome
        self.lbl_usuario_permissoes.configure(text=usuario_nome)
        for var, valor in zip(self.vars_permissoes, dados[3:7]):
            var.set(valor)
        estado = "disabled" if dados[2] == "proprietario" else "normal"
        for check in self.checks_permissoes:
            check.configure(state=estado)

    def salvar_permissoes_usuario(self):
        if not self.usuario_selecionado:
            messagebox.showwarning("Seleção necessária", "Selecione um usuário.")
            return
        self.db.atualizar_permissoes_usuario(
            self.usuario_selecionado, *(var.get() for var in self.vars_permissoes)
        )
        messagebox.showinfo("Permissões atualizadas", "A matriz de acesso foi salva.")

    def abrir_novo_usuario(self):
        janela = ctk.CTkToplevel(self.root)
        janela.title("Novo Usuário")
        janela.geometry("440x480")
        janela.resizable(False, False)
        janela.configure(fg_color=COR["bg"])
        janela.transient(self.root)
        janela.grab_set()
        corpo = ctk.CTkFrame(janela, fg_color=COR["bg"])
        corpo.pack(fill=BOTH, expand=True, padx=28, pady=24)
        ctk.CTkLabel(corpo, text="Novo usuário", text_color=COR["text"], font=(FONTE, 20, "bold")).pack(anchor="w", pady=(0, 16))
        card = self._card(corpo)
        card.pack(fill=BOTH, expand=True)
        self._rotulo_campo(card, "USUÁRIO").pack(anchor="w", padx=16, pady=(18, 5))
        usuario = self._entrada(card, "Nome de acesso", 350)
        usuario.pack(padx=16)
        self._rotulo_campo(card, "SENHA INICIAL").pack(anchor="w", padx=16, pady=(14, 5))
        senha = self._entrada(card, "Senha", 350, show="•")
        senha.pack(padx=16)
        self._rotulo_campo(card, "PERFIL").pack(anchor="w", padx=16, pady=(14, 5))
        perfil = self._combo(card, ["funcionario", "proprietario"], 350)
        perfil.pack(padx=16)
        perfil.set("funcionario")
        historico = ctk.IntVar(value=1)
        ctk.CTkCheckBox(card, text="Permitir consulta ao histórico", variable=historico, fg_color=COR["primary"], text_color=COR["text"]).pack(anchor="w", padx=16, pady=18)

        def salvar():
            try:
                self.db.adicionar_usuario(usuario.get(), senha.get(), perfil.get(), p_his=historico.get())
            except DadosInvalidosError as exc:
                messagebox.showerror("Usuário inválido", str(exc), parent=janela)
                return
            janela.destroy()
            self.navegar("usuarios")

        self._botao_primario(corpo, "Criar Usuário", salvar, 130).pack(side=RIGHT, pady=(14, 0))
        self._botao_secundario(corpo, "Cancelar", janela.destroy, 95).pack(side=RIGHT, padx=8, pady=(14, 0))

    def abrir_alterar_senhas(self):
        janela = ctk.CTkToplevel(self.root)
        janela.title("Alterar Senhas")
        janela.geometry("420x340")
        janela.resizable(False, False)
        janela.configure(fg_color=COR["bg"])
        janela.transient(self.root)
        janela.grab_set()
        corpo = ctk.CTkFrame(janela, fg_color=COR["bg"])
        corpo.pack(fill=BOTH, expand=True, padx=28, pady=24)
        ctk.CTkLabel(corpo, text="Credenciais padrão", text_color=COR["text"], font=(FONTE, 20, "bold")).pack(anchor="w", pady=(0, 16))
        dono = self._entrada(corpo, "Nova senha do proprietário", 360, show="•")
        dono.pack(pady=7)
        caixa = self._entrada(corpo, "Nova senha do caixa", 360, show="•")
        caixa.pack(pady=7)
        def salvar():
            self.db.salvar_configuracoes(dono.get(), caixa.get(), *self.db.buscar_permissoes_caixa())
            janela.destroy()
            messagebox.showinfo("Senhas atualizadas", "As novas credenciais foram protegidas e salvas.")
        self._botao_primario(corpo, "Salvar Senhas", salvar, 130).pack(side=RIGHT, pady=18)
        self._botao_secundario(corpo, "Cancelar", janela.destroy, 95).pack(side=RIGHT, padx=8, pady=18)

    # ------------------------------------------------------------------
    # Backup e configurações
    # ------------------------------------------------------------------
    def montar_backup(self):
        self._cabecalho_pagina("Segurança de Dados", "Gerencie backups para garantir a recuperação do inventário")
        grade = ctk.CTkFrame(self.view_container, fg_color="transparent")
        grade.pack(fill="x")
        grade.grid_columnconfigure((0, 1), weight=1)
        backup = self._card(grade, height=390)
        backup.grid(row=0, column=0, sticky="nsew", padx=(0, 9))
        backup.grid_propagate(False)
        ctk.CTkLabel(backup, text="◈  BACKUP DO SISTEMA", text_color=COR["text"], font=(FONTE, 14, "bold")).pack(anchor="w", padx=22, pady=(24, 12))
        ctk.CTkLabel(backup, text="Crie uma cópia segura do estado atual do banco de dados.\nRecomendamos realizar esta ação regularmente.", justify="left", text_color=COR["muted"], font=(FONTE, 10)).pack(anchor="w", padx=22)
        caixa_info = ctk.CTkFrame(backup, fg_color="#F8FAFC", corner_radius=5)
        caixa_info.pack(fill="x", padx=22, pady=28)
        ctk.CTkLabel(caixa_info, text="O backup usa o mecanismo nativo do SQLite\ne passa por verificação de integridade.", justify="left", text_color=COR["muted"], font=(FONTE, 10)).pack(anchor="w", padx=16, pady=18)
        self._botao_primario(backup, "◈  Criar backup agora", self.fazer_backup, 220).pack(side="bottom", pady=22)

        restaurar = self._card(grade, height=390)
        restaurar.grid(row=0, column=1, sticky="nsew", padx=(9, 0))
        restaurar.grid_propagate(False)
        ctk.CTkLabel(restaurar, text="↻  RESTAURAR BACKUP", text_color=COR["text"], font=(FONTE, 14, "bold")).pack(anchor="w", padx=22, pady=(24, 12))
        ctk.CTkLabel(restaurar, text="Selecione um backup válido. Antes da restauração, o sistema\ncriará automaticamente uma cópia de segurança.", justify="left", text_color=COR["muted"], font=(FONTE, 10)).pack(anchor="w", padx=22)
        caixa_upload = ctk.CTkFrame(restaurar, fg_color="#FAFAFA", border_color="#CBD5E1", border_width=1, corner_radius=5, height=150)
        caixa_upload.pack(fill="x", padx=22, pady=24)
        caixa_upload.pack_propagate(False)
        ctk.CTkLabel(caixa_upload, text="▧", text_color=COR["muted"], font=(FONTE, 28)).pack(pady=(30, 5))
        ctk.CTkLabel(caixa_upload, text="Selecione um arquivo .db", text_color=COR["muted"], font=(FONTE, 10)).pack()
        self._botao_secundario(restaurar, "Simular / Restaurar", self.restaurar_backup, 180).pack(side="bottom", pady=22)

    def fazer_backup(self):
        caminho = filedialog.asksaveasfilename(defaultextension=".db", filetypes=[("Banco de Dados", "*.db")], initialfile=f"backup_estoque_{datetime.now():%d_%m_%Y}.db")
        if not caminho:
            return
        try:
            self.db.criar_backup(caminho)
        except (OSError, DadosInvalidosError, BackupInvalidoError) as exc:
            messagebox.showerror("Falha no backup", str(exc))
            return
        messagebox.showinfo("Backup concluído", "O arquivo foi validado e salvo com sucesso.")

    def restaurar_backup(self):
        caminho = filedialog.askopenfilename(filetypes=[("Banco de Dados", "*.db")])
        if not caminho:
            return
        if not messagebox.askyesno("Restaurar backup", "A base atual será substituída após a criação de uma cópia de segurança. Continuar?"):
            return
        try:
            seguranca = self.db.restaurar_backup(caminho)
        except (OSError, DadosInvalidosError, BackupInvalidoError, MigracaoError) as exc:
            messagebox.showerror("Restauração não realizada", str(exc))
            return
        messagebox.showinfo("Restauração concluída", f"Base restaurada. Cópia anterior: {seguranca}")
        self.navegar("dashboard")

    def montar_configuracoes(self):
        self._cabecalho_pagina("Configurações", "Preferências gerais da aplicação")
        card = self._card(self.view_container, width=620, height=260)
        card.pack(anchor="nw")
        card.pack_propagate(False)
        ctk.CTkLabel(card, text="Aparência da Interface", text_color=COR["text"], font=(FONTE, 15, "bold")).pack(anchor="w", padx=22, pady=(22, 6))
        ctk.CTkLabel(card, text="O layout Modern Stock Manager foi otimizado para o modo claro.", text_color=COR["muted"], font=(FONTE, 10)).pack(anchor="w", padx=22)
        tema_atual = "Light"
        if os.path.exists(ARQUIVO_TEMA):
            tema_atual = Path(ARQUIVO_TEMA).read_text(encoding="utf-8").strip() or "Light"
        combo = self._combo(card, ["Light", "System", "Dark"], 250, self.mudar_tema)
        combo.set(tema_atual)
        combo.pack(anchor="w", padx=22, pady=22)
        ctk.CTkLabel(card, text="As cores estruturais permanecem fiéis ao projeto Stitch.", text_color=COR["subtle"], font=(FONTE, 9)).pack(anchor="w", padx=22)

    def mudar_tema(self, escolha):
        ctk.set_appearance_mode(escolha)
        Path(ARQUIVO_TEMA).write_text(escolha, encoding="utf-8")

    # Compatibilidade com chamadas antigas.
    def exportar_excel(self):
        if not self.permissoes.get("ver_financeiro"):
            messagebox.showwarning("Acesso restrito", "Seu perfil não pode exportar dados financeiros.")
            return
        linhas = self.db.buscar_produtos()
        if not linhas:
            messagebox.showwarning("Base vazia", "Não existem produtos para exportação.")
            return
        caminho = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")], initialfile=f"relatorio_estoque_{datetime.now():%d_%m_%Y}.csv")
        if caminho:
            with open(caminho, "w", newline="", encoding="utf-8-sig") as arquivo:
                writer = csv.writer(arquivo, delimiter=";")
                writer.writerow(["ID", "Código", "Nome", "Categoria", "Tamanho", "Cor", "Qtd", "Preço"])
                writer.writerows(linhas)
            messagebox.showinfo("Exportação concluída", "Os dados foram salvos com sucesso.")
