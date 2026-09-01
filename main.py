"""
Ponto de entrada (Entry Point) da aplicação de Controle de Estoque.
Responsável por inicializar as configurações globais de interface e instanciar a aplicação.
"""
import customtkinter as ctk
from interface import SistemaEstoqueApp
import os
import sys
from pathlib import Path

# Constante para o arquivo de configuração de tema
ARQUIVO_TEMA = "tema.txt"


def configurar_diretorio_da_aplicacao():
    """Mantém banco e preferências ao lado do programa, inclusive congelado."""
    if getattr(sys, "frozen", False):
        diretorio = Path(sys.executable).resolve().parent
    else:
        diretorio = Path(__file__).resolve().parent
    os.chdir(diretorio)

if __name__ == "__main__":
    configurar_diretorio_da_aplicacao()
    tema_atual = "System"
    
    # Recupera a preferência de tema salva localmente
    if os.path.exists(ARQUIVO_TEMA):
        with open(ARQUIVO_TEMA, "r") as arquivo:
            tema_atual = arquivo.read().strip()

    # Configurações iniciais do CustomTkinter
    ctk.set_appearance_mode(tema_atual)
    ctk.set_default_color_theme("blue")
    
    # Instancia e executa o loop principal da interface gráfica
    root = ctk.CTk()
    app = SistemaEstoqueApp(root)
    root.mainloop()
