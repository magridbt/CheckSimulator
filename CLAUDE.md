# CheckSimulator

Motor de Inteligencia de Enxame para simulacao de cenarios futuros com agentes autonomos.

## O que faz

Cria mundos digitais paralelos povoados por milhares de agentes autonomos (cada um com personalidade, memoria e logica comportamental propria) para prever tendencias, testar hipoteses e simular dinamicas sociais. Baseado no projeto MiroFish.

## Stack

- **Frontend:** Vue 3 + Vite (porta :3000)
- **Backend:** Python 3.12 + Flask (porta :5001)
- **LLM:** OpenAI API (gpt-4o-mini) via OpenAI SDK
- **Memoria:** Zep Cloud (memoria persistente dos agentes)
- **Simulacao:** OASIS (CAMEL-AI) — dual platform (Twitter + Reddit)
- **Grafo:** Zep GraphRAG (construcao automatica de grafos de conhecimento)

## Estrutura

```
CheckSimulator/
  frontend/           # Vue 3 + Vite
    src/
      views/          # Home, Process, SimulationView, SimulationRunView, ReportView, InteractionView
      components/     # Step1-5, GraphPanel, HistoryDatabase
      api/            # graph.js, simulation.js, report.js
      store/          # pendingUpload.js
  backend/            # Python Flask
    run.py            # Entry point
    app/
      __init__.py     # Flask app factory
      config.py       # Config (env vars)
      api/            # Routes: graph.py, simulation.py, report.py
      services/       # Core logic:
        ontology_generator.py       # LLM gera ontologia a partir dos documentos
        graph_builder.py            # Constroi grafo Zep com entidades e relacoes
        text_processor.py           # Extrai e processa texto dos documentos
        zep_entity_reader.py        # Le e filtra entidades do grafo Zep
        oasis_profile_generator.py  # Gera perfis de agentes para simulacao OASIS
        simulation_config_generator.py  # LLM gera configuracao de simulacao
        simulation_manager.py       # Gerencia ciclo de vida da simulacao
        simulation_runner.py        # Executa simulacao OASIS (Twitter/Reddit)
        simulation_ipc.py           # Comunicacao inter-processos da simulacao
        zep_graph_memory_updater.py # Atualiza memoria do grafo durante simulacao
        zep_tools.py                # Ferramentas Zep para o Report Agent
        report_agent.py             # Gera relatorio com ReACT (pensamento + ferramentas)
      models/         # project.py, task.py
      utils/          # logger.py, llm_client.py, file_parser.py, retry.py, zep_paging.py
```

## Fluxo de trabalho (5 passos)

1. **Construcao do Grafo** — Upload de documentos + LLM gera ontologia + Zep constroi GraphRAG
2. **Configuracao do Ambiente** — Leitura de entidades + geracao de perfis de agentes + config de simulacao
3. **Simulacao** — Execucao paralela em duas plataformas (Twitter + Reddit) com agentes autonomos
4. **Geracao de Relatorio** — Report Agent usa ReACT com ferramentas Zep para gerar analise
5. **Interacao Profunda** — Conversar com agentes simulados ou com o Report Agent

## Comandos

```bash
# Instalar tudo
npm run setup:all

# Rodar (frontend + backend)
npm run dev

# Build frontend
npm run build

# Apenas backend
npm run backend

# Apenas frontend
npm run frontend
```

## Variaveis de ambiente (.env na raiz)

```env
# LLM (OpenAI)
LLM_API_KEY=sk-...
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL_NAME=gpt-4o-mini

# Zep Cloud (memoria dos agentes)
ZEP_API_KEY=z_...

# Opcional: LLM secundario para acelerar
LLM_BOOST_API_KEY=
LLM_BOOST_BASE_URL=
LLM_BOOST_MODEL_NAME=
```

## Requisitos

- Node.js >= 18
- Python 3.11-3.12 (nao 3.13 — pillow incompativel)
- uv (gerenciador Python)
- Rust compiler (para tiktoken)

## Portas

| Servico  | Porta |
|----------|-------|
| Frontend | 3000  |
| Backend  | 5001  |

## GitHub

- **Repo:** https://github.com/magridbt/CheckSimulator
- **Upstream:** 666ghj/MiroFish
- **Licenca:** AGPL-3.0

## Notas

- Idioma: Toda a UI e comentarios em PT-BR
- Strings funcionais (regex parsing, prompts OASIS) mantidas em chines por compatibilidade
- O backend usa Flask com threads para tarefas longas (construcao de grafo, simulacao)
- Simulacoes podem consumir muitos tokens — monitorar uso da API
- Zep Cloud tem free tier suficiente para testes
