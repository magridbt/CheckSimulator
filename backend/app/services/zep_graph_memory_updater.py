"""
Serviço de atualização de memória do grafo Zep
Atualiza dinamicamente as atividades dos Agents da simulação no grafo Zep
"""

import os
import time
import threading
import json
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass
from datetime import datetime
from queue import Queue, Empty

from zep_cloud.client import Zep

from ..config import Config
from ..utils.logger import get_logger

logger = get_logger('checksimulator.zep_graph_memory_updater')


@dataclass
class AgentActivity:
    """Registro de atividade do Agent"""
    platform: str           # twitter / reddit
    agent_id: int
    agent_name: str
    action_type: str        # CREATE_POST, LIKE_POST, etc.
    action_args: Dict[str, Any]
    round_num: int
    timestamp: str

    def to_episode_text(self) -> str:
        """
        Converte a atividade em descrição textual para enviar ao Zep

        Usa formato de linguagem natural para que o Zep possa extrair entidades e relações
        Não adiciona prefixo de simulação para evitar induzir erro na atualização do grafo
        """
        # Gera descrições diferentes conforme o tipo de ação
        action_descriptions = {
            "CREATE_POST": self._describe_create_post,
            "LIKE_POST": self._describe_like_post,
            "DISLIKE_POST": self._describe_dislike_post,
            "REPOST": self._describe_repost,
            "QUOTE_POST": self._describe_quote_post,
            "FOLLOW": self._describe_follow,
            "CREATE_COMMENT": self._describe_create_comment,
            "LIKE_COMMENT": self._describe_like_comment,
            "DISLIKE_COMMENT": self._describe_dislike_comment,
            "SEARCH_POSTS": self._describe_search,
            "SEARCH_USER": self._describe_search_user,
            "MUTE": self._describe_mute,
        }

        describe_func = action_descriptions.get(self.action_type, self._describe_generic)
        description = describe_func()

        # Retorna diretamente no formato "nome do agent: descrição da atividade", sem prefixo de simulação
        return f"{self.agent_name}: {description}"

    def _describe_create_post(self) -> str:
        content = self.action_args.get("content", "")
        if content:
            return f"publicou um post: '{content}'"
        return "publicou um post"

    def _describe_like_post(self) -> str:
        """Curtir post - inclui conteúdo original e informações do autor"""
        post_content = self.action_args.get("post_content", "")
        post_author = self.action_args.get("post_author_name", "")

        if post_content and post_author:
            return f"curtiu o post de {post_author}: '{post_content}'"
        elif post_content:
            return f"curtiu um post: '{post_content}'"
        elif post_author:
            return f"curtiu um post de {post_author}"
        return "curtiu um post"

    def _describe_dislike_post(self) -> str:
        """Descurtir post - inclui conteúdo original e informações do autor"""
        post_content = self.action_args.get("post_content", "")
        post_author = self.action_args.get("post_author_name", "")

        if post_content and post_author:
            return f"descurtiu o post de {post_author}: '{post_content}'"
        elif post_content:
            return f"descurtiu um post: '{post_content}'"
        elif post_author:
            return f"descurtiu um post de {post_author}"
        return "descurtiu um post"

    def _describe_repost(self) -> str:
        """Repostar - inclui conteúdo original e informações do autor"""
        original_content = self.action_args.get("original_content", "")
        original_author = self.action_args.get("original_author_name", "")

        if original_content and original_author:
            return f"repostou o post de {original_author}: '{original_content}'"
        elif original_content:
            return f"repostou um post: '{original_content}'"
        elif original_author:
            return f"repostou um post de {original_author}"
        return "repostou um post"

    def _describe_quote_post(self) -> str:
        """Citar post - inclui conteúdo original, informações do autor e comentário da citação"""
        original_content = self.action_args.get("original_content", "")
        original_author = self.action_args.get("original_author_name", "")
        quote_content = self.action_args.get("quote_content", "") or self.action_args.get("content", "")

        base = ""
        if original_content and original_author:
            base = f"citou o post de {original_author} '{original_content}'"
        elif original_content:
            base = f"citou um post '{original_content}'"
        elif original_author:
            base = f"citou um post de {original_author}"
        else:
            base = "citou um post"

        if quote_content:
            base += f", e comentou: '{quote_content}'"
        return base

    def _describe_follow(self) -> str:
        """Seguir usuário - inclui nome do usuário seguido"""
        target_user_name = self.action_args.get("target_user_name", "")

        if target_user_name:
            return f"seguiu o usuário '{target_user_name}'"
        return "seguiu um usuário"

    def _describe_create_comment(self) -> str:
        """Publicar comentário - inclui conteúdo do comentário e informações do post comentado"""
        content = self.action_args.get("content", "")
        post_content = self.action_args.get("post_content", "")
        post_author = self.action_args.get("post_author_name", "")

        if content:
            if post_content and post_author:
                return f"comentou no post de {post_author} '{post_content}': '{content}'"
            elif post_content:
                return f"comentou no post '{post_content}': '{content}'"
            elif post_author:
                return f"comentou no post de {post_author}: '{content}'"
            return f"comentou: '{content}'"
        return "publicou um comentário"

    def _describe_like_comment(self) -> str:
        """Curtir comentário - inclui conteúdo do comentário e informações do autor"""
        comment_content = self.action_args.get("comment_content", "")
        comment_author = self.action_args.get("comment_author_name", "")

        if comment_content and comment_author:
            return f"curtiu o comentário de {comment_author}: '{comment_content}'"
        elif comment_content:
            return f"curtiu um comentário: '{comment_content}'"
        elif comment_author:
            return f"curtiu um comentário de {comment_author}"
        return "curtiu um comentário"

    def _describe_dislike_comment(self) -> str:
        """Descurtir comentário - inclui conteúdo do comentário e informações do autor"""
        comment_content = self.action_args.get("comment_content", "")
        comment_author = self.action_args.get("comment_author_name", "")

        if comment_content and comment_author:
            return f"descurtiu o comentário de {comment_author}: '{comment_content}'"
        elif comment_content:
            return f"descurtiu um comentário: '{comment_content}'"
        elif comment_author:
            return f"descurtiu um comentário de {comment_author}"
        return "descurtiu um comentário"

    def _describe_search(self) -> str:
        """Pesquisar posts - inclui termos de busca"""
        query = self.action_args.get("query", "") or self.action_args.get("keyword", "")
        return f"pesquisou '{query}'" if query else "realizou uma pesquisa"

    def _describe_search_user(self) -> str:
        """Pesquisar usuário - inclui termos de busca"""
        query = self.action_args.get("query", "") or self.action_args.get("username", "")
        return f"pesquisou o usuário '{query}'" if query else "pesquisou um usuário"

    def _describe_mute(self) -> str:
        """Silenciar usuário - inclui nome do usuário silenciado"""
        target_user_name = self.action_args.get("target_user_name", "")

        if target_user_name:
            return f"silenciou o usuário '{target_user_name}'"
        return "silenciou um usuário"

    def _describe_generic(self) -> str:
        # Para tipos de ação desconhecidos, gera descrição genérica
        return f"executou a operação {self.action_type}"


