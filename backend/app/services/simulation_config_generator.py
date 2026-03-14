"""
Gerador inteligente de configuração de simulação
Usa LLM para gerar automaticamente parâmetros detalhados de simulação com base nos requisitos de simulação, conteúdo dos documentos e informações do grafo
Implementa automação completa, sem necessidade de configuração manual de parâmetros

Estratégia de geração em etapas para evitar falhas por conteúdo muito longo:
1. Gerar configuração de tempo
2. Gerar configuração de eventos
3. Gerar configuração de Agents em lotes
4. Gerar configuração de plataforma
"""

import json
import math
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field, asdict
from datetime import datetime

from openai import OpenAI

from ..config import Config
from ..utils.logger import get_logger
from .zep_entity_reader import EntityNode, ZepEntityReader

logger = get_logger('checksimulator.simulation_config')

# Configuração de fuso horário chinês (horário de Pequim)
CHINA_TIMEZONE_CONFIG = {
    # Período noturno (quase nenhuma atividade)
    "dead_hours": [0, 1, 2, 3, 4, 5],
    # Período matutino (acordando gradualmente)
    "morning_hours": [6, 7, 8],
    # Período de trabalho
    "work_hours": [9, 10, 11, 12, 13, 14, 15, 16, 17, 18],
    # Pico noturno (mais ativo)
    "peak_hours": [19, 20, 21, 22],
    # Período da noite (atividade diminuindo)
    "night_hours": [23],
    # Coeficientes de atividade
    "activity_multipliers": {
        "dead": 0.05,      # Madrugada quase ninguém
        "morning": 0.4,    # Manhã gradualmente ativo
        "work": 0.7,       # Período de trabalho médio
        "peak": 1.5,       # Pico noturno
        "night": 0.5       # Noite diminuindo
    }
}


@dataclass
class AgentActivityConfig:
    """Configuração de atividade de um Agent individual"""
    agent_id: int
    entity_uuid: str
    entity_name: str
    entity_type: str

    # Configuração de atividade (0.0-1.0)
    activity_level: float = 0.5  # Nível geral de atividade

    # Frequência de publicação (publicações esperadas por hora)
    posts_per_hour: float = 1.0
    comments_per_hour: float = 2.0

    # Horários ativos (formato 24h, 0-23)
    active_hours: List[int] = field(default_factory=lambda: list(range(8, 23)))

    # Velocidade de resposta (atraso de reação a eventos quentes, em minutos simulados)
    response_delay_min: int = 5
    response_delay_max: int = 60

    # Tendência emocional (-1.0 a 1.0, negativo a positivo)
    sentiment_bias: float = 0.0

    # Posicionamento (atitude em relação a tópicos específicos)
    stance: str = "neutral"  # supportive, opposing, neutral, observer

    # Peso de influência (determina a probabilidade de suas publicações serem vistas por outros Agents)
    influence_weight: float = 1.0


@dataclass
class TimeSimulationConfig:
    """Configuração de simulação de tempo (baseada nos hábitos chineses)"""
    # Duração total da simulação (horas simuladas)
    total_simulation_hours: int = 72  # Padrão: simular 72 horas (3 dias)

    # Tempo por rodada (minutos simulados) - padrão 60 minutos (1 hora), acelerando o fluxo de tempo
    minutes_per_round: int = 60

    # Faixa de Agents ativados por hora
    agents_per_hour_min: int = 5
    agents_per_hour_max: int = 20

    # Horário de pico (noite 19-22h, horário mais ativo dos chineses)
    peak_hours: List[int] = field(default_factory=lambda: [19, 20, 21, 22])
    peak_activity_multiplier: float = 1.5

    # Horário de baixa (madrugada 0-5h, quase nenhuma atividade)
    off_peak_hours: List[int] = field(default_factory=lambda: [0, 1, 2, 3, 4, 5])
    off_peak_activity_multiplier: float = 0.05  # Atividade extremamente baixa na madrugada

    # Período matutino
    morning_hours: List[int] = field(default_factory=lambda: [6, 7, 8])
    morning_activity_multiplier: float = 0.4

    # Período de trabalho
    work_hours: List[int] = field(default_factory=lambda: [9, 10, 11, 12, 13, 14, 15, 16, 17, 18])
    work_activity_multiplier: float = 0.7


@dataclass
class EventConfig:
    """Configuração de eventos"""
    # Evento inicial (evento disparador no início da simulação)
    initial_posts: List[Dict[str, Any]] = field(default_factory=list)

    # Eventos agendados (eventos disparados em momentos específicos)
    scheduled_events: List[Dict[str, Any]] = field(default_factory=list)

    # Palavras-chave de tópicos quentes
    hot_topics: List[str] = field(default_factory=list)

    # Direção de orientação da opinião pública
    narrative_direction: str = ""


