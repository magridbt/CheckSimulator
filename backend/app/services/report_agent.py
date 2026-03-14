"""
Serviço Report Agent
Usa LangChain + Zep para implementar geração de relatórios de simulação no padrão ReACT

Funcionalidades:
1. Gera relatórios com base nos requisitos de simulação e informações do grafo Zep
2. Primeiro planeja a estrutura do sumário, depois gera por seções
3. Cada seção usa o padrão ReACT de múltiplas rodadas de raciocínio e reflexão
4. Suporta conversação com o usuário, chamando ferramentas de busca autonomamente
"""

import os
import json
import time
import re
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from ..config import Config
from ..utils.llm_client import LLMClient
from ..utils.logger import get_logger
from .zep_tools import (
    ZepToolsService,
    SearchResult,
    InsightForgeResult,
    PanoramaResult,
    InterviewResult
)

logger = get_logger('checksimulator.report_agent')


class ReportLogger:
    """
    Registrador detalhado de logs do Report Agent

    Gera um arquivo agent_log.jsonl na pasta do relatório, registrando cada ação detalhada.
    Cada linha é um objeto JSON completo, contendo timestamp, tipo de ação, conteúdo detalhado etc.
    """

    def __init__(self, report_id: str):
        """
        Inicializar registrador de logs

        Args:
            report_id: ID do relatório, usado para determinar o caminho do arquivo de log
        """
        self.report_id = report_id
        self.log_file_path = os.path.join(
            Config.UPLOAD_FOLDER, 'reports', report_id, 'agent_log.jsonl'
        )
        self.start_time = datetime.now()
        self._ensure_log_file()

    def _ensure_log_file(self):
        """Garantir que o diretório do arquivo de log existe"""
        log_dir = os.path.dirname(self.log_file_path)
        os.makedirs(log_dir, exist_ok=True)

    def _get_elapsed_time(self) -> float:
        """Obter tempo decorrido desde o início (em segundos)"""
        return (datetime.now() - self.start_time).total_seconds()

    def log(
        self,
        action: str,
        stage: str,
        details: Dict[str, Any],
        section_title: str = None,
        section_index: int = None
    ):
        """
        Registrar uma entrada de log

        Args:
            action: Tipo de ação, como 'start', 'tool_call', 'llm_response', 'section_complete' etc.
            stage: Fase atual, como 'planning', 'generating', 'completed'
            details: Dicionário de conteúdo detalhado, sem truncamento
            section_title: Título da seção atual (opcional)
            section_index: Índice da seção atual (opcional)
        """
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "elapsed_seconds": round(self._get_elapsed_time(), 2),
            "report_id": self.report_id,
            "action": action,
            "stage": stage,
            "section_title": section_title,
            "section_index": section_index,
            "details": details
        }

        # Escrita em modo append no arquivo JSONL
        with open(self.log_file_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')

    def log_start(self, simulation_id: str, graph_id: str, simulation_requirement: str):
        """Registrar início da geração do relatório"""
        self.log(
            action="report_start",
            stage="pending",
            details={
                "simulation_id": simulation_id,
                "graph_id": graph_id,
                "simulation_requirement": simulation_requirement,
                "message": "Tarefa de geração de relatório iniciada"
            }
        )

    def log_planning_start(self):
        """Registrar início do planejamento do sumário"""
        self.log(
            action="planning_start",
            stage="planning",
            details={"message": "Iniciando planejamento do sumário do relatório"}
        )

    def log_planning_context(self, context: Dict[str, Any]):
        """Registrar informações de contexto obtidas no planejamento"""
        self.log(
            action="planning_context",
            stage="planning",
            details={
                "message": "Obtendo informações de contexto da simulação",
                "context": context
            }
        )

    def log_planning_complete(self, outline_dict: Dict[str, Any]):
        """Registrar conclusão do planejamento do sumário"""
        self.log(
            action="planning_complete",
            stage="planning",
            details={
                "message": "Planejamento do sumário concluído",
                "outline": outline_dict
            }
        )

    def log_section_start(self, section_title: str, section_index: int):
        """Registrar início da geração de seção"""
        self.log(
            action="section_start",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={"message": f"Iniciando geração da seção: {section_title}"}
        )

    def log_react_thought(self, section_title: str, section_index: int, iteration: int, thought: str):
        """Registrar processo de raciocínio ReACT"""
        self.log(
            action="react_thought",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "iteration": iteration,
                "thought": thought,
                "message": f"ReACT rodada {iteration} de raciocínio"
            }
        )

    def log_tool_call(
        self,
        section_title: str,
        section_index: int,
        tool_name: str,
        parameters: Dict[str, Any],
        iteration: int
    ):
        """Registrar chamada de ferramenta"""
        self.log(
            action="tool_call",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "iteration": iteration,
                "tool_name": tool_name,
                "parameters": parameters,
                "message": f"Chamando ferramenta: {tool_name}"
            }
        )

    def log_tool_result(
        self,
        section_title: str,
        section_index: int,
        tool_name: str,
        result: str,
        iteration: int
    ):
        """Registrar resultado de chamada de ferramenta (conteúdo completo, sem truncamento)"""
        self.log(
            action="tool_result",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "iteration": iteration,
                "tool_name": tool_name,
                "result": result,  # Resultado completo, sem truncamento
                "result_length": len(result),
                "message": f"Ferramenta {tool_name} retornou resultado"
            }
        )

    def log_llm_response(
        self,
        section_title: str,
        section_index: int,
        response: str,
        iteration: int,
        has_tool_calls: bool,
        has_final_answer: bool
    ):
        """Registrar resposta do LLM (conteúdo completo, sem truncamento)"""
        self.log(
            action="llm_response",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "iteration": iteration,
                "response": response,  # Resposta completa, sem truncamento
                "response_length": len(response),
                "has_tool_calls": has_tool_calls,
                "has_final_answer": has_final_answer,
                "message": f"Resposta LLM (chamada de ferramenta: {has_tool_calls}, resposta final: {has_final_answer})"
            }
        )

    def log_section_content(
        self,
        section_title: str,
        section_index: int,
        content: str,
        tool_calls_count: int
    ):
        """Registrar conclusão da geração de conteúdo da seção (registra apenas o conteúdo, não representa conclusão da seção inteira)"""
        self.log(
            action="section_content",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "content": content,  # Conteúdo completo, sem truncamento
                "content_length": len(content),
                "tool_calls_count": tool_calls_count,
                "message": f"Conteúdo da seção {section_title} gerado"
            }
        )

    def log_section_full_complete(
        self,
        section_title: str,
        section_index: int,
        full_content: str
    ):
        """
        Registrar conclusão da geração da seção

        O frontend deve monitorar este log para determinar se uma seção foi realmente concluída e obter o conteúdo completo
        """
        self.log(
            action="section_complete",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "content": full_content,
                "content_length": len(full_content),
                "message": f"Seção {section_title} gerada com sucesso"
            }
        )

    def log_report_complete(self, total_sections: int, total_time_seconds: float):
        """Registrar conclusão da geração do relatório"""
        self.log(
            action="report_complete",
            stage="completed",
            details={
                "total_sections": total_sections,
                "total_time_seconds": round(total_time_seconds, 2),
                "message": "Geração do relatório concluída"
            }
        )

    def log_error(self, error_message: str, stage: str, section_title: str = None):
        """Registrar erro"""
        self.log(
            action="error",
            stage=stage,
            section_title=section_title,
            section_index=None,
            details={
                "error": error_message,
                "message": f"Ocorreu um erro: {error_message}"
            }
        )


class ReportConsoleLogger:
    """
    Registrador de logs de console do Report Agent

    Escreve logs estilo console (INFO, WARNING etc.) em um arquivo console_log.txt na pasta do relatório.
    Estes logs são diferentes do agent_log.jsonl, são saída de console em formato de texto puro.
    """

    def __init__(self, report_id: str):
        """
        Inicializar registrador de logs de console

        Args:
            report_id: ID do relatório, usado para determinar o caminho do arquivo de log
        """
        self.report_id = report_id
        self.log_file_path = os.path.join(
            Config.UPLOAD_FOLDER, 'reports', report_id, 'console_log.txt'
        )
        self._ensure_log_file()
        self._file_handler = None
        self._setup_file_handler()

    def _ensure_log_file(self):
        """Garantir que o diretório do arquivo de log existe"""
        log_dir = os.path.dirname(self.log_file_path)
        os.makedirs(log_dir, exist_ok=True)

    def _setup_file_handler(self):
        """Configurar handler de arquivo, para escrever logs também no arquivo"""
        import logging

        # Criar handler de arquivo
        self._file_handler = logging.FileHandler(
            self.log_file_path,
            mode='a',
            encoding='utf-8'
        )
        self._file_handler.setLevel(logging.INFO)

        # Usar formato conciso igual ao do console
        formatter = logging.Formatter(
            '[%(asctime)s] %(levelname)s: %(message)s',
            datefmt='%H:%M:%S'
        )
        self._file_handler.setFormatter(formatter)

        # Adicionar aos loggers relacionados ao report_agent
        loggers_to_attach = [
            'checksimulator.report_agent',
            'checksimulator.zep_tools',
        ]

        for logger_name in loggers_to_attach:
            target_logger = logging.getLogger(logger_name)
            # Evitar adicionar duplicatas
            if self._file_handler not in target_logger.handlers:
                target_logger.addHandler(self._file_handler)

    def close(self):
        """Fechar handler de arquivo e remover do logger"""
        import logging

        if self._file_handler:
            loggers_to_detach = [
                'checksimulator.report_agent',
                'checksimulator.zep_tools',
            ]

            for logger_name in loggers_to_detach:
                target_logger = logging.getLogger(logger_name)
                if self._file_handler in target_logger.handlers:
                    target_logger.removeHandler(self._file_handler)

            self._file_handler.close()
            self._file_handler = None

    def __del__(self):
        """Garantir fechamento do handler de arquivo na destruição"""
        self.close()


class ReportStatus(str, Enum):
    """Status do relatório"""
    PENDING = "pending"
    PLANNING = "planning"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ReportSection:
    """Seção do relatório"""
    title: str
    content: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "content": self.content
        }

    def to_markdown(self, level: int = 2) -> str:
        """Converter para formato Markdown"""
        md = f"{'#' * level} {self.title}\n\n"
        if self.content:
            md += f"{self.content}\n\n"
        return md


@dataclass
class ReportOutline:
    """Sumário do relatório"""
    title: str
    summary: str
    sections: List[ReportSection]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "summary": self.summary,
            "sections": [s.to_dict() for s in self.sections]
        }

    def to_markdown(self) -> str:
        """Converter para formato Markdown"""
        md = f"# {self.title}\n\n"
        md += f"> {self.summary}\n\n"
        for section in self.sections:
            md += section.to_markdown()
        return md


