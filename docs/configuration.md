# Configuracao e Variaveis de Ambiente

## Arquivo `.env`

O arquivo `.env` fica na **raiz do projeto** e e lido tanto pelo backend quanto pelo Docker.

```bash
cp .env.example .env
```

---

## Variaveis Obrigatorias

### LLM_API_KEY
Chave de autenticacao da API do LLM.

```env
LLM_API_KEY=sk-proj-xxxxx
```

**Provedores suportados** (qualquer API compativel com OpenAI SDK):
| Provedor | Base URL | Modelos recomendados |
|----------|----------|---------------------|
| OpenAI | `https://api.openai.com/v1` | gpt-4o-mini, gpt-4o |
| Alibaba Qwen | `https://dashscope.aliyuncs.com/compatible-mode/v1` | qwen-plus |
| DeepSeek | `https://api.deepseek.com/v1` | deepseek-chat |

### LLM_BASE_URL
URL base da API do LLM.

```env
LLM_BASE_URL=https://api.openai.com/v1
```

### LLM_MODEL_NAME
Nome do modelo a utilizar.

```env
LLM_MODEL_NAME=gpt-4o-mini
```

### ZEP_API_KEY
Chave do Zep Cloud para GraphRAG e memoria dos agentes.

```env
ZEP_API_KEY=z_xxxxx
```

**Como obter:**
1. Acesse https://app.getzep.com/
2. Crie uma conta (free tier disponivel)
3. Copie a API key do dashboard

---

## Variaveis Opcionais

### LLM Boost (acelerador)
LLM secundario para paralelizar geracao de conteudo.

```env
LLM_BOOST_API_KEY=sk-xxxxx
LLM_BOOST_BASE_URL=https://api.openai.com/v1
LLM_BOOST_MODEL_NAME=gpt-4o-mini
```

Se nao configurado, o sistema usa apenas o LLM principal.

---

## Configuracoes Internas (config.py)

Estas configuracoes sao definidas no codigo e podem ser ajustadas editando `backend/app/config.py`:

### Upload de Arquivos
| Config | Default | Descricao |
|--------|---------|-----------|
| `MAX_CONTENT_LENGTH` | 50 MB | Tamanho maximo de upload |
| `ALLOWED_EXTENSIONS` | pdf, md, txt, markdown | Formatos aceitos |

### Processamento de Texto
| Config | Default | Descricao |
|--------|---------|-----------|
| `DEFAULT_CHUNK_SIZE` | 500 chars | Tamanho dos blocos de texto |
| `DEFAULT_CHUNK_OVERLAP` | 50 chars | Sobreposicao entre blocos |

### Simulacao OASIS
| Config | Default | Descricao |
|--------|---------|-----------|
| `OASIS_DEFAULT_MAX_ROUNDS` | 10 | Rodadas maximas de simulacao |
| `OASIS_TWITTER_ACTIONS` | CREATE_POST, LIKE_POST, REPOST, FOLLOW, DO_NOTHING, QUOTE_POST | Acoes no Twitter |
| `OASIS_REDDIT_ACTIONS` | LIKE_POST, DISLIKE_POST, CREATE_POST, CREATE_COMMENT, ... | Acoes no Reddit |

### Report Agent
| Config | Default | Descricao |
|--------|---------|-----------|
| `REPORT_AGENT_MAX_TOOL_CALLS` | 5 | Max chamadas de ferramenta por secao |
| `REPORT_AGENT_MAX_REFLECTION_ROUNDS` | 2 | Max rodadas de reflexao |
| `REPORT_AGENT_TEMPERATURE` | 0.5 | Temperatura do LLM para relatorio |

---

## Portas

| Servico | Porta | Configuravel em |
|---------|-------|-----------------|
| Frontend (Vite) | 3000 | `frontend/vite.config.js` |
| Backend (Flask) | 5001 | `backend/run.py` |

---

## Armazenamento Local

O backend armazena dados em disco:

```
backend/
├── uploads/                      # Raiz de armazenamento
│   ├── {project_id}/             # Dados de cada projeto
│   │   ├── files/                # Documentos enviados
│   │   ├── extracted_text.txt    # Texto extraido
│   │   └── metadata.json         # Metadata do projeto
│   └── simulations/              # Dados de simulacao
│       └── {simulation_id}/
│           ├── profiles/         # Perfis de agentes (JSON)
│           ├── config/           # Configuracao de simulacao
│           ├── scripts/          # Scripts OASIS
│           ├── report/           # Relatorio gerado
│           └── state.json        # Estado da simulacao
└── logs/                         # Logs do sistema
    └── checksimulator_YYYY-MM-DD.log
```

---

## Consumo de Tokens

A simulacao consome tokens do LLM em varias etapas:

| Etapa | Consumo estimado |
|-------|-----------------|
| Geracao de ontologia | ~2K tokens |
| Geracao de perfis (por agente) | ~1-2K tokens |
| Geracao de config | ~3K tokens |
| Simulacao (por rodada, por agente) | ~500-1K tokens |
| Relatorio | ~5-10K tokens |
| Chat | ~500-1K tokens por mensagem |

**Estimativa total** para simulacao com 20 agentes, 10 rodadas:
- ~50K-100K tokens (input + output)
- Custo com gpt-4o-mini: ~$0.05-0.15

**Dica:** Comece com simulacoes pequenas (< 40 rodadas) para calibrar custos.

---

## Docker

O `docker-compose.yml` ja esta configurado:

```yaml
services:
  checksimulator:
    image: ghcr.io/666ghj/mirofish:latest
    env_file:
      - .env
    ports:
      - "3000:3000"
      - "5001:5001"
    volumes:
      - ./backend/uploads:/app/backend/uploads
```

**Nota:** A imagem Docker ainda usa o nome original MiroFish. Para build local customizado, use o `Dockerfile` na raiz.

---

## Troubleshooting

### Python 3.13 nao funciona
O `pillow 10.3.0` (dependencia do OASIS) nao compila no Python 3.13. Use Python 3.11 ou 3.12:
```bash
uv python install 3.12
uv python pin 3.12
```

### Rust compiler necessario
O `tiktoken` precisa de Rust para compilar:
```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
```

### Zep rate limit
Se receber erros 429 do Zep, aguarde alguns segundos. O sistema tem retry automatico com backoff.

### LLM retorna JSON invalido
O `llm_client.py` limpa automaticamente markdown code fences e tags `<think>`. Se persistir, tente outro modelo.