@dataclass
class PlatformConfig:
    """Configuração específica da plataforma"""
    platform: str  # twitter or reddit

    # Pesos do algoritmo de recomendação
    recency_weight: float = 0.4  # Frescor temporal
    popularity_weight: float = 0.3  # Popularidade
    relevance_weight: float = 0.3  # Relevância

    # Limiar de viralização (após quantas interações dispara disseminação)
    viral_threshold: int = 10

    # Intensidade do efeito câmara de eco (grau de agrupamento de opiniões similares)
    echo_chamber_strength: float = 0.5


@dataclass
class SimulationParameters:
    """Configuração completa dos parâmetros de simulação"""
    # Informações básicas
    simulation_id: str
    project_id: str
    graph_id: str
    simulation_requirement: str

    # Configuração de tempo
    time_config: TimeSimulationConfig = field(default_factory=TimeSimulationConfig)

    # Lista de configurações de Agent
    agent_configs: List[AgentActivityConfig] = field(default_factory=list)

    # Configuração de eventos
    event_config: EventConfig = field(default_factory=EventConfig)

    # Configuração de plataforma
    twitter_config: Optional[PlatformConfig] = None
    reddit_config: Optional[PlatformConfig] = None

    # Configuração do LLM
    llm_model: str = ""
    llm_base_url: str = ""

    # Metadados de geração
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    generation_reasoning: str = ""  # Raciocínio explicativo do LLM

    def to_dict(self) -> Dict[str, Any]:
        """Converter para dicionário"""
        time_dict = asdict(self.time_config)
        return {
            "simulation_id": self.simulation_id,
            "project_id": self.project_id,
            "graph_id": self.graph_id,
            "simulation_requirement": self.simulation_requirement,
            "time_config": time_dict,
            "agent_configs": [asdict(a) for a in self.agent_configs],
            "event_config": asdict(self.event_config),
            "twitter_config": asdict(self.twitter_config) if self.twitter_config else None,
            "reddit_config": asdict(self.reddit_config) if self.reddit_config else None,
            "llm_model": self.llm_model,
            "llm_base_url": self.llm_base_url,
            "generated_at": self.generated_at,
            "generation_reasoning": self.generation_reasoning,
        }

    def to_json(self, indent: int = 2) -> str:
        """Converter para string JSON"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


class SimulationConfigGenerator:
    """
    Gerador inteligente de configuração de simulação

    Usa LLM para analisar requisitos de simulação, conteúdo de documentos e informações de entidades do grafo,
    gerando automaticamente a melhor configuração de parâmetros de simulação

    Estratégia de geração em etapas:
    1. Gerar configuração de tempo e configuração de eventos (leve)
    2. Gerar configuração de Agents em lotes (10-20 por lote)
    3. Gerar configuração de plataforma
    """

    # Comprimento máximo do contexto em caracteres
    MAX_CONTEXT_LENGTH = 50000
    # Número de Agents por lote
    AGENTS_PER_BATCH = 15

    # Comprimento de truncamento do contexto para cada etapa (em caracteres)
    TIME_CONFIG_CONTEXT_LENGTH = 10000   # Configuração de tempo
    EVENT_CONFIG_CONTEXT_LENGTH = 8000   # Configuração de eventos
    ENTITY_SUMMARY_LENGTH = 300          # Resumo de entidade
    AGENT_SUMMARY_LENGTH = 300           # Resumo de entidade na configuração de Agent
    ENTITIES_PER_TYPE_DISPLAY = 20       # Quantidade exibida por tipo de entidade

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model_name: Optional[str] = None
    ):
        self.api_key = api_key or Config.LLM_API_KEY
        self.base_url = base_url or Config.LLM_BASE_URL
        self.model_name = model_name or Config.LLM_MODEL_NAME

        if not self.api_key:
            raise ValueError("LLM_API_KEY não configurada")

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )

    def generate_config(
        self,
        simulation_id: str,
        project_id: str,
        graph_id: str,
        simulation_requirement: str,
        document_text: str,
        entities: List[EntityNode],
        enable_twitter: bool = True,
        enable_reddit: bool = True,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> SimulationParameters:
        """
        Gerar configuração completa de simulação de forma inteligente (geração em etapas)

        Args:
            simulation_id: ID da simulação
            project_id: ID do projeto
            graph_id: ID do grafo
            simulation_requirement: Descrição dos requisitos de simulação
            document_text: Conteúdo original do documento
            entities: Lista de entidades filtradas
            enable_twitter: Se habilitar Twitter
            enable_reddit: Se habilitar Reddit
            progress_callback: Função de callback de progresso(current_step, total_steps, message)

        Returns:
            SimulationParameters: Parâmetros completos da simulação
        """
        logger.info(f"Iniciando geração inteligente de configuração de simulação: simulation_id={simulation_id}, entidades={len(entities)}")

        # Calcular total de etapas
        num_batches = math.ceil(len(entities) / self.AGENTS_PER_BATCH)
        total_steps = 3 + num_batches  # Configuração de tempo + Configuração de eventos + N lotes de Agent + Configuração de plataforma
        current_step = 0

        def report_progress(step: int, message: str):
            nonlocal current_step
            current_step = step
            if progress_callback:
                progress_callback(step, total_steps, message)
            logger.info(f"[{step}/{total_steps}] {message}")

        # 1. Construir informações de contexto base
        context = self._build_context(
            simulation_requirement=simulation_requirement,
            document_text=document_text,
            entities=entities
        )

        reasoning_parts = []

        # ========== Etapa 1: Gerar configuração de tempo ==========
        report_progress(1, "Gerando configuração de tempo...")
        num_entities = len(entities)
        time_config_result = self._generate_time_config(context, num_entities)
        time_config = self._parse_time_config(time_config_result, num_entities)
        reasoning_parts.append(f"Configuração de tempo: {time_config_result.get('reasoning', 'sucesso')}")

        # ========== Etapa 2: Gerar configuração de eventos ==========
        report_progress(2, "Gerando configuração de eventos e tópicos quentes...")
        event_config_result = self._generate_event_config(context, simulation_requirement, entities)
        event_config = self._parse_event_config(event_config_result)
        reasoning_parts.append(f"Configuração de eventos: {event_config_result.get('reasoning', 'sucesso')}")

        # ========== Etapas 3-N: Gerar configuração de Agents em lotes ==========
        all_agent_configs = []
        for batch_idx in range(num_batches):
            start_idx = batch_idx * self.AGENTS_PER_BATCH
            end_idx = min(start_idx + self.AGENTS_PER_BATCH, len(entities))
            batch_entities = entities[start_idx:end_idx]

            report_progress(
                3 + batch_idx,
                f"Gerando configuração de Agent ({start_idx + 1}-{end_idx}/{len(entities)})..."
            )

            batch_configs = self._generate_agent_configs_batch(
                context=context,
                entities=batch_entities,
                start_idx=start_idx,
                simulation_requirement=simulation_requirement
            )
            all_agent_configs.extend(batch_configs)

        reasoning_parts.append(f"Configuração de Agent: {len(all_agent_configs)} gerados com sucesso")

        # ========== Atribuir publicador Agent aos posts iniciais ==========
        logger.info("Atribuindo Agents publicadores adequados aos posts iniciais...")
        event_config = self._assign_initial_post_agents(event_config, all_agent_configs)
        assigned_count = len([p for p in event_config.initial_posts if p.get("poster_agent_id") is not None])
        reasoning_parts.append(f"Atribuição de posts iniciais: {assigned_count} posts com publicadores atribuídos")

        # ========== Última etapa: Gerar configuração de plataforma ==========
        report_progress(total_steps, "Gerando configuração de plataforma...")
        twitter_config = None
        reddit_config = None

        if enable_twitter:
            twitter_config = PlatformConfig(
                platform="twitter",
                recency_weight=0.4,
                popularity_weight=0.3,
                relevance_weight=0.3,
                viral_threshold=10,
                echo_chamber_strength=0.5
            )

        if enable_reddit:
            reddit_config = PlatformConfig(
                platform="reddit",
                recency_weight=0.3,
                popularity_weight=0.4,
                relevance_weight=0.3,
                viral_threshold=15,
                echo_chamber_strength=0.6
            )

        # Construir parâmetros finais
        params = SimulationParameters(
            simulation_id=simulation_id,
            project_id=project_id,
            graph_id=graph_id,
            simulation_requirement=simulation_requirement,
            time_config=time_config,
            agent_configs=all_agent_configs,
            event_config=event_config,
            twitter_config=twitter_config,
            reddit_config=reddit_config,
            llm_model=self.model_name,
            llm_base_url=self.base_url,
            generation_reasoning=" | ".join(reasoning_parts)
        )

        logger.info(f"Geração de configuração de simulação concluída: {len(params.agent_configs)} configurações de Agent")

        return params

    def _build_context(
        self,
        simulation_requirement: str,
        document_text: str,
        entities: List[EntityNode]
    ) -> str:
        """Construir contexto do LLM, truncando para o comprimento máximo"""

        # Resumo de entidades
        entity_summary = self._summarize_entities(entities)

        # Construir contexto
        context_parts = [
            f"## Requisitos de simulação\n{simulation_requirement}",
            f"\n## Informações de entidades ({len(entities)})\n{entity_summary}",
        ]

        current_length = sum(len(p) for p in context_parts)
        remaining_length = self.MAX_CONTEXT_LENGTH - current_length - 500  # Margem de 500 caracteres

        if remaining_length > 0 and document_text:
            doc_text = document_text[:remaining_length]
            if len(document_text) > remaining_length:
                doc_text += "\n...(documento truncado)"
            context_parts.append(f"\n## Conteúdo original do documento\n{doc_text}")

        return "\n".join(context_parts)

    def _summarize_entities(self, entities: List[EntityNode]) -> str:
        """Gerar resumo de entidades"""
        lines = []

        # Agrupar por tipo
        by_type: Dict[str, List[EntityNode]] = {}
        for e in entities:
            t = e.get_entity_type() or "Unknown"
            if t not in by_type:
                by_type[t] = []
            by_type[t].append(e)

        for entity_type, type_entities in by_type.items():
            lines.append(f"\n### {entity_type} ({len(type_entities)})")
            # Usar quantidade e comprimento de resumo configurados
            display_count = self.ENTITIES_PER_TYPE_DISPLAY
            summary_len = self.ENTITY_SUMMARY_LENGTH
            for e in type_entities[:display_count]:
                summary_preview = (e.summary[:summary_len] + "...") if len(e.summary) > summary_len else e.summary
                lines.append(f"- {e.name}: {summary_preview}")
            if len(type_entities) > display_count:
                lines.append(f"  ... mais {len(type_entities) - display_count}")

        return "\n".join(lines)

    def _call_llm_with_retry(self, prompt: str, system_prompt: str) -> Dict[str, Any]:
        """Chamada de LLM com retry, incluindo lógica de reparo de JSON"""
        import re

        max_attempts = 3
        last_error = None

        for attempt in range(max_attempts):
            try:
                response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.7 - (attempt * 0.1)  # Reduzir temperatura a cada retry
                    # Sem definir max_tokens, deixar o LLM livre
                )

                content = response.choices[0].message.content
                finish_reason = response.choices[0].finish_reason

                # Verificar se foi truncado
                if finish_reason == 'length':
                    logger.warning(f"Saída do LLM truncada (tentativa {attempt+1})")
                    content = self._fix_truncated_json(content)

                # Tentar parsear JSON
                try:
                    return json.loads(content)
                except json.JSONDecodeError as e:
                    logger.warning(f"Falha no parse de JSON (tentativa {attempt+1}): {str(e)[:80]}")

                    # Tentar reparar JSON
                    fixed = self._try_fix_config_json(content)
                    if fixed:
                        return fixed

                    last_error = e

            except Exception as e:
                logger.warning(f"Falha na chamada ao LLM (tentativa {attempt+1}): {str(e)[:80]}")
                last_error = e
                import time
                time.sleep(2 * (attempt + 1))

        raise last_error or Exception("Falha na chamada ao LLM")

    def _fix_truncated_json(self, content: str) -> str:
        """Reparar JSON truncado"""
        content = content.strip()

        # Contar colchetes não fechados
        open_braces = content.count('{') - content.count('}')
        open_brackets = content.count('[') - content.count(']')

        # Verificar se há strings não fechadas
        if content and content[-1] not in '",}]':
            content += '"'

        # Fechar colchetes
        content += ']' * open_brackets
        content += '}' * open_braces

        return content

    def _try_fix_config_json(self, content: str) -> Optional[Dict[str, Any]]:
        """Tentar reparar JSON de configuração"""
        import re

        # Reparar caso de truncamento
        content = self._fix_truncated_json(content)

        # Extrair parte JSON
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            json_str = json_match.group()

            # Remover quebras de linha dentro de strings
            def fix_string(match):
                s = match.group(0)
                s = s.replace('\n', ' ').replace('\r', ' ')
                s = re.sub(r'\s+', ' ', s)
                return s

            json_str = re.sub(r'"[^"\\]*(?:\\.[^"\\]*)*"', fix_string, json_str)

            try:
                return json.loads(json_str)
            except:
                # Tentar remover todos os caracteres de controle
                json_str = re.sub(r'[\x00-\x1f\x7f-\x9f]', ' ', json_str)
                json_str = re.sub(r'\s+', ' ', json_str)
                try:
                    return json.loads(json_str)
                except:
                    pass

        return None

    def _generate_time_config(self, context: str, num_entities: int) -> Dict[str, Any]:
        """Gerar configuração de tempo"""
        # Usar comprimento de truncamento configurado
        context_truncated = context[:self.TIME_CONFIG_CONTEXT_LENGTH]

        # Calcular valor máximo permitido (80% dos agents)
        max_agents_allowed = max(1, int(num_entities * 0.9))

        prompt = f"""Com base nos seguintes requisitos de simulação, gere a configuração de simulação de tempo.

