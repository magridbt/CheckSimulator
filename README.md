# CheckSimulator

**Motor de Inteligencia de Enxame — Simule o Futuro**

Plataforma de previsao baseada em simulacao multi-agente. Cria mundos digitais paralelos povoados por milhares de agentes autonomos, cada um com personalidade, memoria e logica comportamental propria, para prever tendencias, testar hipoteses e simular dinamicas sociais.

> Baseado no projeto [MiroFish](https://github.com/666ghj/MiroFish) (AGPL-3.0)

---

## Como funciona

1. **Voce alimenta** com dados reais (noticias, relatorios, narrativas, PDFs, TXTs, MDs)
2. **O sistema constroi** um grafo de conhecimento (GraphRAG) e gera perfis de agentes
3. **Milhares de agentes** interagem autonomamente em plataformas simuladas (Twitter + Reddit)
4. **Comportamentos emergentes** surgem das interacoes coletivas
5. **Voce recebe** um relatorio detalhado e pode conversar com qualquer agente

---

## Fluxo de Trabalho (5 Passos)

| Passo | Nome | Descricao |
|-------|------|-----------|
| 1 | **Construcao do Grafo** | Upload de documentos → LLM gera ontologia → Zep constroi GraphRAG com entidades e relacoes |
| 2 | **Configuracao do Ambiente** | Leitura de entidades do grafo → Geracao de perfis de agentes → Config de simulacao (tempo, frequencia, eventos) |
| 3 | **Simulacao** | Execucao paralela em duas plataformas (Twitter + Reddit) com agentes autonomos interagindo |
| 4 | **Geracao de Relatorio** | Report Agent usa padrao ReACT (pensamento + ferramentas Zep) para gerar analise detalhada |
| 5 | **Interacao Profunda** | Conversar diretamente com agentes simulados ou com o Report Agent |

---

## Stack Tecnica

| Camada | Tecnologia |
|--------|------------|
| **Frontend** | Vue 3 + Vite |
| **Backend** | Python 3.12 + Flask |
| **LLM** | OpenAI API (gpt-4o-mini) via OpenAI SDK |
| **Memoria** | Zep Cloud (memoria persistente dos agentes + GraphRAG) |
| **Simulacao** | OASIS by CAMEL-AI (dual platform: Twitter + Reddit) |
| **Processamento** | PyMuPDF (PDF), charset-normalizer (encoding), tiktoken (tokenizacao) |

---

## Inicio Rapido

### Pre-requisitos

| Ferramenta | Versao | Verificar |
|-----------|--------|-----------|
| Node.js | >= 18 | `node -v` |
| Python | 3.11 ou 3.12 | `python --version` |
| uv | ultima | `uv --version` |
| Rust | ultima | `rustc --version` |

### 1. Clonar e configurar

```bash
git clone https://github.com/magridbt/CheckSimulator.git
cd CheckSimulator
cp .env.example .env
```

### 2. Editar `.env`

```env
# LLM (OpenAI ou qualquer API compativel com OpenAI SDK)
LLM_API_KEY=sk-sua-chave-aqui
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL_NAME=gpt-4o-mini

# Zep Cloud (memoria dos agentes)
# Criar conta gratis em: https://app.getzep.com/
ZEP_API_KEY=z_sua-chave-aqui
```

### 3. Instalar dependencias

```bash
npm run setup:all
```

### 4. Rodar

```bash
npm run dev
```

| Servico | URL |
|---------|-----|
| Frontend | http://localhost:3000 |
| Backend API | http://localhost:5001 |

### Docker (alternativa)

```bash
cp .env.example .env
# Editar .env com suas chaves
docker compose up -d
```

---

## Comandos Disponiveis

| Comando | Descricao |
|---------|-----------|
| `npm run setup:all` | Instala todas as dependencias (Node + Python) |
| `npm run setup` | Instala apenas dependencias Node (root + frontend) |
| `npm run setup:backend` | Instala apenas dependencias Python (backend) |
| `npm run dev` | Inicia frontend + backend simultaneamente |
| `npm run frontend` | Inicia apenas o frontend |
| `npm run backend` | Inicia apenas o backend |
| `npm run build` | Build do frontend para producao |

---

## Estrutura do Projeto

```
CheckSimulator/
├── frontend/                    # Vue 3 + Vite (porta :3000)
│   ├── index.html               # Entry HTML (lang pt-BR)
│   └── src/
│       ├── views/               # Paginas principais
│       │   ├── Home.vue         # Tela inicial (upload + prompt)
│       │   ├── Process.vue      # Orquestrador dos 5 passos
│       │   ├── SimulationView.vue
│       │   ├── SimulationRunView.vue
│       │   ├── ReportView.vue
│       │   └── InteractionView.vue
│       ├── components/          # Componentes reutilizaveis
│       │   ├── Step1GraphBuild.vue    # Passo 1: Ontologia + GraphRAG
│       │   ├── Step2EnvSetup.vue      # Passo 2: Perfis + Config
│       │   ├── Step3Simulation.vue    # Passo 3: Simulacao
│       │   ├── Step4Report.vue        # Passo 4: Relatorio
│       │   ├── Step5Interaction.vue   # Passo 5: Interacao
│       │   ├── GraphPanel.vue         # Visualizacao do grafo
│       │   └── HistoryDatabase.vue    # Historico de simulacoes
│       ├── api/                 # Chamadas API (axios)
│       │   ├── graph.js         # Endpoints de grafo
│       │   ├── simulation.js    # Endpoints de simulacao
│       │   └── report.js        # Endpoints de relatorio
│       └── store/               # Estado reativo
│           └── pendingUpload.js
│
├── backend/                     # Python 3.12 + Flask (porta :5001)
│   ├── run.py                   # Entry point
│   └── app/
│       ├── __init__.py          # Flask app factory
│       ├── config.py            # Configuracao (env vars)
│       ├── api/                 # Rotas da API
│       │   ├── graph.py         # /api/graph/* (ontologia, construcao, dados)
│       │   ├── simulation.py    # /api/simulation/* (criar, preparar, rodar, status)
│       │   └── report.py        # /api/report/* (gerar, status, chat)
│       ├── services/            # Logica de negocio
│       │   ├── ontology_generator.py       # LLM gera ontologia dos documentos
│       │   ├── graph_builder.py            # Constroi grafo Zep (GraphRAG)
│       │   ├── text_processor.py           # Extrai texto de PDF/MD/TXT
│       │   ├── zep_entity_reader.py        # Le entidades do grafo Zep
│       │   ├── oasis_profile_generator.py  # Gera perfis de agentes OASIS
│       │   ├── simulation_config_generator.py # LLM gera config de simulacao
│       │   ├── simulation_manager.py       # Ciclo de vida da simulacao
│       │   ├── simulation_runner.py        # Executa simulacao OASIS
│       │   ├── simulation_ipc.py           # Comunicacao inter-processos
│       │   ├── zep_graph_memory_updater.py # Atualiza memoria durante simulacao
│       │   ├── zep_tools.py                # Ferramentas Zep p/ Report Agent
│       │   └── report_agent.py             # Gera relatorio (padrao ReACT)
│       ├── models/              # Modelos de dados
│       │   ├── project.py       # Projeto (upload, status, metadata)
│       │   └── task.py          # Tarefas assincronas (progresso, resultado)
│       └── utils/               # Utilitarios
│           ├── logger.py        # Logging unificado (console + arquivo)
│           ├── llm_client.py    # Cliente OpenAI SDK
│           ├── file_parser.py   # Parser de PDF/MD/TXT
│           ├── retry.py         # Retry com backoff exponencial
│           └── zep_paging.py    # Paginacao para API Zep
│
├── docs/                        # Documentacao detalhada
│   ├── architecture.md          # Arquitetura do sistema
│   ├── api-reference.md         # Referencia da API REST
│   ├── workflow.md              # Fluxo detalhado dos 5 passos
│   └── configuration.md         # Configuracao e variaveis de ambiente
│
├── .env.example                 # Template de variaveis de ambiente
├── docker-compose.yml           # Deploy com Docker
├── package.json                 # Scripts npm (root)
├── CLAUDE.md                    # Documentacao para Claude Code
└── README.md                    # Este arquivo
```

---

## Variaveis de Ambiente

| Variavel | Obrigatoria | Descricao |
|----------|-------------|-----------|
| `LLM_API_KEY` | Sim | Chave da API do LLM (OpenAI, Qwen, etc.) |
| `LLM_BASE_URL` | Sim | URL base da API (`https://api.openai.com/v1`) |
| `LLM_MODEL_NAME` | Sim | Modelo a usar (`gpt-4o-mini`) |
| `ZEP_API_KEY` | Sim | Chave do Zep Cloud |
| `LLM_BOOST_API_KEY` | Nao | LLM secundario para acelerar geracao |
| `LLM_BOOST_BASE_URL` | Nao | URL do LLM secundario |
| `LLM_BOOST_MODEL_NAME` | Nao | Modelo do LLM secundario |

---

## Casos de Uso

- **Previsao de tendencias** — Alimentar com dados de mercado e simular comportamento do consumidor
- **Teste de politicas** — Simular reacao publica a novas politicas antes de implementar
- **Analise de opiniao** — Prever como diferentes grupos reagem a eventos ou controversias
- **Cenarios financeiros** — Simular impacto de decisoes economicas no comportamento de investidores
- **Narrativas criativas** — Testar desfechos alternativos de historias ou cenarios ficticios
- **Marketing e lancamentos** — Simular recepcao de produtos antes de lancar

---

## Creditos

- Baseado em [MiroFish](https://github.com/666ghj/MiroFish) por 666ghj (suporte estrategico da Shanda Group)
- Motor de simulacao: [OASIS](https://github.com/camel-ai/oasis) por CAMEL-AI
- Memoria e grafos: [Zep](https://www.getzep.com/)

## Licenca

AGPL-3.0 (herdada do MiroFish)
