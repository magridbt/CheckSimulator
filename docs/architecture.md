# Arquitetura do Sistema

## Visao Geral

O CheckSimulator segue uma arquitetura **cliente-servidor** com frontend Vue e backend Flask, conectados por API REST. O backend orquestra chamadas a LLM (OpenAI), Zep Cloud (GraphRAG + memoria) e OASIS (simulacao multi-agente).

```
┌─────────────────────────────────────────────────────────┐
│                    USUARIO (Browser)                     │
│                   http://localhost:3000                   │
└──────────────────────────┬──────────────────────────────┘
                           │ HTTP/REST
                           ▼
┌─────────────────────────────────────────────────────────┐
│                  BACKEND (Flask :5001)                    │
│                                                          │
│  ┌──────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │ API      │  │  Services    │  │    Models/Utils    │  │
│  │ Routes   │──│  (logica)    │──│  (dados/helpers)   │  │
│  └──────────┘  └──────┬───────┘  └───────────────────┘  │
│                        │                                  │
└────────────────────────┼──────────────────────────────────┘
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
   ┌──────────┐   ┌──────────┐   ┌──────────┐
   │ OpenAI   │   │ Zep Cloud│   │  OASIS   │
   │ API      │   │ (GraphRAG│   │ (CAMEL-  │
   │ (LLM)   │   │ +Memoria)│   │  AI)     │
   └──────────┘   └──────────┘   └──────────┘
```

## Camadas

### 1. Frontend (Vue 3 + Vite)

**Responsabilidades:**
- Interface do usuario (upload de arquivos, configuracao, visualizacao)
- Visualizacao do grafo de conhecimento em tempo real
- Monitoramento do progresso da simulacao
- Exibicao do relatorio gerado
- Interface de chat com agentes

**Fluxo de dados:**
- Todas as chamadas passam pela camada `api/` (axios)
- Estado reativo via Vue 3 Composition API
- Polling para acompanhar tarefas assincronas (construcao de grafo, simulacao)

### 2. Backend (Flask)

**Camada API (`app/api/`):**
- `graph.py` — Upload de documentos, geracao de ontologia, construcao do grafo, consulta de dados
- `simulation.py` — Criar, preparar, iniciar, monitorar e parar simulacoes
- `report.py` — Gerar relatorio, consultar status, chat com Report Agent

**Camada de Servicos (`app/services/`):**

| Servico | Funcao |
|---------|--------|
| `ontology_generator` | Usa LLM para analisar documentos e gerar ontologia (10 tipos de entidade + relacoes) |
| `graph_builder` | Constroi grafo Zep: cria grafo, define ontologia, adiciona texto em blocos, aguarda processamento |
| `text_processor` | Extrai e processa texto de PDF/MD/TXT com deteccao automatica de encoding |
| `zep_entity_reader` | Le todos os nos do grafo Zep e filtra por tipos de entidade validos |
| `oasis_profile_generator` | Gera perfis detalhados de agentes (personalidade, bio, comportamento) para OASIS |
| `simulation_config_generator` | LLM gera configuracao completa: tempo, eventos, frequencia, atividade por agente |
| `simulation_manager` | Orquestra todo o ciclo: leitura de entidades → perfis → config → scripts → execucao |
| `simulation_runner` | Executa simulacao OASIS em processo separado (Twitter + Reddit paralelos) |
| `simulation_ipc` | Comunicacao inter-processos entre Flask e processo OASIS |
| `zep_graph_memory_updater` | Atualiza memoria do grafo com acoes dos agentes durante simulacao |
| `zep_tools` | Ferramentas que o Report Agent usa para consultar grafo, entrevistar agentes, buscar posts |
| `report_agent` | Gera relatorio usando padrao ReACT (pensamento → ferramenta → reflexao → escrita) |

### 3. Servicos Externos

**OpenAI API:**
- Geracao de ontologia
- Geracao de perfis de agentes
- Geracao de configuracao de simulacao
- Geracao de relatorio (ReACT)
- Chat com Report Agent

**Zep Cloud:**
- Armazenamento do grafo de conhecimento (GraphRAG)
- Memoria persistente dos agentes (fatos, relacoes, entidades)
- Busca semantica (edges + nodes)
- Atualizacao de memoria durante simulacao

**OASIS (CAMEL-AI):**
- Motor de simulacao multi-agente
- Duas plataformas paralelas (Twitter-like + Reddit-like)
- Agentes com acoes: POST, LIKE, REPOST, FOLLOW, COMMENT, SEARCH, etc.
- Execucao em processo Python separado

## Modelo de Dados

### Projeto (`models/project.py`)
```
Project
├── id (UUID)
├── name (string)
├── status (CREATED → ONTOLOGY_GENERATED → GRAPH_BUILDING → GRAPH_COMPLETED → FAILED)
├── files[] (uploaded docs)
├── ontology (entity_types + edge_types)
├── graph_info (graph_id, node_count, edge_count)
├── config (simulation parameters)
└── timestamps (created_at, updated_at)
```

### Tarefa (`models/task.py`)
```
Task
├── id (UUID)
├── type (graph_build, simulation_prepare, report_generate)
├── status (PENDING → PROCESSING → COMPLETED → FAILED)
├── progress (0-100)
├── message (status message)
├── result (task output)
└── error (error message if failed)
```

### Simulacao (em memoria + disco)
```
SimulationState
├── simulation_id (UUID)
├── project_id
├── graph_id
├── status (CREATED → PREPARING → READY → RUNNING → COMPLETED → FAILED)
├── platforms (twitter: enabled/disabled, reddit: enabled/disabled)
├── agent_profiles[]
├── simulation_config (time, events, actions)
├── runtime (current_round, total_actions, elapsed_time)
└── report (sections[], tools_used, elapsed_time)
```

## Comunicacao

### Frontend → Backend
- REST API via axios
- Polling para tarefas assincronas (cada 2-5s)
- Upload multipart/form-data para documentos

### Backend → Servicos Externos
- OpenAI SDK (chat completions, JSON mode)
- Zep Python SDK (graphs, nodes, edges, episodes)
- OASIS via subprocess (processo Python separado)

### Simulacao IPC
- Backend Flask ↔ Processo OASIS via `simulation_ipc.py`
- Comunicacao por arquivos JSON em disco + polling
- Status, acoes e resultados trocados entre processos

## Concorrencia

- Flask roda em modo debug com reloader (desenvolvimento)
- Tarefas longas executam em **threads** separadas (graph build, prepare)
- Simulacao OASIS roda em **processo** separado (subprocess)
- IPC via arquivos no disco (nao usa sockets/pipes)

## Armazenamento

| Dados | Onde |
|-------|------|
| Projetos (metadata) | Disco local (`backend/uploads/`) |
| Documentos enviados | Disco local (`backend/uploads/{project_id}/files/`) |
| Texto extraido | Disco local (`backend/uploads/{project_id}/extracted_text.txt`) |
| Grafo de conhecimento | Zep Cloud |
| Memoria dos agentes | Zep Cloud |
| Perfis de agentes | Disco local (`backend/uploads/simulations/{sim_id}/`) |
| Config de simulacao | Disco local (`backend/uploads/simulations/{sim_id}/`) |
| Resultados da simulacao | Disco local + Zep Cloud |
| Relatorios | Disco local (`backend/uploads/simulations/{sim_id}/report/`) |
| Logs | Disco local (`backend/logs/`) |