@dataclass
class Report:
    """Relatório completo"""
    report_id: str
    simulation_id: str
    graph_id: str
    simulation_requirement: str
    status: ReportStatus
    outline: Optional[ReportOutline] = None
    markdown_content: str = ""
    created_at: str = ""
    completed_at: str = ""
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "simulation_id": self.simulation_id,
            "graph_id": self.graph_id,
            "simulation_requirement": self.simulation_requirement,
            "status": self.status.value,
            "outline": self.outline.to_dict() if self.outline else None,
            "markdown_content": self.markdown_content,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "error": self.error
        }


# ═══════════════════════════════════════════════════════════════
# Constantes de templates de Prompt
# ═══════════════════════════════════════════════════════════════

# ── Descrições das ferramentas ──

TOOL_DESC_INSIGHT_FORGE = """\
[Busca de Insights Profundos - Ferramenta poderosa de busca]
Esta é nossa poderosa função de busca, projetada para análise profunda. Ela:
1. Decompõe automaticamente sua pergunta em múltiplas subquestões
2. Busca informações no grafo de simulação a partir de múltiplas dimensões
3. Integra resultados de busca semântica, análise de entidades e rastreamento de cadeias de relações
4. Retorna o conteúdo mais abrangente e profundo

[Cenários de uso]
- Necessidade de análise profunda de um tópico
- Necessidade de compreender múltiplos aspectos de um evento
- Necessidade de obter material rico para suportar seções do relatório

[Conteúdo retornado]
- Textos originais de fatos relevantes (podem ser citados diretamente)
- Insights de entidades centrais
- Análise de cadeias de relações"""

TOOL_DESC_PANORAMA_SEARCH = """\
[Busca ampla - Obter visão panorâmica]
Esta ferramenta é usada para obter o panorama completo dos resultados da simulação, especialmente adequada para compreender o processo de evolução dos eventos. Ela:
1. Obtém todos os nós e relações relevantes
2. Distingue entre fatos atualmente válidos e fatos históricos/expirados
3. Ajuda a compreender como a opinião pública evoluiu

[Cenários de uso]
- Necessidade de compreender o desenvolvimento completo do evento
- Necessidade de comparar mudanças de opinião em diferentes fases
- Necessidade de obter informações abrangentes de entidades e relações

[Conteúdo retornado]
- Fatos atualmente válidos (resultados mais recentes da simulação)
- Fatos históricos/expirados (registros de evolução)
- Todas as entidades envolvidas"""

TOOL_DESC_QUICK_SEARCH = """\
[Busca simples - Busca rápida]
Ferramenta de busca rápida e leve, adequada para consultas de informação simples e diretas.

[Cenários de uso]
- Necessidade de buscar rapidamente uma informação específica
- Necessidade de verificar um fato
- Busca simples de informações

[Conteúdo retornado]
- Lista de fatos mais relevantes para a consulta"""

TOOL_DESC_INTERVIEW_AGENTS = """\
[Entrevista profunda - Entrevista real de Agents (duas plataformas)]
Chama a API de entrevista do ambiente de simulação OASIS para realizar entrevistas reais com Agents em simulação!
Isto não é uma simulação de LLM, mas uma chamada à interface real de entrevista para obter respostas originais dos Agents simulados.
Por padrão, entrevista simultaneamente nas plataformas Twitter e Reddit, obtendo perspectivas mais abrangentes.

Fluxo funcional:
1. Lê automaticamente o arquivo de perfis, conhecendo todos os Agents da simulação
2. Seleciona inteligentemente os Agents mais relevantes para o tema da entrevista (estudantes, mídia, oficiais etc.)
3. Gera automaticamente perguntas de entrevista
4. Chama a interface /api/simulation/interview/batch para realizar entrevistas reais em duas plataformas
5. Integra todos os resultados, fornecendo análise de múltiplas perspectivas

[Cenários de uso]
- Necessidade de compreender visões de diferentes papéis sobre o evento (o que pensam os estudantes? E a mídia? O que dizem as autoridades?)
- Necessidade de coletar opiniões e posicionamentos de múltiplas partes
- Necessidade de obter respostas reais dos Agents simulados (do ambiente OASIS)
- Desejo de tornar o relatório mais vívido, incluindo "entrevistas transcritas"

[Conteúdo retornado]
- Informações de identidade dos Agents entrevistados
- Respostas dos Agents nas plataformas Twitter e Reddit
- Citações-chave (podem ser usadas diretamente)
- Resumo das entrevistas e comparação de pontos de vista

[Importante] É necessário que o ambiente de simulação OASIS esteja em execução para usar esta funcionalidade!"""

# ── Prompt de planejamento do sumário ──

PLAN_SYSTEM_PROMPT = """\
Você é um especialista em redação de "Relatórios de Previsão Futura", com uma "visão de Deus" do mundo simulado — você pode observar o comportamento, discurso e interações de cada Agent na simulação.

[Conceito central]
Construímos um mundo simulado e injetamos nele "requisitos de simulação" específicos como variáveis. O resultado da evolução do mundo simulado é a previsão do que pode acontecer no futuro. Você não está observando "dados experimentais", mas sim "um ensaio do futuro".

[Sua tarefa]
Redigir um "Relatório de Previsão Futura", respondendo:
1. Sob as condições que estabelecemos, o que aconteceu no futuro?
2. Como os diversos tipos de Agents (grupos) reagiram e agiram?
3. Quais tendências e riscos futuros dignos de atenção esta simulação revelou?

[Posicionamento do relatório]
- Este é um relatório de previsão futura baseado em simulação, revelando "se isso acontecer, como será o futuro"
- Foco nos resultados da previsão: direção dos eventos, reações de grupos, fenômenos emergentes, riscos potenciais
- As falas e ações dos Agents no mundo simulado são previsões do comportamento futuro de grupos humanos
- Não é uma análise da situação atual do mundo real
- Não é uma revisão genérica de opinião pública

[Limite de número de seções]
- Mínimo 2 seções, máximo 5 seções
- Sem subseções, cada seção redige conteúdo completo diretamente
- Conteúdo deve ser conciso, focado nas descobertas preditivas centrais
- A estrutura das seções é projetada por você com base nos resultados da previsão

Por favor, produza o sumário do relatório em formato JSON, como segue:
{
    "title": "Título do relatório",
    "summary": "Resumo do relatório (uma frase resumindo as descobertas preditivas centrais)",
    "sections": [
        {
            "title": "Título da seção",
            "description": "Descrição do conteúdo da seção"
        }
    ]
}

Nota: o array sections deve ter no mínimo 2 e no máximo 5 elementos!"""

PLAN_USER_PROMPT_TEMPLATE = """\
[Cenário da previsão]
Variável injetada no mundo simulado (requisitos de simulação): {simulation_requirement}

[Escala do mundo simulado]
- Número de entidades participantes na simulação: {total_nodes}
- Número de relações geradas entre entidades: {total_edges}
- Distribuição de tipos de entidade: {entity_types}
- Número de Agents ativos: {total_entities}

[Amostra parcial de fatos futuros previstos pela simulação]
{related_facts_json}

Por favor, examine este ensaio do futuro com uma "visão de Deus":
1. Sob as condições que estabelecemos, que tipo de estado o futuro apresentou?
2. Como os diversos tipos de pessoas (Agents) reagiram e agiram?
3. Quais tendências futuras dignos de atenção esta simulação revelou?

Com base nos resultados da previsão, projete a estrutura de seções mais adequada para o relatório.

[Lembrete novamente] Número de seções do relatório: mínimo 2, máximo 5, conteúdo deve ser conciso e focado nas descobertas preditivas centrais."""

# ── Prompt de geração de seção ──