{context_truncated}

## Tarefa
Por favor, gere o JSON de configuração de tempo.

### Princípios básicos (apenas como referência, ajustar conforme evento e grupo participante):
- O grupo de usuários é chinês, deve seguir os hábitos de horário de Pequim
- Madrugada 0-5h quase nenhuma atividade (coeficiente de atividade 0.05)
- Manhã 6-8h gradualmente ativo (coeficiente de atividade 0.4)
- Horário de trabalho 9-18h atividade média (coeficiente de atividade 0.7)
- Noite 19-22h é o horário de pico (coeficiente de atividade 1.5)
- Após 23h atividade diminui (coeficiente de atividade 0.5)
- Regra geral: baixa atividade na madrugada, crescendo pela manhã, média no trabalho, pico à noite
- **Importante**: os valores de exemplo abaixo são apenas referência, ajuste conforme a natureza do evento e características do grupo
  - Exemplo: pico de estudantes pode ser 21-23h; mídia ativa o dia todo; órgãos oficiais apenas em horário de trabalho
  - Exemplo: tópicos urgentes podem gerar discussão de madrugada, off_peak_hours pode ser reduzido

### Formato JSON de retorno (sem markdown)

Exemplo:
{{
    "total_simulation_hours": 72,
    "minutes_per_round": 60,
    "agents_per_hour_min": 5,
    "agents_per_hour_max": 50,
    "peak_hours": [19, 20, 21, 22],
    "off_peak_hours": [0, 1, 2, 3, 4, 5],
    "morning_hours": [6, 7, 8],
    "work_hours": [9, 10, 11, 12, 13, 14, 15, 16, 17, 18],
    "reasoning": "Explicação da configuração de tempo para este evento"
}}

