# Inovatech OS

Sistema de gerenciamento de Ordens de Serviço com geração de QR Code.  
Conecta diretamente ao banco de dados Firebird do ERP (DADOS5.FDB).

---

## Pré-requisitos

- Python 3.10 ou superior
- Acesso ao arquivo `DADOS5.FDB` (via servidor Firebird já instalado na rede **ou** via Docker)

---

## Instalação

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Copie o arquivo de exemplo e edite conforme o seu ambiente:

```bat
copy .env.example .env
```

---

## Variáveis de ambiente (`.env`)

| Variável | Descrição | Exemplo |
|---|---|---|
| `FIREBIRD_HOST` | IP ou hostname do servidor Firebird | `localhost` ou `192.168.1.10` |
| `FIREBIRD_PORT` | Porta do servidor Firebird | `3050` |
| `FIREBIRD_FILE` | Caminho do arquivo `.fdb` **como visto pelo servidor Firebird** | `/data/DADOS5.FDB` |
| `FIREBIRD_USER` | Usuário do banco | `SYSDBA` |
| `FIREBIRD_PASSWORD` | Senha do banco | `masterkey` |
| `FRONTEND_URL` | URL base usada nos QR Codes | `http://localhost:5050` |
| `SECRET_KEY` | Chave de sessão | qualquer string aleatória |
| `PORT` | Porta do servidor web | `5050` |

> **Atenção:** `FIREBIRD_FILE` deve ser o caminho do arquivo `.fdb` como o **servidor Firebird enxerga**, não o caminho do Windows na sua máquina.  
> Exemplo: se o ERP roda no servidor `192.168.1.10` e o arquivo fica em `C:\ERP\DADOS5.FDB` nesse servidor, o valor correto é `C:/ERP/DADOS5.FDB`.  
> Se você usar Docker localmente, o caminho é `/data/DADOS5.FDB` (veja seção abaixo).

---

## Executar

```bat
.\.venv\Scripts\activate

python main.py
```

Acesse [http://localhost:5050](http://localhost:5050)

---

## Instalação do Firebird (opcional)

Pule esta seção se o Firebird já estiver instalado no seu computador ou acessível na rede.

### Opção A — Docker (recomendado para desenvolvimento local)

> Requer [Docker Desktop para Windows](https://www.docker.com/products/docker-desktop/).

```bat
docker run -d --name firebird-dados5 --restart unless-stopped -e ISC_PASSWORD=masterkey -v "C:/Users/Exemplo/Downloads/DADOS5:/data" -p 3050:3050 jacobalberty/firebird:2.5-ss
```

Ajuste o caminho `C:/Users/Exemplo/Downloads/DADOS5` para a pasta onde está o arquivo `DADOS5.FDB`.

Use a tag `2.5-ss` — o banco é ODS 11.2 (Firebird 2.5) e **não abre** com versões mais novas do Firebird.

No `.env`, use:

```
FIREBIRD_HOST=localhost
FIREBIRD_FILE=/data/DADOS5.FDB
```

Para parar/iniciar o container:

```bat
docker stop firebird-dados5
docker start firebird-dados5
```

### Opção B — Firebird instalado diretamente no Windows

Baixe o instalador do [Firebird 2.5](https://firebirdsql.org/en/firebird-2-5/) (versão SuperServer para Windows).

Após instalar, configure o `.env` com o caminho real do arquivo no servidor:

```
FIREBIRD_HOST=localhost
FIREBIRD_FILE=C:/caminho/para/DADOS5.FDB
```