SECTION_SYSTEM_PROMPT_TEMPLATE = """\
Você é um especialista em redação de "Relatórios de Previsão Futura", redigindo uma seção do relatório.

Título do relatório: {report_title}
Resumo do relatório: {report_summary}
Cenário de previsão (requisitos de simulação): {simulation_requirement}

Seção a ser redigida: {section_title}

═══════════════════════════════════════════════════════════════
[Conceito central]
═══════════════════════════════════════════════════════════════

O mundo simulado é um ensaio do futuro. Injetamos condições específicas (requisitos de simulação) no mundo simulado,
e o comportamento e interações dos Agents na simulação são previsões do comportamento futuro de grupos humanos.

Sua tarefa é:
- Revelar o que aconteceu no futuro sob as condições estabelecidas
- Prever como os diversos tipos de pessoas (Agents) reagiram e agiram
- Descobrir tendências futuras, riscos e oportunidades dignos de atenção

Não escreva como uma análise da situação atual do mundo real
Foque em "como será o futuro" — os resultados da simulação são o futuro previsto

═══════════════════════════════════════════════════════════════
[Regras mais importantes - Devem ser seguidas]
═══════════════════════════════════════════════════════════════

1. [Deve chamar ferramentas para observar o mundo simulado]
   - Você está observando o ensaio do futuro com uma "visão de Deus"
   - Todo o conteúdo deve vir de eventos e falas dos Agents no mundo simulado
   - É proibido usar seu próprio conhecimento para redigir o conteúdo do relatório
   - Cada seção deve chamar ferramentas pelo menos 3 vezes (máximo 5) para observar o mundo simulado, ele representa o futuro

2. [Deve citar falas e ações originais dos Agents]
   - As falas e comportamentos dos Agents são previsões do comportamento futuro de grupos humanos
   - Use formato de citação no relatório para exibir estas previsões, por exemplo:
     > "Um determinado grupo de pessoas expressaria: conteúdo original..."
   - Estas citações são as evidências centrais das previsões da simulação

3. [Consistência linguística - Citações devem ser traduzidas para o idioma do relatório]
   - O conteúdo retornado pelas ferramentas pode conter inglês ou expressões mistas chinês-inglês
   - Se os requisitos de simulação e materiais originais são em chinês, o relatório deve ser inteiramente em chinês
   - Ao citar conteúdo em inglês ou misto retornado pelas ferramentas, deve traduzi-lo para chinês fluente antes de escrever no relatório
   - Ao traduzir, mantenha o significado original inalterado, garantindo expressão natural e fluente
   - Esta regra se aplica tanto ao texto principal quanto ao conteúdo em blocos de citação (formato >)

4. [Apresentar fielmente os resultados da previsão]
   - O conteúdo do relatório deve refletir os resultados simulados que representam o futuro no mundo simulado
   - Não adicione informações que não existam na simulação
   - Se houver informação insuficiente em algum aspecto, declare isso honestamente

═══════════════════════════════════════════════════════════════
[Normas de formato - Extremamente importante!]
═══════════════════════════════════════════════════════════════

[Uma seção = Unidade mínima de conteúdo]
- Cada seção é a menor unidade de divisão do relatório
- Proibido usar qualquer título Markdown dentro da seção (#, ##, ###, #### etc.)
- Proibido adicionar título principal da seção no início do conteúdo
- O título da seção é adicionado automaticamente pelo sistema, você só precisa redigir o texto puro
- Use **negrito**, separação de parágrafos, citações e listas para organizar o conteúdo, mas não use títulos

[Exemplo correto]
```
Esta seção analisa a dinâmica de disseminação de opinião pública do evento. Através de análise profunda dos dados simulados, descobrimos...

**Fase de ignição inicial**

Weibo, como o primeiro cenário da opinião pública, assumiu a função central de publicação inicial:

> "Weibo contribuiu com 68% do volume inicial de voz..."

**Fase de amplificação emocional**

A plataforma Douyin amplificou ainda mais o impacto do evento:

- Forte impacto visual
- Alto grau de ressonância emocional
```

[Exemplo incorreto]
```
## Resumo Executivo          <- Errado! Não adicione nenhum título
### I. Fase Inicial         <- Errado! Não use ### para subseções
#### 1.1 Análise detalhada  <- Errado! Não use #### para subdivisão

Esta seção analisa...
```

═══════════════════════════════════════════════════════════════
[Ferramentas de busca disponíveis] (chamar 3-5 vezes por seção)
═══════════════════════════════════════════════════════════════

{tools_description}

[Sugestões de uso de ferramentas - Misture diferentes ferramentas, não use apenas uma]
- insight_forge: Análise de insights profundos, decomposição automática de questões e busca multidimensional de fatos e relações
- panorama_search: Busca panorâmica ampla, compreender panorama completo, linha do tempo e evolução do evento
- quick_search: Verificação rápida de um ponto de informação específico
- interview_agents: Entrevistar Agents simulados, obter pontos de vista em primeira pessoa e reações reais de diferentes papéis

═══════════════════════════════════════════════════════════════
[Fluxo de trabalho]
═══════════════════════════════════════════════════════════════

A cada resposta você só pode fazer uma destas duas coisas (não ambas ao mesmo tempo):

Opção A - Chamar ferramenta:
Produza seu raciocínio, depois use o seguinte formato para chamar uma ferramenta:
<tool_call>
{{"name": "nome_da_ferramenta", "parameters": {{"nome_parametro": "valor_parametro"}}}}
</tool_call>
O sistema executará a ferramenta e retornará o resultado. Você não precisa e não pode escrever o resultado da ferramenta por conta própria.

Opção B - Produzir conteúdo final:
Quando já tiver obtido informações suficientes através das ferramentas, produza o conteúdo da seção começando com "Final Answer:".

Estritamente proibido:
- Proibido incluir chamada de ferramenta e Final Answer na mesma resposta
- Proibido fabricar resultados de ferramentas (Observation), todos os resultados são injetados pelo sistema
- Cada resposta pode chamar no máximo uma ferramenta

═══════════════════════════════════════════════════════════════
[Requisitos de conteúdo da seção]
═══════════════════════════════════════════════════════════════

1. O conteúdo deve ser baseado nos dados simulados obtidos pelas ferramentas
2. Cite abundantemente textos originais para demonstrar os efeitos da simulação
3. Use formato Markdown (mas proibido usar títulos):
   - Use **texto em negrito** para marcar pontos importantes (substituindo subtítulos)
   - Use listas (- ou 1.2.3.) para organizar pontos-chave
   - Use linhas em branco para separar diferentes parágrafos
   - Proibido usar #, ##, ###, #### ou qualquer outra sintaxe de título
4. [Formato de citação - Deve ser parágrafo independente]
   Citações devem ser parágrafos independentes, com uma linha em branco antes e depois, não podem ser misturadas em parágrafos:

   Formato correto:
   ```
   A resposta da escola foi considerada carente de conteúdo substantivo.

   > "O modo de resposta da escola parece rígido e lento no ambiente dinâmico das mídias sociais."

   Esta avaliação reflete a insatisfação geral do público.
   ```

   Formato incorreto:
   ```
   A resposta da escola foi considerada carente de conteúdo substantivo. > "O modo de resposta da escola..." Esta avaliação reflete...
   ```
5. Manter coerência lógica com outras seções
6. [Evitar repetição] Leia cuidadosamente o conteúdo das seções concluídas abaixo, não repita informações idênticas
7. [Reforçando] Não adicione nenhum título! Use **negrito** em vez de subtítulos de subseção"""

SECTION_USER_PROMPT_TEMPLATE = """\
Conteúdo das seções concluídas (leia cuidadosamente para evitar repetição):
{previous_content}

═══════════════════════════════════════════════════════════════
[Tarefa atual] Redigir seção: {section_title}
═══════════════════════════════════════════════════════════════

[Lembretes importantes]
1. Leia cuidadosamente as seções concluídas acima, evite repetir o mesmo conteúdo!
2. Antes de começar, deve primeiro chamar ferramentas para obter dados da simulação
3. Misture diferentes ferramentas, não use apenas uma
4. O conteúdo do relatório deve vir dos resultados da busca, não use seu próprio conhecimento

[Aviso de formato - Deve ser seguido]
- Não escreva nenhum título (#, ##, ###, #### são todos proibidos)
- Não escreva "{section_title}" como início
- O título da seção é adicionado automaticamente pelo sistema
- Escreva diretamente o texto, use **negrito** em vez de subtítulos de subseção

Por favor, comece:
1. Primeiro pense (Thought) sobre que informações esta seção precisa
2. Depois chame ferramentas (Action) para obter dados da simulação
3. Após coletar informações suficientes, produza Final Answer (texto puro, sem nenhum título)"""

# ── Templates de mensagens dentro do ciclo ReACT ──

REACT_OBSERVATION_TEMPLATE = """\
Observation (resultado da busca):

═══ Ferramenta {tool_name} retornou ═══
{result}

═══════════════════════════════════════════════════════════════
Ferramentas chamadas {tool_calls_count}/{max_tool_calls} vezes (usadas: {used_tools_str}){unused_hint}
- Se a informação for suficiente: produza conteúdo da seção começando com "Final Answer:" (deve citar os textos originais acima)
- Se precisar de mais informações: chame uma ferramenta para continuar a busca
═══════════════════════════════════════════════════════════════"""

REACT_INSUFFICIENT_TOOLS_MSG = (
    "[Atenção] Você chamou ferramentas apenas {tool_calls_count} vezes, são necessárias pelo menos {min_tool_calls} vezes. "
    "Por favor, chame mais ferramentas para obter mais dados da simulação, depois produza Final Answer. {unused_hint}"
)

REACT_INSUFFICIENT_TOOLS_MSG_ALT = (
    "Atualmente foram chamadas apenas {tool_calls_count} ferramentas, são necessárias pelo menos {min_tool_calls}. "
    "Por favor, chame ferramentas para obter dados da simulação. {unused_hint}"
)

REACT_TOOL_LIMIT_MSG = (
    "Limite de chamadas de ferramentas atingido ({tool_calls_count}/{max_tool_calls}), não pode chamar mais ferramentas. "
    'Por favor, produza imediatamente o conteúdo da seção começando com "Final Answer:" baseado nas informações já obtidas.'
)

REACT_UNUSED_TOOLS_HINT = "\n Você ainda não usou: {unused_list}, recomenda-se experimentar diferentes ferramentas para obter informações de múltiplos ângulos"

REACT_FORCE_FINAL_MSG = "Limite de chamadas de ferramentas atingido, por favor produza diretamente Final Answer: e gere o conteúdo da seção."

# ── Prompt de chat ──

CHAT_SYSTEM_PROMPT_TEMPLATE = """\
Você é um assistente conciso e eficiente de previsão por simulação.

[Contexto]
Condições de previsão: {simulation_requirement}

[Relatório de análise já gerado]
{report_content}

[Regras]
1. Priorize responder com base no conteúdo do relatório acima
2. Responda diretamente à pergunta, evite raciocínios longos
3. Chame ferramentas para buscar mais dados apenas quando o conteúdo do relatório for insuficiente
4. Respostas devem ser concisas, claras e organizadas

[Ferramentas disponíveis] (use apenas quando necessário, máximo 1-2 chamadas)
{tools_description}

[Formato de chamada de ferramenta]
<tool_call>
{{"name": "nome_da_ferramenta", "parameters": {{"nome_parametro": "valor_parametro"}}}}
</tool_call>

[Estilo de resposta]
- Conciso e direto, sem textos longos
- Use formato > para citar conteúdo-chave
- Priorize dar a conclusão, depois explique as razões"""

CHAT_OBSERVATION_SUFFIX = "\n\nPor favor, responda a pergunta de forma concisa."


# ═══════════════════════════════════════════════════════════════
# Classe principal ReportAgent
# ═══════════════════════════════════════════════════════════════