Descrição dos campos:
- total_simulation_hours (int): Duração total da simulação, 24-168 horas, eventos urgentes mais curtos, tópicos contínuos mais longos
- minutes_per_round (int): Duração por rodada, 30-120 minutos, recomendado 60 minutos
- agents_per_hour_min (int): Mínimo de Agents ativados por hora (faixa: 1-{max_agents_allowed})
- agents_per_hour_max (int): Máximo de Agents ativados por hora (faixa: 1-{max_agents_allowed})
- peak_hours (array de int): Horários de pico, ajustar conforme grupo participante
- off_peak_hours (array de int): Horários de baixa, geralmente madrugada
- morning_hours (array de int): Período matutino
- work_hours (array de int): Período de trabalho
- reasoning (string): Breve explicação do motivo desta configuração"""

        system_prompt = "Você é um especialista em simulação de mídias sociais. Retorne em formato JSON puro, a configuração de tempo deve seguir os hábitos chineses."

        try:
            return self._call_llm_with_retry(prompt, system_prompt)
        except Exception as e:
            logger.warning(f"Falha na geração de configuração de tempo pelo LLM: {e}, usando configuração padrão")
            return self._get_default_time_config(num_entities)

    def _get_default_time_config(self, num_entities: int) -> Dict[str, Any]:
        """Obter configuração de tempo padrão (hábitos chineses)"""
        return {
            "total_simulation_hours": 72,
            "minutes_per_round": 60,  # 1 hora por rodada, acelerando o tempo
            "agents_per_hour_min": max(1, num_entities // 15),
            "agents_per_hour_max": max(5, num_entities // 5),
            "peak_hours": [19, 20, 21, 22],
            "off_peak_hours": [0, 1, 2, 3, 4, 5],
            "morning_hours": [6, 7, 8],
            "work_hours": [9, 10, 11, 12, 13, 14, 15, 16, 17, 18],
            "reasoning": "Usando configuração padrão de hábitos chineses (1 hora por rodada)"
        }

    def _parse_time_config(self, result: Dict[str, Any], num_entities: int) -> TimeSimulationConfig:
        """Parsear resultado da configuração de tempo e validar que agents_per_hour não exceda o total de agents"""
        # Obter valores originais
        agents_per_hour_min = result.get("agents_per_hour_min", max(1, num_entities // 15))
        agents_per_hour_max = result.get("agents_per_hour_max", max(5, num_entities // 5))

        # Validar e corrigir: garantir que não exceda o total de agents
        if agents_per_hour_min > num_entities:
            logger.warning(f"agents_per_hour_min ({agents_per_hour_min}) excede total de Agents ({num_entities}), corrigido")
            agents_per_hour_min = max(1, num_entities // 10)

        if agents_per_hour_max > num_entities:
            logger.warning(f"agents_per_hour_max ({agents_per_hour_max}) excede total de Agents ({num_entities}), corrigido")
            agents_per_hour_max = max(agents_per_hour_min + 1, num_entities // 2)

        # Garantir min < max
        if agents_per_hour_min >= agents_per_hour_max:
            agents_per_hour_min = max(1, agents_per_hour_max // 2)
            logger.warning(f"agents_per_hour_min >= max, corrigido para {agents_per_hour_min}")

        return TimeSimulationConfig(
            total_simulation_hours=result.get("total_simulation_hours", 72),
            minutes_per_round=result.get("minutes_per_round", 60),  # Padrão 1 hora por rodada
            agents_per_hour_min=agents_per_hour_min,
            agents_per_hour_max=agents_per_hour_max,
            peak_hours=result.get("peak_hours", [19, 20, 21, 22]),
            off_peak_hours=result.get("off_peak_hours", [0, 1, 2, 3, 4, 5]),
            off_peak_activity_multiplier=0.05,  # Madrugada quase ninguém
            morning_hours=result.get("morning_hours", [6, 7, 8]),
            morning_activity_multiplier=0.4,
            work_hours=result.get("work_hours", list(range(9, 19))),
            work_activity_multiplier=0.7,
            peak_activity_multiplier=1.5
        )

    def _generate_event_config(
        self,
        context: str,
        simulation_requirement: str,
        entities: List[EntityNode]
    ) -> Dict[str, Any]:
        """Gerar configuração de eventos"""

        # Obter lista de tipos de entidade disponíveis para referência do LLM
        entity_types_available = list(set(
            e.get_entity_type() or "Unknown" for e in entities
        ))

        # Listar nomes representativos de entidades para cada tipo
        type_examples = {}
        for e in entities:
            etype = e.get_entity_type() or "Unknown"
            if etype not in type_examples:
                type_examples[etype] = []
            if len(type_examples[etype]) < 3:
                type_examples[etype].append(e.name)

        type_info = "\n".join([
            f"- {t}: {', '.join(examples)}"
            for t, examples in type_examples.items()
        ])

        # Usar comprimento de truncamento configurado
        context_truncated = context[:self.EVENT_CONFIG_CONTEXT_LENGTH]

        prompt = f"""Com base nos seguintes requisitos de simulação, gere a configuração de eventos.