class ZepGraphMemoryUpdater:
    """
    Atualizador de memória do grafo Zep

    Monitora o arquivo de log de actions da simulação e atualiza as atividades dos agents
    em tempo real no grafo Zep.
    Agrupa por plataforma e envia em lote ao Zep após acumular BATCH_SIZE atividades.

    Todos os comportamentos significativos são atualizados no Zep, action_args contém
    informações de contexto completas:
    - Conteúdo original do post curtido/descurtido
    - Conteúdo original do post repostado/citado
    - Nome do usuário seguido/silenciado
    - Conteúdo original do comentário curtido/descurtido
    """

    # Tamanho do lote (quantas atividades acumular por plataforma antes de enviar)
    BATCH_SIZE = 5

    # Mapeamento de nomes de exibição das plataformas (para exibição no console)
    PLATFORM_DISPLAY_NAMES = {
        'twitter': 'Mundo 1',
        'reddit': 'Mundo 2',
    }

    # Intervalo de envio (segundos), para evitar requisições muito rápidas
    SEND_INTERVAL = 0.5

    # Configuração de retentativas
    MAX_RETRIES = 3
    RETRY_DELAY = 2  # segundos

    def __init__(self, graph_id: str, api_key: Optional[str] = None):
        """
        Inicializa o atualizador

        Args:
            graph_id: ID do grafo Zep
            api_key: Zep API Key (opcional, padrão lido da configuração)
        """
        self.graph_id = graph_id
        self.api_key = api_key or Config.ZEP_API_KEY

        if not self.api_key:
            raise ValueError("ZEP_API_KEY não configurada")

        self.client = Zep(api_key=self.api_key)

        # Fila de atividades
        self._activity_queue: Queue = Queue()

        # Buffer de atividades agrupado por plataforma (cada plataforma acumula até BATCH_SIZE antes do envio em lote)
        self._platform_buffers: Dict[str, List[AgentActivity]] = {
            'twitter': [],
            'reddit': [],
        }
        self._buffer_lock = threading.Lock()

        # Flags de controle
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None

        # Estatísticas
        self._total_activities = 0  # Total de atividades adicionadas à fila
        self._total_sent = 0        # Total de lotes enviados com sucesso ao Zep
        self._total_items_sent = 0  # Total de atividades enviadas com sucesso ao Zep
        self._failed_count = 0      # Total de lotes com falha no envio
        self._skipped_count = 0     # Total de atividades ignoradas por filtro (DO_NOTHING)

        logger.info(f"ZepGraphMemoryUpdater inicializado: graph_id={graph_id}, batch_size={self.BATCH_SIZE}")

    def _get_platform_display_name(self, platform: str) -> str:
        """Obtém o nome de exibição da plataforma"""
        return self.PLATFORM_DISPLAY_NAMES.get(platform.lower(), platform)

    def start(self):
        """Inicia a thread de trabalho em segundo plano"""
        if self._running:
            return

        self._running = True
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name=f"ZepMemoryUpdater-{self.graph_id[:8]}"
        )
        self._worker_thread.start()
        logger.info(f"ZepGraphMemoryUpdater iniciado: graph_id={self.graph_id}")

    def stop(self):
        """Para a thread de trabalho em segundo plano"""
        self._running = False

        # Envia as atividades restantes
        self._flush_remaining()

        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=10)

        logger.info(f"ZepGraphMemoryUpdater parado: graph_id={self.graph_id}, "
                   f"total_activities={self._total_activities}, "
                   f"batches_sent={self._total_sent}, "
                   f"items_sent={self._total_items_sent}, "
                   f"failed={self._failed_count}, "
                   f"skipped={self._skipped_count}")

    def add_activity(self, activity: AgentActivity):
        """
        Adiciona uma atividade de agent à fila

        Todos os comportamentos significativos são adicionados à fila, incluindo:
        - CREATE_POST (publicar post)
        - CREATE_COMMENT (comentar)
        - QUOTE_POST (citar post)
        - SEARCH_POSTS (pesquisar posts)
        - SEARCH_USER (pesquisar usuário)
        - LIKE_POST/DISLIKE_POST (curtir/descurtir post)
        - REPOST (repostar)
        - FOLLOW (seguir)
        - MUTE (silenciar)
        - LIKE_COMMENT/DISLIKE_COMMENT (curtir/descurtir comentário)

        action_args contém informações de contexto completas (como conteúdo original do post, nome do usuário, etc.).

        Args:
            activity: Registro de atividade do Agent
        """
        # Ignora atividades do tipo DO_NOTHING
        if activity.action_type == "DO_NOTHING":
            self._skipped_count += 1
            return

        self._activity_queue.put(activity)
        self._total_activities += 1
        logger.debug(f"Atividade adicionada à fila Zep: {activity.agent_name} - {activity.action_type}")

    def add_activity_from_dict(self, data: Dict[str, Any], platform: str):
        """
        Adiciona atividade a partir de dados em dicionário

        Args:
            data: Dados do dicionário parseados do actions.jsonl
            platform: Nome da plataforma (twitter/reddit)
        """
        # Ignora entradas do tipo evento
        if "event_type" in data:
            return

        activity = AgentActivity(
            platform=platform,
            agent_id=data.get("agent_id", 0),
            agent_name=data.get("agent_name", ""),
            action_type=data.get("action_type", ""),
            action_args=data.get("action_args", {}),
            round_num=data.get("round", 0),
            timestamp=data.get("timestamp", datetime.now().isoformat()),
        )

        self.add_activity(activity)

    def _worker_loop(self):
        """Loop de trabalho em segundo plano - envia atividades em lote ao Zep por plataforma"""
        while self._running or not self._activity_queue.empty():
            try:
                # Tenta obter atividade da fila (timeout de 1 segundo)
                try:
                    activity = self._activity_queue.get(timeout=1)

                    # Adiciona a atividade ao buffer da plataforma correspondente
                    platform = activity.platform.lower()
                    with self._buffer_lock:
                        if platform not in self._platform_buffers:
                            self._platform_buffers[platform] = []
                        self._platform_buffers[platform].append(activity)

                        # Verifica se a plataforma atingiu o tamanho do lote
                        if len(self._platform_buffers[platform]) >= self.BATCH_SIZE:
                            batch = self._platform_buffers[platform][:self.BATCH_SIZE]
                            self._platform_buffers[platform] = self._platform_buffers[platform][self.BATCH_SIZE:]
                            # Libera o lock antes de enviar
                            self._send_batch_activities(batch, platform)
                            # Intervalo de envio, para evitar requisições muito rápidas
                            time.sleep(self.SEND_INTERVAL)

                except Empty:
                    pass

            except Exception as e:
                logger.error(f"Exceção no loop de trabalho: {e}")
                time.sleep(1)

    def _send_batch_activities(self, activities: List[AgentActivity], platform: str):
        """
        Envia atividades em lote ao grafo Zep (combinadas em um único texto)

        Args:
            activities: Lista de atividades do Agent
            platform: Nome da plataforma
        """
        if not activities:
            return

        # Combina múltiplas atividades em um único texto, separadas por quebra de linha
        episode_texts = [activity.to_episode_text() for activity in activities]
        combined_text = "\n".join(episode_texts)

        # Envio com retentativas
        for attempt in range(self.MAX_RETRIES):
            try:
                self.client.graph.add(
                    graph_id=self.graph_id,
                    type="text",
                    data=combined_text
                )

                self._total_sent += 1
                self._total_items_sent += len(activities)
                display_name = self._get_platform_display_name(platform)
                logger.info(f"Lote de {len(activities)} atividades do {display_name} enviado com sucesso ao grafo {self.graph_id}")
                logger.debug(f"Preview do lote: {combined_text[:200]}...")
                return

            except Exception as e:
                if attempt < self.MAX_RETRIES - 1:
                    logger.warning(f"Falha ao enviar lote ao Zep (tentativa {attempt + 1}/{self.MAX_RETRIES}): {e}")
                    time.sleep(self.RETRY_DELAY * (attempt + 1))
                else:
                    logger.error(f"Falha ao enviar lote ao Zep após {self.MAX_RETRIES} retentativas: {e}")
                    self._failed_count += 1

    def _flush_remaining(self):
        """Envia as atividades restantes na fila e no buffer"""
        # Primeiro processa as atividades restantes na fila, adicionando ao buffer
        while not self._activity_queue.empty():
            try:
                activity = self._activity_queue.get_nowait()
                platform = activity.platform.lower()
                with self._buffer_lock:
                    if platform not in self._platform_buffers:
                        self._platform_buffers[platform] = []
                    self._platform_buffers[platform].append(activity)
            except Empty:
                break

        # Depois envia as atividades restantes no buffer de cada plataforma (mesmo que não atinja BATCH_SIZE)
        with self._buffer_lock:
            for platform, buffer in self._platform_buffers.items():
                if buffer:
                    display_name = self._get_platform_display_name(platform)
                    logger.info(f"Enviando {len(buffer)} atividades restantes da plataforma {display_name}")
                    self._send_batch_activities(buffer, platform)
            # Limpa todos os buffers
            for platform in self._platform_buffers:
                self._platform_buffers[platform] = []

    def get_stats(self) -> Dict[str, Any]:
        """Obtém informações estatísticas"""
        with self._buffer_lock:
            buffer_sizes = {p: len(b) for p, b in self._platform_buffers.items()}

        return {
            "graph_id": self.graph_id,
            "batch_size": self.BATCH_SIZE,
            "total_activities": self._total_activities,  # Total de atividades adicionadas à fila
            "batches_sent": self._total_sent,            # Total de lotes enviados com sucesso
            "items_sent": self._total_items_sent,        # Total de atividades enviadas com sucesso
            "failed_count": self._failed_count,          # Total de lotes com falha no envio
            "skipped_count": self._skipped_count,        # Total de atividades ignoradas por filtro (DO_NOTHING)
            "queue_size": self._activity_queue.qsize(),
            "buffer_sizes": buffer_sizes,                # Tamanho do buffer de cada plataforma
            "running": self._running,
        }