class ReportAgent:
    """
    Report Agent - Agent de geração de relatórios de simulação

    Usa o padrão ReACT (Reasoning + Acting):
    1. Fase de planejamento: analisa requisitos de simulação, planeja estrutura do sumário
    2. Fase de geração: gera conteúdo seção por seção, cada seção pode chamar ferramentas múltiplas vezes
    3. Fase de reflexão: verifica completude e precisão do conteúdo
    """

    # Máximo de chamadas de ferramentas (por seção)
    MAX_TOOL_CALLS_PER_SECTION = 5

    # Máximo de rodadas de reflexão
    MAX_REFLECTION_ROUNDS = 3

    # Máximo de chamadas de ferramentas por chat
    MAX_TOOL_CALLS_PER_CHAT = 2

    def __init__(
        self,
        graph_id: str,
        simulation_id: str,
        simulation_requirement: str,
        llm_client: Optional[LLMClient] = None,
        zep_tools: Optional[ZepToolsService] = None
    ):
        """
        Inicializar Report Agent

        Args:
            graph_id: ID do grafo
            simulation_id: ID da simulação
            simulation_requirement: Descrição dos requisitos de simulação
            llm_client: Cliente LLM (opcional)
            zep_tools: Serviço de ferramentas Zep (opcional)
        """
        self.graph_id = graph_id
        self.simulation_id = simulation_id
        self.simulation_requirement = simulation_requirement

        self.llm = llm_client or LLMClient()
        self.zep_tools = zep_tools or ZepToolsService()

        # Definições de ferramentas
        self.tools = self._define_tools()

        # Registrador de logs (inicializado em generate_report)
        self.report_logger: Optional[ReportLogger] = None
        # Registrador de logs de console (inicializado em generate_report)
        self.console_logger: Optional[ReportConsoleLogger] = None

        logger.info(f"ReportAgent inicializado: graph_id={graph_id}, simulation_id={simulation_id}")

    def _define_tools(self) -> Dict[str, Dict[str, Any]]:
        """Definir ferramentas disponíveis"""
        return {
            "insight_forge": {
                "name": "insight_forge",
                "description": TOOL_DESC_INSIGHT_FORGE,
                "parameters": {
                    "query": "A questão ou tópico que deseja analisar profundamente",
                    "report_context": "Contexto da seção atual do relatório (opcional, ajuda a gerar subquestões mais precisas)"
                }
            },
            "panorama_search": {
                "name": "panorama_search",
                "description": TOOL_DESC_PANORAMA_SEARCH,
                "parameters": {
                    "query": "Consulta de busca, para ordenação por relevância",
                    "include_expired": "Se inclui conteúdo expirado/histórico (padrão True)"
                }
            },
            "quick_search": {
                "name": "quick_search",
                "description": TOOL_DESC_QUICK_SEARCH,
                "parameters": {
                    "query": "String de consulta de busca",
                    "limit": "Quantidade de resultados retornados (opcional, padrão 10)"
                }
            },
            "interview_agents": {
                "name": "interview_agents",
                "description": TOOL_DESC_INTERVIEW_AGENTS,
                "parameters": {
                    "interview_topic": "Tema ou descrição do requisito da entrevista (ex: 'compreender a visão dos estudantes sobre o incidente de formaldeído nos dormitórios')",
                    "max_agents": "Número máximo de Agents a entrevistar (opcional, padrão 5, máximo 10)"
                }
            }
        }

    def _execute_tool(self, tool_name: str, parameters: Dict[str, Any], report_context: str = "") -> str:
        """
        Executar chamada de ferramenta

        Args:
            tool_name: Nome da ferramenta
            parameters: Parâmetros da ferramenta
            report_context: Contexto do relatório (para InsightForge)

        Returns:
            Resultado da execução da ferramenta (formato texto)
        """
        logger.info(f"Executando ferramenta: {tool_name}, parâmetros: {parameters}")

        try:
            if tool_name == "insight_forge":
                query = parameters.get("query", "")
                ctx = parameters.get("report_context", "") or report_context
                result = self.zep_tools.insight_forge(
                    graph_id=self.graph_id,
                    query=query,
                    simulation_requirement=self.simulation_requirement,
                    report_context=ctx
                )
                return result.to_text()

            elif tool_name == "panorama_search":
                # Busca ampla - obter panorama
                query = parameters.get("query", "")
                include_expired = parameters.get("include_expired", True)
                if isinstance(include_expired, str):
                    include_expired = include_expired.lower() in ['true', '1', 'yes']
                result = self.zep_tools.panorama_search(
                    graph_id=self.graph_id,
                    query=query,
                    include_expired=include_expired
                )
                return result.to_text()

            elif tool_name == "quick_search":
                # Busca simples - busca rápida
                query = parameters.get("query", "")
                limit = parameters.get("limit", 10)
                if isinstance(limit, str):
                    limit = int(limit)
                result = self.zep_tools.quick_search(
                    graph_id=self.graph_id,
                    query=query,
                    limit=limit
                )
                return result.to_text()

            elif tool_name == "interview_agents":
                # Entrevista profunda - chamar API real de entrevista OASIS para obter respostas dos Agents simulados (duas plataformas)
                interview_topic = parameters.get("interview_topic", parameters.get("query", ""))
                max_agents = parameters.get("max_agents", 5)
                if isinstance(max_agents, str):
                    max_agents = int(max_agents)
                max_agents = min(max_agents, 10)
                result = self.zep_tools.interview_agents(
                    simulation_id=self.simulation_id,
                    interview_requirement=interview_topic,
                    simulation_requirement=self.simulation_requirement,
                    max_agents=max_agents
                )
                return result.to_text()

            # ========== Ferramentas antigas para compatibilidade retroativa (redirecionam internamente para novas ferramentas) ==========

            elif tool_name == "search_graph":
                # Redirecionar para quick_search
                logger.info("search_graph redirecionado para quick_search")
                return self._execute_tool("quick_search", parameters, report_context)

            elif tool_name == "get_graph_statistics":
                result = self.zep_tools.get_graph_statistics(self.graph_id)
                return json.dumps(result, ensure_ascii=False, indent=2)

            elif tool_name == "get_entity_summary":
                entity_name = parameters.get("entity_name", "")
                result = self.zep_tools.get_entity_summary(
                    graph_id=self.graph_id,
                    entity_name=entity_name
                )
                return json.dumps(result, ensure_ascii=False, indent=2)

            elif tool_name == "get_simulation_context":
                # Redirecionar para insight_forge, pois é mais poderoso
                logger.info("get_simulation_context redirecionado para insight_forge")
                query = parameters.get("query", self.simulation_requirement)
                return self._execute_tool("insight_forge", {"query": query}, report_context)

            elif tool_name == "get_entities_by_type":
                entity_type = parameters.get("entity_type", "")
                nodes = self.zep_tools.get_entities_by_type(
                    graph_id=self.graph_id,
                    entity_type=entity_type
                )
                result = [n.to_dict() for n in nodes]
                return json.dumps(result, ensure_ascii=False, indent=2)

            else:
                return f"Ferramenta desconhecida: {tool_name}. Por favor use uma destas: insight_forge, panorama_search, quick_search"

        except Exception as e:
            logger.error(f"Falha na execução da ferramenta: {tool_name}, erro: {str(e)}")
            return f"Falha na execução da ferramenta: {str(e)}"

    # Conjunto de nomes de ferramentas válidas, usado para validação ao parsear JSON bruto como fallback
    VALID_TOOL_NAMES = {"insight_forge", "panorama_search", "quick_search", "interview_agents"}

    def _parse_tool_calls(self, response: str) -> List[Dict[str, Any]]:
        """
        Parsear chamadas de ferramentas da resposta do LLM

        Formatos suportados (por prioridade):
        1. <tool_call>{"name": "tool_name", "parameters": {...}}</tool_call>
        2. JSON bruto (resposta inteira ou linha única é um JSON de chamada de ferramenta)
        """
        tool_calls = []

        # Formato 1: estilo XML (formato padrão)
        xml_pattern = r'<tool_call>\s*(\{.*?\})\s*</tool_call>'
        for match in re.finditer(xml_pattern, response, re.DOTALL):
            try:
                call_data = json.loads(match.group(1))
                tool_calls.append(call_data)
            except json.JSONDecodeError:
                pass

        if tool_calls:
            return tool_calls

        # Formato 2: fallback - LLM produz JSON bruto (sem tag <tool_call>)
        # Só tenta quando formato 1 não casou, para evitar casar JSON no texto
        stripped = response.strip()
        if stripped.startswith('{') and stripped.endswith('}'):
            try:
                call_data = json.loads(stripped)
                if self._is_valid_tool_call(call_data):
                    tool_calls.append(call_data)
                    return tool_calls
            except json.JSONDecodeError:
                pass

        # Resposta pode conter texto de raciocínio + JSON bruto, tentar extrair último objeto JSON
        json_pattern = r'(\{"(?:name|tool)"\s*:.*?\})\s*$'
        match = re.search(json_pattern, stripped, re.DOTALL)
        if match:
            try:
                call_data = json.loads(match.group(1))
                if self._is_valid_tool_call(call_data):
                    tool_calls.append(call_data)
            except json.JSONDecodeError:
                pass

        return tool_calls

    def _is_valid_tool_call(self, data: dict) -> bool:
        """Validar se JSON parseado é uma chamada de ferramenta válida"""
        # Suporta ambos os formatos de chaves: {"name": ..., "parameters": ...} e {"tool": ..., "params": ...}
        tool_name = data.get("name") or data.get("tool")
        if tool_name and tool_name in self.VALID_TOOL_NAMES:
            # Unificar chaves para name / parameters
            if "tool" in data:
                data["name"] = data.pop("tool")
            if "params" in data and "parameters" not in data:
                data["parameters"] = data.pop("params")
            return True
        return False

    def _get_tools_description(self) -> str:
        """Gerar texto de descrição das ferramentas"""
        desc_parts = ["Ferramentas disponíveis:"]
        for name, tool in self.tools.items():
            params_desc = ", ".join([f"{k}: {v}" for k, v in tool["parameters"].items()])
            desc_parts.append(f"- {name}: {tool['description']}")
            if params_desc:
                desc_parts.append(f"  Parâmetros: {params_desc}")
        return "\n".join(desc_parts)

    def plan_outline(
        self,
        progress_callback: Optional[Callable] = None
    ) -> ReportOutline:
        """
        Planejar sumário do relatório

        Usa LLM para analisar requisitos de simulação e planejar a estrutura do sumário

        Args:
            progress_callback: Função de callback de progresso

        Returns:
            ReportOutline: Sumário do relatório
        """
        logger.info("Iniciando planejamento do sumário do relatório...")

        if progress_callback:
            progress_callback("planning", 0, "Analisando requisitos de simulação...")

        # Primeiro obter contexto da simulação
        context = self.zep_tools.get_simulation_context(
            graph_id=self.graph_id,
            simulation_requirement=self.simulation_requirement
        )

        if progress_callback:
            progress_callback("planning", 30, "Gerando sumário do relatório...")

        system_prompt = PLAN_SYSTEM_PROMPT
        user_prompt = PLAN_USER_PROMPT_TEMPLATE.format(
            simulation_requirement=self.simulation_requirement,
            total_nodes=context.get('graph_statistics', {}).get('total_nodes', 0),
            total_edges=context.get('graph_statistics', {}).get('total_edges', 0),
            entity_types=list(context.get('graph_statistics', {}).get('entity_types', {}).keys()),
            total_entities=context.get('total_entities', 0),
            related_facts_json=json.dumps(context.get('related_facts', [])[:10], ensure_ascii=False, indent=2),
        )

        try:
            response = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3
            )

            if progress_callback:
                progress_callback("planning", 80, "Parseando estrutura do sumário...")

            # Parsear sumário
            sections = []
            for section_data in response.get("sections", []):
                sections.append(ReportSection(
                    title=section_data.get("title", ""),
                    content=""
                ))

            outline = ReportOutline(
                title=response.get("title", "Relatório de análise da simulação"),
                summary=response.get("summary", ""),
                sections=sections
            )

            if progress_callback:
                progress_callback("planning", 100, "Planejamento do sumário concluído")

            logger.info(f"Planejamento do sumário concluído: {len(sections)} seções")
            return outline

        except Exception as e:
            logger.error(f"Falha no planejamento do sumário: {str(e)}")
            # Retornar sumário padrão (3 seções, como fallback)
            return ReportOutline(
                title="Relatório de Previsão Futura",
                summary="Análise de tendências e riscos futuros baseada em previsão por simulação",
                sections=[
                    ReportSection(title="Cenário de previsão e descobertas centrais"),
                    ReportSection(title="Análise preditiva de comportamento de grupos"),
                    ReportSection(title="Perspectivas de tendências e alertas de risco")
                ]
            )

    def _generate_section_react(
        self,
        section: ReportSection,
        outline: ReportOutline,
        previous_sections: List[str],
        progress_callback: Optional[Callable] = None,
        section_index: int = 0
    ) -> str:
        """
        Gerar conteúdo de uma seção usando padrão ReACT

        Ciclo ReACT:
        1. Thought (Raciocínio) - Analisar que informações são necessárias
        2. Action (Ação) - Chamar ferramentas para obter informações
        3. Observation (Observação) - Analisar resultados retornados pelas ferramentas
        4. Repetir até informações suficientes ou atingir máximo de iterações
        5. Final Answer (Resposta final) - Gerar conteúdo da seção

        Args:
            section: Seção a ser gerada
            outline: Sumário completo
            previous_sections: Conteúdo das seções anteriores (para manter coerência)
            progress_callback: Callback de progresso
            section_index: Índice da seção (para registro de log)

        Returns:
            Conteúdo da seção (formato Markdown)
        """
        logger.info(f"ReACT gerando seção: {section.title}")

        # Registrar log de início da seção
        if self.report_logger:
            self.report_logger.log_section_start(section.title, section_index)

        system_prompt = SECTION_SYSTEM_PROMPT_TEMPLATE.format(
            report_title=outline.title,
            report_summary=outline.summary,
            simulation_requirement=self.simulation_requirement,
            section_title=section.title,
            tools_description=self._get_tools_description(),
        )

        # Construir prompt do usuário - cada seção concluída é passada com máximo de 4000 caracteres
        if previous_sections:
            previous_parts = []
            for sec in previous_sections:
                # Máximo 4000 caracteres por seção
                truncated = sec[:4000] + "..." if len(sec) > 4000 else sec
                previous_parts.append(truncated)
            previous_content = "\n\n---\n\n".join(previous_parts)
        else:
            previous_content = "(Esta é a primeira seção)"

        user_prompt = SECTION_USER_PROMPT_TEMPLATE.format(
            previous_content=previous_content,
            section_title=section.title,
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        # Ciclo ReACT
        tool_calls_count = 0
        max_iterations = 5  # Máximo de iterações
        min_tool_calls = 3  # Mínimo de chamadas de ferramentas
        conflict_retries = 0  # Conflitos consecutivos de chamada de ferramenta + Final Answer
        used_tools = set()  # Registrar ferramentas já usadas
        all_tools = {"insight_forge", "panorama_search", "quick_search", "interview_agents"}

        # Contexto do relatório, para geração de subquestões do InsightForge
        report_context = f"Título da seção: {section.title}\nRequisitos de simulação: {self.simulation_requirement}"

        for iteration in range(max_iterations):
            if progress_callback:
                progress_callback(
                    "generating",
                    int((iteration / max_iterations) * 100),
                    f"Busca profunda e redação em andamento ({tool_calls_count}/{self.MAX_TOOL_CALLS_PER_SECTION})"
                )

            # Chamar LLM
            response = self.llm.chat(
                messages=messages,
                temperature=0.5,
                max_tokens=4096
            )

            # Verificar se retorno do LLM é None (exceção de API ou conteúdo vazio)
            if response is None:
                logger.warning(f"Seção {section.title} iteração {iteration + 1}: LLM retornou None")
                # Se ainda há iterações, adicionar mensagem e tentar novamente
                if iteration < max_iterations - 1:
                    messages.append({"role": "assistant", "content": "(resposta vazia)"})
                    messages.append({"role": "user", "content": "Por favor, continue gerando o conteúdo."})
                    continue
                # Última iteração também retornou None, sair do loop para finalização forçada
                break

            logger.debug(f"Resposta LLM: {response[:200]}...")

            # Parsear uma vez, reutilizar resultado
            tool_calls = self._parse_tool_calls(response)
            has_tool_calls = bool(tool_calls)
            has_final_answer = "Final Answer:" in response

            # ── Tratamento de conflito: LLM produziu chamada de ferramenta e Final Answer simultaneamente ──
            if has_tool_calls and has_final_answer:
                conflict_retries += 1
                logger.warning(
                    f"Seção {section.title} rodada {iteration+1}: "
                    f"LLM produziu chamada de ferramenta e Final Answer simultaneamente (conflito {conflict_retries})"
                )

                if conflict_retries <= 2:
                    # Primeiras duas vezes: descartar resposta e pedir ao LLM para responder novamente
                    messages.append({"role": "assistant", "content": response})
                    messages.append({
                        "role": "user",
                        "content": (
                            "[Erro de formato] Você incluiu chamada de ferramenta e Final Answer na mesma resposta, isso não é permitido.\n"
                            "Cada resposta só pode fazer uma destas duas coisas:\n"
                            "- Chamar uma ferramenta (produzir um bloco <tool_call>, não escrever Final Answer)\n"
                            "- Produzir conteúdo final (começar com 'Final Answer:', não incluir <tool_call>)\n"
                            "Por favor, responda novamente, fazendo apenas uma das duas."
                        ),
                    })
                    continue
                else:
                    # Terceira vez: tratamento degradado, truncar até a primeira chamada de ferramenta, executar forçadamente
                    logger.warning(
                        f"Seção {section.title}: {conflict_retries} conflitos consecutivos, "
                        "degradando para truncar e executar a primeira chamada de ferramenta"
                    )
                    first_tool_end = response.find('</tool_call>')
                    if first_tool_end != -1:
                        response = response[:first_tool_end + len('</tool_call>')]
                        tool_calls = self._parse_tool_calls(response)
                        has_tool_calls = bool(tool_calls)
                    has_final_answer = False
                    conflict_retries = 0

            # Registrar log de resposta LLM
            if self.report_logger:
                self.report_logger.log_llm_response(
                    section_title=section.title,
                    section_index=section_index,
                    response=response,
                    iteration=iteration + 1,
                    has_tool_calls=has_tool_calls,
                    has_final_answer=has_final_answer
                )

            # ── Situação 1: LLM produziu Final Answer ──
            if has_final_answer:
                # Número insuficiente de chamadas de ferramentas, recusar e pedir para continuar chamando ferramentas
                if tool_calls_count < min_tool_calls:
                    messages.append({"role": "assistant", "content": response})
                    unused_tools = all_tools - used_tools
                    unused_hint = f"(Estas ferramentas ainda não foram usadas, recomenda-se experimentá-las: {', '.join(unused_tools)})" if unused_tools else ""
                    messages.append({
                        "role": "user",
                        "content": REACT_INSUFFICIENT_TOOLS_MSG.format(
                            tool_calls_count=tool_calls_count,
                            min_tool_calls=min_tool_calls,
                            unused_hint=unused_hint,
                        ),
                    })
                    continue

                # Término normal
                final_answer = response.split("Final Answer:")[-1].strip()
                logger.info(f"Seção {section.title} gerada com sucesso (chamadas de ferramentas: {tool_calls_count})")

                if self.report_logger:
                    self.report_logger.log_section_content(
                        section_title=section.title,
                        section_index=section_index,
                        content=final_answer,
                        tool_calls_count=tool_calls_count
                    )
                return final_answer

            # ── Situação 2: LLM tentou chamar ferramenta ──
            if has_tool_calls:
                # Cota de ferramentas esgotada -> informar claramente e pedir Final Answer
                if tool_calls_count >= self.MAX_TOOL_CALLS_PER_SECTION:
                    messages.append({"role": "assistant", "content": response})
                    messages.append({
                        "role": "user",
                        "content": REACT_TOOL_LIMIT_MSG.format(
                            tool_calls_count=tool_calls_count,
                            max_tool_calls=self.MAX_TOOL_CALLS_PER_SECTION,
                        ),
                    })
                    continue

                # Executar apenas a primeira chamada de ferramenta
                call = tool_calls[0]
                if len(tool_calls) > 1:
                    logger.info(f"LLM tentou chamar {len(tool_calls)} ferramentas, executando apenas a primeira: {call['name']}")

                if self.report_logger:
                    self.report_logger.log_tool_call(
                        section_title=section.title,
                        section_index=section_index,
                        tool_name=call["name"],
                        parameters=call.get("parameters", {}),
                        iteration=iteration + 1
                    )

                result = self._execute_tool(
                    call["name"],
                    call.get("parameters", {}),
                    report_context=report_context
                )

                if self.report_logger:
                    self.report_logger.log_tool_result(
                        section_title=section.title,
                        section_index=section_index,
                        tool_name=call["name"],
                        result=result,
                        iteration=iteration + 1
                    )

                tool_calls_count += 1
                used_tools.add(call['name'])

                # Construir dica de ferramentas não utilizadas
                unused_tools = all_tools - used_tools
                unused_hint = ""
                if unused_tools and tool_calls_count < self.MAX_TOOL_CALLS_PER_SECTION:
                    unused_hint = REACT_UNUSED_TOOLS_HINT.format(unused_list=", ".join(unused_tools))

                messages.append({"role": "assistant", "content": response})
                messages.append({
                    "role": "user",
                    "content": REACT_OBSERVATION_TEMPLATE.format(
                        tool_name=call["name"],
                        result=result,
                        tool_calls_count=tool_calls_count,
                        max_tool_calls=self.MAX_TOOL_CALLS_PER_SECTION,
                        used_tools_str=", ".join(used_tools),
                        unused_hint=unused_hint,
                    ),
                })
                continue

            # ── Situação 3: Nem chamada de ferramenta, nem Final Answer ──
            messages.append({"role": "assistant", "content": response})

            if tool_calls_count < min_tool_calls:
                # Número insuficiente de chamadas, recomendar ferramentas não usadas
                unused_tools = all_tools - used_tools
                unused_hint = f"(Estas ferramentas ainda não foram usadas, recomenda-se experimentá-las: {', '.join(unused_tools)})" if unused_tools else ""

                messages.append({
                    "role": "user",
                    "content": REACT_INSUFFICIENT_TOOLS_MSG_ALT.format(
                        tool_calls_count=tool_calls_count,
                        min_tool_calls=min_tool_calls,
                        unused_hint=unused_hint,
                    ),
                })
                continue

            # Chamadas de ferramentas suficientes, LLM produziu conteúdo mas sem prefixo "Final Answer:"
            # Adotar diretamente esta saída como resposta final, sem iteração vazia
            logger.info(f"Seção {section.title}: prefixo 'Final Answer:' não detectado, adotando saída do LLM diretamente como conteúdo final (chamadas de ferramentas: {tool_calls_count})")
            final_answer = response.strip()

            if self.report_logger:
                self.report_logger.log_section_content(
                    section_title=section.title,
                    section_index=section_index,
                    content=final_answer,
                    tool_calls_count=tool_calls_count
                )
            return final_answer

        # Atingiu máximo de iterações, forçar geração de conteúdo
        logger.warning(f"Seção {section.title} atingiu máximo de iterações, forçando geração")
        messages.append({"role": "user", "content": REACT_FORCE_FINAL_MSG})

        response = self.llm.chat(
            messages=messages,
            temperature=0.5,
            max_tokens=4096
        )

        # Verificar se LLM retornou None na finalização forçada
        if response is None:
            logger.error(f"Seção {section.title}: LLM retornou None na finalização forçada, usando mensagem de erro padrão")
            final_answer = f"(Geração desta seção falhou: LLM retornou resposta vazia, tente novamente mais tarde)"
        elif "Final Answer:" in response:
            final_answer = response.split("Final Answer:")[-1].strip()
        else:
            final_answer = response

        # Registrar log de conclusão do conteúdo da seção
        if self.report_logger:
            self.report_logger.log_section_content(
                section_title=section.title,
                section_index=section_index,
                content=final_answer,
                tool_calls_count=tool_calls_count
            )

        return final_answer

    def generate_report(
        self,
        progress_callback: Optional[Callable[[str, int, str], None]] = None,
        report_id: Optional[str] = None
    ) -> Report:
        """
        Gerar relatório completo (saída em tempo real por seção)

        Cada seção é salva imediatamente ao ser gerada, sem esperar o relatório inteiro.
        Estrutura de arquivos:
        reports/{report_id}/
            meta.json       - Metainformações do relatório
            outline.json    - Sumário do relatório
            progress.json   - Progresso da geração
            section_01.md   - Seção 1
            section_02.md   - Seção 2
            ...
            full_report.md  - Relatório completo

        Args:
            progress_callback: Função de callback de progresso (stage, progress, message)
            report_id: ID do relatório (opcional, se não fornecido será gerado automaticamente)

        Returns:
            Report: Relatório completo
        """
        import uuid

        # Se report_id não foi fornecido, gerar automaticamente
        if not report_id:
            report_id = f"report_{uuid.uuid4().hex[:12]}"
        start_time = datetime.now()

        report = Report(
            report_id=report_id,
            simulation_id=self.simulation_id,
            graph_id=self.graph_id,
            simulation_requirement=self.simulation_requirement,
            status=ReportStatus.PENDING,
            created_at=datetime.now().isoformat()
        )

        # Lista de títulos de seções concluídas (para rastreamento de progresso)
        completed_section_titles = []

        try:
            # Inicializar: criar pasta do relatório e salvar estado inicial
            ReportManager._ensure_report_folder(report_id)

            # Inicializar registrador de logs (log estruturado agent_log.jsonl)
            self.report_logger = ReportLogger(report_id)
            self.report_logger.log_start(
                simulation_id=self.simulation_id,
                graph_id=self.graph_id,
                simulation_requirement=self.simulation_requirement
            )

            # Inicializar registrador de logs de console (console_log.txt)
            self.console_logger = ReportConsoleLogger(report_id)

            ReportManager.update_progress(
                report_id, "pending", 0, "Inicializando relatório...",
                completed_sections=[]
            )
            ReportManager.save_report(report)

            # Fase 1: Planejar sumário
            report.status = ReportStatus.PLANNING
            ReportManager.update_progress(
                report_id, "planning", 5, "Iniciando planejamento do sumário...",
                completed_sections=[]
            )

            # Registrar log de início do planejamento
            self.report_logger.log_planning_start()

            if progress_callback:
                progress_callback("planning", 0, "Iniciando planejamento do sumário...")

            outline = self.plan_outline(
                progress_callback=lambda stage, prog, msg:
                    progress_callback(stage, prog // 5, msg) if progress_callback else None
            )
            report.outline = outline

            # Registrar log de conclusão do planejamento
            self.report_logger.log_planning_complete(outline.to_dict())

            # Salvar sumário em arquivo
            ReportManager.save_outline(report_id, outline)
            ReportManager.update_progress(
                report_id, "planning", 15, f"Sumário concluído, {len(outline.sections)} seções",
                completed_sections=[]
            )
            ReportManager.save_report(report)

            logger.info(f"Sumário salvo em arquivo: {report_id}/outline.json")

            # Fase 2: Gerar seção por seção (salvando cada uma)
            report.status = ReportStatus.GENERATING

            total_sections = len(outline.sections)
            generated_sections = []  # Salvar conteúdo para contexto

            for i, section in enumerate(outline.sections):
                section_num = i + 1
                base_progress = 20 + int((i / total_sections) * 70)

                # Atualizar progresso
                ReportManager.update_progress(
                    report_id, "generating", base_progress,
                    f"Gerando seção: {section.title} ({section_num}/{total_sections})",
                    current_section=section.title,
                    completed_sections=completed_section_titles
                )

                if progress_callback:
                    progress_callback(
                        "generating",
                        base_progress,
                        f"Gerando seção: {section.title} ({section_num}/{total_sections})"
                    )

                # Gerar conteúdo da seção principal
                section_content = self._generate_section_react(
                    section=section,
                    outline=outline,
                    previous_sections=generated_sections,
                    progress_callback=lambda stage, prog, msg:
                        progress_callback(
                            stage,
                            base_progress + int(prog * 0.7 / total_sections),
                            msg
                        ) if progress_callback else None,
                    section_index=section_num
                )

                section.content = section_content
                generated_sections.append(f"## {section.title}\n\n{section_content}")

                # Salvar seção
                ReportManager.save_section(report_id, section_num, section)
                completed_section_titles.append(section.title)

                # Registrar log de conclusão da seção
                full_section_content = f"## {section.title}\n\n{section_content}"

                if self.report_logger:
                    self.report_logger.log_section_full_complete(
                        section_title=section.title,
                        section_index=section_num,
                        full_content=full_section_content.strip()
                    )

                logger.info(f"Seção salva: {report_id}/section_{section_num:02d}.md")

                # Atualizar progresso
                ReportManager.update_progress(
                    report_id, "generating",
                    base_progress + int(70 / total_sections),
                    f"Seção {section.title} concluída",
                    current_section=None,
                    completed_sections=completed_section_titles
                )

            # Fase 3: Montar relatório completo
            if progress_callback:
                progress_callback("generating", 95, "Montando relatório completo...")

            ReportManager.update_progress(
                report_id, "generating", 95, "Montando relatório completo...",
                completed_sections=completed_section_titles
            )

            # Usar ReportManager para montar relatório completo
            report.markdown_content = ReportManager.assemble_full_report(report_id, outline)
            report.status = ReportStatus.COMPLETED
            report.completed_at = datetime.now().isoformat()

            # Calcular tempo total
            total_time_seconds = (datetime.now() - start_time).total_seconds()

            # Registrar log de conclusão do relatório
            if self.report_logger:
                self.report_logger.log_report_complete(
                    total_sections=total_sections,
                    total_time_seconds=total_time_seconds
                )

            # Salvar relatório final
            ReportManager.save_report(report)
            ReportManager.update_progress(
                report_id, "completed", 100, "Geração do relatório concluída",
                completed_sections=completed_section_titles
            )

            if progress_callback:
                progress_callback("completed", 100, "Geração do relatório concluída")

            logger.info(f"Geração do relatório concluída: {report_id}")

            # Fechar registrador de logs de console
            if self.console_logger:
                self.console_logger.close()
                self.console_logger = None

            return report

        except Exception as e:
            logger.error(f"Falha na geração do relatório: {str(e)}")
            report.status = ReportStatus.FAILED
            report.error = str(e)

            # Registrar log de erro
            if self.report_logger:
                self.report_logger.log_error(str(e), "failed")

            # Salvar estado de falha
            try:
                ReportManager.save_report(report)
                ReportManager.update_progress(
                    report_id, "failed", -1, f"Falha na geração do relatório: {str(e)}",
                    completed_sections=completed_section_titles
                )
            except Exception:
                pass  # Ignorar erros ao salvar

            # Fechar registrador de logs de console
            if self.console_logger:
                self.console_logger.close()
                self.console_logger = None

            return report

    def chat(
        self,
        message: str,
        chat_history: List[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Conversar com o Report Agent

        Na conversa, o Agent pode chamar ferramentas de busca autonomamente para responder perguntas

        Args:
            message: Mensagem do usuário
            chat_history: Histórico de conversa

        Returns:
            {
                "response": "Resposta do Agent",
                "tool_calls": [lista de ferramentas chamadas],
                "sources": [fontes de informação]
            }
        """
        logger.info(f"Conversa com Report Agent: {message[:50]}...")

        chat_history = chat_history or []

        # Obter conteúdo do relatório já gerado
        report_content = ""
        try:
            report = ReportManager.get_report_by_simulation(self.simulation_id)
            if report and report.markdown_content:
                # Limitar comprimento do relatório para evitar contexto muito longo
                report_content = report.markdown_content[:15000]
                if len(report.markdown_content) > 15000:
                    report_content += "\n\n... [conteúdo do relatório truncado] ..."
        except Exception as e:
            logger.warning(f"Falha ao obter conteúdo do relatório: {e}")

        system_prompt = CHAT_SYSTEM_PROMPT_TEMPLATE.format(
            simulation_requirement=self.simulation_requirement,
            report_content=report_content if report_content else "(sem relatório no momento)",
            tools_description=self._get_tools_description(),
        )

        # Construir mensagens
        messages = [{"role": "system", "content": system_prompt}]

        # Adicionar histórico de conversa
        for h in chat_history[-10:]:  # Limitar comprimento do histórico
            messages.append(h)

        # Adicionar mensagem do usuário
        messages.append({
            "role": "user",
            "content": message
        })

        # Ciclo ReACT (versão simplificada)
        tool_calls_made = []
        max_iterations = 2  # Reduzir número de iterações

        for iteration in range(max_iterations):
            response = self.llm.chat(
                messages=messages,
                temperature=0.5
            )

            # Parsear chamadas de ferramentas
            tool_calls = self._parse_tool_calls(response)

            if not tool_calls:
                # Sem chamadas de ferramentas, retornar resposta diretamente
                clean_response = re.sub(r'<tool_call>.*?</tool_call>', '', response, flags=re.DOTALL)
                clean_response = re.sub(r'\[TOOL_CALL\].*?\)', '', clean_response)

                return {
                    "response": clean_response.strip(),
                    "tool_calls": tool_calls_made,
                    "sources": [tc.get("parameters", {}).get("query", "") for tc in tool_calls_made]
                }

            # Executar chamadas de ferramentas (limitar quantidade)
            tool_results = []
            for call in tool_calls[:1]:  # Máximo 1 chamada por iteração
                if len(tool_calls_made) >= self.MAX_TOOL_CALLS_PER_CHAT:
                    break
                result = self._execute_tool(call["name"], call.get("parameters", {}))
                tool_results.append({
                    "tool": call["name"],
                    "result": result[:1500]  # Limitar comprimento do resultado
                })
                tool_calls_made.append(call)

            # Adicionar resultados às mensagens
            messages.append({"role": "assistant", "content": response})
            observation = "\n".join([f"[resultado de {r['tool']}]\n{r['result']}" for r in tool_results])
            messages.append({
                "role": "user",
                "content": observation + CHAT_OBSERVATION_SUFFIX
            })

        # Atingiu máximo de iterações, obter resposta final
        final_response = self.llm.chat(
            messages=messages,
            temperature=0.5
        )

        # Limpar resposta
        clean_response = re.sub(r'<tool_call>.*?</tool_call>', '', final_response, flags=re.DOTALL)
        clean_response = re.sub(r'\[TOOL_CALL\].*?\)', '', clean_response)

        return {
            "response": clean_response.strip(),
            "tool_calls": tool_calls_made,
            "sources": [tc.get("parameters", {}).get("query", "") for tc in tool_calls_made]
        }


class ReportManager:
    """
    Gerenciador de relatórios

    Responsável pelo armazenamento persistente e busca de relatórios

    Estrutura de arquivos (saída por seção):
    reports/
      {report_id}/
        meta.json          - Metainformações e status do relatório
        outline.json       - Sumário do relatório
        progress.json      - Progresso da geração
        section_01.md      - Seção 1
        section_02.md      - Seção 2
        ...
        full_report.md     - Relatório completo
    """

    # Diretório de armazenamento dos relatórios
    REPORTS_DIR = os.path.join(Config.UPLOAD_FOLDER, 'reports')

    @classmethod
    def _ensure_reports_dir(cls):
        """Garantir que o diretório raiz dos relatórios existe"""
        os.makedirs(cls.REPORTS_DIR, exist_ok=True)

    @classmethod
    def _get_report_folder(cls, report_id: str) -> str:
        """Obter caminho da pasta do relatório"""
        return os.path.join(cls.REPORTS_DIR, report_id)

    @classmethod
    def _ensure_report_folder(cls, report_id: str) -> str:
        """Garantir que a pasta do relatório existe e retornar o caminho"""
        folder = cls._get_report_folder(report_id)
        os.makedirs(folder, exist_ok=True)
        return folder

    @classmethod
    def _get_report_path(cls, report_id: str) -> str:
        """Obter caminho do arquivo de metainformações do relatório"""
        return os.path.join(cls._get_report_folder(report_id), "meta.json")

    @classmethod
    def _get_report_markdown_path(cls, report_id: str) -> str:
        """Obter caminho do arquivo Markdown do relatório completo"""
        return os.path.join(cls._get_report_folder(report_id), "full_report.md")

    @classmethod
    def _get_outline_path(cls, report_id: str) -> str:
        """Obter caminho do arquivo de sumário"""
        return os.path.join(cls._get_report_folder(report_id), "outline.json")

    @classmethod
    def _get_progress_path(cls, report_id: str) -> str:
        """Obter caminho do arquivo de progresso"""
        return os.path.join(cls._get_report_folder(report_id), "progress.json")

    @classmethod
    def _get_section_path(cls, report_id: str, section_index: int) -> str:
        """Obter caminho do arquivo Markdown da seção"""
        return os.path.join(cls._get_report_folder(report_id), f"section_{section_index:02d}.md")

    @classmethod
    def _get_agent_log_path(cls, report_id: str) -> str:
        """Obter caminho do arquivo de log do Agent"""
        return os.path.join(cls._get_report_folder(report_id), "agent_log.jsonl")

    @classmethod
    def _get_console_log_path(cls, report_id: str) -> str:
        """Obter caminho do arquivo de log de console"""
        return os.path.join(cls._get_report_folder(report_id), "console_log.txt")

    @classmethod
    def get_console_log(cls, report_id: str, from_line: int = 0) -> Dict[str, Any]:
        """
        Obter conteúdo do log de console

        Este é o log de saída de console durante a geração do relatório (INFO, WARNING etc.),
        diferente do log estruturado agent_log.jsonl.

        Args:
            report_id: ID do relatório
            from_line: A partir de qual linha começar a ler (para obtenção incremental, 0 significa do início)

        Returns:
            {
                "logs": [lista de linhas de log],
                "total_lines": total de linhas,
                "from_line": número da linha inicial,
                "has_more": se há mais logs
            }
        """
        log_path = cls._get_console_log_path(report_id)

        if not os.path.exists(log_path):
            return {
                "logs": [],
                "total_lines": 0,
                "from_line": 0,
                "has_more": False
            }

        logs = []
        total_lines = 0

        with open(log_path, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f):
                total_lines = i + 1
                if i >= from_line:
                    # Manter linha de log original, remover quebra de linha final
                    logs.append(line.rstrip('\n\r'))

        return {
            "logs": logs,
            "total_lines": total_lines,
            "from_line": from_line,
            "has_more": False  # Já leu até o final
        }

    @classmethod
    def get_console_log_stream(cls, report_id: str) -> List[str]:
        """
        Obter log de console completo (obter tudo de uma vez)

        Args:
            report_id: ID do relatório

        Returns:
            Lista de linhas de log
        """
        result = cls.get_console_log(report_id, from_line=0)
        return result["logs"]

    @classmethod
    def get_agent_log(cls, report_id: str, from_line: int = 0) -> Dict[str, Any]:
        """
        Obter conteúdo do log do Agent

        Args:
            report_id: ID do relatório
            from_line: A partir de qual linha começar a ler (para obtenção incremental, 0 significa do início)

        Returns:
            {
                "logs": [lista de entradas de log],
                "total_lines": total de linhas,
                "from_line": número da linha inicial,
                "has_more": se há mais logs
            }
        """
        log_path = cls._get_agent_log_path(report_id)

        if not os.path.exists(log_path):
            return {
                "logs": [],
                "total_lines": 0,
                "from_line": 0,
                "has_more": False
            }

        logs = []
        total_lines = 0

        with open(log_path, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f):
                total_lines = i + 1
                if i >= from_line:
                    try:
                        log_entry = json.loads(line.strip())
                        logs.append(log_entry)
                    except json.JSONDecodeError:
                        # Pular linhas com falha no parse
                        continue

        return {
            "logs": logs,
            "total_lines": total_lines,
            "from_line": from_line,
            "has_more": False  # Já leu até o final
        }

    @classmethod
    def get_agent_log_stream(cls, report_id: str) -> List[Dict[str, Any]]:
        """
        Obter log completo do Agent (para obter tudo de uma vez)

        Args:
            report_id: ID do relatório

        Returns:
            Lista de entradas de log
        """
        result = cls.get_agent_log(report_id, from_line=0)
        return result["logs"]

    @classmethod
    def save_outline(cls, report_id: str, outline: ReportOutline) -> None:
        """
        Salvar sumário do relatório

        Chamado imediatamente após conclusão da fase de planejamento
        """
        cls._ensure_report_folder(report_id)

        with open(cls._get_outline_path(report_id), 'w', encoding='utf-8') as f:
            json.dump(outline.to_dict(), f, ensure_ascii=False, indent=2)

        logger.info(f"Sumário salvo: {report_id}")

    @classmethod
    def save_section(
        cls,
        report_id: str,
        section_index: int,
        section: ReportSection
    ) -> str:
        """
        Salvar seção individual

        Chamado imediatamente após geração de cada seção, implementando saída por seção

        Args:
            report_id: ID do relatório
            section_index: Índice da seção (começa em 1)
            section: Objeto da seção

        Returns:
            Caminho do arquivo salvo
        """
        cls._ensure_report_folder(report_id)

        # Construir conteúdo Markdown da seção - limpar possíveis títulos duplicados
        cleaned_content = cls._clean_section_content(section.content, section.title)
        md_content = f"## {section.title}\n\n"
        if cleaned_content:
            md_content += f"{cleaned_content}\n\n"

        # Salvar arquivo
        file_suffix = f"section_{section_index:02d}.md"
        file_path = os.path.join(cls._get_report_folder(report_id), file_suffix)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(md_content)

        logger.info(f"Seção salva: {report_id}/{file_suffix}")
        return file_path

    @classmethod
    def _clean_section_content(cls, content: str, section_title: str) -> str:
        """
        Limpar conteúdo da seção

        1. Remover linhas de título Markdown duplicadas no início do conteúdo com o título da seção
        2. Converter todos os títulos de nível ### e inferior para texto em negrito

        Args:
            content: Conteúdo original
            section_title: Título da seção

        Returns:
            Conteúdo limpo
        """
        import re

        if not content:
            return content

        content = content.strip()
        lines = content.split('\n')
        cleaned_lines = []
        skip_next_empty = False

        for i, line in enumerate(lines):
            stripped = line.strip()

            # Verificar se é uma linha de título Markdown
            heading_match = re.match(r'^(#{1,6})\s+(.+)$', stripped)

            if heading_match:
                level = len(heading_match.group(1))
                title_text = heading_match.group(2).strip()

                # Verificar se é título duplicado com o título da seção (dentro das primeiras 5 linhas)
                if i < 5:
                    if title_text == section_title or title_text.replace(' ', '') == section_title.replace(' ', ''):
                        skip_next_empty = True
                        continue

                # Converter títulos de todos os níveis (#, ##, ###, #### etc.) para negrito
                # Porque o título da seção é adicionado pelo sistema, o conteúdo não deve ter nenhum título
                cleaned_lines.append(f"**{title_text}**")
                cleaned_lines.append("")  # Adicionar linha em branco
                continue

            # Se a linha anterior foi um título ignorado e a atual é vazia, também ignorar
            if skip_next_empty and stripped == '':
                skip_next_empty = False
                continue

            skip_next_empty = False
            cleaned_lines.append(line)

        # Remover linhas em branco do início
        while cleaned_lines and cleaned_lines[0].strip() == '':
            cleaned_lines.pop(0)

        # Remover linhas separadoras do início
        while cleaned_lines and cleaned_lines[0].strip() in ['---', '***', '___']:
            cleaned_lines.pop(0)
            # Também remover linhas em branco após a linha separadora
            while cleaned_lines and cleaned_lines[0].strip() == '':
                cleaned_lines.pop(0)

        return '\n'.join(cleaned_lines)

    @classmethod
    def update_progress(
        cls,
        report_id: str,
        status: str,
        progress: int,
        message: str,
        current_section: str = None,
        completed_sections: List[str] = None
    ) -> None:
        """
        Atualizar progresso da geração do relatório

        O frontend pode obter o progresso em tempo real lendo progress.json
        """
        cls._ensure_report_folder(report_id)

        progress_data = {
            "status": status,
            "progress": progress,
            "message": message,
            "current_section": current_section,
            "completed_sections": completed_sections or [],
            "updated_at": datetime.now().isoformat()
        }

        with open(cls._get_progress_path(report_id), 'w', encoding='utf-8') as f:
            json.dump(progress_data, f, ensure_ascii=False, indent=2)

    @classmethod
    def get_progress(cls, report_id: str) -> Optional[Dict[str, Any]]:
        """Obter progresso da geração do relatório"""
        path = cls._get_progress_path(report_id)

        if not os.path.exists(path):
            return None

        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    @classmethod
    def get_generated_sections(cls, report_id: str) -> List[Dict[str, Any]]:
        """
        Obter lista de seções já geradas

        Retorna informações de todos os arquivos de seção salvos
        """
        folder = cls._get_report_folder(report_id)

        if not os.path.exists(folder):
            return []

        sections = []
        for filename in sorted(os.listdir(folder)):
            if filename.startswith('section_') and filename.endswith('.md'):
                file_path = os.path.join(folder, filename)
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                # Parsear índice da seção do nome do arquivo
                parts = filename.replace('.md', '').split('_')
                section_index = int(parts[1])

                sections.append({
                    "filename": filename,
                    "section_index": section_index,
                    "content": content
                })

        return sections

    @classmethod
    def assemble_full_report(cls, report_id: str, outline: ReportOutline) -> str:
        """
        Montar relatório completo

        Monta relatório completo a partir dos arquivos de seção salvos, com limpeza de títulos
        """
        folder = cls._get_report_folder(report_id)

        # Construir cabeçalho do relatório
        md_content = f"# {outline.title}\n\n"
        md_content += f"> {outline.summary}\n\n"
        md_content += f"---\n\n"

        # Ler todos os arquivos de seção em ordem
        sections = cls.get_generated_sections(report_id)
        for section_info in sections:
            md_content += section_info["content"]

        # Pós-processamento: limpar problemas de títulos no relatório inteiro
        md_content = cls._post_process_report(md_content, outline)

        # Salvar relatório completo
        full_path = cls._get_report_markdown_path(report_id)
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(md_content)

        logger.info(f"Relatório completo montado: {report_id}")
        return md_content

    @classmethod
    def _post_process_report(cls, content: str, outline: ReportOutline) -> str:
        """
        Pós-processar conteúdo do relatório

        1. Remover títulos duplicados
        2. Manter título principal do relatório (#) e títulos de seção (##), remover outros níveis (###, #### etc.)
        3. Limpar linhas em branco e separadores excessivos

        Args:
            content: Conteúdo original do relatório
            outline: Sumário do relatório

        Returns:
            Conteúdo processado
        """
        import re

        lines = content.split('\n')
        processed_lines = []
        prev_was_heading = False

        # Coletar todos os títulos de seção do sumário
        section_titles = set()
        for section in outline.sections:
            section_titles.add(section.title)

        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            # Verificar se é linha de título
            heading_match = re.match(r'^(#{1,6})\s+(.+)$', stripped)

            if heading_match:
                level = len(heading_match.group(1))
                title = heading_match.group(2).strip()

                # Verificar se é título duplicado (mesmo conteúdo nas últimas 5 linhas)
                is_duplicate = False
                for j in range(max(0, len(processed_lines) - 5), len(processed_lines)):
                    prev_line = processed_lines[j].strip()
                    prev_match = re.match(r'^(#{1,6})\s+(.+)$', prev_line)
                    if prev_match:
                        prev_title = prev_match.group(2).strip()
                        if prev_title == title:
                            is_duplicate = True
                            break

                if is_duplicate:
                    # Pular título duplicado e linhas em branco após ele
                    i += 1
                    while i < len(lines) and lines[i].strip() == '':
                        i += 1
                    continue

                # Tratamento de hierarquia de títulos:
                # - # (level=1) manter apenas título principal do relatório
                # - ## (level=2) manter títulos de seção
                # - ### e inferior (level>=3) converter para texto em negrito

                if level == 1:
                    if title == outline.title:
                        # Manter título principal do relatório
                        processed_lines.append(line)
                        prev_was_heading = True
                    elif title in section_titles:
                        # Título de seção usando # erroneamente, corrigir para ##
                        processed_lines.append(f"## {title}")
                        prev_was_heading = True
                    else:
                        # Outros títulos de nível 1 converter para negrito
                        processed_lines.append(f"**{title}**")
                        processed_lines.append("")
                        prev_was_heading = False
                elif level == 2:
                    if title in section_titles or title == outline.title:
                        # Manter título de seção
                        processed_lines.append(line)
                        prev_was_heading = True
                    else:
                        # Títulos de nível 2 que não são de seção converter para negrito
                        processed_lines.append(f"**{title}**")
                        processed_lines.append("")
                        prev_was_heading = False
                else:
                    # Títulos de nível ### e inferior converter para texto em negrito
                    processed_lines.append(f"**{title}**")
                    processed_lines.append("")
                    prev_was_heading = False

                i += 1
                continue

            elif stripped == '---' and prev_was_heading:
                # Pular separador imediatamente após título
                i += 1
                continue

            elif stripped == '' and prev_was_heading:
                # Manter apenas uma linha em branco após título
                if processed_lines and processed_lines[-1].strip() != '':
                    processed_lines.append(line)
                prev_was_heading = False

            else:
                processed_lines.append(line)
                prev_was_heading = False

            i += 1

        # Limpar múltiplas linhas em branco consecutivas (manter no máximo 2)
        result_lines = []
        empty_count = 0
        for line in processed_lines:
            if line.strip() == '':
                empty_count += 1
                if empty_count <= 2:
                    result_lines.append(line)
            else:
                empty_count = 0
                result_lines.append(line)

        return '\n'.join(result_lines)

    @classmethod
    def save_report(cls, report: Report) -> None:
        """Salvar metainformações e relatório completo"""
        cls._ensure_report_folder(report.report_id)

        # Salvar JSON de metainformações
        with open(cls._get_report_path(report.report_id), 'w', encoding='utf-8') as f:
            json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)

        # Salvar sumário
        if report.outline:
            cls.save_outline(report.report_id, report.outline)

        # Salvar relatório Markdown completo
        if report.markdown_content:
            with open(cls._get_report_markdown_path(report.report_id), 'w', encoding='utf-8') as f:
                f.write(report.markdown_content)

        logger.info(f"Relatório salvo: {report.report_id}")

    @classmethod
    def get_report(cls, report_id: str) -> Optional[Report]:
        """Obter relatório"""
        path = cls._get_report_path(report_id)

        if not os.path.exists(path):
            # Compatibilidade com formato antigo: verificar arquivo armazenado diretamente no diretório reports
            old_path = os.path.join(cls.REPORTS_DIR, f"{report_id}.json")
            if os.path.exists(old_path):
                path = old_path
            else:
                return None

        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Reconstruir objeto Report
        outline = None
        if data.get('outline'):
            outline_data = data['outline']
            sections = []
            for s in outline_data.get('sections', []):
                sections.append(ReportSection(
                    title=s['title'],
                    content=s.get('content', '')
                ))
            outline = ReportOutline(
                title=outline_data['title'],
                summary=outline_data['summary'],
                sections=sections
            )

        # Se markdown_content estiver vazio, tentar ler de full_report.md
        markdown_content = data.get('markdown_content', '')
        if not markdown_content:
            full_report_path = cls._get_report_markdown_path(report_id)
            if os.path.exists(full_report_path):
                with open(full_report_path, 'r', encoding='utf-8') as f:
                    markdown_content = f.read()

        return Report(
            report_id=data['report_id'],
            simulation_id=data['simulation_id'],
            graph_id=data['graph_id'],
            simulation_requirement=data['simulation_requirement'],
            status=ReportStatus(data['status']),
            outline=outline,
            markdown_content=markdown_content,
            created_at=data.get('created_at', ''),
            completed_at=data.get('completed_at', ''),
            error=data.get('error')
        )

    @classmethod
    def get_report_by_simulation(cls, simulation_id: str) -> Optional[Report]:
        """Obter relatório por ID da simulação"""
        cls._ensure_reports_dir()

        for item in os.listdir(cls.REPORTS_DIR):
            item_path = os.path.join(cls.REPORTS_DIR, item)
            # Formato novo: pasta
            if os.path.isdir(item_path):
                report = cls.get_report(item)
                if report and report.simulation_id == simulation_id:
                    return report
            # Compatibilidade com formato antigo: arquivo JSON
            elif item.endswith('.json'):
                report_id = item[:-5]
                report = cls.get_report(report_id)
                if report and report.simulation_id == simulation_id:
                    return report

        return None

    @classmethod
    def list_reports(cls, simulation_id: Optional[str] = None, limit: int = 50) -> List[Report]:
        """Listar relatórios"""
        cls._ensure_reports_dir()

        reports = []
        for item in os.listdir(cls.REPORTS_DIR):
            item_path = os.path.join(cls.REPORTS_DIR, item)
            # Formato novo: pasta
            if os.path.isdir(item_path):
                report = cls.get_report(item)
                if report:
                    if simulation_id is None or report.simulation_id == simulation_id:
                        reports.append(report)
            # Compatibilidade com formato antigo: arquivo JSON
            elif item.endswith('.json'):
                report_id = item[:-5]
                report = cls.get_report(report_id)
                if report:
                    if simulation_id is None or report.simulation_id == simulation_id:
                        reports.append(report)

        # Ordenar por data de criação em ordem decrescente
        reports.sort(key=lambda r: r.created_at, reverse=True)

        return reports[:limit]

    @classmethod
    def delete_report(cls, report_id: str) -> bool:
        """Excluir relatório (pasta inteira)"""
        import shutil

        folder_path = cls._get_report_folder(report_id)

        # Formato novo: excluir pasta inteira
        if os.path.exists(folder_path) and os.path.isdir(folder_path):
            shutil.rmtree(folder_path)
            logger.info(f"Pasta do relatório excluída: {report_id}")
            return True

        # Compatibilidade com formato antigo: excluir arquivos individuais
        deleted = False
        old_json_path = os.path.join(cls.REPORTS_DIR, f"{report_id}.json")
        old_md_path = os.path.join(cls.REPORTS_DIR, f"{report_id}.md")

        if os.path.exists(old_json_path):
            os.remove(old_json_path)
            deleted = True
        if os.path.exists(old_md_path):
            os.remove(old_md_path)
            deleted = True

        return deleted