Requisitos de simulação: {simulation_requirement}

{context_truncated}

## Tipos de entidade disponíveis e exemplos
{type_info}

## Tarefa
Gere o JSON de configuração de eventos:
- Extrair palavras-chave de tópicos quentes
- Descrever a direção de desenvolvimento da opinião pública
- Projetar conteúdo de posts iniciais, **cada post deve especificar poster_type (tipo do publicador)**

**Importante**: poster_type deve ser selecionado dos "tipos de entidade disponíveis" acima, para que posts iniciais possam ser atribuídos ao Agent adequado.
Exemplo: declarações oficiais devem ser publicadas por tipo Official/University, notícias por MediaOutlet, opiniões de estudantes por Student.

Formato JSON de retorno (sem markdown):
{{
    "hot_topics": ["palavra-chave1", "palavra-chave2", ...],
    "narrative_direction": "<descrição da direção da opinião pública>",
    "initial_posts": [
        {{"content": "conteúdo do post", "poster_type": "tipo de entidade (deve ser dos tipos disponíveis)"}},
        ...
    ],
    "reasoning": "<breve explicação>"
}}"""

        system_prompt = "Você é um especialista em análise de opinião pública. Retorne em formato JSON puro. O poster_type deve corresponder exatamente aos tipos de entidade disponíveis."

        try:
            return self._call_llm_with_retry(prompt, system_prompt)
        except Exception as e:
            logger.warning(f"Falha na geração de configuração de eventos pelo LLM: {e}, usando configuração padrão")
            return {
                "hot_topics": [],
                "narrative_direction": "",
                "initial_posts": [],
                "reasoning": "Usando configuração padrão"
            }

    def _parse_event_config(self, result: Dict[str, Any]) -> EventConfig:
        """Parsear resultado da configuração de eventos"""
        return EventConfig(
            initial_posts=result.get("initial_posts", []),
            scheduled_events=[],
            hot_topics=result.get("hot_topics", []),
            narrative_direction=result.get("narrative_direction", "")
        )

    def _assign_initial_post_agents(
        self,
        event_config: EventConfig,
        agent_configs: List[AgentActivityConfig]
    ) -> EventConfig:
        """
        Atribuir Agents publicadores adequados aos posts iniciais

        Faz correspondência do agent_id mais adequado baseado no poster_type de cada post
        """
        if not event_config.initial_posts:
            return event_config

        # Construir índice de agents por tipo de entidade
        agents_by_type: Dict[str, List[AgentActivityConfig]] = {}
        for agent in agent_configs:
            etype = agent.entity_type.lower()
            if etype not in agents_by_type:
                agents_by_type[etype] = []
            agents_by_type[etype].append(agent)

        # Tabela de mapeamento de tipos (tratar diferentes formatos que o LLM pode produzir)
        type_aliases = {
            "official": ["official", "university", "governmentagency", "government"],
            "university": ["university", "official"],
            "mediaoutlet": ["mediaoutlet", "media"],
            "student": ["student", "person"],
            "professor": ["professor", "expert", "teacher"],
            "alumni": ["alumni", "person"],
            "organization": ["organization", "ngo", "company", "group"],
            "person": ["person", "student", "alumni"],
        }

        # Registrar índice usado por tipo para evitar reutilizar o mesmo agent
        used_indices: Dict[str, int] = {}

        updated_posts = []
        for post in event_config.initial_posts:
            poster_type = post.get("poster_type", "").lower()
            content = post.get("content", "")

            # Tentar encontrar agent correspondente
            matched_agent_id = None

            # 1. Correspondência direta
            if poster_type in agents_by_type:
                agents = agents_by_type[poster_type]
                idx = used_indices.get(poster_type, 0) % len(agents)
                matched_agent_id = agents[idx].agent_id
                used_indices[poster_type] = idx + 1
            else:
                # 2. Correspondência por aliases
                for alias_key, aliases in type_aliases.items():
                    if poster_type in aliases or alias_key == poster_type:
                        for alias in aliases:
                            if alias in agents_by_type:
                                agents = agents_by_type[alias]
                                idx = used_indices.get(alias, 0) % len(agents)
                                matched_agent_id = agents[idx].agent_id
                                used_indices[alias] = idx + 1
                                break
                    if matched_agent_id is not None:
                        break

            # 3. Se ainda não encontrado, usar Agent com maior influência
            if matched_agent_id is None:
                logger.warning(f"Nenhum Agent correspondente ao tipo '{poster_type}' encontrado, usando Agent com maior influência")
                if agent_configs:
                    # Ordenar por influência, selecionar o de maior influência
                    sorted_agents = sorted(agent_configs, key=lambda a: a.influence_weight, reverse=True)
                    matched_agent_id = sorted_agents[0].agent_id
                else:
                    matched_agent_id = 0

            updated_posts.append({
                "content": content,
                "poster_type": post.get("poster_type", "Unknown"),
                "poster_agent_id": matched_agent_id
            })

            logger.info(f"Atribuição de post inicial: poster_type='{poster_type}' -> agent_id={matched_agent_id}")

        event_config.initial_posts = updated_posts
        return event_config

    def _generate_agent_configs_batch(
        self,
        context: str,
        entities: List[EntityNode],
        start_idx: int,
        simulation_requirement: str
    ) -> List[AgentActivityConfig]:
        """Gerar configurações de Agent em lotes"""

        # Construir informações de entidades (usando comprimento de resumo configurado)
        entity_list = []
        summary_len = self.AGENT_SUMMARY_LENGTH
        for i, e in enumerate(entities):
            entity_list.append({
                "agent_id": start_idx + i,
                "entity_name": e.name,
                "entity_type": e.get_entity_type() or "Unknown",
                "summary": e.summary[:summary_len] if e.summary else ""
            })

        prompt = f"""Com base nas informações abaixo, gere a configuração de atividade em mídias sociais para cada entidade.

