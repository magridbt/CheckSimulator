# Fluxo de Trabalho Detalhado

## Visao Geral

O CheckSimulator opera em 5 passos sequenciais, cada um construindo sobre o resultado do anterior.

```
[Upload Docs] → [Grafo] → [Agentes] → [Simulacao] → [Relatorio] → [Chat]
    Passo 1       Passo 1    Passo 2      Passo 3       Passo 4     Passo 5
```

---

## Passo 1 — Construcao do Grafo

### 1.1 Upload e Geracao de Ontologia

**O que acontece:**
1. Usuario envia documentos (PDF, MD, TXT) + descricao do que quer simular
2. `text_processor` extrai texto de todos os documentos
3. `ontology_generator` envia texto + descricao para o LLM
4. LLM analisa e retorna uma ontologia com:
   - 10 tipos de entidade (8 especificos + 2 genericos de fallback)
   - Tipos de relacao entre entidades
   - Atributos para cada tipo

**Regras da ontologia:**
- Entidades devem ser atores reais que podem interagir em redes sociais
- Nao podem ser conceitos abstratos, topicos ou opinoes
- Os 2 ultimos tipos sao sempre genericos: "Person" e "Organization"
- Nomes de atributos nao podem usar palavras reservadas do Zep (name, uuid, group_id)

**Endpoint:** `POST /api/graph/ontology/generate`

### 1.2 Construcao do GraphRAG

**O que acontece:**
1. Texto extraido e dividido em blocos (chunks de 500 chars, overlap de 50)
2. Cria grafo no Zep Cloud com a ontologia definida
3. Envia blocos de texto em lotes para o Zep
4. Zep processa: extrai entidades, identifica relacoes, constroi memoria
5. Polling ate todos os blocos serem processados

**Tarefa assincrona** — pode levar minutos dependendo do volume de texto.

**Endpoint:** `POST /api/graph/build`
**Acompanhar:** `GET /api/graph/task/<task_id>`

---

## Passo 2 — Configuracao do Ambiente

### 2.1 Leitura e Filtragem de Entidades

**O que acontece:**
1. `zep_entity_reader` le todos os nos do grafo
2. Filtra apenas nos que possuem tipos da ontologia (ignora nos genericos "Entity")
3. Para cada entidade, coleta arestas (relacoes) e nos conectados

### 2.2 Geracao de Perfis de Agentes

**O que acontece:**
1. Para cada entidade, `oasis_profile_generator`:
   - Busca contexto adicional via Zep (hybrid search: edges + nodes)
   - Constroi contexto completo (atributos + relacoes + fatos + entidades relacionadas)
   - Distingue entidades individuais vs. organizacoes/grupos
   - Envia para LLM gerar perfil detalhado
2. Perfil inclui: nome, bio, personalidade, comportamento em redes sociais, interesses, profissao
3. Geracao paralela (default: 5 simultaneos) com retry

**Formato do perfil (simplificado):**
```json
{
  "user_id": 0,
  "username": "maria_silva_42",
  "name": "Maria Silva",
  "bio": "Professora universitaria...",
  "persona": "Perfil detalhado com personalidade...",
  "gender": "female",
  "age": 42,
  "country": "Brasil"
}
```

### 2.3 Geracao de Configuracao de Simulacao

**O que acontece:**
1. `simulation_config_generator` gera em 4 etapas (via LLM):
   - **Tempo:** duracao total, duracao por rodada, total de rodadas
   - **Eventos:** eventos programados com timestamps e descricoes
   - **Agentes:** atividade, frequencia de postagem, horarios ativos por agente
   - **Plataforma:** acoes disponiveis, algoritmo de recomendacao

**Tudo automatico** — LLM decide os parametros baseado no contexto.

**Endpoint:** `POST /api/simulation/prepare`

---

## Passo 3 — Simulacao

### Execucao

**O que acontece:**
1. `simulation_runner` inicia processo Python separado
2. OASIS cria duas plataformas paralelas: Twitter-like + Reddit-like
3. Todos os agentes sao injetados nas plataformas com seus perfis
4. A cada rodada:
   - Cada agente decide uma acao (POST, LIKE, REPOST, COMMENT, FOLLOW, etc.)
   - Decisoes baseadas em personalidade + memoria + contexto
   - Acoes sao executadas na plataforma simulada
