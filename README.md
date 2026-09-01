# 📦 Sistema Desktop de Controle de Estoque e Vendas

Uma aplicação desktop desenvolvida em **Python**, utilizando **CustomTkinter** para uma interface moderna e **SQLite3** para armazenamento de dados local. Projetada para controle de inventário e operação de caixa no comércio varejista.

---

## 🚀 Destaques da Aplicação

- **🎨 Interface Moderna & Temas**: Suporte a modo Claro (*Light*), Escuro (*Dark*) e Automático (*System*), mantendo a preferência salva localmente.
- **🔐 Autenticação & Permissões por Perfil**:
  - **Proprietário**: Acesso total a configurações, gestão de usuários, relatórios e controle financeiro.
  - **Caixa**: Permissões personalizáveis diretamente pelo painel administrativo.
- **⚡ Alta Eficiência no Atendimento**:
  - Validação em tempo real (bloqueio de caracteres inválidos nos campos numéricos de preço e quantidade).
  - Atalhos de teclado (`Enter`) integrados na busca e na confirmação de movimentações (pronto para leitor de código de barras).
- **📊 Alerta Visual de Estoque**: Destaque automático em vermelho para produtos com quantidade igual ou inferior a 5 unidades.
- **📄 Histórico de Movimentações**: Registro visual colorido diferenciando **Entradas** (Verde) e **Saídas/Vendas** (Vermelho).
- **📊 Exportação de Dados**: Geração de relatórios em formato `.csv` (compatível com Microsoft Excel e codificado em UTF-8 com BOM para preservar acentuação).
- **💾 Gestão de Backup**: Módulo integrado para backup e restauração do banco de dados SQLite com tratamento amigável de erros do sistema operacional.

---

## 🛠️ Arquitetura do Projeto

```text
├── main.py        # Ponto de entrada da aplicação e inicialização do tema
├── interface.py   # Camada de apresentação (UI/UX) construída com CustomTkinter
└── banco.py       # Camada de dados e regras de negócio usando SQLite3
```

---

## ⚙️ Como Executar o Projeto

### Pré-requisitos
- Python 3.10 ou superior instalado.

### Passo a Passo
1. Clone este repositório:
   ```bash
   git clone https://github.com/Rfperuzzo/Estoque_de_roupa.git
   cd Estoque_de_roupa
   ```
2. Crie e ative um ambiente virtual:
   ```bash
   python -m venv .venv
   # Windows PowerShell
   .venv\Scripts\Activate.ps1
   ```
3. Instale a aplicação:
   ```bash
   python -m pip install -e .
   ```
4. Inicie o sistema a partir do arquivo principal:
   ```bash
   python main.py
   ```

---

## 🔐 Credenciais Padrão (Primeiro Acesso)

Ao iniciar o sistema pela primeira vez, o banco de dados é criado automaticamente com as seguintes credenciais de teste:

| Usuário | Senha | Perfil |
| :--- | :--- | :--- |
| `dono` | `123` | Proprietário (Acesso Total) |
| `caixa` | `123` | Operador de Caixa |

*As senhas podem ser alteradas dentro do menu de Configurações.*

---

## 🧪 Testes

Instale as dependências de desenvolvimento e execute a suíte:

```bash
python -m pip install -e ".[dev]"
python -m pytest
```

Os testes usam bancos temporários e não modificam o arquivo `estoque.db` da aplicação.

---

## Executável para Windows

Instale as dependências de build e execute o PyInstaller:

```powershell
python -m pip install -e ".[build]"
python -m PyInstaller --noconfirm --clean EstoqueDeRoupas.spec
```

O executável será criado em `dist/EstoqueDeRoupas.exe`. O banco de dados e a
preferência de tema são mantidos no mesmo diretório do executável.

---

## 🔄 Migração e Segurança dos Dados

- Bases criadas por versões anteriores são migradas automaticamente na primeira abertura.
- Antes da migração, o sistema cria um arquivo `*.pre_migracao_*.db` ao lado da base original.
- Preços passam a ser armazenados em centavos inteiros, evitando erros de arredondamento no SQLite.
- Senhas novas são protegidas com PBKDF2. Senhas legadas são convertidas após o primeiro login válido.
- Se forem encontrados dados incompatíveis, a migração é interrompida e a base original permanece intacta.