Requisitos de simulação: {simulation_requirement}

## Lista de entidades
```json
{json.dumps(entity_list, ensure_ascii=False, indent=2)}
```

## Tarefa
Gere a configuração de atividade para cada entidade, observando:
- **Horários seguem hábitos chineses**: madrugada 0-5h quase sem atividade, noite 19-22h mais ativo
- **Órgãos oficiais** (University/GovernmentAgency): atividade baixa (0.1-0.3), horário de trabalho (9-17), resposta lenta (60-240 min), alta influência (2.5-3.0)
- **Mídia** (MediaOutlet): atividade média (0.4-0.6), ativa o dia todo (8-23), resposta rápida (5-30 min), alta influência (2.0-2.5)
- **Indivíduos** (Student/Person/Alumni): atividade alta (0.6-0.9), principalmente à noite (18-23), resposta rápida (1-15 min), baixa influência (0.8-1.2)
- **Figuras públicas/Especialistas**: atividade média (0.4-0.6), influência média-alta (1.5-2.0)

Formato JSON de retorno (sem markdown):
{{
    "agent_configs": [
        {{
            "agent_id": <deve ser consistente com a entrada>,
            "activity_level": <0.0-1.0>,
            "posts_per_hour": <frequência de posts>,
            "comments_per_hour": <frequência de comentários>,
            "active_hours": [<lista de horas ativas, considerando hábitos chineses>],
            "response_delay_min": <atraso mínimo de resposta em minutos>,
            "response_delay_max": <atraso máximo de resposta em minutos>,
            "sentiment_bias": <-1.0 a 1.0>,
            "stance": "<supportive/opposing/neutral/observer>",
            "influence_weight": <peso de influência>
        }},
        ...
    ]
}}"""

        system_prompt = "Você é um especialista em análise de comportamento em mídias sociais. Retorne JSON puro, a configuração deve seguir os hábitos chineses."

        try:
            result = self._call_llm_with_retry(prompt, system_prompt)
            llm_configs = {cfg["agent_id"]: cfg for cfg in result.get("agent_configs", [])}
        except Exception as e:
            logger.warning(f"Falha na geração de lote de configuração de Agent pelo LLM: {e}, usando geração por regras")
            llm_configs = {}

        # Construir objetos AgentActivityConfig
        configs = []
        for i, entity in enumerate(entities):
            agent_id = start_idx + i
            cfg = llm_configs.get(agent_id, {})

            # Se LLM não gerou, usar geração por regras
            if not cfg:
                cfg = self._generate_agent_config_by_rule(entity)

            config = AgentActivityConfig(
                agent_id=agent_id,
                entity_uuid=entity.uuid,
                entity_name=entity.name,
                entity_type=entity.get_entity_type() or "Unknown",
                activity_level=cfg.get("activity_level", 0.5),
                posts_per_hour=cfg.get("posts_per_hour", 0.5),
                comments_per_hour=cfg.get("comments_per_hour", 1.0),
                active_hours=cfg.get("active_hours", list(range(9, 23))),
                response_delay_min=cfg.get("response_delay_min", 5),
                response_delay_max=cfg.get("response_delay_max", 60),
                sentiment_bias=cfg.get("sentiment_bias", 0.0),
                stance=cfg.get("stance", "neutral"),
                influence_weight=cfg.get("influence_weight", 1.0)
            )
            configs.append(config)

        return configs

    def _generate_agent_config_by_rule(self, entity: EntityNode) -> Dict[str, Any]:
        """Gerar configuração de um Agent individual por regras (hábitos chineses)"""
        entity_type = (entity.get_entity_type() or "Unknown").lower()

        if entity_type in ["university", "governmentagency", "ngo"]:
            # Órgãos oficiais: ativos em horário de trabalho, baixa frequência, alta influência
            return {
                "activity_level": 0.2,
                "posts_per_hour": 0.1,
                "comments_per_hour": 0.05,
                "active_hours": list(range(9, 18)),  # 9:00-17:59
                "response_delay_min": 60,
                "response_delay_max": 240,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 3.0
            }
        elif entity_type in ["mediaoutlet"]:
            # Mídia: ativa o dia todo, frequência média, alta influência
            return {
                "activity_level": 0.5,
                "posts_per_hour": 0.8,
                "comments_per_hour": 0.3,
                "active_hours": list(range(7, 24)),  # 7:00-23:59
                "response_delay_min": 5,
                "response_delay_max": 30,
                "sentiment_bias": 0.0,
                "stance": "observer",
                "influence_weight": 2.5
            }
        elif entity_type in ["professor", "expert", "official"]:
            # Especialistas/Professores: trabalho + noite, frequência média
            return {
                "activity_level": 0.4,
                "posts_per_hour": 0.3,
                "comments_per_hour": 0.5,
                "active_hours": list(range(8, 22)),  # 8:00-21:59
                "response_delay_min": 15,
                "response_delay_max": 90,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 2.0
            }
        elif entity_type in ["student"]:
            # Estudantes: principalmente à noite, alta frequência
            return {
                "activity_level": 0.8,
                "posts_per_hour": 0.6,
                "comments_per_hour": 1.5,
                "active_hours": [8, 9, 10, 11, 12, 13, 18, 19, 20, 21, 22, 23],  # Manhã + noite
                "response_delay_min": 1,
                "response_delay_max": 15,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 0.8
            }
        elif entity_type in ["alumni"]:
            # Ex-alunos: principalmente à noite
            return {
                "activity_level": 0.6,
                "posts_per_hour": 0.4,
                "comments_per_hour": 0.8,
                "active_hours": [12, 13, 19, 20, 21, 22, 23],  # Almoço + noite
                "response_delay_min": 5,
                "response_delay_max": 30,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 1.0
            }
        else:
            # Pessoas comuns: pico noturno
            return {
                "activity_level": 0.7,
                "posts_per_hour": 0.5,
                "comments_per_hour": 1.2,
                "active_hours": [9, 10, 11, 12, 13, 18, 19, 20, 21, 22, 23],  # Dia + noite
                "response_delay_min": 2,
                "response_delay_max": 20,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 1.0
            }