5. `zep_graph_memory_updater` atualiza o grafo Zep com novas informacoes
6. Progresso visivel em tempo real no frontend

**Monitoramento:**
- Rodada atual / total
- Tempo decorrido
- Total de acoes executadas
- Acoes por tipo (posts, likes, reposts, etc.)

**Endpoints:**
- `POST /api/simulation/<id>/start`
- `GET /api/simulation/<id>/status/detail`
- `POST /api/simulation/<id>/stop`

---

## Passo 4 — Geracao de Relatorio

### Processo ReACT

**O que acontece:**
1. `report_agent` recebe a descricao da simulacao e o grafo
2. **Planejamento:** LLM define estrutura do relatorio (secoes)
3. **Para cada secao:**
   - LLM "pensa" sobre o que precisa investigar
   - Chama ferramentas Zep para coletar dados:
     - `buscar_previsao` — busca fatos e entidades relevantes
     - `buscar_memoria_grafo` — consulta estado do grafo
     - `entrevistar_agentes` — seleciona e entrevista agentes
     - `buscar_posts` — encontra posts relevantes da simulacao
   - LLM reflete sobre os resultados
   - Gera conteudo da secao
4. Max 5 chamadas de ferramenta por secao, 2 rodadas de reflexao

**Formato do relatorio:**
```json
{
  "sections": [
    {"title": "Resumo Executivo", "content": "..."},
    {"title": "Analise de Tendencias", "content": "..."},
    {"title": "Cenarios Provaveis", "content": "..."}
  ]
}
```

**Endpoint:** `POST /api/report/generate`

---

## Passo 5 — Interacao Profunda

### Chat com Agentes

**O que acontece:**
1. Usuario seleciona um agente da simulacao
2. Envia pergunta
3. Agente responde "em personagem" — com base em seu perfil, memoria e acoes durante a simulacao
4. Contexto de conversa anterior e mantido

### Chat com Report Agent

**O que acontece:**
1. Usuario faz perguntas sobre o relatorio ou a simulacao
2. Report Agent pode usar ferramentas Zep para buscar mais dados
3. Respostas baseadas no grafo completo + resultados da simulacao

**Endpoint:** `POST /api/report/<id>/chat`

---

## Diagrama de Sequencia Completo

```
Usuario          Frontend         Backend          LLM           Zep          OASIS
  │                 │                │               │             │             │
  │── Upload docs ──│                │               │             │             │
  │                 │── POST /ontology/generate ──│  │             │             │
  │                 │                │── extrair texto            │             │
  │                 │                │── gerar ontologia ──────│  │             │
  │                 │                │               │──── JSON ──│             │
  │                 │◄── ontologia ──│               │             │             │
  │                 │                │               │             │             │
  │── Construir ────│                │               │             │             │
  │                 │── POST /build ─│               │             │             │
  │                 │                │── criar grafo ─────────────│             │
  │                 │                │── enviar blocos ───────────│             │
  │                 │                │── aguardar processamento ──│             │
  │                 │◄── grafo OK ───│               │             │             │
  │                 │                │               │             │             │
  │── Preparar ─────│                │               │             │             │
  │                 │── POST /prepare│               │             │             │
  │                 │                │── ler entidades ───────────│             │
  │                 │                │── gerar perfis ──────────│  │             │
  │                 │                │── gerar config ──────────│  │             │
  │                 │◄── pronto ─────│               │             │             │
  │                 │                │               │             │             │
  │── Simular ──────│                │               │             │             │
  │                 │── POST /start ─│               │             │             │
  │                 │                │── iniciar processo ────────────────────│
  │                 │                │               │             │    ◄── acoes│
  │                 │                │── atualizar memoria ───────│             │
  │                 │◄── status ─────│               │             │             │
  │                 │                │               │             │             │
  │── Relatorio ────│                │               │             │             │
  │                 │── POST /report/generate ────│  │             │             │
  │                 │                │── planejar ──────────────│  │             │
  │                 │                │── buscar dados ────────────│             │
  │                 │                │── gerar secoes ──────────│  │             │
  │                 │◄── relatorio ──│               │             │             │
  │                 │                │               │             │             │
  │── Chat ─────────│                │               │             │             │
  │                 │── POST /chat ──│               │             │             │
  │                 │                │── consultar ───────────────│             │
  │                 │                │── responder ─────────────│  │             │
  │                 │◄── resposta ───│               │             │             │
```
