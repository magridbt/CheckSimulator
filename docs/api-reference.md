# Referencia da API REST

Base URL: `http://localhost:5001`

---

## Health Check

### `GET /health`
Verifica status do backend.

**Resposta:**
```json
{
  "service": "CheckSimulator Backend",
  "status": "ok"
}
```

---

## Grafo (`/api/graph`)

### `POST /api/graph/ontology/generate`
Upload de documentos e geracao de ontologia via LLM.

**Content-Type:** `multipart/form-data`

**Parametros:**
| Campo | Tipo | Obrigatorio | Descricao |
|-------|------|-------------|-----------|
| `simulation_requirement` | string | Sim | Descricao do que simular |
| `project_name` | string | Nao | Nome do projeto |
| `additional_info` | string | Nao | Informacoes extras |
| `files` | File[] | Sim | Documentos (PDF, MD, TXT) |

**Resposta:**
```json
{
  "status": "success",
  "project_id": "uuid",
  "ontology": {
    "entity_types": [...],
    "edge_types": [...]
  }
}
```

### `POST /api/graph/build`
Constroi grafo GraphRAG no Zep a partir da ontologia gerada.

**Body (JSON):**
```json
{
  "project_id": "uuid",
  "force": false
}
```

**Resposta:**
```json
{
  "status": "success",
  "task_id": "uuid",
  "message": "Tarefa de construcao do grafo iniciada"
}
```

### `GET /api/graph/task/<task_id>`
Consulta progresso de tarefa assincrona.

**Resposta:**
```json
{
  "status": "success",
  "task": {
    "id": "uuid",
    "status": "processing",
    "progress": 65,
    "message": "Adicionando blocos de texto..."
  }
}
```

### `GET /api/graph/data/<graph_id>`
Retorna dados do grafo (nos e arestas).

**Resposta:**
```json
{
  "status": "success",
  "data": {
    "nodes": [...],
    "edges": [...],
    "node_count": 42,
    "edge_count": 87
  }
}
```

### `GET /api/graph/project/<project_id>`
Detalhes de um projeto.

### `GET /api/graph/projects?limit=20`
Lista todos os projetos.

### `DELETE /api/graph/project/<project_id>`
Exclui projeto e seus arquivos.

### `POST /api/graph/project/<project_id>/reset`
Reseta status do projeto para reconstruir grafo.

---

## Simulacao (`/api/simulation`)

### `POST /api/simulation/create`
Cria nova instancia de simulacao.

**Body (JSON):**
```json
{
  "project_id": "uuid",
  "graph_id": "uuid",
  "enable_twitter": true,
  "enable_reddit": true
}
```

**Resposta:**
```json
{
  "status": "success",
  "simulation_id": "uuid"
}
```

### `POST /api/simulation/prepare`
Prepara ambiente (gera perfis de agentes + configuracao). Tarefa assincrona.

**Body (JSON):**
```json
{
  "simulation_id": "uuid",
  "simulation_requirement": "descricao",
  "document_content": "texto extraido",
  "use_llm_profile": true,
  "parallel_count": 5,
  "force_regenerate": false
}
```

**Resposta:**
```json
{
  "status": "success",
  "task_id": "uuid",
  "message": "Tarefa de preparacao iniciada"
}
```

### `GET /api/simulation/prepare/status?task_id=<id>`
Consulta progresso da preparacao.

### `GET /api/simulation/<sim_id>/profiles`
Retorna perfis de agentes gerados.

### `GET /api/simulation/<sim_id>/profiles/stream`
Stream de perfis sendo gerados em tempo real.

### `GET /api/simulation/<sim_id>/config`
Retorna configuracao de simulacao gerada.

### `GET /api/simulation/<sim_id>/config/stream`
Stream de configuracao sendo gerada.

### `POST /api/simulation/<sim_id>/start`
Inicia simulacao OASIS.

**Body (JSON):**
```json
{
  "max_rounds": 10
}
```

### `POST /api/simulation/<sim_id>/stop`
Para simulacao em andamento.

### `GET /api/simulation/<sim_id>/status`
Status da simulacao em execucao.

### `GET /api/simulation/<sim_id>/status/detail`
Status detalhado com acoes recentes.

### `GET /api/simulation/<sim_id>/posts?platform=twitter&limit=50&offset=0`
Posts gerados pelos agentes.

### `GET /api/simulation/<sim_id>/timeline`
Timeline da simulacao por rodada.

### `GET /api/simulation/<sim_id>/agents/stats`
Estatisticas dos agentes.

### `GET /api/simulation/<sim_id>/actions?limit=100`
Historico de acoes.

### `POST /api/simulation/<sim_id>/shutdown`
Encerra ambiente de simulacao.

### `GET /api/simulation/<sim_id>/env/status`
Status do ambiente.

### `POST /api/simulation/<sim_id>/interview`
Entrevistar agentes em lote.

**Body (JSON):**
```json
{
  "agent_ids": [0, 1, 2],
  "question": "O que voce acha sobre...?"
}
```

### `GET /api/simulation/history?limit=20`
Lista historico de simulacoes com detalhes do projeto.

---

## Relatorio (`/api/report`)

### `POST /api/report/generate`
Inicia geracao do relatorio.

**Body (JSON):**
```json
{
  "simulation_id": "uuid"
}
```

**Resposta:**
```json
{
  "status": "success",
  "report_id": "uuid"
}
```

### `GET /api/report/<report_id>/status`
Status da geracao do relatorio.

### `GET /api/report/<report_id>/agent-logs?offset=0`
Logs detalhados do Report Agent (incremental).

### `GET /api/report/<report_id>/console-logs?offset=0`
Logs do console (incremental).

### `GET /api/report/<report_id>`
Relatorio completo gerado.

**Resposta:**
```json
{
  "status": "success",
  "report": {
    "id": "uuid",
    "sections": [
      {
        "title": "Titulo da secao",
        "content": "Conteudo em markdown"
      }
    ],
    "tools_used": 12,
    "elapsed_time": "3m 45s"
  }
}
```

### `POST /api/report/<report_id>/chat`
Chat com o Report Agent.

**Body (JSON):**
```json
{
  "message": "Explique melhor a tendencia X..."
}
```

---

## Entidades (`/api/simulation/entities`)

### `GET /api/simulation/entities/<graph_id>`
Retorna todas as entidades filtradas do grafo.

**Query params:**
- `entity_types` — Tipos separados por virgula (opcional)
- `include_edges` — Incluir arestas (default: true)

### `GET /api/simulation/entities/<graph_id>/<node_uuid>`
Detalhes de uma entidade especifica.

### `GET /api/simulation/entities/<graph_id>/type/<entity_type>`
Entidades de um tipo especifico.

---

## Codigos de Status

| Codigo | Significado |
|--------|-------------|
| 200 | Sucesso |
| 400 | Requisicao invalida (parametros faltando) |
| 404 | Recurso nao encontrado (projeto, tarefa, simulacao) |
| 500 | Erro interno do servidor |

Todas as respostas seguem o formato:
```json
{
  "status": "success" | "error",
  "message": "descricao",
  "data": {}
}
```