class ZepGraphMemoryManager:
    """
    Gerenciador de atualizadores de memória do grafo Zep para múltiplas simulações

    Cada simulação pode ter sua própria instância de atualizador
    """

    _updaters: Dict[str, ZepGraphMemoryUpdater] = {}
    _lock = threading.Lock()

    @classmethod
    def create_updater(cls, simulation_id: str, graph_id: str) -> ZepGraphMemoryUpdater:
        """
        Cria um atualizador de memória do grafo para a simulação

        Args:
            simulation_id: ID da simulação
            graph_id: ID do grafo Zep

        Returns:
            Instância de ZepGraphMemoryUpdater
        """
        with cls._lock:
            # Se já existe, para o antigo primeiro
            if simulation_id in cls._updaters:
                cls._updaters[simulation_id].stop()

            updater = ZepGraphMemoryUpdater(graph_id)
            updater.start()
            cls._updaters[simulation_id] = updater

            logger.info(f"Atualizador de memória do grafo criado: simulation_id={simulation_id}, graph_id={graph_id}")
            return updater

    @classmethod
    def get_updater(cls, simulation_id: str) -> Optional[ZepGraphMemoryUpdater]:
        """Obtém o atualizador da simulação"""
        return cls._updaters.get(simulation_id)

    @classmethod
    def stop_updater(cls, simulation_id: str):
        """Para e remove o atualizador da simulação"""
        with cls._lock:
            if simulation_id in cls._updaters:
                cls._updaters[simulation_id].stop()
                del cls._updaters[simulation_id]
                logger.info(f"Atualizador de memória do grafo parado: simulation_id={simulation_id}")

    # Flag para evitar chamada duplicada de stop_all
    _stop_all_done = False

    @classmethod
    def stop_all(cls):
        """Para todos os atualizadores"""
        # Evita chamada duplicada
        if cls._stop_all_done:
            return
        cls._stop_all_done = True

        with cls._lock:
            if cls._updaters:
                for simulation_id, updater in list(cls._updaters.items()):
                    try:
                        updater.stop()
                    except Exception as e:
                        logger.error(f"Falha ao parar atualizador: simulation_id={simulation_id}, error={e}")
                cls._updaters.clear()
            logger.info("Todos os atualizadores de memória do grafo foram parados")

    @classmethod
    def get_all_stats(cls) -> Dict[str, Dict[str, Any]]:
        """Obtém informações estatísticas de todos os atualizadores"""
        return {
            sim_id: updater.get_stats()
            for sim_id, updater in cls._updaters.items()
        }
